import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config as config_module
from backup import Backup
from cache import Cache
from config import Config
from database import Database
from eventbus import EventBus
from exceptions import TransientError
from menu import Menu
from sdcard import SdCard
from display import BackupStatusView
from rclone_uploader import Rclone, RcloneError
from uploader import create_uploader
from webdav_uploader import WebDav


class RuntimeConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.config_file = Path(self.tmpdir.name) / "config.json"
        self.config_file.write_text(json.dumps({"mode": "upload", "file_filter": "all", "prune_min_days": 30}))
        self.original_config_file = config_module.CONFIG_FILE
        config_module.CONFIG_FILE = self.config_file
        self.bus = EventBus()

    def tearDown(self):
        config_module.CONFIG_FILE = self.original_config_file
        self.tmpdir.cleanup()

    def test_menu_change_updates_config_and_file(self):
        cfg = Config(bus=self.bus)
        menu = Menu(config=cfg, bus=self.bus)

        menu.down()
        menu.enter()
        menu.down()
        menu.enter()

        self.assertEqual(cfg.mode, "mirror")
        self.assertEqual(json.loads(self.config_file.read_text())["mode"], "mirror")

    def test_keep_forever_can_be_selected(self):
        cfg = Config(bus=self.bus)
        menu = Menu(config=cfg, bus=self.bus)

        menu.down()
        menu.down()
        menu.enter()
        for _ in range(3):
            menu.down()
        menu.enter()

        self.assertIsNone(cfg.prune_min_days)

    def test_backup_mode_changes_on_next_start_only(self):
        class FakeCache:
            def __init__(self):
                self.prepared = 0

            def prepare_backup(self):
                self.prepared += 1

        cache = FakeCache()
        backup = Backup(cache, None, None, bus=self.bus, mode="upload")

        self.bus.emit("config:set", key="mode", value="mirror")

        self.assertEqual(backup._mode, "upload")
        self.assertEqual(backup._next_mode, "mirror")

    def test_cache_settings_are_snapshotted(self):
        class FakeConfig:
            file_filter = "all"
            prune_min_days = 30

        cache_dir = Path(self.tmpdir.name) / "cache"
        source_dir = Path(self.tmpdir.name) / "source"
        cache_dir.mkdir()
        source_dir.mkdir()
        cfg = FakeConfig()
        cfg.sd_src = source_dir
        cfg.cache_path = cache_dir
        cache = Cache(cfg, db=None)

        cfg.file_filter = "jpg"
        cfg.prune_min_days = None
        cache.prepare_backup()
        cfg.file_filter = "all"
        cfg.prune_min_days = 30

        self.assertEqual(cache._file_filter, "jpg")
        self.assertIsNone(cache._prune_min_days)

    def test_mirror_tracks_filtered_files_as_present(self):
        class FakeDatabase:
            def find_by_sd_path(self, path):
                return None

            def create(self, *args):
                return object()

        class FakeConfig:
            file_filter = "jpg"
            prune_min_days = 30

        cache_dir = Path(self.tmpdir.name) / "cache"
        source_dir = Path(self.tmpdir.name) / "source"
        cache_dir.mkdir()
        source_dir.mkdir()
        photo = source_dir / "photo.jpg"
        document = source_dir / "notes.txt"
        photo.write_bytes(b"photo")
        document.write_bytes(b"notes")
        cfg = FakeConfig()
        cfg.sd_src = source_dir
        cfg.cache_path = cache_dir
        cache = Cache(cfg, FakeDatabase())

        cache.copy()

        self.assertEqual(cache.last_seen_paths, {str(photo), str(document)})

    def test_new_cloud_destination_has_one_timestamp(self):
        self.assertEqual(
            Backup._new_cloud_destination("backup_1720000000_1720003600", 1720007200),
            "backup_1720007200",
        )

    def test_failed_uploads_remain_pending(self):
        db = Database(Path(self.tmpdir.name) / "files.db")
        record = db.create("hash", "/sd/photo.jpg", "/cache/photo.jpg", 1, 0)
        db.mark_upload_error(record.id, "temporary error")

        pending = db.find_pending_uploads()

        self.assertEqual([item.id for item in pending], [record.id])
        self.assertEqual(db.count_pending_uploads(), 1)

    def test_webdav_creates_missing_parent_directories(self):
        class FakeClient:
            def __init__(self):
                self.directories = set()
                self.created = []

            def check(self, path):
                return path in self.directories

            def execute_request(self, action, path):
                if action != "mkdir":
                    raise AssertionError(f"Unexpected WebDAV action: {action}")
                self.directories.add(path)
                self.created.append(path)

        uploader = object.__new__(WebDav)
        uploader.client = FakeClient()

        uploader._ensure_directory("backup/2026/08")

        self.assertEqual(uploader.client.created, ["backup", "backup/2026", "backup/2026/08"])

    def test_sd_card_detects_external_mmc_partition(self):
        class FakeResult:
            stdout = json.dumps({
                "blockdevices": [
                    {"path": "/dev/mmcblk0", "type": "disk"},
                    {"path": "/dev/mmcblk0p2", "type": "part"},
                    {"path": "/dev/mmcblk2", "type": "disk"},
                    {"path": "/dev/mmcblk2p1", "type": "part"},
                ]
            })

        from unittest.mock import patch

        with patch("sdcard.subprocess.run", return_value=FakeResult()):
            self.assertEqual(SdCard._find_device(), "/dev/mmcblk2p1")

    def test_sd_card_waits_for_device_node(self):
        from unittest.mock import patch

        with patch("sdcard.subprocess.run"), patch(
            "sdcard.Path.exists", side_effect=[False, True]
        ), patch("sdcard.time.sleep"):
            SdCard._wait_for_device("/dev/mmcblk2p1")

    def test_cache_raises_when_sd_directory_cannot_be_read(self):
        class FakeConfig:
            file_filter = "all"
            prune_min_days = 30

        cfg = FakeConfig()
        cfg.sd_src = Path(self.tmpdir.name) / "sd"
        cfg.cache_path = Path(self.tmpdir.name) / "cache"
        cfg.sd_src.mkdir()
        cache = Cache(cfg, db=None)

        from unittest.mock import patch

        with patch("cache.os.walk", side_effect=OSError("card removed")):
            with self.assertRaises(TransientError):
                cache.copy()

    def test_cache_reports_current_file(self):
        class FakeDatabase:
            def find_by_sd_path(self, path):
                return None

            def create(self, *args):
                return object()

        class FakeConfig:
            file_filter = "all"
            prune_min_days = 30

        source_dir = Path(self.tmpdir.name) / "sd"
        cache_dir = Path(self.tmpdir.name) / "cache"
        source_dir.mkdir()
        (source_dir / "photo.jpg").write_bytes(b"photo")
        cfg = FakeConfig()
        cfg.sd_src = source_dir
        cfg.cache_path = cache_dir
        events = []
        bus = EventBus()
        bus.on("cache:file", lambda **event: events.append(event))

        Cache(cfg, FakeDatabase(), bus).copy()

        self.assertEqual(events[0]["path"], str(source_dir / "photo.jpg"))
        self.assertEqual(events[0]["processed"], 1)

    def test_cached_file_with_matching_metadata_is_not_hashed(self):
        from models import FileRecord
        from unittest.mock import patch

        class FakeDatabase:
            def __init__(self, record):
                self.record = record

            def find_by_sd_path(self, path):
                return self.record

        class FakeConfig:
            file_filter = "all"
            prune_min_days = 30

        source_dir = Path(self.tmpdir.name) / "sd"
        cache_dir = Path(self.tmpdir.name) / "cache"
        source_dir.mkdir()
        cache_dir.mkdir()
        source = source_dir / "photo.jpg"
        cached = cache_dir / "photo.jpg"
        source.write_bytes(b"photo")
        cached.write_bytes(b"photo")
        stat = source.stat()
        record = FileRecord(1, "hash", str(source), str(cached), 5, stat.st_size, stat.st_mtime)
        cfg = FakeConfig()
        cfg.sd_src = source_dir
        cfg.cache_path = cache_dir

        with patch("cache.xx_hash64") as hash_file:
            Cache(cfg, FakeDatabase(record)).copy()

        hash_file.assert_not_called()

    def test_status_view_shows_current_cache_file(self):
        view = BackupStatusView(bus=self.bus)
        view.progress_total = 3

        self.bus.emit("cache:file", path="/mnt/amarelli-sd/DCIM/photo.jpg", processed=1)

        self.assertEqual(view.current_file, "photo.jpg")
        self.assertEqual(view.progress_current, 1)


class FakeUploaderConfig:
    def __init__(self, cache_path, cloud_dst="backup", **extra):
        self.cache_path = cache_path
        self.cloud_dst = cloud_dst
        for key, value in extra.items():
            setattr(self, key, value)


class RecordingRclone(Rclone):
    """Rclone con runner finto: registra i comandi invece di eseguirli."""

    def __init__(self, cfg, db=None, bus=None, outputs=None, errors=None):
        self.commands = []
        self._outputs = list(outputs or [])
        self._errors = dict(errors or {})
        super().__init__(cfg, db, bus, runner=self._fake_run)

    def _fake_run(self, args):
        self.commands.append(list(args))
        error = self._errors.get(args[0])
        if error is not None:
            raise error
        return self._outputs.pop(0) if self._outputs else ""


class UploaderBackendTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.cache_path = Path(self.tmpdir.name) / "cache"
        self.cache_path.mkdir()

    def tearDown(self):
        self.tmpdir.cleanup()

    def _cfg(self, **extra):
        return FakeUploaderConfig(str(self.cache_path), **extra)

    def test_rclone_builds_copyto_command_for_named_remote(self):
        uploader = RecordingRclone(self._cfg(rclone_remote="gdrive:foto/backup"))

        uploader.put(self.cache_path / "DCIM" / "photo.jpg", "backup/DCIM/photo.jpg")

        self.assertEqual(
            uploader.commands,
            [[
                "copyto",
                str(self.cache_path / "DCIM" / "photo.jpg"),
                "gdrive:foto/backup/backup/DCIM/photo.jpg",
            ]],
        )

    def test_rclone_accepts_bare_remote_name(self):
        uploader = RecordingRclone(self._cfg(rclone_remote="dropbox"))

        uploader.delete("backup/photo.jpg")

        self.assertEqual(uploader.commands, [["deletefile", "dropbox:backup/photo.jpg"]])

    def test_rclone_keeps_absolute_base_path_of_a_remote(self):
        uploader = RecordingRclone(self._cfg(rclone_remote="sftp:/srv/backup/"))

        uploader.put(self.cache_path / "photo.jpg", "backup/photo.jpg")

        self.assertEqual(uploader.commands[0][2], "sftp:/srv/backup/backup/photo.jpg")

    def test_rclone_supports_plain_local_directory(self):
        uploader = RecordingRclone(self._cfg(rclone_remote="/mnt/usb/backup/"))

        uploader.ensure_remote_dir("backup/2026")

        self.assertEqual(uploader.commands, [["mkdir", "/mnt/usb/backup/backup/2026"]])

    def test_rclone_falls_back_to_first_configured_remote(self):
        uploader = RecordingRclone(
            self._cfg(rclone_remote=""), outputs=["gdrive:\ndropbox:\n"]
        )

        uploader.put(self.cache_path / "photo.jpg", "backup/photo.jpg")

        self.assertEqual(uploader.commands[0], ["listremotes"])
        self.assertEqual(uploader.commands[1][2], "gdrive:backup/photo.jpg")

    def test_rclone_raises_when_no_remote_is_available(self):
        with self.assertRaises(Exception):
            RecordingRclone(self._cfg(rclone_remote=""), outputs=[""])

    def test_rclone_command_includes_config_file_and_single_retry(self):
        uploader = RecordingRclone(
            self._cfg(rclone_remote="gdrive", rclone_config="/home/pi/rclone.conf")
        )

        command = Rclone._command(uploader, ["mkdir", "gdrive:backup"])

        self.assertEqual(
            command,
            [
                "rclone",
                "--config",
                "/home/pi/rclone.conf",
                "--retries",
                "1",
                "mkdir",
                "gdrive:backup",
            ],
        )

    def test_rclone_exit_codes_are_classified(self):
        uploader = RecordingRclone(self._cfg(rclone_remote="gdrive"))

        self.assertTrue(uploader.is_permanent_error(RcloneError(7, "fatal error", ["copyto"])))
        self.assertFalse(uploader.is_permanent_error(RcloneError(5, "i/o timeout", ["copyto"])))
        self.assertTrue(
            uploader.is_permanent_error(RcloneError(2, "401 Unauthorized", ["copyto"]))
        )

    def test_rclone_upload_marks_files_and_raises_transient_error(self):
        class FakeRecord:
            def __init__(self, id, cache_path):
                self.id = id
                self.cache_path = cache_path

        class FakeDatabase:
            def __init__(self, files):
                self.files = files
                self.uploaded = []
                self.errors = []

            def find_pending_uploads(self):
                return self.files

            def mark_uploaded(self, file_id, remote_path):
                self.uploaded.append((file_id, remote_path))

            def mark_upload_error(self, file_id, message):
                self.errors.append((file_id, message))

        ok = FakeRecord(1, str(self.cache_path / "DCIM" / "ok.jpg"))
        db = FakeDatabase([ok])
        uploader = RecordingRclone(self._cfg(rclone_remote="gdrive"), db=db)

        uploader.upload()
        self.assertEqual(db.uploaded, [(1, "backup/DCIM/ok.jpg")])

        failing = RecordingRclone(
            self._cfg(rclone_remote="gdrive"),
            db=FakeDatabase([ok]),
            errors={"copyto": RcloneError(5, "connection reset", ["copyto"])},
        )
        with self.assertRaises(TransientError):
            failing.upload()

    def test_upload_creates_each_remote_directory_once(self):
        class FakeRecord:
            def __init__(self, id, cache_path):
                self.id = id
                self.cache_path = cache_path

        class FakeDatabase:
            def find_pending_uploads(self):
                return [
                    FakeRecord(1, str(self.base / "DCIM" / "a.jpg")),
                    FakeRecord(2, str(self.base / "DCIM" / "b.jpg")),
                ]

            def mark_uploaded(self, file_id, remote_path):
                pass

            def mark_upload_error(self, file_id, message):
                raise AssertionError(message)

        db = FakeDatabase()
        db.base = self.cache_path
        uploader = RecordingRclone(self._cfg(rclone_remote="gdrive"), db=db)

        uploader.upload()

        mkdirs = [c for c in uploader.commands if c[0] == "mkdir"]
        self.assertEqual(mkdirs, [["mkdir", "gdrive:backup"], ["mkdir", "gdrive:backup/DCIM"]])

    def test_create_uploader_selects_the_configured_backend(self):
        cfg = self._cfg(uploader="rclone", rclone_remote="/mnt/usb")

        uploader = create_uploader(cfg, db=None)

        self.assertIsInstance(uploader, Rclone)
        self.assertEqual(uploader.name, "rclone")

    def test_create_uploader_rejects_unknown_backend(self):
        with self.assertRaises(Exception):
            create_uploader(self._cfg(uploader="dropbox-magic"), db=None)

    def test_menu_no_longer_exposes_service_selection(self):
        # Service è stato rimosso dal menu e-ink: ora si configura da /config web tra i remoti rclone.
        from menu import MENU_TREE
        labels = [item.label for item in MENU_TREE]
        self.assertNotIn("Service", labels)
        self.assertIn("WiFi", labels)
        self.assertIn("Mode", labels)
        self.assertIn("Cache", labels)
        self.assertIn("File type", labels)

    def test_uploader_can_be_switched_via_web_config(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        config_file = Path(tmp.name) / "config.json"
        config_file.write_text(json.dumps({"uploader": "webdav", "rclone_remote": ""}))
        original = config_module.CONFIG_FILE
        config_module.CONFIG_FILE = config_file
        self.addCleanup(lambda: setattr(config_module, "CONFIG_FILE", original))

        bus = EventBus()
        cfg = Config(bus=bus)
        # Simula POST /config con uploader=rclone + remoto rclone
        bus.emit("config:set", key="uploader", value="rclone")
        bus.emit("config:set", key="rclone_remote", value="dropbox:amarelli-test")

        self.assertEqual(cfg.uploader, "rclone")
        self.assertEqual(cfg.rclone_remote, "dropbox:amarelli-test")
        saved = json.loads(config_file.read_text())
        self.assertEqual(saved["uploader"], "rclone")
        self.assertEqual(saved["rclone_remote"], "dropbox:amarelli-test")

    def test_uploader_switch_is_deferred_while_backup_is_active(self):
        from backup import State

        backup = Backup(None, "old", None, bus=EventBus())
        backup._state = State.UPLOADING

        backup.set_uploader("new")

        self.assertEqual(backup._uploader, "old")
        self.assertEqual(backup._next_uploader, "new")


if __name__ == "__main__":
    unittest.main()

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
from menu import Menu
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


if __name__ == "__main__":
    unittest.main()

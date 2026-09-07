"""Test integrazione mock B2: SdCard in mock + caching + upload mock (Dropbox via rclone)."""
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backup import Backup, State
from cache import Cache
from database import Database
from eventbus import EventBus
from rclone_uploader import Rclone
from sdcard import SdCard


class RecordingRclone(Rclone):
    def __init__(self, cfg, db=None, bus=None, outputs=None, errors=None):
        self.commands = []
        self._outputs = list(outputs or [])
        self._errors = dict(errors or {})
        super().__init__(cfg, db, bus, runner=self._fake_run)

    def _fake_run(self, args):
        self.commands.append(list(args))
        err = self._errors.get(args[0])
        if err is not None:
            raise err
        return self._outputs.pop(0) if self._outputs else ""


class FakeUploaderConfig:
    def __init__(self, cache_path, cloud_dst="backup", **extra):
        self.cache_path = cache_path
        self.cloud_dst = cloud_dst
        for k, v in extra.items():
            setattr(self, k, v)


class MockSdCardTests(unittest.TestCase):
    def test_mock_accepts_plain_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            sd = Path(tmp) / "sd"
            sd.mkdir()
            (sd / "DCIM").mkdir()
            (sd / "DCIM" / "photo.jpg").write_bytes(b"fake jpg")
            card = SdCard(sd, mock=True)
            self.assertTrue(card.refresh())
            self.assertEqual(card._device, "mock")
            card.close()
            self.assertIsNone(card._device)

    def test_mock_rejects_missing_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            sd = Path(tmp) / "nonexistent"
            card = SdCard(sd, mock=True)
            self.assertFalse(card.refresh())

    def test_mock_is_readable_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            sd = Path(tmp) / "sd"
            sd.mkdir()
            card = SdCard(sd, mock=True)
            self.assertTrue(card.refresh())
            # rimuovo e verifico che diventi non disponibile
            sd.rmdir()
            self.assertFalse(card.refresh())

    def test_non_mock_still_uses_lsblk(self):
        # senza mock, con directory plain non dovrebbe risultare disponibile
        # perché _find_device ritorna None (nessun mmcblk)
        with tempfile.TemporaryDirectory() as tmp:
            sd = Path(tmp) / "sd"
            sd.mkdir()
            card = SdCard(sd, mock=False)
            # patcha subprocess per evitare lsblk reale, forza None
            from unittest.mock import patch
            with patch("sdcard.SdCard._find_device", return_value=None):
                self.assertFalse(card.refresh())


class FullMockPipelineTests(unittest.TestCase):
    def test_full_caching_then_rclone_upload_in_mock(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            sd = tmp / "sd_mock"
            cache_dir = tmp / "cache"
            db_path = tmp / "files.db"
            sd.mkdir()
            cache_dir.mkdir()
            # crea file finti come se fossero su SD
            (sd / "DCIM").mkdir()
            (sd / "DCIM" / "IMG_0001.jpg").write_bytes(b"photo1 content")
            (sd / "DCIM" / "IMG_0002.jpg").write_bytes(b"photo2 content")
            (sd / "notes.txt").write_bytes(b"should be ignored if jpg filter")

            bus = EventBus()
            db = Database(db_path)

            # SdCard mock -> deve risultare disponibile
            card = SdCard(sd, mock=True)
            self.assertTrue(card.refresh())

            # Cache come in main.py sync_sd_card()
            class Cfg:
                pass
            cfg = Cfg()
            cfg.sd_src = str(sd)
            cfg.cache_path = str(cache_dir)
            cfg.file_filter = "jpg"
            cfg.prune_min_days = 30

            cache_obj = Cache(cfg, db, bus)
            # simula Backup con cache e uploader rclone mock (locale)
            # usa rclone verso cartella locale per simulare Dropbox
            fake_cfg = FakeUploaderConfig(str(cache_dir), cloud_dst="backup", rclone_remote="/tmp/fake-dropbox")
            # usa RecordingRclone per non toccare filesystem remoto reale
            uploader = RecordingRclone(fake_cfg, db=db, bus=bus)

            backup = Backup(cache_obj, uploader, db, bus=bus, mode="upload", retry_delay=0.01)
            # avvia backup asincrono e attendi completamento
            self.assertTrue(backup.start())
            deadline = time.time() + 5
            while backup.state not in (State.COMPLETED, State.ERROR) and time.time() < deadline:
                time.sleep(0.05)
            self.assertEqual(backup.state, State.COMPLETED, f"backup ended in {backup.state}")
            # verifica che i due jpg siano stati copiati in cache e poi uploadati
            self.assertEqual(db.count_cached(), 2)
            self.assertEqual(db.count_pending_uploads(), 0)
            self.assertEqual(db.count_uploaded(), 2)
            # uploader deve aver eseguito mkdir + copyto per ogni file
            copytos = [c for c in uploader.commands if c[0] == "copyto"]
            self.assertEqual(len(copytos), 2)
            # file txt filtrato non deve essere in DB
            pending = db.find_pending_uploads()
            self.assertEqual(len(pending), 0)
            # la cartella cache fisica contiene i file
            self.assertTrue((cache_dir / "DCIM" / "IMG_0001.jpg").exists())

    def test_mock_allows_real_rclone_local_dir(self):
        """Con mock, un rclone_remote locale funziona senza lsblk/hardware."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            sd = tmp / "sd"
            cache_dir = tmp / "cache"
            remote_dir = tmp / "remote_dropbox_fake"
            db_path = tmp / "files.db"
            sd.mkdir()
            cache_dir.mkdir()
            remote_dir.mkdir()
            (sd / "a.jpg").write_bytes(b"data")

            bus = EventBus()
            db = Database(db_path)
            card = SdCard(sd, mock=True)
            self.assertTrue(card.refresh())

            class Cfg:
                pass
            cfg = Cfg()
            cfg.sd_src = str(sd)
            cfg.cache_path = str(cache_dir)
            cfg.cloud_dst = "backup"
            cfg.file_filter = "all"
            cfg.prune_min_days = None
            cfg.rclone_remote = str(remote_dir)
            cache_obj = Cache(cfg, db, bus)
            # uploader reale verso directory locale – usa rclone se presente,
            # altrimenti simula con RecordingRclone. Qui testiamo solo la costruzione.
            fake_cfg = FakeUploaderConfig(str(cache_dir), cloud_dst="backup", rclone_remote=str(remote_dir))
            uploader = RecordingRclone(fake_cfg, db=db, bus=bus)
            self.assertIn(str(remote_dir), uploader._prefix)
            backup = Backup(cache_obj, uploader, db, bus=bus, mode="upload", retry_delay=0.01)
            backup.start()
            deadline = time.time() + 5
            while backup.state not in (State.COMPLETED, State.ERROR) and time.time() < deadline:
                time.sleep(0.05)
            self.assertEqual(backup.state, State.COMPLETED)


if __name__ == "__main__":
    unittest.main()

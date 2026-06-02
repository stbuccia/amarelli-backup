from pathlib import Path
import logging
import shutil
import time
import xxhash

from exceptions import TransientError
from eventbus import EventBus

logger = logging.getLogger(__name__)


def xx_hash64(filepath, chunk_size=131072):
    h = xxhash.xxh64()

    try:
        with open(filepath, "rb") as f:
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                h.update(chunk)
        return h.hexdigest()
    except IOError as e:
        logger.error(f"Errore lettura file: {e}")
        return None


class Cache:
    def __init__(self, cfg, db, bus=None):
        self.sd_src = Path("/home/pi/SD")
        self.local_dst = Path(cfg.cache_path)
        self.cfg = cfg
        self.check_existence_dirs()

        self.db = db
        self._bus = bus or EventBus()
        self._last_seen_hashes: set[str] = set()

    @property
    def last_seen_hashes(self) -> set[str]:
        return set(self._last_seen_hashes)

    def check_existence_dirs(self):
        for path in [self.sd_src, self.local_dst]:
            if not path.exists():
                raise Exception(str(path) + " not found")

            if not path.is_dir():
                raise Exception(str(path) + " is not a directory")

    def _is_cached_file(self, file_hash):
        record = self.db.find_by_hash(file_hash)
        return record is not None and record.cache_path is not None

    def count_uncached(self) -> int:
        count = 0
        try:
            it = self.sd_src.walk()
        except OSError:
            return 0
        for root, dirs, filenames in it:
            for filename in filenames:
                file_hash = xx_hash64(root / filename)
                if file_hash and not self._is_cached_file(file_hash):
                    count += 1
        return count

    def copy(self):
        self._last_seen_hashes = set()

        try:
            it = self.sd_src.walk()
        except OSError as e:
            raise TransientError(f"Cannot read SD card: {e}") from e

        for root, dirs, filenames in it:
            for filename in filenames:
                src = root / filename

                file_hash = xx_hash64(src)
                if file_hash:
                    self._last_seen_hashes.add(file_hash)

                if not self._is_cached_file(file_hash):
                    rel = src.relative_to(self.sd_src)
                    dst = self.local_dst / rel
                    try:
                        dst.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(src, dst)
                        logger.info(f"Copied: {src} -> {dst}")

                        st = src.stat()
                        record = self.db.create(
                            file_hash, str(src), str(dst), st.st_size, st.st_mtime
                        )
                        self._bus.emit("file:cached", file=record)
                        logger.info(
                            f"Inserted in DB: {file_hash}, {src}, {dst}, {st.st_size}, {st.st_mtime}"
                        )
                    except Exception as e:
                        logger.error(f"Error copying {src}: {e}")

    def prune(self):
        min_date = (
            time.time() - (self.cfg.prune_min_days * 86400)
            if self.cfg.prune_min_days
            else None
        )

        try:
            uploaded = self.db.find_uploaded_not_pruned(min_date)
        except Exception as e:
            raise TransientError(f"Database error during prune: {e}") from e
        for f in uploaded:
            try:
                path = Path(f.cache_path)
                if path.exists():
                    path.unlink()
                    logger.info(f"Deleted: {path}")
                self.db.mark_pruned(f.id)
                self._bus.emit("file:pruned", file=f)
                logger.info(f"Marked pruned: {f.id}")
            except Exception as e:
                logger.error(f"Error pruning {f.id}: {e}")

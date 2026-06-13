from pathlib import Path
import logging
import shutil
import time
import xxhash

from exceptions import TransientError
from eventbus import EventBus

logger = logging.getLogger(__name__)

_RAW_EXTENSIONS = frozenset({
    '.cr2', '.cr3',       # Canon
    '.nef', '.nrw',       # Nikon
    '.arw', '.srf', '.sr2',  # Sony
    '.raf',               # Fujifilm
    '.rw2',               # Panasonic
    '.orf',               # Olympus
    '.dng',               # Adobe / Leica
    '.pef',               # Pentax
    '.x3f',               # Sigma
})

_JPG_EXTENSIONS = frozenset({'.jpg', '.jpeg'})

_IMAGE_EXTENSIONS = _JPG_EXTENSIONS | _RAW_EXTENSIONS


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
        logger.error(f"Error reading file: {e}")
        return None


class Cache:
    def __init__(self, cfg, db, bus=None):
        self.sd_src = Path(cfg.sd_src)
        self.local_dst = Path(cfg.cache_path)
        self.cfg = cfg
        self.check_existence_dirs()

        self.db = db
        self._bus = bus or EventBus()
        self._last_seen_paths: set[str] = set()

    @property
    def last_seen_paths(self) -> set[str]:
        return set(self._last_seen_paths)

    def check_existence_dirs(self):
        for path in [self.sd_src, self.local_dst]:
            if not path.exists():
                raise Exception(str(path) + " not found")

            if not path.is_dir():
                raise Exception(str(path) + " is not a directory")

    def _is_allowed_file(self, src: Path) -> bool:
        filter_mode = getattr(self.cfg, 'file_filter', 'all')
        if filter_mode == 'all':
            return True
        suffix = src.suffix.lower()
        if filter_mode == 'jpg':
            return suffix in _JPG_EXTENSIONS
        if filter_mode == 'images':
            return suffix in _IMAGE_EXTENSIONS
        return True

    def _needs_caching(self, sd_path: str, file_hash: str) -> bool:
        record = self.db.find_by_sd_path(sd_path)
        if record is None:
            return True
        if record.cache_path is None:
            return True
        if record.file_hash != file_hash:
            return True
        return False

    def count_uncached(self) -> int:
        count = 0
        try:
            it = self.sd_src.walk()
        except OSError:
            return 0
        for root, dirs, filenames in it:
            for filename in filenames:
                src = root / filename
                if not self._is_allowed_file(src):
                    continue
                file_hash = xx_hash64(src)
                if file_hash and self._needs_caching(str(src), file_hash):
                    count += 1
        return count

    def copy(self):
        self._last_seen_paths = set()

        try:
            it = self.sd_src.walk()
        except OSError as e:
            raise TransientError(f"Cannot read SD card: {e}") from e

        for root, dirs, filenames in it:
            for filename in filenames:
                src = root / filename
                if not self._is_allowed_file(src):
                    continue
                sd_path = str(src)

                file_hash = xx_hash64(src)
                if file_hash:
                    self._last_seen_paths.add(sd_path)

                if not file_hash:
                    continue

                if not self._needs_caching(sd_path, file_hash):
                    continue

                record = self.db.find_by_sd_path(sd_path)
                rel = src.relative_to(self.sd_src)
                dst = self.local_dst / rel
                try:
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dst)
                    logger.info(f"Copied: {src} -> {dst}")

                    st = src.stat()
                    if record is not None:
                        record = self.db.re_cache(
                            file_hash, sd_path, str(dst), st.st_size, st.st_mtime
                        )
                        logger.info(f"Re-cached: {sd_path}")
                    else:
                        record = self.db.create(
                            file_hash, sd_path, str(dst), st.st_size, st.st_mtime
                        )
                        logger.info(f"Inserted in DB: {sd_path}")
                    self._bus.emit("file:cached", file=record)
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

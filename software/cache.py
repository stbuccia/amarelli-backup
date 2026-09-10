from pathlib import Path
import logging
import os
import shutil
import time
import xxhash

from exceptions import TransientError
from eventbus import EventBus

logger = logging.getLogger(__name__)

_RAW_EXTENSIONS = frozenset(
    {
        ".cr2",
        ".cr3",
        ".nef",
        ".nrw",
        ".arw",
        ".srf",
        ".sr2",
        ".raf",
        ".rw2",
        ".orf",
        ".dng",
        ".pef",
        ".x3f",
    }
)
_JPG_EXTENSIONS = frozenset({".jpg", ".jpeg"})
_IMAGE_EXTENSIONS = _JPG_EXTENSIONS | _RAW_EXTENSIONS

_COPY_CHUNK = 64 * 1024


def xx_hash64(filepath, chunk_size=131072):
    hasher = xxhash.xxh64()
    try:
        with open(filepath, "rb") as source:
            while chunk := source.read(chunk_size):
                hasher.update(chunk)
        return hasher.hexdigest()
    except OSError as error:
        logger.error("Error reading file %s: %s", filepath, error)
        return None


class Cache:
    def __init__(self, cfg, db, bus=None, io_lock=None):
        self.sd_src = Path(cfg.sd_src)
        self.local_dst = Path(cfg.cache_path)
        self.cfg = cfg
        self._file_filter = getattr(cfg, "file_filter", "all")
        self._prune_min_days = getattr(cfg, "prune_min_days", 0)
        self.check_existence_dirs()
        self.db = db
        self._bus = bus or EventBus()
        self._last_seen_paths: set[str] = set()
        self.last_copy_stats = {"ok": 0, "failed": 0, "total": 0}
        self.last_prune_stats = {"ok": 0, "failed": 0}

    @property
    def last_seen_paths(self) -> set[str]:
        return set(self._last_seen_paths)

    def check_existence_dirs(self):
        if not self.sd_src.is_dir():
            raise Exception(f"{self.sd_src} is not a directory")
        self.local_dst.mkdir(parents=True, exist_ok=True)
        if not self.local_dst.is_dir():
            raise Exception(f"{self.local_dst} is not a directory")

    def prepare_backup(self):
        self._file_filter = getattr(self.cfg, "file_filter", "all")
        self._prune_min_days = getattr(self.cfg, "prune_min_days", 0)

    def _is_allowed_file(self, src: Path) -> bool:
        if self._file_filter == "jpg":
            return src.suffix.lower() in _JPG_EXTENSIONS
        if self._file_filter == "images":
            return src.suffix.lower() in _IMAGE_EXTENSIONS
        return True

    def _cancelled(self) -> bool:
        cancel = getattr(self, "_cancel", None)
        return cancel is not None and cancel.is_set()

    @staticmethod
    def _raise_sd_error(error):
        raise TransientError(f"Cannot read SD card: {error}")

    @staticmethod
    def _is_cached_unchanged(src: Path, record) -> bool:
        if record is None or record.cache_path is None:
            return False
        if not Path(record.cache_path).exists():
            return False
        stat = src.stat()
        return record.size_bytes == stat.st_size and record.mtime == stat.st_mtime

    def _walk(self):
        for root, dirs, filenames in os.walk(self.sd_src, onerror=self._raise_sd_error):
            yield Path(root), dirs, filenames

    def count_uncached(self) -> int:
        try:
            return sum(
                1
                for root, _, filenames in self._walk()
                for filename in filenames
                if self._is_allowed_file(root / filename)
            )
        except OSError:
            return 0

    def _copy_file(self, src: Path, dst: Path) -> None:
        """Copia a chunk cosi' la pausa resta reattiva e non blocca il display.
        Nessun lock SPI: la SD passa dal kernel (mmc_spi), il display da spidev;
        il bus e' gia' serializzato dal kernel."""
        partial = dst.with_name(f".{dst.name}.partial")
        dst.parent.mkdir(parents=True, exist_ok=True)
        partial.unlink(missing_ok=True)
        try:
            with open(src, "rb") as fsrc, open(partial, "wb") as fdst:
                while chunk := fsrc.read(_COPY_CHUNK):
                    if self._cancelled():
                        partial.unlink(missing_ok=True)
                        raise _CopyCancelled
                    fdst.write(chunk)
            try:
                shutil.copystat(src, partial)
            except OSError:
                pass
            partial.replace(dst)
        except _CopyCancelled:
            raise
        except OSError:
            partial.unlink(missing_ok=True)
            raise

    def copy(self):
        self._last_seen_paths = set()
        failures = []
        ok = 0
        processed = 0
        try:
            for root, _, filenames in self._walk():
                for filename in filenames:
                    if self._cancelled():
                        logger.info("Caching interrupted by pause at %s", filename)
                        self.last_copy_stats = {
                            "ok": ok,
                            "failed": len(failures),
                            "total": processed,
                        }
                        return
                    src = root / filename
                    self._last_seen_paths.add(str(src))
                    if not self._is_allowed_file(src):
                        continue

                    processed += 1
                    self._bus.emit("cache:file", path=str(src), processed=processed)
                    logger.info("Caching file %d: %s", processed, src)
                    record = self.db.find_by_sd_path(str(src))
                    if self._is_cached_unchanged(src, record):
                        logger.info("Already cached (size and mtime match): %s", src)
                        continue

                    dst = self.local_dst / src.relative_to(self.sd_src)
                    try:
                        logger.info("Copying %s -> %s", src, dst)
                        self._copy_file(src, dst)
                    except _CopyCancelled:
                        logger.info("Caching paused mid-copy %s", src)
                        self.last_copy_stats = {
                            "ok": ok,
                            "failed": len(failures),
                            "total": processed,
                        }
                        return
                    except OSError as error:
                        logger.error("Error copying %s: %s", src, error)
                        failures.append(f"{src}: {error}")
                        continue

                    file_hash = xx_hash64(dst)
                    if file_hash is None:
                        dst.unlink(missing_ok=True)
                        failures.append(f"cannot hash cached file {dst}")
                        continue
                    stat = src.stat()
                    if record is None:
                        record = self.db.create(
                            file_hash, str(src), str(dst), stat.st_size, stat.st_mtime
                        )
                        logger.info("Inserted in DB: %s", src)
                    else:
                        record = self.db.re_cache(
                            file_hash, str(src), str(dst), stat.st_size, stat.st_mtime
                        )
                        logger.info("Re-cached: %s", src)
                    self._bus.emit("file:cached", file=record)
                    ok += 1
        except OSError as error:
            self.last_copy_stats = {
                "ok": ok,
                "failed": len(failures),
                "total": processed,
            }
            raise TransientError(f"Cannot read SD card: {error}") from error

        self.last_copy_stats = {"ok": ok, "failed": len(failures), "total": processed}
        if failures:
            raise TransientError(
                f"Failed to cache {len(failures)} file(s): {'; '.join(failures)}"
            )

    def prune(self):
        if self._cancelled():
            logger.info("Pruning interrupted by pause")
            self.last_prune_stats = {"ok": 0, "failed": 0}
            return
        if self._prune_min_days is None:
            logger.info("Cache pruning is disabled")
            self.last_prune_stats = {"ok": 0, "failed": 0}
            return
        min_date = (
            time.time() - self._prune_min_days * 86400 if self._prune_min_days else None
        )
        try:
            uploaded = self.db.find_uploaded_not_pruned(min_date)
        except Exception as error:
            self.last_prune_stats = {"ok": 0, "failed": 0}
            raise TransientError(f"Database error during prune: {error}") from error
        failures = []
        ok = 0
        for record in uploaded:
            try:
                path = Path(record.cache_path)
                if path.exists():
                    path.unlink()
                    logger.info("Deleted: %s", path)
                self.db.mark_pruned(record.id)
                self._bus.emit("file:pruned", file=record)
                ok += 1
            except OSError as error:
                logger.error("Error pruning %s: %s", record.id, error)
                failures.append(f"{record.id}: {error}")
        self.last_prune_stats = {"ok": ok, "failed": len(failures)}
        if failures:
            raise TransientError(
                f"Failed to prune {len(failures)} file(s): {'; '.join(failures)}"
            )


class _CopyCancelled(Exception):
    pass

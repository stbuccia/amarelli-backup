from pathlib import Path
import logging
import shutil
import time
import xxhash

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
    def __init__(self, cfg, db):
        self.sd_src = Path("/home/stefano/Immagini/Luna")
        self.local_dst = Path(cfg.cache_path)
        self.cfg = cfg
        self.check_existence_dirs()

        self.db = db

    def check_existence_dirs(self):
        # TODO: Nel caso non esista meglio inserire il local_dst
        for path in [self.sd_src, self.local_dst]:
            if not path.exists():
                raise Exception(str(path) + " not found")

            if not path.is_dir():
                raise Exception(str(path) + " is not a directory")

    def _is_cached_file(self, file_hash):
        return self.db.is_cached(file_hash)

    def copy(self):
        for root, dirs, filenames in self.sd_src.walk():
            for filename in filenames:
                src = root / filename

                file_hash = xx_hash64(src)
                if not self._is_cached_file(file_hash):
                    rel = src.relative_to(self.sd_src)
                    dst = self.local_dst / rel
                    try:
                        dst.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(src, dst)
                        logger.info(f"Copied: {src} -> {dst}")

                        st = src.stat()
                        self.db.insert_file(
                            file_hash, str(src), str(dst), st.st_size, st.st_mtime
                        )
                        logger.info(
                            f"Inserted in DB: {file_hash}, {src}, {dst}, {st.st_size}, {st.st_mtime}"
                        )
                    except Exception as e:
                        logger.error(f"Error copying {src}: {e}")

    def prune(self):
        min_date = (
            time.time() - (self.cfg.prune_min_days * 86400)  # 86400 = 60*60*24
            if self.cfg.prune_min_days
            else None
        )

        uploaded = self.db.get_files_to_be_pruned(min_date)
        for f in uploaded:
            try:
                path = Path(f["cache_path"])
                if path.exists():
                    path.unlink()
                    logger.info(f"Deleted: {path}")
                self.db.mark_pruned(f["id"])
                logger.info(f"Marked pruned: {f['id']}")
            except Exception as e:
                logger.error(f"Error pruning {f['id']}: {e}")

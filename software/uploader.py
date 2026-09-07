#!/usr/bin/python3
"""Pipeline di upload condivisa da tutti i backend remoti.

Un backend deve implementare solo tre operazioni elementari
(`ensure_remote_dir`, `put`, `delete`): il ciclo sui file pendenti,
l'aggiornamento del database e la classificazione degli errori sono qui.
"""

import logging
from abc import ABC, abstractmethod
from pathlib import Path, PurePosixPath

from exceptions import TransientError, PermanentError
from eventbus import EventBus

logger = logging.getLogger(__name__)

# Sottostringhe che indicano un problema di credenziali/permessi: non ha senso
# ritentare, serve l'intervento dell'utente.
AUTH_ERROR_KEYWORDS = (
    "401",
    "403",
    "unauthor",
    "forbidden",
    "invalid credentials",
    "permission denied",
)


class Uploader(ABC):
    """Base comune dei backend di upload."""

    name = "uploader"

    def __init__(self, cfg, db, bus=None):
        self.db = db
        self._bus = bus or EventBus()
        self.cache_path = cfg.cache_path
        self._cloud_dst = cfg.cloud_dst
        self._ensured_dirs: set[str] = set()
        self.last_upload_stats = {"ok": 0, "failed": 0, "total": 0}
        self.last_cleanup_stats = {"ok": 0, "failed": 0}

    # --- Configurazione ---

    @property
    def cloud_dst(self) -> str:
        return self._cloud_dst

    @cloud_dst.setter
    def cloud_dst(self, value: str) -> None:
        self._cloud_dst = value
        self._ensured_dirs.clear()

    # --- Operazioni specifiche del backend ---

    @abstractmethod
    def ensure_remote_dir(self, directory: str) -> None:
        """Crea la directory remota (con i genitori) se non esiste."""

    @abstractmethod
    def put(self, local_path: Path, remote_path: str) -> None:
        """Carica un singolo file nel percorso remoto indicato."""

    @abstractmethod
    def delete(self, remote_path: str) -> None:
        """Cancella un singolo file remoto."""

    def is_permanent_error(self, error: Exception) -> bool:
        """True se l'errore non e' recuperabile con un retry."""
        text = str(error).lower()
        return any(keyword in text for keyword in AUTH_ERROR_KEYWORDS)

    # --- Helper interni ---

    def _fail(self, error: Exception, permanent_msg: str, transient_msg: str):
        if self.is_permanent_error(error):
            raise PermanentError(permanent_msg) from error
        raise TransientError(transient_msg) from error

    def _ensure_remote_dir_cached(self, directory: str) -> None:
        if directory in self._ensured_dirs:
            return
        self.ensure_remote_dir(directory)
        self._ensured_dirs.add(directory)

    @staticmethod
    def _remote_target(cloud_dst: str, local_src: Path, local_path: Path) -> PurePosixPath:
        rel_path = local_path.relative_to(local_src).as_posix()
        return PurePosixPath(cloud_dst) / rel_path

    # --- Pipeline condivisa ---

    def upload(self):
        cloud_dst = self._cloud_dst
        local_src = Path(self.cache_path)
        self._ensured_dirs.clear()

        try:
            self._ensure_remote_dir_cached(cloud_dst)
        except Exception as e:
            self.last_upload_stats = {"ok": 0, "failed": 1, "total": 1}
            self._fail(
                e,
                f"Remote refused the request: {e}",
                f"Cannot reach remote: {e}",
            )

        files = self.db.find_pending_uploads()
        total = len(files)
        if not files:
            self.last_upload_stats = {"ok": 0, "failed": 0, "total": 0}
            return

        error_count = 0
        ok_count = 0
        last_error = None

        for f in files:
            local_path = Path(f.cache_path)
            remote_path = self._remote_target(cloud_dst, local_src, local_path)

            try:
                self._ensure_remote_dir_cached(str(remote_path.parent))

                logger.info("Uploading %s -> %s", local_path, remote_path)
                self.put(local_path, str(remote_path))
                self.db.mark_uploaded(f.id, str(remote_path))
                self._bus.emit("file:uploaded", file=f)
                logger.info("Uploaded: %s", f.id)
                ok_count += 1
            except Exception as e:
                self.db.mark_upload_error(f.id, str(e))
                logger.error("Error uploading %s: %s", f.id, e)
                error_count += 1
                last_error = e

        self.last_upload_stats = {"ok": ok_count, "failed": error_count, "total": total}
        if error_count > 0 and last_error is not None:
            self._fail(
                last_error,
                f"{error_count} file(s) failed to upload: {last_error}",
                f"{error_count} file(s) failed to upload",
            )

    def cleanup_remote(self):
        files = self.db.find_marked_for_deletion()
        if not files:
            logger.info("No remote files to clean up")
            self.last_cleanup_stats = {"ok": 0, "failed": 0}
            return

        success_count = 0
        error_count = 0
        last_error = None

        for f in files:
            remote_path = f.remote_path
            if not remote_path:
                continue
            try:
                logger.info("Deleting remote file: %s", remote_path)
                self.delete(remote_path)
                local_path = Path(f.cache_path) if f.cache_path else None
                if local_path and local_path.exists():
                    local_path.unlink()
                    logger.info("Deleted local cache: %s", local_path)
                self.db.clear_deletion_mark(f.id)
                self._bus.emit("file:remote_deleted", file=f)
                logger.info("Deleted: %s", remote_path)
                success_count += 1
            except Exception as e:
                logger.error("Error deleting remote file %s: %s", remote_path, e)
                error_count += 1
                last_error = e

        self.last_cleanup_stats = {"ok": success_count, "failed": error_count}
        if success_count == 0 and error_count > 0 and last_error is not None:
            self._fail(
                last_error,
                f"All {error_count} remote deletions failed: {last_error}",
                f"All {error_count} files failed to delete from remote",
            )


def available_backends() -> tuple[str, ...]:
    return ("webdav", "rclone")


def create_uploader(cfg, db, bus=None) -> Uploader:
    """Istanzia il backend indicato da `cfg.uploader` (default: webdav).

    Gli import sono ritardati perche' ogni backend ha dipendenze diverse:
    con rclone il pacchetto `webdavclient3` puo' non essere installato.
    """
    name = (getattr(cfg, "uploader", None) or "webdav").strip().lower()

    if name == "webdav":
        from webdav_uploader import WebDav

        return WebDav(cfg, db, bus)

    if name == "rclone":
        from rclone_uploader import Rclone

        return Rclone(cfg, db, bus)

    raise Exception(
        f"Unknown uploader backend '{name}': valid values are {', '.join(available_backends())}"
    )

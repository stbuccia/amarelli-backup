#!/usr/bin/python3


from webdav3.client import Client
import logging
from pathlib import Path

from exceptions import TransientError, PermanentError
from eventbus import EventBus

logger = logging.getLogger(__name__)


class WebDav:
    def __init__(self, cfg, db, bus=None):
        if not cfg.webdav_hostname:
            raise Exception("WebDAV URL not configured")

        folder = cfg.webdav_folder or ""
        folder_path = "/" + folder + "/" if folder else "/"

        self.client = Client(
            {
                "webdav_hostname": cfg.webdav_hostname + folder_path,
                "webdav_login": cfg.webdav_login,
                "webdav_password": cfg.webdav_password,
            }
        )
        self.db = db
        self._bus = bus or EventBus()
        self.cache_path = cfg.cache_path
        self._cloud_dst = cfg.cloud_dst

    @property
    def cloud_dst(self) -> str:
        return self._cloud_dst

    @cloud_dst.setter
    def cloud_dst(self, value: str) -> None:
        self._cloud_dst = value

    def upload(self):
        cloud_dst = self._cloud_dst
        local_src = Path(self.cache_path)

        try:
            if not self.client.check(cloud_dst):
                self.client.execute_request("mkdir", cloud_dst)
        except Exception as e:
            err = str(e).lower()
            if any(kw in err for kw in ("401", "403", "unauthor", "forbidden")):
                raise PermanentError(f"Auth error accessing remote: {e}") from e
            raise TransientError(f"Cannot reach remote: {e}") from e

        files = self.db.find_pending_uploads()
        if not files:
            return

        success_count = 0
        error_count = 0
        last_error = None

        for f in files:
            local_path = Path(f.cache_path)
            rel_path = local_path.relative_to(local_src)
            remote_path = Path(cloud_dst) / rel_path
            remote_dir = remote_path.parent

            try:
                if not self.client.check(str(remote_dir)):
                    self.client.execute_request("mkdir", str(remote_dir))

                logger.info(f"Uploading {local_path} -> {remote_path}")
                self.client.upload_sync(str(remote_path), str(local_path))
                self.db.mark_uploaded(f.id, str(remote_path))
                self._bus.emit("file:uploaded", file=f)
                logger.info(f"Uploaded: {f.id}")
                success_count += 1
            except Exception as e:
                self.db.mark_upload_error(f.id, str(e))
                logger.error(f"Error uploading {f.id}: {e}")
                error_count += 1
                last_error = e

        if success_count == 0 and error_count > 0 and last_error is not None:
            err = str(last_error).lower()
            if any(kw in err for kw in ("401", "403", "unauthor", "forbidden")):
                raise PermanentError(
                    f"Auth error - all {error_count} files failed"
                ) from last_error
            raise TransientError(
                f"All {error_count} files failed to upload"
            ) from last_error

    def cleanup_remote(self):
        files = self.db.find_marked_for_deletion()
        if not files:
            logger.info("No remote files to clean up")
            return

        success_count = 0
        error_count = 0
        last_error = None

        for f in files:
            remote_path = f.remote_path
            if not remote_path:
                continue
            try:
                logger.info(f"Deleting remote file: {remote_path}")
                self.client.clean(remote_path)
                local_path = Path(f.cache_path) if f.cache_path else None
                if local_path and local_path.exists():
                    local_path.unlink()
                    logger.info(f"Deleted local cache: {local_path}")
                self.db.clear_deletion_mark(f.id)
                self._bus.emit("file:remote_deleted", file=f)
                logger.info(f"Deleted: {remote_path}")
                success_count += 1
            except Exception as e:
                logger.error(f"Error deleting remote file {remote_path}: {e}")
                error_count += 1
                last_error = e

        if success_count == 0 and error_count > 0 and last_error is not None:
            err = str(last_error).lower()
            if any(kw in err for kw in ("401", "403", "unauthor", "forbidden")):
                raise PermanentError(
                    f"Auth error - all {error_count} files failed to delete"
                ) from last_error
            raise TransientError(
                f"All {error_count} files failed to delete from remote"
            ) from last_error

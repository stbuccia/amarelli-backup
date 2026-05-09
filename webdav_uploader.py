#!/usr/bin/python3


from webdav3.client import Client
import datetime
import logging
from pathlib import Path

from config import Config
from database import Database
from cache import Cache
from log import setup_logger

logger = logging.getLogger(__name__)


class WebDav:
    def __init__(self, cfg, db):
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
        self.cache_path = cfg.cache_path

    def upload(self):
        today_str = ""  # datetime.date.today().strftime("%Y-%m-%d")
        cloud_dst = "/" + today_str
        local_src = Path(self.cache_path)

        if not self.client.check(cloud_dst):
            self.client.execute_request("mkdir", cloud_dst)

        files = self.db.get_files_to_upload()
        for f in files:
            local_path = Path(f["cache_path"])
            rel_path = local_path.relative_to(local_src)
            remote_path = Path(cloud_dst) / rel_path
            remote_dir = remote_path.parent

            if not self.client.check(str(remote_dir)):
                self.client.execute_request("mkdir", str(remote_dir))

            try:
                logger.info(f"Uploading {local_path} -> {remote_path}")
                self.client.upload_sync(str(remote_path), str(local_path))
                self.db.mark_uploaded(f["id"], str(remote_path))
                logger.info(f"Uploaded: {f['id']}")
            except Exception as e:
                self.db.mark_upload_error(f["id"], str(e))
                logger.error(f"Error uploading {f['id']}: {e}")

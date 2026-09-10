#!/usr/bin/python3
"""Backend di upload WebDAV (Nextcloud, ownCloud, server generici)."""

import logging
from pathlib import PurePosixPath

from webdav3.client import Client

from uploader import Uploader

logger = logging.getLogger(__name__)


class WebDav(Uploader):
    name = "webdav"

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
        super().__init__(cfg, db, bus)

    def ensure_remote_dir(self, directory: str) -> None:
        path = PurePosixPath(directory)
        current = "/" if path.is_absolute() else ""
        for part in path.parts:
            if part in ("/", "."):
                continue
            current = f"{current.rstrip('/')}/{part}" if current else part
            if not self.client.check(current):
                self.client.execute_request("mkdir", current)

    def put(self, local_path, remote_path: str) -> None:
        self.client.upload_sync(str(remote_path), str(local_path))

    def delete(self, remote_path: str) -> None:
        self.client.clean(str(remote_path))

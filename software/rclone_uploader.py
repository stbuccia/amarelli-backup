#!/usr/bin/python3
"""Backend di upload basato sulla CLI di rclone.

Copre qualunque destinazione rclone (Google Drive, Dropbox, OneDrive, S3,
Backblaze, SFTP, WebDAV, ...). Il remoto si imposta con `rclone_remote` in
config.json o RCLONE_REMOTE nel .env:

    "gdrive"              -> radice del remoto gdrive
    "gdrive:foto/backup"  -> sottocartella del remoto gdrive
    "/mnt/usb/backup"     -> cartella locale (chiavetta USB, disco)
    ""                    -> primo remoto configurato in rclone
"""

import logging
import subprocess

from uploader import Uploader

logger = logging.getLogger(__name__)

# Exit code rclone che non migliorano con un retry:
# 1 uso/sintassi, 3 dir mancante, 4 file mancante, 7 errore fatale.
PERMANENT_EXIT_CODES = frozenset({1, 3, 4, 7})
TIMEOUT_EXIT_CODE = 5
DEFAULT_TIMEOUT = 300


class RcloneError(Exception):
    def __init__(self, returncode: int, stderr: str, args: list[str]):
        self.returncode = returncode
        self.stderr = (stderr or "").strip()
        self.args_list = list(args)
        detail = self.stderr.splitlines()[-1] if self.stderr else "no output"
        super().__init__(
            f"rclone {' '.join(self.args_list)} failed (exit {returncode}): {detail}"
        )


class Rclone(Uploader):
    name = "rclone"

    def __init__(self, cfg, db, bus=None, runner=None):
        self._binary = getattr(cfg, "rclone_binary", None) or "rclone"
        self._config_file = getattr(cfg, "rclone_config", None) or ""
        self._timeout = int(getattr(cfg, "rclone_timeout", None) or DEFAULT_TIMEOUT)
        if runner is not None:
            self._run = runner
        self._prefix = self._resolve_prefix(getattr(cfg, "rclone_remote", "") or "")
        logger.info("rclone backend ready, destination prefix: %s", self._prefix)
        super().__init__(cfg, db, bus)

    def _resolve_prefix(self, remote: str) -> str:
        remote = remote.strip()
        if not remote:
            remote = self._first_remote()

        if ":" in remote:
            name, _, base = remote.partition(":")
            # Rimuovi solo gli slash finali: "sftp:/srv/backup" resta assoluto.
            base = base.rstrip("/")
            return f"{name}:{base}" if base else f"{name}:"

        if remote.startswith(("/", "~", ".")):
            return remote.rstrip("/")

        return f"{remote}:"

    def _first_remote(self) -> str:
        remotes = [line.strip() for line in self._run(["listremotes"]).splitlines()]
        remotes = [r for r in remotes if r]
        if not remotes:
            raise Exception(
                "No rclone remote configured: run 'rclone config' or set rclone_remote"
            )
        chosen = remotes[0]
        logger.info(
            "rclone_remote not set, using the first configured remote: %s", chosen
        )
        return chosen

    def _remote_path(self, path: str) -> str:
        rel = str(path).lstrip("/")
        if not rel:
            return self._prefix
        if self._prefix.endswith(":"):
            return f"{self._prefix}{rel}"
        return f"{self._prefix}/{rel}"

    def _command(self, args: list[str]) -> list[str]:
        command = [self._binary]
        if self._config_file:
            command += ["--config", self._config_file]
        # I retry con backoff li gestisce la macchina a stati di Backup.
        command += ["--retries", "1"]
        return command + list(args)

    def _run(self, args: list[str]) -> str:
        command = self._command(args)
        try:
            result = subprocess.run(
                command, capture_output=True, text=True, timeout=self._timeout
            )
        except FileNotFoundError as e:
            raise Exception(
                f"rclone not found ('{self._binary}'): install it with "
                "'sudo apt install rclone'"
            ) from e
        except subprocess.TimeoutExpired as e:
            raise RcloneError(
                TIMEOUT_EXIT_CODE, f"timed out after {self._timeout}s", args
            ) from e

        if result.returncode != 0:
            raise RcloneError(result.returncode, result.stderr, args)
        return result.stdout

    def ensure_remote_dir(self, directory: str) -> None:
        self._run(["mkdir", self._remote_path(directory)])

    def put(self, local_path, remote_path: str) -> None:
        self._run(["copyto", str(local_path), self._remote_path(remote_path)])

    def delete(self, remote_path: str) -> None:
        self._run(["deletefile", self._remote_path(remote_path)])

    def is_permanent_error(self, error: Exception) -> bool:
        if super().is_permanent_error(error):
            return True
        return getattr(error, "returncode", None) in PERMANENT_EXIT_CODES

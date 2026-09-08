import json
import logging
import os
import re
import subprocess
import time
from pathlib import Path

logger = logging.getLogger(__name__)


class SdCard:
    def __init__(self, mount_path: str | Path, mock: bool = False, mount_enabled: bool = True):
        self.mount_path = Path(mount_path)
        self._device = None
        self._mock = bool(mock)
        self._mount_enabled = bool(mount_enabled)

    def _refresh_mock(self) -> bool:
        if not self.mount_path.is_dir():
            self._device = None
            return False
        try:
            next(self.mount_path.iterdir(), None)
        except OSError as error:
            logger.warning("Mock SD %s is not readable: %s", self.mount_path, error)
            self._device = None
            return False
        self._device = "mock"
        return True

    def is_present(self) -> bool:
        """Device presente (sda/mmcblk) indipendentemente dal mount - per UI 'SD available' in manuale."""
        if self._mock or not self._mount_enabled:
            return self._refresh_mock()
        device = self._find_device()
        return device is not None and Path(device).exists()

    def is_available(self) -> bool:
        """Lightweight detect: verifica se montato e leggibile (usato per creare Cache)."""
        if self._mock or not self._mount_enabled:
            return self._refresh_mock()
        device = self._find_device()
        if device is None or not Path(device).exists():
            self._device = None
            return False
        if not os.path.ismount(self.mount_path):
            self._device = None
            return False
        try:
            next(self.mount_path.iterdir(), None)
        except OSError:
            self._device = None
            return False
        self._device = device
        return True

    def try_mount(self) -> bool:
        """Tenta mount RO se necessario. Ritorna True se dopo la chiamata la SD è disponibile."""
        if self._mock or not self._mount_enabled:
            return self._refresh_mock()
        device = self._find_device()
        if device is None or not Path(device).exists():
            if os.path.ismount(self.mount_path):
                subprocess.run(["sudo", "umount", str(self.mount_path)], check=False)
            self._device = None
            return False
        if not os.path.ismount(self.mount_path):
            try:
                self._wait_for_device(device)
                subprocess.run(
                    ["sudo", "mkdir", "-p", str(self.mount_path)],
                    check=True,
                    capture_output=True,
                    text=True,
                )
                subprocess.run(
                    ["sudo", "mount", "-o", "ro", device, str(self.mount_path)],
                    check=True,
                    capture_output=True,
                    text=True,
                )
                kind = "USB" if self._is_usb_device(device) else "SD card"
                logger.info("Mounted %s %s at %s", kind, device, self.mount_path)
            except subprocess.CalledProcessError as error:
                logger.warning("Cannot mount SD card %s: %s", device, error.stderr.strip())
                return False
            except OSError as error:
                logger.warning("Cannot prepare SD mount point %s: %s", self.mount_path, error)
                return False
        try:
            next(self.mount_path.iterdir(), None)
        except OSError as error:
            logger.warning("SD card mount %s is not readable: %s", self.mount_path, error)
            subprocess.run(["sudo", "umount", str(self.mount_path)], check=False)
            self._device = None
            return False
        self._device = device
        return True

    def refresh(self) -> bool:
        # Compat: mantiene API storica (mount se necessario)
        return self.try_mount()

    def close(self) -> None:
        if self._mock or not self._mount_enabled:
            self._device = None
            return
        if os.path.ismount(self.mount_path):
            subprocess.run(["sudo", "umount", str(self.mount_path)], check=False)
        self._device = None

    @staticmethod
    def _wait_for_device(device: str) -> None:
        """Wait for the block-device node created after an SD hot-plug event."""
        subprocess.run(["udevadm", "settle", "--timeout=5"], check=False)
        deadline = time.monotonic() + 5
        while not Path(device).exists():
            if time.monotonic() >= deadline:
                raise OSError(f"SD card device {device} is not ready")
            time.sleep(0.1)

    @staticmethod
    def _collect_all_devices(blockdevices) -> list[dict]:
        """Raccoglie ricorsivamente tutti i device da lsblk JSON (gestisce 'children')."""
        out: list[dict] = []
        stack = list(blockdevices)
        while stack:
            dev = stack.pop()
            out.append(dev)
            children = dev.get("children")
            if isinstance(children, list):
                stack.extend(children)
        return out

    @staticmethod
    def _find_device() -> str | None:
        """Cerca in ordine: 1) SD SPI (mmcblk1+), 2) USB su microUSB (sdX).
        Ritorna il path del device (partizione se presente, altrimenti disk)."""
        try:
            result = subprocess.run(
                ["lsblk", "--json", "--output", "PATH,TYPE"],
                check=True,
                capture_output=True,
                text=True,
            )
            devices = json.loads(result.stdout)["blockdevices"]
        except (OSError, subprocess.CalledProcessError, json.JSONDecodeError, KeyError) as error:
            logger.warning("Cannot detect SD card: %s", error)
            return None

        all_devs = SdCard._collect_all_devices(devices)

        # 1) SD su SPI (mmcblk1+, esclude mmcblk0 che è la SD di sistema)
        for device in all_devs:
            path = device.get("path", "")
            name = Path(path).name
            if (
                device.get("type") == "part"
                and re.fullmatch(r"mmcblk[1-9]\d*p\d+", name)
            ):
                return path

        for device in all_devs:
            path = device.get("path", "")
            name = Path(path).name
            if device.get("type") == "disk" and re.fullmatch(r"mmcblk[1-9]\d*", name):
                return path

        # 2) Fallback USB su porta microUSB (sda, sdb, ...). Priorità a partizione.
        for device in all_devs:
            path = device.get("path", "")
            name = Path(path).name
            if device.get("type") == "part" and re.fullmatch(r"sd[a-z]+\d+", name):
                return path

        for device in all_devs:
            path = device.get("path", "")
            name = Path(path).name
            if device.get("type") == "disk" and re.fullmatch(r"sd[a-z]+", name):
                return path
        return None

    @staticmethod
    def _is_usb_device(path: str) -> bool:
        return bool(re.fullmatch(r"/dev/sd[a-z]+\d*", path))

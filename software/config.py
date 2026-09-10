import os
import json
import logging
from pathlib import Path
from dotenv import load_dotenv


CONFIG_FILE = Path(__file__).resolve().parent.parent / "config.json"
DEFAULT_FAKE_SD_PATH = "~/liquorice/fake-sd"
logger = logging.getLogger(__name__)


class Config:
    def __init__(self, bus=None):
        load_dotenv()

        self.webdav_hostname = os.getenv("WEBDAV_HOSTNAME")
        self.webdav_folder = os.getenv("WEBDAV_FOLDER")
        self.webdav_login = os.getenv("WEBDAV_LOGIN")
        self.webdav_password = os.getenv("WEBDAV_PASSWORD")
        self.wifi_ap_ssid = os.getenv("WIFI_AP_SSID", "Liquorice")
        self.wifi_ap_password = os.getenv("WIFI_AP_PASSWORD")
        self.wifi_interface = os.getenv("WIFI_INTERFACE", "wlan0")

        with open(CONFIG_FILE, "r") as f:
            self.__dict__.update(json.load(f))

        # I percorsi con ~ vanno espansi sulla home dell'utente corrente.
        for key in ("cache_path", "db_path", "log_path", "sd_src", "rclone_config"):
            value = getattr(self, key, None)
            if isinstance(value, str) and value.startswith("~"):
                setattr(self, key, os.path.expanduser(value))

        if getattr(self, "operation_mode", None) not in ("auto", "manual"):
            self.operation_mode = "manual"

        # sd_mount=False salta lsblk/mount e tratta sd_src come cartella locale.
        self.sd_mount = (
            True if getattr(self, "sd_mount", None) is None else bool(self.sd_mount)
        )

        # fake_sd=True (voce "Debug" del menu): le foto arrivano da una cartella
        # locale invece della SD su SPI. sd_src/sd_mount reali restano memorizzati
        # per poter tornare alla SD vera senza riavviare.
        self.sd_src_real = getattr(self, "sd_src", None)
        self.sd_mount_real = self.sd_mount
        self.fake_sd_path = os.path.expanduser(
            getattr(self, "fake_sd_path", None) or DEFAULT_FAKE_SD_PATH
        )
        self.fake_sd = bool(getattr(self, "fake_sd", False))
        self._apply_fake_sd()

        # Il remoto rclone puo' arrivare dal .env se config.json non lo definisce.
        if not getattr(self, "rclone_remote", ""):
            self.rclone_remote = os.getenv("RCLONE_REMOTE", "")
        if not getattr(self, "rclone_config", ""):
            self.rclone_config = os.getenv("RCLONE_CONFIG_FILE", "")

        if bus:
            bus.on("config:set", self._on_config_set)

    def get(self, key, default=None):
        return getattr(self, key, default)

    def _apply_fake_sd(self) -> None:
        # Sorgente effettiva: cartella fake (nessun mount) oppure SD reale.
        if self.fake_sd:
            try:
                Path(self.fake_sd_path).mkdir(parents=True, exist_ok=True)
            except OSError as e:
                logger.warning("Cannot create fake SD dir %s: %s", self.fake_sd_path, e)
            self.sd_src = self.fake_sd_path
            self.sd_mount = False
        elif self.sd_src_real is not None:
            self.sd_src = self.sd_src_real
            self.sd_mount = self.sd_mount_real

    def __setitem__(self, key, value):
        setattr(self, key, value)

    def _on_config_set(self, key, value, **kw):
        if key == "operation_mode" and value not in ("auto", "manual"):
            logger.warning("Invalid operation_mode %r, ignored", value)
            return
        if key == "sd_mount" and not isinstance(value, bool):
            logger.warning("Invalid sd_mount %r, expected bool", value)
            return
        if key == "fake_sd" and not isinstance(value, bool):
            logger.warning("Invalid fake_sd %r, expected bool", value)
            return
        try:
            with open(CONFIG_FILE) as f:
                cfg = json.load(f)
            cfg[key] = value
            with open(CONFIG_FILE, "w") as f:
                json.dump(cfg, f, indent=4)
            setattr(self, key, value)
            logger.info("Config %s = %s (saved)", key, value)
        except Exception as e:
            logger.warning("Failed to save config %s: %s", key, e)
            return

        # Le chiavi della sorgente vanno ricomposte: sd_src/sd_mount sono derivate.
        if key in ("fake_sd", "fake_sd_path", "sd_src", "sd_mount"):
            if key == "sd_src":
                self.sd_src_real = os.path.expanduser(value) if isinstance(value, str) else value
            elif key == "sd_mount":
                self.sd_mount_real = bool(value)
            elif key == "fake_sd_path":
                self.fake_sd_path = os.path.expanduser(value or DEFAULT_FAKE_SD_PATH)
            self._apply_fake_sd()

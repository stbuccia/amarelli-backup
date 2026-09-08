import os
import json
import logging
from pathlib import Path
from dotenv import load_dotenv


CONFIG_FILE = Path(__file__).resolve().parent.parent / "config.json"
logger = logging.getLogger(__name__)


class Config:
    def __init__(self, bus=None):

        load_dotenv()

        # Variabili d'ambiente
        self.webdav_hostname = os.getenv("WEBDAV_HOSTNAME")
        self.webdav_folder = os.getenv("WEBDAV_FOLDER")
        self.webdav_login = os.getenv("WEBDAV_LOGIN")
        self.webdav_password = os.getenv("WEBDAV_PASSWORD")
        self.wifi_ap_ssid = os.getenv("WIFI_AP_SSID", "Amarelli")
        self.wifi_ap_password = os.getenv("WIFI_AP_PASSWORD")
        self.wifi_interface = os.getenv("WIFI_INTERFACE", "wlan0")

        # config.json
        with open(CONFIG_FILE, "r") as f:
            config = json.load(f)

        self.__dict__.update(config)

        # operation_mode: auto = mounting/caching/uploading automatici (headless LED), manual = passo-passo su conferma
        if getattr(self, "operation_mode", None) not in ("auto", "manual"):
            self.operation_mode = "manual"

        # sd_mount: se False salta lsblk/mount e tratta sd_src come cartella locale (utile per test con fake SD)
        if getattr(self, "sd_mount", None) is None:
            self.sd_mount = True
        else:
            self.sd_mount = bool(self.sd_mount)

        # Il remoto rclone puo' stare nel .env: usato solo se config.json
        # non lo definisce (o lo lascia vuoto).
        if not getattr(self, "rclone_remote", ""):
            self.rclone_remote = os.getenv("RCLONE_REMOTE", "")
        if not getattr(self, "rclone_config", ""):
            self.rclone_config = os.getenv("RCLONE_CONFIG_FILE", "")

        if bus:
            bus.on("config:set", self._on_config_set)

    def get(self, key, default=None):
        return getattr(self, key, default)

    def __setitem__(self, key, value):
        setattr(self, key, value)

    def _on_config_set(self, key, value, **kw):
        if key == "operation_mode" and value not in ("auto", "manual"):
            logger.warning("Invalid operation_mode %r, ignored", value)
            return
        if key == "sd_mount" and not isinstance(value, bool):
            logger.warning("Invalid sd_mount %r, expected bool", value)
            return
        try:
            with open(CONFIG_FILE) as _f:
                _cfg = json.load(_f)
            _cfg[key] = value
            with open(CONFIG_FILE, "w") as _f:
                json.dump(_cfg, _f, indent=4)
            setattr(self, key, value)
            logger.info("Config %s = %s (saved)", key, value)
        except Exception as _e:
            logger.warning("Failed to save config %s: %s", key, _e)

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

        if bus:
            bus.on("config:set", self._on_config_set)

    def _on_config_set(self, key, value, **kw):
        try:
            with open(CONFIG_FILE) as _f:
                _cfg = json.load(_f)
            _cfg[key] = value
            with open(CONFIG_FILE, "w") as _f:
                json.dump(_cfg, _f, indent=4)
            logger.info("Config %s = %s (saved)", key, value)
        except Exception as _e:
            logger.warning("Failed to save config %s: %s", key, _e)

import os
import json
from dotenv import load_dotenv


CONFIG_FILE = "config.json"


class Config:
    def __init__(self):

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

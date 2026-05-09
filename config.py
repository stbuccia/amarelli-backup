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

        # config.json
        with open(CONFIG_FILE, "r") as f:
            config = json.load(f)

        self.__dict__.update(config)

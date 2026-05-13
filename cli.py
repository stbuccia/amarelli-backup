import sys
import argparse
import logging

from webdav_uploader import WebDav
from config import Config
from database import Database
from cache import Cache
from log import setup_logger
from wifi import WiFiManager
from flask_app import create_app


def main():
    parser = argparse.ArgumentParser(
        prog="amarelli",
        description="This program performs a backup for files located in SD card uploading them in a WebDav Server",
    )
    subparsers = parser.add_subparsers(dest="cmd")

    backup_parser = subparsers.add_parser("backup", help="Backup files")
    backup_subparsers = backup_parser.add_subparsers(dest="subcmd")

    backup_subparsers.add_parser("cache", help="Copy files from SD to local cache")
    backup_subparsers.add_parser("upload", help="Upload cached files to WebDav server")
    backup_subparsers.add_parser("prune", help="Remove uploaded files from local cache")

    wifi_parser = subparsers.add_parser("wifi", help="WiFi management")
    wifi_subparsers = wifi_parser.add_subparsers(dest="subcmd")
    wifi_subparsers.add_parser("start_ap", help="Start WiFi access point")
    wifi_subparsers.add_parser("stop_ap", help="Stop WiFi access point")

    args = parser.parse_args()

    config = Config()
    setup_logger(config)

    log = logging.getLogger(__name__)
    if args.cmd == "wifi":
        wm = WiFiManager(config)
        if args.subcmd == "start_ap":
            ssid = config.wifi_ap_ssid
            password = config.wifi_ap_password
            if not password:
                log.error("WIFI_AP_PASSWORD not configured")
                return 1
            wm.start_ap(ssid, password)
            log.info("Access point '%s' started", ssid)
            create_app().run(host="0.0.0.0")
        elif args.subcmd == "stop_ap":
            wm.stop_ap()
            log.info("Access point stopped")
        return 0

    if args.cmd != "backup":
        parser.print_help()
        return 1

    db = Database()
    cache = Cache(config, db)
    webdav = WebDav(config, db)

    subcmd = args.subcmd or "all"

    if subcmd in ("cache", "all"):
        cache.copy()
    if subcmd in ("upload", "all"):
        webdav.upload()
    if subcmd in ("prune", "all"):
        cache.prune()

    return 0


if __name__ == "__main__":
    sys.exit(main())

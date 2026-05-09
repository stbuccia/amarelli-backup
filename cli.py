import sys
import argparse
import logging

from webdav_uploader import WebDav
from config import Config
from database import Database
from cache import Cache
from log import setup_logger


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

    args = parser.parse_args()

    if args.cmd != "backup":
        parser.print_help()
        return 1

    config = Config()
    setup_logger(config)
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

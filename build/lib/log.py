import logging


LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s :: %(message)s"


def setup_logger(cfg):
    formatter = logging.Formatter(LOG_FORMAT)

    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(formatter)

    file_handler = logging.FileHandler(cfg.log_path)
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    root.handlers.clear()
    root.addHandler(console)
    root.addHandler(file_handler)

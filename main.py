#!/usr/bin/env python3
import sys
import os
import argparse
import logging
import time
import subprocess
import json

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

parser = argparse.ArgumentParser(
    description="Amarelli photo backup device - interactive UI"
)
parser.add_argument(
    "--mock", action="store_true", help="Use mock EPD (software rendering, no hardware)"
)
args = parser.parse_args()

picdir = os.path.join(
    os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "pic"
)
libdir = os.path.join(
    os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "lib"
)
if os.path.exists(libdir):
    sys.path.append(libdir)

if args.mock:
    from waveshare_epd.mock_epd import MockEPD as EPD
else:
    from waveshare_epd import epd2in13_V4

    EPD = epd2in13_V4.EPD


import threading

from display import (
    StatusBar,
    Legend,
    BackupStatusView,
    MenuView,
    Display,
    load_font,
    setup_ui_handlers,
)
from menu import Menu
from keylistener import TerminalKeyListener, GpioKeyListener
from eventbus import bus
from config import Config
from database import Database
from cache import Cache
from webdav_uploader import WebDav
from log import setup_logger
from backup import Backup, State
from wifi import WiFiManager
from flask_app import create_app


def get_ip_address() -> str:
    try:
        result = subprocess.run(
            ["hostname", "-I"], capture_output=True, text=True, timeout=5
        )
        ip = result.stdout.strip().split()[0]
        return ip if ip else "N/A"
    except Exception:
        return "N/A"


def run_interactive(epd):
    font = load_font(14)
    display = Display(epd, font)
    display.init()

    config = Config(bus=bus)
    setup_logger(config)

    db = Database()
    cache_obj = None
    webdav = None
    try:
        cache_obj = Cache(config, db, bus)
        webdav = WebDav(config, db, bus)
    except Exception as e:
        logger.warning("Cache/WebDav init skipped: %s", e)

    wf = Backup(cache_obj, webdav, db, bus)

    sb = StatusBar()
    legend = Legend()
    with open("config.json") as f:
        menu_cfg = json.load(f)
    menu = Menu(config=menu_cfg, bus=bus)
    menu_view = MenuView(menu, bus=bus)
    status_view = BackupStatusView(db, bus=bus)
    status_view.refresh()

    keys = TerminalKeyListener() if args.mock else GpioKeyListener(pins=(19, 20, 5, 6))

    _loop(
        display,
        menu,
        menu_view,
        status_view,
        sb,
        legend,
        keys,
        backup=wf,
        bus=bus,
        mock=args.mock,
    )

    keys.cleanup()
    display.init_full()
    display.sleep()


def _handle_mock_keys(ch, sb, display, current_view, legend):
    if ch == "b":
        sb.set_battery(sb._battery - 10)
        logger.info("Battery: %d%%", sb._battery)
        display.render_full(current_view, sb, legend)
        return True
    if ch == "B":
        sb.set_battery(sb._battery + 10)
        logger.info("Battery: %d%%", sb._battery)
        display.render_full(current_view, sb, legend)
        return True
    if ch == "i":
        sb.set_wifi(not sb._wifi)
        logger.info("WiFi: %s", "connected" if sb._wifi else "disconnected")
        display.render_full(current_view, sb, legend)
        return True
    if ch == "t":
        titles = ["Amarelli", "Settings", "Photos", "System"]
        curr = titles.index(sb._title) if sb._title in titles else -1
        sb.set_title(titles[(curr + 1) % len(titles)])
        logger.info("Title: %s", sb._title)
        display.render_full(current_view, sb, legend)
        return True
    return False


def _loop(
    display, menu, menu_view, status_view, sb, legend, keys, backup, bus, mock=False
):
    redraw_pending = False
    last_refresh = 0.0

    def request_redraw():
        nonlocal redraw_pending
        if mock:
            if active_view[0] is status_view:
                print(
                    f"[DISPLAY] {sb._title} | {status_view.status}  cached:{status_view.cached_count} pend:{status_view.pending_upload} up:{status_view.uploaded_count}  bar:{status_view.progress_current}/{status_view.progress_total}"
                )
            elif active_view[0] is menu_view:
                print(f"[DISPLAY] {sb._title} | MENU: {menu.current_label}")
            display.render_full(active_view[0], sb, legend)
        else:
            redraw_pending = True

    active_view = setup_ui_handlers(
        bus, display, sb, legend, menu, status_view, menu_view, request_redraw
    )

    # --- Key routing ---
    def on_key_press(key, **kw):
        if active_view[0] is status_view:
            if key in ("LEFT", "a"):
                bus.emit("menu:opened")
            else:
                backup.handle_key_event(key)
        elif active_view[0] is menu_view:
            menu.handle_key_event(key)

    bus.on("key:press", on_key_press)

    # --- Initial overview display ---
    sb.set_title("Amarelli")
    legend.set_text("\u25b6 backup  \u25c0 menu  Q quit")
    status_view.refresh()
    display.render_full(active_view[0], sb, legend)

    # --- Stato gestione WiFi/AP/Flask ---
    wifi_manager = None
    flask_thread = None

    def start_hotspot(**kw):
        nonlocal wifi_manager, flask_thread
        logger.info("[MENU] Avvio AP + Flask...")

        wifi_manager = WiFiManager(config)
        try:
            ssid = config.wifi_ap_ssid
            password = config.wifi_ap_password
            if not password:
                logger.warning("WIFI_AP_PASSWORD non impostata nel .env")
                legend.set_text("NO AP PASSWORD!")
                display.render_full(active_view[0], sb, legend)
                return
            wifi_manager.start_ap(ssid, password)
            sb.set_wifi(True)
            sb.set_title(f"AP: {ssid}")
            legend.set_text(f"IP: {WiFiManager.AP_IP}:5000")
            display.render_full(active_view[0], sb, legend)
            logger.info("AP '%s' avviato su %s", ssid, wifi_manager.AP_IP)
        except Exception as e:
            logger.error("Errore avvio AP: %s", e)
            legend.set_text("AP error!")
            display.render_full(active_view[0], sb, legend)
            return

        if flask_thread is None or not flask_thread.is_alive():
            app = create_app(wifi_manager=wifi_manager, db=db)
            flask_thread = threading.Thread(
                target=app.run,
                kwargs={"host": "0.0.0.0", "port": 5000, "debug": False, "use_reloader": False},
                daemon=True,
            )
            flask_thread.start()
            logger.info("Flask avviato su 0.0.0.0:5000")

    bus.on("hotspot:start", start_hotspot)
    bus.on("wifi:connect", lambda **kw: start_hotspot())

    def show_ip(**kw):
        ip = get_ip_address()
        logger.info("[MENU] IP: %s", ip)
        sb.set_title(f"IP: {ip}")
        legend.set_text("\u25c0 back")
        display.render_full(active_view[0], sb, legend)

    bus.on("wifi:show_ip", show_ip)

    def stop_hotspot(**kw):
        nonlocal wifi_manager, flask_thread
        logger.info("[MENU] Arresto AP...")
        if wifi_manager:
            try:
                wifi_manager.stop_ap()
            except Exception as e:
                logger.error("Errore arresto AP: %s", e)
        sb.set_wifi(False)
        sb.set_title("Amarelli")
        legend.set_text("\u25b6 backup  \u25c0 menu  Q quit")
        display.render_full(active_view[0], sb, legend)

    bus.on("wifi:reset", stop_hotspot)
    bus.on("system:shutdown", lambda **kw: logger.info("[MENU] Shutdown..."))
    bus.on("system:reboot", lambda **kw: logger.info("[MENU] Reboot..."))

    def on_system_status(**kw):
        status_view.refresh()
        request_redraw()
        logger.info("[MENU] Stato sistema aggiornato")

    bus.on("system:status", on_system_status)

    print("Amarelli interactive. \u25b6 action, \u25c0 back, Q quit.")
    if mock:
        print("          b B battery  i wifi  t title  (mock)")

    while True:
        if redraw_pending:
            redraw_pending = False
            if mock:
                if active_view[0] is status_view:
                    print(
                        f"[DISPLAY] {sb._title} | {status_view.status}  cached:{status_view.cached_count} pend:{status_view.pending_upload} up:{status_view.uploaded_count}"
                    )
                elif active_view[0] is menu_view:
                    print(f"[DISPLAY] {sb._title} | MENU: {menu.current_label}")
            display.render_full(active_view[0], sb, legend)

        ch = keys.get_key()
        if ch is None:
            time.sleep(0.05)
            continue
        if ch in ("q", "Q"):
            print("Exit.")
            break
        if mock and _handle_mock_keys(ch, sb, display, active_view[0], legend):
            continue
        bus.emit("key:press", key=ch)

        now = time.time()
        if backup.is_active and now - last_refresh > 1.0:
            status_view.refresh()
            request_redraw()
            last_refresh = now


def main():
    epd = EPD()
    run_interactive(epd)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Interrupted")
    except IOError as e:
        logger.info(e)

#!/usr/bin/env python3
import sys
import os
import argparse
import logging
import time
import subprocess
from pathlib import Path

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
ASSETS_DIR = PROJECT_ROOT / "assets" / "images"

parser = argparse.ArgumentParser(
    description="Amarelli photo backup device - interactive UI"
)
parser.add_argument(
    "--mock", action="store_true", help="Use mock EPD (software rendering, no hardware)"
)
parser.add_argument(
    "--imagick", action="store_true", help="Use ImageMagick display for live preview"
)
args = parser.parse_args()

if args.mock:
    class EPD:
        """Software-only EPD implementation used by the interactive mock."""

        width = 122
        height = 250

        def init(self):
            pass

        def init_fast(self):
            pass

        def Clear(self, color):
            pass

        def getbuffer(self, image):
            return image

        def display(self, image):
            pass

        def display_fast(self, image):
            pass

        def sleep(self):
            pass
else:
    from waveshare_epd import epd2in13_V4, epdconfig

    EPD = epd2in13_V4.EPD


import threading

from display import (
    StatusBar,
    Legend,
    BackupStatusView,
    MenuView,
    LockView,
    Display,
    load_font,
    setup_ui_handlers,
)
from menu import Menu
from keylistener import TerminalKeyListener, GpioKeyListener, ReedSwitch
from eventbus import bus
from config import Config
from database import Database
from cache import Cache
from sdcard import SdCard
from uploader import create_uploader
from log import setup_logger
from backup import Backup, State
from wifi import WiFiManager
from flask_app import create_app
from led_status import LedStatus


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
    snapshot_path = str(ASSETS_DIR / "display_output.png") if args.imagick else None
    spi_lock = threading.Lock()
    display = Display(epd, font, snapshot_path=snapshot_path, io_lock=spi_lock)
    display.init()

    boot_view = BackupStatusView()
    boot_view.status = "Starting..."
    display.render_full(boot_view, StatusBar(), Legend("Initializing..."))

    led = LedStatus(bus=bus, mock=False)

    config = Config(bus=bus)
    setup_logger(config)
    logger.info(
        "Config: mock=%s sd_src=%s cache=%s db=%s log=%s uploader=%s remote=%s cloud_dst=%s mode=%s filter=%s",
        args.mock,
        config.sd_src,
        config.cache_path,
        config.db_path,
        config.log_path,
        getattr(config, "uploader", "?"),
        getattr(config, "rclone_remote", ""),
        getattr(config, "cloud_dst", ""),
        getattr(config, "mode", ""),
        getattr(config, "file_filter", ""),
    )

    db = Database(Path(config.db_path))
    cache_obj = None
    uploader = None
    try:
        uploader = create_uploader(config, db, bus)
        logger.info("Upload backend: %s", uploader.name)
    except Exception as e:
        logger.warning("Uploader init skipped: %s", e)

    wf = Backup(cache_obj, uploader, db, bus, mode=getattr(config, 'mode', 'upload'))
    sd_card = SdCard(config.sd_src, mock=args.mock, mount_enabled=getattr(config, "sd_mount", True))

    def on_uploader_config_changed(key, value, **kw):
        if key not in ("uploader", "rclone_remote"):
            return
        try:
            wf.set_uploader(create_uploader(config, db, bus))
            logger.info("Upload backend set to %s", getattr(config, "uploader", "webdav"))
        except Exception as error:
            logger.warning("Cannot switch upload backend: %s", error)

    bus.on("config:set", on_uploader_config_changed)

    sb = StatusBar()
    legend = Legend()
    menu = Menu(config=config, bus=bus)
    menu_view = MenuView(menu, bus=bus)
    status_view = BackupStatusView(db, bus=bus)
    status_view.refresh()

    sd_available = None

    def sync_sd_card():
        nonlocal cache_obj, sd_available
        mode = getattr(config, "operation_mode", "manual")
        # In auto montiamo subito, in manuale distinguiamo presente (device) vs montata (cache pronta)
        if mode == "auto":
            cache_available = sd_card.try_mount()
            ui_available = cache_available
        else:
            present = sd_card.is_present()
            mounted = sd_card.is_available()
            ui_available = present
            cache_available = mounted
        if cache_available and cache_obj is None:
            try:
                cache_obj = Cache(config, db, bus, io_lock=spi_lock)
                wf.set_cache(cache_obj)
                logger.info("Cache ready: src=%s dst=%s", config.sd_src, config.cache_path)
            except Exception as error:
                logger.warning("SD card is mounted but cannot be read: %s", error)
                cache_available = False
        elif not cache_available and cache_obj is not None:
            cache_obj = None
            wf.set_cache(None)

        if ui_available != sd_available:
            sd_available = ui_available
            if ui_available:
                logger.info("SD card available at %s", config.sd_src)
            else:
                hint = ""
                if args.mock and not Path(config.sd_src).is_dir():
                    hint = f" (hint: mock expects sd_src dir to exist, got {config.sd_src})"
                logger.info("SD card not available%s", hint)
            bus.emit("sd:changed", available=ui_available)
            # auto: da COMPLETED/ERROR torna IDLE su rimozione SD per permettere nuovo ciclo su reinserimento
            if getattr(config, "operation_mode", "manual") == "auto" and wf.state in (State.COMPLETED, State.ERROR) and not ui_available:
                logger.info("Auto: SD removed in %s, returning to IDLE", wf.state.name)
                wf.stop()

        # auto headless: avvia backup appena SD pronta o pending da uploadare (anche senza SD)
        if getattr(config, "operation_mode", "manual") == "auto" and wf.state == State.IDLE:
            try:
                pending = db.count_pending_uploads()
            except Exception:
                pending = 0
            if ui_available or pending > 0:
                logger.info("Auto-start backup (mode=auto available=%s pending=%s)", ui_available, pending)
                wf.start()

    def ensure_cache_on_demand() -> bool:
        """Manual: tenta mount + Cache init al Confirm. Ritorna True se backup può partire (pending o cache).
        Se la USB/SD è stata inserita dopo l'avvio, tenta sempre il mount prima di decidere."""
        nonlocal cache_obj
        # Tenta mount in ogni caso: se la chiavetta USB è stata appena inserita, va rilevata
        mount_ok = sd_card.try_mount()
        if mount_ok and cache_obj is None:
            try:
                cache_obj = Cache(config, db, bus, io_lock=spi_lock)
                wf.set_cache(cache_obj)
                logger.info("Cache ready (on-demand): src=%s dst=%s", config.sd_src, config.cache_path)
                bus.emit("sd:changed", available=True)
            except Exception as e:
                logger.warning("On-demand SD mount ok but Cache init failed: %s", e)
                bus.emit("sd:changed", available=False)
                # non fallire se c'è pending da uploadare
                try:
                    pending = db.count_pending_uploads()
                except Exception:
                    pending = 0
                return pending > 0
        elif mount_ok:
            bus.emit("sd:changed", available=True)
        else:
            bus.emit("sd:changed", available=False)

        try:
            pending = db.count_pending_uploads()
        except Exception:
            pending = 0
        # Può partire se c'è cache (appena montata) o se c'è pending da uploadare
        if mount_ok or pending > 0:
            return True
        logger.info("On-demand mount failed: no SD available")
        return False

    sync_sd_card()

    keys = TerminalKeyListener() if args.mock else GpioKeyListener(pins=(13, 6, 5, 19))
    reed = ReedSwitch(pin=16, enabled=not args.mock)
    if reed.is_closed:
        display.suspend()

    try:
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
            config=config,
            db=db,
            mock=args.mock,
            imagick=args.imagick,
            sync_sd_card=sync_sd_card,
            ensure_cache_on_demand=ensure_cache_on_demand,
            reed=reed,
        )
    finally:
        try:
            led.cleanup()
        except Exception:
            pass
        sd_card.close()
        reed.cleanup()
        keys.cleanup()
        display.init_full()
        display.sleep()


def _handle_mock_keys(ch, sb, display, current_view, legend):
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
    display, menu, menu_view, status_view, sb, legend, keys, backup, bus, config=None, db=None, mock=False, imagick=False,
    sync_sd_card=None,
    ensure_cache_on_demand=None,
    reed=None,
):
    redraw_pending = False
    last_refresh = 0.0
    last_sd_check = 0.0

    def request_redraw():
        nonlocal redraw_pending
        if mock:
            display.render_full(active_view[0], sb, legend)
        else:
            redraw_pending = True

    active_view = setup_ui_handlers(
        bus, display, sb, legend, menu, status_view, menu_view, request_redraw
    )

    def _mock_dump():
        if not mock:
            return
        leg = legend._text
        title = sb._title
        wifi_s = "ON" if getattr(sb, "_wifi", True) else "OFF"
        if active_view[0] is status_view:
            bv = status_view
            state_name = getattr(getattr(backup, "state", None), "name", "?")
            sd_s = "?" if bv._sd_available is None else ("ON" if bv._sd_available else "OFF")
            bar = f" bar:{bv.progress_current}/{bv.progress_total}" if bv.progress_total else ""
            cur = f" file:{bv.current_file}" if bv.current_file and bv.status == "Caching files..." else ""
            stats = getattr(bv, "_stats", None)
            if stats:
                stats_s = f" | stats cached:{stats.get('cached_ok',0)}/{stats.get('cached_failed',0)} up:{stats.get('uploaded_ok',0)}/{stats.get('uploaded_failed',0)} rm:{stats.get('remote_deleted',0)} pr:{stats.get('pruned',0)}"
                if stats.get("up_to_date"):
                    stats_s += " up_to_date"
            else:
                stats_s = ""
            err_s = f" err:{bv._error_msg}" if getattr(bv, "_error_msg", "") else ""
            print(
                f"[DISPLAY] BACKUP | {title} | {bv.status} ({state_name}) | wifi:{wifi_s} sd:{sd_s} | cached:{bv.cached_count} pend:{bv.pending_upload} up:{bv.uploaded_count}{bar}{cur}{stats_s}{err_s} | legend:{leg}"
            )
        elif active_view[0] is menu_view:
            sel = menu.current_label
            idx = menu._selected
            total = len(menu._items)
            items_preview = " | ".join(
                f"{'>' if i == idx else ' '}{it.label}" for i, it in enumerate(menu._items)
            )
            print(
                f"[DISPLAY] MENU | {title} | sel:{sel} ({idx+1}/{total}) | wifi:{wifi_s} | legend:{leg} | {items_preview}"
            )
        else:
            print(f"[DISPLAY] {title} | legend:{leg}")

    _orig_render_full = display.render_full

    def _wrapped_render_full(content_view, status_bar, legend_obj):
        _orig_render_full(content_view, status_bar, legend_obj)
        _mock_dump()

    if mock:
        display.render_full = _wrapped_render_full

    # --- Key routing ---
    def on_key_press(key, **kw):
        logger.info("Key pressed: %s state=%s active=%s view=%s", key, backup.state.name, backup.is_active, "status" if active_view[0] is status_view else "menu")
        if active_view[0] is status_view:
            # Operazioni lunghe: qualsiasi tasto laterale mette in pausa e ferma blink
            if backup.is_active and key in ("LEFT", "RIGHT", "UP", "DOWN", "a", "d"):
                # LEFT/RIGHT/UP/DOWN tutti mettono in pausa per tollerare cablaggi diversi (pin 29/35/38 vs 13/6/5/19)
                if backup.pause():
                    logger.info("Pause requested via %s", key)
                    return
                # se pause non riuscito (es. già in pausa), non aprire menu
                return
            # Pausa: status "Paused", LED fisso arancione, RIGHT resume, LEFT apre menu
            if backup.state == State.PAUSED:
                if key in ("RIGHT", "d", "\r", "\n"):
                    backup.resume()
                    return
                if key in ("LEFT", "a", "UP", "DOWN"):
                    bus.emit("menu:opened")
                    return
                return
            if key in ("LEFT", "a"):
                bus.emit("menu:opened")
            else:
                # manual: su Confirm ritenta mount on-demand se non c'è cache e non c'è pending
                if (
                    getattr(config, "operation_mode", "manual") == "manual"
                    and backup.state == State.IDLE
                    and key in ("RIGHT", "d", "\r", "\n")
                    and ensure_cache_on_demand is not None
                ):
                    pending = 0
                    try:
                        pending = db.count_pending_uploads() if db else 0
                    except Exception:
                        pass
                    if pending == 0:
                        ok = ensure_cache_on_demand()
                        if not ok:
                            sb.set_title("Amarelli")
                            # status_view già aggiornata via sd:changed
                            legend.set_text("\u25c0 menu  \u25b6 backup")
                            bus.emit("ui:redraw")
                            return
                backup.handle_key_event(key)
        elif active_view[0] is menu_view:
            menu.handle_key_event(key)

    bus.on("key:press", on_key_press)

    # --- Initial overview display ---
    sb.set_title("Amarelli")
    legend.set_text("\u25c0 menu  \u25b6 backup")
    status_view.refresh()
    display.render_full(active_view[0], sb, legend)

    # --- Stato gestione WiFi/AP/Flask ---
    wifi_manager = None
    flask_thread = None

    def _start_flask(wm=None):
        nonlocal flask_thread
        if flask_thread is not None and flask_thread.is_alive():
            logger.info("Flask already running")
            return
        app = create_app(wifi_manager=wm, db=db, bus=bus)
        flask_thread = threading.Thread(
            target=app.run,
            kwargs={"host": "0.0.0.0", "port": 5000, "debug": False, "use_reloader": False},
            daemon=True,
        )
        flask_thread.start()
        logger.info("Flask avviato su 0.0.0.0:5000")

    def start_hotspot(**kw):
        nonlocal wifi_manager, flask_thread
        logger.info("[MENU] Starting AP + Flask...")

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
            logger.info("AP '%s' started on %s", ssid, wifi_manager.AP_IP)
        except Exception as e:
            logger.error("Error starting AP: %s", e)
            legend.set_text("AP error!")
            display.render_full(active_view[0], sb, legend)
            return

        _start_flask(wifi_manager)

    bus.on("hotspot:start", start_hotspot)
    bus.on("wifi:connect", lambda **kw: start_hotspot())

    def start_web_server(**kw):
        nonlocal wifi_manager
        logger.info("[MENU] Starting web server...")
        wifi_manager = WiFiManager(config)
        _start_flask(wifi_manager)
        ip = get_ip_address()
        sb.set_title(f"Server: {ip}:5000")
        legend.set_text("\u25c0 back")
        display.render_full(active_view[0], sb, legend)

    bus.on("server:start", start_web_server)

    def show_ip(**kw):
        ip = get_ip_address()
        logger.info("[MENU] IP: %s", ip)
        sb.set_title(f"IP: {ip}")
        legend.set_text("\u25c0 back")
        display.render_full(active_view[0], sb, legend)

    bus.on("wifi:show_ip", show_ip)

    def stop_hotspot(**kw):
        nonlocal wifi_manager, flask_thread
        logger.info("[MENU] Stopping AP...")
        if wifi_manager:
            try:
                wifi_manager.stop_ap()
            except Exception as e:
                logger.error("Error stopping AP: %s", e)
        sb.set_wifi(False)
        sb.set_title("Amarelli")
        legend.set_text("\u25c0 menu  \u25b6 backup")
        display.render_full(active_view[0], sb, legend)

    bus.on("wifi:reset", stop_hotspot)
    _imagick_proc = None
    if imagick:
        try:
            _imagick_proc = subprocess.Popen(
                ["display", "-update", "1", str(ASSETS_DIR / "display_output.png")]
            )
            print(f"[imagick] ImageMagick display started (pid {_imagick_proc.pid})")
        except FileNotFoundError:
            print("[imagick] 'display' not found. Install ImageMagick.")

    print("Amarelli interactive. \u25c0 back, \u25b6 action")
    if mock:
        print("          i wifi  t title  (mock)")

    while True:
        if reed is not None:
            reed_closed = reed.get_state_change()
            if reed_closed is True:
                logger.info("Coperchio chiuso")
                # Mostra schermata di blocco dedicata prima di sospendere
                lock_view = LockView()
                # usa legend dedicata per il blocco
                display.render_full(lock_view, sb, Legend("Coperchio chiuso"))
                display.suspend()
            elif reed_closed is False:
                logger.info("Coperchio aperto")
                display.resume()
                # Ripristina vista corrente con refresh completo
                display.render_full(active_view[0], sb, legend)

        now = time.monotonic()
        poll_interval = 0.25 if getattr(config, "operation_mode", "manual") == "auto" else 1.0
        if sync_sd_card is not None and now - last_sd_check >= poll_interval:
            sync_sd_card()
            last_sd_check = now

        if redraw_pending:
            redraw_pending = False
            display.render_full(active_view[0], sb, legend)

        ch = keys.get_key()
        if ch is None:
            time.sleep(0.05)
            continue
        if ch in ("q", "Q"):
            print("Exit.")
            if _imagick_proc:
                _imagick_proc.terminate()
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
    if not args.mock:
        logger.info(
            "EPD driver=%s config=%s pins: RST=%s DC=%s BUSY=%s CS=%s",
            epd2in13_V4.__file__,
            epdconfig.__file__,
            epdconfig.RST_PIN,
            epdconfig.DC_PIN,
            epdconfig.BUSY_PIN,
            epdconfig.CS_PIN,
        )
    epd = EPD()
    run_interactive(epd)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Interrupted")
    except IOError as e:
        logger.info(e)

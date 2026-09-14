#!/usr/bin/env python3
import sys
import os
import argparse
import logging
import time
from pathlib import Path

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

parser = argparse.ArgumentParser(
    description="Liquorice photo backup device - interactive UI"
)
parser.add_argument(
    "--mock", action="store_true", help="Use mock EPD (software rendering, no hardware)"
)
args = parser.parse_args()

if args.mock:

    class EPD:
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
    install_busy_timeout,
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
from flask_app import create_app, get_ip_address
from led_status import LedStatus


def run_interactive(epd):
    font = load_font(11)
    spi_lock = threading.Lock()
    display = Display(epd, font, io_lock=spi_lock, health_check=not args.mock)
    display.init()

    boot_view = BackupStatusView()
    boot_view.status = "Starting..."
    display.render_full(boot_view, StatusBar(), Legend("Initializing..."))

    config = Config(bus=bus)
    setup_logger(config)
    if not args.mock:
        # Sicurezza al boot: se il profilo AP fosse rimasto su NetworkManager
        # da un arresto anomalo, va rimosso subito, prima che possa essere
        # scelto automaticamente al posto della rete Wi-Fi normale.
        try:
            WiFiManager(config).disable_ap_autostart()
        except Exception as e:
            logger.warning("Could not clear leftover AP profile at boot: %s", e)
    # LED creato dopo setup_logger: cosi' un eventuale "LED disabilitato"
    # (permessi /dev/mem) finisce in liquorice.log e non solo sullo stderr
    # del servizio.
    led = LedStatus(bus=bus, mock=False)
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

    wf = Backup(cache_obj, uploader, db, bus, mode=getattr(config, "mode", "upload"))
    sd_card = SdCard(
        config.sd_src, mock=args.mock, mount_enabled=getattr(config, "sd_mount", True)
    )

    def on_uploader_config_changed(key, value, **kw):
        if key not in ("uploader", "rclone_remote"):
            return
        try:
            wf.set_uploader(create_uploader(config, db, bus))
            logger.info(
                "Upload backend set to %s", getattr(config, "uploader", "webdav")
            )
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
        # auto: monta subito. manual: distingue "presente" (device) da "montata".
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
                logger.info(
                    "Cache ready: src=%s dst=%s", config.sd_src, config.cache_path
                )
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
            # auto: SD rimossa da COMPLETED/ERROR -> IDLE, pronto al reinserimento.
            if (
                getattr(config, "operation_mode", "manual") == "auto"
                and wf.state in (State.COMPLETED, State.ERROR)
                and not ui_available
            ):
                logger.info("Auto: SD removed in %s, returning to IDLE", wf.state.name)
                wf.stop()

        # auto headless: avvia appena c'e' SD pronta o pending da uploadare.
        if (
            getattr(config, "operation_mode", "manual") == "auto"
            and wf.state == State.IDLE
        ):
            try:
                pending = db.count_pending_uploads()
            except Exception:
                pending = 0
            if ui_available or pending > 0:
                logger.info(
                    "Auto-start backup (mode=auto available=%s pending=%s)",
                    ui_available,
                    pending,
                )
                wf.start()

    def ensure_cache_on_demand() -> bool:
        # Manual/Confirm: tenta mount + init Cache. True se il backup puo' partire
        # (cache appena montata o pending da uploadare). Ritenta sempre il mount
        # nel caso la SD sia stata inserita dopo l'avvio.
        nonlocal cache_obj
        mount_ok = sd_card.try_mount()
        if mount_ok and cache_obj is None:
            try:
                cache_obj = Cache(config, db, bus, io_lock=spi_lock)
                wf.set_cache(cache_obj)
                logger.info(
                    "Cache ready (on-demand): src=%s dst=%s",
                    config.sd_src,
                    config.cache_path,
                )
                bus.emit("sd:changed", available=True)
            except Exception as e:
                logger.warning("On-demand SD mount ok but Cache init failed: %s", e)
                bus.emit("sd:changed", available=False)
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
        if mount_ok or pending > 0:
            return True
        logger.info("On-demand mount failed: no SD available")
        return False

    def on_sd_config_changed(key, value, **kw):
        # Debug > Fake SD (o un cambio di percorso dal web): la sorgente cambia,
        # quindi si smonta l'eventuale SD, si ricrea SdCard e si invalida la Cache.
        if key not in ("fake_sd", "fake_sd_path", "sd_src", "sd_mount"):
            return
        nonlocal sd_card, cache_obj, sd_available
        try:
            sd_card.close()
        except Exception as error:
            logger.warning("Cannot release previous SD source: %s", error)
        sd_card = SdCard(
            config.sd_src,
            mock=args.mock,
            mount_enabled=getattr(config, "sd_mount", True),
        )
        cache_obj = None
        wf.set_cache(None)
        sd_available = None
        logger.info(
            "SD source changed: fake=%s src=%s mount=%s",
            getattr(config, "fake_sd", False),
            config.sd_src,
            getattr(config, "sd_mount", True),
        )
        sync_sd_card()

    bus.on("config:set", on_sd_config_changed)

    sync_sd_card()

    keys = (
        TerminalKeyListener()
        if args.mock
        # pins = (UP, DOWN, LEFT/BACK, RIGHT/CONFIRM)
        else GpioKeyListener(
            pins=(5, 6, 19, 13), display_busy=lambda: display.refreshing
        )
    )
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
        titles = ["Liquorice", "Settings", "Photos", "System"]
        curr = titles.index(sb._title) if sb._title in titles else -1
        sb.set_title(titles[(curr + 1) % len(titles)])
        logger.info("Title: %s", sb._title)
        display.render_full(current_view, sb, legend)
        return True
    return False


def _loop(
    display,
    menu,
    menu_view,
    status_view,
    sb,
    legend,
    keys,
    backup,
    bus,
    config=None,
    db=None,
    mock=False,
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
        ssid_s = getattr(sb, "_wifi_ssid", None)
        if wifi_s == "ON" and ssid_s:
            wifi_s = f"{wifi_s}({ssid_s})"
        if active_view[0] is status_view:
            bv = status_view
            state_name = getattr(getattr(backup, "state", None), "name", "?")
            sd_s = (
                "?"
                if bv._sd_available is None
                else ("ON" if bv._sd_available else "OFF")
            )
            bar = (
                f" bar:{bv.progress_current}/{bv.progress_total}"
                if bv.progress_total
                else ""
            )
            cur = (
                f" file:{bv.current_file}"
                if bv.current_file and bv.status == "Caching files..."
                else ""
            )
            stats = getattr(bv, "_stats", None)
            if stats:
                stats_s = f" | stats cached:{stats.get('cached_ok', 0)}/{stats.get('cached_failed', 0)} up:{stats.get('uploaded_ok', 0)}/{stats.get('uploaded_failed', 0)} rm:{stats.get('remote_deleted', 0)} pr:{stats.get('pruned', 0)}"
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
                f"{'>' if i == idx else ' '}{it.label}"
                for i, it in enumerate(menu._items)
            )
            print(
                f"[DISPLAY] MENU | {title} | sel:{sel} ({idx + 1}/{total}) | wifi:{wifi_s} | legend:{leg} | {items_preview}"
            )
        else:
            print(f"[DISPLAY] {title} | legend:{leg}")

    _orig_render_full = display.render_full

    def _wrapped_render_full(content_view, status_bar, legend_obj):
        _orig_render_full(content_view, status_bar, legend_obj)
        _mock_dump()

    if mock:
        display.render_full = _wrapped_render_full

    def on_key_press(key, **kw):
        logger.info(
            "Key pressed: %s state=%s active=%s view=%s",
            key,
            backup.state.name,
            backup.is_active,
            "status" if active_view[0] is status_view else "menu",
        )
        if active_view[0] is status_view:
            # Durante un'operazione, ogni tasto laterale mette in pausa (tollera
            # cablaggi diversi dei pin).
            if backup.is_active and key in ("LEFT", "RIGHT", "UP", "DOWN", "a", "d"):
                if backup.pause():
                    logger.info("Pause requested via %s", key)
                return
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
                # manual/Confirm: se non c'e' ne' cache ne' pending, ritenta il mount.
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
                            sb.set_title("Liquorice")
                            legend.set_text("\u25c0 menu  \u25b6 backup")
                            bus.emit("ui:redraw")
                            return
                backup.handle_key_event(key)
        elif active_view[0] is menu_view:
            menu.handle_key_event(key)

    bus.on("key:press", on_key_press)

    sb.set_title("Liquorice")
    legend.set_text("\u25c0 menu  \u25b6 backup")

    def _set_wifi_status(connected: bool, ssid: str | None = None) -> None:
        """Stato Wi-Fi su barra e schermata Status, col nome della rete."""
        sb.set_wifi(connected, ssid)
        for view in (status_view, active_view[0]):
            if hasattr(view, "_wifi"):
                view._wifi = connected
                if hasattr(view, "_wifi_ssid"):
                    view._wifi_ssid = sb._wifi_ssid

    # Rete al primo disegno: senza questo la schermata mostrava "Connected"
    # anche senza rete, e non diceva mai a quale rete.
    if not mock and config is not None:
        try:
            current_ssid = WiFiManager(config).get_current_ssid()
            _set_wifi_status(bool(current_ssid), current_ssid)
        except Exception as e:
            logger.debug("Cannot read current Wi-Fi network: %s", e)

    status_view.refresh()
    display.render_full(active_view[0], sb, legend)

    wifi_manager = None
    flask_thread = None
    flask_server = None
    wifi_task_lock = threading.Lock()
    wifi_task_running = None

    def _run_wifi_task(name, work, busy_text):
        """Esegue un'operazione di rete fuori dal ciclo principale.

        nmcli puo' prendersi diversi secondi (attivazione del profilo AP,
        riconnessione, scansione): eseguendola dentro l'handler del tasto, il
        ciclo principale non leggeva piu' i tasti ne' ridisegnava lo schermo,
        e il box sembrava piantato fino alla fine dell'operazione. Qui
        l'utente vede subito "Starting/Stopping AP..." e puo' continuare a
        navigare nel menu mentre il lavoro procede.
        """
        nonlocal wifi_task_running
        with wifi_task_lock:
            if wifi_task_running:
                logger.info(
                    "[MENU] %s ignored: '%s' still running", name, wifi_task_running
                )
                legend.set_text("WiFi busy...")
                bus.emit("ui:redraw")
                return
            wifi_task_running = name
        legend.set_text(busy_text)
        bus.emit("ui:redraw")

        def runner():
            nonlocal wifi_task_running
            try:
                work()
            except Exception as e:
                logger.exception("Wi-Fi task '%s' failed: %s", name, e)
                legend.set_text("WiFi error!")
                bus.emit("ui:redraw")
            finally:
                with wifi_task_lock:
                    wifi_task_running = None

        threading.Thread(target=runner, name=name, daemon=True).start()

    def _start_flask(wm=None):
        nonlocal flask_thread, flask_server
        if flask_thread is not None and flask_thread.is_alive():
            logger.info("Flask already running")
            return True
        from werkzeug.serving import make_server

        host = getattr(config, "flask_host", "0.0.0.0")
        port = int(getattr(config, "flask_port", 5000))
        try:
            app = create_app(wifi_manager=wm, db=db, bus=bus)
            flask_server = make_server(host, port, app)
        except (Exception, SystemExit) as e:
            # Porta occupata, errore nell'app: va detto, non ingoiato, o il
            # box mostra "AP pronto" con una pagina che non risponde.
            # SystemExit e' incluso di proposito: make_server() di werkzeug
            # stampa "Port 5000 is in use" e chiama sys.exit(1), che non
            # essendo una Exception faceva terminare tutta l'applicazione.
            logger.error(
                "Error starting Flask on %s:%s: %s",
                host,
                port,
                "port already in use" if isinstance(e, SystemExit) else e,
            )
            flask_server = None
            flask_thread = None
            return False
        flask_thread = threading.Thread(target=flask_server.serve_forever, daemon=True)
        flask_thread.start()
        logger.info("Flask avviato su %s:%s", host, port)
        return True

    def _stop_flask():
        nonlocal flask_thread, flask_server
        if flask_server is not None:
            try:
                flask_server.shutdown()
            except Exception as e:
                logger.error("Error stopping Flask: %s", e)
            flask_server = None
        flask_thread = None
        logger.info("Flask fermato")

    def start_hotspot(**kw):
        _run_wifi_task("start-ap", _start_hotspot_work, "Starting AP...")

    def _start_hotspot_work():
        nonlocal wifi_manager
        # Per sicurezza il server web parte solo insieme all'access point:
        # non deve mai restare in ascolto sulla rete Wi-Fi normale.
        logger.info("[MENU] Starting AP + Flask...")

        wifi_manager = WiFiManager(config)
        try:
            ssid = config.wifi_ap_ssid
            password = config.wifi_ap_password
            if not password:
                logger.warning("WIFI_AP_PASSWORD non impostata nel .env")
                legend.set_text("NO AP PASSWORD!")
                bus.emit("ui:redraw")
                return
            wifi_manager.start_ap(ssid, password)
        except ValueError as e:
            # Password troppo corta o assente: l'errore e' nel .env, non nella
            # rete, e va distinto da un fallimento di NetworkManager.
            logger.error("Invalid AP configuration: %s", e)
            legend.set_text("AP PASSWORD < 8 CHAR!")
            bus.emit("ui:redraw")
            return
        except Exception as e:
            logger.error("Error starting AP: %s", e)
            # Con l'AP giu' il box non e' raggiungibile: il log e' l'unica
            # traccia, quindi si registra subito lo stato della rete. Un
            # problema qui non deve cambiare il messaggio mostrato.
            try:
                wifi_manager.log_diagnostics()
            except Exception as diag_error:
                logger.warning("AP diagnostics failed: %s", diag_error)
            legend.set_text("AP error!")
            bus.emit("ui:redraw")
            return

        _set_wifi_status(True, f"AP {ssid}")
        sb.set_title(f"AP: {ssid}")
        logger.info("AP '%s' started on %s", ssid, wifi_manager.AP_IP)

        # Lo stato del server web va sempre mostrato: l'AP acceso da solo non
        # serve a niente se la pagina non risponde, e prima non c'era modo di
        # accorgersene dal box.
        port = int(getattr(config, "flask_port", 5000))
        if _start_flask(wifi_manager):
            legend.set_text(f"web {WiFiManager.AP_IP}:{port}")
            if not wifi_manager.captive_portal_ready:
                logger.warning(
                    "Captive portal redirect not active: open http://%s:%s by hand",
                    WiFiManager.AP_IP,
                    port,
                )
        else:
            legend.set_text("AP ok - WEB ERROR!")
        bus.emit("ui:redraw")

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
        _run_wifi_task("stop-ap", _stop_hotspot_work, "Stopping AP...")

    def _stop_hotspot_work():
        nonlocal wifi_manager
        logger.info("[MENU] Stopping AP...")
        reconnected = None
        if wifi_manager:
            try:
                # stop_ap riporta l'interfaccia sulla rete Wi-Fi che c'era
                # prima dell'AP (o sulla piu' recente fra quelle salvate).
                wifi_manager.stop_ap()
                reconnected = wifi_manager.get_current_ssid()
            except Exception as e:
                logger.error("Error stopping AP: %s", e)
        # Il server web non ha senso (e non e' sicuro) senza l'AP: si ferma
        # insieme, cosi' non resta mai in ascolto senza il suo perimetro.
        _stop_flask()
        _set_wifi_status(bool(reconnected), reconnected)
        sb.set_title("Liquorice")
        if reconnected:
            logger.info("AP stopped, back on Wi-Fi '%s'", reconnected)
            legend.set_text(f"WiFi: {reconnected}")
        else:
            logger.info("AP stopped, no Wi-Fi network available")
            legend.set_text("\u25c0 menu  \u25b6 backup")
        bus.emit("ui:redraw")

    bus.on("wifi:reset", stop_hotspot)

    print("Liquorice interactive. \u25c0 back, \u25b6 action")
    if mock:
        print("          i wifi  t title  (mock)")

    while True:
        if reed is not None:
            reed_closed = reed.get_state_change()
            if reed_closed is True:
                logger.info("Closed")
                display.render_full(LockView(), sb, Legend("Closed"))
                display.suspend()
            elif reed_closed is False:
                logger.info("Open")
                display.resume()
                display.render_full(active_view[0], sb, legend)

        now = time.monotonic()
        poll_interval = (
            0.25 if getattr(config, "operation_mode", "manual") == "auto" else 1.0
        )
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
    if not args.mock:
        # Senza timeout, un pannello piantato con BUSY alto blocca per sempre
        # il thread che disegna: e con l'event bus sincrono quel thread e'
        # quello del backup o dei pulsanti.
        install_busy_timeout(epd)
    run_interactive(epd)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Interrupted")
    except IOError as e:
        logger.info(e)

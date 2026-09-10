import logging
import threading
import time

logger = logging.getLogger(__name__)

LED_COUNT = 10
LED_PIN = 12
LED_FREQ_HZ = 800000
LED_DMA = 10
LED_BRIGHTNESS = 40
LED_INVERT = False

COLOR_OFF = (0, 0, 0)
COLOR_GREEN = (0, 255, 0)        # IDLE pronto / COMPLETED
COLOR_YELLOW = (255, 180, 0)     # IDLE senza SD
COLOR_BLUE = (0, 80, 255)        # CACHING
COLOR_CYAN = (0, 200, 200)       # UPLOADING
COLOR_MAGENTA = (180, 0, 180)    # REMOTE_CLEANUP / PRUNING
COLOR_ORANGE = (255, 100, 0)     # PAUSED / RETRYING
COLOR_RED = (255, 0, 0)          # ERROR
COLOR_WHITE = (200, 200, 200)    # BOOT

# stato -> (colore, blink)
_STATE_COLORS = {
    "INIT": (COLOR_WHITE, False),
    "CACHING": (COLOR_BLUE, True),
    "UPLOADING": (COLOR_CYAN, True),
    "REMOTE_CLEANUP": (COLOR_MAGENTA, True),
    "PRUNING": (COLOR_MAGENTA, True),
    "RETRYING": (COLOR_ORANGE, True),
    "PAUSED": (COLOR_ORANGE, False),
    "ERROR": (COLOR_RED, False),
    "COMPLETED": (COLOR_GREEN, False),
}


class LedStatus:
    def __init__(self, bus=None, mock=False):
        self._bus = bus
        self._mock = mock
        self._strip = None
        self._enabled = False
        self._color = COLOR_WHITE
        self._blink = False
        self._blink_on = True
        self._state_name = "INIT"
        self._sd_available = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None

        if mock:
            logger.info("LED mock mode - nessun hardware")
            return

        try:
            import rpi_ws281x as ws  # type: ignore
            self._ws = ws
            strip = ws.PixelStrip(LED_COUNT, LED_PIN, LED_FREQ_HZ, LED_DMA, LED_INVERT, LED_BRIGHTNESS)
            strip.begin()
            self._strip = strip
            self._enabled = True
            logger.info("LED strip inizializzata su BCM%d (%d LED)", LED_PIN, LED_COUNT)
        except ImportError as e:
            logger.warning("LED disabilitato: rpi_ws281x non installato (%s)", e)
            return
        except RuntimeError as e:
            msg = str(e)
            if "mmap" in msg or "Permission" in msg or "-5" in msg:
                logger.warning("LED disabilitato: permessi /dev/mem insufficienti (%s)", e)
            else:
                logger.warning("LED disabilitato: %s", e)
            return
        except Exception as e:
            logger.warning("LED disabilitato: %s", e)
            return

        self._apply(COLOR_WHITE, blink=False, force=True)

        self._thread = threading.Thread(target=self._blink_loop, daemon=True)
        self._thread.start()

        if bus:
            bus.on("backup:state", self._on_backup_state)
            bus.on("sd:changed", self._on_sd_changed)

        threading.Thread(target=self._boot_to_idle, daemon=True).start()

    def _boot_to_idle(self):
        time.sleep(1.5)
        if self._stop.is_set():
            return
        with self._lock:
            if self._state_name == "INIT":
                self._state_name = "IDLE"
        self._resolve()

    def cleanup(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1)
        self._apply(COLOR_OFF, blink=False, force=True)
        logger.info("LED spento")

    def _on_backup_state(self, state, **kw):
        with self._lock:
            self._state_name = getattr(state, "name", str(state))
        self._resolve()

    def _on_sd_changed(self, available, **kw):
        with self._lock:
            self._sd_available = bool(available)
        self._resolve()

    def _resolve(self):
        with self._lock:
            name = self._state_name
            sd = self._sd_available

        if name == "IDLE":
            color, blink = (COLOR_YELLOW, False) if sd is False else (COLOR_GREEN, False)
        else:
            color, blink = _STATE_COLORS.get(name, (COLOR_OFF, False))

        self._apply(color, blink)

    def _apply(self, color, blink, force=False):
        with self._lock:
            if not force and color == self._color and blink == self._blink:
                return
            self._color = color
            self._blink = blink
            self._blink_on = True
        if self._mock or not self._enabled:
            logger.debug("LED %s %s blink=%s", "MOCK" if self._mock else "OFF", color, blink)
            return
        if not blink:
            self._show_color(color)

    def _show_color(self, color):
        if not self._strip:
            return
        try:
            c = self._ws.Color(*color)
            for i in range(LED_COUNT):
                self._strip.setPixelColor(i, c)
            self._strip.show()
        except Exception as e:
            logger.warning("LED show failed: %s", e)

    def _blink_loop(self):
        while not self._stop.is_set():
            with self._lock:
                blink = self._blink
                color = self._color
                on = self._blink_on
            if blink:
                self._show_color(color if on else COLOR_OFF)
                with self._lock:
                    self._blink_on = not self._blink_on
                self._stop.wait(0.5)
            else:
                self._stop.wait(0.2)

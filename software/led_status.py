"""LED di stato per Amarelli - WS2812B su BCM12 (PWM0, 10 LED).
Mappa Backup.State + disponibilita' SD -> colore fisso o blink.
Blink gestito in thread separato per non bloccare il main loop.
In mock o senza rpi_ws281x / permessi: fallback no-op con log.
"""
import logging
import threading
import time

logger = logging.getLogger(__name__)

# Config hardware (cfr. hardware/wiring.md + tests/hardware/test_led.py)
LED_COUNT = 10
LED_PIN = 12
LED_FREQ_HZ = 800000
LED_DMA = 10
LED_BRIGHTNESS = 40  # dimezzato da 80 su richiesta (era 255 di default)
LED_INVERT = False

# Colori (R,G,B)
COLOR_OFF = (0, 0, 0)
COLOR_GREEN = (0, 255, 0)        # IDLE pronto / COMPLETED
COLOR_YELLOW = (255, 180, 0)     # IDLE in attesa SD
COLOR_BLUE = (0, 80, 255)        # CACHING
COLOR_CYAN = (0, 200, 200)       # UPLOADING
COLOR_MAGENTA = (180, 0, 180)    # REMOTE_CLEANUP / PRUNING
COLOR_ORANGE = (255, 100, 0)     # PAUSED / RETRYING
COLOR_RED = (255, 0, 0)          # ERROR
COLOR_WHITE = (200, 200, 200)    # BOOT

# Stati che devono blinkare (operazioni lunghe)
BLINK_STATES = {"CACHING", "UPLOADING", "REMOTE_CLEANUP", "PRUNING", "RETRYING"}


class LedStatus:
    """Controller LED. Ascolta backup:state + sd:changed su bus."""

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
                logger.warning("LED disabilitato: permessi /dev/mem insufficienti (%s) - prova con sudo o riavvia dopo usermod -a -G gpio,kmem,spi", e)
            else:
                logger.warning("LED disabilitato: %s", e)
            return
        except Exception as e:
            logger.warning("LED disabilitato: %s", e)
            return

        # Stato iniziale boot - bianco visibile 1.5s poi IDLE (force per mostrare anche se colore iniziale = WHITE)
        self._apply(COLOR_WHITE, blink=False, force=True)
        logger.info("LED boot bianco (%s)", COLOR_WHITE)

        # Thread blink
        self._thread = threading.Thread(target=self._blink_loop, daemon=True)
        self._thread.start()

        # Subscribe bus
        if bus:
            bus.on("backup:state", self._on_backup_state)
            bus.on("sd:changed", self._on_sd_changed)

        def _boot_to_idle():
            time.sleep(1.5)
            if self._stop.is_set():
                return
            with self._lock:
                if self._state_name == "INIT":
                    self._state_name = "IDLE"
            self._resolve()
            logger.info("LED boot -> IDLE %s sd=%s", self._color, self._sd_available)

        threading.Thread(target=_boot_to_idle, daemon=True).start()

    # --- public API ---
    def cleanup(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1)
        self._apply(COLOR_OFF, blink=False, force=True)
        logger.info("LED spento")

    # --- bus handlers ---
    def _on_backup_state(self, state, **kw):
        name = getattr(state, "name", str(state))
        with self._lock:
            self._state_name = name
        self._resolve()

    def _on_sd_changed(self, available, **kw):
        with self._lock:
            self._sd_available = bool(available)
        self._resolve()

    def _resolve(self):
        """Decide colore/blink in base a stato + SD e applica."""
        with self._lock:
            name = self._state_name
            sd = self._sd_available

        if name == "INIT":
            color, blink = COLOR_WHITE, False
        elif name in ("CACHING",):
            color, blink = COLOR_BLUE, True
        elif name in ("UPLOADING",):
            color, blink = COLOR_CYAN, True
        elif name in ("REMOTE_CLEANUP", "PRUNING"):
            color, blink = COLOR_MAGENTA, True
        elif name == "RETRYING":
            color, blink = COLOR_ORANGE, True
        elif name == "PAUSED":
            color, blink = COLOR_ORANGE, False
        elif name == "ERROR":
            color, blink = COLOR_RED, False
        elif name == "COMPLETED":
            color, blink = COLOR_GREEN, False  # breve blink gestito dal caller se vuoi, qui fisso
        elif name == "IDLE":
            if sd is False:
                color, blink = COLOR_YELLOW, False
            else:
                color, blink = COLOR_GREEN, False
        else:
            color, blink = COLOR_OFF, False

        self._apply(color, blink)

    def _apply(self, color, blink, force=False):
        with self._lock:
            if not force and color == self._color and blink == self._blink:
                return
            self._color = color
            self._blink = blink
            self._blink_on = True  # reset blink cycle
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

    def _show_off(self):
        self._show_color(COLOR_OFF)

    def _blink_loop(self):
        while not self._stop.is_set():
            with self._lock:
                blink = self._blink
                color = self._color
                on = self._blink_on
            if blink:
                if on:
                    self._show_color(color)
                else:
                    self._show_off()
                with self._lock:
                    self._blink_on = not self._blink_on
                self._stop.wait(0.5)
            else:
                # stato fisso - rifresha ogni 200ms per mantenere, ma senza toggling
                self._stop.wait(0.2)

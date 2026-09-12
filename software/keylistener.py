import logging
import time
from abc import ABC, abstractmethod
from queue import SimpleQueue

logger = logging.getLogger(__name__)


class KeyListener(ABC):
    @abstractmethod
    def get_key(self):
        ...

    def cleanup(self):
        pass


class TerminalKeyListener(KeyListener):
    def get_key(self):
        import os
        import sys
        import select
        import tty
        import termios

        if not sys.stdin.isatty():
            ch = sys.stdin.read(1)
            return "Q" if not ch else ch

        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            ch = os.read(fd, 1)
            if ch == b"\x1b":
                if select.select([fd], [], [], 0.05)[0]:
                    rest = os.read(fd, 2)
                    return {
                        b"[A": "UP",
                        b"[B": "DOWN",
                        b"[C": "RIGHT",
                        b"[D": "LEFT",
                    }.get(rest)
                return None
            return ch.decode("ascii", errors="replace")
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)


class GpioKeyListener(KeyListener):
    UP = 0
    DOWN = 1
    LEFT = 2
    RIGHT = 3
    BOUNCE_TIME_MS = 50
    # Il refresh dell'e-ink induce sulla linea del DOWN (BCM6) treni di impulsi
    # che gpiozero fonde in finte pressioni da 60 a 125 ms: generavano un loop di
    # ridisegni. Fuori dal refresh la linea e' pulita (zero eventi in 20s), per
    # cui il filtro si applica solo mentre il pannello sta lavorando: la
    # pressione vale subito, senza dover tenere premuto.
    MIN_PRESS_DURING_REFRESH_MS = 180

    def __init__(self, pins=(None, None, None, None), display_busy=None):
        self._pins = {
            self.UP: pins[self.UP],
            self.DOWN: pins[self.DOWN],
            self.LEFT: pins[self.LEFT],
            self.RIGHT: pins[self.RIGHT],
        }
        self._key_map = {
            self.UP: "UP",
            self.DOWN: "DOWN",
            self.LEFT: "LEFT",
            self.RIGHT: "RIGHT",
        }
        self._display_busy = display_busy
        self._events = SimpleQueue()
        self._pressed_at = {}
        self._buttons = []
        self._available = False
        self._setup()

    def _display_is_refreshing(self):
        if self._display_busy is None:
            return False
        try:
            return bool(self._display_busy())
        except Exception:
            return False

    def _on_pressed(self, key):
        if not self._display_is_refreshing():
            # Linea pulita: l'evento vale subito, alla pressione. Il debounce di
            # gpiozero basta a scartare i rimbalzi del contatto.
            self._pressed_at.pop(key, None)
            self._events.put(key)
            return
        # Durante il refresh serve misurare la durata: si decide al rilascio.
        self._pressed_at[key] = time.monotonic()

    def _on_released(self, key):
        started = self._pressed_at.pop(key, None)
        if started is None:
            # Evento gia' emesso alla pressione.
            return
        held_ms = (time.monotonic() - started) * 1000
        if held_ms < self.MIN_PRESS_DURING_REFRESH_MS:
            logger.debug(
                "Impulso spurio ignorato su %s (%.0f ms durante il refresh)",
                self._key_map[key],
                held_ms,
            )
            return
        self._events.put(key)

    def _setup(self):
        try:
            from gpiozero import Button

            for idx, pin in self._pins.items():
                if pin is not None:
                    button = Button(
                        pin, pull_up=True, bounce_time=self.BOUNCE_TIME_MS / 1000
                    )
                    button.when_pressed = lambda _b, key=idx: self._on_pressed(key)
                    button.when_released = lambda _b, key=idx: self._on_released(key)
                    self._buttons.append(button)
            self._available = True
        except ImportError:
            logger.warning("gpiozero not available, GpioKeyListener is a stub")
        except Exception as e:
            logger.warning("GPIO setup failed: %s", e)

    def get_key(self):
        if not self._available:
            return None
        try:
            return self._key_map[self._events.get_nowait()]
        except Exception:
            return None

    def cleanup(self):
        for button in self._buttons:
            button.close()


class ReedSwitch:
    """Reed su BCM16: chiuso con magnete, aperto senza magnete."""

    def __init__(self, pin=16, enabled=True):
        self._events = SimpleQueue()
        self._button = None
        self._closed = False
        if not enabled:
            return
        try:
            from gpiozero import Button

            self._button = Button(pin, pull_up=True, bounce_time=0.3)
            self._closed = self._button.is_pressed
            self._button.when_pressed = lambda: self._set_closed(True)
            self._button.when_released = lambda: self._set_closed(False)
        except ImportError:
            logger.warning("gpiozero not available, ReedSwitch is disabled")
        except Exception as error:
            logger.warning("Reed switch setup failed: %s", error)

    @property
    def is_closed(self):
        return self._closed

    def _set_closed(self, closed):
        closed = bool(closed)
        if closed != self._closed:
            self._closed = closed
            self._events.put(closed)

    def get_state_change(self):
        """Ritorna l'ultimo stato accumulato in coda, non il primo.

        Un singolo movimento del coperchio puo' generare piu' transizioni in
        rapida successione (rimbalzo del reed oltre il bounce_time di
        gpiozero): senza drenare la coda, il loop principale le riproduce una
        alla volta nei cicli successivi, sospendendo e riattivando il display
        piu' volte per un solo movimento reale. Si tiene solo l'ultimo valore,
        che rappresenta lo stato attuale del coperchio; i valori intermedi
        vengono scartati perche' superati.
        """
        last = None
        while True:
            try:
                last = self._events.get_nowait()
            except Exception:
                break
        return last

    def cleanup(self):
        if self._button is not None:
            self._button.close()

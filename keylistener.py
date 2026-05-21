import logging
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class KeyListener(ABC):
    @abstractmethod
    def get_key(self):
        """Return a key identifier string or None."""
        pass

    def cleanup(self):
        """Restore any system state (e.g., terminal settings)."""
        pass


class TerminalKeyListener(KeyListener):
    def get_key(self):
        import os as _os
        import sys as _sys
        import select as _select
        import tty as _tty
        import termios as _termios

        if not _sys.stdin.isatty():
            ch = _sys.stdin.read(1)
            return "Q" if not ch else ch

        fd = _sys.stdin.fileno()
        old = _termios.tcgetattr(fd)
        try:
            _tty.setraw(fd)
            ch = _os.read(fd, 1)
            if ch == b"\x1b":
                if _select.select([fd], [], [], 0.05)[0]:
                    rest = _os.read(fd, 2)
                    if rest == b"[A":
                        return "UP"
                    elif rest == b"[B":
                        return "DOWN"
                    elif rest == b"[C":
                        return "RIGHT"
                    elif rest == b"[D":
                        return "LEFT"
                return None
            return ch.decode("ascii", errors="replace")
        finally:
            _termios.tcsetattr(fd, _termios.TCSADRAIN, old)


class GpioKeyListener(KeyListener):
    UP = 0
    DOWN = 1
    LEFT = 2
    RIGHT = 3

    def __init__(self, pins=(None, None, None, None)):
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
        self._last_key = None
        self._available = False
        self._setup()

    def _setup(self):
        try:
            import RPi.GPIO as GPIO

            GPIO.setmode(GPIO.BCM)
            for pin in self._pins.values():
                if pin is not None:
                    GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
            self._available = True
        except ImportError:
            logger.warning("RPi.GPIO not available, GpioKeyListener is a stub")
        except Exception as e:
            logger.warning("GPIO setup failed: %s", e)

    def get_key(self):
        if not self._available:
            return None

        import RPi.GPIO as GPIO

        for idx, pin in self._pins.items():
            if pin is None:
                continue
            if GPIO.input(pin) == GPIO.LOW:
                if self._last_key != idx:
                    self._last_key = idx
                    return self._key_map[idx]
            elif self._last_key == idx:
                self._last_key = None
        return None

    def cleanup(self):
        if self._available:
            try:
                import RPi.GPIO as GPIO

                GPIO.cleanup()
            except Exception:
                pass

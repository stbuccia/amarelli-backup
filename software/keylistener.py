import logging
from abc import ABC, abstractmethod
from queue import SimpleQueue

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
    BOUNCE_TIME_MS = 50

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
        self._events = SimpleQueue()
        self._buttons = []
        self._available = False
        self._setup()

    def _setup(self):
        try:
            from gpiozero import Button

            for idx, pin in self._pins.items():
                if pin is not None:
                    button = Button(
                        pin, pull_up=True, bounce_time=self.BOUNCE_TIME_MS / 1000
                    )
                    button.when_pressed = (
                        lambda _button, key=idx: self._events.put(key)
                    )
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

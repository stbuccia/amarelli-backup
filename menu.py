import logging
from collections.abc import Callable

from eventbus import EventBus, bus

logger = logging.getLogger(__name__)


class MenuItem:
    def __init__(
        self,
        label: str,
        action: Callable[[], object] | None = None,
        children: list["MenuItem"] | None = None,
        config_key: str | None = None,
        value: object = None,
    ):
        self.label = label
        self.action = action
        self.children = children
        self.config_key = config_key
        self.value = value

    @property
    def is_branch(self) -> bool:
        return self.children is not None and len(self.children) > 0


MENU_TREE = [
    MenuItem(
        "WiFi",
        children=[
            MenuItem("Connetti a rete",
                     action=lambda: bus.emit("wifi:connect")),
            MenuItem("Mostra IP",
                     action=lambda: bus.emit("wifi:show_ip")),
            MenuItem("Resetta WiFi",
                     action=lambda: bus.emit("wifi:reset")),
        ],
    ),
    MenuItem(
        "Cache",
        config_key="prune_policy",
        children=[
            MenuItem("Cancella subito",  value="immediate"),
            MenuItem("Dopo 7 giorni",    value=7),
            MenuItem("Dopo 30 giorni",   value=30),
            MenuItem("Mantieni sempre",  value=None),
        ],
    ),
    MenuItem("Stato sistema",
             action=lambda: bus.emit("system:status")),
    MenuItem(
        "Spegni",
        children=[
            MenuItem("Spegni",
                     action=lambda: bus.emit("system:shutdown")),
            MenuItem("Riavvia",
                     action=lambda: bus.emit("system:reboot")),
        ],
    ),
]


class Menu:
    def __init__(self, items=MENU_TREE, title="Amarelli", config=None, bus=None):
        self._root = items
        self._title = title
        self._config = config
        self._bus = bus or EventBus()
        self._reset()

    def _set_config_value(self, key: str, value: object) -> None:
        self._config[key] = value
        self._bus.emit("config:set", key=key, value=value)

    def _reset(self):
        self._stack: list[tuple[list[MenuItem], int]] = []
        self._items = self._root
        self._selected = 0

    @property
    def current(self) -> MenuItem:
        return self._items[self._selected]

    @property
    def current_label(self) -> str:
        return self.current.label

    @property
    def current_action(self) -> Callable[[], object] | None:
        return self.current.action

    @property
    def is_branch(self) -> bool:
        return self.current.is_branch

    @property
    def at_root(self) -> bool:
        return len(self._stack) == 0

    @property
    def breadcrumb_title(self) -> str:
        if self.at_root:
            return self._title
        parent_label = self._stack[-1][0][self._stack[-1][1]].label
        return f"{self._title} \u203a {parent_label}"

    def up(self):
        if self._selected > 0:
            self._selected -= 1

    def down(self):
        if self._selected < len(self._items) - 1:
            self._selected += 1

    def enter(self):
        item = self.current
        if item.is_branch:
            self._stack.append((self._items, self._selected))
            self._items = item.children
            self._selected = 0
        else:
            parent_config_key = None
            if self._stack:
                parent_items, parent_idx = self._stack[-1]
                parent = parent_items[parent_idx]
                parent_config_key = getattr(parent, 'config_key', None)
            if parent_config_key is not None and item.value is not None:
                self._set_config_value(parent_config_key, item.value)
                self.back()
            elif item.action is not None:
                item.action()

    def back(self) -> bool:
        if self._stack:
            self._items, self._selected = self._stack.pop()
            return True
        return False

    def handle_key_event(self, key):
        if key in ("UP", "w"):
            self.up()
            self._bus.emit("menu:changed")
        elif key in ("DOWN", "s"):
            self.down()
            self._bus.emit("menu:changed")
        elif key in ("RIGHT", "d", "\r", "\n"):
            self.enter()
            self._bus.emit("menu:changed")
        elif key in ("LEFT", "a"):
            if not self.back():
                self._bus.emit("menu:closed")
            else:
                self._bus.emit("menu:changed")

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
        return bool(self.children)


MENU_TREE = [
    MenuItem(
        "WiFi",
        children=[
            MenuItem("Start hotspot", action=lambda: bus.emit("hotspot:start")),
            MenuItem("Start web server", action=lambda: bus.emit("server:start")),
            MenuItem("Show IP", action=lambda: bus.emit("wifi:show_ip")),
            MenuItem("Reset WiFi", action=lambda: bus.emit("wifi:reset")),
        ],
    ),
    MenuItem(
        "Mode",
        config_key="mode",
        children=[
            MenuItem("Upload only", value="upload"),
            MenuItem("Mirroring", value="mirror"),
        ],
    ),
    MenuItem(
        "Cache",
        config_key="prune_min_days",
        children=[
            MenuItem("Delete now", value=0),
            MenuItem("After 7 days", value=7),
            MenuItem("After 30 days", value=30),
            MenuItem("Keep forever", value=None),
        ],
    ),
    MenuItem(
        "File type",
        config_key="file_filter",
        children=[
            MenuItem("All files", value="all"),
            MenuItem("Photos only (JPG+RAW)", value="images"),
            MenuItem("JPG only", value="jpg"),
        ],
    ),
    MenuItem(
        "Operation",
        config_key="operation_mode",
        children=[
            MenuItem("Manual", value="manual"),
            MenuItem("Automatic (LED)", value="auto"),
        ],
    ),
    MenuItem(
        "Debug",
        children=[
            MenuItem(
                "Fake SD",
                config_key="fake_sd",
                children=[
                    MenuItem("Off (real SD)", value=False),
                    MenuItem("On (fake-sd dir)", value=True),
                ],
            ),
        ],
    ),
]


class Menu:
    def __init__(self, items=MENU_TREE, title="Liquorice", config=None, bus=None):
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
        parent_items, parent_idx = self._stack[-1]
        return f"{self._title} \u203a {parent_items[parent_idx].label}"

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
            return

        parent_config_key = None
        if self._stack:
            parent_items, parent_idx = self._stack[-1]
            parent_config_key = getattr(parent_items[parent_idx], "config_key", None)
        if parent_config_key is not None:
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

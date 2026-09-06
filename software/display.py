import sys
import os
import logging
from PIL import Image, ImageDraw, ImageFont
from contextlib import nullcontext

from backup import State

BATTERY_SIZE = 16
ICON_SIZE = 7


def _draw_icon_triangle(draw, x, y, size, fill, direction):
    h = size
    w = size
    if direction == "right":
        pts = [(x, y), (x, y + h - 1), (x + w - 1, y + h // 2)]
    elif direction == "left":
        pts = [(x + w - 1, y), (x + w - 1, y + h - 1), (x, y + h // 2)]
    elif direction == "up":
        pts = [(x, y + h - 1), (x + w // 2, y), (x + w - 1, y + h - 1)]
    elif direction == "down":
        pts = [(x, y), (x + w // 2, y + h - 1), (x + w - 1, y)]
    draw.polygon(pts, fill=fill)


def _draw_icon_circle(draw, x, y, size, fill):
    r = size // 2
    cx, cy = x + r, y + r
    draw.ellipse([(cx - r, cy - r), (cx + r, cy + r)], outline=fill, fill=None)


def _draw_icon_circle_filled(draw, x, y, size, fill):
    r = size // 2
    cx, cy = x + r, y + r
    draw.ellipse([(cx - r, cy - r), (cx + r, cy + r)], fill=fill, outline=fill)


_ICON_DISPATCH = {
    "\u25b6": lambda d, x, y, s, f: _draw_icon_triangle(d, x, y, s, f, "right"),
    "\u25c0": lambda d, x, y, s, f: _draw_icon_triangle(d, x, y, s, f, "left"),
    "\u25b2": lambda d, x, y, s, f: _draw_icon_triangle(d, x, y, s, f, "up"),
    "\u25bc": lambda d, x, y, s, f: _draw_icon_triangle(d, x, y, s, f, "down"),
    "\u25cb": lambda d, x, y, s, f: _draw_icon_circle(d, x, y, s, f),
    "\u25cf": lambda d, x, y, s, f: _draw_icon_circle_filled(d, x, y, s, f),
}


def _draw_icon_battery(draw, x, y, size, fill, percent=100):
    bw, bh = size * 7 // 10, size * 6 // 10
    bx = x + (size - bw) // 2
    by = y + (size - bh) // 2
    draw.rectangle([(bx, by), (bx + bw - 1, by + bh - 1)], outline=fill, fill=None)
    nw = max(1, size // 10)
    nh = max(1, bh // 3)
    draw.rectangle([(bx + bw, by + nh), (bx + bw + nw - 1, by + bh - nh - 1)], fill=fill)
    iw = bw - 2
    fw = max(0, min(iw, round(iw * percent / 100)))
    if fw > 0:
        draw.rectangle([(bx + 1, by + 1), (bx + fw, by + bh - 2)], fill=fill)


def _render_icons_in_text(draw, x, y, text, font, fill=0):
    _, _, _, th = draw.textbbox((0, 0), "Xg", font=font)
    ox = x
    buf = ""
    for ch in text:
        if ch in _ICON_DISPATCH:
            if buf:
                draw.text((ox, y), buf, font=font, fill=fill)
                ow, _ = draw.textbbox((0, 0), buf, font=font)[2:4]
                ox += ow
                buf = ""
            iy = y + (th - ICON_SIZE) // 2
            _ICON_DISPATCH[ch](draw, ox, iy, ICON_SIZE, fill)
            ox += ICON_SIZE + 1
        else:
            buf += ch
    if buf:
        draw.text((ox, y), buf, font=font, fill=fill)

picdir = os.path.join(
    os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "pic"
)
libdir = os.path.join(
    os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "lib"
)
if os.path.exists(libdir):
    sys.path.append(libdir)

logger = logging.getLogger(__name__)


class StatusBar:
    HEIGHT = 16

    def __init__(self, title="Amarelli"):
        self._title = title
        self._battery = 87
        self._wifi = True

    def set_title(self, title: str):
        self._title = title

    def set_battery(self, percent: int):
        self._battery = max(0, min(100, int(percent)))

    def set_wifi(self, connected: bool):
        self._wifi = connected

    def render(self, draw, font, width):
        y = 0
        draw.rectangle([(0, y), (width, y + self.HEIGHT)], fill=255)

        _, _, _, th = draw.textbbox((0, 0), "Xg", font=font)
        text_y = y + (self.HEIGHT - th) // 2

        draw.text((4, text_y), self._title, font=font, fill=0)

        bat = f"{self._battery}%"
        _, _, bw, _ = draw.textbbox((0, 0), bat, font=font)
        bx = width - bw - 4
        draw.text((bx, text_y), bat, font=font, fill=0)

        ix = bx - 2 - BATTERY_SIZE
        iy = text_y + (th - BATTERY_SIZE) // 2
        _draw_icon_battery(draw, ix, iy, BATTERY_SIZE, 0, self._battery)

        draw.line([(2, y + self.HEIGHT - 1), (width - 2, y + self.HEIGHT - 1)], fill=0)


class Legend:
    HEIGHT = 14

    def __init__(self, text="\u25b2/\u25bc nav  \u25b6 enter  \u25c0 back  Q quit"):
        self._text = text

    def set_text(self, text: str):
        self._text = text

    def render(self, draw, font, width, screen_height):
        _, _, _, th = draw.textbbox((0, 0), "Xg", font=font)
        y = screen_height - self.HEIGHT
        draw.rectangle([(0, y), (width, screen_height)], fill=255)
        tw = 0
        for ch in self._text:
            if ch in _ICON_DISPATCH:
                tw += ICON_SIZE + 1
            else:
                cw, _ = draw.textbbox((0, 0), ch, font=font)[2:4]
                tw += cw
        ty = y + (self.HEIGHT - th) // 2
        _render_icons_in_text(draw, (width - tw) // 2, ty, self._text, font, fill=0)


class BackupStatusView:
    MARGIN_X = 4
    LINE_SPACING = 2

    def __init__(self, db=None, bus=None):
        self.db = db
        self.status = "Ready"
        self.cached_count = 0
        self.pending_upload = 0
        self.uploaded_count = 0
        self.progress_total = 0
        self.progress_current = 0
        self.current_file = ""
        self._wifi = True
        self._bus = bus
        if bus:
            bus.on("backup:state", self._on_backup_state)
            bus.on("file:cached", self._on_file_cached)
            bus.on("file:uploaded", self._on_file_uploaded)
            bus.on("file:pruned", self._on_file_pruned)
            bus.on("file:remote_deleted", self._on_remote_deleted)
            bus.on("cache:file", self._on_cache_file)
            bus.on("sd:changed", self._on_sd_changed)

    def refresh(self):
        try:
            if self.db is not None:
                self.cached_count = self.db.count_cached()
                self.pending_upload = self.db.count_pending_uploads()
                self.uploaded_count = self.db.count_uploaded()
        except Exception:
            pass

    def set_phase(self, total: int):
        self.progress_total = total
        self.progress_current = 0

    def inc_progress(self):
        if self.progress_current < self.progress_total:
            self.progress_current += 1

    def _on_backup_state(self, state, total=0, reset=False, **kw):
        self.status = {
            State.CACHING: "Caching files...",
            State.UPLOADING: "Uploading...",
            State.REMOTE_CLEANUP: "Cleaning remote...",
            State.PRUNING: "Pruning cache...",
            State.COMPLETED: "Done",
            State.PAUSED: "Paused",
            State.RETRYING: "Retrying...",
            State.ERROR: "Error",
            State.IDLE: "Ready",
        }.get(state, "")
        if reset:
            self.cached_count = 0
            self.pending_upload = 0
            self.uploaded_count = 0
            self.progress_total = 0
            self.progress_current = 0
        if state in (State.IDLE, State.COMPLETED, State.PAUSED, State.ERROR):
            self.refresh()
        if total:
            self.set_phase(total)
        legend_text = {
            State.IDLE: "\u25b6 backup  \u25c0 menu  Q quit",
            State.CACHING: "\u25c0 pause  Q quit",
            State.UPLOADING: "\u25c0 pause  Q quit",
            State.REMOTE_CLEANUP: "\u25c0 pause  Q quit",
            State.PRUNING: "\u25c0 pause  Q quit",
            State.PAUSED: "\u25b6 resume  \u25c0 stop  Q quit",
            State.RETRYING: "\u25c0 pause  Q quit",
            State.COMPLETED: "\u25b6 backup  \u25c0 menu  Q quit",
            State.ERROR: "\u25b6 backup  \u25c0 menu  Q quit",
        }.get(state, "")
        if legend_text:
            self._bus.emit("ui:legend-update", text=legend_text)
        self._bus.emit("ui:redraw")

    def _on_file_cached(self, file=None, **kw):
        self.cached_count += 1
        self.pending_upload += 1
        self.inc_progress()
        self._bus.emit("ui:redraw")

    def _on_cache_file(self, path, processed=0, **kw):
        self.current_file = path.rsplit("/", 1)[-1]
        self.progress_current = min(processed, self.progress_total)
        self._bus.emit("ui:redraw")

    def _on_file_uploaded(self, file=None, **kw):
        self.pending_upload -= 1
        self.uploaded_count += 1
        self.inc_progress()
        self._bus.emit("ui:redraw")

    def _on_file_pruned(self, file=None, **kw):
        self.cached_count -= 1
        self.inc_progress()
        self._bus.emit("ui:redraw")

    def _on_remote_deleted(self, file=None, **kw):
        self.uploaded_count = max(0, self.uploaded_count - 1)
        self.cached_count = max(0, self.cached_count - 1)
        self.inc_progress()
        self._bus.emit("ui:redraw")

    def _on_sd_changed(self, available, **kw):
        if available or self.pending_upload > 0:
            self.status = "Ready"
        else:
            self.status = "Waiting for SD card"
        self._bus.emit("ui:redraw")

    def render(self, draw, font, width, height, y_offset=0, bottom_margin=0):
        draw.rectangle([(0, y_offset), (width, height)], fill=255)
        _, _, _, th = draw.textbbox((0, 0), "Xg", font=font)
        line_h = th + self.LINE_SPACING
        x = self.MARGIN_X
        y = y_offset + 4

        draw.text((x, y), f"Status: {self.status}", font=font, fill=0)
        y += line_h

        wifi_label = "Connected" if self._wifi else "Disconnected"
        draw.text((x, y), f"WiFi: {wifi_label}", font=font, fill=0)
        y += line_h

        if self.progress_total > 0:
            bar_y = y
            bar_h = max(4, th - 4)
            bar_w = width - 2 * x
            fill = max(
                0, min(bar_w, int(bar_w * self.progress_current / self.progress_total))
            )
            draw.rectangle(
                [(x, bar_y), (x + bar_w, bar_y + bar_h)], fill=255, outline=0
            )
            if fill > 1:
                draw.rectangle(
                    [(x + 1, bar_y + 1), (x + fill - 1, bar_y + bar_h - 1)], fill=0
                )
            y += bar_h + self.LINE_SPACING

        if self.status == "Caching files..." and self.current_file:
            draw.text((x, y), self.current_file[:30], font=font, fill=0)
            return

        draw.text((x, y), f"Cached: {self.cached_count} files", font=font, fill=0)
        y += line_h
        draw.text((x, y), f"To upload: {self.pending_upload}", font=font, fill=0)
        y += line_h
        draw.text((x, y), f"Uploaded: {self.uploaded_count}", font=font, fill=0)


class MenuView:
    MARGIN_X = 4
    LINE_SPACING = 2

    def __init__(self, menu, bus=None):
        self._menu = menu
        self._bus = bus
        if bus:
            bus.on("menu:changed", self._on_menu_changed)

    def _on_menu_changed(self, **kw):
        self._bus.emit("ui:statusbar-update", title=self._menu.breadcrumb_title)
        self._bus.emit("ui:redraw")

    def render(self, draw, font, width, height, y_offset=0, bottom_margin=0):
        draw.rectangle([(0, y_offset), (width, height)], fill=255)
        _, _, _, th = draw.textbbox((0, 0), "Xg", font=font)
        line_h = th + self.LINE_SPACING
        x = self.MARGIN_X
        y = y_offset + 4

        parent_config_key = None
        if self._menu._stack:
            parent_items, parent_idx = self._menu._stack[-1]
            parent_config_key = parent_items[parent_idx].config_key

        for i, item in enumerate(self._menu._items):
            if y + line_h > height - bottom_margin - 2:
                break

            label_text = item.label
            icon_right = None
            icon_left = None

            if item.is_branch:
                icon_right = "\u25b6"
            elif parent_config_key is not None and self._menu._config is not None:
                current_val = self._menu._config.get(parent_config_key)
                if current_val == item.value:
                    icon_left = "\u25cf"
                else:
                    icon_left = "\u25cb"

            if i == self._menu._selected:
                draw.rectangle([(x, y), (width - x, y + line_h)], fill=0)
                text_fill = 255
            else:
                text_fill = 0

            cx = x + 2
            if icon_left:
                iy = y + 1 + (th - ICON_SIZE) // 2
                _ICON_DISPATCH[icon_left](draw, cx, iy, ICON_SIZE, text_fill)
                cx += ICON_SIZE + 2

            draw.text((cx, y + 1), label_text, font=font, fill=text_fill)
            _, _, lw, _ = draw.textbbox((0, 0), label_text, font=font)
            cx += lw

            if icon_right:
                iy = y + 1 + (th - ICON_SIZE) // 2
                _ICON_DISPATCH[icon_right](draw, cx + 2, iy, ICON_SIZE, text_fill)

            y += line_h


class Display:
    WIDTH = 250
    HEIGHT = 122

    def __init__(self, epd, font, snapshot_path=None, io_lock=None):
        self._epd = epd
        self._font = font
        self._initialized = False
        self.snapshot_path = snapshot_path
        self._io_lock = io_lock

    @property
    def font(self):
        return self._font

    def init(self):
        # Match the Waveshare V4 startup sequence before the first frame.
        with self._io_lock or nullcontext():
            self._epd.init()
            self._epd.Clear(0xFF)

    def init_full(self):
        with self._io_lock or nullcontext():
            self._epd.init()
            self._epd.Clear(0xFF)

    def sleep(self):
        with self._io_lock or nullcontext():
            self._epd.sleep()

    def _compose(self, content_view, status_bar, legend):
        img = Image.new("1", (self.WIDTH, self.HEIGHT), 255)
        draw = ImageDraw.Draw(img)
        status_bar.render(draw, self._font, self.WIDTH)
        content_view.render(
            draw,
            self._font,
            self.WIDTH,
            self.HEIGHT,
            y_offset=StatusBar.HEIGHT,
            bottom_margin=Legend.HEIGHT,
        )
        legend.render(draw, self._font, self.WIDTH, self.HEIGHT)
        return img

    def render_full(self, content_view, status_bar, legend):
        img = self._compose(content_view, status_bar, legend)
        if self.snapshot_path:
            img.save(self.snapshot_path)
        with self._io_lock or nullcontext():
            if not self._initialized:
                self._epd.init()
                self._epd.display(self._epd.getbuffer(img))
                self._initialized = True
            else:
                self._epd.init_fast()
                self._epd.display_fast(self._epd.getbuffer(img))


def setup_ui_handlers(
    bus, display, status_bar, legend, menu, status_view, menu_view, redraw_fn
):
    active_view = [status_view]

    def on_redraw(**kw):
        redraw_fn()

    def on_menu_opened(**kw):
        active_view[0] = menu_view
        status_bar.set_title(menu.breadcrumb_title)
        legend.set_text("\u25b2/\u25bc nav  \u25b6 enter  \u25c0 back  Q quit")
        display.render_full(active_view[0], status_bar, legend)

    def on_menu_closed(**kw):
        active_view[0] = status_view
        status_bar.set_title("Amarelli")
        legend.set_text("\u25b6 backup  \u25c0 menu  Q quit")
        status_view.refresh()
        display.render_full(active_view[0], status_bar, legend)

    def on_statusbar_update(title=None, battery=None, wifi=None, **kw):
        if title is not None:
            status_bar.set_title(title)
        if battery is not None:
            status_bar.set_battery(battery)
        if wifi is not None:
            status_bar.set_wifi(wifi)
            for v in active_view:
                if hasattr(v, '_wifi'):
                    v._wifi = wifi

    def on_legend_update(text, **kw):
        legend.set_text(text)

    bus.on("ui:redraw", on_redraw)
    bus.on("menu:opened", on_menu_opened)
    bus.on("menu:closed", on_menu_closed)
    bus.on("ui:statusbar-update", on_statusbar_update)
    bus.on("ui:legend-update", on_legend_update)

    return active_view


def load_font(size=15):
    font_path = os.path.join(picdir, "Font.ttc")
    if os.path.exists(font_path):
        return ImageFont.truetype(font_path, size)
    for path in [
        "/usr/share/fonts/noto/NotoSans-Regular.ttf",
        "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
    ]:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    logger.warning("No font found, using default")
    return ImageFont.load_default()

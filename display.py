import sys
import os
import logging
from PIL import Image, ImageDraw, ImageFont

from backup import State

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

        wifi_char = "\u25c9" if self._wifi else "\u25cb"
        bat = f"{self._battery}%"
        right_text = f"{wifi_char} {bat}"
        _, _, rw, _ = draw.textbbox((0, 0), right_text, font=font)
        draw.text((width - rw - 4, text_y), right_text, font=font, fill=0)

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
        _, _, tw, _ = draw.textbbox((0, 0), self._text, font=font)
        draw.text(
            ((width - tw) // 2, y + (self.HEIGHT - th) // 2),
            self._text,
            font=font,
            fill=0,
        )


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
        self._bus = bus
        if bus:
            bus.on("backup:state", self._on_backup_state)
            bus.on("file:cached", self._on_file_cached)
            bus.on("file:uploaded", self._on_file_uploaded)
            bus.on("file:pruned", self._on_file_pruned)

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

    def _on_file_uploaded(self, file=None, **kw):
        self.pending_upload -= 1
        self.uploaded_count += 1
        self.inc_progress()
        self._bus.emit("ui:redraw")

    def _on_file_pruned(self, file=None, **kw):
        self.cached_count -= 1
        self.inc_progress()
        self._bus.emit("ui:redraw")

    def render(self, draw, font, width, height, y_offset=0, bottom_margin=0):
        draw.rectangle([(0, y_offset), (width, height)], fill=255)
        _, _, _, th = draw.textbbox((0, 0), "Xg", font=font)
        line_h = th + self.LINE_SPACING
        x = self.MARGIN_X
        y = y_offset + 4

        draw.text((x, y), f"Status: {self.status}", font=font, fill=0)
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
            if fill > 0:
                draw.rectangle(
                    [(x + 1, bar_y + 1), (x + fill - 1, bar_y + bar_h - 1)], fill=0
                )
            y += bar_h + self.LINE_SPACING

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

            if item.is_branch:
                display_label = f"{item.label} \u25b6"
            elif parent_config_key is not None and self._menu._config is not None:
                current_val = self._menu._config.get(parent_config_key)
                if current_val == item.value:
                    display_label = f"\u25cf {item.label}"
                else:
                    display_label = f"\u25cb {item.label}"
            else:
                display_label = item.label

            if i == self._menu._selected:
                draw.rectangle([(x, y), (width - x, y + line_h)], fill=0)
                draw.text((x + 2, y + 1), display_label, font=font, fill=255)
            else:
                draw.text((x + 2, y + 1), display_label, font=font, fill=0)

            y += line_h


class Display:
    WIDTH = 250
    HEIGHT = 122

    def __init__(self, epd, font):
        self._epd = epd
        self._font = font

    @property
    def font(self):
        return self._font

    def init(self):
        self._epd.init()
        self._epd.Clear(0xFF)

    def init_full(self):
        self.init()

    def sleep(self):
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
    return ImageFont.load_default()

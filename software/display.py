import logging
import time
from PIL import Image, ImageDraw, ImageFont
from contextlib import nullcontext

from backup import State

ICON_SIZE = 7


def _draw_icon_triangle(draw, x, y, size, fill, direction):
    h = w = size
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


logger = logging.getLogger(__name__)


class StatusBar:
    HEIGHT = 16

    def __init__(self, title="Liquorice"):
        self._title = title
        self._wifi = True

    def set_title(self, title: str):
        self._title = title

    def set_wifi(self, connected: bool):
        self._wifi = connected

    def render(self, draw, font, width):
        y = 0
        draw.rectangle([(0, y), (width, y + self.HEIGHT)], fill=255)
        _, _, _, th = draw.textbbox((0, 0), "Xg", font=font)
        draw.text((4, y + (self.HEIGHT - th) // 2), self._title, font=font, fill=0)
        draw.line([(2, y + self.HEIGHT - 1), (width - 2, y + self.HEIGHT - 1)], fill=0)


class Legend:
    HEIGHT = 14

    def __init__(self, text="\u25c0 back  \u25bc/\u25b2 nav  \u25b6 enter"):
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


class LockView:
    LINE_SPACING = 4

    def render(self, draw, font, width, height, y_offset=0, bottom_margin=0):
        draw.rectangle([(0, y_offset), (width, height)], fill=255)
        cx = width // 2
        cy = y_offset + (height - y_offset - bottom_margin) // 2 - 6
        bw, bh = 36, 22
        bx, by = cx - bw // 2, cy - 2
        draw.rectangle([(bx, by), (bx + bw, by + bh)], fill=255, outline=0, width=2)
        draw.rectangle([(bx + 12, by + 8), (bx + 24, by + 16)], fill=0)
        draw.arc([(bx + 8, by - 12), (bx + 28, by + 10)], 180, 0, fill=0, width=2)
        y = by + bh + 8
        text = "Schermo bloccato"
        tw = draw.textbbox((0, 0), text, font=font)[2]
        draw.text(((width - tw) // 2, y), text, font=font, fill=0)


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
        self._sd_available = None
        self._stats = None
        self._error_msg = ""
        self._active_phase = None
        self._paused_phase = None
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

    def resume_phase(self, total: int, absolute: bool):
        """Riprende la barra dal punto in cui era prima della pausa.

        In CACHING il totale e' assoluto (tutti i file della scheda) e non cambia
        con la pausa. Nelle altre fasi il totale che arriva e' il residuo
        (pending da uploadare, file da cancellare o da eliminare dalla cache),
        quindi va risommato a quelli gia' fatti per non ripartire da zero.
        """
        done = self.progress_current
        self.progress_total = total if absolute else total + done
        self.progress_current = min(done, self.progress_total)

    def inc_progress(self):
        if self.progress_current < self.progress_total:
            self.progress_current += 1

    def _on_backup_state(self, state, total=0, reset=False, **kw):
        stats = kw.get("stats")
        error = kw.get("error", "")
        up_to_date = kw.get("up_to_date", False)
        # Ricorda la fase operativa per riusare l'etichetta in PAUSED/RETRYING.
        if state in (State.CACHING, State.UPLOADING, State.REMOTE_CLEANUP, State.PRUNING):
            self._active_phase = state
        elif state == State.IDLE:
            self._active_phase = None
        if state == State.PAUSED:
            # Fase in cui si e' fermato: al resume la barra riparte da qui.
            self._paused_phase = self._active_phase
        if state == State.COMPLETED and up_to_date:
            # Giro a vuoto (nessun file copiato, caricato, cancellato o
            # eliminato): si resta sulla schermata iniziale invece di mostrare
            # un riepilogo vuoto.
            self.status = "Ready"
        else:
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
            self._stats = None
            self._error_msg = ""
            self._paused_phase = None
        if state in (State.IDLE, State.COMPLETED, State.PAUSED, State.ERROR):
            self.refresh()
        if self.status == "Ready":
            # Schermata iniziale: nessun residuo di barra o riepilogo.
            self._stats = None
            self._error_msg = ""
            self.progress_total = 0
            self.progress_current = 0
            self.current_file = ""
            self._paused_phase = None
        elif state in (State.COMPLETED, State.ERROR) and stats is not None:
            self._stats = stats
            self._error_msg = error
        if total:
            if state == self._paused_phase:
                self.resume_phase(total, absolute=(state == State.CACHING))
            else:
                self.set_phase(total)
            self._paused_phase = None
        legend_text = {
            State.IDLE: "\u25c0 menu  \u25b6 backup",
            State.CACHING: "\u25c0 pause",
            State.UPLOADING: "\u25c0 pause",
            State.REMOTE_CLEANUP: "\u25c0 pause",
            State.PRUNING: "\u25c0 pause",
            State.PAUSED: "\u25c0 menu  \u25b6 resume",
            State.RETRYING: "\u25c0 pause",
            State.COMPLETED: "\u25c0 menu  \u25b6 backup",
            State.ERROR: "\u25c0 menu  \u25b6 backup",
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
        # max(): dopo un resume la scansione riparte dal primo file della
        # scheda, ma la barra non deve tornare indietro.
        self.progress_current = max(
            self.progress_current, min(processed, self.progress_total)
        )
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
        self._sd_available = bool(available)
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

        if self._sd_available is None:
            sd_label = "--"
        elif self._sd_available:
            sd_label = "Available"
        else:
            sd_label = "No SD"
        draw.text((x, y), f"SD: {sd_label}", font=font, fill=0)
        y += line_h

        # Schermata Ready: solo Status, WiFi e SD, niente barra ne' conteggi.
        if self.status == "Ready":
            return

        if self.progress_total > 0 and self.status not in ("Done", "Error"):
            bar_y = y
            bar_h = max(4, th - 4)
            bar_w = width - 2 * x
            denom = self.progress_total if self.progress_total else 1
            fill = max(0, min(bar_w, int(bar_w * self.progress_current / denom)))
            draw.rectangle([(x, bar_y), (x + bar_w, bar_y + bar_h)], fill=255, outline=0)
            if fill > 1:
                draw.rectangle(
                    [(x + 1, bar_y + 1), (x + fill - 1, bar_y + bar_h - 1)], fill=0
                )
            y += bar_h + self.LINE_SPACING

            if self.current_file:
                if y + line_h <= height - bottom_margin - 2:
                    draw.text((x, y), self.current_file[:30], font=font, fill=0)
                    y += line_h

            per_phase = None
            if self.status == "Caching files...":
                per_phase = f"Cached: {self.progress_current}/{self.progress_total}"
            elif self.status == "Uploading...":
                per_phase = f"Uploaded: {self.progress_current}/{self.progress_total}"
            elif self.status == "Cleaning remote...":
                per_phase = f"Cleaned: {self.progress_current}/{self.progress_total}"
            elif self.status == "Pruning cache...":
                per_phase = f"Pruned: {self.progress_current}/{self.progress_total}"
            elif self.status in ("Retrying...", "Paused"):
                # In pausa/retry si tiene il conteggio raggiunto, con
                # l'etichetta della fase in cui si e' fermato.
                label = {
                    State.CACHING: "Cached",
                    State.UPLOADING: "Uploaded",
                    State.REMOTE_CLEANUP: "Cleaned",
                    State.PRUNING: "Pruned",
                }.get(self._active_phase, "")
                if label:
                    per_phase = (
                        f"{label}: {self.progress_current}/{self.progress_total}"
                    )

            if per_phase and y + line_h <= height - bottom_margin - 2:
                draw.text((x, y), per_phase, font=font, fill=0)
                y += line_h
            if self.status in ("Caching files...", "Uploading...", "Cleaning remote...", "Pruning cache...", "Retrying...", "Paused"):
                return

        if self.status in ("Done", "Error") and self._stats is not None:
            s = self._stats
            if self.status == "Done":
                # Riepilogo su due righe fisse:
                #   Cached / Pruned   (copiati / eliminati dalla cache)
                #   Uploaded / Removed (caricati / rimossi dal cloud)
                cached = s.get("cached_ok", self.cached_count)
                pruned = s.get("pruned", 0)
                uploaded = s.get("uploaded_ok", self.uploaded_count)
                removed = s.get("remote_deleted", 0)
                stats_lines = [
                    f"Cached: {cached} / Pruned: {pruned}",
                    f"Uploaded: {uploaded} / Removed: {removed}",
                ]
                for line in stats_lines:
                    if y + line_h > height - bottom_margin - 2:
                        break
                    draw.text((x, y), line, font=font, fill=0)
                    y += line_h
                return
            if self.status == "Error":
                co = s.get("cached_ok", 0)
                cf = s.get("cached_failed", 0)
                uo = s.get("uploaded_ok", 0)
                uf = s.get("uploaded_failed", 0)
                draw.text((x, y), f"Cached: {co} ok {cf} err", font=font, fill=0)
                y += line_h
                if y + line_h > height - bottom_margin - 2:
                    return
                draw.text((x, y), f"Upload: {uo} ok {uf} err", font=font, fill=0)
                y += line_h
                if s.get("remote_deleted", 0) and y + line_h <= height - bottom_margin - 2:
                    draw.text((x, y), f"Removed: {s.get('remote_deleted',0)}", font=font, fill=0)
                    y += line_h
                if y + line_h <= height - bottom_margin - 2 and self._error_msg:
                    draw.text((x, y), self._error_msg[:30], font=font, fill=0)
                return


class MenuView:
    MARGIN_X = 4
    LINE_SPACING = 1

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

            icon_right = None
            icon_left = None
            if item.is_branch:
                icon_right = "\u25b6"
            elif parent_config_key is not None and self._menu._config is not None:
                current_val = self._menu._config.get(parent_config_key)
                icon_left = "\u25cf" if current_val == item.value else "\u25cb"

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

            draw.text((cx, y + 1), item.label, font=font, fill=text_fill)
            _, _, lw, _ = draw.textbbox((0, 0), item.label, font=font)
            cx += lw

            if icon_right:
                iy = y + 1 + (th - ICON_SIZE) // 2
                _ICON_DISPATCH[icon_right](draw, cx + 2, iy, ICON_SIZE, text_fill)

            y += line_h


class Display:
    WIDTH = 250
    HEIGHT = 122
    # Un refresh vero dell'e-ink dura ~1-2s. Se init+display tornano subito, il
    # pannello non ha eseguito nulla (BUSY mai alto): tipico di alimentazione o
    # cablaggio del display che non fanno contatto.
    MIN_REFRESH_SECONDS = 0.3
    # Ogni quanti render riprovare il recupero quando il pannello e' muto.
    RECOVERY_EVERY = 20
    # Quanto considerare ancora "in refresh" dopo la fine, per coprire il
    # ritardo con cui gpiozero consegna gli eventi dei pulsanti.
    REFRESH_GUARD_SECONDS = 0.35

    def __init__(self, epd, font, io_lock=None, health_check=True):
        self._epd = epd
        self._font = font
        self._initialized = False
        self._io_lock = io_lock
        self._suspended = False
        self._last_frame = None
        self._health_check = health_check
        self._panel_ok = True
        self._silent_renders = 0
        self._refreshing = False
        self._refresh_ended = 0.0

    @property
    def font(self):
        return self._font

    @property
    def refreshing(self):
        """True mentre l'e-ink sta aggiornando: in quella finestra i pin dei
        pulsanti raccolgono disturbi.

        La finestra si estende oltre la fine del refresh perche' il debounce di
        gpiozero consegna l'evento con qualche decina di ms di ritardo.
        """
        if self._refreshing:
            return True
        return (time.monotonic() - self._refresh_ended) < self.REFRESH_GUARD_SECONDS

    @property
    def panel_ok(self):
        return self._panel_ok

    def _lock(self):
        return self._io_lock or nullcontext()

    def init(self):
        with self._lock():
            self._epd.init()
            self._epd.Clear(0xFF)

    def init_full(self):
        with self._lock():
            self._epd.init()
            self._epd.Clear(0xFF)

    def sleep(self):
        with self._lock():
            if not self._suspended:
                self._epd.sleep()

    @property
    def suspended(self):
        return self._suspended

    def suspend(self):
        with self._lock():
            if self._suspended:
                return
            self._epd.sleep()
            self._suspended = True
        logger.info("Display sospeso: coperchio chiuso")

    def resume(self):
        with self._lock():
            if not self._suspended:
                return
            self._suspended = False
            self._epd.init()
            self._initialized = True
        logger.info("Display riattivato: coperchio aperto")

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

    def _push(self, buffer):
        """Invia il frame con la sequenza completa e ritorna la durata del refresh.

        Non si usa init_fast()/display_fast(): su questo pannello la sequenza
        "fast" viene ignorata e lascia il controller piantato con BUSY alto,
        mentre il guadagno era minimo (1.8s contro i ~2s del refresh completo).
        """
        started = time.monotonic()
        self._refreshing = True
        try:
            self._epd.init()
            self._epd.display(buffer)
        finally:
            self._refreshing = False
            self._refresh_ended = time.monotonic()
        return time.monotonic() - started

    def _hard_reset(self):
        """Reset lungo sulla linea RST: sblocca il pannello dopo un refresh fallito.

        Il reset del driver Waveshare tiene RST basso solo 2ms e non basta quando
        il controller si e' piantato.
        """
        try:
            from waveshare_epd import epdconfig
        except ImportError:
            return False
        try:
            epdconfig.digital_write(epdconfig.RST_PIN, 1)
            epdconfig.delay_ms(50)
            epdconfig.digital_write(epdconfig.RST_PIN, 0)
            epdconfig.delay_ms(300)
            epdconfig.digital_write(epdconfig.RST_PIN, 1)
            epdconfig.delay_ms(50)
            return True
        except Exception as error:
            logger.warning("Reset hardware del display non riuscito: %s", error)
            return False

    def _recover(self, buffer):
        """Tenta un reset lungo + refresh completo. True se il pannello risponde."""
        if not self._hard_reset():
            return False
        try:
            elapsed = self._push(buffer)
        except Exception as error:
            logger.warning("Refresh di recupero fallito: %s", error)
            return False
        return elapsed >= self.MIN_REFRESH_SECONDS

    def render_full(self, content_view, status_bar, legend):
        img = self._compose(content_view, status_bar, legend)
        self._last_frame = img
        with self._lock():
            if self._suspended:
                return
            buffer = self._epd.getbuffer(img)
            elapsed = self._push(buffer)
            self._initialized = True
            if not self._health_check:
                return
            if elapsed >= self.MIN_REFRESH_SECONDS:
                if not self._panel_ok:
                    logger.info("Display di nuovo operativo")
                self._panel_ok = True
                self._silent_renders = 0
                return
            self._on_silent_refresh(buffer)

    def _on_silent_refresh(self, buffer):
        """Il pannello ha ignorato il frame: prova a recuperarlo e avvisa."""
        self._silent_renders += 1
        if self._panel_ok:
            logger.warning(
                "Il display non ha eseguito il refresh (BUSY mai attivo): "
                "provo un reset hardware"
            )
        elif self._silent_renders % self.RECOVERY_EVERY:
            return
        if self._recover(buffer):
            logger.info("Display recuperato con il reset hardware")
            self._panel_ok = True
            self._silent_renders = 0
            return
        if self._panel_ok:
            logger.error(
                "Il display e-ink non risponde: l'immagine a schermo resta quella "
                "vecchia. Controlla alimentazione (3.3V/GND) e i fili DIN, CLK, "
                "CS, DC, RST e BUSY; poi togli e ridai corrente alla scatola."
            )
        self._panel_ok = False


def install_busy_timeout(epd, timeout=20.0):
    """Limita l'attesa su BUSY: senza timeout un pannello piantato blocca la UI."""
    try:
        from waveshare_epd import epdconfig
    except ImportError:
        return

    def read_busy():
        started = time.monotonic()
        while epdconfig.digital_read(epd.busy_pin) == 1:
            if time.monotonic() - started > timeout:
                logger.error(
                    "e-Paper BUSY alto da oltre %.0fs: pannello bloccato, proseguo",
                    timeout,
                )
                return
            epdconfig.delay_ms(10)

    epd.ReadBusy = read_busy


def setup_ui_handlers(
    bus, display, status_bar, legend, menu, status_view, menu_view, redraw_fn
):
    active_view = [status_view]

    def on_redraw(**kw):
        redraw_fn()

    def on_menu_opened(**kw):
        active_view[0] = menu_view
        status_bar.set_title(menu.breadcrumb_title)
        legend.set_text("\u25c0 back  \u25bc/\u25b2 nav  \u25b6 enter")
        display.render_full(active_view[0], status_bar, legend)

    def on_menu_closed(**kw):
        active_view[0] = status_view
        status_bar.set_title("Liquorice")
        legend.set_text("\u25c0 menu  \u25b6 backup")
        status_view.refresh()
        display.render_full(active_view[0], status_bar, legend)

    def on_statusbar_update(title=None, wifi=None, **kw):
        if title is not None:
            status_bar.set_title(title)
        if wifi is not None:
            status_bar.set_wifi(wifi)
            for v in active_view:
                if hasattr(v, "_wifi"):
                    v._wifi = wifi

    def on_legend_update(text, **kw):
        legend.set_text(text)

    bus.on("ui:redraw", on_redraw)
    bus.on("menu:opened", on_menu_opened)
    bus.on("menu:closed", on_menu_closed)
    bus.on("ui:statusbar-update", on_statusbar_update)
    bus.on("ui:legend-update", on_legend_update)

    return active_view


def load_font(size=11):
    return ImageFont.load_default(size)

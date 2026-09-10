import logging
import re
import threading
import time
from enum import Enum, auto

from exceptions import TransientError, PermanentError
from eventbus import EventBus

logger = logging.getLogger(__name__)


class State(Enum):
    IDLE = auto()
    CACHING = auto()
    UPLOADING = auto()
    REMOTE_CLEANUP = auto()
    PRUNING = auto()
    COMPLETED = auto()
    PAUSED = auto()
    RETRYING = auto()
    ERROR = auto()


_PHASES = [
    (State.CACHING, "_cache", "copy"),
    (State.UPLOADING, "_uploader", "upload"),
    (State.REMOTE_CLEANUP, "_uploader", "cleanup_remote"),
    (State.PRUNING, "_cache", "prune"),
]

_TIMESTAMP_SUFFIX = re.compile(r"_\d+$")


class Backup:
    def __init__(
        self, cache, uploader, db, bus=None, max_retries=3, retry_delay=5, mode="upload"
    ):
        self._cache = cache
        self._uploader = uploader
        self._next_uploader = None
        self._db = db
        self._bus = bus or EventBus()
        self._max_retries = max_retries
        self._retry_delay = retry_delay
        self._mode = mode
        self._next_mode = mode
        self._state = State.IDLE
        self._resume_state = State.IDLE
        self._cancel = threading.Event()
        self._bus.on("config:set", self._on_config_set)
        if self._cache is not None:
            self._cache._cancel = self._cancel
        if self._uploader is not None:
            self._uploader._cancel = self._cancel

    @property
    def state(self) -> State:
        return self._state

    @property
    def is_active(self) -> bool:
        return self._state in (
            State.CACHING,
            State.UPLOADING,
            State.REMOTE_CLEANUP,
            State.PRUNING,
        )

    def start(self) -> bool:
        if self._state != State.IDLE:
            logger.info("Backup start ignored: state=%s", self._state.name)
            return False

        pending = self._db.count_pending_uploads()

        if self._cache is None and pending == 0:
            logger.info(
                "Backup start ignored: no cache and no pending uploads (pending=%s)",
                pending,
            )
            return False
        self._mode = self._next_mode

        if self._next_uploader is not None:
            self._uploader = self._next_uploader
            self._next_uploader = None

        if self._cache:
            self._cache.prepare_backup()
        self._cancel.clear()
        self._set_state(State.CACHING, reset=True)
        threading.Thread(target=self._run, daemon=True).start()
        return True

    def set_cache(self, cache) -> None:
        self._cache = cache
        if cache is not None:
            cache._cancel = self._cancel

    def set_uploader(self, uploader) -> None:
        # Se un backup è in corso, il cambio scatta al backup successivo.
        if self.is_active or self._state in (State.PAUSED, State.RETRYING):
            self._next_uploader = uploader
            if uploader is not None:
                uploader._cancel = self._cancel
            logger.info("Upload backend will change on the next backup")
            return
        self._uploader = uploader
        self._next_uploader = None
        if uploader is not None:
            uploader._cancel = self._cancel

    def _on_config_set(self, key, value, **kw):
        if key == "mode":
            self._next_mode = value
            logger.info("Backup mode will change to %s on the next backup", value)

    @staticmethod
    def _new_cloud_destination(cloud_dst: str, timestamp: int) -> str:
        base = cloud_dst
        while _TIMESTAMP_SUFFIX.search(base):
            base = _TIMESTAMP_SUFFIX.sub("", base)
        return f"{base}_{timestamp}"

    def pause(self) -> bool:
        if not self.is_active and self._state != State.RETRYING:
            return False
        self._cancel.set()
        self._set_state(State.PAUSED)
        logger.info("Backup paused by user")
        return True

    def resume(self) -> bool:
        if self._state != State.PAUSED:
            return False
        self._cancel.clear()
        self._set_state(self._resume_state)
        threading.Thread(target=self._run, daemon=True).start()
        return True

    def stop(self) -> bool:
        if self._state not in (State.PAUSED, State.COMPLETED, State.ERROR):
            return False
        self._set_state(State.IDLE)
        return True

    def _set_state(self, state: State, **kw):
        if state != self._state:
            old, self._state = self._state, state
            if state == State.PAUSED:
                self._resume_state = old
            logger.info("Backup: %s -> %s", old.name, state.name)
        self._bus.emit("backup:state", state=state, **kw)

    def _get_phase_total(self, state) -> int:
        try:
            if state == State.CACHING:
                return self._cache.count_uncached() if self._cache else 0
            if state == State.UPLOADING:
                return self._db.count_pending_uploads()
            if state == State.REMOTE_CLEANUP:
                return len(self._db.find_marked_for_deletion())
            if state == State.PRUNING:
                return len(self._db.find_uploaded_not_pruned())
        except Exception:
            return 0
        return 0

    @staticmethod
    def _collect_stats(state, obj, stats):
        if state == State.CACHING:
            s = getattr(obj, "last_copy_stats", {})
            stats["cached_ok"] = s.get("ok", 0)
            stats["cached_failed"] = s.get("failed", 0)
        elif state == State.UPLOADING:
            s = getattr(obj, "last_upload_stats", {})
            stats["uploaded_ok"] = s.get("ok", 0)
            stats["uploaded_failed"] = s.get("failed", 0)
        elif state == State.REMOTE_CLEANUP:
            stats["remote_deleted"] = getattr(obj, "last_cleanup_stats", {}).get(
                "ok", 0
            )
        elif state == State.PRUNING:
            stats["pruned"] = getattr(obj, "last_prune_stats", {}).get("ok", 0)

    def _skip_phase(self, state) -> bool:
        if self._mode == "upload" and state == State.REMOTE_CLEANUP:
            return True
        if self._mode == "mirror" and state == State.PRUNING:
            return True
        return False

    def _run_phase(self, state, obj, method_name, stats) -> bool:
        """Esegue una fase con retry+backoff. Ritorna True se l'utente ha messo in pausa."""
        for attempt in range(1, self._max_retries + 1):
            try:
                logger.info("Starting phase %s (%s)", state.name, method_name)
                getattr(obj, method_name)()
                logger.info("Completed phase %s", state.name)
                self._collect_stats(state, obj, stats)
                return False
            except TransientError as e:
                self._collect_stats(state, obj, stats)
                if attempt >= self._max_retries:
                    raise
                wait = self._retry_delay * (2 ** (attempt - 1))
                logger.warning(
                    "%s transient error (attempt %d/%d), retry in %.1fs: %s",
                    state.name,
                    attempt,
                    self._max_retries,
                    wait,
                    e,
                )
                self._set_state(State.RETRYING)
                if self._wait_with_cancel(wait):
                    return True
                self._set_state(state)
            except PermanentError:
                self._collect_stats(state, obj, stats)
                raise
        return False

    def _run(self):
        stats = {
            "cached_ok": 0,
            "cached_failed": 0,
            "uploaded_ok": 0,
            "uploaded_failed": 0,
            "remote_deleted": 0,
            "pruned": 0,
        }
        try:
            target = self._resume_state if self._state == State.PAUSED else self._state
            phase_idx = next(
                (i for i, (state, _, _) in enumerate(_PHASES) if state == target), 0
            )

            for state, obj_attr, method_name in _PHASES[phase_idx:]:
                if self._skip_phase(state):
                    continue
                obj = getattr(self, obj_attr)
                if obj is None:
                    continue

                self._set_state(state, total=self._get_phase_total(state))
                if self._cancel.is_set():
                    self._set_state(State.PAUSED)
                    return

                if self._run_phase(state, obj, method_name, stats):
                    return

                if self._cancel.is_set():
                    self._set_state(State.PAUSED)
                    return

                if (
                    state == State.CACHING
                    and self._mode == "mirror"
                    and self._cache is not None
                    and self._uploader is not None
                ):
                    self._reconcile_mirror()

            up_to_date = not any(
                stats[k]
                for k in (
                    "cached_ok",
                    "uploaded_ok",
                    "cached_failed",
                    "uploaded_failed",
                    "remote_deleted",
                    "pruned",
                )
            )
            self._set_state(State.COMPLETED, stats=stats, up_to_date=up_to_date)

        except (TransientError, PermanentError) as e:
            logger.error("Backup error: %s", e)
            self._set_state(State.ERROR, stats=stats, error=str(e)[:60])
        except Exception as e:
            logger.exception("Unexpected backup error")
            self._set_state(State.ERROR, stats=stats, error=str(e)[:60])

    def _reconcile_mirror(self):
        self._db.mark_deleted_files(
            self._cache.last_seen_paths, self._uploader.cloud_dst
        )

        prefix = self._uploader.cloud_dst
        total = self._db.count_uploaded_for_prefix(prefix)
        marked = self._db.count_marked_for_deletion(prefix)
        if total > 0 and marked >= total:
            logger.warning(
                "Redirect: tutti i %d file remoti cancellati, cambio destinazione",
                total,
            )
            self._db.clear_deletion_marks_for_prefix(prefix)
            new_dst = self._new_cloud_destination(prefix, int(time.time()))
            self._uploader.cloud_dst = new_dst
            self._bus.emit("config:set", key="cloud_dst", value=new_dst)
            logger.info("Nuova destinazione remota: %s", new_dst)

    def handle_key_event(self, key):
        if key in ("RIGHT", "d", "\r", "\n"):
            if self._state == State.IDLE:
                self.start()
            elif self.is_active:
                self.pause()
            elif self._state == State.PAUSED:
                self.resume()
            elif self._state in (State.COMPLETED, State.ERROR):
                self.stop()

    def _wait_with_cancel(self, seconds: float) -> bool:
        steps = max(1, int(seconds / 0.05))
        for _ in range(steps):
            if self._cancel.is_set():
                self._set_state(State.PAUSED)
                return True
            time.sleep(0.05)
        return False

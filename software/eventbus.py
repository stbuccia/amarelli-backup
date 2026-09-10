import logging
from collections import defaultdict

logger = logging.getLogger(__name__)


class EventBus:
    def __init__(self):
        self._handlers = defaultdict(list)

    def on(self, event: str, handler):
        self._handlers[event].append(handler)

    def emit(self, event: str, **data):
        for handler in self._handlers.get(event, []):
            try:
                handler(**data)
            except Exception as e:
                logger.exception("Handler error for '%s': %s", event, e)


bus = EventBus()

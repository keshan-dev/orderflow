"""Run 1 function every few seconds in a background thread."""

import logging
import threading
from collections.abc import Callable

log = logging.getLogger(__name__)


class PeriodicTask:
    def __init__(self, name: str, interval_seconds: float, work: Callable[[], object]) -> None:
        self._name = name
        self._interval = interval_seconds
        self._work = work
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name=name, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        self._thread.join(timeout)

    def _run(self) -> None:
        while not self._stop.wait(self._interval):
            try:
                self._work()
            except Exception:
                # Keep the thread alive; the next round tries again.
                log.error("background task failed", extra={"task": self._name}, exc_info=True)

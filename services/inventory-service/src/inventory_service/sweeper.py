"""Background thread that releases expired stock holds every few seconds."""

import logging
import threading

from inventory_service.reservations import OnRelease, Reservations

log = logging.getLogger(__name__)


class Sweeper:
    def __init__(
        self,
        service: Reservations,
        interval_seconds: float,
        on_result: OnRelease | None = None,
    ) -> None:
        self._service = service
        self._interval = interval_seconds
        self._on_result = on_result
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="hold-sweeper", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        self._thread.join(timeout)

    def sweep_once(self) -> int:
        released = self._service.release_expired(on_result=self._on_result)
        if released:
            log.info("released expired holds", extra={"released": released})
        return released

    def _run(self) -> None:
        while not self._stop.wait(self._interval):
            try:
                self.sweep_once()
            except Exception:
                # Keep the thread alive; the next round tries again.
                log.error("sweeping expired holds failed", exc_info=True)

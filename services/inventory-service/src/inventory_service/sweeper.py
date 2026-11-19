"""Background task that releases expired stock holds every few seconds."""

import logging

from inventory_service.reservations import OnRelease, Reservations
from orderflow_common.background import PeriodicTask

log = logging.getLogger(__name__)


class Sweeper:
    def __init__(
        self,
        service: Reservations,
        interval_seconds: float,
        on_result: OnRelease | None = None,
    ) -> None:
        self._service = service
        self._on_result = on_result
        self._task = PeriodicTask("hold-sweeper", interval_seconds, self.sweep_once)

    def start(self) -> None:
        self._task.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._task.stop(timeout)

    def sweep_once(self) -> int:
        released = self._service.release_expired(on_result=self._on_result)
        if released:
            log.info("released expired holds", extra={"released": released})
        return released

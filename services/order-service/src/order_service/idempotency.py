"""Idempotency-Key handling in Redis, so a retried POST never creates a second order.

idem:{key} holds {"state", "fingerprint", ...} for 24 hours:
- first request:       SET NX -> IN_PROGRESS, then DONE with the stored response
- repeat, finished:    return the stored response again
- repeat, still busy:  409, the client should retry shortly
- same key, new body:  422, the key was reused for a different request
If Redis is down, the unique idempotency_key column in Postgres still blocks duplicates.
"""

import json
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any

import redis

log = logging.getLogger(__name__)

TTL_SECONDS = 24 * 60 * 60


class Begin(Enum):
    NEW = "new"
    IN_PROGRESS = "in_progress"
    REPLAY = "replay"
    MISMATCH = "mismatch"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class BeginResult:
    state: Begin
    status_code: int | None = None
    body: dict[str, Any] | None = None


def _key(idempotency_key: str) -> str:
    return f"idem:{idempotency_key}"


class IdempotencyStore:
    def __init__(self, client: redis.Redis) -> None:
        self._client = client

    def begin(self, idempotency_key: str, fingerprint: str) -> BeginResult:
        marker = json.dumps({"state": "IN_PROGRESS", "fingerprint": fingerprint})
        try:
            if self._client.set(_key(idempotency_key), marker, nx=True, ex=TTL_SECONDS):
                return BeginResult(Begin.NEW)
            raw = self._client.get(_key(idempotency_key))
        except redis.RedisError:
            log.warning("idempotency store unavailable; relying on postgres", exc_info=True)
            return BeginResult(Begin.UNAVAILABLE)
        if raw is None:  # expired between SET and GET: let Postgres decide
            return BeginResult(Begin.UNAVAILABLE)
        stored = json.loads(raw)
        if stored["fingerprint"] != fingerprint:
            return BeginResult(Begin.MISMATCH)
        if stored["state"] == "IN_PROGRESS":
            return BeginResult(Begin.IN_PROGRESS)
        return BeginResult(Begin.REPLAY, stored["status_code"], stored["body"])

    def finish(
        self, idempotency_key: str, fingerprint: str, status_code: int, body: dict[str, Any]
    ) -> None:
        value = json.dumps(
            {"state": "DONE", "fingerprint": fingerprint, "status_code": status_code, "body": body}
        )
        try:
            self._client.set(_key(idempotency_key), value, ex=TTL_SECONDS)
        except redis.RedisError:
            log.warning("could not store idempotent response", exc_info=True)

    def abandon(self, idempotency_key: str) -> None:
        """The request failed before creating anything: let the client try again."""
        try:
            self._client.delete(_key(idempotency_key))
        except redis.RedisError:
            log.warning("could not clear idempotency key", exc_info=True)

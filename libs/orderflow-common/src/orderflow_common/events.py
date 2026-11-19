"""The event envelope, and writing events through the transactional outbox.

Every event has the same envelope:
  {"event_id", "event_type", "order_id", "occurred_at", "version", "payload"}

Services never publish to Kafka directly. They insert an outbox row in the SAME database
transaction as their data change, and Debezium publishes it. aggregatetype picks the topic
("orders" goes to orders.events) and aggregateid (the order_id) becomes the message key.
"""

import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Connection, text

ENVELOPE_VERSION = 1


@dataclass(frozen=True)
class Event:
    event_type: str
    order_id: uuid.UUID
    payload: dict[str, Any]
    event_id: uuid.UUID = field(default_factory=uuid.uuid4)
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    version: int = ENVELOPE_VERSION

    def envelope(self) -> dict[str, Any]:
        return {
            "event_id": str(self.event_id),
            "event_type": self.event_type,
            "order_id": str(self.order_id),
            "occurred_at": self.occurred_at.isoformat(),
            "version": self.version,
            "payload": self.payload,
        }

    @classmethod
    def from_envelope(cls, data: dict[str, Any]) -> "Event":
        """Parse an envelope. Raises ValueError or KeyError if it is malformed."""
        return cls(
            event_type=str(data["event_type"]),
            order_id=uuid.UUID(str(data["order_id"])),
            payload=dict(data["payload"]),
            event_id=uuid.UUID(str(data["event_id"])),
            occurred_at=datetime.fromisoformat(str(data["occurred_at"])),
            version=int(data.get("version", ENVELOPE_VERSION)),
        )


_INSERT_OUTBOX = text(
    """
    INSERT INTO outbox (id, aggregatetype, aggregateid, type, payload, traceparent)
    VALUES (:id, :aggregatetype, :aggregateid, :type, CAST(:payload AS jsonb), :traceparent)
    """
)


def write_outbox(
    conn: Connection, aggregatetype: str, event: Event, traceparent: str | None = None
) -> None:
    """Add the event to the outbox inside the caller's transaction."""
    conn.execute(
        _INSERT_OUTBOX,
        {
            "id": event.event_id,
            "aggregatetype": aggregatetype,
            "aggregateid": str(event.order_id),
            "type": event.event_type,
            "payload": json.dumps(event.envelope()),
            "traceparent": traceparent,
        },
    )


_MARK_PROCESSED = text(
    "INSERT INTO processed_events (event_id) VALUES (:id) ON CONFLICT DO NOTHING RETURNING event_id"
)


def first_time(conn: Connection, event_id: uuid.UUID) -> bool:
    """Record that this event is being handled. False means it was handled before: skip it.

    Call it inside the same transaction as the work, so "handled" and "done" are saved together.
    """
    return conn.execute(_MARK_PROCESSED, {"id": event_id}).first() is not None

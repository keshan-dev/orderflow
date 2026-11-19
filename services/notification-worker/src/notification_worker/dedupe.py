"""Make sure each order gets at most 1 receipt email, even if its job arrives twice.

notified:{order_id} moves through 2 values:
  "sending"  claimed by a worker that is sending right now (expires after CLAIM_SECONDS,
             so a crashed worker cannot block the email forever)
  "sent"     done; kept for 24 hours
If sending fails, the claim is removed so the next try can send.
"""

from enum import Enum

import redis

CLAIM_SECONDS = 120
SENT_SECONDS = 24 * 60 * 60


class Claim(Enum):
    SEND = "send"  # this worker must send now
    DONE = "done"  # already sent: skip
    BUSY = "busy"  # another worker is sending: try again later


def _key(order_id: str) -> str:
    return f"notified:{order_id}"


class EmailDedupe:
    def __init__(self, client: redis.Redis) -> None:
        self._client = client

    def claim(self, order_id: str) -> Claim:
        if self._client.set(_key(order_id), "sending", nx=True, ex=CLAIM_SECONDS):
            return Claim.SEND
        return Claim.DONE if self._client.get(_key(order_id)) == "sent" else Claim.BUSY

    def mark_sent(self, order_id: str) -> None:
        self._client.set(_key(order_id), "sent", ex=SENT_SECONDS)

    def release(self, order_id: str) -> None:
        self._client.delete(_key(order_id))

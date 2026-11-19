"""Turn an order snapshot from an event into a search document."""

from typing import Any

from orderflow_common.events import Event


def to_document(order: dict[str, Any]) -> dict[str, Any]:
    """Fields missing from the snapshot (Debezium drops nulls) are simply left out."""
    items = [
        {
            key: item[key]
            for key in ("product_id", "name", "quantity", "unit_price_cents")
            if item.get(key) is not None
        }
        for item in order.get("items", [])
    ]
    document: dict[str, Any] = {
        "order_id": order["order_id"],
        "status": order["status"],
        "customer_email": order["customer_email"],
        "items": items,
        "product_names": [item["name"] for item in items if "name" in item],
        "created_at": order["created_at"],
        "updated_at": order["updated_at"],
    }
    if order.get("cancel_reason") is not None:
        document["cancel_reason"] = order["cancel_reason"]
    if order.get("total_cents") is not None:
        document["total"] = order["total_cents"] / 100
    return document


def version(event: Event) -> int:
    """The event time in microseconds. Used as the document version, so an older or repeated
    event can never overwrite a newer document (external_gte versioning)."""
    return int(event.occurred_at.timestamp() * 1_000_000)

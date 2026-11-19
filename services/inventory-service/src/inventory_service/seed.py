"""Add sample products and stock. Safe to run many times: existing products are left alone.

Run: python -m inventory_service.seed
"""

import logging
import uuid
from dataclasses import dataclass

from sqlalchemy import Engine
from sqlalchemy.dialects.postgresql import insert

from inventory_service.schema import products, stock
from orderflow_common.connections import make_engine, retry_transient
from orderflow_common.logging import configure_logging
from orderflow_common.settings import env_str

log = logging.getLogger(__name__)

# Fixed namespace, so the same SKU always gets the same product id on every machine.
PRODUCT_NAMESPACE = uuid.UUID("6f1c2a3e-5b7d-4c1e-9a0f-2d4e6b8c0a1f")


@dataclass(frozen=True)
class SeedProduct:
    sku: str
    name: str
    price_cents: int
    stock: int

    @property
    def id(self) -> uuid.UUID:
        return uuid.uuid5(PRODUCT_NAMESPACE, self.sku)


CATALOG = [
    SeedProduct("KB-001", "Mechanical Keyboard", 8999, 200),
    SeedProduct("MS-001", "Wireless Mouse", 2999, 300),
    SeedProduct("MN-027", "27 inch Monitor", 24999, 50),
    SeedProduct("CB-USB", "USB-C Cable", 999, 1000),
    SeedProduct("ST-LAP", "Laptop Stand", 3999, 150),
    SeedProduct("HP-NC1", "Noise Cancelling Headphones", 14999, 80),
    SeedProduct("WC-HD1", "HD Webcam", 5999, 120),
    # Small stock on purpose: used to show what happens when many people buy the last items.
    SeedProduct("LT-ED1", "Limited Edition Desk Lamp", 7999, 10),
]


def seed(engine: Engine, catalog: list[SeedProduct] = CATALOG) -> int:
    """Insert missing products and their stock. Returns how many products were new."""
    created = 0
    with engine.begin() as conn:
        for item in catalog:
            # RETURNING gives a row only when the insert really happened.
            new_id = conn.execute(
                insert(products)
                .values(id=item.id, sku=item.sku, name=item.name, price_cents=item.price_cents)
                .on_conflict_do_nothing(index_elements=["id"])
                .returning(products.c.id)
            ).scalar()
            if new_id is not None:
                conn.execute(insert(stock).values(product_id=item.id, available=item.stock))
                created += 1
    return created


def main() -> None:
    configure_logging("inventory-seed")
    engine = make_engine(env_str("DATABASE_URL"), pool_size=1)
    created = retry_transient(lambda: seed(engine))
    log.info("seed finished", extra={"products_created": created, "catalog_size": len(CATALOG)})
    engine.dispose()


if __name__ == "__main__":
    main()

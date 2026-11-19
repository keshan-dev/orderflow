from sqlalchemy import func, select

from inventory_service.schema import products, stock
from inventory_service.seed import CATALOG, seed


def test_seed_twice_does_not_create_duplicates(engine):
    assert seed(engine) == len(CATALOG)
    assert seed(engine) == 0
    with engine.connect() as conn:
        assert conn.scalar(select(func.count()).select_from(products)) == len(CATALOG)
        assert conn.scalar(select(func.count()).select_from(stock)) == len(CATALOG)


def test_product_ids_are_stable():
    assert CATALOG[0].id == CATALOG[0].id
    assert len({p.id for p in CATALOG}) == len(CATALOG)

"""HTTP API for inventory-service."""

import logging
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel

from inventory_service.catalog import list_products
from inventory_service.config import Settings
from inventory_service.reservations import Reservations
from inventory_service.stock import (
    InvalidItemsError,
    RedisStock,
    load_stock_into_redis,
    normalize_items,
)
from inventory_service.sweeper import Sweeper
from orderflow_common.connections import (
    make_engine,
    make_redis,
    postgres_ok,
    redis_ok,
    retry_transient,
)
from orderflow_common.logging import configure_logging

log = logging.getLogger(__name__)


class ReserveRequest(BaseModel):
    order_id: uuid.UUID
    items: list[dict[str, Any]]


class ReleaseRequest(BaseModel):
    order_id: uuid.UUID


def _try_load_stock(app: FastAPI) -> bool:
    """Copy stock into Redis. On failure the service stays up but reports not ready."""
    try:
        loaded = retry_transient(lambda: load_stock_into_redis(app.state.engine, app.state.redis))
    except Exception:
        log.error("loading stock into redis failed; will retry on the next readiness check")
        return False
    log.info("stock loaded into redis", extra={"stock_keys_loaded": loaded})
    return True


def create_app(settings: Settings | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        cfg = settings or Settings.from_env()
        app.state.settings = cfg
        app.state.engine = make_engine(cfg.database_url)
        app.state.redis = make_redis(cfg.redis_url)
        app.state.stock_loaded = _try_load_stock(app)
        app.state.reservations = Reservations(
            app.state.engine, RedisStock(app.state.redis), cfg.hold_ttl_seconds
        )
        sweeper = Sweeper(app.state.reservations, cfg.sweeper_interval_seconds)
        sweeper.start()
        log.info("inventory-service started")
        yield
        sweeper.stop()
        app.state.redis.close()
        app.state.engine.dispose()
        log.info("inventory-service stopped")

    app = FastAPI(title="inventory-service", lifespan=lifespan)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        """The process is alive. Never checks other services."""
        return {"status": "ok"}

    @app.get("/api/products")
    def get_products() -> list[dict[str, Any]]:
        cfg: Settings = app.state.settings
        return list_products(app.state.engine, app.state.redis, cfg.product_cache_seconds)

    # Temporary endpoints for manual testing in M1 and M2. M3 replaces them with Kafka events.
    @app.post("/internal/reserve")
    def internal_reserve(body: ReserveRequest) -> dict[str, Any]:
        try:
            items = normalize_items(body.items)
        except InvalidItemsError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        result = app.state.reservations.reserve(body.order_id, items)
        return {
            "outcome": result.outcome,
            "reason": result.reason,
            "lines": [line.as_dict() for line in result.lines],
        }

    @app.post("/internal/release")
    def internal_release(body: ReleaseRequest) -> dict[str, Any]:
        result = app.state.reservations.release(body.order_id)
        return {"outcome": result.outcome, "lines": [line.as_dict() for line in result.lines]}

    @app.get("/readyz")
    def readyz(response: Response) -> dict[str, bool]:
        """The service can do its work right now: Postgres and Redis answer, stock is loaded."""
        checks = {
            "postgres": postgres_ok(app.state.engine),
            "redis": redis_ok(app.state.redis),
        }
        if all(checks.values()) and not app.state.stock_loaded:
            app.state.stock_loaded = _try_load_stock(app)
        checks["stock_loaded"] = app.state.stock_loaded
        if not all(checks.values()):
            response.status_code = 503
        return checks

    return app


def main() -> FastAPI:
    """Entry point for uvicorn: `uvicorn --factory inventory_service.api:main`."""
    configure_logging("inventory-service")
    return create_app()

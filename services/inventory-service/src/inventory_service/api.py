"""HTTP API for inventory-service."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Response

from inventory_service.catalog import list_products
from inventory_service.config import Settings
from orderflow_common.connections import make_engine, make_redis, postgres_ok, redis_ok
from orderflow_common.logging import configure_logging

log = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        cfg = settings or Settings.from_env()
        app.state.settings = cfg
        app.state.engine = make_engine(cfg.database_url)
        app.state.redis = make_redis(cfg.redis_url)
        log.info("inventory-service started")
        yield
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

    @app.get("/readyz")
    def readyz(response: Response) -> dict[str, bool]:
        """The service can do its work right now: Postgres and Redis answer."""
        checks = {
            "postgres": postgres_ok(app.state.engine),
            "redis": redis_ok(app.state.redis),
        }
        if not all(checks.values()):
            response.status_code = 503
        return checks

    return app


def main() -> FastAPI:
    """Entry point for uvicorn: `uvicorn --factory inventory_service.api:main`."""
    configure_logging("inventory-service")
    return create_app()

"""HTTP API for order-service."""

import logging
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any

from fastapi import FastAPI, Header, Response
from pydantic import BaseModel, Field

from order_service.config import Settings
from order_service.orders import NewOrder, create_order
from orderflow_common.connections import make_engine, make_redis, postgres_ok, redis_ok
from orderflow_common.logging import configure_logging

log = logging.getLogger(__name__)


class OrderItemIn(BaseModel):
    product_id: uuid.UUID
    quantity: int = Field(gt=0, le=100)


class CreateOrderIn(BaseModel):
    customer_email: str = Field(max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    items: list[OrderItemIn] = Field(min_length=1, max_length=50)

    def to_new_order(self) -> NewOrder:
        return NewOrder.build(self.customer_email, [(i.product_id, i.quantity) for i in self.items])


def create_app(settings: Settings | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        cfg = settings or Settings.from_env()
        app.state.settings = cfg
        app.state.engine = make_engine(cfg.database_url)
        app.state.redis = make_redis(cfg.redis_url)
        log.info("order-service started")
        yield
        app.state.redis.close()
        app.state.engine.dispose()
        log.info("order-service stopped")

    app = FastAPI(title="order-service", lifespan=lifespan)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        """The process is alive. Never checks other services."""
        return {"status": "ok"}

    @app.post("/api/orders", status_code=202)
    def post_order(
        body: CreateOrderIn,
        response: Response,
        idempotency_key: Annotated[str, Header(min_length=1, max_length=100)],
    ) -> dict[str, Any]:
        result = create_order(app.state.engine, idempotency_key, body.to_new_order())
        response.headers["Location"] = f"/api/orders/{result.order_id}"
        return {"order_id": str(result.order_id), "status": "PENDING"}

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
    """Entry point for uvicorn: `uvicorn --factory order_service.api:main`."""
    configure_logging("order-service")
    return create_app()

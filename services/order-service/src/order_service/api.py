"""HTTP API for order-service."""

import logging
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any

from fastapi import FastAPI, Header, HTTPException, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from order_service.config import Settings
from order_service.idempotency import Begin, IdempotencyStore
from order_service.orders import NewOrder, create_order, get_order
from orderflow_common.connections import make_engine, make_redis, postgres_ok, redis_ok
from orderflow_common.logging import configure_logging

log = logging.getLogger(__name__)

MAX_KEY_LENGTH = 100


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
        app.state.idempotency = IdempotencyStore(app.state.redis)
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
        idempotency_key: Annotated[str | None, Header()] = None,
    ) -> JSONResponse:
        if not idempotency_key or len(idempotency_key) > MAX_KEY_LENGTH:
            raise HTTPException(
                400, f"Idempotency-Key header is required (1 to {MAX_KEY_LENGTH} chars)"
            )
        new_order = body.to_new_order()
        fingerprint = new_order.fingerprint()
        store: IdempotencyStore = app.state.idempotency

        begin = store.begin(idempotency_key, fingerprint)
        if begin.state is Begin.MISMATCH:
            raise HTTPException(422, "Idempotency-Key was already used for a different request")
        if begin.state is Begin.IN_PROGRESS:
            raise HTTPException(
                409, "the first request with this key is still running", {"Retry-After": "1"}
            )
        if begin.state is Begin.REPLAY:
            return _order_response(begin.status_code or 202, begin.body or {}, replayed=True)

        try:
            result = create_order(app.state.engine, idempotency_key, new_order)
        except Exception:
            store.abandon(idempotency_key)
            raise
        if not result.same_request:
            raise HTTPException(422, "Idempotency-Key was already used for a different request")
        payload = {"order_id": str(result.order_id), "status": "PENDING"}
        store.finish(idempotency_key, fingerprint, 202, payload)
        return _order_response(202, payload, replayed=not result.created)

    @app.get("/api/orders/{order_id}")
    def read_order(order_id: uuid.UUID) -> dict[str, Any]:
        order = get_order(app.state.engine, order_id)
        if order is None:
            raise HTTPException(404, "order not found")
        return order

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


def _order_response(status_code: int, payload: dict[str, Any], replayed: bool) -> JSONResponse:
    headers = {"Location": f"/api/orders/{payload['order_id']}"}
    if replayed:
        headers["Idempotent-Replayed"] = "true"
    return JSONResponse(payload, status_code=status_code, headers=headers)


def main() -> FastAPI:
    """Entry point for uvicorn: `uvicorn --factory order_service.api:main`."""
    configure_logging("order-service")
    return create_app()

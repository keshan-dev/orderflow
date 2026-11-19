"""HTTP API for order-service."""

import logging
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any

from fastapi import FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse
from opensearchpy.exceptions import OpenSearchException
from pydantic import BaseModel, Field

from order_service.config import Settings
from order_service.handlers import SagaHandler
from order_service.idempotency import Begin, IdempotencyStore
from order_service.job_events import JobsFromEvents
from order_service.jobs import make_job_publisher
from order_service.orders import NewOrder, create_order, get_order
from order_service.ratelimit import RateLimiter, client_id
from order_service.search import make_search_client, search_orders
from order_service.timeouts import cancel_timed_out_orders
from orderflow_common.background import PeriodicTask
from orderflow_common.connections import make_engine, make_redis, postgres_ok, redis_ok
from orderflow_common.kafka import EventConsumer
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
        app.state.search = make_search_client(cfg.opensearch_url)
        app.state.rate_limiter = RateLimiter(
            app.state.redis, cfg.rate_limit_capacity, cfg.rate_limit_per_second
        )
        app.state.saga_consumer = EventConsumer(
            cfg.kafka_bootstrap_servers,
            "order-service",
            ["inventory.events", "payments.events"],
            SagaHandler(app.state.engine),
        )
        app.state.saga_consumer.start()
        # Fails at startup for an unknown JOB_BACKEND, before any traffic is accepted.
        publisher = make_job_publisher(cfg.job_backend, cfg.rabbitmq_url)
        app.state.jobs_consumer = EventConsumer(
            cfg.kafka_bootstrap_servers,
            "order-service-jobs",
            ["orders.events"],
            JobsFromEvents(publisher),
        )
        app.state.jobs_consumer.start()
        timeouts = PeriodicTask(
            "payment-timeouts",
            cfg.timeout_check_seconds,
            lambda: cancel_timed_out_orders(app.state.engine, cfg.payment_timeout_seconds),
        )
        timeouts.start()
        log.info("order-service started")
        yield
        timeouts.stop()
        app.state.jobs_consumer.stop()
        publisher.close()
        app.state.saga_consumer.stop()
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
        request: Request,
        idempotency_key: Annotated[str | None, Header()] = None,
    ) -> JSONResponse:
        caller = client_id(dict(request.headers), request.client.host if request.client else None)
        decision = app.state.rate_limiter.check(caller)
        if not decision.allowed:
            log.info("rate limited", extra={"client": caller})
            raise HTTPException(
                429,
                "too many orders, slow down",
                {"Retry-After": str(decision.retry_after_seconds)},
            )
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
        log.info(
            "order accepted" if result.created else "order request repeated",
            extra={"order_id": payload["order_id"], "items": len(new_order.items)},
        )
        return _order_response(202, payload, replayed=not result.created)

    # Declared before /api/orders/{order_id}, so "search" is not read as an order id.
    @app.get("/api/orders/search")
    def search(
        q: Annotated[str, Query(min_length=1, max_length=200)],
        limit: Annotated[int, Query(ge=1, le=100)] = 20,
    ) -> dict[str, Any]:
        cfg: Settings = app.state.settings
        try:
            results = search_orders(app.state.search, cfg.search_index, q, limit)
        except OpenSearchException as exc:
            log.warning("search failed", exc_info=True)
            raise HTTPException(503, "search is unavailable, try again later") from exc
        return {"query": q, "results": results}

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
            "saga_consumer": app.state.saga_consumer.healthy,
            "jobs_consumer": app.state.jobs_consumer.healthy,
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

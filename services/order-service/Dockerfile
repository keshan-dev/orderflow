# Build from the repository root:
#   docker build -f services/order-service/Dockerfile .

# Stage 1: install the service and its dependencies into a virtual environment.
FROM python:3.13.18-slim-trixie AS build
COPY --from=ghcr.io/astral-sh/uv:0.13.9 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
# The whole uv workspace is needed to read the lock file; only this service gets installed.
COPY pyproject.toml uv.lock ./
COPY libs libs
COPY services services
RUN uv sync --frozen --no-dev --no-editable --package order-service

# Stage 2: a small runtime image with only the virtual environment and the migrations.
FROM python:3.13.18-slim-trixie
RUN useradd --system --uid 10001 --no-create-home app
WORKDIR /app
COPY --from=build /app/.venv /app/.venv
COPY services/order-service/alembic.ini ./alembic.ini
COPY services/order-service/migrations ./migrations
ENV PATH=/app/.venv/bin:$PATH PYTHONUNBUFFERED=1
USER app
EXPOSE 8001
CMD ["uvicorn", "--factory", "order_service.api:main", "--host", "0.0.0.0", "--port", "8001", "--no-access-log"]

# Build from the repository root:
#   docker build -f services/search-indexer/Dockerfile .

# Stage 1: install the service and its dependencies into a virtual environment.
FROM python:3.13.18-slim-trixie AS build
COPY --from=ghcr.io/astral-sh/uv:0.13.9 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
# The whole uv workspace is needed to read the lock file; only this service gets installed.
COPY pyproject.toml uv.lock ./
COPY libs libs
COPY services services
RUN uv sync --frozen --no-dev --no-editable --package search-indexer

# Stage 2: a small runtime image with only the virtual environment.
FROM python:3.13.18-slim-trixie
RUN useradd --system --uid 10001 --no-create-home app
WORKDIR /app
COPY --from=build /app/.venv /app/.venv
ENV PATH=/app/.venv/bin:$PATH PYTHONUNBUFFERED=1
USER app
CMD ["python", "-m", "search_indexer"]

"""Read configuration from environment variables.

Every service reads the same generic names (DATABASE_URL, REDIS_URL, ...), so Compose,
Helm, the operator and Terraform can all inject them the same way.
"""

import os


class MissingSettingError(RuntimeError):
    """A required environment variable is not set."""


def env_str(name: str, default: str | None = None) -> str:
    value = os.environ.get(name, default)
    if value is None or value == "":
        raise MissingSettingError(f"environment variable {name} is required")
    return value


def env_int(name: str, default: int | None = None) -> int:
    raw = env_str(name, None if default is None else str(default))
    try:
        return int(raw)
    except ValueError as exc:
        raise MissingSettingError(f"environment variable {name} must be an integer") from exc


def env_float(name: str, default: float | None = None) -> float:
    raw = env_str(name, None if default is None else str(default))
    try:
        return float(raw)
    except ValueError as exc:
        raise MissingSettingError(f"environment variable {name} must be a number") from exc

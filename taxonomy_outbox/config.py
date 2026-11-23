"""Runtime configuration, read exclusively from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_DATABASE_URL = "postgresql+psycopg://outbox:outbox_local_dev@127.0.0.1:55432/outbox"
DEFAULT_REDIS_URL = "redis://127.0.0.1:6379/0"
PUBLISHERS = ("memory", "redis")


def _int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = int(raw)
    except ValueError as exc:  # pragma: no cover - defensive, covered by a unit test
        raise ValueError(f"{name} must be an integer, got {raw!r}") from exc
    if value <= 0:
        raise ValueError(f"{name} must be positive, got {value}")
    return value


def _float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = float(raw)
    except ValueError as exc:  # pragma: no cover - defensive
        raise ValueError(f"{name} must be a number, got {raw!r}") from exc
    if value <= 0:
        raise ValueError(f"{name} must be positive, got {value}")
    return value


@dataclass(frozen=True)
class Settings:
    """Every knob of the service; all values come from the environment."""

    database_url: str = DEFAULT_DATABASE_URL
    publisher: str = "memory"
    redis_url: str = DEFAULT_REDIS_URL
    redis_stream: str = "taxonomy.events"
    outbox_batch_size: int = 100
    outbox_max_attempts: int = 5
    outbox_retry_backoff_seconds: int = 30
    outbox_poll_interval_seconds: float = 2.0

    @classmethod
    def from_env(cls) -> "Settings":
        publisher = (os.getenv("PUBLISHER") or "memory").strip().lower()
        if publisher not in PUBLISHERS:
            raise ValueError(f"PUBLISHER must be one of {PUBLISHERS}, got {publisher!r}")
        return cls(
            database_url=os.getenv("DATABASE_URL") or DEFAULT_DATABASE_URL,
            publisher=publisher,
            redis_url=os.getenv("REDIS_URL") or DEFAULT_REDIS_URL,
            redis_stream=os.getenv("REDIS_STREAM") or "taxonomy.events",
            outbox_batch_size=_int("OUTBOX_BATCH_SIZE", 100),
            outbox_max_attempts=_int("OUTBOX_MAX_ATTEMPTS", 5),
            outbox_retry_backoff_seconds=_int("OUTBOX_RETRY_BACKOFF_SECONDS", 30),
            outbox_poll_interval_seconds=_float("OUTBOX_POLL_INTERVAL_SECONDS", 2.0),
        )

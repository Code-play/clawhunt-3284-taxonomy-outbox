"""Transport adapters used by the relay.

``InMemoryPublisher`` is for tests and local runs; ``FanoutPublisher`` delivers
straight to in-process consumers; ``RedisStreamPublisher`` appends each event to
a Redis Stream (the production transport).  Consumers read at least once, so the
application-level idempotency ledger in ``consumers/base.py`` is what makes
delivery effectively once.
"""

from __future__ import annotations

import json
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class EventPublisher(Protocol):
    def publish(self, envelope: dict[str, Any]) -> None:  # pragma: no cover - protocol
        ...


class InMemoryPublisher:
    """Collects published envelopes; used by tests and dry runs."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def publish(self, envelope: dict[str, Any]) -> None:
        self.events.append(envelope)


class FanoutPublisher:
    """Delivers each envelope to every subscribed in-process consumer."""

    def __init__(self) -> None:
        self.delivered: list[dict[str, Any]] = []
        self.consumers: list[Any] = []

    def subscribe(self, consumer: Any) -> None:
        self.consumers.append(consumer)

    def publish(self, envelope: dict[str, Any]) -> None:
        self.delivered.append(envelope)
        for consumer in list(self.consumers):
            consumer.handle(envelope)


class RedisStreamPublisher:
    """Production transport: one entry per event on a Redis Stream."""

    def __init__(self, url: str, stream: str, *, maxlen: int = 100_000) -> None:
        import redis  # imported lazily: the redis extra is optional

        self._client = redis.Redis.from_url(url, decode_responses=True)
        self._stream = stream
        self._maxlen = maxlen

    def publish(self, envelope: dict[str, Any]) -> None:
        self._client.xadd(
            self._stream,
            {
                "event_id": str(envelope["event_id"]),
                "event_type": str(envelope["event_type"]),
                "event": json.dumps(envelope, separators=(",", ":"), sort_keys=True),
            },
            maxlen=self._maxlen,
            approximate=True,
        )


def build_publisher(settings: Any) -> EventPublisher:
    """Select the transport from configuration (``memory`` or ``redis``)."""

    if settings.publisher == "memory":
        return InMemoryPublisher()
    if settings.publisher == "redis":
        return RedisStreamPublisher(settings.redis_url, settings.redis_stream)
    raise ValueError(f"unsupported publisher {settings.publisher!r}")

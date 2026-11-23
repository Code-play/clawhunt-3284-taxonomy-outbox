"""Outbox relay: scan pending rows, publish, record the outcome.

Semantics
---------
* at-least-once: a row is marked ``dispatched`` only after the publisher
  accepted it; a crash between publish and commit may republish, which the
  consumer idempotency ledger absorbs;
* ``FOR UPDATE SKIP LOCKED`` lets several relay instances run concurrently;
* permanent failures stop after ``max_attempts`` and keep the last error for
  operators, instead of retrying a poison event forever.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from ..models.base import utcnow
from ..models.outbox import OutboxEvent, OutboxStatus
from .publisher import EventPublisher


@dataclass(frozen=True)
class RelayResult:
    scanned: int = 0
    published: int = 0
    failed: int = 0


class OutboxRelay:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        publisher: EventPublisher,
        *,
        batch_size: int = 100,
        max_attempts: int = 5,
        retry_backoff_seconds: int = 30,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self.session_factory = session_factory
        self.publisher = publisher
        self.batch_size = batch_size
        self.max_attempts = max_attempts
        self.retry_backoff_seconds = retry_backoff_seconds
        self.clock = clock

    def publish_pending(self) -> RelayResult:
        """Publish at most ``batch_size`` due rows and return the counters."""

        now = self.clock()
        published = 0
        failed = 0
        with self.session_factory() as session:
            rows = (
                session.execute(
                    select(OutboxEvent)
                    .where(
                        OutboxEvent.status == OutboxStatus.PENDING,
                        OutboxEvent.available_at <= now,
                    )
                    .order_by(OutboxEvent.occurred_at, OutboxEvent.id)
                    .limit(self.batch_size)
                    .with_for_update(skip_locked=True)
                )
                .scalars()
                .all()
            )
            for row in rows:
                try:
                    self.publisher.publish(dict(row.payload))
                except Exception as exc:  # noqa: BLE001 - recorded and retried, never swallowed silently
                    row.attempts += 1
                    row.last_error = f"{type(exc).__name__}: {exc}"[:1000]
                    if row.attempts >= self.max_attempts:
                        row.status = OutboxStatus.FAILED
                    else:
                        row.available_at = now + timedelta(
                            seconds=self.retry_backoff_seconds * row.attempts
                        )
                    failed += 1
                else:
                    row.status = OutboxStatus.DISPATCHED
                    row.dispatched_at = now
                    published += 1
            session.commit()
        return RelayResult(scanned=len(rows), published=published, failed=failed)

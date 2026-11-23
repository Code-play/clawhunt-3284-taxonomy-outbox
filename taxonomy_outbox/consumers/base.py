"""Shared consumer plumbing: idempotent delivery ledger."""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session, sessionmaker

from ..models.consumer import ConsumerDelivery


class BaseConsumer(ABC):
    """Consumes tag lifecycle events exactly once per ``(consumer, event_id)``.

    Subclasses implement :meth:`apply`.  The delivery ledger insert and the
    projection write share one transaction, so a crash leaves neither half
    behind and the redelivered event is retried.
    """

    name: str = "base"

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def handle(self, envelope: Mapping[str, Any]) -> bool:
        """Apply one event; returns ``False`` for an already processed event."""

        event_id = uuid.UUID(str(envelope["event_id"]))
        org_id = uuid.UUID(str(envelope["org_id"]))
        site_id = uuid.UUID(str(envelope["site_id"]))
        with self.session_factory.begin() as session:
            inserted = session.execute(
                pg_insert(ConsumerDelivery)
                .values(
                    id=uuid.uuid4(),
                    consumer_name=self.name,
                    event_id=event_id,
                    org_id=org_id,
                    site_id=site_id,
                )
                .on_conflict_do_nothing(index_elements=["consumer_name", "event_id"])
                .returning(ConsumerDelivery.id)
            ).scalar_one_or_none()
            if inserted is None:
                return False
            self.apply(session, envelope)
            return True

    @abstractmethod
    def apply(self, session: Session, envelope: Mapping[str, Any]) -> None:
        """Write this consumer's projection for the event."""

    # ------------------------------------------------------------------ utils

    @staticmethod
    def _event_time(envelope: Mapping[str, Any]) -> datetime:
        return datetime.fromisoformat(str(envelope["occurred_at"]))

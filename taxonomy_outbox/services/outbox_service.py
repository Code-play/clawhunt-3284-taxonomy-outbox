"""Write-side half of the transactional outbox.

The writer only ever adds a row to the caller's current transaction.  It never
commits: commit (or rollback) belongs to the same business transaction that
mutated the tag, which is what guarantees "no event for a rolled-back change".
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from ..events.schemas import EventEnvelope
from ..models.outbox import OutboxEvent, OutboxStatus


class OutboxWriter:
    def __init__(self, session: Session) -> None:
        self.session = session

    def enqueue(self, envelope: EventEnvelope) -> OutboxEvent:
        """Append the envelope to the outbox inside the caller's transaction."""

        row = OutboxEvent(
            id=envelope.event_id,
            org_id=envelope.org_id,
            site_id=envelope.site_id,
            aggregate_type=envelope.aggregate_type,
            aggregate_id=envelope.aggregate_id,
            aggregate_version=envelope.aggregate_version,
            event_type=envelope.event_type,
            event_version=envelope.event_version,
            payload=envelope.model_dump(mode="json"),
            status=OutboxStatus.PENDING,
            occurred_at=envelope.occurred_at,
            available_at=envelope.occurred_at,
        )
        self.session.add(row)
        # Flush now so a duplicate aggregate version or a constraint violation
        # surfaces inside the business transaction instead of at commit time.
        self.session.flush()
        return row

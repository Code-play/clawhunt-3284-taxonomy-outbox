"""Transactional outbox table carrying tag lifecycle events."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, Index, Integer, JSON, String, Text, Uuid, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, utcnow

JSONType = JSON().with_variant(JSONB(), "postgresql")


class OutboxStatus:
    PENDING = "pending"
    DISPATCHED = "dispatched"
    FAILED = "failed"


class OutboxEvent(Base):
    """One row per event, written in the same transaction as the business change.

    The full event envelope (see ``docs/event-structure.md``) is stored in
    ``payload``; the indexed columns duplicate the routing keys so the relay can
    scan and the audit can query without touching JSON.
    """

    __tablename__ = "outbox_event"
    __table_args__ = (
        CheckConstraint("status IN ('pending','dispatched','failed')", name="ck_outbox_event_status"),
        CheckConstraint("attempts >= 0", name="ck_outbox_event_attempts"),
        Index(
            "uq_outbox_event_aggregate_version",
            "aggregate_type",
            "aggregate_id",
            "aggregate_version",
            "event_type",
            unique=True,
        ),
        Index(
            "ix_outbox_event_pending",
            "status",
            "available_at",
            postgresql_where=text("status = 'pending'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    site_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    aggregate_type: Mapped[str] = mapped_column(String(64), nullable=False)
    aggregate_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    aggregate_version: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    event_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default=text("1"))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=OutboxStatus.PENDING)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, server_default=text("now()")
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, server_default=text("now()")
    )
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, server_default=text("now()")
    )

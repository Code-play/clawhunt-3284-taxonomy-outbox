"""Idempotency ledger shared by every example consumer."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, String, UniqueConstraint, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, utcnow


class ConsumerDelivery(Base):
    """``(consumer_name, event_id)`` is unique: a redelivered event is ignored."""

    __tablename__ = "consumer_delivery"
    __table_args__ = (
        UniqueConstraint("consumer_name", "event_id", name="uq_consumer_delivery_event"),
        Index("ix_consumer_delivery_processed_at", "processed_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    consumer_name: Mapped[str] = mapped_column(String(64), nullable=False)
    event_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    org_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    site_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, server_default=text("now()")
    )

"""Stub projections maintained by the two example consumers.

They stand in for the real search-index and matching-engine stores: the ticket
allows interface stubs / mocks first, and these tables make the consumer side
re-runnable and assertable in tests.  The README documents the integration
points that would replace them.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, UniqueConstraint, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, utcnow


class SearchIndexDocument(Base):
    __tablename__ = "search_index_document"
    __table_args__ = (UniqueConstraint("org_id", "site_id", "tag_id", name="uq_search_index_document_tag"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    site_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    tag_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    dictionary_code: Mapped[str] = mapped_column(String(64), nullable=False)
    tag_code: Mapped[str] = mapped_column(String(64), nullable=False)
    tag_name: Mapped[str] = mapped_column(String(128), nullable=False)
    tag_version: Mapped[int] = mapped_column(Integer, nullable=False)
    tag_status: Mapped[str] = mapped_column(String(16), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, server_default=text("now()")
    )


class MatchingTagProjection(Base):
    __tablename__ = "matching_tag_projection"
    __table_args__ = (UniqueConstraint("org_id", "site_id", "tag_id", name="uq_matching_tag_projection_tag"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    site_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    tag_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    dictionary_code: Mapped[str] = mapped_column(String(64), nullable=False)
    tag_code: Mapped[str] = mapped_column(String(64), nullable=False)
    #: after a merge this points at the surviving tag code
    canonical_tag_code: Mapped[str] = mapped_column(String(64), nullable=False)
    tag_version: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, server_default=text("now()")
    )

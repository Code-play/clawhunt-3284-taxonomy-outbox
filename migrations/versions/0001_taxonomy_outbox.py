"""taxonomy dictionaries, tags, outbox events and consumer projections

Revision ID: 0001_taxonomy_outbox
Revises:
Create Date: 2026-11-23

Creates the dictionary/tag tables of the "Dictionary & Tag Center" module, the
transactional outbox table that carries tag lifecycle events, and the two
stub projections used by the example consumers (search index and matching
engine) plus their idempotency ledger.

All business tables follow the platform convention: id (UUID), org_id, site_id,
created_at, created_by, updated_at, deleted_at (soft delete).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001_taxonomy_outbox"
down_revision = None
branch_labels = None
depends_on = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    ]


def upgrade() -> None:
    op.create_table(
        "taxonomy_dictionary",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("site_id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("status", sa.String(length=16), nullable=False, server_default=sa.text("'active'")),
        *_timestamps(),
        sa.CheckConstraint("status IN ('active','archived')", name="ck_taxonomy_dictionary_status"),
    )
    op.create_index(
        "uq_taxonomy_dictionary_code",
        "taxonomy_dictionary",
        ["org_id", "site_id", "code"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.create_table(
        "taxonomy_tag",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("site_id", sa.Uuid(), nullable=False),
        sa.Column("dictionary_id", sa.Uuid(), sa.ForeignKey("taxonomy_dictionary.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default=sa.text("'draft'")),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("merged_into_tag_id", sa.Uuid(), sa.ForeignKey("taxonomy_tag.id", ondelete="SET NULL"), nullable=True),
        *_timestamps(),
        sa.CheckConstraint("status IN ('draft','active','deprecated','merged')", name="ck_taxonomy_tag_status"),
    )
    op.create_index(
        "uq_taxonomy_tag_code",
        "taxonomy_tag",
        ["org_id", "site_id", "dictionary_id", "code"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index("ix_taxonomy_tag_dictionary_id", "taxonomy_tag", ["dictionary_id"], unique=False)

    op.create_table(
        "outbox_event",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("site_id", sa.Uuid(), nullable=False),
        sa.Column("aggregate_type", sa.String(length=64), nullable=False),
        sa.Column("aggregate_id", sa.Uuid(), nullable=False),
        sa.Column("aggregate_version", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=128), nullable=False),
        sa.Column("event_version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("status IN ('pending','dispatched','failed')", name="ck_outbox_event_status"),
        sa.CheckConstraint("attempts >= 0", name="ck_outbox_event_attempts"),
    )
    op.create_index(
        "uq_outbox_event_aggregate_version",
        "outbox_event",
        ["aggregate_type", "aggregate_id", "aggregate_version", "event_type"],
        unique=True,
    )
    op.create_index(
        "ix_outbox_event_pending",
        "outbox_event",
        ["status", "available_at"],
        unique=False,
        postgresql_where=sa.text("status = 'pending'"),
    )

    op.create_table(
        "consumer_delivery",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("consumer_name", sa.String(length=64), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("site_id", sa.Uuid(), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("consumer_name", "event_id", name="uq_consumer_delivery_event"),
    )
    op.create_index("ix_consumer_delivery_processed_at", "consumer_delivery", ["processed_at"], unique=False)

    op.create_table(
        "search_index_document",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("site_id", sa.Uuid(), nullable=False),
        sa.Column("tag_id", sa.Uuid(), nullable=False),
        sa.Column("dictionary_code", sa.String(length=64), nullable=False),
        sa.Column("tag_code", sa.String(length=64), nullable=False),
        sa.Column("tag_name", sa.String(length=128), nullable=False),
        sa.Column("tag_version", sa.Integer(), nullable=False),
        sa.Column("tag_status", sa.String(length=16), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("org_id", "site_id", "tag_id", name="uq_search_index_document_tag"),
    )

    op.create_table(
        "matching_tag_projection",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("site_id", sa.Uuid(), nullable=False),
        sa.Column("tag_id", sa.Uuid(), nullable=False),
        sa.Column("dictionary_code", sa.String(length=64), nullable=False),
        sa.Column("tag_code", sa.String(length=64), nullable=False),
        sa.Column("canonical_tag_code", sa.String(length=64), nullable=False),
        sa.Column("tag_version", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("org_id", "site_id", "tag_id", name="uq_matching_tag_projection_tag"),
    )


def downgrade() -> None:
    op.drop_table("matching_tag_projection")
    op.drop_table("search_index_document")
    op.drop_index("ix_consumer_delivery_processed_at", table_name="consumer_delivery")
    op.drop_table("consumer_delivery")
    op.drop_index("ix_outbox_event_pending", table_name="outbox_event")
    op.drop_index("uq_outbox_event_aggregate_version", table_name="outbox_event")
    op.drop_table("outbox_event")
    op.drop_index("ix_taxonomy_tag_dictionary_id", table_name="taxonomy_tag")
    op.drop_index("uq_taxonomy_tag_code", table_name="taxonomy_tag")
    op.drop_table("taxonomy_tag")
    op.drop_index("uq_taxonomy_dictionary_code", table_name="taxonomy_dictionary")
    op.drop_table("taxonomy_dictionary")

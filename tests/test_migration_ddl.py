"""Migration and DDL assertions: the schema enforces the invariants the service relies on."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from taxonomy_outbox.models.outbox import OutboxEvent
from taxonomy_outbox.models.taxonomy import TaxonomyTag
from taxonomy_outbox.services.taxonomy_service import TaxonomyService

ROOT = Path(__file__).resolve().parents[1]

EXPECTED_TABLES = {
    "taxonomy_dictionary",
    "taxonomy_tag",
    "outbox_event",
    "consumer_delivery",
    "search_index_document",
    "matching_tag_projection",
}


def test_database_is_at_alembic_head(engine: Engine) -> None:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    head = ScriptDirectory.from_config(config).get_current_head()
    with engine.connect() as connection:
        current = MigrationContext.configure(connection).get_current_revision()
    assert current == head


def test_expected_tables_and_indexes_exist(engine: Engine) -> None:
    inspector = inspect(engine)
    assert EXPECTED_TABLES <= set(inspector.get_table_names())

    outbox_indexes = {index["name"] for index in inspector.get_indexes("outbox_event")}
    assert {"uq_outbox_event_aggregate_version", "ix_outbox_event_pending"} <= outbox_indexes

    tag_indexes = {index["name"] for index in inspector.get_indexes("taxonomy_tag")}
    assert "uq_taxonomy_tag_code" in tag_indexes

    delivery_indexes = {index["name"] for index in inspector.get_indexes("consumer_delivery")}
    assert "ix_consumer_delivery_processed_at" in delivery_indexes


def test_live_tag_code_unique_index_is_enforced(
    session: Session, dictionary, tenant
) -> None:
    service = TaxonomyService(session)
    service.create_tag(
        org_id=tenant["org_id"],
        site_id=tenant["site_id"],
        dictionary_id=dictionary.id,
        code="ai",
        name="Artificial Intelligence",
    )
    session.commit()

    # bypass the service-level duplicate check to prove the partial unique index exists
    session.add(
        TaxonomyTag(
            org_id=tenant["org_id"],
            site_id=tenant["site_id"],
            dictionary_id=dictionary.id,
            code="ai",
            name="Bypass",
            status="draft",
            version=1,
        )
    )
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()


def test_tag_status_check_constraint_is_enforced(session: Session, dictionary, tenant) -> None:
    session.add(
        TaxonomyTag(
            org_id=tenant["org_id"],
            site_id=tenant["site_id"],
            dictionary_id=dictionary.id,
            code="broken",
            name="Broken",
            status="not-a-status",
            version=1,
        )
    )
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()


def test_outbox_aggregate_version_is_unique(
    session_factory: sessionmaker[Session], make_tag
) -> None:
    tag = make_tag(activate=True)
    now = datetime.now(timezone.utc)
    with session_factory() as session:
        session.add(
            OutboxEvent(
                id=uuid.uuid4(),
                org_id=tag.org_id,
                site_id=tag.site_id,
                aggregate_type="taxonomy_tag",
                aggregate_id=tag.id,
                aggregate_version=tag.version,
                event_type="taxonomy.tag_activated",
                event_version=1,
                payload={"duplicate": True},
                occurred_at=now,
                available_at=now,
            )
        )
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()

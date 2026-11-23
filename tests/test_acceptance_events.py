"""Acceptance criterion 1: all four event types enter the outbox.

Each lifecycle operation is exercised against PostgreSQL; the assertions cover
the outbox row, the validated envelope and every documented payload field.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from taxonomy_outbox.events.registry import (
    ENVELOPE_FIELDS,
    EVENT_TYPE_ACTIVATED,
    EVENT_TYPE_DEPRECATED,
    EVENT_TYPE_MERGED,
    EVENT_TYPE_UPDATED,
    PAYLOAD_FIELDS,
)
from taxonomy_outbox.events.schemas import EventEnvelope
from taxonomy_outbox.models.outbox import OutboxEvent
from taxonomy_outbox.services.taxonomy_service import TaxonomyService

pytestmark = pytest.mark.acceptance


def _events_of_type(session: Session, event_type: str) -> list[OutboxEvent]:
    return list(
        session.execute(
            select(OutboxEvent)
            .where(OutboxEvent.event_type == event_type)
            .order_by(OutboxEvent.occurred_at, OutboxEvent.id)
        )
        .scalars()
        .all()
    )


def _envelope_of_type(session: Session, event_type: str) -> EventEnvelope:
    rows = _events_of_type(session, event_type)
    assert len(rows) == 1, f"expected exactly one {event_type} event, got {len(rows)}"
    assert rows[0].status == "pending"
    return EventEnvelope.model_validate(rows[0].payload)


def test_tag_activated_is_written_to_outbox(session: Session, dictionary, tenant, make_tag) -> None:
    """draft -> active writes taxonomy.tag_activated."""

    tag = make_tag(activate=True)
    assert tag.status == "active"

    envelope = _envelope_of_type(session, EVENT_TYPE_ACTIVATED)
    assert set(envelope.model_dump()) == set(ENVELOPE_FIELDS)
    assert set(envelope.payload.model_dump()) == set(PAYLOAD_FIELDS)
    assert envelope.event_version == 1
    assert envelope.aggregate_id == tag.id
    assert envelope.aggregate_version == tag.version == 2
    assert envelope.payload.dictionary_code == dictionary.code
    assert envelope.payload.tag_code == tag.code
    assert envelope.payload.version == 2
    assert envelope.payload.before is None
    assert envelope.payload.after.tag_status == "active"
    assert envelope.payload.changed_fields == ["status"]
    assert "activated" in envelope.payload.change_summary


def test_tag_updated_is_written_to_outbox(session: Session, tenant, make_tag) -> None:
    """Updating attributes writes taxonomy.tag_updated with a change summary."""

    tag = make_tag(activate=True)
    svc = TaxonomyService(session)
    result = svc.update(
        tag_id=tag.id,
        org_id=tenant["org_id"],
        site_id=tenant["site_id"],
        changes={"name": "Artificial Intelligence (AI)", "description": "AI related tags"},
        expected_version=tag.version,
    )
    assert result is not None
    session.commit()

    envelope = _envelope_of_type(session, EVENT_TYPE_UPDATED)
    assert envelope.aggregate_version == tag.version == 3
    assert envelope.payload.changed_fields == ["description", "name"]
    assert envelope.payload.before is not None
    assert envelope.payload.before.tag_name == "Artificial Intelligence"
    assert envelope.payload.after.tag_name == "Artificial Intelligence (AI)"
    assert "description, name" in envelope.payload.change_summary


def test_tag_deprecated_is_written_to_outbox(session: Session, tenant, make_tag) -> None:
    """active -> deprecated writes taxonomy.tag_deprecated."""

    tag = make_tag(activate=True)
    svc = TaxonomyService(session)
    svc.deprecate(tag_id=tag.id, org_id=tenant["org_id"], site_id=tenant["site_id"])
    session.commit()

    envelope = _envelope_of_type(session, EVENT_TYPE_DEPRECATED)
    assert envelope.aggregate_version == tag.version == 3
    assert envelope.payload.before is not None
    assert envelope.payload.before.tag_status == "active"
    assert envelope.payload.after.tag_status == "deprecated"
    assert envelope.payload.changed_fields == ["status"]
    assert "deprecated" in envelope.payload.change_summary


def test_tag_merged_is_written_to_outbox(session: Session, tenant, make_tag) -> None:
    """Merging a tag writes taxonomy.tag_merged naming the surviving tag."""

    source = make_tag("ml", "Machine Learning", activate=True)
    target = make_tag("ai", "Artificial Intelligence", activate=True)
    svc = TaxonomyService(session)
    svc.merge(
        source_tag_id=source.id,
        target_tag_id=target.id,
        org_id=tenant["org_id"],
        site_id=tenant["site_id"],
    )
    session.commit()

    envelope = _envelope_of_type(session, EVENT_TYPE_MERGED)
    assert envelope.aggregate_id == source.id
    assert envelope.aggregate_version == source.version == 3
    assert envelope.payload.after.tag_status == "merged"
    assert envelope.payload.merged_into is not None
    assert envelope.payload.merged_into.tag_id == target.id
    assert envelope.payload.merged_into.tag_code == target.code
    assert envelope.payload.changed_fields == ["merged_into_tag_id", "status"]
    assert f"merged into '{target.code}'" in envelope.payload.change_summary


def test_all_four_event_types_are_persisted(session: Session, tenant, make_tag) -> None:
    """One lifecycle touching all four operations leaves all four event types in the outbox."""

    svc = TaxonomyService(session)
    updatable = make_tag("data", "Data", activate=True)
    svc.update(
        tag_id=updatable.id,
        org_id=tenant["org_id"],
        site_id=tenant["site_id"],
        changes={"name": "Data & Analytics"},
    )
    deprecated = make_tag("legacy", "Legacy", activate=True)
    svc.deprecate(tag_id=deprecated.id, org_id=tenant["org_id"], site_id=tenant["site_id"])
    merged = make_tag("nlp", "NLP", activate=True)
    target = make_tag("text", "Text", activate=True)
    svc.merge(
        source_tag_id=merged.id,
        target_tag_id=target.id,
        org_id=tenant["org_id"],
        site_id=tenant["site_id"],
    )
    session.commit()

    persisted = {
        row.event_type for row in session.execute(select(OutboxEvent)).scalars().all()
    }
    assert persisted == {
        EVENT_TYPE_ACTIVATED,
        EVENT_TYPE_UPDATED,
        EVENT_TYPE_DEPRECATED,
        EVENT_TYPE_MERGED,
    }
    # every persisted envelope is valid against the published contract
    for row in session.execute(select(OutboxEvent)).scalars().all():
        EventEnvelope.model_validate(row.payload)

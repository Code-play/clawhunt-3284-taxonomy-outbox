"""Counterexamples: rejected or no-op operations must not leave an event behind."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from taxonomy_outbox.models.outbox import OutboxEvent
from taxonomy_outbox.services.errors import (
    DuplicateTagCode,
    InvalidMerge,
    InvalidTagTransition,
    TagNotFound,
    TagVersionConflict,
)
from taxonomy_outbox.services.taxonomy_service import TaxonomyService


def _outbox_count(session: Session) -> int:
    return len(session.execute(select(OutboxEvent)).scalars().all())


def test_deprecating_a_draft_tag_is_rejected_and_emits_nothing(session: Session, tenant, make_tag) -> None:
    tag = make_tag()
    svc = TaxonomyService(session)
    with pytest.raises(InvalidTagTransition):
        svc.deprecate(tag_id=tag.id, org_id=tenant["org_id"], site_id=tenant["site_id"])
    session.rollback()
    assert _outbox_count(session) == 0


def test_activating_twice_is_rejected_and_emits_no_second_event(session: Session, tenant, make_tag) -> None:
    tag = make_tag(activate=True)
    svc = TaxonomyService(session)
    with pytest.raises(InvalidTagTransition):
        svc.activate(tag_id=tag.id, org_id=tenant["org_id"], site_id=tenant["site_id"])
    session.rollback()
    assert _outbox_count(session) == 1


def test_update_without_real_changes_emits_nothing(session: Session, tenant, make_tag) -> None:
    tag = make_tag(activate=True)
    svc = TaxonomyService(session)
    result = svc.update(
        tag_id=tag.id,
        org_id=tenant["org_id"],
        site_id=tenant["site_id"],
        changes={"name": tag.name},
    )
    assert result is None
    session.commit()
    assert _outbox_count(session) == 1  # only the activation event


def test_update_with_unknown_field_is_rejected_and_emits_nothing(session: Session, tenant, make_tag) -> None:
    tag = make_tag(activate=True)
    svc = TaxonomyService(session)
    with pytest.raises(ValueError, match="not updatable"):
        svc.update(
            tag_id=tag.id,
            org_id=tenant["org_id"],
            site_id=tenant["site_id"],
            changes={"code": "changed-code"},
        )
    session.rollback()
    assert _outbox_count(session) == 1


def test_stale_expected_version_is_rejected_and_emits_nothing(session: Session, tenant, make_tag) -> None:
    tag = make_tag(activate=True)
    svc = TaxonomyService(session)
    with pytest.raises(TagVersionConflict):
        svc.update(
            tag_id=tag.id,
            org_id=tenant["org_id"],
            site_id=tenant["site_id"],
            changes={"name": "New name"},
            expected_version=1,
        )
    session.rollback()
    assert _outbox_count(session) == 1


def test_updating_a_deprecated_tag_is_rejected(session: Session, tenant, make_tag) -> None:
    tag = make_tag(activate=True)
    svc = TaxonomyService(session)
    svc.deprecate(tag_id=tag.id, org_id=tenant["org_id"], site_id=tenant["site_id"])
    session.commit()
    with pytest.raises(InvalidTagTransition):
        svc.update(
            tag_id=tag.id,
            org_id=tenant["org_id"],
            site_id=tenant["site_id"],
            changes={"name": "Too late"},
        )
    session.rollback()
    assert _outbox_count(session) == 2  # activation + deprecation, nothing else


def test_merge_into_itself_is_rejected(session: Session, tenant, make_tag) -> None:
    tag = make_tag(activate=True)
    svc = TaxonomyService(session)
    with pytest.raises(InvalidMerge):
        svc.merge(
            source_tag_id=tag.id,
            target_tag_id=tag.id,
            org_id=tenant["org_id"],
            site_id=tenant["site_id"],
        )
    session.rollback()
    assert _outbox_count(session) == 1


def test_merge_into_inactive_target_is_rejected(session: Session, tenant, make_tag) -> None:
    source = make_tag("source", "Source", activate=True)
    draft_target = make_tag("target", "Target")
    svc = TaxonomyService(session)
    with pytest.raises(InvalidMerge):
        svc.merge(
            source_tag_id=source.id,
            target_tag_id=draft_target.id,
            org_id=tenant["org_id"],
            site_id=tenant["site_id"],
        )
    session.rollback()
    assert _outbox_count(session) == 1


def test_merge_across_dictionaries_is_rejected(session: Session, tenant, dictionary, make_tag) -> None:
    svc = TaxonomyService(session)
    other = svc.create_dictionary(
        org_id=tenant["org_id"], site_id=tenant["site_id"], code="region", name="Region"
    )
    source = make_tag("source", "Source", activate=True)
    target = svc.create_tag(
        org_id=tenant["org_id"],
        site_id=tenant["site_id"],
        dictionary_id=other.id,
        code="target",
        name="Target",
    )
    svc.activate(tag_id=target.id, org_id=tenant["org_id"], site_id=tenant["site_id"])
    session.commit()

    with pytest.raises(InvalidMerge):
        svc.merge(
            source_tag_id=source.id,
            target_tag_id=target.id,
            org_id=tenant["org_id"],
            site_id=tenant["site_id"],
        )
    session.rollback()
    assert _outbox_count(session) == 2  # two activations, no merge


def test_cross_tenant_access_is_rejected(session: Session, tenant, make_tag) -> None:
    tag = make_tag()
    svc = TaxonomyService(session)
    with pytest.raises(TagNotFound):
        svc.activate(tag_id=tag.id, org_id=uuid.uuid4(), site_id=tenant["site_id"])
    session.rollback()
    assert _outbox_count(session) == 0


def test_duplicate_tag_code_is_rejected(session: Session, dictionary, tenant) -> None:
    svc = TaxonomyService(session)
    svc.create_tag(
        org_id=tenant["org_id"],
        site_id=tenant["site_id"],
        dictionary_id=dictionary.id,
        code="ai",
        name="Artificial Intelligence",
    )
    session.commit()
    with pytest.raises(DuplicateTagCode):
        svc.create_tag(
            org_id=tenant["org_id"],
            site_id=tenant["site_id"],
            dictionary_id=dictionary.id,
            code="ai",
            name="Duplicate",
        )
    session.rollback()
    assert _outbox_count(session) == 0

"""Acceptance criterion 2: no event is emitted when the business transaction rolls back.

The outbox row lives in the same transaction as the tag change, so a rollback
removes both, and a relay running in another connection can never see the
uncommitted event.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from taxonomy_outbox.models.outbox import OutboxEvent
from taxonomy_outbox.models.taxonomy import TaxonomyTag
from taxonomy_outbox.relay.publisher import InMemoryPublisher
from taxonomy_outbox.relay.relay import OutboxRelay
from taxonomy_outbox.services.taxonomy_service import TaxonomyService

pytestmark = pytest.mark.acceptance


def test_rollback_discards_both_tag_change_and_event(
    session: Session, session_factory: sessionmaker[Session], tenant, make_tag
) -> None:
    tag = make_tag()
    svc = TaxonomyService(session)
    svc.activate(tag_id=tag.id, org_id=tenant["org_id"], site_id=tenant["site_id"])

    # inside the open transaction both halves exist...
    assert len(session.execute(select(OutboxEvent)).scalars().all()) == 1
    assert tag.status == "active"

    session.rollback()

    # ...after the rollback neither is visible to anyone
    with session_factory() as fresh:
        assert fresh.execute(select(OutboxEvent)).scalars().all() == []
        reloaded = fresh.get(TaxonomyTag, tag.id)
        assert reloaded is not None
        assert reloaded.status == "draft"
        assert reloaded.version == 1


def test_uncommitted_event_is_never_published(
    session: Session, session_factory: sessionmaker[Session], tenant, make_tag
) -> None:
    tag = make_tag()
    svc = TaxonomyService(session)
    svc.activate(tag_id=tag.id, org_id=tenant["org_id"], site_id=tenant["site_id"])
    # the tag change and the outbox row are flushed but not committed

    publisher = InMemoryPublisher()
    relay = OutboxRelay(session_factory, publisher)
    result = relay.publish_pending()

    assert result.scanned == 0
    assert result.published == 0
    assert publisher.events == []

    session.rollback()
    with session_factory() as fresh:
        assert fresh.execute(select(OutboxEvent)).scalars().all() == []


def test_committed_change_and_event_become_visible_together(
    session: Session, session_factory: sessionmaker[Session], tenant, make_tag
) -> None:
    tag = make_tag()
    svc = TaxonomyService(session)
    svc.activate(tag_id=tag.id, org_id=tenant["org_id"], site_id=tenant["site_id"])
    session.commit()

    with session_factory() as fresh:
        assert len(fresh.execute(select(OutboxEvent)).scalars().all()) == 1
        assert fresh.get(TaxonomyTag, tag.id).status == "active"

    publisher = InMemoryPublisher()
    assert OutboxRelay(session_factory, publisher).publish_pending().published == 1
    assert len(publisher.events) == 1


def test_later_failure_in_same_transaction_rolls_the_event_back(
    session: Session, session_factory: sessionmaker[Session], tenant, make_tag, dictionary
) -> None:
    """A realistic rollback: the change succeeds, then a later statement violates a constraint."""

    tag = make_tag()
    svc = TaxonomyService(session)
    svc.activate(tag_id=tag.id, org_id=tenant["org_id"], site_id=tenant["site_id"])
    assert len(session.execute(select(OutboxEvent)).scalars().all()) == 1

    # duplicate dictionary code violates the partial unique index inside the same unit of work
    with pytest.raises(IntegrityError):
        svc.create_dictionary(
            org_id=tenant["org_id"],
            site_id=tenant["site_id"],
            code=dictionary.code,
            name="Duplicate industry dictionary",
        )

    session.rollback()

    with session_factory() as fresh:
        assert fresh.execute(select(OutboxEvent)).scalars().all() == []
        assert fresh.get(TaxonomyTag, tag.id).status == "draft"

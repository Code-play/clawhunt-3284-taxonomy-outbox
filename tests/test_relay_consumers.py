"""Relay and consumer behaviour: publish once, retry, idempotency and projections."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from taxonomy_outbox.consumers import MatchingEngineConsumer, SearchIndexConsumer
from taxonomy_outbox.models.outbox import OutboxEvent
from taxonomy_outbox.models.projections import MatchingTagProjection, SearchIndexDocument
from taxonomy_outbox.relay.publisher import FanoutPublisher, InMemoryPublisher
from taxonomy_outbox.relay.relay import OutboxRelay
from taxonomy_outbox.services.taxonomy_service import TaxonomyService


class _BoomPublisher:
    def publish(self, envelope: Mapping[str, Any]) -> None:
        raise RuntimeError("broker unavailable")


def _publish(session_factory: sessionmaker[Session], publisher: Any) -> Any:
    return OutboxRelay(session_factory, publisher).publish_pending()


def test_relay_publishes_a_pending_event_exactly_once(
    session_factory: sessionmaker[Session], make_tag
) -> None:
    tag = make_tag(activate=True)
    publisher = InMemoryPublisher()
    relay = OutboxRelay(session_factory, publisher)

    first = relay.publish_pending()
    assert (first.scanned, first.published, first.failed) == (1, 1, 0)
    assert len(publisher.events) == 1
    assert publisher.events[0]["event_type"] == "taxonomy.tag_activated"
    assert publisher.events[0]["payload"]["tag_code"] == tag.code

    second = relay.publish_pending()
    assert (second.scanned, second.published, second.failed) == (0, 0, 0)
    assert len(publisher.events) == 1

    with session_factory() as fresh:
        row = fresh.execute(select(OutboxEvent)).scalar_one()
        assert row.status == "dispatched"
        assert row.dispatched_at is not None
        assert row.attempts == 0


def test_failed_publish_retries_with_backoff_then_marks_failed(
    session_factory: sessionmaker[Session], make_tag
) -> None:
    make_tag(activate=True)
    relay = OutboxRelay(
        session_factory,
        _BoomPublisher(),
        max_attempts=2,
        retry_backoff_seconds=0,
    )

    first = relay.publish_pending()
    assert (first.scanned, first.published, first.failed) == (1, 0, 1)
    with session_factory() as fresh:
        row = fresh.execute(select(OutboxEvent)).scalar_one()
        assert row.status == "pending"
        assert row.attempts == 1
        assert row.last_error is not None
        assert "broker unavailable" in row.last_error

    second = relay.publish_pending()
    assert (second.scanned, second.published, second.failed) == (1, 0, 1)
    with session_factory() as fresh:
        row = fresh.execute(select(OutboxEvent)).scalar_one()
        assert row.status == "failed"
        assert row.attempts == 2

    assert relay.publish_pending().scanned == 0


def test_consumers_build_their_projections(
    session_factory: sessionmaker[Session], make_tag
) -> None:
    tag = make_tag(activate=True)
    publisher = FanoutPublisher()
    publisher.subscribe(SearchIndexConsumer(session_factory))
    publisher.subscribe(MatchingEngineConsumer(session_factory))
    relay = OutboxRelay(session_factory, publisher)

    assert relay.publish_pending().published == 1

    with session_factory() as fresh:
        document = fresh.execute(select(SearchIndexDocument)).scalar_one()
        assert document.tag_code == tag.code
        assert document.tag_name == tag.name
        assert document.tag_version == tag.version
        projection = fresh.execute(select(MatchingTagProjection)).scalar_one()
        assert projection.tag_code == tag.code
        assert projection.canonical_tag_code == tag.code


def test_deprecation_removes_projections(
    session_factory: sessionmaker[Session], tenant, make_tag
) -> None:
    tag = make_tag(activate=True)
    publisher = FanoutPublisher()
    publisher.subscribe(SearchIndexConsumer(session_factory))
    publisher.subscribe(MatchingEngineConsumer(session_factory))
    relay = OutboxRelay(session_factory, publisher)
    relay.publish_pending()

    with session_factory.begin() as session:
        TaxonomyService(session).deprecate(
            tag_id=tag.id, org_id=tenant["org_id"], site_id=tenant["site_id"]
        )
    assert relay.publish_pending().published == 1

    with session_factory() as fresh:
        assert fresh.execute(select(SearchIndexDocument)).scalars().all() == []
        assert fresh.execute(select(MatchingTagProjection)).scalars().all() == []


def test_merge_remaps_the_matching_canonical_code(
    session_factory: sessionmaker[Session], tenant, make_tag
) -> None:
    source = make_tag("ml", "Machine Learning", activate=True)
    target = make_tag("ai", "Artificial Intelligence", activate=True)
    publisher = FanoutPublisher()
    publisher.subscribe(SearchIndexConsumer(session_factory))
    publisher.subscribe(MatchingEngineConsumer(session_factory))
    relay = OutboxRelay(session_factory, publisher)
    relay.publish_pending()  # both activations

    with session_factory.begin() as session:
        TaxonomyService(session).merge(
            source_tag_id=source.id,
            target_tag_id=target.id,
            org_id=tenant["org_id"],
            site_id=tenant["site_id"],
        )
    assert relay.publish_pending().published == 1

    with session_factory() as fresh:
        projection = fresh.execute(
            select(MatchingTagProjection).where(MatchingTagProjection.tag_id == source.id)
        ).scalar_one()
        assert projection.tag_code == "ml"
        assert projection.canonical_tag_code == "ai"
        # search index drops the merged-away document but keeps the target
        assert (
            fresh.execute(
                select(SearchIndexDocument).where(SearchIndexDocument.tag_id == source.id)
            ).scalars().all()
            == []
        )
        assert fresh.execute(
            select(SearchIndexDocument).where(SearchIndexDocument.tag_id == target.id)
        ).scalar_one()


def test_consumer_ignores_duplicate_delivery(
    session_factory: sessionmaker[Session], make_tag
) -> None:
    make_tag(activate=True)
    publisher = InMemoryPublisher()
    OutboxRelay(session_factory, publisher).publish_pending()
    envelope = publisher.events[0]

    consumer = SearchIndexConsumer(session_factory)
    assert consumer.handle(envelope) is True
    assert consumer.handle(envelope) is False

    with session_factory() as fresh:
        assert len(fresh.execute(select(SearchIndexDocument)).scalars().all()) == 1

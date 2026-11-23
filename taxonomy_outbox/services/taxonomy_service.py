"""Tag lifecycle operations that publish events through the outbox.

Every mutating method:

1. locks the tag (and the parent dictionary) inside the caller's transaction,
2. validates the lifecycle transition,
3. increments the tag version and the dictionary revision,
4. appends the event to the outbox in the *same* transaction,
5. returns the tag row plus the outbox row and the validated envelope.

The method never commits.  The transaction owner (API request or test) decides
whether the business change and its event become visible together.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..events.build import build_tag_event, tag_snapshot
from ..events.registry import (
    EVENT_TYPE_ACTIVATED,
    EVENT_TYPE_DEPRECATED,
    EVENT_TYPE_MERGED,
    EVENT_TYPE_UPDATED,
)
from ..events.schemas import EventEnvelope
from ..models.base import utcnow
from ..models.outbox import OutboxEvent
from ..models.taxonomy import TagStatus, TaxonomyDictionary, TaxonomyTag
from .errors import (
    DictionaryNotFound,
    DuplicateTagCode,
    InvalidMerge,
    InvalidTagTransition,
    TagNotFound,
    TagVersionConflict,
)
from .outbox_service import OutboxWriter

UPDATABLE_TAG_FIELDS: frozenset[str] = frozenset({"name", "description"})


@dataclass(frozen=True)
class MutationResult:
    """A committed-or-not-yet-committed tag change with its outbox event."""

    tag: TaxonomyTag
    event: OutboxEvent
    envelope: EventEnvelope


class TaxonomyService:
    def __init__(
        self,
        session: Session,
        *,
        trace_id: str | None = None,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self.session = session
        self.trace_id = trace_id
        self.clock = clock
        self.outbox = OutboxWriter(session)

    # ------------------------------------------------------------------ reads

    def get_tag(self, *, tag_id: uuid.UUID, org_id: uuid.UUID, site_id: uuid.UUID) -> TaxonomyTag:
        tag = self.session.execute(
            select(TaxonomyTag).where(
                TaxonomyTag.id == tag_id,
                TaxonomyTag.org_id == org_id,
                TaxonomyTag.site_id == site_id,
                TaxonomyTag.deleted_at.is_(None),
            )
        ).scalar_one_or_none()
        if tag is None:
            raise TagNotFound(f"tag {tag_id} not found")
        return tag

    # --------------------------------------------------------------- creation

    def create_dictionary(
        self,
        *,
        org_id: uuid.UUID,
        site_id: uuid.UUID,
        code: str,
        name: str,
        description: str | None = None,
        actor_id: uuid.UUID | None = None,
    ) -> TaxonomyDictionary:
        now = self.clock()
        dictionary = TaxonomyDictionary(
            org_id=org_id,
            site_id=site_id,
            code=code,
            name=name,
            description=description,
            version=1,
            status="active",
            created_at=now,
            updated_at=now,
            created_by=actor_id,
        )
        self.session.add(dictionary)
        self.session.flush()
        return dictionary

    def create_tag(
        self,
        *,
        org_id: uuid.UUID,
        site_id: uuid.UUID,
        dictionary_id: uuid.UUID,
        code: str,
        name: str,
        description: str | None = None,
        actor_id: uuid.UUID | None = None,
    ) -> TaxonomyTag:
        self._lock_dictionary(dictionary_id, org_id, site_id)
        existing = self.session.execute(
            select(TaxonomyTag.id).where(
                TaxonomyTag.org_id == org_id,
                TaxonomyTag.site_id == site_id,
                TaxonomyTag.dictionary_id == dictionary_id,
                TaxonomyTag.code == code,
                TaxonomyTag.deleted_at.is_(None),
            )
        ).first()
        if existing is not None:
            raise DuplicateTagCode(f"tag code {code!r} already exists in dictionary {dictionary_id}")
        now = self.clock()
        tag = TaxonomyTag(
            org_id=org_id,
            site_id=site_id,
            dictionary_id=dictionary_id,
            code=code,
            name=name,
            description=description,
            status=TagStatus.DRAFT.value,
            version=1,
            created_at=now,
            updated_at=now,
            created_by=actor_id,
        )
        self.session.add(tag)
        self.session.flush()
        return tag

    # ------------------------------------------------------------ transitions

    def activate(
        self,
        *,
        tag_id: uuid.UUID,
        org_id: uuid.UUID,
        site_id: uuid.UUID,
        actor_id: uuid.UUID | None = None,
    ) -> MutationResult:
        """draft -> active; emits ``taxonomy.tag_activated``."""

        tag = self._lock_tag(tag_id, org_id, site_id)
        if tag.status != TagStatus.DRAFT.value:
            raise InvalidTagTransition(f"tag {tag.code!r} is {tag.status!r}; only a draft tag can be activated")
        dictionary = self._lock_dictionary(tag.dictionary_id, org_id, site_id)
        tag.status = TagStatus.ACTIVE.value
        return self._finalize(
            event_type=EVENT_TYPE_ACTIVATED,
            tag=tag,
            dictionary=dictionary,
            before=None,
            changed_fields=["status"],
            merged_into=None,
        )

    def update(
        self,
        *,
        tag_id: uuid.UUID,
        org_id: uuid.UUID,
        site_id: uuid.UUID,
        changes: Mapping[str, Any],
        expected_version: int | None = None,
        actor_id: uuid.UUID | None = None,
    ) -> MutationResult | None:
        """Update name/description of a draft or active tag; emits ``taxonomy.tag_updated``.

        Returns ``None`` when nothing actually changed (no event for a no-op).
        """

        unknown = set(changes) - UPDATABLE_TAG_FIELDS
        if unknown:
            raise ValueError(f"fields {sorted(unknown)} are not updatable; allowed: {sorted(UPDATABLE_TAG_FIELDS)}")
        tag = self._lock_tag(tag_id, org_id, site_id)
        if tag.status not in (TagStatus.DRAFT.value, TagStatus.ACTIVE.value):
            raise InvalidTagTransition(f"tag {tag.code!r} is {tag.status!r}; only draft/active tags can be updated")
        if expected_version is not None and expected_version != tag.version:
            raise TagVersionConflict(
                f"tag {tag.code!r} is at version {tag.version}, caller expected {expected_version}"
            )
        before = tag_snapshot(tag)
        changed_fields: list[str] = []
        for field in sorted(changes):
            value = changes[field]
            if field == "name" and (not isinstance(value, str) or not value.strip()):
                raise ValueError("name must be a non-empty string")
            if field == "description" and value is not None and not isinstance(value, str):
                raise ValueError("description must be a string or null")
            if getattr(tag, field) != value:
                setattr(tag, field, value)
                changed_fields.append(field)
        if not changed_fields:
            return None
        dictionary = self._lock_dictionary(tag.dictionary_id, org_id, site_id)
        return self._finalize(
            event_type=EVENT_TYPE_UPDATED,
            tag=tag,
            dictionary=dictionary,
            before=before,
            changed_fields=changed_fields,
            merged_into=None,
        )

    def deprecate(
        self,
        *,
        tag_id: uuid.UUID,
        org_id: uuid.UUID,
        site_id: uuid.UUID,
        actor_id: uuid.UUID | None = None,
    ) -> MutationResult:
        """active -> deprecated; emits ``taxonomy.tag_deprecated``."""

        tag = self._lock_tag(tag_id, org_id, site_id)
        if tag.status != TagStatus.ACTIVE.value:
            raise InvalidTagTransition(f"tag {tag.code!r} is {tag.status!r}; only an active tag can be deprecated")
        dictionary = self._lock_dictionary(tag.dictionary_id, org_id, site_id)
        before = tag_snapshot(tag)
        tag.status = TagStatus.DEPRECATED.value
        return self._finalize(
            event_type=EVENT_TYPE_DEPRECATED,
            tag=tag,
            dictionary=dictionary,
            before=before,
            changed_fields=["status"],
            merged_into=None,
        )

    def merge(
        self,
        *,
        source_tag_id: uuid.UUID,
        target_tag_id: uuid.UUID,
        org_id: uuid.UUID,
        site_id: uuid.UUID,
        actor_id: uuid.UUID | None = None,
    ) -> MutationResult:
        """Fold ``source`` into ``target``; emits ``taxonomy.tag_merged`` for the source."""

        if source_tag_id == target_tag_id:
            raise InvalidMerge("a tag cannot be merged into itself")
        tags = self._lock_tags([source_tag_id, target_tag_id], org_id, site_id)
        source = tags.get(source_tag_id)
        target = tags.get(target_tag_id)
        if source is None or target is None:
            raise TagNotFound(f"merge tags not found in tenant scope: {source_tag_id} -> {target_tag_id}")
        if source.dictionary_id != target.dictionary_id:
            raise InvalidMerge("merge requires both tags to belong to the same dictionary")
        if source.status not in (TagStatus.DRAFT.value, TagStatus.ACTIVE.value, TagStatus.DEPRECATED.value):
            raise InvalidTagTransition(f"tag {source.code!r} is {source.status!r}; it cannot be merged again")
        if target.status != TagStatus.ACTIVE.value:
            raise InvalidMerge(f"merge target {target.code!r} must be active")
        dictionary = self._lock_dictionary(source.dictionary_id, org_id, site_id)
        before = tag_snapshot(source)
        source.status = TagStatus.MERGED.value
        source.merged_into_tag_id = target.id
        merged_into = {"tag_id": target.id, "tag_code": target.code}
        return self._finalize(
            event_type=EVENT_TYPE_MERGED,
            tag=source,
            dictionary=dictionary,
            before=before,
            changed_fields=["merged_into_tag_id", "status"],
            merged_into=merged_into,
        )

    # ---------------------------------------------------------------- helpers

    def _lock_tag(self, tag_id: uuid.UUID, org_id: uuid.UUID, site_id: uuid.UUID) -> TaxonomyTag:
        tag = self.session.execute(
            select(TaxonomyTag)
            .where(
                TaxonomyTag.id == tag_id,
                TaxonomyTag.org_id == org_id,
                TaxonomyTag.site_id == site_id,
                TaxonomyTag.deleted_at.is_(None),
            )
            .with_for_update()
        ).scalar_one_or_none()
        if tag is None:
            raise TagNotFound(f"tag {tag_id} not found")
        return tag

    def _lock_tags(
        self, tag_ids: list[uuid.UUID], org_id: uuid.UUID, site_id: uuid.UUID
    ) -> dict[uuid.UUID, TaxonomyTag]:
        """Lock several tags in a deterministic order to avoid merge deadlocks."""

        rows = (
            self.session.execute(
                select(TaxonomyTag)
                .where(
                    TaxonomyTag.id.in_(tag_ids),
                    TaxonomyTag.org_id == org_id,
                    TaxonomyTag.site_id == site_id,
                    TaxonomyTag.deleted_at.is_(None),
                )
                .order_by(TaxonomyTag.id)
                .with_for_update()
            )
            .scalars()
            .all()
        )
        return {tag.id: tag for tag in rows}

    def _lock_dictionary(
        self, dictionary_id: uuid.UUID, org_id: uuid.UUID, site_id: uuid.UUID
    ) -> TaxonomyDictionary:
        dictionary = self.session.execute(
            select(TaxonomyDictionary)
            .where(
                TaxonomyDictionary.id == dictionary_id,
                TaxonomyDictionary.org_id == org_id,
                TaxonomyDictionary.site_id == site_id,
                TaxonomyDictionary.deleted_at.is_(None),
            )
            .with_for_update()
        ).scalar_one_or_none()
        if dictionary is None:
            raise DictionaryNotFound(f"dictionary {dictionary_id} not found")
        return dictionary

    def _finalize(
        self,
        *,
        event_type: str,
        tag: TaxonomyTag,
        dictionary: TaxonomyDictionary,
        before: Mapping[str, object] | None,
        changed_fields: list[str],
        merged_into: Mapping[str, object] | None,
    ) -> MutationResult:
        now = self.clock()
        tag.version += 1
        tag.updated_at = now
        dictionary.version += 1

        summary = self._summarize(event_type, tag, dictionary, changed_fields, merged_into)
        envelope = build_tag_event(
            event_id=uuid.uuid4(),
            event_type=event_type,
            occurred_at=now,
            dictionary=dictionary,
            tag=tag,
            before=before,
            changed_fields=changed_fields,
            change_summary=summary,
            merged_into=merged_into,
            trace_id=self.trace_id,
        )
        row = self.outbox.enqueue(envelope)
        return MutationResult(tag=tag, event=row, envelope=envelope)

    @staticmethod
    def _summarize(
        event_type: str,
        tag: TaxonomyTag,
        dictionary: TaxonomyDictionary,
        changed_fields: list[str],
        merged_into: Mapping[str, object] | None,
    ) -> str:
        if event_type == EVENT_TYPE_ACTIVATED:
            return f"Tag '{tag.code}' activated in dictionary '{dictionary.code}' (version {tag.version})."
        if event_type == EVENT_TYPE_UPDATED:
            fields = ", ".join(changed_fields)
            return (
                f"Tag '{tag.code}' updated in dictionary '{dictionary.code}': "
                f"{fields} (version {tag.version})."
            )
        if event_type == EVENT_TYPE_DEPRECATED:
            return f"Tag '{tag.code}' deprecated in dictionary '{dictionary.code}' (version {tag.version})."
        if event_type == EVENT_TYPE_MERGED:
            target = dict(merged_into or {}).get("tag_code", "<unknown>")
            return (
                f"Tag '{tag.code}' merged into '{target}' in dictionary "
                f"'{dictionary.code}' (version {tag.version})."
            )
        raise ValueError(f"unsupported event type {event_type!r}")

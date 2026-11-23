"""Build the wire envelope for one tag lifecycle change."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Mapping

from ..models.taxonomy import TaxonomyDictionary, TaxonomyTag
from .registry import EVENT_VERSION
from .schemas import EventEnvelope, MergedInto, TagChangePayload, TagSnapshot


def tag_snapshot(tag: TaxonomyTag) -> dict[str, object]:
    """Project a tag row onto the documented snapshot fields."""

    return {
        "tag_id": tag.id,
        "tag_code": tag.code,
        "tag_name": tag.name,
        "tag_status": tag.status,
        "tag_version": tag.version,
    }


def build_tag_event(
    *,
    event_id: uuid.UUID,
    event_type: str,
    occurred_at: datetime,
    dictionary: TaxonomyDictionary,
    tag: TaxonomyTag,
    before: Mapping[str, object] | None,
    changed_fields: list[str],
    change_summary: str,
    merged_into: Mapping[str, object] | None,
    trace_id: str | None,
) -> EventEnvelope:
    """Assemble and validate the envelope; validation failures are programming errors."""

    payload = TagChangePayload(
        dictionary_id=dictionary.id,
        dictionary_code=dictionary.code,
        dictionary_version=dictionary.version,
        tag_id=tag.id,
        tag_code=tag.code,
        tag_version=tag.version,
        tag_status=tag.status,
        version=tag.version,
        change_summary=change_summary,
        changed_fields=list(changed_fields),
        before=TagSnapshot(**before) if before is not None else None,
        after=TagSnapshot(**tag_snapshot(tag)),
        merged_into=MergedInto(**merged_into) if merged_into is not None else None,
    )
    return EventEnvelope(
        event_id=event_id,
        event_type=event_type,
        event_version=EVENT_VERSION,
        occurred_at=occurred_at,
        org_id=tag.org_id,
        site_id=tag.site_id,
        aggregate_version=tag.version,
        aggregate_id=tag.id,
        trace_id=trace_id,
        payload=payload,
    )

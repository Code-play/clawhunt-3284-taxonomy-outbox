"""Generate the documented event examples from the real envelope builder.

Run ``python examples/build_examples.py`` after changing the event contract; the
doc test validates the generated files against the Pydantic schema, so the
examples can never drift from the code.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from taxonomy_outbox.events.build import build_tag_event, tag_snapshot
from taxonomy_outbox.events.registry import (
    EVENT_TYPE_ACTIVATED,
    EVENT_TYPE_DEPRECATED,
    EVENT_TYPE_MERGED,
    EVENT_TYPE_UPDATED,
)
from taxonomy_outbox.models.taxonomy import TaxonomyDictionary, TaxonomyTag

OUT_DIR = Path(__file__).resolve().parents[1] / "docs" / "examples"

ORG_ID = uuid.UUID("00000000-0000-4000-8000-000000000001")
SITE_ID = uuid.UUID("00000000-0000-4000-8000-000000000002")
DICTIONARY_ID = uuid.UUID("00000000-0000-4000-8000-000000000010")
TAG_ID = uuid.UUID("00000000-0000-4000-8000-000000000020")
TARGET_TAG_ID = uuid.UUID("00000000-0000-4000-8000-000000000021")
TRACE_ID = "demo-trace-0001"

NOW = datetime(2026, 1, 15, 8, 30, 0, tzinfo=timezone.utc)


def _dictionary(version: int) -> TaxonomyDictionary:
    return TaxonomyDictionary(
        id=DICTIONARY_ID,
        org_id=ORG_ID,
        site_id=SITE_ID,
        code="industry",
        name="Industry",
        description="Industry vocabulary shared by matching and search",
        version=version,
        status="active",
    )


def _tag(*, version: int, status: str, name: str = "Artificial Intelligence") -> TaxonomyTag:
    return TaxonomyTag(
        id=TAG_ID,
        org_id=ORG_ID,
        site_id=SITE_ID,
        dictionary_id=DICTIONARY_ID,
        code="ai",
        name=name,
        description="Tags about artificial intelligence",
        status=status,
        version=version,
    )


def _write(filename: str, payload: dict) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / filename).write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def build() -> None:
    activated = build_tag_event(
        event_id=uuid.UUID("00000000-0000-4000-8000-000000000101"),
        event_type=EVENT_TYPE_ACTIVATED,
        occurred_at=NOW,
        dictionary=_dictionary(version=11),
        tag=_tag(version=2, status="active"),
        before=None,
        changed_fields=["status"],
        change_summary="Tag 'ai' activated in dictionary 'industry' (version 2).",
        merged_into=None,
        trace_id=TRACE_ID,
    )

    before_update = _tag(version=2, status="active")
    updated = build_tag_event(
        event_id=uuid.UUID("00000000-0000-4000-8000-000000000102"),
        event_type=EVENT_TYPE_UPDATED,
        occurred_at=NOW,
        dictionary=_dictionary(version=12),
        tag=_tag(version=3, status="active", name="Artificial Intelligence & ML"),
        before=tag_snapshot(before_update),
        changed_fields=["description", "name"],
        change_summary="Tag 'ai' updated in dictionary 'industry': description, name (version 3).",
        merged_into=None,
        trace_id=TRACE_ID,
    )

    before_deprecate = _tag(version=3, status="active", name="Artificial Intelligence & ML")
    deprecated = build_tag_event(
        event_id=uuid.UUID("00000000-0000-4000-8000-000000000103"),
        event_type=EVENT_TYPE_DEPRECATED,
        occurred_at=NOW,
        dictionary=_dictionary(version=13),
        tag=_tag(version=4, status="deprecated", name="Artificial Intelligence & ML"),
        before=tag_snapshot(before_deprecate),
        changed_fields=["status"],
        change_summary="Tag 'ai' deprecated in dictionary 'industry' (version 4).",
        merged_into=None,
        trace_id=TRACE_ID,
    )

    before_merge = _tag(version=4, status="deprecated", name="Artificial Intelligence & ML")
    merged = build_tag_event(
        event_id=uuid.UUID("00000000-0000-4000-8000-000000000104"),
        event_type=EVENT_TYPE_MERGED,
        occurred_at=NOW,
        dictionary=_dictionary(version=14),
        tag=_tag(version=5, status="merged", name="Artificial Intelligence & ML"),
        before=tag_snapshot(before_merge),
        changed_fields=["merged_into_tag_id", "status"],
        change_summary="Tag 'ai' merged into 'ml' in dictionary 'industry' (version 5).",
        merged_into={"tag_id": TARGET_TAG_ID, "tag_code": "ml"},
        trace_id=TRACE_ID,
    )

    for envelope in (activated, updated, deprecated, merged):
        _write(f"{envelope.event_type}.json", envelope.model_dump(mode="json"))
        print(f"wrote {envelope.event_type}.json")


if __name__ == "__main__":
    build()

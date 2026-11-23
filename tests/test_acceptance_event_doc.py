"""Acceptance criterion 3: the event structure documentation specifies every field.

Two directions are checked:

* every field the code emits (the registry) is documented;
* every field row in the document is a field the code actually emits.

The documented JSON examples are parsed and validated against the same Pydantic
schema that builds production events.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from taxonomy_outbox.events.registry import EVENT_TYPES, registry_field_names
from taxonomy_outbox.events.schemas import EventEnvelope

pytestmark = pytest.mark.acceptance

ROOT = Path(__file__).resolve().parents[1]
EVENT_DOC = ROOT / "docs" / "event-structure.md"
CONSUMER_DOC = ROOT / "docs" / "consumers.md"
EXAMPLES = ROOT / "docs" / "examples"

#: a field table row looks like ``| `event_id` | string | always | ... |``
FIELD_ROW = re.compile(r"^\|\s*`([a-z_][a-z0-9_]*)`\s*\|", re.MULTILINE)


def _event_doc() -> str:
    return EVENT_DOC.read_text(encoding="utf-8")


def test_event_document_exists() -> None:
    assert EVENT_DOC.is_file(), "docs/event-structure.md is missing"
    assert len(_event_doc()) > 2_000, "the event document is too thin to specify every field"


def test_every_emitted_field_is_documented() -> None:
    documented = set(FIELD_ROW.findall(_event_doc()))
    missing = registry_field_names() - documented
    assert not missing, f"fields emitted by the code but not documented: {sorted(missing)}"


def test_no_documented_field_is_unknown_to_the_code() -> None:
    documented = set(FIELD_ROW.findall(_event_doc()))
    unknown = documented - registry_field_names()
    assert not unknown, f"documented fields the code never emits: {sorted(unknown)}"


def test_each_event_type_has_its_own_section() -> None:
    text = _event_doc()
    for event_type in EVENT_TYPES:
        assert re.search(rf"^#+ .*{re.escape(event_type)}", text, re.MULTILINE), (
            f"no heading for {event_type}"
        )


@pytest.mark.parametrize("event_type", EVENT_TYPES)
def test_documented_example_matches_the_schema(event_type: str) -> None:
    path = EXAMPLES / f"{event_type}.json"
    assert path.is_file(), f"missing documented example {path.name}"
    envelope = EventEnvelope.model_validate(json.loads(path.read_text(encoding="utf-8")))
    assert envelope.event_type == event_type
    assert envelope.aggregate_version == envelope.payload.version
    assert f"examples/{event_type}.json" in _event_doc()


def test_event_type_specific_field_rules_are_documented_and_enforced() -> None:
    text = _event_doc()
    assert "`before`" in text and "tag_activated" in text
    assert "`merged_into`" in text and "tag_merged" in text

    activated = json.loads((EXAMPLES / "taxonomy.tag_activated.json").read_text(encoding="utf-8"))
    assert activated["payload"]["before"] is None
    assert activated["payload"]["merged_into"] is None

    merged = json.loads((EXAMPLES / "taxonomy.tag_merged.json").read_text(encoding="utf-8"))
    assert merged["payload"]["merged_into"] == {
        "tag_id": merged["payload"]["merged_into"]["tag_id"],
        "tag_code": merged["payload"]["merged_into"]["tag_code"],
    }
    assert merged["payload"]["merged_into"]["tag_code"]


def test_consumer_examples_document_every_event_type() -> None:
    text = CONSUMER_DOC.read_text(encoding="utf-8")
    for event_type in EVENT_TYPES:
        assert event_type in text, f"docs/consumers.md does not mention {event_type}"
    lowered = text.lower()
    assert "idempot" in lowered or "deduplicat" in lowered
    assert "matching" in lowered and "search" in lowered

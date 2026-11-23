"""The event contract as data: event types, versions and the field registry.

``docs/event-structure.md`` is kept in sync with these tuples and the doc test
(``tests/test_acceptance_event_doc.py``) asserts both directions: every field
in the registry is documented, and every field row in the document is a field
the code actually emits.
"""

from __future__ import annotations

EVENT_PRODUCER = "taxonomy"
AGGREGATE_TYPE = "taxonomy_tag"
EVENT_VERSION = 1

EVENT_TYPE_ACTIVATED = "taxonomy.tag_activated"
EVENT_TYPE_UPDATED = "taxonomy.tag_updated"
EVENT_TYPE_DEPRECATED = "taxonomy.tag_deprecated"
EVENT_TYPE_MERGED = "taxonomy.tag_merged"

EVENT_TYPES: tuple[str, ...] = (
    EVENT_TYPE_ACTIVATED,
    EVENT_TYPE_UPDATED,
    EVENT_TYPE_DEPRECATED,
    EVENT_TYPE_MERGED,
)

#: action value inside ``payload.change_summary``-driven events, keyed by type
EVENT_ACTIONS: dict[str, str] = {
    EVENT_TYPE_ACTIVATED: "activated",
    EVENT_TYPE_UPDATED: "updated",
    EVENT_TYPE_DEPRECATED: "deprecated",
    EVENT_TYPE_MERGED: "merged",
}

ENVELOPE_FIELDS: tuple[str, ...] = (
    "event_id",
    "event_type",
    "event_version",
    "occurred_at",
    "org_id",
    "site_id",
    "aggregate_type",
    "aggregate_id",
    "aggregate_version",
    "producer",
    "trace_id",
    "payload",
)

PAYLOAD_FIELDS: tuple[str, ...] = (
    "dictionary_id",
    "dictionary_code",
    "dictionary_version",
    "tag_id",
    "tag_code",
    "tag_version",
    "tag_status",
    "version",
    "change_summary",
    "changed_fields",
    "before",
    "after",
    "merged_into",
)

SNAPSHOT_FIELDS: tuple[str, ...] = (
    "tag_id",
    "tag_code",
    "tag_name",
    "tag_status",
    "tag_version",
)

MERGED_INTO_FIELDS: tuple[str, ...] = (
    "tag_id",
    "tag_code",
)

#: fields that only exist on one event type; every other payload field is always present
CONDITIONAL_FIELDS: dict[str, str] = {
    "merged_into": EVENT_TYPE_MERGED,
}


def registry_field_names() -> set[str]:
    """Every documentable field name of the contract."""

    return set(ENVELOPE_FIELDS) | set(PAYLOAD_FIELDS) | set(SNAPSHOT_FIELDS) | set(MERGED_INTO_FIELDS)

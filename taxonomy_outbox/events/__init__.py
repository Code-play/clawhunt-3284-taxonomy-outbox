"""Event contract: registry, Pydantic schemas and the envelope builder."""

from .build import build_tag_event, tag_snapshot
from .registry import (
    EVENT_ACTIONS,
    EVENT_TYPES,
    EVENT_VERSION,
    EVENT_TYPE_ACTIVATED,
    EVENT_TYPE_DEPRECATED,
    EVENT_TYPE_MERGED,
    EVENT_TYPE_UPDATED,
    registry_field_names,
)
from .schemas import EventEnvelope, MergedInto, TagChangePayload, TagSnapshot

__all__ = [
    "build_tag_event",
    "tag_snapshot",
    "EVENT_ACTIONS",
    "EVENT_TYPES",
    "EVENT_VERSION",
    "EVENT_TYPE_ACTIVATED",
    "EVENT_TYPE_DEPRECATED",
    "EVENT_TYPE_MERGED",
    "EVENT_TYPE_UPDATED",
    "registry_field_names",
    "EventEnvelope",
    "MergedInto",
    "TagChangePayload",
    "TagSnapshot",
]

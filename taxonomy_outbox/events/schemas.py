"""Pydantic v2 models for the tag lifecycle event envelope and payload."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .registry import (
    AGGREGATE_TYPE,
    EVENT_PRODUCER,
    EVENT_VERSION,
    EVENT_TYPE_ACTIVATED,
    EVENT_TYPE_MERGED,
    EVENT_TYPES,
)


class TagSnapshot(BaseModel):
    """State of a tag immediately before or after the change."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tag_id: uuid.UUID
    tag_code: str = Field(min_length=1, max_length=64)
    tag_name: str
    tag_status: str
    tag_version: int = Field(ge=1)


class MergedInto(BaseModel):
    """The surviving tag of a merge."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tag_id: uuid.UUID
    tag_code: str = Field(min_length=1, max_length=64)


class TagChangePayload(BaseModel):
    """Event-specific content. Every field is documented in docs/event-structure.md."""

    model_config = ConfigDict(extra="forbid")

    dictionary_id: uuid.UUID
    dictionary_code: str = Field(min_length=1, max_length=64)
    dictionary_version: int = Field(ge=1)
    tag_id: uuid.UUID
    tag_code: str = Field(min_length=1, max_length=64)
    tag_version: int = Field(ge=1)
    tag_status: str
    #: the version number of the tag after the change (mirrors ``tag_version``)
    version: int = Field(ge=1)
    change_summary: str = Field(min_length=1, max_length=512)
    changed_fields: list[str]
    before: TagSnapshot | None = None
    after: TagSnapshot
    merged_into: MergedInto | None = None

    @model_validator(mode="after")
    def _version_mirror(self) -> "TagChangePayload":
        if self.version != self.tag_version:
            raise ValueError("payload.version must equal payload.tag_version")
        if self.after.tag_id != self.tag_id:
            raise ValueError("payload.after.tag_id must equal payload.tag_id")
        if self.before is not None and self.before.tag_id != self.tag_id:
            raise ValueError("payload.before.tag_id must equal payload.tag_id")
        return self


class EventEnvelope(BaseModel):
    """Wire format published by the outbox relay and consumed downstream."""

    model_config = ConfigDict(extra="forbid")

    event_id: uuid.UUID
    event_type: str
    event_version: int
    occurred_at: datetime
    org_id: uuid.UUID
    site_id: uuid.UUID
    aggregate_type: str = AGGREGATE_TYPE
    aggregate_id: uuid.UUID
    aggregate_version: int = Field(ge=1)
    producer: str = EVENT_PRODUCER
    trace_id: str | None = None
    payload: TagChangePayload

    @field_validator("event_type")
    @classmethod
    def _known_event_type(cls, value: str) -> str:
        if value not in EVENT_TYPES:
            raise ValueError(f"unknown event_type {value!r}; expected one of {EVENT_TYPES}")
        return value

    @field_validator("event_version")
    @classmethod
    def _known_event_version(cls, value: int) -> int:
        if value != EVENT_VERSION:
            raise ValueError(f"unsupported event_version {value}; this producer emits {EVENT_VERSION}")
        return value

    @model_validator(mode="after")
    def _consistent(self) -> "EventEnvelope":
        if self.aggregate_type != AGGREGATE_TYPE:
            raise ValueError(f"aggregate_type must be {AGGREGATE_TYPE!r}")
        if self.producer != EVENT_PRODUCER:
            raise ValueError(f"producer must be {EVENT_PRODUCER!r}")
        if self.aggregate_id != self.payload.tag_id:
            raise ValueError("aggregate_id must equal payload.tag_id")
        if self.aggregate_version != self.payload.version:
            raise ValueError("aggregate_version must equal payload.version")

        if self.event_type == EVENT_TYPE_ACTIVATED:
            if self.payload.before is not None:
                raise ValueError("tag_activated must not carry a before snapshot")
        elif self.payload.before is None:
            raise ValueError(f"{self.event_type} must carry a before snapshot")

        if self.event_type == EVENT_TYPE_MERGED:
            if self.payload.merged_into is None:
                raise ValueError("tag_merged must carry merged_into")
        elif self.payload.merged_into is not None:
            raise ValueError(f"{self.event_type} must not carry merged_into")
        return self

"""Request/response models of the HTTP API."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class TenantContext(BaseModel):
    org_id: uuid.UUID
    site_id: uuid.UUID
    actor_id: uuid.UUID | None = None
    trace_id: str | None = None


class TagView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    org_id: uuid.UUID
    site_id: uuid.UUID
    dictionary_id: uuid.UUID
    code: str
    name: str
    description: str | None = None
    status: str
    version: int
    merged_into_tag_id: uuid.UUID | None = None
    updated_at: datetime


class DictionaryView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    org_id: uuid.UUID
    site_id: uuid.UUID
    code: str
    name: str
    description: str | None = None
    version: int
    status: str


class CreateDictionaryRequest(BaseModel):
    code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=128)
    description: str | None = None


class CreateTagRequest(BaseModel):
    code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=128)
    description: str | None = None


class UpdateTagRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = None
    expected_version: int | None = Field(default=None, ge=1)


class MergeRequest(BaseModel):
    target_tag_id: uuid.UUID


class MutationResponse(BaseModel):
    tag: TagView
    event_id: uuid.UUID
    event_type: str
    outbox_status: str


class OutboxEventView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    event_type: str
    event_version: int
    aggregate_id: uuid.UUID
    aggregate_version: int
    status: str
    attempts: int
    last_error: str | None = None
    occurred_at: datetime
    dispatched_at: datetime | None = None


class DispatchResponse(BaseModel):
    scanned: int
    published: int
    failed: int

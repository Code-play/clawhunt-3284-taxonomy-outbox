"""HTTP API: tag lifecycle mutations and outbox administration.

Every mutating endpoint commits only after the service returned, so the tag
change and its outbox row become visible together.  A request that fails rolls
back both.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models.outbox import OutboxEvent
from ..services.taxonomy_service import MutationResult, TaxonomyService
from .deps import get_service, get_session, tenant_context
from .schemas import (
    CreateDictionaryRequest,
    CreateTagRequest,
    DictionaryView,
    DispatchResponse,
    MergeRequest,
    MutationResponse,
    OutboxEventView,
    TagView,
    TenantContext,
    UpdateTagRequest,
)

router = APIRouter(prefix="/api/v1/taxonomy", tags=["taxonomy"])


def _mutation_response(result: MutationResult) -> MutationResponse:
    return MutationResponse(
        tag=TagView.model_validate(result.tag),
        event_id=result.event.id,
        event_type=result.event.event_type,
        outbox_status=result.event.status,
    )


@router.post("/dictionaries", response_model=DictionaryView, status_code=201)
def create_dictionary(
    body: CreateDictionaryRequest,
    ctx: TenantContext = Depends(tenant_context),
    service: TaxonomyService = Depends(get_service),
    session: Session = Depends(get_session),
) -> DictionaryView:
    dictionary = service.create_dictionary(
        org_id=ctx.org_id,
        site_id=ctx.site_id,
        code=body.code,
        name=body.name,
        description=body.description,
        actor_id=ctx.actor_id,
    )
    session.commit()
    return DictionaryView.model_validate(dictionary)


@router.post("/dictionaries/{dictionary_id}/tags", response_model=TagView, status_code=201)
def create_tag(
    dictionary_id: uuid.UUID,
    body: CreateTagRequest,
    ctx: TenantContext = Depends(tenant_context),
    service: TaxonomyService = Depends(get_service),
    session: Session = Depends(get_session),
) -> TagView:
    tag = service.create_tag(
        org_id=ctx.org_id,
        site_id=ctx.site_id,
        dictionary_id=dictionary_id,
        code=body.code,
        name=body.name,
        description=body.description,
        actor_id=ctx.actor_id,
    )
    session.commit()
    return TagView.model_validate(tag)


@router.get("/tags/{tag_id}", response_model=TagView)
def get_tag(
    tag_id: uuid.UUID,
    ctx: TenantContext = Depends(tenant_context),
    service: TaxonomyService = Depends(get_service),
) -> TagView:
    tag = service.get_tag(tag_id=tag_id, org_id=ctx.org_id, site_id=ctx.site_id)
    return TagView.model_validate(tag)


@router.post("/tags/{tag_id}/activate", response_model=MutationResponse)
def activate_tag(
    tag_id: uuid.UUID,
    ctx: TenantContext = Depends(tenant_context),
    service: TaxonomyService = Depends(get_service),
    session: Session = Depends(get_session),
) -> MutationResponse:
    """draft -> active; publishes ``taxonomy.tag_activated``."""

    result = service.activate(tag_id=tag_id, org_id=ctx.org_id, site_id=ctx.site_id, actor_id=ctx.actor_id)
    session.commit()
    return _mutation_response(result)


@router.patch("/tags/{tag_id}", response_model=MutationResponse)
def update_tag(
    tag_id: uuid.UUID,
    body: UpdateTagRequest,
    ctx: TenantContext = Depends(tenant_context),
    service: TaxonomyService = Depends(get_service),
    session: Session = Depends(get_session),
) -> MutationResponse:
    """Update tag attributes; publishes ``taxonomy.tag_updated`` (no-op changes emit nothing)."""

    changes = body.model_dump(exclude_unset=True, exclude={"expected_version"})
    result = service.update(
        tag_id=tag_id,
        org_id=ctx.org_id,
        site_id=ctx.site_id,
        changes=changes,
        expected_version=body.expected_version,
        actor_id=ctx.actor_id,
    )
    if result is None:
        raise HTTPException(status_code=409, detail="no fields changed; no event was emitted")
    session.commit()
    return _mutation_response(result)


@router.post("/tags/{tag_id}/deprecate", response_model=MutationResponse)
def deprecate_tag(
    tag_id: uuid.UUID,
    ctx: TenantContext = Depends(tenant_context),
    service: TaxonomyService = Depends(get_service),
    session: Session = Depends(get_session),
) -> MutationResponse:
    """active -> deprecated; publishes ``taxonomy.tag_deprecated``."""

    result = service.deprecate(tag_id=tag_id, org_id=ctx.org_id, site_id=ctx.site_id, actor_id=ctx.actor_id)
    session.commit()
    return _mutation_response(result)


@router.post("/tags/{tag_id}/merge", response_model=MutationResponse)
def merge_tag(
    tag_id: uuid.UUID,
    body: MergeRequest,
    ctx: TenantContext = Depends(tenant_context),
    service: TaxonomyService = Depends(get_service),
    session: Session = Depends(get_session),
) -> MutationResponse:
    """Merge ``tag_id`` into ``target_tag_id``; publishes ``taxonomy.tag_merged``."""

    result = service.merge(
        source_tag_id=tag_id,
        target_tag_id=body.target_tag_id,
        org_id=ctx.org_id,
        site_id=ctx.site_id,
        actor_id=ctx.actor_id,
    )
    session.commit()
    return _mutation_response(result)


@router.get("/outbox", response_model=Sequence[OutboxEventView])
def list_outbox(
    ctx: TenantContext = Depends(tenant_context),
    session: Session = Depends(get_session),
    status: str | None = Query(default=None, pattern="^(pending|dispatched|failed)$"),
    limit: int = Query(default=50, ge=1, le=500),
) -> Sequence[OutboxEventView]:
    """Read the outbox for one tenant (ops/debug aid)."""

    stmt = (
        select(OutboxEvent)
        .where(OutboxEvent.org_id == ctx.org_id, OutboxEvent.site_id == ctx.site_id)
        .order_by(OutboxEvent.occurred_at.desc(), OutboxEvent.id)
        .limit(limit)
    )
    if status is not None:
        stmt = stmt.where(OutboxEvent.status == status)
    rows = session.execute(stmt).scalars().all()
    return [OutboxEventView.model_validate(row) for row in rows]


@router.post("/outbox/dispatch", response_model=DispatchResponse)
def dispatch_outbox(request: Request) -> DispatchResponse:
    """Run one relay batch now (ops aid; production runs ``relay.worker``)."""

    result = request.app.state.relay.publish_pending()
    return DispatchResponse(scanned=result.scanned, published=result.published, failed=result.failed)

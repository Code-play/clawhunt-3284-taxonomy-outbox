"""FastAPI dependencies: tenant context and database session."""

from __future__ import annotations

import uuid
from collections.abc import Iterator

from fastapi import Depends, Header, Request
from sqlalchemy.orm import Session

from ..services.taxonomy_service import TaxonomyService
from .schemas import TenantContext


def get_session(request: Request) -> Iterator[Session]:
    """One session per request; rollback on error, always close."""

    session = request.app.state.session_factory()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def tenant_context(
    x_org_id: uuid.UUID = Header(..., alias="X-Org-Id"),
    x_site_id: uuid.UUID = Header(..., alias="X-Site-Id"),
    x_actor_id: uuid.UUID | None = Header(default=None, alias="X-Actor-Id"),
    x_trace_id: str | None = Header(default=None, alias="X-Trace-Id"),
) -> TenantContext:
    return TenantContext(
        org_id=x_org_id,
        site_id=x_site_id,
        actor_id=x_actor_id,
        trace_id=x_trace_id,
    )


def get_service(
    ctx: TenantContext = Depends(tenant_context),
    session: Session = Depends(get_session),
) -> TaxonomyService:
    return TaxonomyService(session, trace_id=ctx.trace_id)

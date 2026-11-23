"""Shared fixtures: migrated PostgreSQL schema, sessions, tenants and tag factories.

The suite runs against a real PostgreSQL 16 database (the project's production
target).  ``TEST_DATABASE_URL`` (or ``DATABASE_URL``) selects it; the default is
the ``docker compose`` database from README.  The schema is created by running
the Alembic migration, so every test run also proves the migration works.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from taxonomy_outbox.db import make_engine, make_session_factory
from taxonomy_outbox.models.taxonomy import TaxonomyDictionary, TaxonomyTag
from taxonomy_outbox.services.taxonomy_service import TaxonomyService

ROOT = Path(__file__).resolve().parents[1]

TEST_DATABASE_URL = (
    os.getenv("TEST_DATABASE_URL")
    or os.getenv("DATABASE_URL")
    or "postgresql+psycopg://outbox:outbox_local_dev@127.0.0.1:55432/outbox"
)
# migrations/env.py prefers DATABASE_URL; align it with the test database.
os.environ["DATABASE_URL"] = TEST_DATABASE_URL

#: children first is unnecessary because of CASCADE, but keep the list explicit
TRUNCATE_SQL = (
    "TRUNCATE TABLE outbox_event, consumer_delivery, matching_tag_projection, "
    "search_index_document, taxonomy_tag, taxonomy_dictionary CASCADE"
)


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    eng = make_engine(TEST_DATABASE_URL)
    with eng.begin() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    alembic_cfg = Config(str(ROOT / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(ROOT / "migrations"))
    command.upgrade(alembic_cfg, "head")
    yield eng
    eng.dispose()


@pytest.fixture(autouse=True)
def clean_database(engine: Engine) -> Iterator[None]:
    with engine.begin() as conn:
        conn.execute(text(TRUNCATE_SQL))
    yield


@pytest.fixture()
def session_factory(engine: Engine) -> sessionmaker[Session]:
    return make_session_factory(engine)


@pytest.fixture()
def session(session_factory: sessionmaker[Session]) -> Iterator[Session]:
    db = session_factory()
    try:
        yield db
    finally:
        db.rollback()
        db.close()


@pytest.fixture()
def tenant() -> dict[str, uuid.UUID]:
    return {"org_id": uuid.uuid4(), "site_id": uuid.uuid4()}


@pytest.fixture()
def service(session: Session) -> TaxonomyService:
    return TaxonomyService(session)


@pytest.fixture()
def dictionary(session: Session, tenant: dict[str, uuid.UUID]) -> TaxonomyDictionary:
    svc = TaxonomyService(session)
    row = svc.create_dictionary(
        org_id=tenant["org_id"],
        site_id=tenant["site_id"],
        code="industry",
        name="Industry",
    )
    session.commit()
    return row


@pytest.fixture()
def make_tag(
    session: Session, dictionary: TaxonomyDictionary, tenant: dict[str, uuid.UUID]
) -> Callable[..., TaxonomyTag]:
    """Create a tag (draft by default); ``activate=True`` publishes its first event."""

    def _make(
        code: str = "ai",
        name: str = "Artificial Intelligence",
        *,
        activate: bool = False,
        commit: bool = True,
    ) -> TaxonomyTag:
        svc = TaxonomyService(session)
        tag = svc.create_tag(
            org_id=tenant["org_id"],
            site_id=tenant["site_id"],
            dictionary_id=dictionary.id,
            code=code,
            name=name,
        )
        if activate:
            svc.activate(tag_id=tag.id, org_id=tenant["org_id"], site_id=tenant["site_id"])
        if commit:
            session.commit()
        return tag

    return _make

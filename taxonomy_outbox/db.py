"""Shared SQLAlchemy 2 configuration: declarative base, engine and session factory."""

from __future__ import annotations

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    """Declarative base shared by every model and by Alembic autogenerate."""


def make_engine(database_url: str, *, echo: bool = False) -> Engine:
    """Create an engine for the configured database URL.

    PostgreSQL 16 is the supported production target; the URL is only ever read
    from configuration (environment variables), never hard-coded per
    environment.
    """

    return create_engine(database_url, echo=echo, pool_pre_ping=True, future=True)


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

"""Dictionary and tag tables of the Dictionary & Tag Center module."""

from __future__ import annotations

import enum
import uuid

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin, TenantMixin, UUIDPrimaryKeyMixin


class TagStatus(str, enum.Enum):
    """Lifecycle states of a taxonomy tag.

    ``draft``      created but not visible to matching / search
    ``active``     published and consumable
    ``deprecated`` retired, kept for historical references
    ``merged``     folded into another tag; ``merged_into_tag_id`` points at it
    """

    DRAFT = "draft"
    ACTIVE = "active"
    DEPRECATED = "deprecated"
    MERGED = "merged"


class DictionaryStatus(str, enum.Enum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class TaxonomyDictionary(UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "taxonomy_dictionary"
    __table_args__ = (
        CheckConstraint("status IN ('active','archived')", name="ck_taxonomy_dictionary_status"),
        Index(
            "uq_taxonomy_dictionary_code",
            "org_id",
            "site_id",
            "code",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: monotonic revision counter; bumped on every tag lifecycle change in this dictionary
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default=text("1"))
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active", server_default=text("'active'"))

    tags: Mapped[list["TaxonomyTag"]] = relationship(back_populates="dictionary")


class TaxonomyTag(UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "taxonomy_tag"
    __table_args__ = (
        CheckConstraint("status IN ('draft','active','deprecated','merged')", name="ck_taxonomy_tag_status"),
        Index(
            "uq_taxonomy_tag_code",
            "org_id",
            "site_id",
            "dictionary_id",
            "code",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("ix_taxonomy_tag_dictionary_id", "dictionary_id"),
    )

    dictionary_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("taxonomy_dictionary.id", ondelete="RESTRICT"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=TagStatus.DRAFT.value)
    #: optimistic version of this tag; incremented on every accepted mutation
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default=text("1"))
    merged_into_tag_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("taxonomy_tag.id", ondelete="SET NULL"), nullable=True
    )

    dictionary: Mapped[TaxonomyDictionary] = relationship(back_populates="tags")

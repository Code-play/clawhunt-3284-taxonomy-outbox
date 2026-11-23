"""Example consumer: keep the matching engine's tag projection in sync.

A merged source tag keeps its row but points at the surviving code
(``canonical_tag_code``), so historic matches can be rewritten without losing the
original code.  A deprecated tag is removed from matching entirely.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any

from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from ..events.registry import EVENT_TYPE_DEPRECATED, EVENT_TYPE_MERGED
from ..models.projections import MatchingTagProjection
from .base import BaseConsumer


class MatchingEngineConsumer(BaseConsumer):
    name = "matching-engine"

    def apply(self, session: Session, envelope: Mapping[str, Any]) -> None:
        payload = envelope["payload"]
        org_id = uuid.UUID(str(envelope["org_id"]))
        site_id = uuid.UUID(str(envelope["site_id"]))
        tag_id = uuid.UUID(str(payload["tag_id"]))

        if envelope["event_type"] == EVENT_TYPE_DEPRECATED:
            session.execute(
                delete(MatchingTagProjection).where(
                    MatchingTagProjection.org_id == org_id,
                    MatchingTagProjection.site_id == site_id,
                    MatchingTagProjection.tag_id == tag_id,
                )
            )
            return

        canonical = str(payload["tag_code"])
        if envelope["event_type"] == EVENT_TYPE_MERGED:
            canonical = str(payload["merged_into"]["tag_code"])

        stmt = pg_insert(MatchingTagProjection).values(
            id=uuid.uuid4(),
            org_id=org_id,
            site_id=site_id,
            tag_id=tag_id,
            dictionary_code=str(payload["dictionary_code"]),
            tag_code=str(payload["tag_code"]),
            canonical_tag_code=canonical,
            tag_version=int(payload["version"]),
            updated_at=self._event_time(envelope),
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["org_id", "site_id", "tag_id"],
            set_={
                "dictionary_code": stmt.excluded.dictionary_code,
                "tag_code": stmt.excluded.tag_code,
                "canonical_tag_code": stmt.excluded.canonical_tag_code,
                "tag_version": stmt.excluded.tag_version,
                "updated_at": stmt.excluded.updated_at,
            },
        )
        session.execute(stmt)

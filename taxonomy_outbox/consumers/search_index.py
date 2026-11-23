"""Example consumer: keep the search index projection in sync with tag events.

``taxonomy.tag_activated`` / ``taxonomy.tag_updated`` upsert the document;
``taxonomy.tag_deprecated`` removes it from the index; a merged source tag is
removed as well (the surviving target already has its own document).
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any

from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from ..events.registry import EVENT_TYPE_DEPRECATED, EVENT_TYPE_MERGED
from ..models.projections import SearchIndexDocument
from .base import BaseConsumer


class SearchIndexConsumer(BaseConsumer):
    name = "search-index"

    def apply(self, session: Session, envelope: Mapping[str, Any]) -> None:
        payload = envelope["payload"]
        org_id = uuid.UUID(str(envelope["org_id"]))
        site_id = uuid.UUID(str(envelope["site_id"]))
        tag_id = uuid.UUID(str(payload["tag_id"]))

        if envelope["event_type"] in (EVENT_TYPE_DEPRECATED, EVENT_TYPE_MERGED):
            session.execute(
                delete(SearchIndexDocument).where(
                    SearchIndexDocument.org_id == org_id,
                    SearchIndexDocument.site_id == site_id,
                    SearchIndexDocument.tag_id == tag_id,
                )
            )
            return

        after = payload["after"]
        stmt = pg_insert(SearchIndexDocument).values(
            id=uuid.uuid4(),
            org_id=org_id,
            site_id=site_id,
            tag_id=tag_id,
            dictionary_code=str(payload["dictionary_code"]),
            tag_code=str(payload["tag_code"]),
            tag_name=str(after["tag_name"]),
            tag_version=int(payload["version"]),
            tag_status=str(after["tag_status"]),
            updated_at=self._event_time(envelope),
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["org_id", "site_id", "tag_id"],
            set_={
                "dictionary_code": stmt.excluded.dictionary_code,
                "tag_code": stmt.excluded.tag_code,
                "tag_name": stmt.excluded.tag_name,
                "tag_version": stmt.excluded.tag_version,
                "tag_status": stmt.excluded.tag_status,
                "updated_at": stmt.excluded.updated_at,
            },
        )
        session.execute(stmt)

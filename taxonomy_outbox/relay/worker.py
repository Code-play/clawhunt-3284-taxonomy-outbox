"""Standalone relay loop: ``python -m taxonomy_outbox.relay.worker``."""

from __future__ import annotations

import logging
import time

from ..config import Settings
from ..db import make_engine, make_session_factory
from .publisher import build_publisher
from .relay import OutboxRelay

log = logging.getLogger("taxonomy_outbox.relay")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = Settings.from_env()
    engine = make_engine(settings.database_url)
    session_factory = make_session_factory(engine)
    publisher = build_publisher(settings)
    relay = OutboxRelay(
        session_factory,
        publisher,
        batch_size=settings.outbox_batch_size,
        max_attempts=settings.outbox_max_attempts,
        retry_backoff_seconds=settings.outbox_retry_backoff_seconds,
    )
    log.info("relay started publisher=%s stream=%s", settings.publisher, settings.redis_stream)
    try:
        while True:
            result = relay.publish_pending()
            if result.scanned:
                log.info("published=%s failed=%s scanned=%s", result.published, result.failed, result.scanned)
            if result.scanned == 0:
                time.sleep(settings.outbox_poll_interval_seconds)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()

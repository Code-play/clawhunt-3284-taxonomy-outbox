# Consumer examples: matching engine and search index

The producer writes tag lifecycle events to the outbox; the relay appends them to
the Redis Stream `taxonomy.events`. This page shows how the two downstream
systems subscribe, plus the runnable, tested reference implementations.

## 1. What each consumer must do

| Consumer | `taxonomy.tag_activated` / `taxonomy.tag_updated` | `taxonomy.tag_deprecated` | `taxonomy.tag_merged` |
|---|---|---|---|
| Search index | upsert the tag document (`tag_code`, `tag_name`, `tag_version`) | remove the document | remove the source document (the target is untouched) |
| Matching engine | upsert the tag projection with `canonical_tag_code = tag_code` | remove the projection | keep the source row, set `canonical_tag_code` to `merged_into.tag_code` |

Both consumers are scoped by `org_id` + `site_id` + `tag_id`.

## 2. Reference implementation

`taxonomy_outbox/consumers/` contains two working consumers:

- `SearchIndexConsumer` (`taxonomy_outbox/consumers/search_index.py`)
- `MatchingEngineConsumer` (`taxonomy_outbox/consumers/matching_engine.py`)

They share `BaseConsumer` (`taxonomy_outbox/consumers/base.py`), which implements
the idempotency ledger: before applying an event it inserts
`(consumer_name, event_id)` into `consumer_delivery` with
`ON CONFLICT DO NOTHING`. If the insert changed no row the event was already
processed and is skipped. The ledger insert and the projection write share one
transaction, so a crash leaves neither half behind.

```python
from taxonomy_outbox.consumers import MatchingEngineConsumer, SearchIndexConsumer

search_index = SearchIndexConsumer(session_factory)
matching_engine = MatchingEngineConsumer(session_factory)

# The body of a Redis Streams consumer loop (one group per downstream system):
# envelope = json.loads(fields["event"])
search_index.handle(envelope)
matching_engine.handle(envelope)
```

`handle` returns `True` when the event was applied and `False` when it was a
duplicate delivery. It never raises for a duplicate.

The reference consumers deduplicate on `event_id` and rely on per-stream
ordering (the relay publishes one tag's events in version order). A production
store that can replay entries out of order should additionally persist the last
applied version per tag and ignore lower versions (see section 5).

## 3. Redis Streams subscription

Each downstream system runs its own consumer group, so both receive every event.
`XACK` only after `handle` returned, and let the pending-entries list drive
recovery of crashed consumers.

```python
import json
import redis

from taxonomy_outbox.consumers import SearchIndexConsumer

client = redis.Redis.from_url("redis://127.0.0.1:6379/0", decode_responses=True)
consumer = SearchIndexConsumer(session_factory)
client.xgroup_create("taxonomy.events", "search-index", id="0", mkstream=True)

while True:
    response = client.xreadgroup(
        "search-index", "search-index-1", {"taxonomy.events": ">"}, count=50, block=5000
    )
    for _stream, entries in response or []:
        for entry_id, fields in entries:
            envelope = json.loads(fields["event"])
            consumer.handle(envelope)          # idempotent
            client.xack("taxonomy.events", "search-index", entry_id)
```

## 4. Wiring into the real targets

The ticket allows interface stubs / mocks first. The two projection tables
(`search_index_document`, `matching_tag_projection`) stand in for the real
stores. The integration points are:

- `SearchIndexConsumer.apply` — replace the `search_index_document` upsert/delete
  with the search engine's document API. Keep the idempotency insert in the same
  unit of work, or add an equivalent outbox/transaction on the consumer side.
- `MatchingEngineConsumer.apply` — replace the `matching_tag_projection`
  upsert/delete with the matching engine's tag table. `canonical_tag_code` is the
  field used to rewrite references to merged tags.
- Transport — `PUBLISHER=redis` (see README) switches `RedisStreamPublisher` on;
  `PUBLISHER=memory` is for local demos and tests.

## 5. Failure handling

- Publishing is at least once; consumers must be idempotent (the ledger does it).
- The relay retries a failed publish with linear backoff and marks the row
  `failed` after `OUTBOX_MAX_ATTEMPTS`; operators can replay a failed row by
  resetting its `status` to `pending`.
- Consumers should treat `payload.version <= stored_version` as stale and skip it;
  this protects against out-of-order redelivery across restarts.
- A failure inside `apply` rolls back both the projection write and the ledger
  insert, so the redelivered event is retried.

## 6. Local check

`tests/test_relay_consumers.py` runs the full path against PostgreSQL: outbox ->
relay -> both consumers -> projections, including merge remapping, removal on
deprecation and duplicate-delivery idempotency. Run it with the rest of the suite
(see README).

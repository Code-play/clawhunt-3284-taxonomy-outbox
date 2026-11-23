# Taxonomy outbox - Dictionary & Tag Center event publishing

Deliverable for ticket **S2-TAX-022**: publish tag lifecycle events through a
transactional outbox when a tag is activated, updated, deprecated or merged.

- Event types: `taxonomy.tag_activated`, `taxonomy.tag_updated`,
  `taxonomy.tag_deprecated`, `taxonomy.tag_merged`.
- Payload carries the dictionary, the tag code, the version number and a change
  summary (`docs/event-structure.md`).
- The matching engine and the search index subscribe through runnable example
  consumers (`docs/consumers.md`, `taxonomy_outbox/consumers/`).

No client name, real person or real enterprise data appears anywhere in this
repository; all identifiers and examples are fictional.

## Architecture

```
HTTP request (FastAPI)
   |
   |-- one database transaction ------------------------------------------
   |     tag row updated (optimistic version +1)
   |     dictionary revision counter +1
   |     outbox_event row appended (same transaction)
   |------------------------------------------------------------------------
   |
relay worker (relay/worker.py, or POST /outbox/dispatch for one batch)
   |
   |-- SELECT ... FOR UPDATE SKIP LOCKED  (batch of due pending rows)
   |-- publisher.publish(envelope)        (Redis Stream / in-memory)
   |-- status=dispatched | retry with backoff | failed after max attempts
   |
Redis Stream `taxonomy.events`
   |
   |-- SearchIndexConsumer     (upsert / delete search documents)
   |-- MatchingEngineConsumer  (upsert / remove tag projections, remap merges)
```

The outbox row is written in the same transaction as the business change, so a
rollback removes both: an event can never be emitted for a change that did not
commit.

## Layout

| Path | Purpose |
|---|---|
| `taxonomy_outbox/models/` | SQLAlchemy 2 models: dictionary, tag, outbox, projections, delivery ledger |
| `taxonomy_outbox/events/` | Event field registry, Pydantic envelope/payload schemas, envelope builder |
| `taxonomy_outbox/services/` | Tag lifecycle transitions and the outbox writer |
| `taxonomy_outbox/relay/` | Outbox relay, Redis Streams publisher, standalone worker |
| `taxonomy_outbox/consumers/` | Search index and matching engine example consumers |
| `taxonomy_outbox/api/` | FastAPI app and routes |
| `migrations/` | Alembic migration (`0001_taxonomy_outbox`, with downgrade) |
| `docs/` | Event structure, consumer guide, generated JSON examples |
| `tests/` | Acceptance, counterexample, relay/consumer, API and DDL tests |

## Requirements

- Python 3.11+
- PostgreSQL 16 (the `pgvector/pgvector:pg16` image works as well)
- Redis 7 is optional and only needed when `PUBLISHER=redis`

## Quickstart

```bash
docker compose up -d db

python -m venv .venv
.venv/Scripts/activate            # Windows; use source .venv/bin/activate elsewhere
pip install -e ".[dev,redis]"     # redis extra is optional

export DATABASE_URL=postgresql+psycopg://outbox:outbox_local_dev@127.0.0.1:55432/outbox
alembic upgrade head

uvicorn taxonomy_outbox.api.main:app --port 8000
```

Create a dictionary, a draft tag, activate it, and look at the outbox:

```bash
ORG=11111111-1111-4111-8111-111111111111
SITE=22222222-2222-4222-8222-222222222222
H=(-H "X-Org-Id: $ORG" -H "X-Site-Id: $SITE" -H "Content-Type: application/json")

curl -s "${H[@]}" -X POST localhost:8000/api/v1/taxonomy/dictionaries \
  -d '{"code":"industry","name":"Industry"}'
curl -s "${H[@]}" -X POST localhost:8000/api/v1/taxonomy/dictionaries/<dictionary-id>/tags \
  -d '{"code":"ai","name":"Artificial Intelligence"}'
curl -s "${H[@]}" -X POST localhost:8000/api/v1/taxonomy/tags/<tag-id>/activate
curl -s "${H[@]}" localhost:8000/api/v1/taxonomy/outbox
curl -s -X POST localhost:8000/api/v1/taxonomy/outbox/dispatch
```

Run the relay continuously (Redis transport):

```bash
PUBLISHER=redis REDIS_URL=redis://127.0.0.1:6379/0 python -m taxonomy_outbox.relay.worker
```

## Configuration

Every value is read from the environment (`taxonomy_outbox/config.py`); nothing
is hard-coded per environment.

| Variable | Default | Meaning |
|---|---|---|
| `DATABASE_URL` | `postgresql+psycopg://outbox:outbox_local_dev@127.0.0.1:55432/outbox` | PostgreSQL connection URL |
| `PUBLISHER` | `memory` | `memory` (tests/demos) or `redis` |
| `REDIS_URL` | `redis://127.0.0.1:6379/0` | Redis URL used when `PUBLISHER=redis` |
| `REDIS_STREAM` | `taxonomy.events` | Stream name |
| `OUTBOX_BATCH_SIZE` | `100` | Rows scanned per relay batch |
| `OUTBOX_MAX_ATTEMPTS` | `5` | Publish attempts before a row is marked `failed` |
| `OUTBOX_RETRY_BACKOFF_SECONDS` | `30` | Linear retry backoff base (seconds per attempt) |
| `OUTBOX_POLL_INTERVAL_SECONDS` | `2.0` | Idle sleep of the relay worker |

## HTTP API

All endpoints require `X-Org-Id` and `X-Site-Id` headers; `X-Actor-Id` and
`X-Trace-Id` are optional.

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/v1/taxonomy/dictionaries` | create a dictionary |
| POST | `/api/v1/taxonomy/dictionaries/{id}/tags` | create a draft tag |
| GET | `/api/v1/taxonomy/tags/{id}` | read a tag |
| POST | `/api/v1/taxonomy/tags/{id}/activate` | draft -> active, emits `tag_activated` |
| PATCH | `/api/v1/taxonomy/tags/{id}` | update name/description, emits `tag_updated` |
| POST | `/api/v1/taxonomy/tags/{id}/deprecate` | active -> deprecated, emits `tag_deprecated` |
| POST | `/api/v1/taxonomy/tags/{id}/merge` | merge into another tag, emits `tag_merged` |
| GET | `/api/v1/taxonomy/outbox` | list outbox rows (ops/debug) |
| POST | `/api/v1/taxonomy/outbox/dispatch` | run one relay batch now |
| GET | `/healthz` | liveness |

Invalid lifecycle transitions return `409 invalid_tag_transition`; a stale
`expected_version` returns `409 tag_version_conflict`; cross-tenant access
returns `404` without revealing existence.

## Tests

```bash
docker compose up -d db
export TEST_DATABASE_URL=postgresql+psycopg://outbox:outbox_local_dev@127.0.0.1:55432/outbox
python -m pytest -q
```

The test session recreates the schema with `alembic upgrade head`, then runs the
acceptance, counterexample, relay/consumer, API and DDL tests. The suite needs a
live PostgreSQL 16; it fails loudly instead of skipping.

## Integration points (matching engine and search index)

The ticket allows interface stubs first, and the deliverable ships two working
stubs:

1. **Transport** - `taxonomy_outbox/relay/publisher.py`. `PUBLISHER=redis` appends
   one entry per event to `taxonomy.events`; `PUBLISHER=memory` is for tests and
   local demos. A different broker only needs a class with `publish(envelope)`.
2. **Consumer projections** - `taxonomy_outbox/consumers/*.py`. The two stub
   tables (`search_index_document`, `matching_tag_projection`) stand in for the
   real search index and matching-engine stores. Replace the `apply` methods with
   the real client calls; the idempotency ledger and the merge/deprecate rules
   stay the same. See `docs/consumers.md` for a Redis Streams loop and the exact
   integration points.

Contract guarantees consumers can rely on: per-tag ordering via
`payload.version`, at-least-once delivery deduplicated by `event_id`,
tenant scoping via `org_id`/`site_id`, `merged_into` on merges and no `before`
snapshot on activation.

## Design notes

- Atomicity: the outbox insert uses the business transaction; the relay never
  sees uncommitted events.
- Ordering: each tag has an optimistic `version` incremented on every accepted
  mutation; the unique `(aggregate_type, aggregate_id, aggregate_version,
  event_type)` index makes a duplicate event impossible.
- No-op updates emit nothing (`update` returns `None`).
- Merge locks both tags in id order to avoid deadlocks; the dictionary row lock
  serialises revision bumps per dictionary.
- Retries are at-least-once by design; consumers are idempotent through
  `consumer_delivery`.

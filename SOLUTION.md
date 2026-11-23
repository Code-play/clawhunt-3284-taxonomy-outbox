# S2-TAX-022 - Dictionary change event publishing (outbox)

## 1. What was delivered

Transactional-outbox event publishing for the Dictionary & Tag Center of the
member space platform. Every accepted tag lifecycle change writes one event to
the outbox inside the same database transaction, and a relay publishes it to the
matching engine and the search index.

Deliverables required by the ticket and where they live:

| Ticket deliverable | Location |
|---|---|
| Event publishing code | `taxonomy_outbox/` (models, services, relay, consumers, API), `migrations/` |
| Event structure documentation | `docs/event-structure.md` (every field, with generated examples in `docs/examples/`) |
| Consumption examples | `docs/consumers.md`, `taxonomy_outbox/consumers/` (runnable consumers), `examples/http_demo.py` |
| README with run and test instructions | `README.md` |
| Test results | `VERIFICATION.md` (clause -> command -> expected -> measured) |

The four event types are `taxonomy.tag_activated`, `taxonomy.tag_updated`,
`taxonomy.tag_deprecated` and `taxonomy.tag_merged`. Each payload carries the
dictionary (id, code, revision), the tag code, the version number and a change
summary, plus before/after snapshots; merges add `merged_into`.

## 2. Architecture

The write path is one transaction:

1. `TaxonomyService` locks the tag row (and its dictionary) and validates the
   lifecycle transition: draft -> active, update, active -> deprecated, or
   merge into another active tag of the same dictionary.
2. It increments the tag version (optimistic version), the dictionary revision
   and writes the outbox row. The API commits only after the service returned.
3. A rollback (any later failure in the transaction) removes the tag change,
   the version bump and the outbox row together - no event can exist for a
   change that did not commit.

The publish path is independent:

1. `OutboxRelay` selects due `pending` rows with `FOR UPDATE SKIP LOCKED`
   (several relays can run in parallel), publishes each envelope, then marks it
   `dispatched`; a publish failure increments attempts, backs off, and marks the
   row `failed` after `OUTBOX_MAX_ATTEMPTS`.
2. `PUBLISHER=memory` is used by tests and demos; `PUBLISHER=redis` appends one
   entry per event to the Redis Stream `taxonomy.events`.
3. `SearchIndexConsumer` and `MatchingEngineConsumer` subscribe, deduplicate on
   `(consumer_name, event_id)` with an `ON CONFLICT DO NOTHING` ledger row, and
   update their projections: upsert on activation/update, delete on
   deprecation, remove the search document and remap `canonical_tag_code` on
   merge.

## 3. Data model and migration

`migrations/versions/0001_taxonomy_outbox.py` creates six tables and their
constraints/indexes:

- `taxonomy_dictionary` (code, name, revision `version`, status)
- `taxonomy_tag` (dictionary, code, name, description, status, optimistic
  `version`, `merged_into_tag_id`)
- `outbox_event` (event metadata columns, JSONB envelope, status, attempts,
  retry bookkeeping), unique on
  `(aggregate_type, aggregate_id, aggregate_version, event_type)`, partial index
  on due pending rows
- `consumer_delivery` (idempotency ledger), unique on `(consumer_name, event_id)`
- `search_index_document` and `matching_tag_projection` (consumer stubs)

All business tables follow the platform convention: `id` UUID, `org_id`,
`site_id`, `created_at`, `created_by`, `updated_at`, `deleted_at` (soft delete);
partial unique indexes ignore soft-deleted rows. The migration has a real
`downgrade()`; `upgrade -> downgrade base -> upgrade` and `alembic check` are
part of verification.

## 4. Event contract

`docs/event-structure.md` documents every field of the envelope, the payload,
the before/after snapshot and `merged_into`, plus versioning, ordering and
consumer obligations. `tests/test_acceptance_event_doc.py` enforces both
directions: every field emitted by the code is documented, and every field row
in the document is emitted by the code. The four JSON examples under
`docs/examples/` are generated from the production builder and validated against
the same Pydantic schemas, so documentation cannot drift from code.

## 5. Acceptance criteria mapping

1. **All four event types enter the outbox after their corresponding
   operations.** `tests/test_acceptance_events.py` exercises activation, update,
   deprecation and merge against PostgreSQL and validates the persisted envelope
   (event type, aggregate version, dictionary code, tag code, version, change
   summary, before/after, merged_into), plus one test that performs all four and
   asserts the complete set is in the outbox.
2. **Events are not emitted when a business transaction is rolled back.**
   `tests/test_acceptance_rollback.py`: the event is visible inside the open
   transaction, disappears after `rollback()` (and the tag stays `draft`); a relay
   on another connection never sees an uncommitted event; a real constraint
   violation later in the same transaction also discards the event.
3. **The event structure documentation specifies every field.**
   `tests/test_acceptance_event_doc.py` (see section 4).

Counterexamples are covered by `tests/test_counterexamples.py`: invalid
transitions (deprecate a draft, activate twice, update a deprecated tag), no-op
updates emit nothing, stale `expected_version` is rejected, merge into itself /
inactive target / across dictionaries is rejected, cross-tenant access is a 404,
duplicate tag codes are rejected - none of them writes an outbox row.

## 6. How to run

```bash
docker compose up -d db
python -m venv .venv && .venv/Scripts/activate
pip install -e ".[dev]"
export DATABASE_URL=postgresql+psycopg://outbox:outbox_local_dev@127.0.0.1:55432/outbox
alembic upgrade head
uvicorn taxonomy_outbox.api.main:app --port 8000
python examples/http_demo.py
```

Tests:

```bash
export TEST_DATABASE_URL=postgresql+psycopg://outbox:outbox_local_dev@127.0.0.1:55432/outbox
python -m pytest -q
```

Configuration is environment-only (see `README.md` and `taxonomy_outbox/config.py`).

## 7. Integration points

- **Matching engine**: consume `taxonomy.events` (Redis Streams consumer group),
  deduplicate on `event_id`, upsert `canonical_tag_code = tag_code` on
  activation/update, delete on deprecation, and on merge set
  `canonical_tag_code = merged_into.tag_code`. Replace
  `MatchingEngineConsumer.apply`'s stub table write with the real store;
  `docs/consumers.md` documents the exact seam.
- **Search index**: same subscription; upsert documents on
  activation/update, delete on deprecation and on merge (the surviving tag is
  already indexed). Replace `SearchIndexConsumer.apply`'s stub table write.
- **Transport**: any broker can replace Redis by implementing
  `publish(envelope)`; the outbox contract does not change.
- No dependency on other tickets is required; both consumers ship as stubs and
  the integration points are documented as the ticket allows.

## 8. Guarantees and limitations

- At-least-once publishing; consumers are effectively-once through the delivery
  ledger. A crash between publish and commit may republish, which the ledger
  absorbs.
- Per-tag ordering through the monotonic `version`; the unique aggregate-version
  index makes duplicate events for one version impossible.
- Multi-tenant isolation on `org_id` + `site_id` for reads, writes and
  projections.
- The two consumer projections are stubs by design (the ticket allows interface
  stubs/mocks first); wiring them to external stores is an integration step,
  documented but outside this ticket.
- The service does not manage dictionary archival or tag deletion; the ticket
  scope is activate / update / deprecate / merge event publishing.

## 9. Confidentiality

All identifiers, tags and examples are fictional. No client name, real person or
real enterprise data appears in the code, documentation, tests or this document.
No third-party SDK that sends data abroad is used; runtime configuration and
credentials are read only from environment variables.

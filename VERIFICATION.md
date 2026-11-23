# VERIFICATION - S2-TAX-022

Clause -> command -> expected -> measured. Every command below was run in this
workspace against a live PostgreSQL 16 database (`postgres:16-alpine` container)
on 2026-11-23, with Python 3.13.14 and pytest 9.2.0.

Environment used for the run:

```text
TEST_DATABASE_URL=postgresql+psycopg://outbox:outbox_local_dev@127.0.0.1:45159/outbox
```

(The compose file maps the same database to `127.0.0.1:55432`, which is the
default in `tests/conftest.py`; only the host port differs.)

## 1. Acceptance criterion 1 - all four event types enter the outbox

Clause: "All 4 event types enter the outbox after their corresponding operations (test passed)".

Command:

```bash
python -m pytest tests/test_acceptance_events.py --tb=no -q -o addopts="" -p no:warnings
```

Expected: one test per operation plus one combined test, all passing; each test
validates the outbox row and the persisted envelope (event type, aggregate
version, dictionary code, tag code, version, change summary, before/after,
merged_into).

Measured:

```text
5 passed
```

Covered operations and asserted event types:

| Test | Operation | Event type |
|---|---|---|
| `test_tag_activated_is_written_to_outbox` | draft -> active | `taxonomy.tag_activated` |
| `test_tag_updated_is_written_to_outbox` | PATCH name/description | `taxonomy.tag_updated` |
| `test_tag_deprecated_is_written_to_outbox` | active -> deprecated | `taxonomy.tag_deprecated` |
| `test_tag_merged_is_written_to_outbox` | merge source into target | `taxonomy.tag_merged` |
| `test_all_four_event_types_are_persisted` | all four in one lifecycle | the complete set of four |

## 2. Acceptance criterion 2 - no event when the business transaction rolls back

Clause: "Events are not emitted when a business transaction is rolled back (test passed)".

```bash
python -m pytest tests/test_acceptance_rollback.py --tb=no -q -o addopts="" -p no:warnings
```

Expected: the event exists inside the open transaction and disappears after the
rollback; a relay on another connection never sees an uncommitted event; a later
constraint violation in the same transaction discards the event as well.

Measured:

```text
4 passed
```

## 3. Acceptance criterion 3 - the event structure documentation specifies every field

Clause: "The event structure documentation specifies every field".

```bash
python -m pytest tests/test_acceptance_event_doc.py --tb=no -q -o addopts="" -p no:warnings
```

Expected: every field of the code registry appears as a documented field row,
every documented field row exists in the registry, each event type has its own
section, and each documented JSON example validates against the production
Pydantic schema.

Measured:

```text
10 passed
```

## 4. Counterexamples (negative paths emit nothing)

```bash
python -m pytest tests/test_counterexamples.py --tb=no -q -o addopts="" -p no:warnings
```

Expected: invalid transitions, no-op updates, stale versions, invalid merges,
cross-tenant access and duplicate codes are rejected and leave the outbox
unchanged.

Measured:

```text
11 passed
```

## 5. Relay and consumers

```bash
python -m pytest tests/test_relay_consumers.py --tb=no -q -o addopts="" -p no:warnings
```

Expected: a pending row is published exactly once and marked `dispatched`;
failures retry with backoff and become `failed` after max attempts; both
consumers build their projections; deprecation removes them; merge remaps the
canonical code; duplicate delivery is ignored.

Measured:

```text
6 passed
```

## 6. HTTP API

```bash
python -m pytest tests/test_api.py --tb=no -q -o addopts="" -p no:warnings
```

Expected: activation over HTTP commits tag + event, invalid transitions return
409 with no event, stale/no-op patch is rejected, cross-tenant access is 404,
and one dispatch batch publishes the pending rows.

Measured:

```text
5 passed
```

## 7. Migration and DDL assertions

```bash
python -m pytest tests/test_migration_ddl.py --tb=no -q -o addopts="" -p no:warnings
```

Expected: database at Alembic head; tables/indexes exist; the partial unique tag
code index, the tag status CHECK and the unique outbox aggregate version are
enforced by PostgreSQL.

Measured:

```text
5 passed
```

## 8. Full suite

```bash
python -m pytest --tb=no -q -o addopts="" -p no:warnings
```

Expected: the whole suite green.

Measured:

```text
46 passed in 8.39s
```

## 9. Migration roundtrip (upgrade -> downgrade -> upgrade)

```bash
alembic downgrade base
alembic upgrade head
alembic current
```

Measured:

```text
INFO  [alembic.runtime.migration] Running downgrade 0001_taxonomy_outbox -> , taxonomy dictionaries, ...
INFO  [alembic.runtime.migration] Running upgrade  -> 0001_taxonomy_outbox, taxonomy dictionaries, ...
0001_taxonomy_outbox (head)
```

No dependency on extensions or data is needed by the downgrade; the schema is
fully recreated by the next upgrade.

## 10. No model/migration drift

```bash
alembic check
```

Measured:

```text
No new upgrade operations detected.
```

## 11. DDL sample (outbox table)

```bash
docker exec <db> psql -U outbox -d outbox -c "\d+ outbox_event"
```

Measured (excerpt):

```text
Indexes:
    "outbox_event_pkey" PRIMARY KEY, btree (id)
    "ix_outbox_event_pending" btree (status, available_at) WHERE status::text = 'pending'::text
    "uq_outbox_event_aggregate_version" UNIQUE, btree (aggregate_type, aggregate_id, aggregate_version, event_type)
Check constraints:
    "ck_outbox_event_attempts" CHECK (attempts >= 0)
    "ck_outbox_event_status" CHECK (status::text = ANY (ARRAY['pending','dispatched','failed']))
```

## 12. End-to-end HTTP demo

Command (server running via `uvicorn taxonomy_outbox.api.main:app --port 18084`,
then `python examples/http_demo.py`):

Measured (abridged):

```text
{"step": "healthz", "status": 200, "body": {"status": "ok"}}
{"step": "create_dictionary", "status": 201, ...}
{"step": "activate:ai", "status": 200, "body": {"event_type": "taxonomy.tag_activated", "outbox_status": "pending", ...}}
{"step": "update:ai", "status": 200, "body": {"event_type": "taxonomy.tag_updated", ...}}
{"step": "merge:ml->ai", "status": 200, "body": {"event_type": "taxonomy.tag_merged", ...}}
{"step": "deprecate:nlp", "status": 200, "body": {"event_type": "taxonomy.tag_deprecated", ...}}
{"step": "outbox:pending", "status": 200, "body": [6 events: activated, activated, updated, activated, merged, deprecated]}
{"step": "dispatch", "status": 200, "body": {"scanned": 6, "published": 6, "failed": 0}}
{"step": "outbox:dispatched", "status": 200, "body": [6 events, all "status": "dispatched"]}
```

## 13. Documentation examples are generated, not hand-written

```bash
python examples/build_examples.py
```

Measured:

```text
wrote taxonomy.tag_activated.json
wrote taxonomy.tag_updated.json
wrote taxonomy.tag_deprecated.json
wrote taxonomy.tag_merged.json
```

The examples are validated against the same `EventEnvelope` schema by
`test_documented_example_matches_the_schema` (part of the 10 tests in section 3).

## Summary

| Clause | Result |
|---|---|
| 1. All 4 event types enter the outbox | pass (5 tests) |
| 2. No event on rollback | pass (4 tests) |
| 3. Event structure doc specifies every field | pass (10 tests) |
| Counterexamples (invalid operations emit nothing) | pass (11 tests) |
| Relay, retries, idempotent consumers | pass (6 tests) |
| HTTP API commit/rollback semantics | pass (5 tests) |
| Migration + DDL constraints | pass (5 tests) |
| Full suite | 46 passed |
| Migration roundtrip + no drift | pass |
| End-to-end demo (all four types dispatched) | pass |

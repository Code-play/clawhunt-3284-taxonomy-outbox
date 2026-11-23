# Taxonomy tag lifecycle event structure

This document is the contract between the Dictionary & Tag Center (producer) and
its subscribers: the matching engine and the search index. It is published and
versioned together with the code; `tests/test_acceptance_event_doc.py` fails if a
field emitted by the code is not documented here, or if this document describes a
field the code does not emit.

## 1. Topic, producer and delivery guarantees

- Producer: the Dictionary & Tag Center publishes on the tag lifecycle.
- Transport: every event is written to the `outbox_event` table inside the same
  database transaction as the tag change, then appended by the relay to the Redis
  Stream `taxonomy.events` (one entry per event; `event` holds this JSON).
- Delivery is **at least once**. Consumers must deduplicate on `event_id`
  (the reference consumers use the `consumer_delivery` ledger).
- Ordering is per tag: `aggregate_version` increases by exactly one for every
  accepted change of one tag, so a consumer can detect gaps or stale deliveries.
- A rolled-back business transaction leaves no outbox row at all: the event is
  never emitted for a change that did not commit.

## 2. Event types

### `taxonomy.tag_activated`

A draft tag became active and may now be used by matching and search.
`before` is `null`; `changed_fields` is `["status"]`.

### `taxonomy.tag_updated`

Name and/or description of a draft or active tag changed. `changed_fields` names
exactly what moved; a no-op update emits nothing at all.

### `taxonomy.tag_deprecated`

An active tag was retired. Consumers must stop using it for new work but keep
historical references addressable.

### `taxonomy.tag_merged`

A tag was folded into another tag. The event is published for the merged
(source) tag and `merged_into` names the surviving tag.

## 3. Envelope fields

Every event has this envelope. It is the object appended to the stream and the
object stored in `outbox_event.payload`.

| Field | Type | Presence | Description |
|---|---|---|---|
| `event_id` | string (UUID) | always | Unique event identifier; also the consumer idempotency key. |
| `event_type` | string | always | One of the four event types above. |
| `event_version` | integer | always | Version of this event contract; currently `1`. A breaking change increments it. |
| `occurred_at` | string (ISO 8601, UTC) | always | When the business change happened, from the producer clock, not the relay clock. |
| `org_id` | string (UUID) | always | Tenant of the tag; consumers must scope projections by it. |
| `site_id` | string (UUID) | always | Site of the tag within the tenant. |
| `aggregate_type` | string | always | Always `taxonomy_tag`. |
| `aggregate_id` | string (UUID) | always | The tag id; equals `payload.tag_id`. |
| `aggregate_version` | integer | always | The tag version after the change; equals `payload.version`. |
| `producer` | string | always | Always `taxonomy`. |
| `trace_id` | string or null | always | Correlation id propagated from the request (`X-Trace-Id`), null when absent. |
| `payload` | object | always | Event-specific content, documented in sections 4-7. |

## 4. Payload fields

The payload always contains the dictionary, the tag code, the version number and
a change summary, plus a before/after snapshot.

| Field | Type | Presence | Description |
|---|---|---|---|
| `dictionary_id` | string (UUID) | always | Id of the dictionary that owns the tag. |
| `dictionary_code` | string | always | Stable dictionary code (for example `industry`); the "dictionary" subscribers key on. |
| `dictionary_version` | integer | always | Dictionary revision counter after the change; increases on every tag lifecycle change in that dictionary. |
| `tag_id` | string (UUID) | always | Id of the tag. |
| `tag_code` | string | always | Stable tag code (for example `ai`); the "tag code" subscribers key on. |
| `tag_version` | integer | always | Version of the tag after the change; mirrors `version`. |
| `tag_status` | string | always | Status after the change: `draft`, `active`, `deprecated` or `merged`. |
| `version` | integer | always | The version number of this change (same value as `aggregate_version` and `tag_version`); monotonically increasing per tag. |
| `change_summary` | string | always | Human-readable one-line summary of the change, safe for logs and audit. |
| `changed_fields` | array of string | always | Names of the fields this event changed, for example `["status"]` or `["description","name"]`. |
| `before` | object or null | always | Snapshot of the tag before the change; `null` for `taxonomy.tag_activated` (there was no published state). |
| `after` | object | always | Snapshot of the tag after the change. |
| `merged_into` | object or null | `taxonomy.tag_merged` only | The surviving tag of a merge; `null` for every other event type. |

## 5. Tag snapshot fields

`before` and `after` share this shape.

| Field | Type | Presence | Description |
|---|---|---|---|
| `tag_id` | string (UUID) | always | Tag id at snapshot time. |
| `tag_code` | string | always | Tag code at snapshot time. |
| `tag_name` | string | always | Display name at snapshot time. |
| `tag_status` | string | always | Status at snapshot time. |
| `tag_version` | integer | always | Version at snapshot time; `after.tag_version` equals the event `version`. |

## 6. Merged-into fields

Present only on `taxonomy.tag_merged`.

| Field | Type | Presence | Description |
|---|---|---|---|
| `tag_id` | string (UUID) | `taxonomy.tag_merged` only | Id of the surviving tag. |
| `tag_code` | string | `taxonomy.tag_merged` only | Code of the surviving tag; consumers rewrite references to this code. |

## 7. Field semantics that consumers depend on

- `payload.version` is authoritative for ordering. A consumer that already saw
  version `N` of a tag must ignore a delivery with version `<= N`.
- `taxonomy.tag_updated` is only published when at least one field really
  changed; a no-op update emits nothing (`changed_fields` is never empty).
- `taxonomy.tag_merged` is published for the **source** tag. The source keeps
  its row with status `merged` and `merged_into_tag_id` set; the target tag is
  untouched by this event.
- `dictionary_version` is a coarse revision counter. Consumers that cache a
  whole dictionary can use it to invalidate, without assuming per-tag ordering.
- `occurred_at` is the producer time. Do not replace it with the consumer clock
  when persisting projections; that keeps replays deterministic.

## 8. Examples

The JSON files below are generated from the production builder
(`examples/build_examples.py`) and validated by the test suite, so they cannot
drift from the schemas.

| Event | Example file |
|---|---|
| `taxonomy.tag_activated` | [`docs/examples/taxonomy.tag_activated.json`](examples/taxonomy.tag_activated.json) |
| `taxonomy.tag_updated` | [`docs/examples/taxonomy.tag_updated.json`](examples/taxonomy.tag_updated.json) |
| `taxonomy.tag_deprecated` | [`docs/examples/taxonomy.tag_deprecated.json`](examples/taxonomy.tag_deprecated.json) |
| `taxonomy.tag_merged` | [`docs/examples/taxonomy.tag_merged.json`](examples/taxonomy.tag_merged.json) |

## 9. Versioning

- `event_version` versions the whole envelope/payload contract. Additive,
  optional fields keep the version; renaming or removing a field increments it
  and consumers get a migration window.
- `payload.version` / `aggregate_version` version one tag. It is the tag's
  optimistic concurrency version: every accepted mutation increments it by one.
- `payload.dictionary_version` versions one dictionary's tag set.

## 10. Consumer obligations

1. Deduplicate on `event_id`; Redis Streams redeliver after a consumer crash.
2. Skip stale deliveries (`payload.version` not greater than the stored version).
3. Keep `org_id` and `site_id` in every projection key; never mix tenants.
4. On `taxonomy.tag_merged`, rewrite references to the source `tag_code` using
   `merged_into.tag_code`; do not delete historical matches.
5. On `taxonomy.tag_deprecated`, stop offering the tag for new matching or
   indexing, but keep the historical record addressable.

See `docs/consumers.md` for runnable consumer examples.

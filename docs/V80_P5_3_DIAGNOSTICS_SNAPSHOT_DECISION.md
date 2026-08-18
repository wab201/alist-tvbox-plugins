# V80 P5-3 Diagnostics Snapshot Decision

Date: 2026-08-16

Chinese module alias: **P5-3 诊断快照覆盖层**

## Scope

P5-3 upgrades the existing private `Spider._diagnostic_snapshot()` owner from
a copied event list to the sealed P5-1 snapshot envelope. It does not add a
public route, persist diagnostics, emit a snapshot event, or alter any
TVBox/FongMi response or play ID.

## Owner

- Snapshot generation owner: the existing `Spider._diagnostic_snapshot()` only.
- Event buffer and ordering owner: the existing `_diagnostic_lock`,
  `_diagnostics`, and `_diagnostic_sequence` state only.
- Redaction owner: P4 `_short_error()` at `_diagnostic_event()` ingress only.
- Limit owner: `V80_OBSERVABILITY_LIMITS["max_snapshot_events"]`.
- Schema owner: `V80_OBSERVABILITY_SCHEMAS["snapshot"]`.

P5-3 adds no clock read. A snapshot is a deterministic view of already stored
events and does not receive `generated_at` or another timestamp.

## Envelope

The snapshot has exactly three top-level fields in this order:

| Field | Source |
| --- | --- |
| `schema` | `V80_OBSERVABILITY_SCHEMAS["snapshot"]` |
| `count` | Length of the copied `events` list |
| `events` | Oldest-to-newest copies of the most recent requested events |

The existing `limit` argument remains private and compatible: `None` or an
invalid value selects the policy maximum, while numeric values are clamped to
`1..max_snapshot_events`. The stored event buffer is already bounded to 256,
so P5-3 creates no second buffer and no dropped-event counter.

## Invariants

- Snapshot generation never calls `_diagnostic_event()` and cannot recurse.
- Snapshot generation never calls `_short_error()` or introduces a second
  redaction pass; stored events were already redacted at ingress.
- Returned event dictionaries and the returned list are detached from the
  internal buffer.
- The existing P5-2 event owner returns `dict(payload)` after storing the
  internal event, so callers cannot mutate the buffer after P4 ingress
  redaction; event fields remain bounded scalar values and the snapshot does
  not need deep copying or a second redaction owner.
- Snapshot reads do not increment sequence numbers or mutate the event buffer.
- No network, file I/O, persistence, retry, cache, thread, timer, clock, or
  logging subsystem is introduced.
- Public V70, the ten source parts, root index, deployment, and production
  state remain unchanged.

## Excluded

- Public or authenticated diagnostics endpoints.
- Snapshot persistence, upload, telemetry, or cross-process aggregation.
- Cache, circuit, provider, playback, or History state aggregation.
- Performance claims, private canary, device testing, and public promotion.

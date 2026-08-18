# V80 P5-2 Runtime Correlation Decision

Date: 2026-08-16

Chinese module alias: **P5-2 运行时关联字段覆盖层**

## Scope

P5-2 connects the sealed P5-1 observability schema to the existing private
`Spider._diagnostic_event()` buffer. It does not create a public diagnostics
response, persist diagnostics, or alter any TVBox/FongMi response or play ID.

## Owners

- Event owner: the existing `Spider._diagnostic_event()` method only.
- Redaction owner: the existing P4 `_short_error()` path only.
- Operation source: the existing P3 `TimeoutBudgetController` thread-local
  operation stack, lifecycle generation, and one monotonic scope sequence held
  for the lifetime of that controller.
- Time source: the existing event `time.time()` call. P5-2 adds no clock call.
- Error source: the existing P3 `_diagnostic_error_kind()` classification and
  the sealed P5-1 `v80_observability_error_code()` lookup.

## Field Sources

| Field | Source |
| --- | --- |
| `schema` | `V80_OBSERVABILITY_SCHEMAS["event"]` |
| `request_id` | Opaque digest of current scope sequence and lifecycle generation |
| `trace_id` | Root scope digest inherited by nested operations in the same lifecycle generation |
| `stage` | Fixed event-first, operation-second mapping into the P5-1 closed stage set |
| `error_code` | P5-1 lookup of the existing P3 reliability kind |
| `elapsed_ms` | Existing `elapsed_ms` or legacy `duration_ms` call-site evidence only |
| `provider` | Existing `provider`, or the existing resource `mode` field |
| `media_id`, `episode` | Existing exact-name diagnostic fields only; no inference from URLs, cache keys, or play IDs |

The identifiers are unique correlation handles within one Spider diagnostic
buffer lifetime. They are not stable storage IDs, are not reversible to media
or credential values, and are omitted when no valid TimeoutBudget operation is
active. Reset, cancellation, generation mismatch, and finished scopes invalidate
the context even if an old thread-local stack has not yet unwound.

## Stage Mapping

The mapping is deliberately closed and ordered:

1. History and playback-sync events -> `history`
2. Cache events -> `cache`
3. Follow persistence and lifecycle events -> `lifecycle`
4. Probe events -> `probe`
5. Route/player/playback events -> `playback`
6. Detail events -> `detail`
7. Match events -> `match`
8. Resource/search/category/home events -> `search`
9. Everything else -> `request`

## Invariants

- P4 redaction runs before any call-site value enters the managed fields.
- Existing diagnostic keys, error text, trace text, sequence, limit, and
  fail-closed behavior remain compatible.
- No network, file I/O, persistence, retry, cache, lock, thread, timer, clock,
  or second logging/redaction subsystem is introduced.
- Diagnostics Snapshot generation remains out of scope.
- Public V70, the ten source parts, root index, deployment, and production
  state remain unchanged.

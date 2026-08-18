# V80 P4 Security Policy

## Scope

P4-1 freezes a pure decision contract. It performs no DNS lookup, network request,
cache write, logging, retry, or timeout allocation. P4-2 applies that contract to
the existing media-route probe family only; other network call families remain
outside the runtime policy until later P4 work packages integrate them one seam at
a time. P4-3 freezes a pure post-parse JSON shape policy. P4-4 applies that policy
only to successful TMDB metadata JSON while preserving the existing response read,
parse, close, cache, retry, and TimeoutBudget owners. P4-5 adds only the TMDB
pre-parse byte and field-length boundary while reusing the same reader, deadline,
status, parser-normalization, and response-close ownership graph. P4-6 routes the
existing runtime diagnostics and stage report through one bounded redaction policy.
P4-7 applies a separate immutable 512 KiB pre-parse ceiling only to Douban JSON
requests and the Douban wish action while retaining the same shape, deadline,
session, retry, cache, and response-close owners.
P4-8 applies an independently evidenced 256 KiB decompressed-byte ceiling only to
`_DoubanClient.request_text`, preserving Requests text decoding, the existing
TimeoutBudget deadline, cache/stale behavior, and exactly-once response closure.

## Network zones

| Zone | Identity | Non-global address policy | Credential policy |
|---|---|---|---|
| `trusted_backend` | Exact configured origin for AList-TVBox, History, TMDB, or another owned backend | Private, loopback, and link-local addresses are allowed because the origin is explicit; unspecified, multicast, and reserved addresses are always rejected | Same-origin allowlist may retain credentials; cross-origin redirects remove them |
| `configured_internal` | Exact user-configured internal origin that is not an owned credential endpoint | Private, loopback, and link-local addresses are allowed only for the exact origin | Same-origin allowlist may retain caller-provided headers; it never receives headers from an external redirect |
| `external_untrusted` | Every origin not present in the two explicit sets | Every resolved address must be global; empty, mixed global/private, loopback, link-local, or private results are rejected | Only the cross-origin allowlist survives a redirect |

`trusted_backend` wins if an origin appears in both configured sets. Origins are
canonicalized by scheme, IDNA host, and effective port. Paths and queries never
affect trust classification, and userinfo is forbidden.

## Redirect decision table

| Source | Target | Result |
|---|---|---|
| Same origin | Same origin | Revalidate the target and keep only the same-origin header allowlist |
| Trusted/configured | Global external | Revalidate all resolved addresses and remove credentials, Cookie, Origin, Referer, and backend-only headers |
| External | Trusted/configured internal | Reject; an untrusted redirect cannot turn the plugin into an internal-network client |
| External HTTPS | External HTTP | Reject downgrade |
| Any | Missing or non-compliant resolution | Reject |
| Any | Sixth hop | Reject before target processing; the maximum is five hops |

Every hop receives a fresh resolved-address set. A later hop cannot reuse the
previous hop's DNS admission.

## Frozen existing byte ceilings

P4-1 records the existing V70/P3 ceilings without changing runtime behavior:

- URL: 16 Ki characters
- Route probe: 4 KiB
- Resource JSON: 2 MiB
- History JSON: 4 MiB
- History row/config: 128 KiB
- Ordinary header value: 16 KiB
- Cookie: 64 KiB
- Total request headers: 80 KiB

P4-3 freezes JSON container depth, total-node, and per-collection limits as a pure
post-parse decision. P4-5 additionally freezes the TMDB response at 2 MiB, object
keys at 1024 UTF-8 bytes, and string values at 128 KiB. Signed-URL cache policy,
other response families, and wider runtime adoption remain explicit P4 follow-up
work; the TMDB boundary does not imply they are complete. P4-7 independently caps
the two Douban JSON response paths at 512 KiB before parsing and reuses the P4-3
shape policy; it does not add Douban field-length policy. P4-8 independently caps
decompressed Douban HTML at 256 KiB after complete Top250 and wishlist envelope
evidence; it does not reuse either the TMDB 2 MiB or Douban JSON 512 KiB ceiling.

## Non-goals

- No second retry loop or replacement for TimeoutBudget.
- No global private-network block; explicit AList/History LAN endpoints remain valid.
- No TLS disable switch, implicit trust promotion, or fallback that converts a
  rejected external target into an internal target.
- No redirect, signed-URL cache, Provider, History, playback, general-session, or P5
  observability takeover in P4-8.
- No public V70 source, repository index, or deployment change.

## P4-2 media-route integration

P4-2 keeps the existing route-probe ownership graph intact. `_resolved_media_target()`
still performs DNS resolution; the pinned connection still owns IP selection,
Host/SNI, request I/O, and response closure; the existing redirect loop, probe
executor, cache, and TimeoutBudget remain authoritative. The overlay adds only four
audited insertions: target policy construction, initial probe-header filtering,
per-hop redirect decisions, and redirect-state transition.

- Exact configured `atvp_api`, `history_api`, and recorded History origins are trusted.
- External targets require every resolved address to be global.
- Each redirect target is freshly resolved before the redirect policy decision.
- External redirects cannot enter a trusted internal origin.
- External HTTPS cannot downgrade to HTTP.
- Cross-origin requests and returned playback headers use the fixed allowlist.
- Provider, History, TMDB, and general requests sessions are unchanged.
- No retry, transport, DNS cache, executor, cache, or timeout owner is added.

## P4-3 JSON shape policy

P4-3 appends a pure, iterative validator after the exact P4-2 output. It accepts
only `None`, exact `str`/`int`/`bool` types, finite `float`, `list`, and `dict` with
exact string keys. It returns the identical accepted object without normalization.

- Maximum container depth: 64
- Maximum total value nodes: 131072
- Maximum items in one list or object: 8192
- Unsupported Python values and non-finite floats are rejected.
- Stable rejection reasons never include the rejected key or value.
- Traversal is iterative and does not depend on Python recursion depth.
- No I/O, response parsing, network, cache, logging, retry, TimeoutBudget,
  response-close, or runtime hook is owned by the module.

TMDB and Douban are intentionally not integrated in P4-3. Their current non-200,
invalid-JSON, cache, response-close, and TimeoutBudget behavior remains unchanged.

## P4-4 TMDB JSON shape integration

P4-4 changes only the successful return in `Spider._request_tmdb()` from `data` to
`v80_validate_json_shape(data)`. The existing `_json_response` call still owns JSON
parsing and its invalid-JSON error. The 401/403, 429, and other non-200 decisions
remain before the success return, so error payloads retain their existing behavior
and are not shape-validated. The existing timeout child scope, requests session,
stream mode, cache callers, and `close_tracked()` finally block remain authoritative.

This is still a post-parse boundary. P4-4 does not cap bytes before the JSON parser,
does not impose string or field-specific limits, and does not integrate Douban,
Provider, History, playback, or a general requests session.

## P4-5 TMDB response boundary

P4-5 keeps `_json_response()` as the parser/error-normalization owner and adds an
optional bounded mode. Existing one-argument callers still call `response.json()`.
Only `_request_tmdb()` supplies `max_bytes`, the current `operation.deadline`,
`close_response=False`, and the fixed `TMDB` label; `_read_bounded_json_shared()`
therefore reuses the existing stream reader while the outer `close_tracked()`
finally block remains the only response-close owner.

- Maximum TMDB response: 2 MiB before JSON parsing.
- Maximum object key: 1024 UTF-8 bytes.
- Maximum string value: 128 KiB.
- `401`, `403`, and `429` fixed errors are decided before body iteration.
- Other non-200 invalid or oversized bodies retain generic `TMDB HTTP <status>`.
- Successful payloads run JSON shape validation before field-length validation.
- Accepted values are returned by identity; stable rejection reasons never echo data.
- No retry, cache, transport, session, TimeoutBudget, parser, or close owner is added.
- Douban, Provider, History, playback, and general requests sessions remain outside.

## Sealed evidence

P4-1 was sealed locally on 2026-08-15. The policy module is appended byte-for-byte
after the sealed P3 TimeoutBudget output and remains a leaf with no runtime call
site takeover.

- Policy module: 13919 bytes, SHA-256
  `8BB1DF6C481E6EC6FDA2A0DEE2B2EE52D562C9430F2C6FD049E06758C14D26B8`
- Isolated candidate: 822566 bytes, SHA-256
  `A1C922715DDA59168D9EB12D0D820A345341840BA9DCF0856F7238CF1C8B8F76`
- Policy tests: 42 passed
- Complete stage gate: 18/18 passed; pytest 1412 passed; Golden, Macro A/B,
  Chaos 12/12, ATVP, dual runtime, FongMi category, and AList-TVBox 1.45.1 passed
- Managed sensitive-data scan: 112 files, zero findings
- Seal report: `work/v80-p4-1-security-policy-stage-gate-sealed-20260815.json`

Later P4 packages must continue integrating one existing network call family or
one unified response boundary at a time. They must not add a second retry owner,
bypass TimeoutBudget, or claim the remaining JSON-depth, collection, metadata,
redaction, and signed-URL-cache work complete.

## P4-2 sealed evidence

- P4-1 overlay input: 822566 bytes, SHA-256
  `A1C922715DDA59168D9EB12D0D820A345341840BA9DCF0856F7238CF1C8B8F76`
- Route overlay insertions: `target-policy`, `probe-headers`, `redirect-decision`,
  `redirect-transition`
- Final isolated candidate: 823561 bytes, SHA-256
  `D8B2E08B80DCD24CF55205ABA8CE441136587FEBE2BCA216D90A29EEC9520D2F`
- Route overlay tests: 10 passed
- Key combined regression: 461 passed
- Complete stage-gate target: 18/18 passed; pytest 1426 passed; Golden, Macro A/B,
  Chaos 12/12, ATVP, dual runtime, FongMi category, and AList-TVBox 1.45.1 passed
- Seal report: `work/v80-p4-2-route-security-stage-gate-sealed-20260815.json`

## P4-3 contract evidence

- P4-2 route output input: 823561 bytes, SHA-256
  `D8B2E08B80DCD24CF55205ABA8CE441136587FEBE2BCA216D90A29EEC9520D2F`
- JSON shape policy module: 2383 bytes, SHA-256
  `91AAD2A2417D226C87DD750D7C2C825E01D176A7BE699857B9239C5EBFCF3EAF`
- Final isolated candidate: 825944 bytes, SHA-256
  `8FB4EEDAB97057412D622881A074BDA6D04F76617B81CA6802B6D34525FB70F0`
- JSON shape policy tests: 12 passed; combined P4 tests at that point: 64 passed
- The standalone complete-gate attempt correctly rejected a concurrently changing
  implementation tree; P4-3 is therefore sealed by the inclusive P4-4 report below.

## P4-4 sealed evidence

- P4-3 candidate input: 825944 bytes, SHA-256
  `8FB4EEDAB97057412D622881A074BDA6D04F76617B81CA6802B6D34525FB70F0`
- Overlay builder: 7094 bytes, SHA-256
  `768E3E0F7FAF4B9E055AFADA4608C919302BF57F741F4C329EDFFA218A8171D5`
- Final isolated candidate: 825969 bytes, SHA-256
  `4746D9EB74B6351EFBF8764985BA295F6936914A7F0A47CFACD6AC52257E86C7`
- Combined P4 tests: 74 passed; P4-4 overlay tests: 10 passed
- Complete repository pytest: 1456 passed
- Managed sensitive-data scan: 118 files, zero findings
- Complete stage gate: 18/18 passed; Golden, Macro A/B, Chaos 12/12, ATVP,
  dual runtime, FongMi category, and AList-TVBox 1.45.1 passed
- Seal report: `work/v80-p4-4-tmdb-json-shape-stage-gate-sealed-20260815.json`

## P4-5 sealed evidence

- P4-4 candidate input: 825969 bytes, SHA-256
  `4746D9EB74B6351EFBF8764985BA295F6936914A7F0A47CFACD6AC52257E86C7`
- TMDB response policy module: 1735 bytes, SHA-256
  `C2D56B1432AB66163591953BA0ACD532A71BE0D963984EAF78C31F70DF3BD375`
- Appended policy output: 827704 bytes, SHA-256
  `3CDCB55A06A9BA862DBE541AAD8CF36E32887B7A98F2F4487E78BA29A5668443`
- Final isolated candidate: 829040 bytes, SHA-256
  `60B083C7F3DF4DCD368CA92F39296C8F3885A36B1491A8D5507169A474DBFEE4`
- Combined P4 tests: 103 passed; complete repository pytest: 1493 passed
- Managed sensitive-data scan: 122 files, zero findings
- Macro A/B: 50000 equal, zero different, zero errors each; Chaos: 12/12 passed
- Seal report: `work/v80-p4-5-tmdb-response-boundary-stage-gate-sealed-20260815.json`

## P4-6 candidate evidence

- P4-5 candidate input: 829040 bytes, SHA-256
  `60B083C7F3DF4DCD368CA92F39296C8F3885A36B1491A8D5507169A474DBFEE4`
- Diagnostic Redaction Policy module: 9503 bytes, SHA-256
  `4A05F0910BEF7FCFA70CFEAA4D25B5B9B05482150A004CB3AFF9D5C1CD17A831`
- Appended policy output: 838543 bytes, SHA-256
  `23023B88E3EFA12A2DE97D6E3833CAEC8855FCB4C0E9F766558C029D3C3E0580`
- Final isolated candidate: 837931 bytes, SHA-256
  `AF00837D15B2168BE9B211D64594A70A889DE87EEEE7BAC21607F430BB7756E3`
- Runtime limits: 4096 output characters; 32 explicit secrets; 4096 characters per secret
- Report limit: stage-gate uses the same managed core with a fixed 12000-character output
- Coverage: credential headers, assignments, auth schemes, URL userinfo, signed query,
  encoded query/path structure, playback route tokens, structured values, event/level,
  and diagnostic field keys and values
- Ownership: two overlay anchors; no new network, I/O, retry, cache, transport,
  TimeoutBudget, session, response-close, or lifecycle owner
- Focused build/gate tests: 252 passed; combined P4 tests: 172 passed;
  complete repository pytest: 1602 passed
- Decision evidence: `work/v80-p4-6-diagnostic-redaction-decision-20260815.json`
- Seal report path: `work/v80-p4-6-diagnostic-redaction-stage-gate-sealed-20260815.json`

## P4-7 pre-seal candidate evidence

- P4-6 candidate input: 837931 bytes, SHA-256
  `AF00837D15B2168BE9B211D64594A70A889DE87EEEE7BAC21607F430BB7756E3`
- Credential-free fixture set: 8 payloads, SHA-256
  `C4198A408607B67672A3460EC60DBA0191F97084F23AFA68BB9CC084559754A0`
- Ceiling evidence: largest canonical fixture 561 bytes; conservative 50-item
  projection 28050 bytes; fixed response maximum 512 KiB, about 18.69x headroom
- Douban response policy module: 251 bytes, SHA-256
  `69C7AEF61E8724616A6621CF74C7686D702D34A8A6E3C207DB430D50301A4170`
- Appended policy output: 838182 bytes, SHA-256
  `91B9FB70EEC5B84E40A0E6DEB4DFFC1B0E599A5D3904263D885FABB2C180637C`
- Final pre-seal candidate: 839093 bytes, SHA-256
  `B1F980E71AC95CF9C6F143C568CA0B724917E0D8F98B43F09FDBD1B1A6284145`
- Integration owners: `_DoubanClient.request_json` and the Douban wish POST inside
  `_v80_action_unbounded`; existing bounded reader, JSON shape, deadline,
  session/retry/cache/stale, and outer `close_tracked()` ownership are reused
- Verification: package 29 passed; combined P4 201 passed; build/stage-gate directed
  185 passed; complete repository pytest 1639 passed; managed sensitive scan
  132 files with zero findings
- Decisions: `work/v80-p4-7-douban-json-response-boundary-decision-20260815.json`
  and `work/v80-p4-7-douban-json-response-fixture-decision-20260815.json`
- AList-TVBox 1.46.1 seal report:
  `work/v80-p4-7-alist-tvbox-1461-stage-gate-sealed-r2-20260816.json`
- Formal gate: 18/18 passed; complete pytest 1667 passed; Macro A/B each
  `50000 equal / 0 different / 0 errors`; Chaos 12/12
- This seal did not authorize deployment, a public V70/index write, or transition
  to P5.

## P4-8 seal-input evidence

- Owner: `_DoubanClient.request_text` only
- Complete envelope observations: Top250 64547 decompressed bytes; wishlist 57197
  decompressed bytes with SHA-256
  `AA28F4570F11493F8B9EBB19E6176E2A12368817F0371804CC6E2C442EADB0C9`
- Wishlist observation contract: one authorized low-frequency request, HTTP 200,
  no redirect, `text/html; charset=utf-8`, 15 grid items, 15 valid movie subject
  links, and no persisted body, URL, account identifier, title, or card data
- Parser projection maximum: 12258 bytes
- Ceiling formula: `round_up_64KiB(max(16*P,4*O))`
- Selected response maximum: 262144 bytes
- P4-7 candidate input: 839093 bytes, SHA-256
  `B1F980E71AC95CF9C6F143C568CA0B724917E0D8F98B43F09FDBD1B1A6284145`
- Douban HTML response policy module: 271 bytes, SHA-256
  `DBBA0B73239F25884A4FECD9CCB3014D0AC2772D5B3334C76EBCCE98D018EDB8`
- Appended policy output: 839364 bytes, SHA-256
  `A817548D2D168A225DD7ED77BCC18FA4236408D6066ED09611B03D06D8B0B93F`
- Final candidate: 840543 bytes, SHA-256
  `749F16F38DE178756C48AE4A857F30B509F16ACFFAF5E28FF421474852E4892A`
- Ordering: non-200 status before header/body inspection; declared-length rejection
  before iteration; actual decompressed stream count before Requests text decoding;
  character-based short-page validation after decoding
- Ownership: existing session/retry/cache/stale/TimeoutBudget graph and
  `close_tracked()` remain authoritative; no second parser, reader, retry, cache,
  timeout, session, or close owner is introduced
- Formal seal report path:
  `work/v80-p4-8-douban-html-response-boundary-stage-gate-sealed-20260816.json`;
  final status is determined only by that report's `admit` and content-addressed
  implementation-tree evidence

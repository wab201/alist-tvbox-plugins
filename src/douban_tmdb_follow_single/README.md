# Douban/TMDB Follow Single - V80 development source

This directory is the V80 development source. The public
`py/豆瓣TMDB追更单入口.py` V70 file remains a read-only compatibility baseline.

`release.json` defines the writable V80 development build under `build/v80-dev/`.
`baseline_v70.json` separately freezes the public V70 source and root index and
cannot be used with `--write`. The ten files under `parts/` are byte-preserving
slices of V70 for this first migration step; they are not independently
importable modules.

## 中文维护别名

下表是维护导航，不修改文件名、Python 符号、构建顺序或运行时合同。`parts/`
中的 10 个文件仍是有序源码切片；根目录中的 36 个 `.py` 文件仍按现有
依赖图和构建器使用。

| 路径 | 中文别名 | 阶段 | 类型 |
| --- | --- | --- | --- |
| `parts/00_module_prelude.pyinc` | 启动前导与兼容层 | P1 | chunk |
| `parts/01_runtime_components.pyinc` | 运行时传输与持久化组件 | P1 | chunk |
| `parts/02_filter.pyinc` | AList-TVBox 过滤器适配层 | P1 | chunk |
| `parts/03_spider_runtime.pyinc` | FongMi Spider 运行时入口 | P1 | chunk |
| `parts/04_follow_workflows.pyinc` | 追更列表与刷新流程 | P1 | chunk |
| `parts/05_history_sync.pyinc` | 历史同步与续播匹配 | P1 | chunk |
| `parts/06_resource_discovery.pyinc` | 资源发现与来源归一化 | P1 | chunk |
| `parts/07_resource_ranking.pyinc` | 资源分组评分与排序 | P1 | chunk |
| `parts/08_playback_transport.pyinc` | 播放路由与传输输出 | P1 | chunk |
| `parts/09_metadata_and_utilities.pyinc` | 元数据接口与通用工具 | P1 | chunk |
| `resource_row_identity.py` | 资源行身份识别 | P2 | module |
| `resource_candidate_merge.py` | 候选列表身份去重合并 | P2 | module |
| `resource_candidate_ordering.py` | 候选公平排序 | P2 | module |
| `resource_candidate_pipeline.py` | 候选处理流水线 | P2 | module |
| `resource_candidate_preference.py` | 候选行偏好计算 | P2 | module |
| `resource_candidate_shadow.py` | 候选差分影子 | P2 | module |
| `resource_candidate_shadow_policy.py` | 候选影子准入策略 | P2 | module |
| `resource_candidate_shadow_composition.py` | 候选影子组合器 | P2 | module |
| `resource_candidate_shadow_background.py` | 后台候选影子输入适配 | P2 | module |
| `resource_candidate_shadow_runtime.py` | 候选影子运行时接缝 | P2 | module |
| `resource_models.py` | 资源标准模型 | P2 | module |
| `resource_schema.py` | 资源 Schema 注册 | P2 | module |
| `resource_normalization.py` | 标题年份季号归一化 | P2 | module |
| `resource_matching.py` | 标题年份季号匹配判定 | P2 | module |
| `resource_scoring.py` | 单标题匹配评分 | P2 | module |
| `resource_row_scoring.py` | 资源行证据聚合评分 | P2 | module |
| `resource_row_merge.py` | 双资源行字段合并 | P2 | module |
| `resource_shadow.py` | 资源归一化影子映射 | P2 | module |
| `resource_provider.py` | 资源来源适配器 | P2 | module |
| `resource_search_plan.py` | 分层搜索计划 | P2 | module |
| `resource_search_shadow.py` | 分层搜索影子组合 | P2 | module |
| `resource_search_v70_adapter.py` | V70 搜索行适配 | P2 | module |
| `resource_search_shadow_runtime.py` | 分层搜索影子运行时 | P2 | module |
| `resource_output_admission.py` | V80 输出切换准入 | P2 | module |
| `history_sync_v145.py` | History 同步引擎 | P3 | module |
| `reliability_contract.py` | 可靠性失败与重试合同 | P3 | module |
| `cache_health_contract.py` | 缓存健康与失败退避合同 | P3 | module |
| `background_bulkhead_contract.py` | 后台任务舱壁合同 | P3 | module |
| `timeout_budget_contract.py` | 端到端超时与生命周期合同 | P3 | module |
| `security_policy.py` | 网络区域与重定向安全策略 | P4 | module |
| `json_shape_policy.py` | JSON 结构边界策略 | P4 | module |
| `tmdb_response_policy.py` | TMDB 响应字段边界策略 | P4 | module |
| `diagnostic_redaction_policy.py` | 诊断信息脱敏策略 | P4 | module |
| `douban_response_policy.py` | 豆瓣 JSON 响应字节策略 | P4 | module |
| `douban_html_response_policy.py` | 豆瓣 HTML 响应字节策略 | P4 | module |
| `observability_policy.py` | 可观测事件与错误码策略 | P5 | module |

P1 and P2-1 through P2-7 completed local acceptance on 2026-08-13. P2-1 adds four
immutable normalized models, stable serialization, pure shadow mappers, and
credential-free synthetic fixtures. P2-2 adds fixed schema identifiers,
payload detection, and row classification for `vod1`, `vod`, `pansou`, and
`telegram`; it does not add provider classes, networking, caches, scoring, or
runtime takeover. P2-3 adds pure title normalization, year extraction, and
season extraction with direct V70 equivalence contracts. P2-4 adds a pure
three-state title/year/season decision contract without scores, weights, or ranking.
P2-5 adds only the frozen V70 decorated-title admission rule, newline-separated
string aliases, and longest-match helper return semantics. P2-6 adds the frozen
single-title scoring policy: bound resource 10000, exact title 500, decorated
title 470, exact season +80, and exact year +30. Its immutable result includes
the decision reason and score components, but it does not rank or select multiple
candidates. The complete stage gate passed 475 tests, 15 Golden behavior
comparisons, the fixed six-module DAG, the 40-file credential scan, ATVP
direct-play, FongMi dual runtime/category contracts, and the AList-TVBox 1.44.0
source contract. P2-7 adds only the pure row aggregation boundary: native dict
title collection, work-title precedence, the first 32 nested links, parent-row
year evidence, and maximum single-title score. It does not rank multiple rows.
The row-scoring narrow suite passes 17 tests; combined P2-6 scoring and P2-7
row-scoring tests pass 40 tests. The complete stage gate then passed 492 tests,
15 Golden behavior comparisons,
the fixed seven-module DAG, the 42-file credential scan, ATVP direct-play,
FongMi dual runtime/category contracts, and the AList-TVBox 1.44.0 source
contract. P2-8 adds only the pure candidate-ordering boundary over precomputed
score, preference, mode, and provider metadata. It filters non-positive scores,
keeps stable input order for equal preferences, performs provider then mode
round-robin ordering, and returns every original row reference. It does not
merge identities, detect providers, recalculate scores, truncate results, or
take over runtime paths. Its narrow suite passes 11 tests; the complete stage
gate passes 503 tests with an eight-module DAG and a 44-file credential scan.
P2-9 adds only the frozen V70 candidate-preference tuple over precomputed score,
password, and timestamp evidence. It preserves the native-dict boundary,
work-title state, validated-groups and seven metadata fields without importing
scoring, password, timestamp, provider, merge, or runtime code. Its narrow suite
passes 35 tests; the complete stage gate passes 538 tests with a nine-module DAG
and a 46-file credential scan. P2-10 adds only the frozen V70 two-row merge over
precomputed preferences. It preserves strict primary selection, empty-field fill,
resource ID and timestamp precedence, validated-group invalidation, shallow copies,
and native conversion exceptions without importing identity, provider, sorting, or
runtime code. Its narrow suite passes 54 tests; the complete stage gate passes 592
tests with a ten-module DAG and a 48-file credential scan. All ten P2 modules remain
outside the release manifest and ten published parts. P2-11 adds only the frozen
V70 row identity for raw IDs and native dict rows. It preserves the fixed six-field
priority, mode-sensitive plain IDs, limited decoding, lowercase push handling,
HTTP identity normalization, BTIH unification, and ED2K hash selection without
moving callers or adding list deduplication. Its narrow suite passes 39 tests; all
P2 module tests pass 301 tests, and the complete stage gate passes 631 tests with
an eleven-module DAG and a 50-file credential scan. All eleven P2 modules remain
outside the release manifest and ten published parts. P2-12 adds only the frozen
V70 candidate-list merge orchestration over the P2-11 identity and an injected
two-row merger. It skips non-dicts, shallow-copies accepted rows, computes each
incoming identity once, retains empty identities, binds the first non-empty
identity position, and feeds later duplicates the current merge result without
moving callers or importing provider, sorting, scoring, or runtime behavior. Its
narrow suite passes 31 tests; all P2 module tests pass 332 tests. The complete
stage gate collects 662 project tests, with 660 passed and two existing Windows
symlink tests skipped, and uses a twelve-module DAG plus a 52-file credential
scan. All twelve P2 modules remain outside the release manifest and ten published
parts, so the V80 development build is still byte-identical to the public V70
source. P2-13 adds only the frozen V70 post-merge candidate pipeline. It scores
each merged row once, filters non-positive rows, completes preference sorting for
all first-seen modes before provider resolution, and then delegates provider/mode
fairness to P2-8. The public API accepts injected merge, score, preference, and
provider callbacks; callers and runtime paths remain unchanged. Its narrow suite
passes 21 tests; all P2 module tests pass 353 tests. The complete stage gate
collects 683 project tests, with 681 passed and two existing Windows symlink tests
skipped, and uses a thirteen-module DAG plus a 54-file credential scan. All
thirteen P2 modules remain outside the release manifest and ten published parts.
This does not authorize changing the public source or index.

P2-14 adds only a pure, redacted comparison seam over the P2-13 pipeline. The
report contains exactly `status`, `legacy_count`, `candidate_count`,
`first_difference`, and `error_type`; it never contains candidate rows or
exception messages, catches `Exception` by type only, and leaves
`BaseException` untouched. Neither V70 call site uses the seam. A 2,000-iteration
benchmark over 20 rows measured `5686.525 us/call` for legacy ordering and
`11013.866 us/call` for legacy plus shadow (`1.937x`), so unconditional runtime
integration is not authorized. The narrow suite passes 17 tests; all P2 module
tests pass 370 tests. The complete stage gate collects 700 project tests, with
698 passed and two existing Windows symlink tests skipped, and uses a
fourteen-module DAG plus a 56-file credential scan. A fixed-seed 50,000-case
differential reports 50,000 equal, zero different, and zero errors. All three
scoped audits report zero findings. All fourteen P2 modules remain outside the
release manifest and ten published parts.

P2-15 adds a stateless scheduling decision for that report seam. Only literal
`True` enables it; `already_sampled` blocks repeated work before validation,
`sample_every=1` selects every eligible call, and larger intervals use the first
eight SHA-256 bytes for stable cross-process buckets. Missing keys and budgets
below the estimated microsecond cost skip the run. The result contains only
`run` and `reason`, never the sampling key. Its narrow suite passes 25 tests; all
P2 module tests pass 395 tests. A fixed-seed 50,000-case reference differential
reports 50,000 equal, zero different, and zero errors across all six reasons. The
complete stage gate collects 725 project tests, with 723 passed and two existing
Windows symlink tests skipped, and uses a fifteen-module DAG plus a 58-file
credential scan. The policy is not imported by either V70 call site, the release
manifest, or the ten published parts.

P2-16 adds only the pure composition boundary between the P2-15 admission
decision and the P2-14 redacted report. It returns a fixed `decision`/`report`
envelope, does not consume rows or callbacks when admission is skipped, and
does not generate, persist, or decrement the caller-owned sampling key,
dedicated shadow budget, or `already_sampled` state. Its narrow suite passes 12
tests; all P2 module tests pass 407 tests. A fixed-seed 50,000-case composition
differential reports 50,000 equal, zero different, and zero errors while covering
all six decision reasons and equal/different/error report states. The complete
stage gate collects 737 project tests, with 735 passed and two existing Windows
symlink tests skipped, and uses a sixteen-module DAG plus a 60-file credential
scan. All three scoped audits report zero findings. The composition API remains
outside both V70 call sites, the release manifest, and the ten published parts.

P2-17 adds only a pure development adapter for the future background call
site. It defaults to disabled with zero dedicated shadow budget, accepts only
nonnegative exact integers as generations, and hashes a domain-separated
`cache_key` plus generation only when literal `True` is enabled and that
generation has not already been sampled. The raw key is never returned. The
caller still owns `sampled_generation` and the shadow budget; the adapter only
returns the six keyword arguments required by the P2-15 policy and never reads
the foreground validation or search budgets. Its narrow suite passes 29 tests;
all P2 module tests pass 436 tests. A fixed-seed 50,000-case differential
reports 50,000 equal, zero different, and zero errors across all six decision
reasons, with sample-key lengths limited to zero or 64. The complete stage gate
collects 766 project tests, with 764 passed and two existing Windows symlink
tests skipped, and uses a seventeen-module DAG plus a 62-file credential scan.
All three scoped audits report zero findings. The adapter remains outside both
V70 call sites, all runtime paths, the release manifest, and the ten published
parts.

P2-18 proves that the fixed eight-module shadow closure can be statically
vendored into one file without changing any runtime call site. The builder uses
AST only to validate and locate same-package relative imports, removes complete
import line spans, enforces a fixed forward-only topology, and rejects top-level
symbol collisions, conflicting import bindings, missing imported symbols, and a
relative import sharing a physical line with another statement. It does not use
`exec`, runtime module registration, `sys.modules` injection, `ast.unparse`, or a
general-purpose bundler. The output is 16,070 bytes with SHA-256
`9610528E9023C77BA051F789C7C75437D0873AC0B7CC58DA20A87D4ECC9668FD`; the
closure SHA-256 is
`00A8ECF9688B4677088C4C2E51F86039A19609C2CD6163544B1E8915629D8EB2`.
Its narrow suite passes 19 tests; all P2 module tests pass 455 tests. A
fixed-seed 50,000-case differential reports 50,000 equal, zero different, and
zero errors while covering all six decision reasons, all three report states,
and zero/64 sample-key lengths. The complete stage gate collects 785 project
tests, with 783 passed and two existing Windows symlink tests skipped, and all
12 required steps pass with a 65-file credential scan. Initial audit findings
for two redundant checks/metadata fields, missing root-index isolation coverage,
and same-line relative-import deletion were fixed; the final simplify, harden,
and spec audits report zero findings. The builder holds the generated bytes in
memory and its CLI only prints the validation result; P2-18 does not write a
vendor-proof file. The manifest only freezes an isolated output path, and P2-18
keeps the vendor outside every runtime call site, the public source and index,
the release manifest, and the ten published parts.

P2-19 appends those exact vendor bytes to the isolated V80 single-file
development output without inserting a separator. The result is exactly the
616,699-byte frozen V70 prefix plus the 16,070-byte vendor suffix: 632,769 bytes,
SHA-256 `F7590CEFD7A882CFED00D86745A68C210FB1D55B976D1228BF8AD7791D6F3172`.
The manifest remains version 70 with `index_contract: none`. Before insertion,
the build rejects namespace collisions between V70 and the vendor; the vendor
builder also rejects dynamic top-level statements, and the stage gate checks a
fixed SHA-256 for each of the ten frozen parts. The narrow suite passes 75 tests
with two Windows symlink skips; all P2 and Golden tests pass 464 tests. The
complete gate collects 800 tests, with 798 passed and two skipped, and all 13
required steps pass. Its required P2-19 differential independently regenerates
50,000 cases and verifies zero differences or errors, fixed build fingerprints,
all six decision reasons, all three report states, and zero/64 sample-key
lengths. No Spider or Filter call site references the vendor yet.

P2 macro batch A adds the first runtime shadow hook without changing production
output. A nine-module vendor is inserted at six fixed anchors; the only call is
after `_schedule_supplement_resource_search.worker` has committed production
state and cleared its job/admission bookkeeping. The hook stays outside the
cache lock, defaults off, owns a separate zero-default budget and generation
sample state, and never writes `_resource_candidates` or consumes production
search/validation budgets. The final development output is 636,475 bytes with
SHA-256 `809CB654A74DEC0364A62FE8D43FFA1BC72A43ECADD0575CCD479EFB78755FFB`;
the vendor SHA-256 is
`F8C118103A09AC67F8CE8DBE5F7DCD7891D40F81222CD28A4BF59223E7E1603D`.
The integration suite passes 64 tests with two Windows symlink skips, all P2
and Golden tests pass 479 tests, and the complete gate passes 813 tests with
two skips. A fixed-seed 50,000-case runtime differential reports 50,000 equal,
zero different, and zero errors. One pre-admission row materialization issue was
removed; the final simplify, harden, and spec reviews report zero findings.
Macro batch B now owns fixed Provider/Schema boundaries and layered resource
search, remains shadow-only, and must reuse the existing V70 I/O and lifecycle
contracts instead of adding a generic provider framework.

Macro B-B1 adds `resource_provider.py` as a static four-entry adapter registry.
Each adapter freezes the V70 endpoint, search/detail parameters, accepted
payload and row schemas, and the existing candidate normalizer. Unknown schemas
produce no candidates and there is no dynamic registration or I/O. The first
review replaced a generated registry with four explicit entries. The provider,
schema, model, gate, build-isolation, and credential checks pass 103 tests; the
public V70 and isolated development fingerprints remain unchanged. B2 will add
only a pure layered-search plan before any runtime integration.

Macro B-B2 adds `resource_search_plan.py`. Given available local layers and
registered modes, it emits the immutable order `cache`, `recent_success`,
`binding`, `vod1`, `vod`, `pansou`, `telegram`; the last two are marked as
supplement providers. Mode input is normalized and deduplicated through B1's
fixed registry. The planner performs no I/O, scheduling, cache access, or
runtime state mutation. Its provider/schema/model/gate isolation suite passes
108 tests, the managed scan covers 75 files, and both build fingerprints remain
unchanged. B3 will compose injected local candidates and provider payloads into
a pure layered shadow result.

Macro B-B3 adds `resource_search_shadow.py`. It combines already-normalized
cache/recent/binding candidates with registered provider payloads and returns
immutable `LayeredResourceBatch` values in B2 order. It deliberately leaves
deduplication, scoring, and scheduling to the existing candidate pipeline.
Omitted provider modes are inferred from payload keys; an explicit empty list
disables providers. The related suite passes 114 tests, the managed scan covers
77 files, and build fingerprints remain unchanged. The future runtime hook is
fixed after `_resource_candidates` has assembled mode and bound rows but before
the existing fair ordering call, so no extra I/O is required. B4 will first add
a pure V70-row adapter; it will not alter the runtime build yet.

Macro B-B4 adds `resource_search_v70_adapter.py`. It classifies assembled V70
rows with the frozen identity contract using cache, recent-success, binding,
then provider priority, and feeds the typed batches from B3. Encoded URL
identity, overlapping local layers, empty provider batches, unknown modes, and
input immutability are covered. The related suite passes 158 tests, the managed
scan covers 79 files, and build fingerprints remain unchanged. A read-only
namespace audit found no collision with V70 and only three private helper-name
collisions inside the future closure: `_text`, `_mode`, and `_first`. B5 will
prefix only those helpers and expand the fixed vendor; no generic bundler is
planned. The runtime overlay remains a later B6 step.

Macro B-B5 prefixes those private helpers by module and extends the fixed vendor
from nine to sixteen modules by appending the B1-B4 closure in dependency order.
The flattened V70 layered-search adapter is checked against the source module;
the complete related seal passes 169 tests with two Windows symlink skips. The
vendor is 58,319 bytes with SHA-256
`04A308757A40179B5F38170185E5669983BABE134E00521C3B75100E2CFD1588` and closure
SHA-256 `8F13F7D449CFD866A3B18AA26395AAD00BAD79C94425454CF95306AD72190D9D`.
The isolated development output is 676,335 bytes with SHA-256
`31A32AF22A883957DAF70333A3A7089760EA0ED05DE4FFE84E844AE349E36015`.
At the B5 seal, the six existing Macro A overlay anchors were unchanged and none
of the seven new modules had a runtime call site; B6 was reserved as the first
layered-search overlay and is recorded below.

Macro B-B6 adds `resource_search_shadow_runtime.py` and the layered-search call
at the frozen `_resource_candidates` seam after all V70 I/O and local/bound row
assembly but before fair ordering. It defaults off, owns an independent
zero-default budget, sample generation, lock, and last report, and persists only
layer/mode counts plus an error type. Initialization and `destroy()` clear its
sample/report state, while stale generations cannot commit. The fixed vendor now
contains 17 modules and is 61,679 bytes with SHA-256
`53C6A87F2CFF65C4B9FABADF800D3D0F2291D90E3122174699F1DA4C2C8EF857`; its closure
SHA-256 is `BD591DFEC19FA242F779AE93EBC9B01EB2787A63C25CECFBF0319D682DF355E8`.
The eight-anchor development output is 681,512 bytes with SHA-256
`52C9ABA52F9572790B268CF0DB95B4302952EE3CACA9A4ED337CA843E69F92BE`.
The B6 seal passes 584 tests with two Windows symlink skips, an 82-file managed
credential scan, the P2 DAG, and all three ATVP/FongMi compatibility gates.
Both Macro A and Macro B 50,000-case differentials report 50,000 equal, zero
different, and zero errors. The merged audit found one destroy-state reset gap;
the fixed lifecycle regression and follow-up audit close it with no remaining
findings.

Macro C-C1 adds the leaf-only `resource_output_admission.py` policy. Admission
requires a literal `True` switch followed by literal `True` evidence for the
development build, candidate shadow, layered shadow, ATVP compatibility, dual
runtime, FongMi category calls, the public V70 lock, and untouched public output.
The first missing proof wins in that fixed order, and every path returns only
`admit` and `reason`. The module performs no I/O, report parsing, runtime state,
vendoring, overlay insertion, or output takeover. Its combined P2, Golden,
build, and stage-gate seal passes 639 tests with two existing Windows symlink
skips; the 84-file managed scan and P2 DAG pass, while every B6 build
fingerprint remains unchanged. The merged simplify/harden/spec audit reports
zero findings. C2 is recorded below and does not modify public V70 output.

Macro C-C2 connects that policy to the isolated stage-gate dry-run. The new
`output_admission_dry_run` step aggregates only in-memory step statuses for the
development build, Macro A/B shadows, ATVP, dual runtime, FongMi category,
public V70 lock, and untouched public output, then calls C1. Complete evidence is
reported as `passed` with `admit=true`; skipped evidence remains `skipped`, and
real failures or write/deployment flags become `failed`. Missing or duplicate
evidence and malformed policy decisions are rejected without reading external
reports or touching vendor, overlay, frozen parts, or public output. The C2
seal passes 653 tests with two existing Windows symlink skips; the 84-file
managed scan, P2 DAG, and B6 build fingerprints remain unchanged. The merged
simplify/harden/spec audit reports zero findings. C3 is recorded below.

Macro C-C3 completes V70 source-lock verification and the P2 phase seal. The new
`v70_source_lock` step verifies the frozen tag and manifest, public V70 bytes and
root-index record, isolated `build/v80-dev` output, C2 public-output isolation
evidence, and literal zero production writes or deployment attempts. Complete
mode now requires the upstream AList-TVBox source contract. A content-addressed
implementation manifest covers all managed inputs and the full `tests` tree,
then recomputes its file count, SHA-256, and per-file manifest after every
command to reject mid-gate drift. Pytest uses a gate-private `--basetemp` with the cache plugin disabled, so global temp-directory permissions cannot affect the result. The final complete gate passes all 17 steps;
pytest reports 953 passed and seven Windows symlink skips, both 50,000-case
differentials report 50,000 equal with zero differences or errors, and ATVP,
dual-runtime, FongMi category, and AList-TVBox 1.42.0 upstream contracts pass.
The 86-file implementation tree SHA-256 is
`1A53C72BEBCEA2F76C5A223E76F72D2C6517EEE0E24BCC5D43D17C92A620009F`.
The final report is `work/v80-stage-gate.json`, SHA-256
`20D2E011EF76191FEB6D650643A511CC2D7CFCEA8766DF894497B48B0AAD5403`.
It records `admit=true`, `source_lock_verified=true`, `restore_action_planned=false`,
`production_writes=false`, and `deployment_attempted=false`. Final simplify,
harden, and spec review has no blocking findings. P2 is complete; P3 reliability
and synchronization is next, without deploying or switching the public V70 path.

The first P3 History synchronization work package is sealed against
AList-TVBox 1.45.1. AList-TVBox 1.45.x removes the legacy
`/history/{token}` server implementation, so the isolated V80 path uses
`/api/playback/*` while retaining a bounded 404/405 fallback for older servers.
The module covers `site`/`spider_plugin` identity, incremental cursors, full
snapshots, tombstones, post-import commit, restart UID rediscovery, decreasing
cursor rebuilds, token isolation, and serialized History access. Its focused
tests report 46 passed; the isolated candidate is 714878 bytes with SHA-256
`4F293BF5D62A1AC10A287B0608556C6C449FB46B98CE0F9826DF4EDBA9AC5B26`.
This does not complete P3 or change the public V70 source, index, or frozen
parts. Public V70 History deployment evidence remains tied to AList-TVBox
1.44.0; the History seal result is recorded in `work/v80-stage-gate-1451.json`.

The second P3 Reliability work package is implemented and entering its seal
gate. It adds structured failure classification, HTTP/payload error mapping at
Provider `_resource_api_get()`, and absolute-deadline phase allocation through
the existing `_atvp_deadline_timeout()` helper. Structured errors take
precedence while legacy English and Chinese diagnostics remain compatible. It
does not take over History, TMDB, or the general network layer and does not yet
implement retry/backoff, circuit breakers, bulkheads, health state, chaos, or
an end-to-end timeout budget. Focused verification reports 259 passed and seven
skipped; the isolated candidate is 724277 bytes with SHA-256
`6D590868B80950923F44A793A515A351EC9CC8FABC631EF7DD6DE5ED860C4099`.
Its seal report is `work/v80-stage-gate-1451-reliability.json`; P3 remains open.

The third P3 Retry/Backoff work package is implemented and entering its seal
gate. It formalizes the existing urllib3 transport retry as the sole retry
owner: `total/connect/read=2`, `status/other=0`, `backoff_factor=0.4`, GET-only,
with `Retry-After` and status retries disabled. Provider deadline allocation
reserves the worst-case `0.8s` transport backoff and adds no application-level
retry loop. The legacy urllib3 construction path preserves the original
transport retry instead of silently disabling retries; no-deadline callers keep
V70 behavior. Focused verification reports 278 passed and seven skipped; both
50,000-case Macro A/B differentials are equal with zero differences and zero
errors. The isolated candidate is 727368 bytes with SHA-256
`3BF3D5C02A4ED67F48F852A78614528B123DE53D4C4B055D1FC588EF66C5A0AE`.
This package does not take over HTTP status retries, redirects, hard wall-clock
cancellation, circuit breakers, bulkheads, health, chaos, History/TMDB, or the
general network layer; P3 remains open and V70 is not deployed or replaced.

The fourth P3 Provider Reliability work package is sealed after focused tests
and simplify, harden, and spec review. Provider `_resource_api_get()` now uses
per-backend/per-mode circuit, bulkhead, and health state: three consecutive
transient failures open the circuit for 30 seconds, half-open permits one probe,
and each bulkhead key admits two concurrent requests. Transient failures are
limited to timeout, DNS, TLS, transport, server, and rate-limit categories;
rejections use structured `circuit_open` and `bulkhead_rejected` failures. Health
keeps bounded samples and an EWMA score. Backend switches, reinitialization, and
`destroy()` advance generation state so stale requests and leases cannot mutate
the active backend. urllib3 remains the sole retry owner and no application
retry loop was added. Focused verification reports 171 passed; the expanded
package suite reports 304 passed and seven skipped. The isolated candidate is
738611 bytes with SHA-256
`49106B27ED2F1824F9C9460464B200093BB243554EB4F023736FD28D7832AB76`;
the seal report is `work/v80-stage-gate-1451-provider-reliability.json`. The
package does not extend to TMDB, History, the general network layer, HTTP status
retry, redirects, or public V70 takeover. Later P3 packages still need the other
subsystem isolation work, chaos/recovery evidence, and final end-to-end timeout
closure.

The fifth P3 History client event-queue work package is sealed after a second
simplify, harden, and spec review. The active queue is capped at 256 events;
bulk overflow is persisted as `deferred` within `HISTORY_ROW_LIMIT`, and each
drain processes at most eight events. Deferred rows survive restart, rotate with
the account UID, remain isolated from stale `transition_pending` state, and use
monotonic upsert/delete merging. Repeated bulk pushes preserve equal-watermark
deferred rows, while a full queue can update an existing deferred identity but
still rejects a genuinely new identity. Focused History tests report 31 passed,
the P3 suite reports 249 passed, and build/stage tests report 86 passed with seven
skips. The complete 17-step gate passes with 1207 passed and seven skipped;
both 50,000-case Macro A/B differentials remain equal with zero differences or
errors. The isolated candidate is 776229 bytes with SHA-256
`9A3008A774FACE213EDC337E3B92CDBF088C4A79CB8961D04DD24F133A02C5C6`.
The report is `work/v80-p3-1451-stage-gate-sealed-r2-20260814.json`. At that
seal point, P3 remained open for stale-cache migration, independent bulkheads,
chaos/recovery evidence, and final timeout closure; public V70 was not deployed
or replaced.

The sixth P3 Cache Health work package was sealed on 2026-08-15 after focused
tests, real thread-interleaving regressions, and consolidated review. It applies
one stale/backoff contract to the TMDB JSON cache, Douban JSON/text caches,
non-blocking Spider History snapshot refresh, and the generic background cache
refresh lifecycle. Only `None` is a miss; inclusive TTL and `allow_stale=False`
semantics remain unchanged. Stale values return immediately while one background
owner refreshes them. Failure count is capped at six, with 1/2/4/8/16/32-second
delays bounded by `failure_ttl`; failure state remains memory-only. Generation
validation and payload/health commit are atomic, so stale tasks cannot mutate the
active cache or health state. History refresh failures now suppress repeated
non-blocking refreshes through the same backoff without affecting playback.
Provider circuit/bulkhead state, resource caches, Filter History cache, the
persistent History event queue, and P4 security scope remain outside this package.
Focused tests report 47 passed, build/stage tests report 91 passed with seven
skips, and the complete 17-step gate reports 1259 passed with seven skips. Both
50,000-case Macro A/B differentials remain equal with zero differences or errors;
ATVP, FongMi dual-runtime/category, and AList-TVBox 1.45.1 upstream contracts pass.
The isolated candidate is 781140 bytes with SHA-256
`50572D6304283CE39AA17AA2F25D1ED3EE9CEE88BB4DEB1C5B81D06EC6D79FBE`;
the report is `work/v80-p3-1451-cache-health-stage-gate-sealed-20260815.json`.
The seventh P3 Background Bulkhead work package was sealed on 2026-08-15. It
adds exactly three fixed, independent, non-blocking lanes:
`resource_completion=10`, `history=1`, and `route_probe=5`. Resource completion
covers bound-route replacement, entry resource preheat, and supplement search;
History covers background snapshot/sync plus manual probe/sync jobs; route probe
covers background route preheating only. Admission rejection returns immediately
without a queue, wait, or new retry layer. Executor/thread startup failures
release the lease and preserve the original startup-failure diagnostics.
Generation resets fence stale leases during reinitialization and `destroy()`.
Provider bulkheads, foreground searches, the persistent History event queue,
cache refresh, and public V70 remain unchanged. Focused coverage reports 44
passed; affected regression reports 81 passed and two skipped; the package gate
reports 163 passed and seven skipped. The final complete gate is fixed to 17/17
steps with 1308 passed and seven skipped, zero Macro A/B differences, and the
ATVP, FongMi dual-runtime/category, and AList-TVBox 1.45.1 contracts. The isolated
candidate is 786881 bytes with SHA-256
`694B39E802BBD3D18D7006B81E48C439449FD80032EACDEBC052DD488261ED3F`;
the report is
`work/v80-p3-1451-background-bulkhead-stage-gate-sealed-20260815.json`,
71535 bytes with SHA-256
`01E67933BC238319ECD064FC1527D6BAF36896A86E8A3729B48A759F43E639C9`.

The eighth P3 Chaos/Recovery work package was completed on 2026-08-15 with a
deterministic virtual clock and local fault fixtures. Twelve scenarios cover
TMDB 500/timeout stale recovery, PanSou timeout, History 401 reauthentication,
History 500 playback isolation, AList 502, DNS failure, IPv6 unreachable,
expired playback URL reissue, truncated JSON, the existing oversized streamed
JSON boundary, and stale lifecycle tasks. All 12 pass with fixed recovery
baselines of 0, 1000, or 30000 ms. The recorded 250 ms cold start and 0 ms hot
cache values are synthetic transport latency, not real-device performance.
Consolidated review moved History 401/500 onto the AList-TVBox 1.45.1
`/api/playback/changes` route, verifies the `GET -> POST login -> GET` reauth
sequence and a real `followplay` path after History faults, and prevents raw
unexpected exception text from entering the report. Focused regression reports
92 passed and five skipped; the P3 package regression reports 446 passed and
seven skipped; all 105 managed files pass the sensitive-data scan. The isolated
candidate remains 786881 bytes with SHA-256
`694B39E802BBD3D18D7006B81E48C439449FD80032EACDEBC052DD488261ED3F`.
Seal evidence is recorded in
`work/v80-p3-1451-chaos-recovery-stage-gate-sealed-20260815.json`. The fixtures
perform no real network requests, real sleeps, production writes, or deployment;
unified oversized-response security remains P4 scope.

The ninth P3 package subsequently sealed end-to-end TimeoutBudget and lifecycle
hard cancellation. P3 is complete as a local engineering stage; its final
candidate was 808647 bytes with SHA-256
`9DF8697F950068A56E42BFC4331A5E0ED1520FE91F7C156B30BEF8B2C58187B9`.

P4-1 is now sealed as a pure Security Policy decision contract. It defines the
`trusted_backend`, `configured_internal`, and `external_untrusted` zones, exact
internal-origin admission, all-global external resolution, per-hop redirect
validation, external-to-internal and HTTPS-downgrade rejection, and a fixed
cross-origin header allowlist. It performs no DNS, network, cache, logging,
retry, TimeoutBudget allocation, or runtime interception. The 13919-byte module
has SHA-256
`8BB1DF6C481E6EC6FDA2A0DEE2B2EE52D562C9430F2C6FD049E06758C14D26B8`;
the isolated candidate is 822566 bytes with SHA-256
`A1C922715DDA59168D9EB12D0D820A345341840BA9DCF0856F7238CF1C8B8F76`.
The complete gate passed 18/18 steps with 1412 pytest cases. P4 remains open for
one-network-seam-at-a-time runtime integration. Public V70, the root index, and
the frozen parts remain locked.

P4-2 now integrates that policy into the existing media-route probe family only.
The existing DNS resolution, pinned-IP connection, Host/SNI handling, redirect
loop, response probe, TimeoutBudget, and route executor remain the sole owners of
their responsibilities. Exact configured ATVP and History origins remain trusted;
external targets require all-global addresses, every redirect target is freshly
resolved, external redirects cannot enter trusted internal origins, external HTTPS
cannot downgrade to HTTP, and cross-origin headers use the fixed allowlist. No
Provider, History, TMDB, or general requests session is intercepted, and no retry,
transport, DNS cache, executor, or timeout owner is added. The P4-1 output remains
the fixed overlay input; the resulting candidate is 823561 bytes with SHA-256
`D8B2E08B80DCD24CF55205ABA8CE441136587FEBE2BCA216D90A29EEC9520D2F`.
Seal evidence is written to
`work/v80-p4-2-route-security-stage-gate-sealed-20260815.json`. P4 remains open
for the remaining network families and unified response, JSON, redaction, and
signed-URL-cache boundaries.

P4-3 freezes a pure post-parse JSON shape policy without taking over a metadata
runtime. Its iterative validator caps container depth at 64, total value
nodes at 131072, and one list or object at 8192 items. It rejects non-string object
keys, unsupported Python values, and non-finite floats; accepted values are returned
by identity, and stable errors never echo the rejected value. The module performs no
I/O, response read or parse, response close, network, cache, logging, retry,
TimeoutBudget, or runtime interception. Its 2383 bytes have SHA-256
`91AAD2A2417D226C87DD750D7C2C825E01D176A7BE699857B9239C5EBFCF3EAF` and are
appended byte-for-byte after the P4-2 route output. The resulting candidate is
825944 bytes with SHA-256
`8FB4EEDAB97057412D622881A074BDA6D04F76617B81CA6802B6D34525FB70F0`.
The policy suite passed 12 cases and the combined P4 suite at that point passed 64.
Its standalone complete-gate attempt correctly rejected a concurrently changing
implementation tree, so P4-3 uses the inclusive P4-4 seal evidence rather than a
mislabelled standalone success report.

P4-4 integrates the policy only at the successful `200` return of
`Spider._request_tmdb()`. The existing `_json_response`, status decisions, cache,
requests session, TimeoutBudget, stream mode, and `close_tracked()` finally block
remain the sole owners of their current behavior. Non-200 payloads are not
shape-validated, and this package still does not cap bytes before parsing or impose
string and field-specific limits. The P4-3 candidate input is 825944 bytes with
SHA-256 `8FB4EEDAB97057412D622881A074BDA6D04F76617B81CA6802B6D34525FB70F0`;
the final candidate is 825969 bytes with SHA-256
`4746D9EB74B6351EFBF8764985BA295F6936914A7F0A47CFACD6AC52257E86C7`.
The combined P4 suite passed 74 cases, the complete repository suite passed 1456,
and the 118-file managed sensitive scan found nothing. Seal evidence is written to
`work/v80-p4-4-tmdb-json-shape-stage-gate-sealed-20260815.json`.

P4-5 keeps that scope. The immutable TMDB response policy caps the streamed body at
2 MiB before parsing, object keys at 1024 UTF-8 bytes, and string values at 128 KiB.
`_json_response()` gains an optional bounded mode, while its other two one-argument
callers still use `response.json()`. The TMDB call forwards the current operation
deadline and `close_response=False` into the existing shared reader, leaving the
outer `close_tracked()` finally block as the only close owner. Fixed 401/403/429
errors win before body iteration; other non-200 invalid or oversized bodies retain
the generic `TMDB HTTP <status>` result; successful JSON is shape-validated before
field validation. No Douban, Provider, History, playback, general-session, retry,
cache, transport, timeout, parser, or close owner is added. The candidate is 829040
bytes with SHA-256
`60B083C7F3DF4DCD368CA92F39296C8F3885A36B1491A8D5507169A474DBFEE4`.
The combined P4 suite passed 103 cases, the complete repository suite passed 1493,
Macro A/B each completed 50000 equal cases with zero differences or errors, and
Chaos passed 12/12. Seal evidence is written to
`work/v80-p4-5-tmdb-response-boundary-stage-gate-sealed-20260815.json`.

P4-6 adds one bounded Diagnostic Redaction Policy after the sealed P4-5 output. The
runtime path keeps a 4096-character output bound, accepts at most 32 explicit secrets
of at most 4096 characters each, and redacts before truncation within a fixed scan
window. It covers credential headers, assignments, Bearer/Basic values, URL userinfo,
signed queries, encoded and double-encoded query/path structure, playback route tokens,
structured containers, and configured secret encodings. A two-anchor overlay routes
`_short_error()` plus `_diagnostic_event()` names, level, error, trace, field keys, and
field values through that sole policy. The stage-gate report uses the same managed core
with its fixed 12000-character report bound; it does not keep a second URL/query/path
redactor. No network, I/O, retry, cache, transport, TimeoutBudget, session, response-close,
or lifecycle owner is added. The policy module is 9503 bytes with SHA-256
`4A05F0910BEF7FCFA70CFEAA4D25B5B9B05482150A004CB3AFF9D5C1CD17A831`;
the final candidate is 837931 bytes with SHA-256
`AF00837D15B2168BE9B211D64594A70A889DE87EEEE7BAC21607F430BB7756E3`.
The focused build/gate set passed 252 cases, the combined P4 suite passed 172, and the
complete repository suite passed 1602. The seal report path is
`work/v80-p4-6-diagnostic-redaction-stage-gate-sealed-20260815.json`.

P4-7 adds one immutable Douban response byte policy after the sealed P4-6 output.
Eight credential-free fixtures freeze collection, recommendation/filter, two search,
detail, and action payload shapes. The largest canonical fixture is 561 bytes; a
conservative 50-item projection is 28050 bytes, so the fixed 512 KiB ceiling keeps
about 18.69 times headroom without copying the independent 2 MiB TMDB limit. A
two-anchor overlay applies the existing bounded `_json_response()` mode and JSON shape
policy only to `_DoubanClient.request_json` and the Douban wish POST inside
`_v80_action_unbounded`. It reuses `_read_bounded_json_shared()`, `operation.deadline`,
the current session/retry/cache/TimeoutBudget graph, and the outer `close_tracked()`
owner. Non-200 HTTP order, authentication/action messages, and Douban stale/backoff
behavior remain unchanged. Douban HTML, redirects, signed-URL cache, Provider, History,
playback, P5, and new parser/reader/close owners remain excluded. The policy module is
251 bytes with SHA-256
`69C7AEF61E8724616A6621CF74C7686D702D34A8A6E3C207DB430D50301A4170`; the sealed
candidate is 839093 bytes with SHA-256
`B1F980E71AC95CF9C6F143C568CA0B724917E0D8F98B43F09FDBD1B1A6284145`. The final
AList-TVBox 1.46.1 gate passed all 18 steps, the complete repository suite passed
1667 cases, Macro A/B each returned 50000 equal with zero differences and errors,
and Chaos passed 12/12. The seal report is
`work/v80-p4-7-alist-tvbox-1461-stage-gate-sealed-r2-20260816.json`; no public V70,
root index, production write, or deployment was changed.

P4-8 adds one immutable Douban HTML response byte policy after the sealed P4-7 output.
A single authorized, low-frequency, no-redirect wishlist observation retained no body,
URL, account identifier, title, or card data; its safe evidence is HTTP 200,
`text/html; charset=utf-8`, 57197 decompressed bytes, SHA-256
`AA28F4570F11493F8B9EBB19E6176E2A12368817F0371804CC6E2C442EADB0C9`, 15 grid
items, and 15 valid movie subject links. Together with the 64547-byte Top250 body and
the 12258-byte maximum parser projection, the frozen formula
`round_up_64KiB(max(16*P,4*O))` selects 256 KiB. The one-anchor overlay changes only
`_DoubanClient.request_text`: non-200 status still wins first, declared and streamed
decompressed bytes are bounded before the unchanged Requests text decode, the existing
operation deadline remains authoritative during iteration, and `close_tracked()` remains
the sole response-close owner. The policy module is 271 bytes with SHA-256
`DBBA0B73239F25884A4FECD9CCB3014D0AC2772D5B3334C76EBCCE98D018EDB8`; the final
candidate is 840543 bytes with SHA-256
`749F16F38DE178756C48AE4A857F30B509F16ACFFAF5E28FF421474852E4892A`. Redirects,
signed-URL cache, Provider, History, playback, general sessions, public V70, the root
index, and deployment remain excluded. The final gate passed all 18 steps with 1680
pytest cases, two 50000-case zero-difference macro runs, 12/12 Chaos cases, and a stable
145-file implementation tree. The seal report is
`work/v80-p4-8-douban-html-response-boundary-stage-gate-final-r2-20260816.json`.

P5-1 appends a pure observability policy after the exact P4-8 output. It freezes event
and snapshot schemas, a 256-event snapshot limit, a 512-character text limit, ordered
core/context/measurement fields, closed level and stage sets, and one unique stable
error code for each of the 16 P3 reliability failure kinds. It does not emit runtime
events, read a clock, perform I/O, change public responses, or change play IDs. The
policy module is 2138 bytes with SHA-256
`FDFA66B624DD9C5405A77B8FAAC1D2A3973B83AB7EBFB241AFBC99319AAE4C59`; the current
development candidate is 842681 bytes with SHA-256
`19A5FFA67ADA386585DA663AD1C7FD91FEC04322903EE207602FE2A4CC082A73`. Focused policy
and build tests pass 42 cases, and focused stage-gate chain tests pass 7 cases. The final
P5-1 gate passes all 18 steps with 1711 pytest cases, two 50000-case zero-difference
runtime differentials, 12/12 Chaos cases, and 146 managed files with zero sensitive-data
findings; the report is
`work/v80-p5-1-observability-policy-stage-gate-final-r2-20260816.json`. Runtime correlation
wiring, Diagnostics Snapshot generation, private canary, and public promotion remain open.

P5-2 adds only the runtime correlation overlay after the exact P5-1 output. Six fixed
insertions keep `_diagnostic_event()`, P4 `_short_error()`, and P3 TimeoutBudget/lifecycle
as the event, redaction, and operation owners. A monotonic scope sequence supplies unique
top-level request/trace handles, nested scopes inherit the root trace, and reset, cancel,
generation mismatch, or finished scopes omit stale correlation context. Managed schema,
stage, request/trace, and error-code fields cannot be overwritten by call-site fields;
elapsed time is emitted only as a finite non-negative integer. The candidate is 848247
bytes with SHA-256
`510D4CFEC01457AB6A264A7AF35204E87F6A2814F0A8028A9C2B9437317AB873`.
Focused overlay tests pass 29 cases, and the current build plus stage-gate chain selection
passes 26 cases. The complete gate passes all 18 steps with 1764 pytest cases, two
50000-case zero-difference runtime differentials, 12/12 Chaos cases, 149 managed files
with zero sensitive-data findings, and `admit=true`. The final managed-document closure
report is `work/v80-p5-2-runtime-correlation-closure-final-20260816.json`. P5-2 does not
enable Diagnostics Snapshot generation, deployment, or public promotion.

P5-3 wraps the existing private `_diagnostic_snapshot()` owner in the sealed
`v80-diagnostics-snapshot/1` envelope with exactly `schema`, `count`, and `events`.
Limits are clamped to `1..256`, event order remains oldest to newest, and the returned
list and event dictionaries are detached from the internal buffer. It adds no endpoint,
persistence, clock read, second buffer, dropped counter, redaction pass, cache, thread,
or logger. A hardening audit found that the P5-2 event owner returned the same dictionary
stored in the diagnostic buffer; the owner now returns `dict(payload)` so post-ingress
caller mutation cannot inject unredacted state. The historical P5-2 sealed output remains
848247 bytes / `510D4CFE...AB873`; the P5-3 chain uses a hardened 848253-byte intermediate
with SHA-256 `5B9C10F2EC877DEEF1302DCA35ABADC8BB65063EF33F0EA9698120DD96AD964C`
and produces an 848431-byte candidate with SHA-256
`30EBACE80D845AA5E743EDC5AACB7DDD11A7D314A006A32F5A8B45CD8B87A409`.
Focused P5-2, P5-3, build/tamper, fingerprint, and trusted-resume tests pass. The complete
P5-3 gate passes all 18 steps with 1784 pytest cases, two 50000-case zero-difference
runtime differentials, 12/12 Chaos cases, 152 managed files with zero sensitive-data
findings, and a stable 154-file implementation tree at
`221363D790E1CCA2E3A95470D749248883213DF282061CDD9204AC53EC86CC25`.
Output admission is true; no production write or deployment occurred. The full report is
`work/v80-p5-3-diagnostics-snapshot-closure-20260816.json`, and the final managed-document
closure path is `work/v80-p5-3-diagnostics-snapshot-closure-final-20260816.json`. Resume
reuse requires an independently trusted `--resume-source-sha256`; unverified reports
cannot supply passed evidence.

P5-5 keeps the resume mechanism content-addressed and fail-closed while advancing the
source contract to AList-TVBox 1.48.0. Both FongMi requirements candidates now follow
the same `exists()` semantics as `verify_dual_runtime.installed_requirements()`: every
existing candidate is fingerprinted, directories and read errors invalidate the scope,
and an empty candidate set is invalid. A dual-runtime failure propagates through output
admission and the V70 source lock. The pre-fix 15/18 closure remains diagnostic evidence,
not a passing baseline. The pinned 1.48.0 verifier passes 24/24 checks over the exact
7-commit, 34-file delta and confirms unchanged Atvp/History/playback Git blobs. Its report
is `work/v80-upstream-1480-source-contract-20260816.json` with SHA-256
`BA37264DE2FDEFD13A1F13E2B221EC69982561151F10DBE1B149CF04F10D4E83`.

After a 45-second quiet-period double fingerprint, the single complete P5-5 baseline
passed all 18 required steps with 18 executed and zero reused. Pytest reported 1811
passed cases, Macro A and B each reported 50,000 equal / 0 different / 0 errors,
Chaos reported 12/12, and the managed sensitive scan reported 158 files / 0 findings.
The stable implementation tree contains 160 files with SHA-256
`FE835719DD2CF3FF6B259A75D23F2F63EFE47BECDF2B96F2E9310B681301149C`.
The report is `work/v80-p5-5-upstream-1480-fingerprinted-baseline-20260816.json`;
its trusted resume pin is
`14AA4142678A71B0B64B1B9F86EE2BA6A6C9666AC1942997172B8A762476FFFD`.
Output admission passed, the public V70 source lock remained verified, and no
production write or deployment was attempted. Later documentation-only changes must
resume from this pinned report and execute only the invalidated DAG closure.
No server, emulator, FongMi, or real-device danmaku/Kuaishou claim is made from source
evidence alone.

P5-5A adds the **repeated lifecycle quiescence overlay** only after the exact P5-3
diagnostics-snapshot output. It fixes retained references after the three managed sessions
are closed by `destroy()` and does not change the frozen V70 source, the ten source parts,
network behavior, retries, caches, TimeoutBudget ownership, or public return contracts.
The candidate is 848540 bytes with SHA-256
`A14571DF5C8EECBC5C7B8A09C4385978F5C244D806F9FA8228C2CEEDE5D15280`.
The candidate-bound runner completes 32 `init({}) -> destroy()` cycles, proves managed
Thread/Future/Timer work is active at the destroy boundary, then releases it under test
control and requires final quiescence within one second. It also checks consecutive
generations, exact session closure, stale-callback isolation, and zero observed network,
persistence, or deployment activity. The lifecycle report is
`work/v80-p5-lifecycle-stability-r7-20260817.json`, with 32/32 passed and SHA-256
`E55CFC0FE64CB9597944447CFBDB51F705A62A6A00BB0160AABFEC4C1A2E2FF6`.

The first complete gate correctly rejected a stale Macro A final-candidate fingerprint;
that failed report remains read-only evidence. After updating only that consumer, the
trusted DAG resume closure passed all 18 steps with 8 executed and 10 reused. Pytest
reported 1873 passed, and the stable 163-file implementation tree is
`9CFDD9B20BD92D8BEC485C29516C5B651D9FD0DB57DE409E67779F273E5B849B`.
The closure is `work/v80-p5-5a-lifecycle-stability-resume-closure-r2-20260817.json`
with SHA-256
`62A3F2F1755214E4EFC1895056BA46B3E6A96F1FEB044ECBF292B8372E70B117`.
No production write or deployment occurred. The runner is not a general Python sandbox;
its zero-network claim is limited to this provenance-bound candidate. Performance,
concurrent search/playback/History, long-run behavior, real networking, and device testing
remain separate packages.

P5-5D adds the **search call-family concurrency and isolation baseline**. Its single
post-lifecycle overlay has the Chinese maintenance alias `搜索并发所有权覆盖层` and is
anchored to the exact P5-5A 848540-byte / `A14571DF...5280` output. It keeps one search
job identity and one same-generation admission owner, blocks partial and final writes
from stale generations, transfers `_resource_api_get()` response ownership exactly once,
and clears search job state while retiring runtime owners during `init()` and `destroy()`.
It does not add a
generic token, cache, dependency inference, or stress-test framework, and it does not own
playback or History concurrency.

The candidate is 854833 bytes with SHA-256
`3C734E2840ABB50A31CC9A15F241DAC1A0B0E77EC638A882D85CB911DE619766`.
The formal `v80-p5-search-concurrency/3` runner passes all seven scenarios: foreground
capacity, queued cancellation, job ownership, generation writeback, exactly-once response
close, resource-completion bulkhead isolation, and live init/destroy races. Cleanup closes
all 18 sessions once and all six executors, rotates six executors and four slots on live
init, and leaves job, refresh, reference, bulkhead, and timeout state at zero. The report is
`work/v80-p5-search-concurrency-runtime-owner-final-r3-20260817.json` with SHA-256
`A26D93477EF9E7798EBE023F2ECE110E10C32D6E862640F609FC21C9999CA0EE`.
The fixed overlay uses 24 explicit unique insertions. DNS/media pools are a shared
dependency of search playability validation and playback probing; this package changes
only their owner/slot lifecycle. Four shared playback-probe algorithms are AST-identical,
and the two pool-owner methods are AST-equivalent after owner normalization, so P5-5E
playback concurrency remains separate. Runtime ownership tests pass 43 cases, the shared
playback boundary passes 6, runner tests pass 15, and stage-gate tests pass 242; the second
simplify/spec/security review has zero findings. The first complete closure exposed nine
stale test/runner assumptions plus an obsolete 1.46.1 upstream root, not a production
concurrency defect. After those fixed consumers were updated and the clean 1.48.0 root was
selected, `work/v80-p5-5d-search-concurrency-runtime-owner-resume-closure-r2-20260817.json`
passed all 18 steps with 8 executed and 10 reused, 2044 passing pytest cases, a stable
171-file implementation tree, 165 managed files with zero sensitive findings, and admitted
output. These are candidate-bound, forbidden-network tests; they do not prove real
network/device performance. Playback and History concurrency remain separate follow-up
packages, and public V70 remains unchanged.

P5-5E adds the **playback call-family concurrency and isolation baseline**. The fixed
overlay has the Chinese maintenance alias `播放并发所有权覆盖层`, applies exactly seven
unique replacements to the pinned P5-5D `854833 / 3C734E...9766` input, and does not add a
generic executor, cache, retry, sandbox, token, or concurrency framework. It binds each
player call to its generation, backend, session, response/connection owner, and media slot;
it also rejects stale route-quality, probe, and History side effects across live init and
destroy boundaries.

The candidate is 857088 bytes with SHA-256
`3DAB5769B4D2A413BC876A478EC690E2E2B4808916773B9D570CA4A244E3299F`.
The formal `v80-p5-playback-concurrency/1` report covers eight scenarios and passes `8/8`:
concurrent player isolation, old ATVP session isolation, exactly-once response/connection
close, slot recovery after cancellation, foreground/background isolation, live-init
generation fencing, stale side-effect rejection, and destroy cleanup. The report is
`work/v80-p5-playback-concurrency-r2-20260817.json` with SHA-256
`ABFB274DD4C98C282FDBB13F8329DF32BC1AA58DE77AA3C5CB302904EADC36E0`.
The evidence runner compiles all scenarios from the candidate bytes read and hashed at
startup, then restores any existing `base` and `base.spider` modules after loading.

Focused P5-5E verification passes 31 tests, and the final simplify, spec, and security
reviews report zero findings. The technical closure
`work/v80-p5-5e-playback-concurrency-closure-r1-20260817.json` passes all 18 steps with
2079 executed pytest cases, a stable 176-file implementation tree, 170 managed files with
zero sensitive findings, and admitted output; its SHA-256 is
`1E0D3ACB2B7C3041917E75E386C935BEE895AA47C10BDA09A5E06775AD5246AA`.
This remains controlled local evidence, not real server, MuMu, FongMi, or device proof.
History concurrency is the next independent package, and public V70 remains unchanged.

P5-5F adds the **History call-family concurrency and isolation baseline**. The fixed
overlay has the Chinese maintenance alias `History 并发所有权覆盖层`, applies exactly 13
unique replacements to the pinned P5-5E `857088 / 3DAB5769...299F` input, and limits its
scope to History job, background/manual, replacement-owner, generation/category-refresh,
and persistence critical-section ownership. It leaves `_history_sync_lock` and the History
event queue unchanged and does not introduce a generic executor, cache, retry, or
concurrency framework.

The candidate is 859732 bytes with SHA-256
`B42B37C097AA989F0FE82EF380A71865A4FDA02F6606A295E120FD79DA610700`.
The formal `v80-p5-history-concurrency/1` report passes `8/8` and is stored at
`work/v80-p5-history-concurrency-r3-20260817.json` with SHA-256
`9B00F4A4FCDBF4556CC764D706E67BC73EA0E4A5A6660D595BBB043050BC5E9C`.
Focused overlay/runner, build-consumer, stage-selector, Chaos, and repaired historical-
consumer verification pass 34, 4, 12, 7, and 53 tests respectively; final simplify,
spec, and security reviews report zero findings.

The first closure failed only when pytest exceeded 2400 seconds at about 75 percent. The
second exposed 53 historical consumers that did not disable later History overlays. Both
reports remain read-only recovery evidence. The final technical closure
`work/v80-p5-5f-history-concurrency-closure-r3-20260817.json` passes all 18 steps with
`7 executed / 11 reused`, 2117 pytest cases, and a stable 180-file implementation tree
`FE0ADBCF7628CFCE1E10D55FAF3B0780394CEFE1518755BBD388BDCDC5F87609`; its SHA-256 is
`77E0FF352DA25FAE2D76311584F70D1585CBB4E68274BD2CFCD505023F8D8648`.
There were no production writes or deployment attempts. Private canary validation, real
server/MuMu/FongMi evidence, rollback rehearsal, human approval, and production promotion
remain outstanding; public V70 stays frozen.

The 2026-08-18 project security review closed the remaining P4 redirect/body-boundary
blockers without adding a generic redirect or session layer. The fixed Douban JSON/HTML,
TMDB, wishlist, and user-id owners disable Requests automatic redirects; user-id 3xx
responses are not followed or read, while 200 responses use the existing 256 KiB limit,
absolute deadline, and single close owner. The three focused P4 overlay files pass 66 tests.
That review's candidate is 862377 bytes with SHA-256
`C1ACAB802121E3F69ADEA0EBF1AB271C14015124AA28D2D1F8F58F97C8481B7D`.
The maintenance alias table above covers the exact 46-unit set: 10 ordered chunks and all
36 root Python modules. The final content-addressed report for this batch is fixed at
`work/v80-p5-5f-redirect-boundary-alias-closure-r6-20260818.json`; private canary work is
not authorized unless that report passes all required steps.

A later atomic owner audit found one remaining V80-only gap: an unprobed ATVP output
could still use the weak URL-shape check after DNS/media probing returned no result. The
minimal fix keeps all ten shared V70 chunks byte-identical and expands only the V80 route
overlay from four to nine explicit seams. `_safe_atvp_play_output`, both foreground player
fallbacks, and the resource-detail probe/fallback paths now reuse the strict resolved-target
policy with the existing absolute deadline. The current candidate is 862581 bytes with
SHA-256 `87DCAC75E7F60CA70219EA99C238940E756D53D17A82D2FE684622A38CD5BADC`;
write/check passed and the focused composite closure is 318 passed. Atomic source evidence
is recorded in `work/v80-source-owner-audit-20260818.json`.

The raw-row-preserving combiner and private-V80-only controlled switch now share one
`_resource_output_candidate_order` owner across foreground and background output. The switch
is disabled by default and is accepted only for the raw-plugin private configuration. A
combiner exception performs one legacy fallback without retry. The development candidate is
870797 bytes with SHA-256
`0CEBC73A78BCC8C7853A6BD0F0C78F4D95DD786C861425F9E0A4EC40FA0583F9`; Macro A has
50,000 cases, 14,736 controlled differences, and zero errors, while Macro B is 50,000 equal
with zero errors and Chaos is 13/13. The independent `private/v80/` package is also staged as
`douban_tmdb_follow_single_v80_private` version 80. Its source is 870801 bytes with SHA-256
`049C722515F6851C379969C2886FA466EDD9FC9478B6B6F591E757DEEEDDCB97`; ATVP direct-play
and dual-runtime checks pass. Server and MuMu deployment must wait for the new changed-node
dependency-graph closure.

Write and then check the independent V80 development output:

```powershell
python tools/build_follow_plugin.py --write
python tools/build_follow_plugin.py --check
```

Explicitly verify the frozen public V70 source and root index:

```powershell
python tools/build_follow_plugin.py --baseline-check
```

Run the complete local phase gate with explicit checked-out source contracts:

```powershell
python tools/run_v80_stage_gate.py --report work/v80-stage-gate.json `
  --fongmi-root <fongmi-source-root> --atvp <Atvp.py> `
  --upstream-root <alist-tvbox-source-root>
```

The build gate validates strict UTF-8 decoding, manifest size and SHA-256,
Python AST parsing, duplicate methods in `Spider` and `Filter`, and source
metadata. Only the baseline contract validates the root `spiders_v2.json`.
`--write` uses an atomic replace and rejects the public V70 path, aliases that
resolve to it, and every read-only manifest.

When V80 development intentionally changes assembled bytes, update the version
and expected size/SHA-256 in `release.json` in the same reviewed change. Do not
change `baseline_v70.json`, the public V70 source, or the root index.

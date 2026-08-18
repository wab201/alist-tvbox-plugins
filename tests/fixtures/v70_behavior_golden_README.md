# V70 Behavior Golden Fixture

This fixture is a frozen, offline P1 equivalence sample. It does not approve any
V80 behavior change. A difference requires explicit review and approval before
the fixture can be updated.

## Provenance and Redaction

- Expected values come from the frozen public V70 source and existing regression
  tests in `tests/test_follow_operation_v51.py`.
- Inputs are synthetic and deterministic. Identifiers, titles, resource IDs, and
  play IDs are examples rather than deployment data.
- The fixture contains no network locations, credentials, session material, or
  signed media values.
- Time-sensitive cache cases patch the module clock to a fixed value.
- Both V70 and the current in-memory V80 build receive exactly the same input.

## Domain Mapping

| Roadmap domain | Golden cases | Stable boundary represented |
| --- | --- | --- |
| Metadata | `plugin_metadata_contract`, `metadata_subject_id` | Release annotations and source identity parsing |
| Resource search and selection | `resource_title_score_selects_matching_season`, `resource_provider_label` | Candidate title/season scoring and provider classification after search |
| Detail | `detail_splits_resource_groups` | Detail playlist grouping and per-group metadata alignment |
| Playback return | `player_returns_direct_opaque_id`, `player_select_prompt_is_non_playable` | Stable `playerContent` response shapes without transport calls |
| History merge and normalization | `history_normalizes_numeric_fields_and_drops_empty_key`, `history_merge_uses_cloud_rank_without_followplay_reference` | Bounded row normalization and the legacy timestamp rank used when no packed follow-play reference exists |
| Cache hit and expiry | `cache_returns_fresh_memory_entry`, `cache_removes_entry_beyond_stale_ttl` | In-memory hit and stale eviction with a fixed clock |
| Failure fallback | `detail_failure_clears_playable_routes` | Detail degradation that removes invalid playable routes and exposes status |
| Compatibility parsing | Episode and magnet cases | Existing provider episode parsing and resource-ID classification contracts |

High-level detail, search, and playback workflows depend on remote services,
runtime bridges, or background coordination. P1 therefore uses their stable
boundary functions and return contracts. The broader existing regression suite
continues to cover orchestrated flows with mocks. Later V80 phases must add
module-level tests as real components replace the byte-preserving source parts.

## Running

The pytest test always assembles the current V80 bytes with
`build_follow_plugin.build_release()` and writes them only to pytest's temporary
directory. The comparison module also provides a standalone CLI used by the V80
stage gate. Its JSON report includes source and fixture hashes, per-case results,
normalized result maps, differences, and the explicit approval state.

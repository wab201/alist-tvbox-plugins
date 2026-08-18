from typing import Any, Iterable

from .resource_candidate_shadow_background import (
    build_background_resource_candidate_shadow_inputs,
)
from .resource_candidate_shadow_composition import (
    compose_resource_candidate_shadow,
)


def _shadow_runtime_provider(owner: Any, row: dict):
    return owner._resource_provider_key(
        row.get("provider"),
        row.get("type"),
        row.get("type_name"),
        row.get("vod_remarks"),
        row.get("source"),
        row.get("vod_id") or row.get("id") or row.get("url"),
    ) or "unknown"


def run_background_resource_candidate_shadow(
    owner: Any,
    legacy_rows: Any,
    rows: Any,
    *,
    item: dict,
    cache_key: str,
    generation: int,
    modes: Iterable[str],
):
    """Run one caller-owned background shadow comparison outside the cache lock."""
    with owner._resource_candidate_shadow_lock:
        with owner._cache_lock:
            if generation != owner._cache_generation:
                return None
            enabled = owner._resource_candidate_shadow_enabled
            sample_every = owner._resource_candidate_shadow_sample_every
            shadow_budget_us = owner._resource_candidate_shadow_budget_us
            sampled_generation = owner._resource_candidate_shadow_sampled_generation

        inputs = build_background_resource_candidate_shadow_inputs(
            enabled=enabled,
            cache_key=cache_key,
            generation=generation,
            sampled_generation=sampled_generation,
            sample_every=sample_every,
            shadow_budget_us=shadow_budget_us,
        )
        result = compose_resource_candidate_shadow(
            legacy_rows,
            rows,
            merge_rows=lambda left, right: owner._merge_resource_rows(
                left, right, item, "",
            ),
            score_row=lambda row: owner._resource_score(row, item, ""),
            preference_row=lambda row: owner._resource_row_preference(
                row, item, "",
            ),
            provider_row=lambda row: _shadow_runtime_provider(owner, row),
            modes=modes,
            **inputs,
        )
        if result["decision"]["run"]:
            with owner._cache_lock:
                if generation == owner._cache_generation:
                    owner._resource_candidate_shadow_sampled_generation = generation
                    owner._resource_candidate_shadow_last_report = result["report"]
        return result

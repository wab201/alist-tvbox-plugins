from typing import Any, Iterable, Mapping, Sequence

from .resource_candidate_shadow_background import (
    build_background_resource_candidate_shadow_inputs,
)
from .resource_candidate_shadow_policy import decide_resource_candidate_shadow
from .resource_search_v70_adapter import build_v70_layered_resource_shadow


RESOURCE_SEARCH_LAYERED_SHADOW_ESTIMATED_COST_US = 1000


def build_resource_search_layered_shadow_report(
        rows: Sequence[Mapping[str, Any]], *,
        cached_rows: Sequence[Mapping[str, Any]] = (),
        recent_resource_id: Any = "", binding_resource_id: Any = "",
        available_modes: Iterable[Any] = ()) -> dict:
    batches = build_v70_layered_resource_shadow(
        rows,
        cached_rows=cached_rows,
        recent_resource_id=recent_resource_id,
        binding_resource_id=binding_resource_id,
        available_modes=available_modes,
    )
    layers = tuple({
        "layer": batch.step.layer,
        "mode": batch.step.mode,
        "candidate_count": len(batch.candidates),
    } for batch in batches)
    return {
        "status": "observed",
        "input_count": sum(1 for row in rows or () if isinstance(row, Mapping)),
        "candidate_count": sum(layer["candidate_count"] for layer in layers),
        "batch_count": len(layers),
        "layers": layers,
        "error_type": "",
    }


def run_resource_search_layered_shadow(
        owner: Any, rows: Sequence[Mapping[str, Any]], *, cache_key: str,
        cached_rows: Sequence[Mapping[str, Any]] = (),
        recent_resource_id: Any = "", binding_resource_id: Any = "",
        available_modes: Iterable[Any] = ()) -> dict:
    """Record one bounded, redacted layered-search observation."""
    with owner._resource_search_layered_shadow_lock:
        with owner._cache_lock:
            generation = owner._cache_generation
            inputs = build_background_resource_candidate_shadow_inputs(
                enabled=owner._resource_search_layered_shadow_enabled,
                cache_key=cache_key,
                generation=generation,
                sampled_generation=owner._resource_search_layered_shadow_sampled_generation,
                sample_every=owner._resource_search_layered_shadow_sample_every,
                shadow_budget_us=owner._resource_search_layered_shadow_budget_us,
                estimated_cost_us=RESOURCE_SEARCH_LAYERED_SHADOW_ESTIMATED_COST_US,
            )
        decision = decide_resource_candidate_shadow(**inputs)
        result = {"decision": decision, "report": None}
        if not decision["run"]:
            return result
        try:
            report = build_resource_search_layered_shadow_report(
                rows,
                cached_rows=cached_rows,
                recent_resource_id=recent_resource_id,
                binding_resource_id=binding_resource_id,
                available_modes=available_modes,
            )
        except Exception as exc:
            report = {
                "status": "error",
                "input_count": 0,
                "candidate_count": 0,
                "batch_count": 0,
                "layers": (),
                "error_type": type(exc).__name__,
            }
        result["report"] = report
        with owner._cache_lock:
            if generation == owner._cache_generation:
                owner._resource_search_layered_shadow_sampled_generation = generation
                owner._resource_search_layered_shadow_last_report = report
        return result

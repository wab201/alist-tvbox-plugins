import hashlib
from typing import Any


RESOURCE_CANDIDATE_SHADOW_ESTIMATED_COST_US = 5328


def _valid_generation(value: Any):
    return value if type(value) is int and value >= 0 else None


def build_background_resource_candidate_shadow_inputs(
    *,
    enabled: bool = False,
    cache_key: Any = "",
    generation: Any = None,
    sampled_generation: Any = None,
    sample_every: int = 1,
    shadow_budget_us: int = 0,
    estimated_cost_us: int = RESOURCE_CANDIDATE_SHADOW_ESTIMATED_COST_US,
) -> dict:
    """Build policy inputs from caller-owned background job state."""
    current_generation = _valid_generation(generation)
    sampled = _valid_generation(sampled_generation)
    already_sampled = current_generation is not None and sampled == current_generation
    if (
        enabled is True
        and not already_sampled
        and isinstance(cache_key, str)
        and cache_key
        and current_generation is not None
    ):
        material = "resource-candidate-shadow|%d|%s" % (current_generation, cache_key)
        sample_key = hashlib.sha256(material.encode("utf-8")).hexdigest()
    else:
        sample_key = ""
    return {
        "enabled": enabled,
        "sample_key": sample_key,
        "sample_every": sample_every,
        "available_budget_us": shadow_budget_us,
        "estimated_cost_us": estimated_cost_us,
        "already_sampled": already_sampled,
    }

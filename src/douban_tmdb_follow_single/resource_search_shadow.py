from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Optional, Sequence, Tuple

from .resource_models import ResourceCandidate
from .resource_provider import get_resource_provider_adapter
from .resource_search_plan import (
    BINDING_LAYER,
    CACHE_LAYER,
    RECENT_SUCCESS_LAYER,
    ResourceSearchStep,
    build_resource_search_plan,
)


LOCAL_LAYERS = (CACHE_LAYER, RECENT_SUCCESS_LAYER, BINDING_LAYER)


@dataclass(frozen=True)
class LayeredResourceBatch:
    step: ResourceSearchStep
    candidates: Tuple[ResourceCandidate, ...]

    def to_dict(self):
        return {
            "step": self.step.to_dict(),
            "candidates": [candidate.to_dict() for candidate in self.candidates],
        }


def build_layered_resource_shadow(
        local_candidates: Mapping[str, Sequence[ResourceCandidate]],
        provider_payloads: Mapping[str, Any],
        available_modes: Optional[Iterable[Any]] = None) -> Tuple[LayeredResourceBatch, ...]:
    local = {
        layer: tuple((local_candidates or {}).get(layer) or ())
        for layer in LOCAL_LAYERS
    }
    payloads = provider_payloads or {}
    modes = tuple(payloads.keys() if available_modes is None else available_modes)
    plan = build_resource_search_plan(
        modes,
        cache_available=bool(local[CACHE_LAYER]),
        recent_success_available=bool(local[RECENT_SUCCESS_LAYER]),
        binding_available=bool(local[BINDING_LAYER]),
    )
    batches = []
    for step in plan:
        candidates = (
            get_resource_provider_adapter(step.mode).normalize(payloads.get(step.mode))
            if step.mode else local[step.layer]
        )
        batches.append(LayeredResourceBatch(step, tuple(candidates)))
    return tuple(batches)

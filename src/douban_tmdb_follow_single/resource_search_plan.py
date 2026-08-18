from dataclasses import dataclass
from typing import Any, Iterable, Tuple

from .resource_provider import (
    RESOURCE_PROVIDER_ADAPTERS,
    get_resource_provider_adapter,
)
from .resource_schema import SUPPLEMENT_MODES


CACHE_LAYER = "cache"
RECENT_SUCCESS_LAYER = "recent_success"
BINDING_LAYER = "binding"
FAST_PROVIDER_LAYER = "fast_provider"
SUPPLEMENT_PROVIDER_LAYER = "supplement_provider"


@dataclass(frozen=True)
class ResourceSearchStep:
    layer: str
    mode: str = ""

    def to_dict(self):
        return {"layer": self.layer, "mode": self.mode}


def _ordered_modes(available_modes: Iterable[Any]) -> Tuple[str, ...]:
    selected = set()
    for value in available_modes or ():
        selected.add(get_resource_provider_adapter(value).mode)
    return tuple(
        adapter.mode for adapter in RESOURCE_PROVIDER_ADAPTERS
        if adapter.mode in selected
    )


def build_resource_search_plan(
        available_modes: Iterable[Any], cache_available: bool = False,
        recent_success_available: bool = False,
        binding_available: bool = False) -> Tuple[ResourceSearchStep, ...]:
    steps = []
    if cache_available:
        steps.append(ResourceSearchStep(CACHE_LAYER))
    if recent_success_available:
        steps.append(ResourceSearchStep(RECENT_SUCCESS_LAYER))
    if binding_available:
        steps.append(ResourceSearchStep(BINDING_LAYER))
    for mode in _ordered_modes(available_modes):
        layer = (
            SUPPLEMENT_PROVIDER_LAYER
            if mode in SUPPLEMENT_MODES else FAST_PROVIDER_LAYER
        )
        steps.append(ResourceSearchStep(layer, mode))
    return tuple(steps)

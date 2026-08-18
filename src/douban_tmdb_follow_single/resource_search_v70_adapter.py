from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping, Sequence, Tuple

from .resource_candidate_ordering import RESOURCE_MODE_ORDER
from .resource_candidate_pipeline import order_resource_candidate_rows
from .resource_provider import get_resource_provider_adapter
from .resource_row_identity import build_resource_row_identity
from .resource_search_plan import (
    BINDING_LAYER,
    CACHE_LAYER,
    RECENT_SUCCESS_LAYER,
    ResourceSearchStep,
    build_resource_search_plan,
)
from .resource_search_shadow import LayeredResourceBatch


@dataclass(frozen=True)
class LayeredResourceRowsBatch:
    step: ResourceSearchStep
    rows: Tuple[dict, ...] = field(repr=False)


def _v70_row_resource_id(row: Mapping[str, Any]) -> str:
    return str(row.get("vod_id") or row.get("id") or "").strip()


def _v70_matches_resource(row: Mapping[str, Any], resource_id: Any) -> bool:
    target = str(resource_id or "").strip()
    if not target:
        return False
    if _v70_row_resource_id(row) == target:
        return True
    mode = str(row.get("_resource_mode") or "vod").strip().lower() or "vod"
    target_identity = build_resource_row_identity({
        "vod_id": target,
        "_resource_mode": mode,
    })
    return bool(target_identity and build_resource_row_identity(dict(row)) == target_identity)


def _partition_v70_layered_resource_rows(
        rows: Sequence[Mapping[str, Any]], *,
        cached_rows: Sequence[Mapping[str, Any]] = (),
        recent_resource_id: Any = "",
        binding_resource_id: Any = ""):
    cache_identities = {
        identity for identity in (
            build_resource_row_identity(dict(row))
            for row in cached_rows or ()
            if isinstance(row, Mapping)
        ) if identity
    }
    local = {
        CACHE_LAYER: [],
        RECENT_SUCCESS_LAYER: [],
        BINDING_LAYER: [],
    }
    provider_rows = {}
    for value in rows or ():
        if not isinstance(value, Mapping):
            continue
        row = dict(value)
        mode = str(row.get("_resource_mode") or "vod").strip().lower() or "vod"
        adapter = get_resource_provider_adapter(mode)
        identity = build_resource_row_identity(row)
        if identity and identity in cache_identities:
            layer = CACHE_LAYER
        elif _v70_matches_resource(row, recent_resource_id):
            layer = RECENT_SUCCESS_LAYER
        elif _v70_matches_resource(row, binding_resource_id):
            layer = BINDING_LAYER
        else:
            provider_rows.setdefault(mode, []).append(row)
            continue
        local[layer].append(row)
    return local, provider_rows


def build_v70_layered_resource_rows(
        rows: Sequence[Mapping[str, Any]], *,
        cached_rows: Sequence[Mapping[str, Any]] = (),
        recent_resource_id: Any = "",
        binding_resource_id: Any = "",
        available_modes: Iterable[Any] = ()) -> Tuple[LayeredResourceRowsBatch, ...]:
    """Classify shallow-copied V70 rows without dropping playback payload fields."""
    local, provider_rows = _partition_v70_layered_resource_rows(
        rows,
        cached_rows=cached_rows,
        recent_resource_id=recent_resource_id,
        binding_resource_id=binding_resource_id,
    )
    plan = build_resource_search_plan(
        available_modes,
        cache_available=bool(local[CACHE_LAYER]),
        recent_success_available=bool(local[RECENT_SUCCESS_LAYER]),
        binding_available=bool(local[BINDING_LAYER]),
    )
    return tuple(LayeredResourceRowsBatch(
        step,
        tuple(provider_rows.get(step.mode, ()) if step.mode else local[step.layer]),
    ) for step in plan)


def combine_v70_layered_resource_rows(
        rows: Sequence[Mapping[str, Any]], *,
        merge_rows: Callable[[dict, dict], dict],
        score_row: Callable[[dict], Any],
        preference_row: Callable[[dict], Any],
        provider_row: Callable[[dict], Any],
        cached_rows: Sequence[Mapping[str, Any]] = (),
        recent_resource_id: Any = "",
        binding_resource_id: Any = "",
        available_modes: Iterable[Any] = (),
        modes: Iterable[str] = RESOURCE_MODE_ORDER) -> list:
    """Merge and order complete V70 rows within each frozen search layer."""
    batches = build_v70_layered_resource_rows(
        rows,
        cached_rows=cached_rows,
        recent_resource_id=recent_resource_id,
        binding_resource_id=binding_resource_id,
        available_modes=available_modes,
    )
    mode_order = tuple(modes or RESOURCE_MODE_ORDER)
    ordered = []
    for batch in batches:
        ordered.extend(order_resource_candidate_rows(
            batch.rows,
            merge_rows=merge_rows,
            score_row=score_row,
            preference_row=preference_row,
            provider_row=provider_row,
            modes=(batch.step.mode,) if batch.step.mode else mode_order,
        ))
    return ordered


def build_v70_layered_resource_shadow(
        rows: Sequence[Mapping[str, Any]], *,
        cached_rows: Sequence[Mapping[str, Any]] = (),
        recent_resource_id: Any = "",
        binding_resource_id: Any = "",
        available_modes: Iterable[Any] = ()) -> Tuple[LayeredResourceBatch, ...]:
    raw_batches = build_v70_layered_resource_rows(
        rows,
        cached_rows=cached_rows,
        recent_resource_id=recent_resource_id,
        binding_resource_id=binding_resource_id,
        available_modes=available_modes,
    )
    batches = []
    for batch in raw_batches:
        candidates = []
        if batch.step.mode:
            adapter = get_resource_provider_adapter(batch.step.mode)
            candidates.extend(adapter.normalize({"list": list(batch.rows)}))
        else:
            for row in batch.rows:
                mode = str(row.get("_resource_mode") or "vod").strip().lower() or "vod"
                candidates.extend(
                    get_resource_provider_adapter(mode).normalize({"list": [row]})
                )
        batches.append(LayeredResourceBatch(batch.step, tuple(candidates)))
    return tuple(batches)

from typing import Any, Iterable, Mapping, Sequence, Tuple

from .resource_provider import get_resource_provider_adapter
from .resource_row_identity import build_resource_row_identity
from .resource_search_plan import (
    BINDING_LAYER,
    CACHE_LAYER,
    RECENT_SUCCESS_LAYER,
)
from .resource_search_shadow import (
    LayeredResourceBatch,
    build_layered_resource_shadow,
)


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


def build_v70_layered_resource_shadow(
        rows: Sequence[Mapping[str, Any]], *,
        cached_rows: Sequence[Mapping[str, Any]] = (),
        recent_resource_id: Any = "",
        binding_resource_id: Any = "",
        available_modes: Iterable[Any] = ()) -> Tuple[LayeredResourceBatch, ...]:
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
        local[layer].extend(adapter.normalize({"list": [row]}))
    provider_payloads = {
        mode: {"list": values} for mode, values in provider_rows.items()
    }
    return build_layered_resource_shadow(
        local,
        provider_payloads,
        available_modes=available_modes,
    )

from typing import Any, Callable

from .resource_row_identity import build_resource_row_identity


def merge_resource_candidate_rows(
    rows: Any,
    *,
    merge_rows: Callable[[dict, dict], dict],
) -> list:
    """Deduplicate candidate rows using the frozen V70 identity and merge order."""
    merged = []
    positions = {}
    for value in rows or []:
        if not isinstance(value, dict):
            continue
        row = dict(value)
        identity = build_resource_row_identity(row)
        if not identity:
            merged.append(row)
            continue
        if identity in positions:
            index = positions[identity]
            merged[index] = merge_rows(merged[index], row)
        else:
            positions[identity] = len(merged)
            merged.append(row)
    return merged

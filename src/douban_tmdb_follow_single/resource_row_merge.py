from typing import Any, Tuple


Preference = Tuple[int, int, int, int, float, int, int]
_EMPTY_VALUES = (None, "", [], {})
_PROTECTED_TITLE_KEYS = (
    "work_title", "vod_name", "name", "title", "vod_title", "show_name", "note",
)
_TIMESTAMP_KEYS = (
    "_resource_timestamp", "datetime", "vod_time", "timestamp",
    "created_at", "updated_at", "create_time", "update_time",
)


def merge_resource_rows(
        current: Any,
        candidate: Any,
        *,
        current_preference: Preference,
        candidate_preference: Preference,
        item_is_dict: bool) -> dict:
    """Merge two rows using the frozen V70 preference and evidence contract."""
    left = dict(current or {})
    right = dict(candidate or {})
    if candidate_preference > current_preference:
        primary, secondary = right, left
    else:
        primary, secondary = left, right

    merged = dict(primary)
    for key, value in secondary.items():
        if key.startswith("_") or value in _EMPTY_VALUES:
            continue
        if item_is_dict and key in _PROTECTED_TITLE_KEYS:
            continue
        if merged.get(key) in _EMPTY_VALUES:
            merged[key] = value

    primary_id = str(primary.get("vod_id") or primary.get("id") or "").strip()
    left_id = str(left.get("vod_id") or left.get("id") or "").strip()
    right_id = str(right.get("vod_id") or right.get("id") or "").strip()
    left_password = current_preference[3]
    right_password = candidate_preference[3]
    left_timestamp = current_preference[4]
    right_timestamp = candidate_preference[4]
    if right_password > left_password:
        selected_id = right_id
    elif left_password > right_password:
        selected_id = left_id
    elif right_timestamp > left_timestamp:
        selected_id = right_id
    else:
        selected_id = primary_id or left_id or right_id
    if selected_id:
        merged["vod_id"] = selected_id

    if max(left_timestamp, right_timestamp) > 0:
        newer = right if right_timestamp > left_timestamp else left
        merged["_resource_timestamp"] = next((
            newer.get(key) for key in _TIMESTAMP_KEYS
            if newer.get(key) not in (None, "")
        ), max(left_timestamp, right_timestamp))

    if (
            selected_id != primary_id
            or str(merged.get("_resource_mode") or "") != str(primary.get("_resource_mode") or "")):
        merged.pop("_validated_groups", None)
    return merged

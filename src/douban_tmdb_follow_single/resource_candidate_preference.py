from typing import Any, Optional, Tuple


Preference = Tuple[int, int, int, int, float, int, int]
_METADATA_KEYS = (
    "vod_name", "name", "title", "note", "source", "type", "vod_remarks",
)


def _validated_groups_flag(value: Any) -> int:
    try:
        return 1 if int(value) > 0 else 0
    except Exception:
        return 0


def build_resource_row_preference(
        row: Any,
        *,
        row_score: int,
        work_title_score: Optional[int],
        password_score: int,
        timestamp_rank: float) -> Preference:
    """Compose the frozen V70 row-preference tuple from precomputed evidence."""
    if not isinstance(row, dict):
        return (0, 0, 0, 0, 0.0, 0, 0)

    work_title = str(row.get("work_title") or "").strip()
    if work_title and work_title_score is not None:
        work_state = 2 if work_title_score > 0 else 0
    else:
        work_state = 2 if work_title else 1

    metadata_count = sum(
        1 for key in _METADATA_KEYS
        if row.get(key) not in (None, "", [], {})
    )
    return (
        1 if row_score > 0 else 0,
        work_state,
        row_score,
        password_score,
        timestamp_rank,
        _validated_groups_flag(row.get("_validated_groups")),
        metadata_count,
    )

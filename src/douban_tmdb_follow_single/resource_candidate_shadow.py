from typing import Any, Callable, Iterable

from .resource_candidate_ordering import RESOURCE_MODE_ORDER
from .resource_candidate_pipeline import order_resource_candidate_rows


def build_resource_candidate_shadow_report(
    legacy_rows: Any,
    rows: Any,
    *,
    merge_rows: Callable[[dict, dict], dict],
    score_row: Callable[[dict], Any],
    preference_row: Callable[[dict], Any],
    provider_row: Callable[[dict], Any],
    modes: Iterable[str] = RESOURCE_MODE_ORDER,
) -> dict:
    """Compare legacy and P2 orders without exposing rows or changing legacy output."""
    legacy_count = 0
    candidate_count = 0
    try:
        legacy = list(legacy_rows or ())
        legacy_count = len(legacy)
        candidate = order_resource_candidate_rows(
            rows,
            merge_rows=merge_rows,
            score_row=score_row,
            preference_row=preference_row,
            provider_row=provider_row,
            modes=modes,
        )
        candidate_count = len(candidate)
        common_count = min(legacy_count, candidate_count)
        first_difference = next((
            index for index in range(common_count)
            if legacy[index] != candidate[index]
        ), -1)
        if first_difference < 0 and legacy_count != candidate_count:
            first_difference = common_count
        return {
            "status": "equal" if first_difference < 0 else "different",
            "legacy_count": legacy_count,
            "candidate_count": candidate_count,
            "first_difference": first_difference,
            "error_type": "",
        }
    except Exception as exc:
        return {
            "status": "error",
            "legacy_count": legacy_count,
            "candidate_count": candidate_count,
            "first_difference": -1,
            "error_type": type(exc).__name__,
        }

from typing import Any, Callable, Iterable

from .resource_candidate_merge import merge_resource_candidate_rows
from .resource_candidate_ordering import (
    CandidateOrderEntry,
    RESOURCE_MODE_ORDER,
    order_resource_candidates,
)


def order_resource_candidate_rows(
    rows: Any,
    *,
    merge_rows: Callable[[dict, dict], dict],
    score_row: Callable[[dict], Any],
    preference_row: Callable[[dict], Any],
    provider_row: Callable[[dict], Any],
    modes: Iterable[str] = RESOURCE_MODE_ORDER,
) -> list:
    """Merge and fairly order rows with the frozen V70 callback sequence."""
    candidates = merge_resource_candidate_rows(rows, merge_rows=merge_rows)
    ranked = {}
    positive_modes = {}

    for order, row in enumerate(candidates):
        score = score_row(row)
        if score <= 0:
            continue
        mode = str(row.get("_resource_mode") or "vod")
        positive_modes[order] = mode
        ranked.setdefault(mode, []).append((row, order))

    preferences = {}
    providers = {}

    def preference_key(value):
        row, order = value
        preference = preference_row(row)
        preferences[order] = preference
        return preference, -order

    for values in ranked.values():
        values.sort(key=preference_key, reverse=True)

    for values in ranked.values():
        for row, order in values:
            providers[order] = provider_row(row) or "unknown"

    entries = [
        CandidateOrderEntry(
            row=row,
            score=1,
            preference=preferences[order],
            mode=positive_modes[order],
            provider=providers[order],
        )
        for order, row in enumerate(candidates)
        if order in positive_modes
    ]
    return list(order_resource_candidates(entries, modes=modes))

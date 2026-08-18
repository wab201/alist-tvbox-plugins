from typing import Any, Callable, Iterable

from .resource_candidate_ordering import RESOURCE_MODE_ORDER
from .resource_candidate_shadow import build_resource_candidate_shadow_report
from .resource_candidate_shadow_policy import decide_resource_candidate_shadow


def compose_resource_candidate_shadow(
    legacy_rows: Any,
    rows: Any,
    *,
    enabled: bool,
    sample_key: str,
    sample_every: int,
    available_budget_us: int,
    estimated_cost_us: int,
    already_sampled: bool = False,
    merge_rows: Callable[[dict, dict], dict],
    score_row: Callable[[dict], Any],
    preference_row: Callable[[dict], Any],
    provider_row: Callable[[dict], Any],
    modes: Iterable[str] = RESOURCE_MODE_ORDER,
) -> dict:
    """Apply shadow admission before building the fixed redacted report."""
    decision = decide_resource_candidate_shadow(
        enabled=enabled,
        sample_key=sample_key,
        sample_every=sample_every,
        available_budget_us=available_budget_us,
        estimated_cost_us=estimated_cost_us,
        already_sampled=already_sampled,
    )
    result = {"decision": decision, "report": None}
    if not decision["run"]:
        return result
    result["report"] = build_resource_candidate_shadow_report(
        legacy_rows,
        rows,
        merge_rows=merge_rows,
        score_row=score_row,
        preference_row=preference_row,
        provider_row=provider_row,
        modes=modes,
    )
    return result

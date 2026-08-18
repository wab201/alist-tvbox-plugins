import hashlib


def _decision(run, reason):
    return {"run": run, "reason": reason}


def decide_resource_candidate_shadow(
    *,
    enabled: bool,
    sample_key: str,
    sample_every: int,
    available_budget_us: int,
    estimated_cost_us: int,
    already_sampled: bool = False,
) -> dict:
    """Select a bounded deterministic shadow run without exposing its key."""
    if enabled is not True:
        return _decision(False, "disabled")
    if already_sampled:
        return _decision(False, "already_sampled")
    if not isinstance(sample_key, str) or not sample_key:
        return _decision(False, "missing_key")
    if type(sample_every) is not int or sample_every < 1:
        raise ValueError("sample_every must be a positive integer")
    if type(estimated_cost_us) is not int or estimated_cost_us < 1:
        raise ValueError("estimated_cost_us must be a positive integer")
    if type(available_budget_us) is not int:
        raise ValueError("available_budget_us must be an integer")
    if available_budget_us < estimated_cost_us:
        return _decision(False, "insufficient_budget")

    digest = hashlib.sha256(sample_key.encode("utf-8")).digest()
    selected = int.from_bytes(digest[:8], "big") % sample_every == 0
    return _decision(selected, "selected" if selected else "not_selected")

import pytest

from src.douban_tmdb_follow_single.resource_candidate_shadow_composition import (
    compose_resource_candidate_shadow,
)


class _UnreadableRows:
    def __iter__(self):
        raise AssertionError("rows must not be consumed")


def _compose(**overrides):
    values = {
        "legacy_rows": [],
        "rows": [],
        "enabled": True,
        "sample_key": "background-detail-1",
        "sample_every": 1,
        "available_budget_us": 5328,
        "estimated_cost_us": 5328,
        "already_sampled": False,
        "merge_rows": lambda _left, right: right,
        "score_row": lambda row: row["score"],
        "preference_row": lambda row: row["preference"],
        "provider_row": lambda row: row.get("provider"),
    }
    values.update(overrides)
    return compose_resource_candidate_shadow(**values)


@pytest.mark.parametrize(("overrides", "reason"), [
    ({"enabled": False}, "disabled"),
    ({"already_sampled": True}, "already_sampled"),
    ({"sample_key": ""}, "missing_key"),
    ({"available_budget_us": 5327}, "insufficient_budget"),
    ({"sample_key": "skip-2", "sample_every": 2}, "not_selected"),
])
def test_skipped_decisions_do_not_consume_rows_or_callbacks(overrides, reason):
    def fail(*_args):
        raise AssertionError("report callbacks must not run")

    result = _compose(
        legacy_rows=_UnreadableRows(),
        rows=_UnreadableRows(),
        merge_rows=fail,
        score_row=fail,
        preference_row=fail,
        provider_row=fail,
        **overrides,
    )

    assert result == {
        "decision": {"run": False, "reason": reason},
        "report": None,
    }


def test_selected_decision_builds_the_redacted_report_once():
    calls = {"merge": 0, "score": 0, "preference": 0, "provider": 0}
    rows = [{
        "vod_id": "a",
        "score": 1,
        "preference": (1,),
        "provider": "quark",
    }]

    def merge(_left, right):
        calls["merge"] += 1
        return right

    def score(row):
        calls["score"] += 1
        return row["score"]

    def preference(row):
        calls["preference"] += 1
        return row["preference"]

    def provider(row):
        calls["provider"] += 1
        return row["provider"]

    result = _compose(
        legacy_rows=rows,
        rows=rows,
        merge_rows=merge,
        score_row=score,
        preference_row=preference,
        provider_row=provider,
    )

    assert result == {
        "decision": {"run": True, "reason": "selected"},
        "report": {
            "status": "equal",
            "legacy_count": 1,
            "candidate_count": 1,
            "first_difference": -1,
            "error_type": "",
        },
    }
    assert calls == {"merge": 0, "score": 1, "preference": 1, "provider": 1}


def test_selected_difference_preserves_only_fixed_report_fields():
    private_marker = "private-row-value"
    result = _compose(
        legacy_rows=[{"vod_id": private_marker}],
        rows=[{"vod_id": "candidate", "score": 1, "preference": (1,)}],
    )

    assert result["decision"] == {"run": True, "reason": "selected"}
    assert result["report"] == {
        "status": "different",
        "legacy_count": 1,
        "candidate_count": 1,
        "first_difference": 0,
        "error_type": "",
    }
    assert private_marker not in str(result)


def test_selected_report_errors_remain_contained():
    private_marker = "private-callback-value"

    result = _compose(
        legacy_rows=[],
        rows=[{"vod_id": "a", "score": 1, "preference": (1,)}],
        score_row=lambda _row: (_ for _ in ()).throw(RuntimeError(private_marker)),
    )

    assert result == {
        "decision": {"run": True, "reason": "selected"},
        "report": {
            "status": "error",
            "legacy_count": 0,
            "candidate_count": 0,
            "first_difference": -1,
            "error_type": "RuntimeError",
        },
    }
    assert private_marker not in str(result)


def test_policy_validation_errors_are_not_hidden_by_composition():
    with pytest.raises(ValueError, match="sample_every"):
        _compose(sample_every=0)


def test_base_exceptions_from_selected_report_are_not_swallowed():
    with pytest.raises(KeyboardInterrupt):
        _compose(
            rows=[{"vod_id": "a"}],
            score_row=lambda _row: (_ for _ in ()).throw(KeyboardInterrupt()),
        )


def test_input_ownership_remains_with_the_caller():
    legacy = []
    rows = [{"vod_id": "a", "score": 1, "preference": (1,)}]
    rows_before = [dict(row) for row in rows]

    result = _compose(legacy_rows=legacy, rows=rows, already_sampled=False)

    assert legacy == []
    assert rows == rows_before
    assert result["decision"]["run"] is True


def test_result_has_a_fixed_two_field_envelope():
    result = _compose(enabled=False)

    assert tuple(result) == ("decision", "report")
    assert tuple(result["decision"]) == ("run", "reason")

import importlib.util
import sys
import types
from contextlib import contextmanager
from pathlib import Path

import pytest

import src.douban_tmdb_follow_single.resource_candidate_pipeline as pipeline_module
from src.douban_tmdb_follow_single.resource_candidate_ordering import RESOURCE_MODE_ORDER
from src.douban_tmdb_follow_single.resource_candidate_pipeline import (
    order_resource_candidate_rows,
)


ROOT = Path(__file__).resolve().parents[1]
PUBLIC_SOURCE = ROOT / "py" / "豆瓣TMDB追更单入口.py"


@contextmanager
def _load_v70():
    base_module = types.ModuleType("base")
    spider_module = types.ModuleType("base.spider")
    spider_module.Spider = type("BaseSpider", (object,), {})
    base_module.spider = spider_module
    saved = (sys.modules.get("base"), sys.modules.get("base.spider"))
    sys.modules["base"] = base_module
    sys.modules["base.spider"] = spider_module
    try:
        spec = importlib.util.spec_from_file_location("v70_candidate_pipeline_reference", PUBLIC_SOURCE)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        yield module
    finally:
        for name, previous in zip(("base", "base.spider"), saved):
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous


@pytest.fixture(scope="module")
def v70():
    with _load_v70() as module:
        yield module


def _identity_merge(_left, right):
    return right


def _order(rows, modes=RESOURCE_MODE_ORDER, merge_rows=_identity_merge):
    return order_resource_candidate_rows(
        rows,
        merge_rows=merge_rows,
        score_row=lambda row: row["score"],
        preference_row=lambda row: row["preference"],
        provider_row=lambda row: row.get("provider"),
        modes=modes,
    )


def test_pipeline_matches_v70_with_injected_frozen_callbacks(v70):
    rows = [
        {"vod_id": "vod-low", "score": 1, "preference": (1,), "_resource_mode": "vod", "provider": "quark"},
        {"vod_id": "telegram-high", "score": 1, "preference": (3,), "_resource_mode": "telegram", "provider": "ali"},
        {"vod_id": "vod-high-a", "score": 1, "preference": (3,), "_resource_mode": "vod", "provider": "quark"},
        {"vod_id": "vod-high-b", "score": 1, "preference": (3,), "_resource_mode": "vod", "provider": "ali"},
        {"vod_id": "zero", "score": 0, "preference": (99,), "_resource_mode": "vod", "provider": "ali"},
        {"vod_id": "future", "score": 1, "preference": (2,), "_resource_mode": "future", "provider": ""},
    ]
    spider = v70.Spider.__new__(v70.Spider)
    spider.RESOURCE_SEARCH_MODES = RESOURCE_MODE_ORDER
    spider._merge_resource_candidate_rows = lambda values, _item, _bound: [dict(row) for row in values]
    spider._resource_score = lambda row, _item, _bound: row["score"]
    spider._resource_row_preference = lambda row, _item, _bound: row["preference"]
    spider._resource_provider_key = lambda *values: values[0]

    expected = spider._resource_fair_candidate_order(rows, {}, modes=RESOURCE_MODE_ORDER)
    actual = _order(rows)

    assert actual == expected


def test_callbacks_follow_v70_stage_order(monkeypatch):
    rows = [
        {"name": "vod-a", "score": 2, "preference": (5,), "_resource_mode": "vod", "provider": "a"},
        {"name": "telegram-b", "score": 1, "preference": (3,), "_resource_mode": "telegram", "provider": "b"},
        {"name": "vod-c", "score": 1, "preference": (4,), "_resource_mode": "vod", "provider": "c"},
        {"name": "zero", "score": 0, "preference": (99,), "_resource_mode": "pansou", "provider": "z"},
    ]
    events = []
    monkeypatch.setattr(
        pipeline_module,
        "merge_resource_candidate_rows",
        lambda values, merge_rows: events.append(("merge", [row["name"] for row in values])) or list(values),
    )

    result = order_resource_candidate_rows(
        rows,
        merge_rows=_identity_merge,
        score_row=lambda row: events.append(("score", row["name"])) or row["score"],
        preference_row=lambda row: events.append(("preference", row["name"])) or row["preference"],
        provider_row=lambda row: events.append(("provider", row["name"])) or row["provider"],
        modes=("vod", "telegram"),
    )

    assert [row["name"] for row in result] == ["vod-a", "telegram-b", "vod-c"]
    assert events == [
        ("merge", ["vod-a", "telegram-b", "vod-c", "zero"]),
        ("score", "vod-a"),
        ("score", "telegram-b"),
        ("score", "vod-c"),
        ("score", "zero"),
        ("preference", "vod-a"),
        ("preference", "vod-c"),
        ("preference", "telegram-b"),
        ("provider", "vod-a"),
        ("provider", "vod-c"),
        ("provider", "telegram-b"),
    ]


def test_merge_finishes_before_scoring_and_duplicate_is_scored_once():
    events = []

    def merge_rows(left, right):
        events.append(("merge_rows", left["vod_id"], right["vod_id"]))
        return {"vod_id": left["vod_id"], "score": 1, "preference": (2,), "provider": "merged"}

    rows = [
        {"vod_id": "same", "score": 1, "preference": (1,), "provider": "first"},
        {"vod_id": "same", "score": 1, "preference": (2,), "provider": "second"},
    ]
    result = order_resource_candidate_rows(
        rows,
        merge_rows=merge_rows,
        score_row=lambda row: events.append(("score", row["provider"])) or row["score"],
        preference_row=lambda row: row["preference"],
        provider_row=lambda row: row["provider"],
    )

    assert events == [("merge_rows", "same", "same"), ("score", "merged")]
    assert [row["provider"] for row in result] == ["merged"]


def test_nonpositive_rows_do_not_call_preference_or_provider():
    rows = [
        {"vod_id": "zero", "score": 0},
        {"vod_id": "negative", "score": -1},
    ]

    assert order_resource_candidate_rows(
        rows,
        merge_rows=_identity_merge,
        score_row=lambda row: row["score"],
        preference_row=lambda _row: pytest.fail("preference should not run"),
        provider_row=lambda _row: pytest.fail("provider should not run"),
    ) == []


def test_preferences_run_by_first_seen_mode_then_input_order():
    rows = [
        {"name": "telegram-1", "score": 1, "preference": (1,), "_resource_mode": "telegram"},
        {"name": "vod-1", "score": 1, "preference": (1,), "_resource_mode": "vod"},
        {"name": "telegram-2", "score": 1, "preference": (2,), "_resource_mode": "telegram"},
    ]
    calls = []

    order_resource_candidate_rows(
        rows,
        merge_rows=_identity_merge,
        score_row=lambda row: row["score"],
        preference_row=lambda row: calls.append(row["name"]) or row["preference"],
        provider_row=lambda _row: "provider",
    )

    assert calls == ["telegram-1", "telegram-2", "vod-1"]


def test_providers_run_in_ranked_order_within_each_mode():
    rows = [
        {"name": "low", "score": 1, "preference": (1,)},
        {"name": "high", "score": 1, "preference": (3,)},
        {"name": "mid", "score": 1, "preference": (2,)},
    ]
    calls = []

    order_resource_candidate_rows(
        rows,
        merge_rows=_identity_merge,
        score_row=lambda row: row["score"],
        preference_row=lambda row: row["preference"],
        provider_row=lambda row: calls.append(row["name"]) or row["name"],
    )

    assert calls == ["high", "mid", "low"]


def test_modes_are_consumed_after_all_candidate_callbacks():
    events = []

    def modes():
        events.append("modes")
        yield "vod"

    result = order_resource_candidate_rows(
        [{"vod_id": "a", "score": 1, "preference": (1,)}],
        merge_rows=_identity_merge,
        score_row=lambda row: events.append("score") or row["score"],
        preference_row=lambda row: events.append("preference") or row["preference"],
        provider_row=lambda _row: events.append("provider") or "x",
        modes=modes(),
    )

    assert [row["vod_id"] for row in result] == ["a"]
    assert events == ["score", "preference", "provider", "modes"]


@pytest.mark.parametrize(("mode", "expected"), [
    (None, "vod"),
    ("", "vod"),
    (7, "7"),
    (" VOD ", " VOD "),
])
def test_mode_keeps_v70_string_conversion(mode, expected):
    row = {"vod_id": "a", "score": 1, "preference": (1,), "_resource_mode": mode}

    result = _order([row], modes=(expected,))

    assert result[0]["vod_id"] == "a"


def test_falsey_providers_share_the_unknown_bucket():
    rows = [
        {"vod_id": "a", "score": 1, "preference": (3,), "provider": ""},
        {"vod_id": "b", "score": 1, "preference": (2,), "provider": None},
        {"vod_id": "c", "score": 1, "preference": (1,), "provider": "known"},
    ]

    assert [row["vod_id"] for row in _order(rows)] == ["a", "c", "b"]


def test_non_dict_rows_are_skipped_before_scoring():
    calls = []
    result = order_resource_candidate_rows(
        [None, "skip", {"vod_id": "a", "score": 1, "preference": (1,)}],
        merge_rows=_identity_merge,
        score_row=lambda row: calls.append(row["vod_id"]) or row["score"],
        preference_row=lambda row: row["preference"],
        provider_row=lambda _row: "x",
    )

    assert calls == ["a"]
    assert [row["vod_id"] for row in result] == ["a"]


@pytest.mark.parametrize("rows", [1, object()])
def test_truthy_noniterable_rows_keep_native_type_error(rows):
    with pytest.raises(TypeError):
        order_resource_candidate_rows(
            rows,
            merge_rows=_identity_merge,
            score_row=lambda _row: pytest.fail("score should not run"),
            preference_row=lambda _row: (),
            provider_row=lambda _row: "x",
        )


@pytest.mark.parametrize("stage", ["merge", "score", "preference", "provider"])
def test_callback_exceptions_propagate_without_wrapping(stage):
    def fail(name):
        if stage == name:
            raise RuntimeError(name + " failed")

    with pytest.raises(RuntimeError, match=stage + " failed"):
        order_resource_candidate_rows(
            [{"vod_id": "same", "score": 1, "preference": (1,)}, {"vod_id": "same", "score": 1, "preference": (2,)}],
            merge_rows=lambda left, right: fail("merge") or left,
            score_row=lambda row: fail("score") or row["score"],
            preference_row=lambda row: fail("preference") or row["preference"],
            provider_row=lambda _row: fail("provider") or "x",
        )


def test_result_is_a_list_of_shallow_copied_rows_without_input_mutation():
    nested = {"shared": True}
    row = {"vod_id": "a", "score": 1, "preference": (1,), "nested": nested}
    before = dict(row)

    result = _order([row])

    assert type(result) is list
    assert result[0] is not row
    assert result[0]["nested"] is nested
    assert row == before


def test_all_positive_rows_are_returned_without_truncation():
    rows = [
        {"vod_id": str(index), "score": 1, "preference": (30 - index,), "provider": str(index % 3)}
        for index in range(30)
    ]

    result = _order(rows)

    assert len(result) == 30
    assert {row["vod_id"] for row in result} == {row["vod_id"] for row in rows}

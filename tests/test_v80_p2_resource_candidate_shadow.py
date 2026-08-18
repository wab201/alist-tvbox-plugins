import importlib.util
import sys
import types
from contextlib import contextmanager
from pathlib import Path

import pytest

from src.douban_tmdb_follow_single.resource_candidate_ordering import RESOURCE_MODE_ORDER
from src.douban_tmdb_follow_single.resource_candidate_shadow import (
    build_resource_candidate_shadow_report,
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
        spec = importlib.util.spec_from_file_location("v70_candidate_shadow_reference", PUBLIC_SOURCE)
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


def _replace_left(_left, right):
    return right


def _report(legacy_rows, rows, **overrides):
    callbacks = {
        "merge_rows": _replace_left,
        "score_row": lambda row: row["score"],
        "preference_row": lambda row: row["preference"],
        "provider_row": lambda row: row.get("provider"),
        "modes": RESOURCE_MODE_ORDER,
    }
    callbacks.update(overrides)
    return build_resource_candidate_shadow_report(legacy_rows, rows, **callbacks)


def test_equal_report_matches_v70_candidate_order(v70):
    rows = [
        {"vod_id": "vod-low", "score": 1, "preference": (1,), "_resource_mode": "vod", "provider": "quark"},
        {"vod_id": "telegram-high", "score": 1, "preference": (3,), "_resource_mode": "telegram", "provider": "ali"},
        {"vod_id": "vod-high", "score": 1, "preference": (3,), "_resource_mode": "vod", "provider": "ali"},
        {"vod_id": "zero", "score": 0, "preference": (99,), "_resource_mode": "vod", "provider": "quark"},
    ]
    spider = v70.Spider.__new__(v70.Spider)
    spider.RESOURCE_SEARCH_MODES = RESOURCE_MODE_ORDER
    spider._merge_resource_candidate_rows = lambda values, _item, _bound: [dict(row) for row in values]
    spider._resource_score = lambda row, _item, _bound: row["score"]
    spider._resource_row_preference = lambda row, _item, _bound: row["preference"]
    spider._resource_provider_key = lambda *values: values[0]
    legacy = spider._resource_fair_candidate_order(rows, {}, modes=RESOURCE_MODE_ORDER)

    assert _report(legacy, rows) == {
        "status": "equal",
        "legacy_count": 3,
        "candidate_count": 3,
        "first_difference": -1,
        "error_type": "",
    }


def test_first_different_row_index_is_reported_without_row_values():
    legacy = [
        {"vod_id": "a", "score": 1, "preference": (3,)},
        {"vod_id": "wrong", "score": 1, "preference": (2,)},
        {"vod_id": "c", "score": 1, "preference": (1,)},
    ]
    rows = [
        {"vod_id": "a", "score": 1, "preference": (3,)},
        {"vod_id": "b", "score": 1, "preference": (2,)},
        {"vod_id": "c", "score": 1, "preference": (1,)},
    ]

    report = _report(legacy, rows)

    assert report == {
        "status": "different",
        "legacy_count": 3,
        "candidate_count": 3,
        "first_difference": 1,
        "error_type": "",
    }
    assert "wrong" not in str(report)


@pytest.mark.parametrize(("legacy", "rows", "expected_index"), [
    ([{"vod_id": "a", "score": 1, "preference": (2,)}], [
        {"vod_id": "a", "score": 1, "preference": (2,)},
        {"vod_id": "b", "score": 1, "preference": (1,)},
    ], 1),
    ([
        {"vod_id": "a", "score": 1, "preference": (1,)},
        {"vod_id": "b", "score": 1, "preference": (0,)},
    ], [
        {"vod_id": "a", "score": 1, "preference": (1,)},
    ], 1),
])
def test_length_difference_uses_the_shared_prefix_length(legacy, rows, expected_index):
    report = _report(legacy, rows)

    assert report["status"] == "different"
    assert report["first_difference"] == expected_index


def test_empty_outputs_are_equal():
    assert _report([], []) == {
        "status": "equal",
        "legacy_count": 0,
        "candidate_count": 0,
        "first_difference": -1,
        "error_type": "",
    }


def test_full_row_difference_is_detected_even_when_resource_id_matches():
    legacy = [{"vod_id": "same", "vod_name": "legacy"}]
    rows = [{"vod_id": "same", "vod_name": "candidate", "score": 1, "preference": (1,)}]

    assert _report(legacy, rows)["first_difference"] == 0


def test_legacy_generator_is_consumed_once():
    legacy = (
        {"vod_id": value, "score": 1, "preference": preference}
        for value, preference in (("a", (2,)), ("b", (1,)))
    )
    rows = [
        {"vod_id": "a", "score": 1, "preference": (2,)},
        {"vod_id": "b", "score": 1, "preference": (1,)},
    ]

    assert _report(legacy, rows)["status"] == "equal"
    assert list(legacy) == []


@pytest.mark.parametrize("stage", ["merge", "score", "preference", "provider"])
def test_candidate_callback_errors_are_contained_without_messages(stage):
    message_marker = "private-" + "value-must-not-appear"

    def fail(name):
        if stage == name:
            raise RuntimeError(name + " failed " + message_marker)

    report = build_resource_candidate_shadow_report(
        [],
        [{"vod_id": "same", "score": 1, "preference": (1,)}, {"vod_id": "same", "score": 1, "preference": (2,)}],
        merge_rows=lambda left, right: fail("merge") or left,
        score_row=lambda row: fail("score") or row["score"],
        preference_row=lambda row: fail("preference") or row["preference"],
        provider_row=lambda _row: fail("provider") or "x",
    )

    assert report["status"] == "error"
    assert report["error_type"] == "RuntimeError"
    assert message_marker not in str(report)


def test_legacy_iteration_error_is_contained():
    class BrokenRows:
        def __iter__(self):
            raise ValueError("raw legacy row must stay private")

    report = _report(BrokenRows(), [])

    assert report == {
        "status": "error",
        "legacy_count": 0,
        "candidate_count": 0,
        "first_difference": -1,
        "error_type": "ValueError",
    }


def test_row_comparison_error_is_contained():
    class BrokenEquality:
        def __eq__(self, _other):
            raise LookupError("comparison failed")

        def __ne__(self, other):
            return not self == other

    legacy = [{
        "vod_id": "a", "marker": BrokenEquality(), "score": 1, "preference": (1,),
    }]
    rows = [{"vod_id": "a", "marker": BrokenEquality(), "score": 1, "preference": (1,)}]

    report = _report(legacy, rows)

    assert report["status"] == "error"
    assert report["error_type"] == "LookupError"


def test_truthy_noniterable_candidate_rows_are_contained():
    report = _report([], 1)

    assert report["status"] == "error"
    assert report["error_type"] == "TypeError"


def test_base_exceptions_are_not_swallowed():
    with pytest.raises(KeyboardInterrupt):
        _report(
            [],
            [{"vod_id": "a"}],
            score_row=lambda _row: (_ for _ in ()).throw(KeyboardInterrupt()),
        )


def test_inputs_are_not_mutated_and_report_never_contains_rows():
    legacy = [{"vod_id": "a", "private": "legacy-private"}]
    rows = [{"vod_id": "a", "private": "candidate-private", "score": 1, "preference": (1,)}]
    legacy_before = [dict(row) for row in legacy]
    rows_before = [dict(row) for row in rows]

    report = _report(legacy, rows)

    assert legacy == legacy_before
    assert rows == rows_before
    assert "legacy-private" not in str(report)
    assert "candidate-private" not in str(report)


def test_report_has_only_the_fixed_diagnostic_fields():
    assert tuple(_report([], [])) == (
        "status", "legacy_count", "candidate_count", "first_difference", "error_type",
    )

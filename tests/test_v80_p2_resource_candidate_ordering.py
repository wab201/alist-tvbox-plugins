import importlib.util
import sys
import types
from contextlib import contextmanager
from pathlib import Path

import pytest

from src.douban_tmdb_follow_single.resource_candidate_ordering import (
    CandidateOrderEntry,
    RESOURCE_MODE_ORDER,
    order_resource_candidates,
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
        spec = importlib.util.spec_from_file_location("v70_candidate_ordering_reference", PUBLIC_SOURCE)
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


def _entry(name, score, preference, mode="vod", provider=""):
    return CandidateOrderEntry(
        row=name,
        score=score,
        preference=preference,
        mode=mode,
        provider=provider,
    )


def test_zero_scores_are_filtered_and_all_positive_entries_are_returned():
    entries = [
        _entry("zero", 0, (99,)),
        _entry("negative", -1, (100,)),
        _entry("first", 500, (1,)),
        _entry("second", 470, (0,)),
    ]

    assert order_resource_candidates(entries) == ("first", "second")


def test_preference_descends_and_input_order_breaks_ties():
    entries = [
        _entry("late-high", 1, (5,)),
        _entry("early-high", 1, (5,)),
        _entry("low", 1, (4,)),
    ]

    assert order_resource_candidates(entries) == ("late-high", "early-high", "low")


def test_provider_round_robin_uses_first_provider_order_after_ranking():
    entries = [
        _entry("ali-1", 1, (1,), provider="ali"),
        _entry("quark-1", 1, (3,), provider="quark"),
        _entry("quark-2", 1, (2,), provider="quark"),
        _entry("ali-2", 1, (0,), provider="ali"),
    ]

    assert order_resource_candidates(entries) == (
        "quark-1", "ali-1", "quark-2", "ali-2",
    )


def test_empty_provider_values_share_unknown_bucket_without_detection():
    entries = [
        _entry("unknown-1", 1, (3,)),
        _entry("known", 1, (2,), provider="quark"),
        _entry("unknown-2", 1, (1,)),
    ]

    assert order_resource_candidates(entries) == (
        "unknown-1", "known", "unknown-2",
    )


def test_modes_are_interleaved_in_fixed_order_and_unlisted_modes_append():
    entries = [
        _entry("telegram-1", 1, (3,), mode="telegram", provider="x"),
        _entry("vod-1", 1, (2,), mode="vod", provider="x"),
        _entry("telegram-2", 1, (1,), mode="telegram", provider="x"),
        _entry("future-1", 1, (0,), mode="future", provider="x"),
    ]

    assert RESOURCE_MODE_ORDER == ("vod1", "vod", "pansou", "telegram")
    assert order_resource_candidates(entries) == (
        "vod-1", "telegram-1", "future-1", "telegram-2",
    )


def test_falsy_mode_uses_vod_bucket_without_normalizing_other_modes():
    entries = [
        _entry("empty-mode", 1, (2,), mode=""),
        _entry("literal-mode", 1, (1,), mode=" VOD "),
    ]

    assert order_resource_candidates(entries) == ("empty-mode", "literal-mode")


def test_highest_preference_is_not_promoted_across_mode_round_robin():
    entries = [
        _entry("vod1-normal", 1, (1,), mode="vod1"),
        _entry("vod-bound", 10000, (10000,), mode="vod"),
        _entry("vod-normal", 1, (1,), mode="vod"),
    ]

    assert order_resource_candidates(entries) == (
        "vod1-normal", "vod-bound", "vod-normal",
    )


def test_duplicate_values_are_preserved_without_identity_merge():
    entries = [
        _entry("same", 1, (2,), provider="quark"),
        _entry("same", 1, (1,), provider="quark"),
    ]

    ordered = order_resource_candidates(entries)
    assert ordered == ("same", "same")


def test_more_than_fifteen_rows_are_returned_by_identity_without_truncation():
    rows = [{"id": index} for index in range(20)]
    entries = [
        CandidateOrderEntry(row=row, score=1, preference=(20 - index,))
        for index, row in enumerate(rows)
    ]

    ordered = order_resource_candidates(entries)

    assert len(ordered) == 20
    assert all(actual is expected for actual, expected in zip(ordered, rows))


def test_precomputed_score_and_preference_are_used_without_callbacks():
    entries = [
        _entry("provided", 1, (10,), provider="quark"),
        _entry("also-provided", 1, (9,), provider="ali"),
    ]

    assert order_resource_candidates(entries) == ("provided", "also-provided")


def test_full_order_matches_v70_when_merge_scoring_and_provider_detection_are_precomputed(v70):
    entries = [
        _entry("vod-low", 470, (1, 1), mode="vod", provider="quark"),
        _entry("telegram-high", 530, (1, 3), mode="telegram", provider="ali"),
        _entry("vod-high-a", 530, (1, 3), mode="vod", provider="quark"),
        _entry("vod-high-b", 530, (1, 3), mode="vod", provider="ali"),
        _entry("zero", 0, (1, 99), mode="vod", provider="ali"),
        _entry("future", 500, (1, 2), mode="future", provider=""),
    ]
    rows = [{
        "value": entry.row,
        "_score": entry.score,
        "_preference": entry.preference,
        "_resource_mode": entry.mode,
        "provider": entry.provider,
    } for entry in entries]
    spider = v70.Spider()
    spider.RESOURCE_SEARCH_MODES = RESOURCE_MODE_ORDER
    spider._merge_resource_candidate_rows = lambda values, _item, _bound: list(values)
    spider._resource_score = lambda row, _item, _bound: row["_score"]
    spider._resource_row_preference = lambda row, _item, _bound: row["_preference"]
    spider._resource_provider_key = lambda *values: str(values[0] or "")

    expected = [row["value"] for row in spider._resource_fair_candidate_order(
        rows, {}, modes=RESOURCE_MODE_ORDER,
    )]
    actual = list(order_resource_candidates(entries, modes=RESOURCE_MODE_ORDER))

    assert actual == expected

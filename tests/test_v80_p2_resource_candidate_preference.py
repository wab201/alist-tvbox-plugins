import importlib.util
import sys
import types
from collections import UserDict
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import unquote

import pytest

from src.douban_tmdb_follow_single.resource_candidate_preference import (
    build_resource_row_preference,
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
        spec = importlib.util.spec_from_file_location("v70_candidate_preference_reference", PUBLIC_SOURCE)
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


def _actual_from_v70_evidence(v70, row, item=None, bound=""):
    if not isinstance(row, dict):
        return build_resource_row_preference(
            row,
            row_score=object(),
            work_title_score=object(),
            password_score=object(),
            timestamp_rank=object(),
        )

    spider = v70.Spider()
    item_is_dict = isinstance(item, dict)
    row_score = spider._resource_score(row, item, bound) if item_is_dict else 0
    work_title = str(row.get("work_title") or "").strip()
    work_title_score = None
    if item_is_dict and work_title:
        work_title_score = spider._resource_score({
            "vod_id": row.get("vod_id") or row.get("id"),
            "work_title": work_title,
        }, item, bound)
    resource_id = str(row.get("vod_id") or row.get("id") or "").strip()
    return build_resource_row_preference(
        row,
        row_score=row_score,
        work_title_score=work_title_score,
        password_score=spider._resource_url_password_score(unquote(resource_id)),
        timestamp_rank=spider._resource_row_timestamp(row),
    )


def _assert_v70_equal(v70, row, item=None, bound=""):
    expected = v70.Spider()._resource_row_preference(row, item, bound)
    actual = _actual_from_v70_evidence(v70, row, item, bound)
    assert actual == expected
    return actual


@pytest.mark.parametrize(("row", "item", "bound"), [
    (None, {}, ""),
    (UserDict({"work_title": "测试剧集"}), {}, ""),
    ({"work_title": "测试剧集"}, None, ""),
    ({"work_title": "测试剧集"}, UserDict({"title": "测试剧集"}), ""),
    ({"vod_id": "candidate", "vod_name": "测试剧集"}, {"title": "测试剧集"}, ""),
    ({"vod_id": "candidate", "work_title": "测试剧集"}, {"title": "测试剧集"}, ""),
    ({"vod_id": "candidate", "work_title": "另一部作品"}, {"title": "测试剧集"}, ""),
    ({"vod_id": "bound", "work_title": "测试剧集预告"}, {"title": "测试剧集"}, "bound"),
    ({"id": "bound", "work_title": "测试剧集"}, {"title": "测试剧集"}, "bound"),
    ({"vod_id": "https%3A%2F%2Fexample.com%2Fs%2Fabc%3Fpwd%3D1234"}, None, ""),
    ({"datetime": "2026-01-01", "updated_at": 1900000000}, None, ""),
])
def test_preference_matches_v70_for_fixed_contract_cases(v70, row, item, bound):
    _assert_v70_equal(v70, row, item, bound)


def test_dict_subclasses_are_accepted_but_userdict_is_rejected(v70):
    class RowDict(dict):
        pass

    row = RowDict({"work_title": "测试剧集", "vod_name": "测试剧集"})

    assert _assert_v70_equal(v70, row, None) == (0, 2, 0, 0, 0.0, 0, 1)
    assert _assert_v70_equal(v70, UserDict(row), None) == (0, 0, 0, 0, 0.0, 0, 0)


@pytest.mark.parametrize(("value", "expected"), [
    (True, 1),
    (1.9, 1),
    ("2", 1),
    (False, 0),
    (-1, 0),
    ("1.9", 0),
    (float("nan"), 0),
    (float("inf"), 0),
    ([], 0),
])
def test_validated_groups_keeps_v70_positive_int_boundary(v70, value, expected):
    row = {"_validated_groups": value}

    result = _assert_v70_equal(v70, row, None)

    assert result[5] == expected


@pytest.mark.parametrize(("value", "expected"), [
    (None, 0),
    ("", 0),
    ([], 0),
    ({}, 0),
    (0, 1),
    (False, 1),
    ((), 1),
    (set(), 1),
    ("   ", 1),
])
def test_metadata_count_excludes_only_v70_sentinels(v70, value, expected):
    row = {"vod_name": value}

    result = _assert_v70_equal(v70, row, None)

    assert result[6] == expected


def test_metadata_count_uses_only_the_frozen_seven_keys(v70):
    row = {
        "vod_name": "1", "name": "2", "title": "3", "note": "4",
        "source": "5", "type": "6", "vod_remarks": "7",
        "work_title": "not-counted", "vod_year": "not-counted",
        "provider": "not-counted", "links": ["not-counted"],
    }

    assert _assert_v70_equal(v70, row, None)[6] == 7


def test_precomputed_values_are_placed_without_recalculation_or_clamping():
    row = {"work_title": "测试剧集", "vod_name": "resource", "_validated_groups": "2"}

    result = build_resource_row_preference(
        row,
        row_score=10000,
        work_title_score=0,
        password_score=1,
        timestamp_rank=123.5,
    )

    assert type(result) is tuple
    assert result == (1, 0, 10000, 1, 123.5, 1, 1)


def test_work_title_score_none_records_that_v70_did_not_run_second_score():
    assert build_resource_row_preference(
        {"work_title": "测试剧集"},
        row_score=0,
        work_title_score=None,
        password_score=0,
        timestamp_rank=0.0,
    )[1] == 2
    assert build_resource_row_preference(
        {},
        row_score=0,
        work_title_score=None,
        password_score=0,
        timestamp_rank=0.0,
    )[1] == 1


def test_tuple_comparison_keeps_v70_field_priority():
    def preference(
            row_score=1, work_title_score=1, password_score=0,
            timestamp_rank=0.0, validated_groups=0, metadata=False):
        row = {"work_title": "work", "_validated_groups": validated_groups}
        if metadata:
            row["vod_name"] = "resource"
        return build_resource_row_preference(
            row,
            row_score=row_score,
            work_title_score=work_title_score,
            password_score=password_score,
            timestamp_rank=timestamp_rank,
        )

    assert preference() > preference(row_score=0, password_score=9, timestamp_rank=999.0)
    assert preference() > preference(row_score=10000, work_title_score=0)
    assert preference(row_score=2) > preference(row_score=1, password_score=9)
    assert preference(password_score=1) > preference(timestamp_rank=999.0)
    assert preference(timestamp_rank=1.0) > preference(validated_groups=1, metadata=True)
    assert preference(validated_groups=1) > preference(metadata=True)
    assert preference(metadata=True) > preference()


def test_function_does_not_mutate_the_row():
    row = {"work_title": " 测试剧集 ", "links": [{"title": "nested"}]}
    before = {"work_title": row["work_title"], "links": [dict(row["links"][0])]}

    build_resource_row_preference(
        row,
        row_score=500,
        work_title_score=500,
        password_score=0,
        timestamp_rank=0.0,
    )

    assert row == before

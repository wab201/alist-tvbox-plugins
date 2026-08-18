import importlib.util
import sys
import types
from collections import UserDict
from contextlib import contextmanager
from pathlib import Path

import pytest

from src.douban_tmdb_follow_single.resource_row_scoring import (
    RESOURCE_LINK_SCAN_LIMIT,
    resource_title_values,
    resource_work_title_values,
    score_resource_row,
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
        spec = importlib.util.spec_from_file_location("v70_resource_row_scoring_reference", PUBLIC_SOURCE)
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


def _item(aliases, target_year="", tracking_season=1, season_count=0):
    values = aliases.split("\n") if isinstance(aliases, str) else list(aliases or ())
    return {
        "title": values[0] if values else "",
        "title_aliases": values[1:],
        "year": target_year,
        "trackingSeason": tracking_season,
        "season_count": season_count,
    }


def _assert_v70_equal(v70, row, aliases, target_year="", tracking_season=1,
                      season_count=0, bound_resource_id=""):
    expected = v70.Spider()._resource_score(
        row,
        _item(aliases, target_year, tracking_season, season_count),
        bound_resource_id,
    )
    actual = score_resource_row(
        row,
        aliases,
        target_year=target_year,
        tracking_season=tracking_season,
        season_count=season_count,
        bound_resource_id=bound_resource_id,
    )
    assert actual == expected
    return actual


def test_title_collectors_keep_v70_order_uniqueness_and_link_limit():
    assert RESOURCE_LINK_SCAN_LIMIT == 32
    row = {
        "vod_name": " parent ",
        "name": "parent",
        "title": "title",
        "work_title": "work",
        "links": [
            {"work_title": "work"},
            {"work_title": "nested", "title": "nested title", "note": "note"},
        ] + [{"work_title": "late-%d" % index} for index in range(32)],
    }

    assert resource_work_title_values(row)[:2] == ("work", "nested")
    assert "late-30" not in resource_work_title_values(row)
    assert resource_title_values(row)[:5] == ("parent", "title", "work", "nested", "nested title")


def test_direct_work_title_overrides_matching_parent_fields(v70):
    row = {
        "vod_id": "candidate",
        "work_title": "完全无关的另一部作品",
        "vod_name": "测试剧集 2026 1080P",
        "title": "测试剧集",
    }

    assert _assert_v70_equal(v70, row, ("测试剧集",), target_year="2026") == 0


def test_nested_work_title_overrides_matching_parent_fields(v70):
    row = {
        "vod_id": "candidate",
        "vod_name": "测试剧集 2026 1080P",
        "links": [{"work_title": "完全无关的另一部作品"}],
    }

    assert _assert_v70_equal(v70, row, ("测试剧集",), target_year="2026") == 0


def test_mapping_subclass_row_is_not_a_v70_dict(v70):
    row = UserDict({"vod_id": "candidate", "vod_name": "测试剧集"})

    assert _assert_v70_equal(v70, row, ("测试剧集",)) == 0


def test_mapping_subclass_row_keeps_type_rejection_before_bound(v70):
    row = UserDict({"vod_id": "bound-id", "vod_name": "测试剧集"})

    assert _assert_v70_equal(
        v70, row, ("测试剧集",), bound_resource_id="bound-id",
    ) == 0


def test_mapping_subclass_nested_link_is_skipped_like_v70(v70):
    row = {
        "vod_id": "candidate",
        "vod_name": "完全无关",
        "links": [UserDict({"work_title": "测试剧集"})],
    }

    assert _assert_v70_equal(v70, row, ("测试剧集",)) == 0


def test_row_keeps_highest_score_across_work_titles(v70):
    row = {
        "vod_id": "candidate",
        "work_title": "测试剧集 1080P",
        "vod_remarks": "2026",
        "links": [{"work_title": "测试剧集"}],
    }

    assert _assert_v70_equal(v70, row, ("测试剧集",), target_year="2026") == 530


def test_regular_fields_are_used_only_when_no_work_title_exists(v70):
    row = {
        "vod_id": "candidate",
        "vod_name": "完全无关",
        "name": "测试剧集",
        "links": [{"title": "测试剧集 S02", "note": "ignored duplicate"}],
    }

    assert _assert_v70_equal(
        v70, row, ("测试剧集",), tracking_season=2, season_count=3,
    ) == 550


def test_matching_work_title_after_first_32_links_is_not_scanned(v70):
    assert RESOURCE_LINK_SCAN_LIMIT == 32
    row = {
        "vod_id": "candidate",
        "vod_name": "测试剧集",
        "links": [
            {"work_title": "无关作品 %d" % index}
            for index in range(32)
        ] + [{"work_title": "测试剧集"}],
    }

    assert _assert_v70_equal(v70, row, ("测试剧集",)) == 0


def test_nested_title_year_is_not_row_year_evidence(v70):
    row = {
        "vod_id": "candidate",
        "links": [{"work_title": "测试剧集 2026"}],
    }

    assert _assert_v70_equal(v70, row, ("测试剧集",), target_year="2026") == 470


def test_parent_year_evidence_scores_nested_exact_title(v70):
    row = {
        "vod_id": "candidate",
        "vod_remarks": "2026",
        "links": [{"work_title": "测试剧集"}],
    }

    assert _assert_v70_equal(v70, row, ("测试剧集",), target_year="2026") == 530


def test_parent_year_conflict_rejects_nested_title_without_exact_season(v70):
    row = {
        "vod_id": "candidate",
        "vod_remarks": "2025",
        "links": [{"work_title": "测试剧集"}],
    }

    assert _assert_v70_equal(v70, row, ("测试剧集",), target_year="2026") == 0


def test_exact_season_overrides_parent_year_conflict(v70):
    row = {
        "vod_id": "candidate",
        "vod_remarks": "2025",
        "links": [{"work_title": "测试剧集 S02"}],
    }

    assert _assert_v70_equal(
        v70, row, ("测试剧集",), target_year="2026", tracking_season=2, season_count=3,
    ) == 550


@pytest.mark.parametrize(("row", "expected"), [
    ({"vod_id": "bound-id"}, 0),
    ({"vod_id": "bound-id", "vod_name": "测试剧集预告"}, 0),
    ({"vod_id": "bound-id", "vod_name": "测试剧集预告", "title": "完全无关"}, 10000),
    ({"vod_id": "bound-id", "vod_name": "___"}, 10000),
])
def test_bound_row_keeps_v70_title_preconditions(v70, row, expected):
    assert _assert_v70_equal(
        v70, row, ("测试剧集",), bound_resource_id="bound-id",
    ) == expected

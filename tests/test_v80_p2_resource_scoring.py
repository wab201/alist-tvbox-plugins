import importlib.util
import sys
import types
from contextlib import contextmanager
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from src.douban_tmdb_follow_single.resource_matching import CONFLICT, INSUFFICIENT, MATCH
from src.douban_tmdb_follow_single.resource_scoring import (
    BOUND_RESOURCE_SCORE,
    DECORATED_TITLE_SCORE,
    EXACT_SEASON_SCORE,
    EXACT_TITLE_SCORE,
    EXACT_YEAR_SCORE,
    ResourceScore,
    score_resource_title,
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
        spec = importlib.util.spec_from_file_location("v70_resource_scoring_reference", PUBLIC_SOURCE)
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


def _v70_score(v70, raw_title, aliases, target_year="", tracking_season=1,
               season_count=0, candidate_year_text="", resource_id="candidate", bound=""):
    values = aliases.split("\n") if isinstance(aliases, str) else list(aliases or ())
    item = {
        "title": values[0] if values else "",
        "title_aliases": values[1:],
        "year": target_year,
        "trackingSeason": tracking_season,
        "season_count": season_count,
    }
    row = {"vod_id": resource_id, "vod_name": raw_title, "vod_remarks": candidate_year_text}
    return v70.Spider()._resource_score(row, item, bound)


def _v70_score_with_raw_aliases(v70, raw_title, aliases):
    item = {"title": "", "title_aliases": aliases}
    row = {"vod_id": "candidate", "vod_name": raw_title}
    return v70.Spider()._resource_score(row, item, "")


def test_frozen_policy_values_match_v70():
    assert BOUND_RESOURCE_SCORE == 10000
    assert EXACT_TITLE_SCORE == 500
    assert DECORATED_TITLE_SCORE == 470
    assert EXACT_SEASON_SCORE == 80
    assert EXACT_YEAR_SCORE == 30


@pytest.mark.parametrize(("raw_title", "aliases", "kwargs", "expected"), [
    ("测试剧集", ("测试剧集",), {}, ResourceScore(
        500, MATCH, "exact_title", (("exact_title", 500),),
    )),
    ("测试剧集 1080P", ("测试剧集",), {}, ResourceScore(
        470, MATCH, "decorated_title", (("decorated_title", 470),),
    )),
    ("测试剧集 S02", ("测试剧集",), {"tracking_season": 2, "season_count": 3}, ResourceScore(
        550, MATCH, "decorated_title", (("decorated_title", 470), ("exact_season", 80)),
    )),
    ("测试剧集", ("测试剧集",), {"target_year": "2026", "candidate_year_text": "2026"}, ResourceScore(
        530, MATCH, "exact_title", (("exact_title", 500), ("exact_year", 30)),
    )),
    ("测试剧集 S02", ("测试剧集 S02",), {
        "target_year": "2026", "tracking_season": 2, "season_count": 3,
        "candidate_year_text": "2026",
    }, ResourceScore(
        610, MATCH, "exact_title",
        (("exact_title", 500), ("exact_season", 80), ("exact_year", 30)),
    )),
])
def test_score_and_components_match_v70(v70, raw_title, aliases, kwargs, expected):
    result = score_resource_title(raw_title, aliases, **kwargs)

    assert result == expected
    assert result.score == _v70_score(v70, raw_title, aliases, **kwargs)


@pytest.mark.parametrize(("raw_title", "aliases", "kwargs", "outcome", "reason"), [
    ("测试剧集预告", ("测试剧集",), {}, CONFLICT, "denied_variant"),
    ("测试剧集 S02", ("测试剧集",), {"tracking_season": 1, "season_count": 3},
     CONFLICT, "season_conflict"),
    ("测试剧集", ("测试剧集",), {"target_year": "2026", "candidate_year_text": "2025"},
     CONFLICT, "year_conflict"),
    ("另一部作品", ("测试剧集",), {}, INSUFFICIENT, "non_exact_title"),
    ("测试剧集", (), {}, INSUFFICIENT, "missing_aliases"),
])
def test_rejected_or_insufficient_candidates_keep_zero_score(
        v70, raw_title, aliases, kwargs, outcome, reason):
    result = score_resource_title(raw_title, aliases, **kwargs)

    assert result == ResourceScore(0, outcome, reason)
    assert _v70_score(v70, raw_title, aliases, **kwargs) == 0


def test_bound_resource_keeps_v70_precedence_over_match_conflicts(v70):
    kwargs = {
        "target_year": "2026",
        "tracking_season": 1,
        "season_count": 3,
        "candidate_year_text": "2025",
        "resource_id": "  bound-id  ",
        "bound_resource_id": "bound-id",
    }

    result = score_resource_title("测试剧集 S02", (), **kwargs)

    assert result == ResourceScore(
        10000, MATCH, "bound_resource", (("bound_resource", 10000),),
    )
    assert _v70_score(
        v70, "测试剧集 S02", (), target_year="2026", tracking_season=1,
        season_count=3, candidate_year_text="2025", resource_id="  bound-id  ", bound="bound-id",
    ) == 10000


@pytest.mark.parametrize(("raw_title", "reason"), [
    ("", "missing_title"),
    ("测试剧集预告", "denied_variant"),
])
def test_bound_resource_does_not_override_missing_or_denied_title(v70, raw_title, reason):
    result = score_resource_title(
        raw_title, ("测试剧集",), resource_id="bound-id", bound_resource_id="bound-id",
    )

    assert result.score == 0
    assert result.reason == reason
    assert _v70_score(
        v70, raw_title, ("测试剧集",), resource_id="bound-id", bound="bound-id",
    ) == 0


@pytest.mark.parametrize("raw_title", ["___", "---", "（ ）", "..."])
def test_bound_resource_precedes_per_title_normalization_like_v70(v70, raw_title):
    bound = score_resource_title(
        raw_title, ("Title",), resource_id="bound-id", bound_resource_id="bound-id",
    )
    unbound = score_resource_title(raw_title, ("Title",))

    assert bound == ResourceScore(
        10000, MATCH, "bound_resource", (("bound_resource", 10000),),
    )
    assert unbound == ResourceScore(0, INSUFFICIENT, "missing_title")
    assert _v70_score(
        v70, raw_title, ("Title",), resource_id="bound-id", bound="bound-id",
    ) == 10000
    assert _v70_score(v70, raw_title, ("Title",)) == 0


def test_float_tracking_season_and_string_aliases_remain_v70_equivalent(v70):
    result = score_resource_title(
        "测试剧集 S02 2026", "另一标题\n测试剧集", target_year="2026",
        tracking_season="2.0", season_count=3,
    )

    assert result == ResourceScore(
        580, MATCH, "decorated_title",
        (("decorated_title", 470), ("exact_season", 80), ("exact_year", 30)),
    )
    assert result.score == _v70_score(
        v70, "测试剧集 S02 2026", "另一标题\n测试剧集", target_year="2026",
        tracking_season="2.0", season_count=3,
    )


@pytest.mark.parametrize("aliases", [{"Title": "other"}, 123, b"Title"])
def test_non_collection_alias_values_keep_v70_zero_score(v70, aliases):
    result = score_resource_title("Title", aliases)

    assert result == ResourceScore(0, INSUFFICIENT, "non_exact_title")
    assert _v70_score_with_raw_aliases(v70, "Title", aliases) == 0


def test_resource_score_is_immutable():
    result = score_resource_title("测试剧集", ("测试剧集",))

    with pytest.raises(FrozenInstanceError):
        result.score = 0

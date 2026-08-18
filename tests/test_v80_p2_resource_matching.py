import importlib.util
import sys
import types
from contextlib import contextmanager
from pathlib import Path

import pytest

from src.douban_tmdb_follow_single.resource_matching import (
    CONFLICT,
    INSUFFICIENT,
    MATCH,
    MatchDecision,
    _decorated_alias,
    match_resource_title,
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
        spec = importlib.util.spec_from_file_location("v70_resource_matching_reference", PUBLIC_SOURCE)
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
               season_count=0, candidate_year_text=""):
    values = list(aliases)
    item = {
        "title": values[0] if values else "",
        "title_aliases": values[1:],
        "year": target_year,
        "trackingSeason": tracking_season,
        "season_count": season_count,
    }
    row = {"vod_id": "candidate", "vod_name": raw_title, "vod_remarks": candidate_year_text}
    return v70.Spider()._resource_score(row, item, "")


def _v70_score_with_alias_text(v70, raw_title, aliases):
    item = {"title": "", "title_aliases": aliases}
    row = {"vod_id": "candidate", "vod_name": raw_title}
    return v70.Spider()._resource_score(row, item, "")


@pytest.mark.parametrize(("raw_title", "aliases"), [
    ("测试 剧集", ("测试剧集",)),
    ("ＴＥＳＴ", ("test",)),
    ("Original", ("Primary", "original")),
])
def test_exact_normalized_alias_is_a_clear_match(v70, raw_title, aliases):
    decision = match_resource_title(raw_title, aliases)

    assert decision == MatchDecision(MATCH, "exact_title")
    assert _v70_score(v70, raw_title, aliases) > 0


def test_missing_title_or_aliases_are_insufficient():
    assert match_resource_title("", ("Title",)) == MatchDecision(INSUFFICIENT, "missing_title")
    assert match_resource_title("Title", ()) == MatchDecision(INSUFFICIENT, "missing_aliases")
    assert match_resource_title("Title", None) == MatchDecision(INSUFFICIENT, "missing_aliases")


@pytest.mark.parametrize(("raw_title", "kwargs", "reason"), [
    ("Title S02", {"tracking_season": 1, "season_count": 3}, "season_conflict"),
    ("Title", {"target_year": "2026", "candidate_year_text": "2025"}, "year_conflict"),
])
def test_missing_aliases_do_not_hide_v70_hard_conflicts(v70, raw_title, kwargs, reason):
    assert match_resource_title(raw_title, (), **kwargs) == MatchDecision(CONFLICT, reason)
    assert _v70_score(v70, raw_title, (), **kwargs) == 0


def test_v70_decorated_title_is_a_clear_match(v70):
    raw_title = "测试剧集 2026 1080P"
    aliases = ("测试剧集",)

    assert match_resource_title(raw_title, aliases, target_year="2026",
                                candidate_year_text=raw_title) == MatchDecision(
        MATCH, "decorated_title",
    )
    assert _v70_score(v70, raw_title, aliases, "2026", candidate_year_text=raw_title) > 0


@pytest.mark.parametrize("raw_title", [
    "测试剧集(2026) S01E01-E06 内封简繁 HiveWeb",
    "测试剧集 [夸克] 更新至E06",
    "测试剧集 第一季 4K HDR10Plus H265 DDP5",
    "测试剧集 美剧 附前两季 12GB Telegram",
])
def test_v70_allowed_decorations_are_promoted(v70, raw_title):
    aliases = ("测试剧集",)

    assert match_resource_title(raw_title, aliases) == MatchDecision(MATCH, "decorated_title")
    assert _v70_score(v70, raw_title, aliases) > 0


def test_decorated_alias_returns_v70_longest_match_or_empty(v70):
    aliases = {"测试剧集", "测试剧集完整版"}

    assert _decorated_alias("测试剧集完整版2026", aliases) == v70.Spider._resource_decorated_alias(
        "测试剧集完整版2026", aliases,
    ) == "测试剧集完整版"
    assert _decorated_alias("测试剧集导演收藏", aliases) == v70.Spider._resource_decorated_alias(
        "测试剧集导演收藏", aliases,
    ) == ""


@pytest.mark.parametrize(("raw_title", "aliases", "reason"), [
    ("测试剧集", "测试剧集", "exact_title"),
    ("测试剧集2026", "测试剧集", "decorated_title"),
    ("测试剧集", "另一标题\n测试剧集", "exact_title"),
])
def test_string_aliases_keep_v70_newline_semantics(v70, raw_title, aliases, reason):
    assert match_resource_title(raw_title, aliases) == MatchDecision(MATCH, reason)
    assert _v70_score_with_alias_text(v70, raw_title, aliases) > 0


@pytest.mark.parametrize("aliases", [{"Title": "other"}, 123, b"Title"])
def test_non_collection_alias_values_keep_v70_string_semantics(v70, aliases):
    assert match_resource_title("Title", aliases) == MatchDecision(
        INSUFFICIENT, "non_exact_title",
    )
    assert _v70_score_with_alias_text(v70, "Title", aliases) == 0


def test_short_alias_can_be_removed_but_cannot_promote_by_itself(v70):
    aliases = ("测试剧集", "特别")
    raw_title = "测试剧集特别2026"

    assert match_resource_title(raw_title, aliases) == MatchDecision(MATCH, "decorated_title")
    assert _v70_score(v70, raw_title, aliases) > 0

    assert match_resource_title("权游2026", ("权游",)) == MatchDecision(
        INSUFFICIENT, "non_exact_title",
    )
    assert _v70_score(v70, "权游2026", ("权游",)) == 0


def test_unknown_remainder_stays_insufficient(v70):
    raw_title = "测试剧集导演收藏"
    aliases = ("测试剧集",)

    assert match_resource_title(raw_title, aliases) == MatchDecision(
        INSUFFICIENT, "non_exact_title",
    )
    assert _v70_score(v70, raw_title, aliases) == 0


def test_unrelated_title_is_not_promoted_to_a_conflict(v70):
    decision = match_resource_title("另一部作品", ("测试剧集",))

    assert decision == MatchDecision(INSUFFICIENT, "non_exact_title")
    assert _v70_score(v70, "另一部作品", ("测试剧集",)) == 0


@pytest.mark.parametrize("raw_title", [
    "测试剧集预告",
    "测试剧集解说",
    "测试剧集剧场版",
    "Test Trailer",
])
def test_v70_denied_title_variants_are_clear_conflicts(v70, raw_title):
    aliases = (raw_title,)

    assert match_resource_title(raw_title, aliases) == MatchDecision(CONFLICT, "denied_variant")
    assert _v70_score(v70, raw_title, aliases) == 0


def test_multi_season_conflict_is_rejected_before_title_policy(v70):
    raw_title = "测试剧集 S02"
    aliases = ("测试剧集",)

    assert match_resource_title(raw_title, aliases, tracking_season=1, season_count=3) == MatchDecision(
        CONFLICT, "season_conflict",
    )
    assert _v70_score(v70, raw_title, aliases, tracking_season=1, season_count=3) == 0


def test_single_season_contract_keeps_other_season_markers_for_decoration_policy(v70):
    raw_title = "测试剧集 S02"
    aliases = ("测试剧集",)

    assert match_resource_title(raw_title, aliases, tracking_season=1, season_count=1) == MatchDecision(
        MATCH, "decorated_title",
    )
    assert _v70_score(v70, raw_title, aliases, tracking_season=1, season_count=1) > 0


@pytest.mark.parametrize("candidate_year_text", ["2025", "剧2025版"])
def test_year_conflict_without_exact_season_is_rejected(v70, candidate_year_text):
    raw_title = "测试剧集"
    aliases = ("测试剧集",)

    assert match_resource_title(raw_title, aliases, target_year="2026",
                                candidate_year_text=candidate_year_text) == MatchDecision(
        CONFLICT, "year_conflict",
    )
    assert _v70_score(v70, raw_title, aliases, "2026",
                      candidate_year_text=candidate_year_text) == 0


def test_year_embedded_in_raw_title_participates_without_duplicate_input(v70):
    raw_title = "测试剧集2025"
    aliases = (raw_title,)

    assert match_resource_title(raw_title, aliases, target_year="2026") == MatchDecision(
        CONFLICT, "year_conflict",
    )
    assert _v70_score(v70, raw_title, aliases, "2026") == 0


def test_exact_candidate_season_overrides_year_conflict_like_v70(v70):
    raw_title = "测试剧集 S02"
    aliases = ("测试剧集",)

    assert match_resource_title(raw_title, aliases, target_year="2026", tracking_season=2,
                                season_count=3, candidate_year_text="2025") == MatchDecision(
        MATCH, "decorated_title",
    )
    assert _v70_score(v70, raw_title, aliases, "2026", tracking_season=2,
                      season_count=3, candidate_year_text="2025") > 0


def test_float_text_tracking_season_keeps_v70_compatibility(v70):
    raw_title = "测试剧集 S02"
    aliases = (raw_title,)

    assert match_resource_title(raw_title, aliases, tracking_season="2.0",
                                season_count=3) == MatchDecision(MATCH, "exact_title")
    assert _v70_score(v70, raw_title, aliases, tracking_season="2.0", season_count=3) > 0


@pytest.mark.parametrize("candidate_year_text", ["", "2026", "2025 2026"])
def test_exact_title_with_compatible_year_is_a_match(v70, candidate_year_text):
    raw_title = "测试剧集"
    aliases = ("测试剧集",)

    assert match_resource_title(raw_title, aliases, target_year="2026",
                                candidate_year_text=candidate_year_text) == MatchDecision(
        MATCH, "exact_title",
    )
    assert _v70_score(v70, raw_title, aliases, "2026",
                      candidate_year_text=candidate_year_text) > 0


def test_target_year_keeps_v70_first_four_character_semantics(v70):
    assert match_resource_title("测试剧集", ("测试剧集",), target_year="20260",
                                candidate_year_text="2026") == MatchDecision(MATCH, "exact_title")
    assert _v70_score(v70, "测试剧集", ("测试剧集",), "20260",
                      candidate_year_text="2026") > 0


def test_decision_is_immutable():
    decision = match_resource_title("Title", ("Title",))
    with pytest.raises(Exception) as error:
        decision.outcome = CONFLICT
    assert error.type.__name__ == "FrozenInstanceError"

import importlib.util
import sys
import types
from contextlib import contextmanager
from pathlib import Path

import pytest

from src.douban_tmdb_follow_single.resource_normalization import (
    _chinese_number,
    extract_season,
    extract_year,
    normalize_media_title,
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
        spec = importlib.util.spec_from_file_location("v70_resource_normalization_reference", PUBLIC_SOURCE)
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


@pytest.mark.parametrize("value", [
    None,
    "",
    "  The Last of Us  ",
    "THE_LAST-OF.US",
    "Ｓｅａｓｏｎ　２：测试",
    "Straße",
    "遭到流放的转生重骑士（2026）S01E06",
    "剧集_名称【内封简繁】",
])
def test_title_normalization_matches_v70(value, v70):
    assert normalize_media_title(value) == v70.Spider._normalize_media_title(value)


@pytest.mark.parametrize("value", [
    None,
    "",
    "Movie (2026)",
    "1999 2026",
    "剧2026版",
    "20260",
    "Ｓｅａｓｏｎ ２０２６",
    "1080p",
])
def test_year_extraction_matches_v70(value, v70):
    assert extract_year(value) == v70.Filter._year(value)


@pytest.mark.parametrize("value", [
    None,
    "",
    "Show S01E06",
    "Show S 02",
    "Show Season 03",
    "第4季",
    "第05部",
    "第二季",
    "两季全",
    "第十一季",
    "第壹拾贰部",
    "S00E01",
    "Season 123",
    "S01x02",
])
def test_season_extraction_matches_v70(value, v70):
    assert extract_season(value) == v70.Filter._season(value)


@pytest.mark.parametrize("value", [
    None,
    "",
    "零",
    "〇",
    "两",
    "一二",
    "十一",
    "壹拾贰",
    "一百零二",
    "壹佰零贰",
    "甲二乙",
    "百",
])
def test_chinese_number_helper_matches_v70(value, v70):
    assert _chinese_number(value) == v70.Filter._chinese_number(value)


def test_normalization_is_pure_and_does_not_guess_missing_metadata():
    assert normalize_media_title("A_B-C") == "abc"
    assert extract_year("no year") == 0
    assert extract_season("第六集") == 0

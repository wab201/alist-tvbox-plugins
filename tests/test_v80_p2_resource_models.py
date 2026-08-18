import hashlib
import importlib.util
import json
import sys
import types
from contextlib import contextmanager
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from src.douban_tmdb_follow_single.resource_models import (
    EpisodeRange,
    MediaIdentity,
    PlaySource,
    ResourceCandidate,
)
from src.douban_tmdb_follow_single.resource_shadow import (
    build_shadow_snapshot,
    map_detail_play_sources,
    map_media_identity,
    map_resource_payload,
)
from tools import run_v80_stage_gate


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "v80_p2_resource_samples.json"
PUBLIC_SOURCE = ROOT / "py" / "豆瓣TMDB追更单入口.py"


@pytest.fixture(scope="module")
def samples():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


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
        spec = importlib.util.spec_from_file_location("v70_resource_shadow_reference", PUBLIC_SOURCE)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        yield module
    finally:
        for name, previous in zip(("base", "base.spider"), saved):
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous


def test_models_have_exact_defaults_and_serialization_order():
    assert list(MediaIdentity().to_dict()) == [
        "source_id", "media_type", "tmdb_id", "title", "original_title", "title_aliases", "year",
    ]
    assert MediaIdentity().to_dict() == {
        "source_id": "", "media_type": "movie", "tmdb_id": 0, "title": "",
        "original_title": "", "title_aliases": [], "year": "",
    }
    assert list(ResourceCandidate().to_dict()) == [
        "resource_id", "mode", "provider", "work_title", "titles", "year", "source", "timestamp",
    ]
    assert list(EpisodeRange().to_dict()) == ["season", "start_episode", "end_episode", "explicit"]
    assert list(PlaySource().to_dict()) == ["target", "label", "resource_id", "mode", "provider", "episode"]


@pytest.mark.parametrize("model", [
    MediaIdentity(title_aliases=("A", "B")),
    ResourceCandidate(titles=("A", "B")),
    EpisodeRange(2, 3, 4, True),
    PlaySource(episode=EpisodeRange(2, 3, 3, True)),
])
def test_models_round_trip_and_are_frozen(model):
    assert type(model).from_dict(model.to_dict()) == model
    with pytest.raises(FrozenInstanceError):
        model.mode = "changed"


def test_collection_fields_are_copied_to_immutable_tuples():
    aliases = ["A"]
    titles = ["B"]
    identity = MediaIdentity(title_aliases=aliases)
    candidate = ResourceCandidate(titles=titles)
    episode = {"season": 2, "start_episode": 3, "end_episode": 3, "explicit": True}
    source = PlaySource(episode=episode)
    aliases.append("changed")
    titles.append("changed")
    episode["season"] = 9
    assert identity.title_aliases == ("A",)
    assert candidate.titles == ("B",)
    assert source.episode == EpisodeRange(2, 3, 3, True)
    assert source.to_dict()["episode"]["season"] == 2


def test_media_identity_precedence_and_alias_drift(samples):
    case = samples["identity"]
    identity = map_media_identity(case["raw_id"], case["base_vod"], case["follow_item"])
    assert identity == MediaIdentity(
        source_id="follow-id", media_type="tv", tmdb_id=101,
        title="Follow Title", original_title="Original Follow",
        title_aliases=("Follow Alias", "Shared Alias"), year="2025",
    )
    fallback = map_media_identity("raw", {"titleAliases": '["Alias"]', "vod_name": "Base"}, {})
    assert fallback.source_id == "raw"
    assert fallback.title_aliases == ("Alias",)


@pytest.mark.parametrize("mode", ["vod1", "vod", "pansou", "telegram"])
def test_all_provider_payloads_map_two_or_more_candidates(samples, mode):
    candidates = map_resource_payload(mode, samples["payloads"][mode])
    assert len(candidates) >= 2
    assert all(candidate.mode == mode and candidate.resource_id for candidate in candidates)


def test_generic_payload_precedence(samples):
    vod1 = map_resource_payload("vod1", samples["payloads"]["vod1"])
    assert vod1[0] == ResourceCandidate(
        resource_id="v1-a", mode="vod1", provider="quark", work_title="Alpha",
        titles=("Alpha",), year="2026", source="catalog-a", timestamp="",
    )
    vod = map_resource_payload("vod", samples["payloads"]["vod"])
    assert [row.resource_id for row in vod] == ["https://media.invalid/vod/a", "opaque-vod-b"]
    assert vod[1].work_title == "Delta Work"
    assert vod[1].provider == "pan123"


def test_supplement_payload_is_fair_ordered_and_deduplicated(samples):
    rows = map_resource_payload("pansou", samples["payloads"]["pansou"])
    assert [row.resource_id for row in rows] == [
        "https://pan.quark.cn/s/alpha",
        "https://pan.baidu.com/s/beta?pwd=1234",
        "https://alipan.com/s/delta",
        "https://123pan.com/s/gamma",
    ]
    assert [row.provider for row in rows] == ["quark", "baidu", "ali", "pan123"]
    assert rows[0].work_title == "Parent One"


def test_supplement_dedup_preserves_password_and_v70_url_identities():
    payload = {
        "results": [{
            "title": "Identity cases",
            "links": [
                {"url": "https://pan.baidu.com/s/beta", "title": "Beta"},
                {"url": "https://pan.baidu.com/s/beta", "password": "test-password", "title": "Beta protected"},
                {"url": "https://pan.quark.cn:443/s/share?b=2&a=1", "title": "Share"},
                {"url": "https://pan.quark.cn/s/share?a=1&b=2", "title": "Share duplicate"},
                {"url": "magnet:?xt=urn:btih:0123456789abcdef0123456789abcdef01234567&dn=one", "title": "Magnet"},
                {"url": "magnet:?dn=two&xt=urn:btih:0123456789ABCDEF0123456789ABCDEF01234567", "title": "Magnet duplicate"},
                {"url": "ed2k://|file|one.mkv|1|0123456789abcdef0123456789abcdef|/", "title": "ED2K"},
                {"url": "ed2k://|file|two.mkv|2|0123456789ABCDEF0123456789ABCDEF|/", "title": "ED2K duplicate"},
            ],
        }],
    }
    rows = map_resource_payload("pansou", payload)
    assert len(rows) == 4
    assert "password=test-password" in rows[0].resource_id


def test_provider_aliases_conflicts_and_unknown_supplements_match_v70():
    assert map_resource_payload("vod", {"list": [{"id": "x", "provider": "夸克网盘"}]})[0].provider == "quark"
    alternate_domain = map_resource_payload("pansou", {"results": [
        {"url": "https://123pan.cn/s/x", "note": "Alternate domain"},
    ]})
    assert alternate_domain[0].provider == "pan123"
    rows = map_resource_payload("pansou", {"results": [{"links": [
        {"url": "https://pan.baidu.com/s/conflict", "provider": "夸克", "title": "Conflict"},
        {"url": "https://unknown.invalid/s/value", "title": "Unknown"},
    ]}]})
    assert rows == ()
    direct = map_resource_payload("telegram", {"results": [
        {"url": "https://pan.baidu.com/s/conflict", "provider": "夸克", "title": "Conflict"},
        {"url": "https://unknown.invalid/s/value", "title": "Unknown"},
    ]})
    assert direct == ()


def test_supplement_link_and_generic_row_admission_match_v70():
    rows = map_resource_payload("pansou", {"results": [
        {"id": "opaque", "url": "https://pan.quark.cn/s/a", "work_title": "A"},
        {"url": "https://pan.xunlei.com/s/name", "name": "Name only", "type": "迅雷"},
        {"url": "https://115.com/s/title", "title": "Title only", "provider": "115"},
    ]})
    assert [(row.resource_id, row.work_title, row.provider) for row in rows] == [
        ("https://pan.quark.cn/s/a", "A", "quark"),
        ("opaque", "A", ""),
    ]
    generic = map_resource_payload("vod", {"list": [
        {"id": "opaque", "url": "https://pan.quark.cn/s/a", "work_title": "A"},
    ]})
    assert [(row.resource_id, row.provider) for row in generic] == [("opaque", "")]


def test_detail_groups_preserve_order_provider_and_episode(samples):
    vod = samples["details"]["vod"][0]
    sources = map_detail_play_sources("vod", vod["resource_id"], vod)
    assert [(item.label, item.target, item.provider) for item in sources] == [
        ("01.4K.mkv", "play-1", "quark"),
        ("02.mkv", "play-2", "quark"),
        ("S03E04", "play-4", "pan123"),
    ]
    assert [item.episode for item in sources] == [
        EpisodeRange(1, 1, 1, True),
        EpisodeRange(1, 2, 2, True),
        EpisodeRange(3, 4, 4, True),
    ]
    fallback = map_detail_play_sources("vod", "fallback", samples["details"]["vod"][1])
    assert fallback[0].episode == EpisodeRange(1, 1, 1, False)


def test_snapshot_is_deterministic(samples):
    case = samples["identity"]
    first = build_shadow_snapshot(
        case["raw_id"], case["base_vod"], case["follow_item"], samples["payloads"], samples["details"],
    )
    second = build_shadow_snapshot(
        case["raw_id"], case["base_vod"], case["follow_item"], samples["payloads"], samples["details"],
    )
    assert first == second
    assert list(first) == ["identity", "candidates", "play_sources"]
    assert len(first["candidates"]) == 11
    assert len(first["play_sources"]) == 13
    canonical = json.dumps(first, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    assert hashlib.sha256(canonical).hexdigest() == "52795c8450dd6a4e57025b1b6268422341af47590f0905527eda8362c9d10d2b"


def test_p2_fixtures_contain_no_credentials():
    paths = [FIXTURE, FIXTURE.with_name("v80_p2_resource_samples_README.md")]
    assert run_v80_stage_gate.scan_sensitive_files(paths, repo_root=ROOT) == []


def test_invalid_mode_is_rejected(samples):
    with pytest.raises(ValueError):
        map_resource_payload("future-provider", samples["payloads"]["vod"])


def test_shadow_helpers_match_safe_v70_reference_cases():
    with _load_v70() as module:
        for value in ("夸克", "百度", "123", "https://pan.xunlei.com/s/example"):
            candidate = map_resource_payload("vod", {"list": [{"id": "x", "provider": value}]})[0]
            assert candidate.provider == module.Spider._resource_provider_key(value)
        labels = [
            "01.4K.mkv", "S02E03.1080p.mkv", "Season 2 Episode 3", "EP03",
            "第3集", "03", "8.28 GB", "720.1080p.mkv", "01(413.43 MB)",
        ]
        vod = {"vod_play_from": "资源", "vod_play_url": "#".join(
            "%s$play-%d" % (label, index) for index, label in enumerate(labels, 1)
        )}
        mapped = map_detail_play_sources("vod", "resource", vod)
        assert [
            (item.episode.season, item.episode.start_episode, item.episode.explicit)
            for item in mapped
        ] == [
            module.Spider._episode_from_text_info(label, index, 1)
            for index, label in enumerate(labels, 1)
        ]

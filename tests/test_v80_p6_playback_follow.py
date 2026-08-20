# -*- coding: utf-8 -*-

import importlib.util
import json
import sys
import threading
import time
import types
from pathlib import Path
from unittest.mock import Mock

import pytest


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src" / "douban_tmdb_follow_v80" / "豆瓣TMDB追更单入口.py"


def _load_module():
    base_module = types.ModuleType("base")
    spider_module = types.ModuleType("base.spider")

    class BaseSpider(object):
        pass

    spider_module.Spider = BaseSpider
    sys.modules.setdefault("base", base_module)
    sys.modules.setdefault("base.spider", spider_module)
    spec = importlib.util.spec_from_file_location("douban_tmdb_follow_v801", SOURCE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MODULE = _load_module()


@pytest.fixture
def spider():
    value = MODULE.Spider()
    value.tmdb_api_key = "test-key"
    value._follow_state_loaded = True
    value._persist_follow_state = Mock(return_value=True)
    try:
        yield value
    finally:
        value.destroy()


def _followplay(spider, item, resource_id, episode, **overrides):
    payload_item = dict(item)
    payload_item.update(overrides.pop("item", {}))
    return spider._build_followplay(
        "1@episode-%s" % episode,
        payload_item,
        resource_id,
        1,
        episode,
        "S01E%02d" % episode,
        resource_mode=overrides.pop("resource_mode", "vod"),
        resource_provider=overrides.pop("resource_provider", "alist"),
    )


def _history(spider, item, resource_id, episode, **values):
    row = {
        "key": "plugin-421@@@%s@@@7" % resource_id,
        "vodName": item["title"],
        "vodRemarks": "S01E%02d" % episode,
        "episodeUrl": "S01E%02d$%s" % (
            episode,
            _followplay(spider, item, resource_id, episode),
        ),
        "position": 120000,
        "duration": 1200000,
        "createTime": 100,
        "sourceKind": "spider_plugin",
        "sourceKey": "plugin-421",
        "vodId": resource_id,
        "updatedAt": 100,
    }
    row.update(values)
    return row


def test_playback_state_model_preserves_1511_fields_and_boolean_completed():
    event = MODULE._v80_history_event({
        "sourceKind": "spider_plugin",
        "sourceKey": "plugin-421",
        "vodId": "resource-1",
        "completed": False,
        "clientKey": "tv-living-room",
        "playlistIndex": 4,
        "sourceGroupIndex": 2,
        "sourceIndex": 1,
        "sourceSubgroupIndex": 3,
        "sourceSubgroupName": "第二季",
        "driveDirId": "dir-9",
        "driveShareKey": "quark@share-id@",
        "drivePath": "/Show/S02/E03.mp4",
        "updatedAt": 99,
    })

    assert event["completed"] is False
    assert event["clientKey"] == "tv-living-room"
    assert event["playlistIndex"] == 4
    assert event["sourceGroupIndex"] == 2
    assert event["sourceSubgroupName"] == "第二季"
    assert event["driveDirId"] == "dir-9"
    assert event["driveShareKey"] == "quark@share-id@"
    assert event["drivePath"] == "/Show/S02/E03.mp4"

    numeric = MODULE._v80_history_event({
        "sourceKind": "site", "sourceKey": "s", "vodId": "v", "completed": 1,
    })
    assert "completed" not in numeric


def test_playback_state_v1_migrates_read_only_to_v2():
    scope = "https://server|7|site,spider_plugin"
    cached = {
        "version": 1,
        "scope": scope,
        "nextSince": "8",
        "records": [{
            "sourceKind": "site", "sourceKey": "s", "vodId": "v", "updatedAt": 7,
        }],
    }
    owner = types.SimpleNamespace(
        _v80_history_auth_origin="https://server",
        _v80_history_auth_uid=7,
        HISTORY_ROW_LIMIT=32,
        getCache=lambda _key: cached,
    )

    state = MODULE._v80_history_state_get(owner)

    assert state["version"] == 2
    assert state["nextSince"] == "8"
    assert state["records"][0]["vodId"] == "v"


def test_strong_identity_conflict_fails_closed(spider):
    item = {
        "media_type": "tv",
        "tmdb_id": 101,
        "source_id": "tmdb:tv:101",
        "title": "测试剧集",
        "trackingSeason": 1,
    }
    conflicting_item = dict(item, source_id="douban:subject:999")
    history = _history(spider, conflicting_item, "resource-1", 3)

    match = spider._atvp_history_for_item(item, [history])

    assert match["_follow_history_conflict"] is True
    assert spider._history_resume_fields(item, match) == {}
    assert spider._follow_remark(item, match) == "播放记录待确认（TMDB或来源编号冲突） · 不自动更新追更进度"


def test_exact_followplay_identity_wins_over_stale_conflicting_history(spider):
    item = {
        "media_type": "tv",
        "tmdb_id": 101,
        "source_id": "tmdb:tv:101",
        "title": "测试剧集",
        "trackingSeason": 1,
    }
    stale = _history(
        spider,
        dict(item, source_id="douban:subject:999"),
        "resource-old",
        2,
        updatedAt=100,
    )
    exact = _history(spider, item, "resource-new", 3, updatedAt=200)

    match = spider._atvp_history_for_item(item, [stale, exact])

    assert match.get("_follow_history_conflict") is not True
    assert match["vodId"] == "resource-new"


def test_bound_fallback_rejects_conflicting_full_playback_identity(spider):
    item = {
        "media_type": "tv",
        "tmdb_id": 101,
        "title": "测试剧集",
        "alist_vod_id": "resource-1",
        "history_playback": {
            "sourceKind": "spider_plugin",
            "sourceKey": "plugin-421",
            "vodId": "resource-1",
        },
    }
    spider._v80_history_source_kinds = {("resource-site", "resource-1"): "site"}
    history = {
        "key": "resource-site@@@resource-1@@@7",
        "vodName": "测试剧集",
        "vodRemarks": "S01E03",
        "position": 120000,
        "duration": 1200000,
    }

    match = spider._atvp_history_for_item(item, [history])

    assert match["_follow_history_conflict"] is True
    assert match["_follow_history_conflict_reason"] == "playback_identity"


def test_completed_false_blocks_legacy_threshold_and_true_advances_seen(spider):
    item = {
        "media_type": "tv",
        "tmdb_id": 101,
        "source_id": "tmdb:tv:101",
        "title": "测试剧集",
        "trackingSeason": 1,
        "latest_episode": "S01E06",
        "seen_episode": "S01E02",
    }
    spider._follow_memory = {"version": 2, "items": {"101": item}}
    unfinished = _history(
        spider, item, "resource-1", 3,
        position=920000, duration=1000000, completed=False, updatedAt=200,
    )

    assert spider._reconcile_follow_histories([unfinished]) == 1
    current = spider._follow_memory["items"]["101"]
    assert current["history_completed"] is False
    assert current["seen_episode"] == "S01E02"

    finished = _history(
        spider, item, "resource-1", 3,
        position=930000, duration=1000000, completed=True, updatedAt=300,
    )
    assert spider._reconcile_follow_histories([finished]) == 1
    current = spider._follow_memory["items"]["101"]
    assert current["history_completed"] is True
    assert current["seen_episode"] == "S01E03"


def test_rewatch_updates_current_resume_without_regressing_seen(spider):
    item = {
        "media_type": "tv",
        "tmdb_id": 101,
        "source_id": "tmdb:tv:101",
        "title": "测试剧集",
        "trackingSeason": 1,
        "latest_episode": "S01E12",
        "seen_episode": "S01E10",
        "tracked_episode": "S01E10",
        "history_episode": "S01E10",
        "history_position": 700000,
        "history_duration": 1200000,
        "history_source_updated_at_ms": 100,
        "history_playback": {
            "sourceKind": "spider_plugin",
            "sourceKey": "plugin-421",
            "vodId": "resource-1",
            "updatedAt": 100,
        },
    }
    spider._follow_memory = {"version": 2, "items": {"101": item}}
    replay = _history(
        spider, item, "resource-1", 3,
        position=180000, duration=1200000, completed=False, updatedAt=200,
    )

    assert spider._reconcile_follow_histories([replay]) == 1
    current = spider._follow_memory["items"]["101"]
    assert current["history_episode"] == "S01E03"
    assert current["history_position"] == 180000
    assert current["seen_episode"] == "S01E10"
    assert current["tracked_episode"] == "S01E10"


def test_drive_identity_change_clears_old_route_coordinates(spider):
    item = {
        "media_type": "tv",
        "tmdb_id": 101,
        "source_id": "tmdb:tv:101",
        "title": "测试剧集",
        "trackingSeason": 1,
        "history_episode": "S01E03",
        "history_position": 120000,
        "history_duration": 1200000,
        "history_source_updated_at_ms": 100,
        "history_playback": {
            "sourceKind": "spider_plugin",
            "sourceKey": "plugin-421",
            "vodId": "resource-1",
            "driveShareKey": "quark@share-id@",
            "drivePath": "/Show/old/E03.mp4",
            "updatedAt": 100,
        },
        "last_play_route": {"resourceId": "resource-1", "sourceGroupIndex": 1},
    }
    spider._follow_memory = {"version": 2, "items": {"101": item}}
    changed = _history(
        spider, item, "resource-1", 3,
        position=180000,
        updatedAt=200,
        driveShareKey="quark@share-id@",
        drivePath="/Show/new/E03.mp4",
    )

    assert spider._reconcile_follow_histories([changed]) == 1
    assert "last_play_route" not in spider._follow_memory["items"]["101"]


def test_tombstone_clears_resume_sidecar_without_regressing_durable_progress(spider):
    item = {
        "tmdb_id": 101,
        "title": "测试剧集",
        "seen_episode": "S01E10",
        "tracked_episode": "S01E10",
        "history_episode": "S01E03",
        "history_position": 180000,
        "history_duration": 1200000,
        "history_updated_at": 123,
        "history_source_updated_at_ms": 200,
        "history_playback": {
            "sourceKind": "spider_plugin",
            "sourceKey": "plugin-421",
            "vodId": "resource-1",
            "updatedAt": 200,
            "sourceGroupIndex": 1,
        },
        "last_play_route": {"resourceId": "resource-1"},
    }
    spider._follow_memory = {"version": 2, "items": {"101": item}}

    tombstone = {
        "scope": "item",
        "sourceKind": "spider_plugin",
        "sourceKey": "plugin-421",
        "vodId": "resource-1",
        "deletedAt": 201,
    }
    spider._v80_history_source_kinds = {("plugin-421", "resource-1"): "spider_plugin"}
    spider._v80_history_tombstones = [tombstone]
    changed = spider._reconcile_follow_histories([{
        "key": "plugin-421@@@resource-1@@@7",
        "vodName": "测试剧集",
        "position": 180000,
        "duration": 1200000,
        "createTime": 200,
    }])

    assert changed == 1
    current = spider._follow_memory["items"]["101"]
    assert current["seen_episode"] == "S01E10"
    assert current["tracked_episode"] == "S01E10"
    assert "history_episode" not in current
    assert "history_playback" not in current
    assert "last_play_route" not in current


def test_late_tombstone_keeps_newer_resume_sidecar(spider):
    item = {
        "tmdb_id": 101,
        "title": "测试剧集",
        "seen_episode": "S01E03",
        "history_episode": "S01E03",
        "history_position": 180000,
        "history_duration": 1200000,
        "history_source_updated_at_ms": 300,
        "history_playback": {
            "sourceKind": "spider_plugin",
            "sourceKey": "plugin-421",
            "vodId": "resource-1",
            "updatedAt": 300,
        },
    }
    spider._follow_memory = {"version": 2, "items": {"101": item}}

    changed = spider._reconcile_follow_tombstones([{
        "scope": "item",
        "sourceKind": "spider_plugin",
        "sourceKey": "plugin-421",
        "vodId": "resource-1",
        "deletedAt": 299,
    }])

    assert changed == 0
    assert spider._follow_memory["items"]["101"]["history_episode"] == "S01E03"


def test_follow_updates_sorts_globally_before_pagination(spider):
    spider.follow_page_size = 1
    spider._follow_memory = {"version": 2, "items": {
        "1": {
            "tmdb_id": 1, "title": "已追平", "latest_episode": "S01E01",
            "seen_episode": "S01E01", "tracked_episode": "S01E01",
        },
        "2": {
            "tmdb_id": 2, "title": "有更新", "latest_episode": "S01E05",
            "seen_episode": "S01E01", "tracked_episode": "S01E01",
        },
    }}
    spider._require_tmdb_credentials = Mock()
    spider._refresh_follow_page_async = Mock(return_value=False)
    spider._follow_history_snapshot = Mock(return_value=[])
    spider._history_alert_cards = Mock(return_value=[])
    spider._follow_state_cards = Mock(return_value=[])

    result = spider._category_follow_updates(1)

    assert result["list"][0]["vod_name"] == "有更新"
    spider._refresh_follow_page_async.assert_called_once()
    assert spider._refresh_follow_page_async.call_args.args[0][0]["tmdb_id"] == 2


def test_follow_card_uses_three_layer_summary_and_action_text(spider):
    item = {
        "tmdb_id": 101,
        "title": "测试剧集",
        "latest_episode": "S01E12",
        "seen_episode": "S01E10",
        "history_episode": "S01E11",
        "history_position": 1420000,
        "history_duration": 2400000,
        "history_completed": False,
    }

    remark = spider._follow_remark(item)

    assert remark.startswith("更新至 S01E12 · 已看 S01E10 · 正在看 S01E11 23:40")
    assert remark.endswith("继续观看 S01E11")


def test_playback_management_uses_plain_chinese_labels(spider):
    spider.atvp_api = "https://server"
    spider.atvp_token = "token"
    spider._atvp_session = object()
    spider._atvp_status_remark = Mock(return_value="")
    spider._history_share_policy_loaded = True
    cards = spider._history_management_cards()

    assert cards[0]["vod_name"] == "立即同步播放记录"
    assert all("History" not in card["vod_name"] for card in cards)
    assert any(card["vod_name"] == "快速同步播放记录" for card in cards)
    assert any("已开启" in card["vod_name"] for card in cards)


def test_resume_injection_keeps_bounded_navigation_sidecar(spider):
    item = {
        "media_type": "tv",
        "tmdb_id": 101,
        "source_id": "tmdb:tv:101",
        "title": "测试剧集",
    }
    history = _history(
        spider, item, "resource-1", 3,
        completed=False,
        clientKey="living-room",
        sourceGroupIndex=2,
        sourceIndex=1,
        driveShareKey="quark@share-id@",
        drivePath="/Show/S01/E03.mp4",
    )
    parsed = spider._parse_followplay(_followplay(spider, item, "resource-1", 3))
    spider._atvp_history_snapshot = Mock(return_value=[history])
    output = {}

    spider._inject_resume(output, parsed)

    assert output["position"] == 120000
    assert output["history_playback"]["sourceGroupIndex"] == 2
    assert output["history_playback"]["drivePath"] == "/Show/S01/E03.mp4"
    assert "url" not in output["history_playback"]


def test_sync_result_prioritizes_plain_language_summary():
    message = MODULE.Spider._history_sync_message({
        "mode": "双向",
        "local": 3,
        "cloud": 4,
        "upload_allowed": 1,
        "uploaded": 1,
        "imported": 2,
        "progress": 1,
        "errors": [],
    })

    assert message.startswith("同步完成 · 3 条播放记录更新 · 1 条追更进度更新")


def test_alist_resource_name_cleaning_removes_leading_marker_and_update_noise():
    value = MODULE.Spider._standardize_resource_name("C沧元图第二季（2024）系列更新中 31-55")

    assert value == "沧元图 第二季(2024)"


def test_reachable_route_preheat_persists_safe_long_lived_binding(spider):
    spider.atvp_api = "https://atvp.example"
    spider.atvp_token = "token"
    spider._atvp_session = Mock()
    spider._follow_memory = {"version": 2, "items": {"101": {
        "tmdb_id": 101,
        "source_id": "tmdb:tv:101",
        "title": "测试剧集",
    }}}
    spider._probe_route_candidate = Mock(return_value={
        "checked_at": 1,
        "reachable": True,
        "fingerprint": "range-v1:verified",
        "height": 1080,
        "codec": "h264",
        "startup_ms": 120,
        "output": {
            "parse": 0,
            "url": "https://signed.example/video.m3u8?token=secret",
            "header": {"Cookie": "secret"},
        },
    })
    spider._record_route_quality = Mock()

    def run_now(_kind, _generation, target, _name):
        target()
        return True

    spider._submit_background_bulkhead_task = Mock(side_effect=run_now)
    spider._schedule_route_preheat([{
        "episode_key": (1, 3),
        "resource_id": "resource-1",
        "payload": {
            "url": "1@episode-3",
            "resourceId": "resource-1",
            "resourceMode": "vod",
            "resourceProvider": "quark",
            "name": "第3集",
        },
    }], {
        "tmdb_id": 101,
        "source_id": "tmdb:tv:101",
        "history_episode": "S01E03",
    })

    route = spider._follow_memory["items"]["101"]["last_play_route"]
    assert route["resourceId"] == "resource-1"
    assert route["playId"] == "1@episode-3"
    assert route["season"] == 1
    assert route["episode"] == 3
    assert route["quality"]["height"] == 1080
    assert spider._follow_memory["items"]["101"]["alist_vod_id"] == "resource-1"
    serialized = json.dumps(route, ensure_ascii=False)
    assert "signed.example" not in serialized
    assert "secret" not in serialized


def test_cached_verified_route_is_persisted_without_second_probe(spider):
    spider.atvp_api = "https://atvp.example"
    spider.atvp_token = "token"
    spider._atvp_session = Mock()
    spider._follow_memory = {"version": 2, "items": {"101": {
        "tmdb_id": 101,
        "source_id": "tmdb:tv:101",
        "title": "测试剧集",
    }}}
    backend = spider._resource_capability_identity()
    probe_key = spider._route_probe_key(
        "1@episode-3", "resource-1", "vod", backend=backend,
    )
    spider._route_probe_cache[probe_key] = {
        "checked_at": MODULE.time.time(),
        "reachable": True,
        "fingerprint": "range-v1:cached",
        "height": 1080,
        "codec": "h265",
        "startup_ms": 80,
    }
    spider._submit_background_bulkhead_task = Mock(
        side_effect=AssertionError("已验证线路不应重复探测"),
    )
    spider._refresh_follow_categories = Mock()

    spider._schedule_route_preheat([{
        "episode_key": (1, 3),
        "name": "第3集",
        "resource_id": "resource-1",
        "payload": {
            "url": "1@episode-3",
            "resourceId": "resource-1",
            "resourceMode": "vod",
            "resourceProvider": "quark",
        },
    }], {
        "tmdb_id": 101,
        "source_id": "tmdb:tv:101",
        "history_episode": "S01E03",
    })

    route = spider._follow_memory["items"]["101"]["last_play_route"]
    assert route["playId"] == "1@episode-3"
    assert route["episode"] == 3
    spider._submit_background_bulkhead_task.assert_not_called()


def test_follow_candidate_and_resource_matching_use_cleaned_cangyuan_title(spider):
    merged = {}
    spider._merge_follow_candidate(
        merged,
        {"vodName": "C沧元图第二季（2024）系列更新中 31-55", "createTime": 1},
        "history",
    )

    assert list(merged.values())[0]["title"] == "沧元图"
    values = spider._resource_title_values({"vod_name": "C沧元图第二季"})
    assert "沧元图 第二季" in values


def test_follow_candidate_resolution_prefers_clean_title_and_accepts_unique_one_char_suffix(spider):
    spider._resolve_keep_follow_item = Mock(return_value=({"tmdb_id": 1}, ""))

    spider._resolve_follow_candidate({
        "title": "百花杀",
        "match_title": "【短剧】百花杀 更新至24集",
        "pic": "",
    })

    assert spider._resolve_keep_follow_item.call_args.args[0]["title"] == "百花杀"
    ranked = spider._rank_keep_candidates(
        [{"id": 272938, "name": "师兄太稳健", "original_name": "师兄太稳健"}],
        spider._normalize_media_title("师兄太稳健了"),
        0,
        True,
        False,
    )
    assert ranked[0][0] >= 90


def test_candidate_history_clear_executes_on_first_click(spider):
    spider._decode_follow_candidate = Mock(return_value={
        "title": "测试剧集",
        "history_keys": ["site@@@vod@@@1"],
    })
    spider._native_history_delete_java = Mock(return_value=1)
    spider._refresh_follow_categories = Mock()
    spider._alist_tvbox_plugin = False

    result = json.loads(spider._request_follow_candidate_clear("payload"))

    assert result["msg"].startswith("已清理播放记录：测试剧集")
    spider._native_history_delete_java.assert_called_once_with(["site@@@vod@@@1"])


def test_newer_local_history_is_not_overwritten_by_older_cloud_followplay(spider):
    item = {
        "media_type": "tv",
        "tmdb_id": 101,
        "source_id": "tmdb:tv:101",
        "title": "测试剧集",
    }
    cloud = _history(
        spider, item, "resource-1", 3,
        position=120000, duration=1200000, createTime=100, updatedAt=100,
    )
    local = {
        "key": cloud["key"],
        "vodName": "测试剧集",
        "vodRemarks": "S01E03",
        "episodeUrl": "S01E03$local-play-id",
        "position": 360000,
        "duration": 1200000,
        "createTime": 200,
        "uid": 1,
        "cid": 0,
    }

    merged, uploads = spider._merge_native_history([local], [cloud])

    assert merged[0]["position"] == 360000
    assert uploads[0]["position"] == 360000


def test_real_episode_list_never_emits_non_playable_select_placeholder(spider):
    item = {
        "media_type": "tv",
        "tmdb_id": 101,
        "source_id": "tmdb:tv:101",
        "title": "测试剧集",
        "trackingSeason": 1,
    }
    merged = spider._merge_resource_vods(
        [{
            "vod_play_from": "夸克网盘",
            "vod_play_url": "第1集$%s#第2集$%s" % (
                _followplay(spider, item, "resource-1", 1),
                _followplay(spider, item, "resource-1", 2),
            ),
            "resource_id": "resource-1",
            "_resource_mode": "vod",
            "group_seasons": [1],
            "group_providers": ["quark"],
            "group_quality": [{}],
        }],
        item,
        "tmdb:tv:101",
        {"vod_name": "测试剧集"},
        preferred_resource_id="resource-1",
    )

    assert merged is not None
    assert "选集播放$" not in merged["vod_play_url"]
    assert merged["vodFlags"][0]["episodes"][0]["url"].startswith("followplay_")


def test_persisted_success_route_restores_immediate_playable_entry(spider):
    item = {
        "media_type": "tv",
        "tmdb_id": 101,
        "source_id": "tmdb:tv:101",
        "title": "测试剧集",
        "last_play_route": {
            "backend": "",
            "resourceId": "resource-1",
            "resourceMode": "vod",
            "resourceProvider": "quark",
            "playId": "1@episode-3",
            "season": 1,
            "episode": 3,
            "name": "第3集",
        },
    }
    spider._schedule_entry_resource_preheat = Mock(return_value=True)

    restored = spider._remembered_route_detail(
        "tmdb:tv:101", item, {"vod_name": "测试剧集"},
    )

    assert restored is not None
    assert "上次成功线路" in restored["vod_play_from"]
    assert "followplay_" in restored["vod_play_url"]
    spider._schedule_entry_resource_preheat.assert_called_once()


@pytest.mark.parametrize("mode", ["view", "seen", "remove"])
def test_follow_manage_modes_always_show_preheat_progress(spider, mode):
    spider._follow_memory = {"version": 2, "items": {
        "101": {"tmdb_id": 101, "title": "测试剧集"},
    }}
    spider._atvp_history_snapshot = Mock(return_value=[])
    spider._reconcile_follow_histories = Mock()
    spider._follow_state_cards = Mock(return_value=[])
    spider._history_management_cards = Mock(return_value=[])
    spider._history_alert_cards = Mock(return_value=[])

    result = spider._category_follow_manage(1, {"mode": mode})
    preheat_cards = [
        card for card in result["list"]
        if card.get("action") == spider.FOLLOW_PREHEAT_ACTION
    ]

    assert len(preheat_cards) == 1
    assert preheat_cards[0]["vod_name"] == "主动预热追更线路"
    assert "可直接播放" in preheat_cards[0]["vod_remarks"]


def test_active_preheat_cascades_until_every_follow_item_is_processed(spider):
    items = [
        {
            "tmdb_id": tmdb_id,
            "source_id": "tmdb:tv:%d" % tmdb_id,
            "media_type": "tv",
            "title": "测试剧集%d" % tmdb_id,
        }
        for tmdb_id in range(101, 106)
    ]
    spider._follow_memory = {
        "version": 2,
        "items": {str(item["tmdb_id"]): dict(item) for item in items},
    }
    spider.RESOURCE_ENTRY_PREHEAT_LIMIT = 2
    spider._follow_route_binding_ready = Mock(return_value=False)
    spider._ready_resource_rows = Mock(return_value=[])
    spider._refresh_follow_categories = Mock()
    scheduled = []

    def schedule_one(batch, page=1):
        item = dict(batch[0])
        key = spider._entry_resource_preheat_key(item)
        spider._resource_entry_preheat_jobs[key] = object()
        scheduled.append(item)
        return True

    spider._schedule_entry_resource_preheat = Mock(side_effect=schedule_one)

    progress = spider._start_follow_preheat_all(items)

    assert progress["accepted"] is True
    assert [item["tmdb_id"] for item in scheduled] == [101, 102]
    index = 0
    while index < len(scheduled):
        item = scheduled[index]
        spider._resource_entry_preheat_jobs.pop(
            spider._entry_resource_preheat_key(item), None,
        )
        spider._complete_follow_preheat_resource(item, False)
        index += 1

    final = spider._follow_preheat_snapshot()
    assert [item["tmdb_id"] for item in scheduled] == [101, 102, 103, 104, 105]
    assert final["processed"] == 5
    assert final["running"] is False


def test_cancel_follow_stays_inside_management_menu_and_preheat_is_visible(spider):
    assert ("follow_remove", "取消追更") not in spider.CATEGORIES
    manage_actions = spider._base_filters()["follow_manage"][0]["value"]
    assert {"n": "取消追更（需确认）", "v": "remove"} in manage_actions
    spider._follow_memory = {"version": 2, "items": {
        "101": {"tmdb_id": 101, "title": "测试剧集"},
    }}
    spider._alist_tvbox_plugin = True
    spider.atvp_api = "https://atvp.example"
    spider.atvp_token = "token"
    spider._atvp_session = object()
    spider._start_follow_preheat_all = Mock(return_value={
        "accepted": True,
        "running": True,
    })
    spider._refresh_follow_categories = Mock()

    card = spider._follow_preheat_card()
    result = json.loads(spider._start_follow_preheat())

    assert card["vod_name"] == "主动预热追更线路"
    assert card["action"] == spider.FOLLOW_PREHEAT_ACTION
    assert "主动预热已开始" in result["msg"]


def test_failed_candidate_confirmation_stops_refresh_retry_loop(spider):
    candidate = {"title": "网络失败剧集", "match_title": "网络失败剧集"}
    spider._follow_action_state = {
        "version": 1,
        "pending": {},
        "last": {
            "state": "failed",
            "message": "确认追更失败：HTTPSConnectionPool",
            "operation": "candidate",
            "title": candidate["title"],
            "updated_at": int(MODULE.time.time()),
        },
    }
    spider._tasks.start_thread = Mock(side_effect=AssertionError("失败冷却期间不应重启网络任务"))
    spider._refresh_follow_categories = Mock()

    result = json.loads(spider._start_follow_candidate_add(
        spider._encode_follow_candidate(candidate)
    ))

    assert "已停止自动重试" in result["msg"]
    spider._tasks.start_thread.assert_not_called()
    spider._refresh_follow_categories.assert_not_called()


def test_failed_candidate_card_does_not_replay_action_on_category_refresh(spider):
    candidate = {"title": "网络失败剧集", "match_title": "网络失败剧集"}
    spider._follow_action_state = {
        "version": 1,
        "pending": {},
        "last": {
            "state": "failed",
            "message": "确认追更失败：HTTPSConnectionPool",
            "operation": "candidate",
            "title": candidate["title"],
            "updated_at": int(MODULE.time.time()),
        },
    }

    card = spider._follow_candidate_card(candidate)

    assert "action" not in card
    assert card["vod_id"].startswith(spider.ERROR_PREFIX)
    assert "清除后可重试" in card["vod_remarks"]


def test_follow_confirmation_uses_atvp_tmdb_once_after_client_https_failure(spider):
    spider._tmdb_api = Mock(side_effect=MODULE.requests.exceptions.SSLError("tls failed"))
    spider._atvp_tmdb_follow_match = Mock(return_value=({
        "id": 272938,
        "name": "师兄太稳健",
        "_media_type": "tv",
        "_atvp_fallback": True,
        "_atvp_detail": {
            "id": 272938,
            "name": "师兄太稳健",
            "poster_path": "https://image.example/poster.jpg",
            "first_air_date": "2026",
        },
    }, ""))

    item, reason = spider._resolve_keep_follow_item({"title": "师兄太稳健了"})

    assert reason == ""
    assert item["tmdb_id"] == 272938
    assert item["title"] == "师兄太稳健"
    assert item["pending_metadata"] is True
    assert item["pic"] == "https://image.example/poster.jpg"
    spider._atvp_tmdb_follow_match.assert_called_once()


@pytest.mark.parametrize("media_type,episode_count,expected_reason", [
    ("movie", None, "movie_conflict"),
    ("tv", 1, "single_episode"),
])
def test_follow_confirmation_rejects_movie_and_known_single_episode(
        spider, media_type, episode_count, expected_reason):
    spider._match_keep_to_tmdb = Mock(return_value=({
        "id": 101,
        "name": "单集项目",
        "_media_type": media_type,
    }, ""))
    detail = {
        "id": 101,
        "name": "单集项目",
        "first_air_date": "2026-01-01",
        "number_of_seasons": 1,
    }
    if episode_count is not None:
        detail["number_of_episodes"] = episode_count
    spider._tmdb_api = Mock(return_value=detail)

    item, reason = spider._resolve_keep_follow_item({"title": "单集项目"})

    assert item is None
    assert reason == expected_reason


def test_follow_confirmation_allows_multi_episode_variety(spider):
    spider._match_keep_to_tmdb = Mock(return_value=({
        "id": 202,
        "name": "多期综艺",
        "_media_type": "tv",
    }, ""))
    spider._tmdb_api = Mock(return_value={
        "id": 202,
        "name": "多期综艺",
        "first_air_date": "2026-01-01",
        "number_of_seasons": 1,
        "number_of_episodes": 12,
        "genres": [{"id": 10764, "name": "真人秀"}],
    })
    spider._attach_douban_to_tmdb_item = Mock(side_effect=lambda item, _detail: item)

    item, reason = spider._resolve_keep_follow_item({"title": "多期综艺"})

    assert reason == ""
    assert item["tmdb_id"] == 202
    assert item["pending_metadata"] is False


def test_atvp_tmdb_fallback_reuses_safe_cached_metadata(spider):
    spider._alist_tvbox_plugin = True
    spider.atvp_api = "https://atvp.example"
    spider._history_selected_origin = spider.atvp_api
    spider._ensure_atvp_connection = Mock(return_value=True)
    spider._atvp_history_login = Mock(return_value=True)
    response = Mock(status_code=200)
    response.close = Mock()
    spider._atvp_session = Mock()
    spider._atvp_session.get.side_effect = [response, response]
    spider._atvp_session.post.return_value = response
    stable_path = "/__v80_follow_cache__/" + MODULE.hashlib.sha256(
        "师兄太稳健了|".encode("utf-8")
    ).hexdigest()[:24]
    spider._read_bounded_json_response = Mock(side_effect=[
        {"content": []},
        {
            "vod_name": "师兄太稳健",
            "vod_pic": "https://image.example/poster.jpg",
            "vod_year": "2026",
        },
        {"content": [{
            "path": stable_path,
            "tmId": 272938,
            "type": "tv",
            "name": "师兄太稳健",
            "year": 2026,
        }]},
    ])

    first, reason = spider._atvp_tmdb_follow_match({"title": "师兄太稳健了"})
    second, second_reason = spider._atvp_tmdb_follow_match({"title": "师兄太稳健了"})

    assert reason == second_reason == ""
    assert first["id"] == second["id"] == 272938
    assert spider._atvp_session.get.call_count == 2
    assert spider._atvp_session.post.call_count == 1


def test_tmdb_detail_cache_avoids_duplicate_client_request(spider):
    spider._request_tmdb = Mock(return_value={
        "id": 303,
        "name": "缓存剧集",
        "number_of_seasons": 1,
        "number_of_episodes": 8,
    })

    first = spider._tmdb_api("/tv/303", {}, spider.detail_cache_ttl)
    second = spider._tmdb_api("/tv/303", {}, spider.detail_cache_ttl)

    assert first == second
    spider._request_tmdb.assert_called_once()


def test_fast_sync_action_publishes_immediate_status(spider):
    spider._ensure_atvp_connection = Mock(return_value=True)
    spider._schedule_atvp_history_refresh = Mock(return_value=True)
    spider._refresh_follow_categories = Mock()

    result = json.loads(spider._start_atvp_job("quick"))

    assert "快速播放进度同步已开始" in result["msg"]
    assert spider._atvp_status["quick"]["state"] == "running"
    spider._schedule_atvp_history_refresh.assert_called_once_with(
        "atvp-history-snapshot", lightweight=True, status_kind="quick",
    )
    spider._refresh_follow_categories.assert_called()


def test_resume_route_hides_redundant_select_prompt(spider):
    item = {
        "media_type": "tv",
        "tmdb_id": 101,
        "source_id": "tmdb:tv:101",
        "title": "测试剧集",
        "trackingSeason": 1,
        "history_episode": "S01E01",
        "_resume_verified": True,
        "alist_vod_id": "resource-1",
    }
    play_id = spider._build_followplay(
        "1@episode-1", item, "resource-1", 1, 1, "第1集",
        resource_mode="vod", resource_provider="alist",
    )
    merged = spider._merge_resource_vods(
        [{
            "vod_play_from": "夸克网盘",
            "vod_play_url": "第1集$%s#第2集$%s" % (
                play_id,
                spider._build_followplay(
                    "1@episode-2", item, "resource-1", 1, 2, "第2集",
                    resource_mode="vod", resource_provider="alist",
                ),
            ),
            "resource_id": "resource-1",
            "_resource_mode": "vod",
            "group_seasons": [1],
            "group_providers": ["quark"],
            "group_quality": [{}],
        }],
        item,
        "tmdb:tv:101",
        {"vod_name": "测试剧集"},
        preferred_resource_id="resource-1",
    )

    assert merged is not None
    assert all("选集播放$" not in url for url in merged["vod_play_url"].split("$$$"))


def test_v89_tmdb_empty_accepts_explicit_multi_episode_variety(spider):
    spider._tmdb_api = Mock(return_value={"results": []})

    item, reason = spider._resolve_keep_follow_item({
        "title": "新综艺",
        "match_title": "新综艺 更新至12期",
        "history_remark": "第12期",
        "year": "2026",
        "pic": "poster.jpg",
    })

    assert reason == ""
    assert item["tmdb_id"] == 0
    assert item["source_id"].startswith("local:tv:")
    assert item["media_type"] == "tv"
    assert item["latest_episode"] == "S01E12"
    assert item["pending_metadata"] is True
    assert item["metadata_source"] == "local_series"


@pytest.mark.parametrize("candidate,expected_reason", [
    ({"title": "未收录电影", "match_title": "未收录电影 2026"}, "movie_conflict"),
    ({"title": "独立视频.mp4", "match_title": "独立视频.mp4"}, "single_episode"),
    ({"title": "只有标题的新内容", "match_title": "只有标题的新内容"}, "no_confident_tv"),
])
def test_v89_local_identity_still_rejects_movie_single_and_unproven_content(
        spider, candidate, expected_reason):
    spider._tmdb_api = Mock(return_value={"results": []})

    item, reason = spider._resolve_keep_follow_item(candidate)

    assert item is None
    assert reason == expected_reason


def test_v89_local_identity_persists_and_opens_resource_detail(spider):
    item, reason = spider._local_follow_item({
        "title": "师兄太稳健了",
        "match_title": "师兄太稳健了 S01E01",
        "history_remark": "第1集",
        "year": "2026",
    })
    assert reason == ""
    key = spider._follow_item_key(item)
    spider._follow_memory = {"version": 2, "items": {key: dict(item)}}
    spider._refresh_follow_page_async = Mock(return_value=True)
    spider._alist_detail_from_metadata = Mock(return_value={
        "list": [{"vod_id": key, "vod_name": item["title"]}],
    })

    spider._save_follow_state({key: item})
    result = spider.detailContent([key])

    stored = spider._follow_memory["items"][key]
    assert stored["source_id"] == key
    assert stored["metadata_source"] == "local_series"
    assert result["list"][0]["vod_id"] == key
    metadata = spider._alist_detail_from_metadata.call_args.args[1]["list"][0]
    assert "TMDB尚未收录" in metadata["vod_content"]


def test_v89_local_follow_can_be_cancelled_inside_management(spider):
    item, _reason = spider._local_follow_item({
        "title": "待取消新剧",
        "match_title": "待取消新剧 更新至2集",
    })
    key = spider._follow_item_key(item)
    spider._follow_memory = {"version": 2, "items": {key: dict(item)}}
    spider._refresh_follow_categories = Mock()

    requested = json.loads(spider._request_follow_confirmation("remove", key))
    pending = spider._follow_action_state["pending"]
    payload = "%s:remove:%s" % (pending["nonce"], key)
    executed = json.loads(spider._execute_follow_confirmation(payload))

    assert "待确认取消追更" in requested["msg"]
    assert executed["msg"] == "已取消追更：待取消新剧"
    assert key not in spider._follow_memory["items"]


def test_v89_local_identity_migrates_to_tmdb_without_losing_newer_progress(spider):
    local, _reason = spider._local_follow_item({
        "title": "后补录新剧",
        "match_title": "后补录新剧 更新至3集",
        "year": "2026",
    })
    local.update({
        "history_episode": "S01E03",
        "history_position": 360000,
        "history_duration": 1200000,
        "history_source_updated_at_ms": 300,
        "alist_vod_id": "resource-local",
        "alist_resource_mode": "vod",
        "last_play_route": {
            "resourceId": "resource-local",
            "resourceMode": "vod",
            "playId": "1@episode-3",
            "season": 1,
            "episode": 3,
        },
    })
    local_source_id = local["source_id"]
    spider._match_keep_to_tmdb = Mock(return_value=({
        "id": 909,
        "name": "后补录新剧",
        "_media_type": "tv",
    }, ""))
    spider._tmdb_api = Mock(return_value={
        "id": 909,
        "name": "后补录新剧",
        "first_air_date": "2026-08-20",
        "number_of_seasons": 1,
        "number_of_episodes": 12,
        "last_episode_to_air": {
            "season_number": 1,
            "episode_number": 4,
            "air_date": "2026-08-20",
        },
    })

    migrated = spider._refresh_follow_item(local)

    assert spider._follow_item_key(migrated) == "909"
    assert migrated["source_id"] == "tmdb:tv:909"
    assert migrated["local_source_id"] == local_source_id
    assert local_source_id in migrated["source_aliases"]
    assert migrated["history_episode"] == "S01E03"
    assert migrated["history_position"] == 360000
    assert migrated["alist_vod_id"] == "resource-local"
    assert migrated["last_play_route"]["playId"] == "1@episode-3"


def test_v89_migrated_item_matches_history_written_with_local_source_identity(spider):
    local, _reason = spider._local_follow_item({
        "title": "身份迁移剧",
        "match_title": "身份迁移剧 S01E02",
    })
    history = _history(spider, local, "resource-local", 2)
    migrated = dict(local)
    migrated.update({
        "tmdb_id": 808,
        "source_id": "tmdb:tv:808",
        "local_source_id": local["source_id"],
        "source_aliases": [local["source_id"], "tmdb:tv:808"],
    })

    matched = spider._atvp_history_for_item(migrated, [history])

    assert matched is not None
    assert matched["position"] == history["position"]


def test_v89_candidate_click_preserves_episode_evidence_and_persists_local_identity(spider):
    candidate = {
        "title": "点击确认新剧",
        "match_title": "点击确认新剧",
        "history_remark": "更新至4集",
        "year": "2026",
        "history_keys": ["site@@@vod@@@1"],
    }
    encoded = spider._encode_follow_candidate(candidate)
    decoded = spider._decode_follow_candidate(encoded)
    spider._tmdb_api = Mock(return_value={"results": []})
    spider._refresh_follow_categories = Mock()
    spider._tasks.start_thread = Mock(side_effect=lambda worker, name=None: worker())

    result = json.loads(spider._start_follow_candidate_add(encoded))

    assert decoded["history_remark"] == "更新至4集"
    assert "已开始确认追更" in result["msg"]
    assert len(spider._follow_memory["items"]) == 1
    key, item = next(iter(spider._follow_memory["items"].items()))
    assert key.startswith("local:tv:")
    assert item["latest_episode"] == "S01E04"
    assert item["history_keys"] == ["site@@@vod@@@1"]
    assert spider._follow_action_state["last"]["state"] == "done"


def test_v89_background_refresh_rekeys_local_identity_to_tmdb(spider):
    local, _reason = spider._local_follow_item({
        "title": "自动迁移剧",
        "match_title": "自动迁移剧 更新至2集",
    })
    old_key = spider._follow_item_key(local)
    local["last_checked"] = 0
    migrated = dict(local)
    migrated.update({
        "tmdb_id": 707,
        "source_id": "tmdb:tv:707",
        "local_source_id": old_key,
        "source_aliases": [old_key, "tmdb:tv:707"],
        "pending_metadata": False,
        "last_checked": 100,
    })
    spider._follow_memory = {"version": 2, "items": {old_key: dict(local)}}
    spider._refresh_follow_item = Mock(return_value=migrated)
    spider._refresh_follow_categories = Mock()
    spider._tasks.start_thread = Mock(side_effect=lambda worker, name=None: worker())

    accepted = spider._refresh_follow_page_async([local])

    assert accepted is True
    assert old_key not in spider._follow_memory["items"]
    assert spider._follow_memory["items"]["707"]["local_source_id"] == old_key
    assert spider._follow_memory["items"]["707"]["latest_episode"] == "S01E02"


def test_v90_fast_client_tmdb_wins_without_server_and_identity_cache_prevents_dual_query(spider):
    calls = []

    def tmdb_api(path, _params=None, _ttl=None, allow_stale=True):
        calls.append(path)
        assert allow_stale is True
        if path == "/search/tv":
            return {"results": [{
                "id": 901,
                "name": "快速新剧",
                "original_name": "快速新剧",
                "first_air_date": "2026-08-20",
            }]}
        raise AssertionError("显式多集证据不应等待电影搜索")

    spider._tmdb_api = Mock(side_effect=tmdb_api)
    spider._tmdb_server_follow_match = Mock(return_value=({
        "id": 902, "name": "服务端候选", "_media_type": "tv",
    }, ""))
    spider.TMDB_HEDGE_DELAY_SECONDS = 0.05
    keep = {
        "title": "快速新剧",
        "match_title": "快速新剧 更新至2集",
        "history_remark": "第2集",
        "year": "2026",
    }

    first, first_reason = spider._match_keep_to_tmdb(keep)
    second, second_reason = spider._match_keep_to_tmdb(keep)

    assert first_reason == second_reason == ""
    assert first["id"] == second["id"] == 901
    assert calls == ["/search/tv"]
    spider._tmdb_server_follow_match.assert_not_called()


def test_v90_slow_client_starts_server_after_hedge_delay_for_explicit_series(spider):
    def tmdb_api(path, _params=None, _ttl=None, allow_stale=True):
        assert path == "/search/tv"
        assert allow_stale is True
        time.sleep(0.08)
        return {"results": [{
            "id": 910,
            "name": "慢响应剧",
            "original_name": "慢响应剧",
            "first_air_date": "2026-08-20",
        }]}

    spider._tmdb_api = Mock(side_effect=tmdb_api)
    spider._tmdb_server_follow_match = Mock(return_value=({
        "id": 911,
        "name": "慢响应剧",
        "first_air_date": "2026",
        "_media_type": "tv",
        "_atvp_fallback": True,
    }, ""))
    spider.TMDB_HEDGE_DELAY_SECONDS = 0.01

    match, reason = spider._match_keep_to_tmdb({
        "title": "慢响应剧",
        "match_title": "慢响应剧 S01E02",
        "year": "2026",
    })

    assert reason == ""
    assert match["id"] == 911
    spider._tmdb_server_follow_match.assert_called_once()


def test_v90_empty_client_result_queries_server_before_local_identity(spider):
    paths = []

    def tmdb_api(path, _params=None, _ttl=None, allow_stale=True):
        paths.append(path)
        assert allow_stale is True
        return {"results": []}

    spider._tmdb_api = Mock(side_effect=tmdb_api)
    spider._tmdb_server_follow_match = Mock(return_value=({
        "id": 920,
        "name": "服务端独有剧",
        "first_air_date": "2026",
        "_media_type": "tv",
        "_atvp_fallback": True,
    }, ""))

    match, reason = spider._match_keep_to_tmdb({
        "title": "服务端独有剧",
        "year": "2026",
    })

    assert reason == ""
    assert match["id"] == 920
    assert paths == ["/search/tv", "/search/movie"]
    spider._tmdb_server_follow_match.assert_called_once()


def test_v90_unclear_content_waits_for_client_movie_conflict_before_accepting_server(spider):
    def tmdb_api(path, _params=None, _ttl=None, allow_stale=True):
        assert allow_stale is True
        if path == "/search/tv":
            time.sleep(0.05)
            return {"results": [{
                "id": 930,
                "name": "同名内容",
                "original_name": "同名内容",
                "first_air_date": "2026-08-20",
            }]}
        return {"results": [{
            "id": 931,
            "title": "同名内容",
            "original_title": "同名内容",
            "release_date": "2026-08-20",
        }]}

    spider._tmdb_api = Mock(side_effect=tmdb_api)
    spider._tmdb_server_follow_match = Mock(return_value=({
        "id": 932,
        "name": "同名内容",
        "first_air_date": "2026",
        "_media_type": "tv",
        "_atvp_fallback": True,
    }, ""))
    spider.TMDB_HEDGE_DELAY_SECONDS = 0.01

    match, reason = spider._match_keep_to_tmdb({
        "title": "同名内容",
        "year": "2026",
    })

    assert match is None
    assert reason == "movie_conflict"
    spider._tmdb_server_follow_match.assert_called_once()


def test_v90_repeated_channel_failures_trigger_short_degrade_and_health_snapshot(spider):
    for latency in (20, 30, 40):
        spider._tmdb_hedge_record(
            "client", False, latency, error=RuntimeError("受控失败"),
        )
    snapshot = spider._tmdb_hedge_snapshot()
    assert snapshot["client"] == {
        "samples": 3,
        "success_rate": 0.0,
        "average_latency_ms": 30,
        "consecutive_failures": 3,
        "degraded": True,
    }

    spider._tmdb_client_follow_match = Mock(return_value=({
        "id": 940, "name": "不应调用", "_media_type": "tv",
    }, ""))
    spider._tmdb_server_follow_match = Mock(return_value=({
        "id": 941,
        "name": "降级接管剧",
        "_media_type": "tv",
        "_atvp_fallback": True,
    }, ""))

    match, reason = spider._match_keep_to_tmdb({
        "title": "降级接管剧",
    })

    assert reason == ""
    assert match["id"] == 941
    spider._tmdb_client_follow_match.assert_not_called()
    spider._tmdb_server_follow_match.assert_called_once()


def test_v90_client_transport_failure_allows_server_takeover_without_episode_hint(spider):
    spider._tmdb_client_follow_match = Mock(side_effect=TimeoutError("受控超时"))
    spider._tmdb_server_follow_match = Mock(return_value=({
        "id": 942,
        "name": "服务端接管剧",
        "_media_type": "tv",
        "_atvp_fallback": True,
    }, ""))
    spider.TMDB_HEDGE_DELAY_SECONDS = 0.01

    match, reason = spider._match_keep_to_tmdb({"title": "服务端接管剧"})

    assert reason == ""
    assert match["id"] == 942
    spider._tmdb_client_follow_match.assert_called_once()
    spider._tmdb_server_follow_match.assert_called_once()

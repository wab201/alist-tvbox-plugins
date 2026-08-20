# -*- coding: utf-8 -*-

import base64
import importlib.util
import json
import sys
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
    spec = importlib.util.spec_from_file_location("douban_tmdb_follow_v87_candidate", SOURCE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MODULE = _load_module()


def _ext(plugin_id, origin="https://atvp.example"):
    payload = {
        "source": "%s/plugins/runtime/%s.txt" % (origin, plugin_id),
        "data": "{}",
    }
    return base64.b64encode(
        json.dumps(payload, ensure_ascii=False).encode("utf-8")
    ).decode("ascii")


@pytest.fixture
def spider():
    value = MODULE.Spider()
    value._follow_state_loaded = True
    value._persist_follow_state = Mock(return_value=True)
    try:
        yield value
    finally:
        value.destroy()


def test_active_subscription_selects_only_searchable_exact_allowlist_plugins():
    config = {
        "sites": [
            {"name": "豆瓣TMDB追更助手", "searchable": 1, "ext": _ext(421)},
            {"name": "欧歌[盘]", "searchable": 0, "ext": _ext(230)},
            {"name": "欧歌[盘]", "searchable": 1, "ext": _ext(230)},
            {"name": "木偶[盘]", "searchable": 1, "ext": _ext(243)},
            {"name": "木偶[盘]复制", "searchable": 1, "ext": _ext(243)},
            {"name": "外部同名", "searchable": 1, "ext": _ext(230, "https://other.example")},
        ]
    }

    selected = MODULE.Spider._atvp_plugin_sites_from_subscription(
        config, "https://atvp.example",
    )

    assert [(row["plugin_id"], row["name"]) for row in selected] == [
        (230, "欧歌[盘]"),
        (243, "木偶[盘]"),
    ]


def test_plugin_resource_id_rejects_urls_and_round_trips_only_opaque_ids():
    assert MODULE.Spider._atvp_plugin_encode_resource_id(
        230, "https://quark.cn/s/secret",
    ) == ""

    encoded = MODULE.Spider._atvp_plugin_encode_resource_id(230, "atvp_detail:opaque-1")

    assert encoded.startswith("atvp-plugin-resource:")
    assert "http" not in encoded
    assert MODULE.Spider._atvp_plugin_decode_resource_id(encoded) == {
        "plugin_id": 230,
        "raw_id": "atvp_detail:opaque-1",
    }


def test_one_plugin_failure_does_not_block_other_candidate_source(spider):
    spider._atvp_plugin_sites = [
        {"plugin_id": 230, "name": "欧歌[盘]", "ext": "a"},
        {"plugin_id": 243, "name": "木偶[盘]", "ext": "b"},
    ]
    good_id = spider._atvp_plugin_encode_resource_id(243, "opaque-good")

    def search(site, _queries, deadline=None):
        if site["plugin_id"] == 230:
            raise RuntimeError("source failed")
        return [{
            "vod_id": good_id,
            "vod_name": "沧元图",
            "source": "木偶[盘]",
            "_resource_mode": "plugin",
        }]

    spider._atvp_plugin_search_site = search
    spider._resource_binding_resource_id = Mock(return_value="")

    rows = spider._atvp_plugin_candidates(
        {"title": "沧元图", "media_type": "tv", "latest_episode": "S01E01"},
        deadline=time.monotonic() + 2,
        expected_generation=spider._cache_generation,
    )

    assert [row["vod_id"] for row in rows] == [good_id]


def test_plugin_detail_rewrites_raw_play_ids_and_group_urls_to_safe_handles(spider):
    encoded = spider._atvp_plugin_encode_resource_id(230, "opaque-detail")

    class Wrapper(object):
        DETAIL_PREFIX = "atvp_detail:"

        @staticmethod
        def _category_mode_enabled():
            return False

        @staticmethod
        def detailContent(_ids):
            return {
                "list": [{
                    "vod_name": "沧元图",
                    "vod_play_from": "插件直连",
                    "vod_play_url": "第1集$opaque-play-id",
                    "group": [{
                        "name": "夸克资源",
                        "media": [{"name": "第2集", "url": "https://quark.cn/s/secret"}],
                    }],
                }]
            }

    spider._atvp_plugin_sites = [
        {"plugin_id": 230, "name": "欧歌[盘]", "ext": "unused"},
    ]
    spider._atvp_plugin_wrappers[230] = Wrapper()
    spider._atvp_plugin_call_locks[230] = MODULE.threading.Lock()

    detail = spider._atvp_plugin_detail(encoded, deadline=time.monotonic() + 2)
    serialized = json.dumps(detail, ensure_ascii=False)
    vod = detail["list"][0]
    handles = [
        part.rpartition("$")[2]
        for group in vod["vod_play_url"].split("$$$")
        for part in group.split("#")
    ]

    assert "opaque-play-id" not in serialized
    assert "https://quark.cn/s/secret" not in serialized
    assert len(handles) == 2
    assert all(handle.count("-") == 1 and handle.replace("-", "").isdigit() for handle in handles)
    assert spider._atvp_plugin_play_context(handles[0])["kind"] == "plugin"
    assert spider._atvp_plugin_play_context(handles[1])["kind"] == "alist"


def test_plugin_route_persists_only_safe_handle_and_rehydrates_from_bound_resource(spider):
    resource_id = spider._atvp_plugin_encode_resource_id(230, "opaque-detail")
    handle = spider._atvp_plugin_play_handle(
        230, "opaque-detail", "插件直连", "signed-or-opaque-play-id", "plugin",
    )
    item = {
        "tmdb_id": 101,
        "source_id": "tmdb:tv:101",
        "title": "沧元图",
        "alist_vod_id": resource_id,
        "alist_resource_mode": "plugin",
        "last_play_route": {
            "resourceId": resource_id,
            "resourceMode": "plugin",
            "playId": handle,
            "season": 1,
            "episode": 1,
        },
    }

    sanitized = spider._sanitize_follow_persisted_item(item)

    assert sanitized["last_play_route"]["playId"] == handle
    assert "signed-or-opaque-play-id" not in json.dumps(sanitized, ensure_ascii=False)
    spider._atvp_plugin_play_handles.clear()
    assert spider._remembered_route_detail("tmdb:tv:101", item, {}) is None
    assert spider._bound_resource_row(item) == {
        "vod_id": resource_id,
        "vod_name": "沧元图",
        "_resource_mode": "plugin",
        "_bound_route": True,
    }


def test_plugin_preheat_candidate_must_pass_playable_validation_before_binding(spider):
    item = {
        "tmdb_id": 101,
        "source_id": "tmdb:tv:101",
        "media_type": "tv",
        "title": "沧元图",
        "latest_episode": "S01E01",
    }
    plugin_id = spider._atvp_plugin_encode_resource_id(230, "opaque-bound")
    plugin_row = {
        "vod_id": plugin_id,
        "vod_name": "沧元图",
        "_resource_mode": "plugin",
        "_validated_groups": 1,
    }
    spider._alist_tvbox_plugin = True
    spider.route_preheat = True
    spider.atvp_api = "https://atvp.example"
    spider.atvp_token = "token"
    spider._atvp_session = object()
    spider.resource_limit = 1
    spider._follow_memory = {"items": {"101": dict(item)}}
    spider._ready_resource_rows = Mock(return_value=[])
    spider._resource_candidates = Mock(return_value=[])
    spider._atvp_plugin_candidates = Mock(return_value=[plugin_row])
    spider._checked_resource_rows = Mock(side_effect=lambda rows, _deadline=None: list(rows))

    def playable(rows, _item, _deadline=None, expected_generation=None, on_update=None):
        result = list(rows) if rows and rows[0].get("_resource_mode") == "plugin" else []
        if result and callable(on_update):
            on_update(result)
        return result

    spider._playable_resource_rows = Mock(side_effect=playable)
    spider._resource_output_candidate_order = Mock(
        side_effect=lambda rows, *_args, **_kwargs: list(rows),
    )
    spider._target_covering_resource_row = Mock(
        side_effect=lambda rows, _item: rows[0] if rows else None,
    )
    spider._cache_ready_resource_rows = Mock(return_value=True)
    spider._replace_bound_resource = Mock(return_value=True)
    spider._schedule_active_detail_refresh = Mock()
    spider._complete_follow_preheat_resource = Mock()
    spider._refresh_follow_categories = Mock()

    def run_now(_lane, _generation, worker, _name, executor=None):
        worker()
        return True

    spider._submit_background_bulkhead_task = Mock(side_effect=run_now)

    assert spider._schedule_entry_resource_preheat([item]) is True
    spider._atvp_plugin_candidates.assert_called_once()
    spider._replace_bound_resource.assert_called_once()
    bound_row = spider._replace_bound_resource.call_args.args[1]
    assert bound_row["vod_id"] == plugin_id


def test_unvalidated_plugin_candidate_is_not_persisted(spider):
    item = {
        "tmdb_id": 101,
        "source_id": "tmdb:tv:101",
        "media_type": "tv",
        "title": "沧元图",
        "latest_episode": "S01E01",
    }
    plugin_id = spider._atvp_plugin_encode_resource_id(230, "opaque-unverified")
    plugin_row = {
        "vod_id": plugin_id,
        "vod_name": "沧元图",
        "_resource_mode": "plugin",
    }
    spider._alist_tvbox_plugin = True
    spider.route_preheat = True
    spider.atvp_api = "https://atvp.example"
    spider.atvp_token = "token"
    spider._atvp_session = object()
    spider._follow_memory = {"items": {"101": dict(item)}}
    spider._ready_resource_rows = Mock(return_value=[])
    spider._resource_candidates = Mock(return_value=[])
    spider._atvp_plugin_candidates = Mock(return_value=[plugin_row])
    spider._checked_resource_rows = Mock(side_effect=lambda rows, _deadline=None: list(rows))
    spider._playable_resource_rows = Mock(return_value=[])
    spider._replace_bound_resource = Mock(return_value=True)
    spider._complete_follow_preheat_resource = Mock()
    spider._refresh_follow_categories = Mock()
    spider._submit_background_bulkhead_task = Mock(
        side_effect=lambda _lane, _generation, worker, _name, executor=None: (worker(), True)[1],
    )

    assert spider._schedule_entry_resource_preheat([item]) is True
    spider._replace_bound_resource.assert_not_called()

# -*- coding: utf-8 -*-

import importlib.util
import json
import re
import sys
import time
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


base_module = types.ModuleType("base")
spider_module = types.ModuleType("base.spider")


class BaseSpider(object):
    pass


spider_module.Spider = BaseSpider
sys.modules.setdefault("base", base_module)
sys.modules.setdefault("base.spider", spider_module)

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "py" / "豆瓣TMDB追更单入口.py"
SPEC = importlib.util.spec_from_file_location("douban_tmdb_follow_v51", str(SOURCE))
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
Spider = MODULE.Spider


class FollowOperationV51Test(unittest.TestCase):
    def setUp(self):
        self.spider = Spider()
        self.spider.tmdb_api_key = "test-key"
        self.spider._follow_state_loaded = True
        self.spider._persist_follow_state = Mock(return_value=True)

    def tearDown(self):
        self.spider.destroy()

    def test_plugin_metadata_is_parseable_by_alist_tvbox(self):
        source = SOURCE.read_text(encoding="utf-8")
        expected = {
            "name": "豆瓣TMDB追更助手（AList-TVBox专用）",
            "id": "douban_tmdb_follow_single",
            "version": "52",
        }
        for field, value in expected.items():
            match = re.search(r"(?m)^\s*//@%s:(.+?)\s*$" % field, source)
            self.assertIsNotNone(match, field)
            self.assertEqual(match.group(1), value)

    def _wait_follow_jobs(self, timeout=2):
        deadline = time.time() + timeout
        while self.spider._follow_enrich_jobs and time.time() < deadline:
            time.sleep(0.01)
        self.assertFalse(self.spider._follow_enrich_jobs)

    def test_home_exposes_confirmation_between_updates_and_management(self):
        result = self.spider.homeContent(True)
        ids = [row["type_id"] for row in result["class"]]
        self.assertEqual(ids[:3], ["follow_updates", "follow_candidates", "follow_manage"])
        self.assertIn("follow_candidates", result["filters"])

    def test_history_share_policy_defaults_to_both_categories_enabled(self):
        self.spider._history_share_policy = {"follow": False, "watch": False}
        self.spider.getCache = Mock(return_value=None)

        policy = self.spider._load_history_share_policy()

        self.assertEqual(policy, {"follow": True, "watch": True})
        self.assertEqual(self.spider._history_share_policy, policy)

    def test_history_share_policy_cache_read_failure_preserves_disabled_state(self):
        self.spider._history_share_policy = {"follow": False, "watch": False}
        self.spider._history_share_policy_loaded = True
        self.spider.getCache = Mock(side_effect=RuntimeError("cache unavailable"))

        policy = self.spider._load_history_share_policy()

        self.assertEqual(policy, {"follow": False, "watch": False})
        self.assertEqual(self.spider._history_share_policy, policy)
        self.assertFalse(self.spider._history_share_policy_loaded)

    def test_history_share_policy_cold_start_cache_failure_blocks_uploads(self):
        fresh = Spider()
        try:
            fresh.getCache = Mock(side_effect=RuntimeError("cache unavailable"))
            fresh._load_history_share_policy()

            self.assertFalse(fresh._history_share_policy_loaded)
            self.assertEqual(
                fresh._history_share_uploads([{"key": "watch", "episodeUrl": "normal-play-id"}]),
                [],
            )
        finally:
            fresh.destroy()

    def test_history_share_unknown_toggle_unlocks_only_selected_category(self):
        cache = {}
        self.spider._history_share_policy = {"follow": True, "watch": True}
        self.spider._history_share_policy_loaded = False
        self.spider.setCache = Mock(side_effect=lambda key, value: cache.__setitem__(key, value))
        self.spider._refresh_follow_categories = Mock(return_value=True)
        follow = {"key": "follow", "episodeUrl": "S01E01$followplay_invalid"}
        watch = {"key": "watch", "episodeUrl": "normal-play-id"}

        result = json.loads(self.spider.action("history-share:follow"))

        self.assertIn("已允许异地同步", result["msg"])
        self.assertEqual(self.spider._history_share_policy, {"follow": True, "watch": False})
        self.assertTrue(self.spider._history_share_policy_loaded)
        self.assertEqual(
            cache[self.spider.HISTORY_SHARE_POLICY_CACHE_KEY]["watch"],
            False,
        )
        self.assertEqual(self.spider._history_share_uploads([follow, watch]), [follow])

    def test_history_share_policy_loads_and_toggle_persists_locally(self):
        cache = {
            self.spider.HISTORY_SHARE_POLICY_CACHE_KEY: {
                "version": 1, "follow": False, "watch": True,
            },
        }
        self.spider.getCache = Mock(side_effect=lambda key: cache.get(key))
        self.spider.setCache = Mock(side_effect=lambda key, value: cache.__setitem__(key, value))
        self.spider._refresh_follow_categories = Mock(return_value=True)

        self.spider._load_history_share_policy()
        result = json.loads(self.spider.action("history-share:follow"))

        self.assertTrue(self.spider._history_share_policy["follow"])
        self.assertTrue(cache[self.spider.HISTORY_SHARE_POLICY_CACHE_KEY]["follow"])
        self.assertTrue(cache[self.spider.HISTORY_SHARE_POLICY_CACHE_KEY]["watch"])
        self.assertIn("仅影响本机未来上传", result["msg"])
        self.spider._refresh_follow_categories.assert_called_once()

    def test_history_share_toggle_failure_does_not_change_memory(self):
        self.spider._history_share_policy = {"follow": True, "watch": False}
        self.spider.setCache = Mock(return_value="failed")
        self.spider._refresh_follow_categories = Mock(return_value=True)

        result = json.loads(self.spider.action("history-share:follow"))

        self.assertEqual(self.spider._history_share_policy, {"follow": True, "watch": False})
        self.assertIn("未能保存", result["msg"])
        self.spider._refresh_follow_categories.assert_not_called()

    def test_history_share_filters_follow_and_watch_uploads_independently(self):
        play_id = self.spider._build_followplay(
            "1@episode-1",
            {"media_type": "tv", "tmdb_id": 101, "title": "测试剧集"},
            "resource-101", 1, 1, "S01E01",
        )
        follow = {"key": "follow", "episodeUrl": "S01E01$" + play_id}
        watch = {"key": "watch", "episodeUrl": "normal-play-id"}

        self.spider._history_share_policy = {"follow": False, "watch": True}
        self.spider._history_share_policy_loaded = True
        self.assertEqual(self.spider._history_share_uploads([follow, watch]), [watch])

        self.spider._history_share_policy = {"follow": True, "watch": False}
        self.assertEqual(self.spider._history_share_uploads([follow, watch]), [follow])

    def test_invalid_followplay_reference_fails_closed_as_follow_upload(self):
        malformed_follow = {"key": "follow", "episodeUrl": "S01E01$followplay_invalid"}
        watch = {"key": "watch", "episodeUrl": "normal-play-id"}
        self.spider._history_share_policy = {"follow": False, "watch": True}
        self.spider._history_share_policy_loaded = True

        self.assertEqual(
            self.spider._history_share_uploads([malformed_follow, watch]),
            [watch],
        )

    def test_history_sync_still_pulls_and_imports_when_all_uploads_are_disabled(self):
        merged = [{"key": "cloud-row"}]
        uploads = [
            {"key": "follow", "episodeUrl": "followplay_invalid"},
            {"key": "watch", "episodeUrl": "normal-play-id"},
        ]
        self.spider._history_share_policy = {"follow": False, "watch": False}
        self.spider._history_share_policy_loaded = True
        self.spider._capture_native_history = Mock(return_value=uploads)
        self.spider._atvp_fetch_history = Mock(return_value=merged)
        self.spider._merge_native_history = Mock(return_value=(merged, uploads))
        self.spider._atvp_history_push = Mock()
        self.spider._import_native_history = Mock(return_value=1)
        self.spider.history_username = "user"
        self.spider.history_password = "password"

        result = self.spider._sync_history_once()

        self.spider._atvp_fetch_history.assert_called_once()
        self.spider._import_native_history.assert_called_once_with(merged)
        self.spider._atvp_history_push.assert_not_called()
        self.assertEqual(result["upload_candidates"], 2)
        self.assertEqual(result["upload_allowed"], 0)
        self.assertEqual(result["upload_blocked"], 2)

    def test_history_sync_uploads_only_permitted_category_and_keeps_import(self):
        play_id = self.spider._build_followplay(
            "1@episode-1",
            {"media_type": "tv", "tmdb_id": 101, "title": "测试剧集"},
            "resource-101", 1, 1, "S01E01",
        )
        follow = {"key": "follow", "episodeUrl": "S01E01$" + play_id}
        watch = {"key": "watch", "episodeUrl": "normal-play-id"}
        merged = [{"key": "cloud-row"}]
        self.spider._history_share_policy = {"follow": False, "watch": True}
        self.spider._history_share_policy_loaded = True
        self.spider._capture_native_history = Mock(return_value=[follow, watch])
        self.spider._atvp_fetch_history = Mock(return_value=merged)
        self.spider._merge_native_history = Mock(return_value=(merged, [follow, watch]))
        self.spider._atvp_history_push = Mock()
        self.spider._import_native_history = Mock(return_value=1)
        self.spider.history_username = "user"
        self.spider.history_password = "password"

        result = self.spider._sync_history_once()

        self.spider._atvp_history_push.assert_called_once_with([watch])
        self.spider._import_native_history.assert_called_once_with(merged)
        self.assertEqual(result["uploaded"], 1)
        self.assertEqual(result["upload_blocked"], 1)

    def test_history_share_toggle_prevents_pending_sync_from_using_old_policy(self):
        watch = {"key": "watch", "episodeUrl": "normal-play-id"}
        merge_started = MODULE.threading.Event()
        merge_release = MODULE.threading.Event()
        result = {}

        def merge(_local, _cloud):
            merge_started.set()
            self.assertTrue(merge_release.wait(2))
            return [watch], [watch]

        self.spider._history_share_policy = {"follow": True, "watch": True}
        self.spider._history_share_policy_loaded = True
        self.spider.setCache = Mock(return_value=None)
        self.spider._refresh_follow_categories = Mock(return_value=True)
        self.spider._capture_native_history = Mock(return_value=[watch])
        self.spider._atvp_fetch_history = Mock(return_value=[])
        self.spider._merge_native_history = Mock(side_effect=merge)
        self.spider._atvp_history_push = Mock()
        self.spider._import_native_history = Mock(return_value=1)
        self.spider.history_username = "user"
        self.spider.history_password = "password"

        worker = MODULE.threading.Thread(
            target=lambda: result.setdefault("value", self.spider._sync_history_once())
        )
        worker.start()
        self.assertTrue(merge_started.wait(2))
        toggle = json.loads(self.spider.action("history-share:watch"))
        merge_release.set()
        worker.join(2)

        self.assertFalse(worker.is_alive())
        self.assertIn("已禁止异地同步", toggle["msg"])
        self.spider._atvp_history_push.assert_not_called()
        self.assertEqual(result["value"]["upload_blocked"], 1)

    def test_history_management_cards_reflect_local_share_policy(self):
        self.spider._history_share_policy = {"follow": False, "watch": True}
        self.spider._history_share_policy_loaded = True

        cards = self.spider._history_management_cards()
        by_action = {card.get("action"): card for card in cards}

        self.assertIn("禁止异地同步", by_action["history-share:follow"]["vod_name"])
        self.assertIn("允许异地同步", by_action["history-share:watch"]["vod_name"])
        self.assertIn("不影响云端读取", by_action["history-share:follow"]["vod_remarks"])

    def test_navigation_cards_search_directly_without_mode_card(self):
        self.spider._tmdb_api = Mock(return_value={
            "results": [
                {"id": 101, "name": "测试剧集", "media_type": "tv"},
                {"id": 202, "title": "测试电影", "media_type": "movie"},
            ],
            "total_pages": 1,
            "total_results": 2,
        })

        cards = self.spider.categoryContent("tmdb_trending", "1", True, {})["list"]

        self.assertEqual(len(cards), 2)
        self.assertTrue(all(card["action"].startswith("fongmi-search:") for card in cards))
        self.assertFalse(any(str(card.get("vod_id") or "").startswith("series-mode:") for card in cards))
        self.assertFalse(any(str(card.get("action") or "").startswith("series-card:") for card in cards))

    def test_cached_series_action_also_searches_and_returns_feedback(self):
        self.spider._series_action_mode = "add"
        self.spider._open_global_search = Mock(return_value=json.dumps({"msg": "已打开全局搜索：测试剧集"}, ensure_ascii=False))

        result = json.loads(self.spider.action("series-card:tmdb:101:%E6%B5%8B%E8%AF%95%E5%89%A7%E9%9B%86"))

        self.assertIn("已打开全局搜索", result["msg"])
        self.spider._open_global_search.assert_called_once()

    def test_confirmation_merges_keep_and_history_as_one_pending_candidate(self):
        self.spider._native_keep_export_java = Mock(return_value=[{
            "key": "site@@@vod@@@1", "title": "测试剧集", "pic": "keep.jpg",
            "site_name": "收藏站", "create_time": 10,
        }])
        self.spider._native_history_export_java = Mock(return_value={
            "config": "{}",
            "rows": [{
                "key": "other@@@vod@@@1", "vodName": "测试剧集 S01E03",
                "vodPic": "history.jpg", "vodRemarks": "第3集", "createTime": 20,
            }],
        })

        result = self.spider.categoryContent("follow_candidates", "1", False, {})
        candidate = next(card for card in result["list"] if card.get("action"))

        self.assertEqual(result["total"], 1)
        self.assertEqual(candidate["vod_name"], "测试剧集")
        self.assertIn("收藏 + 播放记录", candidate["vod_remarks"])
        self.assertTrue(candidate["action"].startswith("follow-candidate:add:"))

    def test_candidate_source_rows_and_identity_fields_are_bounded(self):
        self.spider.keep_follow_scan_limit = 1
        self.spider._native_keep_export_java = Mock(return_value=[
            {
                "key": "key-%d" % index,
                "title": "同名剧" + ("长" * 400),
                "site_name": "站点-%d" % index,
                "create_time": index,
            }
            for index in range(5000)
        ])
        self.spider._native_history_export_java = Mock(return_value={"config": "{}", "rows": []})

        candidates, _cards = self.spider._native_follow_candidates()

        self.assertEqual(len(candidates), 1)
        self.assertLessEqual(len(candidates[0]["keep_keys"]), 3)
        self.assertLessEqual(len(candidates[0]["site_names"]), 4)
        self.assertLessEqual(len(candidates[0]["title"]), 256)
        self.spider._native_keep_export_java.assert_called_once_with(1)
        self.spider._native_history_export_java.assert_called_once_with(1)

    def test_candidate_keep_bridge_limits_rows_before_python_conversion(self):
        class JavaRow(object):
            def __init__(self, index):
                self.index = index

            def getKey(self):
                return "key-%d" % self.index

            def getVodName(self):
                return "剧集-%d" % self.index

            def getVodPic(self):
                return "pic-%d" % self.index

            def getSiteName(self):
                return "site-%d" % self.index

            def getCreateTime(self):
                return 1000 - self.index

            def getCid(self):
                return 1

            def getType(self):
                return 0

        class JavaRows(object):
            def __init__(self):
                self.get_count = 0

            def size(self):
                return 5000

            def get(self, index):
                self.get_count += 1
                return JavaRow(index)

        rows = JavaRows()
        keep_class = type("Keep", (), {"getVod": staticmethod(lambda: rows)})
        java_module = types.ModuleType("java")
        java_module.jclass = lambda _name: keep_class

        with patch.dict(sys.modules, {"java": java_module}):
            exported = self.spider._native_keep_export_java(3)

        self.assertEqual(len(exported), 3)
        self.assertEqual(rows.get_count, 3)

    def test_empty_ext_direct_runtime_keeps_detail_and_direct_player_contract(self):
        self.spider.init({})
        self.spider._get_json = Mock(return_value={
            "id": "123456", "title": "测试影片", "intro": "简介",
            "pic": {"large": "poster.jpg"}, "year": 2026,
        })
        self.spider._resource_candidates = Mock(side_effect=AssertionError("direct mode called AList"))

        detail = self.spider.detailContent(["123456"])
        player = self.spider.playerContent("直链", "https://media.example/test.m3u8", [])

        self.assertEqual(detail["list"][0]["vod_name"], "测试影片")
        self.assertEqual(detail["list"][0]["vod_pic"], "poster.jpg")
        self.spider._resource_candidates.assert_not_called()
        self.assertEqual(player, {
            "parse": 0, "jx": 0, "playUrl": "",
            "url": "https://media.example/test.m3u8", "header": {},
        })

    def test_confirmed_candidate_moves_to_management_with_live_status(self):
        candidate = {
            "title": "测试剧集",
            "match_title": "测试剧集 S01E03",
            "pic": "poster.jpg",
            "sources": ["收藏", "播放记录"],
            "keep_keys": ["site@@@vod@@@1"],
            "history_keys": ["other@@@vod@@@1"],
            "site_names": ["测试站"],
        }
        item = {
            "tmdb_id": 101, "title": "测试剧集", "pic": "poster.jpg",
            "seen_episode": "", "tracked_episode": "S01E03", "latest_episode": "S01E03",
        }
        self.spider._resolve_follow_candidate = Mock(return_value=(item, ""))
        self.spider._refresh_follow_categories = Mock(return_value=True)
        action = self.spider.FOLLOW_CANDIDATE_ADD_PREFIX + self.spider._encode_follow_candidate(candidate)

        immediate = json.loads(self.spider.action(action))
        self.assertIn("已开始确认追更", immediate["msg"])
        self._wait_follow_jobs()

        saved = self.spider._follow_memory["items"]["101"]
        self.assertEqual(saved["keep_keys"], ["site@@@vod@@@1"])
        self.assertEqual(saved["history_keys"], ["other@@@vod@@@1"])
        self.assertEqual(self.spider._follow_action_state["last"]["state"], "done")
        self.assertIn("已加入追更", self.spider._follow_action_state["last"]["message"])
        self.assertGreaterEqual(self.spider._refresh_follow_categories.call_count, 2)

    def test_candidate_confirmation_failure_keeps_live_failed_feedback(self):
        candidate = {
            "title": "无法确认的剧集", "match_title": "无法确认的剧集",
            "pic": "poster.jpg", "sources": ["收藏"],
        }
        self.spider._resolve_follow_candidate = Mock(return_value=(None, "no_confident_tv"))
        self.spider._refresh_follow_categories = Mock(return_value=True)
        action = self.spider.FOLLOW_CANDIDATE_ADD_PREFIX + self.spider._encode_follow_candidate(candidate)

        immediate = json.loads(self.spider.action(action))
        self.assertIn("已开始确认追更", immediate["msg"])
        self._wait_follow_jobs()

        self.assertEqual(self.spider._follow_action_state["last"]["state"], "failed")
        self.assertIn("确认追更失败", self.spider._follow_action_state["last"]["message"])

    def test_candidate_confirmation_persistence_failure_is_not_reported_as_success(self):
        candidate = {"title": "测试剧集", "match_title": "测试剧集", "sources": ["收藏"]}
        item = {"tmdb_id": 101, "title": "测试剧集", "latest_episode": "S01E03"}
        self.spider._resolve_follow_candidate = Mock(return_value=(item, ""))
        self.spider._persist_follow_state = Mock(return_value=False)
        self.spider._refresh_follow_categories = Mock(return_value=True)
        action = self.spider.FOLLOW_CANDIDATE_ADD_PREFIX + self.spider._encode_follow_candidate(candidate)

        self.spider.action(action)
        self._wait_follow_jobs()

        self.assertNotIn("101", self.spider._follow_memory["items"])
        self.assertEqual(self.spider._follow_action_state["last"]["state"], "failed")
        self.assertIn("追更状态未能持久保存", self.spider._follow_action_state["last"]["message"])

    def test_candidate_worker_does_not_write_after_generation_change(self):
        started = MODULE.threading.Event()
        release = MODULE.threading.Event()
        candidate = {"title": "旧订阅剧集", "match_title": "旧订阅剧集"}
        item = {"tmdb_id": 101, "title": "旧订阅剧集", "latest_episode": "S01E03"}

        def resolve(_candidate):
            started.set()
            release.wait(2)
            return item, ""

        self.spider._resolve_follow_candidate = resolve
        self.spider._refresh_follow_categories = Mock(return_value=True)
        action = self.spider.FOLLOW_CANDIDATE_ADD_PREFIX + self.spider._encode_follow_candidate(candidate)
        self.spider.action(action)
        self.assertTrue(started.wait(1))
        with self.spider._cache_lock:
            self.spider._cache_generation += 1
        self.spider._follow_memory = {"version": 2, "items": {
            "2": {"tmdb_id": 2, "title": "新订阅剧集"},
        }}
        release.set()
        self._wait_follow_jobs()

        self.assertEqual(set(self.spider._follow_memory["items"]), {"2"})
        self.assertNotIn("已加入追更", self.spider._follow_action_state["last"].get("message", ""))

    def test_interrupted_candidate_running_status_is_not_restored_after_init(self):
        cache = {
            self.spider.FOLLOW_ACTION_STATE_CACHE_KEY: {
                "version": 1,
                "last": {
                    "state": "running", "message": "正在确认追更：旧剧集",
                    "operation": "candidate", "title": "旧剧集", "updated_at": int(time.time()),
                },
                "pending": {},
            },
        }
        self.spider.getCache = lambda key: cache.get(key)
        self.spider.setCache = lambda key, value: cache.__setitem__(key, value)

        self.spider._load_follow_action_state()

        self.assertEqual(self.spider._follow_action_state["last"]["state"], "failed")
        self.assertIn("被中断", self.spider._follow_action_state["last"]["message"])
        self.assertEqual(cache[self.spider.FOLLOW_ACTION_STATE_CACHE_KEY]["last"]["state"], "failed")

    def test_candidate_confirmation_start_failure_is_reported_immediately(self):
        candidate = {"title": "启动失败剧集", "match_title": "启动失败剧集"}
        self.spider._refresh_follow_categories = Mock(return_value=True)
        thread = Mock()
        thread.start.side_effect = RuntimeError("thread unavailable")
        action = self.spider.FOLLOW_CANDIDATE_ADD_PREFIX + self.spider._encode_follow_candidate(candidate)

        with patch.object(MODULE.threading, "Thread", return_value=thread):
            result = json.loads(self.spider.action(action))

        self.assertIn("确认追更启动失败", result["msg"])
        self.assertEqual(self.spider._follow_action_state["last"]["state"], "failed")
        self.assertIn("确认追更启动失败", self.spider._follow_action_state["last"]["message"])

    def test_same_title_different_year_candidates_start_independent_jobs(self):
        first = {"title": "同名剧", "match_title": "同名剧 (2001)", "year": "2001"}
        second = {"title": "同名剧", "match_title": "同名剧 (2020)", "year": "2020"}
        self.spider._refresh_follow_categories = Mock(return_value=True)
        thread = Mock()

        with patch.object(MODULE.threading, "Thread", return_value=thread):
            first_result = json.loads(self.spider.action(
                self.spider.FOLLOW_CANDIDATE_ADD_PREFIX + self.spider._encode_follow_candidate(first)
            ))
            second_result = json.loads(self.spider.action(
                self.spider.FOLLOW_CANDIDATE_ADD_PREFIX + self.spider._encode_follow_candidate(second)
            ))

        self.assertIn("已开始确认追更", first_result["msg"])
        self.assertIn("已开始确认追更", second_result["msg"])
        self.assertEqual(len(self.spider._follow_enrich_jobs), 2)
        self.spider._follow_enrich_jobs.clear()

    def test_concurrent_candidate_jobs_publish_terminal_state_only_after_last_job(self):
        releases = {
            "先完成剧集": MODULE.threading.Event(),
            "后完成剧集": MODULE.threading.Event(),
        }
        started = {title: MODULE.threading.Event() for title in releases}

        def resolve(candidate):
            title = candidate["title"]
            started[title].set()
            releases[title].wait(2)
            tmdb_id = 101 if title == "先完成剧集" else 202
            return {"tmdb_id": tmdb_id, "title": title, "latest_episode": "S01E03"}, ""

        self.spider._resolve_follow_candidate = resolve
        self.spider._refresh_follow_categories = Mock(return_value=True)
        for title in releases:
            candidate = {"title": title, "match_title": title}
            self.spider.action(
                self.spider.FOLLOW_CANDIDATE_ADD_PREFIX
                + self.spider._encode_follow_candidate(candidate)
            )
            self.assertTrue(started[title].wait(1))

        releases["先完成剧集"].set()
        deadline = time.time() + 1
        while len(self.spider._follow_enrich_jobs) > 1 and time.time() < deadline:
            time.sleep(0.01)

        self.assertEqual(len(self.spider._follow_enrich_jobs), 1)
        self.assertEqual(self.spider._follow_action_state["last"]["state"], "running")
        self.assertIn("剩余 1 项", self.spider._follow_action_state["last"]["message"])

        releases["后完成剧集"].set()
        self._wait_follow_jobs()

        self.assertEqual(self.spider._follow_action_state["last"]["state"], "done")
        self.assertIn("成功 2 项", self.spider._follow_action_state["last"]["message"])

    def test_seen_and_remove_confirmations_report_completion_status(self):
        self.spider._refresh_follow_categories = Mock(return_value=True)
        self.spider._follow_memory = {"version": 2, "items": {
            "101": {"tmdb_id": 101, "title": "测试剧集", "latest_episode": "S01E03"},
        }}
        for operation, prefix, message in (
                ("seen", self.spider.FOLLOW_SEEN_PREFIX, "已标记看到 S01E03"),
                ("remove", self.spider.FOLLOW_REMOVE_PREFIX, "已取消追更：测试剧集")):
            with self.subTest(operation=operation):
                self.spider._follow_memory = {"version": 2, "items": {
                    "101": {"tmdb_id": 101, "title": "测试剧集", "latest_episode": "S01E03"},
                }}
                request = json.loads(self.spider.action(prefix + "101"))
                self.assertIn("待确认", request["msg"])
                pending = dict(self.spider._follow_action_state["pending"])
                self.assertEqual(pending["operation"], operation)
                self.spider._follow_action = Mock(return_value=json.dumps({"msg": message}, ensure_ascii=False))
                execute = self.spider.FOLLOW_EXECUTE_PREFIX + "%s:%s:101" % (
                    pending["nonce"], operation,
                )
                result = json.loads(self.spider.action(execute))
                self.assertEqual(result["msg"], message)
                self.assertEqual(self.spider._follow_action_state["last"]["state"], "done")
                self.assertEqual(self.spider._follow_action_state["last"]["operation"], operation)
                self.assertFalse(self.spider._follow_action_state["pending"])

    def test_confirmation_cancel_and_status_ack_clear_state_with_feedback(self):
        self.spider._refresh_follow_categories = Mock(return_value=True)
        self.spider._follow_memory = {"version": 2, "items": {
            "101": {"tmdb_id": 101, "title": "测试剧集"},
        }}
        self.spider.action(self.spider.FOLLOW_REMOVE_PREFIX + "101")
        nonce = self.spider._follow_action_state["pending"]["nonce"]

        cancelled = json.loads(self.spider.action(self.spider.FOLLOW_CONFIRM_CANCEL_PREFIX + nonce))
        self.assertIn("已放弃取消追更", cancelled["msg"])
        self.assertEqual(self.spider._follow_action_state["last"]["state"], "info")
        self.assertFalse(self.spider._follow_action_state["pending"])

        acknowledged = json.loads(self.spider.action(self.spider.FOLLOW_STATUS_ACK_ACTION))
        self.assertEqual(acknowledged["msg"], "操作状态已清除")
        self.assertFalse(self.spider._follow_action_state["last"])

    def test_old_auto_follow_card_only_redirects_to_confirmation(self):
        self.spider._start_atvp_job = Mock(side_effect=AssertionError("must not auto-follow favorites"))
        self.spider._refresh_follow_categories = Mock(return_value=True)

        result = json.loads(self.spider.action(self.spider.KEEP_FOLLOW_ACTION))

        self.assertIn("追更待选", result["msg"])
        self.assertEqual(self.spider._follow_action_state["last"]["state"], "info")
        self.spider._refresh_follow_categories.assert_called_once()

    def test_old_direct_add_actions_cannot_bypass_confirmation(self):
        self.spider._follow_action = Mock(side_effect=AssertionError("must not add directly"))
        self.spider._follow_action_from_douban = Mock(side_effect=AssertionError("must not add directly"))
        self.spider._refresh_follow_categories = Mock(return_value=True)

        for action in ("tmdb-follow:add:101", "douban-follow:add:123456"):
            with self.subTest(action=action):
                result = json.loads(self.spider.action(action))
                self.assertIn("追更确认", result["msg"])
                self.assertEqual(self.spider._follow_action_state["last"]["state"], "info")

        self.spider._follow_action.assert_not_called()
        self.spider._follow_action_from_douban.assert_not_called()
        self.assertEqual(self.spider._refresh_follow_categories.call_count, 2)

    def test_old_keep_background_entry_cannot_bypass_confirmation(self):
        self.spider._follow_memory = {"version": 2, "items": {}}
        self.spider._refresh_follow_categories = Mock(return_value=True)
        self.spider._native_keep_export_java = Mock(return_value=[{
            "key": "site@@@vod@@@1", "title": "测试剧集", "create_time": 10,
        }])

        result = json.loads(self.spider._start_atvp_job("keep"))

        self.assertIn("追更确认", result["msg"])
        self.assertFalse(self.spider._follow_memory["items"])
        self.assertFalse(self.spider._atvp_jobs)
        self.assertEqual(self.spider._follow_action_state["last"]["state"], "info")

    def test_refresh_thread_start_failure_does_not_escape_action(self):
        self.spider._queue_instantiated_follow_refresh = Mock(return_value=False)
        thread = Mock()
        thread.start.side_effect = RuntimeError("thread unavailable")

        with patch.object(MODULE.threading, "Thread", return_value=thread):
            result = json.loads(self.spider.action(self.spider.KEEP_FOLLOW_ACTION))

        self.assertIn("追更待选", result["msg"])
        self.assertEqual(self.spider._follow_action_state["last"]["state"], "info")

    def test_followed_source_record_is_not_left_in_pending_list(self):
        self.spider._follow_memory = {"version": 2, "items": {
            "101": {"tmdb_id": 101, "title": "测试剧集", "keep_keys": ["site@@@vod@@@1"]},
        }}
        self.spider._native_keep_export_java = Mock(return_value=[{
            "key": "site@@@vod@@@1", "title": "测试剧集", "create_time": 10,
        }])
        self.spider._native_history_export_java = Mock(return_value={"config": "{}", "rows": []})

        result = self.spider.categoryContent("follow_candidates", "1", False, {})

        self.assertEqual(result["total"], 0)
        self.assertTrue(any(card["vod_name"] == "暂无追更待选" for card in result["list"]))

    def test_same_provider_missing_episode_is_completed_and_marked(self):
        item = {
            "media_type": "tv",
            "tmdb_id": 101,
            "title": "测试剧集",
            "trackingSeason": 1,
            "latest_episode": "S01E03",
        }
        merged = self.spider._merge_resource_vods([
            {
                "vod_play_from": "夸克分享A",
                "vod_play_url": "S01E01$play-a-1#S01E03$play-a-3",
                "resource_id": "quark-share-a",
                "group_seasons": [1],
                "group_providers": ["quark"],
            },
            {
                "vod_play_from": "夸克分享B",
                "vod_play_url": "S01E01$play-b-1#S01E02$play-b-2#S01E03$play-b-3",
                "resource_id": "quark-share-b",
                "group_seasons": [1],
                "group_providers": ["quark"],
            },
        ], item, "tmdb:tv:101", {"vod_name": "测试剧集"})

        self.assertIsNotNone(merged)
        groups = str(merged["vod_play_url"]).split("$$$")
        self.assertIn("S01E02补全$play-b-2", groups[0])
        self.assertIn("同盘补全 1 集", merged["vod_remarks"])

    def test_missing_episode_is_not_mixed_across_cloud_providers(self):
        item = {"media_type": "tv", "tmdb_id": 101, "title": "测试剧集", "trackingSeason": 1}
        merged = self.spider._merge_resource_vods([
            {
                "vod_play_from": "夸克分享",
                "vod_play_url": "S01E01$quark-1#S01E03$quark-3",
                "resource_id": "quark-share",
                "group_providers": ["quark"],
            },
            {
                "vod_play_from": "百度分享",
                "vod_play_url": "S01E02$baidu-2",
                "resource_id": "baidu-share",
                "group_providers": ["baidu"],
            },
        ], item, "tmdb:tv:101", {"vod_name": "测试剧集"})

        self.assertIsNotNone(merged)
        self.assertNotIn("补全", str(merged["vod_play_url"]).split("$$$")[0])
        self.assertNotIn("同盘补全", merged["vod_remarks"])

    def test_completed_episode_keeps_real_donor_play_id_without_cross_provider_fallback(self):
        item = {
            "media_type": "tv",
            "tmdb_id": 101,
            "title": "测试剧集",
            "trackingSeason": 1,
            "latest_episode": "S01E03",
        }
        quark_a = self.spider._rewrite_resource_vod({
            "vod_name": "测试剧集",
            "vod_play_from": "夸克分享A",
            "vod_play_url": "S01E01$https://pan.quark.cn/s/a1#S01E03$https://pan.quark.cn/s/a3",
        }, item, "quark-share-a", provider_hint="夸克")
        quark_b = self.spider._rewrite_resource_vod({
            "vod_name": "测试剧集",
            "vod_play_from": "夸克分享B",
            "vod_play_url": "S01E02$https://pan.quark.cn/s/b2",
        }, item, "quark-share-b", provider_hint="夸克")
        baidu_b = self.spider._rewrite_resource_vod({
            "vod_name": "测试剧集",
            "vod_play_from": "百度分享",
            "vod_play_url": "S01E02$https://pan.baidu.com/s/b2",
        }, item, "baidu-share-b", provider_hint="百度")
        donor_play_id = quark_b["vod_play_url"].rpartition("$")[2]

        merged = self.spider._merge_resource_vods(
            [quark_a, quark_b, baidu_b], item, "tmdb:tv:101", {"vod_name": "测试剧集"}
        )

        completed_part = next(
            part for part in str(merged["vod_play_url"]).split("$$$")[0].split("#")
            if part.startswith("S01E02补全$")
        )
        completed_play_id = completed_part.rpartition("$")[2]
        payload = self.spider._parse_followplay(completed_play_id)
        self.assertEqual(completed_play_id, donor_play_id)
        self.assertEqual(payload["url"], "https://pan.quark.cn/s/b2")
        self.assertFalse(any("pan.baidu.com" in row["url"] for row in payload["fallbacks"]))

    def test_same_episode_fallbacks_are_isolated_by_provider(self):
        item = {"media_type": "tv", "tmdb_id": 101, "title": "测试剧集", "trackingSeason": 1}
        quark = self.spider._rewrite_resource_vod({
            "vod_name": "测试剧集", "vod_play_from": "夸克分享",
            "vod_play_url": "S01E01$https://pan.quark.cn/s/q1",
        }, item, "quark-share", provider_hint="夸克")
        baidu = self.spider._rewrite_resource_vod({
            "vod_name": "测试剧集", "vod_play_from": "百度分享",
            "vod_play_url": "S01E01$https://pan.baidu.com/s/b1",
        }, item, "baidu-share", provider_hint="百度")

        merged = self.spider._merge_resource_vods(
            [quark, baidu], item, "tmdb:tv:101", {"vod_name": "测试剧集"}
        )
        payloads = []
        for group in str(merged["vod_play_url"]).split("$$$"):
            for part in group.split("#"):
                payload = self.spider._parse_followplay(part.rpartition("$")[2])
                if payload:
                    payloads.append(payload)
        quark_payload = next(row for row in payloads if row["url"].endswith("/q1"))
        baidu_payload = next(row for row in payloads if row["url"].endswith("/b1"))
        self.assertFalse(any("pan.baidu.com" in row["url"] for row in quark_payload["fallbacks"]))
        self.assertFalse(any("pan.quark.cn" in row["url"] for row in baidu_payload["fallbacks"]))

    def test_conflicting_provider_hints_fail_closed(self):
        self.assertEqual(self.spider._resource_provider_key("夸克", "百度分享"), "")
        item = {
            "media_type": "tv", "tmdb_id": 101, "title": "测试剧集",
            "trackingSeason": 1, "latest_episode": "S01E03",
        }
        rewritten = self.spider._rewrite_resource_vod(
            {
                "vod_name": "测试剧集", "vod_play_from": "百度分享",
                "vod_play_url": "S01E01$play-1#S01E03$play-3",
            },
            item,
            "opaque-conflict-id",
            mode="pansou",
            provider_hint="夸克",
        )
        self.assertEqual(rewritten["group_providers"], [""])
        baidu_donor = self.spider._rewrite_resource_vod(
            {"vod_name": "测试剧集", "vod_play_from": "百度分享", "vod_play_url": "S01E02$baidu-2"},
            item,
            "opaque-baidu-id",
            mode="pansou",
            provider_hint="百度",
        )

        merged = self.spider._merge_resource_vods(
            [rewritten, baidu_donor], item, "tmdb:tv:101", {"vod_name": "测试剧集"}
        )

        self.assertNotIn("补全", str(merged["vod_play_url"]).split("$$$")[0])
        self.assertNotIn("同盘补全", merged["vod_remarks"])

    def test_target_provider_mismatch_and_lookalike_domain_fail_closed(self):
        self.assertEqual(self.spider._resource_provider_key("https://pan.quark.cn.evil.example/s/a"), "")
        item = {
            "media_type": "tv", "tmdb_id": 101, "title": "测试剧集",
            "trackingSeason": 1, "latest_episode": "S01E03",
        }
        mislabeled = self.spider._rewrite_resource_vod({
            "vod_name": "测试剧集", "vod_play_from": "资源A",
            "vod_play_url": "S01E01$https://pan.baidu.com/s/a1#S01E03$https://pan.baidu.com/s/a3",
        }, item, "opaque-a", provider_hint="夸克")
        quark_donor = self.spider._rewrite_resource_vod({
            "vod_name": "测试剧集", "vod_play_from": "资源B",
            "vod_play_url": "S01E02$https://pan.quark.cn/s/b2",
        }, item, "opaque-b", provider_hint="夸克")

        self.assertEqual(mislabeled["group_providers"], [""])
        evil = self.spider._rewrite_resource_vod({
            "vod_name": "测试剧集", "vod_play_from": "资源A",
            "vod_play_url": "S01E01$https://pan.quark.cn.evil.example/s/a1#S01E03$https://pan.quark.cn.evil.example/s/a3",
        }, item, "opaque-a", provider_hint="夸克")
        self.assertEqual(evil["group_providers"], [""])
        merged = self.spider._merge_resource_vods(
            [mislabeled, quark_donor], item, "tmdb:tv:101", {"vod_name": "测试剧集"}
        )
        self.assertNotIn("补全", str(merged["vod_play_url"]).split("$$$")[0])
        self.assertNotIn("同盘补全", merged["vod_remarks"])

    def test_pan123_alternate_domains_are_recognized_as_same_provider(self):
        item = {
            "media_type": "tv", "tmdb_id": 101, "title": "测试剧集",
            "trackingSeason": 1, "latest_episode": "S01E03",
        }
        first = self.spider._rewrite_resource_vod({
            "vod_name": "测试剧集", "vod_play_from": "线路A",
            "vod_play_url": (
                "S01E01$https://www.123684.com/s/a1#"
                "S01E03$https://www.123684.com/s/a3"
            ),
        }, item, "opaque-a")
        donor = self.spider._rewrite_resource_vod({
            "vod_name": "测试剧集", "vod_play_from": "线路B",
            "vod_play_url": "S01E02$https://123685.cn/s/b2",
        }, item, "opaque-b")

        self.assertEqual(first["group_providers"], ["pan123"])
        self.assertEqual(donor["group_providers"], ["pan123"])
        merged = self.spider._merge_resource_vods(
            [first, donor], item, "tmdb:tv:101", {"vod_name": "测试剧集"}
        )
        self.assertIn("S01E02补全$", merged["vod_play_url"].split("$$$")[0])
        self.assertIn("同盘补全 3 集", merged["vod_remarks"])

    def test_rewrite_entry_limits_oversized_episode_payload_before_merge(self):
        item = {"media_type": "tv", "tmdb_id": 101, "title": "测试剧集", "trackingSeason": 1}
        play_url = "#".join(
            "S01E%03d$https://pan.quark.cn/s/%03d" % (episode, episode)
            for episode in range(1, self.spider.RESOURCE_GROUP_EPISODE_LIMIT + 80)
        )
        rewritten = self.spider._rewrite_resource_vod(
            {"vod_name": "测试剧集", "vod_play_from": "夸克分享", "vod_play_url": play_url},
            item, "quark-oversized", provider_hint="夸克",
        )
        self.assertTrue(rewritten["_resource_limited"])
        self.assertEqual(
            len(rewritten["vod_play_url"].split("#")),
            self.spider.RESOURCE_GROUP_EPISODE_LIMIT,
        )
        merged = self.spider._merge_resource_vods(
            [rewritten], item, "tmdb:tv:101", {"vod_name": "测试剧集"}
        )
        self.assertIn("资源分集过多 已截断", merged["vod_remarks"])

    def test_invalid_parts_do_not_consume_valid_record_budget(self):
        item = {"media_type": "tv", "tmdb_id": 101, "title": "测试剧集", "trackingSeason": 1}
        invalid_group = "#".join("bad-%d" % index for index in range(256))
        rewritten = self.spider._rewrite_resource_vod({
            "vod_name": "测试剧集",
            "vod_play_from": "异常A$$$异常B$$$夸克分享",
            "vod_play_url": "%s$$$%s$$$S01E01$https://pan.quark.cn/s/ok" % (
                invalid_group, invalid_group,
            ),
        }, item, "quark-valid-last", provider_hint="夸克")

        self.assertIsNotNone(rewritten)
        self.assertIn("S01E01$", rewritten["vod_play_url"])
        with self.assertRaisesRegex(RuntimeError, "资源播放项无效"):
            self.spider._rewrite_resource_vod({
                "vod_name": "测试剧集", "vod_play_from": "异常线路",
                "vod_play_url": invalid_group,
            }, item, "invalid-only")

    def test_followplay_encoding_growth_is_bounded_and_reported(self):
        item = {"media_type": "tv", "tmdb_id": 101, "title": "测试剧集", "trackingSeason": 1}
        suffix = "x" * 7950
        play_url = "#".join(
            "S01E%03d$https://pan.quark.cn/s/%03d%s" % (episode, episode, suffix)
            for episode in range(1, 121)
        )
        rewritten = self.spider._rewrite_resource_vod(
            {"vod_name": "测试剧集", "vod_play_from": "夸克分享", "vod_play_url": play_url},
            item, "quark-growth", provider_hint="夸克",
        )

        self.assertTrue(rewritten["_resource_limited"])
        self.assertLessEqual(len(rewritten["vod_play_url"]), self.spider.RESOURCE_PLAY_URL_MAX_LENGTH)
        merged = self.spider._merge_resource_vods(
            [rewritten], item, "tmdb:tv:101", {"vod_name": "测试剧集"}
        )
        self.assertIsNotNone(merged)
        self.assertIn("资源分集过多 已截断", merged["vod_remarks"])

    def test_oversized_resource_id_cannot_expand_source_label(self):
        item = {"media_type": "tv", "tmdb_id": 101, "title": "测试剧集", "trackingSeason": 1}
        rewritten = self.spider._rewrite_resource_vod(
            {"vod_name": "测试剧集", "vod_play_url": "S01E01$play-1"},
            item, "R" * 200000, provider_hint="夸克",
        )

        self.assertTrue(rewritten["_resource_limited"])
        self.assertLessEqual(len(rewritten["resource_id"]), self.spider.RESOURCE_ID_MAX_LENGTH)
        self.assertLessEqual(len(rewritten["vod_play_from"]), self.spider.RESOURCE_SOURCE_LABEL_MAX_LENGTH)

    def test_single_oversized_play_item_is_rejected_with_feedback(self):
        item = {"media_type": "tv", "tmdb_id": 101, "title": "测试剧集", "trackingSeason": 1}
        oversized = "S01E01$" + ("x" * self.spider.RESOURCE_PLAY_URL_MAX_LENGTH)

        with self.assertRaisesRegex(RuntimeError, "资源播放项过长"):
            self.spider._rewrite_resource_vod(
                {"vod_name": "测试剧集", "vod_play_from": "夸克分享", "vod_play_url": oversized},
                item, "quark-oversized", provider_hint="夸克",
            )

    def test_no_completion_keeps_original_episode_order(self):
        records = [
            {"group": 0, "part": 0, "origin_part": 0, "provider": "quark", "episode_key": (1, 0), "name": "特别篇"},
            {"group": 0, "part": 1, "origin_part": 1, "provider": "quark", "episode_key": (1, 2), "name": "S01E02"},
            {"group": 0, "part": 2, "origin_part": 2, "provider": "quark", "episode_key": (1, 1), "name": "S01E01"},
        ]

        output, completed, limited = self.spider._complete_same_provider_groups(records)

        self.assertEqual(completed, 0)
        self.assertFalse(limited)
        self.assertEqual([row["name"] for row in output], ["特别篇", "S01E02", "S01E01"])

    def test_resource_episode_amplification_is_bounded_with_feedback(self):
        item = {"media_type": "tv", "tmdb_id": 101, "title": "测试剧集", "trackingSeason": 1}
        vods = []
        for group_index in range(3):
            first_episode = group_index * 200 + 1
            episodes = [
                "S01E%03d$play-%d" % (episode, episode)
                for episode in range(first_episode, first_episode + 200)
            ]
            vods.append({
                "vod_play_from": "夸克分享%d" % group_index,
                "vod_play_url": "#".join(episodes),
                "resource_id": "quark-share-%d" % group_index,
                "group_providers": ["quark"],
            })

        merged = self.spider._merge_resource_vods(
            vods, item, "tmdb:tv:101", {"vod_name": "测试剧集"}
        )

        episode_total = sum(len(flag["episodes"]) - 1 for flag in merged["vodFlags"])
        self.assertLessEqual(
            episode_total,
            self.spider.RESOURCE_RECORD_LIMIT + self.spider.RESOURCE_COMPLETION_LIMIT,
        )
        self.assertIn("资源分集过多 已截断", merged["vod_remarks"])

    def test_completion_cannot_expand_final_play_urls_past_budget(self):
        item = {"media_type": "tv", "tmdb_id": 101, "title": "测试剧集", "trackingSeason": 1}
        vods = []
        for group_index in range(5):
            first_episode = group_index * 40 + 1
            episodes = [
                "S01E%03d$%s" % (episode, "p%d-" % episode + ("x" * 1490))
                for episode in range(first_episode, first_episode + 40)
            ]
            vods.append({
                "vod_play_from": "夸克分享%d" % group_index,
                "vod_play_url": "#".join(episodes),
                "resource_id": "quark-share-%d" % group_index,
                "group_providers": ["quark"],
            })

        merged = self.spider._merge_resource_vods(
            vods, item, "tmdb:tv:101", {"vod_name": "测试剧集"}
        )

        self.assertLessEqual(len(merged["vod_play_url"]), self.spider.RESOURCE_PLAY_URL_MAX_LENGTH)
        self.assertTrue(all(
            len(flag["urls"]) <= self.spider.RESOURCE_PLAY_URL_MAX_LENGTH
            for flag in merged["vodFlags"]
        ))
        self.assertIn("资源分集过多 已截断", merged["vod_remarks"])

    def test_fallback_encoding_cannot_expand_final_play_urls_past_budget(self):
        item = {"media_type": "tv", "tmdb_id": 101, "title": "测试剧集", "trackingSeason": 1}
        vods = []
        suffix = "x" * 7900
        for group_index in range(3):
            play_url = "#".join(
                "S01E%02d$https://pan.quark.cn/s/g%d-e%02d-%s" % (
                    episode, group_index, episode, suffix,
                )
                for episode in range(1, 16)
            )
            vods.append(self.spider._rewrite_resource_vod({
                "vod_name": "测试剧集", "vod_play_from": "夸克分享%d" % group_index,
                "vod_play_url": play_url,
            }, item, "quark-share-%d" % group_index, provider_hint="夸克"))

        merged = self.spider._merge_resource_vods(
            vods, item, "tmdb:tv:101", {"vod_name": "测试剧集"}
        )

        self.assertLessEqual(len(merged["vod_play_url"]), self.spider.RESOURCE_PLAY_URL_MAX_LENGTH)
        self.assertTrue(all(
            len(flag["urls"]) <= self.spider.RESOURCE_PLAY_URL_MAX_LENGTH
            for flag in merged["vodFlags"]
        ))
        parsed_payloads = []
        for group in merged["vod_play_url"].split("$$$"):
            for part in group.split("#"):
                payload = self.spider._parse_followplay(part.rpartition("$")[2])
                if payload:
                    parsed_payloads.append(payload)
        self.assertFalse(any(payload.get("fallbacks") for payload in parsed_payloads))
        self.assertEqual(len(merged["vod_play_from"].split("$$$")), 3)

    def test_bound_resource_is_validated_before_global_search(self):
        self.spider._alist_tvbox_plugin = True
        self.spider._follow_memory = {"version": 2, "items": {
            "101": {
                "tmdb_id": 101,
                "title": "测试剧集",
                "alist_vod_id": "bound-resource",
                "last_play_route": {
                    "version": 1,
                    "backend": self.spider._resource_capability_identity(),
                    "resourceId": "bound-resource",
                    "resourceMode": "vod",
                    "playId": "1@bound-episode",
                    "season": 1,
                    "episode": 6,
                    "updatedAt": int(time.time()),
                },
            },
        }}
        metadata = {"list": [{
            "vod_id": "tmdb:tv:101",
            "vod_name": "测试剧集",
            "vod_pic": "poster.jpg",
            "vod_year": "2026",
        }]}
        validated = {"list": [{
            "vod_name": "测试剧集",
            "vod_play_from": "4K线路",
            "vod_play_url": "S01E06$1@bound-episode",
        }]}
        rewritten = {
            "vod_play_from": "4K线路",
            "vod_play_url": "S01E06$bound-packed",
            "resource_id": "bound-resource",
            "group_seasons": [1],
            "group_providers": ["quark"],
            "group_quality": [{"resolution": 20, "total": 70}],
        }
        self.spider._atvp_history_snapshot = Mock(return_value=[])
        self.spider._resource_detail = Mock(return_value=validated)
        self.spider._validated_playable_detail = Mock(return_value=validated)
        self.spider._rewrite_resource_vod = Mock(return_value=rewritten)
        self.spider._merge_resource_vods = Mock(return_value={"vod_name": "测试剧集", "vod_play_from": "4K线路"})
        self.spider._resource_candidates = Mock(return_value=[])

        result = self.spider._alist_detail_from_metadata("tmdb:tv:101", metadata)

        self.assertEqual(result["list"][0]["vod_play_from"], "4K线路")
        bound_row = self.spider._resource_detail.call_args.args[0]
        self.assertEqual(bound_row["vod_id"], "bound-resource")
        self.assertEqual(bound_row["_resource_mode"], "vod")
        self.assertEqual(
            self.spider._validated_playable_detail.call_args.kwargs["preferred_route"]["playId"],
            "1@bound-episode",
        )
        self.spider._resource_candidates.assert_called_once()

    def test_valid_bound_route_keeps_two_backups_and_bound_episode_first(self):
        self.spider._alist_tvbox_plugin = True
        self.spider.route_preheat = False
        self.spider.resource_limit = 3
        self.spider._follow_memory = {"version": 2, "items": {
            "101": {
                "tmdb_id": 101,
                "title": "测试剧集",
                "alist_vod_id": "bound-resource",
                "last_play_route": {
                    "version": 1,
                    "backend": self.spider._resource_capability_identity(),
                    "resourceId": "bound-resource",
                    "resourceMode": "vod",
                    "playId": "1@bound-episode-6",
                    "season": 1,
                    "episode": 6,
                    "updatedAt": int(time.time()),
                },
            },
        }}
        self.spider._atvp_history_snapshot = Mock(return_value=[])
        self.spider._resource_candidates = Mock(return_value=[
            {"vod_id": "backup-a", "_resource_mode": "vod"},
            {"vod_id": "backup-b", "_resource_mode": "vod"},
        ])
        details = {
            "bound-resource": {"list": [{"vod_play_url": "S01E01$1@bound-1#S01E06$1@bound-episode-6"}]},
            "backup-a": {"list": [{"vod_play_url": "S01E06$1@backup-a"}]},
            "backup-b": {"list": [{"vod_play_url": "S01E06$1@backup-b"}]},
        }
        self.spider._resource_detail = Mock(side_effect=lambda row, deadline=None: details[row["vod_id"]])
        self.spider._validated_playable_detail = Mock(side_effect=lambda detail, *_args, **_kwargs: detail)
        rewritten = {
            "bound-resource": {
                "vod_play_from": "绑定720P",
                "vod_play_url": "S01E01$bound-1#S01E06$bound-6",
                "resource_id": "bound-resource",
                "group_seasons": [1],
                "group_providers": ["quark"],
                "group_quality": [{"resolution": 12, "total": 60}],
            },
            "backup-a": {
                "vod_play_from": "4K备选",
                "vod_play_url": "S01E06$backup-a",
                "resource_id": "backup-a",
                "group_seasons": [1],
                "group_providers": ["baidu"],
                "group_quality": [{"resolution": 20, "total": 90}],
            },
            "backup-b": {
                "vod_play_from": "1440P备选",
                "vod_play_url": "S01E06$backup-b",
                "resource_id": "backup-b",
                "group_seasons": [1],
                "group_providers": ["ali"],
                "group_quality": [{"resolution": 18, "total": 80}],
            },
        }
        self.spider._rewrite_resource_vod = Mock(
            side_effect=lambda _vod, _item, resource_id, **_kwargs: rewritten[resource_id]
        )

        result = self.spider._alist_detail_from_metadata(
            "tmdb:tv:101",
            {"list": [{"vod_id": "tmdb:tv:101", "vod_name": "测试剧集"}]},
        )

        sources = result["list"][0]["vod_play_from"].split("$$$")
        self.assertEqual(len(sources), 3)
        self.assertTrue(sources[0].startswith("继续播放"))
        self.assertIn("绑定720P", "$$$".join(sources))
        self.assertIn("4K备选", "$$$".join(sources))
        self.assertIn("1440P备选", "$$$".join(sources))
        self.assertIn("S01E06", result["list"][0]["vod_play_url"].split("$$$")[0])
        self.assertIn("S01E01", result["list"][0]["vod_play_url"].split("$$$")[0])
        self.spider._resource_candidates.assert_called_once()

    def test_persisted_route_is_probed_first_after_process_restart(self):
        self.spider._alist_tvbox_plugin = True
        self.spider.atvp_api = "https://atvp.example"
        self.spider.atvp_token = "token"
        self.spider._follow_memory = {"version": 2, "items": {
            "101": {
                "tmdb_id": 101,
                "title": "测试剧集",
                "latest_episode": "S01E01",
                "last_play_route": {
                    "version": 1,
                    "backend": self.spider._resource_capability_identity(),
                    "resourceId": "bound-resource",
                    "resourceMode": "vod",
                    "playId": "1@episode-6",
                    "season": 1,
                    "episode": 6,
                    "updatedAt": int(time.time()),
                },
            },
        }}
        self.assertEqual(self.spider._route_probe_cache, {})
        self.spider._atvp_history_snapshot = Mock(return_value=[])
        self.spider._resource_detail = Mock(return_value={"list": [{
            "vod_name": "测试剧集",
            "vod_play_from": "绑定线路",
            "vod_play_url": "S01E01$1@episode-1#S01E06$1@episode-6",
        }]})
        played = []

        def atvp_play(play_id, **_kwargs):
            played.append(play_id)
            return {"parse": 0, "url": "https://cdn.example/%s.m3u8" % play_id, "header": {}}

        self.spider._atvp_play = Mock(side_effect=atvp_play)
        self.spider._probe_media_output = Mock(return_value={
            "checked_at": time.time(),
            "reachable": True,
            "startup_ms": 100,
            "height": 1080,
            "codec": "h264",
            "output": {"parse": 0, "url": "https://cdn.example/episode-6.m3u8", "header": {}},
        })
        self.spider._resource_candidates = Mock(return_value=[])

        result = self.spider._alist_detail_from_metadata(
            "tmdb:tv:101",
            {"list": [{"vod_id": "tmdb:tv:101", "vod_name": "测试剧集"}]},
        )

        self.assertTrue(result["list"][0]["vod_play_url"])
        self.assertEqual(played[0], "1@episode-6")
        self.spider._resource_candidates.assert_called_once()

    def test_persisted_route_group_is_validated_before_current_episode_group(self):
        self.spider.atvp_api = "https://atvp.example"
        self.spider.atvp_token = "token"
        played = []
        self.spider._atvp_play = Mock(side_effect=lambda play_id, **_kwargs: (
            played.append(play_id)
            or {"parse": 0, "url": "https://cdn.example/%s.m3u8" % play_id, "header": {}}
        ))
        self.spider._probe_media_output = Mock(return_value={
            "checked_at": time.time(), "reachable": True, "startup_ms": 100,
            "output": {"parse": 0, "url": "https://cdn.example/video.m3u8", "header": {}},
        })

        result = self.spider._validated_playable_detail(
            {"list": [{
                "vod_play_from": "当前集线路$$$上次线路",
                "vod_play_url": "S01E01$1@episode-1$$$S01E06$1@episode-6",
            }]},
            {"latest_episode": "S01E01", "trackingSeason": 1},
            time.monotonic() + 10,
            1,
            resource_id="bound-resource",
            resource_mode="vod",
            preferred_route={
                "resourceId": "bound-resource", "resourceMode": "vod",
                "playId": "1@episode-6", "season": 1, "episode": 6,
            },
        )

        self.assertIsNotNone(result)
        self.assertEqual(played[0], "1@episode-6")
        self.assertEqual(result["list"][0]["vod_play_from"], "上次线路")

    def test_reused_play_id_is_not_bound_to_a_different_episode_label(self):
        self.spider.atvp_api = "https://atvp.example"
        self.spider.atvp_token = "token"
        played = []
        self.spider._atvp_play = Mock(side_effect=lambda play_id, **_kwargs: (
            played.append(play_id)
            or {"parse": 0, "url": "https://cdn.example/%s.m3u8" % play_id, "header": {}}
        ))
        self.spider._probe_media_output = Mock(return_value={
            "checked_at": time.time(), "reachable": True, "startup_ms": 100,
            "output": {"parse": 0, "url": "https://cdn.example/video.m3u8", "header": {}},
        })

        self.spider._validated_playable_detail(
            {"list": [{
                "vod_play_from": "变更后线路",
                "vod_play_url": "S01E01$1@reused#S01E06$1@episode-6-new",
            }]},
            {"latest_episode": "S01E06", "trackingSeason": 1},
            time.monotonic() + 10,
            1,
            resource_id="bound-resource",
            resource_mode="vod",
            preferred_route={
                "resourceId": "bound-resource", "resourceMode": "vod",
                "playId": "1@reused", "season": 1, "episode": 6,
            },
        )

        self.assertEqual(played[0], "1@episode-6-new")

    def test_bound_probe_is_not_trusted_when_detail_route_changed(self):
        self.spider._alist_tvbox_plugin = True
        self.spider._follow_memory = {"version": 2, "items": {
            "101": {
                "tmdb_id": 101,
                "title": "测试剧集",
                "alist_vod_id": "bound-resource",
                "last_play_route": {
                    "version": 1,
                    "resourceId": "bound-resource",
                    "resourceMode": "vod",
                    "playId": "1@old-episode",
                    "season": 1,
                    "episode": 6,
                    "updatedAt": int(time.time()),
                },
            },
        }}
        self.spider._cache_route_probe(
            "1@old-episode",
            {
                "checked_at": time.time(),
                "reachable": True,
                "output": {"parse": 0, "url": "https://cdn.example/old.m3u8", "header": {}},
            },
            resource_id="bound-resource",
            resource_mode="vod",
        )
        self.spider._atvp_history_snapshot = Mock(return_value=[])
        self.spider._resource_detail = Mock(return_value={"list": [{
            "vod_name": "测试剧集",
            "vod_play_from": "已变更线路",
            "vod_play_url": "S01E06$1@new-episode",
        }]})
        self.spider._validated_playable_detail = Mock(return_value=None)
        self.spider._resource_candidates = Mock(return_value=[])
        self.spider._supplement_resource_state = Mock(return_value=(False, False))
        self.spider._schedule_bound_route_replacement = Mock(return_value=True)

        result = self.spider._alist_detail_from_metadata(
            "tmdb:tv:101",
            {"list": [{"vod_id": "tmdb:tv:101", "vod_name": "测试剧集"}]},
        )

        self.spider._validated_playable_detail.assert_called_once()
        self.assertEqual(result["list"][0]["vod_play_from"], "")
        self.assertIn("原绑定线路失效，后台备选线路验证中", result["list"][0]["vod_director"])
        replacement_item, replacement_id = self.spider._schedule_bound_route_replacement.call_args.args
        self.assertEqual(replacement_id, "bound-resource")
        self.assertEqual(replacement_item["tmdb_id"], 101)
        self.assertEqual(replacement_item.get("history_episode", ""), "")

    def test_persisted_binding_remains_valid_without_route_ttl(self):
        self.spider.atvp_api = "https://atvp.example"
        self.spider.atvp_token = "token"
        self.spider._follow_memory = {"version": 2, "items": {
            "101": {
                "tmdb_id": 101,
                "title": "测试剧集",
                "alist_vod_id": "bound-resource",
                "alist_resource_mode": "vod",
                "last_play_route": {
                    "resourceId": "bound-resource",
                    "resourceMode": "vod",
                    "playId": "1@episode-6",
                    "season": 1,
                    "episode": 6,
                    "updatedAt": 1,
                },
            },
        }}

        row = self.spider._bound_resource_row({
            "tmdb_id": 101,
            "source_id": "tmdb:tv:101",
            "alist_vod_id": "bound-resource",
            "alist_resource_mode": "vod",
        })

        self.assertEqual(row["vod_id"], "bound-resource")
        self.assertEqual(row["_resource_mode"], "vod")

    def test_stale_binding_schedules_background_replacement_and_keeps_progress(self):
        self.spider._alist_tvbox_plugin = True
        self.spider.atvp_api = "https://atvp.example"
        self.spider.atvp_token = "token"
        self.spider._follow_memory = {"version": 2, "items": {
            "101": {
                "tmdb_id": 101,
                "source_id": "tmdb:tv:101",
                "title": "测试剧集",
                "history_episode": "S01E06",
                "history_position": 321000,
                "history_duration": 1200000,
                "alist_vod_id": "old-resource",
                "last_play_route": {
                    "resourceId": "old-resource",
                    "resourceMode": "vod",
                    "playId": "1@old-episode",
                    "season": 1,
                    "episode": 6,
                },
            },
        }}
        self.spider._resource_candidates = Mock(return_value=[{
            "vod_id": "replacement-resource", "_resource_mode": "pansou",
        }])
        self.spider._resource_detail = Mock(return_value={"list": [{
            "vod_name": "测试剧集", "vod_play_from": "备选网盘",
            "vod_play_url": "S01E06$1@replacement-episode",
        }]})
        self.spider._validated_playable_detail = Mock(return_value={"list": [{
            "vod_name": "测试剧集", "vod_play_from": "备选网盘",
            "vod_play_url": "S01E06$1@replacement-episode",
        }]})
        self.spider._store_validated_resource_detail = Mock(return_value=True)
        self.spider._schedule_active_detail_refresh = Mock(return_value=True)

        self.assertTrue(self.spider._schedule_bound_route_replacement(
            dict(self.spider._follow_memory["items"]["101"]), "old-resource",
        ))
        deadline = time.time() + 2
        while self.spider._bound_replacement_jobs and time.time() < deadline:
            time.sleep(0.01)

        item = self.spider._follow_memory["items"]["101"]
        self.assertFalse(self.spider._bound_replacement_jobs)
        self.assertEqual(item["alist_vod_id"], "replacement-resource")
        self.assertEqual(item["alist_resource_mode"], "pansou")
        self.assertEqual(item["history_episode"], "S01E06")
        self.assertEqual(item["history_position"], 321000)
        self.assertNotIn("last_play_route", item)
        self.assertEqual(self.spider._bound_resource_row(item)["vod_id"], "replacement-resource")
        self.spider._schedule_active_detail_refresh.assert_called_once()

    def test_old_replacement_worker_cannot_clear_new_lifecycle_job_owner(self):
        self.spider._alist_tvbox_plugin = True
        item = {
            "tmdb_id": 101,
            "source_id": "tmdb:tv:101",
            "title": "测试剧集",
            "alist_vod_id": "old-resource",
        }
        old_started = MODULE.threading.Event()
        new_started = MODULE.threading.Event()
        old_release = MODULE.threading.Event()
        new_release = MODULE.threading.Event()
        call_lock = MODULE.threading.Lock()
        call_count = {"value": 0}

        def candidates(_item, deadline=None):
            with call_lock:
                call_count["value"] += 1
                current = call_count["value"]
            if current == 1:
                old_started.set()
                old_release.wait(1)
            else:
                new_started.set()
                new_release.wait(1)
            return []

        self.spider._resource_candidates = Mock(side_effect=candidates)
        self.assertTrue(self.spider._schedule_bound_route_replacement(item, "old-resource"))
        self.assertTrue(old_started.wait(1))

        self.spider.init({"atvp_plugin_mode": "alist-tvbox-raw"})
        self.assertTrue(self.spider._schedule_bound_route_replacement(item, "old-resource"))
        self.assertTrue(new_started.wait(1))
        job_key = self.spider._bound_replacement_key(item, "old-resource")
        new_job_owner = self.spider._bound_replacement_jobs[job_key]

        old_release.set()
        deadline = time.time() + 1
        while self.spider._bound_replacement_jobs.get(job_key) is not new_job_owner and time.time() < deadline:
            time.sleep(0.01)

        self.assertIs(self.spider._bound_replacement_jobs.get(job_key), new_job_owner)
        new_release.set()
        deadline = time.time() + 1
        while self.spider._bound_replacement_jobs and time.time() < deadline:
            time.sleep(0.01)
        self.assertEqual(self.spider._bound_replacement_jobs, {})

    def test_stale_backend_binding_does_not_fall_back_to_old_resource_id(self):
        self.spider.atvp_api = "https://new-atvp.example"
        self.spider.atvp_token = "new-token"
        self.spider._follow_memory = {"version": 2, "items": {
            "101": {
                "tmdb_id": 101,
                "title": "测试剧集",
                "alist_vod_id": "old-resource",
                "last_play_route": {
                    "backend": "old-backend",
                    "resourceId": "old-resource",
                    "resourceMode": "vod",
                    "playId": "1@old",
                },
            },
        }}

        self.assertIsNone(self.spider._bound_resource_row({"tmdb_id": 101, "source_id": "tmdb:tv:101"}))

    def test_detail_keeps_primary_plus_two_independent_routes_resolution_first(self):
        self.spider.route_preheat = False
        self.spider.resource_limit = 5
        item = {"media_type": "tv", "tmdb_id": 101, "title": "测试剧集", "trackingSeason": 1}
        qualities = [
            ("720P", 12, 99),
            ("1080P快速", 16, 95),
            ("1440P", 18, 80),
            ("4K较慢", 20, 72),
        ]
        vods = []
        for index, (source, resolution, total) in enumerate(qualities):
            vods.append({
                "vod_play_from": source,
                "vod_play_url": "S01E01$route-%d" % index,
                "resource_id": "resource-%d" % index,
                "group_seasons": [1],
                "group_providers": ["provider-%d" % index],
                "group_quality": [{
                    "resolution": resolution,
                    "total": total,
                    "startup": total,
                    "stability": 10,
                }],
            })

        merged = self.spider._merge_resource_vods(
            vods, item, "tmdb:tv:101", {"vod_name": "测试剧集", "vod_remarks": "原摘要"},
        )

        sources = merged["vod_play_from"].split("$$$")
        self.assertEqual(len(sources), 3)
        self.assertIn("4K较慢", sources[0])
        self.assertIn("1440P", sources[1])
        self.assertIn("1080P快速", sources[2])
        self.assertNotIn("同集备用线路", merged["vod_remarks"])
        for group in merged["vod_play_url"].split("$$$"):
            payload = self.spider._parse_followplay(group.split("#")[-1].rpartition("$")[2])
            self.assertFalse((payload or {}).get("fallbacks"))

    def test_single_resource_keeps_five_candidates_until_resolution_selection(self):
        item = {"media_type": "tv", "tmdb_id": 101, "title": "测试剧集", "trackingSeason": 1}
        vod = {
            "vod_name": "测试剧集",
            "vod_play_from": "720P$$$1080P$$$1440P$$$4K",
            "vod_play_url": "$$$".join(
                "S01E01$1@route-%d" % index for index in range(4)
            ),
            "_route_quality": [
                {"resolution": 12, "total": 99, "startup": 99, "stability": 10},
                {"resolution": 16, "total": 95, "startup": 95, "stability": 10},
                {"resolution": 18, "total": 80, "startup": 80, "stability": 10},
                {"resolution": 20, "total": 72, "startup": 72, "stability": 10},
            ],
        }

        rewritten = self.spider._rewrite_resource_vod(vod, item, "resource-101", mode="vod", validated=True)
        merged = self.spider._merge_resource_vods(
            [rewritten], item, "tmdb:tv:101", {"vod_name": "测试剧集"},
        )

        sources = merged["vod_play_from"].split("$$$")
        self.assertEqual(len(sources), 3)
        self.assertIn("4K", sources[0])
        self.assertIn("1440P", sources[1])
        self.assertIn("1080P", sources[2])

    def test_candidate_pool_trim_is_not_reported_as_episode_truncation(self):
        item = {"media_type": "tv", "tmdb_id": 101, "title": "测试剧集", "trackingSeason": 1}
        sources = ["720P", "1080P", "1440P", "4K", "4K高码", "备用低清"]
        vod = {
            "vod_name": "测试剧集",
            "vod_play_from": "$$$".join(sources),
            "vod_play_url": "$$$".join(
                "S01E01$1@route-%d" % index for index in range(len(sources))
            ),
            "_route_quality": [
                {"resolution": 12 + index, "total": 70 + index, "startup": 70, "stability": 10}
                for index in range(len(sources))
            ],
        }

        rewritten = self.spider._rewrite_resource_vod(vod, item, "resource-101", mode="vod")
        merged = self.spider._merge_resource_vods(
            [rewritten], item, "tmdb:tv:101", {"vod_name": "测试剧集"},
        )

        self.assertTrue(rewritten["_route_candidates_limited"])
        self.assertFalse(rewritten["_resource_limited"])
        self.assertIn("线路候选已按清晰度筛选", merged["vod_remarks"])
        self.assertNotIn("资源分集过多 已截断", merged["vod_remarks"])

    def test_detail_collects_candidate_pool_before_selecting_three_routes(self):
        self.spider._alist_tvbox_plugin = True
        self.spider.route_preheat = False
        self.spider.resource_limit = 3
        self.spider._atvp_history_snapshot = Mock(return_value=[])
        candidates = [{"vod_id": "resource-%d" % index} for index in range(4)]
        qualities = {
            "resource-0": ("720P", 12, 99),
            "resource-1": ("1080P", 16, 95),
            "resource-2": ("1440P", 18, 80),
            "resource-3": ("4K", 20, 72),
        }
        self.spider._resource_candidates = Mock(return_value=candidates)
        self.spider._resource_detail = Mock(side_effect=lambda row, deadline=None: {
            "list": [{"vod_name": "测试剧集", "vod_play_url": "S01E01$1@raw"}]
        })

        def rewrite(_vod, _item, resource_id, **_kwargs):
            source, resolution, total = qualities[resource_id]
            return {
                "vod_play_from": source,
                "vod_play_url": "S01E01$route-%s" % resource_id,
                "resource_id": resource_id,
                "group_seasons": [1],
                "group_providers": ["provider-%s" % resource_id],
                "group_quality": [{
                    "resolution": resolution,
                    "total": total,
                    "startup": total,
                    "stability": 10,
                }],
            }

        self.spider._rewrite_resource_vod = Mock(side_effect=rewrite)

        result = self.spider._alist_detail_from_metadata(
            "tmdb:tv:101",
            {"list": [{"vod_id": "tmdb:tv:101", "vod_name": "测试剧集"}]},
        )

        sources = result["list"][0]["vod_play_from"].split("$$$")
        self.assertEqual(self.spider._resource_detail.call_count, 4)
        self.assertEqual(len(sources), 3)
        self.assertIn("4K", sources[0])
        self.assertIn("1440P", sources[1])
        self.assertIn("1080P", sources[2])
        self.assertNotIn("资源分集过多 已截断", result["list"][0]["vod_remarks"])
        self.assertIn("线路候选已按清晰度筛选", result["list"][0]["vod_remarks"])

    def test_removed_shared_route_cache_symbols_stay_out_of_plugin(self):
        source = SOURCE.read_text(encoding="utf-8")
        for symbol in (
                "_publish_route", "_schedule_route_cache_write", "_local_cache_set",
                "_local_cache_get", "_shared_filter_route_candidates", "_followplay_with_fallbacks",
        ):
            self.assertNotIn(symbol, source)

    def test_player_does_not_mix_independent_or_shared_fallback_routes(self):
        item = {"media_type": "tv", "tmdb_id": 101, "title": "测试剧集"}
        play_id = self.spider._build_followplay(
            "1@primary", item, "resource-primary", 1, 6, "S01E06",
        )
        self.spider._atvp_play = Mock(side_effect=RuntimeError("primary failed"))

        result = self.spider.playerContent("测试线路", play_id, [])

        self.assertEqual(self.spider._atvp_play.call_count, 1)
        self.spider._atvp_play.assert_called_once_with("1@primary", deadline=self.spider._atvp_play.call_args.kwargs["deadline"])
        self.assertIn("已尝试 1 条线路", result["msg"])

    def test_successful_playback_waits_before_history_sync(self):
        self.spider._alist_tvbox_plugin = True
        self.spider._schedule_playback_sync_check = Mock(return_value=True)
        self.spider._trigger_history_sync_now = Mock(return_value=True)
        parsed = {
            "tmdbId": 101,
            "sourceId": "tmdb:tv:101",
            "resourceId": "resource-101",
            "resourceMode": "vod",
            "season": 1,
            "episode": 6,
            "name": "S01E06",
        }

        self.assertTrue(self.spider._register_playback_sync_window(parsed))

        self.spider._schedule_playback_sync_check.assert_called_once()
        self.assertEqual(
            self.spider._schedule_playback_sync_check.call_args.args[1],
            self.spider.PLAYBACK_SYNC_MIN_SECONDS,
        )
        scheduled_owner = self.spider._schedule_playback_sync_check.call_args.kwargs["expected_owner"]
        self.assertIs(
            scheduled_owner,
            next(iter(self.spider._playback_sync_pending.values()))["owner"],
        )
        self.spider._trigger_history_sync_now.assert_not_called()

    def test_failed_initial_playback_timer_removes_pending_window(self):
        self.spider._alist_tvbox_plugin = True
        self.spider._schedule_playback_sync_check = Mock(return_value=False)
        parsed = {
            "tmdbId": 101,
            "sourceId": "tmdb:tv:101",
            "resourceId": "resource-101",
            "resourceMode": "vod",
            "season": 1,
            "episode": 6,
        }

        self.assertFalse(self.spider._register_playback_sync_window(parsed))

        self.assertEqual(self.spider._playback_sync_pending, {})

    def test_playback_exit_after_eight_minutes_triggers_history_sync(self):
        self.spider._alist_tvbox_plugin = True
        owner = object()
        self.spider._playback_sync_pending["pending"] = {
            "owner": owner,
            "started_at": time.time() - self.spider.PLAYBACK_SYNC_MIN_SECONDS - 1,
            "tmdb_id": 101,
            "source_id": "tmdb:tv:101",
            "title": "测试剧集",
            "resource_id": "resource-101",
            "season": 1,
            "episode": 6,
        }
        self.spider._playback_activity_active = Mock(return_value=False)
        self.spider._capture_native_history = Mock(return_value=[{"key": "history-1"}])
        self.spider._atvp_history_for_item = Mock(return_value={"position": 500000})
        self.spider._trigger_history_sync_now = Mock(return_value=True)

        self.assertTrue(self.spider._playback_sync_check("pending"))

        self.spider._trigger_history_sync_now.assert_called_once_with()
        self.assertNotIn("pending", self.spider._playback_sync_pending)

    def test_stale_playback_timer_token_cannot_consume_new_pending_window(self):
        self.spider._playback_sync_pending["pending"] = {"started_at": time.time()}
        self.spider._playback_sync_tokens["pending"] = object()

        self.assertFalse(self.spider._playback_sync_check("pending", object()))

        self.assertIn("pending", self.spider._playback_sync_pending)

    def test_navigation_flush_cannot_duplicate_inflight_playback_sync_check(self):
        started = MODULE.threading.Event()
        release = MODULE.threading.Event()
        token = object()
        self.spider._playback_sync_pending["pending"] = {
            "owner": object(),
            "started_at": time.time(),
        }
        self.spider._playback_sync_tokens["pending"] = token

        def owned(_key, _marker):
            started.set()
            release.wait(1)
            return True

        self.spider._playback_sync_check_owned = Mock(side_effect=owned)
        first = MODULE.threading.Thread(
            target=self.spider._playback_sync_check, args=("pending", token),
        )
        first.start()
        self.assertTrue(started.wait(1))

        self.spider._flush_playback_sync_on_navigation()
        time.sleep(0.05)

        self.assertEqual(self.spider._playback_sync_check_owned.call_count, 1)
        release.set()
        first.join(1)

    def test_navigation_flush_cannot_duplicate_history_sync_trigger(self):
        started = MODULE.threading.Event()
        release = MODULE.threading.Event()
        owner = object()
        token = object()
        self.spider._playback_sync_pending["pending"] = {
            "owner": owner,
            "started_at": time.time() - self.spider.PLAYBACK_SYNC_MIN_SECONDS - 1,
            "tmdb_id": 101,
            "source_id": "tmdb:tv:101",
            "resource_id": "resource-101",
            "season": 1,
            "episode": 6,
        }
        self.spider._playback_sync_tokens["pending"] = token
        self.spider._playback_activity_active = Mock(return_value=False)

        def capture():
            started.set()
            release.wait(1)
            return [{"key": "history-1"}]

        self.spider._capture_native_history = Mock(side_effect=capture)
        self.spider._atvp_history_for_item = Mock(return_value={"position": 500000})
        self.spider._trigger_history_sync_now = Mock(return_value=True)
        first = MODULE.threading.Thread(
            target=self.spider._playback_sync_check, args=("pending", token),
        )
        first.start()
        self.assertTrue(started.wait(1))

        self.spider._flush_playback_sync_on_navigation()
        time.sleep(0.05)
        release.set()
        first.join(1)

        self.assertEqual(self.spider._capture_native_history.call_count, 1)
        self.spider._trigger_history_sync_now.assert_called_once_with()

    def test_navigation_flush_does_not_cancel_new_timer_while_old_check_is_inflight(self):
        started = MODULE.threading.Event()
        release = MODULE.threading.Event()
        old_owner = object()
        old_token = object()
        self.spider._playback_sync_pending["pending"] = {
            "owner": old_owner,
            "started_at": time.time() - self.spider.PLAYBACK_SYNC_MIN_SECONDS - 1,
            "tmdb_id": 101,
            "source_id": "tmdb:tv:101",
            "resource_id": "old-resource",
            "season": 1,
            "episode": 6,
        }
        self.spider._playback_sync_tokens["pending"] = old_token
        self.spider._playback_activity_active = Mock(return_value=False)

        def capture():
            started.set()
            release.wait(1)
            return [{"key": "history-1"}]

        self.spider._capture_native_history = Mock(side_effect=capture)
        self.spider._atvp_history_for_item = Mock(return_value={"position": 500000})
        first = MODULE.threading.Thread(
            target=self.spider._playback_sync_check, args=("pending", old_token),
        )
        first.start()
        self.assertTrue(started.wait(1))

        new_owner = object()
        new_token = object()
        new_timer = Mock()
        with self.spider._playback_sync_lock:
            self.spider._playback_sync_pending["pending"] = {
                "owner": new_owner,
                "started_at": time.time(),
            }
            self.spider._playback_sync_timers["pending"] = new_timer
            self.spider._playback_sync_tokens["pending"] = new_token

        self.spider._flush_playback_sync_on_navigation()
        release.set()
        first.join(1)

        new_timer.cancel.assert_not_called()
        self.assertIs(self.spider._playback_sync_pending["pending"]["owner"], new_owner)
        self.assertIs(self.spider._playback_sync_timers["pending"], new_timer)
        self.assertIs(self.spider._playback_sync_tokens["pending"], new_token)

    def test_destroy_during_history_capture_cannot_reschedule_old_window(self):
        started = MODULE.threading.Event()
        release = MODULE.threading.Event()
        owner = object()
        token = object()
        self.spider._playback_sync_pending["pending"] = {
            "owner": owner,
            "started_at": time.time() - self.spider.PLAYBACK_SYNC_MIN_SECONDS - 1,
            "tmdb_id": 101,
            "source_id": "tmdb:tv:101",
            "resource_id": "resource-101",
            "season": 1,
            "episode": 6,
        }
        self.spider._playback_sync_tokens["pending"] = token
        self.spider._playback_activity_active = Mock(return_value=False)

        def capture():
            started.set()
            release.wait(1)
            return [{"key": "history-1"}]

        self.spider._capture_native_history = Mock(side_effect=capture)
        self.spider._atvp_history_for_item = Mock(return_value={})
        first = MODULE.threading.Thread(
            target=self.spider._playback_sync_check, args=("pending", token),
        )
        first.start()
        self.assertTrue(started.wait(1))

        self.spider.destroy()
        release.set()
        first.join(1)

        self.assertEqual(self.spider._playback_sync_pending, {})
        self.assertEqual(self.spider._playback_sync_timers, {})
        self.assertEqual(self.spider._playback_sync_tokens, {})
        self.assertEqual(self.spider._playback_sync_inflight, {})

    def test_old_callback_finally_cannot_clear_new_lifecycle_inflight_owner(self):
        old_started = MODULE.threading.Event()
        new_started = MODULE.threading.Event()
        old_release = MODULE.threading.Event()
        new_release = MODULE.threading.Event()
        old_owner = object()
        new_owner = object()
        old_token = object()
        new_token = object()

        def owned(_key, marker):
            if marker.get("owner") is old_owner:
                old_started.set()
                old_release.wait(1)
            else:
                new_started.set()
                new_release.wait(1)
            return True

        self.spider._playback_sync_check_owned = Mock(side_effect=owned)
        self.spider._playback_sync_pending["pending"] = {
            "owner": old_owner,
            "started_at": time.time(),
        }
        self.spider._playback_sync_tokens["pending"] = old_token
        old_thread = MODULE.threading.Thread(
            target=self.spider._playback_sync_check, args=("pending", old_token),
        )
        old_thread.start()
        self.assertTrue(old_started.wait(1))

        self.spider.init({})
        self.spider._playback_sync_pending["pending"] = {
            "owner": new_owner,
            "started_at": time.time(),
        }
        self.spider._playback_sync_tokens["pending"] = new_token
        new_thread = MODULE.threading.Thread(
            target=self.spider._playback_sync_check, args=("pending", new_token),
        )
        new_thread.start()
        self.assertTrue(new_started.wait(1))

        old_release.set()
        old_thread.join(1)

        self.assertIs(self.spider._playback_sync_inflight.get("pending"), new_owner)
        new_release.set()
        new_thread.join(1)
        self.assertEqual(self.spider._playback_sync_inflight, {})

    def test_init_and_destroy_clear_playback_sync_state(self):
        first_timer = Mock()
        self.spider._playback_sync_pending["pending"] = {"owner": object()}
        self.spider._playback_sync_timers["pending"] = first_timer
        self.spider._playback_sync_tokens["pending"] = object()
        self.spider._playback_sync_inflight["pending"] = self.spider._playback_sync_pending["pending"]["owner"]

        self.spider.init({})

        first_timer.cancel.assert_called_once_with()
        self.assertEqual(self.spider._playback_sync_pending, {})
        self.assertEqual(self.spider._playback_sync_timers, {})
        self.assertEqual(self.spider._playback_sync_tokens, {})
        self.assertEqual(self.spider._playback_sync_inflight, {})

        second_timer = Mock()
        self.spider._playback_sync_pending["pending"] = {"owner": object()}
        self.spider._playback_sync_timers["pending"] = second_timer
        self.spider._playback_sync_tokens["pending"] = object()
        self.spider._playback_sync_inflight["pending"] = self.spider._playback_sync_pending["pending"]["owner"]

        self.spider.destroy()

        second_timer.cancel.assert_called_once_with()
        self.assertEqual(self.spider._playback_sync_pending, {})
        self.assertEqual(self.spider._playback_sync_timers, {})
        self.assertEqual(self.spider._playback_sync_tokens, {})
        self.assertEqual(self.spider._playback_sync_inflight, {})

    def test_history_sync_failure_keeps_pending_window_for_retry(self):
        owner = object()
        self.spider._playback_sync_pending["pending"] = {
            "owner": owner,
            "started_at": time.time() - self.spider.PLAYBACK_SYNC_MIN_SECONDS - 1,
            "tmdb_id": 101,
            "source_id": "tmdb:tv:101",
            "resource_id": "resource-101",
            "season": 1,
            "episode": 6,
        }
        self.spider._playback_activity_active = Mock(return_value=False)
        self.spider._capture_native_history = Mock(return_value=[{"key": "history-1"}])
        self.spider._atvp_history_for_item = Mock(return_value={"position": 500000})
        self.spider._trigger_history_sync_now = Mock(return_value=False)
        self.spider._schedule_playback_sync_check = Mock(return_value=True)

        self.assertTrue(self.spider._playback_sync_check("pending"))

        self.assertIn("pending", self.spider._playback_sync_pending)
        self.spider._schedule_playback_sync_check.assert_called_once_with(
            "pending", self.spider.PLAYBACK_SYNC_RETRY_SECONDS, expected_owner=owner,
        )

    def test_failed_playback_timer_start_leaves_no_timer_or_token(self):
        timer = Mock()
        timer.start.side_effect = RuntimeError("thread start failed")

        with patch.object(MODULE.threading, "Timer", return_value=timer):
            self.assertFalse(self.spider._schedule_playback_sync_check("pending", 1))

        self.assertNotIn("pending", self.spider._playback_sync_timers)
        self.assertNotIn("pending", self.spider._playback_sync_tokens)

    def test_replacement_generation_guard_blocks_stale_follow_state_write(self):
        self.spider._follow_memory = {"version": 2, "items": {
            "101": {"tmdb_id": 101, "alist_vod_id": "old-resource"},
        }}
        self.spider._cache_generation = 4

        self.assertFalse(self.spider._replace_bound_resource(
            {"tmdb_id": 101},
            {"vod_id": "replacement-resource", "_resource_mode": "vod"},
            expected_generation=3,
        ))

        self.assertEqual(
            self.spider._follow_memory["items"]["101"]["alist_vod_id"],
            "old-resource",
        )

    def test_replacement_binding_guard_blocks_worker_for_old_binding(self):
        self.spider._follow_memory = {"version": 2, "items": {
            "101": {
                "tmdb_id": 101,
                "source_id": "tmdb:tv:101",
                "alist_vod_id": "new-resource",
                "last_play_route": {"resourceId": "old-resource", "resourceMode": "vod"},
            },
        }}

        self.assertFalse(self.spider._replace_bound_resource(
            {"tmdb_id": 101, "source_id": "tmdb:tv:101"},
            {"vod_id": "replacement-resource", "_resource_mode": "vod"},
            expected_bound_resource_id="old-resource",
        ))

        self.assertEqual(
            self.spider._follow_memory["items"]["101"]["alist_vod_id"],
            "new-resource",
        )

    def test_replacement_does_not_persist_signed_url_resource_id(self):
        self.spider._follow_memory = {"version": 2, "items": {
            "101": {"tmdb_id": 101, "alist_vod_id": "old-resource"},
        }}

        self.assertFalse(self.spider._replace_bound_resource(
            {"tmdb_id": 101},
            {"vod_id": "https://cdn.example/signed?token=secret", "_resource_mode": "vod"},
            expected_bound_resource_id="old-resource",
        ))

        self.assertEqual(
            self.spider._follow_memory["items"]["101"]["alist_vod_id"],
            "old-resource",
        )

    def test_replacement_rejects_embedded_and_protocol_relative_urls(self):
        for resource_id in (
                "resource|https://cdn.example/signed?token=secret",
                "//cdn.example/signed?token=secret",
        ):
            self.spider._follow_memory = {"version": 2, "items": {
                "101": {"tmdb_id": 101, "alist_vod_id": "old-resource"},
            }}

            self.assertFalse(self.spider._replace_bound_resource(
                {"tmdb_id": 101},
                {"vod_id": resource_id, "_resource_mode": "vod"},
                expected_bound_resource_id="old-resource",
            ))
            self.assertEqual(
                self.spider._follow_memory["items"]["101"]["alist_vod_id"],
                "old-resource",
            )

    def test_trigger_history_sync_clears_snapshot_cache_and_schedules_background_refresh(self):
        self.spider._alist_tvbox_plugin = True
        self.spider._ensure_atvp_connection = Mock(return_value=True)
        self.spider._schedule_atvp_history_refresh = Mock(return_value=True)
        self.spider._cache["atvp-history-snapshot"] = (time.time(), [{"key": "stale"}])
        self.spider._persistent_cache["atvp-history-snapshot"] = (time.time(), [{"key": "stale"}])

        self.assertTrue(self.spider._trigger_history_sync_now())

        self.assertNotIn("atvp-history-snapshot", self.spider._cache)
        self.assertNotIn("atvp-history-snapshot", self.spider._persistent_cache)
        self.spider._schedule_atvp_history_refresh.assert_called_once_with("atvp-history-snapshot")

    def test_successful_player_persists_refreshable_binding_without_direct_url(self):
        self.spider.atvp_api = "https://atvp.example"
        self.spider.atvp_token = "token"
        self.spider._follow_memory = {"version": 2, "items": {
            "101": {"tmdb_id": 101, "title": "测试剧集"},
        }}
        item = {"media_type": "tv", "tmdb_id": 101, "title": "测试剧集"}
        play_id = self.spider._build_followplay(
            "1@episode-6", item, "resource-101", 1, 6, "S01E06",
        )
        direct_output = {
            "parse": 0,
            "jx": 0,
            "url": "https://cdn.example/signed/video.m3u8?signature=secret",
            "header": {"User-Agent": "test"},
        }
        checked = {
            "reachable": True,
            "checked_at": time.time(),
            "startup_ms": 420,
            "height": 2160,
            "codec": "hevc",
            "subtitle": True,
            "output": direct_output,
        }
        self.spider._atvp_play = Mock(return_value=direct_output)
        self.spider._probe_media_output = Mock(return_value=checked)
        self.spider._atvp_history_snapshot = Mock(return_value=[])

        result = self.spider.playerContent("4K线路", play_id, [])

        self.assertEqual(result["url"], direct_output["url"])
        route = self.spider._follow_memory["items"]["101"]["last_play_route"]
        self.assertEqual(route["playId"], "1@episode-6")
        self.assertEqual(route["resourceId"], "resource-101")
        self.assertEqual(route["season"], 1)
        self.assertEqual(route["episode"], 6)
        self.assertNotIn("url", route)
        self.assertNotIn("output", route)
        self.assertNotIn("signature", json.dumps(route, ensure_ascii=False))
        self.assertEqual(self.spider._follow_memory["items"]["101"]["alist_vod_id"], "resource-101")
        cached = self.spider._route_probe_snapshot("1@episode-6", "resource-101", "vod")
        self.assertEqual(cached["output"]["url"], direct_output["url"])

    def test_numeric_play_id_is_persisted_and_restored(self):
        self.spider.atvp_api = "https://atvp.example"
        self.spider.atvp_token = "token"
        self.spider._follow_memory = {"version": 2, "items": {
            "101": {"tmdb_id": 101, "title": "测试剧集"},
        }}
        self.spider._persist_follow_state = Mock(return_value=True)

        self.spider._remember_successful_follow_route(
            {
                "tmdbId": 101, "resourceId": "resource-101", "resourceMode": "vod",
                "season": 1, "episode": 1,
            },
            {"resourceId": "resource-101", "name": "S01E01"},
            "123456",
            {"height": 1080, "codec": "h264", "startup_ms": 100},
        )

        self.assertEqual(
            self.spider._follow_memory["items"]["101"]["last_play_route"]["playId"],
            "123456",
        )

    def test_encoded_url_play_id_and_resource_id_are_not_persisted(self):
        self.spider.atvp_api = "https://atvp.example"
        self.spider.atvp_token = "token"
        self.spider._follow_memory = {"version": 2, "items": {
            "101": {"tmdb_id": 101, "title": "测试剧集"},
        }}
        self.spider._persist_follow_state = Mock(return_value=True)

        self.spider._remember_successful_follow_route(
            {"tmdbId": 101, "resourceMode": "vod", "season": 1, "episode": 1},
            {"resourceId": "https%25253A%25252F%25252Fcdn.example%25252Fresource"},
            "1@https%25253A%25252F%25252Fcdn.example%25252Fsigned%25253Ftoken%25253Dsecret",
            {"height": 1080, "codec": "h264", "startup_ms": 100},
        )

        self.assertNotIn("last_play_route", self.spider._follow_memory["items"]["101"])

    def test_route_name_does_not_persist_url_shaped_episode_label(self):
        self.spider.atvp_api = "https://atvp.example"
        self.spider.atvp_token = "token"
        self.spider._follow_memory = {"version": 2, "items": {
            "101": {"tmdb_id": 101, "title": "测试剧集"},
        }}
        self.spider._persist_follow_state = Mock(return_value=True)

        self.spider._remember_successful_follow_route(
            {"tmdbId": 101, "resourceMode": "vod", "season": 1, "episode": 1},
            {
                "resourceId": "resource-101",
                "name": "https://cdn.example/signed?token=secret",
            },
            "123456",
            {"height": 1080, "codec": "h264", "startup_ms": 100},
        )

        route = self.spider._follow_memory["items"]["101"]["last_play_route"]
        self.assertEqual(route["playId"], "123456")
        self.assertEqual(route["name"], "")

    def test_route_name_does_not_persist_embedded_url(self):
        self.spider.atvp_api = "https://atvp.example"
        self.spider.atvp_token = "token"
        self.spider._follow_memory = {"version": 2, "items": {
            "101": {"tmdb_id": 101, "title": "测试剧集"},
        }}
        self.spider._persist_follow_state = Mock(return_value=True)

        self.spider._remember_successful_follow_route(
            {"tmdbId": 101, "resourceMode": "vod", "season": 1, "episode": 1},
            {"resourceId": "resource-101", "name": "S01E01 https://cdn.example/signed?token=secret"},
            "123456",
            {"height": 1080, "codec": "h264", "startup_ms": 100},
        )

        self.assertEqual(
            self.spider._follow_memory["items"]["101"]["last_play_route"]["name"],
            "",
        )

    def test_route_name_does_not_persist_protocol_relative_url(self):
        self.spider.atvp_api = "https://atvp.example"
        self.spider.atvp_token = "token"
        self.spider._follow_memory = {"version": 2, "items": {
            "101": {"tmdb_id": 101, "title": "测试剧集"},
        }}

        self.spider._remember_successful_follow_route(
            {"tmdbId": 101, "resourceMode": "vod", "season": 1, "episode": 1},
            {"resourceId": "resource-101", "name": "S01E01 //cdn.example/signed?token=secret"},
            "123456",
            {"height": 1080, "codec": "h264", "startup_ms": 100},
        )

        self.assertEqual(
            self.spider._follow_memory["items"]["101"]["last_play_route"]["name"],
            "",
        )

    def test_activity_probe_without_app_instance_fails_closed(self):
        class ClassApi(object):
            @staticmethod
            def forName(name):
                return AppType() if name == "com.fongmi.android.tv.App" else object()

        class AppType(object):
            @staticmethod
            def getDeclaredFields():
                return []

        class ModifierApi(object):
            @staticmethod
            def isStatic(_value):
                return False

        java_module = types.ModuleType("java")
        java_module.jclass = lambda name: {
            "java.lang.Class": ClassApi,
            "java.lang.reflect.Modifier": ModifierApi,
        }[name]

        with patch.dict(sys.modules, {"java": java_module}):
            activity = self.spider._current_fongmi_activity()

        self.assertIs(activity, self.spider.ACTIVITY_PROBE_FAILED)

    def test_packed_resource_identity_rejects_url_and_unknown_mode(self):
        item = {"media_type": "tv", "tmdb_id": 101, "title": "测试剧集"}
        url_id = self.spider._build_followplay(
            "1@primary", item, "https://cdn.example/signed?token=secret", 1, 1, "S01E01",
        )
        bad_mode_id = self.spider._build_followplay(
            "1@primary", item, "resource-101", 1, 1, "S01E01", resource_mode="unknown",
        )
        encoded_url_id = self.spider._build_followplay(
            "1@primary", item, "https%3A%2F%2Fcdn.example%2Fsigned%3Ftoken%3Dsecret", 1, 1, "S01E01",
        )
        double_encoded_url_id = self.spider._build_followplay(
            "1@primary", item, "https%253A%252F%252Fcdn.example%252Fsigned%253Ftoken%253Dsecret", 1, 1, "S01E01",
        )

        self.assertIsNone(self.spider._parse_followplay(url_id))
        self.assertIsNone(self.spider._parse_followplay(bad_mode_id))
        self.assertIsNone(self.spider._parse_followplay(encoded_url_id))
        self.assertIsNone(self.spider._parse_followplay(double_encoded_url_id))

    def test_resource_search_and_detail_reject_unbounded_resource_ids(self):
        limit = self.spider.RESOURCE_SEARCH_RESULT_LIMIT
        rows = [
            {"vod_id": "resource-%d" % index, "vod_name": "测试剧集"}
            for index in range(limit + 20)
        ]
        rows.insert(0, {"vod_id": "x" * (self.spider.RESOURCE_ID_MAX_LENGTH + 1), "vod_name": "测试剧集"})
        self.spider._resource_capability = Mock(return_value="present")
        self.spider._resource_api_get = Mock(return_value={"list": rows})

        result = self.spider._resource_search_mode("vod", ["测试剧集", "测试别名"])

        self.assertLessEqual(len(result), limit)
        self.assertGreaterEqual(len(result), limit - 1)
        self.assertTrue(all(len(row["vod_id"]) <= self.spider.RESOURCE_ID_MAX_LENGTH for row in result))
        with self.assertRaisesRegex(RuntimeError, "资源 ID 过长"):
            self.spider._resource_detail({
                "vod_id": "x" * (self.spider.RESOURCE_ID_MAX_LENGTH + 1),
                "_resource_mode": "vod",
            }, use_validated_cache=False)

    def test_resource_api_response_has_content_length_and_stream_byte_limits(self):
        class FakeResponse:
            def __init__(self, headers, chunks):
                self.status_code = 200
                self.headers = headers
                self._chunks = chunks
                self.closed = False

            def iter_content(self, chunk_size=None):
                return iter(self._chunks)

            def close(self):
                self.closed = True

        self.spider.atvp_api = "https://atvp.example"
        self.spider.atvp_token = "token"
        self.spider._ensure_atvp_connection = Mock(return_value=True)
        self.spider._resource_capability = Mock(return_value="present")
        self.spider._mark_resource_capability = Mock()
        self.spider._atvp_session = Mock()
        oversized = FakeResponse(
            {"Content-Length": str(self.spider.RESOURCE_API_RESPONSE_MAX_BYTES + 1)},
            [],
        )
        self.spider._atvp_session.get.return_value = oversized

        with self.assertRaisesRegex(RuntimeError, "响应过大"):
            self.spider._resource_api_get("vod", {}, deadline=time.monotonic() + 5)
        self.assertTrue(oversized.closed)

        streaming = FakeResponse({}, [b"{" + b"x" * self.spider.RESOURCE_API_RESPONSE_MAX_BYTES])
        self.spider._atvp_session.get.return_value = streaming
        with self.assertRaisesRegex(RuntimeError, "响应过大"):
            self.spider._resource_api_get("vod", {}, deadline=time.monotonic() + 5)
        self.assertTrue(streaming.closed)

    def test_play_parse_and_check_links_use_bounded_json_reader(self):
        class FakeResponse:
            def __init__(self, payload):
                self.status_code = 200
                self.headers = {}
                self._payload = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.closed = False

            def iter_content(self, chunk_size=None):
                return iter([self._payload])

            def close(self):
                self.closed = True

        self.spider.atvp_api = "https://atvp.example"
        self.spider.atvp_token = "token"
        self.spider._ensure_atvp_connection = Mock(return_value=True)
        self.spider._atvp_session = Mock()
        play_response = FakeResponse({"parse": 0, "url": "https://cdn.example/video.m3u8", "header": {}})
        self.spider._atvp_session.get.return_value = play_response
        output = self.spider._atvp_play("1@episode-1", deadline=time.monotonic() + 5)
        self.assertEqual(output["url"], "https://cdn.example/video.m3u8")
        self.assertTrue(play_response.closed)
        self.assertTrue(self.spider._atvp_session.get.call_args.kwargs["stream"])

        parse_response = FakeResponse({"list": [{"vod_play_url": "S01E01$1@episode-1"}]})
        self.spider._atvp_session.post.return_value = parse_response
        candidates = self.spider._atvp_parse_candidates("https://pan.quark.cn/s/demo", deadline=time.monotonic() + 5)
        self.assertEqual(candidates, ["1@episode-1"])
        self.assertTrue(parse_response.closed)

        check_response = FakeResponse({"results": [{"url": "https://pan.quark.cn/s/demo", "state": "ok"}]})
        self.spider._atvp_session.post.return_value = check_response
        checked = self.spider._checked_resource_rows(
            [{"vod_id": "https://pan.quark.cn/s/demo"}], deadline=time.monotonic() + 5,
        )
        self.assertEqual(len(checked), 1)
        self.assertTrue(check_response.closed)

    def test_route_probe_cache_requires_resource_identity(self):
        self.spider.atvp_api = "https://atvp.example"
        self.spider.atvp_token = "token"
        probe = {
            "checked_at": time.time(),
            "reachable": True,
            "output": {"parse": 0, "url": "https://cdn.example/video.m3u8", "header": {}},
        }
        self.spider._cache_route_probe("1@same-play", probe, "resource-a", "vod")

        self.assertIsNone(self.spider._route_probe_snapshot("1@same-play"))
        self.assertIsNone(self.spider._route_probe_snapshot("1@same-play", "resource-b", "vod"))
        self.assertEqual(
            self.spider._route_probe_snapshot("1@same-play", "resource-a", "vod")["output"]["url"],
            probe["output"]["url"],
        )

    def test_route_probe_cache_prunes_expired_and_overflow_entries(self):
        self.spider.atvp_api = "https://atvp.example"
        self.spider.atvp_token = "token"
        now = time.time()
        old_key = self.spider._route_probe_key("1@old", "resource-old", "vod")
        self.spider._route_probe_cache[old_key] = {
            "checked_at": now - self.spider.route_probe_ttl - 1,
            "reachable": True,
            "output": {"url": "https://cdn.example/expired.m3u8"},
        }
        probe = {
            "checked_at": now,
            "reachable": True,
            "output": {"url": "https://cdn.example/video.m3u8"},
        }
        for index in range(self.spider.ROUTE_PROBE_CACHE_LIMIT + 8):
            self.spider._cache_route_probe("1@route-%d" % index, probe, "resource-%d" % index, "vod")

        self.assertNotIn(old_key, self.spider._route_probe_cache)
        self.assertLessEqual(len(self.spider._route_probe_cache), self.spider.ROUTE_PROBE_CACHE_LIMIT)

    def test_successful_route_binding_keeps_concurrent_follow_items(self):
        self.spider._follow_memory = {"version": 2, "items": {
            "101": {"tmdb_id": 101, "title": "甲剧"},
            "202": {"tmdb_id": 202, "title": "乙剧"},
        }}
        self.spider._persist_follow_state = Mock(return_value=True)
        barrier = MODULE.threading.Barrier(2)

        def remember(tmdb_id, resource_id):
            barrier.wait(1)
            self.spider._remember_successful_follow_route(
                {
                    "tmdbId": tmdb_id, "season": 1, "episode": 1,
                    "resourceId": resource_id, "resourceMode": "vod",
                },
                {"resourceId": resource_id, "name": "S01E01"},
                "1@%s" % resource_id,
                {"height": 1080, "codec": "h264", "startup_ms": 100},
            )

        threads = [
            MODULE.threading.Thread(target=remember, args=(101, "resource-a")),
            MODULE.threading.Thread(target=remember, args=(202, "resource-b")),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(2)

        self.assertEqual(
            self.spider._follow_memory["items"]["101"]["last_play_route"]["resourceId"],
            "resource-a",
        )
        self.assertEqual(
            self.spider._follow_memory["items"]["202"]["last_play_route"]["resourceId"],
            "resource-b",
        )

    def test_route_status_is_shown_after_director_without_replacing_summary(self):
        result = self.spider._resource_error_vod({
            "vod_name": "测试剧集",
            "vod_director": "导演甲",
            "vod_remarks": "9.1分 / 12集",
            "vod_content": "剧情简介",
        }, "线路更新中")

        self.assertEqual(result["vod_remarks"], "9.1分 / 12集")
        self.assertEqual(result["vod_director"], "导演甲 · 线路状态：线路更新中")
        self.assertIn("播放资源状态：线路更新中", result["vod_content"])
        self.assertEqual(result["vod_play_from"], "")
        self.assertEqual(result["vod_play_url"], "")

    def test_quality_scores_stay_in_backend_metadata_not_detail_source_label(self):
        quality = self.spider._route_quality_score(
            "1@quality-route",
            probe={"startup_ms": 1200, "height": 1080, "codec": "h264", "subtitle": True},
        )

        self.assertEqual(quality["startup"], 22)
        self.assertEqual(quality["codec"], 20)
        self.assertEqual(quality["resolution"], 16)
        self.assertEqual(self.spider._strip_legacy_route_quality_label("网盘候选 · 夸克"), "网盘候选 · 夸克")
        self.assertNotIn("质量", self.spider._strip_legacy_route_quality_label("网盘候选 · 夸克"))

    def test_same_title_different_years_stay_separate_candidates(self):
        self.spider._native_keep_export_java = Mock(return_value=[
            {"key": "old", "title": "同名剧 (2001)", "create_time": 10},
            {"key": "new", "title": "同名剧 (2020)", "create_time": 20},
        ])
        self.spider._native_history_export_java = Mock(return_value={"config": "{}", "rows": []})

        result = self.spider.categoryContent("follow_candidates", "1", False, {})
        candidates = [card for card in result["list"] if str(card.get("action") or "").startswith("follow-candidate:add:")]

        self.assertEqual(result["total"], 2)
        self.assertEqual(len(candidates), 2)
        self.assertEqual({"2001", "2020"}, {
            "2001" if "2001" in card["vod_remarks"] else "2020" for card in candidates
        })

    def test_follow_cache_unknown_blocks_mutation_and_persistence(self):
        original = {"version": 2, "items": {"101": {"tmdb_id": 101, "title": "旧记录"}}}
        self.spider._follow_memory = original
        self.spider.getCache = Mock(side_effect=RuntimeError("cache unavailable"))
        self.spider._load_follow_state_from_loopback = Mock(return_value=(None, ""))
        self.spider._persist_follow_state = MODULE.Spider._persist_follow_state.__get__(self.spider, MODULE.Spider)
        self.spider.setCache = Mock(return_value=True)

        self.assertFalse(self.spider._load_follow_state(force=True))
        with self.assertRaisesRegex(RuntimeError, "尚未成功读取"):
            self.spider._save_follow_state({"202": {"tmdb_id": 202}})

        self.spider.setCache.assert_not_called()
        self.assertIs(self.spider._follow_memory, original)

    def test_explicit_empty_follow_cache_allows_first_persisted_write(self):
        self.spider._follow_state_loaded = False
        self.spider.getCache = Mock(return_value=None)
        self.spider._load_follow_state_from_loopback = Mock(return_value=(None, ""))
        self.spider._persist_follow_state = Mock(return_value=True)

        self.assertTrue(self.spider._load_follow_state(force=True))
        self.assertTrue(self.spider._save_follow_state({"101": {"tmdb_id": 101}}))

        self.assertIn("101", self.spider._follow_memory["items"])
        self.spider._load_follow_state_from_loopback.assert_not_called()

    def test_concurrent_forced_follow_loads_are_serialized(self):
        active = {"count": 0, "max": 0}
        guard = MODULE.threading.Lock()

        def get_cache(_key):
            with guard:
                active["count"] += 1
                active["max"] = max(active["max"], active["count"])
            time.sleep(0.03)
            with guard:
                active["count"] -= 1
            return {"version": 2, "items": {"101": {"tmdb_id": 101, "title": "测试剧集"}}}

        self.spider._follow_state_loaded = False
        self.spider.getCache = Mock(side_effect=get_cache)
        self.spider._load_follow_state_from_loopback = Mock(return_value=(None, ""))
        threads = [MODULE.threading.Thread(target=self.spider._load_follow_state, args=(True,)) for _index in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(1)

        self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertEqual(active["max"], 1)
        self.assertEqual(self.spider._follow_memory["items"]["101"]["title"], "测试剧集")

    def test_uri_schemes_and_encoded_schemes_never_persist_as_route_identity(self):
        self.spider._follow_memory = {"version": 2, "items": {
            "101": {"tmdb_id": 101, "title": "测试剧集"},
        }}
        self.spider._persist_follow_state = Mock(return_value=True)
        for resource_id in (
                "magnet:?xt=urn:btih:ABC",
                "data:text/plain,secret",
                "javascript:alert(1)",
                "magnet%253A%253Fxt%253Durn%253Abtih%253AABC"):
            self.spider._remember_successful_follow_route(
                {"tmdbId": 101, "resourceMode": "vod", "season": 1, "episode": 1},
                {"resourceId": resource_id, "name": "S01E01"},
                "1@" + resource_id,
                {"height": 1080, "codec": "h264", "startup_ms": 100},
            )

        self.assertNotIn("last_play_route", self.spider._follow_memory["items"]["101"])
        self.assertNotIn("alist_vod_id", self.spider._follow_memory["items"]["101"])

    def test_embedded_and_deeply_encoded_uri_schemes_never_persist(self):
        self.spider._follow_memory = {"version": 2, "items": {
            "101": {"tmdb_id": 101, "title": "测试剧集"},
        }}
        self.spider._persist_follow_state = Mock(return_value=True)
        for value in (
                "prefix|magnet:?xt=urn:btih:ABC",
                "source=javascript:alert(1)",
                "x,data:text/plain,secret",
                "1@x|javascript:alert(1)"):
            self.assertTrue(self.spider._contains_url_reference(value))
            self.spider._remember_successful_follow_route(
                {"tmdbId": 101, "resourceMode": "vod", "season": 1, "episode": 1},
                {"resourceId": value, "name": "S01E01"},
                value,
                {"height": 1080, "codec": "h264", "startup_ms": 100},
            )
        encoded = "https://a"
        for _index in range(33):
            encoded = MODULE.quote(encoded, safe="")
        self.assertTrue(self.spider._contains_url_reference(encoded))
        self.spider._remember_successful_follow_route(
            {"tmdbId": 101, "resourceMode": "vod", "season": 1, "episode": 1},
            {"resourceId": encoded, "name": "S01E01"},
            "1@" + encoded,
            {"height": 1080, "codec": "h264", "startup_ms": 100},
        )

        self.assertNotIn("last_play_route", self.spider._follow_memory["items"]["101"])
        self.assertNotIn("alist_vod_id", self.spider._follow_memory["items"]["101"])

    def test_loaded_follow_state_cleans_legacy_uri_bindings(self):
        cached = {"version": 2, "items": {"101": {
            "tmdb_id": 101,
            "title": "测试剧集",
            "alist_vod_id": "magnet:?xt=urn:btih:ABC",
            "alist_resource_mode": "vod",
            "last_play_route": {
                "resourceId": "data:text/plain,secret",
                "resourceMode": "vod",
                "playId": "1@javascript:alert(1)",
                "season": 1,
                "episode": 1,
            },
        }}}
        self.spider._follow_state_loaded = False
        self.spider.getCache = Mock(return_value=cached)
        self.spider._load_follow_state_from_loopback = Mock(return_value=(None, ""))
        self.spider._persist_follow_state = Mock(return_value=True)

        self.assertTrue(self.spider._load_follow_state(force=True))

        item = self.spider._follow_memory["items"]["101"]
        self.assertNotIn("alist_vod_id", item)
        self.assertNotIn("last_play_route", item)
        self.spider._persist_follow_state.assert_called_once()

    def test_history_cloud_response_is_byte_bounded_and_closed(self):
        class FakeResponse(object):
            def __init__(self, headers, chunks):
                self.status_code = 200
                self.headers = headers
                self._chunks = chunks
                self.closed = False

            def iter_content(self, chunk_size=None):
                return iter(self._chunks)

            def close(self):
                self.closed = True

        response = FakeResponse(
            {"Content-Length": str(self.spider.HISTORY_RESPONSE_MAX_BYTES + 1)},
            [],
        )
        self.spider._atvp_history_request = Mock(return_value=response)

        with self.assertRaisesRegex(RuntimeError, "响应过大"):
            self.spider._atvp_fetch_history()

        self.assertTrue(response.closed)
        self.spider._atvp_history_request.assert_called_once_with("GET", stream=True)

    def test_filter_history_uses_the_same_bounded_normalization(self):
        class FakeResponse(object):
            def __init__(self, content, content_length=None):
                self.status_code = 200
                self.headers = {"Content-Length": str(len(content) if content_length is None else content_length)}
                self._content = content
                self.closed = False

            def iter_content(self, chunk_size=None):
                return iter((self._content,))

            def close(self):
                self.closed = True

        filter_obj = MODULE.Filter()
        filter_obj._local_follow_history_rows = Mock(return_value=[])
        oversized = FakeResponse(b"", MODULE.HISTORY_RESPONSE_MAX_BYTES + 1)
        payload = json.dumps([{
            "key": "history-1",
            "vodName": "剧" * 2000,
            "episodeUrl": "x" * (MODULE.HISTORY_FIELD_MAX_LENGTH * 2),
            "unknown": "drop-me",
        }], ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        normal = FakeResponse(payload)
        filter_obj._session.get = Mock(side_effect=(oversized, normal))
        context = {"api": "https://atvp.example", "token": "token"}

        self.assertEqual(filter_obj._history_rows(context), [])
        rows = filter_obj._history_rows(context)

        self.assertTrue(oversized.closed)
        self.assertTrue(normal.closed)
        self.assertEqual(len(rows), 1)
        self.assertLessEqual(MODULE._history_utf8_size(rows[0]["vodName"]), 1024)
        self.assertLessEqual(MODULE._history_utf8_size(rows[0]["episodeUrl"]), MODULE.HISTORY_FIELD_MAX_LENGTH)
        self.assertNotIn("unknown", rows[0])
        filter_obj._session.close()

    def test_filter_followplay_rejects_oversized_id_before_decode(self):
        oversized = MODULE.FOLLOWPLAY_PREFIX + ("x" * MODULE.Filter.FOLLOWPLAY_MAX_ID_LENGTH)
        self.assertIsNone(MODULE.Filter._followplay(oversized))

    def test_history_rows_and_upload_payload_are_uniformly_bounded(self):
        oversized = [{
            "key": "key-1",
            "vodName": "剧" * 4000,
            "vodRemarks": "注" * 10000,
            "episodeUrl": "x" * (self.spider.HISTORY_FIELD_MAX_LENGTH * 2),
            "vodPic": "https://image.example/cover.jpg",
            "unknown": "not-uploaded",
        }]
        normalized = self.spider._normalize_history_rows(oversized)
        self.assertEqual(len(normalized), 1)
        self.assertLessEqual(self.spider._utf8_size(normalized[0]["vodName"]), 1024)
        self.assertLessEqual(self.spider._utf8_size(normalized[0]["vodRemarks"]), 4096)
        self.assertLessEqual(
            self.spider._utf8_size(normalized[0]["episodeUrl"]),
            self.spider.HISTORY_FIELD_MAX_LENGTH,
        )
        self.assertNotIn("unknown", normalized[0])
        payload = self.spider._history_upload_payload(oversized)
        self.assertNotIn("vodPic", payload[0])

        many_rows = [{"key": "key-%d" % index, "vodName": "剧"} for index in range(self.spider.HISTORY_ROW_LIMIT + 20)]
        self.assertEqual(len(self.spider._normalize_history_rows(many_rows)), self.spider.HISTORY_ROW_LIMIT)

        invalid_prefix = [{} for _index in range(self.spider.HISTORY_ROW_LIMIT)]
        invalid_prefix.append({"key": "trailing-valid", "vodName": "不应被扫描"})
        self.assertEqual(self.spider._normalize_history_rows(invalid_prefix), [])

        large_rows = [{"key": "large-%d" % index, "episodeUrl": "x" * 60000} for index in range(80)]
        bounded = self.spider._normalize_history_rows(large_rows)
        self.assertLess(len(bounded), len(large_rows))
        self.assertLessEqual(
            self.spider._utf8_size(json.dumps(bounded, ensure_ascii=False, separators=(",", ":"))),
            self.spider.HISTORY_RESPONSE_MAX_BYTES,
        )

    def test_history_callback_rejects_oversized_targets_before_json_parse(self):
        pending = {"captured": {}, "event": MODULE.threading.Event()}
        self.spider._native_exports["nonce"] = pending

        result = self.spider.localProxy({
            "follow_sync_callback": "nonce",
            "config": "{}",
            "targets": "x" * (self.spider.HISTORY_RESPONSE_MAX_BYTES + 1),
        })

        self.assertEqual(result[0], 200)
        self.assertTrue(pending["event"].is_set())
        self.assertIn("过大", pending["captured"]["error"])
        self.assertNotIn("targets", pending["captured"])

    def test_history_callback_rejects_oversized_string_before_json_parse(self):
        pending = {"captured": {}, "event": MODULE.threading.Event()}
        self.spider._native_exports["nonce"] = pending
        value = json.dumps({
            "follow_sync_callback": "nonce",
            "config": "{}",
            "targets": "x" * (self.spider.HISTORY_RESPONSE_MAX_BYTES + self.spider.HISTORY_CONFIG_MAX_BYTES + 100000),
        }, ensure_ascii=False, separators=(",", ":"))

        result = self.spider.localProxy(value)

        self.assertEqual(result[0], 413)
        self.assertTrue(pending["event"].is_set())
        self.assertIn("过大", pending["captured"]["error"])
        self.assertNotIn("targets", pending["captured"])

    def test_atvp_transport_retry_is_get_only_but_auth_retry_remains_explicit(self):
        adapter = self.spider._atvp_retry_adapter()
        allowed = set(getattr(adapter.max_retries, "allowed_methods", ()) or ())
        self.assertEqual(allowed, {"GET"})

        first = Mock(status_code=401)
        second = Mock(status_code=200)
        self.spider._alist_tvbox_plugin = True
        self.spider.history_username = "user"
        self.spider.history_password = "pass"
        self.spider._history_auth_token = "old-token"
        self.spider._atvp_session = Mock()
        self.spider._atvp_session.post.side_effect = [first, second]
        self.spider._atvp_history_login = Mock(return_value=True)
        self.spider._atvp_endpoint = Mock(return_value="https://atvp.example/history/token")

        result = self.spider._atvp_history_request("POST", json=[])

        self.assertIs(result, second)
        self.assertEqual(self.spider._atvp_session.post.call_count, 2)
        first.close.assert_called_once_with()
        self.spider._atvp_history_login.assert_called_once_with(force=True)

    def test_playback_retry_interval_is_five_seconds_for_active_player(self):
        self.assertEqual(self.spider.PLAYBACK_SYNC_RETRY_SECONDS, 5)
        owner = object()
        self.spider._playback_sync_pending["pending"] = {
            "owner": owner,
            "started_at": time.time() - self.spider.PLAYBACK_SYNC_MIN_SECONDS - 1,
        }
        self.spider._playback_activity_active = Mock(return_value=True)
        self.spider._schedule_playback_sync_check = Mock(return_value=True)

        self.assertTrue(self.spider._playback_sync_check("pending"))

        self.spider._schedule_playback_sync_check.assert_called_once_with(
            "pending", 5, expected_owner=owner,
        )

    def test_playback_retry_interval_is_five_seconds_when_history_is_not_ready(self):
        owner = object()
        self.spider._playback_sync_pending["pending"] = {
            "owner": owner,
            "started_at": time.time() - self.spider.PLAYBACK_SYNC_MIN_SECONDS - 1,
            "tmdb_id": 101,
            "source_id": "tmdb:tv:101",
            "resource_id": "resource-101",
            "season": 1,
            "episode": 6,
        }
        self.spider._playback_activity_active = Mock(return_value=False)
        self.spider._capture_native_history = Mock(return_value=[{"key": "history-1"}])
        self.spider._atvp_history_for_item = Mock(return_value={"position": 1000})
        self.spider._schedule_playback_sync_check = Mock(return_value=True)

        self.assertTrue(self.spider._playback_sync_check("pending"))

        self.spider._schedule_playback_sync_check.assert_called_once_with(
            "pending", 5, expected_owner=owner,
        )

    def test_each_follow_page_flushes_pending_playback_sync(self):
        self.spider._flush_playback_sync_on_navigation = Mock()
        self.spider._load_follow_state = Mock(return_value=True)
        self.spider._category_follow_updates = Mock(return_value={"list": []})
        self.spider._category_follow_candidates = Mock(return_value={"list": []})
        self.spider._category_follow_manage = Mock(return_value={"list": []})

        for tid in ("follow_updates", "follow_candidates", "follow_manage"):
            self.spider.categoryContent(tid, "1", False, {})

        self.assertEqual(self.spider._flush_playback_sync_on_navigation.call_count, 3)


if __name__ == "__main__":
    unittest.main()

# -*- coding: utf-8 -*-

import importlib.util
import json
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
        self.assertTrue(any(payload.get("fallbacks") for payload in parsed_payloads))
        self.assertIn("资源分集过多 已截断", merged["vod_remarks"])

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


if __name__ == "__main__":
    unittest.main()

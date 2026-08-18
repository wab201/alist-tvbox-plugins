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

    def test_diagnostics_are_bounded_and_redact_configured_secrets(self):
        self.spider.tmdb_access_token = "secret-tmdb-token"
        self.spider.DIAGNOSTIC_LIMIT = 3

        for index in range(5):
            self.spider._diagnostic_event(
                "test.event", "ERROR",
                exc=RuntimeError("request token=fixture-tmdb-token failed"),
                request_url="https://example.test/play?token=fixture-tmdb-token&index=%d" % index,
            )

        snapshot = self.spider._diagnostic_snapshot()
        self.assertEqual(len(snapshot), 3)
        serialized = json.dumps(snapshot, ensure_ascii=False)
        self.assertNotIn("secret-tmdb-token", serialized)
        self.assertEqual([row["seq"] for row in snapshot], [3, 4, 5])

    def test_native_history_import_converts_legacy_numeric_flags_to_booleans(self):
        captured = {}

        class FakeHistory(object):
            @staticmethod
            def arrayFrom(payload):
                captured["rows"] = json.loads(payload)
                return captured["rows"]

            @staticmethod
            def sync(rows):
                captured["synced"] = rows

            @staticmethod
            def find(key):
                return object()

        fake_java = types.ModuleType("java")
        fake_java.jclass = lambda name: FakeHistory
        with patch.dict(sys.modules, {"java": fake_java}):
            imported = self.spider._import_native_history([
                {
                    "key": "site@@@vod@@@1",
                    "vodName": "测试剧集",
                    "revSort": 0,
                    "revPlay": 1,
                    "position": 1200,
                }
            ])

        self.assertEqual(imported, 1)
        self.assertIs(captured["rows"][0]["revSort"], False)
        self.assertIs(captured["rows"][0]["revPlay"], True)

    def test_diagnostic_failure_never_changes_business_result(self):
        with patch.object(self.spider, "_short_error", side_effect=RuntimeError("diagnostic failed")):
            self.assertIsNone(self.spider._diagnostic_event("test.failure", exc=RuntimeError("boom")))
        self.assertEqual(self.spider._diagnostic_snapshot(), [])

    def test_task_supervisor_rejects_new_work_after_shutdown(self):
        supervisor = MODULE._TaskSupervisor()
        supervisor.shutdown()

        with self.assertRaises(RuntimeError):
            supervisor.start_thread(lambda: None)
        with self.assertRaises(RuntimeError):
            supervisor.start_timer(0, lambda: None)

    def test_task_supervisor_thread_start_failure_rolls_back_tracking(self):
        supervisor = MODULE._TaskSupervisor()
        thread = Mock()
        thread.start.side_effect = RuntimeError("thread start failed")

        with patch.object(MODULE.threading, "Thread", return_value=thread):
            with self.assertRaises(RuntimeError):
                supervisor.start_thread(lambda: None)

        self.assertEqual(supervisor._threads, set())
        supervisor.shutdown()

    def test_task_supervisor_shutdown_is_idempotent(self):
        supervisor = MODULE._TaskSupervisor()
        executor = Mock()
        supervisor.register_executor(executor)

        supervisor.shutdown()
        supervisor.shutdown()

        executor.shutdown.assert_called_once_with(wait=False, cancel_futures=True)

    def test_destroy_then_init_rebuilds_task_runtime(self):
        old_tasks = self.spider._tasks
        self.spider.destroy()

        self.spider.init({})

        self.assertIsNot(self.spider._tasks, old_tasks)
        self.assertFalse(self.spider._tasks.is_closed())
        completed = MODULE.threading.Event()
        self.assertTrue(self.spider._tasks.start_thread(completed.set, name="reinit-check"))
        self.assertTrue(completed.wait(1))

    def test_playback_timer_owner_mismatch_is_not_tracked(self):
        self.spider._playback_sync_pending["key"] = {"owner": object()}

        self.assertFalse(
            self.spider._schedule_playback_sync_check("key", 1, expected_owner=object())
        )

        self.assertEqual(self.spider._tasks._timers, set())

    def test_cached_failure_backoff_grows_and_success_resets_it(self):
        key = "cache:test"
        self.spider.failure_ttl = 60
        self.spider._remember_failure(key, RuntimeError("first"))
        first = self.spider._failures[key]
        self.spider._remember_failure(key, RuntimeError("second"))
        second = self.spider._failures[key]

        self.assertGreaterEqual(second[1] - second[0], first[1] - first[0])
        self.assertTrue(self.spider._has_cached_failure(key))
        self.spider._clear_cached_failure(key)
        self.assertFalse(self.spider._has_cached_failure(key))
        self.assertNotIn(key, self.spider._failure_attempts)

    def test_destroy_flushes_dirty_persistent_response_cache(self):
        fresh = Spider()
        fresh.setCache = Mock()
        fresh._persistent_cache["json:test"] = (time.time(), {"ok": True})
        fresh._persistent_cache_dirty = True

        fresh.destroy()

        fresh.setCache.assert_called_once()
        cache_key, payload = fresh.setCache.call_args.args
        self.assertEqual(cache_key, fresh.RESPONSE_CACHE_KEY)
        self.assertEqual(payload["entries"][-1][0], "json:test")

    def test_clean_empty_response_cache_does_not_write_on_destroy(self):
        fresh = Spider()
        fresh.setCache = Mock()

        fresh.destroy()

        fresh.setCache.assert_not_called()

    def test_async_response_cache_exception_keeps_dirty_for_later_retry(self):
        fresh = Spider()
        attempted = MODULE.threading.Event()

        def fail_save(*_args):
            attempted.set()
            raise RuntimeError("cache unavailable")

        fresh.setCache = Mock(side_effect=fail_save)
        fresh._persistent_cache["json:test"] = (time.time(), {"ok": True})

        self.assertTrue(fresh._schedule_response_cache_save())
        self.assertTrue(attempted.wait(1))
        deadline = time.time() + 1
        while fresh._persistent_cache_saving and time.time() < deadline:
            time.sleep(0.01)

        self.assertFalse(fresh._persistent_cache_saving)
        self.assertTrue(fresh._persistent_cache_dirty)
        fresh._tasks.shutdown(wait=False)

    def test_async_response_cache_failed_result_keeps_dirty_for_later_retry(self):
        fresh = Spider()
        attempted = MODULE.threading.Event()

        def fail_save(*_args):
            attempted.set()
            return "failed"

        fresh.setCache = Mock(side_effect=fail_save)
        fresh._persistent_cache["json:test"] = (time.time(), {"ok": True})

        self.assertTrue(fresh._schedule_response_cache_save())
        self.assertTrue(attempted.wait(1))
        deadline = time.time() + 1
        while fresh._persistent_cache_saving and time.time() < deadline:
            time.sleep(0.01)

        self.assertFalse(fresh._persistent_cache_saving)
        self.assertTrue(fresh._persistent_cache_dirty)
        fresh._tasks.shutdown(wait=False)

    def test_response_cache_flush_exception_keeps_dirty(self):
        fresh = Spider()
        fresh.setCache = Mock(side_effect=RuntimeError("cache unavailable"))
        fresh._persistent_cache["json:test"] = (time.time(), {"ok": True})
        fresh._persistent_cache_dirty = True

        self.assertFalse(fresh._flush_response_cache_sync())

        self.assertTrue(fresh._persistent_cache_dirty)
        fresh._tasks.shutdown(wait=False)

    def test_response_cache_flush_failed_result_keeps_dirty(self):
        fresh = Spider()
        fresh.setCache = Mock(return_value="failed")
        fresh._persistent_cache["json:test"] = (time.time(), {"ok": True})
        fresh._persistent_cache_dirty = True

        self.assertFalse(fresh._flush_response_cache_sync())

        self.assertTrue(fresh._persistent_cache_dirty)
        fresh._tasks.shutdown(wait=False)

    def test_old_response_cache_worker_cannot_clear_new_save_owner(self):
        fresh = Spider()
        fresh.setCache = Mock()
        fresh._persistent_cache["json:old"] = (time.time(), {"old": True})

        self.assertTrue(fresh._schedule_response_cache_save())
        old_owner = fresh._persistent_cache_saving
        with fresh._cache_lock:
            fresh._cache_generation += 1
            new_owner = object()
            fresh._persistent_cache_saving = new_owner
        deadline = time.time() + 1
        while old_owner is fresh._persistent_cache_saving and time.time() < deadline:
            time.sleep(0.01)

        self.assertIs(fresh._persistent_cache_saving, new_owner)
        fresh._persistent_cache_saving = None
        fresh._tasks.shutdown(wait=False)

    def test_response_cache_write_finishes_before_lifecycle_generation_switch(self):
        fresh = Spider()
        entered = MODULE.threading.Event()
        release = MODULE.threading.Event()
        switched = MODULE.threading.Event()

        def blocking_save(*_args):
            entered.set()
            release.wait(1)
            return None

        fresh.setCache = blocking_save
        fresh._persistent_cache["json:old"] = (time.time(), {"old": True})
        self.assertTrue(fresh._schedule_response_cache_save())
        self.assertTrue(entered.wait(1))

        def switch_generation():
            with fresh._cache_persist_lock:
                with fresh._cache_lock:
                    fresh._cache_generation += 1
            switched.set()

        switcher = MODULE.threading.Thread(target=switch_generation)
        switcher.start()
        self.assertFalse(switched.wait(0.05))
        release.set()
        self.assertTrue(switched.wait(1))
        switcher.join(1)
        fresh._tasks.shutdown(wait=False)

    def test_old_cache_refresh_cannot_clear_new_single_flight_owner(self):
        old_started = MODULE.threading.Event()
        old_release = MODULE.threading.Event()
        new_started = MODULE.threading.Event()
        new_release = MODULE.threading.Event()
        key = "json:shared"

        def old_loader():
            old_started.set()
            old_release.wait(1)
            return {"old": True}

        def new_loader():
            new_started.set()
            new_release.wait(1)
            return {"new": True}

        self.assertTrue(self.spider._schedule_cache_refresh(key, old_loader))
        self.assertTrue(old_started.wait(1))
        with self.spider._cache_lock:
            self.spider._cache_generation += 1
            self.spider._refreshing_cache_keys.clear()
        self.assertTrue(self.spider._schedule_cache_refresh(key, new_loader))
        self.assertTrue(new_started.wait(1))
        new_owner = self.spider._refreshing_cache_keys[key]

        old_release.set()
        deadline = time.time() + 1
        while self.spider._refreshing_cache_keys.get(key) is not new_owner and time.time() < deadline:
            time.sleep(0.01)
        self.assertIs(self.spider._refreshing_cache_keys.get(key), new_owner)

        new_release.set()
        deadline = time.time() + 1
        while key in self.spider._refreshing_cache_keys and time.time() < deadline:
            time.sleep(0.01)
        self.assertNotIn(key, self.spider._refreshing_cache_keys)

    def test_route_quality_save_failures_keep_dirty(self):
        for failure in (RuntimeError("cache unavailable"), "failed"):
            fresh = Spider()
            attempted = MODULE.threading.Event()

            def fail_save(*_args, result=failure):
                attempted.set()
                if isinstance(result, Exception):
                    raise result
                return result

            fresh.setCache = fail_save
            fresh._route_quality_history["a" * 64] = {"updatedAt": int(time.time())}
            self.assertTrue(fresh._schedule_route_quality_save())
            self.assertTrue(attempted.wait(1))
            deadline = time.time() + 1
            while fresh._route_quality_saving and time.time() < deadline:
                time.sleep(0.01)
            self.assertTrue(fresh._route_quality_dirty)
            fresh._route_quality_dirty = False
            fresh._tasks.shutdown(wait=False)

    def test_follow_page_refresh_uses_supervised_executor(self):
        self.assertIn(self.spider._follow_refresh_executor, self.spider._tasks._executors)
        item = {"tmdb_id": 101, "title": "测试", "last_checked": 0}
        self.spider._follow_memory = {"version": 2, "items": {"101": dict(item)}}
        self.spider._refresh_follow_item = Mock(return_value=dict(item, last_checked=int(time.time())))

        with patch.object(MODULE, "ThreadPoolExecutor", side_effect=AssertionError("临时线程池不应创建")):
            self.assertTrue(self.spider._refresh_follow_page_async([item]))
            self._wait_follow_jobs()

    def test_stale_follow_enrichment_cannot_write_into_new_lifecycle(self):
        started = MODULE.threading.Event()
        release = MODULE.threading.Event()
        self.spider._follow_memory = {"version": 2, "items": {
            "101": {"tmdb_id": 101, "title": "旧生命周期", "pending_metadata": True},
        }}

        def delayed_tmdb(*_args, **_kwargs):
            started.set()
            release.wait(1)
            return {"id": 101, "name": "旧任务返回", "seasons": []}

        self.spider._tmdb_api = delayed_tmdb
        self.spider._attach_tmdb_title_aliases = lambda item, _data: item
        self.spider._attach_douban_to_tmdb_item = lambda item, _data: item

        self.assertTrue(self.spider._start_follow_enrichment("tmdb", "101"))
        self.assertTrue(started.wait(1))
        with self.spider._cache_lock:
            self.spider._cache_generation += 1
        self.spider._follow_memory = {"version": 2, "items": {
            "101": {"tmdb_id": 101, "title": "新生命周期", "pending_metadata": True},
        }}
        release.set()
        self._wait_follow_jobs()

        self.assertEqual(self.spider._follow_memory["items"]["101"]["title"], "新生命周期")
        self.spider._persist_follow_state.assert_not_called()

    def test_stale_follow_page_refresh_cannot_persist_new_lifecycle(self):
        started = MODULE.threading.Event()
        release = MODULE.threading.Event()
        old_item = {"tmdb_id": 101, "title": "旧页面", "last_checked": 0}
        self.spider._follow_memory = {"version": 2, "items": {"101": dict(old_item)}}

        def delayed_refresh(_item):
            started.set()
            release.wait(1)
            return {"tmdb_id": 101, "title": "旧刷新返回", "last_checked": int(time.time())}

        self.spider._refresh_follow_item = delayed_refresh

        self.assertTrue(self.spider._refresh_follow_page_async([old_item]))
        self.assertTrue(started.wait(1))
        with self.spider._cache_lock:
            self.spider._cache_generation += 1
        self.spider._follow_memory = {"version": 2, "items": {
            "101": {"tmdb_id": 101, "title": "新页面", "last_checked": 0},
        }}
        release.set()
        self._wait_follow_jobs()

        self.assertEqual(self.spider._follow_memory["items"]["101"]["title"], "新页面")
        self.spider._persist_follow_state.assert_not_called()

    def test_runtime_components_are_bound_to_the_spider_instance(self):
        self.assertIs(self.spider._tmdb_client.owner, self.spider)
        self.assertIs(self.spider._douban_client.owner, self.spider)
        self.assertIs(self.spider._follow_repository.owner, self.spider)
        self.assertIs(self.spider._history_coordinator.owner, self.spider)
        self.assertIs(self.spider._cache_coordinator.owner, self.spider)

    def test_tmdb_legacy_methods_delegate_to_component(self):
        self.spider._tmdb_client.api = Mock(return_value={"id": 1})
        self.spider._tmdb_client.image = Mock(return_value="https://image.test/a.jpg")

        self.assertEqual(self.spider._tmdb_api("/test", {"page": 1}, 10, False), {"id": 1})
        self.assertEqual(self.spider._tmdb_image("/a.jpg"), "https://image.test/a.jpg")
        self.spider._tmdb_client.api.assert_called_once_with("/test", {"page": 1}, 10, False)

    def test_douban_legacy_methods_delegate_to_component(self):
        self.spider._douban_client.request_json = Mock(return_value={"ok": True})
        self.spider._douban_client.request_text = Mock(return_value="page")

        self.assertEqual(self.spider._request_json("https://example.test", {"q": "x"}), {"ok": True})
        self.assertEqual(self.spider._request_text("https://example.test/page"), "page")

    def test_history_legacy_methods_delegate_to_component(self):
        self.spider._history_coordinator.fetch = Mock(return_value=[{"key": "one"}])
        self.spider._history_coordinator.push = Mock(return_value=None)

        self.assertEqual(self.spider._atvp_fetch_history(), [{"key": "one"}])
        self.assertIsNone(self.spider._atvp_history_push([{"key": "one"}]))

    def test_history_coordinator_delegates_background_sync(self):
        expected = {"merged": [], "errors": []}
        self.spider._sync_history_once = Mock(return_value=expected)

        result = self.spider._history_coordinator.sync_once(expected_generation=7)

        self.assertIs(result, expected)
        self.spider._sync_history_once.assert_called_once_with(expected_generation=7)

    def test_plugin_metadata_is_parseable_by_alist_tvbox(self):
        source = SOURCE.read_text(encoding="utf-8")
        expected = {
            "name": "豆瓣TMDB追更助手（AList-TVBox专用）",
            "id": "douban_tmdb_follow_single",
            "version": "70",
        }
        for field, value in expected.items():
            match = re.search(r"(?m)^\s*//@%s:(.+?)\s*$" % field, source)
            self.assertIsNotNone(match, field)
            self.assertEqual(match.group(1), value)
        repository = json.loads((ROOT / "spiders_v2.json").read_text(encoding="utf-8"))
        entry = next(row for row in repository if row.get("id") == expected["id"])
        self.assertEqual(str(entry.get("version")), expected["version"])
        self.assertEqual(entry.get("file"), "py/豆瓣TMDB追更单入口.py")
        self.assertIs(entry.get("valid"), True)

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

    def test_lightweight_history_cache_collision_releases_snapshot_job_marker(self):
        cache_key = "atvp-history-snapshot"
        self.spider._refreshing_cache_keys[cache_key] = object()

        scheduled = self.spider._schedule_atvp_history_refresh(cache_key, lightweight=True)

        self.assertFalse(scheduled)
        self.assertNotIn("snapshot-background", self.spider._atvp_jobs)

    def test_old_lightweight_history_cannot_publish_after_full_sync(self):
        fetch_started = MODULE.threading.Event()
        release_fetch = MODULE.threading.Event()
        old_rows = [{"key": "show", "vodName": "测试剧集", "vodRemarks": "S01E03"}]
        new_rows = [{"key": "show", "vodName": "测试剧集", "vodRemarks": "S01E14"}]

        def delayed_fetch():
            fetch_started.set()
            self.assertTrue(release_fetch.wait(2))
            return old_rows

        self.spider._atvp_fetch_history = Mock(side_effect=delayed_fetch)
        self.spider._alist_tvbox_plugin = True
        self.spider._ensure_atvp_connection = Mock(return_value=True)
        self.spider._reconcile_follow_histories = Mock(return_value=0)
        self.spider._refresh_follow_categories = Mock(return_value=True)
        self.spider._sync_history_once = Mock(return_value={
            "mode": "双向", "local": 1, "cloud": 1,
            "cloud_available": True, "upload_candidates": 0,
            "upload_allowed": 0, "upload_blocked": 0, "uploaded": 0,
            "imported": 0, "merged": new_rows, "import_rows": [],
            "progress": 0, "errors": [],
        })

        self.assertTrue(self.spider._schedule_atvp_history_refresh(
            "atvp-history-snapshot", lightweight=True,
        ))
        self.assertTrue(fetch_started.wait(1))
        sync_result = {}
        sync_finished = MODULE.threading.Event()

        def run_full_sync():
            sync_result.update(json.loads(self.spider._atvp_sync_history(
                expected_generation=self.spider._cache_generation,
            )))
            sync_finished.set()

        sync_thread = MODULE.threading.Thread(target=run_full_sync)
        sync_thread.start()
        self.assertTrue(sync_finished.wait(2))
        sync_thread.join(1)
        self.assertTrue(sync_result["ok"], sync_result)
        release_fetch.set()

        deadline = time.time() + 2
        while "snapshot-background" in self.spider._atvp_jobs and time.time() < deadline:
            time.sleep(0.01)
        cached = self.spider._cache_get("atvp-history-snapshot", 60)
        self.assertEqual(cached, new_rows)
        self.assertNotIn("snapshot-background", self.spider._atvp_jobs)

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

    def test_history_resource_change_restores_mode_provider_and_clears_old_route(self):
        old_resource = "https://pan.quark.cn/s/old"
        new_resource = "https://pan.baidu.com/s/new"
        item = {
            "media_type": "tv", "tmdb_id": 101, "title": "测试剧集",
            "trackingSeason": 1, "alist_vod_id": old_resource,
            "alist_resource_mode": "vod", "alist_resource_provider": "quark",
            "last_play_route": {
                "resourceId": old_resource, "resourceMode": "vod",
                "resourceProvider": "quark", "playId": "1@old-route",
                "season": 1, "episode": 1,
            },
        }
        play_id = self.spider._build_followplay(
            "1@new-route", item, new_resource, 1, 2, "S01E02",
            resource_mode="pansou", resource_provider="baidu",
        )
        history = {
            "vodName": "测试剧集", "vodFlag": "测试线路",
            "episodeUrl": "S01E02$" + play_id,
            "position": 120000, "duration": 1200000,
        }
        self.spider._follow_memory = {"version": 2, "items": {"101": item}}

        self.assertEqual(self.spider._reconcile_follow_histories([history]), 1)

        updated = self.spider._follow_memory["items"]["101"]
        self.assertEqual(updated["alist_vod_id"], new_resource)
        self.assertEqual(updated["alist_resource_mode"], "pansou")
        self.assertEqual(updated["alist_resource_provider"], "baidu")
        self.assertNotIn("last_play_route", updated)

    def test_history_conflicting_provider_clears_previous_provider(self):
        new_resource = "https://pan.baidu.com/s/new"
        item = {
            "media_type": "tv", "tmdb_id": 101, "title": "测试剧集",
            "trackingSeason": 1, "alist_vod_id": "old-resource",
            "alist_resource_mode": "vod", "alist_resource_provider": "quark",
        }
        play_id = self.spider._build_followplay(
            "1@new-route", item, new_resource, 1, 2, "S01E02",
            resource_mode="pansou", resource_provider="quark",
        )
        fields = self.spider._history_resume_fields(item, {
            "vodName": "测试剧集", "episodeUrl": "S01E02$" + play_id,
        })

        self.assertEqual(fields["alist_vod_id"], new_resource)
        self.assertEqual(fields["alist_resource_provider"], "")

    def test_history_private_https_origin_falls_back_to_http(self):
        self.spider._alist_tvbox_plugin = True
        self.spider.atvp_api = "https://192.168.1.10:4568"
        self.spider.atvp_token = "token"
        response = Mock(status_code=200)
        self.spider._atvp_session = Mock()
        self.spider._atvp_session.get.side_effect = [
            MODULE.requests.exceptions.SSLError("wrong version number"), response,
        ]

        result = self.spider._atvp_history_request("GET", stream=True)

        self.assertIs(result, response)
        calls = self.spider._atvp_session.get.call_args_list
        self.assertEqual(
            [call.args[0] for call in calls],
            [
                "https://192.168.1.10:4568/history/token",
                "http://192.168.1.10:4568/history/token",
            ],
        )
        self.assertEqual(self.spider._history_selected_origin, "http://192.168.1.10:4568")

    def test_history_get_authenticates_before_cold_read_when_credentials_exist(self):
        self.spider._alist_tvbox_plugin = True
        self.spider.atvp_api = "http://192.168.1.10:4568"
        self.spider.atvp_token = "token"
        self.spider.history_username = "user"
        self.spider.history_password = "pass"
        self.spider._atvp_session = Mock()
        self.spider._atvp_session.headers = {}
        history = Mock(status_code=200)

        def login(force=False):
            self.spider._history_auth_token = "history-token"
            self.spider._history_selected_origin = "http://192.168.1.10:4568"
            self.spider._atvp_session.headers["Authorization"] = "history-token"
            return True

        self.spider._atvp_history_login = Mock(side_effect=login)
        self.spider._atvp_session.get.return_value = history

        result = self.spider._atvp_history_request("GET", stream=True)

        self.assertIs(result, history)
        self.spider._atvp_history_login.assert_called_once_with(force=False)
        self.assertEqual(
            self.spider._atvp_session.get.call_args.args[0],
            "http://192.168.1.10:4568/history/token",
        )

    def test_selected_history_origin_is_reused_before_stale_config_origin(self):
        self.spider.atvp_api = "https://192.168.1.8:4568"
        self.spider._history_selected_origin = "http://192.168.1.8:4568"
        self.spider._history_primary_origin = "https://192.168.1.8:4568"

        candidates = self.spider._history_origin_candidates()

        self.assertEqual(candidates[0], "http://192.168.1.8:4568")
        self.assertEqual(candidates[1], "https://192.168.1.8:4568")

    def test_explicit_history_api_is_separate_from_https_subscription_api(self):
        self.spider.init({
            "atvp_plugin_mode": "alist-tvbox-raw",
            "api": "https://tv.example.com",
            "token": "fixture-sub-token",
            "history_api": "http://history.example.com",
        })

        self.assertEqual(self.spider.atvp_api, "https://tv.example.com")
        self.assertEqual(self.spider.history_api, "http://history.example.com")
        candidates = self.spider._history_origin_candidates()
        self.assertEqual(candidates[0], "http://history.example.com")
        self.assertNotEqual(self.spider.atvp_api, self.spider.history_api)

    def test_history_public_https_never_downgrades_to_http(self):
        self.spider.atvp_api = "https://history.example:443"

        self.assertEqual(
            self.spider._history_origin_candidates(),
            ["https://history.example:443"],
        )

    def test_history_private_counterpart_requires_literal_private_host(self):
        self.assertEqual(
            self.spider._history_private_origin_counterpart("https://127.evil.example:443"),
            "",
        )
        self.assertEqual(
            self.spider._history_private_origin_counterpart("https://127.0.0.1:443"),
            "http://127.0.0.1:443",
        )
        self.assertEqual(
            self.spider._history_private_origin_counterpart("http://192.168.1.8:8080"),
            "https://192.168.1.8:8080",
        )
        self.assertEqual(
            self.spider._history_private_origin_counterpart("https://192.168.1.8"),
            "http://192.168.1.8",
        )
        for origin in (
                "https://0.0.0.0:4568",
                "https://169.254.169.254:4568",
                "https://192.0.2.1:4568",
                "https://224.0.0.1:4568",
                "https://[fe80::1]:4568",
                "https://[2001:db8::1]:4568"):
            with self.subTest(origin=origin):
                self.assertEqual(self.spider._history_private_origin_counterpart(origin), "")
        self.assertEqual(
            self.spider._history_private_origin_counterpart("https://[fd00::8]:4568"),
            "http://[fd00::8]:4568",
        )
        self.assertEqual(
            self.spider._history_private_origin_counterpart("https://[::1]:4568"),
            "http://[::1]:4568",
        )

    def test_history_current_https_origin_precedes_stale_http_primary(self):
        self.spider.atvp_api = "https://192.168.1.8:4568"
        self.spider._history_primary_origin = "http://192.168.1.8:4568"
        self.spider._history_api_origins = ["http://192.168.1.8:4568"]
        self.spider._history_selected_origin = ""

        candidates = self.spider._history_origin_candidates()

        self.assertEqual(candidates[0], "https://192.168.1.8:4568")
        self.assertEqual(candidates[1], "http://192.168.1.8:4568")

    def test_history_request_retries_current_https_after_fallback_login(self):
        class LoginResponse(object):
            def __init__(self):
                self.status_code = 200
                self.headers = {}
                self.closed = False
                self.payload = json.dumps({
                    "authorities": [{"authority": "USER"}],
                    "token": "fixture-history-token",
                }).encode("utf-8")

            def iter_content(self, chunk_size=None):
                return iter((self.payload,))

            def close(self):
                self.closed = True

        self.spider._alist_tvbox_plugin = True
        self.spider.atvp_api = "https://192.168.1.10:4568"
        self.spider.atvp_token = "token"
        self.spider.history_username = "user"
        self.spider.history_password = "pass"
        login = LoginResponse()
        history = Mock(status_code=200)
        self.spider._atvp_session = Mock()
        self.spider._atvp_session.headers = {}
        self.spider._atvp_session.post.side_effect = [
            MODULE.requests.exceptions.ConnectionError(
                "Failed to establish a new connection: connection refused"
            ),
            login,
            history,
        ]

        result = self.spider._atvp_history_request("POST", json=[])

        self.assertIs(result, history)
        urls = [call.args[0] for call in self.spider._atvp_session.post.call_args_list]
        self.assertEqual(
            urls,
            [
                "https://192.168.1.10:4568/api/accounts/login",
                "http://192.168.1.10:4568/api/accounts/login",
                "http://192.168.1.10:4568/history/token",
            ],
        )
        self.assertEqual(self.spider._history_selected_origin, "http://192.168.1.10:4568")
        self.assertTrue(login.closed)
        self.assertTrue(self.spider._atvp_session.post.call_args_list[1].kwargs["stream"])
        self.assertTrue(self.spider._atvp_session.post.call_args_list[2].kwargs["stream"])

    def test_history_error_body_is_streamed_with_a_byte_limit(self):
        class OversizedErrorResponse(object):
            status_code = 500
            headers = {}

            def __init__(self, chunk_count):
                self.chunk_count = chunk_count
                self.read_count = 0
                self.closed = False

            def iter_content(self, chunk_size=None):
                for _index in range(self.chunk_count):
                    self.read_count += 1
                    yield b"x" * 16384

            @property
            def text(self):
                raise AssertionError("streamed error response must not use response.text")

            def close(self):
                self.closed = True

        response = OversizedErrorResponse(1000)

        self.assertFalse(self.spider._atvp_history_needs_auth(response))
        self.assertTrue(response.closed)
        self.assertLessEqual(response.read_count, 9)

    def test_history_ambiguous_post_failure_is_not_retried_on_counterpart(self):
        self.spider._alist_tvbox_plugin = True
        self.spider.atvp_api = "https://192.168.1.10:4568"
        self.spider.atvp_token = "token"
        self.spider.history_username = "user"
        self.spider.history_password = "pass"
        self.spider._history_auth_token = "history-token"
        self.spider._atvp_session = Mock()
        self.spider._atvp_session.post.side_effect = MODULE.requests.exceptions.Timeout("read timed out")

        with self.assertRaises(MODULE.requests.exceptions.Timeout):
            self.spider._atvp_history_request("POST", json=[])

        self.assertEqual(self.spider._atvp_session.post.call_count, 1)
        self.assertEqual(
            self.spider._atvp_session.post.call_args.args[0],
            "https://192.168.1.10:4568/history/token",
        )

    def test_history_post_retries_only_tls_protocol_mismatch(self):
        self.spider._alist_tvbox_plugin = True
        self.spider.atvp_api = "https://192.168.1.10:4568"
        self.spider.atvp_token = "token"
        self.spider.history_username = "user"
        self.spider.history_password = "pass"
        self.spider._history_auth_token = "history-token"
        response = Mock(status_code=200)
        self.spider._atvp_session = Mock()
        self.spider._atvp_session.post.side_effect = [
            MODULE.requests.exceptions.SSLError("wrong version number"),
            response,
        ]

        result = self.spider._atvp_history_request("POST", json=[])

        self.assertIs(result, response)
        self.assertEqual(
            [call.args[0] for call in self.spider._atvp_session.post.call_args_list],
            [
                "https://192.168.1.10:4568/history/token",
                "http://192.168.1.10:4568/history/token",
            ],
        )

    def test_history_post_rejects_ssl_and_ambiguous_connection_retries(self):
        self.spider._alist_tvbox_plugin = True
        self.spider.atvp_api = "https://192.168.1.10:4568"
        self.spider.atvp_token = "token"
        self.spider.history_username = "user"
        self.spider.history_password = "pass"
        self.spider._history_auth_token = "history-token"
        failures = (
            MODULE.requests.exceptions.SSLError("EOF occurred in violation of protocol"),
            MODULE.requests.exceptions.ConnectionError(
                "Max retries exceeded: ProtocolError RemoteDisconnected"
            ),
            MODULE.requests.exceptions.Timeout("read timed out"),
        )
        for failure in failures:
            with self.subTest(failure=type(failure).__name__):
                self.spider._atvp_session = Mock()
                self.spider._atvp_session.post.side_effect = failure
                with self.assertRaises(type(failure)):
                    self.spider._atvp_history_request("POST", json=[])
                self.assertEqual(self.spider._atvp_session.post.call_count, 1)

    def test_history_login_rejects_oversized_response(self):
        class OversizedLoginResponse(object):
            status_code = 200

            def __init__(self):
                self.headers = {
                    "Content-Length": str(self.spider_limit + 1),
                }
                self.closed = False

            def iter_content(self, chunk_size=None):
                return iter(())

            def close(self):
                self.closed = True

        OversizedLoginResponse.spider_limit = self.spider.HISTORY_CONFIG_MAX_BYTES
        response = OversizedLoginResponse()
        self.spider.atvp_api = "https://192.168.1.10:4568"
        self.spider.history_username = "user"
        self.spider.history_password = "pass"
        self.spider._atvp_session = Mock()
        self.spider._atvp_session.headers = {}
        self.spider._atvp_session.post.return_value = response

        with self.assertRaisesRegex(RuntimeError, "响应过大"):
            self.spider._atvp_history_login(force=True)

        self.assertTrue(response.closed)

    def test_history_import_protects_local_recent_playback_from_future_cloud_row(self):
        now = int(time.time() * 1000)
        local = [{
            "key": "local@@@vod@@@1",
            "vodName": "测试剧集",
            "vodRemarks": "S01E06",
            "createTime": now,
            "position": 900000,
            "duration": 1200000,
        }]
        cloud = [{
            "key": "cloud@@@vod@@@1",
            "vodName": "测试剧集",
            "vodRemarks": "S01E06",
            "createTime": now + 86400000,
            "position": 1000,
            "duration": 1200000,
        }]

        rows = self.spider._history_import_rows(cloud, local)

        self.assertEqual(rows, [])

    def test_history_sync_refreshes_local_snapshot_before_import(self):
        now = int(time.time() * 1000)
        initial = [{
            "key": "local@@@vod@@@1", "vodName": "测试剧集", "vodRemarks": "S01E06",
            "createTime": now - 60000, "position": 1000, "duration": 1200000,
        }]
        fresh = [{
            "key": "local@@@vod@@@1", "vodName": "测试剧集", "vodRemarks": "S01E06",
            "createTime": now, "position": 900000, "duration": 1200000,
        }]
        cloud = [{
            "key": "cloud@@@vod@@@1", "vodName": "测试剧集", "vodRemarks": "S01E06",
            "createTime": now + 86400000, "position": 1000, "duration": 1200000,
        }]
        self.spider._history_share_policy = {"follow": False, "watch": False}
        self.spider._history_share_policy_loaded = True
        self.spider._capture_native_history = Mock(side_effect=[initial, fresh])
        self.spider._atvp_fetch_history = Mock(return_value=cloud)
        self.spider._import_native_history = Mock(return_value=0)
        self.spider._atvp_history_push = Mock()

        result = self.spider._sync_history_once()

        imported_rows = self.spider._import_native_history.call_args.args[0]
        self.assertEqual(imported_rows, [])
        self.assertEqual(result["merged"], self.spider._merge_native_history(initial, cloud)[0])
        self.assertEqual(result["import_rows"], [])

    def test_history_sync_reconciles_full_snapshot_when_import_delta_is_empty(self):
        item = {
            "media_type": "tv", "tmdb_id": 101, "source_id": "tmdb:tv:101",
            "title": "沧元图", "trackingSeason": 1, "seen_episode": "S01E03",
        }
        play_id = self.spider._build_followplay(
            "1@episode-14", item, "resource-101", 1, 14, "S01E14",
        )
        merged = [{
            "key": "site@@@resource-101@@@1", "vodName": "沧元图",
            "episodeUrl": "S01E14$" + play_id,
            "createTime": int(time.time() * 1000),
            "position": 1200000, "duration": 1200000,
        }]
        self.spider._follow_memory = {"version": 2, "items": {"101": item}}
        self.spider._capture_native_history = Mock(return_value=[])
        self.spider._atvp_fetch_history = Mock(return_value=merged)
        self.spider._merge_native_history = Mock(return_value=(merged, []))
        self.spider._history_import_rows = Mock(return_value=[])
        self.spider._import_native_history = Mock(return_value=0)

        result = self.spider._sync_history_once()
        self.spider._apply_history_sync_result("atvp-history-snapshot", result)

        self.assertEqual(result["merged"], merged)
        self.assertEqual(result["import_rows"], [])
        self.assertEqual(result["progress"], 1)
        self.assertEqual(self.spider._follow_memory["items"]["101"]["seen_episode"], "S01E14")

    def test_older_cloud_snapshot_cannot_regress_follow_progress_or_binding(self):
        item = {
            "media_type": "tv", "tmdb_id": 101, "source_id": "tmdb:tv:101",
            "title": "沧元图", "trackingSeason": 1,
            "history_episode": "S01E14", "history_position": 600000,
            "history_duration": 1200000, "alist_vod_id": "resource-new",
        }
        old_play_id = self.spider._build_followplay(
            "1@episode-3", item, "resource-old", 1, 3, "S01E03",
        )
        self.spider._follow_memory = {"version": 2, "items": {"101": item}}

        changed = self.spider._reconcile_follow_histories([{
            "vodName": "沧元图", "episodeUrl": "S01E03$" + old_play_id,
            "position": 100000, "duration": 1200000,
        }])

        self.assertEqual(changed, 0)
        current = self.spider._follow_memory["items"]["101"]
        self.assertEqual(current["history_episode"], "S01E14")
        self.assertEqual(current["history_position"], 600000)
        self.assertEqual(current["alist_vod_id"], "resource-new")

    def test_same_episode_older_position_cannot_regress_progress(self):
        item = {
            "media_type": "tv", "tmdb_id": 101, "source_id": "tmdb:tv:101",
            "title": "沧元图", "trackingSeason": 1,
            "history_episode": "S01E14", "history_position": 600000,
            "history_duration": 1200000,
        }
        play_id = self.spider._build_followplay(
            "1@episode-14", item, "resource-101", 1, 14, "S01E14",
        )
        self.spider._follow_memory = {"version": 2, "items": {"101": item}}

        changed = self.spider._reconcile_follow_histories([{
            "vodName": "沧元图", "episodeUrl": "S01E14$" + play_id,
            "position": 100000, "duration": 1200000,
        }])

        self.assertEqual(changed, 0)
        self.assertEqual(self.spider._follow_memory["items"]["101"]["history_position"], 600000)

    def test_follow_history_prefers_higher_episode_over_newer_lower_episode(self):
        item = {
            "media_type": "tv", "tmdb_id": 101, "source_id": "tmdb:tv:101",
            "title": "沧元图", "trackingSeason": 1,
        }
        low_id = self.spider._build_followplay(
            "1@episode-3", item, "resource-101", 1, 3, "S01E03",
        )
        high_id = self.spider._build_followplay(
            "1@episode-14", item, "resource-101", 1, 14, "S01E14",
        )
        histories = [
            {"episodeUrl": "S01E03$" + low_id, "createTime": 2000, "position": 1000, "duration": 2000},
            {"episodeUrl": "S01E14$" + high_id, "createTime": 1000, "position": 1000, "duration": 2000},
        ]

        selected = self.spider._atvp_history_for_item(item, histories)

        self.assertIn("S01E14", selected["episodeUrl"])

    def test_history_sync_skips_second_local_export_when_cloud_has_no_delta(self):
        now = int(time.time() * 1000)
        local = [{
            "key": "local@@@vod@@@1", "vodName": "测试剧集", "vodRemarks": "S01E06",
            "createTime": now, "position": 900000, "duration": 1200000,
        }]
        cloud = [{
            "key": "cloud@@@vod@@@1", "vodName": "测试剧集", "vodRemarks": "S01E06",
            "createTime": now - 60000, "position": 1000, "duration": 1200000,
        }]
        self.spider._history_share_policy = {"follow": False, "watch": False}
        self.spider._history_share_policy_loaded = True
        self.spider._capture_native_history = Mock(return_value=local)
        self.spider._atvp_fetch_history = Mock(return_value=cloud)
        self.spider._import_native_history = Mock(return_value=0)
        self.spider._atvp_history_push = Mock()

        result = self.spider._sync_history_once()

        self.assertEqual(self.spider._capture_native_history.call_count, 1)
        self.spider._import_native_history.assert_called_once_with([])
        self.assertEqual(result["imported"], 0)

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

    def test_already_followed_candidate_returns_terminal_feedback_immediately(self):
        candidate = {
            "title": "测试剧集", "match_title": "测试剧集",
            "history_keys": ["site@@@vod@@@1"],
        }
        self.spider._follow_memory = {"version": 2, "items": {
            "101": {
                "tmdb_id": 101, "title": "测试剧集",
                "history_keys": ["site@@@vod@@@1"],
            },
        }}
        self.spider._resolve_follow_candidate = Mock(
            side_effect=AssertionError("已追更候选不应再次启动后台解析")
        )

        result = json.loads(self.spider._start_follow_candidate_add(
            self.spider._encode_follow_candidate(candidate)
        ))

        self.assertIn("已在追更管理", result["msg"])
        self.assertFalse(self.spider._follow_enrich_jobs)

    def test_candidate_card_exposes_running_state_when_category_refreshes(self):
        candidate = {"title": "测试剧集", "match_title": "测试剧集", "sources": ["播放记录"]}
        self.spider._set_follow_action_status(
            "running", "正在确认追更：测试剧集", "candidate", "测试剧集",
        )

        card = self.spider._follow_candidate_card(candidate)

        self.assertIn("正在确认", card["vod_remarks"])

    def test_candidate_history_clear_requires_confirmation_and_deletes_exact_keys(self):
        candidate = {
            "title": "不追更剧集", "match_title": "不追更剧集",
            "sources": ["播放记录"],
            "history_keys": ["site@@@vod@@@1", "site@@@vod@@@2"],
        }
        self.spider._native_history_delete_java = Mock(return_value=2)
        self.spider._atvp_history_delete = Mock(return_value=True)
        self.spider._ensure_atvp_connection = Mock(return_value=True)
        self.spider._alist_tvbox_plugin = True
        self.spider.history_username = "user"
        self.spider.history_password = "pass"
        self.spider._refresh_follow_categories = Mock(return_value=True)

        requested = json.loads(self.spider._request_follow_candidate_clear(
            self.spider._encode_follow_candidate(candidate)
        ))
        pending = dict(self.spider._follow_action_state["pending"])
        completed = json.loads(self.spider._execute_follow_candidate_clear(pending["nonce"]))

        self.assertIn("待确认清理播放记录", requested["msg"])
        self.assertIn("已清理播放记录", completed["msg"])
        self.spider._native_history_delete_java.assert_called_once_with(candidate["history_keys"])
        self.assertEqual(
            [call.args[0] for call in self.spider._atvp_history_delete.call_args_list],
            candidate["history_keys"],
        )

    def test_candidate_clear_mode_keeps_favorites_but_targets_history_only(self):
        candidate = {
            "title": "收藏与记录剧集", "match_title": "收藏与记录剧集",
            "sources": ["收藏", "播放记录"],
            "keep_keys": ["keep@@@vod@@@1"],
            "history_keys": ["history@@@vod@@@1"],
        }
        self.spider._native_follow_candidates = Mock(return_value=([candidate], []))

        result = self.spider._category_follow_candidates(1, {"mode": "clear"})
        card = result["list"][0]

        self.assertTrue(card["action"].startswith(self.spider.FOLLOW_CANDIDATE_CLEAR_PREFIX))
        self.assertIn("仅清理播放记录", card["vod_remarks"])
        self.assertIn("收藏保留", card["vod_remarks"])

    def test_candidate_clear_without_history_credentials_keeps_local_record(self):
        candidate = {
            "title": "不追更剧集", "match_title": "不追更剧集",
            "sources": ["播放记录"], "history_keys": ["site@@@vod@@@1"],
        }
        self.spider._alist_tvbox_plugin = True
        self.spider._ensure_atvp_connection = Mock(return_value=True)
        self.spider._native_history_delete_java = Mock(return_value=1)
        self.spider._refresh_follow_categories = Mock(return_value=True)

        self.spider._request_follow_candidate_clear(
            self.spider._encode_follow_candidate(candidate)
        )
        pending = dict(self.spider._follow_action_state["pending"])
        result = json.loads(self.spider._execute_follow_candidate_clear(pending["nonce"]))

        self.assertIn("未配置History写入账号", result["msg"])
        self.spider._native_history_delete_java.assert_not_called()

    def test_history_delete_reauthenticates_once_after_expired_session(self):
        self.spider._alist_tvbox_plugin = True
        self.spider.atvp_api = "http://192.168.1.10:4568"
        self.spider.atvp_token = "token"
        self.spider.history_username = "user"
        self.spider.history_password = "pass"
        self.spider._history_auth_token = "expired"
        expired = Mock(status_code=401)
        success = Mock(status_code=204)
        self.spider._atvp_session = Mock()
        self.spider._atvp_session.headers = {"Authorization": "expired"}
        self.spider._atvp_session.delete.side_effect = [expired, success]
        self.spider._atvp_history_login = Mock(return_value=True)

        self.assertTrue(self.spider._atvp_history_delete("site@@@vod@@@1"))

        self.spider._atvp_history_login.assert_called_once_with(force=True)
        self.assertEqual(self.spider._atvp_session.delete.call_count, 2)

    def test_history_delete_falls_back_to_authenticated_id_delete_after_server_error(self):
        class JsonResponse(object):
            def __init__(self, payload):
                self.status_code = 200
                self.headers = {}
                self.payload = json.dumps(payload).encode("utf-8")

            def iter_content(self, chunk_size=None):
                return iter((self.payload,))

            def close(self):
                pass

        self.spider._alist_tvbox_plugin = True
        self.spider.atvp_api = "https://history.example.com"
        self.spider.atvp_token = "token"
        self.spider.history_username = "user"
        self.spider.history_password = "pass"
        self.spider._history_auth_token = "history-token"
        failed = Mock(status_code=500)
        failed.close = Mock()
        success = Mock(status_code=200)
        success.close = Mock()
        self.spider._atvp_session = Mock()
        self.spider._atvp_session.headers = {"Authorization": "fixture-history-token"}
        self.spider._atvp_session.delete.side_effect = [failed, success]
        self.spider._atvp_session.get.return_value = JsonResponse({
            "id": 37, "key": "site@@@vod@@@1",
        })

        self.assertTrue(self.spider._atvp_history_delete("site@@@vod@@@1"))

        self.spider._atvp_session.get.assert_called_once()
        self.assertEqual(
            self.spider._atvp_session.delete.call_args_list[1].args[0],
            "https://history.example.com/api/history/37",
        )

    def test_history_delete_fallback_rejects_mismatched_key(self):
        class JsonResponse(object):
            status_code = 200
            headers = {}

            def iter_content(self, chunk_size=None):
                return iter((json.dumps({
                    "id": 37, "key": "different@@@history@@@key",
                }).encode("utf-8"),))

            def close(self):
                pass

        self.spider._alist_tvbox_plugin = True
        self.spider.atvp_api = "https://history.example.com"
        self.spider.atvp_token = "token"
        self.spider.history_username = "user"
        self.spider.history_password = "pass"
        self.spider._history_auth_token = "history-token"
        failed = Mock(status_code=500)
        failed.close = Mock()
        self.spider._atvp_session = Mock()
        self.spider._atvp_session.headers = {"Authorization": "fixture-history-token"}
        self.spider._atvp_session.delete.return_value = failed
        self.spider._atvp_session.get.return_value = JsonResponse()

        with self.assertRaises(RuntimeError):
            self.spider._atvp_history_delete("site@@@vod@@@1")

        self.assertEqual(self.spider._atvp_session.delete.call_count, 1)

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

    def test_scheduled_follow_refresh_falls_back_to_loopback_category_refresh(self):
        generation = self.spider._follow_refresh_generation
        self.spider._refresh_visible_follow_category = Mock(return_value=False)
        self.spider._refresh_native_category = Mock(return_value=True)

        with patch.object(MODULE.time, "sleep", return_value=None):
            self.spider._refresh_follow_categories_worker(generation)

        self.spider._refresh_visible_follow_category.assert_called_once()
        self.spider._refresh_native_category.assert_called_once()

    def test_history_ui_refresh_posts_native_history_and_home_events(self):
        calls = []

        class FakeRefreshEvent(object):
            @staticmethod
            def history():
                calls.append("history")

            @staticmethod
            def home():
                calls.append("home")

        fake_java = types.ModuleType("java")
        fake_java.jclass = lambda _name: FakeRefreshEvent
        with patch.dict(sys.modules, {"java": fake_java}):
            self.assertTrue(self.spider._refresh_native_history_views())

        self.assertEqual(calls, ["history", "home"])

    def test_history_ui_refresh_waits_for_fongmi_save_and_refreshes_on_return(self):
        scheduled = []

        def start_timer(delay, target, args=(), name="timer"):
            scheduled.append((delay, target, args, name))
            return object()

        self.spider._tasks.start_timer = Mock(side_effect=start_timer)
        self.spider._refresh_native_history_views = Mock(return_value=True)
        self.spider._refresh_local_follow_progress = Mock(return_value=True)
        self.spider._refresh_follow_categories = Mock(return_value=True)
        self.spider._current_fongmi_activity = Mock()
        self.spider._cache["atvp-history-snapshot"] = (time.time(), [{"key": "old"}])
        self.spider._persistent_cache["atvp-history-snapshot"] = (
            time.time(), [{"key": "old"}],
        )

        self.assertTrue(self.spider._schedule_native_history_ui_refresh())
        self.assertNotIn("atvp-history-snapshot", self.spider._cache)
        self.assertNotIn("atvp-history-snapshot", self.spider._persistent_cache)
        self.assertEqual(scheduled[0][0], 1.2)

        _delay, callback, args, _name = scheduled.pop(0)
        callback(*args)
        self.assertEqual(scheduled[0][0], 5.2)
        self.spider._refresh_local_follow_progress.assert_not_called()

        _delay, callback, args, _name = scheduled.pop(0)
        callback(*args)
        self.spider._refresh_local_follow_progress.assert_called_once()
        self.assertFalse(scheduled)
        self.assertEqual(self.spider._refresh_local_follow_progress.call_count, 1)
        self.assertEqual(self.spider._refresh_native_history_views.call_count, 2)

    def test_new_playback_supersedes_pending_history_ui_refresh(self):
        scheduled = []
        self.spider._tasks.start_timer = Mock(
            side_effect=lambda delay, target, args=(), name="timer": scheduled.append(
                (target, args)
            ) or object()
        )
        self.spider._refresh_native_history_views = Mock(return_value=True)

        self.assertTrue(self.spider._schedule_native_history_ui_refresh())
        old_callback, old_args = scheduled[-1]
        self.assertTrue(self.spider._schedule_native_history_ui_refresh())
        old_callback(*old_args)

        self.spider._refresh_native_history_views.assert_not_called()

    def test_destroy_invalidates_pending_history_ui_refresh(self):
        scheduled = []
        self.spider._tasks.start_timer = Mock(
            side_effect=lambda delay, target, args=(), name="timer": scheduled.append(
                (target, args)
            ) or object()
        )
        self.spider._refresh_native_history_views = Mock(return_value=True)

        self.assertTrue(self.spider._schedule_native_history_ui_refresh())
        callback, args = scheduled[-1]
        self.spider.destroy()
        callback(*args)

        self.spider._refresh_native_history_views.assert_not_called()

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
        sources = str(merged["vod_play_from"]).split("$$$")
        groups = str(merged["vod_play_url"]).split("$$$")
        self.assertIn("夸克分享B", sources[0])
        incomplete_index = next(index for index, source in enumerate(sources) if "夸克分享A" in source)
        self.assertIn("S01E02补全$play-b-2", groups[incomplete_index])
        self.assertIn("同盘补全 1 集", merged["vod_remarks"])

    def test_complete_route_is_default_over_single_episode_higher_quality(self):
        item = {
            "media_type": "tv", "tmdb_id": 270603,
            "title": "遭到流放的转生重骑士凭借游戏知识大开无双",
            "trackingSeason": 1, "latest_episode": "S01E06",
        }
        complete = {
            "vod_play_from": "完整1080P",
            "vod_play_url": "#".join(
                "S01E%02d$complete-%d" % (episode, episode)
                for episode in range(1, 7)
            ),
            "resource_id": "complete-resource",
            "group_seasons": [1], "group_providers": ["quark"],
            "group_quality": [{"resolution": 16, "total": 70}],
            "_resource_mode": "vod",
        }
        single = {
            "vod_play_from": "单集4K",
            "vod_play_url": "S01E06$single-6",
            "resource_id": "single-resource",
            "group_seasons": [1], "group_providers": ["baidu"],
            "group_quality": [{"resolution": 20, "total": 99}],
            "_resource_mode": "vod",
        }

        merged = self.spider._merge_resource_vods(
            [complete, single], item, "tmdb:tv:270603", {"vod_name": item["title"]},
            preferred_resource_id="single-resource",
        )

        sources = merged["vod_play_from"].split("$$$")
        self.assertIn("完整1080P", sources[0])
        self.assertIn("单集4K", sources[1])
        self.assertNotIn("同盘补全", merged["vod_remarks"])

    def test_verified_resume_route_survives_single_route_limit(self):
        self.spider.resource_limit = 1
        item = {
            "media_type": "tv", "tmdb_id": 101, "title": "测试剧集",
            "trackingSeason": 1, "latest_episode": "S01E06",
            "_bound_route_validated": True,
            "last_play_route": {"season": 1, "episode": 6},
        }
        complete = {
            "vod_play_from": "完整线路",
            "vod_play_url": "#".join(
                "S01E%02d$complete-%d" % (episode, episode)
                for episode in range(1, 7)
            ),
            "resource_id": "complete-resource", "group_seasons": [1],
            "group_providers": ["quark"], "_resource_mode": "vod",
        }
        resume = {
            "vod_play_from": "续播线路", "vod_play_url": "S01E06$resume-6",
            "resource_id": "resume-resource", "group_seasons": [1],
            "group_providers": ["baidu"], "_resource_mode": "vod",
        }

        merged = self.spider._merge_resource_vods(
            [complete, resume], item, "tmdb:tv:101", {"vod_name": "测试剧集"},
            preferred_resource_id="resume-resource",
        )

        self.assertEqual(len(merged["vod_play_from"].split("$$$")), 1)
        self.assertIn("继续播放", merged["vod_play_from"])
        self.assertIn("续播线路", merged["vod_play_from"])

    def test_exact_resume_group_wins_with_same_resource_and_single_route_limit(self):
        self.spider.resource_limit = 1
        item = {
            "media_type": "tv", "tmdb_id": 101, "title": "测试剧集",
            "trackingSeason": 3, "latest_episode": "S03E06",
            "history_episode": "S02E03", "_resume_verified": True,
        }
        vod = {
            "vod_play_from": "第三季完整$$$第二季续播",
            "vod_play_url": "#".join(
                "S03E%02d$season-3-%d" % (episode, episode)
                for episode in range(1, 7)
            ) + "$$$S02E03$season-2-resume",
            "resource_id": "shared-resource",
            "group_seasons": [3, 2],
            "group_providers": ["quark", "quark"],
            "_resource_mode": "vod",
        }

        merged = self.spider._merge_resource_vods(
            [vod], item, "tmdb:tv:101", {"vod_name": "测试剧集"},
            preferred_resource_id="shared-resource",
        )

        self.assertEqual(len(merged["vod_play_from"].split("$$$")), 1)
        self.assertIn("第二季续播", merged["vod_play_from"])
        self.assertIn("S02E03", merged["vod_play_url"])

    def test_noncanonical_provider_does_not_enable_episode_completion(self):
        item = {
            "media_type": "tv", "tmdb_id": 101, "title": "测试剧集",
            "trackingSeason": 1, "latest_episode": "S01E03",
        }
        merged = self.spider._merge_resource_vods([
            {
                "vod_play_from": "来源A", "vod_play_url": "S01E01$a-1#S01E03$a-3",
                "resource_id": "opaque-a", "group_providers": ["provider-x"],
            },
            {
                "vod_play_from": "来源B", "vod_play_url": "S01E02$b-2",
                "resource_id": "opaque-b", "group_providers": ["provider-x"],
            },
        ], item, "tmdb:tv:101", {"vod_name": "测试剧集"})

        self.assertNotIn("补全", merged["vod_play_url"])
        self.assertNotIn("同盘补全", merged["vod_remarks"])

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

        conflict_group = next(
            group for group in str(merged["vod_play_url"]).split("$$$")
            if any(
                (self.spider._parse_followplay(part.rpartition("$")[2]) or {}).get("resourceId")
                == "opaque-conflict-id"
                for part in group.split("#")
            )
        )
        self.assertNotIn("补全", conflict_group)
        self.assertNotIn("同盘补全", merged["vod_remarks"])

    def test_pansou_provider_aliases_domains_and_offline_types_are_recognized(self):
        cases = {
            "https://115cdn.com/s/share-a": "pan115",
            "https://anxia.com/s/share-b": "pan115",
            "https://caiyun.feixin.10086.cn/share-c": "mobile",
            "magnet:?xt=urn:btih:0123456789abcdef0123456789abcdef01234567": "magnet",
            "ed2k://|file|sample.mkv|123|0123456789ABCDEF0123456789ABCDEF|/": "ed2k",
            "aliyun": "ali",
            "123": "pan123",
            "115": "pan115",
            "0": "ali",
            "6": "mobile",
        }
        for value, expected in cases.items():
            with self.subTest(value=value):
                self.assertEqual(self.spider._resource_provider_key(value), expected)

    def test_resource_score_accepts_pansou_work_title_and_note_fields(self):
        item = {
            "media_type": "tv", "tmdb_id": 270603,
            "title": "遭到流放的转生重骑士凭借游戏知识大开无双",
            "year": "2026", "season_count": 1, "trackingSeason": 1,
        }
        work_title = {
            "vod_id": "work-title", "work_title": item["title"] + " S01E06 1080P",
        }
        note = {
            "vod_id": "note", "note": item["title"] + " 2026 更新至第6集",
        }

        self.assertGreater(self.spider._resource_score(work_title, item, ""), 0)
        self.assertGreater(self.spider._resource_score(note, item, ""), 0)

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

    def test_playback_delimiter_scans_remain_bounded_on_huge_inputs(self):
        huge_groups = "$$$".join("S01E01$play-%d" % index for index in range(50000))
        huge_episodes = "#".join("S01E%03d$play-%d" % (index % 999, index) for index in range(50000))

        started = time.monotonic()
        groups, groups_limited = MODULE._split_bounded_shared(
            huge_groups, "$$$", self.spider.RESOURCE_PLAY_GROUP_SCAN_LIMIT,
        )
        parts, parts_limited = MODULE._split_bounded_shared(
            huge_episodes, "#", self.spider.RESOURCE_GROUP_EPISODE_LIMIT,
        )
        split_groups = self.spider._split_resource_vod_groups({
            "vod_play_from": huge_groups,
            "vod_play_url": huge_groups,
        })
        score = self.spider._resource_group_match_score(
            huge_episodes, {"history_episode": "S01E01", "trackingSeason": 1},
        )
        elapsed = time.monotonic() - started

        self.assertTrue(groups_limited)
        self.assertTrue(parts_limited)
        self.assertEqual(len(groups), self.spider.RESOURCE_PLAY_GROUP_SCAN_LIMIT)
        self.assertEqual(len(parts), self.spider.RESOURCE_GROUP_EPISODE_LIMIT)
        self.assertEqual(len(split_groups), self.spider.RESOURCE_PLAY_GROUP_SCAN_LIMIT)
        self.assertGreaterEqual(score, 1)
        self.assertLess(elapsed, 1.0)
        source = SOURCE.read_text(encoding="utf-8")
        self.assertNotIn('.split("$$$")', source)
        self.assertNotIn('.split("#")', source)

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

    def test_oversized_play_id_is_rejected_before_validation_or_network(self):
        item = {
            "media_type": "tv", "tmdb_id": 101, "title": "测试剧集",
            "trackingSeason": 1, "latest_episode": "S01E01",
        }
        oversized = "x" * (1536 * 1024)
        detail = {"list": [{
            "vod_name": "测试剧集",
            "vod_play_from": "异常线路",
            "vod_play_url": "S01E01$" + oversized,
        }]}

        with patch.object(self.spider, "_atvp_play") as atvp_play:
            validated = self.spider._validated_playable_detail(
                detail, item, time.monotonic() + 2, 1,
            )
            self.assertIsNone(validated)
            atvp_play.assert_not_called()

        self.spider._ensure_atvp_connection = Mock(return_value=True)
        with self.assertRaisesRegex(RuntimeError, "播放线路过长"):
            self.spider._atvp_play(oversized)
        self.spider._ensure_atvp_connection.assert_not_called()

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

    def test_followed_tmdb_detail_uses_persisted_metadata_without_sync_tmdb_request(self):
        self.spider._follow_memory = {"version": 2, "items": {
            "326695": {
                "tmdb_id": 326695, "title": "择日飞升", "pic": "poster.jpg",
                "year": "2026", "season_count": 1, "latest_episode": "S01E06",
                "latest_episode_name": "第 6 集", "next_air_date": "2026-08-15",
            },
        }}
        self.spider._tmdb_detail = Mock(side_effect=AssertionError("must not block on TMDB"))
        self.spider._start_follow_enrichment = Mock(return_value=True)
        self.spider._alist_detail_from_metadata = Mock(return_value={"list": [{"vod_name": "择日飞升"}]})

        result = self.spider.detailContent(["tmdb:tv:326695"])

        self.assertEqual(result["list"][0]["vod_name"], "择日飞升")
        self.spider._tmdb_detail.assert_not_called()
        metadata = self.spider._alist_detail_from_metadata.call_args.args[1]["list"][0]
        self.assertEqual(metadata["vod_pic"], "poster.jpg")
        self.assertEqual(metadata["vod_remarks"], "已播 S01E06 · 下集 2026-08-15")
        self.assertIn("当前更新至 S01E06 第 6 集", metadata["vod_content"])
        self.assertIsInstance(
            self.spider._alist_detail_from_metadata.call_args.kwargs.get("deadline"), float,
        )

    def test_detail_deadline_is_not_reset_after_metadata_stage(self):
        self.spider._alist_tvbox_plugin = True
        self.spider._follow_memory = {"version": 2, "items": {}}
        metadata = {"list": [{"vod_id": "tmdb:tv:101", "vod_name": "测试剧集"}]}
        self.spider._atvp_history_snapshot = Mock(return_value=[])
        self.spider._ready_resource_detail = Mock(return_value=None)
        self.spider._bound_resource_row = Mock(return_value=None)
        self.spider._resource_candidates = Mock(return_value=[])
        self.spider._schedule_entry_resource_preheat = Mock(return_value=False)
        self.spider._entry_resource_preheat_pending = Mock(return_value=False)
        self.spider._supplement_resource_state = Mock(return_value=(0, False))
        deadline = time.monotonic() + 2

        self.spider._alist_detail_from_metadata(
            "tmdb:tv:101", metadata, deadline=deadline,
        )

        ready_deadline = self.spider._ready_resource_detail.call_args.kwargs["deadline"]
        candidate_deadline = self.spider._resource_candidates.call_args.kwargs["deadline"]
        self.assertLessEqual(ready_deadline, deadline)
        self.assertLessEqual(candidate_deadline, deadline)

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

    def test_safe_atvp_direct_url_survives_unknown_desktop_probe(self):
        self.spider.atvp_api = "https://atvp.example"
        self.spider.atvp_token = "token"
        direct_output = {
            "parse": 0,
            "jx": 0,
            "url": "https://cdn.example/episode-1.m3u8?sig=ok",
            "header": {"User-Agent": "test"},
        }
        self.spider._atvp_play = Mock(return_value=direct_output)
        self.spider._probe_media_output = Mock(return_value=None)

        result = self.spider._validated_playable_detail(
            {"list": [{
                "vod_play_from": "安全线路",
                "vod_play_url": "S01E01$1@episode-1",
            }]},
            {"latest_episode": "S01E01", "trackingSeason": 1},
            time.monotonic() + 10,
            1,
            resource_id="resource-101",
            resource_mode="vod",
        )

        self.assertIsNotNone(result)
        self.assertEqual(result["list"][0]["vod_play_from"], "安全线路")
        self.assertEqual(self.spider._route_probe_cache, {})

    def test_player_returns_parse_verified_url_when_desktop_probe_is_unknown(self):
        self.spider.atvp_api = "https://atvp.example"
        self.spider.atvp_token = "token"
        item = {"media_type": "tv", "tmdb_id": 101, "title": "测试剧集"}
        play_id = self.spider._build_followplay(
            "1@episode-1", item, "resource-101", 1, 1, "S01E01",
        )
        direct_output = {
            "parse": 0,
            "jx": 0,
            "url": "https://cdn.example/episode-1.m3u8?sig=ok",
            "header": {
                "User-Agent": "test",
                "Cookie": "fixture-play-cookie",
                "Authorization": "test-should-drop",
            },
        }
        self.spider._atvp_play = Mock(return_value=direct_output)
        self.spider._probe_media_output = Mock(return_value=None)

        result = self.spider.playerContent("安全线路", play_id, [])

        self.assertEqual(result["url"], direct_output["url"])
        self.assertEqual(result["header"], {
            "User-Agent": "test",
            "Cookie": "fixture-play-cookie",
        })
        self.assertEqual(self.spider._route_probe_cache, {})

    def test_media_probe_keeps_required_cookie_and_drops_unapproved_headers(self):
        captured = {}
        self.spider._resolved_media_target = Mock(return_value=(
            MODULE.urlparse("https://cdn.example/video.mp4?sig=ok"),
            ("8.8.8.8",),
        ))

        def request(_parsed, _address, headers, _deadline):
            captured.update(headers)
            return {
                "status": 206,
                "headers": {
                    "Content-Type": "video/mp4",
                    "Content-Range": "bytes 0-3/1024",
                },
                "body": b"test",
            }

        self.spider._pinned_media_request = Mock(side_effect=request)
        result = self.spider._probe_media_output({
            "parse": 0,
            "url": "https://cdn.example/video.mp4?sig=ok",
            "header": {
                "Cookie": "fixture-play-cookie",
                "Referer": "https://pan.example/",
                "Authorization": "test-should-drop",
            },
        }, deadline=time.monotonic() + 5)

        self.assertIsNotNone(result)
        self.assertEqual(captured["Cookie"], "fixture-play-cookie")
        self.assertNotIn("Authorization", captured)
        self.assertEqual(result["output"]["header"]["Cookie"], "fixture-play-cookie")

    def test_media_probe_drops_sensitive_headers_on_cross_origin_redirect(self):
        requests = []
        resolved = {
            "https://cdn.example/video.mp4": (
                MODULE.urlparse("https://cdn.example/video.mp4"),
                ("8.8.8.8",),
            ),
            "https://other.example/video.mp4": (
                MODULE.urlparse("https://other.example/video.mp4"),
                ("1.1.1.1",),
            ),
        }
        self.spider._resolved_media_target = Mock(side_effect=lambda value, deadline=None: resolved[value])

        def request(parsed, _address, headers, _deadline):
            requests.append((parsed.hostname, dict(headers)))
            if parsed.hostname == "cdn.example":
                return {
                    "status": 302,
                    "headers": {"Location": "https://other.example/video.mp4"},
                    "body": b"",
                }
            return {
                "status": 206,
                "headers": {
                    "Content-Type": "video/mp4",
                    "Content-Range": "bytes 0-3/1024",
                },
                "body": b"test",
            }

        self.spider._pinned_media_request = Mock(side_effect=request)
        result = self.spider._probe_media_output({
            "parse": 0,
            "url": "https://cdn.example/video.mp4",
            "header": {
                "Cookie": "fixture-play-cookie",
                "Origin": "https://pan.example",
                "Referer": "https://pan.example/",
            },
        }, deadline=time.monotonic() + 5)

        self.assertIsNotNone(result)
        self.assertEqual(requests[0][1]["Cookie"], "fixture-play-cookie")
        self.assertNotIn("Cookie", requests[1][1])
        self.assertNotIn("Origin", requests[1][1])
        self.assertNotIn("Referer", requests[1][1])
        self.assertEqual(result["output"]["url"], "https://other.example/video.mp4")
        self.assertNotIn("Cookie", result["output"]["header"])
        self.assertNotIn("Origin", result["output"]["header"])
        self.assertNotIn("Referer", result["output"]["header"])

    def test_player_uses_sanitized_cross_origin_output_when_redirect_target_fails(self):
        self.spider.atvp_api = "https://atvp.example"
        self.spider.atvp_token = "token"
        item = {"media_type": "tv", "tmdb_id": 101, "title": "测试剧集"}
        play_id = self.spider._build_followplay(
            "1@episode-1", item, "resource-101", 1, 1, "S01E01",
        )
        original = {
            "parse": 0,
            "url": "https://cdn.example/video.mp4",
            "header": {
                "Cookie": "fixture-play-cookie",
                "Origin": "https://pan.example",
                "Referer": "https://pan.example/",
                "User-Agent": "test-agent",
            },
        }
        self.spider._atvp_play = Mock(return_value=original)
        resolved = {
            "https://cdn.example/video.mp4": (
                MODULE.urlparse("https://cdn.example/video.mp4"), ("8.8.8.8",),
            ),
            "https://other.example/video.mp4": (
                MODULE.urlparse("https://other.example/video.mp4"), ("1.1.1.1",),
            ),
        }
        self.spider._resolved_media_target = Mock(side_effect=lambda value, deadline=None: resolved[value])

        def request(parsed, _address, _headers, _deadline):
            if parsed.hostname == "cdn.example":
                return {
                    "status": 302,
                    "headers": {"Location": "https://other.example/video.mp4"},
                    "body": b"",
                }
            return {"status": 403, "headers": {}, "body": b""}

        self.spider._pinned_media_request = Mock(side_effect=request)
        self.spider._register_playback_sync_window = Mock(return_value=True)
        original_invalidate = self.spider._invalidate_route_probe
        self.spider._invalidate_route_probe = Mock(side_effect=original_invalidate)

        result = self.spider.playerContent("线路", play_id, [])

        self.assertEqual(result["url"], "https://other.example/video.mp4")
        self.assertEqual(result["header"], {"User-Agent": "test-agent"})

    def test_route_output_rejects_conflicting_case_insensitive_headers(self):
        output = self.spider._sanitize_route_output({
            "url": "https://cdn.example/video.mp4",
            "header": {"Cookie": "first", "cookie": "second"},
        })

        self.assertIsNone(output)

    def test_route_output_rejects_oversized_cookie(self):
        output = self.spider._sanitize_route_output({
            "url": "https://cdn.example/video.mp4",
            "header": {"Cookie": "x" * (self.spider.ROUTE_COOKIE_MAX_BYTES + 1)},
        })

        self.assertIsNone(output)

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
            "vod_play_url": "#".join(
                "S01E%02d$1@replacement-%d" % (index, index) for index in range(1, 7)
            ),
        }]})
        self.spider._validated_playable_detail = Mock(return_value={"list": [{
            "vod_name": "测试剧集", "vod_play_from": "备选网盘",
            "vod_play_url": "#".join(
                "S01E%02d$1@replacement-%d" % (index, index) for index in range(1, 7)
            ),
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

    def test_bound_replacement_skips_incomplete_candidate_and_binds_complete_line(self):
        self.spider._alist_tvbox_plugin = True
        self.spider.atvp_api = "https://atvp.example"
        self.spider.atvp_token = "token"
        item = {
            "tmdb_id": 101, "source_id": "tmdb:tv:101", "media_type": "tv",
            "title": "测试剧集", "trackingSeason": 1, "latest_episode": "S01E05",
            "alist_vod_id": "old-resource",
        }
        self.spider._follow_memory = {"version": 2, "items": {"101": dict(item)}}
        rows = [
            {"vod_id": "e4-resource", "_resource_mode": "vod"},
            {"vod_id": "e5-resource", "_resource_mode": "pansou"},
        ]
        details = {
            "e4-resource": {"list": [{
                "vod_play_from": "残缺线路",
                "vod_play_url": "#".join("S01E%02d$1@old-%d" % (index, index) for index in range(1, 5)),
            }]},
            "e5-resource": {"list": [{
                "vod_play_from": "完整线路",
                "vod_play_url": "#".join("S01E%02d$1@new-%d" % (index, index) for index in range(1, 6)),
            }]},
        }
        self.spider._resource_candidates = Mock(return_value=rows)
        self.spider._resource_detail = Mock(
            side_effect=lambda row, deadline=None, **_kwargs: details[row["vod_id"]]
        )
        self.spider._validated_playable_detail = Mock(
            side_effect=lambda detail, *_args, **_kwargs: detail
        )
        self.spider._schedule_active_detail_refresh = Mock(return_value=True)

        self.assertTrue(self.spider._schedule_bound_route_replacement(item, "old-resource"))
        deadline = time.time() + 2
        while self.spider._bound_replacement_jobs and time.time() < deadline:
            time.sleep(0.01)

        self.assertEqual(
            self.spider._follow_memory["items"]["101"]["alist_vod_id"],
            "e5-resource",
        )

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

        def candidates(_item, deadline=None, background=False):
            self.assertTrue(background)
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

    def test_detail_keeps_all_independent_routes_within_limit_resolution_first(self):
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
        self.assertEqual(len(sources), 4)
        self.assertIn("4K较慢", sources[0])
        self.assertIn("1440P", sources[1])
        self.assertIn("1080P快速", sources[2])
        self.assertIn("720P", sources[3])
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
        self.assertEqual(len(sources), 4)
        self.assertIn("4K", sources[0])
        self.assertIn("1440P", sources[1])
        self.assertIn("1080P", sources[2])
        self.assertIn("720P", sources[3])

    def test_sixth_highest_quality_group_survives_global_route_selection(self):
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

        selected_sources = merged["vod_play_from"].split("$$$")
        self.assertFalse(rewritten["_route_candidates_limited"])
        self.assertFalse(rewritten["_resource_limited"])
        self.assertTrue(any("备用低清" in source for source in selected_sources), selected_sources)
        self.assertFalse(any("720P" in source for source in selected_sources), selected_sources)
        self.assertIn("线路候选已按清晰度筛选", merged["vod_remarks"])
        self.assertNotIn("资源分集过多 已截断", merged["vod_remarks"])

    def test_large_low_quality_groups_do_not_hide_later_high_quality_group(self):
        item = {"media_type": "tv", "tmdb_id": 101, "title": "测试剧集", "trackingSeason": 1}
        low_groups = [
            "#".join(
                "S01E%03d$1@low-%d-%03d" % (episode, group_index, episode)
                for episode in range(1, self.spider.RESOURCE_GROUP_EPISODE_LIMIT + 1)
            )
            for group_index in range(2)
        ]
        vod = {
            "vod_name": "测试剧集",
            "vod_play_from": "低质A$$$低质B$$$4K高质",
            "vod_play_url": "$$$".join(low_groups + ["S01E01$1@best-late"]),
            "_route_quality": [
                {"resolution": 8, "total": 10},
                {"resolution": 8, "total": 11},
                {"resolution": 20, "total": 99},
            ],
        }

        rewritten = self.spider._rewrite_resource_vod(
            vod, item, "resource-101", mode="vod", validated=True,
        )
        merged = self.spider._merge_resource_vods(
            [rewritten], item, "tmdb:tv:101", {"vod_name": "测试剧集"},
        )

        self.assertIsNotNone(merged)
        sources = merged["vod_play_from"].split("$$$")
        high_index = next(index for index, source in enumerate(sources) if "4K高质" in source)
        high_group = merged["vod_play_url"].split("$$$")[high_index]
        high_play_id = next(
            part.rpartition("$")[2]
            for part in high_group.split("#")
            if not part.rpartition("$")[2].startswith(self.spider.SELECT_PROMPT_ID)
        )
        self.assertEqual(self.spider._parse_followplay(high_play_id)["url"], "1@best-late")

    def test_resource_rewrite_stops_at_sixty_four_group_scan_boundary(self):
        item = {"media_type": "tv", "tmdb_id": 101, "title": "测试剧集", "trackingSeason": 1}
        scan_limit = self.spider.RESOURCE_PLAY_GROUP_SCAN_LIMIT
        sources = ["线路%02d" % index for index in range(1, scan_limit + 2)]
        vod = {
            "vod_name": "测试剧集",
            "vod_play_from": "$$$".join(sources),
            "vod_play_url": "$$$".join(
                "S01E01$1@route-%02d" % index for index in range(1, scan_limit + 2)
            ),
            "_route_quality": [
                {"resolution": index, "total": index}
                for index in range(1, scan_limit + 2)
            ],
        }

        rewritten = self.spider._rewrite_resource_vod(
            vod, item, "resource-101", mode="vod", validated=True,
        )
        merged = self.spider._merge_resource_vods(
            [rewritten], item, "tmdb:tv:101", {"vod_name": "测试剧集"},
        )

        rewritten_sources = rewritten["vod_play_from"].split("$$$")
        selected_sources = merged["vod_play_from"].split("$$$")
        self.assertEqual(len(rewritten_sources), scan_limit)
        self.assertEqual(len(rewritten["vod_play_url"].split("$$$")), scan_limit)
        self.assertTrue(rewritten["_route_candidates_limited"])
        self.assertTrue(any("线路64" in source for source in selected_sources), selected_sources)
        self.assertFalse(any("线路65" in source for source in rewritten_sources), rewritten_sources)
        self.assertFalse(any("线路65" in source for source in selected_sources), selected_sources)

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

    def test_detail_keeps_one_group_from_each_api_before_filling_extra_routes(self):
        self.spider._alist_tvbox_plugin = True
        self.spider.route_preheat = False
        self.spider.resource_limit = 5
        self.spider._atvp_history_snapshot = Mock(return_value=[])
        candidates = [
            {"vod_id": "vod1-resource", "_resource_mode": "vod1"},
            {"vod_id": "vod-resource", "_resource_mode": "vod"},
            {"vod_id": "pansou-resource", "_resource_mode": "pansou"},
            {"vod_id": "telegram-resource", "_resource_mode": "telegram"},
        ]
        self.spider._resource_candidates = Mock(return_value=candidates)
        self.spider._resource_detail = Mock(return_value={
            "list": [{"vod_name": "测试剧集", "vod_play_url": "S01E01$1@raw"}],
        })

        def rewrite(_vod, _item, resource_id, mode="vod", **_kwargs):
            group_count = 5 if mode == "vod1" else 1
            return {
                "vod_play_from": "$$$".join(
                    "%s-%d" % (mode, index + 1) for index in range(group_count)
                ),
                "vod_play_url": "$$$".join(
                    "S01E01$route-%s-%d" % (mode, index + 1) for index in range(group_count)
                ),
                "resource_id": resource_id,
                "group_seasons": [1] * group_count,
                "group_providers": [mode] * group_count,
                "group_quality": [{"resolution": 10, "total": 50}] * group_count,
            }

        self.spider._rewrite_resource_vod = Mock(side_effect=rewrite)

        result = self.spider._alist_detail_from_metadata(
            "tmdb:tv:101",
            {"list": [{"vod_id": "tmdb:tv:101", "vod_name": "测试剧集"}]},
        )

        sources = result["list"][0]["vod_play_from"].split("$$$")
        self.assertEqual(self.spider._resource_detail.call_count, 4)
        self.assertEqual(len(sources), 5)
        for mode in ("vod1", "vod", "pansou", "telegram"):
            self.assertTrue(any(mode in source for source in sources), (mode, sources))

    def test_detail_tries_second_candidate_from_each_api_after_first_failure(self):
        self.spider._alist_tvbox_plugin = True
        self.spider.route_preheat = False
        self.spider.resource_limit = 5
        self.spider._atvp_history_snapshot = Mock(return_value=[])
        modes = ("vod1", "vod", "pansou", "telegram")
        candidates = [
            {"vod_id": "%s-%s" % (mode, round_name), "_resource_mode": mode}
            for round_name in ("first", "second")
            for mode in modes
        ]
        self.spider._resource_candidates = Mock(return_value=candidates)

        def detail(row, deadline=None):
            if str(row["vod_id"]).endswith("-first"):
                raise RuntimeError("first route unavailable")
            return {
                "list": [{
                    "vod_name": "测试剧集",
                    "vod_play_from": row["_resource_mode"],
                    "vod_play_url": "S01E01$1@%s" % row["vod_id"],
                }],
            }

        self.spider._resource_detail = Mock(side_effect=detail)

        result = self.spider._alist_detail_from_metadata(
            "tmdb:tv:101",
            {"list": [{"vod_id": "tmdb:tv:101", "vod_name": "测试剧集"}]},
        )

        sources = result["list"][0]["vod_play_from"].split("$$$")
        self.assertEqual(self.spider._resource_detail.call_count, 8)
        self.assertEqual(len(sources), 4)
        for mode in modes:
            self.assertTrue(any(mode in source for source in sources), (mode, sources))

    def test_merge_ranks_all_extra_routes_before_applying_route_limit(self):
        self.spider.resource_limit = 5
        item = {"media_type": "tv", "tmdb_id": 101, "title": "测试剧集", "trackingSeason": 1}
        vods = []
        for mode in ("vod1", "vod", "pansou", "telegram"):
            vods.append({
                "vod_play_from": "%s-base" % mode,
                "vod_play_url": "S01E01$%s-base" % mode,
                "resource_id": "%s-base" % mode,
                "group_quality": [{"resolution": 10, "total": 50}],
                "_resource_mode": mode,
            })
        vods.extend((
            {
                "vod_play_from": "vod-low-extra",
                "vod_play_url": "S01E01$vod-low-extra",
                "resource_id": "vod-low-extra",
                "group_quality": [{"resolution": 8, "total": 1}],
                "_resource_mode": "vod",
            },
            {
                "vod_play_from": "vod-best-extra",
                "vod_play_url": "S01E01$vod-best-extra",
                "resource_id": "vod-best-extra",
                "group_quality": [{"resolution": 40, "total": 900}],
                "_resource_mode": "vod",
            },
        ))

        merged = self.spider._merge_resource_vods(
            vods, item, "tmdb:tv:101", {"vod_name": "测试剧集"},
        )

        sources = merged["vod_play_from"].split("$$$")
        self.assertEqual(len(sources), 5)
        self.assertTrue(any("vod-best-extra" in source for source in sources), sources)
        self.assertFalse(any("vod-low-extra" in source for source in sources), sources)

    def test_four_resource_api_shapes_keep_decorated_title_matches(self):
        item = {
            "media_type": "tv",
            "tmdb_id": 270603,
            "title": "遭到流放的转生重骑士凭借游戏知识大开无双",
            "year": "2026",
            "season_count": 1,
            "trackingSeason": 1,
        }
        rows = [
            {
                "id": "vod1-270603",
                "title": "遭到流放的转生重骑士凭借游戏知识大开无双 2026 1080P",
                "_resource_mode": "vod1",
            },
            {
                "vod_id": "vod-270603",
                "vod_name": "遭到流放的转生重骑士凭借游戏知识大开无双(2026) S01E01",
                "_resource_mode": "vod",
            },
            {
                "id": "pansou-270603",
                "name": "遭到流放的转生重骑士凭借游戏知识大开无双 [夸克] 更新至E06",
                "_resource_mode": "pansou",
            },
            {
                "id": "telegram-270603",
                "vod_name": "遭到流放的转生重骑士凭借游戏知识大开无双(2026)1080p S01E01-E06 内封简繁 HiveWeb",
                "_resource_mode": "telegram",
            },
        ]

        scores = [self.spider._resource_score(row, item, "") for row in rows]

        self.assertTrue(all(score > 0 for score in scores), scores)

    def test_explicit_work_title_rejects_conflicting_parent_titles(self):
        item = {
            "media_type": "tv", "tmdb_id": 270603,
            "title": "遭到流放的转生重骑士凭借游戏知识大开无双",
            "year": "2026", "season_count": 1, "trackingSeason": 1,
        }
        row = {
            "vod_id": "conflict",
            "work_title": "完全无关的另一部作品",
            "vod_name": item["title"] + " 2026 1080P",
            "title": item["title"],
            "note": item["title"] + " 更新至第6集",
        }

        self.assertEqual(self.spider._resource_score(row, item, ""), 0)

    def test_nested_work_title_rejects_conflicting_parent_title(self):
        item = {
            "media_type": "tv", "tmdb_id": 270603,
            "title": "遭到流放的转生重骑士凭借游戏知识大开无双",
            "year": "2026", "season_count": 1, "trackingSeason": 1,
        }
        row = {
            "vod_id": "nested-conflict",
            "vod_name": item["title"] + " 2026 1080P",
            "title": item["title"],
            "links": [{"work_title": "完全无关的另一部作品"}],
        }

        self.assertEqual(self.spider._resource_score(row, item, ""), 0)

    def test_raw_pansou_results_keep_link_matches_and_dedupe_the_same_share(self):
        title = "遭到流放的转生重骑士凭借游戏知识大开无双"
        item = {
            "media_type": "tv", "tmdb_id": 270603, "title": title,
            "year": "2026", "season_count": 1, "trackingSeason": 1,
        }
        payload = {"data": {
            "merged_by_type": {
                "115": [{
                    "url": "https://115cdn.com/s/share-a", "password": "a1b2",
                    "note": title + " S01E01-E06 1080P",
                    "datetime": "2026-08-10T10:00:00Z", "source": "merged-source",
                }],
                "mobile": [{
                    "url": "https://caiyun.feixin.10086.cn/share-b",
                    "note": title + " 更新至第6集",
                    "datetime": "2026-08-11T08:00:00Z", "source": "mobile-source",
                }],
            },
            "results": [{
                "title": title + " 合集",
                "channel": "result-channel",
                "datetime": "2026-08-11T09:00:00Z",
                "links": [
                    {
                        "type": "8", "url": "https://115cdn.com/s/share-a",
                        "work_title": title + " S01E06",
                    },
                    {
                        "type": "aliyun", "url": "https://www.alipan.com/s/share-c",
                        "work_title": title + " 2026 4K",
                    },
                    {
                        "type": "quark", "url": "https://pan.quark.cn/s/unrelated",
                        "work_title": "完全无关的另一部作品",
                        "note": title + " 合集消息",
                    },
                ],
            }],
        }}
        self.spider._resource_capability = Mock(return_value="present")
        self.spider._resource_api_get = Mock(return_value=payload)

        rows = self.spider._resource_search_mode("pansou", [title])

        self.assertEqual(len(rows), 4)
        self.assertTrue(all(row["_resource_mode"] == "pansou" for row in rows))
        decoded_ids = [MODULE.unquote(row["vod_id"]) for row in rows]
        self.assertEqual(sum("115cdn.com/s/share-a" in value for value in decoded_ids), 1)
        self.assertTrue(any("password=a1b2" in value for value in decoded_ids))
        providers = {
            self.spider._resource_provider_key(row.get("type"), MODULE.unquote(row["vod_id"]))
            for row in rows
        }
        self.assertEqual(providers, {"pan115", "mobile", "ali", "quark"})
        matched = [row for row in rows if self.spider._resource_score(row, item, "") > 0]
        self.assertEqual(len(matched), 3)
        unrelated = next(row for row in rows if "unrelated" in MODULE.unquote(row["vod_id"]))
        self.assertEqual(self.spider._resource_score(unrelated, item, ""), 0)

    def test_pansou_scan_budget_is_shared_fairly_across_results_and_providers(self):
        payload = {"data": {
            "merged_by_type": {
                "quark": [
                    {
                        "url": "https://pan.quark.cn/s/noise-%d" % index,
                        "work_title": "完全无关的作品 %d" % index,
                    }
                    for index in range(64)
                ],
                "ali": [{
                    "url": "https://www.alipan.com/s/ali-match",
                    "work_title": "测试剧集",
                }],
            },
            "results": [{
                "title": "测试剧集资源",
                "links": [{
                    "type": "baidu",
                    "url": "https://pan.baidu.com/s/result-match",
                    "work_title": "测试剧集",
                }],
            }],
        }}

        rows = self.spider._resource_payload_rows(payload, "pansou", limit=3)
        decoded = [MODULE.unquote(row["vod_id"]) for row in rows]

        self.assertTrue(any("result-match" in value for value in decoded), decoded)
        self.assertTrue(any("ali-match" in value for value in decoded), decoded)

    def test_pansou_link_precedes_generic_parent_when_result_limit_is_one(self):
        payload = {"data": {"results": [{
            "id": "opaque-parent-noise",
            "vod_name": "测试剧集父记录",
            "links": [{
                "type": "quark",
                "url": "https://pan.quark.cn/s/valid-child",
                "work_title": "测试剧集",
            }],
        }]}}

        rows = self.spider._resource_payload_rows(payload, "pansou", limit=1)

        self.assertEqual(len(rows), 1)
        self.assertIn("valid-child", MODULE.unquote(rows[0]["vod_id"]))
        self.assertNotEqual(rows[0]["vod_id"], "opaque-parent-noise")

    def test_duplicate_share_keeps_link_work_title_over_parent_match(self):
        title = "遭到流放的转生重骑士凭借游戏知识大开无双"
        payload = {"data": {
            "merged_by_type": {"quark": [{
                "url": "https://pan.quark.cn/s/same",
                "note": title + " 2026 1080P",
                "datetime": "2026-08-11T10:00:00Z",
            }]},
            "results": [{
                "title": title + " 合集",
                "datetime": "2026-08-10T10:00:00Z",
                "links": [{
                    "type": "quark",
                    "url": "https://pan.quark.cn/s/same",
                    "work_title": "完全无关的另一部作品",
                }],
            }],
        }}
        rows = self.spider._resource_payload_rows(payload, "pansou")

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["work_title"], "完全无关的另一部作品")
        self.assertEqual(rows[0]["vod_name"], "完全无关的另一部作品")
        self.assertEqual(rows[0]["note"], "")
        self.assertEqual(rows[0]["title"], "")
        self.assertEqual(self.spider._resource_score(rows[0], {
            "title": title, "year": "2026", "season_count": 1, "trackingSeason": 1,
        }, ""), 0)

    def test_duplicate_share_password_tie_prefers_newer_timestamp(self):
        payload = {"data": {
            "merged_by_type": {"quark": [{
                "url": "https://pan.quark.cn/s/same",
                "password": "NEW1",
                "note": "测试剧集",
                "datetime": "2026-08-11T10:00:00Z",
            }]},
            "results": [{
                "title": "测试剧集",
                "datetime": "2026-08-10T10:00:00Z",
                "links": [{
                    "type": "quark",
                    "url": "https://pan.quark.cn/s/same",
                    "password": "OLD9",
                }],
            }],
        }}

        rows = self.spider._resource_payload_rows(payload, "pansou")

        self.assertEqual(len(rows), 1)
        decoded = MODULE.unquote(rows[0]["vod_id"])
        self.assertIn("password=NEW1", decoded)
        self.assertNotIn("OLD9", decoded)

    def test_duplicate_share_timestamp_compares_rfc3339_offsets(self):
        payload = {"data": {
            "merged_by_type": {"quark": [{
                "url": "https://pan.quark.cn/s/same-offset",
                "password": "OLD1",
                "note": "测试剧集",
                "datetime": "2026-08-11T10:00:00+08:00",
            }]},
            "results": [{
                "title": "测试剧集",
                "datetime": "2026-08-11T03:00:00Z",
                "links": [{
                    "type": "quark",
                    "url": "https://pan.quark.cn/s/same-offset",
                    "password": "NEW1",
                }],
            }],
        }}

        rows = self.spider._resource_payload_rows(payload, "pansou")

        self.assertEqual(len(rows), 1)
        decoded = MODULE.unquote(rows[0]["vod_id"])
        self.assertIn("password=NEW1", decoded)
        self.assertNotIn("OLD1", decoded)

    def test_existing_password_formats_are_not_duplicated(self):
        urls = (
            "https://pan.quark.cn/s/demo?passcode=A1",
            "https://pan.quark.cn/s/demo?pass_code=A1",
            "https://pan.quark.cn/s/demo?share_pwd=A1",
            "https://pan.quark.cn/s/demo#pwd=A1",
            "https://pan.quark.cn/s/demo#password=A1",
            "https://pan.quark.cn/s/demo#A1",
            "https://pan.quark.cn/s/demo 提取码：A1",
        )
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self.spider._resource_url_with_password(url, "B2"), url)
                self.assertEqual(self.spider._resource_url_password_score(url), 1)

    def test_independent_password_fields_are_appended_to_share_urls(self):
        password_fields = (
            ("passcode", "A1"),
            ("pass_code", "B2"),
            ("share_pwd", "C3"),
            ("提取码", "D4"),
            ("访问码", "E5"),
            ("密码", "F6"),
        )
        for key, password in password_fields:
            with self.subTest(key=key):
                payload = {"data": {"results": [{
                    "title": "测试剧集",
                    "links": [{
                        "type": "quark",
                        "url": "https://pan.quark.cn/s/%s" % key,
                        key: password,
                    }],
                }]}}

                rows = self.spider._resource_payload_rows(payload, "pansou")

                self.assertEqual(len(rows), 1)
                self.assertIn(
                    "password=%s" % password,
                    MODULE.unquote(rows[0]["vod_id"]),
                )

    def test_generic_supplement_rows_append_independent_passwords(self):
        for mode in ("pansou", "telegram"):
            with self.subTest(mode=mode):
                payload = {"list": [{
                    "vod_id": "https://pan.quark.cn/s/generic-%s" % mode,
                    "vod_name": "测试剧集",
                    "pass_code": "A1B2",
                }]}

                rows = self.spider._resource_payload_rows(payload, mode)

                self.assertEqual(len(rows), 1)
                self.assertIn("password=A1B2", MODULE.unquote(rows[0]["vod_id"]))

    def test_empty_or_oversized_url_password_does_not_block_independent_password(self):
        urls = (
            "https://pan.quark.cn/s/empty-query?password=",
            "https://pan.quark.cn/s/empty-fragment#pwd=",
            "https://pan.quark.cn/s/oversized?password=" + ("X" * 65),
            "https://pan.quark.cn/s/oversized-fragment#pwd=" + ("Y" * 65),
        )
        for url in urls:
            with self.subTest(url=url):
                protected = self.spider._resource_url_with_password(url, "GOOD")
                self.assertEqual(self.spider._resource_url_password_value(protected), "GOOD")
                self.assertEqual(protected.count("password=GOOD"), 1)

    def test_bare_fragment_password_shares_plain_url_identity(self):
        plain = "https://pan.quark.cn/s/demo"
        identities = {
            self.spider._resource_row_identity(plain),
            self.spider._resource_row_identity(plain + "#A1"),
            self.spider._resource_row_identity(plain + "?password=B2"),
        }

        self.assertEqual(len(identities), 1)

    def test_magnet_and_ed2k_identities_use_content_hashes(self):
        btih = "0123456789ABCDEF0123456789ABCDEF01234567"
        magnets = (
            "magnet:?xt=urn:btih:%s&dn=first&tr=udp://tracker-a" % btih,
            "magnet:?tr=udp://tracker-b&dn=second&xt=urn:btih:%s" % btih.lower(),
        )
        ed2k_hash = "0123456789ABCDEF0123456789ABCDEF"
        ed2ks = (
            "ed2k://|file|first.mkv|123|%s|/" % ed2k_hash,
            "ED2K://|file|second.mp4|999|%s|/" % ed2k_hash.lower(),
        )

        self.assertEqual(len({self.spider._resource_row_identity(value) for value in magnets}), 1)
        self.assertEqual(len({self.spider._resource_row_identity(value) for value in ed2ks}), 1)

    def test_base32_and_hex_btih_representations_share_one_identity(self):
        hex_btih = "0123456789ABCDEF0123456789ABCDEF01234567"
        base32_btih = MODULE.base64.b32encode(bytes.fromhex(hex_btih)).decode("ascii")
        identities = {
            self.spider._resource_row_identity("magnet:?xt=urn:btih:" + hex_btih),
            self.spider._resource_row_identity("magnet:?xt=urn:btih:" + base32_btih),
        }

        self.assertEqual(len(identities), 1)

    def test_long_pansou_magnet_survives_search_and_detail(self):
        magnet = "magnet:?xt=urn:btih:" + ("A" * 40) + "".join(
            "&tr=udp://tracker%d.example:80/announce" % index for index in range(40)
        )
        self.assertGreater(len(magnet), self.spider.RESOURCE_ID_MAX_LENGTH)
        payload = {"data": {"merged_by_type": {"magnet": [{
            "url": magnet,
            "work_title": "测试剧集",
            "datetime": "2026-08-11T10:00:00Z",
        }]}}}
        self.spider._resource_capability = Mock(return_value="present")
        self.spider._resource_api_get = Mock(return_value=payload)

        rows = self.spider._resource_search_mode("pansou", ["测试剧集"])

        self.assertEqual(len(rows), 1)
        self.assertEqual(MODULE.unquote(rows[0]["vod_id"]), magnet)
        self.spider._resource_api_get = Mock(return_value={"list": []})
        self.spider._resource_detail(rows[0])
        self.assertEqual(self.spider._resource_api_get.call_args.args[0], "pansou")
        self.assertEqual(self.spider._resource_api_get.call_args.args[1]["id"], magnet)

    def test_check_links_prefers_password_bearing_duplicate(self):
        class CheckResponse(object):
            status_code = 200
            headers = {}

            def __init__(self, payload):
                self.payload = json.dumps(payload).encode("utf-8")
                self.closed = False

            def iter_content(self, chunk_size=None):
                return iter((self.payload,))

            def close(self):
                self.closed = True

        plain = "https://pan.quark.cn/s/demo"
        protected = plain + "?password=A1"
        rows = [
            {"vod_id": MODULE.quote(plain, safe=""), "_resource_mode": "pansou"},
            {"vod_id": MODULE.quote(protected, safe=""), "_resource_mode": "pansou"},
        ]
        response = CheckResponse({"results": [{"url": protected, "state": "ok"}]})
        self.spider._ensure_atvp_connection = Mock(return_value=True)
        self.spider._atvp_session = Mock()
        self.spider._atvp_session.post.return_value = response

        checked = self.spider._checked_resource_rows(rows)

        self.assertEqual(checked, [rows[1]])
        self.assertEqual(
            self.spider._atvp_session.post.call_args.kwargs["json"]["items"],
            [{"url": protected}],
        )

    def test_pansou_metadata_fields_are_bounded_before_storage(self):
        title = "测试剧集" + ("标题" * 3000)
        note = "测试剧集" + ("说明" * 5000)
        source = "来源" * 1000
        oversized_url = "https://pan.quark.cn/s/" + ("x" * 20000)
        payload = {"data": {"merged_by_type": {"quark": [
            {
                "url": "https://pan.quark.cn/s/title",
                "work_title": title,
                "source": source,
            },
            {
                "url": "https://pan.quark.cn/s/note",
                "note": note,
                "source": source,
            },
            {
                "url": oversized_url,
                "work_title": "测试剧集",
                "source": source,
            },
        ]}}}

        rows = self.spider._resource_payload_rows(payload, "pansou")

        self.assertEqual(len(rows), 2)
        self.assertTrue(all(
            len(row.get("vod_name") or "") <= self.spider.RESOURCE_METADATA_TITLE_MAX_LENGTH
            for row in rows
        ))
        self.assertTrue(all(
            len(row.get("work_title") or "") <= self.spider.RESOURCE_METADATA_TITLE_MAX_LENGTH
            for row in rows
        ))
        self.assertTrue(all(
            len(row.get("note") or "") <= self.spider.RESOURCE_METADATA_NOTE_MAX_LENGTH
            for row in rows
        ))
        self.assertTrue(all(
            len(row.get("source") or "") <= self.spider.RESOURCE_METADATA_SOURCE_MAX_LENGTH
            for row in rows
        ))
        self.assertFalse(any("x" * 1000 in MODULE.unquote(row["vod_id"]) for row in rows))

    def test_vod_and_vod1_metadata_fields_are_bounded_before_storage(self):
        payload = {"list": [{
            "vod_id": "resource-1",
            "vod_name": "标题" * 4000,
            "title": "标题" * 4000,
            "note": "说明" * 6000,
            "source": "来源" * 1000,
            "vod_remarks": "备注" * 6000,
        }]}

        for mode in ("vod", "vod1"):
            with self.subTest(mode=mode):
                rows = self.spider._resource_payload_rows(payload, mode)
                self.assertEqual(len(rows), 1)
                self.assertLessEqual(len(rows[0]["vod_name"]), self.spider.RESOURCE_METADATA_TITLE_MAX_LENGTH)
                self.assertLessEqual(len(rows[0]["title"]), self.spider.RESOURCE_METADATA_TITLE_MAX_LENGTH)
                self.assertLessEqual(len(rows[0]["note"]), self.spider.RESOURCE_METADATA_NOTE_MAX_LENGTH)
                self.assertLessEqual(len(rows[0]["source"]), self.spider.RESOURCE_METADATA_SOURCE_MAX_LENGTH)
                self.assertLessEqual(len(rows[0]["vod_remarks"]), self.spider.RESOURCE_METADATA_NOTE_MAX_LENGTH)

    def test_generic_api_rows_discard_unknown_nested_and_oversized_fields(self):
        payload = {"list": [{
            "vod_id": "resource-1",
            "vod_name": "测试剧集",
            "blob": "X" * (1024 * 1024),
            "nested": {"blob": "Y" * (512 * 1024)},
            "_upstream_control": "secret",
            "links": [
                {
                    "work_title": "测试剧集 %d" % index,
                    "title": "标题 %d" % index,
                    "note": "说明 %d" % index,
                    "url": "https://pan.quark.cn/s/%d" % index,
                    "password": "PASS",
                    "nested": {"blob": "Z" * 1000},
                }
                for index in range(100)
            ],
        }]}

        rows = self.spider._resource_payload_rows(payload, "vod")

        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertNotIn("blob", row)
        self.assertNotIn("nested", row)
        self.assertNotIn("_upstream_control", row)
        self.assertLessEqual(len(row.get("links") or []), self.spider.RESOURCE_PAYLOAD_SCAN_MIN)
        self.assertTrue(all(
            set(link).issubset({"work_title", "title", "note"})
            for link in row.get("links") or []
        ))

    def test_pansou_limit_bounds_link_scanning(self):
        payload = {"data": {"merged_by_type": {"quark": [
            {
                "url": "https://pan.quark.cn/s/%d" % index,
                "work_title": "测试剧集",
            }
            for index in range(5000)
        ]}}}
        with patch.object(
                Spider, "_resource_provider_key", wraps=Spider._resource_provider_key,
        ) as provider_key:
            rows = self.spider._resource_payload_rows(payload, "pansou", limit=1)

        self.assertEqual(len(rows), 1)
        self.assertLessEqual(provider_key.call_count, self.spider.RESOURCE_PAYLOAD_SCAN_MIN)

    def test_uncached_supplement_apis_join_the_foreground_candidate_pool(self):
        item = {
            "title": "遭到流放的转生重骑士凭借游戏知识大开无双",
            "year": "2026", "season_count": 1, "trackingSeason": 1,
        }
        self.spider.resource_search_modes = ["vod1", "vod", "pansou", "telegram"]
        self.spider._cache_get = Mock(return_value=None)
        self.spider._schedule_supplement_resource_search = Mock(return_value=True)
        rows = {
            "vod1": [],
            "vod": [],
            "pansou": [{
                "id": "pansou-1", "name": item["title"] + " 2026 1080P", "_resource_mode": "pansou",
            }],
            "telegram": [{
                "id": "telegram-1", "vod_name": item["title"] + " S01E01-E06 HiveWeb",
                "_resource_mode": "telegram",
            }],
        }
        self.spider._resource_search_mode = Mock(
            side_effect=lambda mode, _queries, _deadline=None: rows[mode]
        )

        candidates = self.spider._resource_candidates(item, deadline=time.monotonic() + 2)

        self.assertEqual(
            {row["_resource_mode"] for row in candidates},
            {"pansou", "telegram"},
        )
        self.spider._schedule_supplement_resource_search.assert_not_called()

    def test_ready_entry_cache_revalidates_current_route_without_search(self):
        self.spider._alist_tvbox_plugin = True
        self.spider.atvp_api = "https://atvp.example"
        self.spider.atvp_token = "token"
        self.spider.route_preheat = False
        item = {
            "tmdb_id": 101, "source_id": "tmdb:tv:101", "media_type": "tv",
            "title": "测试剧集", "alist_vod_id": "ready-resource",
            "alist_resource_mode": "vod",
        }
        self.spider._follow_memory = {"version": 2, "items": {"101": dict(item)}}
        row = {
            "vod_id": "ready-resource", "vod_name": "测试剧集",
            "_resource_mode": "vod", "_validated_groups": 1,
        }
        detail = {"list": [{
            "vod_name": "测试剧集", "vod_play_from": "已预热线路",
            "vod_play_url": "S01E01$1@ready-episode",
        }]}
        self.assertTrue(self.spider._store_validated_resource_detail(row, detail))
        self.assertTrue(self.spider._cache_ready_resource_rows(item, [row]))
        self.spider._atvp_history_snapshot = Mock(return_value=[])
        self.spider._resource_candidates = Mock(side_effect=AssertionError("不应首次搜索"))
        self.spider._validated_playable_detail = Mock(return_value=detail)

        result = self.spider._alist_detail_from_metadata(
            "tmdb:tv:101",
            {"list": [{"vod_id": "tmdb:tv:101", "vod_name": "测试剧集"}]},
        )

        self.assertIn("已预热线路", result["list"][0]["vod_play_from"])
        self.assertIn("S01E01", result["list"][0]["vod_play_url"])
        self.spider._resource_candidates.assert_not_called()
        self.spider._validated_playable_detail.assert_called_once()
        self.assertTrue(
            self.spider._validated_playable_detail.call_args.kwargs["force_refresh"]
        )

    def test_entry_preheat_key_changes_when_target_episode_advances(self):
        self.spider.atvp_api = "https://atvp.example"
        self.spider.atvp_token = "token"
        item = {"tmdb_id": 101, "title": "测试剧集", "latest_episode": "S01E04"}

        first = self.spider._entry_resource_preheat_key(item)
        second = self.spider._entry_resource_preheat_key(dict(item, latest_episode="S01E05"))

        self.assertNotEqual(first, second)

    def test_ready_cache_requires_at_least_one_line_covering_target_episode(self):
        self.spider.atvp_api = "https://atvp.example"
        self.spider.atvp_token = "token"
        item = {
            "tmdb_id": 101, "media_type": "tv", "title": "测试剧集",
            "trackingSeason": 1, "latest_episode": "S01E05",
        }
        stale = {"vod_id": "stale", "_resource_mode": "vod", "_validated_groups": 1}
        fresh = {"vod_id": "fresh", "_resource_mode": "pansou", "_validated_groups": 1}
        self.assertTrue(self.spider._store_validated_resource_detail(stale, {"list": [{
            "vod_play_from": "旧线路",
            "vod_play_url": "#".join("S01E%02d$1@old-%d" % (index, index) for index in range(1, 5)),
        }]}))

        self.assertFalse(self.spider._cache_ready_resource_rows(item, [stale]))

        self.assertTrue(self.spider._store_validated_resource_detail(fresh, {"list": [{
            "vod_play_from": "新线路",
            "vod_play_url": "#".join("S01E%02d$1@new-%d" % (index, index) for index in range(1, 6)),
        }]}))
        self.assertTrue(self.spider._cache_ready_resource_rows(item, [stale, fresh]))
        self.assertEqual(
            [row["vod_id"] for row in self.spider._ready_resource_rows(item)],
            ["stale", "fresh"],
        )

    def test_single_target_episode_is_not_a_complete_ready_line(self):
        self.spider.atvp_api = "https://atvp.example"
        self.spider.atvp_token = "token"
        item = {
            "tmdb_id": 101, "media_type": "tv", "title": "测试剧集",
            "trackingSeason": 1, "latest_episode": "S01E05",
        }
        row = {"vod_id": "single-e5", "_resource_mode": "vod", "_validated_groups": 1}
        self.assertTrue(self.spider._store_validated_resource_detail(row, {"list": [{
            "vod_play_from": "单集线路", "vod_play_url": "S01E05$1@e5",
        }]}))

        self.assertFalse(self.spider._cache_ready_resource_rows(item, [row]))

    def test_separate_incomplete_groups_do_not_form_one_complete_ready_line(self):
        self.spider.atvp_api = "https://atvp.example"
        self.spider.atvp_token = "token"
        item = {
            "tmdb_id": 101, "media_type": "tv", "title": "测试剧集",
            "trackingSeason": 1, "latest_episode": "S01E05",
        }
        row = {"vod_id": "split-groups", "_resource_mode": "vod", "_validated_groups": 2}
        self.assertTrue(self.spider._store_validated_resource_detail(row, {"list": [{
            "vod_play_from": "上半段$$$下半段",
            "vod_play_url": (
                "S01E01$1@e1#S01E02$1@e2$$$"
                "S01E03$1@e3#S01E04$1@e4#S01E05$1@e5"
            ),
        }]}))

        self.assertFalse(self.spider._cache_ready_resource_rows(item, [row]))

    def test_ready_cache_retains_target_line_beyond_display_limit(self):
        self.spider.atvp_api = "https://atvp.example"
        self.spider.atvp_token = "token"
        item = {
            "tmdb_id": 101, "media_type": "tv", "title": "测试剧集",
            "trackingSeason": 1, "latest_episode": "S01E05",
        }
        rows = []
        for index in range(self.spider.RESOURCE_HOT_ROUTE_LIMIT + 1):
            row = {"vod_id": "route-%d" % index, "_resource_mode": "vod", "_validated_groups": 1}
            complete = index == self.spider.RESOURCE_HOT_ROUTE_LIMIT
            detail = {"list": [{
                "vod_play_from": "线路%d" % index,
                "vod_play_url": (
                    "#".join(
                        "S01E%02d$1@route-%d-%d" % (episode, index, episode)
                        for episode in range(1, 6)
                    ) if complete else "S01E04$1@route-%d-play" % index
                ),
            }]}
            self.assertTrue(self.spider._store_validated_resource_detail(row, detail))
            rows.append(row)

        self.assertTrue(self.spider._cache_ready_resource_rows(item, rows))

        ready_ids = [row["vod_id"] for row in self.spider._ready_resource_rows(item)]
        self.assertEqual(len(ready_ids), self.spider.RESOURCE_HOT_ROUTE_LIMIT)
        self.assertIn("route-%d" % self.spider.RESOURCE_HOT_ROUTE_LIMIT, ready_ids)

    def test_ready_detail_does_not_replace_e05_snapshot_with_refreshed_e04(self):
        self.spider.atvp_api = "https://atvp.example"
        self.spider.atvp_token = "token"
        item = {
            "tmdb_id": 101, "source_id": "tmdb:tv:101", "media_type": "tv",
            "title": "测试剧集", "trackingSeason": 1, "latest_episode": "S01E05",
            "last_play_route": {
                "resourceId": "ready", "resourceMode": "vod", "playId": "1@e5",
                "season": 1, "episode": 5,
            },
        }
        row = {"vod_id": "ready", "_resource_mode": "vod", "_validated_groups": 1}
        cached = {"list": [{
            "vod_play_from": "缓存线路",
            "vod_play_url": "#".join(
                "S01E%02d$1@e%d" % (index, index) for index in range(1, 6)
            ),
        }]}
        stale_refresh = {"list": [{
            "vod_play_from": "旧刷新线路", "vod_play_url": "S01E04$1@e4",
        }]}
        self.assertTrue(self.spider._store_validated_resource_detail(row, cached))
        self.assertTrue(self.spider._cache_ready_resource_rows(item, [row]))
        self.spider._validated_playable_detail = Mock(return_value=stale_refresh)
        self.spider._store_validated_resource_detail = Mock(return_value=True)

        detail = self.spider._ready_resource_detail(
            "tmdb:tv:101", item, {"vod_id": "tmdb:tv:101", "vod_name": "测试剧集"},
        )

        self.assertIn("S01E05", detail["vod_play_url"])
        self.spider._store_validated_resource_detail.assert_not_called()

    def test_ready_detail_without_remembered_route_keeps_complete_snapshot(self):
        self.spider.atvp_api = "https://atvp.example"
        self.spider.atvp_token = "token"
        item = {
            "tmdb_id": 101, "source_id": "tmdb:tv:101", "media_type": "tv",
            "title": "测试剧集", "trackingSeason": 1, "latest_episode": "S01E05",
        }
        row = {"vod_id": "ready", "_resource_mode": "vod", "_validated_groups": 1}
        cached = {"list": [{
            "vod_play_from": "完整缓存",
            "vod_play_url": "#".join("S01E%02d$1@e%d" % (index, index) for index in range(1, 6)),
        }]}
        stale_refresh = {"list": [{
            "vod_play_from": "残缺刷新", "vod_play_url": "S01E04$1@e4",
        }]}
        self.assertTrue(self.spider._store_validated_resource_detail(row, cached))
        self.assertTrue(self.spider._cache_ready_resource_rows(item, [row]))
        self.spider._validated_playable_detail = Mock(return_value=stale_refresh)
        self.spider._store_validated_resource_detail = Mock(return_value=True)

        detail = self.spider._ready_resource_detail(
            "tmdb:tv:101", item, {"vod_id": "tmdb:tv:101", "vod_name": "测试剧集"},
        )

        self.assertIn("S01E05", detail["vod_play_url"])
        self.spider._store_validated_resource_detail.assert_not_called()

    def test_detail_flag_switch_discards_short_lived_probe_before_play(self):
        self.spider.atvp_api = "https://atvp.example"
        self.spider.atvp_token = "token"
        item = {"media_type": "tv", "tmdb_id": 101, "title": "测试剧集"}
        play_id = self.spider._build_followplay(
            "1@episode-1", item, "resource-101", 1, 1, "S01E01",
        )
        key = self.spider._route_probe_key("1@episode-1", "resource-101", "vod")
        self.spider._route_probe_cache[key] = {
            "checked_at": time.time(), "reachable": True,
            "output": {"url": "https://cdn.example/old.mp4", "header": {}},
        }
        output = {"parse": 0, "url": "https://cdn.example/new.mp4", "header": {}}
        self.spider._atvp_play = Mock(return_value=output)
        self.spider._probe_media_output = Mock(return_value={
            "checked_at": time.time(), "reachable": True, "output": output,
        })
        self.spider._register_playback_sync_window = Mock(return_value=True)
        invalidate = self.spider._invalidate_route_probe
        self.spider._invalidate_route_probe = Mock(side_effect=invalidate)

        self.spider.playerContent("线路A", play_id, [])
        first_calls = self.spider._atvp_play.call_count
        self.spider.playerContent("线路B", play_id, [])

        self.assertGreaterEqual(self.spider._atvp_play.call_count, first_calls + 1)
        self.spider._invalidate_route_probe.assert_called_once_with(
            "1@episode-1", "resource-101", "vod",
        )

    def test_flag_switch_is_scoped_to_same_route_context(self):
        self.spider.atvp_api = "https://atvp.example"
        self.spider.atvp_token = "token"
        item = {"media_type": "tv", "tmdb_id": 101, "title": "测试剧集"}
        first_id = self.spider._build_followplay(
            "1@episode-1", item, "resource-101", 1, 1, "S01E01",
        )
        second_id = self.spider._build_followplay(
            "1@episode-2", item, "resource-101", 1, 2, "S01E02",
        )
        self.spider._atvp_play = Mock(side_effect=[
            {"parse": 0, "url": "https://cdn.example/1.mp4", "header": {}},
            {"parse": 0, "url": "https://cdn.example/2.mp4", "header": {}},
        ])
        self.spider._probe_media_output = Mock(side_effect=lambda output, deadline=None: {
            "checked_at": time.time(), "reachable": True, "output": output,
        })
        self.spider._register_playback_sync_window = Mock(return_value=True)
        self.spider._invalidate_route_probe = Mock()

        self.spider.playerContent("线路A", first_id, [])
        self.spider.playerContent("线路B", second_id, [])

        self.assertFalse(self.spider._invalidate_route_probe.called)

    def test_real_flag_switch_with_different_play_id_forces_refresh(self):
        self.spider.atvp_api = "https://atvp.example"
        self.spider.atvp_token = "token"
        item = {"media_type": "tv", "tmdb_id": 101, "title": "测试剧集"}
        first_id = self.spider._build_followplay(
            "1@line-a", item, "resource-a", 1, 1, "S01E01",
        )
        second_id = self.spider._build_followplay(
            "1@line-b", item, "resource-b", 1, 1, "S01E01",
        )
        first = {"parse": 0, "url": "https://cdn.example/a.mp4", "header": {}}
        second = {"parse": 0, "url": "https://cdn.example/b.mp4", "header": {}}
        self.spider._atvp_play = Mock(side_effect=[first, second, second])
        self.spider._probe_media_output = Mock(side_effect=lambda output, deadline=None: {
            "checked_at": time.time(), "reachable": True, "output": output,
        })
        self.spider._register_playback_sync_window = Mock(return_value=True)
        invalidate = self.spider._invalidate_route_probe
        self.spider._invalidate_route_probe = Mock(side_effect=invalidate)

        self.spider.playerContent("线路A", first_id, [])
        self.spider.playerContent("线路B", second_id, [])

        self.spider._invalidate_route_probe.assert_called_once_with(
            "1@line-b", "resource-b", "vod",
        )

    def test_failed_probe_reissues_signed_output_once(self):
        self.spider.atvp_api = "https://atvp.example"
        self.spider.atvp_token = "token"
        item = {"media_type": "tv", "tmdb_id": 101, "title": "测试剧集"}
        play_id = self.spider._build_followplay(
            "1@episode-1", item, "resource-101", 1, 1, "S01E01",
        )
        expired = {"parse": 0, "url": "https://cdn.example/expired.mp4", "header": {}}
        refreshed = {"parse": 0, "url": "https://cdn.example/refreshed.mp4", "header": {}}
        self.spider._atvp_play = Mock(side_effect=[expired, refreshed])
        self.spider._probe_media_output = Mock(side_effect=[None, {
            "checked_at": time.time(), "reachable": True, "output": refreshed,
        }])
        self.spider._register_playback_sync_window = Mock(return_value=True)

        result = self.spider.playerContent("线路A", play_id, [])

        self.assertEqual(result["url"], refreshed["url"])
        self.assertEqual(self.spider._atvp_play.call_count, 2)
        self.assertEqual(self.spider._probe_media_output.call_count, 2)

    def test_first_detail_uses_nonblocking_history_snapshot_for_resume(self):
        self.spider._alist_tvbox_plugin = True
        self.spider.atvp_api = "https://atvp.example"
        self.spider.atvp_token = "token"
        item = {
            "tmdb_id": 101, "source_id": "tmdb:tv:101", "media_type": "tv",
            "title": "测试剧集",
        }
        self.spider._follow_memory = {"version": 2, "items": {"101": dict(item)}}
        history = {"key": "site@@@vod@@@1", "vodName": "测试剧集", "position": 88000}
        self.spider._atvp_history_snapshot = Mock(return_value=[history])
        self.spider._atvp_history_for_item = Mock(return_value=history)
        self.spider._history_resume_fields = Mock(return_value={"resume_position": 88000})
        ready = {"vod_name": "测试剧集", "vod_play_from": "线路", "vod_play_url": "E1$play"}
        self.spider._ready_resource_detail = Mock(return_value=ready)

        self.spider._alist_detail_from_metadata(
            "tmdb:tv:101", {"list": [{"vod_id": "tmdb:tv:101", "vod_name": "测试剧集"}]},
        )

        self.spider._atvp_history_snapshot.assert_called_once_with(nonblocking=True)
        called_item = self.spider._ready_resource_detail.call_args.args[1]
        self.assertEqual(called_item["resume_position"], 88000)

    def test_first_detail_shares_one_foreground_deadline_with_ready_route(self):
        self.spider._alist_tvbox_plugin = True
        self.spider.atvp_api = "https://atvp.example"
        self.spider.atvp_token = "token"
        self.spider._atvp_history_snapshot = Mock(return_value=[])
        self.spider._ready_resource_detail = Mock(return_value={
            "vod_name": "测试剧集", "vod_play_from": "线路", "vod_play_url": "E1$play",
        })

        with patch.object(MODULE.time, "monotonic", return_value=100.0):
            self.spider._alist_detail_from_metadata(
                "tmdb:tv:101",
                {"list": [{"vod_id": "tmdb:tv:101", "vod_name": "测试剧集"}]},
            )

        deadline = self.spider._ready_resource_detail.call_args.kwargs["deadline"]
        self.assertEqual(deadline, 100.0 + self.spider.RESOURCE_FOREGROUND_BUDGET)

    def test_pending_entry_preheat_without_ready_route_falls_back_to_foreground_search(self):
        self.spider._alist_tvbox_plugin = True
        self.spider.atvp_api = "https://atvp.example"
        self.spider.atvp_token = "token"
        item = {
            "tmdb_id": 101, "source_id": "tmdb:tv:101", "media_type": "tv",
            "title": "测试剧集",
        }
        self.spider._follow_memory = {"version": 2, "items": {"101": dict(item)}}
        self.spider._resource_entry_preheat_jobs[
            self.spider._entry_resource_preheat_key(item)
        ] = object()
        candidate = {"vod_id": "foreground-resource", "_resource_mode": "vod"}
        detail = {"list": [{
            "vod_name": "测试剧集", "vod_play_from": "前台线路",
            "vod_play_url": "S01E01$1@foreground-episode",
        }]}
        self.spider._atvp_history_snapshot = Mock(return_value=[])
        self.spider._resource_candidates = Mock(return_value=[candidate])
        self.spider._resource_detail = Mock(return_value=detail)

        result = self.spider._alist_detail_from_metadata(
            "tmdb:tv:101", {"list": [{"vod_id": "tmdb:tv:101", "vod_name": "测试剧集"}]},
        )

        self.assertIn("前台线路", result["list"][0]["vod_play_from"])
        self.spider._resource_candidates.assert_called_once()

    def test_foreground_candidate_detail_uses_short_slice_and_tries_next_mode(self):
        self.spider._alist_tvbox_plugin = True
        self.spider.atvp_api = "https://atvp.example"
        self.spider.atvp_token = "token"
        self.spider.route_preheat = False
        self.spider._atvp_history_snapshot = Mock(return_value=[])
        self.spider._resource_candidates = Mock(return_value=[
            {"vod_id": "slow-vod", "_resource_mode": "vod"},
            {"vod_id": "fast-pansou", "_resource_mode": "pansou"},
        ])
        fast_detail = {"list": [{
            "vod_name": "测试剧集", "vod_play_from": "盘搜线路",
            "vod_play_url": "S01E01$1@fast",
        }]}
        deadlines = []

        def detail(row, deadline=None):
            deadlines.append(deadline)
            if row["vod_id"] == "slow-vod":
                raise RuntimeError("slow endpoint")
            return fast_detail

        self.spider._resource_detail = Mock(side_effect=detail)
        with patch.object(MODULE.time, "monotonic", return_value=100.0):
            result = self.spider._alist_detail_from_metadata(
                "tmdb:tv:101",
                {"list": [{"vod_id": "tmdb:tv:101", "vod_name": "测试剧集"}]},
            )

        self.assertIn("盘搜线路", result["list"][0]["vod_play_from"])
        self.assertEqual(len(deadlines), 2)
        self.assertEqual(deadlines, [
            100.0 + self.spider.RESOURCE_FOREGROUND_DETAIL_SLICE,
            100.0 + self.spider.RESOURCE_FOREGROUND_DETAIL_SLICE,
        ])

    def test_empty_foreground_result_schedules_current_entry_preheat(self):
        self.spider._alist_tvbox_plugin = True
        self.spider.atvp_api = "https://atvp.example"
        self.spider.atvp_token = "token"
        self.spider._atvp_history_snapshot = Mock(return_value=[])
        self.spider._resource_candidates = Mock(return_value=[])
        self.spider._schedule_entry_resource_preheat = Mock(return_value=True)
        self.spider._supplement_resource_state = Mock(return_value=(0, False))

        result = self.spider._alist_detail_from_metadata(
            "tmdb:tv:101",
            {"list": [{"vod_id": "tmdb:tv:101", "vod_name": "测试剧集"}]},
        )

        self.assertIn("后台线路验证中", result["list"][0]["vod_director"])
        scheduled = self.spider._schedule_entry_resource_preheat.call_args.args[0]
        self.assertEqual(scheduled[0]["tmdb_id"], 101)

    def test_existing_entry_preheat_is_reported_as_accepted(self):
        self.spider._alist_tvbox_plugin = True
        self.spider.route_preheat = True
        self.spider.atvp_api = "https://atvp.example"
        self.spider.atvp_token = "token"
        self.spider._atvp_session = Mock()
        item = {
            "tmdb_id": 101, "source_id": "tmdb:tv:101", "media_type": "tv",
            "title": "测试剧集", "latest_episode": "S01E14",
        }
        key = self.spider._entry_resource_preheat_key(item)
        self.spider._resource_entry_preheat_jobs[key] = object()

        self.assertTrue(self.spider._schedule_entry_resource_preheat([item]))

    def test_finished_entry_preheat_is_restarted_after_foreground_timeout(self):
        self.spider._alist_tvbox_plugin = True
        self.spider.atvp_api = "https://atvp.example"
        self.spider.atvp_token = "token"
        self.spider._atvp_history_snapshot = Mock(return_value=[])
        self.spider._ready_resource_detail = Mock(return_value=None)
        self.spider._bound_resource_row = Mock(return_value=None)
        self.spider._resource_candidates = Mock(return_value=[])
        self.spider._supplement_resource_state = Mock(return_value=(0, False))
        self.spider._entry_resource_preheat_pending = Mock(side_effect=[True, False, True])
        self.spider._schedule_entry_resource_preheat = Mock(return_value=True)

        result = self.spider._alist_detail_from_metadata(
            "tmdb:tv:101",
            {"list": [{"vod_id": "tmdb:tv:101", "vod_name": "测试剧集"}]},
        )

        self.assertIn("后台线路验证中", result["list"][0]["vod_director"])
        self.spider._schedule_entry_resource_preheat.assert_called_once()

    def test_follow_history_snapshot_prefers_newer_native_episode(self):
        cloud = {
            "key": "douban_tmdb_follow_single@@@tmdb:tv:101@@@1",
            "vodName": "测试剧集", "vodRemarks": "S01E03",
            "episodeUrl": "S01E03$play-cloud", "position": 80000,
        }
        local = {
            "key": "douban_tmdb_follow_single@@@tmdb:tv:101@@@1",
            "vodName": "测试剧集", "vodRemarks": "S01E14",
            "episodeUrl": "S01E14$play-local", "position": 1000,
        }
        self.spider._atvp_history_snapshot = Mock(return_value=[cloud])
        self.spider._native_history_export_java = Mock(return_value={
            "config": "{}", "rows": [local],
        })

        result = self.spider._follow_history_snapshot()

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["vodRemarks"], "S01E14")

    def test_pending_entry_preheat_uses_complete_bound_route_without_global_search(self):
        self.spider._alist_tvbox_plugin = True
        self.spider.atvp_api = "https://atvp.example"
        self.spider.atvp_token = "token"
        self.spider.route_preheat = False
        item = {
            "tmdb_id": 101, "source_id": "tmdb:tv:101", "media_type": "tv",
            "title": "测试剧集", "alist_vod_id": "bound-resource",
            "alist_resource_mode": "vod", "latest_episode": "S01E01",
        }
        self.spider._follow_memory = {"version": 2, "items": {"101": dict(item)}}
        preheat_key = self.spider._entry_resource_preheat_key(item)
        self.spider._resource_entry_preheat_jobs[preheat_key] = object()
        bound_detail = {"list": [{
            "vod_name": "测试剧集", "vod_play_from": "绑定兜底",
            "vod_play_url": "S01E01$1@bound-episode",
        }]}
        self.spider._atvp_history_snapshot = Mock(return_value=[])
        self.spider._resource_detail = Mock(return_value=bound_detail)
        self.spider._validated_playable_detail = Mock(return_value=bound_detail)
        self.spider._resource_candidates = Mock(side_effect=AssertionError("预热中不应全局搜索"))

        result = self.spider._alist_detail_from_metadata(
            "tmdb:tv:101",
            {"list": [{"vod_id": "tmdb:tv:101", "vod_name": "测试剧集"}]},
        )

        self.assertIn("绑定兜底", result["list"][0]["vod_play_from"])
        self.spider._resource_candidates.assert_not_called()
        self.spider._validated_playable_detail.assert_called_once()

    def test_pending_entry_preheat_searches_when_bound_route_is_incomplete(self):
        self.spider._alist_tvbox_plugin = True
        self.spider.atvp_api = "https://atvp.example"
        self.spider.atvp_token = "token"
        self.spider.route_preheat = False
        item = {
            "tmdb_id": 101, "source_id": "tmdb:tv:101", "media_type": "tv",
            "title": "测试剧集", "alist_vod_id": "bound-resource",
            "alist_resource_mode": "vod", "latest_episode": "S01E06",
        }
        self.spider._follow_memory = {"version": 2, "items": {"101": dict(item)}}
        preheat_key = self.spider._entry_resource_preheat_key(item)
        self.spider._resource_entry_preheat_jobs[preheat_key] = object()
        bound_detail = {"list": [{
            "vod_name": "测试剧集", "vod_play_from": "绑定单集",
            "vod_play_url": "S01E06$1@bound-episode",
        }]}
        candidate = {"vod_id": "complete-resource", "_resource_mode": "pansou"}
        complete_detail = {"list": [{
            "vod_name": "测试剧集", "vod_play_from": "完整线路",
            "vod_play_url": "#".join(
                "S01E%02d$1@complete-%d" % (episode, episode)
                for episode in range(1, 7)
            ),
        }]}
        self.spider._atvp_history_snapshot = Mock(return_value=[])
        self.spider._validated_playable_detail = Mock(return_value=bound_detail)
        self.spider._resource_candidates = Mock(return_value=[candidate])
        self.spider._resource_detail = Mock(side_effect=[bound_detail, complete_detail])

        result = self.spider._alist_detail_from_metadata(
            "tmdb:tv:101",
            {"list": [{"vod_id": "tmdb:tv:101", "vod_name": "测试剧集"}]},
        )

        vod = result["list"][0]
        self.assertIn("完整线路", vod["vod_play_from"])
        self.assertIn("S01E01", vod["vod_play_url"])
        self.assertIn("S01E06", vod["vod_play_url"])
        self.spider._resource_candidates.assert_called_once()

    def test_entry_preheat_publishes_playable_cache_binds_fallback_and_refreshes_detail(self):
        self.spider._alist_tvbox_plugin = True
        self.spider.atvp_api = "https://atvp.example"
        self.spider.atvp_token = "token"
        self.spider._atvp_session = Mock()
        item = {
            "tmdb_id": 101, "title": "测试剧集", "latest_episode": "S01E06",
        }
        self.spider._follow_memory = {"version": 2, "items": {"101": dict(item)}}
        first_row = {
            "vod_id": "ready-resource", "vod_name": "测试剧集",
            "_resource_mode": "pansou", "_validated_groups": 1,
        }
        second_row = {
            "vod_id": "ready-resource-2", "vod_name": "测试剧集备选",
            "_resource_mode": "telegram", "_validated_groups": 1,
        }
        first_detail = {"list": [{
            "vod_name": "测试剧集", "vod_play_from": "盘搜已验证",
            "vod_play_url": "#".join(
                "S01E%02d$1@ready-%d" % (index, index) for index in range(1, 7)
            ),
        }]}
        second_detail = {"list": [{
            "vod_name": "测试剧集备选", "vod_play_from": "电报已验证",
            "vod_play_url": "S01E01$1@ready-2",
        }]}
        self.spider._resource_candidates = Mock(return_value=[first_row, second_row])
        self.spider._checked_resource_rows = Mock(side_effect=lambda rows, _deadline=None: rows)

        def playable(rows, _item, _deadline=None, expected_generation=None, on_update=None):
            self.spider._store_validated_resource_detail(
                rows[0], first_detail, expected_generation=expected_generation,
            )
            on_update(rows[:1])
            self.spider._store_validated_resource_detail(
                rows[1], second_detail, expected_generation=expected_generation,
            )
            on_update(rows[:2])
            return rows

        self.spider._playable_resource_rows = Mock(side_effect=playable)
        self.spider._replace_bound_resource = Mock(return_value=True)
        self.spider._schedule_active_detail_refresh = Mock(return_value=True)

        self.assertTrue(self.spider._schedule_entry_resource_preheat([item]))
        deadline = time.time() + 2
        while self.spider._resource_entry_preheat_jobs and time.time() < deadline:
            time.sleep(0.01)

        self.assertFalse(self.spider._resource_entry_preheat_jobs)
        self.assertEqual(self.spider._ready_resource_rows(item)[0]["vod_id"], "ready-resource")
        self.spider._replace_bound_resource.assert_called_once()
        self.assertEqual(self.spider._schedule_active_detail_refresh.call_count, 2)
        refresh_item = self.spider._schedule_active_detail_refresh.call_args_list[0].args[0]
        self.assertEqual(refresh_item["source_id"], "tmdb:tv:101")
        self.spider._resource_candidates.assert_called_once()
        self.assertTrue(self.spider._resource_candidates.call_args.kwargs["background"])

    def test_entry_preheat_keeps_multiple_valid_groups_from_one_resource(self):
        self.spider._alist_tvbox_plugin = True
        self.spider.atvp_api = "https://atvp.example"
        self.spider.atvp_token = "token"
        self.spider._atvp_session = Mock()
        item = {
            "tmdb_id": 101, "source_id": "tmdb:tv:101", "media_type": "tv",
            "title": "测试剧集", "trackingSeason": 1, "latest_episode": "S01E02",
        }
        row = {
            "vod_id": "multi-group-resource", "vod_name": "测试剧集",
            "_resource_mode": "pansou",
        }
        detail = {"list": [{
            "vod_name": "测试剧集",
            "vod_play_from": "来源A$$$来源B",
            "vod_play_url": (
                "S01E01$1@route-a#S01E02$1@route-a2$$$"
                "S01E01$1@route-b#S01E02$1@route-b2"
            ),
        }]}
        self.spider._resource_candidates = Mock(return_value=[row])
        self.spider._checked_resource_rows = Mock(side_effect=lambda rows, _deadline=None: rows)
        self.spider._resource_detail = Mock(return_value=detail)
        self.spider._atvp_play = Mock(side_effect=lambda play_id, **_kwargs: {
            "parse": 0, "url": "https://cdn.example/%s.mp4" % play_id,
            "header": {"Cookie": "fixture-required"},
        })
        self.spider._probe_media_output = Mock(side_effect=lambda output, deadline=None: {
            "checked_at": time.time(), "reachable": True,
            "output": dict(output), "startup_ms": 10,
        })
        self.spider._schedule_active_detail_refresh = Mock(return_value=True)

        self.assertTrue(self.spider._schedule_entry_resource_preheat([item]))
        deadline = time.time() + 2
        while self.spider._resource_entry_preheat_jobs and time.time() < deadline:
            time.sleep(0.01)

        ready = self.spider._ready_resource_detail(
            "tmdb:tv:101", item, {"vod_id": "tmdb:tv:101", "vod_name": "测试剧集"},
        )
        self.assertIsNotNone(ready)
        self.assertIn("来源A", ready["vod_play_from"])
        self.assertIn("来源B", ready["vod_play_from"])
        self.assertEqual(len(ready["vod_play_url"].split("$$$")), 2)

    def test_home_and_follow_category_entries_retry_resource_preheat(self):
        self.spider._schedule_entry_resource_preheat = Mock(return_value=True)
        self.spider._flush_playback_sync_on_navigation = Mock()
        self.spider._load_follow_state = Mock()

        self.spider.homeContent(False)
        self.spider.categoryContent("unknown", "2", False, {})
        self.spider.categoryContent("follow_updates", "3", False, {})

        self.assertEqual(self.spider._schedule_entry_resource_preheat.call_count, 2)
        self.spider._schedule_entry_resource_preheat.assert_any_call()
        self.spider._schedule_entry_resource_preheat.assert_any_call(page=3)

    def test_old_generation_cannot_write_ready_rows_to_new_backend_cache(self):
        self.spider.atvp_api = "https://old-atvp.example"
        self.spider.atvp_token = "old-token"
        item = {"tmdb_id": 101, "title": "测试剧集"}
        row = {
            "vod_id": "old-resource", "vod_name": "测试剧集",
            "_resource_mode": "pansou", "_validated_groups": 1,
        }
        detail = {"list": [{
            "vod_name": "测试剧集", "vod_play_from": "旧后端线路",
            "vod_play_url": "S01E01$1@old-route",
        }]}
        old_generation = self.spider._cache_generation
        old_key = self.spider._entry_resource_preheat_key(item)
        self.assertTrue(self.spider._store_validated_resource_detail(row, detail))

        with self.spider._cache_lock:
            self.spider.atvp_api = "https://new-atvp.example"
            self.spider.atvp_token = "new-token"
            self.spider._cache_generation += 1
        new_key = self.spider._entry_resource_preheat_key(item)

        self.assertFalse(self.spider._cache_ready_resource_rows(
            item, [row], expected_generation=old_generation, cache_key=old_key,
        ))
        self.assertNotIn(old_key, self.spider._cache)
        self.assertNotIn(new_key, self.spider._cache)

    def test_supplement_search_refreshes_after_each_material_route_growth(self):
        item = {"title": "测试剧集", "year": "2026", "trackingSeason": 1}
        rows = [
            {
                "vod_id": "route-a", "vod_name": "测试剧集 2026",
                "_resource_mode": "pansou", "_validated_groups": 1,
            },
            {
                "vod_id": "route-b", "vod_name": "测试剧集 2026",
                "_resource_mode": "telegram", "_validated_groups": 1,
            },
        ]
        self.spider._resource_search_mode = Mock(side_effect=lambda mode, *_args: [
            row for row in rows if row["_resource_mode"] == mode
        ])
        self.spider._checked_resource_rows = Mock(side_effect=lambda values, _deadline=None: values)
        self.spider._resource_fair_candidate_order = Mock(side_effect=lambda values, *_args, **_kwargs: values)

        def playable(values, *_args, **kwargs):
            callback = kwargs["on_update"]
            callback(values[:1])
            callback(values[:2])
            return values

        self.spider._playable_resource_rows = Mock(side_effect=playable)
        self.spider._schedule_active_detail_refresh = Mock(return_value=True)
        cache_key = "supplement-growth-test"

        self.assertTrue(self.spider._schedule_supplement_resource_search(
            ["pansou", "telegram"], ["测试剧集"], item, cache_key,
        ))
        deadline = time.time() + 2
        while cache_key in self.spider._resource_search_jobs and time.time() < deadline:
            time.sleep(0.01)

        self.assertNotIn(cache_key, self.spider._resource_search_jobs)
        self.assertEqual(self.spider._schedule_active_detail_refresh.call_count, 2)

    def test_init_triggers_resource_preheat_after_state_load(self):
        fresh = Spider()
        fresh._schedule_entry_resource_preheat = Mock(return_value=True)
        try:
            fresh.init({})
            fresh._schedule_entry_resource_preheat.assert_called_once_with()
        finally:
            fresh.destroy()

    def test_resource_mode_search_executor_queues_without_exceeding_four_active_searches(self):
        release = MODULE.threading.Event()
        saturated = MODULE.threading.Event()
        guard = MODULE.threading.Lock()
        state = {"active": 0, "maximum": 0, "completed": 0}

        def search(mode, queries, deadline=None):
            with guard:
                state["active"] += 1
                state["maximum"] = max(state["maximum"], state["active"])
                if state["active"] == 4:
                    saturated.set()
            try:
                release.wait(2)
                return []
            finally:
                with guard:
                    state["active"] -= 1
                    state["completed"] += 1

        self.spider._resource_search_mode = Mock(side_effect=search)
        futures = [
            self.spider._submit_resource_mode_search("vod", ["测试剧集"], time.monotonic() + 3)
            for _index in range(8)
        ]
        try:
            self.assertTrue(saturated.wait(1))
            self.assertTrue(all(future is not None for future in futures))
            self.assertEqual(state["maximum"], 4)
        finally:
            release.set()
            for future in futures:
                if future is not None:
                    future.result(timeout=2)
        self.assertEqual(state["completed"], 8)
        self.assertEqual(state["maximum"], 4)

    def test_background_resource_search_saturation_does_not_block_foreground(self):
        release = MODULE.threading.Event()
        background_started = MODULE.threading.Event()
        guard = MODULE.threading.Lock()
        state = {"background_active": 0}

        def search(mode, queries, deadline=None):
            if str(mode).startswith("background-"):
                with guard:
                    state["background_active"] += 1
                    if state["background_active"] == self.spider.RESOURCE_BACKGROUND_MODE_WORKERS:
                        background_started.set()
                try:
                    release.wait(2)
                    return []
                finally:
                    with guard:
                        state["background_active"] -= 1
            return [{"vod_id": "foreground-result", "vod_name": "测试剧集"}]

        self.spider._resource_search_mode = Mock(side_effect=search)
        background_futures = [
            self.spider._submit_resource_mode_search(
                "background-%d" % index, ["测试剧集"], time.monotonic() + 3,
                background=True,
            )
            for index in range(
                self.spider.RESOURCE_BACKGROUND_MODE_WORKERS
                + self.spider.RESOURCE_BACKGROUND_MODE_QUEUE_LIMIT
            )
        ]
        try:
            self.assertTrue(background_started.wait(1))
            foreground = self.spider._submit_resource_mode_search(
                "vod", ["测试剧集"], time.monotonic() + 1,
            )
            self.assertIsNotNone(foreground)
            self.assertEqual(foreground.result(timeout=1)[0]["vod_id"], "foreground-result")
        finally:
            release.set()
            for future in background_futures:
                if future is not None:
                    future.result(timeout=2)

    def test_cancelled_queued_resource_search_releases_admission(self):
        release = MODULE.threading.Event()
        saturated = MODULE.threading.Event()
        guard = MODULE.threading.Lock()
        state = {"active": 0}

        def search(mode, queries, deadline=None):
            with guard:
                state["active"] += 1
                if state["active"] == self.spider.RESOURCE_FOREGROUND_MODE_WORKERS:
                    saturated.set()
            try:
                release.wait(2)
                return [mode]
            finally:
                with guard:
                    state["active"] -= 1

        self.spider._resource_search_mode = Mock(side_effect=search)
        running = [
            self.spider._submit_resource_mode_search(
                "running-%d" % index, ["测试剧集"], time.monotonic() + 3,
            )
            for index in range(self.spider.RESOURCE_FOREGROUND_MODE_WORKERS)
        ]
        self.assertTrue(saturated.wait(1))
        queued = self.spider._submit_resource_mode_search(
            "queued", ["测试剧集"], time.monotonic() + 3,
        )
        self.assertIsNotNone(queued)
        self.assertTrue(queued.cancel())
        release.set()
        for future in running:
            future.result(timeout=2)

        replacement = self.spider._submit_resource_mode_search(
            "replacement", ["测试剧集"], time.monotonic() + 1,
        )
        self.assertIsNotNone(replacement)
        self.assertEqual(replacement.result(timeout=1), ["replacement"])

    def test_validated_resource_detail_cache_is_sanitized_and_lru_bounded(self):
        detail = {"list": [{
            "vod_name": "测试剧集",
            "vod_remarks": "已验证",
            "vod_play_from": "夸克线路",
            "vod_play_url": "S01E01$1@playable",
            "_route_quality": [{"resolution": 20, "total": 99, "blob": "drop"}],
            "blob": "X" * (512 * 1024),
            "nested": {"blob": "Y" * (512 * 1024)},
        }]}
        rows = [
            {"vod_id": "resource-%d" % index, "_resource_mode": "vod"}
            for index in range(self.spider.VALIDATED_RESOURCE_DETAIL_CACHE_LIMIT + 5)
        ]

        for row in rows:
            self.assertTrue(self.spider._store_validated_resource_detail(row, detail))

        self.assertEqual(
            len(self.spider._validated_resource_details),
            self.spider.VALIDATED_RESOURCE_DETAIL_CACHE_LIMIT,
        )
        self.assertIsNone(self.spider._validated_resource_detail(rows[0]))
        cached = self.spider._validated_resource_detail(rows[-1])
        self.assertIsNotNone(cached)
        cached_vod = cached["list"][0]
        self.assertNotIn("blob", cached_vod)
        self.assertNotIn("nested", cached_vod)
        self.assertNotIn("blob", cached_vod["_route_quality"][0])
        self.assertEqual(
            set(cached_vod).difference({
                "vod_name", "vod_remarks", "type_name", "type",
                "vod_play_from", "vod_play_url", "_route_quality",
            }),
            set(),
        )

    def test_real_candidate_order_keeps_one_row_per_api_before_cached_extras(self):
        item = {
            "title": "测试剧集", "year": "2026", "season_count": 1,
            "trackingSeason": 1,
        }
        self.spider.resource_search_modes = ["vod1", "vod", "pansou", "telegram"]
        cached = [
            {
                "vod_id": "%s-%d" % (mode, index),
                "vod_name": "测试剧集 2026 1080P",
                "_resource_mode": mode,
                "_validated_groups": 1,
            }
            for mode, count in (("pansou", 3), ("telegram", 2))
            for index in range(count)
        ]
        self.spider._cache_get = Mock(return_value=cached)
        self.spider._resource_capability = Mock(return_value="present")
        self.spider._resource_search_mode = Mock(side_effect=lambda mode, _queries, _deadline=None: [
            {
                "vod_id": "%s-live" % mode,
                "vod_name": "测试剧集 2026 1080P",
                "_resource_mode": mode,
            }
        ])

        candidates = self.spider._resource_candidates(item, deadline=time.monotonic() + 2)

        self.assertEqual(
            [row["_resource_mode"] for row in candidates[:4]],
            ["vod1", "vod", "pansou", "telegram"],
        )
        self.assertEqual(
            {row["_resource_mode"] for row in candidates[:self.spider.RESOURCE_DETAIL_ATTEMPT_LIMIT]},
            {"vod1", "vod", "pansou", "telegram"},
        )

    def test_candidate_order_interleaves_providers_inside_one_api(self):
        item = {"title": "测试剧集", "year": "2026", "trackingSeason": 1}
        rows = [
            {
                "vod_id": MODULE.quote("https://www.123pan.com/s/recent-%d" % index, safe=""),
                "vod_name": "测试剧集 2026 第6集", "_resource_mode": "pansou",
            }
            for index in range(3)
        ] + [{
            "vod_id": MODULE.quote("https://pan.baidu.com/s/complete", safe=""),
            "vod_name": "测试剧集 2026", "_resource_mode": "pansou",
        }]

        ordered = self.spider._resource_fair_candidate_order(
            rows, item, modes=["pansou"],
        )

        self.assertIn("123pan", MODULE.unquote(ordered[0]["vod_id"]))
        self.assertIn("baidu", MODULE.unquote(ordered[1]["vod_id"]))

    def test_background_validation_continues_until_complete_target_exists(self):
        self.spider.resource_limit = 1
        item = {
            "media_type": "tv", "title": "测试剧集", "trackingSeason": 1,
            "latest_episode": "S01E06",
        }
        rows = [
            {"vod_id": "recent", "_resource_mode": "pansou"},
            {"vod_id": "complete", "_resource_mode": "pansou"},
        ]
        details = {
            "recent": {"list": [{"vod_play_url": "S01E06$recent-6"}]},
            "complete": {"list": [{"vod_play_url": "#".join(
                "S01E%02d$complete-%d" % (episode, episode) for episode in range(1, 7)
            )}]},
        }
        self.spider._resource_detail = Mock(
            side_effect=lambda row, **_kwargs: details[row["vod_id"]],
        )
        self.spider._validated_playable_detail = Mock(
            side_effect=lambda detail, *_args, **_kwargs: detail,
        )
        self.spider._store_validated_resource_detail = Mock(return_value=True)

        playable = self.spider._playable_resource_rows(
            rows, item, deadline=time.monotonic() + 5,
        )

        self.assertEqual(self.spider._resource_detail.call_count, 2)
        self.assertEqual([row["vod_id"] for row in playable], ["recent", "complete"])

    def test_merge_deduplicates_same_share_exposed_by_multiple_apis(self):
        self.spider.resource_limit = 5
        item = {
            "media_type": "tv", "title": "测试剧集", "trackingSeason": 1,
            "latest_episode": "S01E01",
        }
        share = "https://pan.baidu.com/s/shared"
        vods = [
            {
                "vod_play_from": "盘搜百度", "vod_play_url": "S01E01$pansou-play",
                "resource_id": share, "group_providers": ["baidu"],
                "_resource_mode": "pansou",
            },
            {
                "vod_play_from": "电报百度", "vod_play_url": "S01E01$telegram-play",
                "resource_id": share + "?pwd=1234", "group_providers": ["baidu"],
                "_resource_mode": "telegram",
            },
        ]

        merged = self.spider._merge_resource_vods(
            vods, item, "tmdb:tv:101", {"vod_name": "测试剧集"},
        )

        self.assertEqual(len(merged["vod_play_from"].split("$$$")), 1)

    def test_incomplete_routes_report_missing_episode_range(self):
        item = {
            "media_type": "tv", "title": "择日飞升", "trackingSeason": 1,
            "latest_episode": "S01E06",
        }
        merged = self.spider._merge_resource_vods([{
            "vod_play_from": "近期更新", "vod_play_url": "S01E05$play-5#S01E06$play-6",
            "resource_id": "recent-resource", "group_seasons": [1],
            "group_providers": ["pan123"], "_resource_mode": "pansou",
        }], item, "tmdb:tv:101", {"vod_name": "择日飞升"})

        self.assertIn("线路均不完整 缺少 E01-E04", merged["vod_remarks"])

    def test_cross_api_duplicate_keeps_matching_password_bearing_row(self):
        item = {
            "title": "测试剧集", "year": "2026", "season_count": 1,
            "trackingSeason": 1,
        }
        plain = "https://pan.quark.cn/s/shared"
        protected = plain + "?password=A1"
        self.spider.resource_search_modes = ["pansou", "telegram"]
        self.spider._cache_get = Mock(return_value=None)
        rows = {
            "pansou": [{
                "vod_id": MODULE.quote(plain, safe=""),
                "vod_name": "测试剧集 2026 1080P",
                "work_title": "完全无关的另一部作品",
                "_resource_timestamp": "2026-08-11T02:00:00Z",
                "_resource_mode": "pansou",
            }],
            "telegram": [{
                "vod_id": MODULE.quote(protected, safe=""),
                "vod_name": "测试剧集 2026 4K",
                "work_title": "测试剧集",
                "_resource_timestamp": "2026-08-11T03:00:00Z",
                "_resource_mode": "telegram",
            }],
        }
        self.spider._resource_search_mode = Mock(
            side_effect=lambda mode, _queries, _deadline=None: rows[mode]
        )

        candidates = self.spider._resource_candidates(item, deadline=time.monotonic() + 2)

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["_resource_mode"], "telegram")
        self.assertEqual(candidates[0]["work_title"], "测试剧集")
        self.assertIn("password=A1", MODULE.unquote(candidates[0]["vod_id"]))

    def test_same_opaque_resource_id_from_two_api_indexes_remains_two_playlists(self):
        item = {
            "title": "测试剧集", "year": "2026", "season_count": 1,
            "trackingSeason": 1,
        }
        self.spider.resource_search_modes = ["pansou", "telegram"]
        self.spider._cache_get = Mock(return_value=None)
        self.spider._resource_search_mode = Mock(side_effect=lambda mode, _queries, _deadline=None: [{
            "id": "same-resource", "vod_name": "测试剧集 2026 1080P", "_resource_mode": mode,
        }])

        candidates = self.spider._resource_candidates(item, deadline=time.monotonic() + 2)

        self.assertEqual(len(candidates), 2)
        self.assertEqual(
            {row["_resource_mode"] for row in candidates},
            {"pansou", "telegram"},
        )

    def test_background_validation_interleaves_supplement_apis(self):
        captured = []
        item = {"title": "测试剧集", "year": "2026", "trackingSeason": 1}
        self.spider._resource_search_mode = Mock(side_effect=lambda mode, _queries, _deadline=None: [
            {
                "vod_id": MODULE.quote("https://pan.quark.cn/s/%s-%d" % (mode, index), safe=""),
                "vod_name": "测试剧集 2026 1080P",
                "_resource_mode": mode,
            }
            for index in range(6 if mode == "pansou" else 1)
        ])
        self.spider._checked_resource_rows = Mock(side_effect=lambda rows, _deadline=None: list(rows))
        self.spider._playable_resource_rows = Mock(
            side_effect=lambda rows, *_args, **_kwargs: captured.extend(rows) or []
        )
        cache_key = "fair-background-test"

        self.assertTrue(self.spider._schedule_supplement_resource_search(
            ["pansou", "telegram"], ["测试剧集"], item, cache_key,
        ))
        deadline = time.time() + 2
        while cache_key in self.spider._resource_search_jobs and time.time() < deadline:
            time.sleep(0.01)

        self.assertNotIn(cache_key, self.spider._resource_search_jobs)
        self.assertEqual(
            [row["_resource_mode"] for row in captured[:2]],
            ["pansou", "telegram"],
        )

    def test_background_and_check_links_share_normalized_resource_identity(self):
        variants = (
            "http://pan.quark.cn/s/demo/",
            "https://pan.quark.cn/s/demo?password=test-password",
            "https://pan.quark.cn/s/demo#pwd=test-password",
        )
        identities = {self.spider._resource_row_identity(value) for value in variants}
        self.assertEqual(len(identities), 1)

        captured = []
        self.spider._resource_search_mode = Mock(side_effect=lambda mode, _queries, _deadline=None: [{
            "vod_id": variants[0 if mode == "pansou" else 1],
            "vod_name": "测试剧集 2026 1080P",
            "_resource_mode": mode,
        }])
        self.spider._checked_resource_rows = Mock(
            side_effect=lambda rows, _deadline=None: captured.extend(rows) or []
        )
        self.spider._playable_resource_rows = Mock(return_value=[])
        cache_key = "identity-background-test"

        self.assertTrue(self.spider._schedule_supplement_resource_search(
            ["pansou", "telegram"], ["测试剧集"],
            {"title": "测试剧集", "year": "2026", "trackingSeason": 1},
            cache_key,
        ))
        deadline = time.time() + 2
        while cache_key in self.spider._resource_search_jobs and time.time() < deadline:
            time.sleep(0.01)
        self.assertNotIn(cache_key, self.spider._resource_search_jobs)
        self.assertEqual(len(captured), 1)

        class FakeResponse(object):
            def __init__(self):
                self.status_code = 200
                self.headers = {}
                self.closed = False
                self.payload = json.dumps({
                    "results": [
                        {"url": value, "state": "ok"} for value in variants
                    ],
                }).encode("utf-8")

            def iter_content(self, chunk_size=None):
                return iter((self.payload,))

            def close(self):
                self.closed = True

        response = FakeResponse()
        self.spider._ensure_atvp_connection = Mock(return_value=True)
        self.spider._atvp_session = Mock()
        self.spider._atvp_session.post.return_value = response

        checked = Spider._checked_resource_rows(
            self.spider,
            [{"vod_id": value} for value in variants], deadline=time.monotonic() + 5,
        )

        self.assertEqual(len(checked), 1)
        self.assertEqual(
            len(self.spider._atvp_session.post.call_args.kwargs["json"]["items"]),
            1,
        )
        self.assertTrue(response.closed)

    def test_multiple_resource_api_results_render_distinct_playlists(self):
        item = {
            "media_type": "tv", "tmdb_id": 270603,
            "title": "遭到流放的转生重骑士凭借游戏知识大开无双", "trackingSeason": 1,
        }
        vods = [
            {
                "vod_play_from": "我的云盘",
                "vod_play_url": "S01E01$1@vod1",
                "resource_id": "vod1-270603",
                "group_seasons": [1], "group_providers": ["quark"],
            },
            {
                "vod_play_from": "我的云盘",
                "vod_play_url": "S01E01$1@vod-270603",
                "resource_id": "vod-270603",
                "group_seasons": [1], "group_providers": ["baidu"],
            },
            {
                "vod_play_from": "我的云盘",
                "vod_play_url": "S01E01$1@pansou-270603",
                "resource_id": "pansou-270603",
                "group_seasons": [1], "group_providers": ["ali"],
            },
            {
                "vod_play_from": "我的云盘",
                "vod_play_url": "S01E01$1@telegram-270603",
                "resource_id": "telegram-270603",
                "group_seasons": [1], "group_providers": ["uc"],
            },
        ]

        merged = self.spider._merge_resource_vods(
            vods, item, "tmdb:tv:270603", {"vod_name": item["title"]},
        )

        sources = merged["vod_play_from"].split("$$$")
        urls = merged["vod_play_url"].split("$$$")
        self.assertEqual(len(sources), 4)
        self.assertEqual(len(urls), 4)
        self.assertEqual(len(set(sources)), 4)
        self.assertTrue(all("S01E01$" in value for value in urls))

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

    def test_candidate_provider_survives_rewrite_player_persistence_and_restart(self):
        self.spider._alist_tvbox_plugin = True
        self.spider.route_preheat = False
        self.spider.atvp_api = "https://atvp.example"
        self.spider.atvp_token = "token"
        item = {
            "media_type": "tv", "tmdb_id": 101, "source_id": "tmdb:tv:101",
            "title": "测试剧集", "trackingSeason": 1, "latest_episode": "S01E06",
        }
        self.spider._follow_memory = {"version": 2, "items": {"101": dict(item)}}
        self.spider._atvp_history_snapshot = Mock(return_value=[])
        self.spider._resource_candidates = Mock(return_value=[{
            "vod_id": "opaque-resource", "vod_name": "测试剧集",
            "provider": "夸克", "_resource_mode": "vod",
        }])
        self.spider._resource_detail = Mock(return_value={"list": [{
            "vod_name": "测试剧集", "vod_play_from": "我的云盘",
            "vod_play_url": "S01E06$1@episode-6",
        }]})

        detail = self.spider._alist_detail_from_metadata(
            "tmdb:tv:101", {"list": [{"vod_id": "tmdb:tv:101", "vod_name": "测试剧集"}]},
        )
        real_play_id = next(
            part.rpartition("$")[2]
            for group in detail["list"][0]["vod_play_url"].split("$$$")
            for part in group.split("#")
            if not part.rpartition("$")[2].startswith(self.spider.SELECT_PROMPT_ID)
        )
        parsed = self.spider._parse_followplay(real_play_id)
        self.assertEqual(parsed["resourceProvider"], "quark")

        direct_output = {
            "parse": 0, "jx": 0, "url": "https://cdn.example/video.m3u8", "header": {},
        }
        checked = {
            "reachable": True, "checked_at": time.time(), "startup_ms": 100,
            "height": 1080, "codec": "h264", "subtitle": False,
            "output": direct_output,
        }
        self.spider._atvp_play = Mock(return_value=direct_output)
        self.spider._probe_media_output = Mock(return_value=checked)
        self.spider._register_playback_sync_window = Mock(return_value=True)

        result = self.spider.playerContent("我的云盘", real_play_id, [])

        self.assertEqual(result["url"], direct_output["url"])
        stored = self.spider._follow_memory["items"]["101"]
        self.assertEqual(stored["last_play_route"]["resourceProvider"], "quark")
        self.assertEqual(stored["alist_resource_provider"], "quark")
        persisted = self.spider._sanitize_follow_persisted_item(stored)
        fresh = Spider()
        try:
            fresh.atvp_api = self.spider.atvp_api
            fresh.atvp_token = self.spider.atvp_token
            bound = fresh._bound_resource_row(persisted)
            self.assertEqual(bound["vod_id"], "opaque-resource")
            self.assertEqual(bound["provider"], "quark")
        finally:
            fresh.destroy()

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

    def test_long_magnet_survives_search_followplay_parse_and_player_routing(self):
        magnet = (
            "magnet:?xt=urn:btih:" + ("A" * 40)
            + "&dn=测试剧集&tr=https://tracker.example/announce?token="
            + ("x" * 900)
        )
        self.assertGreater(len(magnet), self.spider.RESOURCE_ID_MAX_LENGTH)
        self.spider._resource_capability = Mock(return_value="present")
        self.spider._resource_api_get = Mock(return_value={"results": [{
            "url": magnet,
            "work_title": "测试剧集",
            "type": "magnet",
        }]})

        rows = self.spider._resource_search_mode("pansou", ["测试剧集"])

        self.assertEqual(len(rows), 1)
        self.assertEqual(MODULE.unquote(rows[0]["vod_id"]), magnet)

        self.spider._resource_api_get = Mock(return_value={"list": []})
        self.spider._resource_detail(rows[0], use_validated_cache=False)
        self.assertEqual(self.spider._resource_api_get.call_args.args[0], "pansou")
        self.assertEqual(self.spider._resource_api_get.call_args.args[1]["id"], magnet)

        play_id = self.spider._build_followplay(
            magnet,
            {"media_type": "tv", "tmdb_id": 101, "title": "测试剧集"},
            rows[0]["vod_id"], 1, 1, "S01E01", resource_mode="pansou",
        )
        parsed = self.spider._parse_followplay(play_id)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["url"], magnet)
        self.assertEqual(MODULE.unquote(parsed["resourceId"]), magnet)

        self.spider._prepare_player_candidates = Mock(side_effect=lambda values: values)
        self.spider._atvp_play = Mock(return_value={
            "parse": 0, "url": "https://cdn.example/video.m3u8", "header": {},
        })
        self.spider._probe_media_output = Mock(return_value=None)
        self.spider._safe_atvp_play_output = Mock(return_value=True)
        self.spider._inject_resume = Mock()
        self.spider._record_route_quality = Mock()
        self.spider._cache_route_probe = Mock()
        self.spider._remember_successful_follow_route = Mock()
        self.spider._register_playback_sync_window = Mock()

        output = self.spider.playerContent("磁力", play_id, [])

        self.assertEqual(output["url"], "https://cdn.example/video.m3u8")
        self.spider._atvp_play.assert_called_once()
        self.assertEqual(self.spider._atvp_play.call_args.args[0], magnet)

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

    def test_stale_resource_response_cannot_mark_new_backend_capability(self):
        class NotFoundResponse(object):
            status_code = 404
            headers = {}

            def __init__(self):
                self.closed = False

            def close(self):
                self.closed = True

        response = NotFoundResponse()
        self.spider.resource_auto_discover = True
        self.spider.atvp_api = "https://old-atvp.example"
        self.spider.atvp_token = "old-token"
        self.spider._ensure_atvp_connection = Mock(return_value=True)
        self.spider.getCache = Mock(return_value=None)
        self.spider.setCache = Mock()
        self.spider._atvp_session = Mock()

        def switch_backend(*_args, **_kwargs):
            with self.spider._cache_lock:
                self.spider.atvp_api = "https://new-atvp.example"
                self.spider.atvp_token = "new-token"
                self.spider._resource_capabilities = {}
                self.spider._resource_capabilities_backend = ""
                self.spider._cache_generation += 1
            return response

        self.spider._atvp_session.get.side_effect = switch_backend

        with self.assertRaisesRegex(RuntimeError, "HTTP 404"):
            self.spider._resource_api_get("vod", {}, deadline=time.monotonic() + 5)

        self.assertTrue(response.closed)
        self.assertEqual(self.spider._resource_capability("vod"), "unknown")
        persisted_modes = [
            (call.args[1].get("modes") or {})
            for call in self.spider.setCache.call_args_list
            if len(call.args) > 1 and isinstance(call.args[1], dict)
        ]
        self.assertFalse(any("vod" in modes for modes in persisted_modes))

    def test_capability_cold_load_cannot_overwrite_newer_live_probe(self):
        self.spider.resource_auto_discover = True
        self.spider.atvp_api = "https://atvp.example"
        self.spider.atvp_token = "token"
        identity = self.spider._resource_capability_identity()
        started = MODULE.threading.Event()
        release = MODULE.threading.Event()

        def cached_value(_key):
            started.set()
            release.wait(2)
            return {
                "version": self.spider.RESOURCE_CAPABILITY_VERSION,
                "backend": identity,
                "modes": {
                    "vod": {
                        "state": "missing",
                        "status": 404,
                        "checkedAt": int(time.time()),
                    },
                },
            }

        self.spider.getCache = Mock(side_effect=cached_value)
        self.spider.setCache = Mock()
        loader = MODULE.threading.Thread(
            target=lambda: self.spider._resource_capability("vod"),
        )
        loader.start()
        try:
            self.assertTrue(started.wait(1))
            self.assertTrue(self.spider._mark_resource_capability("vod", "present", 200))
        finally:
            release.set()
            loader.join(2)

        self.assertFalse(loader.is_alive())
        self.assertEqual(self.spider._resource_capability("vod"), "present")

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

    def test_atvp_play_keeps_backend_snapshot_for_parse_and_relative_output(self):
        class FakeResponse:
            def __init__(self, payload):
                self.status_code = 200
                self.headers = {}
                self._payload = json.dumps(payload, ensure_ascii=False).encode("utf-8")

            def iter_content(self, chunk_size=None):
                return iter([self._payload])

            def close(self):
                return None

        old_session = Mock()
        old_session.post.return_value = FakeResponse({
            "list": [{"vod_play_url": "S01E01$1@old-route"}],
        })
        old_session.get.return_value = FakeResponse({
            "parse": 0, "url": "/p/old-token/1@old-route", "header": {},
        })
        self.spider.atvp_api = "https://old-atvp.example"
        self.spider.atvp_token = "old-token"
        self.spider._atvp_session = old_session
        self.spider._ensure_atvp_connection = Mock(return_value=True)
        backend = self.spider._resource_capability_identity()

        def switch_backend(*_args, **_kwargs):
            self.spider.atvp_api = "https://new-atvp.example"
            self.spider.atvp_token = "new-token"
            self.spider._atvp_session = Mock()
            return old_session.post.return_value

        old_session.post.side_effect = switch_backend

        result = self.spider._atvp_play(
            "https://pan.quark.cn/s/demo",
            deadline=time.monotonic() + 5,
            expected_generation=self.spider._cache_generation,
            expected_backend=backend,
        )

        self.assertEqual(result["url"], "https://old-atvp.example/p/old-token/1@old-route")
        self.assertEqual(old_session.post.call_args.args[0], "https://old-atvp.example/parse/old-token")
        self.assertEqual(old_session.get.call_args.args[0], "https://old-atvp.example/play/old-token")

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

    def test_route_probe_cache_rejects_oversized_headers(self):
        self.spider.atvp_api = "https://atvp.example"
        self.spider.atvp_token = "token"
        probe = {
            "checked_at": time.time(),
            "reachable": True,
            "output": {
                "parse": 0,
                "url": "https://cdn.example/video.m3u8",
                "header": {"Cookie": "x" * (self.spider.ROUTE_COOKIE_MAX_BYTES + 1)},
            },
        }

        self.spider._cache_route_probe("1@same-play", probe, "resource-a", "vod")

        self.assertEqual(self.spider._route_probe_cache, {})

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

    def test_route_probe_cache_keeps_negative_snapshots_without_output(self):
        self.spider.atvp_api = "https://atvp.example"
        self.spider.atvp_token = "token"
        probe = {
            "checked_at": time.time(),
            "reachable": False,
            "fingerprint": "",
            "error": "HTTP 403",
        }

        self.spider._cache_route_probe("1@failed", probe, "resource-a", "vod")

        cached = self.spider._route_probe_snapshot("1@failed", "resource-a", "vod")
        self.assertIsNotNone(cached)
        self.assertFalse(cached["reachable"])
        self.assertNotIn("output", cached)

    def test_negative_route_probe_expires_before_positive_probe(self):
        self.spider.atvp_api = "https://atvp.example"
        self.spider.atvp_token = "token"
        self.spider.route_probe_ttl = 300
        age = self.spider.ROUTE_PROBE_NEGATIVE_TTL + 1
        negative_key = self.spider._route_probe_key("1@failed", "resource-a", "vod")
        positive_key = self.spider._route_probe_key("1@ok", "resource-b", "vod")
        self.spider._route_probe_cache[negative_key] = {
            "checked_at": time.time() - age, "reachable": False,
        }
        self.spider._route_probe_cache[positive_key] = {
            "checked_at": time.time() - age,
            "reachable": True,
            "output": {"url": "https://cdn.example/video.mp4", "header": {}},
        }

        self.assertIsNone(self.spider._route_probe_snapshot("1@failed", "resource-a", "vod"))
        self.assertIsNotNone(self.spider._route_probe_snapshot("1@ok", "resource-b", "vod"))

    def test_old_preheat_worker_cannot_remove_new_generation_job_owner(self):
        self.spider.atvp_api = "https://atvp.example"
        self.spider.atvp_token = "token"
        self.spider._atvp_session = Mock()
        self.spider._probe_route_candidate = Mock(return_value={
            "checked_at": time.time(),
            "reachable": True,
            "fingerprint": "range-v1:test",
            "output": {"parse": 0, "url": "https://cdn.example/video.mp4", "header": {}},
        })
        self.spider._record_route_quality = Mock()
        threads = []

        class DeferredThread(object):
            daemon = False

            def __init__(self, target):
                self.target = target
                threads.append(self)

            def start(self):
                return None

        records = [{
            "episode_key": (1, 1),
            "resource_id": "resource-a",
            "payload": {"url": "1@episode-1", "resourceMode": "vod"},
        }]
        with patch.object(MODULE.threading, "Thread", DeferredThread):
            self.spider._schedule_route_preheat(records, {"history_episode": "S01E01"})
            probe_key = self.spider._route_probe_key("1@episode-1", "resource-a", "vod")
            old_owner = self.spider._route_probe_jobs[probe_key]
            with self.spider._cache_lock:
                self.spider._route_probe_jobs.clear()
                self.spider._cache_generation += 1
            self.spider._schedule_route_preheat(records, {"history_episode": "S01E01"})
            new_owner = self.spider._route_probe_jobs[probe_key]

        self.assertIsNot(old_owner, new_owner)
        threads[0].target()
        self.spider._probe_route_candidate.assert_not_called()
        self.assertIs(self.spider._route_probe_jobs[probe_key], new_owner)
        self.assertIsNone(self.spider._route_probe_snapshot("1@episode-1", "resource-a", "vod"))

        threads[1].target()
        self.spider._probe_route_candidate.assert_called_once()
        self.assertNotIn(probe_key, self.spider._route_probe_jobs)
        self.assertTrue(
            self.spider._route_probe_snapshot("1@episode-1", "resource-a", "vod")["reachable"],
        )

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

    def test_stale_player_does_not_persist_route_after_backend_switch(self):
        self.spider.atvp_api = "https://old-atvp.example"
        self.spider.atvp_token = "old-token"
        self.spider._follow_memory = {"version": 2, "items": {
            "101": {"tmdb_id": 101, "title": "测试剧集"},
        }}
        item = {"media_type": "tv", "tmdb_id": 101, "title": "测试剧集"}
        play_id = self.spider._build_followplay(
            "1@episode-1", item, "old-resource", 1, 1, "S01E01",
        )
        output = {"parse": 0, "url": "https://cdn.example/video.mp4", "header": {}}

        def switch_backend(*_args, **_kwargs):
            with self.spider._cache_lock:
                self.spider.atvp_api = "https://new-atvp.example"
                self.spider.atvp_token = "new-token"
                self.spider._cache_generation += 1
            return output

        self.spider._atvp_play = Mock(side_effect=switch_backend)
        self.spider._probe_media_output = Mock(return_value={
            "checked_at": time.time(), "reachable": True, "output": output,
        })
        self.spider._register_playback_sync_window = Mock(return_value=True)

        result = self.spider.playerContent("线路", play_id, [])

        self.assertEqual(result["url"], output["url"])
        self.assertNotIn("last_play_route", self.spider._follow_memory["items"]["101"])
        self.assertEqual(self.spider._route_probe_cache, {})
        self.spider._register_playback_sync_window.assert_not_called()

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

    def test_follow_save_sanitizes_signed_resource_urls_before_persisting(self):
        self.spider._follow_state_loaded = True
        captured = {}

        def persist(state):
            captured.update(state)
            return True

        self.spider._persist_follow_state = Mock(side_effect=persist)

        self.assertTrue(self.spider._save_follow_state({
            "101": {
                "tmdb_id": 101,
                "title": "测试剧集",
                "alist_vod_id": "https://cdn.example/video.m3u8?signature=secret",
                "alist_resource_mode": "pansou",
                "alist_resource_provider": "quark",
            },
        }))

        stored = captured["items"]["101"]
        self.assertNotIn("alist_vod_id", stored)
        self.assertNotIn("alist_resource_mode", stored)
        self.assertNotIn("alist_resource_provider", stored)
        self.assertEqual(self.spider._follow_memory["items"]["101"], stored)

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
            "alist_resource_provider": "quark",
            "last_play_route": {
                "resourceId": "data:text/plain,secret",
                "resourceMode": "vod",
                "resourceProvider": "quark",
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
        self.assertNotIn("alist_resource_provider", item)
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

    def test_history_login_json_is_bounded_streamed_and_closed(self):
        class FakeResponse(object):
            def __init__(self, content, content_length=None):
                self.status_code = 200
                self.headers = {
                    "Content-Length": str(len(content) if content_length is None else content_length),
                }
                self.content = content
                self.closed = False

            def iter_content(self, chunk_size=None):
                return iter((self.content,))

            def close(self):
                self.closed = True

        oversized = FakeResponse(b"", self.spider.HISTORY_CONFIG_MAX_BYTES + 1)
        invalid = FakeResponse(b"not-json")
        self.spider.atvp_api = "https://history.example:443"
        self.spider.history_username = "user"
        self.spider.history_password = "pass"
        self.spider._atvp_session = Mock()
        self.spider._atvp_session.headers = {}
        self.spider._atvp_session.post.side_effect = [oversized, invalid]

        with self.assertRaisesRegex(RuntimeError, "响应过大"):
            self.spider._atvp_history_login(force=True)
        with self.assertRaisesRegex(RuntimeError, "无效 JSON"):
            self.spider._atvp_history_login(force=True)

        self.assertTrue(oversized.closed)
        self.assertTrue(invalid.closed)
        self.assertEqual(self.spider._atvp_session.post.call_count, 2)
        self.assertTrue(all(
            call.kwargs.get("stream") is True
            for call in self.spider._atvp_session.post.call_args_list
        ))

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

    def test_history_upload_payload_deduplicates_keys_and_keeps_newest(self):
        rows = [
            {"key": "same", "createTime": 10, "position": 100},
            {"key": "same", "createTime": 20, "position": 200},
            {"key": "other", "createTime": 15, "position": 50},
        ]
        payload = self.spider._history_upload_payload(rows)
        self.assertEqual([row["key"] for row in payload], ["same", "other"])
        self.assertEqual(payload[0]["position"], 200)

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

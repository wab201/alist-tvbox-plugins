"""Evidence runner for the V80 playback-call-family concurrency boundary."""

import argparse
import datetime as dt
import hashlib
import importlib.util
import ipaddress
import json
import sys
import threading
import time
import types
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parent.parent
CANDIDATE_PATH = ROOT / "build" / "v80-dev" / "豆瓣TMDB追更单入口.py"
MANIFEST_PATH = ROOT / "src" / "douban_tmdb_follow_single" / "release.json"
OVERLAY_PATH = ROOT / "tools" / "build_v80_playback_concurrency_ownership_overlay.py"
TEST_PATH = ROOT / "tests" / "test_v80_p5_playback_concurrency.py"
DEFAULT_REPORT = ROOT / "work" / "v80-p5-playback-concurrency.json"
REPORT_SCHEMA = "v80-p5-playback-concurrency/1"
SCENARIOS = (
    "concurrent_player_isolation",
    "old_atvp_session_isolation",
    "response_connection_close",
    "cancelled_slot_release",
    "foreground_background_isolation",
    "live_init_generation_fence",
    "stale_side_effect_rejection",
    "destroy_cleanup",
)
SCENARIO_LABELS_ZH = {
    "concurrent_player_isolation": "并发播放调用隔离",
    "old_atvp_session_isolation": "旧代次 ATVP 会话隔离",
    "response_connection_close": "响应与连接单次关闭",
    "cancelled_slot_release": "取消后的播放槽位释放",
    "foreground_background_isolation": "前台播放与后台任务隔离",
    "live_init_generation_fence": "实时初始化代次围栏",
    "stale_side_effect_rejection": "陈旧播放副作用拒绝",
    "destroy_cleanup": "播放资源销毁清理",
}
LIMITATIONS = (
    "candidate_bound_playback_call_family_only",
    "controlled_sessions_connections_and_forbidden_real_network",
    "no_real_server_mumu_fongmi_or_device_latency",
    "history_concurrency_is_a_separate_package",
    "report_freshness_requires_external_sha256_and_stage_closure",
)
_CANDIDATE_RUN_LOCK = threading.Lock()
_BOUND_CANDIDATE_BYTES = None


class PlaybackConcurrencyAssertionError(AssertionError):
    pass


def _require(condition, detail):
    if not condition:
        raise PlaybackConcurrencyAssertionError(detail)


def _sha256(payload):
    return hashlib.sha256(payload).hexdigest().upper()


def _load(name, path, payload=None):
    if payload is None:
        payload = Path(path).read_bytes()
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load playback evidence input")
    module = importlib.util.module_from_spec(spec)
    exec(compile(payload, str(path), "exec"), module.__dict__)
    return module


def _load_candidate(name):
    base_module = types.ModuleType("base")
    spider_module = types.ModuleType("base.spider")
    missing = object()
    previous_base = sys.modules.get("base", missing)
    previous_spider = sys.modules.get("base.spider", missing)

    class BaseSpider(object):
        pass

    spider_module.Spider = BaseSpider
    sys.modules["base"] = base_module
    sys.modules["base.spider"] = spider_module
    try:
        payload = _BOUND_CANDIDATE_BYTES
        if payload is None:
            payload = CANDIDATE_PATH.read_bytes()
        return _load(name, CANDIDATE_PATH, payload=payload)
    finally:
        if previous_spider is missing:
            sys.modules.pop("base.spider", None)
        else:
            sys.modules["base.spider"] = previous_spider
        if previous_base is missing:
            sys.modules.pop("base", None)
        else:
            sys.modules["base"] = previous_base


class ResponseFixture(object):
    def __init__(self, body=b'{"url":"https://media.example/video.mp4"}',
                 status=200, read_started=None, read_release=None):
        self.status_code = int(status)
        self.headers = {"Content-Length": str(len(body))}
        self.body = bytes(body)
        self.read_started = read_started
        self.read_release = read_release
        self.close_calls = 0

    def iter_content(self, chunk_size=65536):
        del chunk_size
        if self.read_started is not None:
            self.read_started.set()
        if self.read_release is not None:
            _require(self.read_release.wait(5.0), "response release timed out")
        yield self.body

    def close(self):
        self.close_calls += 1


class SessionFixture(object):
    def __init__(self, label):
        self.label = label
        self.headers = {}
        self.proxies = {}
        self.trust_env = False
        self.close_calls = 0
        self.get_calls = 0
        self.post_calls = 0
        self.get_handler = None
        self.post_handler = None

    def mount(self, *_args, **_kwargs):
        return None

    def get(self, *args, **kwargs):
        self.get_calls += 1
        if not callable(self.get_handler):
            raise AssertionError("unexpected real-network GET surface")
        return self.get_handler(*args, **kwargs)

    def post(self, *args, **kwargs):
        self.post_calls += 1
        if not callable(self.post_handler):
            raise AssertionError("unexpected real-network POST surface")
        return self.post_handler(*args, **kwargs)

    def delete(self, *_args, **_kwargs):
        raise AssertionError("unexpected real-network DELETE surface")

    def close(self):
        self.close_calls += 1


class SessionFactory(object):
    def __init__(self):
        self.sessions = []

    def __call__(self):
        session = SessionFixture("session-%d" % (len(self.sessions) + 1))
        self.sessions.append(session)
        return session

    def active(self):
        _require(len(self.sessions) >= 3, "session factory did not create a runtime triplet")
        return tuple(self.sessions[-3:])


def _runtime(name, token=None):
    if token is None:
        token = "test-playback"
    module = _load_candidate(name)
    factory = SessionFactory()
    original = module.requests
    module.requests = types.SimpleNamespace(
        Session=factory,
        adapters=original.adapters,
        exceptions=original.exceptions,
        packages=original.packages,
    )
    spider = module.Spider()
    spider.init({
        "atvp_plugin_mode": "alist-tvbox-raw",
        "atvp_api": "http://127.0.0.1:5000",
        "atvp_token": token,
        "route_preheat": False,
    })
    return module, spider, factory


def _join(thread, detail, timeout=5.0):
    thread.join(timeout)
    _require(not thread.is_alive(), detail)


def _play_id(spider, tmdb_id, target):
    return spider._build_followplay(
        target,
        {
            "media_type": "movie",
            "tmdb_id": tmdb_id,
            "source_id": "source-%s" % tmdb_id,
            "title": "Playback Fixture %s" % tmdb_id,
            "year": 2026,
        },
        str(tmdb_id), 1, 1, "正片",
    )


def _stub_player_side_effects(spider, resume=None, register=None):
    spider._inject_resume = resume or (lambda *_args, **_kwargs: None)
    spider._record_route_quality = lambda *_args, **_kwargs: None
    spider._cache_route_probe = lambda *_args, **_kwargs: None
    spider._remember_successful_follow_route = lambda *_args, **_kwargs: None
    spider._register_playback_sync_window = register or (lambda *_args, **_kwargs: True)
    spider._schedule_native_history_ui_refresh = lambda: True


def _scenario_concurrent_player_isolation():
    _module, spider, _factory = _runtime("v80_p5e_concurrent_player")
    barrier = threading.Barrier(2)
    records = []
    record_lock = threading.Lock()
    results = {}
    targets = {
        "a": "https://media.example/a.mp4",
        "b": "https://media.example/b.mp4",
    }

    def probe(output, deadline=None, **_kwargs):
        del deadline
        barrier.wait(3.0)
        return {"output": dict(output), "reachable": True, "startup_ms": 1}

    def resume(output, parsed):
        with record_lock:
            records.append((str(parsed.get("tmdbId")), output.get("url")))

    spider._probe_media_output = probe
    _stub_player_side_effects(spider, resume=resume)
    threads = []
    try:
        for key, tmdb_id in (("a", 101), ("b", 202)):
            play_id = _play_id(spider, tmdb_id, targets[key])
            thread = threading.Thread(
                target=lambda owned=key, value=play_id: results.__setitem__(
                    owned, spider.playerContent("线路-%s" % owned, value, []),
                )
            )
            threads.append(thread)
            thread.start()
        for thread in threads:
            _join(thread, "concurrent player call did not finish")
        _require(results["a"].get("url") == targets["a"], "player A crossed outputs")
        _require(results["b"].get("url") == targets["b"], "player B crossed outputs")
        _require(
            sorted(records) == [("101", targets["a"]), ("202", targets["b"])],
            "resume side effects crossed player calls",
        )
        return {"calls": 2, "distinct_outputs": 2, "crossed_side_effects": 0}
    finally:
        spider.destroy()


def _scenario_old_atvp_session_isolation():
    _module, spider, factory = _runtime("v80_p5e_old_session", "old-token")
    old_session = factory.active()[2]
    read_started = threading.Event()
    read_release = threading.Event()
    response = ResponseFixture(read_started=read_started, read_release=read_release)
    old_session.get_handler = lambda *_args, **_kwargs: response
    old_generation = spider._cache_generation
    old_backend = spider._resource_capability_identity()
    result = {}

    def run_old_play():
        try:
            result["value"] = spider._atvp_play(
                "1@old-play",
                expected_generation=old_generation,
                expected_backend=old_backend,
            )
        except Exception as exc:
            result["error"] = type(exc).__name__

    worker = threading.Thread(target=run_old_play)
    try:
        worker.start()
        _require(read_started.wait(3.0), "old session did not own the response read")
        spider.init({
            "atvp_plugin_mode": "alist-tvbox-raw",
            "atvp_api": "http://127.0.0.1:5000",
            "atvp_token": "new-token",
            "route_preheat": False,
        })
        new_session = factory.active()[2]
        read_release.set()
        _join(worker, "old ATVP request did not settle")
        _require(new_session is not old_session, "live init reused the old ATVP session")
        _require(old_session.get_calls == 1, "old play did not use the old session once")
        _require(new_session.get_calls == 0, "old play reached the new ATVP session")
        _require(old_session.close_calls == 1, "live init did not close the old session once")
        _require(response.close_calls == 1, "old response was not closed exactly once")
        return {
            "old_session_requests": old_session.get_calls,
            "new_session_requests": new_session.get_calls,
            "old_session_close_calls": old_session.close_calls,
            "response_close_calls": response.close_calls,
        }
    finally:
        read_release.set()
        if worker.is_alive():
            _join(worker, "old ATVP cleanup timed out")
        spider.destroy()


def _scenario_response_connection_close():
    module, spider, factory = _runtime("v80_p5e_close_owner")
    response = ResponseFixture()
    factory.active()[2].get_handler = lambda *_args, **_kwargs: response
    connections = []

    class SocketFixture(object):
        def settimeout(self, _value):
            return None

    class HTTPResponseFixture(object):
        status = 206

        def __init__(self):
            self.sent = False

        def getheaders(self):
            return (("Content-Type", "video/mp4"), ("Content-Length", "4"))

        def read1(self, _size):
            if self.sent:
                return b""
            self.sent = True
            return b"data"

    class ConnectionFixture(object):
        def __init__(self, *_args, **_kwargs):
            self.close_calls = 0
            self.sock = SocketFixture()
            connections.append(self)

        def request(self, *_args, **_kwargs):
            return None

        def getresponse(self):
            return HTTPResponseFixture()

        def close(self):
            self.close_calls += 1

    module._PinnedHTTPConnection = ConnectionFixture
    try:
        output = spider._atvp_play("1@close-owner")
        _require(output.get("url"), "ATVP response fixture did not produce playback output")
        generation = spider._cache_generation
        with spider._timeout_budget_controller.scope(
                "player", 5, expected_generation=generation) as operation:
            pinned = spider._pinned_media_request_blocking(
                urlparse("http://media.example/video.mp4"),
                ipaddress.ip_address("8.8.8.8"), {}, time.monotonic() + 2,
                control={}, timeout_operation=operation,
            )
        _require(pinned and pinned.get("status") == 206, "pinned request did not complete")
        _require(response.close_calls == 1, "ATVP response close owner drifted")
        _require(len(connections) == 1, "pinned request created an unexpected connection count")
        _require(connections[0].close_calls == 1, "pinned connection was not closed once")
        return {
            "response_close_calls": response.close_calls,
            "connection_close_calls": connections[0].close_calls,
        }
    finally:
        spider.destroy()


def _scenario_cancelled_slot_release():
    _module, spider, _factory = _runtime("v80_p5e_slot_cancel")
    release = threading.Event()
    started = threading.Event()
    state = {"count": 0}
    lock = threading.Lock()

    def blocker():
        with lock:
            state["count"] += 1
            if state["count"] == 4:
                started.set()
        _require(release.wait(5.0), "media blocker release timed out")

    blockers = [spider._media_probe_executor.submit(blocker) for _index in range(4)]
    recovered = 0
    try:
        _require(started.wait(2.0), "media executor was not saturated")
        result = spider._pinned_media_request(
            urlparse("http://media.example/video.mp4"),
            ipaddress.ip_address("8.8.8.8"), {}, time.monotonic() + 0.05,
        )
        for _index in range(4):
            if spider._media_probe_slots.acquire(False):
                recovered += 1
        for _index in range(recovered):
            spider._media_probe_slots.release()
        _require(result is None, "cancelled queued probe returned a result")
        _require(recovered == 4, "cancelled queued probe leaked a media slot")
        return {"cancelled_tasks": 1, "slot_capacity_recovered": recovered}
    finally:
        release.set()
        for future in blockers:
            future.result(timeout=5.0)
        spider.destroy()


def _scenario_foreground_background_isolation():
    _module, spider, _factory = _runtime("v80_p5e_lane_isolation")
    release = threading.Event()
    started = threading.Event()
    state = {"count": 0}
    lock = threading.Lock()

    def blocker():
        with lock:
            state["count"] += 1
            if state["count"] == spider.RESOURCE_BACKGROUND_MODE_WORKERS:
                started.set()
        _require(release.wait(5.0), "background blocker release timed out")

    blockers = [
        spider._resource_background_mode_executor.submit(blocker)
        for _index in range(spider.RESOURCE_BACKGROUND_MODE_WORKERS)
    ]
    target = "https://media.example/foreground.mp4"
    spider._probe_media_output = lambda output, deadline=None, **_kwargs: {
        "output": dict(output), "reachable": True, "startup_ms": 1,
    }
    _stub_player_side_effects(spider)
    try:
        _require(started.wait(2.0), "background executor was not saturated")
        started_at = time.monotonic()
        output = spider.playerContent("前台线路", _play_id(spider, 303, target), [])
        elapsed = time.monotonic() - started_at
        _require(output.get("url") == target, "foreground playback was blocked or crossed")
        _require(not release.is_set(), "background blockers were released before playback")
        return {
            "background_workers_blocked": len(blockers),
            "foreground_completed_while_blocked": True,
            "host_elapsed_ms": max(1, int(round(elapsed * 1000))),
        }
    finally:
        release.set()
        for future in blockers:
            future.result(timeout=5.0)
        spider.destroy()


def _scenario_live_init_generation_fence():
    _module, spider, _factory = _runtime("v80_p5e_generation_fence", "old-token")
    entered = threading.Event()
    release = threading.Event()
    init_done = threading.Event()
    side_effect_generations = []
    result = {}
    old_generation = spider._cache_generation

    def resume(_output, _parsed):
        entered.set()
        _require(release.wait(5.0), "resume fence release timed out")
        side_effect_generations.append(spider._cache_generation)

    def register(_parsed):
        side_effect_generations.append(spider._cache_generation)
        return True

    def record_route_quality(_route_id, reachable, **_kwargs):
        if reachable:
            _require(init_done.wait(5.0), "live init did not finish before the next side effect")

    spider._probe_media_output = lambda output, deadline=None, **_kwargs: {
        "output": dict(output), "reachable": True, "startup_ms": 1,
    }
    _stub_player_side_effects(spider, resume=resume, register=register)
    spider._record_route_quality = record_route_quality

    player_thread = threading.Thread(
        target=lambda: result.__setitem__(
            "value", spider.playerContent(
                "旧线路", _play_id(spider, 404, "https://media.example/fence.mp4"), [],
            ),
        )
    )

    def run_init():
        spider.init({
            "atvp_plugin_mode": "alist-tvbox-raw",
            "atvp_api": "http://127.0.0.1:5000",
            "atvp_token": "new-token",
            "route_preheat": False,
        })
        init_done.set()

    init_thread = threading.Thread(target=run_init)
    try:
        player_thread.start()
        _require(entered.wait(3.0), "player did not reach the History side-effect fence")
        init_thread.start()
        time.sleep(0.1)
        _require(not init_done.is_set(), "live init crossed an owned History side effect")
        release.set()
        _join(player_thread, "fenced player did not finish")
        _join(init_thread, "live init did not finish after the player released")
        _require(side_effect_generations, "player did not execute an owned side effect")
        _require(all(value == old_generation for value in side_effect_generations),
                 "playback side effects escaped to the new generation")
        _require(spider._cache_generation == old_generation + 1,
                 "live init did not advance exactly one generation")
        player_result = result.get("value")
        _require(isinstance(player_result, dict), "fenced player returned no result")
        _require(player_result.get("url") == "", "stale player returned a playable output")
        _require("cancelled" in str(player_result.get("msg") or "").lower(),
                 "stale player did not return the expected cancellation")
        return {
            "old_generation": old_generation,
            "new_generation": spider._cache_generation,
            "init_blocked_at_owned_side_effect": True,
            "old_generation_side_effects": len(side_effect_generations),
            "new_generation_side_effects": 0,
            "player_result": "cancelled",
        }
    finally:
        release.set()
        if player_thread.is_alive():
            _join(player_thread, "player fence cleanup timed out")
        if init_thread.is_alive():
            _join(init_thread, "init fence cleanup timed out")
        spider.destroy()


def _scenario_stale_side_effect_rejection():
    _module, spider, _factory = _runtime("v80_p5e_stale_effects", "old-token")
    old_generation = spider._cache_generation
    old_backend = spider._resource_capability_identity()
    target = "https://media.example/current.mp4"
    resource_id = "current-resource"
    history_effects = []
    try:
        spider.init({
            "atvp_plugin_mode": "alist-tvbox-raw",
            "atvp_api": "http://127.0.0.1:5000",
            "atvp_token": "new-token",
            "route_preheat": False,
        })
        current_generation = spider._cache_generation
        current_backend = spider._resource_capability_identity()
        current_probe = {
            "output": {"parse": 0, "jx": 0, "url": target, "header": {}},
            "reachable": True,
            "checked_at": time.time(),
        }
        spider._cache_route_probe(
            target, current_probe, resource_id=resource_id,
            expected_generation=current_generation, expected_backend=current_backend,
        )
        spider._record_route_quality(
            "1@stale", True,
            expected_generation=old_generation, expected_backend=old_backend,
        )
        spider._cache_route_probe(
            target,
            {"output": {"parse": 0, "jx": 0,
                        "url": "https://media.example/stale.mp4", "header": {}},
             "reachable": True, "checked_at": time.time()},
            resource_id=resource_id,
            expected_generation=old_generation, expected_backend=old_backend,
        )
        spider._invalidate_route_probe(
            target, resource_id,
            expected_generation=old_generation, expected_backend=old_backend,
        )
        spider._refresh_native_history_views = lambda: history_effects.append("views")
        spider._refresh_local_follow_progress = lambda: history_effects.append("progress")
        spider._refresh_follow_categories = lambda: history_effects.append("categories")
        with spider._history_ui_refresh_lock:
            current_token = spider._history_ui_refresh_token
        spider._native_history_ui_refresh_step(
            current_token, old_generation, "early", time.monotonic(),
        )
        snapshot = spider._route_probe_snapshot(target, resource_id)
        _require(not spider._route_quality_history, "stale route quality mutated current state")
        _require(spider._route_quality_loaded is False,
                 "stale route quality changed the current lazy-load owner")
        _require(snapshot and snapshot["output"]["url"] == target,
                 "stale probe write or invalidation replaced the current probe")
        _require(not history_effects, "stale History callback reached current UI state")
        return {
            "route_quality_writes": 0,
            "route_quality_loaded": False,
            "current_probe_preserved": True,
            "history_refresh_side_effects": len(history_effects),
        }
    finally:
        spider.destroy()


def _scenario_destroy_cleanup():
    _module, spider, factory = _runtime("v80_p5e_destroy_cleanup")
    active_sessions = factory.active()
    executors = (
        spider._resource_search_executor,
        spider._follow_refresh_executor,
        spider._resource_foreground_mode_executor,
        spider._resource_background_mode_executor,
        spider._dns_executor,
        spider._media_probe_executor,
    )
    parsed = {
        "tmdbId": 505, "sourceId": "source-505", "resourceId": "505",
        "resourceMode": "vod", "season": 1, "episode": 1, "name": "Cleanup",
    }
    _require(spider._register_playback_sync_window(parsed),
             "playback cleanup scenario did not register a timer")
    spider._schedule_native_history_ui_refresh()
    supervisor = spider._tasks
    spider.destroy()
    _require(supervisor.is_closed(), "destroy did not close the task supervisor")
    _require(all(getattr(executor, "_shutdown", False) for executor in executors),
             "destroy did not close every instance executor")
    _require(all(session.close_calls == 1 for session in active_sessions),
             "destroy did not close active sessions exactly once")
    _require(spider._session is spider._tmdb_session is spider._atvp_session is None,
             "destroy retained a session reference")
    _require(not spider._playback_sync_pending, "destroy retained playback pending state")
    _require(not spider._playback_sync_timers, "destroy retained playback timers")
    _require(not spider._playback_sync_tokens, "destroy retained playback tokens")
    _require(not spider._playback_sync_inflight, "destroy retained playback inflight state")
    return {
        "sessions_closed_once": sum(session.close_calls == 1 for session in active_sessions),
        "session_references_cleared": 3,
        "executors_shutdown": sum(getattr(executor, "_shutdown", False) for executor in executors),
        "playback_state_entries": sum(len(value) for value in (
            spider._playback_sync_pending,
            spider._playback_sync_timers,
            spider._playback_sync_tokens,
            spider._playback_sync_inflight,
        )),
        "task_supervisor_closed": supervisor.is_closed(),
    }


SCENARIO_FUNCTIONS = {
    "concurrent_player_isolation": _scenario_concurrent_player_isolation,
    "old_atvp_session_isolation": _scenario_old_atvp_session_isolation,
    "response_connection_close": _scenario_response_connection_close,
    "cancelled_slot_release": _scenario_cancelled_slot_release,
    "foreground_background_isolation": _scenario_foreground_background_isolation,
    "live_init_generation_fence": _scenario_live_init_generation_fence,
    "stale_side_effect_rejection": _scenario_stale_side_effect_rejection,
    "destroy_cleanup": _scenario_destroy_cleanup,
}


def validate_report(report):
    _require(isinstance(report, dict), "playback report must be an object")
    _require(report.get("schema") == REPORT_SCHEMA, "playback report schema drifted")
    rows = report.get("scenario_results")
    _require(isinstance(rows, list), "playback scenario rows are missing")
    _require(tuple(row.get("name") for row in rows) == SCENARIOS,
             "playback scenario order drifted")
    _require(all(row.get("status") == "passed" for row in rows),
             "playback report contains a failed scenario")
    for row in rows:
        _require(row.get("label_zh") == SCENARIO_LABELS_ZH[row["name"]],
                 "playback scenario label drifted")
        _require(isinstance(row.get("duration_seconds"), (int, float))
                 and row["duration_seconds"] >= 0,
                 "playback scenario duration drifted")
    _require(report.get("summary") == {"passed": 8, "failed": 0, "total": 8},
             "playback report summary drifted")
    _require(report.get("overall") == "passed", "playback report was not admitted")
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    candidate = report.get("candidate") or {}
    _require(candidate.get("size") == manifest.get("expected_size"),
             "playback report candidate size drifted")
    _require(candidate.get("sha256") == str(manifest.get("expected_sha256")).upper(),
             "playback report candidate SHA256 drifted")
    _require(candidate.get("path") == CANDIDATE_PATH.relative_to(ROOT).as_posix(),
             "playback report candidate path drifted")
    _require(report.get("workload") == {
        "call_family": "playback",
        "scenario_count": 8,
        "overlay_alias_zh": "播放并发所有权覆盖层",
    }, "playback report workload drifted")
    _require(tuple(report.get("limitations") or ()) == LIMITATIONS,
             "playback report limitations drifted")
    expected_provenance = {
        "runner": {
            "path": Path(__file__).relative_to(ROOT).as_posix(),
            "sha256": _sha256(Path(__file__).read_bytes()),
        },
        "overlay": {
            "path": OVERLAY_PATH.relative_to(ROOT).as_posix(),
            "sha256": _sha256(OVERLAY_PATH.read_bytes()),
        },
        "test": {
            "path": TEST_PATH.relative_to(ROOT).as_posix(),
            "sha256": _sha256(TEST_PATH.read_bytes()),
        },
    }
    _require(report.get("evidence_provenance") == expected_provenance,
             "playback report provenance drifted")
    metrics = {row["name"]: row.get("metrics") for row in rows}
    _require(metrics["concurrent_player_isolation"] == {
        "calls": 2, "distinct_outputs": 2, "crossed_side_effects": 0,
    }, "concurrent player evidence drifted")
    _require(metrics["old_atvp_session_isolation"] == {
        "old_session_requests": 1,
        "new_session_requests": 0,
        "old_session_close_calls": 1,
        "response_close_calls": 1,
    }, "old ATVP session evidence drifted")
    _require(metrics["response_connection_close"] == {
        "response_close_calls": 1, "connection_close_calls": 1,
    }, "response/connection close evidence drifted")
    _require(metrics["cancelled_slot_release"] == {
        "cancelled_tasks": 1, "slot_capacity_recovered": 4,
    }, "cancelled slot evidence drifted")
    lane = metrics["foreground_background_isolation"] or {}
    _require(lane.get("background_workers_blocked", 0) >= 1
             and lane.get("foreground_completed_while_blocked") is True
             and lane.get("host_elapsed_ms", 0) >= 1,
             "foreground/background evidence drifted")
    fence = metrics["live_init_generation_fence"] or {}
    _require(fence.get("new_generation") == fence.get("old_generation", -2) + 1
             and fence.get("init_blocked_at_owned_side_effect") is True
             and fence.get("old_generation_side_effects") == 1
             and fence.get("new_generation_side_effects") == 0
             and fence.get("player_result") == "cancelled",
             "live-init generation evidence drifted")
    _require(metrics["stale_side_effect_rejection"] == {
        "route_quality_writes": 0,
        "route_quality_loaded": False,
        "current_probe_preserved": True,
        "history_refresh_side_effects": 0,
    }, "stale side-effect evidence drifted")
    _require(metrics["destroy_cleanup"] == {
        "sessions_closed_once": 3,
        "session_references_cleared": 3,
        "executors_shutdown": 6,
        "playback_state_entries": 0,
        "task_supervisor_closed": True,
    }, "destroy cleanup evidence drifted")
    return True


def run_playback_concurrency():
    global _BOUND_CANDIDATE_BYTES
    candidate = CANDIDATE_PATH.read_bytes()
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    _require(len(candidate) == manifest["expected_size"], "candidate size does not match manifest")
    _require(_sha256(candidate) == str(manifest["expected_sha256"]).upper(),
             "candidate SHA256 does not match manifest")
    rows = []
    with _CANDIDATE_RUN_LOCK:
        _require(_BOUND_CANDIDATE_BYTES is None, "candidate evidence run is already active")
        _BOUND_CANDIDATE_BYTES = candidate
        try:
            for name in SCENARIOS:
                started = time.monotonic()
                try:
                    metrics = SCENARIO_FUNCTIONS[name]()
                    rows.append({
                        "name": name,
                        "label_zh": SCENARIO_LABELS_ZH[name],
                        "status": "passed",
                        "duration_seconds": round(time.monotonic() - started, 3),
                        "metrics": metrics,
                    })
                except Exception as exc:
                    rows.append({
                        "name": name,
                        "label_zh": SCENARIO_LABELS_ZH[name],
                        "status": "failed",
                        "duration_seconds": round(time.monotonic() - started, 3),
                        "error": "%s: %s" % (type(exc).__name__, exc),
                        "metrics": {},
                    })
        finally:
            _BOUND_CANDIDATE_BYTES = None
    passed = sum(row["status"] == "passed" for row in rows)
    report = {
        "schema": REPORT_SCHEMA,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
        "evidence_provenance": {
            "runner": {"path": str(Path(__file__).relative_to(ROOT)).replace("\\", "/"),
                       "sha256": _sha256(Path(__file__).read_bytes())},
            "overlay": {"path": str(OVERLAY_PATH.relative_to(ROOT)).replace("\\", "/"),
                        "sha256": _sha256(OVERLAY_PATH.read_bytes())},
            "test": {"path": str(TEST_PATH.relative_to(ROOT)).replace("\\", "/"),
                     "sha256": _sha256(TEST_PATH.read_bytes())},
        },
        "candidate": {
            "path": str(CANDIDATE_PATH.relative_to(ROOT)).replace("\\", "/"),
            "size": len(candidate),
            "sha256": _sha256(candidate),
        },
        "workload": {
            "call_family": "playback",
            "scenario_count": len(SCENARIOS),
            "overlay_alias_zh": "播放并发所有权覆盖层",
        },
        "limitations": list(LIMITATIONS),
        "scenario_results": rows,
        "summary": {"passed": passed, "failed": len(rows) - passed, "total": len(rows)},
        "overall": "passed" if passed == len(rows) else "failed",
    }
    if report["overall"] == "passed":
        validate_report(report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json-out", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args(argv)
    report = run_playback_concurrency()
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report["summary"], ensure_ascii=False, sort_keys=True))
    return 0 if report["overall"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())

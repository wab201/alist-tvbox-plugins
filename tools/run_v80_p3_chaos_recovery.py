"""Run deterministic P3 chaos scenarios against the isolated V80 build."""

import argparse
import importlib.util
import ipaddress
import json
import os
import socket
import sys
import types
from functools import lru_cache
from pathlib import Path

import requests


ROOT = Path(__file__).resolve().parents[1]
BUILD_PATH = ROOT / "tools" / "build_follow_plugin.py"
MANIFEST_PATH = ROOT / "src" / "douban_tmdb_follow_single" / "release.json"
DEFAULT_REPORT = ROOT / "work" / "v80-p3-chaos-recovery.json"
REPORT_SCHEMA = "v80-p3-chaos-recovery/1"
EXPECTED_RECOVERY_MS = {
    "tmdb_500_stale": 1000,
    "tmdb_timeout_stale": 1000,
    "pansou_timeout": 30000,
    "history_401_reauth": 0,
    "history_500_isolation": 1000,
    "alist_502": 30000,
    "dns_failure": 30000,
    "ipv6_unreachable": 30000,
    "expired_play_url": 0,
    "truncated_json": 0,
    "oversized_json_boundary": 0,
    "stale_lifecycle_task": 0,
    "resource_combiner_fail_open": 0,
}


class ChaosAssertionError(AssertionError):
    pass


class VirtualClock(object):
    def __init__(self):
        self.seconds = 0.0

    def time(self):
        return self.seconds

    def monotonic(self):
        return self.seconds

    def advance_ms(self, milliseconds):
        self.seconds += float(milliseconds) / 1000.0

    def milliseconds(self):
        return int(round(self.seconds * 1000.0))


class FakeResponse(object):
    def __init__(self, status_code=200, payload=None, raw=None, declared_length=None):
        self.status_code = int(status_code)
        if raw is None:
            raw = json.dumps(
                {} if payload is None else payload,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        self.content = bytes(raw)
        length = len(self.content) if declared_length is None else int(declared_length)
        self.headers = {"Content-Length": str(length)}
        self.closed = False

    def json(self):
        return json.loads(self.content.decode("utf-8"))

    def iter_content(self, chunk_size=65536):
        for offset in range(0, len(self.content), max(1, int(chunk_size))):
            yield self.content[offset:offset + chunk_size]

    def close(self):
        self.closed = True


class SequenceSession(object):
    def __init__(self, actions):
        self.actions = list(actions)
        self.calls = []
        self.headers = {}

    def _send(self, method, url, **kwargs):
        self.calls.append({"method": method, "url": str(url)})
        if not self.actions:
            raise ChaosAssertionError("fixture session ran out of actions")
        action = self.actions.pop(0)
        if isinstance(action, BaseException):
            raise action
        if callable(action):
            return action(method, url, **kwargs)
        return action

    def get(self, url, **kwargs):
        return self._send("GET", url, **kwargs)

    def post(self, url, **kwargs):
        return self._send("POST", url, **kwargs)

    def delete(self, url, **kwargs):
        return self._send("DELETE", url, **kwargs)

    def close(self):
        return None


class InlineTasks(object):
    def __init__(self):
        self.closed = False

    def start_thread(self, target, args=(), kwargs=None, name="background"):
        if self.closed:
            raise RuntimeError("inline task supervisor is closed")
        target(*tuple(args or ()), **dict(kwargs or {}))
        return True

    def is_closed(self):
        return self.closed


def _require(condition, detail):
    if not condition:
        raise ChaosAssertionError(detail)


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load %s" % path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BUILD = _load("v80_p3_chaos_build", BUILD_PATH)


@lru_cache(maxsize=1)
def _build_result():
    return BUILD.build_release(MANIFEST_PATH)


def _runtime_module():
    base_module = types.ModuleType("base")
    spider_module = types.ModuleType("base.spider")

    class BaseSpider(object):
        pass

    spider_module.Spider = BaseSpider
    sys.modules.setdefault("base", base_module)
    sys.modules.setdefault("base.spider", spider_module)
    module = types.ModuleType("v80_p3_chaos_runtime")
    exec(
        compile(_build_result()["bytes"], "v80-p3-chaos-runtime.py", "exec"),
        module.__dict__,
    )
    return module


def _new_spider(module):
    spider = module.Spider()
    spider._diagnostic_event = lambda *args, **kwargs: None
    spider._alist_tvbox_plugin = True
    spider.atvp_api = "https://atvp.invalid"
    spider.atvp_token = "fixture"
    spider._history_primary_origin = spider.atvp_api
    spider._history_api_origins = [spider.atvp_api]
    spider._ensure_atvp_connection = lambda force=False: True
    return spider


def _close_spider(spider, original_tasks=None):
    if original_tasks is not None:
        spider._tasks = original_tasks
    spider.destroy()


def _configure_history_auth(spider):
    spider.history_username = "fixture-user"
    spider.history_password = "fixture-password"
    spider._v80_history_auth_token = "fixture-session"
    spider._v80_history_auth_origin = spider.atvp_api
    spider._v80_history_auth_uid = 1
    spider._v80_history_auth_username = spider.history_username
    spider._v80_history_auth_generation = spider._cache_generation
    spider._history_selected_origin = spider.atvp_api


def _followplay_available(spider):
    spider._prepare_player_candidates = lambda candidates: list(candidates)
    spider._probe_media_output = lambda output, **kwargs: {
        "output": dict(output), "startup_ms": 1,
    }
    spider._record_route_quality = lambda *args, **kwargs: None
    spider._cache_route_probe = lambda *args, **kwargs: None
    spider._remember_successful_follow_route = lambda *args, **kwargs: None
    spider._inject_resume = lambda *args, **kwargs: None
    spider._register_playback_sync_window = lambda *args, **kwargs: None
    spider._schedule_native_history_ui_refresh = lambda: None
    play_id = spider._build_followplay(
        "https://media.invalid/video.mp4",
        {"title": "Fixture", "media_type": "tv"}, "",
        1, 1, "S01E01", resource_mode="vod",
    )
    _require(bool(play_id), "followplay isolation fixture could not be built")
    output = spider.playerContent("AList", play_id)
    return output.get("url") == "https://media.invalid/video.mp4"


def _tmdb_stale_scenario(fault):
    module = _runtime_module()
    spider = _new_spider(module)
    clock = VirtualClock()
    original_tasks = spider._tasks
    spider._tasks = InlineTasks()
    spider._cache_health_controller._clock = clock.time
    spider.tmdb_access_token = "fixture"
    spider.tmdb_api_key = ""
    spider.tmdb_api_base = "https://tmdb.invalid"
    spider.tmdb_language = "zh-CN"
    spider.list_cache_ttl = 60
    spider.stale_ttl = 3600

    def cold_success(_method, _url, **_kwargs):
        clock.advance_ms(250)
        return FakeResponse(payload={"results": [{"id": 1}]})

    session = SequenceSession([
        cold_success,
        fault,
        FakeResponse(payload={"results": [{"id": 2}]}),
    ])
    spider._tmdb_session = session
    path = "/trending/tv/day"
    params = {"page": 1}
    try:
        cold_started = clock.milliseconds()
        initial = spider._tmdb_api(path, params)
        cold_ms = clock.milliseconds() - cold_started
        hot_started = clock.milliseconds()
        hot = spider._tmdb_api(path, params)
        hot_ms = clock.milliseconds() - hot_started
        _require(initial == hot == {"results": [{"id": 1}]}, "TMDB cache warmup failed")
        _require(len(session.calls) == 1, "TMDB hot cache performed a network request")

        tmdb_keys = [key for key in spider._cache if str(key).startswith("tmdb-json:")]
        _require(len(tmdb_keys) == 1, "TMDB cache key was not isolated")
        key = tmdb_keys[0]
        created, value = spider._cache[key]
        spider._cache[key] = (created - 61, value)
        if key in spider._persistent_cache:
            persistent_created, persistent_value = spider._persistent_cache[key]
            spider._persistent_cache[key] = (persistent_created - 61, persistent_value)

        failed_at = clock.milliseconds()
        stale = spider._tmdb_api(path, params)
        _require(stale == initial, "TMDB fault cleared the compliant stale cache")
        _require(len(session.calls) == 2, "TMDB fault injection did not reach the loader")
        blocked = spider._tmdb_api(path, params)
        _require(blocked == initial, "TMDB backoff stopped serving stale data")
        _require(len(session.calls) == 2, "TMDB backoff allowed an early retry")

        clock.advance_ms(999)
        spider._tmdb_api(path, params)
        _require(len(session.calls) == 2, "TMDB retry occurred before the one-second baseline")
        clock.advance_ms(1)
        spider._tmdb_api(path, params)
        recovered = spider._tmdb_api(path, params)
        _require(recovered == {"results": [{"id": 2}]}, "TMDB refresh did not recover")
        _require(len(session.calls) == 3, "TMDB recovery performed an unexpected request count")
        return {
            "recovery_ms": clock.milliseconds() - failed_at,
            "cold_start_ms": cold_ms,
            "hot_cache_ms": hot_ms,
            "network_calls": len(session.calls),
            "stale_preserved": True,
        }
    finally:
        _close_spider(spider, original_tasks)


def _provider_scenario(mode, fault_factory, expected_kind):
    module = _runtime_module()
    spider = _new_spider(module)
    clock = VirtualClock()
    identity = spider._resource_capability_identity()
    controller = spider._provider_reliability_for(identity)
    controller._clock = clock.monotonic
    actions = [fault_factory() for _ in range(3)]
    actions.extend([
        FakeResponse(payload={"list": [{"id": "independent"}]}),
        FakeResponse(payload={"list": [{"id": "recovered"}]}),
    ])
    session = SequenceSession(actions)
    spider._atvp_session = session
    independent_mode = "vod" if mode != "vod" else "telegram"
    try:
        for _ in range(3):
            try:
                spider._resource_api_get(mode, {"wd": "fixture"})
            except Exception as exc:
                _require(
                    module.v80_reliability_classify(exc) == expected_kind,
                    "provider failure kind drifted",
                )
            else:
                raise ChaosAssertionError("provider fault unexpectedly succeeded")
        opened = spider._provider_reliability_controller.snapshot(identity, mode)
        _require(opened["state"] == "open", "provider circuit did not open")

        independent = spider._resource_api_get(independent_mode, {"wd": "fixture"})
        _require(independent["list"][0]["id"] == "independent", "provider isolation failed")
        failed_at = clock.milliseconds()
        clock.advance_ms(29999)
        calls_before = len(session.calls)
        try:
            spider._resource_api_get(mode, {"wd": "fixture"})
        except Exception as exc:
            _require(
                module.v80_reliability_classify(exc) == "circuit_open",
                "provider circuit admitted an early probe",
            )
        else:
            raise ChaosAssertionError("provider circuit recovered too early")
        _require(len(session.calls) == calls_before, "open circuit performed network I/O")

        clock.advance_ms(1)
        recovered = spider._resource_api_get(mode, {"wd": "fixture"})
        _require(recovered["list"][0]["id"] == "recovered", "provider probe failed")
        closed = spider._provider_reliability_controller.snapshot(identity, mode)
        _require(closed["state"] == "closed", "provider circuit did not close")
        return {
            "recovery_ms": clock.milliseconds() - failed_at,
            "failure_kind": expected_kind,
            "independent_provider_available": True,
            "network_calls": len(session.calls),
        }
    finally:
        spider.destroy()


def _history_401_scenario():
    module = _runtime_module()
    spider = _new_spider(module)
    _configure_history_auth(spider)
    session = SequenceSession([
        FakeResponse(status_code=401, payload={"message": "fixture"}),
        FakeResponse(payload={
            "id": 1,
            "token": "test-renewed-session",
            "authorities": [{"authority": "USER"}],
        }),
        FakeResponse(payload={"items": [], "deleted": [], "nextSince": "1"}),
    ])
    spider._atvp_session = session
    try:
        rows = module.v80_history_fetch(
            spider, lambda: (_ for _ in ()).throw(
                ChaosAssertionError("History 401 unexpectedly used legacy fallback")
            ),
        )
        _require(rows == [], "History 401 reauthentication did not recover")
        _require(_followplay_available(spider), "History 401 blocked followplay playback")
        methods = [item["method"] for item in session.calls]
        _require(methods == ["GET", "POST", "GET"], "History 401 request sequence drifted")
        _require(
            session.calls[0]["url"].endswith("/api/playback/changes"),
            "History 401 did not use the V145 playback route",
        )
        return {
            "recovery_ms": 0,
            "forced_logins": 1,
            "request_calls": len(session.calls),
            "request_methods": methods,
            "v145_route": True,
            "playback_available": True,
        }
    finally:
        spider.destroy()


def _history_500_scenario():
    module = _runtime_module()
    spider = _new_spider(module)
    clock = VirtualClock()
    original_tasks = spider._tasks
    spider._tasks = InlineTasks()
    spider._cache_health_controller._clock = clock.time
    _configure_history_auth(spider)
    session = SequenceSession([
        FakeResponse(status_code=500, payload={"message": "fixture"}),
        FakeResponse(payload={"items": [], "deleted": [], "nextSince": "1"}),
    ])
    spider._atvp_session = session
    spider._reconcile_follow_histories = lambda histories, changed: 0
    spider._refresh_follow_categories = lambda: None
    key = "atvp-history-snapshot"
    try:
        failed_at = clock.milliseconds()
        _require(spider._schedule_atvp_history_refresh(key, lightweight=True), "History fault task was not admitted")
        _require(spider._has_cached_failure(key), "History 500 did not enter cache backoff")
        _require(_followplay_available(spider), "History 500 blocked followplay playback")
        _require(not spider._schedule_atvp_history_refresh(key, lightweight=True), "History 500 retried immediately")
        clock.advance_ms(999)
        _require(not spider._schedule_atvp_history_refresh(key, lightweight=True), "History retried before baseline")
        clock.advance_ms(1)
        _require(spider._schedule_atvp_history_refresh(key, lightweight=True), "History recovery was not admitted")
        _require(not spider._has_cached_failure(key), "History recovery did not clear backoff")
        _require(
            all(item["url"].endswith("/api/playback/changes") for item in session.calls),
            "History 500 did not stay on the V145 playback route",
        )
        return {
            "recovery_ms": clock.milliseconds() - failed_at,
            "failure_kind": "server",
            "request_calls": len(session.calls),
            "v145_route": True,
            "playback_available": True,
            "cache_recovered": True,
        }
    finally:
        _close_spider(spider, original_tasks)


def _payload_scenario(raw, oversized=False):
    module = _runtime_module()
    spider = _new_spider(module)
    clock = VirtualClock()
    identity = spider._resource_capability_identity()
    controller = spider._provider_reliability_for(identity)
    controller._clock = clock.monotonic
    declared_length = 0 if oversized else None
    session = SequenceSession([
        FakeResponse(raw=raw, declared_length=declared_length),
        FakeResponse(payload={"list": [{"id": "recovered"}]}),
    ])
    spider._atvp_session = session
    try:
        try:
            spider._resource_api_get("vod", {"wd": "fixture"})
        except Exception as exc:
            _require(module.v80_reliability_classify(exc) == "payload", "payload failure kind drifted")
        else:
            raise ChaosAssertionError("invalid payload unexpectedly succeeded")
        failed = spider._provider_reliability_controller.snapshot(identity, "vod")
        _require(failed["state"] == "closed", "payload error opened the transient circuit")
        _require(failed["non_transient_failures"] == 1, "payload error was not counted once")
        recovered = spider._resource_api_get("vod", {"wd": "fixture"})
        _require(recovered["list"][0]["id"] == "recovered", "payload path did not recover")
        return {
            "recovery_ms": 0,
            "failure_kind": "payload",
            "circuit_opened": False,
            "stream_limit_checked": bool(oversized),
        }
    finally:
        spider.destroy()


def _expired_play_url_scenario():
    module = _runtime_module()
    spider = _new_spider(module)
    old_output = {"parse": 0, "url": "https://cdn.invalid/expired.m3u8", "header": {}}
    new_output = {"parse": 0, "url": "https://cdn.invalid/fresh.m3u8", "header": {}}
    play_outputs = [old_output, new_output]
    probes = [None, {"output": new_output, "startup_ms": 50}]
    spider._prepare_player_candidates = lambda candidates: list(candidates)
    spider._atvp_play = lambda *args, **kwargs: dict(play_outputs.pop(0))
    spider._probe_media_output = lambda *args, **kwargs: probes.pop(0)
    spider._resolve_addresses = lambda *_args, **_kwargs: {
        ipaddress.ip_address("1.1.1.1")
    }
    spider._record_route_quality = lambda *args, **kwargs: None
    spider._cache_route_probe = lambda *args, **kwargs: None
    spider._remember_successful_follow_route = lambda *args, **kwargs: None
    spider._inject_resume = lambda *args, **kwargs: None
    spider._register_playback_sync_window = lambda *args, **kwargs: None
    spider._schedule_native_history_ui_refresh = lambda: None
    play_id = spider._build_followplay(
        "1@fixture", {"title": "Fixture", "media_type": "tv"}, "",
        1, 1, "S01E01", resource_mode="vod",
    )
    try:
        _require(bool(play_id), "followplay fixture could not be built")
        output = spider.playerContent("AList", play_id)
        _require(output.get("url") == new_output["url"], "expired play URL was not reissued")
        _require(not play_outputs and not probes, "play URL reissue call count drifted")
        return {
            "recovery_ms": 0,
            "play_requests": 2,
            "probe_requests": 2,
            "fresh_url_returned": True,
        }
    finally:
        spider.destroy()


def _stale_lifecycle_scenario():
    module = _runtime_module()
    spider = _new_spider(module)
    key = "tmdb-json:lifecycle"
    job_owner = object()
    try:
        old_generation = spider._cache_health_controller.claim_refresh(key, job_owner)
        _require(old_generation == 0, "cache lifecycle fixture did not start at generation zero")
        spider._cache_generation = 1
        spider._cache[key] = (module.time.time(), {"generation": 1})
        committed = spider._cache_health_controller.commit_refresh_success(
            key, {"generation": 0}, old_generation, job_owner,
        )
        _require(committed is False, "stale cache task committed into the new generation")
        _require(spider._cache[key][1] == {"generation": 1}, "stale cache task replaced new state")

        controller = spider._background_bulkhead_controller
        controller.reset(1)
        old_lease = controller.acquire("history", 1)
        _require(old_lease is not None, "old lifecycle lease was not admitted")
        controller.reset(2)
        new_lease = controller.acquire("history", 2)
        _require(new_lease is not None, "new lifecycle lease was not admitted")
        old_lease.finish()
        _require(controller.snapshot()["inflight"]["history"] == 1, "old lease released new capacity")
        new_lease.finish()
        _require(controller.snapshot()["inflight"]["history"] == 0, "new lease did not release capacity")
        return {
            "recovery_ms": 0,
            "stale_cache_commit_rejected": True,
            "stale_bulkhead_release_fenced": True,
        }
    finally:
        spider.destroy()


def _resource_combiner_fail_open_scenario():
    module = _runtime_module()
    spider = _new_spider(module)
    original_combiner = module.combine_v70_layered_resource_rows
    calls = {"combiner": 0, "legacy": 0}
    rows = [
        {"vod_id": "vod-one", "vod_name": "One", "_resource_mode": "vod"},
        {"vod_id": "pan-one", "vod_name": "Two", "_resource_mode": "pansou"},
    ]
    item = {"title": "Fixture", "tmdb_id": "1"}
    fallback = [dict(rows[1]), dict(rows[0])]

    def fail_combiner(*args, **kwargs):
        calls["combiner"] += 1
        raise RuntimeError("fixture combiner failure")

    def legacy_order(actual_rows, actual_item, bound="", modes=None):
        calls["legacy"] += 1
        _require(actual_rows is rows, "legacy fallback did not receive the original rows")
        _require(actual_item is item, "legacy fallback did not receive the original item")
        _require(bound == "", "background legacy fallback binding changed")
        _require(tuple(modes or ()) == ("vod", "pansou"), "legacy fallback modes changed")
        return fallback

    try:
        module.combine_v70_layered_resource_rows = fail_combiner
        spider._resource_fair_candidate_order = legacy_order
        spider._v80_resource_layered_output_enabled = True
        output = spider._resource_output_candidate_order(
            rows,
            item,
            bound="layered-bound",
            cached_rows=({"vod_id": "cached"},),
            modes=("vod", "pansou"),
            legacy_bound="",
        )
        _require(output is fallback, "legacy fallback output was not returned")
        _require(calls["combiner"] == 1, "combiner failure was retried")
        _require(calls["legacy"] == 1, "legacy fallback did not execute exactly once")
        return {
            "recovery_ms": 0,
            "switch_active": True,
            "combiner_calls": calls["combiner"],
            "legacy_fallback_calls": calls["legacy"],
            "retry_attempts": 0,
            "legacy_bound": "",
            "fallback_preserved": True,
        }
    finally:
        module.combine_v70_layered_resource_rows = original_combiner
        spider.destroy()


def _scenario_functions():
    module = _runtime_module()
    max_bytes = int(module.Spider.RESOURCE_API_RESPONSE_MAX_BYTES)
    return {
        "tmdb_500_stale": lambda: _tmdb_stale_scenario(
            FakeResponse(status_code=500, payload={"status_message": "fixture"})
        ),
        "tmdb_timeout_stale": lambda: _tmdb_stale_scenario(requests.Timeout("fixture")),
        "pansou_timeout": lambda: _provider_scenario(
            "pansou", lambda: requests.Timeout("fixture"), "timeout",
        ),
        "history_401_reauth": _history_401_scenario,
        "history_500_isolation": _history_500_scenario,
        "alist_502": lambda: _provider_scenario(
            "vod", lambda: FakeResponse(status_code=502, payload={"message": "fixture"}), "server",
        ),
        "dns_failure": lambda: _provider_scenario(
            "telegram", lambda: socket.gaierror(-2, "fixture"), "dns",
        ),
        "ipv6_unreachable": lambda: _provider_scenario(
            "vod1", lambda: requests.ConnectionError(OSError(101, "fixture")), "transport",
        ),
        "expired_play_url": _expired_play_url_scenario,
        "truncated_json": lambda: _payload_scenario(b'{"list":['),
        "oversized_json_boundary": lambda: _payload_scenario(
            b" " * (max_bytes + 1), oversized=True,
        ),
        "stale_lifecycle_task": _stale_lifecycle_scenario,
        "resource_combiner_fail_open": _resource_combiner_fail_open_scenario,
    }


def run_chaos_recovery():
    build = _build_result()
    functions = _scenario_functions()
    scenarios = []
    for name in EXPECTED_RECOVERY_MS:
        try:
            evidence = functions[name]()
            recovery_ms = int(evidence.get("recovery_ms", -1))
            expected_ms = EXPECTED_RECOVERY_MS[name]
            _require(recovery_ms == expected_ms, "%s recovery baseline drifted" % name)
            scenarios.append({
                "name": name,
                "status": "passed",
                "expected_recovery_ms": expected_ms,
                "recovery_ms": recovery_ms,
                "evidence": evidence,
            })
        except Exception as exc:
            scenarios.append({
                "name": name,
                "status": "failed",
                "expected_recovery_ms": EXPECTED_RECOVERY_MS[name],
                "error_type": type(exc).__name__,
                "error": (
                    str(exc)[:240]
                    if isinstance(exc, ChaosAssertionError)
                    else "scenario execution failed"
                ),
            })
    passed = sum(row["status"] == "passed" for row in scenarios)
    tmdb = next((row for row in scenarios if row["name"] == "tmdb_500_stale"), {})
    tmdb_evidence = tmdb.get("evidence", {}) if isinstance(tmdb, dict) else {}
    return {
        "schema": REPORT_SCHEMA,
        "candidate": {
            "size": build["size"],
            "sha256": build["sha256"],
            "output": str(build["output"].relative_to(ROOT)).replace("\\", "/"),
        },
        "clock": "virtual",
        "performance_baseline": {
            "source": "virtual_fault_fixture",
            "cold_start_ms": tmdb_evidence.get("cold_start_ms"),
            "hot_cache_ms": tmdb_evidence.get("hot_cache_ms"),
            "note": "Synthetic transport latency; not a real-device benchmark.",
        },
        "summary": {
            "total": len(scenarios),
            "passed": passed,
            "failed": len(scenarios) - passed,
        },
        "scenarios": scenarios,
        "oversized_json_scope": "existing_stream_boundary_only_p4_unified_security_pending",
        "production_writes": False,
        "deployment_attempted": False,
    }


def write_report(path, report):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    os.replace(str(temp), str(path))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json-out", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args(argv)
    report = run_chaos_recovery()
    write_report(args.json_out, report)
    summary = report["summary"]
    print(
        "V80 P3 chaos recovery: %d/%d passed (%s)"
        % (summary["passed"], summary["total"], args.json_out)
    )
    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

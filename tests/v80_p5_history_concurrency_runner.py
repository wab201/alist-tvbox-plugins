"""Evidence runner for the V80 History-call-family concurrency boundary."""

import argparse
import contextlib
import datetime as dt
import hashlib
import importlib.util
import json
import sys
import threading
import time
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
CANDIDATE_PATH = ROOT / "build" / "v80-dev" / "豆瓣TMDB追更单入口.py"
MANIFEST_PATH = ROOT / "src" / "douban_tmdb_follow_single" / "release.json"
OVERLAY_PATH = ROOT / "tools" / "build_v80_history_concurrency_ownership_overlay.py"
TEST_PATH = ROOT / "tests" / "test_v80_p5_history_concurrency.py"
DEFAULT_REPORT = ROOT / "work" / "v80-p5-history-concurrency.json"
REPORT_SCHEMA = "v80-p5-history-concurrency/1"
SCENARIOS = (
    "live_init_job_reset",
    "old_background_owner_isolation",
    "old_manual_owner_isolation",
    "duplicate_admission_compatibility",
    "submit_failure_owner_isolation",
    "history_sync_lock_serialization",
    "event_queue_generation_fence",
    "destroy_job_cleanup",
)
SCENARIO_LABELS_ZH = {
    "live_init_job_reset": "实时初始化清理旧 History 任务",
    "old_background_owner_isolation": "旧后台任务所有权隔离",
    "old_manual_owner_isolation": "旧手动任务所有权隔离",
    "duplicate_admission_compatibility": "兼容任务集合重复准入",
    "submit_failure_owner_isolation": "提交失败所有权隔离",
    "history_sync_lock_serialization": "History 同步锁串行化观察",
    "event_queue_generation_fence": "History 事件队列代次围栏观察",
    "destroy_job_cleanup": "History 任务销毁清理",
}
LIMITATIONS = (
    "candidate_bound_history_call_family_only",
    "job_generation_ownership_is_the_only_modified_slice",
    "history_sync_lock_and_event_queue_are_independent_observations",
    "controlled_no_network_runtime",
    "no_real_server_mumu_fongmi_or_device_latency",
    "report_freshness_requires_external_sha256_and_stage_closure",
)
_CANDIDATE_RUN_LOCK = threading.Lock()
_BOUND_CANDIDATE_BYTES = None


class HistoryConcurrencyAssertionError(AssertionError):
    pass


def _require(condition, detail):
    if not condition:
        raise HistoryConcurrencyAssertionError(detail)


def _sha256(payload):
    return hashlib.sha256(payload).hexdigest().upper()


def _load(name, path, payload=None):
    if payload is None:
        payload = Path(path).read_bytes()
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load History evidence input")
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


def _runtime(name, token="test-history-evidence"):
    module = _load_candidate(name)
    spider = module.Spider()
    spider.init({
        "atvp_plugin_mode": "alist-tvbox-raw",
        "atvp_api": "http://127.0.0.1:5000",
        "atvp_token": token,
        "route_preheat": False,
    })
    return module, spider


def _capture_submissions(spider):
    workers = []
    spider._submit_background_bulkhead_task = (
        lambda _kind, _generation, worker, _name: workers.append(worker) or True
    )
    return workers


def _scenario_live_init_job_reset():
    _module, spider = _runtime("v80_p5f_live_init_reset", "old-token")
    workers = _capture_submissions(spider)
    try:
        _require(spider._schedule_atvp_history_refresh("history-cache"),
                 "old generation History job was not admitted")
        old_owner = spider._atvp_job_owners.get("sync-background")
        spider.init({
            "atvp_plugin_mode": "alist-tvbox-raw",
            "atvp_api": "http://127.0.0.1:5000",
            "atvp_token": "new-token",
            "route_preheat": False,
        })
        _require(not spider._atvp_jobs and not spider._atvp_job_owners,
                 "live init retained old History task state")
        _require(spider._schedule_atvp_history_refresh("history-cache"),
                 "new generation History job was blocked by stale state")
        new_owner = spider._atvp_job_owners.get("sync-background")
        _require(new_owner is not None and new_owner is not old_owner,
                 "new generation did not receive a distinct History owner")
        return {
            "old_marker_cleared": True,
            "new_generation_admitted": True,
            "distinct_owner": True,
            "captured_workers": len(workers),
        }
    finally:
        spider.destroy()


def _scenario_old_background_owner_isolation():
    _module, spider = _runtime("v80_p5f_old_background", "old-token")
    workers = _capture_submissions(spider)
    try:
        _require(spider._schedule_atvp_history_refresh("history-cache"),
                 "old background History job was not admitted")
        old_worker = workers[0]
        spider.init({
            "atvp_plugin_mode": "alist-tvbox-raw",
            "atvp_api": "http://127.0.0.1:5000",
            "atvp_token": "new-token",
            "route_preheat": False,
        })
        _require(spider._schedule_atvp_history_refresh("history-cache"),
                 "new background History job was not admitted")
        owner = spider._atvp_job_owners["sync-background"]
        cache_owner = spider._refreshing_cache_keys["history-cache"]
        old_worker()
        _require(spider._atvp_job_owners.get("sync-background") is owner,
                 "old background finally cleared the new owner")
        _require(spider._refreshing_cache_keys.get("history-cache") is cache_owner,
                 "old background finally cleared the new cache owner")
        _require("sync-background" in spider._atvp_jobs,
                 "old background finally cleared the compatibility marker")
        return {
            "new_job_owner_preserved": True,
            "new_cache_owner_preserved": True,
            "compatibility_marker_preserved": True,
        }
    finally:
        spider.destroy()


def _scenario_old_manual_owner_isolation():
    _module, spider = _runtime("v80_p5f_old_manual", "old-token")
    workers = _capture_submissions(spider)
    try:
        first = json.loads(spider._start_atvp_job("probe"))
        _require("已开始" in str(first.get("msg") or ""),
                 "old manual History job was not admitted")
        old_worker = workers[0]
        spider.init({
            "atvp_plugin_mode": "alist-tvbox-raw",
            "atvp_api": "http://127.0.0.1:5000",
            "atvp_token": "new-token",
            "route_preheat": False,
        })
        second = json.loads(spider._start_atvp_job("probe"))
        _require("已开始" in str(second.get("msg") or ""),
                 "new manual History job was not admitted")
        owner = spider._atvp_job_owners["probe"]
        old_worker()
        _require(spider._atvp_job_owners.get("probe") is owner,
                 "old manual finally cleared the new owner")
        _require("probe" in spider._atvp_jobs,
                 "old manual finally cleared the compatibility marker")
        return {
            "new_manual_owner_preserved": True,
            "compatibility_marker_preserved": True,
        }
    finally:
        spider.destroy()


def _scenario_duplicate_admission_compatibility():
    _module, spider = _runtime("v80_p5f_duplicate_admission")
    _capture_submissions(spider)
    try:
        _require(spider._schedule_atvp_history_refresh("history-cache"),
                 "first History job was not admitted")
        owner = spider._atvp_job_owners["sync-background"]
        cache_owner = spider._refreshing_cache_keys["history-cache"]
        second = spider._schedule_atvp_history_refresh("history-cache")
        _require(second is False, "duplicate History job was admitted")
        _require(spider._atvp_jobs == {"sync-background"},
                 "compatibility set drifted after duplicate admission")
        _require(spider._atvp_job_owners["sync-background"] is owner,
                 "duplicate admission replaced the active owner")
        _require(spider._refreshing_cache_keys["history-cache"] is cache_owner,
                 "duplicate admission replaced the cache owner")
        return {
            "first_admitted": True,
            "duplicate_rejected": True,
            "active_owner_preserved": True,
        }
    finally:
        spider.destroy()


def _scenario_submit_failure_owner_isolation():
    _module, spider = _runtime("v80_p5f_submit_failure")
    replacement_owner = object()
    replacement_cache_owner = object()

    def replace_then_fail(_kind, _generation, _worker, _name):
        with spider._atvp_job_lock:
            spider._atvp_job_owners["sync-background"] = replacement_owner
            spider._atvp_jobs.add("sync-background")
        with spider._cache_lock:
            spider._refreshing_cache_keys["history-cache"] = replacement_cache_owner
        raise RuntimeError("controlled submit failure")

    spider._submit_background_bulkhead_task = replace_then_fail
    try:
        _require(spider._schedule_atvp_history_refresh("history-cache") is False,
                 "controlled submit failure was not reported")
        _require(spider._atvp_job_owners.get("sync-background") is replacement_owner,
                 "submit failure cleared a replacement job owner")
        _require(spider._refreshing_cache_keys.get("history-cache") is replacement_cache_owner,
                 "submit failure cleared a replacement cache owner")
        return {
            "submit_failed": True,
            "replacement_job_owner_preserved": True,
            "replacement_cache_owner_preserved": True,
        }
    finally:
        spider.destroy()


def _scenario_history_sync_lock_serialization():
    _module, spider = _runtime("v80_p5f_sync_lock")
    first_entered = threading.Event()
    release = threading.Event()
    state_lock = threading.Lock()
    state = {"active": 0, "max_active": 0, "entries": 0}

    def worker(first=False):
        with spider._history_sync_lock:
            with state_lock:
                state["active"] += 1
                state["entries"] += 1
                state["max_active"] = max(state["max_active"], state["active"])
            if first:
                first_entered.set()
                _require(release.wait(5.0), "History sync-lock release timed out")
            with state_lock:
                state["active"] -= 1

    first = threading.Thread(target=worker, kwargs={"first": True})
    second = threading.Thread(target=worker)
    try:
        first.start()
        _require(first_entered.wait(3.0), "first History sync owner did not enter")
        second.start()
        time.sleep(0.05)
        with state_lock:
            _require(state["max_active"] == 1 and state["entries"] == 1,
                     "History sync lock admitted concurrent owners")
        release.set()
        first.join(5.0)
        second.join(5.0)
        _require(not first.is_alive() and not second.is_alive(),
                 "History sync-lock observation did not finish")
        _require(state["entries"] == 2 and state["max_active"] == 1,
                 "History sync lock did not serialize both owners")
        return {"owners": 2, "max_concurrent": state["max_active"]}
    finally:
        release.set()
        first.join(5.0) if first.is_alive() else None
        second.join(5.0) if second.is_alive() else None
        spider.destroy()


class _QueueResponse(object):
    status_code = 204

    def close(self):
        return None


class _QueueSession(object):
    def __init__(self, owner):
        self.owner = owner
        self.headers = {}
        self.calls = 0

    def post(self, _url, **_kwargs):
        self.calls += 1
        self.owner._cache_generation += 1
        return _QueueResponse()


class _QueueOperation(object):
    def request_timeout(self, value, retry_policy=None):
        del retry_policy
        return value

    def track(self, response):
        return response

    @staticmethod
    def close_tracked(response):
        response.close()


class _QueueOwner(object):
    HISTORY_ROW_LIMIT = 100
    HISTORY_RESPONSE_MAX_BYTES = 1024 * 1024
    RESOURCE_DETAIL_BUDGET = 30

    def __init__(self):
        self.cache = {}
        self._history_context_lock = threading.RLock()
        self._history_primary_origin = "https://server"
        self._history_selected_origin = "https://server"
        self._v80_history_auth_origin = "https://server"
        self._v80_history_auth_token = "session-token"
        self._v80_history_auth_uid = 1
        self._v80_history_auth_username = "evidence-user"
        self._v80_history_auth_generation = 0
        self._cache_generation = 1
        self.atvp_api = "https://server"
        self.history_api = ""
        self.history_username = "evidence-user"
        self.history_password = "evidence-password"
        self.siteKey = "douban_tmdb_follow_single"
        self.timeout = 8
        self.verify_tls = True
        self._atvp_session = _QueueSession(self)

    def _history_write_enabled(self):
        return True

    def _history_origin_candidates(self):
        return [self.atvp_api]

    @staticmethod
    def _history_retryable_transport_error(_exc, _method):
        return False

    @staticmethod
    def _v80_timeout_child_scope(_operation, _timeout_seconds, deadline=None):
        del deadline
        return contextlib.nullcontext(_QueueOperation())

    def _diagnostic_event(self, *_args, **_kwargs):
        return None

    def getCache(self, key):
        return self.cache.get(key)

    def setCache(self, key, value):
        self.cache[key] = value

    @staticmethod
    def _read_bounded_json_response(response, _label, _max_bytes):
        return getattr(response, "value", None)


def _scenario_event_queue_generation_fence():
    module = _load_candidate("v80_p5f_event_queue")
    owner = _QueueOwner()
    row = {
        "key": "site-a@@@vod-1@@@7",
        "position": 10,
        "duration": 100,
        "createTime": 100,
    }
    cancelled = False
    try:
        module.v80_history_push(owner, [row], lambda _rows: None)
    except module._V80HistoryQueueCancelled:
        cancelled = True
    _require(cancelled, "old-generation event response was not cancelled")
    state = module.v80_history_queue_snapshot(owner)
    _require(len(state.get("events") or []) == 1,
             "cancelled event was not retained for the current owner")
    event = state["events"][0]
    _require(event.get("status") == "pending" and event.get("attempts") == 0,
             "generation cancellation consumed the event retry budget")
    _require(not state.get("acknowledged"),
             "old-generation response acknowledged the event")
    return {
        "post_calls": owner._atvp_session.calls,
        "pending_events": 1,
        "attempts_consumed": 0,
        "acknowledged": 0,
    }


def _scenario_destroy_job_cleanup():
    _module, spider = _runtime("v80_p5f_destroy_cleanup")
    _capture_submissions(spider)
    _require(spider._schedule_atvp_history_refresh("history-cache"),
             "History cleanup scenario did not admit a job")
    _require(bool(spider._atvp_jobs) and bool(spider._atvp_job_owners),
             "History cleanup scenario did not own task state")
    spider.destroy()
    _require(not spider._atvp_jobs and not spider._atvp_job_owners,
             "destroy retained History task state")
    return {"compatibility_markers": 0, "owner_entries": 0}


SCENARIO_FUNCTIONS = {
    "live_init_job_reset": _scenario_live_init_job_reset,
    "old_background_owner_isolation": _scenario_old_background_owner_isolation,
    "old_manual_owner_isolation": _scenario_old_manual_owner_isolation,
    "duplicate_admission_compatibility": _scenario_duplicate_admission_compatibility,
    "submit_failure_owner_isolation": _scenario_submit_failure_owner_isolation,
    "history_sync_lock_serialization": _scenario_history_sync_lock_serialization,
    "event_queue_generation_fence": _scenario_event_queue_generation_fence,
    "destroy_job_cleanup": _scenario_destroy_job_cleanup,
}


def validate_report(report):
    _require(isinstance(report, dict), "History report must be an object")
    _require(report.get("schema") == REPORT_SCHEMA, "History report schema drifted")
    rows = report.get("scenario_results")
    _require(isinstance(rows, list), "History scenario rows are missing")
    _require(tuple(row.get("name") for row in rows) == SCENARIOS,
             "History scenario order drifted")
    _require(all(row.get("status") == "passed" for row in rows),
             "History report contains a failed scenario")
    for row in rows:
        _require(row.get("label_zh") == SCENARIO_LABELS_ZH[row["name"]],
                 "History scenario label drifted")
        _require(isinstance(row.get("duration_seconds"), (int, float))
                 and row["duration_seconds"] >= 0,
                 "History scenario duration drifted")
    _require(report.get("summary") == {"passed": 8, "failed": 0, "total": 8},
             "History report summary drifted")
    _require(report.get("overall") == "passed", "History report was not admitted")
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    candidate = report.get("candidate") or {}
    _require(candidate.get("size") == manifest.get("expected_size"),
             "History report candidate size drifted")
    _require(candidate.get("sha256") == str(manifest.get("expected_sha256")).upper(),
             "History report candidate SHA256 drifted")
    _require(candidate.get("path") == CANDIDATE_PATH.relative_to(ROOT).as_posix(),
             "History report candidate path drifted")
    _require(report.get("workload") == {
        "call_family": "history",
        "scenario_count": 8,
        "overlay_alias_zh": "History 并发所有权覆盖层",
    }, "History report workload drifted")
    _require(tuple(report.get("limitations") or ()) == LIMITATIONS,
             "History report limitations drifted")
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
             "History report provenance drifted")
    metrics = {row["name"]: row.get("metrics") for row in rows}
    _require(metrics["live_init_job_reset"] == {
        "old_marker_cleared": True,
        "new_generation_admitted": True,
        "distinct_owner": True,
        "captured_workers": 2,
    }, "live-init History evidence drifted")
    _require(metrics["old_background_owner_isolation"] == {
        "new_job_owner_preserved": True,
        "new_cache_owner_preserved": True,
        "compatibility_marker_preserved": True,
    }, "background History owner evidence drifted")
    _require(metrics["old_manual_owner_isolation"] == {
        "new_manual_owner_preserved": True,
        "compatibility_marker_preserved": True,
    }, "manual History owner evidence drifted")
    _require(metrics["duplicate_admission_compatibility"] == {
        "first_admitted": True,
        "duplicate_rejected": True,
        "active_owner_preserved": True,
    }, "History duplicate-admission evidence drifted")
    _require(metrics["submit_failure_owner_isolation"] == {
        "submit_failed": True,
        "replacement_job_owner_preserved": True,
        "replacement_cache_owner_preserved": True,
    }, "History submit-failure evidence drifted")
    _require(metrics["history_sync_lock_serialization"] == {
        "owners": 2, "max_concurrent": 1,
    }, "History sync-lock evidence drifted")
    _require(metrics["event_queue_generation_fence"] == {
        "post_calls": 1,
        "pending_events": 1,
        "attempts_consumed": 0,
        "acknowledged": 0,
    }, "History event-queue evidence drifted")
    _require(metrics["destroy_job_cleanup"] == {
        "compatibility_markers": 0, "owner_entries": 0,
    }, "History destroy evidence drifted")
    return True


def run_history_concurrency():
    global _BOUND_CANDIDATE_BYTES
    candidate = CANDIDATE_PATH.read_bytes()
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    _require(len(candidate) == manifest["expected_size"],
             "candidate size does not match manifest")
    _require(_sha256(candidate) == str(manifest["expected_sha256"]).upper(),
             "candidate SHA256 does not match manifest")
    rows = []
    with _CANDIDATE_RUN_LOCK:
        _require(_BOUND_CANDIDATE_BYTES is None,
                 "candidate evidence run is already active")
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
            "runner": {"path": Path(__file__).relative_to(ROOT).as_posix(),
                       "sha256": _sha256(Path(__file__).read_bytes())},
            "overlay": {"path": OVERLAY_PATH.relative_to(ROOT).as_posix(),
                        "sha256": _sha256(OVERLAY_PATH.read_bytes())},
            "test": {"path": TEST_PATH.relative_to(ROOT).as_posix(),
                     "sha256": _sha256(TEST_PATH.read_bytes())},
        },
        "candidate": {
            "path": CANDIDATE_PATH.relative_to(ROOT).as_posix(),
            "size": len(candidate),
            "sha256": _sha256(candidate),
        },
        "workload": {
            "call_family": "history",
            "scenario_count": len(SCENARIOS),
            "overlay_alias_zh": "History 并发所有权覆盖层",
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
    report = run_history_concurrency()
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report["summary"], ensure_ascii=False, sort_keys=True))
    return 0 if report["overall"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())

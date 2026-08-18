import copy
import importlib.util
import json
import sys
import threading
import types
from functools import lru_cache
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parent.parent
CANDIDATE_PATH = ROOT / "build" / "v80-dev" / "豆瓣TMDB追更单入口.py"
RUNNER_PATH = ROOT / "tests" / "v80_p5_history_concurrency_runner.py"


def _load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RUNNER = _load_module("v80_p5_history_concurrency_runner", RUNNER_PATH)


@lru_cache(maxsize=1)
def _report():
    return RUNNER.run_history_concurrency()


def _load_candidate():
    previous_base = sys.modules.get("base")
    previous_spider = sys.modules.get("base.spider")
    base_module = types.ModuleType("base")
    spider_module = types.ModuleType("base.spider")

    class BaseSpider(object):
        pass

    spider_module.Spider = BaseSpider
    sys.modules["base"] = base_module
    sys.modules["base.spider"] = spider_module
    try:
        payload = CANDIDATE_PATH.read_bytes()
        spec = importlib.util.spec_from_file_location(
            "v80_p5_history_concurrency_candidate", CANDIDATE_PATH,
        )
        module = importlib.util.module_from_spec(spec)
        exec(compile(payload, str(CANDIDATE_PATH), "exec"), module.__dict__)
        return module
    finally:
        if previous_base is None:
            sys.modules.pop("base", None)
        else:
            sys.modules["base"] = previous_base
        if previous_spider is None:
            sys.modules.pop("base.spider", None)
        else:
            sys.modules["base.spider"] = previous_spider


def _config(token):
    return json.dumps({
        "atvp_plugin_mode": "alist-tvbox-raw",
        "atvp_api": "http://127.0.0.1:5000",
        "atvp_token": token,
        "route_preheat": False,
    })


def test_live_init_clears_stale_background_job_and_admits_new_generation(monkeypatch):
    module = _load_candidate()
    spider = module.Spider()
    spider.init(_config("old-token"))
    workers = []
    monkeypatch.setattr(
        spider,
        "_submit_background_bulkhead_task",
        lambda _kind, _generation, worker, _name: workers.append(worker) or True,
    )
    try:
        assert spider._schedule_atvp_history_refresh("history-cache") is True
        old_owner = spider._atvp_job_owners["sync-background"]
        assert spider._atvp_jobs == {"sync-background"}

        spider.init(_config("new-token"))
        assert spider._atvp_jobs == set()
        assert spider._atvp_job_owners == {}
        assert spider._schedule_atvp_history_refresh("history-cache") is True
        new_owner = spider._atvp_job_owners["sync-background"]
        assert new_owner is not old_owner
        assert len(workers) == 2
    finally:
        spider.destroy()


def test_old_background_finally_cannot_release_new_generation_job(monkeypatch):
    module = _load_candidate()
    spider = module.Spider()
    spider.init(_config("old-token"))
    workers = []
    monkeypatch.setattr(
        spider,
        "_submit_background_bulkhead_task",
        lambda _kind, _generation, worker, _name: workers.append(worker) or True,
    )
    try:
        assert spider._schedule_atvp_history_refresh("history-cache") is True
        old_worker = workers[0]
        spider.init(_config("new-token"))
        assert spider._schedule_atvp_history_refresh("history-cache") is True
        new_owner = spider._atvp_job_owners["sync-background"]
        new_cache_owner = spider._refreshing_cache_keys["history-cache"]

        old_worker()

        assert spider._atvp_jobs == {"sync-background"}
        assert spider._atvp_job_owners["sync-background"] is new_owner
        assert spider._refreshing_cache_keys["history-cache"] is new_cache_owner
    finally:
        spider.destroy()


def test_old_manual_worker_cannot_release_new_generation_job(monkeypatch):
    module = _load_candidate()
    spider = module.Spider()
    spider.init(_config("old-token"))
    workers = []
    monkeypatch.setattr(
        spider,
        "_submit_background_bulkhead_task",
        lambda _kind, _generation, worker, _name: workers.append(worker) or True,
    )
    try:
        assert "已开始" in json.loads(spider._start_atvp_job("probe"))["msg"]
        old_worker = workers[0]
        old_owner = spider._atvp_job_owners["probe"]
        spider.init(_config("new-token"))
        assert "已开始" in json.loads(spider._start_atvp_job("probe"))["msg"]
        new_owner = spider._atvp_job_owners["probe"]
        assert new_owner is not old_owner

        old_worker()

        assert spider._atvp_jobs == {"probe"}
        assert spider._atvp_job_owners["probe"] is new_owner
    finally:
        spider.destroy()


def test_background_submit_exception_does_not_clear_replacement_owner(monkeypatch):
    module = _load_candidate()
    spider = module.Spider()
    spider.init(_config("token"))
    replacement_job_owner = object()
    replacement_cache_owner = object()

    def replace_then_fail(_kind, _generation, _worker, _name):
        with spider._atvp_job_lock:
            spider._atvp_job_owners["sync-background"] = replacement_job_owner
            spider._atvp_jobs.add("sync-background")
            spider._set_atvp_status(
                "sync", "running", "replacement background running", persist=False,
            )
        with spider._cache_lock:
            spider._refreshing_cache_keys["history-cache"] = replacement_cache_owner
        raise RuntimeError("submit failed")

    monkeypatch.setattr(spider, "_submit_background_bulkhead_task", replace_then_fail)
    try:
        assert spider._schedule_atvp_history_refresh("history-cache") is False
        assert spider._atvp_job_owners["sync-background"] is replacement_job_owner
        assert spider._atvp_jobs == {"sync-background"}
        assert spider._refreshing_cache_keys["history-cache"] is replacement_cache_owner
        assert spider._atvp_status["sync"] == {
            "state": "running",
            "message": "replacement background running",
            "updated_at": spider._atvp_status["sync"]["updated_at"],
        }
    finally:
        spider.destroy()


def test_background_busy_does_not_clear_or_fail_replacement_owner(monkeypatch):
    module = _load_candidate()
    spider = module.Spider()
    spider.init(_config("token"))
    replacement_job_owner = object()
    replacement_cache_owner = object()

    def replace_then_report_busy(_kind, _generation, _worker, _name):
        with spider._atvp_job_lock:
            spider._atvp_job_owners["sync-background"] = replacement_job_owner
            spider._atvp_jobs.add("sync-background")
            spider._set_atvp_status(
                "sync", "running", "replacement background running", persist=False,
            )
        with spider._cache_lock:
            spider._refreshing_cache_keys["history-cache"] = replacement_cache_owner
        return False

    monkeypatch.setattr(
        spider, "_submit_background_bulkhead_task", replace_then_report_busy,
    )
    try:
        assert spider._schedule_atvp_history_refresh("history-cache") is False
        assert spider._atvp_job_owners["sync-background"] is replacement_job_owner
        assert spider._atvp_jobs == {"sync-background"}
        assert spider._refreshing_cache_keys["history-cache"] is replacement_cache_owner
        assert spider._atvp_status["sync"]["state"] == "running"
        assert spider._atvp_status["sync"]["message"] == (
            "replacement background running"
        )
    finally:
        spider.destroy()


def test_manual_submit_exception_does_not_clear_replacement_owner(monkeypatch):
    module = _load_candidate()
    spider = module.Spider()
    spider.init(_config("token"))
    replacement_owner = object()

    def replace_then_fail(_kind, _generation, _worker, _name):
        with spider._atvp_job_lock:
            spider._atvp_job_owners["probe"] = replacement_owner
            spider._atvp_jobs.add("probe")
            spider._set_atvp_status(
                "probe", "running", "replacement manual running", persist=False,
            )
        raise RuntimeError("submit failed")

    monkeypatch.setattr(spider, "_submit_background_bulkhead_task", replace_then_fail)
    try:
        assert "启动失败" in json.loads(spider._start_atvp_job("probe"))["msg"]
        assert spider._atvp_job_owners["probe"] is replacement_owner
        assert spider._atvp_jobs == {"probe"}
        assert spider._atvp_status["probe"]["state"] == "running"
        assert spider._atvp_status["probe"]["message"] == "replacement manual running"
    finally:
        spider.destroy()


def test_manual_busy_does_not_clear_or_fail_replacement_owner(monkeypatch):
    module = _load_candidate()
    spider = module.Spider()
    spider.init(_config("token"))
    replacement_owner = object()

    def replace_then_report_busy(_kind, _generation, _worker, _name):
        with spider._atvp_job_lock:
            spider._atvp_job_owners["probe"] = replacement_owner
            spider._atvp_jobs.add("probe")
            spider._set_atvp_status(
                "probe", "running", "replacement manual running", persist=False,
            )
        return False

    monkeypatch.setattr(
        spider, "_submit_background_bulkhead_task", replace_then_report_busy,
    )
    try:
        assert "任务繁忙" in json.loads(spider._start_atvp_job("probe"))["msg"]
        assert spider._atvp_job_owners["probe"] is replacement_owner
        assert spider._atvp_jobs == {"probe"}
        assert spider._atvp_status["probe"]["state"] == "running"
        assert spider._atvp_status["probe"]["message"] == "replacement manual running"
    finally:
        spider.destroy()


def test_old_manual_worker_cannot_refresh_after_new_generation_init(monkeypatch):
    module = _load_candidate()
    spider = module.Spider()
    spider.init(_config("old-token"))
    workers = []
    monkeypatch.setattr(
        spider,
        "_submit_background_bulkhead_task",
        lambda _kind, _generation, worker, _name: workers.append(worker) or True,
    )
    assert "已开始" in json.loads(spider._start_atvp_job("probe"))["msg"]

    old_generation = spider._cache_generation
    original_generation_active = spider._history_generation_active
    final_check_entered = threading.Event()
    release_final_check = threading.Event()
    init_started = threading.Event()
    init_done = threading.Event()
    refresh_after_init = []
    active_checks = {"count": 0}

    def gated_generation_active(generation):
        result = original_generation_active(generation)
        if generation == old_generation:
            active_checks["count"] += 1
            if active_checks["count"] == 4:
                final_check_entered.set()
                release_final_check.wait(5.0)
        return result

    def run_init():
        init_started.set()
        spider.init(_config("new-token"))
        init_done.set()

    monkeypatch.setattr(spider, "_history_generation_active", gated_generation_active)
    monkeypatch.setattr(
        spider, "_atvp_probe_history", lambda: json.dumps({"ok": True, "msg": "ok"}),
    )
    monkeypatch.setattr(
        spider,
        "_refresh_current_category",
        lambda: refresh_after_init.append(True) if init_done.is_set() else None,
    )
    worker_thread = threading.Thread(target=workers[0])
    init_thread = threading.Thread(target=run_init)
    try:
        worker_thread.start()
        assert final_check_entered.wait(3.0)
        init_thread.start()
        assert init_started.wait(1.0)
        init_done.wait(1.0)
        release_final_check.set()
        worker_thread.join(5.0)
        init_thread.join(5.0)
        assert not worker_thread.is_alive()
        assert not init_thread.is_alive()
        assert init_done.is_set()
        assert refresh_after_init == []
    finally:
        release_final_check.set()
        if worker_thread.is_alive():
            worker_thread.join(5.0)
        if init_thread.is_alive():
            init_thread.join(5.0)
        spider.destroy()


def test_destroy_clears_history_job_compatibility_and_owner_state(monkeypatch):
    module = _load_candidate()
    spider = module.Spider()
    spider.init(_config("token"))
    monkeypatch.setattr(
        spider, "_submit_background_bulkhead_task",
        lambda *_args, **_kwargs: True,
    )
    assert spider._schedule_atvp_history_refresh("history-cache") is True
    assert spider._atvp_jobs
    assert spider._atvp_job_owners

    spider.destroy()

    assert spider._atvp_jobs == set()
    assert spider._atvp_job_owners == {}


def test_formal_history_concurrency_report_is_admitted():
    report = _report()
    assert RUNNER.validate_report(report) is True
    assert report["summary"] == {"passed": 8, "failed": 0, "total": 8}
    assert report["workload"] == {
        "call_family": "history",
        "scenario_count": 8,
        "overlay_alias_zh": "History 并发所有权覆盖层",
    }


def test_history_report_separates_modified_and_observed_contracts():
    report = _report()
    rows = {row["name"]: row for row in report["scenario_results"]}
    assert rows["old_background_owner_isolation"]["metrics"][
        "new_job_owner_preserved"
    ] is True
    assert rows["old_manual_owner_isolation"]["metrics"][
        "new_manual_owner_preserved"
    ] is True
    assert rows["history_sync_lock_serialization"]["metrics"] == {
        "owners": 2,
        "max_concurrent": 1,
    }
    assert rows["event_queue_generation_fence"]["metrics"] == {
        "post_calls": 1,
        "pending_events": 1,
        "attempts_consumed": 0,
        "acknowledged": 0,
    }
    assert "history_sync_lock_and_event_queue_are_independent_observations" in (
        report["limitations"]
    )


def test_formal_history_run_reuses_startup_candidate_bytes(monkeypatch):
    original_path = RUNNER.CANDIDATE_PATH
    initial = original_path.read_bytes()

    class CandidatePathFixture(object):
        def __init__(self):
            self.payload = initial

        def read_bytes(self):
            return self.payload

        def relative_to(self, _root):
            return Path("build/v80-dev/豆瓣TMDB追更单入口.py")

        def __str__(self):
            return str(original_path)

    candidate_path = CandidatePathFixture()
    loaded = []

    def load_bound(_name, _path, payload=None):
        loaded.append(payload)
        return object()

    def scenario():
        RUNNER._load_candidate("history_binding_probe_%d" % len(loaded))
        candidate_path.payload = b"replacement-candidate-bytes"
        return {}

    monkeypatch.setattr(RUNNER, "CANDIDATE_PATH", candidate_path)
    monkeypatch.setattr(RUNNER, "_load", load_bound)
    monkeypatch.setattr(
        RUNNER, "SCENARIO_FUNCTIONS", {name: scenario for name in RUNNER.SCENARIOS},
    )
    monkeypatch.setattr(RUNNER, "validate_report", lambda _report: True)

    report = RUNNER.run_history_concurrency()

    assert report["overall"] == "passed"
    assert len(loaded) == len(RUNNER.SCENARIOS)
    assert all(payload == initial for payload in loaded)
    assert RUNNER._BOUND_CANDIDATE_BYTES is None


@pytest.mark.parametrize(
    "field",
    ("schema", "candidate", "scenario", "summary", "limitations", "metrics"),
)
def test_history_report_rejects_tampered_evidence(field):
    report = copy.deepcopy(_report())
    if field == "schema":
        report["schema"] = "evil"
    elif field == "candidate":
        report["candidate"]["sha256"] = "0" * 64
    elif field == "scenario":
        report["scenario_results"][0]["status"] = "failed"
    elif field == "summary":
        report["summary"]["passed"] = 7
    elif field == "limitations":
        report["limitations"].append("unbounded-claim")
    else:
        report["scenario_results"][6]["metrics"]["acknowledged"] = 1
    with pytest.raises(RUNNER.HistoryConcurrencyAssertionError):
        RUNNER.validate_report(report)

"""Evidence runner for the V80 search-call-family concurrency boundary.

The runner builds one fixed candidate, executes that exact byte stream once,
and exercises its real search admission, owner, generation, response,
bulkhead, and destroy paths without network or production access.
"""

import argparse
import datetime as dt
import hashlib
import importlib.util
import json
import math
import threading
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
P5A_RUNNER_PATH = ROOT / "tests" / "v80_p5_lifecycle_stability_runner.py"
TEST_PATH = ROOT / "tests" / "test_v80_p5_search_concurrency.py"
BUILD_PATH = ROOT / "tools" / "build_follow_plugin.py"
RUNTIME_OVERLAY_PATH = ROOT / "tools" / "build_v80_search_concurrency_ownership_overlay.py"
MANIFEST_PATH = ROOT / "src" / "douban_tmdb_follow_single" / "release.json"
DEFAULT_REPORT = ROOT / "work" / "v80-p5-search-concurrency.json"
REPORT_SCHEMA = "v80-p5-search-concurrency/3"
SCENARIOS = (
    "foreground_capacity",
    "queued_cancellation",
    "job_owner",
    "generation_writeback",
    "response_close",
    "resource_completion_isolation",
    "destroy_race",
)
SCENARIO_LABELS_ZH = {
    "foreground_capacity": "前台搜索容量边界",
    "queued_cancellation": "排队取消即时释放准入",
    "job_owner": "搜索任务所有权与单次释放",
    "generation_writeback": "真实生命周期旧代次阻断",
    "response_close": "真实搜索响应所有者单次关闭",
    "resource_completion_isolation": "资源补全舱壁隔离",
    "destroy_race": "实例执行器销毁与隔离",
}
LIMITATIONS = (
    "candidate_bound_search_call_family_only",
    "fake_session_and_forbidden_network_surfaces",
    "no_real_network_or_device_latency",
    "playback_and_history_concurrency_are_separate_packages",
    "host_waits_are_observational_not_slo_admission",
    "report_freshness_requires_external_sha256_and_stage_closure",
)
TOP_LEVEL_KEYS = {
    "schema", "generated_at", "evidence_provenance", "candidate",
    "candidate_closure", "workload", "limitations", "scenario_results",
    "summary", "invariants", "isolation", "cleanup", "failure", "overall",
}


class SearchConcurrencyAssertionError(AssertionError):
    pass


def _require(condition, detail):
    if not condition:
        raise SearchConcurrencyAssertionError(detail)


def _sha256_bytes(payload):
    return hashlib.sha256(payload).hexdigest().upper()


def _file_sha256(path):
    return _sha256_bytes(Path(path).read_bytes())


def _load(name, path):
    path = Path(path)
    payload = path.read_bytes()
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load required evidence module")
    module = importlib.util.module_from_spec(spec)
    module.__dict__["__loaded_source_sha256__"] = _sha256_bytes(payload)
    exec(compile(payload, str(path), "exec"), module.__dict__)
    return module


_RUNNER_LOADED_SHA256 = globals().get("__loaded_source_sha256__")
if __name__ == "__main__" and _RUNNER_LOADED_SHA256 is None:
    _BOOTSTRAPPED = _load("v80_p5_search_concurrency_main", Path(__file__).resolve())
    raise SystemExit(_BOOTSTRAPPED.main())


P5A = _load("v80_p5_search_concurrency_lifecycle", P5A_RUNNER_PATH)
BUILD = P5A.BUILD
_BUILD_LOADED_SHA256 = _file_sha256(BUILD_PATH)
_TEST_LOADED_SHA256 = _file_sha256(TEST_PATH)
_RUNTIME_OVERLAY_LOADED_SHA256 = _file_sha256(RUNTIME_OVERLAY_PATH)
_MANIFEST_LOADED_SHA256 = _file_sha256(MANIFEST_PATH)
_MANIFEST = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
EXPECTED_CANDIDATE = {
    "size": _MANIFEST["expected_size"],
    "sha256": str(_MANIFEST["expected_sha256"]).upper(),
    "output": str(_MANIFEST["output"]).replace("\\", "/"),
}
REFERENCE_NAMES = tuple(P5A.REFERENCE_FIELDS + P5A.REFERENCE_SCALAR_FIELDS)
EXECUTOR_FIELDS = (
    "_resource_search_executor",
    "_follow_refresh_executor",
    "_resource_foreground_mode_executor",
    "_resource_background_mode_executor",
    "_dns_executor",
    "_media_probe_executor",
)
SLOT_FIELDS = (
    "_resource_foreground_mode_slots",
    "_resource_background_mode_slots",
    "_dns_slots",
    "_media_probe_slots",
)


def _loaded_inputs_are_current():
    if not isinstance(_RUNNER_LOADED_SHA256, str):
        return False
    try:
        return (
            _file_sha256(__file__) == _RUNNER_LOADED_SHA256
            and _file_sha256(P5A_RUNNER_PATH) == P5A.__loaded_source_sha256__
            and _file_sha256(TEST_PATH) == _TEST_LOADED_SHA256
            and _file_sha256(BUILD_PATH) == _BUILD_LOADED_SHA256
            and _file_sha256(RUNTIME_OVERLAY_PATH) == _RUNTIME_OVERLAY_LOADED_SHA256
            and _file_sha256(MANIFEST_PATH) == _MANIFEST_LOADED_SHA256
        )
    except OSError:
        return False


def _file_provenance(path):
    path = Path(path).resolve()
    payload = path.read_bytes()
    return {
        "path": str(path.relative_to(ROOT)).replace("\\", "/"),
        "size": len(payload),
        "sha256": _sha256_bytes(payload),
    }


def _evidence_provenance():
    return {
        "runner": _file_provenance(__file__),
        "test": _file_provenance(TEST_PATH),
        "runtime_overlay": _file_provenance(RUNTIME_OVERLAY_PATH),
        "lifecycle_runner": _file_provenance(P5A_RUNNER_PATH),
        "build_tool": _file_provenance(BUILD_PATH),
        "release": _file_provenance(MANIFEST_PATH),
    }


EXPECTED_EVIDENCE_PROVENANCE = _evidence_provenance()


def _provenance_snapshot():
    return dict((name, dict(value)) for name, value in EXPECTED_EVIDENCE_PROVENANCE.items())


def _candidate_evidence_from(build):
    return {
        "size": build["size"],
        "sha256": build["sha256"],
        "output": str(build["output"].relative_to(ROOT)).replace("\\", "/"),
    }


def _executed_build():
    return BUILD.build_release(MANIFEST_PATH)


def _candidate_state_sha256(output_path):
    paths = {
        Path(output_path), MANIFEST_PATH, Path(__file__), TEST_PATH,
        RUNTIME_OVERLAY_PATH, P5A_RUNNER_PATH, BUILD_PATH,
    }
    digest = hashlib.sha256()
    for path in sorted(paths, key=lambda item: str(item).lower()):
        digest.update(str(path.relative_to(ROOT)).replace("\\", "/").encode("utf-8"))
        digest.update(b"\0")
        digest.update(_file_sha256(path).encode("ascii") if path.exists() else b"missing")
        digest.update(b"\0")
    return digest.hexdigest().upper()


def _output_evidence(path):
    return _candidate_evidence_from({
        "size": Path(path).stat().st_size,
        "sha256": _file_sha256(path),
        "output": Path(path),
    })


def _candidate_closure(executed, state_before):
    output = _output_evidence(executed["output"])
    state_after = _candidate_state_sha256(executed["output"])
    executed_evidence = _candidate_evidence_from(executed)
    return {
        "executed": executed_evidence,
        "output": output,
        "state_before_sha256": state_before,
        "state_after_sha256": state_after,
        "stable_after_samples": (
            _loaded_inputs_are_current()
            and state_before == state_after
            and executed_evidence == output
        ),
    }


def _runtime_module(observer, executed):
    original = P5A._build_result
    try:
        P5A._build_result = lambda: executed
        return P5A._runtime_module(observer)
    finally:
        P5A._build_result = original


class ResponseFixture(object):
    def __init__(self, body, observer, read_started=None, read_release=None):
        self.headers = {"Content-Length": str(len(body))}
        self.status_code = 200
        self._body = bytes(body)
        self.close_calls = 0
        self.observer = observer
        self.read_started = read_started
        self.read_release = read_release

    def iter_content(self, chunk_size=65536):
        del chunk_size
        if self.read_started is not None:
            self.read_started.set()
        if self.read_release is not None:
            _require(
                self.read_release.wait(5.0),
                "response fixture read release timed out",
            )
        yield self._body

    def close(self):
        self.close_calls += 1
        self.observer["closed"] += 1


class ResourceSessionFixture(object):
    def __init__(self, response, request_observer=None):
        self.response = response
        self.get_calls = 0
        self.close_calls = 0
        self.request_observer = request_observer
        self.request_observations = []

    def get(self, *_args, **_kwargs):
        self.get_calls += 1
        if callable(self.request_observer):
            self.request_observations.append(dict(self.request_observer()))
        return self.response

    def close(self):
        self.close_calls += 1


class ReliabilityLeaseFixture(object):
    def __init__(self):
        self.finishes = []

    def finish(self, **kwargs):
        self.finishes.append(dict(kwargs))
        return True


class ReliabilityControllerFixture(object):
    def __init__(self, lease):
        self.lease = lease
        self.acquire_calls = 0

    def acquire(self, *_args, **_kwargs):
        self.acquire_calls += 1
        return self.lease


class CountingSlotFixture(object):
    """Observe one real mode admission without replacing semaphore behavior."""

    def __init__(self, delegate):
        self.delegate = delegate
        self.acquire_attempts = 0
        self.acquire_successes = 0
        self.release_calls = 0
        self._lock = threading.Lock()

    def acquire(self, *args, **kwargs):
        with self._lock:
            self.acquire_attempts += 1
        admitted = self.delegate.acquire(*args, **kwargs)
        if admitted:
            with self._lock:
                self.acquire_successes += 1
        return admitted

    def release(self):
        with self._lock:
            self.release_calls += 1
        return self.delegate.release()


def _wait_for(predicate, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return bool(predicate())


def _task_counts(tasks):
    with tasks._lock:
        return {
            "threads": len(tasks._threads),
            "timers": len(tasks._timers),
            "executors": len(tasks._executors),
        }


def _executor_list(spider):
    return tuple(getattr(spider, name) for name in EXECUTOR_FIELDS)


def _slot_list(spider):
    return tuple(getattr(spider, name) for name in SLOT_FIELDS)


def _executor_worker_threads(executors):
    threads = set()
    for executor in executors:
        threads.update(getattr(executor, "_threads", ()))
    return threads


def _zero_reference_counts_are_admitted(value):
    return (
        isinstance(value, dict)
        and set(value) == set(REFERENCE_NAMES)
        and all(type(value[name]) is int and value[name] == 0 for name in REFERENCE_NAMES)
    )


def _restore_attributes(target, originals):
    for name, value in originals.items():
        setattr(target, name, value)


def _scenario_row(name, metrics):
    return {
        "name": name,
        "label_zh": SCENARIO_LABELS_ZH[name],
        "status": "passed",
        "metrics": dict(metrics),
    }


def _run_foreground_capacity(spider):
    release = threading.Event()
    started = threading.Event()
    lock = threading.Lock()
    state = {"active": 0, "peak": 0, "completed": 0, "deadlines": []}
    original = spider._resource_search_mode
    futures = []
    replacement = None
    blocked_at_rejection = False

    def search(mode, queries, deadline=None, expected_generation=None):
        del queries, expected_generation
        with lock:
            state["active"] += 1
            state["peak"] = max(state["peak"], state["active"])
            state["deadlines"].append(deadline)
            if state["active"] == spider.RESOURCE_FOREGROUND_MODE_WORKERS:
                started.set()
        try:
            _require(deadline is not None and deadline > time.monotonic(), "foreground deadline expired at admission")
            _require(release.wait(5.0), "foreground worker release timed out")
            return [{"vod_id": str(mode), "vod_name": "测试搜索"}]
        finally:
            with lock:
                state["active"] -= 1
                state["completed"] += 1

    spider._resource_search_mode = search
    count = spider.RESOURCE_FOREGROUND_MODE_WORKERS + spider.RESOURCE_FOREGROUND_MODE_QUEUE_LIMIT
    try:
        futures = [
            spider._submit_resource_mode_search(
                "foreground-%d" % index, ["测试剧集"], time.monotonic() + 5.0,
            )
            for index in range(count)
        ]
        _require(all(future is not None for future in futures), "foreground queue admission was lost")
        _require(started.wait(1.0), "foreground worker pool did not reach capacity")
        rejected = spider._submit_resource_mode_search(
            "foreground-capacity-plus-one", ["测试剧集"], time.monotonic() + 0.05,
        )
        with lock:
            blocked_at_rejection = state["active"] == spider.RESOURCE_FOREGROUND_MODE_WORKERS
        _require(rejected is None, "foreground capacity plus one was admitted")
        _require(blocked_at_rejection, "foreground workers released before capacity rejection")
        release.set()
        for future in futures:
            future.result(timeout=5.0)
        replacement = spider._submit_resource_mode_search(
            "foreground-replacement", ["测试剧集"], time.monotonic() + 2.0,
        )
        _require(replacement is not None, "foreground admission was not released")
        replacement.result(timeout=2.0)
    finally:
        release.set()
        for future in futures:
            if future is not None and not future.done():
                future.cancel()
        spider._resource_search_mode = original
    return _scenario_row("foreground_capacity", {
        "submitted": count,
        "completed": state["completed"],
        "active_peak": state["peak"],
        "max_workers": spider.RESOURCE_FOREGROUND_MODE_WORKERS,
        "queue_limit": spider.RESOURCE_FOREGROUND_MODE_QUEUE_LIMIT,
        "capacity_plus_one_rejected": True,
        "rejected_while_workers_blocked": blocked_at_rejection,
        "replacement_admitted_after_release": replacement is not None,
        "finite_deadlines": all(
            type(value) in (int, float) and math.isfinite(float(value))
            for value in state["deadlines"]
        ),
    })


def _run_queued_cancellation(spider):
    release = threading.Event()
    started = threading.Event()
    lock = threading.Lock()
    state = {"active": 0, "completed": 0}
    original = spider._resource_search_mode
    workers = []
    queued = []
    replacement = None
    workers_still_blocked = False

    def search(mode, queries, deadline=None, expected_generation=None):
        del queries, deadline, expected_generation
        with lock:
            state["active"] += 1
            if state["active"] == spider.RESOURCE_FOREGROUND_MODE_WORKERS:
                started.set()
        try:
            _require(release.wait(5.0), "cancel scenario release timed out")
            return [mode]
        finally:
            with lock:
                state["active"] -= 1
                state["completed"] += 1

    spider._resource_search_mode = search
    try:
        workers = [
            spider._submit_resource_mode_search(
                "running-%d" % index, ["测试剧集"], time.monotonic() + 5.0,
            )
            for index in range(spider.RESOURCE_FOREGROUND_MODE_WORKERS)
        ]
        _require(all(future is not None for future in workers), "cancel running admission failed")
        _require(started.wait(1.0), "cancel scenario did not saturate foreground workers")
        queued = [
            spider._submit_resource_mode_search(
                "queued-%d" % index, ["测试剧集"], time.monotonic() + 5.0,
            )
            for index in range(spider.RESOURCE_FOREGROUND_MODE_QUEUE_LIMIT)
        ]
        _require(all(future is not None for future in queued), "cancel scenario queue admission failed")
        cancelled = queued[-1].cancel()
        _require(cancelled, "queued future could not be cancelled before execution")
        replacement = spider._submit_resource_mode_search(
            "replacement-before-release", ["测试剧集"], time.monotonic() + 1.0,
        )
        with lock:
            workers_still_blocked = state["active"] == spider.RESOURCE_FOREGROUND_MODE_WORKERS
        _require(replacement is not None, "cancelled queue slot was not released immediately")
        _require(workers_still_blocked, "replacement was admitted only after workers released")
        release.set()
        for future in workers + queued[:-1] + [replacement]:
            future.result(timeout=5.0)
    finally:
        release.set()
        for future in workers + queued + ([replacement] if replacement is not None else []):
            if future is not None and not future.done():
                future.cancel()
        spider._resource_search_mode = original
    return _scenario_row("queued_cancellation", {
        "running": len(workers),
        "queued": len(queued),
        "cancelled": True,
        "replacement_admitted_before_release": replacement is not None,
        "workers_blocked_during_replacement": workers_still_blocked,
        "completed": state["completed"],
    })


def _run_job_owner(spider):
    publish_seam = threading.Event()
    release = threading.Event()
    candidate_seam = threading.Event()
    release_candidate = threading.Event()
    cache_key = "p5-5d-owner-test"
    rejected_key = "p5-5d-owner-submit-rejected"
    originals = dict(
        (name, getattr(spider, name))
        for name in (
            "_resource_search_mode", "_checked_resource_rows",
            "_resource_fair_candidate_order", "_playable_resource_rows",
            "_validated_resource_group_count", "_cache_set",
            "_schedule_active_detail_refresh", "_submit_background_bulkhead_task",
            "_available_resource_modes", "_cache_get",
            "_schedule_supplement_resource_search",
        )
    )
    duplicate = None
    duplicate_owner_preserved = False
    duplicate_refresh_owner_preserved = False
    owner = None
    submit_rejected = None
    owner_released = False
    refresh_owner_released = False
    rejected_owner_cleared = False
    rejected_refresh_owner_cleared = False
    candidate_future = None
    candidate_result = None
    candidate_scheduler_calls = []
    candidate_job_registered = False
    candidate_refresh_registered = False
    candidate_old_generation = spider._cache_generation
    candidate_new_generation = candidate_old_generation

    def search(mode, queries, deadline=None, expected_generation=None):
        del queries, deadline, expected_generation
        return [{"vod_id": str(mode), "_resource_mode": str(mode)}]

    def playable(rows, _item, *_args, **_kwargs):
        publish_seam.set()
        _require(release.wait(5.0), "job owner release timed out")
        return list(rows)

    spider._resource_search_mode = search
    spider._checked_resource_rows = lambda rows, _deadline=None: list(rows)
    spider._resource_fair_candidate_order = lambda rows, *_args, **_kwargs: list(rows)
    spider._playable_resource_rows = playable
    spider._validated_resource_group_count = lambda _rows: 0
    spider._cache_set = lambda *_args, **_kwargs: None
    spider._schedule_active_detail_refresh = lambda *_args, **_kwargs: None
    try:
        _require(
            spider._schedule_supplement_resource_search(
                ["owner-primary"], ["测试剧集"],
                {"title": "测试剧集"}, cache_key,
            ),
            "primary owner job was not admitted",
        )
        _require(publish_seam.wait(2.0), "primary owner did not reach publish seam")
        with spider._cache_lock:
            owner = spider._resource_search_jobs.get(cache_key)
            refresh_owner = spider._refreshing_cache_keys.get(cache_key)
        _require(owner is not None, "primary owner identity was not retained")
        _require(refresh_owner is owner, "primary refresh owner identity drifted")
        duplicate = spider._schedule_supplement_resource_search(
            ["owner-duplicate"], ["测试剧集"],
            {"title": "测试剧集"}, cache_key,
        )
        with spider._cache_lock:
            duplicate_owner_preserved = spider._resource_search_jobs.get(cache_key) is owner
            duplicate_refresh_owner_preserved = spider._refreshing_cache_keys.get(cache_key) is owner
        _require(duplicate is False, "same-key duplicate job was admitted")
        _require(
            duplicate_owner_preserved and duplicate_refresh_owner_preserved,
            "duplicate changed the active owner identity",
        )
        release.set()
        _require(
            _wait_for(
                lambda: cache_key not in spider._resource_search_jobs
                and cache_key not in spider._refreshing_cache_keys,
                3.0,
            ),
            "primary owner was not released after completion",
        )
        with spider._cache_lock:
            owner_released = cache_key not in spider._resource_search_jobs
            refresh_owner_released = cache_key not in spider._refreshing_cache_keys

        spider._submit_background_bulkhead_task = lambda *_args, **_kwargs: False
        submit_rejected = spider._schedule_supplement_resource_search(
            ["owner-submit-rejected"], ["测试剧集"],
            {"title": "测试剧集"}, rejected_key,
        )
        with spider._cache_lock:
            rejected_owner_cleared = rejected_key not in spider._resource_search_jobs
            rejected_refresh_owner_cleared = rejected_key not in spider._refreshing_cache_keys
        _require(submit_rejected is False, "executor submit rejection was reported as admitted")
        _require(
            rejected_owner_cleared and rejected_refresh_owner_cleared,
            "executor submit rejection retained a job owner",
        )

        spider._submit_background_bulkhead_task = originals["_submit_background_bulkhead_task"]
        candidate_item = {"title": "候选代次竞态", "tmdb_id": "p5-5d-candidate-race"}
        candidate_cache_key = spider._resource_search_cache_key(
            candidate_item, "supplement",
        )
        cached_rows = [{
            "vod_id": "https://fixture.invalid/cached",
            "vod_name": "旧代缓存",
            "_resource_mode": "pansou",
        }]
        original_schedule = originals["_schedule_supplement_resource_search"]

        def candidate_group_count(rows):
            if rows is cached_rows:
                candidate_seam.set()
                _require(
                    release_candidate.wait(5.0),
                    "resource candidate generation seam release timed out",
                )
            return 0

        def observe_schedule(*args, **kwargs):
            candidate_scheduler_calls.append({
                "expected_generation": kwargs.get("expected_generation"),
            })
            return original_schedule(*args, **kwargs)

        spider._available_resource_modes = lambda: ["pansou"]
        spider._cache_get = lambda key, *_args, **_kwargs: (
            cached_rows if key == candidate_cache_key else None
        )
        spider._validated_resource_group_count = candidate_group_count
        spider._schedule_supplement_resource_search = observe_schedule
        candidate_old_generation = spider._cache_generation
        candidate_future = spider._resource_search_executor.submit(
            lambda: spider._resource_candidates(
                candidate_item,
                deadline=time.monotonic() + 5.0,
                expected_generation=candidate_old_generation,
            )
        )
        _require(
            candidate_seam.wait(2.0),
            "resource candidates did not reach the supplement registration seam",
        )
        spider.init({})
        candidate_new_generation = spider._cache_generation
        _require(
            candidate_new_generation == candidate_old_generation + 1,
            "resource candidate race did not use a real init rollover",
        )
        release_candidate.set()
        candidate_result = candidate_future.result(timeout=5.0)
        with spider._cache_lock:
            candidate_job_registered = candidate_cache_key in spider._resource_search_jobs
            candidate_refresh_registered = candidate_cache_key in spider._refreshing_cache_keys
        _require(candidate_result == [], "old resource candidates survived the init generation fence")
        _require(
            len(candidate_scheduler_calls) == 1
            and candidate_scheduler_calls[0]["expected_generation"] == candidate_old_generation,
            "resource candidates did not propagate the captured generation to supplement scheduling",
        )
        _require(
            not candidate_job_registered and not candidate_refresh_registered,
            "old resource candidates registered a new-generation supplement owner",
        )
    finally:
        release.set()
        release_candidate.set()
        if candidate_future is not None and not candidate_future.done():
            candidate_future.cancel()
        _wait_for(
            lambda: cache_key not in spider._resource_search_jobs
            and cache_key not in spider._refreshing_cache_keys,
            3.0,
        )
        _restore_attributes(spider, originals)
    return _scenario_row("job_owner", {
        "duplicate_rejected": duplicate is False,
        "duplicate_owner_preserved": duplicate_owner_preserved,
        "duplicate_refresh_owner_preserved": duplicate_refresh_owner_preserved,
        "owner_identity_observed": owner is not None,
        "owner_released_after_completion": owner_released,
        "refresh_owner_released_after_completion": refresh_owner_released,
        "submit_rejection_reported": submit_rejected is False,
        "submit_rejection_owner_cleared": rejected_owner_cleared,
        "submit_rejection_refresh_owner_cleared": rejected_refresh_owner_cleared,
        "candidate_lifecycle_path": "Spider.init",
        "candidate_old_generation": candidate_old_generation,
        "candidate_new_generation": candidate_new_generation,
        "candidate_scheduler_calls": len(candidate_scheduler_calls),
        "candidate_scheduler_received_old_generation": (
            len(candidate_scheduler_calls) == 1
            and candidate_scheduler_calls[0]["expected_generation"] == candidate_old_generation
        ),
        "candidate_result_rows": len(candidate_result or []),
        "candidate_job_registered_after_init": candidate_job_registered,
        "candidate_refresh_registered_after_init": candidate_refresh_registered,
    })


def _run_generation_writeback(spider, observer):
    publish_seam = threading.Event()
    release_publish = threading.Event()
    response_read_started = threading.Event()
    release_response = threading.Event()
    release_old_executors = threading.Event()
    state_lock = threading.Lock()
    started = dict((name, threading.Event()) for name in (
        "foreground", "background", "dns", "media",
    ))
    state = dict(("%s_blockers" % name, 0) for name in started)
    state.update({"partial_attempts": 0, "final_seam_reached": False})
    writes = []
    refreshes = []
    endpoint_observations = []
    close_state = {"closed": 0}
    response = ResponseFixture(
        b'{"list": []}', close_state,
        read_started=response_read_started,
        read_release=release_response,
    )
    lease = ReliabilityLeaseFixture()
    controller = ReliabilityControllerFixture(lease)
    cache_key = "p5-5d-generation-test"
    old_token = "p5-5d-old-fixture-token"
    new_token = "p5-5d-new-fixture-token"
    old_session = None
    new_session = None
    init_completed = False
    owner_before_init = None
    owner_cleared_by_init = False
    old_executors = _executor_list(spider)
    old_slots = _slot_list(spider)
    old_supervisor = spider._tasks
    foreground_slots = CountingSlotFixture(spider._resource_foreground_mode_slots)
    background_slots = CountingSlotFixture(spider._resource_background_mode_slots)
    spider._resource_foreground_mode_slots = foreground_slots
    spider._resource_background_mode_slots = background_slots
    blocker_futures = []
    api_future = None
    queued_mode_futures = []
    queued_fenced = 0
    queued_cancelled = 0
    queued_empty = 0
    api_result = None
    new_executors = ()
    new_slots = ()
    new_executor_probe_count = 0
    new_slot_probe_count = 0
    old_executors_closed = 0
    old_workers_alive_after_release = -1
    observer_requests_before = observer.snapshot()["request_attempts"]
    observer_request_delta = -1
    originals = dict(
        (name, getattr(spider, name))
        for name in (
            "_checked_resource_rows", "_resource_fair_candidate_order",
            "_playable_resource_rows", "_validated_resource_group_count",
            "_cache_set", "_schedule_active_detail_refresh",
            "_resource_capability", "_ensure_atvp_connection",
            "_resource_capability_identity", "_atvp_endpoint",
            "_provider_reliability_for", "_mark_resource_capability",
        )
    )

    def request_observation():
        return {
            "old_token": spider.atvp_token == old_token,
            "old_session": spider._atvp_session is old_session,
        }

    old_session = ResourceSessionFixture(
        response, request_observer=request_observation,
    )

    def endpoint(mode):
        endpoint_observations.append({
            "old_token": spider.atvp_token == old_token,
            "old_session": spider._atvp_session is old_session,
        })
        return "https://fixture.invalid/%s" % mode

    def block_executor(name, expected):
        key = "%s_blockers" % name
        with state_lock:
            state[key] += 1
            if state[key] == expected:
                started[name].set()
        _require(
            release_old_executors.wait(5.0),
            "%s executor blocker release timed out" % name,
        )

    def playable(rows, _item, *_args, **kwargs):
        publish_seam.set()
        _require(
            release_publish.wait(5.0),
            "generation publish seam release timed out",
        )
        callback = kwargs.get("on_update")
        state["partial_attempts"] += 1
        if callable(callback):
            callback(list(rows))
        state["final_seam_reached"] = True
        return list(rows)

    spider._checked_resource_rows = lambda rows, _deadline=None: list(rows)
    spider._resource_fair_candidate_order = lambda rows, *_args, **_kwargs: list(rows)
    spider._playable_resource_rows = playable
    spider._validated_resource_group_count = lambda rows: int(bool(rows))
    spider._cache_set = lambda key, value: writes.append((key, list(value)))
    spider._schedule_active_detail_refresh = lambda item: refreshes.append(dict(item))
    spider._resource_capability = lambda _mode: "unknown"
    spider._ensure_atvp_connection = lambda force=False: bool(force)
    spider._resource_capability_identity = lambda: "p5-5d-generation-backend"
    spider._atvp_endpoint = endpoint
    spider._provider_reliability_for = lambda *_args, **_kwargs: controller
    spider._mark_resource_capability = lambda *_args, **_kwargs: None
    displaced_session = spider._atvp_session
    _require(
        displaced_session is not None and displaced_session.close_calls == 0,
        "fixture replacement did not own one active session",
    )
    displaced_session.close()
    _require(
        displaced_session.close_calls == 1,
        "fixture replacement did not close the displaced session once",
    )
    spider._atvp_session = old_session
    spider._alist_tvbox_plugin = True
    spider.atvp_api = "https://old.fixture.invalid"
    spider.atvp_token = old_token
    old_generation = spider._cache_generation
    new_generation = old_generation
    try:
        api_future = spider._submit_resource_mode_search(
            "vod", ["测试剧集"], time.monotonic() + 5.0,
            expected_generation=old_generation,
        )
        _require(api_future is not None, "old generation API mode task was not admitted")
        _require(
            response_read_started.wait(2.0),
            "old generation API did not reach the response ownership seam",
        )

        foreground_blockers = max(0, spider.RESOURCE_FOREGROUND_MODE_WORKERS - 1)
        lane_specs = (
            ("foreground", spider._resource_foreground_mode_executor, foreground_blockers),
            ("background", spider._resource_background_mode_executor, spider.RESOURCE_BACKGROUND_MODE_WORKERS),
            ("dns", spider._dns_executor, spider._dns_executor._max_workers),
            ("media", spider._media_probe_executor, spider._media_probe_executor._max_workers),
        )
        for name, executor, count in lane_specs:
            if count <= 0:
                started[name].set()
                continue
            blocker_futures.extend(
                executor.submit(block_executor, name, count)
                for _index in range(count)
            )
        for name in started:
            _require(started[name].wait(2.0), "%s old executor did not saturate" % name)

        queued_mode_futures = [
            spider._submit_resource_mode_search(
                "vod", ["排队前台"], time.monotonic() + 5.0,
                expected_generation=old_generation,
            ),
            spider._submit_resource_mode_search(
                "pansou", ["排队后台"], time.monotonic() + 5.0,
                background=True, expected_generation=old_generation,
            ),
        ]
        _require(
            all(future is not None for future in queued_mode_futures),
            "old generation foreground/background task was not queued",
        )
        _require(
            spider._schedule_supplement_resource_search(
                [], ["测试剧集"], {"title": "测试剧集"}, cache_key,
                expected_generation=old_generation,
            ),
            "generation scenario did not admit the old supplement job",
        )
        _require(publish_seam.wait(2.0), "old generation did not reach publish seam")
        with spider._cache_lock:
            owner_before_init = spider._resource_search_jobs.get(cache_key)
        _require(owner_before_init is not None, "old generation job owner was not observable")

        spider.init({
            "atvp_plugin_mode": spider.ATVP_PLUGIN_MODE,
            "atvp_api": "https://new.fixture.invalid",
            "atvp_token": new_token,
        })
        init_completed = True
        new_generation = spider._cache_generation
        new_session = spider._atvp_session
        new_executors = _executor_list(spider)
        new_slots = _slot_list(spider)
        with spider._cache_lock:
            owner_cleared_by_init = (
                cache_key not in spider._resource_search_jobs
                and cache_key not in spider._refreshing_cache_keys
            )
        _require(new_generation == old_generation + 1, "real init did not advance one generation")
        _require(spider.atvp_token == new_token, "real init did not install the new fixture token")
        _require(new_session is not old_session, "real init reused the old request session")
        _require(owner_cleared_by_init, "real init retained the old generation job owner")
        _require(old_supervisor.is_closed(), "real init did not seal the old task supervisor")
        _require(
            not set(map(id, old_executors)).intersection(map(id, new_executors)),
            "real init reused an old instance executor",
        )
        _require(
            not set(map(id, old_slots)).intersection(map(id, new_slots)),
            "real init reused an old instance slot",
        )
        old_executors_closed = sum(
            P5A._executor_is_closed(executor) for executor in old_executors
        )
        _require(
            old_executors_closed == len(EXECUTOR_FIELDS),
            "real init did not close all old instance executors",
        )
        probe_values = [
            future.result(timeout=1.0)
            for future in (
                executor.submit(lambda value=name: value)
                for name, executor in zip(EXECUTOR_FIELDS, new_executors)
            )
        ]
        new_executor_probe_count = len(probe_values)
        _require(
            probe_values == list(EXECUTOR_FIELDS),
            "new instance executors were blocked by saturated old DNS/media work",
        )
        for slot in new_slots:
            admitted = slot.acquire(False)
            if admitted:
                new_slot_probe_count += 1
                slot.release()
        _require(
            new_slot_probe_count == len(SLOT_FIELDS),
            "new instance slots were not immediately usable after live init",
        )

        release_response.set()
        release_publish.set()
        release_old_executors.set()
        api_result = api_future.result(timeout=5.0)
        for future in queued_mode_futures:
            _require(
                _wait_for(lambda owned=future: owned.done(), 5.0),
                "old queued mode future did not settle after init",
            )
            if future.cancelled():
                queued_cancelled += 1
                queued_fenced += 1
            else:
                result = future.result(timeout=0.1)
                if result == []:
                    queued_empty += 1
                    queued_fenced += 1
        _require(api_result == [], "in-flight old API mode result survived the init fence")
        _require(queued_fenced == 2, "old queued mode tasks survived the init fence")
        _require(
            _wait_for(lambda: state["final_seam_reached"], 3.0),
            "old generation worker did not return through final publish seam",
        )
        _require(not writes, "old generation wrote a cache result")
        _require(not refreshes, "old generation triggered a detail refresh")
        _require(old_session.get_calls == 1, "old API request was not owned by the old session once")
        _require(
            old_session.request_observations == [{"old_token": True, "old_session": True}],
            "old API request observed the new token or session",
        )
        _require(
            endpoint_observations == [{"old_token": True, "old_session": True}],
            "old API endpoint was composed from the new token or session",
        )
        observer_request_delta = (
            observer.snapshot()["request_attempts"] - observer_requests_before
        )
        _require(observer_request_delta == 0, "old work reached the new guarded session")
        _require(old_session.close_calls == 1, "real init did not close the old session once")
        _require(response.close_calls == 1, "in-flight old response was not closed exactly once")
        _require(close_state["closed"] == 1, "old response close observer drifted")
        _require(
            foreground_slots.acquire_successes == foreground_slots.release_calls == 2,
            "old foreground slots were not released exactly once per task",
        )
        _require(
            background_slots.acquire_successes == background_slots.release_calls == 1,
            "old background slot was not released exactly once",
        )
    finally:
        release_response.set()
        release_publish.set()
        release_old_executors.set()
        for future in blocker_futures + queued_mode_futures + ([api_future] if api_future is not None else []):
            if future is not None and not future.done():
                future.cancel()
        _wait_for(
            lambda: all(future.done() for future in blocker_futures if future is not None),
            5.0,
        )
        if not init_completed:
            spider._resource_foreground_mode_slots = foreground_slots.delegate
            spider._resource_background_mode_slots = background_slots.delegate
        _restore_attributes(spider, originals)
    _require(
        _wait_for(
            lambda: not any(
                thread.is_alive() for thread in _executor_worker_threads(old_executors)
            ),
            5.0,
        ),
        "old live-init executor workers survived release",
    )
    old_workers_alive_after_release = sum(
        thread.is_alive() for thread in _executor_worker_threads(old_executors)
    )
    return _scenario_row("generation_writeback", {
        "old_generation": old_generation,
        "new_generation": new_generation,
        "lifecycle_path": "Spider.init",
        "old_job_owner_observed": owner_before_init is not None,
        "old_job_owner_cleared_by_init": owner_cleared_by_init,
        "partial_publish_attempts": state["partial_attempts"],
        "final_publish_seam_reached": state["final_seam_reached"],
        "cache_writes": len(writes),
        "detail_refreshes": len(refreshes),
        "inflight_api_tasks": 1,
        "queued_foreground_tasks": 1,
        "queued_background_tasks": 1,
        "queued_mode_tasks_fenced": queued_fenced,
        "queued_mode_tasks_cancelled": queued_cancelled,
        "queued_mode_tasks_empty": queued_empty,
        "old_session_request_calls": old_session.get_calls,
        "old_session_close_calls": old_session.close_calls,
        "old_request_used_only_old_token_session": (
            old_session.request_observations == [{"old_token": True, "old_session": True}]
            and endpoint_observations == [{"old_token": True, "old_session": True}]
        ),
        "new_session_identity_changed": new_session is not old_session,
        "new_session_request_attempts": observer_request_delta,
        "response_close_calls": response.close_calls,
        "response_double_closes": max(0, response.close_calls - 1),
        "foreground_slot_acquires": foreground_slots.acquire_successes,
        "foreground_slot_releases": foreground_slots.release_calls,
        "background_slot_acquires": background_slots.acquire_successes,
        "background_slot_releases": background_slots.release_calls,
        "old_executors_closed": old_executors_closed,
        "new_executor_identities_distinct": not set(map(id, old_executors)).intersection(map(id, new_executors)),
        "new_executor_probes_while_old_saturated": new_executor_probe_count,
        "new_slot_identities_distinct": not set(map(id, old_slots)).intersection(map(id, new_slots)),
        "new_slot_probes_while_old_saturated": new_slot_probe_count,
        "old_executor_workers_alive_after_release": old_workers_alive_after_release,
        "jobs_after_release": len(spider._resource_search_jobs),
        "refresh_owners_after_release": len(spider._refreshing_cache_keys),
    })


def _run_response_close(spider, module):
    close_state = {"closed": 0}
    response = ResponseFixture(b'{"list": []}', close_state)
    session = ResourceSessionFixture(response)
    lease = ReliabilityLeaseFixture()
    controller = ReliabilityControllerFixture(lease)
    state = {
        "shared_reader_calls": 0,
        "shared_reader_close_response_false": 0,
        "capability_marks": 0,
    }
    originals = dict(
        (name, getattr(spider, name))
        for name in (
            "_atvp_session", "_resource_capability", "_ensure_atvp_connection",
            "_resource_capability_identity", "_atvp_endpoint",
            "_provider_reliability_for", "_mark_resource_capability",
        )
    )
    shared_reader = module._read_bounded_json_shared

    def read_shared(*args, **kwargs):
        state["shared_reader_calls"] += 1
        state["shared_reader_close_response_false"] += int(
            kwargs.get("close_response") is False
        )
        return shared_reader(*args, **kwargs)

    def mark_capability(*_args, **_kwargs):
        state["capability_marks"] += 1

    spider._atvp_session = session
    spider._resource_capability = lambda _mode: "unknown"
    spider._ensure_atvp_connection = lambda force=False: bool(force)
    spider._resource_capability_identity = lambda: "p5-5d-response-backend"
    spider._atvp_endpoint = lambda mode: "https://fixture.invalid/%s" % mode
    spider._provider_reliability_for = lambda *_args, **_kwargs: controller
    spider._mark_resource_capability = mark_capability
    module._read_bounded_json_shared = read_shared
    value = None
    try:
        value = spider._resource_api_get(
            "vod", {"wd": "测试剧集"}, deadline=time.monotonic() + 2.0,
            expected_generation=spider._cache_generation,
        )
    finally:
        _restore_attributes(spider, originals)
        module._read_bounded_json_shared = shared_reader
    _require(value == {"list": []}, "resource API payload drifted")
    _require(session.get_calls == 1, "resource API request owner was not exercised once")
    _require(state["shared_reader_calls"] == 1, "shared reader was not reached through resource API owner")
    _require(
        state["shared_reader_close_response_false"] == 1,
        "resource API did not retain the response owner while reading",
    )
    _require(response.close_calls == 1, "resource API response was not closed exactly once")
    _require(close_state["closed"] == 1, "response close observer count drifted")
    _require(lease.finishes == [{"success": True}], "provider reliability lease finish drifted")
    return _scenario_row("response_close", {
        "owner_path": "Spider._resource_api_get",
        "request_calls": session.get_calls,
        "shared_reader_calls": state["shared_reader_calls"],
        "shared_reader_close_response_false": state["shared_reader_close_response_false"],
        "capability_marks": state["capability_marks"],
        "lease_success_finishes": len(lease.finishes),
        "responses_created": 1,
        "responses_closed": close_state["closed"],
        "response_double_closes": max(0, response.close_calls - 1),
        "exactly_once": response.close_calls == 1,
    })


def _run_resource_completion_isolation(spider):
    release = threading.Event()
    started = threading.Event()
    lock = threading.Lock()
    state = {"active": 0, "peak": 0, "completed": 0, "foreground_calls": 0}
    original = spider._resource_search_mode
    controller = spider._background_bulkhead_controller
    generation = spider._cache_generation
    before = controller.snapshot()
    limit = before["limits"]["resource_completion"]
    admitted = []
    extra = None
    at_capacity = before
    after_reject = before

    def completion_worker():
        with lock:
            state["active"] += 1
            state["peak"] = max(state["peak"], state["active"])
            if state["active"] == spider.RESOURCE_HOT_JOB_LIMIT:
                started.set()
        try:
            _require(release.wait(5.0), "resource completion release timed out")
        finally:
            with lock:
                state["active"] -= 1
                state["completed"] += 1

    def foreground_search(mode, queries, deadline=None, expected_generation=None):
        del queries, deadline, expected_generation
        state["foreground_calls"] += 1
        return [{"vod_id": str(mode), "vod_name": "前台结果"}]

    spider._resource_search_mode = foreground_search
    try:
        admitted = [
            spider._submit_background_bulkhead_task(
                "resource_completion", generation, completion_worker,
                "p5-5d-resource-completion-%d" % index,
                executor=spider._resource_search_executor,
            )
            for index in range(limit)
        ]
        _require(all(admitted), "resource completion lane lost an in-capacity admission")
        _require(started.wait(1.0), "resource completion workers did not reach executor capacity")
        at_capacity = controller.snapshot()
        extra = spider._submit_background_bulkhead_task(
            "resource_completion", generation, completion_worker,
            "p5-5d-resource-completion-capacity-plus-one",
            executor=spider._resource_search_executor,
        )
        after_reject = controller.snapshot()
        _require(extra is False, "resource completion capacity plus one was admitted")
        _require(at_capacity["inflight"]["resource_completion"] == limit, "resource completion lane was not saturated")
        foreground = spider._submit_resource_mode_search(
            "foreground-during-resource-completion", ["测试剧集"],
            time.monotonic() + 1.0,
        )
        _require(foreground is not None, "foreground submission blocked behind resource completion lane")
        _require(
            foreground.result(timeout=1.0)[0]["vod_name"] == "前台结果",
            "foreground result drifted while resource completion lane was saturated",
        )
        release.set()
        _require(_wait_for(lambda: state["completed"] == limit, 5.0), "resource completion workers did not finish")
        _require(
            _wait_for(
                lambda: controller.snapshot()["inflight"]["resource_completion"] == 0,
                2.0,
            ),
            "resource completion inflight did not return to zero",
        )
    finally:
        release.set()
        _wait_for(lambda: state["completed"] == limit, 5.0)
        spider._resource_search_mode = original
    return _scenario_row("resource_completion_isolation", {
        "lane_limit": limit,
        "admitted": sum(bool(value) for value in admitted),
        "capacity_plus_one_rejected": extra is False,
        "rejected_delta": (
            after_reject["rejected"]["resource_completion"]
            - before["rejected"]["resource_completion"]
        ),
        "inflight_at_capacity": at_capacity["inflight"]["resource_completion"],
        "worker_peak": state["peak"],
        "foreground_calls": state["foreground_calls"],
        "foreground_non_blocking": True,
        "completed": state["completed"],
        "inflight_after_release": controller.snapshot()["inflight"]["resource_completion"],
    })


def _destroy_spider(spider, destroy_state):
    destroy_state["called"] = True
    spider.destroy()
    destroy_state["returned"] = True


def _run_destroy_race(spider, destroy_state, executors, module, observer):
    release_old_executors = threading.Event()
    state_lock = threading.Lock()
    started = dict((name, threading.Event()) for name in (
        "foreground", "background", "dns", "media",
    ))
    active = dict((name, 0) for name in started)
    originals = {
        "_resource_search_mode": spider._resource_search_mode,
        "_resource_api_get": spider._resource_api_get,
        "_resource_foreground_mode_slots": spider._resource_foreground_mode_slots,
        "_resource_background_mode_slots": spider._resource_background_mode_slots,
    }
    foreground_slots = CountingSlotFixture(originals["_resource_foreground_mode_slots"])
    background_slots = CountingSlotFixture(originals["_resource_background_mode_slots"])
    spider._resource_foreground_mode_slots = foreground_slots
    spider._resource_background_mode_slots = background_slots
    old_token = "p5-5d-destroy-old-fixture-token"
    old_generation = spider._cache_generation
    destroy_generation = old_generation
    mode_calls = []
    api_calls = []
    blocker_futures = []
    mode_futures = []
    next_spider = None
    next_executors = ()
    next_probe_futures = []
    new_executor_probes_completed = 0
    old_executors_closed = 0
    next_executors_closed = 0
    old_references_after = {}
    next_references_after = {}
    timeout_after_destroy = {"active": -1, "closed": False}
    bulkhead_after_destroy = {"inflight": {"resource_completion": -1}}

    def block_executor(name, expected):
        with state_lock:
            active[name] += 1
            if active[name] == expected:
                started[name].set()
        _require(
            release_old_executors.wait(5.0),
            "%s executor blocker release timed out" % name,
        )

    def search(mode, queries, deadline=None, expected_generation=None):
        del queries, deadline, expected_generation
        mode_calls.append({
            "mode": str(mode),
            "used_replacement_token": spider.atvp_token != old_token,
        })
        spider._resource_api_get(mode, {"wd": "测试剧集"})
        return []

    def api_get(mode, *_args, **_kwargs):
        api_calls.append({
            "mode": str(mode),
            "used_replacement_token": spider.atvp_token != old_token,
        })
        return {"list": []}

    spider._resource_search_mode = search
    spider._resource_api_get = api_get
    spider.atvp_token = old_token
    lane_specs = (
        (
            "foreground", spider._resource_foreground_mode_executor,
            spider.RESOURCE_FOREGROUND_MODE_WORKERS,
        ),
        (
            "background", spider._resource_background_mode_executor,
            spider.RESOURCE_BACKGROUND_MODE_WORKERS,
        ),
        ("dns", spider._dns_executor, spider._dns_executor._max_workers),
        ("media", spider._media_probe_executor, spider._media_probe_executor._max_workers),
    )
    try:
        for name, executor, count in lane_specs:
            blocker_futures.extend(
                executor.submit(block_executor, name, count)
                for _index in range(count)
            )
        for name in started:
            _require(started[name].wait(1.0), "%s executor did not saturate" % name)
        mode_futures = [
            spider._submit_resource_mode_search(
                "destroy-foreground", ["测试剧集"], time.monotonic() + 5.0,
                expected_generation=old_generation,
            ),
            spider._submit_resource_mode_search(
                "destroy-background", ["测试剧集"], time.monotonic() + 5.0,
                background=True, expected_generation=old_generation,
            ),
        ]
        _require(all(future is not None for future in mode_futures), "destroy generation mode task was not queued")
        _destroy_spider(spider, destroy_state)
        destroy_generation = spider._cache_generation
        timeout_after_destroy = spider._timeout_budget_controller.snapshot()
        bulkhead_after_destroy = spider._background_bulkhead_controller.snapshot()
        _require(destroy_generation == old_generation + 1, "real destroy did not advance one generation")
        _require(
            _wait_for(lambda: all(future.done() for future in mode_futures), 2.0),
            "destroy did not settle queued mode futures",
        )
        _require(all(future.cancelled() for future in mode_futures), "destroy did not cancel queued old mode futures")
        _require(not mode_calls and not api_calls, "destroyed old mode task reached the request path")
        _require(
            foreground_slots.acquire_successes == foreground_slots.release_calls == 1,
            "destroyed foreground slot was not released exactly once",
        )
        _require(
            background_slots.acquire_successes == background_slots.release_calls == 1,
            "destroyed background slot was not released exactly once",
        )
        old_executors_closed = sum(P5A._executor_is_closed(executor) for executor in executors)
        _require(old_executors_closed == len(EXECUTOR_FIELDS), "destroy did not close all old instance executors")

        next_spider = module.Spider()
        P5A._install_isolation_stubs(next_spider, observer)
        next_spider.init({})
        next_executors = _executor_list(next_spider)
        _require(
            not set(map(id, executors)).intersection(map(id, next_executors)),
            "new Spider reused an old instance executor",
        )
        next_probe_futures = [
            executor.submit(lambda value=name: value)
            for name, executor in zip(EXECUTOR_FIELDS, next_executors)
        ]
        probe_values = [future.result(timeout=1.0) for future in next_probe_futures]
        new_executor_probes_completed = len(probe_values)
        _require(
            probe_values == list(EXECUTOR_FIELDS),
            "new Spider executor probes were blocked by the saturated old instance",
        )
        next_spider.destroy()
        next_executors_closed = sum(
            P5A._executor_is_closed(executor) for executor in next_executors
        )
        _require(next_executors_closed == len(EXECUTOR_FIELDS), "new Spider destroy did not close all executors")
        _require(
            _wait_for(
                lambda: not any(
                    thread.is_alive()
                    for thread in _executor_worker_threads(next_executors)
                ),
                5.0,
            ),
            "new Spider executor workers survived destroy",
        )
        next_references_after = P5A._reference_counts(next_spider)
        _require(
            _zero_reference_counts_are_admitted(next_references_after),
            "new Spider retained runtime references after destroy",
        )
    finally:
        release_old_executors.set()
        if next_spider is not None and not next_spider._tasks.is_closed():
            next_spider.destroy()
        if not destroy_state["called"]:
            _destroy_spider(spider, destroy_state)
        _wait_for(
            lambda: all(future.done() for future in blocker_futures if future is not None),
            5.0,
        )
        _restore_attributes(spider, originals)
    _require(
        _wait_for(
            lambda: not any(
                thread.is_alive() for thread in _executor_worker_threads(executors)
            ),
            5.0,
        ),
        "old instance executor workers survived blocker release",
    )
    old_references_after = P5A._reference_counts(spider)
    _require(
        _zero_reference_counts_are_admitted(old_references_after),
        "old Spider retained runtime references after destroy",
    )
    return _scenario_row("destroy_race", {
        "lifecycle_path": "Spider.destroy",
        "old_generation": old_generation,
        "destroy_generation": destroy_generation,
        "queued_foreground_tasks": 1,
        "queued_background_tasks": 1,
        "queued_futures_cancelled": sum(future.cancelled() for future in mode_futures),
        "old_mode_calls_after_destroy": len(mode_calls),
        "old_api_calls_after_destroy": len(api_calls),
        "replacement_token_observations": sum(
            item["used_replacement_token"] for item in mode_calls + api_calls
        ),
        "foreground_slot_acquires": foreground_slots.acquire_successes,
        "foreground_slot_releases": foreground_slots.release_calls,
        "background_slot_acquires": background_slots.acquire_successes,
        "background_slot_releases": background_slots.release_calls,
        "executors_per_instance": len(EXECUTOR_FIELDS),
        "old_executors_closed": old_executors_closed,
        "new_executor_identities_distinct": not set(map(id, executors)).intersection(map(id, next_executors)),
        "new_executor_probes_completed_while_old_saturated": new_executor_probes_completed,
        "new_executors_closed": next_executors_closed,
        "old_references_zero_after_release": _zero_reference_counts_are_admitted(old_references_after),
        "new_references_zero_after_destroy": _zero_reference_counts_are_admitted(next_references_after),
        "old_executor_workers_alive_after_release": sum(
            thread.is_alive() for thread in _executor_worker_threads(executors)
        ),
        "new_executor_workers_alive_after_destroy": sum(
            thread.is_alive() for thread in _executor_worker_threads(next_executors)
        ),
        "destroy_returned": destroy_state["returned"],
        "timeout_active_after_destroy": timeout_after_destroy["active"],
        "timeout_closed_after_destroy": timeout_after_destroy["closed"],
        "bulkhead_inflight_after_destroy": sum(bulkhead_after_destroy["inflight"].values()),
    })


def _isolation_evidence(observer, deployment_surface):
    evidence = dict(observer.snapshot())
    evidence.update({
        "scope": "candidate_search_call_family",
        "deployment_surface": deployment_surface,
        "deployment_attempted": not deployment_surface["listed_deployment_surfaces_absent_static_ast"],
        "deployment_attempted_basis": "pre_execution_static_ast_guard",
    })
    return evidence


def _cleanup_evidence(spider, executors, destroy_state):
    task_counts = _task_counts(spider._tasks)
    references = P5A._reference_counts(spider)
    sessions = list(P5A.FakeSession.instances)
    timeout = spider._timeout_budget_controller.snapshot()
    bulkhead = spider._background_bulkhead_controller.snapshot()
    return {
        "destroy_called": bool(destroy_state["called"]),
        "destroy_returned": bool(destroy_state["returned"]),
        "sessions_created_total": len(sessions),
        "sessions_closed_once": sum(session.close_calls == 1 for session in sessions),
        "session_close_calls_total": sum(session.close_calls for session in sessions),
        "session_references_retained": int(spider._session is not None)
        + sum(value is not None for value in (spider._tmdb_session, spider._atvp_session)),
        "task_threads": task_counts["threads"],
        "task_timers": task_counts["timers"],
        "task_executors": task_counts["executors"],
        "executor_fields": list(EXECUTOR_FIELDS),
        "executors_total": len(executors),
        "executors_closed": sum(P5A._executor_is_closed(executor) for executor in executors),
        "executor_workers_alive": sum(
            thread.is_alive() for thread in _executor_worker_threads(executors)
        ),
        "resource_search_jobs": len(spider._resource_search_jobs),
        "refreshing_cache_keys": len(spider._refreshing_cache_keys),
        "resource_completion_inflight": bulkhead["inflight"]["resource_completion"],
        "bulkhead_inflight_total": sum(bulkhead["inflight"].values()),
        "timeout_active": timeout["active"],
        "timeout_closed": timeout["closed"],
        "reference_counts": references,
    }


def _workload_evidence(spider):
    bulkhead = spider._background_bulkhead_controller.snapshot()
    return {
        "owner": "candidate.search_call_family",
        "scenario_order": list(SCENARIOS),
        "scenario_labels_zh": dict(SCENARIO_LABELS_ZH),
        "foreground_workers": spider.RESOURCE_FOREGROUND_MODE_WORKERS,
        "foreground_queue_limit": spider.RESOURCE_FOREGROUND_MODE_QUEUE_LIMIT,
        "background_workers": spider.RESOURCE_BACKGROUND_MODE_WORKERS,
        "background_queue_limit": spider.RESOURCE_BACKGROUND_MODE_QUEUE_LIMIT,
        "resource_job_workers": spider.RESOURCE_HOT_JOB_LIMIT,
        "resource_job_queue_limit": spider.RESOURCE_HOT_JOB_QUEUE_LIMIT,
        "resource_completion_limit": bulkhead["limits"]["resource_completion"],
        "background_bulkhead_lane": "resource_completion",
        "instance_executor_fields": list(EXECUTOR_FIELDS),
        "instance_executor_count": len(EXECUTOR_FIELDS),
        "instance_slot_fields": list(SLOT_FIELDS),
        "instance_slot_count": len(SLOT_FIELDS),
        "mode_slot_owner": "Spider._submit_resource_mode_search.release_once",
        "search_budget_seconds": spider.RESOURCE_SEARCH_BUDGET,
        "background_validation_budget_seconds": spider.RESOURCE_HOT_VALIDATION_BUDGET,
        "response_owner": "Spider._resource_api_get",
        "generation_owner": "Spider._cache_generation_and_instance_executors",
        "formal_profile": True,
    }


def _workload_is_admitted(workload):
    required = {
        "owner", "scenario_order", "scenario_labels_zh", "foreground_workers",
        "foreground_queue_limit", "background_workers", "background_queue_limit",
        "resource_job_workers", "resource_job_queue_limit", "resource_completion_limit",
        "background_bulkhead_lane", "instance_executor_fields",
        "instance_executor_count", "instance_slot_fields", "instance_slot_count",
        "mode_slot_owner", "search_budget_seconds",
        "background_validation_budget_seconds", "response_owner", "generation_owner",
        "formal_profile",
    }
    return (
        isinstance(workload, dict)
        and set(workload) == required
        and workload.get("owner") == "candidate.search_call_family"
        and workload.get("scenario_order") == list(SCENARIOS)
        and workload.get("scenario_labels_zh") == SCENARIO_LABELS_ZH
        and all(type(workload.get(name)) is int and workload.get(name) > 0 for name in (
            "foreground_workers", "foreground_queue_limit", "background_workers",
            "background_queue_limit", "resource_job_workers", "resource_job_queue_limit",
            "resource_completion_limit", "search_budget_seconds",
            "background_validation_budget_seconds",
        ))
        and workload.get("resource_completion_limit")
        == workload.get("resource_job_workers") + workload.get("resource_job_queue_limit")
        and workload.get("background_bulkhead_lane") == "resource_completion"
        and workload.get("instance_executor_fields") == list(EXECUTOR_FIELDS)
        and workload.get("instance_executor_count") == len(EXECUTOR_FIELDS)
        and workload.get("instance_slot_fields") == list(SLOT_FIELDS)
        and workload.get("instance_slot_count") == len(SLOT_FIELDS)
        and workload.get("mode_slot_owner") == "Spider._submit_resource_mode_search.release_once"
        and workload.get("response_owner") == "Spider._resource_api_get"
        and workload.get("generation_owner") == "Spider._cache_generation_and_instance_executors"
        and workload.get("formal_profile") is True
    )


def _scenario_is_admitted(row, expected_name):
    if not isinstance(row, dict) or set(row) != {"name", "label_zh", "status", "metrics"}:
        return False
    return (
        row.get("name") == expected_name
        and row.get("label_zh") == SCENARIO_LABELS_ZH[expected_name]
        and row.get("status") == "passed"
        and isinstance(row.get("metrics"), dict)
    )


def _scenario_metrics_are_admitted(row, expected_name, workload):
    metrics = row.get("metrics")
    if not isinstance(metrics, dict):
        return False
    if expected_name == "foreground_capacity":
        return (
            set(metrics) == {
                "submitted", "completed", "active_peak", "max_workers", "queue_limit",
                "capacity_plus_one_rejected", "rejected_while_workers_blocked",
                "replacement_admitted_after_release", "finite_deadlines",
            }
            and metrics["submitted"] == workload["foreground_workers"] + workload["foreground_queue_limit"]
            and metrics["completed"] == metrics["submitted"] + 1
            and metrics["active_peak"] == metrics["max_workers"] == workload["foreground_workers"]
            and metrics["queue_limit"] == workload["foreground_queue_limit"]
            and all(metrics[name] is True for name in (
                "capacity_plus_one_rejected", "rejected_while_workers_blocked",
                "replacement_admitted_after_release", "finite_deadlines",
            ))
        )
    if expected_name == "queued_cancellation":
        return (
            set(metrics) == {
                "running", "queued", "cancelled", "replacement_admitted_before_release",
                "workers_blocked_during_replacement", "completed",
            }
            and metrics["running"] == workload["foreground_workers"]
            and metrics["queued"] == workload["foreground_queue_limit"]
            and metrics["completed"] == metrics["running"] + metrics["queued"]
            and all(metrics[name] is True for name in (
                "cancelled", "replacement_admitted_before_release",
                "workers_blocked_during_replacement",
            ))
        )
    if expected_name == "job_owner":
        return (
            set(metrics) == {
                "duplicate_rejected", "duplicate_owner_preserved",
                "duplicate_refresh_owner_preserved", "owner_identity_observed",
                "owner_released_after_completion",
                "refresh_owner_released_after_completion",
                "submit_rejection_reported", "submit_rejection_owner_cleared",
                "submit_rejection_refresh_owner_cleared",
                "candidate_lifecycle_path", "candidate_old_generation",
                "candidate_new_generation", "candidate_scheduler_calls",
                "candidate_scheduler_received_old_generation",
                "candidate_result_rows", "candidate_job_registered_after_init",
                "candidate_refresh_registered_after_init",
            }
            and all(metrics[name] is True for name in (
                "duplicate_rejected", "duplicate_owner_preserved",
                "duplicate_refresh_owner_preserved", "owner_identity_observed",
                "owner_released_after_completion",
                "refresh_owner_released_after_completion",
                "submit_rejection_reported", "submit_rejection_owner_cleared",
                "submit_rejection_refresh_owner_cleared",
                "candidate_scheduler_received_old_generation",
            ))
            and metrics["candidate_lifecycle_path"] == "Spider.init"
            and type(metrics["candidate_old_generation"]) is int
            and metrics["candidate_new_generation"] == metrics["candidate_old_generation"] + 1
            and metrics["candidate_scheduler_calls"] == 1
            and metrics["candidate_result_rows"] == 0
            and metrics["candidate_job_registered_after_init"] is False
            and metrics["candidate_refresh_registered_after_init"] is False
        )
    if expected_name == "generation_writeback":
        return (
            set(metrics) == {
                "old_generation", "new_generation", "lifecycle_path",
                "old_job_owner_observed", "old_job_owner_cleared_by_init",
                "partial_publish_attempts",
                "final_publish_seam_reached", "cache_writes",
                "detail_refreshes", "inflight_api_tasks",
                "queued_foreground_tasks", "queued_background_tasks",
                "queued_mode_tasks_fenced", "queued_mode_tasks_cancelled",
                "queued_mode_tasks_empty", "old_session_request_calls",
                "old_session_close_calls", "old_request_used_only_old_token_session",
                "new_session_identity_changed", "new_session_request_attempts",
                "response_close_calls", "response_double_closes",
                "foreground_slot_acquires", "foreground_slot_releases",
                "background_slot_acquires", "background_slot_releases",
                "old_executors_closed", "new_executor_identities_distinct",
                "new_executor_probes_while_old_saturated",
                "new_slot_identities_distinct", "new_slot_probes_while_old_saturated",
                "old_executor_workers_alive_after_release",
                "jobs_after_release", "refresh_owners_after_release",
            }
            and type(metrics["old_generation"]) is int
            and metrics["new_generation"] == metrics["old_generation"] + 1
            and metrics["lifecycle_path"] == "Spider.init"
            and metrics["old_job_owner_observed"] is True
            and metrics["old_job_owner_cleared_by_init"] is True
            and metrics["partial_publish_attempts"] == 1
            and metrics["final_publish_seam_reached"] is True
            and metrics["inflight_api_tasks"] == 1
            and metrics["queued_foreground_tasks"] == 1
            and metrics["queued_background_tasks"] == 1
            and metrics["queued_mode_tasks_fenced"] == 2
            and metrics["queued_mode_tasks_cancelled"] + metrics["queued_mode_tasks_empty"] == 2
            and metrics["old_session_request_calls"] == 1
            and metrics["old_session_close_calls"] == 1
            and metrics["old_request_used_only_old_token_session"] is True
            and metrics["new_session_identity_changed"] is True
            and metrics["new_session_request_attempts"] == 0
            and metrics["response_close_calls"] == 1
            and metrics["response_double_closes"] == 0
            and metrics["foreground_slot_acquires"] == metrics["foreground_slot_releases"] == 2
            and metrics["background_slot_acquires"] == metrics["background_slot_releases"] == 1
            and metrics["old_executors_closed"] == workload["instance_executor_count"]
            and metrics["new_executor_identities_distinct"] is True
            and metrics["new_executor_probes_while_old_saturated"] == workload["instance_executor_count"]
            and metrics["new_slot_identities_distinct"] is True
            and metrics["new_slot_probes_while_old_saturated"] == len(SLOT_FIELDS)
            and metrics["old_executor_workers_alive_after_release"] == 0
            and all(metrics[name] == 0 for name in (
                "cache_writes", "detail_refreshes", "jobs_after_release", "refresh_owners_after_release",
            ))
        )
    if expected_name == "response_close":
        return (
            set(metrics) == {
                "owner_path", "request_calls", "shared_reader_calls",
                "shared_reader_close_response_false", "capability_marks",
                "lease_success_finishes", "responses_created", "responses_closed",
                "response_double_closes", "exactly_once",
            }
            and metrics == {
                "owner_path": "Spider._resource_api_get",
                "request_calls": 1,
                "shared_reader_calls": 1,
                "shared_reader_close_response_false": 1,
                "capability_marks": 1,
                "lease_success_finishes": 1,
                "responses_created": 1,
                "responses_closed": 1,
                "response_double_closes": 0,
                "exactly_once": True,
            }
        )
    if expected_name == "resource_completion_isolation":
        return (
            set(metrics) == {
                "lane_limit", "admitted", "capacity_plus_one_rejected", "rejected_delta",
                "inflight_at_capacity", "worker_peak", "foreground_calls",
                "foreground_non_blocking", "completed", "inflight_after_release",
            }
            and metrics["lane_limit"] == workload["resource_completion_limit"]
            and metrics["admitted"] == metrics["completed"] == metrics["inflight_at_capacity"] == metrics["lane_limit"]
            and metrics["capacity_plus_one_rejected"] is True
            and metrics["rejected_delta"] == 1
            and metrics["worker_peak"] == workload["resource_job_workers"]
            and metrics["foreground_calls"] == 1
            and metrics["foreground_non_blocking"] is True
            and metrics["inflight_after_release"] == 0
        )
    if expected_name == "destroy_race":
        return (
            set(metrics) == {
                "lifecycle_path", "old_generation", "destroy_generation",
                "queued_foreground_tasks", "queued_background_tasks",
                "queued_futures_cancelled", "old_mode_calls_after_destroy",
                "old_api_calls_after_destroy", "replacement_token_observations",
                "foreground_slot_acquires", "foreground_slot_releases",
                "background_slot_acquires", "background_slot_releases",
                "executors_per_instance", "old_executors_closed",
                "new_executor_identities_distinct",
                "new_executor_probes_completed_while_old_saturated",
                "new_executors_closed", "old_references_zero_after_release",
                "new_references_zero_after_destroy",
                "old_executor_workers_alive_after_release",
                "new_executor_workers_alive_after_destroy", "destroy_returned",
                "timeout_active_after_destroy", "timeout_closed_after_destroy",
                "bulkhead_inflight_after_destroy",
            }
            and metrics["lifecycle_path"] == "Spider.destroy"
            and type(metrics["old_generation"]) is int
            and metrics["destroy_generation"] == metrics["old_generation"] + 1
            and metrics["queued_foreground_tasks"] == 1
            and metrics["queued_background_tasks"] == 1
            and metrics["queued_futures_cancelled"] == 2
            and metrics["foreground_slot_acquires"] == metrics["foreground_slot_releases"] == 1
            and metrics["background_slot_acquires"] == metrics["background_slot_releases"] == 1
            and metrics["executors_per_instance"] == workload["instance_executor_count"]
            and metrics["old_executors_closed"] == metrics["executors_per_instance"]
            and metrics["new_executor_identities_distinct"] is True
            and metrics["new_executor_probes_completed_while_old_saturated"] == metrics["executors_per_instance"]
            and metrics["new_executors_closed"] == metrics["executors_per_instance"]
            and metrics["old_references_zero_after_release"] is True
            and metrics["new_references_zero_after_destroy"] is True
            and metrics["destroy_returned"] is True
            and all(metrics[name] == 0 for name in (
                "old_mode_calls_after_destroy", "old_api_calls_after_destroy",
                "replacement_token_observations",
                "old_executor_workers_alive_after_release",
                "new_executor_workers_alive_after_destroy",
            ))
            and metrics["timeout_active_after_destroy"] == 0
            and metrics["timeout_closed_after_destroy"] is True
            and metrics["bulkhead_inflight_after_destroy"] == 0
        )
    return False


def _cleanup_is_admitted(cleanup):
    references = cleanup.get("reference_counts") if isinstance(cleanup, dict) else None
    required = {
        "destroy_called", "destroy_returned", "sessions_created_total",
        "sessions_closed_once", "session_close_calls_total",
        "session_references_retained", "task_threads", "task_timers",
        "task_executors", "executor_fields", "executors_total", "executors_closed",
        "executor_workers_alive", "resource_search_jobs",
        "refreshing_cache_keys",
        "resource_completion_inflight", "bulkhead_inflight_total",
        "timeout_active", "timeout_closed", "reference_counts",
    }
    return (
        isinstance(cleanup, dict)
        and set(cleanup) == required
        and cleanup.get("destroy_called") is True
        and cleanup.get("destroy_returned") is True
        and type(cleanup.get("sessions_created_total")) is int
        and cleanup.get("sessions_created_total") > 0
        and cleanup.get("sessions_closed_once") == cleanup.get("sessions_created_total")
        and cleanup.get("session_close_calls_total") == cleanup.get("sessions_created_total")
        and cleanup.get("session_references_retained") == 0
        and cleanup.get("task_threads") == 0
        and cleanup.get("task_timers") == 0
        and cleanup.get("task_executors") == 0
        and cleanup.get("executor_fields") == list(EXECUTOR_FIELDS)
        and cleanup.get("executors_total") == len(EXECUTOR_FIELDS)
        and cleanup.get("executors_closed") == cleanup.get("executors_total")
        and cleanup.get("executor_workers_alive") == 0
        and cleanup.get("resource_search_jobs") == 0
        and cleanup.get("refreshing_cache_keys") == 0
        and cleanup.get("resource_completion_inflight") == 0
        and cleanup.get("bulkhead_inflight_total") == 0
        and cleanup.get("timeout_active") == 0
        and cleanup.get("timeout_closed") is True
        and _zero_reference_counts_are_admitted(references)
    )


def _generated_at_is_admitted(value):
    if not isinstance(value, str) or not value.endswith("Z"):
        return False
    try:
        parsed = dt.datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return False
    return parsed.tzinfo is not None


def _candidate_is_admitted(candidate):
    return isinstance(candidate, dict) and candidate == EXPECTED_CANDIDATE


def _closure_is_admitted(closure, candidate):
    if not isinstance(closure, dict) or set(closure) != {
        "executed", "output", "state_before_sha256", "state_after_sha256",
        "stable_after_samples",
    }:
        return False
    before = closure.get("state_before_sha256")
    after = closure.get("state_after_sha256")
    return (
        closure.get("stable_after_samples") is True
        and candidate == closure.get("executed") == closure.get("output")
        and isinstance(before, str) and len(before) == 64
        and all(character in "0123456789ABCDEF" for character in before)
        and before == after
    )


def report_is_admitted(report, allow_pending=False):
    if not isinstance(report, dict) or set(report) != TOP_LEVEL_KEYS:
        return False
    workload = report.get("workload")
    rows = report.get("scenario_results")
    summary = report.get("summary")
    invariants = report.get("invariants")
    candidate = report.get("candidate")
    closure = report.get("candidate_closure")
    isolation = report.get("isolation")
    required_invariants = {
        "foreground_bound", "capacity_plus_one_rejected",
        "queued_cancel_released_while_blocked", "job_owner_duplicate_preserved",
        "job_owner_submit_rejection_clean", "candidate_supplement_generation_fenced",
        "generation_writeback_blocked", "generation_queued_modes_fenced",
        "generation_response_owner_once", "generation_executor_rotation",
        "generation_slots_released_once",
        "response_closed_once", "resource_completion_isolated",
        "instance_executors_isolated", "destroy_slots_released_once",
        "destroy_race_quiescent",
        "cleanup_quiescent", "candidate_stable_after_samples",
    }
    return (
        report.get("schema") == REPORT_SCHEMA
        and _generated_at_is_admitted(report.get("generated_at"))
        and (report.get("overall") == "passed" or (allow_pending and report.get("overall") == "pending"))
        and report.get("failure") is None
        and report.get("evidence_provenance") == EXPECTED_EVIDENCE_PROVENANCE
        and _workload_is_admitted(workload)
        and report.get("limitations") == list(LIMITATIONS)
        and isinstance(rows, list)
        and len(rows) == len(SCENARIOS)
        and all(
            _scenario_is_admitted(row, name)
            and _scenario_metrics_are_admitted(row, name, workload)
            for row, name in zip(rows, SCENARIOS)
        )
        and summary == {"total": len(SCENARIOS), "passed": len(SCENARIOS), "failed": 0}
        and isinstance(invariants, dict)
        and set(invariants) == required_invariants
        and all(value is True for value in invariants.values())
        and _candidate_is_admitted(candidate)
        and _closure_is_admitted(closure, candidate)
        and isinstance(isolation, dict)
        and isolation.get("scope") == "candidate_search_call_family"
        and isolation.get("request_attempts") == 0
        and isolation.get("socket_connect_attempts") == 0
        and isolation.get("network_requests") == 0
        and isolation.get("credential_values_observed") == 0
        and isolation.get("credentials_used") is False
        and isolation.get("production_persistence_calls") == 4
        and isolation.get("production_persistence_calls_blocked") == 4
        and isolation.get("production_writes") is False
        and isolation.get("deployment_attempted") is False
        and isolation.get("deployment_surface", {}).get("listed_deployment_surfaces_absent_static_ast") is True
        and _cleanup_is_admitted(report.get("cleanup"))
    )


def _safe_error(exc):
    if isinstance(exc, SearchConcurrencyAssertionError):
        return {"error_type": "SearchConcurrencyAssertionError", "error": str(exc)}
    if isinstance(exc, TimeoutError):
        return {"error_type": "TimeoutError", "error": "scenario timed out"}
    if isinstance(exc, RuntimeError):
        return {"error_type": "RuntimeError", "error": "scenario runtime failure"}
    return {"error_type": "UnknownError", "error": "scenario execution failed"}


def _failed_row(name, exc):
    return {
        "name": name,
        "label_zh": SCENARIO_LABELS_ZH[name],
        "status": "failed",
        "metrics": _safe_error(exc),
    }


def run_search_concurrency():
    _require(_loaded_inputs_are_current(), "loaded evidence inputs changed; start a new process")
    executed = _executed_build()
    candidate = _candidate_evidence_from(executed)
    _require(candidate == EXPECTED_CANDIDATE, "built candidate does not match release manifest")
    state_before = _candidate_state_sha256(executed["output"])
    observer = P5A.IsolationObserver()
    P5A.FakeSession.instances = []
    module = _runtime_module(observer, executed)
    deployment_surface = dict(P5A._deployment_surface_evidence(executed["bytes"]))
    runner_findings = P5A._deployment_surface_scan(
        Path(__file__).read_bytes(), "tests/v80_p5_search_concurrency_runner.py",
    )
    deployment_surface["scanned"].append("tests/v80_p5_search_concurrency_runner.py")
    deployment_surface["findings"].extend(runner_findings)
    deployment_surface["listed_deployment_surfaces_absent_static_ast"] = not deployment_surface["findings"]
    spider = module.Spider()
    P5A._install_isolation_stubs(spider, observer)
    executors = ()
    destroy_state = {"called": False, "returned": False}
    rows = []
    failure = None
    operations = (
        ("foreground_capacity", lambda: _run_foreground_capacity(spider)),
        ("queued_cancellation", lambda: _run_queued_cancellation(spider)),
        ("job_owner", lambda: _run_job_owner(spider)),
        ("generation_writeback", lambda: _run_generation_writeback(spider, observer)),
        ("response_close", lambda: _run_response_close(spider, module)),
        ("resource_completion_isolation", lambda: _run_resource_completion_isolation(spider)),
        (
            "destroy_race",
            lambda: _run_destroy_race(
                spider, destroy_state, _executor_list(spider), module, observer,
            ),
        ),
    )
    try:
        spider.init({})
        executors = _executor_list(spider)
        observer.observe_credentials(spider)
        for name, operation in operations:
            try:
                rows.append(operation())
            except Exception as exc:
                rows.append(_failed_row(name, exc))
                if failure is None:
                    failure = _safe_error(exc)
    finally:
        if not destroy_state["called"]:
            try:
                _destroy_spider(spider, destroy_state)
            except Exception as exc:
                if failure is None:
                    failure = _safe_error(exc)
        if destroy_state["called"]:
            executors = _executor_list(spider)
            _wait_for(
                lambda: not any(
                    thread.is_alive()
                    for thread in _executor_worker_threads(executors)
                ),
                5.0,
            )
    closure = _candidate_closure(executed, state_before)
    cleanup = _cleanup_evidence(spider, _executor_list(spider), destroy_state)
    isolation = _isolation_evidence(observer, deployment_surface)
    workload = _workload_evidence(spider)
    passed = sum(row.get("status") == "passed" for row in rows)
    by_name = dict((row.get("name"), row) for row in rows)
    report = {
        "schema": REPORT_SCHEMA,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
        "evidence_provenance": _provenance_snapshot(),
        "candidate": candidate,
        "candidate_closure": closure,
        "workload": workload,
        "limitations": list(LIMITATIONS),
        "scenario_results": rows,
        "summary": {"total": len(SCENARIOS), "passed": passed, "failed": len(SCENARIOS) - passed},
        "invariants": {
            "foreground_bound": by_name.get("foreground_capacity", {}).get("status") == "passed",
            "capacity_plus_one_rejected": by_name.get("foreground_capacity", {}).get("metrics", {}).get("capacity_plus_one_rejected") is True,
            "queued_cancel_released_while_blocked": by_name.get("queued_cancellation", {}).get("metrics", {}).get("workers_blocked_during_replacement") is True,
            "job_owner_duplicate_preserved": by_name.get("job_owner", {}).get("metrics", {}).get("duplicate_owner_preserved") is True,
            "job_owner_submit_rejection_clean": by_name.get("job_owner", {}).get("metrics", {}).get("submit_rejection_owner_cleared") is True,
            "candidate_supplement_generation_fenced": (
                by_name.get("job_owner", {}).get("metrics", {}).get("candidate_scheduler_received_old_generation") is True
                and by_name.get("job_owner", {}).get("metrics", {}).get("candidate_job_registered_after_init") is False
            ),
            "generation_writeback_blocked": by_name.get("generation_writeback", {}).get("metrics", {}).get("cache_writes") == 0,
            "generation_queued_modes_fenced": by_name.get("generation_writeback", {}).get("metrics", {}).get("queued_mode_tasks_fenced") == 2,
            "generation_response_owner_once": (
                by_name.get("generation_writeback", {}).get("metrics", {}).get("response_close_calls") == 1
                and by_name.get("generation_writeback", {}).get("metrics", {}).get("response_double_closes") == 0
            ),
            "generation_executor_rotation": (
                by_name.get("generation_writeback", {}).get("metrics", {}).get("new_executor_identities_distinct") is True
                and by_name.get("generation_writeback", {}).get("metrics", {}).get("new_slot_identities_distinct") is True
            ),
            "generation_slots_released_once": (
                by_name.get("generation_writeback", {}).get("metrics", {}).get("foreground_slot_releases") == 2
                and by_name.get("generation_writeback", {}).get("metrics", {}).get("background_slot_releases") == 1
            ),
            "response_closed_once": by_name.get("response_close", {}).get("metrics", {}).get("exactly_once") is True,
            "resource_completion_isolated": by_name.get("resource_completion_isolation", {}).get("metrics", {}).get("foreground_non_blocking") is True,
            "instance_executors_isolated": by_name.get("destroy_race", {}).get("metrics", {}).get("new_executor_identities_distinct") is True,
            "destroy_slots_released_once": (
                by_name.get("destroy_race", {}).get("metrics", {}).get("foreground_slot_releases") == 1
                and by_name.get("destroy_race", {}).get("metrics", {}).get("background_slot_releases") == 1
            ),
            "destroy_race_quiescent": by_name.get("destroy_race", {}).get("metrics", {}).get("old_references_zero_after_release") is True,
            "cleanup_quiescent": _cleanup_is_admitted(cleanup),
            "candidate_stable_after_samples": closure.get("stable_after_samples") is True,
        },
        "isolation": isolation,
        "cleanup": cleanup,
        "failure": failure,
        "overall": "pending",
    }
    admitted = report_is_admitted(report, allow_pending=True)
    report["overall"] = "passed" if admitted else "failed"
    _require(report_is_admitted(report) is admitted, "final search concurrency admission state drifted")
    return report


def write_report(path, report):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    temp.replace(path)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json-out", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args(argv)
    report = run_search_concurrency()
    write_report(args.json_out, report)
    print(
        "V80 P5-5D search concurrency: %s, %d/%d scenarios passed (%s)"
        % ("passed" if report_is_admitted(report) else "failed", report["summary"]["passed"], report["summary"]["total"], args.json_out)
    )
    return 0 if report_is_admitted(report) else 1


if __name__ == "__main__":
    raise SystemExit(main())

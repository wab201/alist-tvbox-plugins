"""Measure deterministic cold, fresh, and stale cache behavior for V80."""

import argparse
import datetime as dt
import hashlib
import importlib.util
import json
import math
import os
import stat
import statistics
import sys
import tempfile
import threading
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
WORK_ROOT = (ROOT / "work").resolve()
BUILD_PATH = ROOT / "tools" / "build_follow_plugin.py"
MANIFEST_PATH = ROOT / "src" / "douban_tmdb_follow_single" / "release.json"
LIFECYCLE_RUNNER_PATH = ROOT / "tests" / "v80_p5_lifecycle_stability_runner.py"
DEFAULT_REPORT = WORK_ROOT / "v80-p5-cache-performance.json"
REPORT_SCHEMA = "v80-p5-cache-performance/2"
SAMPLE_COUNT = 32
TTL_SECONDS = 60
STALE_TTL_SECONDS = 3600
LOADER_WORK_MS = 250.0
SCENARIOS = ("cold_miss", "fresh_hot_hit", "stale_background_refresh")
MEASUREMENTS = (
    "cold_miss",
    "fresh_hot_hit",
    "stale_immediate_return",
    "controlled_refresh_commit",
    "post_refresh_hot_hit",
)
LIMITATIONS = (
    "synthetic_cache_control_path_only",
    "managed_requests_and_socket_surfaces_only",
    "no_real_network_or_device_latency",
    "no_provider_history_playback_or_detail_slo_claim",
    "host_timing_is_observational_not_admission",
    "report_freshness_requires_external_sha256_and_stage_closure",
)
COUNTER_NAMES = (
    "loader_calls",
    "cache_set_calls",
    "schedule_attempts",
    "schedule_accepted",
)
SCENARIO_CALLS = {
    "cold_miss": {
        "loader_calls": 1,
        "cache_set_calls": 1,
        "schedule_attempts": 0,
        "schedule_accepted": 0,
    },
    "fresh_hot_hit": {
        "loader_calls": 0,
        "cache_set_calls": 0,
        "schedule_attempts": 0,
        "schedule_accepted": 0,
    },
    "stale_background_refresh": {
        "loader_calls": 1,
        "cache_set_calls": 1,
        "schedule_attempts": 2,
        "schedule_accepted": 1,
    },
}
TOP_LEVEL_KEYS = {
    "schema", "generated_at", "evidence_provenance", "candidate",
    "candidate_closure", "workload", "limitations", "summary",
    "statistics", "invariants", "isolation", "cycle_results", "overall",
}
COMMON_ROW_KEYS = {"cycle", "scenario", "status", "calls", "tasks_enqueued"}
SIMPLE_ROW_KEYS = COMMON_ROW_KEYS | {
    "host_elapsed_us", "synthetic_work_ms", "result_version", "cache_entries",
}
STALE_ROW_KEYS = COMMON_ROW_KEYS | {
    "immediate_host_elapsed_us", "refresh_host_elapsed_us",
    "post_refresh_host_elapsed_us", "immediate_synthetic_work_ms",
    "refresh_synthetic_work_ms", "post_refresh_synthetic_work_ms",
    "stale_result_version", "duplicate_result_version",
    "refreshed_cache_version", "post_refresh_result_version",
    "before_release", "after_release",
}
ISOLATION_KEYS = {
    "scope", "network_guard", "task_mode", "request_attempts",
    "socket_connect_attempts", "network_requests",
    "credential_values_observed", "credentials_used",
    "persistence_write_attempts", "captured_task_enqueues",
    "captured_task_executions", "candidate_sleep_calls",
    "thread_start_attempts", "thread_starts_blocked",
}
_CANDIDATE_VALIDATION_CACHE = {}


class CachePerformanceAssertionError(AssertionError):
    pass


def _require(condition, detail):
    if not condition:
        raise CachePerformanceAssertionError(detail)


def _sha256_bytes(payload):
    return hashlib.sha256(payload).hexdigest().upper()


def _file_sha256(path):
    return _sha256_bytes(Path(path).read_bytes())


def _load(name, path):
    path = Path(path)
    payload = path.read_bytes()
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load required module")
    module = importlib.util.module_from_spec(spec)
    module.__dict__["__loaded_source_sha256__"] = _sha256_bytes(payload)
    exec(compile(payload, str(path), "exec"), module.__dict__)
    return module


_RUNNER_LOADED_SHA256 = globals().get("__loaded_source_sha256__")
if __name__ == "__main__" and _RUNNER_LOADED_SHA256 is None:
    _BOOTSTRAPPED = _load(
        "v80_p5_cache_performance_main", Path(__file__).resolve(),
    )
    raise SystemExit(_BOOTSTRAPPED.main())

LIFECYCLE = _load("v80_p5_cache_runtime_guard", LIFECYCLE_RUNNER_PATH)
BUILD = _load("v80_p5_cache_build", BUILD_PATH)
LIFECYCLE.BUILD = BUILD
LIFECYCLE._build_result.cache_clear()


def _loaded_inputs_are_current():
    if not isinstance(_RUNNER_LOADED_SHA256, str):
        return False
    try:
        return (
            _file_sha256(__file__) == _RUNNER_LOADED_SHA256
            and _file_sha256(LIFECYCLE_RUNNER_PATH)
            == LIFECYCLE.__loaded_source_sha256__
            and _file_sha256(BUILD_PATH) == BUILD.__loaded_source_sha256__
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
        "runtime_guard": _file_provenance(LIFECYCLE_RUNNER_PATH),
        "build_tool": _file_provenance(BUILD_PATH),
        "manifest": _file_provenance(MANIFEST_PATH),
    }


def _candidate_evidence_from(build):
    return {
        "size": build["size"],
        "sha256": build["sha256"],
        "output": str(build["output"].relative_to(ROOT)).replace("\\", "/"),
    }


def _executed_build():
    return BUILD.build_release(MANIFEST_PATH)


def _candidate_evidence():
    return _candidate_evidence_from(_executed_build())


def _runtime_module(observer, executed):
    original_build_result = LIFECYCLE._build_result
    try:
        LIFECYCLE._build_result = lambda: executed
        return LIFECYCLE._runtime_module(observer)
    finally:
        LIFECYCLE._build_result = original_build_result


def _output_evidence(path):
    path = Path(path)
    payload = path.read_bytes()
    return {
        "size": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest().upper(),
        "output": str(path.relative_to(ROOT)).replace("\\", "/"),
    }


def _candidate_state_sha256(output_path):
    paths = set((MANIFEST_PATH, Path(output_path)))
    paths.update(
        path for path in (ROOT / "src" / "douban_tmdb_follow_single").rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    )
    paths.update(
        path for path in (ROOT / "tools").glob("build_*.py")
        if path.is_file()
    )
    digest = hashlib.sha256()
    for path in sorted(paths, key=lambda item: str(item).lower()):
        relative = str(path.relative_to(ROOT)).replace("\\", "/")
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        if path.exists():
            digest.update(hashlib.sha256(path.read_bytes()).digest())
        else:
            digest.update(b"missing")
        digest.update(b"\0")
    return digest.hexdigest().upper()


def _candidate_closure(executed):
    _require(
        _loaded_inputs_are_current(),
        "loaded evidence inputs changed; start a new process",
    )
    state_before = _candidate_state_sha256(executed["output"])
    rebuilt = BUILD.build_release(MANIFEST_PATH)
    executed_evidence = _candidate_evidence_from(executed)
    rebuilt_evidence = _candidate_evidence_from(rebuilt)
    output_evidence = _output_evidence(rebuilt["output"])
    state_after = _candidate_state_sha256(rebuilt["output"])
    stable = (
        _loaded_inputs_are_current()
        and state_before == state_after
        and executed_evidence == rebuilt_evidence == output_evidence
    )
    if stable:
        _CANDIDATE_VALIDATION_CACHE[state_after] = dict(executed_evidence)
    return {
        "executed": executed_evidence,
        "rebuilt": rebuilt_evidence,
        "output": output_evidence,
        "state_before_sha256": state_before,
        "state_after_sha256": state_after,
        "stable_after_samples": stable,
    }


def _current_candidate_is_stable(candidate, expected_state):
    if not _loaded_inputs_are_current():
        return False
    output_path = ROOT / candidate["output"]
    state_before = _candidate_state_sha256(output_path)
    if state_before != expected_state:
        return False
    if _CANDIDATE_VALIDATION_CACHE.get(expected_state) == candidate:
        state_after = _candidate_state_sha256(output_path)
        return (
            state_after == expected_state
            and _loaded_inputs_are_current()
        )
    rebuilt = BUILD.build_release(MANIFEST_PATH)
    rebuilt_evidence = _candidate_evidence_from(rebuilt)
    output_evidence = _output_evidence(rebuilt["output"])
    state_after = _candidate_state_sha256(rebuilt["output"])
    stable = (
        _loaded_inputs_are_current()
        and state_before == state_after == expected_state
        and candidate == rebuilt_evidence == output_evidence
    )
    if stable:
        _CANDIDATE_VALIDATION_CACHE[expected_state] = dict(candidate)
    return stable


def _payloads():
    return {"v1": {"version": 1}, "v2": {"version": 2}}


def _workload_evidence():
    return {
        "owner": "candidate.v80_cache_load",
        "samples_per_scenario": SAMPLE_COUNT,
        "scenario_order": list(SCENARIOS),
        "ttl_seconds": TTL_SECONDS,
        "stale_ttl_seconds": STALE_TTL_SECONDS,
        "synthetic_loader_work_ms": LOADER_WORK_MS,
        "cache_scope": "non_persistable_memory_key",
        "task_mode": "captured_callback_manual_release",
        "payloads": {"v1": "fixed_version_1", "v2": "fixed_version_2"},
    }


class VirtualClock(object):
    def __init__(self, now):
        self.now = float(now)
        self.work_ms = 0.0
        self.sleep_calls = 0

    def time(self):
        return self.now

    def monotonic(self):
        return self.now

    def advance_seconds(self, seconds):
        self.now += float(seconds)

    def advance_work(self, milliseconds):
        value = float(milliseconds)
        self.work_ms += value
        self.now += value / 1000.0

    def sleep(self, seconds):
        self.sleep_calls += 1
        self.advance_seconds(seconds)

    def __getattr__(self, name):
        return getattr(time, name)


class ThreadStartGuard(object):
    def __init__(self):
        self.attempts = 0
        self.blocked = 0
        self._original = None

    def __enter__(self):
        self._original = threading.Thread.start
        guard = self

        def blocked_start(_thread, *_args, **_kwargs):
            guard.attempts += 1
            guard.blocked += 1
            raise CachePerformanceAssertionError("real thread start is forbidden")

        threading.Thread.start = blocked_start
        return self

    def __exit__(self, _exc_type, _exc, _traceback):
        threading.Thread.start = self._original


class CapturedTasks(object):
    def __init__(self):
        self.rows = []
        self.start_calls = 0
        self.run_calls = 0

    def start_thread(self, target, args=(), kwargs=None, name="background"):
        self.start_calls += 1
        self.rows.append((target, tuple(args or ()), dict(kwargs or {}), str(name)))
        return True

    def run_next(self):
        _require(len(self.rows) == 1, "exactly one captured task must be pending")
        target, args, kwargs, _name = self.rows.pop(0)
        self.run_calls += 1
        return target(*args, **kwargs)

    def clear(self):
        self.rows[:] = []


class OwnerProbe(object):
    def __init__(self, spider):
        self.spider = spider
        self.counts = {name: 0 for name in COUNTER_NAMES}
        self._install()

    def _install(self):
        spider = self.spider
        cache_set = spider._cache_set
        schedule = spider._schedule_cache_refresh

        def counted_set(*args, **kwargs):
            self.counts["cache_set_calls"] += 1
            return cache_set(*args, **kwargs)

        def counted_schedule(*args, **kwargs):
            self.counts["schedule_attempts"] += 1
            accepted = schedule(*args, **kwargs)
            if accepted:
                self.counts["schedule_accepted"] += 1
            return accepted

        spider._cache_set = counted_set
        spider._schedule_cache_refresh = counted_schedule

    def loader(self, clock, value):
        def load():
            self.counts["loader_calls"] += 1
            clock.advance_work(LOADER_WORK_MS)
            return value
        return load

    def unexpected_loader(self, value):
        def load():
            self.counts["loader_calls"] += 1
            return value
        return load

    def snapshot(self):
        return dict(self.counts)


def _counter_delta(before, after):
    return {name: after[name] - before[name] for name in COUNTER_NAMES}


def _elapsed_us(call):
    started = time.perf_counter_ns()
    result = call()
    elapsed = max(0, time.perf_counter_ns() - started) / 1000.0
    return result, round(elapsed, 3)


def _payload_version(value, payloads):
    if value == payloads["v1"]:
        return "v1"
    if value == payloads["v2"]:
        return "v2"
    return "unknown"


def _cache_entries(spider):
    with spider._cache_lock:
        return len(spider._cache)


def _cache_value(spider, key):
    with spider._cache_lock:
        item = spider._cache.get(key)
        return None if item is None else item[1]


def _refreshing_keys(spider):
    with spider._cache_lock:
        return len(spider._refreshing_cache_keys)


def _base_row(cycle, scenario):
    return {"cycle": cycle, "scenario": scenario, "status": "passed"}


def _cold_row(module, spider, probe, tasks, clock, key, payloads, cycle):
    before = probe.snapshot()
    work_before = clock.work_ms
    task_before = tasks.start_calls
    value, host_elapsed = _elapsed_us(lambda: module.v80_cache_load(
        spider, key, TTL_SECONDS, probe.loader(clock, payloads["v1"]),
    ))
    row = dict(_base_row(cycle, "cold_miss"), **{
        "host_elapsed_us": host_elapsed,
        "synthetic_work_ms": round(clock.work_ms - work_before, 3),
        "result_version": _payload_version(value, payloads),
        "calls": _counter_delta(before, probe.snapshot()),
        "tasks_enqueued": tasks.start_calls - task_before,
        "cache_entries": _cache_entries(spider),
    })
    if not _scenario_row_is_admitted(row, cycle):
        row["status"] = "failed"
    return row


def _fresh_row(module, spider, probe, tasks, clock, key, payloads, cycle):
    before = probe.snapshot()
    work_before = clock.work_ms
    task_before = tasks.start_calls
    value, host_elapsed = _elapsed_us(lambda: module.v80_cache_load(
        spider, key, TTL_SECONDS, probe.unexpected_loader(payloads["v2"]),
    ))
    row = dict(_base_row(cycle, "fresh_hot_hit"), **{
        "host_elapsed_us": host_elapsed,
        "synthetic_work_ms": round(clock.work_ms - work_before, 3),
        "result_version": _payload_version(value, payloads),
        "calls": _counter_delta(before, probe.snapshot()),
        "tasks_enqueued": tasks.start_calls - task_before,
        "cache_entries": _cache_entries(spider),
    })
    if not _scenario_row_is_admitted(row, cycle):
        row["status"] = "failed"
    return row


def _stale_row(module, spider, probe, tasks, clock, key, payloads, cycle):
    clock.advance_seconds(TTL_SECONDS + 1)
    before = probe.snapshot()
    work_before = clock.work_ms
    task_before = tasks.start_calls
    loader = probe.loader(clock, payloads["v2"])
    stale, immediate_host = _elapsed_us(lambda: module.v80_cache_load(
        spider, key, TTL_SECONDS, loader,
    ))
    duplicate = module.v80_cache_load(spider, key, TTL_SECONDS, loader)
    before_release = {
        "loader_calls": probe.counts["loader_calls"] - before["loader_calls"],
        "pending_tasks": len(tasks.rows),
        "refreshing_keys": _refreshing_keys(spider),
    }
    _unused, refresh_host = _elapsed_us(tasks.run_next)
    refreshed = _cache_value(spider, key)
    post_refresh, post_host = _elapsed_us(lambda: module.v80_cache_load(
        spider, key, TTL_SECONDS, probe.unexpected_loader(payloads["v1"]),
    ))
    after_release = {
        "loader_calls": probe.counts["loader_calls"] - before["loader_calls"],
        "pending_tasks": len(tasks.rows),
        "refreshing_keys": _refreshing_keys(spider),
        "cache_entries": _cache_entries(spider),
    }
    row = dict(_base_row(cycle, "stale_background_refresh"), **{
        "immediate_host_elapsed_us": immediate_host,
        "refresh_host_elapsed_us": refresh_host,
        "post_refresh_host_elapsed_us": post_host,
        "immediate_synthetic_work_ms": 0.0,
        "refresh_synthetic_work_ms": round(clock.work_ms - work_before, 3),
        "post_refresh_synthetic_work_ms": 0.0,
        "stale_result_version": _payload_version(stale, payloads),
        "duplicate_result_version": _payload_version(duplicate, payloads),
        "refreshed_cache_version": _payload_version(refreshed, payloads),
        "post_refresh_result_version": _payload_version(post_refresh, payloads),
        "before_release": before_release,
        "after_release": after_release,
        "calls": _counter_delta(before, probe.snapshot()),
        "tasks_enqueued": tasks.start_calls - task_before,
    })
    if not _scenario_row_is_admitted(row, cycle):
        row["status"] = "failed"
    return row


def _run_cycle(module, observer, cycle):
    clock = VirtualClock(2000000000.0 + cycle * 10000.0)
    module.time = clock
    spider = module.Spider()
    observer.observe_credentials(spider)
    persistence = {"attempts": 0}

    def block_persistence(*_args, **_kwargs):
        persistence["attempts"] += 1
        raise CachePerformanceAssertionError("persistence write is forbidden")

    spider.setCache = block_persistence
    original_tasks = spider._tasks
    tasks = CapturedTasks()
    spider._tasks = tasks
    spider.cache_ttl = TTL_SECONDS
    spider.stale_ttl = STALE_TTL_SECONDS
    spider._persistent_cache_loaded = True
    with spider._cache_lock:
        spider._cache.clear()
        spider._persistent_cache.clear()
        spider._failures.clear()
        spider._failure_attempts.clear()
        spider._refreshing_cache_keys.clear()
    spider._cache_health_controller._clock = clock.time
    probe = OwnerProbe(spider)
    payloads = _payloads()
    key = "p55b-memory:%d" % cycle
    try:
        rows = [
            _cold_row(module, spider, probe, tasks, clock, key, payloads, cycle),
            _fresh_row(module, spider, probe, tasks, clock, key, payloads, cycle),
            _stale_row(module, spider, probe, tasks, clock, key, payloads, cycle),
        ]
        _require(not tasks.rows, "captured tasks must be drained")
    finally:
        tasks.clear()
        spider._tasks = original_tasks
        spider.destroy()
    return (
        rows, clock.sleep_calls, tasks.start_calls, tasks.run_calls,
        persistence["attempts"],
    )


def _is_int(value):
    return type(value) is int


def _is_number(value):
    return type(value) in (int, float) and math.isfinite(float(value))


def _valid_elapsed(value):
    return _is_number(value) and value >= 0


def _exact_int_dict(value, expected):
    return (
        isinstance(value, dict)
        and set(value) == set(expected)
        and all(_is_int(value[name]) and value[name] == expected[name] for name in expected)
    )


def _scenario_row_is_admitted(row, cycle):
    if not isinstance(row, dict) or not _is_int(row.get("cycle")):
        return False
    if row.get("cycle") != cycle or row.get("status") != "passed":
        return False
    scenario = row.get("scenario")
    expected_calls = SCENARIO_CALLS.get(scenario)
    if expected_calls is None or not _exact_int_dict(row.get("calls"), expected_calls):
        return False
    if not _is_int(row.get("tasks_enqueued")):
        return False
    if scenario in ("cold_miss", "fresh_hot_hit"):
        if set(row) != SIMPLE_ROW_KEYS:
            return False
        return (
            _valid_elapsed(row.get("host_elapsed_us"))
            and row.get("synthetic_work_ms") == (
                LOADER_WORK_MS if scenario == "cold_miss" else 0.0
            )
            and row.get("result_version") == "v1"
            and row.get("tasks_enqueued") == 0
            and _is_int(row.get("cache_entries"))
            and row.get("cache_entries") == 1
        )
    if scenario != "stale_background_refresh" or set(row) != STALE_ROW_KEYS:
        return False
    return (
        all(_valid_elapsed(row.get(name)) for name in (
            "immediate_host_elapsed_us", "refresh_host_elapsed_us",
            "post_refresh_host_elapsed_us",
        ))
        and row.get("immediate_synthetic_work_ms") == 0.0
        and row.get("refresh_synthetic_work_ms") == LOADER_WORK_MS
        and row.get("post_refresh_synthetic_work_ms") == 0.0
        and row.get("stale_result_version") == "v1"
        and row.get("duplicate_result_version") == "v1"
        and row.get("refreshed_cache_version") == "v2"
        and row.get("post_refresh_result_version") == "v2"
        and _exact_int_dict(row.get("before_release"), {
            "loader_calls": 0, "pending_tasks": 1, "refreshing_keys": 1,
        })
        and _exact_int_dict(row.get("after_release"), {
            "loader_calls": 1, "pending_tasks": 0,
            "refreshing_keys": 0, "cache_entries": 1,
        })
        and row.get("tasks_enqueued") == 1
    )


def _series_values(rows, measurement):
    if measurement in ("cold_miss", "fresh_hot_hit"):
        selected = [row for row in rows if row.get("scenario") == measurement]
        return (
            [row.get("host_elapsed_us") for row in selected],
            [row.get("synthetic_work_ms") for row in selected],
        )
    selected = [row for row in rows if row.get("scenario") == "stale_background_refresh"]
    fields = {
        "stale_immediate_return": (
            "immediate_host_elapsed_us", "immediate_synthetic_work_ms",
        ),
        "controlled_refresh_commit": (
            "refresh_host_elapsed_us", "refresh_synthetic_work_ms",
        ),
        "post_refresh_hot_hit": (
            "post_refresh_host_elapsed_us", "post_refresh_synthetic_work_ms",
        ),
    }
    host_name, work_name = fields[measurement]
    return (
        [row.get(host_name) for row in selected],
        [row.get(work_name) for row in selected],
    )


def _distribution(values, source, fixture_expectation):
    if not values or not all(_valid_elapsed(value) for value in values):
        metrics = {"min": None, "median": None, "p95": None, "max": None}
    else:
        ordered = sorted(float(value) for value in values)
        index = max(0, (95 * len(ordered) + 99) // 100 - 1)
        metrics = {
            "min": round(ordered[0], 3),
            "median": round(statistics.median(ordered), 3),
            "p95": round(ordered[index], 3),
            "max": round(ordered[-1], 3),
        }
    return dict({
        "samples": len(values),
        "source": source,
        "fixture_expectation": fixture_expectation,
    }, **metrics)


def _statistics_from_rows(rows):
    result = {}
    for measurement in MEASUREMENTS:
        host, work = _series_values(rows, measurement)
        result[measurement] = {
            "host_elapsed_us": _distribution(
                host, "host_perf_counter_observation", False,
            ),
            "synthetic_work_ms": _distribution(
                work, "virtual_clock_fixture", True,
            ),
        }
    return result


def _summary_from_rows(rows):
    passed = sum(row.get("status") == "passed" for row in rows)
    return {
        "scenario_count": len(SCENARIOS),
        "samples_per_scenario": SAMPLE_COUNT,
        "total": len(rows),
        "passed": passed,
        "failed": len(rows) - passed,
    }


def _summary_is_admitted(summary):
    expected = {
        "scenario_count": 3,
        "samples_per_scenario": SAMPLE_COUNT,
        "total": SAMPLE_COUNT * 3,
        "passed": SAMPLE_COUNT * 3,
        "failed": 0,
    }
    return _exact_int_dict(summary, expected)


def _rows_are_complete(rows):
    if not isinstance(rows, list) or len(rows) != SAMPLE_COUNT * len(SCENARIOS):
        return False
    offset = 0
    for cycle in range(1, SAMPLE_COUNT + 1):
        for scenario in SCENARIOS:
            row = rows[offset]
            if row.get("scenario") != scenario or not _scenario_row_is_admitted(row, cycle):
                return False
            offset += 1
    return True


def _statistics_are_valid(statistics):
    if not isinstance(statistics, dict) or set(statistics) != set(MEASUREMENTS):
        return False
    for measurement in MEASUREMENTS:
        sections = statistics.get(measurement)
        if not isinstance(sections, dict) or set(sections) != {
                "host_elapsed_us", "synthetic_work_ms"}:
            return False
        for name, expected_source, expected_fixture in (
                ("host_elapsed_us", "host_perf_counter_observation", False),
                ("synthetic_work_ms", "virtual_clock_fixture", True)):
            section = sections[name]
            if not isinstance(section, dict) or set(section) != {
                    "samples", "source", "fixture_expectation",
                    "min", "median", "p95", "max"}:
                return False
            if not _is_int(section.get("samples")) or section["samples"] != SAMPLE_COUNT:
                return False
            if section.get("source") != expected_source:
                return False
            if type(section.get("fixture_expectation")) is not bool:
                return False
            if section["fixture_expectation"] is not expected_fixture:
                return False
            values = tuple(section.get(field) for field in ("min", "median", "p95", "max"))
            if not all(_valid_elapsed(value) for value in values):
                return False
            if not values[0] <= values[1] <= values[2] <= values[3]:
                return False
    return True


def _isolation_is_admitted(isolation):
    if not isinstance(isolation, dict) or set(isolation) != ISOLATION_KEYS:
        return False
    integer_fields = ISOLATION_KEYS - {
        "scope", "network_guard", "task_mode", "credentials_used",
    }
    return (
        isolation.get("scope") == "candidate_cache_owner"
        and isolation.get("network_guard") == "requests_and_socket_import_surfaces"
        and isolation.get("task_mode") == "captured_callback_manual_release"
        and all(_is_int(isolation.get(name)) and isolation[name] >= 0 for name in integer_fields)
        and isolation.get("request_attempts") == 0
        and isolation.get("socket_connect_attempts") == 0
        and isolation.get("network_requests") == 0
        and isolation.get("credential_values_observed") == 0
        and type(isolation.get("credentials_used")) is bool
        and isolation.get("credentials_used") is False
        and isolation.get("persistence_write_attempts") == 0
        and isolation.get("captured_task_enqueues") == SAMPLE_COUNT
        and isolation.get("captured_task_executions") == SAMPLE_COUNT
        and isolation.get("candidate_sleep_calls") == 0
        and isolation.get("thread_start_attempts") == 0
        and isolation.get("thread_starts_blocked") == 0
    )


def _candidate_closure_is_admitted(closure, candidate):
    if not isinstance(closure, dict) or set(closure) != {
            "executed", "rebuilt", "output", "state_before_sha256",
            "state_after_sha256", "stable_after_samples"}:
        return False
    state_before = closure.get("state_before_sha256")
    state_after = closure.get("state_after_sha256")
    return (
        closure.get("executed") == candidate
        and closure.get("rebuilt") == candidate
        and closure.get("output") == candidate
        and isinstance(state_before, str)
        and len(state_before) == 64
        and all(value in "0123456789ABCDEF" for value in state_before)
        and state_after == state_before
        and type(closure.get("stable_after_samples")) is bool
        and closure.get("stable_after_samples") is True
    )


def _invariants_from(rows, statistics, isolation, closure, candidate):
    return {
        "rows_complete": _rows_are_complete(rows),
        "statistics_recomputed": statistics == _statistics_from_rows(rows),
        "isolation_observed": _isolation_is_admitted(isolation),
        "candidate_stable_after_samples": _candidate_closure_is_admitted(
            closure, candidate,
        ),
    }


def _generated_at_is_admitted(value):
    if not isinstance(value, str) or not value.endswith("Z"):
        return False
    try:
        parsed = dt.datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return False
    return parsed.tzinfo is not None


def report_is_admitted(report, allow_pending=False):
    if not isinstance(report, dict) or set(report) != TOP_LEVEL_KEYS:
        return False
    rows = report.get("cycle_results")
    statistics = report.get("statistics")
    isolation = report.get("isolation")
    candidate = report.get("candidate")
    closure = report.get("candidate_closure")
    invariants = report.get("invariants")
    expected_invariants = None
    if isinstance(rows, list):
        expected_invariants = _invariants_from(
            rows, statistics, isolation, closure, candidate,
        )
    return (
        (report.get("overall") == "passed" or (
            allow_pending and report.get("overall") == "pending"))
        and report.get("schema") == REPORT_SCHEMA
        and _generated_at_is_admitted(report.get("generated_at"))
        and _loaded_inputs_are_current()
        and candidate == _candidate_evidence()
        and _candidate_closure_is_admitted(closure, candidate)
        and report.get("evidence_provenance") == _evidence_provenance()
        and report.get("workload") == _workload_evidence()
        and report.get("limitations") == list(LIMITATIONS)
        and _rows_are_complete(rows)
        and report.get("summary") == _summary_from_rows(rows)
        and _summary_is_admitted(report.get("summary"))
        and statistics == _statistics_from_rows(rows)
        and _statistics_are_valid(statistics)
        and invariants == expected_invariants
        and isinstance(invariants, dict)
        and set(invariants) == {
            "rows_complete", "statistics_recomputed", "isolation_observed",
            "candidate_stable_after_samples",
        }
        and all(type(value) is bool and value is True for value in invariants.values())
        and _isolation_is_admitted(isolation)
        and _current_candidate_is_stable(
            candidate, closure["state_after_sha256"],
        )
    )


def run_cache_performance():
    _require(
        _loaded_inputs_are_current(),
        "loaded evidence inputs changed; start a new process",
    )
    provenance = _evidence_provenance()
    workload = _workload_evidence()
    executed = _executed_build()
    rows = []
    sleep_calls = 0
    task_enqueues = 0
    task_executions = 0
    persistence_attempts = 0
    LIFECYCLE.FakeSession.instances = []
    observer = LIFECYCLE.IsolationObserver()
    with ThreadStartGuard() as thread_guard:
        module = _runtime_module(observer, executed)
        for cycle in range(1, SAMPLE_COUNT + 1):
            try:
                result = _run_cycle(module, observer, cycle)
            except Exception as exc:
                rows.append({
                    "cycle": cycle,
                    "scenario": "runner_failure",
                    "status": "failed",
                    "error_type": type(exc).__name__,
                    "error": "scenario execution failed",
                })
                break
            cycle_rows, sleeps, enqueues, executions, writes = result
            rows.extend(cycle_rows)
            sleep_calls += sleeps
            task_enqueues += enqueues
            task_executions += executions
            persistence_attempts += writes
    observation = observer.snapshot()
    isolation = {
        "scope": "candidate_cache_owner",
        "network_guard": "requests_and_socket_import_surfaces",
        "task_mode": "captured_callback_manual_release",
        "request_attempts": observation["request_attempts"],
        "socket_connect_attempts": observation["socket_connect_attempts"],
        "network_requests": observation["network_requests"],
        "credential_values_observed": observation["credential_values_observed"],
        "credentials_used": observation["credentials_used"],
        "persistence_write_attempts": persistence_attempts,
        "captured_task_enqueues": task_enqueues,
        "captured_task_executions": task_executions,
        "candidate_sleep_calls": sleep_calls,
        "thread_start_attempts": thread_guard.attempts,
        "thread_starts_blocked": thread_guard.blocked,
    }
    candidate = _candidate_evidence_from(executed)
    closure = _candidate_closure(executed)
    statistics = _statistics_from_rows(rows)
    invariants = _invariants_from(rows, statistics, isolation, closure, candidate)
    report = {
        "schema": REPORT_SCHEMA,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
        "evidence_provenance": provenance,
        "candidate": candidate,
        "candidate_closure": closure,
        "workload": workload,
        "limitations": list(LIMITATIONS),
        "summary": _summary_from_rows(rows),
        "statistics": statistics,
        "invariants": invariants,
        "isolation": isolation,
        "cycle_results": rows,
        "overall": "pending",
    }
    admitted = report_is_admitted(report, allow_pending=True)
    report["overall"] = "passed" if admitted else "failed"
    if report_is_admitted(report) is not admitted:
        raise CachePerformanceAssertionError("final cache performance admission state drifted")
    return report


def _is_link_or_reparse(path):
    try:
        info = os.lstat(str(path))
    except FileNotFoundError:
        return False
    attributes = getattr(info, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return stat.S_ISLNK(info.st_mode) or bool(attributes & reparse_flag)


def _verify_no_reparse_components(path):
    absolute = Path(os.path.abspath(str(path)))
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current = current / part
        if (current.exists() or current.is_symlink()) and _is_link_or_reparse(current):
            raise CachePerformanceAssertionError("report path contains a link or reparse point")


def _assert_report_path_allowed(path):
    path = Path(os.path.abspath(str(path)))
    _verify_no_reparse_components(path)
    resolved = path.resolve(strict=False)
    work_root = Path(WORK_ROOT).resolve()
    try:
        resolved.relative_to(work_root)
    except ValueError:
        raise CachePerformanceAssertionError("report path must be inside work")
    if resolved.suffix.lower() != ".json":
        raise CachePerformanceAssertionError("report path must end in .json")
    if resolved.exists() or resolved.is_symlink():
        raise CachePerformanceAssertionError("report path must be new")
    return resolved


def write_report(path, report):
    approved = _assert_report_path_allowed(path)
    approved.parent.mkdir(parents=True, exist_ok=True)
    if _assert_report_path_allowed(approved) != approved:
        raise CachePerformanceAssertionError("report target changed while preparing parent")
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", newline="\n",
                prefix=approved.name + ".", suffix=".tmp",
                dir=str(approved.parent), delete=False) as handle:
            temp_path = Path(handle.name)
            json.dump(report, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        if _is_link_or_reparse(temp_path):
            raise CachePerformanceAssertionError("temporary report became a link")
        if _assert_report_path_allowed(approved) != approved:
            raise CachePerformanceAssertionError("report target changed before publish")
        os.link(str(temp_path), str(approved))
    finally:
        if temp_path is not None and temp_path.exists() and not _is_link_or_reparse(temp_path):
            temp_path.unlink()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json-out", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args(argv)
    try:
        report = run_cache_performance()
        admitted = report_is_admitted(report)
        write_report(args.json_out, report)
    except Exception as exc:
        print(
            "V80 P5 cache performance: failed (%s)" % type(exc).__name__,
            file=sys.stderr,
        )
        return 2
    summary = report["summary"]
    print(
        "V80 P5 cache performance: %s, %d/%d samples passed (%s)"
        % (
            "passed" if admitted else "failed",
            summary["passed"], summary["total"], args.json_out,
        )
    )
    return 0 if admitted else 1


if __name__ == "__main__":
    raise SystemExit(main())

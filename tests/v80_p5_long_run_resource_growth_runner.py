"""Measure bounded resource growth for one long-lived V80 Spider."""

import argparse
import datetime as dt
import gc
import hashlib
import importlib.util
import sys
import tracemalloc
import weakref
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
P5B_RUNNER_PATH = ROOT / "tests" / "v80_p5_cache_performance_runner.py"
DEFAULT_REPORT = ROOT / "work" / "v80-p5-long-run-resource-growth.json"
REPORT_SCHEMA = "v80-p5-long-run-resource-growth/2"
DEFAULT_WARMUP_OPERATIONS = 256
DEFAULT_CHECKPOINT_COUNT = 32
DEFAULT_OPERATIONS_PER_CHECKPOINT = 128
CACHE_MAX_ENTRIES = 256
CACHE_TTL_SECONDS = 60
EXPECTED_TASK_EXECUTORS = 6
CANDIDATE_TRACE_FILENAME = "v80-p5-lifecycle-runtime.py"
LIMITATIONS = (
    "sequential_single_spider_owner_path_only",
    "candidate_filename_tracemalloc_is_observational_not_admission",
    "candidate_filename_trace_excludes_runner_payloads_and_native_memory",
    "managed_requests_and_socket_surfaces_only",
    "no_real_network_concurrent_search_playback_history_or_device_slo",
    "operation_count_baseline_not_wall_clock_endurance",
    "report_freshness_requires_external_sha256_and_stage_closure",
)
TOP_LEVEL_KEYS = {
    "schema", "generated_at", "evidence_provenance", "candidate",
    "candidate_closure", "workload", "limitations", "warmup",
    "checkpoint_results", "memory", "summary", "invariants",
    "isolation", "cleanup", "failure", "overall",
}
WORKLOAD_KEYS = {
    "owner", "scenario", "warmup_operations", "checkpoint_count",
    "operations_per_checkpoint", "measured_operations",
    "total_operations", "cache_max_entries", "cache_key_policy",
    "cache_call_pattern", "diagnostic_owner", "response_owner",
    "task_mode", "formal_profile",
}
SAMPLE_KEYS = {
    "checkpoint", "phase", "status", "operations_total", "generation",
    "candidate_traced_bytes", "candidate_sampled_peak_bytes", "cache_entries",
    "persistent_cache_entries", "failure_entries",
    "failure_attempt_entries", "diagnostic_events", "loader_calls",
    "hot_loader_calls", "cache_calls", "responses_created",
    "responses_closed", "response_double_closes", "response_weakrefs_alive",
    "timeout_active", "reference_counts", "task_threads", "task_timers",
    "task_executors", "task_worker_threads", "captured_task_attempts",
    "captured_tasks_pending", "sessions_created_total", "sessions_open",
}
MEMORY_KEYS = {
    "source", "trace_filename", "admission_threshold",
    "baseline_candidate_bytes", "baseline_sampled_peak_bytes",
    "final_candidate_bytes", "final_sampled_peak_bytes",
    "delta_candidate_bytes", "sample_count",
}
SUMMARY_KEYS = {
    "warmup_operations", "warmup_passed", "checkpoint_count",
    "passed_checkpoints", "failed_checkpoints", "operations_per_checkpoint",
    "measured_operations", "total_operations", "cache_calls", "loader_calls",
}
INVARIANT_KEYS = {
    "profile_complete", "single_generation", "cache_and_diagnostics_bounded",
    "responses_closed_and_collected", "timeout_scopes_released",
    "task_owners_stable", "reference_owners_empty", "memory_observed",
    "isolation_observed", "destroy_references_cleared",
    "candidate_stable_after_samples",
}
ISOLATION_KEYS = {
    "scope", "session_factory", "network_guard", "task_mode",
    "request_attempts", "socket_connect_attempts", "network_requests",
    "credential_values_observed", "credentials_used",
    "production_persistence_calls", "production_persistence_calls_blocked",
    "production_writes", "set_cache_attempts", "candidate_sleep_calls",
    "thread_start_attempts", "thread_starts_blocked",
    "captured_task_attempts", "captured_tasks_pending", "spider_instances",
}
CLEANUP_KEYS = {
    "destroy_called", "destroy_succeeded", "session_references_retained",
    "sessions_created_total", "sessions_closed_once", "task_threads",
    "task_timers", "task_executors", "task_worker_threads",
    "timeout_active", "timeout_closed", "reference_counts",
    "captured_tasks_pending", "response_weakrefs_alive",
}


class ResourceGrowthAssertionError(AssertionError):
    pass


def _require(condition, detail):
    if not condition:
        raise ResourceGrowthAssertionError(detail)


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
        "v80_p5_long_run_resource_growth_main", Path(__file__).resolve(),
    )
    raise SystemExit(_BOOTSTRAPPED.main())


P5B = _load("v80_p5_long_run_resource_growth_p5b", P5B_RUNNER_PATH)
P5A = P5B.LIFECYCLE
BUILD = P5B.BUILD
BUILD_PATH = P5B.BUILD_PATH
MANIFEST_PATH = P5B.MANIFEST_PATH
P5A_RUNNER_PATH = P5B.LIFECYCLE_RUNNER_PATH
_MANIFEST_LOADED_SHA256 = _file_sha256(MANIFEST_PATH)
REFERENCE_NAMES = tuple(P5A.REFERENCE_FIELDS + P5A.REFERENCE_SCALAR_FIELDS)


def _loaded_inputs_are_current():
    if not isinstance(_RUNNER_LOADED_SHA256, str):
        return False
    try:
        return (
            _file_sha256(__file__) == _RUNNER_LOADED_SHA256
            and _file_sha256(P5B_RUNNER_PATH) == P5B.__loaded_source_sha256__
            and _file_sha256(P5A_RUNNER_PATH) == P5A.__loaded_source_sha256__
            and _file_sha256(BUILD_PATH) == BUILD.__loaded_source_sha256__
            and _file_sha256(MANIFEST_PATH) == _MANIFEST_LOADED_SHA256
            and P5A.BUILD is BUILD
            and P5B._loaded_inputs_are_current()
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
        "p5b_runner": _file_provenance(P5B_RUNNER_PATH),
        "p5a_runner": _file_provenance(P5A_RUNNER_PATH),
        "build_tool": _file_provenance(BUILD_PATH),
        "manifest": _file_provenance(MANIFEST_PATH),
    }


def _is_int(value):
    return type(value) is int


def _profile(warmup_operations, checkpoint_count, operations_per_checkpoint):
    values = (warmup_operations, checkpoint_count, operations_per_checkpoint)
    if not all(_is_int(value) for value in values):
        raise ValueError("long-run profile values must be integers")
    if not 1 <= warmup_operations <= DEFAULT_WARMUP_OPERATIONS:
        raise ValueError("warmup operations are outside the fixed test range")
    if not 1 <= checkpoint_count <= DEFAULT_CHECKPOINT_COUNT:
        raise ValueError("checkpoint count is outside the fixed test range")
    if not 1 <= operations_per_checkpoint <= DEFAULT_OPERATIONS_PER_CHECKPOINT:
        raise ValueError("checkpoint operations are outside the fixed test range")
    return {
        "warmup_operations": warmup_operations,
        "checkpoint_count": checkpoint_count,
        "operations_per_checkpoint": operations_per_checkpoint,
    }


def _workload_evidence(profile):
    measured = profile["checkpoint_count"] * profile["operations_per_checkpoint"]
    total = profile["warmup_operations"] + measured
    return {
        "owner": "candidate.long_lived_spider",
        "scenario": "sequential_bounded_owner_churn",
        "warmup_operations": profile["warmup_operations"],
        "checkpoint_count": profile["checkpoint_count"],
        "operations_per_checkpoint": profile["operations_per_checkpoint"],
        "measured_operations": measured,
        "total_operations": total,
        "cache_max_entries": CACHE_MAX_ENTRIES,
        "cache_key_policy": "unique_non_persistable",
        "cache_call_pattern": ["cold_miss", "fresh_hot_hit"],
        "diagnostic_owner": "Spider._diagnostic_event",
        "response_owner": "TimeoutOperation.track_close_tracked",
        "task_mode": "captured_start_thread_no_execution",
        "formal_profile": profile == {
            "warmup_operations": DEFAULT_WARMUP_OPERATIONS,
            "checkpoint_count": DEFAULT_CHECKPOINT_COUNT,
            "operations_per_checkpoint": DEFAULT_OPERATIONS_PER_CHECKPOINT,
        },
    }


class ResponseObserver(object):
    def __init__(self):
        self.created = 0
        self.closed = 0
        self.double_closes = 0
        self.live = weakref.WeakSet()


class FakeResponse(object):
    __slots__ = ("observer", "close_calls", "__weakref__")

    def __init__(self, observer):
        self.observer = observer
        self.close_calls = 0
        observer.created += 1
        observer.live.add(self)

    def close(self):
        self.close_calls += 1
        if self.close_calls == 1:
            self.observer.closed += 1
        else:
            self.observer.double_closes += 1


def _zero_reference_counts():
    return {name: 0 for name in REFERENCE_NAMES}


def _zero_reference_counts_are_admitted(value):
    return (
        isinstance(value, dict)
        and set(value) == set(REFERENCE_NAMES)
        and all(type(value[name]) is int and value[name] == 0 for name in REFERENCE_NAMES)
    )


def _reference_counts(spider):
    return P5A._reference_counts(spider)


def _task_counts(tasks):
    with tasks._lock:
        threads = tuple(tasks._threads)
        timers = tuple(tasks._timers)
        executors = tuple(tasks._executors)
    workers = tuple(
        thread
        for executor in executors
        for thread in tuple(getattr(executor, "_threads", ()))
    )
    return {
        "task_threads": len(threads),
        "task_timers": len(timers),
        "task_executors": len(executors),
        "task_worker_threads": sum(thread.is_alive() for thread in workers),
    }


def _session_counts(spider):
    current = (spider._session, spider._tmdb_session, spider._atvp_session)
    return len(P5A.FakeSession.instances), sum(session is not None for session in current)


def _candidate_traced_bytes():
    snapshot = tracemalloc.take_snapshot()
    filtered = snapshot.filter_traces((
        tracemalloc.Filter(True, "*" + CANDIDATE_TRACE_FILENAME),
    ))
    try:
        return sum(trace.size for trace in filtered.traces)
    finally:
        del filtered
        del snapshot


def _operate_once(module, spider, response_observer, counters, operation_index):
    key = "p55c-memory:%08d" % operation_index
    payload = {"sequence": operation_index}

    def cold_loader():
        counters["loader_calls"] += 1
        return payload

    cold = module.v80_cache_load(spider, key, CACHE_TTL_SECONDS, cold_loader)
    counters["cache_calls"] += 1
    _require(cold == payload, "cold cache result drifted")

    def forbidden_hot_loader():
        counters["hot_loader_calls"] += 1
        raise ResourceGrowthAssertionError("fresh cache unexpectedly called loader")

    hot = module.v80_cache_load(
        spider, key, CACHE_TTL_SECONDS, forbidden_hot_loader,
    )
    counters["cache_calls"] += 1
    _require(hot == payload, "hot cache result drifted")

    with spider._v80_timeout_child_scope("p55c_resource_growth", 5.0) as operation:
        event = spider._diagnostic_event(
            "cache.long_run", count="%08d" % operation_index,
        )
        _require(isinstance(event, dict), "diagnostic event was not recorded")
        response = FakeResponse(response_observer)
        operation.track(response)
        _require(len(operation._tracked) == 1, "response was not tracked once")
        _require(operation.close_tracked(response), "tracked response did not close")
        _require(not operation._tracked, "response reference remained tracked")
        del response
    _require(
        spider._timeout_budget_controller.snapshot()["active"] == 0,
        "timeout operation remained active",
    )


def _sample(
        spider, response_observer, counters, captured, memory_state, checkpoint,
        phase, operations_total):
    gc.collect()
    candidate_bytes = _candidate_traced_bytes()
    memory_state["sampled_peak_bytes"] = max(
        memory_state["sampled_peak_bytes"], candidate_bytes,
    )
    with spider._cache_lock:
        cache_entries = len(spider._cache)
        persistent_entries = len(spider._persistent_cache)
        failure_entries = len(spider._failures)
        failure_attempt_entries = len(spider._failure_attempts)
    with spider._diagnostic_lock:
        diagnostic_events = len(spider._diagnostics)
    sessions_created, sessions_open = _session_counts(spider)
    row = {
        "checkpoint": checkpoint,
        "phase": phase,
        "status": "passed",
        "operations_total": operations_total,
        "generation": spider._cache_generation,
        "candidate_traced_bytes": candidate_bytes,
        "candidate_sampled_peak_bytes": memory_state["sampled_peak_bytes"],
        "cache_entries": cache_entries,
        "persistent_cache_entries": persistent_entries,
        "failure_entries": failure_entries,
        "failure_attempt_entries": failure_attempt_entries,
        "diagnostic_events": diagnostic_events,
        "loader_calls": counters["loader_calls"],
        "hot_loader_calls": counters["hot_loader_calls"],
        "cache_calls": counters["cache_calls"],
        "responses_created": response_observer.created,
        "responses_closed": response_observer.closed,
        "response_double_closes": response_observer.double_closes,
        "response_weakrefs_alive": len(response_observer.live),
        "timeout_active": spider._timeout_budget_controller.snapshot()["active"],
        "reference_counts": _reference_counts(spider),
        "captured_task_attempts": captured["attempts"],
        "captured_tasks_pending": len(captured["rows"]),
        "sessions_created_total": sessions_created,
        "sessions_open": sessions_open,
    }
    row.update(_task_counts(spider._tasks))
    return row


def _sample_is_admitted(row, workload, checkpoint, phase, generation):
    if not isinstance(row, dict) or set(row) != SAMPLE_KEYS:
        return False
    operations_total = (
        workload["warmup_operations"]
        if checkpoint == 0
        else workload["warmup_operations"]
        + checkpoint * workload["operations_per_checkpoint"]
    )
    bounded_count = min(CACHE_MAX_ENTRIES, operations_total)
    integer_fields = SAMPLE_KEYS - {"phase", "status", "reference_counts"}
    return (
        all(_is_int(row.get(name)) for name in integer_fields)
        and row.get("checkpoint") == checkpoint
        and row.get("phase") == phase
        and row.get("status") == "passed"
        and row.get("operations_total") == operations_total
        and row.get("generation") == generation
        and generation > 0
        and row.get("candidate_traced_bytes") >= 0
        and row.get("candidate_sampled_peak_bytes") >= row.get("candidate_traced_bytes")
        and row.get("cache_entries") == bounded_count
        and row.get("persistent_cache_entries") == 0
        and row.get("failure_entries") == 0
        and row.get("failure_attempt_entries") == 0
        and row.get("diagnostic_events") == bounded_count
        and row.get("loader_calls") == operations_total
        and row.get("hot_loader_calls") == 0
        and row.get("cache_calls") == operations_total * 2
        and row.get("responses_created") == operations_total
        and row.get("responses_closed") == operations_total
        and row.get("response_double_closes") == 0
        and row.get("response_weakrefs_alive") == 0
        and row.get("timeout_active") == 0
        and _zero_reference_counts_are_admitted(row.get("reference_counts"))
        and row.get("task_threads") == 0
        and row.get("task_timers") == 0
        and row.get("task_executors") == EXPECTED_TASK_EXECUTORS
        and row.get("task_worker_threads") == 0
        and row.get("captured_task_attempts") == 0
        and row.get("captured_tasks_pending") == 0
        and row.get("sessions_created_total") == 6
        and row.get("sessions_open") == 3
    )


def _workload_is_admitted(workload):
    if not isinstance(workload, dict) or set(workload) != WORKLOAD_KEYS:
        return False
    try:
        profile = _profile(
            workload.get("warmup_operations"),
            workload.get("checkpoint_count"),
            workload.get("operations_per_checkpoint"),
        )
    except ValueError:
        return False
    return workload == _workload_evidence(profile)


def _samples_are_admitted(warmup, rows, workload):
    if not isinstance(warmup, dict) or not isinstance(rows, list):
        return False
    if len(rows) != workload["checkpoint_count"]:
        return False
    generation = warmup.get("generation")
    if not _sample_is_admitted(warmup, workload, 0, "warmup", generation):
        return False
    return all(
        _sample_is_admitted(row, workload, index, "checkpoint", generation)
        for index, row in enumerate(rows, 1)
    )


def _memory_is_admitted(memory, warmup, rows):
    if not isinstance(memory, dict) or set(memory) != MEMORY_KEYS or not rows:
        return False
    integer_fields = MEMORY_KEYS - {
        "source", "trace_filename", "admission_threshold",
    }
    if not all(_is_int(memory.get(name)) for name in integer_fields):
        return False
    final = rows[-1]
    return (
        memory.get("source") == "python_tracemalloc_candidate_filename_observation"
        and memory.get("trace_filename") == CANDIDATE_TRACE_FILENAME
        and type(memory.get("admission_threshold")) is bool
        and memory.get("admission_threshold") is False
        and memory.get("baseline_candidate_bytes") == warmup["candidate_traced_bytes"]
        and memory.get("baseline_sampled_peak_bytes") == warmup["candidate_sampled_peak_bytes"]
        and memory.get("final_candidate_bytes") == final["candidate_traced_bytes"]
        and memory.get("final_sampled_peak_bytes") == final["candidate_sampled_peak_bytes"]
        and memory.get("delta_candidate_bytes") == (
            final["candidate_traced_bytes"] - warmup["candidate_traced_bytes"]
        )
        and memory.get("sample_count") == len(rows) + 1
        and memory.get("baseline_candidate_bytes") >= 0
        and memory.get("baseline_sampled_peak_bytes") >= memory["baseline_candidate_bytes"]
        and memory.get("final_candidate_bytes") >= 0
        and memory.get("final_sampled_peak_bytes") >= memory["final_candidate_bytes"]
    )


def _summary_from(warmup, rows, workload):
    generation = warmup.get("generation") if isinstance(warmup, dict) else None
    warmup_passed = (
        isinstance(warmup, dict)
        and _sample_is_admitted(warmup, workload, 0, "warmup", generation)
    )
    passed = sum(
        _sample_is_admitted(row, workload, index, "checkpoint", generation)
        for index, row in enumerate(rows, 1)
    ) if isinstance(rows, list) else 0
    total_operations = rows[-1]["operations_total"] if rows else (
        warmup.get("operations_total", 0) if isinstance(warmup, dict) else 0
    )
    loader_calls = rows[-1]["loader_calls"] if rows else (
        warmup.get("loader_calls", 0) if isinstance(warmup, dict) else 0
    )
    cache_calls = rows[-1]["cache_calls"] if rows else (
        warmup.get("cache_calls", 0) if isinstance(warmup, dict) else 0
    )
    return {
        "warmup_operations": workload["warmup_operations"],
        "warmup_passed": warmup_passed,
        "checkpoint_count": workload["checkpoint_count"],
        "passed_checkpoints": passed,
        "failed_checkpoints": workload["checkpoint_count"] - passed,
        "operations_per_checkpoint": workload["operations_per_checkpoint"],
        "measured_operations": workload["measured_operations"],
        "total_operations": total_operations,
        "cache_calls": cache_calls,
        "loader_calls": loader_calls,
    }


def _summary_is_admitted(summary, workload):
    if not isinstance(summary, dict) or set(summary) != SUMMARY_KEYS:
        return False
    if type(summary.get("warmup_passed")) is not bool:
        return False
    integer_fields = SUMMARY_KEYS - {"warmup_passed"}
    expected = {
        "warmup_operations": workload["warmup_operations"],
        "warmup_passed": True,
        "checkpoint_count": workload["checkpoint_count"],
        "passed_checkpoints": workload["checkpoint_count"],
        "failed_checkpoints": 0,
        "operations_per_checkpoint": workload["operations_per_checkpoint"],
        "measured_operations": workload["measured_operations"],
        "total_operations": workload["total_operations"],
        "cache_calls": workload["total_operations"] * 2,
        "loader_calls": workload["total_operations"],
    }
    return all(_is_int(summary.get(name)) for name in integer_fields) and summary == expected


def _isolation_is_admitted(isolation):
    if not isinstance(isolation, dict) or set(isolation) != ISOLATION_KEYS:
        return False
    integer_fields = ISOLATION_KEYS - {
        "scope", "session_factory", "network_guard", "task_mode",
        "credentials_used", "production_writes",
    }
    zero_fields = integer_fields - {
        "production_persistence_calls",
        "production_persistence_calls_blocked",
        "spider_instances",
    }
    return (
        isolation.get("scope") == "candidate_long_lived_spider"
        and isolation.get("session_factory") == "FakeSession"
        and isolation.get("network_guard") == "requests_and_socket_import_surfaces"
        and isolation.get("task_mode") == "captured_start_thread_no_execution"
        and all(_is_int(isolation.get(name)) for name in integer_fields)
        and all(isolation.get(name) == 0 for name in zero_fields)
        and isolation.get("production_persistence_calls") == 2
        and isolation.get("production_persistence_calls_blocked") == 2
        and isolation.get("spider_instances") == 1
        and type(isolation.get("credentials_used")) is bool
        and isolation.get("credentials_used") is False
        and type(isolation.get("production_writes")) is bool
        and isolation.get("production_writes") is False
    )


def _cleanup_is_admitted(cleanup):
    if not isinstance(cleanup, dict) or set(cleanup) != CLEANUP_KEYS:
        return False
    integer_fields = CLEANUP_KEYS - {
        "destroy_called", "destroy_succeeded", "timeout_closed", "reference_counts",
    }
    return (
        type(cleanup.get("destroy_called")) is bool
        and cleanup.get("destroy_called") is True
        and type(cleanup.get("destroy_succeeded")) is bool
        and cleanup.get("destroy_succeeded") is True
        and type(cleanup.get("timeout_closed")) is bool
        and cleanup.get("timeout_closed") is True
        and all(_is_int(cleanup.get(name)) for name in integer_fields)
        and cleanup.get("session_references_retained") == 0
        and cleanup.get("sessions_created_total") == 6
        and cleanup.get("sessions_closed_once") == 6
        and cleanup.get("task_threads") == 0
        and cleanup.get("task_timers") == 0
        and cleanup.get("task_executors") == 0
        and cleanup.get("task_worker_threads") == 0
        and cleanup.get("timeout_active") == 0
        and _zero_reference_counts_are_admitted(cleanup.get("reference_counts"))
        and cleanup.get("captured_tasks_pending") == 0
        and cleanup.get("response_weakrefs_alive") == 0
    )


def _invariants_from(report):
    workload = report.get("workload")
    warmup = report.get("warmup")
    rows = report.get("checkpoint_results")
    memory = report.get("memory")
    isolation = report.get("isolation")
    cleanup = report.get("cleanup")
    candidate = report.get("candidate")
    closure = report.get("candidate_closure")
    samples_valid = (
        isinstance(workload, dict)
        and _workload_is_admitted(workload)
        and _samples_are_admitted(warmup, rows, workload)
    )
    all_rows = [warmup] + rows if samples_valid else []
    generations = {row["generation"] for row in all_rows}
    return {
        "profile_complete": samples_valid,
        "single_generation": samples_valid and len(generations) == 1,
        "cache_and_diagnostics_bounded": samples_valid,
        "responses_closed_and_collected": samples_valid and all(
            row["responses_created"] == row["responses_closed"]
            and row["response_weakrefs_alive"] == 0
            for row in all_rows
        ),
        "timeout_scopes_released": samples_valid and all(
            row["timeout_active"] == 0 for row in all_rows
        ),
        "task_owners_stable": samples_valid and all(
            row["task_threads"] == 0
            and row["task_timers"] == 0
            and row["task_executors"] == EXPECTED_TASK_EXECUTORS
            and row["task_worker_threads"] == 0
            for row in all_rows
        ),
        "reference_owners_empty": samples_valid and all(
            _zero_reference_counts_are_admitted(row["reference_counts"])
            for row in all_rows
        ),
        "memory_observed": samples_valid and _memory_is_admitted(memory, warmup, rows),
        "isolation_observed": _isolation_is_admitted(isolation),
        "destroy_references_cleared": _cleanup_is_admitted(cleanup),
        "candidate_stable_after_samples": P5B._candidate_closure_is_admitted(
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
    workload = report.get("workload")
    warmup = report.get("warmup")
    rows = report.get("checkpoint_results")
    candidate = report.get("candidate")
    closure = report.get("candidate_closure")
    invariants = report.get("invariants")
    expected_invariants = _invariants_from(report)
    return (
        (report.get("overall") == "passed" or (
            allow_pending and report.get("overall") == "pending"))
        and report.get("schema") == REPORT_SCHEMA
        and report.get("failure") is None
        and _generated_at_is_admitted(report.get("generated_at"))
        and _loaded_inputs_are_current()
        and report.get("evidence_provenance") == _evidence_provenance()
        and _workload_is_admitted(workload)
        and workload.get("formal_profile") is True
        and report.get("limitations") == list(LIMITATIONS)
        and candidate == P5B._candidate_evidence()
        and P5B._candidate_closure_is_admitted(closure, candidate)
        and _samples_are_admitted(warmup, rows, workload)
        and _memory_is_admitted(report.get("memory"), warmup, rows)
        and report.get("summary") == _summary_from(warmup, rows, workload)
        and _summary_is_admitted(report.get("summary"), workload)
        and invariants == expected_invariants
        and isinstance(invariants, dict)
        and set(invariants) == INVARIANT_KEYS
        and all(type(value) is bool and value is True for value in invariants.values())
        and _isolation_is_admitted(report.get("isolation"))
        and _cleanup_is_admitted(report.get("cleanup"))
        and P5B._current_candidate_is_stable(
            candidate, closure["state_after_sha256"],
        )
    )


def _safe_error_type(exc):
    for error_type, label in (
        (ResourceGrowthAssertionError, "ResourceGrowthAssertionError"),
        (P5B.CachePerformanceAssertionError, "CachePerformanceAssertionError"),
        (OSError, "OSError"),
        (RuntimeError, "RuntimeError"),
        (ValueError, "ValueError"),
        (TypeError, "TypeError"),
        (AssertionError, "AssertionError"),
    ):
        if isinstance(exc, error_type):
            return label
    return "Exception"


def _failure(exc):
    return {
        "error_type": _safe_error_type(exc),
        "error": "long-run resource execution failed",
    }


def run_long_run_resource_growth(
        warmup_operations=DEFAULT_WARMUP_OPERATIONS,
        checkpoint_count=DEFAULT_CHECKPOINT_COUNT,
        operations_per_checkpoint=DEFAULT_OPERATIONS_PER_CHECKPOINT):
    profile = _profile(
        warmup_operations, checkpoint_count, operations_per_checkpoint,
    )
    _require(
        _loaded_inputs_are_current(),
        "loaded evidence inputs changed; start a new process",
    )
    provenance = _evidence_provenance()
    workload = _workload_evidence(profile)
    executed = P5B._executed_build()
    candidate = P5B._candidate_evidence_from(executed)
    P5A.FakeSession.instances = []
    observer = P5A.IsolationObserver()
    response_observer = ResponseObserver()
    clock = P5B.VirtualClock(2000000000.0)
    counters = {"loader_calls": 0, "hot_loader_calls": 0, "cache_calls": 0}
    captured = {"attempts": 0, "rows": []}
    persistence = {"attempts": 0}
    warmup = None
    rows = []
    failure = None
    memory = {
        "source": "python_tracemalloc_candidate_filename_observation",
        "trace_filename": CANDIDATE_TRACE_FILENAME,
        "admission_threshold": False,
        "baseline_candidate_bytes": 0,
        "baseline_sampled_peak_bytes": 0,
        "final_candidate_bytes": 0,
        "final_sampled_peak_bytes": 0,
        "delta_candidate_bytes": 0,
        "sample_count": 0,
    }
    memory_state = {"sampled_peak_bytes": 0}
    cleanup = {
        "destroy_called": False,
        "destroy_succeeded": False,
        "session_references_retained": 0,
        "sessions_created_total": 0,
        "sessions_closed_once": 0,
        "task_threads": 0,
        "task_timers": 0,
        "task_executors": 0,
        "task_worker_threads": 0,
        "timeout_active": 0,
        "timeout_closed": False,
        "reference_counts": _zero_reference_counts(),
        "captured_tasks_pending": 0,
        "response_weakrefs_alive": 0,
    }
    spider = None
    tasks = None
    original_start_thread = None
    thread_guard = P5B.ThreadStartGuard()
    tracer_started = False
    with thread_guard:
        try:
            module = P5B._runtime_module(observer, executed)
            module.time = clock
            spider = module.Spider()
            P5A._install_isolation_stubs(spider, observer)

            def block_persistence(*_args, **_kwargs):
                persistence["attempts"] += 1
                raise ResourceGrowthAssertionError("persistence write is forbidden")

            spider.setCache = block_persistence
            spider.init({})
            _require(
                observer.observe_credentials(spider) == 0,
                "credential material entered the isolated long run",
            )
            spider.cache_max_entries = CACHE_MAX_ENTRIES
            spider.cache_ttl = CACHE_TTL_SECONDS
            spider.stale_ttl = max(spider.stale_ttl, CACHE_TTL_SECONDS)
            with spider._cache_lock:
                spider._cache.clear()
                spider._persistent_cache.clear()
                spider._persistent_cache_loaded = True
                spider._persistent_cache_dirty = False
                spider._persistent_cache_saving = None
                spider._failures.clear()
                spider._failure_attempts.clear()
                spider._refreshing_cache_keys.clear()
                spider._resource_search_jobs.clear()
                spider._resource_entry_preheat_jobs.clear()
                spider._route_probe_jobs.clear()
                spider._bound_replacement_jobs.clear()
                spider._native_exports.clear()
                spider._route_quality_saving = None
            tasks = spider._tasks
            original_start_thread = tasks.start_thread

            def capture_task(target, args=(), kwargs=None, name="background"):
                captured["attempts"] += 1
                captured["rows"].append(
                    (target, tuple(args or ()), dict(kwargs or {}), str(name)),
                )
                return True

            tasks.start_thread = capture_task
            _require(not tracemalloc.is_tracing(), "tracemalloc is already active")
            tracemalloc.start()
            tracer_started = True
            operation_index = 0
            for _unused in range(profile["warmup_operations"]):
                operation_index += 1
                _operate_once(
                    module, spider, response_observer, counters, operation_index,
                )
            warmup = _sample(
                spider, response_observer, counters, captured,
                memory_state,
                0, "warmup", operation_index,
            )
            if not _sample_is_admitted(
                    warmup, workload, 0, "warmup", warmup["generation"]):
                warmup["status"] = "failed"
            for checkpoint in range(1, profile["checkpoint_count"] + 1):
                for _unused in range(profile["operations_per_checkpoint"]):
                    operation_index += 1
                    _operate_once(
                        module, spider, response_observer, counters, operation_index,
                    )
                row = _sample(
                    spider, response_observer, counters, captured,
                    memory_state,
                    checkpoint, "checkpoint", operation_index,
                )
                if not _sample_is_admitted(
                        row, workload, checkpoint, "checkpoint", warmup["generation"]):
                    row["status"] = "failed"
                rows.append(row)
            memory = {
                "source": "python_tracemalloc_candidate_filename_observation",
                "trace_filename": CANDIDATE_TRACE_FILENAME,
                "admission_threshold": False,
                "baseline_candidate_bytes": warmup["candidate_traced_bytes"],
                "baseline_sampled_peak_bytes": warmup["candidate_sampled_peak_bytes"],
                "final_candidate_bytes": rows[-1]["candidate_traced_bytes"],
                "final_sampled_peak_bytes": rows[-1]["candidate_sampled_peak_bytes"],
                "delta_candidate_bytes": (
                    rows[-1]["candidate_traced_bytes"]
                    - warmup["candidate_traced_bytes"]
                ),
                "sample_count": len(rows) + 1,
            }
        except Exception as exc:
            failure = _failure(exc)
        finally:
            if tracer_started:
                tracemalloc.stop()
            if tasks is not None and original_start_thread is not None:
                tasks.start_thread = original_start_thread
            if spider is not None:
                cleanup["destroy_called"] = True
                try:
                    spider.destroy()
                    cleanup["destroy_succeeded"] = True
                except Exception as exc:
                    if failure is None:
                        failure = _failure(exc)
                gc.collect()
                current_sessions = (
                    spider._session, spider._tmdb_session, spider._atvp_session,
                )
                cleanup["session_references_retained"] = sum(
                    session is not None for session in current_sessions
                )
                cleanup["sessions_created_total"] = len(P5A.FakeSession.instances)
                cleanup["sessions_closed_once"] = sum(
                    session.close_calls == 1 for session in P5A.FakeSession.instances
                )
                cleanup.update(_task_counts(spider._tasks))
                timeout_snapshot = spider._timeout_budget_controller.snapshot()
                cleanup["timeout_active"] = timeout_snapshot["active"]
                cleanup["timeout_closed"] = timeout_snapshot["closed"]
                cleanup["reference_counts"] = _reference_counts(spider)
            cleanup["captured_tasks_pending"] = len(captured["rows"])
            cleanup["response_weakrefs_alive"] = len(response_observer.live)
            captured["rows"][:] = []

    observation = observer.snapshot()
    isolation = {
        "scope": "candidate_long_lived_spider",
        "session_factory": "FakeSession",
        "network_guard": "requests_and_socket_import_surfaces",
        "task_mode": "captured_start_thread_no_execution",
        "request_attempts": observation["request_attempts"],
        "socket_connect_attempts": observation["socket_connect_attempts"],
        "network_requests": observation["network_requests"],
        "credential_values_observed": observation["credential_values_observed"],
        "credentials_used": observation["credentials_used"],
        "production_persistence_calls": observation["production_persistence_calls"],
        "production_persistence_calls_blocked": (
            observation["production_persistence_calls_blocked"]
        ),
        "production_writes": observation["production_writes"],
        "set_cache_attempts": persistence["attempts"],
        "candidate_sleep_calls": clock.sleep_calls,
        "thread_start_attempts": thread_guard.attempts,
        "thread_starts_blocked": thread_guard.blocked,
        "captured_task_attempts": captured["attempts"],
        "captured_tasks_pending": cleanup["captured_tasks_pending"],
        "spider_instances": int(spider is not None),
    }
    _require(
        _loaded_inputs_are_current(),
        "loaded evidence inputs changed; start a new process",
    )
    closure = P5B._candidate_closure(executed)
    report = {
        "schema": REPORT_SCHEMA,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat().replace(
            "+00:00", "Z",
        ),
        "evidence_provenance": provenance,
        "candidate": candidate,
        "candidate_closure": closure,
        "workload": workload,
        "limitations": list(LIMITATIONS),
        "warmup": warmup,
        "checkpoint_results": rows,
        "memory": memory,
        "summary": _summary_from(warmup, rows, workload),
        "invariants": {},
        "isolation": isolation,
        "cleanup": cleanup,
        "failure": failure,
        "overall": "pending",
    }
    report["invariants"] = _invariants_from(report)
    admitted = report_is_admitted(report, allow_pending=True)
    report["overall"] = "passed" if admitted else "failed"
    if report_is_admitted(report) is not admitted:
        raise ResourceGrowthAssertionError("final resource growth admission state drifted")
    return report


def write_report(path, report):
    workload = report.get("workload") if isinstance(report, dict) else None
    formal_workload = _workload_evidence(_profile(
        DEFAULT_WARMUP_OPERATIONS,
        DEFAULT_CHECKPOINT_COUNT,
        DEFAULT_OPERATIONS_PER_CHECKPOINT,
    ))
    _require(
        _workload_is_admitted(workload) and workload == formal_workload,
        "diagnostic profiles cannot be published",
    )
    return P5B.write_report(path, report)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json-out", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args(argv)
    try:
        report = run_long_run_resource_growth()
        admitted = report_is_admitted(report)
        write_report(args.json_out, report)
    except Exception as exc:
        print(
            "V80 P5 long-run resource growth: failed (%s)" % _safe_error_type(exc),
            file=sys.stderr,
        )
        return 2
    summary = report["summary"]
    print(
        "V80 P5 long-run resource growth: %s, %d/%d checkpoints passed (%s)"
        % (
            "passed" if admitted else "failed",
            summary["passed_checkpoints"], summary["checkpoint_count"],
            args.json_out,
        )
    )
    return 0 if admitted else 1


if __name__ == "__main__":
    raise SystemExit(main())

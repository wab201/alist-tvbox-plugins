import copy
import hashlib
import importlib.util
import json
import threading
from functools import lru_cache
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parent.parent
RUNNER_PATH = ROOT / "tests" / "v80_p5_long_run_resource_growth_runner.py"
GATE_PATH = ROOT / "tools" / "run_v80_stage_gate.py"


def _load(name, path):
    payload = Path(path).read_bytes()
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    module.__dict__["__loaded_source_sha256__"] = (
        hashlib.sha256(payload).hexdigest().upper()
    )
    exec(compile(payload, str(path), "exec"), module.__dict__)
    return module


RUNNER = _load("v80_p5_long_run_resource_growth_runner", RUNNER_PATH)
GATE = _load("v80_p5_long_run_resource_growth_gate", GATE_PATH)


@lru_cache(maxsize=1)
def _report():
    return RUNNER.run_long_run_resource_growth()


@lru_cache(maxsize=1)
def _mini_report():
    return RUNNER.run_long_run_resource_growth(
        warmup_operations=4,
        checkpoint_count=2,
        operations_per_checkpoint=3,
    )


@lru_cache(maxsize=1)
def _executed_build():
    return RUNNER.P5B._executed_build()


def _fast_closure(monkeypatch):
    closure = copy.deepcopy(_report()["candidate_closure"])
    executed = _executed_build()
    monkeypatch.setattr(RUNNER.P5B, "_executed_build", lambda: executed)
    monkeypatch.setattr(
        RUNNER.P5B, "_candidate_closure",
        lambda _executed: copy.deepcopy(closure),
    )


def test_formal_long_run_report_is_admitted_and_observational():
    report = _report()

    assert report["schema"] == "v80-p5-long-run-resource-growth/2"
    assert report["overall"] == "passed"
    assert RUNNER.report_is_admitted(report) is True
    assert report["workload"] == {
        "owner": "candidate.long_lived_spider",
        "scenario": "sequential_bounded_owner_churn",
        "warmup_operations": 256,
        "checkpoint_count": 32,
        "operations_per_checkpoint": 128,
        "measured_operations": 4096,
        "total_operations": 4352,
        "cache_max_entries": 256,
        "cache_key_policy": "unique_non_persistable",
        "cache_call_pattern": ["cold_miss", "fresh_hot_hit"],
        "diagnostic_owner": "Spider._diagnostic_event",
        "response_owner": "TimeoutOperation.track_close_tracked",
        "task_mode": "captured_start_thread_no_execution",
        "formal_profile": True,
    }
    assert report["summary"] == {
        "warmup_operations": 256,
        "warmup_passed": True,
        "checkpoint_count": 32,
        "passed_checkpoints": 32,
        "failed_checkpoints": 0,
        "operations_per_checkpoint": 128,
        "measured_operations": 4096,
        "total_operations": 4352,
        "cache_calls": 8704,
        "loader_calls": 4352,
    }
    assert report["memory"]["source"] == (
        "python_tracemalloc_candidate_filename_observation"
    )
    assert report["memory"]["trace_filename"] == (
        "v80-p5-lifecycle-runtime.py"
    )
    assert report["memory"]["admission_threshold"] is False
    assert len(report["checkpoint_results"]) == 32


def test_micro_profile_exercises_the_same_closed_path():
    report = _mini_report()

    assert report["overall"] == "failed"
    assert RUNNER.report_is_admitted(report) is False
    assert report["workload"]["formal_profile"] is False
    assert report["summary"] == {
        "warmup_operations": 4,
        "warmup_passed": True,
        "checkpoint_count": 2,
        "passed_checkpoints": 2,
        "failed_checkpoints": 0,
        "operations_per_checkpoint": 3,
        "measured_operations": 6,
        "total_operations": 10,
        "cache_calls": 20,
        "loader_calls": 10,
    }
    assert report["warmup"]["cache_entries"] == 4
    assert [row["cache_entries"] for row in report["checkpoint_results"]] == [7, 10]


def test_candidate_trace_filter_excludes_runner_owned_allocations(monkeypatch):
    observed = []

    class Filtered(object):
        traces = (type("Trace", (), {"size": 7})(), type("Trace", (), {"size": 11})())

    class Snapshot(object):
        def filter_traces(self, filters):
            observed.extend(filters)
            return Filtered()

    monkeypatch.setattr(RUNNER.tracemalloc, "take_snapshot", Snapshot)

    assert RUNNER._candidate_traced_bytes() == 18
    assert len(observed) == 1
    assert observed[0].filename_pattern == "*v80-p5-lifecycle-runtime.py"


def test_all_samples_bind_one_generation_and_bounded_owner_counts():
    report = _report()
    rows = [report["warmup"]] + report["checkpoint_results"]
    generations = {row["generation"] for row in rows}

    assert len(generations) == 1
    assert report["warmup"]["cache_entries"] == 256
    assert report["warmup"]["diagnostic_events"] == 256
    for row in rows:
        assert row["cache_entries"] == 256
        assert row["persistent_cache_entries"] == 0
        assert row["failure_entries"] == 0
        assert row["failure_attempt_entries"] == 0
        assert row["diagnostic_events"] == 256
        assert row["responses_created"] == row["responses_closed"]
        assert row["response_double_closes"] == 0
        assert row["response_weakrefs_alive"] == 0
        assert row["timeout_active"] == 0
        assert row["reference_counts"] == RUNNER._zero_reference_counts()
        assert row["task_threads"] == 0
        assert row["task_timers"] == 0
        assert row["task_executors"] == 6
        assert row["task_worker_threads"] == 0
        assert row["captured_task_attempts"] == 0
        assert row["captured_tasks_pending"] == 0
        assert row["sessions_created_total"] == 6
        assert row["sessions_open"] == 3


def test_cleanup_and_isolation_are_exact_and_non_production():
    report = _report()

    assert report["isolation"] == {
        "scope": "candidate_long_lived_spider",
        "session_factory": "FakeSession",
        "network_guard": "requests_and_socket_import_surfaces",
        "task_mode": "captured_start_thread_no_execution",
        "request_attempts": 0,
        "socket_connect_attempts": 0,
        "network_requests": 0,
        "credential_values_observed": 0,
        "credentials_used": False,
        "production_persistence_calls": 2,
        "production_persistence_calls_blocked": 2,
        "production_writes": False,
        "set_cache_attempts": 0,
        "candidate_sleep_calls": 0,
        "thread_start_attempts": 0,
        "thread_starts_blocked": 0,
        "captured_task_attempts": 0,
        "captured_tasks_pending": 0,
        "spider_instances": 1,
    }
    assert report["cleanup"] == {
        "destroy_called": True,
        "destroy_succeeded": True,
        "session_references_retained": 0,
        "sessions_created_total": 6,
        "sessions_closed_once": 6,
        "task_threads": 0,
        "task_timers": 0,
        "task_executors": 0,
        "task_worker_threads": 0,
        "timeout_active": 0,
        "timeout_closed": True,
        "reference_counts": RUNNER._zero_reference_counts(),
        "captured_tasks_pending": 0,
        "response_weakrefs_alive": 0,
    }


def test_evidence_provenance_uses_exact_loaded_bytes_and_single_builder():
    report = _report()

    assert RUNNER._RUNNER_LOADED_SHA256 == RUNNER._file_sha256(RUNNER_PATH)
    assert RUNNER.P5B.__loaded_source_sha256__ == RUNNER._file_sha256(
        RUNNER.P5B_RUNNER_PATH
    )
    assert RUNNER.P5A.__loaded_source_sha256__ == RUNNER._file_sha256(
        RUNNER.P5A_RUNNER_PATH
    )
    assert RUNNER.BUILD.__loaded_source_sha256__ == RUNNER._file_sha256(
        RUNNER.BUILD_PATH
    )
    assert RUNNER.P5A.BUILD is RUNNER.BUILD
    assert report["evidence_provenance"] == RUNNER._evidence_provenance()
    assert report["candidate"] == report["candidate_closure"]["executed"]
    assert report["candidate"] == report["candidate_closure"]["rebuilt"]
    assert report["candidate"] == report["candidate_closure"]["output"]


@pytest.mark.parametrize(
    "case",
    (
        "schema", "extra_top", "provenance", "candidate", "closure",
        "workload", "warmup", "sample_extra", "bool_checkpoint", "cache",
        "persistent", "diagnostics", "response", "weakref", "timeout",
        "reference", "reference_bool", "task", "generation", "memory",
        "summary", "invariant", "isolation", "cleanup",
        "cleanup_reference_bool", "failure", "pending",
    ),
)
def test_report_admission_rejects_closed_schema_tamper(monkeypatch, case):
    report = copy.deepcopy(_report())
    current_candidate = copy.deepcopy(report["candidate"])
    monkeypatch.setattr(
        RUNNER.P5B, "_candidate_evidence", lambda: copy.deepcopy(current_candidate),
    )
    monkeypatch.setattr(
        RUNNER.P5B, "_current_candidate_is_stable", lambda *_args: True,
    )
    if case == "schema":
        report["schema"] = "forged"
    elif case == "extra_top":
        report["debug"] = "not allowed"
    elif case == "provenance":
        report["evidence_provenance"]["runner"]["sha256"] = "0" * 64
    elif case == "candidate":
        report["candidate"]["sha256"] = "0" * 64
    elif case == "closure":
        report["candidate_closure"]["stable_after_samples"] = False
    elif case == "workload":
        report["workload"]["formal_profile"] = False
    elif case == "warmup":
        report["warmup"]["status"] = "failed"
    elif case == "sample_extra":
        report["checkpoint_results"][0]["raw"] = "not allowed"
    elif case == "bool_checkpoint":
        report["checkpoint_results"][0]["checkpoint"] = True
    elif case == "cache":
        report["checkpoint_results"][0]["cache_entries"] = 257
    elif case == "persistent":
        report["checkpoint_results"][0]["persistent_cache_entries"] = 1
    elif case == "diagnostics":
        report["checkpoint_results"][0]["diagnostic_events"] = 257
    elif case == "response":
        report["checkpoint_results"][0]["responses_closed"] -= 1
    elif case == "weakref":
        report["checkpoint_results"][0]["response_weakrefs_alive"] = 1
    elif case == "timeout":
        report["checkpoint_results"][0]["timeout_active"] = 1
    elif case == "reference":
        report["checkpoint_results"][0]["reference_counts"][
            RUNNER.REFERENCE_NAMES[0]
        ] = 1
    elif case == "reference_bool":
        report["checkpoint_results"][0]["reference_counts"][
            RUNNER.REFERENCE_NAMES[0]
        ] = False
    elif case == "task":
        report["checkpoint_results"][0]["task_worker_threads"] = 1
    elif case == "generation":
        report["checkpoint_results"][0]["generation"] += 1
    elif case == "memory":
        report["memory"]["admission_threshold"] = True
    elif case == "summary":
        report["summary"]["total_operations"] -= 1
    elif case == "invariant":
        report["invariants"]["profile_complete"] = 1
    elif case == "isolation":
        report["isolation"]["network_requests"] = 1
    elif case == "cleanup":
        report["cleanup"]["session_references_retained"] = 1
    elif case == "cleanup_reference_bool":
        report["cleanup"]["reference_counts"][RUNNER.REFERENCE_NAMES[0]] = False
    elif case == "failure":
        report["failure"] = {
            "error_type": "RuntimeError", "error": "execution failed",
        }
    elif case == "pending":
        report["overall"] = "pending"

    assert RUNNER.report_is_admitted(report) is False


def test_candidate_closure_and_current_state_are_both_required(monkeypatch):
    report = copy.deepcopy(_report())
    current_candidate = copy.deepcopy(report["candidate"])
    monkeypatch.setattr(
        RUNNER.P5B, "_candidate_evidence", lambda: copy.deepcopy(current_candidate),
    )
    report["candidate_closure"]["state_before_sha256"] = "B" * 64
    report["candidate_closure"]["state_after_sha256"] = "B" * 64
    assert RUNNER.report_is_admitted(report) is False

    report = copy.deepcopy(_report())
    observed = []

    def reject_current(candidate, expected_state):
        observed.append((candidate, expected_state))
        return False

    monkeypatch.setattr(RUNNER.P5B, "_current_candidate_is_stable", reject_current)
    assert RUNNER.report_is_admitted(report) is False
    assert observed == [(
        report["candidate"],
        report["candidate_closure"]["state_after_sha256"],
    )]


@pytest.mark.parametrize(
    "changed_path",
    (
        RUNNER_PATH,
        RUNNER.P5B_RUNNER_PATH,
        RUNNER.P5A_RUNNER_PATH,
        RUNNER.BUILD_PATH,
        RUNNER.MANIFEST_PATH,
    ),
)
def test_loaded_input_drift_rejects_report_and_new_run(monkeypatch, changed_path):
    report = copy.deepcopy(_report())
    original_file_sha256 = RUNNER._file_sha256

    def drifted_file_sha256(path):
        if Path(path).resolve() == Path(changed_path).resolve():
            return "B" * 64
        return original_file_sha256(path)

    monkeypatch.setattr(RUNNER, "_file_sha256", drifted_file_sha256)

    assert RUNNER.report_is_admitted(report) is False
    with pytest.raises(
            RUNNER.ResourceGrowthAssertionError,
            match="loaded evidence inputs changed"):
        RUNNER.run_long_run_resource_growth(1, 1, 1)


def test_thread_start_attempt_is_blocked_and_fails_report(monkeypatch):
    _fast_closure(monkeypatch)

    def start_thread(_module, _spider, _responses, _counters, _index):
        threading.Thread(target=lambda: None).start()

    monkeypatch.setattr(RUNNER, "_operate_once", start_thread)
    report = RUNNER.run_long_run_resource_growth(1, 1, 1)

    assert report["overall"] == "failed"
    assert report["isolation"]["thread_start_attempts"] == 1
    assert report["isolation"]["thread_starts_blocked"] == 1
    assert report["failure"] == {
        "error_type": "CachePerformanceAssertionError",
        "error": "long-run resource execution failed",
    }


def test_persistence_attempt_is_counted_and_fails_report(monkeypatch):
    _fast_closure(monkeypatch)
    original_operate = RUNNER._operate_once

    def persist_then_operate(module, spider, responses, counters, index):
        try:
            spider.setCache("p55c-write", "blocked")
        except RUNNER.ResourceGrowthAssertionError:
            pass
        return original_operate(module, spider, responses, counters, index)

    monkeypatch.setattr(RUNNER, "_operate_once", persist_then_operate)
    report = RUNNER.run_long_run_resource_growth(2, 1, 1)

    assert report["overall"] == "failed"
    assert report["isolation"]["set_cache_attempts"] == 3
    assert report["isolation"]["production_writes"] is False


def test_destroy_retained_session_reference_fails_cleanup(monkeypatch):
    _fast_closure(monkeypatch)
    original_runtime_module = RUNNER.P5A._runtime_module

    def runtime_with_retained_session(observer):
        module = original_runtime_module(observer)
        original_destroy = module.Spider.destroy

        def destroy(spider):
            retained = spider._session
            result = original_destroy(spider)
            spider._session = retained
            return result

        module.Spider.destroy = destroy
        return module

    monkeypatch.setattr(RUNNER.P5A, "_runtime_module", runtime_with_retained_session)
    report = RUNNER.run_long_run_resource_growth(2, 1, 1)

    assert report["overall"] == "failed"
    assert report["cleanup"]["session_references_retained"] == 1
    assert report["invariants"]["destroy_references_cleared"] is False


def test_failure_report_does_not_persist_exception_text(monkeypatch):
    _fast_closure(monkeypatch)

    def fail_operation(*_args, **_kwargs):
        raise RuntimeError("opaque-sensitive-value")

    monkeypatch.setattr(RUNNER, "_operate_once", fail_operation)
    report = RUNNER.run_long_run_resource_growth(1, 1, 1)
    serialized = json.dumps(report, ensure_ascii=False)

    assert report["overall"] == "failed"
    assert report["failure"] == {
        "error_type": "RuntimeError",
        "error": "long-run resource execution failed",
    }
    assert "opaque-sensitive-value" not in serialized


def test_failure_type_is_allowlisted(monkeypatch):
    _fast_closure(monkeypatch)
    SensitiveError = type("opaque-sensitive-value", (Exception,), {})

    def fail_operation(*_args, **_kwargs):
        raise SensitiveError()

    monkeypatch.setattr(RUNNER, "_operate_once", fail_operation)
    report = RUNNER.run_long_run_resource_growth(1, 1, 1)
    serialized = json.dumps(report, ensure_ascii=False)

    assert report["failure"] == {
        "error_type": "Exception",
        "error": "long-run resource execution failed",
    }
    assert "opaque-sensitive-value" not in serialized


def test_report_writer_is_new_file_only_utf8_and_atomic(monkeypatch, tmp_path):
    monkeypatch.setattr(RUNNER.P5B, "WORK_ROOT", tmp_path.resolve())
    path = tmp_path / "long-run.json"
    report = _report()

    RUNNER.write_report(path, report)
    payload = path.read_bytes()

    assert not payload.startswith(b"\xef\xbb\xbf")
    assert payload.endswith(b"\n")
    assert json.loads(payload.decode("utf-8")) == report
    assert not list(tmp_path.glob("*.tmp"))
    with pytest.raises(RUNNER.P5B.CachePerformanceAssertionError, match="must be new"):
        RUNNER.write_report(path, report)


def test_report_writer_rejects_diagnostic_profile(monkeypatch, tmp_path):
    monkeypatch.setattr(RUNNER.P5B, "WORK_ROOT", tmp_path.resolve())

    reports = [_mini_report(), _mini_report()]
    reports[1]["workload"]["formal_profile"] = True
    for index, report in enumerate(reports):
        with pytest.raises(
                RUNNER.ResourceGrowthAssertionError,
                match="diagnostic profiles cannot be published"):
            RUNNER.write_report(tmp_path / ("mini-%d.json" % index), report)


def test_main_sanitizes_preflight_errors(monkeypatch, capsys, tmp_path):
    def fail_run():
        raise RuntimeError("opaque-sensitive-value")

    monkeypatch.setattr(RUNNER, "run_long_run_resource_growth", fail_run)
    assert RUNNER.main(["--json-out", str(tmp_path / "unused.json")]) == 2
    captured = capsys.readouterr()
    assert "RuntimeError" in captured.err
    assert "opaque-sensitive-value" not in captured.err


def test_main_sanitizes_dynamic_exception_type(monkeypatch, capsys, tmp_path):
    SensitiveError = type("opaque-sensitive-value", (Exception,), {})

    def fail_run():
        raise SensitiveError()

    monkeypatch.setattr(RUNNER, "run_long_run_resource_growth", fail_run)
    assert RUNNER.main(["--json-out", str(tmp_path / "unused.json")]) == 2
    captured = capsys.readouterr()
    assert "Exception" in captured.err
    assert "opaque-sensitive-value" not in captured.err


def test_runner_and_test_are_stage_gate_inputs():
    implementation_paths = {
        Path(path).resolve() for path in GATE.implementation_tree_paths(ROOT)
    }
    pytest_paths = {Path(path).resolve() for path in GATE._pytest_input_paths(ROOT)}

    assert RUNNER_PATH.resolve() in implementation_paths
    assert Path(__file__).resolve() in implementation_paths
    assert RUNNER_PATH.resolve() in pytest_paths
    assert Path(__file__).resolve() in pytest_paths


def test_runner_and_test_pass_the_existing_sensitive_scan():
    result = GATE.check_sensitive(
        ROOT,
        paths=[RUNNER_PATH, Path(__file__)],
    )

    assert result["status"] == "passed"
    assert result["findings"] == []
    assert result["files_scanned"] == 2

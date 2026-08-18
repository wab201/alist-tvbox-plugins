import copy
import hashlib
import importlib.util
import json
import threading
from functools import lru_cache
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parent.parent
RUNNER_PATH = ROOT / "tests" / "v80_p5_cache_performance_runner.py"
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


RUNNER = _load("v80_p5_cache_performance_runner", RUNNER_PATH)
GATE = _load("v80_p5_cache_performance_gate", GATE_PATH)


@lru_cache(maxsize=1)
def _report():
    return RUNNER.run_cache_performance()


def _valid_closure():
    candidate = RUNNER._candidate_evidence()
    state = RUNNER._candidate_state_sha256(ROOT / candidate["output"])
    return {
        "executed": dict(candidate),
        "rebuilt": dict(candidate),
        "output": dict(candidate),
        "state_before_sha256": state,
        "state_after_sha256": state,
        "stable_after_samples": True,
    }


def test_current_candidate_cache_performance_report_is_admitted():
    report = _report()

    assert report["schema"] == "v80-p5-cache-performance/2"
    assert report["overall"] == "passed"
    assert RUNNER.report_is_admitted(report) is True
    assert report["summary"] == {
        "scenario_count": 3,
        "samples_per_scenario": 32,
        "total": 96,
        "passed": 96,
        "failed": 0,
    }
    assert report["candidate"] == RUNNER._candidate_evidence()
    assert report["candidate_closure"] == _valid_closure()
    assert report["workload"] == RUNNER._workload_evidence()
    assert report["limitations"] == list(RUNNER.LIMITATIONS)


def test_evidence_modules_use_the_exact_loaded_bytes_and_single_builder():
    assert RUNNER._RUNNER_LOADED_SHA256 == RUNNER._file_sha256(RUNNER_PATH)
    assert RUNNER.LIFECYCLE.__loaded_source_sha256__ == RUNNER._file_sha256(
        RUNNER.LIFECYCLE_RUNNER_PATH
    )
    assert RUNNER.BUILD.__loaded_source_sha256__ == RUNNER._file_sha256(
        RUNNER.BUILD_PATH
    )
    assert RUNNER.LIFECYCLE.BUILD is RUNNER.BUILD


def test_runtime_module_consumes_each_run_executed_build(monkeypatch):
    original_build_result = RUNNER.LIFECYCLE._build_result
    executed_a = {"bytes": b"A"}
    executed_b = {"bytes": b"B"}
    observed = []

    def runtime_module(_observer):
        observed.append(RUNNER.LIFECYCLE._build_result())
        return object()

    monkeypatch.setattr(RUNNER.LIFECYCLE, "_runtime_module", runtime_module)

    RUNNER._runtime_module(None, executed_a)
    assert RUNNER.LIFECYCLE._build_result is original_build_result
    RUNNER._runtime_module(None, executed_b)

    assert observed == [executed_a, executed_b]
    assert RUNNER.LIFECYCLE._build_result is original_build_result


def test_all_32_sample_triplets_match_the_single_owner_contract():
    rows = _report()["cycle_results"]

    assert len(rows) == 96
    for cycle in range(1, 33):
        cold, hot, stale = rows[(cycle - 1) * 3:cycle * 3]
        assert [cold["scenario"], hot["scenario"], stale["scenario"]] == list(
            RUNNER.SCENARIOS
        )
        for row in (cold, hot, stale):
            assert RUNNER._scenario_row_is_admitted(row, cycle) is True
            assert row["calls"] == RUNNER.SCENARIO_CALLS[row["scenario"]]
        assert cold["result_version"] == hot["result_version"] == "v1"
        assert stale["before_release"] == {
            "loader_calls": 0,
            "pending_tasks": 1,
            "refreshing_keys": 1,
        }
        assert stale["after_release"] == {
            "loader_calls": 1,
            "pending_tasks": 0,
            "refreshing_keys": 0,
            "cache_entries": 1,
        }
        assert stale["stale_result_version"] == "v1"
        assert stale["duplicate_result_version"] == "v1"
        assert stale["refreshed_cache_version"] == "v2"
        assert stale["post_refresh_result_version"] == "v2"


def test_statistics_are_recomputed_and_host_time_is_observational():
    report = _report()

    assert report["statistics"] == RUNNER._statistics_from_rows(
        report["cycle_results"]
    )
    assert RUNNER._statistics_are_valid(report["statistics"]) is True
    expected_work = {
        "cold_miss": 250.0,
        "fresh_hot_hit": 0.0,
        "stale_immediate_return": 0.0,
        "controlled_refresh_commit": 250.0,
        "post_refresh_hot_hit": 0.0,
    }
    for name, expected in expected_work.items():
        host = report["statistics"][name]["host_elapsed_us"]
        work = report["statistics"][name]["synthetic_work_ms"]
        assert host["source"] == "host_perf_counter_observation"
        assert host["fixture_expectation"] is False
        assert work == {
            "samples": 32,
            "source": "virtual_clock_fixture",
            "fixture_expectation": True,
            "min": expected,
            "median": expected,
            "p95": expected,
            "max": expected,
        }


def test_large_finite_host_observations_do_not_fail_admission():
    report = copy.deepcopy(_report())
    for row in report["cycle_results"]:
        if row["scenario"] in ("cold_miss", "fresh_hot_hit"):
            row["host_elapsed_us"] = 10_000_000_000.0
        else:
            row["immediate_host_elapsed_us"] = 10_000_000_000.0
            row["refresh_host_elapsed_us"] = 10_000_000_000.0
            row["post_refresh_host_elapsed_us"] = 10_000_000_000.0
    report["statistics"] = RUNNER._statistics_from_rows(report["cycle_results"])
    report["invariants"] = RUNNER._invariants_from(
        report["cycle_results"], report["statistics"], report["isolation"],
        report["candidate_closure"], report["candidate"],
    )

    assert RUNNER.report_is_admitted(report) is True


def test_isolation_fields_are_observed_and_narrowly_scoped():
    isolation = _report()["isolation"]

    assert set(isolation) == RUNNER.ISOLATION_KEYS
    assert isolation == {
        "scope": "candidate_cache_owner",
        "network_guard": "requests_and_socket_import_surfaces",
        "task_mode": "captured_callback_manual_release",
        "request_attempts": 0,
        "socket_connect_attempts": 0,
        "network_requests": 0,
        "credential_values_observed": 0,
        "credentials_used": False,
        "persistence_write_attempts": 0,
        "captured_task_enqueues": 32,
        "captured_task_executions": 32,
        "candidate_sleep_calls": 0,
        "thread_start_attempts": 0,
        "thread_starts_blocked": 0,
    }


@pytest.mark.parametrize(
    "case",
    (
        "schema", "candidate", "closure", "runner", "extra_top",
        "missing_row", "extra_row_field", "extra_isolation_field",
        "bool_cycle", "bool_tasks", "bool_nested", "bool_summary",
        "bool_invariant", "loader_count", "virtual_work", "nan_host",
        "aggregate", "network", "generated_at", "pending",
    ),
)
def test_report_admission_rejects_tamper(case):
    report = copy.deepcopy(_report())
    if case == "schema":
        report["schema"] = "forged"
    elif case == "candidate":
        report["candidate"]["sha256"] = "0" * 64
    elif case == "closure":
        report["candidate_closure"]["stable_after_samples"] = False
    elif case == "runner":
        report["evidence_provenance"]["runner"]["sha256"] = "0" * 64
    elif case == "extra_top":
        report["debug_dump"] = "not allowed"
    elif case == "missing_row":
        report["cycle_results"].pop()
    elif case == "extra_row_field":
        report["cycle_results"][0]["url"] = "not allowed"
    elif case == "extra_isolation_field":
        report["isolation"]["raw"] = "not allowed"
    elif case == "bool_cycle":
        report["cycle_results"][0]["cycle"] = True
    elif case == "bool_tasks":
        report["cycle_results"][0]["tasks_enqueued"] = False
    elif case == "bool_nested":
        report["cycle_results"][2]["before_release"]["pending_tasks"] = True
    elif case == "bool_summary":
        report["summary"]["failed"] = False
    elif case == "bool_invariant":
        report["invariants"]["rows_complete"] = 1
    elif case == "loader_count":
        report["cycle_results"][0]["calls"]["loader_calls"] = 0
    elif case == "virtual_work":
        report["cycle_results"][1]["synthetic_work_ms"] = 1.0
    elif case == "nan_host":
        report["cycle_results"][2]["immediate_host_elapsed_us"] = float("nan")
    elif case == "aggregate":
        report["statistics"]["cold_miss"]["host_elapsed_us"]["median"] = 0.0
    elif case == "network":
        report["isolation"]["network_requests"] = 1
    elif case == "generated_at":
        report["generated_at"] = "not-utc"
    elif case == "pending":
        report["overall"] = "pending"

    assert RUNNER.report_is_admitted(report) is False


def test_thread_start_attempt_is_blocked_and_fails_report(monkeypatch):
    def start_thread(_module, _observer, _cycle):
        threading.Thread(target=lambda: None).start()

    monkeypatch.setattr(RUNNER, "_run_cycle", start_thread)
    monkeypatch.setattr(RUNNER, "_candidate_closure", lambda _build: _valid_closure())
    report = RUNNER.run_cache_performance()

    assert report["overall"] == "failed"
    assert report["isolation"]["thread_start_attempts"] == 1
    assert report["isolation"]["thread_starts_blocked"] == 1


def test_same_process_candidate_state_drift_is_rebuilt_and_rejected(monkeypatch):
    report = copy.deepcopy(_report())
    expected_state = report["candidate_closure"]["state_after_sha256"]
    drifted_state = "B" * 64
    if drifted_state == expected_state:
        drifted_state = "C" * 64
    states = iter((expected_state, drifted_state))
    executed = RUNNER._executed_build()
    build_calls = []

    def rebuild(_manifest):
        build_calls.append(True)
        return executed

    monkeypatch.setattr(RUNNER, "_CANDIDATE_VALIDATION_CACHE", {})
    monkeypatch.setattr(RUNNER, "_candidate_evidence", lambda: report["candidate"])
    monkeypatch.setattr(
        RUNNER, "_candidate_state_sha256", lambda _output: next(states),
    )
    monkeypatch.setattr(RUNNER.BUILD, "build_release", rebuild)

    assert RUNNER.report_is_admitted(report) is False
    assert build_calls == [True]


def test_stable_candidate_state_drift_is_rejected(monkeypatch):
    report = copy.deepcopy(_report())
    drifted_state = "B" * 64
    monkeypatch.setattr(RUNNER, "_CANDIDATE_VALIDATION_CACHE", {})
    monkeypatch.setattr(RUNNER, "_candidate_evidence", lambda: report["candidate"])
    monkeypatch.setattr(
        RUNNER, "_candidate_state_sha256", lambda _output: drifted_state,
    )
    monkeypatch.setattr(
        RUNNER.BUILD, "build_release",
        lambda _manifest: pytest.fail("stable drift must reject before rebuild"),
    )

    assert RUNNER.report_is_admitted(report) is False


def test_matching_tampered_candidate_state_hashes_are_rejected():
    report = copy.deepcopy(_report())
    report["candidate_closure"]["state_before_sha256"] = "B" * 64
    report["candidate_closure"]["state_after_sha256"] = "B" * 64

    assert RUNNER.report_is_admitted(report) is False


def test_cached_candidate_rechecks_loaded_identity_after_state_read(monkeypatch):
    report = copy.deepcopy(_report())
    candidate = report["candidate"]
    expected_state = report["candidate_closure"]["state_after_sha256"]
    current = {"loaded": True}

    def state_sha256(_output):
        current["loaded"] = False
        return expected_state

    monkeypatch.setattr(
        RUNNER, "_CANDIDATE_VALIDATION_CACHE", {expected_state: candidate},
    )
    monkeypatch.setattr(
        RUNNER, "_loaded_inputs_are_current", lambda: current["loaded"],
    )
    monkeypatch.setattr(RUNNER, "_candidate_state_sha256", state_sha256)

    assert RUNNER._current_candidate_is_stable(candidate, expected_state) is False


def test_cached_candidate_rechecks_candidate_state_before_admission(monkeypatch):
    report = copy.deepcopy(_report())
    candidate = report["candidate"]
    expected_state = report["candidate_closure"]["state_after_sha256"]
    drifted_state = "B" * 64
    if drifted_state == expected_state:
        drifted_state = "C" * 64
    states = iter((expected_state, drifted_state))

    monkeypatch.setattr(
        RUNNER, "_CANDIDATE_VALIDATION_CACHE", {expected_state: candidate},
    )
    monkeypatch.setattr(
        RUNNER, "_candidate_state_sha256", lambda _output: next(states),
    )

    assert RUNNER._current_candidate_is_stable(candidate, expected_state) is False


@pytest.mark.parametrize(
    "changed_path",
    (RUNNER_PATH, RUNNER.BUILD_PATH, RUNNER.LIFECYCLE_RUNNER_PATH),
)
def test_loaded_evidence_input_drift_is_rejected(monkeypatch, changed_path):
    report = copy.deepcopy(_report())
    original_file_sha256 = RUNNER._file_sha256
    validation_cache = {}

    def drifted_file_sha256(path):
        if Path(path).resolve() == Path(changed_path).resolve():
            return "B" * 64
        return original_file_sha256(path)

    monkeypatch.setattr(RUNNER, "_file_sha256", drifted_file_sha256)
    monkeypatch.setattr(RUNNER, "_CANDIDATE_VALIDATION_CACHE", validation_cache)

    assert RUNNER.report_is_admitted(report) is False
    with pytest.raises(
            RUNNER.CachePerformanceAssertionError,
            match="loaded evidence inputs changed"):
        RUNNER.run_cache_performance()
    assert validation_cache == {}


def test_destroy_persistence_attempt_is_counted_and_fails_report(monkeypatch):
    original_runtime_module = RUNNER.LIFECYCLE._runtime_module

    def runtime_with_destroy_write(observer):
        module = original_runtime_module(observer)
        original_destroy = module.Spider.destroy

        def destroy(spider):
            try:
                spider.setCache("p55b-destroy", "blocked")
            except RUNNER.CachePerformanceAssertionError:
                pass
            return original_destroy(spider)

        module.Spider.destroy = destroy
        return module

    monkeypatch.setattr(RUNNER, "SAMPLE_COUNT", 1)
    monkeypatch.setattr(
        RUNNER.LIFECYCLE, "_runtime_module", runtime_with_destroy_write,
    )
    monkeypatch.setattr(RUNNER, "_candidate_closure", lambda _build: _valid_closure())

    report = RUNNER.run_cache_performance()

    assert report["isolation"]["persistence_write_attempts"] == 1
    assert report["overall"] == "failed"


def test_failure_rows_do_not_persist_exception_text(monkeypatch):
    def fail_cycle(_module, _observer, _cycle):
        raise RuntimeError("opaque-sensitive-value")

    monkeypatch.setattr(RUNNER, "_run_cycle", fail_cycle)
    monkeypatch.setattr(RUNNER, "_candidate_closure", lambda _build: _valid_closure())
    report = RUNNER.run_cache_performance()
    serialized = json.dumps(report, ensure_ascii=False)

    assert report["overall"] == "failed"
    assert report["cycle_results"] == [{
        "cycle": 1,
        "scenario": "runner_failure",
        "status": "failed",
        "error_type": "RuntimeError",
        "error": "scenario execution failed",
    }]
    assert "opaque-sensitive-value" not in serialized


def test_report_writer_is_new_file_only_utf8_and_atomic(monkeypatch, tmp_path):
    monkeypatch.setattr(RUNNER, "WORK_ROOT", tmp_path.resolve())
    path = tmp_path / "cache-performance.json"
    report = _report()

    RUNNER.write_report(path, report)
    first = path.read_bytes()

    assert not first.startswith(b"\xef\xbb\xbf")
    assert first.endswith(b"\n")
    assert json.loads(first.decode("utf-8")) == report
    assert not list(tmp_path.glob("*.tmp"))
    with pytest.raises(RUNNER.CachePerformanceAssertionError, match="must be new"):
        RUNNER.write_report(path, report)
    assert path.read_bytes() == first


def test_report_writer_rejects_outside_work_and_managed_candidate(
        monkeypatch, tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    monkeypatch.setattr(RUNNER, "WORK_ROOT", allowed.resolve())
    with pytest.raises(RUNNER.CachePerformanceAssertionError, match="inside work"):
        RUNNER.write_report(tmp_path / "outside.json", _report())

    candidate = ROOT / _report()["candidate"]["output"]
    before = candidate.read_bytes()
    monkeypatch.setattr(RUNNER, "run_cache_performance", lambda: _report())
    assert RUNNER.main(["--json-out", str(candidate)]) == 2
    assert candidate.read_bytes() == before


def test_main_sanitizes_preflight_errors(monkeypatch, capsys, tmp_path):
    def fail_preflight():
        raise RuntimeError("opaque-sensitive-value")

    monkeypatch.setattr(RUNNER, "_evidence_provenance", fail_preflight)
    assert RUNNER.main(["--json-out", str(tmp_path / "unused.json")]) == 2
    captured = capsys.readouterr()
    assert "RuntimeError" in captured.err
    assert "opaque-sensitive-value" not in captured.err


def test_main_returns_zero_for_new_admitted_report(monkeypatch, tmp_path):
    monkeypatch.setattr(RUNNER, "WORK_ROOT", tmp_path.resolve())
    monkeypatch.setattr(RUNNER, "run_cache_performance", lambda: _report())
    path = tmp_path / "passed.json"

    assert RUNNER.main(["--json-out", str(path)]) == 0
    assert path.exists()


def test_runner_and_test_pass_the_existing_sensitive_scan():
    result = GATE.check_sensitive(
        ROOT,
        paths=[RUNNER_PATH, Path(__file__)],
    )

    assert result["status"] == "passed"
    assert result["findings"] == []
    assert result["files_scanned"] == 2

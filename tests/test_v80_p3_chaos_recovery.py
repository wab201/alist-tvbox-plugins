import importlib.util
import json
from functools import lru_cache
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
RUNNER_PATH = ROOT / "tools" / "run_v80_p3_chaos_recovery.py"
EXPECTED_SIZE = 862377
EXPECTED_SHA256 = "C1ACAB802121E3F69ADEA0EBF1AB271C14015124AA28D2D1F8F58F97C8481B7D"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RUNNER = _load("v80_p3_chaos_recovery", RUNNER_PATH)


@lru_cache(maxsize=1)
def _report():
    return RUNNER.run_chaos_recovery()


def test_chaos_report_covers_every_planned_fault_and_recovery_baseline():
    report = _report()
    rows = {row["name"]: row for row in report["scenarios"]}

    assert tuple(rows) == tuple(RUNNER.EXPECTED_RECOVERY_MS)
    assert report["summary"] == {"total": 12, "passed": 12, "failed": 0}
    for name, expected_ms in RUNNER.EXPECTED_RECOVERY_MS.items():
        assert rows[name]["status"] == "passed"
        assert rows[name]["expected_recovery_ms"] == expected_ms
        assert rows[name]["recovery_ms"] == expected_ms


def test_chaos_report_is_bound_to_the_current_isolated_candidate():
    report = _report()

    assert report["schema"] == "v80-p3-chaos-recovery/1"
    assert report["candidate"] == {
        "size": EXPECTED_SIZE,
        "sha256": EXPECTED_SHA256,
        "output": "build/v80-dev/豆瓣TMDB追更单入口.py",
    }
    assert report["clock"] == "virtual"
    assert report["production_writes"] is False
    assert report["deployment_attempted"] is False


def test_chaos_report_keeps_cold_and_hot_cache_evidence_separate():
    baseline = _report()["performance_baseline"]

    assert baseline["source"] == "virtual_fault_fixture"
    assert baseline["cold_start_ms"] == 250
    assert baseline["hot_cache_ms"] == 0
    assert "not a real-device benchmark" in baseline["note"]


def test_chaos_report_proves_isolation_and_lifecycle_invariants():
    rows = {row["name"]: row for row in _report()["scenarios"]}

    for name in ("pansou_timeout", "alist_502", "dns_failure", "ipv6_unreachable"):
        assert rows[name]["evidence"]["independent_provider_available"] is True
    assert rows["history_401_reauth"]["evidence"] == {
        "recovery_ms": 0,
        "forced_logins": 1,
        "request_calls": 3,
        "request_methods": ["GET", "POST", "GET"],
        "v145_route": True,
        "playback_available": True,
    }
    assert rows["history_500_isolation"]["evidence"]["v145_route"] is True
    assert rows["history_500_isolation"]["evidence"]["playback_available"] is True
    assert rows["expired_play_url"]["evidence"]["play_requests"] == 2
    assert rows["stale_lifecycle_task"]["evidence"] == {
        "recovery_ms": 0,
        "stale_cache_commit_rejected": True,
        "stale_bulkhead_release_fenced": True,
    }


def test_oversized_json_claim_is_limited_to_the_existing_stream_boundary():
    report = _report()
    row = next(
        item for item in report["scenarios"]
        if item["name"] == "oversized_json_boundary"
    )

    assert row["evidence"]["stream_limit_checked"] is True
    assert row["evidence"]["circuit_opened"] is False
    assert report["oversized_json_scope"] == (
        "existing_stream_boundary_only_p4_unified_security_pending"
    )


def test_report_writer_uses_utf8_without_bom_and_round_trips(tmp_path):
    path = tmp_path / "chaos.json"
    report = _report()

    RUNNER.write_report(path, report)

    raw = path.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")
    assert raw.endswith(b"\n")
    assert json.loads(raw.decode("utf-8")) == report


def test_unexpected_scenario_errors_do_not_leak_raw_exception_text(monkeypatch):
    secret = "test-secret"
    functions = {
        name: (lambda value=value: {"recovery_ms": value})
        for name, value in RUNNER.EXPECTED_RECOVERY_MS.items()
    }

    def fail():
        raise RuntimeError("https://private.invalid/path?token=" + secret)

    functions["tmdb_500_stale"] = fail
    monkeypatch.setattr(RUNNER, "_scenario_functions", lambda: functions)

    report = RUNNER.run_chaos_recovery()
    failed = report["scenarios"][0]

    assert failed["status"] == "failed"
    assert failed["error"] == "scenario execution failed"
    assert secret not in json.dumps(report, ensure_ascii=False)

import copy
import importlib.util
import sys
import types
from functools import lru_cache
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parent.parent
RUNNER_PATH = ROOT / "tests" / "v80_p5_playback_concurrency_runner.py"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RUNNER = _load("v80_p5_playback_concurrency_runner", RUNNER_PATH)


@lru_cache(maxsize=1)
def _report():
    return RUNNER.run_playback_concurrency()


def _by_name():
    return {row["name"]: row for row in _report()["scenario_results"]}


def test_formal_playback_concurrency_report_is_admitted():
    report = _report()
    assert RUNNER.validate_report(report) is True
    assert report["summary"] == {"passed": 8, "failed": 0, "total": 8}
    assert report["workload"] == {
        "call_family": "playback",
        "scenario_count": 8,
        "overlay_alias_zh": "播放并发所有权覆盖层",
    }


def test_playback_scenarios_cover_the_fixed_boundary_with_chinese_labels():
    rows = _report()["scenario_results"]
    assert tuple(row["name"] for row in rows) == RUNNER.SCENARIOS
    assert {row["label_zh"] for row in rows} == set(RUNNER.SCENARIO_LABELS_ZH.values())
    assert all(row["duration_seconds"] >= 0 for row in rows)


def test_playback_owner_generation_and_cleanup_evidence_is_observed():
    rows = _by_name()
    assert rows["concurrent_player_isolation"]["metrics"]["crossed_side_effects"] == 0
    assert rows["old_atvp_session_isolation"]["metrics"] == {
        "old_session_requests": 1,
        "new_session_requests": 0,
        "old_session_close_calls": 1,
        "response_close_calls": 1,
    }
    assert rows["response_connection_close"]["metrics"] == {
        "response_close_calls": 1,
        "connection_close_calls": 1,
    }
    assert rows["cancelled_slot_release"]["metrics"]["slot_capacity_recovered"] == 4
    assert rows["foreground_background_isolation"]["metrics"][
        "foreground_completed_while_blocked"
    ] is True
    fence = rows["live_init_generation_fence"]["metrics"]
    assert fence["new_generation"] == fence["old_generation"] + 1
    assert fence["old_generation_side_effects"] == 1
    assert fence["new_generation_side_effects"] == 0
    assert fence["player_result"] == "cancelled"
    stale = rows["stale_side_effect_rejection"]["metrics"]
    assert stale == {
        "route_quality_writes": 0,
        "route_quality_loaded": False,
        "current_probe_preserved": True,
        "history_refresh_side_effects": 0,
    }
    cleanup = rows["destroy_cleanup"]["metrics"]
    assert cleanup["sessions_closed_once"] == 3
    assert cleanup["session_references_cleared"] == 3
    assert cleanup["executors_shutdown"] == 6
    assert cleanup["playback_state_entries"] == 0
    assert cleanup["task_supervisor_closed"] is True


def test_playback_report_keeps_evidence_scope_narrow():
    report = _report()
    assert tuple(report["limitations"]) == RUNNER.LIMITATIONS
    assert set(report["evidence_provenance"]) == {"runner", "overlay", "test"}
    assert all(len(item["sha256"]) == 64 for item in report["evidence_provenance"].values())


def test_formal_run_reuses_the_startup_candidate_bytes_for_every_scenario(monkeypatch):
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
    scenario_calls = []

    def load_bound(_name, _path, payload=None):
        loaded.append(payload)
        return object()

    def scenario():
        RUNNER._load_candidate("candidate_binding_probe_%d" % len(scenario_calls))
        scenario_calls.append(1)
        candidate_path.payload = b"replacement-candidate-bytes"
        return {}

    monkeypatch.setattr(RUNNER, "CANDIDATE_PATH", candidate_path)
    monkeypatch.setattr(RUNNER, "_load", load_bound)
    monkeypatch.setattr(
        RUNNER, "SCENARIO_FUNCTIONS", {name: scenario for name in RUNNER.SCENARIOS},
    )
    monkeypatch.setattr(RUNNER, "validate_report", lambda _report: True)

    report = RUNNER.run_playback_concurrency()

    assert report["overall"] == "passed"
    assert len(loaded) == len(RUNNER.SCENARIOS)
    assert all(payload == initial for payload in loaded)
    assert RUNNER._BOUND_CANDIDATE_BYTES is None


def test_candidate_loader_restores_existing_base_modules(monkeypatch):
    existing_base = types.ModuleType("existing_base")
    existing_spider = types.ModuleType("existing_base.spider")
    monkeypatch.setitem(sys.modules, "base", existing_base)
    monkeypatch.setitem(sys.modules, "base.spider", existing_spider)

    loaded = RUNNER._load_candidate("candidate_base_restore")

    assert loaded.Spider is not None
    assert sys.modules["base"] is existing_base
    assert sys.modules["base.spider"] is existing_spider


@pytest.mark.parametrize(
    "field",
    (
        "schema", "candidate", "scenario", "summary", "limitations",
        "workload", "provenance", "metrics", "label",
    ),
)
def test_playback_report_rejects_tampered_evidence(field):
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
        report["limitations"].append("unbounded_claim")
    elif field == "workload":
        report["workload"]["scenario_count"] = 7
    elif field == "provenance":
        report["evidence_provenance"]["runner"]["sha256"] = "0" * 64
    elif field == "metrics":
        report["scenario_results"][1]["metrics"]["new_session_requests"] = 999
    else:
        report["scenario_results"][0]["label_zh"] = "伪造标签"
    with pytest.raises(RUNNER.PlaybackConcurrencyAssertionError):
        RUNNER.validate_report(report)

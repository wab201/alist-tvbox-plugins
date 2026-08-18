import importlib.util
import copy
import json
from functools import lru_cache
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parent.parent
RUNNER_PATH = ROOT / "tests" / "v80_p5_lifecycle_stability_runner.py"
OVERLAY_PATH = ROOT / "tools" / "build_v80_lifecycle_stability_overlay.py"
GATE_PATH = ROOT / "tools" / "run_v80_stage_gate.py"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RUNNER = _load("v80_p5_lifecycle_stability_runner", RUNNER_PATH)
OVERLAY = _load("v80_p5_lifecycle_stability_overlay", OVERLAY_PATH)
GATE = _load("v80_p5_lifecycle_stability_gate", GATE_PATH)


@lru_cache(maxsize=1)
def _report():
    return RUNNER.run_lifecycle_stability(cycles=8)


def _overlay_fixture():
    return (
        "class Spider:\n"
        "    def destroy(self):\n"
        "        with self._history_context_lock:\n"
        + OVERLAY.DESTROY_SESSION_ANCHOR
    ).encode("utf-8")


def test_lifecycle_overlay_is_deterministic_and_has_one_narrow_insertion():
    source = _overlay_fixture()
    first = OVERLAY.apply_lifecycle_stability_overlay(source)
    second = OVERLAY.apply_lifecycle_stability_overlay(source)

    assert first == second
    assert first["insertions"] == ("destroy-session-reference-clear",)
    assert first["input_size"] == len(source)
    assert first["size"] > first["input_size"]
    text = first["bytes"].decode("utf-8")
    for name in ("_session", "_tmdb_session", "_atvp_session"):
        assert text.count("self.%s = None" % name) == 1


def test_lifecycle_overlay_rejects_anchor_drift_and_invalid_utf8():
    source = _overlay_fixture()
    anchor = OVERLAY.DESTROY_SESSION_ANCHOR.encode("utf-8")

    with pytest.raises(OVERLAY.LifecycleStabilityOverlayError, match="must appear once"):
        OVERLAY.apply_lifecycle_stability_overlay(source.replace(anchor, b"", 1))
    with pytest.raises(OVERLAY.LifecycleStabilityOverlayError, match="must appear once"):
        OVERLAY.apply_lifecycle_stability_overlay(source.replace(anchor, anchor + anchor, 1))
    with pytest.raises(OVERLAY.LifecycleStabilityOverlayError, match="not valid UTF-8"):
        OVERLAY.apply_lifecycle_stability_overlay(b"\xff")


def test_lifecycle_overlay_rejects_anchor_inside_dead_branch():
    source = (
        "class Spider:\n"
        "    def destroy(self):\n"
        "        if False:\n"
        + OVERLAY.DESTROY_SESSION_ANCHOR
    ).encode("utf-8")

    with pytest.raises(
        OVERLAY.LifecycleStabilityOverlayError,
        match="direct history-context cleanup block",
    ):
        OVERLAY.apply_lifecycle_stability_overlay(source)


@pytest.mark.parametrize(
    "body, error",
    (
        (
            "        return\n"
            "        with self._history_context_lock:\n"
            + OVERLAY.DESTROY_SESSION_ANCHOR,
            "only the direct history-context owner",
        ),
        (
            "        with self._history_context_lock:\n"
            "            return\n"
            + OVERLAY.DESTROY_SESSION_ANCHOR,
            "cannot follow an early return or raise",
        ),
        (
            "        with self._history_context_lock:\n"
            "            raise RuntimeError('stop')\n"
            + OVERLAY.DESTROY_SESSION_ANCHOR,
            "cannot follow an early return or raise",
        ),
    ),
)
def test_lifecycle_overlay_rejects_cleanup_after_early_exit(body, error):
    source = ("class Spider:\n    def destroy(self):\n" + body).encode("utf-8")

    with pytest.raises(OVERLAY.LifecycleStabilityOverlayError, match=error):
        OVERLAY.apply_lifecycle_stability_overlay(source)


def test_lifecycle_overlay_rejects_generator_destroy():
    source = _overlay_fixture() + (
        "            if False:\n"
        "                yield None\n"
    ).encode("utf-8")

    with pytest.raises(
        OVERLAY.LifecycleStabilityOverlayError,
        match="cannot be a generator",
    ):
        OVERLAY.apply_lifecycle_stability_overlay(source)


def test_lifecycle_overlay_rejects_yield_from_destroy():
    source = _overlay_fixture() + (
        "            if False:\n"
        "                yield from ()\n"
    ).encode("utf-8")

    with pytest.raises(
        OVERLAY.LifecycleStabilityOverlayError,
        match="cannot be a generator",
    ):
        OVERLAY.apply_lifecycle_stability_overlay(source)


def test_lifecycle_overlay_rejects_decorated_destroy():
    source = (
        "def no_op(_method):\n"
        "    return lambda self: None\n"
        "class Spider:\n"
        "    @no_op\n"
        "    def destroy(self):\n"
        "        with self._history_context_lock:\n"
        + OVERLAY.DESTROY_SESSION_ANCHOR
    ).encode("utf-8")

    with pytest.raises(
        OVERLAY.LifecycleStabilityOverlayError,
        match="cannot be decorated",
    ):
        OVERLAY.apply_lifecycle_stability_overlay(source)


def test_lifecycle_overlay_rejects_decorated_spider_class():
    source = (
        "def decorate(owner):\n"
        "    return owner\n"
        "@decorate\n"
        "class Spider:\n"
        "    def destroy(self):\n"
        "        with self._history_context_lock:\n"
        + OVERLAY.DESTROY_SESSION_ANCHOR
    ).encode("utf-8")

    with pytest.raises(
        OVERLAY.LifecycleStabilityOverlayError,
        match="class cannot be decorated or customized",
    ):
        OVERLAY.apply_lifecycle_stability_overlay(source)


@pytest.mark.parametrize(
    "suffix",
    (
        "    destroy = lambda self: None\n",
        "Spider.destroy = lambda self: None\n",
        "    if True:\n        destroy = lambda self: None\n",
        "    destroy, marker = (lambda self: None), object()\n",
        "if True:\n    Spider.destroy = lambda self: None\n",
        "setattr(Spider, 'destroy', lambda self: None)\n",
        "    del destroy\n",
        "del Spider.destroy\n",
        "delattr(Spider, 'destroy')\n",
        "    if True:\n        def destroy(self):\n            return None\n",
        "    async def destroy(self):\n        return None\n",
        "    class destroy:\n        pass\n",
        "Spider = object\n",
        "if True:\n    class Spider:\n        pass\n",
    ),
)
def test_lifecycle_overlay_rejects_destroy_rebinding(suffix):
    source = _overlay_fixture() + suffix.encode("utf-8")

    with pytest.raises(
        OVERLAY.LifecycleStabilityOverlayError,
        match="cannot be rebound",
    ):
        OVERLAY.apply_lifecycle_stability_overlay(source)


def test_lifecycle_overlay_allows_destroy_name_local_to_another_method():
    source = _overlay_fixture() + (
        "    def helper(self):\n"
        "        destroy = 'local-only'\n"
        "        return destroy\n"
    ).encode("utf-8")

    assert OVERLAY.apply_lifecycle_stability_overlay(source)["insertions"] == (
        "destroy-session-reference-clear",
    )


def test_final_candidate_consumes_the_p5_3_snapshot_output_once():
    build = RUNNER._build_result()
    snapshot = build["diagnostics_snapshot_overlay"]
    lifecycle = build["lifecycle_stability_overlay"]
    search_ownership = build["search_concurrency_ownership_overlay"]
    playback_ownership = build["playback_concurrency_ownership_overlay"]
    history_ownership = build["history_concurrency_ownership_overlay"]

    assert lifecycle["input_size"] == snapshot["size"]
    assert lifecycle["input_sha256"] == snapshot["sha256"]
    assert lifecycle["insertions"] == ("destroy-session-reference-clear",)
    assert search_ownership["input_size"] == lifecycle["size"]
    assert search_ownership["input_sha256"] == lifecycle["sha256"]
    assert playback_ownership["input_size"] == search_ownership["size"]
    assert playback_ownership["input_sha256"] == search_ownership["sha256"]
    assert history_ownership["input_size"] == playback_ownership["size"]
    assert history_ownership["input_sha256"] == playback_ownership["sha256"]
    assert history_ownership["size"] == build["size"]
    assert history_ownership["sha256"] == build["sha256"]


def test_repeated_lifecycle_reaches_quiescence_without_growth():
    report = _report()

    assert report["schema"] == "v80-p5-lifecycle-stability/3"
    assert report["overall"] == "passed"
    assert RUNNER.report_is_admitted(report) is True
    assert report["summary"] == {"total": 8, "passed": 8, "failed": 0}
    assert report["invariants"] == {
        "generation_monotonic": True,
        "task_supervisor_closed": True,
        "playback_state_cleared": True,
        "sessions_closed_once": True,
        "old_generation_callback_rejected": True,
        "response_references_non_growing": True,
        "owned_resources_quiescent": True,
    }
    generations = [row["generation"]["after_destroy"] for row in report["cycle_results"]]
    assert generations == sorted(generations)
    assert len(generations) == len(set(generations))
    for index, row in enumerate(report["cycle_results"], 1):
        assert row["status"] == "passed"
        assert row["controlled_task_contract"] == {
            "active_at_destroy": True,
            "active_after_destroy_before_release": True,
            "release_owner": "runner_after_destroy",
            "release_after_destroy": True,
            "shutdown_cancellation_claimed": False,
            "safety_timeout_seconds": (
                RUNNER.QUIESCENCE_TIMEOUT + RUNNER.SHORT_TASK_SECONDS
            ),
        }
        before = row["owned_resources_before_destroy"]
        assert before["supervised_threads_alive"] == 1
        assert before["owned_timer_alive"] == 1
        assert before["executor_futures_pending"] > 0
        assert before["executor_worker_threads_alive"] == (
            before["executor_futures_pending"]
        )
        after_destroy = row["owned_resources_after_destroy_before_release"]
        assert after_destroy["supervised_threads_alive"] == 1
        assert after_destroy["executor_futures_pending"] == (
            before["executor_futures_pending"]
        )
        assert after_destroy["executor_worker_threads_alive"] == (
            before["executor_worker_threads_alive"]
        )
        expected_counts = {
            name: 0
            for name in RUNNER.REFERENCE_FIELDS + RUNNER.REFERENCE_SCALAR_FIELDS
        }
        if index == 1:
            expected_counts["_refreshing_cache_keys"] = 1
        assert row["owned_resources_after_destroy"] == {
            "threads": 0,
            "timers": 0,
            "executors": 0,
            "supervised_threads_alive": 0,
            "executor_futures_pending": 0,
            "executor_worker_threads_alive": 0,
            "owned_timer_alive": 0,
            "response_references": 1 if index == 1 else 0,
            "response_reference_counts": expected_counts,
            "expected_response_reference_counts": expected_counts,
            "response_reference_owner_mismatches": 0,
        }


def test_report_is_bound_to_current_candidate_and_is_observational_only():
    report = _report()
    build = RUNNER._build_result()

    assert report["candidate"] == {
        "size": build["size"],
        "sha256": build["sha256"],
        "output": str(build["output"].relative_to(ROOT)).replace("\\", "/"),
    }
    assert report["timing"]["source"] == "host_wall_clock_observation"
    assert report["timing"]["admission_threshold"] is False
    for key in ("min_ms", "median_ms", "p95_ms", "max_ms"):
        assert report["timing"][key] is not None


def test_runner_uses_no_network_credentials_production_writes_or_deployment():
    isolation = _report()["isolation"]

    assert isolation["scope"] == "candidate_runtime"
    assert isolation["session_factory"] == "FakeSession"
    assert isolation["stubbed_methods"] == list(RUNNER.STUBBED_METHODS)
    assert isolation["request_attempts"] == 0
    assert isolation["socket_connect_attempts"] == 0
    assert isolation["network_requests"] == 0
    assert isolation["credential_values_observed"] == 0
    assert isolation["production_persistence_calls"] == (
        _report()["cycles"] * len(RUNNER.PERSISTENCE_STUBBED_METHODS)
    )
    assert isolation["production_persistence_calls_blocked"] == (
        isolation["production_persistence_calls"]
    )
    assert isolation["credentials_used"] is False
    assert isolation["production_writes"] is False
    assert isolation["deployment_attempted"] is False
    assert isolation["deployment_attempted_basis"] == (
        "pre_execution_static_ast_guard"
    )
    assert isolation["deployment_surface"]["source"] == "static_ast"
    assert isolation["deployment_surface"]["guard_phase"] == (
        "before_candidate_exec"
    )
    assert isolation["deployment_surface"][
        "listed_deployment_surfaces_absent_static_ast"
    ] is True
    assert isolation["deployment_surface"]["findings"] == []


def test_runtime_network_surfaces_are_counted_and_fail_closed():
    observer = RUNNER.IsolationObserver()
    module = RUNNER._runtime_module(observer)

    blocked_calls = (
        lambda: module.requests.request("GET", "https://invalid.example"),
        lambda: module.requests.get("https://invalid.example"),
        lambda: module.requests.post("https://invalid.example"),
        lambda: module.socket.socket(),
        lambda: module.socket.create_connection(("invalid.example", 443)),
        lambda: module.socket.getaddrinfo("invalid.example", 443),
    )
    for call in blocked_calls:
        with pytest.raises(RUNNER.LifecycleAssertionError, match="is forbidden"):
            call()

    observation = observer.snapshot()
    assert observation["request_attempts"] == 3
    assert observation["socket_connect_attempts"] == 3
    assert observation["network_requests"] == 6


@pytest.mark.parametrize(
    "source, counter",
    (
        (b"import requests\nrequests.get('http://127.0.0.1')\n", "request_attempts"),
        (b"from requests import get\nget('http://127.0.0.1')\n", "request_attempts"),
        (
            b"import requests.sessions as requests\nrequests.Session().get('http://127.0.0.1')\n",
            "request_attempts",
        ),
        (
            b"from requests.sessions import Session\nSession().get('http://127.0.0.1')\n",
            "request_attempts",
        ),
        (
            b"import importlib\nrequests = importlib.import_module('requests')\nrequests.get('http://127.0.0.1')\n",
            "request_attempts",
        ),
        (
            b"from requests.adapters import HTTPAdapter\nHTTPAdapter().send(None)\n",
            "request_attempts",
        ),
        (b"import socket\nsocket.create_connection(('127.0.0.1', 1))\n", "socket_connect_attempts"),
        (b"from socket import socket\nsocket()\n", "socket_connect_attempts"),
    ),
)
def test_runtime_blocks_network_before_candidate_exec(monkeypatch, source, counter):
    observer = RUNNER.IsolationObserver()
    monkeypatch.setattr(RUNNER, "_build_result", lambda: {"bytes": source})

    with pytest.raises(
        RUNNER.LifecycleAssertionError,
        match="(?:network|socket) access is forbidden",
    ):
        RUNNER._runtime_module(observer)

    assert getattr(observer, counter) == 1


def test_deployment_surface_scan_fails_closed_on_process_execution():
    findings = RUNNER._deployment_surface_scan(
        b"import subprocess\nsubprocess.run(['deploy'])\n",
        "fixture.py",
    )

    assert {finding["surface"] for finding in findings} == {
        "import:subprocess",
        "call:subprocess.run",
    }


@pytest.mark.parametrize(
    "source, expected_surface",
    (
        (b"from os import system\nsystem('deploy')\n", "import:os.system"),
        (b"import os as host\nhost.system('deploy')\n", "call:os.system"),
        (b"import os\nos.startfile('deploy.exe')\n", "call:os.startfile"),
        (b"import os as host\nhost.startfile('deploy.exe')\n", "call:os.startfile"),
        (b"__import__('subprocess').run(['deploy'])\n", "dynamic-import:subprocess"),
        (
            b"import importlib\nimportlib.import_module('subprocess').run(['deploy'])\n",
            "dynamic-import:subprocess",
        ),
        (
            b"import importlib as il\nil.import_module('subprocess').run(['deploy'])\n",
            "dynamic-import:subprocess",
        ),
        (
            b"from importlib import import_module as im\nim('subprocess').run(['deploy'])\n",
            "dynamic-import:subprocess",
        ),
        (
            b"from os import *\nsystem('deploy')\n",
            "call:os.system",
        ),
        (
            b"import importlib\nf = importlib.import_module\nf('subprocess')\n",
            "dynamic-import:subprocess",
        ),
        (
            b"from importlib import import_module as im\nf = im\nf('subprocess')\n",
            "dynamic-import:subprocess",
        ),
    ),
)
def test_deployment_surface_scan_covers_aliases_and_dynamic_imports(
        source, expected_surface):
    findings = RUNNER._deployment_surface_scan(source, "fixture.py")

    assert expected_surface in {
        finding["surface"] for finding in findings
    }


def test_report_admission_rejects_false_invariant_and_isolation():
    report = copy.deepcopy(_report())
    report["invariants"]["owned_resources_quiescent"] = False
    assert RUNNER.report_is_admitted(report) is False

    report = copy.deepcopy(_report())
    report["isolation"]["network_requests"] = 1
    assert RUNNER.report_is_admitted(report) is False

    report = copy.deepcopy(_report())
    report.pop("cycle_results")
    report["isolation"].pop("production_persistence_calls")
    report["isolation"].pop("production_persistence_calls_blocked")
    assert RUNNER.report_is_admitted(report) is False

    report = copy.deepcopy(_report())
    report["cycle_results"] = [
        {"cycle": index, "status": "passed"}
        for index in range(1, report["cycles"] + 1)
    ]
    assert RUNNER.report_is_admitted(report) is False

    report = copy.deepcopy(_report())
    report["schema"] = "forged"
    assert RUNNER.report_is_admitted(report) is False

    report = copy.deepcopy(_report())
    report["candidate"]["sha256"] = "EVIL"
    assert RUNNER.report_is_admitted(report) is False

    report = copy.deepcopy(_report())
    report.pop("generated_at")
    assert RUNNER.report_is_admitted(report) is False

    report = copy.deepcopy(_report())
    report["timing"]["max_ms"] = -1
    assert RUNNER.report_is_admitted(report) is False

    report = copy.deepcopy(_report())
    report["overall"] = "failed"
    assert RUNNER.report_is_admitted(report) is False

    report = copy.deepcopy(_report())
    report["overall"] = "pending"
    assert RUNNER.report_is_admitted(report) is False

    report = copy.deepcopy(_report())
    report["summary"] = {
        "total": float(report["cycles"]),
        "passed": float(report["cycles"]),
        "failed": 0.0,
    }
    assert RUNNER.report_is_admitted(report) is False

    report = copy.deepcopy(_report())
    report["cycle_results"][0]["sessions_created_total"] = 0
    assert RUNNER.report_is_admitted(report) is False

    report = copy.deepcopy(_report())
    report["isolation"]["deployment_surface"]["findings"] = [
        {"surface": "call:os.system"}
    ]
    assert RUNNER.report_is_admitted(report) is False

    report = copy.deepcopy(_report())
    report["isolation"]["deployment_attempted"] = True
    assert RUNNER.report_is_admitted(report) is False

    report = copy.deepcopy(_report())
    report["isolation"]["deployment_surface"]["source"] = "forged"
    assert RUNNER.report_is_admitted(report) is False

    report = copy.deepcopy(_report())
    report["isolation"]["scope"] = "production"
    report["isolation"]["stubbed_methods"] = []
    assert RUNNER.report_is_admitted(report) is False

    report = copy.deepcopy(_report())
    report.pop("evidence_provenance")
    assert RUNNER.report_is_admitted(report) is False

    report = copy.deepcopy(_report())
    report["evidence_provenance"]["runner"]["sha256"] = "EVIL"
    assert RUNNER.report_is_admitted(report) is False

    report = copy.deepcopy(_report())
    report["cycle_results"][1]["generation"] = {
        "before": 100,
        "after_init": 101,
        "after_destroy": 102,
    }
    assert RUNNER.report_is_admitted(report) is False

    report = copy.deepcopy(_report())
    for row in report["cycle_results"]:
        row["generation"] = {"before": 0, "after_init": 1, "after_destroy": 2}
    assert RUNNER.report_is_admitted(report) is False

    report = copy.deepcopy(_report())
    for row in report["cycle_results"]:
        row["owned_resources_before_destroy"]["supervised_threads_alive"] = True
        row["owned_resources_before_destroy"]["owned_timer_alive"] = True
        for name in (
            "threads",
            "timers",
            "executors",
            "supervised_threads_alive",
            "executor_futures_pending",
            "executor_worker_threads_alive",
            "owned_timer_alive",
        ):
            row["owned_resources_after_destroy"][name] = False
    assert RUNNER.report_is_admitted(report) is False

    report = copy.deepcopy(_report())
    for row in report["cycle_results"]:
        expected = row["owned_resources_after_destroy"][
            "expected_response_reference_counts"
        ]
        row["owned_resources_after_destroy"][
            "expected_response_reference_counts"
        ] = {name: bool(value) for name, value in expected.items()}
    assert RUNNER.report_is_admitted(report) is False


def test_report_admission_rejects_current_runner_identity_change(monkeypatch):
    report = copy.deepcopy(_report())
    changed = dict(report["evidence_provenance"]["runner"])
    changed["sha256"] = "0" * 64
    monkeypatch.setattr(RUNNER, "_runner_provenance", lambda: changed)

    assert RUNNER.report_is_admitted(report) is False


def test_report_admission_recomputes_deployment_evidence(monkeypatch):
    report = copy.deepcopy(_report())
    changed = copy.deepcopy(report["isolation"]["deployment_surface"])
    changed["findings"] = [{"surface": "call:os.system"}]
    changed["listed_deployment_surfaces_absent_static_ast"] = False
    monkeypatch.setattr(RUNNER, "_deployment_surface_evidence", lambda _source: changed)

    assert RUNNER.report_is_admitted(report) is False


def test_main_exits_zero_when_report_is_admitted(monkeypatch, tmp_path):
    report = copy.deepcopy(_report())
    monkeypatch.setattr(RUNNER, "run_lifecycle_stability", lambda _cycles: report)

    assert RUNNER.main([
        "--cycles", "8", "--json-out", str(tmp_path / "passed.json"),
    ]) == 0


def test_main_exits_nonzero_when_a_mandatory_invariant_is_false(
        monkeypatch, tmp_path):
    report = copy.deepcopy(_report())
    report["invariants"]["owned_resources_quiescent"] = False
    report["overall"] = "failed"
    monkeypatch.setattr(RUNNER, "run_lifecycle_stability", lambda _cycles: report)

    assert RUNNER.main([
        "--cycles", "8", "--json-out", str(tmp_path / "failed.json"),
    ]) == 1


def test_cycle_count_is_bounded():
    with pytest.raises(ValueError, match="cycles must be between"):
        RUNNER.run_lifecycle_stability(RUNNER.MIN_CYCLES - 1)
    with pytest.raises(ValueError, match="cycles must be between"):
        RUNNER.run_lifecycle_stability(RUNNER.MAX_CYCLES + 1)


def test_report_writer_uses_utf8_without_bom_and_round_trips(tmp_path):
    path = tmp_path / "lifecycle.json"
    report = _report()

    RUNNER.write_report(path, report)

    payload = path.read_bytes()
    assert not payload.startswith(b"\xef\xbb\xbf")
    assert json.loads(payload.decode("utf-8")) == report


def test_runner_and_test_pass_the_existing_sensitive_scan():
    result = GATE.check_sensitive(
        ROOT,
        paths=[OVERLAY_PATH, RUNNER_PATH, Path(__file__)],
    )

    assert result["status"] == "passed"
    assert result["findings"] == []
    assert result["files_scanned"] == 3

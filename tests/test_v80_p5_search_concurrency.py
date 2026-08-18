import ast
import copy
import importlib.util
from functools import lru_cache
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parent.parent
RUNNER_PATH = ROOT / "tests" / "v80_p5_search_concurrency_runner.py"


def _load(name, path):
    payload = Path(path).read_bytes()
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    module.__dict__["__loaded_source_sha256__"] = __import__("hashlib").sha256(payload).hexdigest().upper()
    exec(compile(payload, str(path), "exec"), module.__dict__)
    return module


RUNNER = _load("v80_p5_search_concurrency_runner", RUNNER_PATH)


@lru_cache(maxsize=1)
def _report():
    return RUNNER.run_search_concurrency()


def test_formal_search_concurrency_report_is_admitted():
    report = _report()
    assert report["schema"] == "v80-p5-search-concurrency/3"
    assert report["overall"] == "passed"
    assert RUNNER.report_is_admitted(report) is True
    assert report["summary"] == {"total": 7, "passed": 7, "failed": 0}
    assert [row["name"] for row in report["scenario_results"]] == list(RUNNER.SCENARIOS)


def test_search_workload_has_explicit_owners_and_chinese_labels():
    report = _report()
    workload = report["workload"]
    assert workload["owner"] == "candidate.search_call_family"
    assert workload["response_owner"] == "Spider._resource_api_get"
    assert workload["generation_owner"] == "Spider._cache_generation_and_instance_executors"
    assert workload["background_bulkhead_lane"] == "resource_completion"
    assert workload["instance_executor_fields"] == list(RUNNER.EXECUTOR_FIELDS)
    assert workload["instance_executor_count"] == 6
    assert workload["instance_slot_fields"] == list(RUNNER.SLOT_FIELDS)
    assert workload["instance_slot_count"] == 4
    assert workload["mode_slot_owner"] == "Spider._submit_resource_mode_search.release_once"
    assert workload["scenario_labels_zh"]["generation_writeback"] == "真实生命周期旧代次阻断"


def test_owner_generation_response_bulkhead_and_destroy_evidence_are_observed():
    report = _report()
    rows = dict((row["name"], row["metrics"]) for row in report["scenario_results"])
    assert rows["job_owner"]["duplicate_owner_preserved"] is True
    assert rows["job_owner"]["submit_rejection_owner_cleared"] is True
    assert rows["job_owner"]["candidate_lifecycle_path"] == "Spider.init"
    assert rows["job_owner"]["candidate_scheduler_calls"] == 1
    assert rows["job_owner"]["candidate_scheduler_received_old_generation"] is True
    assert rows["job_owner"]["candidate_result_rows"] == 0
    assert rows["job_owner"]["candidate_job_registered_after_init"] is False
    assert rows["job_owner"]["candidate_refresh_registered_after_init"] is False
    assert "admission_transitions" not in rows["job_owner"]
    assert rows["generation_writeback"]["lifecycle_path"] == "Spider.init"
    assert rows["generation_writeback"]["partial_publish_attempts"] == 1
    assert rows["generation_writeback"]["final_publish_seam_reached"] is True
    assert rows["generation_writeback"]["queued_mode_tasks_fenced"] == 2
    assert rows["generation_writeback"]["old_session_request_calls"] == 1
    assert rows["generation_writeback"]["old_request_used_only_old_token_session"] is True
    assert rows["generation_writeback"]["new_session_request_attempts"] == 0
    assert rows["generation_writeback"]["response_close_calls"] == 1
    assert rows["generation_writeback"]["response_double_closes"] == 0
    assert rows["generation_writeback"]["foreground_slot_acquires"] == 2
    assert rows["generation_writeback"]["foreground_slot_releases"] == 2
    assert rows["generation_writeback"]["background_slot_acquires"] == 1
    assert rows["generation_writeback"]["background_slot_releases"] == 1
    assert rows["response_close"]["owner_path"] == "Spider._resource_api_get"
    assert rows["response_close"]["shared_reader_calls"] == 1
    assert rows["response_close"]["shared_reader_close_response_false"] == 1
    assert rows["response_close"]["response_double_closes"] == 0
    assert rows["resource_completion_isolation"]["capacity_plus_one_rejected"] is True
    assert rows["resource_completion_isolation"]["foreground_non_blocking"] is True
    assert rows["destroy_race"]["lifecycle_path"] == "Spider.destroy"
    assert rows["destroy_race"]["old_executors_closed"] == 6
    assert rows["destroy_race"]["new_executor_identities_distinct"] is True
    assert rows["destroy_race"]["new_executor_probes_completed_while_old_saturated"] == 6
    assert rows["destroy_race"]["new_executors_closed"] == 6
    assert rows["destroy_race"]["old_references_zero_after_release"] is True
    assert rows["destroy_race"]["new_references_zero_after_destroy"] is True
    assert rows["destroy_race"]["old_executor_workers_alive_after_release"] == 0
    assert rows["destroy_race"]["new_executor_workers_alive_after_destroy"] == 0


def test_cleanup_observes_workers_bulkhead_timeout_and_sessions():
    cleanup = _report()["cleanup"]
    assert cleanup["destroy_called"] is True
    assert cleanup["destroy_returned"] is True
    assert cleanup["sessions_created_total"] > 0
    assert cleanup["sessions_closed_once"] == cleanup["sessions_created_total"]
    assert cleanup["session_close_calls_total"] == cleanup["sessions_created_total"]
    assert cleanup["executor_fields"] == list(RUNNER.EXECUTOR_FIELDS)
    assert cleanup["executors_total"] == 6
    assert cleanup["executors_closed"] == 6
    assert cleanup["executor_workers_alive"] == 0
    assert "resource_search_admissions" not in cleanup
    assert cleanup["resource_completion_inflight"] == 0
    assert cleanup["bulkhead_inflight_total"] == 0
    assert cleanup["timeout_active"] == 0
    assert cleanup["timeout_closed"] is True
    assert RUNNER._zero_reference_counts_are_admitted(cleanup["reference_counts"])


def test_report_keeps_direct_evidence_provenance_narrow():
    provenance = _report()["evidence_provenance"]
    assert set(provenance) == {
        "runner", "test", "runtime_overlay", "lifecycle_runner",
        "build_tool", "release",
    }


@pytest.mark.parametrize("field", [
    "schema", "candidate", "workload", "scenario_results", "cleanup", "invariants",
])
def test_report_admission_rejects_tampered_search_evidence(field):
    report = copy.deepcopy(_report())
    if field == "schema":
        report["schema"] = "forged"
    elif field == "candidate":
        report["candidate"]["sha256"] = "0" * 64
    elif field == "workload":
        report["workload"]["response_owner"] = "wrong-owner"
    elif field == "scenario_results":
        report["scenario_results"][3]["metrics"]["cache_writes"] = 1
    elif field == "cleanup":
        report["cleanup"]["executors_closed"] = 5
    elif field == "invariants":
        report["invariants"]["generation_writeback_blocked"] = False
    assert RUNNER.report_is_admitted(report) is False


def test_runner_fails_closed_on_loaded_input_drift(monkeypatch):
    original = RUNNER._file_sha256

    def drift(path):
        if Path(path).resolve() == RUNNER_PATH.resolve():
            return "B" * 64
        return original(path)

    monkeypatch.setattr(RUNNER, "_file_sha256", drift)
    with pytest.raises(RUNNER.SearchConcurrencyAssertionError):
        RUNNER.run_search_concurrency()


def test_report_validator_is_pure_after_loaded_input_drift(monkeypatch):
    report = copy.deepcopy(_report())
    monkeypatch.setattr(RUNNER, "_loaded_inputs_are_current", lambda: False)
    assert RUNNER.report_is_admitted(report) is True


def test_runner_does_not_directly_mutate_generation_or_owner_state():
    tree = ast.parse(RUNNER_PATH.read_text(encoding="utf-8"))
    forbidden_attributes = {
        "_cache_generation",
        "_resource_search_jobs",
        "_resource_search_admissions",
        "_refreshing_cache_keys",
    }
    violations = []
    mutators = {
        "__delitem__", "__setitem__", "clear", "pop", "popitem",
        "setdefault", "update",
    }

    def literal_string(node):
        return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None

    def dict_key(node):
        if isinstance(node, ast.Subscript):
            return literal_string(node.slice)
        return None

    def is_state_dict(node):
        if isinstance(node, ast.Attribute) and node.attr == "__dict__":
            return True
        return (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "vars"
            and len(node.args) == 1
        ) or (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "getattr"
            and len(node.args) >= 2
            and literal_string(node.args[1]) == "__dict__"
        )

    def direct_state_name(node):
        if isinstance(node, ast.Attribute) and node.attr in forbidden_attributes:
            return node.attr
        if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "getattr"
                and len(node.args) >= 2):
            name = literal_string(node.args[1])
            return name if name in forbidden_attributes else None
        return None

    def target_attributes(target):
        if isinstance(target, (ast.Tuple, ast.List)):
            values = []
            for item in target.elts:
                values.extend(target_attributes(item))
            return values
        if isinstance(target, ast.Attribute):
            return [target.attr]
        return []

    def inspect_target(target, lineno):
        for name in target_attributes(target):
            if name in forbidden_attributes:
                violations.append(("attribute-write", name, lineno))
        if isinstance(target, ast.Subscript):
            name = dict_key(target)
            if name in forbidden_attributes and is_state_dict(target.value):
                violations.append(("dict-write", name, lineno))

    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign, ast.Delete)):
            targets = node.targets if isinstance(node, (ast.Assign, ast.Delete)) else [node.target]
            for target in targets:
                inspect_target(target, node.lineno)
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name) and node.func.id == "setattr" and len(node.args) >= 2:
            name = literal_string(node.args[1])
            if name in forbidden_attributes:
                violations.append(("setattr", name, node.lineno))
        if (
                isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "object"
                and node.func.attr == "__setattr__"
                and len(node.args) >= 2):
            name = literal_string(node.args[1])
            if name in forbidden_attributes:
                violations.append(("object-setattr", name, node.lineno))
        if (
                isinstance(node.func, ast.Attribute)
                and node.func.attr in mutators):
            state_name = direct_state_name(node.func.value)
            if state_name is not None:
                violations.append(("state-mutation", state_name, node.lineno))
            elif is_state_dict(node.func.value):
                keys = []
                if node.func.attr in {"__delitem__", "__setitem__", "pop", "setdefault"} and node.args:
                    keys.append(literal_string(node.args[0]))
                if node.func.attr == "update" and node.args and isinstance(node.args[0], ast.Dict):
                    keys.extend(literal_string(key) for key in node.args[0].keys)
                for keyword in node.keywords:
                    keys.append(keyword.arg)
                for name in keys:
                    if name in forbidden_attributes:
                        violations.append(("dict-mutation", name, node.lineno))

    assert violations == []


def test_generation_evidence_calls_real_lifecycle_methods():
    tree = ast.parse(RUNNER_PATH.read_text(encoding="utf-8"))
    functions = {
        node.name: node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
    }

    def called_methods(function):
        return {
            node.func.attr
            for node in ast.walk(function)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }

    assert "init" in called_methods(functions["_run_generation_writeback"])
    assert "destroy" in called_methods(functions["_run_destroy_race"])

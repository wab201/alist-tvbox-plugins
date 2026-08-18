import argparse
import importlib.util
import json
import random
import socket
import sys
import tempfile
import threading
import types
from collections import Counter
from concurrent.futures import Future
from contextlib import ExitStack, contextmanager
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import requests


ROOT = Path(__file__).resolve().parents[1]
BUILD_PATH = ROOT / "tools" / "build_follow_plugin.py"
DEV_MANIFEST = ROOT / "src" / "douban_tmdb_follow_single" / "release.json"
BASELINE_MANIFEST = ROOT / "src" / "douban_tmdb_follow_single" / "baseline_v70.json"
REPORT_PATH = ROOT / "work" / "v80-p2-macro-a-differential.json"
SEED = 8020
CASE_COUNT = 50000
SCENARIOS = (
    "disabled",
    "selected_equal",
    "already_sampled",
    "insufficient_budget",
    "not_selected",
    "selected_different",
    "selected_error",
    "duplicate_job",
    "submit_failure",
    "stale_worker",
)
EXPECTED_FIXED_FIELDS = {
    "schema": "v80-p2-macro-a-runtime-differential/1",
    "seed": SEED,
    "cases": CASE_COUNT,
    "errors": 0,
    "baseline_size": 616699,
    "baseline_sha256": "233C73CAE1048210B34872D4A10EA6023662300F70A8657DB82EA65C342182D4",
    "development_size": 870797,
    "development_sha256": "0CEBC73A78BCC8C7853A6BD0F0C78F4D95DD786C861425F9E0A4EC40FA0583F9",
    "vendor_size": 64973,
    "vendor_sha256": "5405EE86F10155B717852E3578750BFA9DE89073AB9BAD8FF3E92C58ACC77601",
    "closure_sha256": "484FCBC3EB079CE3739AD08928D21F82E24101210AED012FC5FA6487553A7968",
    "module_count": 17,
    "overlay_input_size": 681672,
    "overlay_input_sha256": "761EB09F5184A9B9914295A43B0A2F5AF1C46A414F8B0D0456477CA9A3639C01",
    "overlay_insertion_count": 8,
    "output_switch_input_size": 865875,
    "output_switch_input_sha256": "DCD2CE50277119998BE2D92631CC90C11B3DDC733CB7B397E072E62FE117E773",
    "output_switch_size": 870797,
    "output_switch_sha256": "0CEBC73A78BCC8C7853A6BD0F0C78F4D95DD786C861425F9E0A4EC40FA0583F9",
    "output_switch_insertion_count": 9,
    "controlled_switch_active": True,
    "shadow_calls": 30000,
    "disabled_shadow_calls": 0,
    "redacted_reports": True,
    "production_writes": False,
    "deployment_attempted": False,
}
EXPECTED_SCENARIO_COUNTS = {name: 5000 for name in SCENARIOS}
EXPECTED_DECISION_COUNTS = {
    "already_sampled": 5000,
    "insufficient_budget": 5000,
    "not_selected": 5000,
    "selected": 15000,
}
EXPECTED_REPORT_STATUS_COUNTS = {
    "different": 5000,
    "equal": 10000,
}
EXPECTED_ZERO_DIFFERENCE_SCENARIOS = frozenset((
    "duplicate_job", "selected_equal", "selected_error",
    "stale_worker", "submit_failure",
))


def _load_script(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load %s" % path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_source(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load %s" % path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _deny_network(*_args, **_kwargs):
    raise AssertionError("Macro A differential must remain offline")


@contextmanager
def _offline_runtime():
    base_module = types.ModuleType("base")
    spider_module = types.ModuleType("base.spider")

    class BaseSpider(object):
        pass

    spider_module.Spider = BaseSpider
    base_module.spider = spider_module
    saved_base = sys.modules.get("base")
    saved_spider = sys.modules.get("base.spider")
    sys.modules["base"] = base_module
    sys.modules["base.spider"] = spider_module
    try:
        with ExitStack() as stack:
            stack.enter_context(patch.object(socket, "create_connection", _deny_network))
            stack.enter_context(patch.object(socket, "getaddrinfo", _deny_network))
            stack.enter_context(patch.object(requests.sessions.Session, "request", _deny_network))
            yield
    finally:
        if saved_base is None:
            sys.modules.pop("base", None)
        else:
            sys.modules["base"] = saved_base
        if saved_spider is None:
            sys.modules.pop("base.spider", None)
        else:
            sys.modules["base.spider"] = saved_spider


class _InlineExecutor:
    def __init__(self, before_run=None, fail=False):
        self.before_run = before_run
        self.fail = fail

    def submit(self, function, *args, **kwargs):
        if self.fail:
            raise RuntimeError("synthetic submit failure")
        future = Future()
        try:
            if self.before_run is not None:
                self.before_run()
            future.set_result(function(*args, **kwargs))
        except BaseException as exc:
            future.set_exception(exc)
        return future


def _load_candidates():
    build = _load_script(BUILD_PATH, "v80_p2_macro_a_build")
    baseline_result = build.build_release(BASELINE_MANIFEST)
    development_result = build.build_release(DEV_MANIFEST)
    with tempfile.TemporaryDirectory(dir=str(ROOT / "work")) as directory:
        directory = Path(directory)
        baseline_path = directory / "baseline.py"
        development_path = directory / "development.py"
        baseline_path.write_bytes(baseline_result["bytes"])
        development_path.write_bytes(development_result["bytes"])
        with _offline_runtime():
            baseline = _load_source(baseline_path, "v80_p2_macro_a_baseline")
            development = _load_source(
                development_path, "v80_p2_macro_a_development"
            )
    return baseline_result, development_result, baseline, development


def _find_not_selected_key(development, estimated_cost):
    for index in range(1000):
        cache_key = "resource-search:not-selected-%d" % index
        inputs = development.build_background_resource_candidate_shadow_inputs(
            enabled=True,
            cache_key=cache_key,
            generation=20,
            sample_every=2,
            shadow_budget_us=estimated_cost,
        )
        if development.decide_resource_candidate_shadow(**inputs)["reason"] == "not_selected":
            return cache_key
    raise AssertionError("not-selected bucket not found")


def _row(index, offset, mode, rng):
    return {
        "vod_id": "resource-%d-%d" % (index, offset),
        "vod_name": "Example %d" % index,
        "_resource_mode": mode,
        "provider": ("quark", "baidu", "pan123")[offset % 3],
        "score": 1 + rng.randrange(10),
        "preference": (rng.randrange(5), rng.randrange(5)),
        "_validated_groups": rng.randrange(2),
    }


def _make_case(rng, index, not_selected_key):
    scenario = SCENARIOS[index % len(SCENARIOS)]
    cache_key = "resource-search:%064x" % rng.getrandbits(256)
    modes = ("pansou", "telegram")[:1 + rng.randrange(2)]
    rows = {
        mode: [_row(index, offset, mode, rng) for offset in range(1 + rng.randrange(2))]
        for mode in modes
    }
    if scenario == "selected_equal":
        modes = ("pansou",)
        rows = {"pansou": [_row(index, 0, "pansou", rng)]}
    elif scenario == "selected_different":
        modes = ("pansou",)
        first = _row(index, 0, "pansou", rng)
        second = _row(index, 1, "pansou", rng)
        first["preference"] = (0,)
        second["preference"] = (9,)
        rows = {"pansou": [first, second]}
    elif scenario == "selected_error":
        modes = ("pansou",)
        value = _row(index, 0, "pansou", rng)
        value["raise_score"] = True
        rows = {"pansou": [value]}
    elif scenario == "not_selected":
        cache_key = not_selected_key
    return {
        "scenario": scenario,
        "cache_key": cache_key,
        "modes": modes,
        "rows": rows,
        "partial": bool(index % 2),
    }


def _configure_owner(
        module, case, estimated_cost, shadow_enabled, futures,
        layered_output=False):
    owner = module.Spider.__new__(module.Spider)
    owner._cache_lock = threading.RLock()
    owner._cache_generation = 20
    controller = getattr(module, "BackgroundBulkheadController", None)
    if controller is not None:
        owner._background_bulkhead_controller = controller(
            generation=owner._cache_generation,
        )
    timeout_controller = getattr(module, "TimeoutBudgetController", None)
    if timeout_controller is not None:
        owner._timeout_budget_controller = timeout_controller(
            generation=owner._cache_generation,
        )
    owner._resource_search_jobs = {}
    owner._refreshing_cache_keys = {}
    owner._resource_search_admissions = 0
    cache_writes = []
    refreshes = []

    if case["scenario"] == "duplicate_job":
        owner._resource_search_jobs[case["cache_key"]] = object()
    if case["scenario"] == "stale_worker":
        before_run = lambda: setattr(
            owner, "_cache_generation", owner._cache_generation + 1
        )
    else:
        before_run = None
    owner._resource_search_executor = _InlineExecutor(
        before_run=before_run,
        fail=case["scenario"] == "submit_failure",
    )

    def submit_search(mode, *_args, **_kwargs):
        return futures[mode]

    def playable(rows, *_args, **kwargs):
        values = list(rows)
        if case["partial"] and values:
            kwargs["on_update"](values[:1])
        return values

    owner._submit_resource_mode_search = submit_search
    owner._resource_fair_candidate_order = (
        lambda rows, *_args, **_kwargs: list(rows)
    )
    owner._checked_resource_rows = lambda rows, *_args, **_kwargs: list(rows)
    owner._playable_resource_rows = playable
    owner._cache_set = lambda key, rows: cache_writes.append(
        (key, [dict(row) for row in rows])
    )
    owner._validated_resource_group_count = lambda rows: sum(
        int(bool(row.get("_validated_groups"))) for row in rows
    )
    owner._schedule_active_detail_refresh = lambda item: refreshes.append(dict(item))
    owner._merge_resource_rows = lambda left, right, *_args: dict(left, **right)

    def score(row, *_args):
        if row.get("raise_score"):
            raise ValueError("private differential marker")
        return row.get("score", 0)

    owner._resource_score = score
    owner._resource_row_preference = (
        lambda row, *_args: tuple(row.get("preference") or ())
    )
    owner._resource_provider_key = lambda *values: next(
        (str(value) for value in values if value), ""
    )
    if layered_output:
        owner._alist_tvbox_plugin = True
        owner._v80_resource_layered_output_enabled = (
            owner._resource_layered_output_from_config({
                "v80_resource_layered_output": True,
            })
        )

    if shadow_enabled:
        owner._resource_candidate_shadow_lock = threading.Lock()
        owner._resource_candidate_shadow_enabled = case["scenario"] != "disabled"
        owner._resource_candidate_shadow_sample_every = (
            2 if case["scenario"] == "not_selected" else 1
        )
        owner._resource_candidate_shadow_budget_us = (
            estimated_cost - 1
            if case["scenario"] == "insufficient_budget"
            else estimated_cost
        )
        owner._resource_candidate_shadow_sampled_generation = (
            owner._cache_generation
            if case["scenario"] == "already_sampled"
            else None
        )
        owner._resource_candidate_shadow_last_report = None
    return owner, cache_writes, refreshes


def _projection(owner, scheduled, cache_writes, refreshes):
    return {
        "scheduled": scheduled,
        "cache_writes": cache_writes,
        "refresh_count": len(refreshes),
        "job_keys": sorted(owner._resource_search_jobs),
        "refreshing_keys": sorted(owner._refreshing_cache_keys),
        "admissions": owner._resource_search_admissions,
    }


def _run_schedule(module, owner, case, cache_writes, refreshes):
    scheduled = owner._schedule_supplement_resource_search(
        case["modes"],
        ["Example"],
        {"title": "Example", "year": "2026"},
        case["cache_key"],
    )
    return _projection(owner, scheduled, cache_writes, refreshes)


def validation_errors(result):
    errors = [
        name
        for name, expected in EXPECTED_FIXED_FIELDS.items()
        if result.get(name) != expected
    ]
    if result.get("scenario_counts") != EXPECTED_SCENARIO_COUNTS:
        errors.append("scenario_counts")
    if result.get("decision_counts") != EXPECTED_DECISION_COUNTS:
        errors.append("decision_counts")
    if result.get("report_status_counts") != EXPECTED_REPORT_STATUS_COUNTS:
        errors.append("report_status_counts")
    equal = result.get("equal")
    different = result.get("different")
    runtime_errors = result.get("errors")
    if (
            type(equal) is not int or type(different) is not int
            or type(runtime_errors) is not int
            or equal + different + runtime_errors != CASE_COUNT
            or different < EXPECTED_SCENARIO_COUNTS["selected_different"]):
        errors.append("outcome_counts")
    scenario_differences = result.get("scenario_differences")
    if (
            not isinstance(scenario_differences, dict)
            or set(scenario_differences) != set(SCENARIOS)
            or sum(scenario_differences.values()) != different
            or scenario_differences.get("selected_different")
            != EXPECTED_SCENARIO_COUNTS["selected_different"]
            or any(scenario_differences.get(name) != 0
                   for name in EXPECTED_ZERO_DIFFERENCE_SCENARIOS)):
        errors.append("scenario_differences")
    if result.get("first_failures") != []:
        errors.append("first_failures")
    return errors


def _parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json-out", type=Path, default=REPORT_PATH)
    return parser


def main(argv=None):
    args = _parser().parse_args(argv)
    baseline_result, development_result, baseline, development = _load_candidates()
    vendor = development_result["vendor"]
    overlay = development_result["overlay"]
    output_switch = development_result["resource_output_switch_overlay"]
    estimated_cost = development.RESOURCE_CANDIDATE_SHADOW_ESTIMATED_COST_US
    not_selected_key = _find_not_selected_key(development, estimated_cost)
    rng = random.Random(SEED)
    scenario_counts = Counter()
    scenario_differences = Counter({name: 0 for name in SCENARIOS})
    decision_counts = Counter()
    report_status_counts = Counter()
    shadow_results = []
    disabled_shadow_calls = 0
    redacted_reports = True
    equal = 0
    errors = 0
    first_failures = []
    controlled_switch_active = True
    original_shadow = development.run_background_resource_candidate_shadow

    def capture_shadow(owner, legacy_rows, rows, **kwargs):
        nonlocal redacted_reports
        result = original_shadow(owner, legacy_rows, rows, **kwargs)
        shadow_results.append(result)
        raw_ids = [str(row.get("vod_id") or "") for row in rows]
        serialized = json.dumps(result, ensure_ascii=False, sort_keys=True)
        if any(value and value in serialized for value in raw_ids):
            redacted_reports = False
        return result

    development.run_background_resource_candidate_shadow = capture_shadow
    try:
        for index in range(CASE_COUNT):
            case = _make_case(rng, index, not_selected_key)
            scenario_counts[case["scenario"]] += 1
            before_calls = len(shadow_results)
            futures = {}
            for mode in case["modes"]:
                future = Future()
                future.set_result([
                    dict(row) for row in case["rows"].get(mode, ())
                ])
                futures[mode] = future
            try:
                baseline_owner, baseline_writes, baseline_refreshes = _configure_owner(
                    baseline, case, estimated_cost, False, futures
                )
                development_owner, development_writes, development_refreshes = (
                    _configure_owner(
                        development, case, estimated_cost, True, futures,
                        layered_output=True,
                    )
                )
                controlled_switch_active = (
                    controlled_switch_active
                    and development_owner._resource_layered_output_active()
                )
                expected = _run_schedule(
                    baseline, baseline_owner, case, baseline_writes, baseline_refreshes
                )
                actual = _run_schedule(
                    development,
                    development_owner,
                    case,
                    development_writes,
                    development_refreshes,
                )
            except Exception as exc:
                errors += 1
                if len(first_failures) < 10:
                    first_failures.append({
                        "index": index,
                        "scenario": case["scenario"],
                        "error_type": type(exc).__name__,
                    })
                continue

            new_results = shadow_results[before_calls:]
            if case["scenario"] == "disabled":
                disabled_shadow_calls += len(new_results)
            for result in new_results:
                decision_counts[result["decision"]["reason"]] += 1
                if result["report"] is not None:
                    report_status_counts[result["report"]["status"]] += 1
            if expected == actual:
                equal += 1
            else:
                scenario_differences[case["scenario"]] += 1
    finally:
        development.run_background_resource_candidate_shadow = original_shadow

    result = {
        "schema": "v80-p2-macro-a-runtime-differential/1",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "seed": SEED,
        "cases": CASE_COUNT,
        "equal": equal,
        "different": CASE_COUNT - equal - errors,
        "errors": errors,
        "baseline_size": baseline_result["size"],
        "baseline_sha256": baseline_result["sha256"],
        "development_size": development_result["size"],
        "development_sha256": development_result["sha256"],
        "vendor_size": vendor["size"],
        "vendor_sha256": vendor["sha256"],
        "closure_sha256": vendor["closure_sha256"],
        "module_count": len(vendor["modules"]),
        "overlay_input_size": overlay["input_size"],
        "overlay_input_sha256": overlay["input_sha256"],
        "overlay_insertion_count": len(overlay["insertions"]),
        "output_switch_input_size": output_switch["input_size"],
        "output_switch_input_sha256": output_switch["input_sha256"],
        "output_switch_size": output_switch["size"],
        "output_switch_sha256": output_switch["sha256"],
        "output_switch_insertion_count": len(output_switch["insertions"]),
        "controlled_switch_active": controlled_switch_active,
        "scenario_counts": dict(sorted(scenario_counts.items())),
        "scenario_differences": dict(sorted(scenario_differences.items())),
        "decision_counts": dict(sorted(decision_counts.items())),
        "report_status_counts": dict(sorted(report_status_counts.items())),
        "shadow_calls": len(shadow_results),
        "disabled_shadow_calls": disabled_shadow_calls,
        "redacted_reports": redacted_reports,
        "production_writes": False,
        "deployment_attempted": False,
        "first_failures": first_failures,
    }
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False))
    failures = validation_errors(result)
    if failures:
        print(
            "Macro A differential evidence failed: %s" % ", ".join(failures),
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

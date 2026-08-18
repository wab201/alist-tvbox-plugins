import argparse
import copy
import importlib.util
import json
import random
import re
import socket
import sys
import tempfile
import types
from collections import Counter
from concurrent.futures import Future
from contextlib import ExitStack, contextmanager
from pathlib import Path
from unittest.mock import patch

import requests


ROOT = Path(__file__).resolve().parents[1]
BUILD_PATH = ROOT / "tools" / "build_follow_plugin.py"
DEV_MANIFEST = ROOT / "src" / "douban_tmdb_follow_single" / "release.json"
BASELINE_MANIFEST = ROOT / "src" / "douban_tmdb_follow_single" / "baseline_v70.json"
REPORT_PATH = ROOT / "work" / "v80-p2-macro-b-differential.json"
SEED = 8021
CASE_COUNT = 50000
SCENARIOS = (
    "disabled",
    "insufficient_budget",
    "selected_provider",
    "selected_cache",
    "selected_recent",
    "selected_binding",
    "already_sampled",
    "shadow_exception",
    "empty_title",
    "selected_binding_only",
)


def validation_errors(payload, expected_cases=None, expected_seed=None):
    errors = []
    cases = payload.get("cases") if expected_cases is None else expected_cases
    seed = payload.get("seed") if expected_seed is None else expected_seed
    if type(cases) is not int or cases < 1 or cases % len(SCENARIOS):
        return ["cases must be a positive multiple of the scenario count"]
    per_scenario = cases // len(SCENARIOS)
    expected_scenarios = {name: per_scenario for name in SCENARIOS}
    expected_decisions = {
        "already_sampled": per_scenario,
        "insufficient_budget": per_scenario,
        "selected": per_scenario * 5,
    }
    expected_reports = {"observed": per_scenario * 5}
    checks = {
        "schema": payload.get("schema") == "v80-p2-macro-b-runtime-differential/1",
        "seed": payload.get("seed") == seed,
        "cases": payload.get("cases") == cases,
        "equal": payload.get("equal") == cases,
        "different": payload.get("different") == 0,
        "errors": payload.get("errors") == 0,
        "scenario_counts": payload.get("scenario_counts") == expected_scenarios,
        "decision_counts": payload.get("decision_counts") == expected_decisions,
        "report_status_counts": payload.get("report_status_counts") == expected_reports,
        "shadow_calls": payload.get("shadow_calls") == per_scenario * 8,
        "disabled_shadow_calls": payload.get("disabled_shadow_calls") == 0,
        "exception_calls": payload.get("exception_calls") == per_scenario,
        "redacted_reports": payload.get("redacted_reports") is True,
        "first_failures": payload.get("first_failures") == [],
        "production_writes": payload.get("production_writes") is False,
        "deployment_attempted": payload.get("deployment_attempted") is False,
        "baseline_size": type(payload.get("baseline_size")) is int and payload["baseline_size"] > 0,
        "development_size": type(payload.get("development_size")) is int and payload["development_size"] > 0,
        "vendor_size": type(payload.get("vendor_size")) is int and payload["vendor_size"] > 0,
        "module_count": payload.get("module_count") == 17,
        "overlay_input_size": type(payload.get("overlay_input_size")) is int and payload["overlay_input_size"] > 0,
        "overlay_insertion_count": payload.get("overlay_insertion_count") == 8,
        "output_switch_input_size": type(payload.get("output_switch_input_size")) is int and payload["output_switch_input_size"] > 0,
        "output_switch_size": payload.get("output_switch_size") == payload.get("development_size"),
        "output_switch_insertion_count": payload.get("output_switch_insertion_count") == 9,
        "controlled_switch_active": payload.get("controlled_switch_active") is True,
    }
    for name in (
            "baseline_sha256", "development_sha256", "vendor_sha256",
            "closure_sha256", "overlay_input_sha256",
            "output_switch_input_sha256", "output_switch_sha256"):
        checks[name] = bool(re.fullmatch(r"[0-9A-F]{64}", str(payload.get(name) or "")))
    errors.extend(name for name, valid in checks.items() if not valid)
    return errors


def _load_script(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BUILD = _load_script(BUILD_PATH, "v80_macro_b_build")


def _deny_network(*_args, **_kwargs):
    raise AssertionError("Macro B differential must remain offline")


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
            stack.enter_context(patch.object(requests, "request", _deny_network))
            stack.enter_context(patch.object(requests.Session, "request", _deny_network))
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


def _load_runtime(source, name, directory):
    path = Path(directory) / (name + ".py")
    path.write_bytes(source)
    return _load_script(path, name)


def _future(rows):
    future = Future()
    future.set_result([dict(row) for row in rows])
    return future


def _case(scenario, index, rng):
    marker = "%016x" % rng.getrandbits(64)
    title = "Macro B Title %d" % rng.randrange(997)
    item = {
        "title": title,
        "year": str(2000 + rng.randrange(27)),
        "tmdb_id": index + 1,
        "source_id": "source-%s" % marker,
    }
    mode = "vod"
    resource_id = "vod-%s" % marker
    row = {
        "vod_id": resource_id,
        "vod_name": title,
        "vod_year": item["year"],
        "_resource_mode": mode,
        "provider": "quark",
    }
    modes = (mode,)
    provider_rows = [row]
    cached_rows = []
    bindings = {}

    if scenario == "selected_cache":
        mode = "pansou"
        resource_id = "https://pan.quark.cn/s/%s" % marker
        row.update(vod_id=resource_id, _resource_mode=mode)
        modes = (mode,)
        provider_rows = []
        cached_rows = [row]
    elif scenario == "selected_recent":
        item["last_play_route"] = {
            "backend": "macro-b-backend",
            "resourceId": resource_id,
        }
    elif scenario == "selected_binding":
        bindings[str(item["tmdb_id"])] = resource_id
    elif scenario == "selected_binding_only":
        modes = ()
        provider_rows = []
        bindings[str(item["tmdb_id"])] = resource_id
    elif scenario == "empty_title":
        item["title"] = ""

    return {
        "scenario": scenario,
        "marker": marker,
        "item": item,
        "modes": modes,
        "provider_rows": provider_rows,
        "cached_rows": cached_rows,
        "bindings": bindings,
    }


def _configure(spider, case):
    spider.follow_alist_bindings = dict(case["bindings"])
    spider._follow_title_alias_values = lambda *_args, **_kwargs: []
    spider._available_resource_modes = lambda: tuple(case["modes"])
    spider._resource_capability_identity = lambda: "macro-b-backend"
    spider._resource_search_cache_key = (
        lambda _item, mode: "resource-search:%s:%s" % (mode, case["marker"])
    )
    spider._cache_get = lambda *_args, **_kwargs: [
        dict(row) for row in case["cached_rows"]
    ]
    spider._validated_resource_group_count = lambda rows: len(rows or ())
    spider._schedule_supplement_resource_search = lambda *_args, **_kwargs: False
    spider._submit_resource_mode_search = lambda mode, *_args, **_kwargs: _future(
        row for row in case["provider_rows"]
        if str(row.get("_resource_mode") or "vod") == mode
    )
    spider._diagnostic_event = lambda *_args, **_kwargs: None


def _build_evidence(cases, seed):
    baseline_build = BUILD.check_release(BASELINE_MANIFEST)
    development_build = BUILD.check_release(DEV_MANIFEST)
    vendor = development_build["vendor"]
    overlay = development_build["overlay"]
    output_switch = development_build["resource_output_switch_overlay"]
    scenario_counts = Counter()
    decision_counts = Counter()
    report_status_counts = Counter()
    first_failures = []
    equal = 0
    different = 0
    errors = 0
    shadow_calls = 0
    disabled_shadow_calls = 0
    exception_calls = 0
    redacted_reports = True

    with tempfile.TemporaryDirectory(prefix="v80-macro-b-differential-") as temp_name:
        with _offline_runtime():
            baseline_module = _load_runtime(
                baseline_build["bytes"], "v70_macro_b_runtime", temp_name,
            )
            development_module = _load_runtime(
                development_build["bytes"], "v80_macro_b_runtime", temp_name,
            )
            baseline_spider = baseline_module.Spider()
            development_spider = development_module.Spider()
            development_spider._alist_tvbox_plugin = True
            development_spider._v80_resource_layered_output_enabled = (
                development_spider._resource_layered_output_from_config({
                    "v80_resource_layered_output": True,
                })
            )
            controlled_switch_active = (
                development_spider._resource_layered_output_active()
            )
            original_shadow = development_module.run_resource_search_layered_shadow
            current = {"scenario": "", "marker": ""}

            def capture_shadow(*args, **kwargs):
                nonlocal shadow_calls, disabled_shadow_calls, exception_calls, redacted_reports
                shadow_calls += 1
                if current["scenario"] == "disabled":
                    disabled_shadow_calls += 1
                if current["scenario"] == "shadow_exception":
                    exception_calls += 1
                    raise RuntimeError("synthetic layered shadow failure")
                result = original_shadow(*args, **kwargs)
                decision_counts[result["decision"]["reason"]] += 1
                report = result.get("report")
                if report is not None:
                    report_status_counts[report.get("status")] += 1
                    rendered = repr(report)
                    if current["marker"] in rendered or "Macro B Title" in rendered:
                        redacted_reports = False
                return result

            development_module.run_resource_search_layered_shadow = capture_shadow
            rng = random.Random(seed)
            try:
                for index in range(cases):
                    scenario = SCENARIOS[index % len(SCENARIOS)]
                    scenario_counts[scenario] += 1
                    case = _case(scenario, index, rng)
                    current.update(scenario=scenario, marker=case["marker"])
                    _configure(baseline_spider, case)
                    _configure(development_spider, case)
                    development_spider._cache_generation = 0
                    development_spider._resource_search_layered_shadow_enabled = (
                        scenario not in ("disabled", "empty_title")
                    )
                    development_spider._resource_search_layered_shadow_budget_us = (
                        0 if scenario == "insufficient_budget"
                        else development_module.RESOURCE_SEARCH_LAYERED_SHADOW_ESTIMATED_COST_US
                    )
                    development_spider._resource_search_layered_shadow_sample_every = 1
                    development_spider._resource_search_layered_shadow_sampled_generation = (
                        0 if scenario == "already_sampled" else None
                    )
                    development_spider._resource_search_layered_shadow_last_report = None
                    try:
                        baseline_rows = baseline_spider._resource_candidates(
                            copy.deepcopy(case["item"])
                        )
                        development_rows = development_spider._resource_candidates(
                            copy.deepcopy(case["item"])
                        )
                    except Exception as exc:
                        errors += 1
                        if len(first_failures) < 5:
                            first_failures.append({
                                "case": index,
                                "scenario": scenario,
                                "error_type": type(exc).__name__,
                            })
                        continue
                    if development_rows == baseline_rows:
                        equal += 1
                    else:
                        different += 1
                        if len(first_failures) < 5:
                            first_failures.append({
                                "case": index,
                                "scenario": scenario,
                                "baseline_count": len(baseline_rows),
                                "development_count": len(development_rows),
                            })
            finally:
                baseline_spider.destroy()
                development_spider.destroy()

    return {
        "schema": "v80-p2-macro-b-runtime-differential/1",
        "seed": seed,
        "cases": cases,
        "equal": equal,
        "different": different,
        "errors": errors,
        "baseline_size": baseline_build["size"],
        "baseline_sha256": baseline_build["sha256"],
        "development_size": development_build["size"],
        "development_sha256": development_build["sha256"],
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
        "decision_counts": dict(sorted(decision_counts.items())),
        "report_status_counts": dict(sorted(report_status_counts.items())),
        "shadow_calls": shadow_calls,
        "disabled_shadow_calls": disabled_shadow_calls,
        "exception_calls": exception_calls,
        "redacted_reports": redacted_reports,
        "first_failures": first_failures,
        "production_writes": False,
        "deployment_attempted": False,
    }


def _write_report(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=int, default=CASE_COUNT)
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--json-out", type=Path, default=REPORT_PATH)
    args = parser.parse_args(argv)
    if args.cases < 1 or args.cases % len(SCENARIOS):
        parser.error("--cases must be a positive multiple of %d" % len(SCENARIOS))
    evidence = _build_evidence(args.cases, args.seed)
    _write_report(args.json_out, evidence)
    valid = not validation_errors(
        evidence, expected_cases=args.cases, expected_seed=args.seed,
    )
    print(json.dumps({
        "status": "passed" if valid else "failed",
        "cases": evidence["cases"],
        "equal": evidence["equal"],
        "different": evidence["different"],
        "errors": evidence["errors"],
        "shadow_calls": evidence["shadow_calls"],
        "report": str(args.json_out),
    }, ensure_ascii=False))
    return 0 if valid else 1


if __name__ == "__main__":
    raise SystemExit(main())

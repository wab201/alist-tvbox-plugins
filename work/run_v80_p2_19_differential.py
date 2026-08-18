import argparse
import importlib.util
import json
import random
import socket
import sys
import tempfile
import types
from collections import Counter
from contextlib import ExitStack, contextmanager
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import requests


ROOT = Path(__file__).resolve().parents[1]
BUILD_PATH = ROOT / "tools" / "build_follow_plugin.py"
VENDOR_BUILDER_PATH = ROOT / "tools" / "build_v80_resource_shadow_vendor.py"
DEV_MANIFEST = ROOT / "src" / "douban_tmdb_follow_single" / "release.json"
BASELINE_MANIFEST = ROOT / "src" / "douban_tmdb_follow_single" / "baseline_v70.json"
REPORT_PATH = ROOT / "work" / "v80-p2-19-differential.json"
SEED = 8019
CASE_COUNT = 50000
EXPECTED_FIXED_FIELDS = {
    "schema": "v80-p2-19-build-insertion-differential/1",
    "seed": SEED,
    "cases": CASE_COUNT,
    "equal": CASE_COUNT,
    "different": 0,
    "errors": 0,
    "baseline_size": 616699,
    "baseline_sha256": "233C73CAE1048210B34872D4A10EA6023662300F70A8657DB82EA65C342182D4",
    "development_size": 632769,
    "development_sha256": "F7590CEFD7A882CFED00D86745A68C210FB1D55B976D1228BF8AD7791D6F3172",
    "vendor_size": 16070,
    "vendor_sha256": "9610528E9023C77BA051F789C7C75437D0873AC0B7CC58DA20A87D4ECC9668FD",
    "closure_sha256": "00A8ECF9688B4677088C4C2E51F86039A19609C2CD6163544B1E8915629D8EB2",
    "module_count": 8,
    "prefix_equal": True,
    "suffix_equal": True,
    "production_writes": False,
    "deployment_attempted": False,
}
EXPECTED_REASON_COUNTS = {
    "already_sampled": 8334,
    "disabled": 8334,
    "insufficient_budget": 8333,
    "missing_key": 8333,
    "not_selected": 8333,
    "selected": 8333,
}
EXPECTED_REPORT_STATUS_COUNTS = {
    "different": 2778,
    "equal": 2778,
    "error": 2777,
}
EXPECTED_SAMPLE_KEY_LENGTH_COUNTS = {"0": 25001, "64": 24999}


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
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(name, None)
    return module


def _deny_network(*_args, **_kwargs):
    raise AssertionError("P2-19 differential must remain offline")


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


def _load_candidates():
    build = _load_script(BUILD_PATH, "v80_p2_19_build_pipeline")
    vendor_builder = _load_script(
        VENDOR_BUILDER_PATH, "v80_p2_19_vendor_builder"
    )
    baseline_result = build.build_release(BASELINE_MANIFEST)
    development_result = build.build_release(DEV_MANIFEST)
    vendor_result = vendor_builder.build_vendor()
    with tempfile.TemporaryDirectory(dir=str(ROOT / "work")) as directory:
        directory = Path(directory)
        vendor_path = directory / "vendor.py"
        development_path = directory / "development.py"
        vendor_path.write_bytes(vendor_result["bytes"])
        development_path.write_bytes(development_result["bytes"])
        with _offline_runtime():
            vendor = _load_source(vendor_path, "v80_p2_19_standalone_vendor")
            development = _load_source(
                development_path, "v80_p2_19_development_build"
            )
    return baseline_result, development_result, vendor_result, vendor, development


def merge_rows(left, right):
    merged = dict(left)
    for key, value in right.items():
        if merged.get(key) in (None, "", [], ()):
            merged[key] = value
    return merged


def score_row(row):
    if row.get("raise_score"):
        raise ValueError("private differential marker")
    return row.get("score", 0)


def preference_row(row):
    return tuple(row.get("preference") or ())


def provider_row(row):
    return row.get("provider")


CALLBACKS = {
    "merge_rows": merge_rows,
    "score_row": score_row,
    "preference_row": preference_row,
    "provider_row": provider_row,
}


def find_not_selected_cache_key(vendor):
    for index in range(1000):
        inputs = vendor.build_background_resource_candidate_shadow_inputs(
            enabled=True,
            cache_key="resource-search:not-selected-%d" % index,
            generation=19,
            sample_every=2,
            shadow_budget_us=vendor.RESOURCE_CANDIDATE_SHADOW_ESTIMATED_COST_US,
        )
        if vendor.decide_resource_candidate_shadow(**inputs)["reason"] == "not_selected":
            return "resource-search:not-selected-%d" % index
    raise AssertionError("not-selected bucket not found")


def make_rows(rng, index):
    modes = ("vod1", "vod", "pansou", "telegram")
    providers = ("quark", "baidu", "pan123", "unknown")
    rows = []
    for offset in range(1 + index % 5):
        resource = (index + offset) % 7
        rows.append({
            "vod_id": "resource-%d" % resource,
            "vod_name": "Title %d" % resource,
            "vod_year": "2026" if offset % 2 else "",
            "_resource_mode": modes[(index + offset) % len(modes)],
            "provider": providers[(index * 3 + offset) % len(providers)],
            "score": rng.randrange(-2, 20),
            "preference": (rng.randrange(0, 5), rng.randrange(0, 5)),
        })
    return rows


def make_case(rng, index, not_selected_key, estimated_cost):
    generation = rng.randrange(0, 100000)
    case = {
        "enabled": True,
        "cache_key": "resource-search:%064x" % rng.getrandbits(256),
        "generation": generation,
        "sampled_generation": None,
        "sample_every": 1,
        "shadow_budget_us": estimated_cost,
    }
    variant = index % 6
    if variant == 0:
        case["enabled"] = False
    elif variant == 1:
        case["sampled_generation"] = generation
    elif variant == 2:
        case["cache_key"] = ""
    elif variant == 3:
        case["shadow_budget_us"] = estimated_cost - 1
    elif variant == 4:
        case["cache_key"] = not_selected_key
        case["generation"] = 19
        case["sample_every"] = 2
    return case


def validation_errors(result):
    errors = [
        name
        for name, expected in EXPECTED_FIXED_FIELDS.items()
        if result.get(name) != expected
    ]
    if result.get("reason_counts") != EXPECTED_REASON_COUNTS:
        errors.append("reason_counts")
    if result.get("report_status_counts") != EXPECTED_REPORT_STATUS_COUNTS:
        errors.append("report_status_counts")
    if result.get("sample_key_length_counts") != EXPECTED_SAMPLE_KEY_LENGTH_COUNTS:
        errors.append("sample_key_length_counts")
    if result.get("first_failures") != []:
        errors.append("first_failures")
    return errors


def _parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json-out", type=Path, default=REPORT_PATH)
    return parser


def main(argv=None):
    args = _parser().parse_args(argv)
    baseline_result, development_result, vendor_result, vendor, development = (
        _load_candidates()
    )
    prefix_equal = development_result["bytes"].startswith(baseline_result["bytes"])
    suffix_equal = development_result["bytes"][baseline_result["size"] :] == vendor_result["bytes"]
    not_selected_key = find_not_selected_cache_key(vendor)
    estimated_cost = vendor.RESOURCE_CANDIDATE_SHADOW_ESTIMATED_COST_US
    rng = random.Random(SEED)
    equal = 0
    errors = 0
    reasons = Counter()
    report_statuses = Counter()
    key_lengths = Counter()
    first_failures = []

    for index in range(CASE_COUNT):
        case = make_case(rng, index, not_selected_key, estimated_cost)
        rows = make_rows(rng, index)
        report_variant = (index // 6) % 3
        if index % 6 == 5 and report_variant == 2:
            rows = [{"vod_id": "private-row-marker", "raise_score": True}]
            legacy = []
        else:
            legacy = vendor.order_resource_candidate_rows(rows, **CALLBACKS)
            if index % 6 == 5 and report_variant == 1:
                legacy = list(reversed(legacy))
                if len(legacy) < 2:
                    legacy.append({"vod_id": "different-only"})
        try:
            expected_inputs = vendor.build_background_resource_candidate_shadow_inputs(
                **case
            )
            actual_inputs = development.build_background_resource_candidate_shadow_inputs(
                **case
            )
            expected = vendor.compose_resource_candidate_shadow(
                legacy, rows, **expected_inputs, **CALLBACKS
            )
            actual = development.compose_resource_candidate_shadow(
                legacy, rows, **actual_inputs, **CALLBACKS
            )
        except Exception as exc:
            errors += 1
            if len(first_failures) < 10:
                first_failures.append({"index": index, "error_type": type(exc).__name__})
            continue

        reasons[expected["decision"]["reason"]] += 1
        key_lengths[len(expected_inputs["sample_key"])] += 1
        if expected["report"] is not None:
            report_statuses[expected["report"]["status"]] += 1
        if expected_inputs == actual_inputs and expected == actual:
            equal += 1
        elif len(first_failures) < 10:
            first_failures.append({
                "index": index,
                "expected_inputs": expected_inputs,
                "actual_inputs": actual_inputs,
                "expected": expected,
                "actual": actual,
            })

    result = {
        "schema": "v80-p2-19-build-insertion-differential/1",
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
        "vendor_size": vendor_result["size"],
        "vendor_sha256": vendor_result["sha256"],
        "closure_sha256": vendor_result["closure_sha256"],
        "module_count": len(vendor_result["modules"]),
        "prefix_equal": prefix_equal,
        "suffix_equal": suffix_equal,
        "reason_counts": dict(sorted(reasons.items())),
        "report_status_counts": dict(sorted(report_statuses.items())),
        "sample_key_length_counts": {
            str(key): value for key, value in sorted(key_lengths.items())
        },
        "production_writes": False,
        "deployment_attempted": False,
        "first_failures": first_failures,
    }
    args.json_out.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False))
    failures = validation_errors(result)
    if failures:
        print("P2-19 differential evidence failed: %s" % ", ".join(failures), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

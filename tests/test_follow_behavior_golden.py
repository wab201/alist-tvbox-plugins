# -*- coding: utf-8 -*-
"""Offline V70/V80 behavior equivalence fixture and command-line reporter."""

import argparse
import hashlib
import importlib.util
import json
import re
import socket
import sys
import threading
import types
from collections import OrderedDict
from contextlib import ExitStack, contextmanager
from pathlib import Path
from unittest.mock import patch

import requests


ROOT = Path(__file__).resolve().parent.parent
PUBLIC_V70_SOURCE = ROOT / "py" / "豆瓣TMDB追更单入口.py"
FIXTURE_PATH = ROOT / "tests" / "fixtures" / "v70_behavior_golden.json"
BUILD_SCRIPT = ROOT / "tools" / "build_follow_plugin.py"
DEV_MANIFEST = ROOT / "src" / "douban_tmdb_follow_single" / "release.json"
METADATA_PATTERN = re.compile(
    r"(?m)^\s*//@(?P<key>name|id|version):(?P<value>.*?)\s*$"
)


def _deny_network(*_args, **_kwargs):
    raise AssertionError("Golden behavior checks must remain offline")


def _sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest().upper()


def _load_source(path, module_name):
    spec = importlib.util.spec_from_file_location(module_name, str(path))
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load source: %s" % path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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


def _json_value(value):
    return json.loads(json.dumps(value, ensure_ascii=False, sort_keys=True))


def _source_metadata(path):
    text = Path(path).read_text(encoding="utf-8")
    values = {}
    for match in METADATA_PATTERN.finditer(text):
        values[match.group("key")] = match.group("value").strip()
    return values


def _call_case(module, case):
    owner_name = case.get("owner")
    owner = module if owner_name == "module" else getattr(module, owner_name)
    target = owner.__new__(owner) if case.get("instance") else owner
    if case.get("instance") and owner_name == "Spider":
        controller = getattr(module, "TimeoutBudgetController", None)
        if controller is not None:
            target._cache_generation = 0
            target._timeout_budget_controller = controller(generation=0)
    method = getattr(target, case["method"])
    return method(*case.get("args", []), **case.get("kwargs", {}))


def _cache_lookup_case(module, case):
    setup = case["setup"]
    target = module.Spider.__new__(module.Spider)
    target._cache_lock = threading.RLock()
    target._cache = OrderedDict(
        (key, (created, value)) for key, created, value in setup.get("entries", [])
    )
    target._persistent_cache = OrderedDict()
    target._persistent_cache_loaded = True
    target.stale_ttl = setup["stale_ttl"]
    target._schedule_response_cache_save = lambda: False
    with patch.object(module.time, "time", return_value=setup["now"]):
        return target._cache_get(setup["key"], setup["ttl"])


def _evaluate_case(module, source_path, case):
    kind = case.get("kind", "call")
    if kind == "source_metadata":
        return _source_metadata(source_path)
    if kind == "call":
        return _call_case(module, case)
    if kind == "cache_lookup":
        return _cache_lookup_case(module, case)
    raise ValueError("unsupported Golden case kind: %s" % kind)


def _evaluate(module, source_path, cases):
    return {
        case["name"]: _json_value(_evaluate_case(module, source_path, case))
        for case in cases
    }


def compare_behavior(baseline, candidate, fixture=FIXTURE_PATH):
    """Compare two sources against one deterministic fixture without pytest state."""
    baseline = Path(baseline).resolve()
    candidate = Path(candidate).resolve()
    fixture = Path(fixture).resolve()
    fixture_data = json.loads(fixture.read_text(encoding="utf-8"))
    if fixture_data.get("schema_version") != 2:
        raise ValueError("unsupported Golden fixture schema_version")
    cases = fixture_data.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("Golden fixture must contain cases")
    names = [case.get("name") for case in cases]
    if any(not name for name in names) or len(names) != len(set(names)):
        raise ValueError("Golden case names must be non-empty and unique")

    suffix = hashlib.sha256((str(baseline) + str(candidate)).encode("utf-8")).hexdigest()[:12]
    with _offline_runtime():
        public_module = _load_source(baseline, "follow_behavior_public_" + suffix)
        dev_module = _load_source(candidate, "follow_behavior_candidate_" + suffix)
        public_results = _evaluate(public_module, baseline, cases)
        dev_results = _evaluate(dev_module, candidate, cases)

    expected = {case["name"]: case["expected"] for case in cases}
    rows = []
    differences = []
    for case in cases:
        name = case["name"]
        public_value = public_results[name]
        candidate_value = dev_results[name]
        matches_expected = public_value == expected[name] and candidate_value == expected[name]
        equal = public_value == candidate_value and matches_expected
        difference = None if equal else {
            "expected": expected[name],
            "public": public_value,
            "candidate": candidate_value,
        }
        row = {
            "domain": case["domain"],
            "name": name,
            "status": "equal" if equal else "different",
            "public": public_value,
            "candidate": candidate_value,
            "difference": difference,
        }
        rows.append(row)
        if difference is not None:
            differences.append({
                "domain": case["domain"],
                "name": name,
                "difference": difference,
            })

    total = len(rows)
    different = len(differences)
    report = {
        "schema_version": 1,
        "fixture": {
            "path": str(fixture),
            "sha256": _sha256(fixture),
            "schema_version": fixture_data["schema_version"],
        },
        "baseline": {"path": str(baseline), "sha256": _sha256(baseline)},
        "candidate": {"path": str(candidate), "sha256": _sha256(candidate)},
        "cases": rows,
        "public_results": public_results,
        "dev_results": dev_results,
        "differences": differences,
        "summary": {"total": total, "equal": total - different, "different": different},
        "approval_required": different > 0,
        "approval": (
            "V80 behavior change requires explicit approval" if different else None
        ),
        "overall": "fail" if different else "pass",
    }
    return report


def _write_report(report, output):
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def test_public_v70_and_current_v80_build_match_behavior_golden(tmp_path):
    build_module = _load_source(BUILD_SCRIPT, "follow_behavior_build_pipeline")
    build = build_module.build_release(DEV_MANIFEST)
    candidate = tmp_path / "v80-candidate.py"
    candidate.write_bytes(build["bytes"])

    report = compare_behavior(PUBLIC_V70_SOURCE, candidate, FIXTURE_PATH)

    assert report["public_results"] == report["dev_results"]
    assert report["differences"] == []
    assert report["summary"]["different"] == 0
    assert report["approval_required"] is False
    assert report["approval"] is None
    assert report["overall"] == "pass"


def test_golden_fixture_is_utf8_without_bom_or_sensitive_runtime_data():
    raw = FIXTURE_PATH.read_bytes()
    text = raw.decode("utf-8").lower()

    assert not raw.startswith(b"\xef\xbb\xbf")
    assert "http" + "://" not in text
    assert "https" + "://" not in text
    for forbidden in (
            "author" + "ization", "coo" + "kie", "pass" + "word",
            "access" + "_token", "api" + "_token"):
        assert forbidden not in text


def _parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--fixture", type=Path, default=FIXTURE_PATH)
    parser.add_argument("--json-out", type=Path, required=True)
    return parser


def main(argv=None):
    args = _parser().parse_args(argv)
    try:
        report = compare_behavior(args.baseline, args.candidate, args.fixture)
        _write_report(report, args.json_out)
    except Exception as exc:
        print("Golden behavior error: %s" % exc, file=sys.stderr)
        return 2
    print(
        "Golden behavior: %s (%d equal, %d different)"
        % (report["overall"], report["summary"]["equal"], report["summary"]["different"])
    )
    return 0 if report["overall"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())

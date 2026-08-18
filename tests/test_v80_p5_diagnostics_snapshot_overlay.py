import ast
import importlib.util
import sys
import types
from functools import lru_cache
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parent.parent
BUILD_PATH = ROOT / "tools" / "build_follow_plugin.py"
RUNTIME_OVERLAY_PATH = ROOT / "tools" / "build_v80_observability_runtime_overlay.py"
SNAPSHOT_OVERLAY_PATH = ROOT / "tools" / "build_v80_diagnostics_snapshot_overlay.py"
MANIFEST_PATH = ROOT / "src" / "douban_tmdb_follow_single" / "release.json"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BUILD = _load("v80_p5_snapshot_build", BUILD_PATH)
RUNTIME_OVERLAY = _load("v80_p5_snapshot_runtime_overlay", RUNTIME_OVERLAY_PATH)
SNAPSHOT_OVERLAY = _load("v80_p5_snapshot_overlay", SNAPSHOT_OVERLAY_PATH)


@lru_cache(maxsize=1)
def _input_source():
    built = BUILD.build_release(MANIFEST_PATH)
    policy = built["observability_policy_module"]
    p5_1 = policy["input_bytes"] + policy["bytes"]
    return RUNTIME_OVERLAY.apply_observability_runtime_overlay(p5_1)["bytes"]


@lru_cache(maxsize=1)
def _overlay_result():
    return SNAPSHOT_OVERLAY.apply_diagnostics_snapshot_overlay(_input_source())


@lru_cache(maxsize=1)
def _runtime():
    base_module = types.ModuleType("base")
    spider_module = types.ModuleType("base.spider")

    class BaseSpider(object):
        pass

    spider_module.Spider = BaseSpider
    sys.modules.setdefault("base", base_module)
    sys.modules.setdefault("base.spider", spider_module)
    module = types.ModuleType("v80_p5_diagnostics_snapshot_runtime")
    exec(
        compile(_overlay_result()["bytes"], "v80-p5-diagnostics-snapshot.py", "exec"),
        module.__dict__,
    )
    return module


def _spider():
    return _runtime().Spider()


def test_overlay_is_deterministic_and_has_one_narrow_insertion():
    first = _overlay_result()
    second = SNAPSHOT_OVERLAY.apply_diagnostics_snapshot_overlay(_input_source())

    assert first == second
    assert first["insertions"] == ("diagnostics-snapshot-envelope",)
    assert first["input_size"] == 854396
    assert first["input_sha256"] == (
        "A4AE219E575441137ADD531DCF7FD86D41BBF64D4096C67D4FD8B8C25993A798"
    )
    assert first["size"] > first["input_size"]


def test_overlay_rejects_missing_and_duplicate_anchor():
    anchor = SNAPSHOT_OVERLAY.DIAGNOSTIC_SNAPSHOT_ANCHOR
    source = _input_source().decode("utf-8")
    with pytest.raises(
            SNAPSHOT_OVERLAY.DiagnosticsSnapshotOverlayError,
            match="must appear once"):
        SNAPSHOT_OVERLAY.apply_diagnostics_snapshot_overlay(
            source.replace(anchor, "", 1).encode("utf-8")
        )
    with pytest.raises(
            SNAPSHOT_OVERLAY.DiagnosticsSnapshotOverlayError,
            match="must appear once"):
        SNAPSHOT_OVERLAY.apply_diagnostics_snapshot_overlay(
            source.replace(anchor, anchor + anchor, 1).encode("utf-8")
        )


def test_overlay_rejects_invalid_utf8():
    with pytest.raises(
            SNAPSHOT_OVERLAY.DiagnosticsSnapshotOverlayError,
            match="not valid UTF-8"):
        SNAPSHOT_OVERLAY.apply_diagnostics_snapshot_overlay(b"\xff")


def test_empty_snapshot_uses_the_sealed_envelope_without_mutation():
    spider = _spider()
    try:
        before_sequence = spider._diagnostic_sequence
        snapshot = spider._diagnostic_snapshot()
        assert snapshot == {
            "schema": "v80-diagnostics-snapshot/1",
            "count": 0,
            "events": [],
        }
        assert spider._diagnostic_sequence == before_sequence
        assert spider._diagnostics == []
    finally:
        spider.destroy()


def test_snapshot_preserves_order_limit_and_invalid_limit_fallback():
    spider = _spider()
    try:
        for index in range(5):
            spider._diagnostic_event("snapshot.case", index=index)

        limited = spider._diagnostic_snapshot(3)
        assert limited["count"] == 3
        assert [event["seq"] for event in limited["events"]] == [3, 4, 5]
        assert spider._diagnostic_snapshot(0)["events"][0]["seq"] == 5
        assert spider._diagnostic_snapshot("invalid")["count"] == 5
        assert spider._diagnostic_snapshot(10000)["count"] == 5
    finally:
        spider.destroy()


def test_snapshot_is_bounded_by_the_sealed_policy_limit():
    spider = _spider()
    try:
        for index in range(300):
            spider._diagnostic_event("snapshot.bound", index=index)
        snapshot = spider._diagnostic_snapshot()
        assert snapshot["count"] == 256
        assert [snapshot["events"][0]["seq"], snapshot["events"][-1]["seq"]] == [45, 300]
    finally:
        spider.destroy()


def test_snapshot_returns_detached_event_and_list_copies():
    spider = _spider()
    try:
        spider._diagnostic_event("snapshot.detached", value="original")
        first = spider._diagnostic_snapshot()
        first["events"][0]["event"] = "changed"
        first["events"].append({"seq": 999})

        second = spider._diagnostic_snapshot()
        assert second["count"] == 1
        assert second["events"][0]["event"] == "snapshot.detached"
        assert second["events"][0]["value"] == "original"
    finally:
        spider.destroy()


def test_snapshot_does_not_add_clock_event_or_redaction_owners(monkeypatch):
    module = _runtime()
    spider = module.Spider()
    try:
        spider._diagnostic_event("snapshot.owner")
        before_sequence = spider._diagnostic_sequence
        before_events = list(spider._diagnostics)

        monkeypatch.setattr(
            module.time, "time",
            lambda: (_ for _ in ()).throw(AssertionError("clock called")),
        )
        spider._short_error = lambda *_args, **_kwargs: (
            (_ for _ in ()).throw(AssertionError("redaction called"))
        )

        snapshot = spider._diagnostic_snapshot()
        assert snapshot["count"] == 1
        assert spider._diagnostic_sequence == before_sequence
        assert spider._diagnostics == before_events
    finally:
        spider.destroy()


def test_overlay_keeps_one_snapshot_owner_and_adds_no_runtime_subsystem():
    tree = ast.parse(_overlay_result()["bytes"].decode("utf-8"))
    spider_class = next(
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "Spider"
    )
    methods = [
        node for node in spider_class.body
        if isinstance(node, ast.FunctionDef) and node.name == "_diagnostic_snapshot"
    ]
    assert len(methods) == 1

    overlay_text = SNAPSHOT_OVERLAY_PATH.read_text(encoding="utf-8")
    for forbidden in (
            "requests.", "Session(", "Retry(", "_cache_set(", "threading.",
            "Timer(", "time.time(", "time.monotonic(", "_diagnostic_event(",
            "_short_error(", "open(",
    ):
        assert forbidden not in overlay_text

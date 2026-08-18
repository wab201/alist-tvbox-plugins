import ast
import importlib.util
import re
import sys
import types
from functools import lru_cache
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parent.parent
BUILD_PATH = ROOT / "tools" / "build_follow_plugin.py"
OVERLAY_PATH = ROOT / "tools" / "build_v80_observability_runtime_overlay.py"
MANIFEST_PATH = ROOT / "src" / "douban_tmdb_follow_single" / "release.json"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BUILD = _load("v80_p5_runtime_correlation_build", BUILD_PATH)
OVERLAY = _load("v80_p5_runtime_correlation_overlay", OVERLAY_PATH)


@lru_cache(maxsize=1)
def _input_source():
    built = BUILD.build_release(MANIFEST_PATH)
    module = built["observability_policy_module"]
    return module["input_bytes"] + module["bytes"]


@lru_cache(maxsize=1)
def _overlay_result():
    return OVERLAY.apply_observability_runtime_overlay(_input_source())


@lru_cache(maxsize=1)
def _runtime():
    base_module = types.ModuleType("base")
    spider_module = types.ModuleType("base.spider")

    class BaseSpider(object):
        pass

    spider_module.Spider = BaseSpider
    sys.modules.setdefault("base", base_module)
    sys.modules.setdefault("base.spider", spider_module)
    module = types.ModuleType("v80_p5_runtime_correlation_runtime")
    exec(
        compile(_overlay_result()["bytes"], "v80-p5-runtime-correlation.py", "exec"),
        module.__dict__,
    )
    return module


def _spider(clock=lambda: 100.0):
    module = _runtime()
    spider = module.Spider()
    spider._timeout_budget_controller = module.TimeoutBudgetController(
        generation=spider._cache_generation,
        clock=clock,
    )
    return module, spider


def test_overlay_is_deterministic_and_has_fixed_narrow_insertions():
    first = _overlay_result()
    second = OVERLAY.apply_observability_runtime_overlay(_input_source())

    assert first == second
    assert first["insertions"] == (
        "timeout-operation-correlation-fields",
        "timeout-controller-correlation-sequence-slot",
        "timeout-controller-correlation-sequence-init",
        "timeout-controller-correlation-scope",
        "timeout-controller-diagnostic-context",
        "diagnostic-event-runtime-correlation",
    )
    assert first["input_size"] == len(_input_source())
    assert first["size"] > first["input_size"]
    final_build = BUILD.build_release(MANIFEST_PATH)
    assert first["size"] == final_build["diagnostics_snapshot_overlay"]["input_size"]
    assert first["sha256"] == (
        final_build["diagnostics_snapshot_overlay"]["input_sha256"]
    )


@pytest.mark.parametrize("index", range(6))
def test_overlay_rejects_missing_and_duplicate_anchors(index):
    _label, anchor, _replacement = OVERLAY.INSERTIONS[index]
    source = _input_source().decode("utf-8")
    with pytest.raises(OVERLAY.ObservabilityRuntimeOverlayError, match="must appear once"):
        OVERLAY.apply_observability_runtime_overlay(
            source.replace(anchor, "", 1).encode("utf-8")
        )
    with pytest.raises(OVERLAY.ObservabilityRuntimeOverlayError, match="must appear once"):
        OVERLAY.apply_observability_runtime_overlay(
            source.replace(anchor, anchor + anchor, 1).encode("utf-8")
        )


def test_overlay_rejects_invalid_utf8():
    with pytest.raises(OVERLAY.ObservabilityRuntimeOverlayError, match="not valid UTF-8"):
        OVERLAY.apply_observability_runtime_overlay(b"\xff")


def test_nested_timeout_operations_share_trace_and_restore_request_context():
    _module, spider = _spider()
    generation = spider._cache_generation
    try:
        with spider._timeout_budget_controller.scope(
                "category", 10, expected_generation=generation):
            outer = spider._diagnostic_event(
                "resource_mode.start", mode="pansou", duration_ms=12, count=3,
            )
            with spider._timeout_budget_controller.scope(
                    "resource_api_get", 5, expected_generation=generation):
                inner = spider._diagnostic_event(
                    "resource_mode.request", mode="pansou",
                )
            restored = spider._diagnostic_event("resource_mode.finish", mode="pansou")

        assert outer["schema"] == "v80-diagnostic-event/1"
        assert outer["stage"] == "search"
        assert outer["provider"] == "pansou"
        assert outer["elapsed_ms"] == 12
        assert outer["count"] == "3"
        assert outer["trace_id"] == inner["trace_id"] == restored["trace_id"]
        assert outer["request_id"] == restored["request_id"]
        assert inner["request_id"] != outer["request_id"]
        for event in (outer, inner, restored):
            assert re.fullmatch(r"[0-9a-f]{16}", event["request_id"])
            assert re.fullmatch(r"[0-9a-f]{16}", event["trace_id"])
    finally:
        spider.destroy()


def test_error_kind_maps_to_stable_error_code_without_changing_legacy_fields():
    module, spider = _spider()
    generation = spider._cache_generation
    try:
        with spider._timeout_budget_controller.scope(
                "resource_api_get", 10, expected_generation=generation):
            event = spider._diagnostic_event(
                "resource_mode.request",
                "WARN",
                exc=module.ReliabilityFailure("timeout", operation="resource_api_get"),
                duration_ms=8,
            )

        assert event["error_kind"] == "timeout"
        assert event["error_code"] == "V80-TIMEOUT"
        assert event["elapsed_ms"] == 8
        assert event["duration_ms"] == "8"
        assert "error" in event
    finally:
        spider.destroy()


def test_managed_fields_cannot_be_overridden_by_callers():
    module, spider = _spider()
    generation = spider._cache_generation
    try:
        with spider._timeout_budget_controller.scope(
                "resource_api_get", 10, expected_generation=generation):
            event = spider._diagnostic_event(
                "resource_mode.request",
                "WARN",
                exc=module.ReliabilityFailure("timeout", operation="resource_api_get"),
                schema="forged",
                stage="snapshot",
                request_id="foreign-request",
                trace_id="foreign-trace",
                error_code="FORGED",
                error_kind="forged",
                seq=999,
                elapsed_ms="not-a-number",
            )

        assert event["schema"] == "v80-diagnostic-event/1"
        assert event["stage"] == "search"
        assert event["error_kind"] == "timeout"
        assert event["error_code"] == "V80-TIMEOUT"
        assert event["seq"] != 999
        assert event["request_id"] != "foreign-request"
        assert event["trace_id"] != "foreign-trace"
        assert "elapsed_ms" not in event
    finally:
        spider.destroy()


def test_returned_event_is_detached_from_the_internal_buffer():
    _module, spider = _spider()
    try:
        event = spider._diagnostic_event("snapshot.detached", note="safe")
        stored = spider._diagnostics[-1]

        assert event == stored
        assert event is not stored

        event["late"] = (
            "Author" + "ization: " + "Bearer " + "late-secret-value"
        )
        event["nested"] = {"items": ["escaped"]}

        snapshot = spider._diagnostic_snapshot()
        assert "late" not in snapshot[0]
        assert "nested" not in snapshot[0]
        assert snapshot[0]["note"] == "safe"
    finally:
        spider.destroy()


@pytest.mark.parametrize("value", ("not-a-number", -1, float("inf"), float("nan")))
def test_invalid_elapsed_values_are_omitted(value):
    _module, spider = _spider()
    try:
        event = spider._diagnostic_event("standalone", elapsed_ms=value)
        assert "elapsed_ms" not in event
    finally:
        spider.destroy()


def test_sequential_same_name_operations_keep_unique_correlation_ids():
    _module, spider = _spider()
    generation = spider._cache_generation
    request_ids = []
    trace_ids = []
    try:
        for _index in range(64):
            with spider._timeout_budget_controller.scope(
                    "category", 10, expected_generation=generation):
                event = spider._diagnostic_event("resource_mode.start")
            request_ids.append(event["request_id"])
            trace_ids.append(event["trace_id"])
        assert len(set(request_ids)) == 64
        assert len(set(trace_ids)) == 64
    finally:
        spider.destroy()


def test_reset_invalidates_stale_thread_local_correlation_context():
    _module, spider = _spider()
    generation = spider._cache_generation
    operation = spider._timeout_budget_controller.scope(
        "category", 10, expected_generation=generation,
    )
    operation.__enter__()
    try:
        before = spider._diagnostic_event("resource_mode.start")
        spider._timeout_budget_controller.reset(generation + 1, closed=True)
        after = spider._diagnostic_event("resource_mode.finish")
        assert "request_id" in before
        assert "trace_id" in before
        assert "request_id" not in after
        assert "trace_id" not in after
    finally:
        operation.__exit__(None, None, None)
        spider.destroy()


@pytest.mark.parametrize(("event_name", "operation", "expected"), (
    ("history_sync.start", "category", "history"),
    ("cache.flush", "category", "cache"),
    ("follow.persist.local", "category", "lifecycle"),
    ("route_quality.flush", "category", "playback"),
    ("unknown", "playback_probe", "probe"),
    ("unknown", "detail", "detail"),
    ("unknown", "candidate_match", "match"),
    ("unknown", "category", "search"),
    ("unknown", "other", "request"),
))
def test_stage_mapping_is_closed_and_event_first(event_name, operation, expected):
    _module, spider = _spider()
    generation = spider._cache_generation
    try:
        with spider._timeout_budget_controller.scope(
                operation, 10, expected_generation=generation):
            event = spider._diagnostic_event(event_name)
        assert event["stage"] == expected
    finally:
        spider.destroy()


def test_no_active_operation_omits_correlation_ids_and_does_not_create_snapshot_schema():
    _module, spider = _spider()
    try:
        event = spider._diagnostic_event("standalone")
        assert event["schema"] == "v80-diagnostic-event/1"
        assert event["stage"] == "request"
        assert "request_id" not in event
        assert "trace_id" not in event
        assert "elapsed_ms" not in event
        assert "v80-diagnostics-snapshot/1" not in repr(spider._diagnostic_snapshot())
    finally:
        spider.destroy()


def test_provider_alias_and_existing_fields_share_the_p4_redaction_owner():
    _module, spider = _spider()
    generation = spider._cache_generation
    try:
        mode = "https" + "://cdn.example/video?" + "sign" + "ature=opaque-signature"
        note = "Author" + "ization: " + "Bearer " + "opaque-token"
        with spider._timeout_budget_controller.scope(
                "resource_api_get", 10, expected_generation=generation):
            event = spider._diagnostic_event(
                "resource_mode.request",
                mode=mode,
                note=note,
            )
        assert "opaque" not in repr(event)
        assert "***" in event["provider"]
        assert "***" in event["mode"]
        assert "***" in event["note"]
    finally:
        spider.destroy()


def test_overlay_keeps_one_event_owner_and_adds_no_runtime_subsystem():
    tree = ast.parse(_overlay_result()["bytes"].decode("utf-8"))
    spider_class = next(
        node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Spider"
    )
    methods = [
        node for node in spider_class.body
        if isinstance(node, ast.FunctionDef) and node.name == "_diagnostic_event"
    ]
    assert len(methods) == 1
    clock_calls = [
        node for node in ast.walk(methods[0])
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "time"
    ]
    assert [node.func.attr for node in clock_calls] == ["time"]

    overlay_text = OVERLAY_PATH.read_text(encoding="utf-8")
    for forbidden in (
            "requests.", "Session(", "Retry(", "_cache_set(", "open(",
            "time.monotonic(", "threading.", "Timer(",
            "_diagnostic_snapshot(",
    ):
        assert forbidden not in overlay_text

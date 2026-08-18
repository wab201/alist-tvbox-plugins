import ast
import hashlib
import importlib.util
import sys
import threading
import types
from concurrent.futures import Future
from functools import lru_cache
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parent.parent
BUILD_SCRIPT = ROOT / "tools" / "build_follow_plugin.py"
OVERLAY_SCRIPT = ROOT / "tools" / "build_v80_resource_shadow_overlay.py"
BASELINE_MANIFEST = ROOT / "src" / "douban_tmdb_follow_single" / "baseline_v70.json"
DEV_MANIFEST = ROOT / "src" / "douban_tmdb_follow_single" / "release.json"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_runtime(name, path):
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
        return _load(name, path)
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
    def submit(self, function, *args, **kwargs):
        future = Future()
        try:
            future.set_result(function(*args, **kwargs))
        except BaseException as exc:
            future.set_exception(exc)
        return future

    def shutdown(self, *args, **kwargs):
        return None


class _TrackingRLock:
    def __init__(self):
        self._lock = threading.RLock()
        self.depth = 0

    def acquire(self, *args, **kwargs):
        acquired = self._lock.acquire(*args, **kwargs)
        if acquired:
            self.depth += 1
        return acquired

    def release(self):
        self.depth -= 1
        self._lock.release()

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.release()


@pytest.fixture(scope="module")
def runtime_module(tmp_path_factory):
    path = tmp_path_factory.mktemp("v80-shadow-runtime") / "candidate.py"
    path.write_bytes(_build_result()["bytes"])
    return _load_runtime("v80_shadow_runtime_candidate", path)


@pytest.fixture
def runtime_spider(runtime_module, request):
    spider = runtime_module.Spider()
    spider._resource_search_executor = _InlineExecutor()
    spider._cache_lock = _TrackingRLock()
    cache_writes = []
    row = {
        "vod_id": "private-resource-id",
        "_resource_mode": "pansou",
        "provider": "quark",
        "score": 10,
        "preference": (2, 1),
    }

    def submit_search(*_args, **_kwargs):
        future = Future()
        future.set_result([dict(row)])
        return future

    spider._submit_resource_mode_search = submit_search
    spider._resource_fair_candidate_order = (
        lambda rows, *_args, **_kwargs: list(rows)
    )
    spider._checked_resource_rows = lambda rows, *_args, **_kwargs: list(rows)
    spider._playable_resource_rows = lambda rows, *_args, **_kwargs: list(rows)
    spider._cache_set = lambda key, rows: cache_writes.append((key, list(rows)))
    spider._validated_resource_group_count = lambda _rows: 0
    spider._schedule_active_detail_refresh = lambda _item: False
    spider._merge_resource_rows = lambda left, right, *_args: dict(left, **right)
    spider._resource_score = lambda value, *_args: value.get("score", 0)
    spider._resource_row_preference = (
        lambda value, *_args: tuple(value.get("preference") or ())
    )
    spider._resource_provider_key = lambda *values: next(
        (str(value) for value in values if value), ""
    )
    request.addfinalizer(spider.destroy)
    return spider, cache_writes


def _schedule(spider, cache_key):
    return spider._schedule_supplement_resource_search(
        ["pansou"],
        ["Example"],
        {"title": "Example", "year": "2026"},
        cache_key,
    )


def _resource_candidates(spider, order_events=None):
    row = {
        "vod_id": "private-layered-resource-id",
        "vod_name": "Example",
        "_resource_mode": "vod",
    }

    def submit_search(*_args, **_kwargs):
        future = Future()
        future.set_result([dict(row)])
        return future

    def order(rows, *_args, **_kwargs):
        if order_events is not None:
            order_events.append("order")
        return list(rows)

    spider._follow_title_alias_values = lambda *_args, **_kwargs: []
    spider._available_resource_modes = lambda: ("vod",)
    spider._submit_resource_mode_search = submit_search
    spider._resource_fair_candidate_order = order
    spider._resource_search_cache_key = lambda *_args: "resource-search:layered"
    spider._diagnostic_event = lambda *_args, **_kwargs: None
    spider.follow_alist_bindings = {}
    return spider._resource_candidates({"title": "Example"})


BUILD = _load("v80_overlay_build", BUILD_SCRIPT)
OVERLAY = _load("v80_runtime_overlay", OVERLAY_SCRIPT)


@lru_cache(maxsize=1)
def _build_result():
    return BUILD.build_release(DEV_MANIFEST)


def _pre_overlay_bytes():
    baseline = BUILD.check_release(BASELINE_MANIFEST)
    vendor = BUILD._load_resource_shadow_vendor_builder().build_vendor()
    return baseline["bytes"] + vendor["bytes"]


def test_development_build_applies_the_fixed_runtime_overlay():
    result = _build_result()
    tree = ast.parse(result["bytes"].decode("utf-8"))
    spider = next(
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "Spider"
    )
    calls = [
        node for node in ast.walk(spider)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in (
            "run_background_resource_candidate_shadow",
            "run_resource_search_layered_shadow",
        )
    ]

    assert result["overlay"] == {
        "size": 684806,
        "sha256": "299C4B60A9F558677B2749FCE669FB81C1E367E37C6126D8946B64FFAC05A2C1",
        "input_size": 681672,
        "input_sha256": "761EB09F5184A9B9914295A43B0A2F5AF1C46A414F8B0D0456477CA9A3639C01",
        "insertions": (
            "state", "reset", "destroy", "worker", "order", "payload", "call", "layered",
        ),
    }
    assert sorted(node.func.id for node in calls) == [
        "run_background_resource_candidate_shadow",
        "run_resource_search_layered_shadow",
    ]


def test_runtime_overlay_input_is_exactly_v70_plus_the_fixed_vendor():
    source = _pre_overlay_bytes()
    result = _build_result()

    assert len(source) == result["overlay"]["input_size"]
    assert hashlib.sha256(source).hexdigest().upper() == result["overlay"]["input_sha256"]


def test_runtime_overlay_rejects_any_missing_fixed_anchor():
    source = _pre_overlay_bytes().replace(
        OVERLAY.STATE_ANCHOR.encode("utf-8"),
        b"        self._resource_search_admissions = 0\n",
        1,
    )

    with pytest.raises(OVERLAY.RuntimeOverlayError, match="anchor state"):
        OVERLAY.apply_runtime_overlay(source)


def test_generated_runtime_defaults_disabled_and_preserves_committed_rows(
        runtime_module, runtime_spider, monkeypatch):
    spider, cache_writes = runtime_spider

    def unexpected_shadow(*_args, **_kwargs):
        raise AssertionError("disabled shadow must not be called")

    monkeypatch.setattr(
        runtime_module, "run_background_resource_candidate_shadow", unexpected_shadow,
    )

    assert _schedule(spider, "disabled") is True
    assert cache_writes == [("disabled", [{
        "vod_id": "private-resource-id",
        "_resource_mode": "pansou",
        "provider": "quark",
        "score": 10,
        "preference": (2, 1),
    }])]
    assert spider._resource_candidate_shadow_last_report is None
    assert spider._resource_search_jobs == {}
    assert not hasattr(spider, "_resource_search_admissions")


def test_private_output_switch_requires_raw_plugin_mode(runtime_spider):
    spider, _cache_writes = runtime_spider

    spider._alist_tvbox_plugin = False
    assert spider._resource_layered_output_from_config({
        "v80_resource_layered_output": True,
    }) is False
    spider._alist_tvbox_plugin = True
    assert spider._resource_layered_output_from_config({}) is False
    assert spider._resource_layered_output_from_config({
        "v80_resource_layered_output": True,
    }) is True


def test_private_output_switch_routes_foreground_and_background_through_one_combiner(
        runtime_module, runtime_spider, monkeypatch):
    spider, cache_writes = runtime_spider
    calls = []

    def combine(rows, **kwargs):
        calls.append({
            "ids": [row.get("vod_id") for row in rows],
            "modes": tuple(kwargs["available_modes"]),
            "binding": kwargs["binding_resource_id"],
            "recent": kwargs["recent_resource_id"],
        })
        return list(rows)

    monkeypatch.setattr(runtime_module, "combine_v70_layered_resource_rows", combine)
    spider._resource_fair_candidate_order = lambda *_args, **_kwargs: (
        (_ for _ in ()).throw(AssertionError("enabled output bypassed shared combiner"))
    )
    spider._v80_resource_layered_output_enabled = True
    spider.follow_alist_bindings = {}

    assert [row["vod_id"] for row in _resource_candidates(spider)] == [
        "private-layered-resource-id",
    ]

    def submit_background(*_args, **_kwargs):
        future = Future()
        future.set_result([{
            "vod_id": "private-resource-id",
            "_resource_mode": "pansou",
            "provider": "quark",
            "score": 10,
            "preference": (2, 1),
        }])
        return future

    spider._submit_resource_mode_search = submit_background
    assert _schedule(spider, "layered-output") is True

    assert calls == [
        {
            "ids": ["private-layered-resource-id"],
            "modes": ("vod",),
            "binding": "",
            "recent": "",
        },
        {
            "ids": ["private-resource-id"],
            "modes": ("pansou",),
            "binding": "",
            "recent": "",
        },
    ]
    assert cache_writes[-1][0] == "layered-output"


def test_private_output_switch_falls_back_to_legacy_order_on_combiner_failure(
        runtime_module, runtime_spider, monkeypatch):
    spider, cache_writes = runtime_spider
    legacy_calls = []

    def legacy_order(rows, *_args, **_kwargs):
        legacy_calls.append([row.get("vod_id") for row in rows])
        return list(reversed(list(rows)))

    monkeypatch.setattr(
        runtime_module,
        "combine_v70_layered_resource_rows",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("score failed")),
    )
    spider._resource_fair_candidate_order = legacy_order
    spider._v80_resource_layered_output_enabled = True
    spider.follow_alist_bindings = {}

    rows = [{"vod_id": "first"}, {"vod_id": "second"}]
    assert [row["vod_id"] for row in spider._resource_output_candidate_order(
        rows, {"title": "Example"}, modes=("pansou",),
    )] == ["second", "first"]

    assert _schedule(spider, "layered-output-fallback") is True
    assert cache_writes[-1][0] == "layered-output-fallback"
    assert legacy_calls


def test_private_output_switch_disabled_keeps_background_legacy_bound_empty(
        runtime_spider):
    spider, cache_writes = runtime_spider
    observed_bounds = []

    def legacy_order(rows, *_args, **kwargs):
        observed_bounds.append(kwargs.get("bound"))
        return list(rows)

    spider._resource_fair_candidate_order = legacy_order
    spider._v80_resource_layered_output_enabled = False
    spider.follow_alist_bindings = {"123": "bound-resource"}

    assert spider._schedule_supplement_resource_search(
        ["pansou"],
        ["Example"],
        {"title": "Example", "year": "2026", "tmdb_id": "123"},
        "legacy-bound",
    ) is True
    assert observed_bounds == [""]
    assert cache_writes[-1][0] == "legacy-bound"


def test_private_output_switch_shadow_compares_actual_layered_production_order(
        runtime_module, runtime_spider):
    spider, cache_writes = runtime_spider
    rows = [
        {
            "vod_id": "bound-resource",
            "_resource_mode": "pansou",
            "provider": "quark",
            "score": 1,
            "preference": (1,),
        },
        {
            "vod_id": "high-resource",
            "_resource_mode": "pansou",
            "provider": "baidu",
            "score": 10,
            "preference": (10,),
        },
    ]

    def submit_search(*_args, **_kwargs):
        future = Future()
        future.set_result([dict(row) for row in rows])
        return future

    spider._submit_resource_mode_search = submit_search
    spider._resource_fair_candidate_order = lambda values, *_args, **_kwargs: sorted(
        values, key=lambda row: row["preference"], reverse=True,
    )
    spider._v80_resource_layered_output_enabled = True
    spider._resource_candidate_shadow_enabled = True
    spider._resource_candidate_shadow_sample_every = 1
    spider._resource_candidate_shadow_budget_us = (
        runtime_module.RESOURCE_CANDIDATE_SHADOW_ESTIMATED_COST_US
    )
    spider._resource_candidate_shadow_sampled_generation = None
    spider.follow_alist_bindings = {"123": "bound-resource"}

    assert spider._schedule_supplement_resource_search(
        ["pansou"],
        ["Example"],
        {"title": "Example", "year": "2026", "tmdb_id": "123"},
        "layered-shadow",
    ) is True
    assert [row["vod_id"] for row in cache_writes[-1][1]] == [
        "bound-resource", "high-resource",
    ]
    assert spider._resource_candidate_shadow_last_report == {
        "status": "different",
        "legacy_count": 2,
        "candidate_count": 2,
        "first_difference": 0,
        "error_type": "",
    }


def test_layered_runtime_defaults_disabled_before_fair_order(
        runtime_module, runtime_spider, monkeypatch):
    spider, _cache_writes = runtime_spider
    events = []
    monkeypatch.setattr(
        runtime_module,
        "run_resource_search_layered_shadow",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not run")),
    )

    rows = _resource_candidates(spider, events)

    assert events == ["order"]
    assert [row["vod_id"] for row in rows] == ["private-layered-resource-id"]
    assert spider._resource_search_layered_shadow_last_report is None


def test_layered_runtime_runs_before_fair_order_with_independent_budget(
        runtime_module, runtime_spider, monkeypatch):
    spider, _cache_writes = runtime_spider
    spider._resource_search_layered_shadow_enabled = True
    spider._resource_search_layered_shadow_budget_us = (
        runtime_module.RESOURCE_SEARCH_LAYERED_SHADOW_ESTIMATED_COST_US
    )
    production_budgets = (
        spider.RESOURCE_HOT_VALIDATION_BUDGET,
        spider.RESOURCE_SEARCH_BUDGET,
    )
    original = runtime_module.run_resource_search_layered_shadow
    events = []

    def capture(*args, **kwargs):
        events.append("shadow")
        return original(*args, **kwargs)

    monkeypatch.setattr(runtime_module, "run_resource_search_layered_shadow", capture)

    rows = _resource_candidates(spider, events)

    assert events == ["shadow", "order"]
    assert [row["vod_id"] for row in rows] == ["private-layered-resource-id"]
    assert spider._resource_search_layered_shadow_last_report == {
        "status": "observed",
        "input_count": 1,
        "candidate_count": 1,
        "batch_count": 1,
        "layers": ({
            "layer": "fast_provider", "mode": "vod", "candidate_count": 1,
        },),
        "error_type": "",
    }
    assert "private-layered-resource-id" not in repr(
        spider._resource_search_layered_shadow_last_report
    )
    assert production_budgets == (
        spider.RESOURCE_HOT_VALIDATION_BUDGET,
        spider.RESOURCE_SEARCH_BUDGET,
    )


def test_layered_runtime_failure_does_not_change_v70_output(
        runtime_module, runtime_spider, monkeypatch):
    spider, _cache_writes = runtime_spider
    spider._resource_search_layered_shadow_enabled = True
    monkeypatch.setattr(
        runtime_module,
        "run_resource_search_layered_shadow",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("shadow failed")),
    )

    rows = _resource_candidates(spider)

    assert [row["vod_id"] for row in rows] == ["private-layered-resource-id"]


def test_destroy_clears_layered_shadow_lifecycle_state(runtime_spider):
    spider, _cache_writes = runtime_spider
    generation = spider._cache_generation
    spider._resource_search_layered_shadow_sampled_generation = generation
    spider._resource_search_layered_shadow_last_report = {"status": "observed"}

    spider.destroy()

    assert spider._cache_generation == generation + 1
    assert spider._resource_search_layered_shadow_sampled_generation is None
    assert spider._resource_search_layered_shadow_last_report is None


def test_generated_runtime_records_one_redacted_report_from_dedicated_budget(
        runtime_module, runtime_spider):
    spider, cache_writes = runtime_spider
    spider._resource_candidate_shadow_enabled = True
    spider._resource_candidate_shadow_budget_us = (
        runtime_module.RESOURCE_CANDIDATE_SHADOW_ESTIMATED_COST_US
    )
    production_budgets = (
        spider.RESOURCE_HOT_VALIDATION_BUDGET,
        spider.RESOURCE_SEARCH_BUDGET,
    )

    assert _schedule(spider, "enabled") is True
    assert len(cache_writes) == 1
    assert spider._resource_candidate_shadow_last_report == {
        "status": "equal",
        "legacy_count": 1,
        "candidate_count": 1,
        "first_difference": -1,
        "error_type": "",
    }
    assert "private-resource-id" not in str(
        spider._resource_candidate_shadow_last_report
    )
    assert spider._resource_candidate_shadow_sampled_generation == 0
    assert spider._resource_candidate_shadow_budget_us == (
        runtime_module.RESOURCE_CANDIDATE_SHADOW_ESTIMATED_COST_US
    )
    assert production_budgets == (
        spider.RESOURCE_HOT_VALIDATION_BUDGET,
        spider.RESOURCE_SEARCH_BUDGET,
    )


def test_generated_runtime_does_not_materialize_rows_before_budget_admission(
        runtime_module, runtime_spider, monkeypatch):
    spider, _cache_writes = runtime_spider
    spider._resource_candidate_shadow_enabled = True
    spider._resource_candidate_shadow_budget_us = 0
    original = runtime_module.run_background_resource_candidate_shadow
    observed = []

    def capture(owner, legacy_rows, rows, **kwargs):
        observed.append(legacy_rows[0] is rows[0])
        result = original(owner, legacy_rows, rows, **kwargs)
        observed.append(result["decision"])
        return result

    monkeypatch.setattr(
        runtime_module, "run_background_resource_candidate_shadow", capture,
    )

    assert _schedule(spider, "zero-budget") is True
    assert observed == [True, {"run": False, "reason": "insufficient_budget"}]
    assert spider._resource_candidate_shadow_last_report is None


def test_generated_runtime_samples_only_once_per_generation(
        runtime_module, runtime_spider, monkeypatch):
    spider, _cache_writes = runtime_spider
    spider._resource_candidate_shadow_enabled = True
    spider._resource_candidate_shadow_budget_us = (
        runtime_module.RESOURCE_CANDIDATE_SHADOW_ESTIMATED_COST_US
    )
    original = runtime_module.run_background_resource_candidate_shadow
    decisions = []
    score_calls = []
    original_score = spider._resource_score

    def score(row, *args):
        score_calls.append(row["vod_id"])
        return original_score(row, *args)

    def capture(*args, **kwargs):
        result = original(*args, **kwargs)
        decisions.append(result["decision"])
        return result

    spider._resource_score = score
    monkeypatch.setattr(
        runtime_module, "run_background_resource_candidate_shadow", capture,
    )

    assert _schedule(spider, "first") is True
    first_score_count = len(score_calls)
    assert _schedule(spider, "second") is True

    assert decisions == [
        {"run": True, "reason": "selected"},
        {"run": False, "reason": "already_sampled"},
    ]
    assert first_score_count > 0
    assert len(score_calls) == first_score_count


def test_generated_runtime_discards_report_after_lifecycle_change(
        runtime_module, runtime_spider, monkeypatch):
    spider, _cache_writes = runtime_spider
    spider._resource_candidate_shadow_enabled = True
    spider._resource_candidate_shadow_budget_us = (
        runtime_module.RESOURCE_CANDIDATE_SHADOW_ESTIMATED_COST_US
    )
    original = runtime_module.run_background_resource_candidate_shadow
    results = []

    def change_generation(*args, **kwargs):
        original_score = spider._resource_score

        def score(row, *score_args):
            value = original_score(row, *score_args)
            spider._cache_generation += 1
            return value

        spider._resource_score = score
        try:
            result = original(*args, **kwargs)
        finally:
            spider._resource_score = original_score
        results.append(result)
        return result

    monkeypatch.setattr(
        runtime_module, "run_background_resource_candidate_shadow", change_generation,
    )

    assert _schedule(spider, "lifecycle") is True
    assert results[0]["decision"] == {"run": True, "reason": "selected"}
    assert spider._cache_generation > 0
    assert spider._resource_candidate_shadow_sampled_generation is None
    assert spider._resource_candidate_shadow_last_report is None


def test_generated_runtime_hook_runs_after_search_cleanup(
        runtime_module, runtime_spider, monkeypatch):
    spider, cache_writes = runtime_spider
    spider._resource_candidate_shadow_enabled = True
    spider._resource_candidate_shadow_budget_us = (
        runtime_module.RESOURCE_CANDIDATE_SHADOW_ESTIMATED_COST_US
    )
    original = runtime_module.run_background_resource_candidate_shadow
    observed = []

    def capture(owner, *args, **kwargs):
        observed.append({
            "jobs": dict(owner._resource_search_jobs),
            "cache_lock_depth": owner._cache_lock.depth,
            "cache_writes": len(cache_writes),
        })
        return original(owner, *args, **kwargs)

    monkeypatch.setattr(
        runtime_module, "run_background_resource_candidate_shadow", capture,
    )

    assert _schedule(spider, "cleanup-order") is True
    assert observed == [{
        "jobs": {},
        "cache_lock_depth": 0,
        "cache_writes": 1,
    }]

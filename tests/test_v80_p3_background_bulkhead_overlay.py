import ast
import hashlib
import importlib.util
import sys
import threading
import types
from functools import lru_cache
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parent.parent
BUILD_PATH = ROOT / "tools" / "build_follow_plugin.py"
OVERLAY_PATH = ROOT / "tools" / "build_v80_background_bulkhead_overlay.py"
MANIFEST_PATH = ROOT / "src" / "douban_tmdb_follow_single" / "release.json"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BUILD = _load("v80_background_bulkhead_build", BUILD_PATH)
OVERLAY = _load("v80_background_bulkhead_overlay", OVERLAY_PATH)


@lru_cache(maxsize=1)
def _build_result():
    return BUILD.build_release(MANIFEST_PATH)


def _pre_overlay_source():
    module = _build_result()["background_bulkhead_module"]
    return module["input_bytes"] + module["bytes"]


def _class(tree, name):
    rows = [
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == name
    ]
    assert len(rows) == 1
    return rows[0]


def _method(class_node, name):
    rows = [
        node for node in class_node.body
        if isinstance(node, ast.FunctionDef) and node.name == name
    ]
    assert len(rows) == 1
    return rows[0]


def _bulkhead_calls(node):
    return [
        item for item in ast.walk(node)
        if isinstance(item, ast.Call)
        and isinstance(item.func, ast.Attribute)
        and item.func.attr == "_submit_background_bulkhead_task"
    ]


def test_overlay_applies_exact_insertions_and_matches_timeout_module_input():
    source = _pre_overlay_source()
    result = OVERLAY.apply_background_bulkhead_overlay(source)
    built = _build_result()

    assert result["insertions"] == (
        "state", "task-runtime", "init-reset", "destroy-reset",
        "bound-replacement", "entry-preheat", "supplement-search",
        "history-refresh", "history-action", "route-probe",
    )
    assert result["input_size"] == len(source)
    assert result["input_sha256"] == hashlib.sha256(source).hexdigest().upper()
    assert result["size"] == len(result["bytes"])
    assert result["sha256"] == hashlib.sha256(result["bytes"]).hexdigest().upper()
    assert result["bytes"] == built["timeout_budget_module"]["input_bytes"]


def test_overlay_wires_one_fixed_lane_at_each_background_seam():
    tree = ast.parse(_build_result()["bytes"])
    compile(tree, "v80-background-bulkhead-overlay.py", "exec")
    spider = _class(tree, "Spider")
    expected = {
        "_schedule_bound_route_replacement": "resource_completion",
        "_schedule_entry_resource_preheat": "resource_completion",
        "_schedule_supplement_resource_search": "resource_completion",
        "_schedule_atvp_history_refresh": "history",
        "_start_atvp_job": "history",
        "_schedule_route_preheat": "route_probe",
    }

    for method_name, lane in expected.items():
        calls = _bulkhead_calls(_method(spider, method_name))
        assert len(calls) == 1
        assert isinstance(calls[0].args[0], ast.Constant)
        assert calls[0].args[0].value == lane


@pytest.mark.parametrize("label,anchor,_replacement", OVERLAY.INSERTIONS)
def test_overlay_rejects_each_missing_anchor(label, anchor, _replacement):
    source = _pre_overlay_source().decode("utf-8").replace(anchor, "", 1)
    with pytest.raises(OVERLAY.BackgroundBulkheadOverlayError, match="anchor %s" % label):
        OVERLAY.apply_background_bulkhead_overlay(source.encode("utf-8"))


@pytest.mark.parametrize("label,anchor,_replacement", OVERLAY.INSERTIONS)
def test_overlay_rejects_each_duplicate_anchor(label, anchor, _replacement):
    source = _pre_overlay_source().decode("utf-8").replace(anchor, anchor + anchor, 1)
    with pytest.raises(OVERLAY.BackgroundBulkheadOverlayError, match="anchor %s" % label):
        OVERLAY.apply_background_bulkhead_overlay(source.encode("utf-8"))


def test_overlay_rejects_invalid_utf8():
    with pytest.raises(OVERLAY.BackgroundBulkheadOverlayError, match="not valid UTF-8"):
        OVERLAY.apply_background_bulkhead_overlay(b"\xff")


def _load_runtime():
    base_module = types.ModuleType("base")
    spider_module = types.ModuleType("base.spider")

    class BaseSpider(object):
        pass

    spider_module.Spider = BaseSpider
    sys.modules.setdefault("base", base_module)
    sys.modules.setdefault("base.spider", spider_module)
    module = types.ModuleType("v80_background_bulkhead_runtime")
    source = _build_result()["bytes"]
    exec(compile(source, "v80-background-bulkhead-runtime.py", "exec"), module.__dict__)
    return module


class _QueuedExecutor(object):
    def __init__(self):
        self.work = []

    def submit(self, worker):
        self.work.append(worker)
        return object()


class _FailingExecutor(object):
    def submit(self, _worker):
        raise RuntimeError("closed")


def test_runtime_helper_releases_thread_capacity_after_completion(monkeypatch):
    module = _load_runtime()
    spider = module.Spider()
    finished = threading.Event()
    released = threading.Event()

    def worker():
        finished.set()

    controller_type = type(spider._background_bulkhead_controller)
    original_release = controller_type._release

    def release(controller, lane, generation):
        result = original_release(controller, lane, generation)
        released.set()
        return result

    monkeypatch.setattr(controller_type, "_release", release)
    try:
        assert spider._submit_background_bulkhead_task(
            "history", 0, worker, "history-test",
        ) is True
        assert finished.wait(2.0)
        assert released.wait(2.0)
        assert spider._background_bulkhead_controller.snapshot()["inflight"]["history"] == 0
    finally:
        spider.destroy()


def test_runtime_helper_bounds_queued_work_and_keeps_lanes_independent():
    module = _load_runtime()
    spider = module.Spider()
    executor = _QueuedExecutor()
    try:
        for index in range(10):
            assert spider._submit_background_bulkhead_task(
                "resource_completion", 0, lambda: None,
                "resource-%s" % index, executor=executor,
            ) is True
        assert spider._submit_background_bulkhead_task(
            "resource_completion", 0, lambda: None,
            "resource-rejected", executor=executor,
        ) is False
        assert spider._submit_background_bulkhead_task(
            "route_probe", 0, lambda: None,
            "route-independent", executor=executor,
        ) is True
        snapshot = spider._background_bulkhead_controller.snapshot()
        assert snapshot["inflight"]["resource_completion"] == 10
        assert snapshot["rejected"]["resource_completion"] == 1
        assert snapshot["inflight"]["route_probe"] == 1

        for worker in executor.work:
            worker()
        assert spider._background_bulkhead_controller.snapshot()["inflight"] == {
            "resource_completion": 0,
            "history": 0,
            "route_probe": 0,
        }
    finally:
        spider.destroy()


def test_runtime_helper_releases_capacity_when_executor_rejects_submission():
    module = _load_runtime()
    spider = module.Spider()
    try:
        with pytest.raises(RuntimeError, match="closed"):
            spider._submit_background_bulkhead_task(
                "history", 0, lambda: None, "history-test", executor=_FailingExecutor(),
            )
        assert spider._background_bulkhead_controller.snapshot()["inflight"]["history"] == 0
    finally:
        spider.destroy()


def test_runtime_reset_fences_old_queued_completion():
    module = _load_runtime()
    spider = module.Spider()
    executor = _QueuedExecutor()
    try:
        assert spider._submit_background_bulkhead_task(
            "history", 0, lambda: None, "old-history", executor=executor,
        ) is True
        spider._background_bulkhead_controller.reset(1)
        spider._timeout_budget_controller.reset(1)
        assert spider._submit_background_bulkhead_task(
            "history", 1, lambda: None, "new-history", executor=executor,
        ) is True
        with pytest.raises(module.ReliabilityFailure) as exc_info:
            executor.work[0]()
        assert exc_info.value.kind == "cancelled"
        assert spider._background_bulkhead_controller.snapshot()["inflight"]["history"] == 1
        executor.work[1]()
        assert spider._background_bulkhead_controller.snapshot()["inflight"]["history"] == 0
    finally:
        spider.destroy()


def test_runtime_history_rejection_cleans_refresh_claim(monkeypatch):
    module = _load_runtime()
    spider = module.Spider()
    monkeypatch.setattr(spider, "_submit_background_bulkhead_task", lambda *args, **kwargs: False)
    try:
        assert spider._schedule_atvp_history_refresh("history-cache", lightweight=True) is False
        assert "snapshot-background" not in spider._atvp_jobs
        assert "history-cache" not in spider._refreshing_cache_keys
    finally:
        spider.destroy()


def test_runtime_manual_history_rejection_cleans_job_claim(monkeypatch):
    module = _load_runtime()
    spider = module.Spider()
    monkeypatch.setattr(spider, "_submit_background_bulkhead_task", lambda *args, **kwargs: False)
    try:
        message = spider._start_atvp_job("probe")
        assert "繁忙" in message
        assert "probe" not in spider._atvp_jobs
    finally:
        spider.destroy()


def test_runtime_manual_history_start_failure_keeps_startup_diagnostic(monkeypatch):
    module = _load_runtime()
    spider = module.Spider()

    def fail(*_args, **_kwargs):
        raise RuntimeError("thread pool closed")

    monkeypatch.setattr(spider._tasks, "start_thread", fail)
    try:
        message = spider._start_atvp_job("probe")
        assert "启动失败" in message
        assert "繁忙" not in message
        assert "probe" not in spider._atvp_jobs
    finally:
        spider.destroy()


def test_runtime_resource_rejections_clean_all_job_claims(monkeypatch):
    module = _load_runtime()
    spider = module.Spider()
    spider._alist_tvbox_plugin = True
    spider.route_preheat = True
    spider.atvp_api = "https://atvp.invalid"
    spider.atvp_token = "token"
    spider._atvp_session = object()
    monkeypatch.setattr(spider, "_submit_background_bulkhead_task", lambda *args, **kwargs: False)
    monkeypatch.setattr(spider, "_ready_resource_rows", lambda _item: [])
    item = {"title": "Series", "tmdb_id": 1}
    try:
        assert spider._schedule_bound_route_replacement(item, "vod-old") is False
        assert spider._bound_replacement_jobs == {}
        assert spider._schedule_entry_resource_preheat([item]) is False
        assert spider._resource_entry_preheat_jobs == {}
        assert spider._schedule_supplement_resource_search(
            ["pansou"], ["Series"], item, "resource-cache",
        ) is False
        assert spider._resource_search_jobs == {}
        assert spider._refreshing_cache_keys == {}
        assert not hasattr(spider, "_resource_search_admissions")
    finally:
        spider._atvp_session = None
        spider.destroy()


def test_runtime_route_probe_rejection_cleans_job_claim(monkeypatch):
    module = _load_runtime()
    spider = module.Spider()
    spider.route_preheat = True
    spider.atvp_api = "https://atvp.invalid"
    spider.atvp_token = "token"
    spider._atvp_session = object()
    monkeypatch.setattr(spider, "_submit_background_bulkhead_task", lambda *args, **kwargs: False)
    records = [{
        "episode_key": (1, 1),
        "resource_id": "vod-1",
        "payload": {"url": "play-1", "resourceMode": "vod"},
    }]
    try:
        spider._schedule_route_preheat(records, {"history_episode": "S01E01"})
        assert spider._route_probe_jobs == {}
    finally:
        spider._atvp_session = None
        spider.destroy()

import ast
import hashlib
import importlib.util
import sys
import types
from functools import lru_cache
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parent.parent
BUILD_PATH = ROOT / "tools" / "build_follow_plugin.py"
OVERLAY_PATH = ROOT / "tools" / "build_v80_cache_health_overlay.py"
MANIFEST_PATH = ROOT / "src" / "douban_tmdb_follow_single" / "release.json"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BUILD = _load("v80_cache_health_build", BUILD_PATH)
OVERLAY = _load("v80_cache_health_overlay", OVERLAY_PATH)


@lru_cache(maxsize=1)
def _build_result():
    return BUILD.build_release(MANIFEST_PATH)


def _pre_overlay_source():
    module = _build_result()["cache_health_module"]
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


def _named_calls(node, name):
    return [
        item for item in ast.walk(node)
        if isinstance(item, ast.Call)
        and isinstance(item.func, ast.Name)
        and item.func.id == name
    ]


def test_overlay_applies_exact_insertions_and_matches_cache_health_stage():
    source = _pre_overlay_source()
    result = OVERLAY.apply_cache_health_overlay(source)
    built = _build_result()

    assert result["insertions"] == (
        "coordinator", "tmdb", "state", "init-reset", "destroy-reset",
        "douban-json", "douban-text", "refresh", "history",
    )
    assert result["input_size"] == len(source)
    assert result["input_sha256"] == hashlib.sha256(source).hexdigest().upper()
    assert result["size"] == len(result["bytes"])
    assert result["sha256"] == hashlib.sha256(result["bytes"]).hexdigest().upper()
    assert result["bytes"] == built["background_bulkhead_module"]["input_bytes"]
    assert result["bytes"] != built["bytes"]
    assert (
        built["background_bulkhead_overlay"]["size"]
        == built["timeout_budget_module"]["input_size"]
    )
    assert (
        built["background_bulkhead_overlay"]["sha256"]
        == built["timeout_budget_module"]["input_sha256"]
    )


def test_overlay_output_has_one_bounded_call_at_each_cache_seam():
    tree = ast.parse(OVERLAY.apply_cache_health_overlay(_pre_overlay_source())["bytes"])
    compile(tree, "v80-cache-health-overlay.py", "exec")
    spider = _class(tree, "Spider")
    tmdb = _class(tree, "_TMDBClient")

    assert len(_named_calls(_method(tmdb, "api"), "v80_cache_load")) == 1
    assert len(_named_calls(_method(spider, "_get_json"), "v80_cache_load")) == 1
    assert len(_named_calls(_method(spider, "_get_text"), "v80_cache_load")) == 1
    assert len(_named_calls(
        _method(spider, "_schedule_cache_refresh"),
        "v80_cache_schedule_refresh",
    )) == 1
    assert len(_named_calls(_method(spider, "__init__"), "CacheHealthController")) == 1

    for method_name in ("_get_json", "_get_text", "_schedule_cache_refresh"):
        assert not any(
            isinstance(item, (ast.For, ast.AsyncFor, ast.While))
            for item in ast.walk(_method(spider, method_name))
        )


@pytest.mark.parametrize("label,anchor,_replacement", OVERLAY.INSERTIONS)
def test_overlay_rejects_each_missing_anchor(label, anchor, _replacement):
    source = _pre_overlay_source().decode("utf-8").replace(anchor, "", 1)
    with pytest.raises(OVERLAY.CacheHealthOverlayError, match="anchor %s" % label):
        OVERLAY.apply_cache_health_overlay(source.encode("utf-8"))


@pytest.mark.parametrize("label,anchor,_replacement", OVERLAY.INSERTIONS)
def test_overlay_rejects_each_duplicate_anchor(label, anchor, _replacement):
    source = _pre_overlay_source().decode("utf-8").replace(anchor, anchor + anchor, 1)
    with pytest.raises(OVERLAY.CacheHealthOverlayError, match="anchor %s" % label):
        OVERLAY.apply_cache_health_overlay(source.encode("utf-8"))


def test_overlay_rejects_invalid_utf8():
    with pytest.raises(OVERLAY.CacheHealthOverlayError, match="not valid UTF-8"):
        OVERLAY.apply_cache_health_overlay(b"\xff")


def _load_runtime():
    base_module = types.ModuleType("base")
    spider_module = types.ModuleType("base.spider")

    class BaseSpider(object):
        pass

    spider_module.Spider = BaseSpider
    sys.modules.setdefault("base", base_module)
    sys.modules.setdefault("base.spider", spider_module)
    module = types.ModuleType("v80_cache_health_runtime")
    source = _build_result()["bytes"]
    exec(compile(source, "v80-cache-health-runtime.py", "exec"), module.__dict__)
    return module


def test_runtime_douban_and_tmdb_methods_route_through_shared_policy(monkeypatch):
    module = _load_runtime()
    spider = module.Spider()
    calls = []

    def shared(owner, key, ttl, loader, allow_stale=True):
        calls.append((owner, key, ttl, allow_stale, loader()))
        return calls[-1][-1]

    monkeypatch.setattr(module, "v80_cache_load", shared)
    monkeypatch.setattr(spider, "_request_json", lambda url, params: {"json": url})
    monkeypatch.setattr(spider, "_request_text", lambda url, params: "text:" + url)
    spider.cache_ttl = 180

    assert spider._get_json("https://douban.invalid", {"a": 1}) == {
        "json": "https://douban.invalid",
    }
    assert spider._get_text(
        "https://douban.invalid/page", custom_key="text:custom",
    ) == "text:https://douban.invalid/page"

    spider.tmdb_access_token = "credential"
    spider.tmdb_api_key = ""
    spider.tmdb_api_base = "https://tmdb.invalid"
    spider.tmdb_language = "zh-CN"
    spider.list_cache_ttl = 600
    monkeypatch.setattr(spider, "_require_tmdb_credentials", lambda: None)
    monkeypatch.setattr(spider, "_request_tmdb", lambda path, query: {"path": path})
    assert spider._tmdb_client.api("/search", allow_stale=False) == {"path": "/search"}

    assert [row[3] for row in calls] == [True, True, False]
    assert calls[1][1] == "text:custom"
    assert calls[2][1].startswith("tmdb-json:")
    spider.destroy()


def test_runtime_history_nonblocking_refresh_honors_cache_backoff(monkeypatch):
    module = _load_runtime()
    spider = module.Spider()
    monkeypatch.setattr(spider, "_has_cached_failure", lambda _key: True)

    assert spider._schedule_atvp_history_refresh(
        "atvp-history-snapshot", lightweight=True,
    ) is False
    assert "snapshot-background" not in spider._atvp_jobs
    assert "atvp-history-snapshot" not in spider._refreshing_cache_keys
    spider.destroy()

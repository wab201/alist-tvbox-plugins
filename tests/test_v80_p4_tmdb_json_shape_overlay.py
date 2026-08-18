import importlib.util
import sys
import types
from functools import lru_cache
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parent.parent
BUILD_PATH = ROOT / "tools" / "build_follow_plugin.py"
OVERLAY_PATH = ROOT / "tools" / "build_v80_tmdb_json_shape_overlay.py"
MANIFEST_PATH = ROOT / "src" / "douban_tmdb_follow_single" / "release.json"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BUILD = _load("v80_tmdb_json_shape_build", BUILD_PATH)
OVERLAY = _load("v80_tmdb_json_shape_overlay", OVERLAY_PATH)


@lru_cache(maxsize=1)
def _input_source():
    built = BUILD.build_release(MANIFEST_PATH)
    module = built["json_shape_policy_module"]
    return module["input_bytes"] + module["bytes"]


@lru_cache(maxsize=1)
def _overlay_result():
    return OVERLAY.apply_tmdb_json_shape_overlay(_input_source())


@lru_cache(maxsize=1)
def _runtime():
    base_module = types.ModuleType("base")
    spider_module = types.ModuleType("base.spider")

    class BaseSpider(object):
        pass

    spider_module.Spider = BaseSpider
    sys.modules.setdefault("base", base_module)
    sys.modules.setdefault("base.spider", spider_module)
    module = types.ModuleType("v80_tmdb_json_shape_runtime")
    exec(
        compile(_overlay_result()["bytes"], "v80-tmdb-json-shape-runtime.py", "exec"),
        module.__dict__,
    )
    return module


class JsonResponse(object):
    def __init__(self, status=200, payload=None, json_error=None):
        self.status_code = status
        self.payload = {} if payload is None else payload
        self.json_error = json_error
        self.headers = {}
        self.close_calls = 0

    def json(self):
        if self.json_error is not None:
            raise self.json_error
        return self.payload

    def close(self):
        self.close_calls += 1


class Session(object):
    def __init__(self, response):
        self.response = response
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, dict(kwargs)))
        return self.response

    def close(self):
        return None


def _spider(response):
    spider = _runtime().Spider()
    spider._tmdb_session = Session(response)
    return spider


def _nested_list(depth):
    value = None
    for _index in range(depth):
        value = [value]
    return value


def test_overlay_is_deterministic_and_has_one_narrow_insertion():
    first = _overlay_result()
    second = OVERLAY.apply_tmdb_json_shape_overlay(_input_source())

    assert first == second
    assert first["insertions"] == ("tmdb-json-shape",)
    assert first["input_size"] == 825944
    assert first["input_sha256"] == (
        "8FB4EEDAB97057412D622881A074BDA6D04F76617B81CA6802B6D34525FB70F0"
    )


def test_overlay_rejects_missing_duplicate_anchor_and_invalid_utf8():
    _label, anchor, _replacement = OVERLAY.INSERTIONS[0]
    source = _input_source().decode("utf-8")
    with pytest.raises(OVERLAY.TmdbJsonShapeOverlayError, match="must appear once"):
        OVERLAY.apply_tmdb_json_shape_overlay(source.replace(anchor, "", 1).encode("utf-8"))
    with pytest.raises(OVERLAY.TmdbJsonShapeOverlayError, match="must appear once"):
        OVERLAY.apply_tmdb_json_shape_overlay(source.replace(anchor, anchor + anchor, 1).encode("utf-8"))
    with pytest.raises(OVERLAY.TmdbJsonShapeOverlayError, match="not valid UTF-8"):
        OVERLAY.apply_tmdb_json_shape_overlay(b"\xff")


def test_successful_tmdb_json_is_validated_after_status_checks_and_keeps_identity():
    payload = {"results": [{"id": 1}]}
    response = JsonResponse(payload=payload)
    spider = _spider(response)
    try:
        result = spider._request_tmdb("/test", {"page": 1})
        assert result is payload
        assert response.close_calls == 1
        assert spider._tmdb_session.calls[0][1]["stream"] is True
    finally:
        spider.destroy()


def test_successful_tmdb_json_shape_rejection_closes_response_once():
    response = JsonResponse(payload={"data": _nested_list(64)})
    spider = _spider(response)
    try:
        with pytest.raises(_runtime().V80JsonShapeError) as exc_info:
            spider._request_tmdb("/test", {})
        assert exc_info.value.reason == "too_deep"
        assert response.close_calls == 1
    finally:
        spider.destroy()


@pytest.mark.parametrize("status,expected", (
    (401, "TMDB API 凭据无效或无权访问"),
    (403, "TMDB API 凭据无效或无权访问"),
    (429, "TMDB API 请求过于频繁，请稍后刷新"),
    (500, "upstream unavailable"),
))
def test_non_200_errors_keep_existing_pre_shape_semantics(status, expected):
    payload = {"status_message": "upstream unavailable", "data": _nested_list(64)}
    response = JsonResponse(status=status, payload=payload)
    spider = _spider(response)
    try:
        with pytest.raises(RuntimeError, match=expected):
            spider._request_tmdb("/test", {})
        assert response.close_calls == 1
    finally:
        spider.destroy()


def test_successful_non_json_error_keeps_existing_message_and_close_owner():
    response = JsonResponse(status=200, json_error=ValueError("invalid"))
    spider = _spider(response)
    try:
        with pytest.raises(RuntimeError, match="上游返回了非 JSON 内容"):
            spider._request_tmdb("/test", {})
        assert response.close_calls == 1
    finally:
        spider.destroy()


def test_overlay_owns_no_response_reader_cache_retry_or_timeout_policy():
    source = OVERLAY_PATH.read_text(encoding="utf-8")
    assert "response.json" not in source
    assert "_cache_" not in source
    assert "Retry(" not in source
    assert "TimeoutBudget" not in source
    assert "v80_validate_json_shape(data)" in source

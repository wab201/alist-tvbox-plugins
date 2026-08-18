import ast
import importlib.util
import json
import sys
import types
from functools import lru_cache
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parent.parent
BUILD_PATH = ROOT / "tools" / "build_follow_plugin.py"
OVERLAY_PATH = ROOT / "tools" / "build_v80_tmdb_response_boundary_overlay.py"
MANIFEST_PATH = ROOT / "src" / "douban_tmdb_follow_single" / "release.json"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BUILD = _load("v80_tmdb_response_boundary_build", BUILD_PATH)
OVERLAY = _load("v80_tmdb_response_boundary_overlay", OVERLAY_PATH)


@lru_cache(maxsize=1)
def _input_source():
    built = BUILD.build_release(MANIFEST_PATH)
    module = built["tmdb_response_policy_module"]
    return module["input_bytes"] + module["bytes"]


@lru_cache(maxsize=1)
def _overlay_result():
    return OVERLAY.apply_tmdb_response_boundary_overlay(_input_source())


@lru_cache(maxsize=1)
def _runtime():
    base_module = types.ModuleType("base")
    spider_module = types.ModuleType("base.spider")

    class BaseSpider(object):
        pass

    spider_module.Spider = BaseSpider
    sys.modules.setdefault("base", base_module)
    sys.modules.setdefault("base.spider", spider_module)
    module = types.ModuleType("v80_tmdb_response_boundary_runtime")
    exec(
        compile(_overlay_result()["bytes"], "v80-tmdb-response-boundary-runtime.py", "exec"),
        module.__dict__,
    )
    return module


class StreamResponse(object):
    def __init__(self, body=b"{}", status=200, content_length=True, chunks=None):
        self.status_code = status
        self.body = bytes(body)
        self.headers = {}
        if content_length:
            self.headers["Content-Length"] = str(len(self.body))
        self.chunks = chunks
        self.json_calls = 0
        self.iter_calls = 0
        self.close_calls = 0

    def json(self):
        self.json_calls += 1
        return json.loads(self.body)

    def iter_content(self, chunk_size=65536):
        self.iter_calls += 1
        if self.chunks is not None:
            for chunk in self.chunks:
                yield chunk
            return
        for offset in range(0, len(self.body), chunk_size):
            yield self.body[offset:offset + chunk_size]

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


def _body(payload):
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _json_body_with_exact_size(size):
    prefix = b'{"items":['
    suffix = b"]}"
    chunk_size = 64 * 1024
    full_count = 31
    last_size = (
        size
        - len(prefix)
        - len(suffix)
        - full_count * (chunk_size + 2)
        - full_count
        - 2
    )
    assert 0 <= last_size <= 128 * 1024
    values = [b'"' + (b"a" * chunk_size) + b'"' for _index in range(full_count)]
    values.append(b'"' + (b"b" * last_size) + b'"')
    body = prefix + b",".join(values) + suffix
    assert len(body) == size
    json.loads(body)
    return body


def _nested_list(depth):
    value = None
    for _index in range(depth):
        value = [value]
    return value


def test_overlay_is_deterministic_and_has_two_narrow_insertions():
    first = _overlay_result()
    second = OVERLAY.apply_tmdb_response_boundary_overlay(_input_source())

    assert first == second
    assert first["insertions"] == (
        "json-response-bounded-mode",
        "tmdb-response-boundary",
    )
    assert first["bytes"] == BUILD.build_release(MANIFEST_PATH)[
        "diagnostic_redaction_policy_module"
    ]["input_bytes"]


@pytest.mark.parametrize("index", (0, 1))
def test_overlay_rejects_missing_and_duplicate_anchors(index):
    _label, anchor, _replacement = OVERLAY.INSERTIONS[index]
    source = _input_source().decode("utf-8")
    with pytest.raises(OVERLAY.TmdbResponseBoundaryOverlayError, match="must appear once"):
        OVERLAY.apply_tmdb_response_boundary_overlay(
            source.replace(anchor, "", 1).encode("utf-8")
        )
    with pytest.raises(OVERLAY.TmdbResponseBoundaryOverlayError, match="must appear once"):
        OVERLAY.apply_tmdb_response_boundary_overlay(
            source.replace(anchor, anchor + anchor, 1).encode("utf-8")
        )


def test_overlay_rejects_invalid_utf8():
    with pytest.raises(OVERLAY.TmdbResponseBoundaryOverlayError, match="not valid UTF-8"):
        OVERLAY.apply_tmdb_response_boundary_overlay(b"\xff")


def test_exact_response_byte_boundary_is_accepted_and_plus_one_is_rejected():
    limit = _runtime().V80_TMDB_RESPONSE_LIMITS["max_response_bytes"]
    accepted = StreamResponse(_json_body_with_exact_size(limit))
    accepted_spider = _spider(accepted)
    try:
        result = accepted_spider._request_tmdb("/test", {})
        assert len(result["items"]) == 32
        assert accepted.iter_calls == 1
        assert accepted.json_calls == 0
        assert accepted.close_calls == 1
    finally:
        accepted_spider.destroy()

    rejected = StreamResponse(_json_body_with_exact_size(limit + 1))
    rejected_spider = _spider(rejected)
    try:
        with pytest.raises(RuntimeError, match="TMDB 响应过大"):
            rejected_spider._request_tmdb("/test", {})
        assert rejected.iter_calls == 0
        assert rejected.json_calls == 0
        assert rejected.close_calls == 1
    finally:
        rejected_spider.destroy()


def test_content_length_rejection_happens_before_iteration():
    limit = _runtime().V80_TMDB_RESPONSE_LIMITS["max_response_bytes"]
    response = StreamResponse(b"{}")
    response.headers["Content-Length"] = str(limit + 1)
    spider = _spider(response)
    try:
        with pytest.raises(RuntimeError, match="TMDB 响应过大"):
            spider._request_tmdb("/test", {})
        assert response.iter_calls == 0
        assert response.close_calls == 1
    finally:
        spider.destroy()


def test_chunked_overflow_is_rejected_after_crossing_the_limit():
    limit = _runtime().V80_TMDB_RESPONSE_LIMITS["max_response_bytes"]
    response = StreamResponse(
        body=b"",
        content_length=False,
        chunks=(b"x" * limit, b"y"),
    )
    spider = _spider(response)
    try:
        with pytest.raises(RuntimeError, match="TMDB 响应过大"):
            spider._request_tmdb("/test", {})
        assert response.iter_calls == 1
        assert response.close_calls == 1
    finally:
        spider.destroy()


def test_successful_invalid_json_keeps_existing_message():
    response = StreamResponse(b"not-json")
    spider = _spider(response)
    try:
        with pytest.raises(RuntimeError, match="上游返回了非 JSON 内容"):
            spider._request_tmdb("/test", {})
        assert response.close_calls == 1
    finally:
        spider.destroy()


@pytest.mark.parametrize("status,expected", (
    (401, "TMDB API 凭据无效或无权访问"),
    (403, "TMDB API 凭据无效或无权访问"),
    (429, "TMDB API 请求过于频繁，请稍后刷新"),
))
def test_fixed_status_errors_win_before_oversized_body(status, expected):
    limit = _runtime().V80_TMDB_RESPONSE_LIMITS["max_response_bytes"]
    response = StreamResponse(b"x" * (limit + 1), status=status)
    spider = _spider(response)
    try:
        with pytest.raises(RuntimeError, match=expected):
            spider._request_tmdb("/test", {})
        assert response.iter_calls == 0
        assert response.close_calls == 1
    finally:
        spider.destroy()


@pytest.mark.parametrize("body", (b"not-json", b"x" * 32))
def test_generic_non_200_unreadable_body_falls_back_to_http_status(body):
    response = StreamResponse(body, status=500)
    if body.startswith(b"x"):
        response.headers["Content-Length"] = str(
            _runtime().V80_TMDB_RESPONSE_LIMITS["max_response_bytes"] + 1
        )
    spider = _spider(response)
    try:
        with pytest.raises(RuntimeError, match="TMDB HTTP 500"):
            spider._request_tmdb("/test", {})
        assert response.close_calls == 1
    finally:
        spider.destroy()


def test_generic_non_200_valid_status_message_is_preserved():
    response = StreamResponse(_body({"status_message": "upstream unavailable"}), status=500)
    spider = _spider(response)
    try:
        with pytest.raises(RuntimeError, match="upstream unavailable"):
            spider._request_tmdb("/test", {})
        assert response.close_calls == 1
    finally:
        spider.destroy()


def test_shape_validation_runs_before_field_length_validation():
    limit = _runtime().V80_TMDB_RESPONSE_LIMITS["max_string_bytes"]
    response = StreamResponse(_body({
        "data": _nested_list(64),
        "description": "x" * (limit + 1),
    }))
    spider = _spider(response)
    try:
        with pytest.raises(_runtime().V80JsonShapeError) as exc_info:
            spider._request_tmdb("/test", {})
        assert exc_info.value.reason == "too_deep"
        assert response.close_calls == 1
    finally:
        spider.destroy()


@pytest.mark.parametrize("payload,reason", (
    ({"description": "x" * (128 * 1024 + 1)}, "string_too_long"),
    ({"k" * 1025: None}, "key_too_long"),
))
def test_successful_field_limit_rejection_is_stable(payload, reason):
    response = StreamResponse(_body(payload))
    spider = _spider(response)
    try:
        with pytest.raises(_runtime().V80TmdbResponsePolicyError) as exc_info:
            spider._request_tmdb("/test", {})
        assert exc_info.value.reason == reason
        assert response.close_calls == 1
    finally:
        spider.destroy()


def test_unbounded_json_response_callers_keep_the_one_argument_behavior():
    response = StreamResponse(b"[]", status=200)
    spider = _spider(response)
    try:
        assert spider._json_response(response) == {"data": []}
        assert response.json_calls == 1
        assert response.iter_calls == 0
        assert response.close_calls == 0
    finally:
        spider.destroy()


def test_tmdb_request_disables_requests_automatic_redirects():
    response = StreamResponse(_body({"ok": True}))
    spider = _spider(response)
    try:
        assert spider._request_tmdb("/test", {}) == {"ok": True}
        assert len(spider._tmdb_session.calls) == 1
        assert spider._tmdb_session.calls[0][1]["allow_redirects"] is False
        assert response.close_calls == 1
    finally:
        spider.destroy()


def test_overlay_keeps_single_transport_timeout_reader_and_close_owners():
    tree = ast.parse(_overlay_result()["bytes"].decode("utf-8"))
    spider_class = next(
        node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Spider"
    )
    methods = {
        node.name: node for node in spider_class.body if isinstance(node, ast.FunctionDef)
    }
    request = methods["_request_tmdb"]
    json_response = methods["_json_response"]

    def calls(node, name):
        return [
            call for call in ast.walk(node)
            if isinstance(call, ast.Call)
            and (
                isinstance(call.func, ast.Name) and call.func.id == name
                or isinstance(call.func, ast.Attribute) and call.func.attr == name
            )
        ]

    assert len(calls(request, "_tmdb_session")) == 0
    assert len(calls(request, "_v80_timeout_child_scope")) == 1
    assert len(calls(request, "request_timeout")) == 1
    assert len(calls(request, "_json_response")) == 1
    assert len(calls(request, "close_tracked")) == 1
    assert len(calls(request, "_read_bounded_json_shared")) == 0
    assert len(calls(json_response, "json")) == 1
    assert len(calls(json_response, "_read_bounded_json_shared")) == 1
    assert len(calls(json_response, "close_tracked")) == 0
    assert "_cache_" not in OVERLAY_PATH.read_text(encoding="utf-8")
    assert "Retry(" not in OVERLAY_PATH.read_text(encoding="utf-8")
    assert "TimeoutBudget" not in OVERLAY_PATH.read_text(encoding="utf-8")

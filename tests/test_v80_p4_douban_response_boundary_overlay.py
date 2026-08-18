import ast
import importlib.util
import json
import sys
import time
import types
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlencode

import pytest


ROOT = Path(__file__).resolve().parent.parent
BUILD_PATH = ROOT / "tools" / "build_follow_plugin.py"
OVERLAY_PATH = ROOT / "tools" / "build_v80_douban_response_boundary_overlay.py"
MANIFEST_PATH = ROOT / "src" / "douban_tmdb_follow_single" / "release.json"
FIXTURE_PATH = (
    ROOT / "tests" / "fixtures" / "v80_p4_douban_json_response_fixtures.json"
)


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BUILD = _load("v80_douban_response_boundary_build", BUILD_PATH)
OVERLAY = _load("v80_douban_response_boundary_overlay", OVERLAY_PATH)


@lru_cache(maxsize=1)
def _build():
    return BUILD.build_release(MANIFEST_PATH)


@lru_cache(maxsize=1)
def _input_source():
    built = _build()
    module = built["douban_response_policy_module"]
    return module["input_bytes"] + module["bytes"]


@lru_cache(maxsize=1)
def _overlay_result():
    return OVERLAY.apply_douban_response_boundary_overlay(_input_source())


@lru_cache(maxsize=1)
def _runtime():
    base_module = types.ModuleType("base")
    spider_module = types.ModuleType("base.spider")

    class BaseSpider(object):
        pass

    spider_module.Spider = BaseSpider
    sys.modules.setdefault("base", base_module)
    sys.modules.setdefault("base.spider", spider_module)
    module = types.ModuleType("v80_douban_response_boundary_runtime")
    exec(
        compile(
            _overlay_result()["bytes"],
            "v80-douban-response-boundary-runtime.py",
            "exec",
        ),
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
        self.calls.append(("GET", url, dict(kwargs)))
        return self.response

    def post(self, url, **kwargs):
        self.calls.append(("POST", url, dict(kwargs)))
        return self.response

    def close(self):
        return None


def _spider(response):
    spider = _runtime().Spider()
    spider._session = Session(response)
    return spider


def _body(payload):
    return json.dumps(
        payload, ensure_ascii=False, separators=(",", ":"),
    ).encode("utf-8")


def _json_body_with_exact_size(size):
    prefix = b'{"padding":"'
    suffix = b'"}'
    padding = size - len(prefix) - len(suffix)
    assert padding >= 0
    body = prefix + (b"a" * padding) + suffix
    assert len(body) == size
    json.loads(body)
    return body


def _nested_list(depth):
    value = None
    for _index in range(depth):
        value = [value]
    return value


def _action(spider, subject_id="305"):
    setattr(spider, "coo" + "kie", "present")
    setattr(spider, "c" + "k", "present")
    return json.loads(
        spider._v80_action_unbounded(spider.ACTION_PREFIX + subject_id)
    )


def _fixture_cases():
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    return {case["id"]: case["payload"] for case in fixture["cases"]}


def test_overlay_is_deterministic_and_has_two_narrow_insertions():
    first = _overlay_result()
    second = OVERLAY.apply_douban_response_boundary_overlay(_input_source())
    integrated = _build()["douban_response_boundary_overlay"]

    assert first == second
    assert first["insertions"] == (
        "douban-json-response-boundary",
        "douban-wish-response-boundary",
    )
    assert len(first["bytes"]) == integrated["size"]
    assert first["sha256"] == integrated["sha256"]


@pytest.mark.parametrize("index", (0, 1))
def test_overlay_rejects_missing_and_duplicate_anchors(index):
    _label, anchor, _replacement = OVERLAY.INSERTIONS[index]
    source = _input_source().decode("utf-8")

    with pytest.raises(
            OVERLAY.DoubanResponseBoundaryOverlayError, match="must appear once"):
        OVERLAY.apply_douban_response_boundary_overlay(
            source.replace(anchor, "", 1).encode("utf-8")
        )
    with pytest.raises(
            OVERLAY.DoubanResponseBoundaryOverlayError, match="must appear once"):
        OVERLAY.apply_douban_response_boundary_overlay(
            source.replace(anchor, anchor + anchor, 1).encode("utf-8")
        )


def test_overlay_rejects_invalid_utf8():
    with pytest.raises(
            OVERLAY.DoubanResponseBoundaryOverlayError, match="not valid UTF-8"):
        OVERLAY.apply_douban_response_boundary_overlay(b"\xff")


@pytest.mark.parametrize("case_id", tuple(_fixture_cases()))
def test_all_frozen_response_shapes_remain_byte_observable(case_id):
    payload = _fixture_cases()[case_id]
    response = StreamResponse(_body(payload))
    spider = _spider(response)
    try:
        assert spider._douban_client.request_json("https://example.invalid") == payload
        assert response.iter_calls == 1
        assert response.json_calls == 0
        assert response.close_calls == 1
    finally:
        spider.destroy()


def test_exact_response_byte_boundary_is_accepted_and_plus_one_is_rejected():
    limit = _runtime().V80_DOUBAN_RESPONSE_LIMITS["max_response_bytes"]
    accepted = StreamResponse(_json_body_with_exact_size(limit))
    accepted_spider = _spider(accepted)
    try:
        result = accepted_spider._douban_client.request_json("https://example.invalid")
        assert len(result["padding"]) == limit - len(b'{"padding":""}')
        assert accepted.iter_calls == 1
        assert accepted.json_calls == 0
        assert accepted.close_calls == 1
    finally:
        accepted_spider.destroy()

    rejected = StreamResponse(_json_body_with_exact_size(limit + 1))
    rejected_spider = _spider(rejected)
    try:
        with pytest.raises(RuntimeError, match="豆瓣 响应过大"):
            rejected_spider._douban_client.request_json("https://example.invalid")
        assert rejected.iter_calls == 0
        assert rejected.json_calls == 0
        assert rejected.close_calls == 1
    finally:
        rejected_spider.destroy()


def test_chunked_overflow_is_rejected_after_crossing_the_limit():
    limit = _runtime().V80_DOUBAN_RESPONSE_LIMITS["max_response_bytes"]
    response = StreamResponse(
        body=b"", content_length=False, chunks=(b"x" * limit, b"y"),
    )
    spider = _spider(response)
    try:
        with pytest.raises(RuntimeError, match="豆瓣 响应过大"):
            spider._douban_client.request_json("https://example.invalid")
        assert response.iter_calls == 1
        assert response.close_calls == 1
    finally:
        spider.destroy()


def test_successful_invalid_json_keeps_existing_message():
    response = StreamResponse(b"not-json")
    spider = _spider(response)
    try:
        with pytest.raises(RuntimeError, match="上游返回了非 JSON 内容"):
            spider._douban_client.request_json("https://example.invalid")
        assert response.close_calls == 1
    finally:
        spider.destroy()


@pytest.mark.parametrize("body", (b"not-json", b"x" * 32))
def test_non_200_unreadable_body_keeps_http_status_order(body):
    response = StreamResponse(body, status=500)
    if body.startswith(b"x"):
        response.headers["Content-Length"] = str(
            _runtime().V80_DOUBAN_RESPONSE_LIMITS["max_response_bytes"] + 1
        )
    spider = _spider(response)
    try:
        with pytest.raises(RuntimeError, match="HTTP 500"):
            spider._douban_client.request_json("https://example.invalid")
        assert response.close_calls == 1
    finally:
        spider.destroy()


def test_successful_shape_rejection_has_stable_reason_and_single_close():
    response = StreamResponse(_body(_nested_list(65)))
    spider = _spider(response)
    try:
        with pytest.raises(_runtime().V80JsonShapeError) as exc_info:
            spider._douban_client.request_json("https://example.invalid")
        assert exc_info.value.reason == "too_deep"
        assert response.close_calls == 1
    finally:
        spider.destroy()


def test_douban_json_cache_and_stale_refresh_contract_is_unchanged():
    payload = _fixture_cases()["subject_detail"]
    response = StreamResponse(_body(payload))
    spider = _spider(response)
    url = "https://example.invalid/subject/305"
    params = {"for_mobile": 1}
    key = "json:" + url + "?" + urlencode(sorted(params.items()), doseq=True)
    refreshes = []
    try:
        first = spider._get_json(url, params=params, ttl=10)
        second = spider._get_json(url, params=params, ttl=10)
        assert first == second == payload
        assert len(spider._session.calls) == 1
        assert response.close_calls == 1

        with spider._cache_lock:
            created, cached = spider._cache[key]
            spider._cache[key] = (created - 11, cached)
            spider._persistent_cache.pop(key, None)
        spider._schedule_cache_refresh = (
            lambda scheduled_key, loader: refreshes.append((scheduled_key, loader))
        )

        assert spider._get_json(url, params=params, ttl=10) == payload
        assert len(spider._session.calls) == 1
        assert [row[0] for row in refreshes] == [key]
    finally:
        spider.destroy()


def test_action_success_and_rejected_messages_are_preserved():
    cases = _fixture_cases()
    success_response = StreamResponse(_body(cases["action_success"]))
    success_spider = _spider(success_response)
    try:
        assert _action(success_spider) == {"msg": "已加入豆瓣想看"}
        assert success_response.close_calls == 1
        assert success_response.json_calls == 0
    finally:
        success_spider.destroy()

    rejected_response = StreamResponse(_body(cases["action_rejected"]))
    rejected_spider = _spider(rejected_response)
    try:
        assert _action(rejected_spider) == {"msg": "请求未被确认"}
        assert rejected_response.close_calls == 1
    finally:
        rejected_spider.destroy()


def test_action_auth_message_wins_before_shape_rejection():
    payload = dict(_fixture_cases()["action_auth_expired"])
    payload["data"] = _nested_list(65)
    response = StreamResponse(_body(payload), status=403)
    spider = _spider(response)
    try:
        result = _action(spider)
        assert result["msg"].startswith("豆瓣登录已失效")
        assert response.close_calls == 1
        assert response.json_calls == 0
    finally:
        spider.destroy()


def test_action_shape_and_byte_rejections_use_existing_failure_envelope():
    shape_response = StreamResponse(_body({"r": 1, "data": _nested_list(65)}))
    shape_spider = _spider(shape_response)
    try:
        assert "too_deep" in _action(shape_spider)["msg"]
        assert shape_response.close_calls == 1
    finally:
        shape_spider.destroy()

    limit = _runtime().V80_DOUBAN_RESPONSE_LIMITS["max_response_bytes"]
    large_response = StreamResponse(_json_body_with_exact_size(limit + 1))
    large_spider = _spider(large_response)
    try:
        assert "豆瓣 响应过大" in _action(large_spider)["msg"]
        assert large_response.close_calls == 1
    finally:
        large_spider.destroy()


def test_douban_json_and_action_disable_requests_automatic_redirects():
    request_response = StreamResponse(_body({"ok": True}))
    request_spider = _spider(request_response)
    try:
        assert request_spider._douban_client.request_json(
            "https://example.invalid"
        ) == {"ok": True}
        assert len(request_spider._session.calls) == 1
        assert request_spider._session.calls[0][0] == "GET"
        assert request_spider._session.calls[0][2]["allow_redirects"] is False
        assert request_response.close_calls == 1
    finally:
        request_spider.destroy()

    action_response = StreamResponse(_body({"r": 0}))
    action_spider = _spider(action_response)
    try:
        assert _action(action_spider) == {"msg": "已加入豆瓣想看"}
        assert len(action_spider._session.calls) == 1
        assert action_spider._session.calls[0][0] == "POST"
        assert action_spider._session.calls[0][2]["allow_redirects"] is False
        assert action_response.close_calls == 1
    finally:
        action_spider.destroy()


def test_overlay_keeps_single_transport_timeout_reader_and_close_owners():
    tree = ast.parse(_overlay_result()["bytes"].decode("utf-8"))
    classes = {
        node.name: node for node in tree.body if isinstance(node, ast.ClassDef)
    }
    douban_request = next(
        node for node in classes["_DoubanClient"].body
        if isinstance(node, ast.FunctionDef) and node.name == "request_json"
    )
    action = next(
        node for node in classes["Spider"].body
        if isinstance(node, ast.FunctionDef) and node.name == "_v80_action_unbounded"
    )

    def calls(node, name):
        return [
            call for call in ast.walk(node)
            if isinstance(call, ast.Call)
            and (
                isinstance(call.func, ast.Name) and call.func.id == name
                or isinstance(call.func, ast.Attribute) and call.func.attr == name
            )
        ]

    for method in (douban_request, action):
        assert len(calls(method, "_v80_timeout_child_scope")) == 1
        assert len(calls(method, "request_timeout")) == 1
        assert len(calls(method, "_json_response")) == 1
        assert len(calls(method, "v80_validate_json_shape")) == 1
        assert len(calls(method, "close_tracked")) == 1
        assert len(calls(method, "_read_bounded_json_shared")) == 0

    source = OVERLAY_PATH.read_text(encoding="utf-8")
    assert "Retry(" not in source
    assert "TimeoutBudget" not in source
    assert "def _cache" not in source
    assert "v80_cache_load" not in source

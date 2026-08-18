import ast
import gzip
import importlib.util
import io
import sys
import types
import zlib
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlencode

import pytest
import requests
import urllib3


ROOT = Path(__file__).resolve().parent.parent
BUILD_PATH = ROOT / "tools" / "build_follow_plugin.py"
OVERLAY_PATH = ROOT / "tools" / "build_v80_douban_html_response_boundary_overlay.py"
RELEASE_PATH = ROOT / "src" / "douban_tmdb_follow_single" / "release.json"
FIXTURE_ROOT = ROOT / "tests" / "fixtures"
P4_7_SIZE = 839214
P4_7_SHA256 = "6A62E667F23EB395BA7ACAC71F0A2AF11772D2E25DC703B35CFA731ED964579D"
P4_8_SIZE = 843188
P4_8_SHA256 = "70FFFECDD0166A8263E793502421EA06BA0AD0D1D19FB10F5ECE6CB6A3708740"
TEST_LIMIT = 4096
TEST_POLICY = (
    "\n# Test-only lower limit for exact boundary and overflow coverage.\n"
    "V80_DOUBAN_HTML_RESPONSE_LIMITS = {\"max_response_bytes\": %d}\n"
    % TEST_LIMIT
).encode("utf-8")


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BUILD = _load("v80_douban_html_boundary_build", BUILD_PATH)
OVERLAY = _load("v80_douban_html_boundary_overlay", OVERLAY_PATH)


@lru_cache(maxsize=1)
def _build():
    return BUILD.build_release(RELEASE_PATH)


@lru_cache(maxsize=1)
def _input_source():
    built = _build()
    policy = built["douban_html_response_policy_module"]
    return policy["input_bytes"] + TEST_POLICY


@lru_cache(maxsize=1)
def _overlay_result():
    return OVERLAY.apply_douban_html_response_boundary_overlay(_input_source())


@lru_cache(maxsize=1)
def _runtime():
    base_module = types.ModuleType("base")
    spider_module = types.ModuleType("base.spider")

    class BaseSpider(object):
        pass

    spider_module.Spider = BaseSpider
    sys.modules.setdefault("base", base_module)
    sys.modules.setdefault("base.spider", spider_module)
    module = types.ModuleType("v80_douban_html_boundary_runtime")
    exec(
        compile(
            _overlay_result()["bytes"],
            "v80-douban-html-boundary-runtime.py",
            "exec",
        ),
        module.__dict__,
    )
    return module


class StreamResponse(requests.Response):
    def __init__(
            self, body=b"", status=200, declared_length=None,
            content_type="text/html; charset=utf-8", chunks=None,
            on_iter=None, url="https://www.douban.com/mine/", location=None):
        super().__init__()
        self.status_code = status
        self.url = url
        self._content = bytes(body)
        self._content_consumed = True
        self.chunks = chunks
        self.on_iter = on_iter
        self.iter_calls = 0
        self.close_calls = 0
        if declared_length is not None:
            self.headers["Content-Length"] = str(declared_length)
        if content_type:
            self.headers["Content-Type"] = content_type
            self.encoding = requests.utils.get_encoding_from_headers(self.headers)
        if location is not None:
            self.headers["Location"] = location

    def iter_content(self, chunk_size=65536):
        self.iter_calls += 1
        if self.on_iter is not None:
            self.on_iter()
        if self.chunks is not None:
            for chunk in self.chunks:
                yield chunk
            return
        body = bytes(self._content)
        for offset in range(0, len(body), chunk_size):
            yield body[offset:offset + chunk_size]

    def close(self):
        self.close_calls += 1


class EncodedStreamResponse(requests.Response):
    def __init__(self, body, content_encoding):
        super().__init__()
        if content_encoding == "gzip":
            encoded = gzip.compress(body)
        elif content_encoding == "deflate":
            encoded = zlib.compress(body)
        else:
            raise AssertionError("unsupported test content encoding")
        headers = {
            "Content-Encoding": content_encoding,
            "Content-Length": str(len(encoded)),
            "Content-Type": "text/html; charset=utf-8",
        }
        self.status_code = 200
        self.headers.update(headers)
        self.encoding = requests.utils.get_encoding_from_headers(self.headers)
        self.raw = urllib3.response.HTTPResponse(
            body=io.BytesIO(encoded),
            headers=headers,
            preload_content=False,
            decode_content=False,
        )
        self._content = False
        self._content_consumed = False
        self.close_calls = 0

    def close(self):
        self.close_calls += 1
        return super().close()


class FailOnReadHeaders(dict):
    def get(self, *_args, **_kwargs):
        raise AssertionError("headers must not be inspected for a non-200 response")


class Session(object):
    def __init__(self, response):
        self.response = response
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, dict(kwargs)))
        return self.response

    def close(self):
        return None


class Clock(object):
    def __init__(self, value=100.0):
        self.value = float(value)

    def __call__(self):
        return self.value


def _spider(response):
    spider = _runtime().Spider()
    spider._session = Session(response)
    return spider


def _reference_text(body, content_type=""):
    response = requests.Response()
    response.status_code = 200
    response._content = bytes(body)
    response._content_consumed = True
    if content_type:
        response.headers["Content-Type"] = content_type
        response.encoding = requests.utils.get_encoding_from_headers(response.headers)
    return response.text


def _fixture(name):
    return (FIXTURE_ROOT / name).read_bytes()


def _method(tree, class_name, method_name):
    class_node = next(
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == class_name
    )
    return next(
        node for node in class_node.body
        if isinstance(node, ast.FunctionDef) and node.name == method_name
    )


def test_overlay_is_deterministic_and_integrated_after_the_p4_7_candidate():
    first = _overlay_result()
    second = OVERLAY.apply_douban_html_response_boundary_overlay(_input_source())
    built = _build()
    policy = built["douban_html_response_policy_module"]
    integrated = built["douban_html_response_boundary_overlay"]

    assert first == second
    assert first["insertions"] == (
        "douban-html-response-boundary",
        "douban-user-id-response-boundary",
    )
    assert first["input_size"] == P4_7_SIZE + len(TEST_POLICY)
    assert policy["input_size"] == P4_7_SIZE
    assert policy["input_sha256"] == P4_7_SHA256
    assert integrated["insertions"] == (
        "douban-html-response-boundary",
        "douban-user-id-response-boundary",
    )
    assert integrated["input_size"] == policy["output_size"]
    assert integrated["input_sha256"] == policy["output_sha256"]
    assert integrated["size"] == P4_8_SIZE
    assert integrated["sha256"] == P4_8_SHA256


def test_overlay_rejects_missing_duplicate_and_invalid_utf8_inputs():
    source = _input_source().decode("utf-8")
    for _label, anchor, _replacement in OVERLAY.INSERTIONS:
        with pytest.raises(
                OVERLAY.DoubanHtmlResponseBoundaryOverlayError,
                match="must appear once"):
            OVERLAY.apply_douban_html_response_boundary_overlay(
                source.replace(anchor, "", 1).encode("utf-8")
            )
        with pytest.raises(
                OVERLAY.DoubanHtmlResponseBoundaryOverlayError,
                match="must appear once"):
            OVERLAY.apply_douban_html_response_boundary_overlay(
                source.replace(anchor, anchor + anchor, 1).encode("utf-8")
            )
    with pytest.raises(
            OVERLAY.DoubanHtmlResponseBoundaryOverlayError,
            match="not valid UTF-8"):
        OVERLAY.apply_douban_html_response_boundary_overlay(b"\xff")


def test_exact_limit_succeeds_and_declared_plus_one_rejects_before_iteration():
    accepted = StreamResponse(b"a" * TEST_LIMIT, declared_length=TEST_LIMIT)
    spider = _spider(accepted)
    try:
        assert spider._douban_client.request_text("https://example.invalid") == (
            "a" * TEST_LIMIT
        )
        assert accepted.iter_calls == 1
        assert accepted.close_calls == 1
        assert spider._session.calls[0][1]["stream"] is True
    finally:
        spider.destroy()

    rejected = StreamResponse(b"a" * 600, declared_length=TEST_LIMIT + 1)
    spider = _spider(rejected)
    try:
        with pytest.raises(RuntimeError, match="豆瓣页面响应过大"):
            spider._douban_client.request_text("https://example.invalid")
        assert rejected.iter_calls == 0
        assert rejected.close_calls == 1
    finally:
        spider.destroy()


@pytest.mark.parametrize("declared_length", (None, "malformed"))
def test_missing_or_malformed_length_is_still_bounded_by_streamed_bytes(
        declared_length):
    response = StreamResponse(
        b"", declared_length=declared_length,
        chunks=(b"a" * TEST_LIMIT, b"b"),
    )
    spider = _spider(response)
    try:
        with pytest.raises(RuntimeError, match="豆瓣页面响应过大"):
            spider._douban_client.request_text("https://example.invalid")
        assert response.iter_calls == 1
        assert response.close_calls == 1
    finally:
        spider.destroy()


def test_underreported_valid_length_cannot_bypass_the_streamed_byte_limit():
    response = StreamResponse(
        b"", declared_length=1,
        chunks=(b"a" * TEST_LIMIT, b"b"),
    )
    spider = _spider(response)
    try:
        with pytest.raises(RuntimeError, match="豆瓣页面响应过大"):
            spider._douban_client.request_text("https://example.invalid")
        assert response.iter_calls == 1
        assert response.close_calls == 1
    finally:
        spider.destroy()


def test_non_200_status_wins_before_headers_iteration_decode_and_short_page():
    response = StreamResponse(b"x", status=503, content_type="")
    response.headers = FailOnReadHeaders()
    spider = _spider(response)
    try:
        with pytest.raises(RuntimeError, match="HTTP 503"):
            spider._douban_client.request_text("https://example.invalid")
        assert response.iter_calls == 0
        assert response.close_calls == 1
    finally:
        spider.destroy()


@pytest.mark.parametrize("body,content_type", (
    (_fixture("v80_p4_douban_wishlist.html"), "text/html; charset=utf-8"),
    (_fixture("v80_p4_douban_wishlist.html"), "text/html"),
    (_fixture("v80_p4_douban_wishlist.html"), ""),
    ((b"valid-prefix-\xff-valid-suffix" + b"x" * 600), "text/html; charset=utf-8"),
))
def test_streaming_preserves_requests_text_decoding(body, content_type):
    response = StreamResponse(
        body, declared_length=len(body), content_type=content_type,
    )
    spider = _spider(response)
    try:
        assert spider._douban_client.request_text("https://example.invalid") == (
            _reference_text(body, content_type)
        )
        assert response.iter_calls == 1
        assert response.close_calls == 1
    finally:
        spider.destroy()


@pytest.mark.parametrize("content_encoding", ("gzip", "deflate"))
def test_real_requests_stream_counts_decompressed_bytes(content_encoding):
    exact_body = b"a" * TEST_LIMIT
    exact = EncodedStreamResponse(exact_body, content_encoding)
    spider = _spider(exact)
    try:
        assert spider._douban_client.request_text("https://example.invalid") == (
            _reference_text(exact_body, "text/html; charset=utf-8")
        )
        assert exact.close_calls == 1
    finally:
        spider.destroy()

    overflow = EncodedStreamResponse(b"a" * (TEST_LIMIT + 1), content_encoding)
    spider = _spider(overflow)
    try:
        with pytest.raises(RuntimeError, match="豆瓣页面响应过大"):
            spider._douban_client.request_text("https://example.invalid")
        assert overflow.close_calls == 1
    finally:
        spider.destroy()


def test_short_page_boundary_remains_character_based_after_decode():
    short_body = ("界" * 499).encode("utf-8")
    short = StreamResponse(short_body, declared_length=len(short_body))
    spider = _spider(short)
    try:
        with pytest.raises(RuntimeError, match="页面内容异常短"):
            spider._douban_client.request_text("https://example.invalid")
        assert short.iter_calls == 1
        assert short.close_calls == 1
    finally:
        spider.destroy()

    exact_body = ("界" * 500).encode("utf-8")
    exact = StreamResponse(exact_body, declared_length=len(exact_body))
    spider = _spider(exact)
    try:
        assert spider._douban_client.request_text("https://example.invalid") == (
            "界" * 500
        )
        assert exact.close_calls == 1
    finally:
        spider.destroy()


def test_byte_overflow_wins_before_short_page_validation():
    response = StreamResponse(
        b"", declared_length=None, chunks=(b"\xff" * (TEST_LIMIT + 1),),
    )
    spider = _spider(response)
    try:
        with pytest.raises(RuntimeError, match="豆瓣页面响应过大"):
            spider._douban_client.request_text("https://example.invalid")
        assert response.close_calls == 1
    finally:
        spider.destroy()


def test_deadline_expiry_during_streaming_closes_once(monkeypatch):
    module = _runtime()
    clock = Clock()
    response = StreamResponse(
        b"a" * 600,
        declared_length=600,
        on_iter=lambda: setattr(clock, "value", 102.0),
    )
    spider = _spider(response)
    spider.timeout = 1.0
    spider._timeout_budget_controller = module.TimeoutBudgetController(
        generation=spider._cache_generation,
        clock=clock,
    )
    monkeypatch.setattr(module.time, "monotonic", clock)
    try:
        with pytest.raises(RuntimeError, match="豆瓣页面响应超过总时限"):
            spider._douban_client.request_text("https://example.invalid")
        assert response.iter_calls == 1
        assert response.close_calls == 1
    finally:
        spider.destroy()


def test_html_request_disables_requests_automatic_redirects():
    body = _fixture("v80_p4_douban_top250.html")
    response = StreamResponse(body, declared_length=len(body))
    spider = _spider(response)
    try:
        assert spider._douban_client.request_text(
            "https://example.invalid"
        ) == body.decode("utf-8")
        assert len(spider._session.calls) == 1
        assert spider._session.calls[0][1]["allow_redirects"] is False
        assert response.close_calls == 1
    finally:
        spider.destroy()


def test_user_id_same_origin_location_is_parsed_without_following_or_reading():
    response = StreamResponse(
        b"must-not-be-read",
        status=302,
        location="/people/evidence-user/",
    )
    spider = _spider(response)
    spider.cookie = "test-cookie"
    try:
        assert spider._resolve_user_id() == "evidence-user"
        assert len(spider._session.calls) == 1
        assert spider._session.calls[0][1]["allow_redirects"] is False
        assert response.iter_calls == 0
        assert response.close_calls == 1
    finally:
        spider.destroy()


def test_user_id_cross_origin_location_is_ignored_without_following_or_reading():
    response = StreamResponse(
        b"must-not-be-read",
        status=302,
        location="http://127.0.0.1/internal/people/not-allowed/",
    )
    spider = _spider(response)
    spider.cookie = "test-cookie"
    try:
        assert spider._resolve_user_id() == ""
        assert len(spider._session.calls) == 1
        assert spider._session.calls[0][1]["allow_redirects"] is False
        assert response.iter_calls == 0
        assert response.close_calls == 1
    finally:
        spider.destroy()


def test_user_id_200_body_is_bounded_by_html_limit_and_deadline(monkeypatch):
    module = _runtime()
    accepted_body = (
        b"x" * 600
        + b" https://www.douban.com/people/body-user/"
    )
    accepted = StreamResponse(
        accepted_body,
        status=200,
        declared_length=len(accepted_body),
    )
    spider = _spider(accepted)
    spider.cookie = "test-cookie"
    try:
        assert spider._resolve_user_id() == "body-user"
        assert accepted.iter_calls == 1
        assert accepted.close_calls == 1
    finally:
        spider.destroy()

    oversized = StreamResponse(
        b"https://www.douban.com/people/oversized/",
        status=200,
        declared_length=TEST_LIMIT + 1,
    )
    spider = _spider(oversized)
    spider.cookie = "test-cookie"
    try:
        assert spider._resolve_user_id() == ""
        assert oversized.iter_calls == 0
        assert oversized.close_calls == 1
    finally:
        spider.destroy()

    clock = Clock()
    expired = StreamResponse(
        accepted_body,
        status=200,
        declared_length=len(accepted_body),
        on_iter=lambda: setattr(clock, "value", 102.0),
    )
    spider = _spider(expired)
    spider.cookie = "test-cookie"
    spider.timeout = 1.0
    spider._timeout_budget_controller = module.TimeoutBudgetController(
        generation=spider._cache_generation,
        clock=clock,
    )
    monkeypatch.setattr(module.time, "monotonic", clock)
    try:
        assert spider._resolve_user_id() == ""
        assert expired.iter_calls == 1
        assert expired.close_calls == 1
    finally:
        spider.destroy()


def test_text_cache_and_stale_refresh_contract_is_unchanged():
    body = _fixture("v80_p4_douban_top250.html")
    response = StreamResponse(body, declared_length=len(body))
    spider = _spider(response)
    url = "https://example.invalid/top250"
    params = {"start": 0}
    key = "text:" + url + "?" + urlencode(sorted(params.items()), doseq=True)
    refreshes = []
    try:
        first = spider._get_text(url, params=params, ttl=10)
        second = spider._get_text(url, params=params, ttl=10)
        assert first == second == body.decode("utf-8")
        assert len(spider._session.calls) == 1
        assert response.close_calls == 1

        with spider._cache_lock:
            created, cached = spider._cache[key]
            spider._cache[key] = (created - 11, cached)
            spider._persistent_cache.pop(key, None)
        spider._schedule_cache_refresh = (
            lambda scheduled_key, loader: refreshes.append((scheduled_key, loader))
        )

        assert spider._get_text(url, params=params, ttl=10) == first
        assert len(spider._session.calls) == 1
        assert [row[0] for row in refreshes] == [key]
    finally:
        spider.destroy()


def test_overlay_changes_only_request_text_and_user_id_owners():
    before = ast.parse(_input_source().decode("utf-8"))
    after = ast.parse(_overlay_result()["bytes"].decode("utf-8"))

    assert ast.dump(
        _method(before, "_DoubanClient", "request_text"),
        include_attributes=False,
    ) != ast.dump(
        _method(after, "_DoubanClient", "request_text"),
        include_attributes=False,
    )
    assert ast.dump(
        _method(before, "Spider", "_resolve_user_id"),
        include_attributes=False,
    ) != ast.dump(
        _method(after, "Spider", "_resolve_user_id"),
        include_attributes=False,
    )
    for class_name, method_name in (
        ("_DoubanClient", "request_json"),
        ("Spider", "_get_text"),
        ("Spider", "_category_top250"),
        ("Spider", "_category_wishlist"),
        ("Spider", "_reset_session"),
    ):
        assert ast.dump(
            _method(before, class_name, method_name), include_attributes=False,
        ) == ast.dump(
            _method(after, class_name, method_name), include_attributes=False,
        )

    request_text = _method(after, "_DoubanClient", "request_text")
    call_names = [
        node.func.attr
        for node in ast.walk(request_text)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    ]
    session_gets = [
        node for node in ast.walk(request_text)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "get"
        and isinstance(node.func.value, ast.Attribute)
        and node.func.value.attr == "_session"
    ]
    assert len(session_gets) == 1
    assert call_names.count("iter_content") == 1
    assert call_names.count("close_tracked") == 1
    assert "close" not in call_names
    assert "decode" not in call_names
    assert "_read_bounded_json_shared" not in call_names

    resolve_user_id = _method(after, "Spider", "_resolve_user_id")
    resolve_calls = [
        node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id
        for node in ast.walk(resolve_user_id)
        if isinstance(node, ast.Call)
        and isinstance(node.func, (ast.Attribute, ast.Name))
    ]
    assert resolve_calls.count("iter_content") == 1
    assert resolve_calls.count("close_tracked") == 1
    assert resolve_calls.count("urljoin") == 1
    assert resolve_calls.count("urlparse") == 1

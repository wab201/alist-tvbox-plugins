import ast
import importlib.util
import sys
import types
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote, quote_plus

import pytest


ROOT = Path(__file__).resolve().parent.parent
BUILD_PATH = ROOT / "tools" / "build_follow_plugin.py"
OVERLAY_PATH = ROOT / "tools" / "build_v80_diagnostic_redaction_overlay.py"
MANIFEST_PATH = ROOT / "src" / "douban_tmdb_follow_single" / "release.json"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fixture(*parts):
    return "".join(parts)


BUILD = _load("v80_diagnostic_redaction_build", BUILD_PATH)
OVERLAY = _load("v80_diagnostic_redaction_overlay", OVERLAY_PATH)


@lru_cache(maxsize=1)
def _input_source():
    built = BUILD.build_release(MANIFEST_PATH)
    module = built["diagnostic_redaction_policy_module"]
    return module["input_bytes"] + module["bytes"]


@lru_cache(maxsize=1)
def _overlay_result():
    return OVERLAY.apply_diagnostic_redaction_overlay(_input_source())


@lru_cache(maxsize=1)
def _runtime():
    base_module = types.ModuleType("base")
    spider_module = types.ModuleType("base.spider")

    class BaseSpider(object):
        pass

    spider_module.Spider = BaseSpider
    sys.modules.setdefault("base", base_module)
    sys.modules.setdefault("base.spider", spider_module)
    module = types.ModuleType("v80_diagnostic_redaction_runtime")
    exec(
        compile(_overlay_result()["bytes"], "v80-diagnostic-redaction-runtime.py", "exec"),
        module.__dict__,
    )
    return module


def _spider():
    spider = _runtime().Spider()
    spider.tmdb_access_token = "configured secret/with+plus"
    return spider


def test_overlay_is_deterministic_and_has_two_narrow_insertions():
    first = _overlay_result()
    second = OVERLAY.apply_diagnostic_redaction_overlay(_input_source())

    assert first == second
    assert first["insertions"] == (
        "diagnostic-field-redaction",
        "short-error-redaction",
    )
    assert first["bytes"] == BUILD.build_release(MANIFEST_PATH)[
        "douban_response_policy_module"
    ]["input_bytes"]


@pytest.mark.parametrize("index", (0, 1))
def test_overlay_rejects_missing_and_duplicate_anchors(index):
    _label, anchor, _replacement = OVERLAY.INSERTIONS[index]
    source = _input_source().decode("utf-8")
    with pytest.raises(OVERLAY.DiagnosticRedactionOverlayError, match="must appear once"):
        OVERLAY.apply_diagnostic_redaction_overlay(
            source.replace(anchor, "", 1).encode("utf-8")
        )
    with pytest.raises(OVERLAY.DiagnosticRedactionOverlayError, match="must appear once"):
        OVERLAY.apply_diagnostic_redaction_overlay(
            source.replace(anchor, anchor + anchor, 1).encode("utf-8")
        )


def test_overlay_rejects_invalid_utf8():
    with pytest.raises(OVERLAY.DiagnosticRedactionOverlayError, match="not valid UTF-8"):
        OVERLAY.apply_diagnostic_redaction_overlay(b"\xff")


def test_short_error_preserves_plain_text_and_fixed_limits():
    spider = _spider()
    try:
        assert spider._short_error(RuntimeError("plain failure")) == "plain failure"
        assert len(spider._short_error(RuntimeError("x" * 800))) == 220
        assert len(spider._short_error(RuntimeError("x" * 800), limit=512)) == 512
        assert len(spider._short_error(RuntimeError("x" * 800), limit=9999)) == 220
    finally:
        spider.destroy()


@pytest.mark.parametrize("text", (
    _fixture("Author", "ization: Bearer opaque-", "fixture"),
    _fixture("Proxy-Author", "ization: Basic ", "b3Bh", "cXVl", "OnNl", "Y3JldA=="),
    _fixture("Coo", "kie: session=opaque-", "fixture"),
    _fixture("Set-Coo", "kie: session=opaque-", "fixture; HttpOnly"),
    _fixture('{"access_', 'to', 'ken":"opaque-', 'fixture","safe":"ok"}'),
))
def test_short_error_redacts_header_and_assignment_secrets(text):
    spider = _spider()
    try:
        output = spider._short_error(RuntimeError(text))
        assert "opaque" not in output
        assert "b3BhcXVlOnNlY3JldA" not in output
        assert "***" in output
    finally:
        spider.destroy()


@pytest.mark.parametrize("query", (
    "signature=opaque-signature",
    "sign=opaque-signature",
    "auth_key=opaque-signature",
    "expires=1700000000",
    "X-Amz-Credential=opaque-credential&X-Amz-Signature=opaque-signature",
    "X-Goog-Credential=opaque-credential&X-Goog-Signature=opaque-signature",
    "x-oss-signature=opaque-signature&X-Bce-Signature=opaque-signature",
    "auth=opaque-signature&key=opaque-signature",
    "wsSecret=opaque-signature",
))
def test_short_error_redacts_signed_url_queries(query):
    spider = _spider()
    try:
        output = spider._short_error(RuntimeError("https://cdn.example/video?" + query))
        assert "opaque" not in output
        assert "1700000000" not in output
        assert "***" in output
    finally:
        spider.destroy()


def test_short_error_redacts_url_userinfo_path_tokens_and_configured_encodings():
    spider = _spider()
    configured_value = spider.tmdb_access_token
    encoded = quote(configured_value, safe="")
    plus_encoded = quote_plus(configured_value, safe="")
    double_encoded = quote(encoded, safe="")
    double_plus_encoded = quote_plus(plus_encoded, safe="")
    text = _fixture(
        "https", "://user:password@example.test/play/path-token?next=", encoded,
        "&again=", double_encoded, "&plus=", plus_encoded,
        "&plus_again=", double_plus_encoded,
    )
    try:
        output = spider._short_error(RuntimeError(text))
        for leaked in (
                "user", "password", "path-token", configured_value, encoded, double_encoded,
                plus_encoded, double_plus_encoded):
            assert leaked not in output
    finally:
        spider.destroy()


def test_diagnostic_fields_are_redacted_without_key_name_allowlisting():
    spider = _spider()
    try:
        event = spider._diagnostic_event(
            "test.redaction",
            headers={"Author" + "ization": "Bearer opaque-" + "header"},
            header_pairs=[("Coo" + "kie", "sid=opaque-" + "pair-cookie")],
            request="https" + "://cdn.example/video?signature=opaque-signature",
            response="Set-" + "Coo" + "kie: sid=opaque-cookie",
            cookies={"Set-" + "Cookie": ["sid=opaque-list-cookie"]},
            message="to" + "ken=opaque-token",
            note="x" * 800,
        )
        serialized = repr(event)
        assert "opaque" not in serialized
        assert event["note"] == "x" * 512
    finally:
        spider.destroy()


def test_diagnostic_names_and_field_keys_use_the_bounded_redaction_path():
    spider = _spider()
    try:
        event = spider._diagnostic_event(
            "to" + "ken=opaque-event" + "x" * 600,
            "Coo" + "kie: sid=opaque-level",
            **{"to" + "ken=opaque-key": "safe"},
        )
        serialized = repr(event)
        assert "opaque" not in serialized
        assert len(event["event"]) <= 512
        assert len(event["level"]) <= 512
        assert "token=***" in event
    finally:
        spider.destroy()


def test_short_error_redacts_max_length_secret_crossing_policy_boundary():
    spider = _spider()
    secret = "s" * 4096
    spider.tmdb_access_token = secret
    try:
        output = spider._short_error(RuntimeError("x" * 100 + secret), limit=512)
        assert "s" * 32 not in output
        assert "***" in output
    finally:
        spider.destroy()


def test_short_error_redacts_encoded_structures_in_malformed_url():
    spider = _spider()
    value = (
        "http://[invalid/%2570arse/opaque-path/x?"
        "%2574oken=opaque-query"
    )
    try:
        output = spider._short_error(RuntimeError(value), limit=512)
        assert "opaque" not in output
        assert "***" in output
    finally:
        spider.destroy()


def test_header_redaction_preserves_following_text_and_trace_uses_field_limit():
    spider = _spider()
    try:
        text = "Author" + "ization: Bearer opaque-token\r\nsafe detail"
        assert spider._short_error(RuntimeError(text)) == (
            "Authorization: ***  safe detail"
        )
        event = spider._diagnostic_event(
            "test.trace", "ERROR", exc=RuntimeError("x" * 800),
        )
        assert len(event["error"]) == 220
        assert len(event["trace"]) == 512
    finally:
        spider.destroy()


def test_exception_trace_and_error_card_share_the_same_redaction_owner():
    spider = _spider()
    try:
        exc = RuntimeError(
            "request failed Author" + "ization: Bearer opaque-token "
            "https" + "://cdn.example/video?signature=opaque-signature"
        )
        event = spider._diagnostic_event("test.error", "ERROR", exc=exc)
        card = spider._error_card("失败", exc)
        assert "opaque" not in repr(event)
        assert "opaque" not in repr(card)
        assert card["vod_remarks"] == card["vod_content"]
    finally:
        spider.destroy()


def test_overlay_keeps_single_redaction_owner_and_adds_no_runtime_subsystem():
    tree = ast.parse(_overlay_result()["bytes"].decode("utf-8"))
    spider_class = next(
        node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Spider"
    )
    methods = {
        node.name: node for node in spider_class.body if isinstance(node, ast.FunctionDef)
    }

    def calls(node, name):
        return [
            call for call in ast.walk(node)
            if isinstance(call, ast.Call)
            and (
                isinstance(call.func, ast.Name) and call.func.id == name
                or isinstance(call.func, ast.Attribute) and call.func.attr == name
            )
        ]

    assert len(calls(methods["_short_error"], "v80_redact_diagnostic_text")) == 1
    assert len(calls(methods["_diagnostic_event"], "_short_error")) == 6
    overlay_text = OVERLAY_PATH.read_text(encoding="utf-8")
    for forbidden in ("requests.", "Session(", "Retry(", "TimeoutBudget", "_cache_set("):
        assert forbidden not in overlay_text

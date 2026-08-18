import importlib.util
import sys
import time
import types
from functools import lru_cache
from pathlib import Path
from unittest.mock import Mock

import pytest


ROOT = Path(__file__).resolve().parent.parent
BUILD_PATH = ROOT / "tools" / "build_follow_plugin.py"
OVERLAY_PATH = ROOT / "tools" / "build_v80_route_security_overlay.py"
MANIFEST_PATH = ROOT / "src" / "douban_tmdb_follow_single" / "release.json"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BUILD = _load("v80_route_security_build", BUILD_PATH)
OVERLAY = _load("v80_route_security_overlay", OVERLAY_PATH)


@lru_cache(maxsize=1)
def _input_source():
    built = BUILD.build_release(MANIFEST_PATH)
    security = built["security_policy_module"]
    return security["input_bytes"] + security["bytes"]


@lru_cache(maxsize=1)
def _overlay_result():
    return OVERLAY.apply_route_security_overlay(_input_source())


@lru_cache(maxsize=1)
def _runtime():
    base_module = types.ModuleType("base")
    spider_module = types.ModuleType("base.spider")

    class BaseSpider(object):
        pass

    spider_module.Spider = BaseSpider
    sys.modules.setdefault("base", base_module)
    sys.modules.setdefault("base.spider", spider_module)
    module = types.ModuleType("v80_route_security_runtime")
    source = _overlay_result()["bytes"]
    exec(compile(source, "v80-route-security-runtime.py", "exec"), module.__dict__)
    return module


def _spider(atvp_api=""):
    spider = _runtime().Spider()
    spider.atvp_api = atvp_api
    spider.history_api = ""
    spider._history_api_origins = []
    spider.user_agent = "route-security-test"
    return spider


def test_overlay_is_deterministic_and_has_four_narrow_insertions():
    first = _overlay_result()
    second = OVERLAY.apply_route_security_overlay(_input_source())

    assert first["bytes"] == second["bytes"]
    assert first["insertions"] == (
        "target-policy", "probe-headers", "redirect-decision", "redirect-transition",
    )
    assert first["input_size"] == 822566
    assert first["input_sha256"] == (
        "A1C922715DDA59168D9EB12D0D820A345341840BA9DCF0856F7238CF1C8B8F76"
    )


@pytest.mark.parametrize("index", range(4))
def test_overlay_rejects_missing_anchors(index):
    source = _input_source().decode("utf-8")
    label, anchor, _replacement = OVERLAY.INSERTIONS[index]
    source = source.replace(anchor, "", 1)

    with pytest.raises(OVERLAY.RouteSecurityOverlayError, match="anchor %s" % label):
        OVERLAY.apply_route_security_overlay(source.encode("utf-8"))


def test_exact_configured_private_backend_is_allowed_without_global_ip_requirement():
    module = _runtime()
    spider = _spider("http://10.10.100.4:4568")
    spider._resolve_addresses = Mock(return_value={module.ipaddress.ip_address("10.10.100.4")})

    resolved = spider._resolved_media_target(
        "http://10.10.100.4:4568/media/video.mp4",
        deadline=time.monotonic() + 5,
    )

    assert resolved is not None
    assert resolved[0].hostname == "10.10.100.4"
    assert resolved[0].port == 4568


def test_unconfigured_private_media_target_is_rejected():
    module = _runtime()
    spider = _spider("https://backend.example")
    spider._resolve_addresses = Mock(return_value={module.ipaddress.ip_address("10.0.0.8")})

    assert spider._resolved_media_target(
        "http://10.0.0.8/video.mp4",
        deadline=time.monotonic() + 5,
    ) is None


def test_external_redirect_to_trusted_internal_backend_is_rejected_before_second_request():
    module = _runtime()
    spider = _spider("http://10.10.100.4:4568")
    cookie_value = "route-" + "header-value"
    resolved = {
        "https://cdn.example/video.mp4": (
            module.urlparse("https://cdn.example/video.mp4"), ("8.8.8.8",),
        ),
        "http://10.10.100.4:4568/video.mp4": (
            module.urlparse("http://10.10.100.4:4568/video.mp4"), ("10.10.100.4",),
        ),
    }
    spider._resolved_media_target = Mock(
        side_effect=lambda value, deadline=None: resolved[value]
    )
    spider._pinned_media_request = Mock(return_value={
        "status": 302,
        "headers": {"Location": "http://10.10.100.4:4568/video.mp4"},
        "body": b"",
    })

    result = spider._v80_probe_media_output_unbounded({
        "url": "https://cdn.example/video.mp4",
        "header": {"Cookie": cookie_value},
    }, deadline=time.monotonic() + 5)

    assert result is None
    assert spider._pinned_media_request.call_count == 1


def test_external_https_downgrade_is_rejected_before_second_request():
    module = _runtime()
    spider = _spider()
    resolved = {
        "https://cdn.example/video.mp4": (
            module.urlparse("https://cdn.example/video.mp4"), ("8.8.8.8",),
        ),
        "http://edge.example/video.mp4": (
            module.urlparse("http://edge.example/video.mp4"), ("1.1.1.1",),
        ),
    }
    spider._resolved_media_target = Mock(
        side_effect=lambda value, deadline=None: resolved[value]
    )
    spider._pinned_media_request = Mock(return_value={
        "status": 302,
        "headers": {"Location": "http://edge.example/video.mp4"},
        "body": b"",
    })

    result = spider._v80_probe_media_output_unbounded({
        "url": "https://cdn.example/video.mp4",
    }, deadline=time.monotonic() + 5)

    assert result is None
    assert spider._pinned_media_request.call_count == 1


def test_allowed_cross_origin_redirect_uses_fixed_header_allowlist():
    module = _runtime()
    spider = _spider()
    cookie_value = "route-" + "header-value"
    requests = []
    resolved = {
        "https://cdn.example/video.mp4": (
            module.urlparse("https://cdn.example/video.mp4"), ("8.8.8.8",),
        ),
        "https://edge.example/video.mp4": (
            module.urlparse("https://edge.example/video.mp4"), ("1.1.1.1",),
        ),
    }
    spider._resolved_media_target = Mock(
        side_effect=lambda value, deadline=None: resolved[value]
    )

    def request(parsed, _address, headers, _deadline):
        requests.append((parsed.hostname, dict(headers)))
        if parsed.hostname == "cdn.example":
            return {
                "status": 302,
                "headers": {"Location": "https://edge.example/video.mp4"},
                "body": b"",
            }
        return {
            "status": 206,
            "headers": {
                "Content-Type": "video/mp4",
                "Content-Range": "bytes 0-3/1024",
            },
            "body": b"test",
        }

    spider._pinned_media_request = Mock(side_effect=request)
    result = spider._v80_probe_media_output_unbounded({
        "url": "https://cdn.example/video.mp4",
        "header": {
            "Cookie": cookie_value,
            "Origin": "https://pan.example",
            "Referer": "https://pan.example/",
            "User-Agent": "test-agent",
        },
    }, deadline=time.monotonic() + 5)

    assert result["reachable"] is True
    assert requests[0][1]["Cookie"] == cookie_value
    assert requests[1][1] == {
        "Accept": "*/*",
        "Range": "bytes=0-4095",
        "User-Agent": "test-agent",
    }
    assert result["output"]["header"] == {"User-Agent": "test-agent"}

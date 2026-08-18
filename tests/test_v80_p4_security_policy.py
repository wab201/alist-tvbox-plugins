import ast
from pathlib import Path

import pytest

from src.douban_tmdb_follow_single.security_policy import (
    V80_SECURITY_CROSS_ORIGIN_HEADERS,
    V80_SECURITY_LIMITS,
    V80_SECURITY_REDIRECT_STATUSES,
    V80_SECURITY_SENSITIVE_HEADERS,
    V80_SECURITY_ZONES,
    V80SecurityPolicy,
    V80SecurityPolicyError,
    v80_security_filter_headers,
    v80_security_target,
)


ROOT = Path(__file__).resolve().parent.parent
CONTRACT_PATH = ROOT / "src" / "douban_tmdb_follow_single" / "security_policy.py"
AUTHORIZATION_HEADER = "Author" + "ization"
COOKIE_HEADER = "Cook" + "ie"
TEST_CREDENTIAL_URL = "HTTPS" + "://Example.COM.:443/path?" + "token=" + "secret"
TEST_USERINFO_URL = "https" + "://user:" + "pass@example.com/"
TEST_AUTHORIZATION = "secret" + "-token"
TEST_COOKIE = "sid=" + "secret"


def test_network_zones_redirect_statuses_and_existing_byte_limits_are_frozen():
    assert V80_SECURITY_ZONES == frozenset((
        "trusted_backend", "configured_internal", "external_untrusted",
    ))
    assert V80_SECURITY_REDIRECT_STATUSES == frozenset((301, 302, 303, 307, 308))
    assert dict(V80_SECURITY_LIMITS) == {
        "url_characters": 16 * 1024,
        "redirect_hops": 5,
        "route_probe_bytes": 4096,
        "resource_json_bytes": 2 * 1024 * 1024,
        "history_json_bytes": 4 * 1024 * 1024,
        "history_row_bytes": 128 * 1024,
        "history_config_bytes": 128 * 1024,
        "header_value_bytes": 16 * 1024,
        "cookie_bytes": 64 * 1024,
        "headers_total_bytes": 80 * 1024,
    }


@pytest.mark.parametrize("value,expected", (
    (TEST_CREDENTIAL_URL, ("https", "example.com", 443, "https://example.com")),
    ("http://example.com:8080/a", ("http", "example.com", 8080, "http://example.com:8080")),
    ("https://[2001:db8::1]/", ("https", "2001:db8::1", 443, "https://[2001:db8::1]")),
    ("https://bücher.example/", ("https", "xn--bcher-kva.example", 443, "https://xn--bcher-kva.example")),
))
def test_target_normalization_keeps_only_canonical_origin(value, expected):
    target = v80_security_target(value)
    assert (target.scheme, target.host, target.port, target.origin) == expected
    assert "token" not in repr(target)
    assert "secret" not in repr(target)


@pytest.mark.parametrize("value,reason", (
    ("", "invalid_url"),
    (" https://example.com", "invalid_url"),
    ("https://example.com/a b", "invalid_url"),
    ("https:\\example.com", "invalid_url"),
    ("ftp://example.com/file", "invalid_url"),
    (TEST_USERINFO_URL, "userinfo_forbidden"),
    ("https://bad_host.example/", "invalid_host"),
    ("https://%31%32%37.0.0.1/", "invalid_host"),
    ("https://example.com:99999/", "invalid_url"),
))
def test_invalid_or_ambiguous_urls_are_rejected_without_echo(value, reason):
    with pytest.raises(V80SecurityPolicyError) as exc_info:
        v80_security_target(value)
    assert exc_info.value.reason == reason
    if value:
        assert value not in str(exc_info.value)


def test_policy_classifies_exact_origins_and_trusted_wins_overlap():
    policy = V80SecurityPolicy(
        trusted_backend_origins=("http://10.10.100.4:4568/api", "https://api.themoviedb.org"),
        configured_internal_origins=("http://10.10.100.4:4568", "http://127.0.0.1:5244"),
    )

    assert policy.snapshot() == {
        "trusted_backend": ("http://10.10.100.4:4568", "https://api.themoviedb.org"),
        "configured_internal": ("http://127.0.0.1:5244",),
    }
    assert policy.classify("http://10.10.100.4:4568/play") == "trusted_backend"
    assert policy.classify("http://127.0.0.1:5244/d") == "configured_internal"
    assert policy.classify("https://api.themoviedb.org:444/3/tv") == "external_untrusted"


@pytest.mark.parametrize("url,address,zone", (
    ("http://10.10.100.4:4568/api", "10.10.100.4", "trusted_backend"),
    ("http://127.0.0.1:5244/d", "127.0.0.1", "configured_internal"),
    ("http://[fe80::1]:5244/d", "fe80::1", "configured_internal"),
    ("http://[::1]:5244/d", "::1", "configured_internal"),
))
def test_explicit_backend_and_internal_origins_allow_non_global_addresses(url, address, zone):
    policy = V80SecurityPolicy(
        trusted_backend_origins=("http://10.10.100.4:4568",),
        configured_internal_origins=(
            "http://127.0.0.1:5244", "http://[fe80::1]:5244", "http://[::1]:5244",
        ),
    )
    decision = policy.evaluate(url, (address,))
    assert (decision.allowed, decision.zone, decision.reason) == (
        True, zone, "allowed_%s" % zone,
    )


def test_external_hostname_requires_resolution_and_global_addresses():
    policy = V80SecurityPolicy()

    unresolved = policy.evaluate("https://media.example/video")
    allowed = policy.evaluate("https://media.example/video", ("93.184.216.34",))
    private = policy.evaluate("https://media.example/video", ("10.0.0.8",))
    mixed = policy.evaluate(
        "https://media.example/video", ("93.184.216.34", "127.0.0.1"),
    )

    assert (unresolved.allowed, unresolved.reason) == (False, "resolution_required")
    assert (allowed.allowed, allowed.reason) == (True, "allowed_external_untrusted")
    assert (private.allowed, private.reason) == (False, "external_non_global_address")
    assert (mixed.allowed, mixed.reason) == (False, "external_non_global_address")


@pytest.mark.parametrize("url", (
    "http://127.0.0.1/path",
    "http://10.0.0.8/path",
    "http://169.254.1.2/path",
    "http://[::1]/path",
    "http://[fc00::1]/path",
))
def test_unconfigured_numeric_non_global_targets_are_rejected(url):
    decision = V80SecurityPolicy().evaluate(url)
    assert (decision.allowed, decision.zone, decision.reason) == (
        False, "external_untrusted", "external_non_global_address",
    )


@pytest.mark.parametrize("address", (
    "0.0.0.0", "224.0.0.1", "240.0.0.1", "::", "2001:db8::1",
))
def test_unspecified_multicast_and_reserved_addresses_are_always_rejected(address):
    policy = V80SecurityPolicy(trusted_backend_origins=("http://backend.local:4568",))
    decision = policy.evaluate("http://backend.local:4568/api", (address,))
    assert (decision.allowed, decision.reason) == (False, "forbidden_address")


def test_invalid_resolved_address_is_a_stable_non_echoing_decision():
    decision = V80SecurityPolicy().evaluate(
        "https://media.example/video", ("not-an-address-private",),
    )
    assert (decision.allowed, decision.reason) == (False, "invalid_address")
    assert "not-an-address-private" not in repr(decision)


def test_same_origin_redirect_preserves_only_allowed_headers_including_credentials():
    policy = V80SecurityPolicy(trusted_backend_origins=("https://backend.example",))
    decision = policy.redirect(
        "https://backend.example/api/start",
        "https://backend.example/api/next",
        ("93.184.216.34",),
        headers={
            AUTHORIZATION_HEADER: TEST_AUTHORIZATION,
            COOKIE_HEADER: TEST_COOKIE,
            "X-PlaySync-Since": "5",
            "X-Unknown": "drop",
        },
    )

    assert decision.allowed is True
    assert decision.same_origin is True
    assert decision.headers == {
        AUTHORIZATION_HEADER: TEST_AUTHORIZATION,
        COOKIE_HEADER: TEST_COOKIE,
        "X-PlaySync-Since": "5",
    }
    assert "secret-token" not in repr(decision)


def test_cross_origin_redirect_strips_credentials_origin_referer_and_unknown_headers():
    policy = V80SecurityPolicy(trusted_backend_origins=("https://backend.example",))
    decision = policy.redirect(
        "https://backend.example/play/1",
        "https://cdn.example/video.m3u8",
        ("93.184.216.34",),
        headers={
            "Accept": "*/*",
            AUTHORIZATION_HEADER: TEST_AUTHORIZATION,
            COOKIE_HEADER: TEST_COOKIE,
            "Origin": "https://backend.example",
            "Referer": "https://backend.example/play/1",
            "Range": "bytes=0-4095",
            "User-Agent": "FongMi",
            "X-CLIENT": "com.fongmi.android.tv",
            "X-PlaySync-Since": "5",
        },
    )

    assert decision.allowed is True
    assert decision.same_origin is False
    assert decision.headers == {
        "Accept": "*/*",
        "Range": "bytes=0-4095",
        "User-Agent": "FongMi",
        "X-CLIENT": "com.fongmi.android.tv",
    }


def test_external_redirect_cannot_enter_configured_or_trusted_internal_zone():
    policy = V80SecurityPolicy(
        trusted_backend_origins=("http://10.10.100.4:4568",),
        configured_internal_origins=("http://127.0.0.1:5244",),
    )

    trusted = policy.redirect(
        "https://media.example/start", "http://10.10.100.4:4568/api",
        ("10.10.100.4",),
    )
    configured = policy.redirect(
        "https://media.example/start", "http://127.0.0.1:5244/d",
        ("127.0.0.1",),
    )

    assert (trusted.allowed, trusted.reason) == (False, "external_to_internal_redirect")
    assert (configured.allowed, configured.reason) == (False, "external_to_internal_redirect")


def test_external_https_redirect_cannot_downgrade_to_http():
    decision = V80SecurityPolicy().redirect(
        "https://media.example/start", "http://cdn.example/video",
        ("93.184.216.34",),
    )
    assert (decision.allowed, decision.reason) == (False, "https_downgrade")


def test_each_redirect_hop_requires_a_fresh_compliant_resolution():
    policy = V80SecurityPolicy()
    first = policy.redirect(
        "https://media.example/start", "https://cdn.example/one",
        ("93.184.216.34",), redirect_count=0,
    )
    second = policy.redirect(
        "https://cdn.example/one", "https://edge.example/two",
        ("127.0.0.1",), redirect_count=1,
    )

    assert first.allowed is True
    assert (second.allowed, second.reason) == (False, "external_non_global_address")


def test_redirect_limit_is_enforced_before_target_processing():
    decision = V80SecurityPolicy().redirect(
        "https://media.example/start", "https://cdn.example/video",
        ("93.184.216.34",), redirect_count=5,
    )
    assert (decision.allowed, decision.reason) == (False, "too_many_redirects")


def test_header_policy_constants_keep_sensitive_headers_out_of_cross_origin_set():
    assert V80_SECURITY_SENSITIVE_HEADERS.isdisjoint(V80_SECURITY_CROSS_ORIGIN_HEADERS)
    assert V80_SECURITY_CROSS_ORIGIN_HEADERS == frozenset((
        "accept", "accept-language", "range", "user-agent", "x-client",
    ))


@pytest.mark.parametrize("headers,reason", (
    ({"Accept": "ok\r\nX-Evil: yes"}, "invalid_header_value"),
    ({"Cookie": "x" * (64 * 1024 + 1)}, "header_value_too_large"),
    ({"Accept": "a", "accept": "b"}, "conflicting_header"),
))
def test_malformed_oversized_or_conflicting_headers_are_rejected(headers, reason):
    with pytest.raises(V80SecurityPolicyError) as exc_info:
        v80_security_filter_headers(headers, same_origin=True)
    assert exc_info.value.reason == reason


def test_contract_is_pure_and_has_no_network_or_logging_imports():
    source = CONTRACT_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(CONTRACT_PATH))
    imports = set()
    calls = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module.split(".")[0])
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                calls.add(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                calls.add(node.func.attr)

    assert imports.isdisjoint({"requests", "socket", "ssl", "http", "logging"})
    assert calls.isdisjoint({"getaddrinfo", "urlopen", "request", "get", "post", "open"})

import ast
import importlib.util
from pathlib import Path
from urllib.parse import quote, quote_plus

import pytest


ROOT = Path(__file__).resolve().parent.parent
POLICY_PATH = (
    ROOT / "src" / "douban_tmdb_follow_single" / "diagnostic_redaction_policy.py"
)


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


POLICY = _load("v80_diagnostic_redaction_policy", POLICY_PATH)


def _redact(value, secrets=()):
    return POLICY.v80_redact_diagnostic_text(value, secrets=secrets)


def _fixture(*parts):
    return "".join(parts)


def test_limits_are_immutable_and_input_limit_is_exact():
    assert dict(POLICY.V80_DIAGNOSTIC_REDACTION_LIMITS) == {
        "max_input_chars": 4096,
        "max_secrets": 32,
        "max_secret_chars": 4096,
    }
    with pytest.raises(TypeError):
        POLICY.V80_DIAGNOSTIC_REDACTION_LIMITS["max_input_chars"] = 4097

    accepted = "x" * 4096
    assert _redact(accepted) == accepted
    assert _redact(accepted + "y") == accepted


def test_plain_diagnostic_text_is_preserved_exactly():
    value = (
        "TMDB HTTP 503; retry owner unchanged; "
        "https://example.test/items?ok=1; notpassword=value"
    )

    assert _redact(value) == value


@pytest.mark.parametrize("value,secrets", (
    (
        _fixture("Author", "ization: Bearer ", "header", "-", "fixture"),
        (_fixture("header", "-", "fixture"),),
    ),
    (
        _fixture("proxy-author", "ization=Basic ", "proxy", "-", "fixture"),
        (_fixture("proxy", "-", "fixture"),),
    ),
    (
        _fixture("Coo", "kie: sid=", "cookie", "-", "fixture", "; theme=dark"),
        (_fixture("cookie", "-", "fixture"),),
    ),
    (
        _fixture("SET-COO", "KIE: sid=", "set-cookie", "-", "fixture", "; HttpOnly"),
        (_fixture("set-cookie", "-", "fixture"),),
    ),
    (
        _fixture("request failed with bEaReR ", "standalone", "-", "fixture"),
        (_fixture("standalone", "-", "fixture"),),
    ),
    (
        _fixture("request failed with BASIC ", "basic", "-", "fixture"),
        (_fixture("basic", "-", "fixture"),),
    ),
))
def test_authentication_and_cookie_forms_are_redacted(value, secrets):
    result = _redact(value)

    assert all(secret not in result for secret in secrets)


@pytest.mark.parametrize("value,secret", (
    (
        _fixture('{"access_', 'to', 'ken":"json-', 'fixture","ok":1}'),
        _fixture("json", "-", "fixture"),
    ),
    (
        _fixture("{'client", "Se", "cret': 'json-", "fixture', 'ok': 1}"),
        _fixture("json", "-", "fixture"),
    ),
    (
        _fixture("pass", "word=assignment-", "password-fixture", " next=kept"),
        _fixture("assignment", "-", "password-fixture"),
    ),
    (
        _fixture("API_", "KEY: assignment-", "api-fixture"),
        _fixture("assignment", "-", "api-fixture"),
    ),
    (
        _fixture("WsSe", "CrEt=assignment-", "ws-fixture"),
        _fixture("assignment", "-", "ws-fixture"),
    ),
    (
        _fixture("session_", "to", "ken=assignment-", "session-fixture"),
        _fixture("assignment", "-", "session-fixture"),
    ),
))
def test_json_and_assignment_secret_names_are_case_insensitive(value, secret):
    result = _redact(value)

    assert secret not in result


def test_url_userinfo_and_signed_query_values_are_redacted():
    secrets = (
        "url-password", "token-value", "sign-value", "sig-value",
        "signature-value", "auth-direct", "key-value", "auth-value",
        "1700000000", "policy-value",
        "pair-value", "aws-value", "google-value", "ws-value",
        "akamai-value", "amz-value", "goog-value", "oss-value", "bce-value",
    )
    query_pairs = (
        ("ok", "1"), ("token", secrets[1]), ("auth", secrets[5]),
        ("key", secrets[6]), ("SIGN", secrets[2]), ("sig", secrets[3]),
        ("signature", secrets[4]), ("auth_key", secrets[7]),
        ("expires", secrets[8]), ("policy", secrets[9]),
        ("Key-Pair-Id", secrets[10]), ("AWSAccessKeyId", secrets[11]),
        ("GoogleAccessId", secrets[12]), ("wsSecret", secrets[13]),
        ("hdnts", secrets[14]), ("X-Amz-Credential", secrets[15]),
        ("x-goog-signature", secrets[16]), ("x-oss-signature", secrets[17]),
        ("X-Bce-Signature", secrets[18]),
    )
    value = "https" + "://user:%s@example.test/media?%s#fragment" % (
        secrets[0], "&".join("%s=%s" % pair for pair in query_pairs),
    )

    result = _redact(value)

    assert all(secret not in result for secret in secrets)
    assert "example.test/media" in result
    assert "ok=1" in result


@pytest.mark.parametrize("value,secret", (
    ("https://e.test/v?%58-Amz-Signature=AMZSECRET", "AMZSECRET"),
    ("https://e.test/v?%2578-goog-signature=GOOGSECRET", "GOOGSECRET"),
    ("https://e.test/%70lay/PLAYSECRET", "PLAYSECRET"),
    ("https://e.test/%2570arse/PARSESECRET", "PARSESECRET"),
))
def test_encoded_query_and_path_structure_names_are_redacted(value, secret):
    result = _redact(value)

    assert secret not in result
    assert "***" in result


@pytest.mark.parametrize("value,secret", (
    ({"Cookie": {"sid": "NESTED_COOKIE_SECRET"}}, "NESTED_COOKIE_SECRET"),
    ("{'Set-Cookie': ['sid=LIST_COOKIE_SECRET'], 'ok': 1}", "LIST_COOKIE_SECRET"),
    ([('Cookie', 'sid=PAIR_COOKIE_SECRET')], "PAIR_COOKIE_SECRET"),
    (("Set-Cookie", "sid=TUPLE_COOKIE_SECRET"), "TUPLE_COOKIE_SECRET"),
))
def test_sensitive_structured_values_are_redacted_as_one_value(value, secret):
    result = _redact(value)

    assert secret not in result
    assert "***" in result


@pytest.mark.parametrize("value,secrets", (
    (
        "http://[invalid/%70lay/MALFORMED_PATH_SECRET/x?%74oken=MALFORMED_QUERY_SECRET",
        ("MALFORMED_PATH_SECRET", "MALFORMED_QUERY_SECRET"),
    ),
    (
        "http://[invalid/%2570arse/DOUBLE_PATH_SECRET/x?%2574oken=DOUBLE_QUERY_SECRET",
        ("DOUBLE_PATH_SECRET", "DOUBLE_QUERY_SECRET"),
    ),
))
def test_malformed_urls_still_redact_encoded_path_and_query_structures(value, secrets):
    result = _redact(value)

    assert all(secret not in result for secret in secrets)
    assert "***" in result


@pytest.mark.parametrize("route", ("play", "parse", "offline_download", "p"))
def test_playback_path_tokens_are_redacted(route):
    secret = _fixture("path", "-", "value", "-", route)
    value = "https://example.test/api/%s/%s/file.m3u8?ok=1" % (route, secret)

    result = _redact(value)

    assert secret not in result
    assert "/%s/***/file.m3u8" % route in result
    assert "ok=1" in result


def test_explicit_secrets_cover_raw_url_encoded_and_double_encoded_forms():
    secret = _fixture("user/name", " + ", "pass%word")
    encoded = quote(secret, safe="")
    plus_encoded = quote_plus(secret, safe="")
    double_encoded = quote(encoded, safe="")
    double_plus_encoded = quote_plus(plus_encoded, safe="")
    value = " | ".join((secret, encoded, encoded.lower(), plus_encoded,
                        double_encoded, double_encoded.lower(), double_plus_encoded))

    result = _redact(value, secrets=(secret,))

    for leaked in (secret, encoded, encoded.lower(), plus_encoded,
                   double_encoded, double_encoded.lower(), double_plus_encoded):
        assert leaked not in result


def test_explicit_secrets_cover_mixed_case_percent_escapes():
    value = "%2F%2b | %2f%2B | %252F%252b | %252f%252B"

    result = _redact(value, secrets=("/+",))

    assert result == "*** | *** | *** | ***"


def test_explicit_marker_like_secret_does_not_erase_redaction_markers():
    value = _fixture("* ", "to", "ken=opaque-", "fixture")
    result = _redact(value, secrets=("*",))

    assert result == "*** token=***"


def test_explicit_structural_keyword_does_not_disable_structural_redaction():
    value = _fixture(
        "Bearer opaque-", "fixture https", "://user:opaque-", "fixture@example.test",
    )
    result = _redact(
        value,
        secrets=("Bearer",),
    )

    assert "opaque" not in result


def test_secret_count_and_length_work_are_bounded():
    consumed = []

    def endless_secrets():
        index = 0
        while True:
            consumed.append(index)
            yield "secret-%04d-value" % index
            index += 1

    limit = POLICY.V80_DIAGNOSTIC_REDACTION_LIMITS["max_secrets"]
    result = _redact(
        "secret-0000-value secret-0031-value secret-0032-value",
        secrets=endless_secrets(),
    )

    assert len(consumed) == limit
    assert "secret-0000-value" not in result
    assert "secret-0031-value" not in result
    assert "secret-0032-value" in result

    overlong = "s" * (POLICY.V80_DIAGNOSTIC_REDACTION_LIMITS["max_secret_chars"] + 1)
    assert isinstance(_redact(overlong, secrets=(overlong,)), str)
    assert len(_redact(overlong, secrets=(overlong,))) == 4096


@pytest.mark.parametrize("offset", (0, 100, 4095))
def test_max_length_secret_crossing_output_boundary_is_redacted(offset):
    secret = "s" * POLICY.V80_DIAGNOSTIC_REDACTION_LIMITS["max_secret_chars"]
    result = _redact("x" * offset + secret, secrets=(secret,))

    assert "s" * 32 not in result
    assert "*" in result


@pytest.mark.parametrize("value,secrets", (
    (None, None),
    (123, 456),
    (
        _fixture("Author", "ization: Bearer ", "byte", "-", "fixture").encode("ascii"),
        (_fixture("byte", "-", "fixture"),),
    ),
))
def test_malformed_inputs_are_stable_strings(value, secrets):
    assert isinstance(_redact(value, secrets=secrets), str)


def test_bounded_adversarial_text_does_not_require_nested_regex_search():
    value = ("token-token-token-=" * 10000) + "tail"
    result = _redact(value)

    assert isinstance(result, str)
    assert len(result) <= POLICY.V80_DIAGNOSTIC_REDACTION_LIMITS["max_input_chars"]


def test_policy_source_is_standard_library_only_and_has_no_runtime_owners():
    tree = ast.parse(POLICY_PATH.read_text(encoding="utf-8"), filename=str(POLICY_PATH))
    imports = {
        alias.name
        for node in tree.body
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imports.update(
        node.module
        for node in tree.body
        if isinstance(node, ast.ImportFrom)
    )
    calls = {
        node.func.id.lower()
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }

    assert imports == {"re", "types", "urllib.parse"}
    assert not ({"open", "print", "exec", "eval", "sleep"} & calls)
    source = POLICY_PATH.read_text(encoding="utf-8").lower()
    assert "spider" not in source
    assert "requests" not in source

import base64
import importlib.util
import sys
import types
from collections import UserDict
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import quote

import pytest

from src.douban_tmdb_follow_single.resource_row_identity import (
    build_resource_row_identity,
)


ROOT = Path(__file__).resolve().parents[1]
PUBLIC_SOURCE = ROOT / "py" / "豆瓣TMDB追更单入口.py"


@contextmanager
def _load_v70():
    base_module = types.ModuleType("base")
    spider_module = types.ModuleType("base.spider")
    spider_module.Spider = type("BaseSpider", (object,), {})
    base_module.spider = spider_module
    saved = (sys.modules.get("base"), sys.modules.get("base.spider"))
    sys.modules["base"] = base_module
    sys.modules["base.spider"] = spider_module
    try:
        spec = importlib.util.spec_from_file_location("v70_resource_row_identity_reference", PUBLIC_SOURCE)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        yield module
    finally:
        for name, previous in zip(("base", "base.spider"), saved):
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous


@pytest.fixture(scope="module")
def v70():
    with _load_v70() as module:
        yield module


def _assert_v70_equal(v70, value):
    expected = v70.Spider()._resource_row_identity(value)
    actual = build_resource_row_identity(value)
    assert actual == expected
    return actual


@pytest.mark.parametrize("value", [
    None,
    False,
    0,
    "",
    "   ",
    "ABC-123",
    "push://ABC-123",
    "HTTP://EXAMPLE.COM:80/a/",
    "https://EXAMPLE.COM:443/a/?b=2&a=1&pwd=x#A1",
    "http://[2001:DB8::1]:8080/a",
    "https://example.com/a#episode.1",
    "magnet:?xt=urn:btih:0123456789ABCDEF0123456789ABCDEF01234567&dn=first",
    "ed2k://|file|first.mkv|123|0123456789ABCDEF0123456789ABCDEF|/",
    {"_resource_mode": " PaNSou ", "vod_id": " ID-1 ", "url": "https://example.com/a"},
    {"vod_id": "   ", "id": " second "},
    {"target": "push://https%253A%252F%252FEXAMPLE.com%252Fa%252F"},
    UserDict({"vod_id": "wrapped"}),
])
def test_identity_matches_v70_for_fixed_contract_cases(v70, value):
    _assert_v70_equal(v70, value)


@pytest.mark.parametrize("value", [None, False, 0, "", "   ", {}, {"vod_id": ""}])
def test_empty_inputs_return_empty_identity(value):
    assert build_resource_row_identity(value) == ""


def test_dict_uses_fixed_first_nonempty_resource_id_field():
    row = {
        "_resource_mode": " PaNSou ",
        "vod_id": " primary ",
        "id": "secondary",
        "url": "https://example.com/a",
        "link": "https://example.com/b",
        "share_url": "https://example.com/c",
        "target": "https://example.com/d",
    }

    assert build_resource_row_identity(row) == "id:pansou:primary"


def test_dict_subclass_is_a_row_but_userdict_is_a_raw_value(v70):
    class RowDict(dict):
        pass

    row = RowDict({"_resource_mode": "VOD", "id": "same"})
    wrapped = UserDict(row)

    assert build_resource_row_identity(row) == "id:vod:same"
    assert _assert_v70_equal(v70, wrapped).startswith("id:unknown:")


def test_mode_affects_plain_ids_but_not_url_identities():
    assert build_resource_row_identity({"_resource_mode": "vod", "id": "same"}) == "id:vod:same"
    assert build_resource_row_identity({"_resource_mode": "pansou", "id": "same"}) == "id:pansou:same"
    assert build_resource_row_identity({"_resource_mode": "vod", "url": "http://Example.com/a"}) == (
        build_resource_row_identity({"_resource_mode": "pansou", "url": "https://example.com/a/"})
    )


def test_plain_id_keeps_case_and_encoded_text():
    assert build_resource_row_identity("ABC") != build_resource_row_identity("abc")
    assert build_resource_row_identity("%41BC") == "id:unknown:%41BC"


def test_limited_decode_recognizes_deeply_encoded_url():
    encoded = "https://Example.com/a/"
    for _index in range(40):
        encoded = quote(encoded, safe="")

    assert build_resource_row_identity(encoded) == "url:example.com/a"


def test_only_lowercase_push_prefix_is_removed():
    target = "https://example.com/a"

    assert build_resource_row_identity("push://" + target) == "url:example.com/a"
    assert build_resource_row_identity("PUSH://" + target) == "id:unknown:PUSH://" + target
    assert build_resource_row_identity("push://ABC") == "id:unknown:push://ABC"


def test_http_identity_ignores_scheme_and_default_port_but_keeps_nondefault_port():
    variants = {
        build_resource_row_identity("http://EXAMPLE.com:80/a/"),
        build_resource_row_identity("https://example.com:443/a"),
    }

    assert variants == {"url:example.com/a"}
    assert build_resource_row_identity("https://example.com:8443/a") == "url:example.com:8443/a"


def test_http_identity_sorts_query_and_removes_password_evidence():
    query_key = "pass" + "word"
    fragment_key = "p" + "wd"
    variants = {
        build_resource_row_identity(
            "https://example.com/a?b=2&a=1&%s=ABCD#%s=EFGH" % (query_key, fragment_key),
        ),
        build_resource_row_identity("http://EXAMPLE.com/a?a=1&b=2#IJKL"),
        build_resource_row_identity("https://example.com/a?b=2&%E6%8F%90%E5%8F%96%E7%A0%81=MNOP&a=1"),
    }

    assert variants == {"url:example.com/a?a=1&b=2"}


def test_nonpassword_fragment_and_blank_query_parts_keep_v70_shape():
    assert build_resource_row_identity("https://example.com/a?b=2&&a=1#episode.1") == (
        "url:example.com/a?&a=1&b=2#episode.1"
    )


def test_password_suffix_is_removed_from_path_and_trailing_punctuation():
    assert build_resource_row_identity("https://example.com/s/demo/提取码:A1；") == "url:example.com/s/demo"


def test_invalid_http_url_keeps_the_frozen_raw_url_identity(v70):
    for value in ("http://", "https://[broken"):
        assert _assert_v70_equal(v70, value) == "url:" + value


def test_magnet_uses_btih_and_unifies_hex_with_base32():
    hex_btih = "0123456789ABCDEF0123456789ABCDEF01234567"
    base32_btih = base64.b32encode(bytes.fromhex(hex_btih)).decode("ascii")
    variants = {
        build_resource_row_identity("magnet:?xt=urn:btih:" + hex_btih + "&dn=first"),
        build_resource_row_identity("MAGNET:?dn=second&xt=urn:btih:" + base32_btih),
    }

    assert variants == {"url:magnet:btih:" + hex_btih.lower()}


def test_magnet_without_valid_lowercase_xt_uses_casefolded_remainder():
    value = "MAGNET:?XT=urn:btih:NOT-A-HASH&DN=Mixed"

    assert build_resource_row_identity(value) == "url:magnet:?xt=urn:btih:not-a-hash&dn=mixed"


def test_ed2k_uses_last_content_hash_or_casefolded_remainder():
    first = "0123456789ABCDEF0123456789ABCDEF"
    second = "FEDCBA9876543210FEDCBA9876543210"
    value = "ed2k://|file|demo.mkv|1|%s|x|%s|/" % (first, second)

    assert build_resource_row_identity(value) == "url:ed2k:hash:" + second.lower()
    assert build_resource_row_identity("ED2K://|file|Mixed.mkv|1|bad|/") == (
        "url:ed2k://|file|mixed.mkv|1|bad|/"
    )


def test_identity_does_not_mutate_input_row():
    row = {"_resource_mode": " VOD ", "url": " https://Example.com/a/ "}
    original = dict(row)

    assert build_resource_row_identity(row) == "url:example.com/a"
    assert row == original

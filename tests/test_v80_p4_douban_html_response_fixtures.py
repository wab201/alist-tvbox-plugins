import hashlib
import importlib.util
import json
import re
import sys
import types
from functools import lru_cache
from pathlib import Path

import requests


ROOT = Path(__file__).resolve().parent.parent
FIXTURE_ROOT = ROOT / "tests" / "fixtures"
MANIFEST_PATH = FIXTURE_ROOT / "v80_p4_douban_html_response_fixtures.json"
BUILD_PATH = ROOT / "tools" / "build_follow_plugin.py"
RELEASE_PATH = ROOT / "src" / "douban_tmdb_follow_single" / "release.json"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BUILD = _load("v80_douban_html_fixture_build", BUILD_PATH)


def _manifest():
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def _fixtures():
    return {item["id"]: item for item in _manifest()["fixtures"]}


def _fixture_bytes(item):
    return (FIXTURE_ROOT / item["filename"]).read_bytes()


def _projection_metrics(raw):
    pattern = re.compile(
        rb"<!-- fixture:item:(valid|decoy):start -->.*?"
        rb"<!-- fixture:item:end -->",
        re.DOTALL,
    )
    matches = tuple(pattern.finditer(raw))
    valid_sizes = [
        len(match.group(0))
        for match in matches
        if match.group(1) == b"valid"
    ]
    shell_bytes = len(raw) - sum(len(match.group(0)) for match in matches)
    return shell_bytes, max(valid_sizes)


@lru_cache(maxsize=1)
def _runtime():
    base_module = types.ModuleType("base")
    spider_module = types.ModuleType("base.spider")

    class BaseSpider(object):
        pass

    spider_module.Spider = BaseSpider
    sys.modules.setdefault("base", base_module)
    sys.modules.setdefault("base.spider", spider_module)
    module = types.ModuleType("v80_douban_html_fixture_runtime")
    source = BUILD.build_release(RELEASE_PATH)["bytes"]
    exec(compile(source, "v80-douban-html-fixture-runtime.py", "exec"), module.__dict__)
    return module


def _parsed(case_id):
    item = _fixtures()[case_id]
    text = _fixture_bytes(item).decode("utf-8")
    spider = _runtime().Spider()
    spider.image_headers = False
    spider._get_text = lambda *_args, **_kwargs: text
    try:
        if case_id == "top250":
            return spider._category_top250(1, {})
        spider.user_id = "fixture-user"
        return spider._category_wishlist(1)
    finally:
        spider.destroy()


def _requests_text(body, content_type=""):
    response = requests.Response()
    response.status_code = 200
    response._content = bytes(body)
    response._content_consumed = True
    if content_type:
        response.headers["Content-Type"] = content_type
        response.encoding = requests.utils.get_encoding_from_headers(response.headers)
    return response.text


def test_fixture_inventory_and_text_encoding_are_frozen():
    manifest = _manifest()

    assert manifest["schema"] == "v80-p4-douban-html-response-fixtures/1"
    assert manifest["encoding"] == "utf-8"
    assert manifest["line_endings"] == "lf"
    assert tuple(item["id"] for item in manifest["fixtures"]) == (
        "top250", "wishlist",
    )


def test_raw_fixture_bytes_hashes_and_projection_inputs_are_exact():
    for item in _manifest()["fixtures"]:
        raw = _fixture_bytes(item)
        shell_bytes, largest_item_bytes = _projection_metrics(raw)

        assert not raw.startswith(b"\xef\xbb\xbf")
        assert b"\r" not in raw
        assert len(raw) == item["utf8_bytes"]
        assert hashlib.sha256(raw).hexdigest().upper() == item["sha256"]
        assert shell_bytes == item["shell_bytes"]
        assert largest_item_bytes == item["largest_valid_item_bytes"]
        assert (
            shell_bytes + item["page_size"] * largest_item_bytes
            == item["projected_parser_page_bytes"]
        )
        assert len(raw.decode("utf-8")) >= 500


def test_response_limit_is_selected_from_complete_observed_envelopes():
    response_limit = _manifest()["response_limit"]
    projections = [
        item["projected_parser_page_bytes"]
        for item in _manifest()["fixtures"]
    ]
    observed = [
        value
        for value in response_limit["observed_decompressed_bodies"].values()
        if value is not None
    ]
    selection_input = max(16 * max(projections), 4 * max(observed))
    rounded_selection = ((selection_input + 65535) // 65536) * 65536

    assert max(projections) == response_limit["maximum_parser_projection_bytes"]
    assert rounded_selection == response_limit["computed_bytes"] == 256 * 1024
    assert response_limit["observed_decompressed_bodies"] == {
        "top250": 64547,
        "wishlist": 57197,
    }
    assert response_limit["selected_bytes"] == rounded_selection
    assert response_limit["status"] == "selected_from_complete_observed_envelopes"
    assert response_limit["formula"] == "round_up_64KiB(max(16*P,4*O))"
    assert response_limit["must_not_copy"] == [
        "P4-5 TMDB 2 MiB",
        "P4-7 Douban JSON 512 KiB",
    ]


def test_wishlist_observation_is_complete_and_identity_free():
    observation = _manifest()["response_limit"]["wishlist_observation"]

    assert observation == {
        "provenance": "authorized_single_request_redacted",
        "observed_on": "2026-08-16",
        "request_count": 1,
        "status_code": 200,
        "redirect": False,
        "content_type": "text/html",
        "charset": "utf-8",
        "sha256": (
            "AA28F4570F11493F8B9EBB19E6176E2A12368817F0371804CC6E2C442EADB0C9"
        ),
        "grid_view_items": 15,
        "valid_movie_subject_links": 15,
        "full_15_item_page": True,
    }


def test_requests_text_decode_contract_is_frozen_before_streaming_changes():
    fixture_body = _fixture_bytes(_fixtures()["wishlist"])

    assert _requests_text(
        fixture_body, "text/html; charset=utf-8",
    ) == fixture_body.decode("utf-8")
    assert _requests_text(
        fixture_body, "text/html",
    ) == fixture_body.decode("iso-8859-1")
    assert _requests_text(fixture_body) == fixture_body.decode("utf-8")
    assert _requests_text(
        b"valid-prefix-\xff-valid-suffix", "text/html; charset=utf-8",
    ) == "valid-prefix-\ufffd-valid-suffix"


def test_top250_parser_contract_preserves_two_cards_and_score_fallback():
    item = _fixtures()["top250"]
    result = _parsed("top250")

    assert result["list"] == item["expected_cards"]
    assert {key: result[key] for key in item["expected_page"]} == (
        item["expected_page"]
    )


def test_wishlist_parser_contract_preserves_all_three_fallback_paths():
    item = _fixtures()["wishlist"]
    result = _parsed("wishlist")

    assert result["list"] == item["expected_cards"]
    assert {key: result[key] for key in item["expected_page"]} == (
        item["expected_page"]
    )

# -*- coding: utf-8 -*-

import json
from pathlib import Path

import pytest

from src.douban_tmdb_follow_single.resource_provider import (
    GENERIC_PAYLOAD_SCHEMAS,
    RESOURCE_PROVIDER_ADAPTERS,
    SUPPLEMENT_PAYLOAD_SCHEMAS,
    get_resource_provider_adapter,
)
from src.douban_tmdb_follow_single.resource_schema import (
    GENERIC_ROW_SCHEMA,
    RESOURCE_MODES,
    SUPPLEMENT_ROW_SCHEMA,
)
from src.douban_tmdb_follow_single.resource_shadow import map_resource_payload


ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "v80_p2_resource_samples.json"


@pytest.fixture(scope="module")
def samples():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_registry_is_fixed_and_ordered_like_v70_modes():
    assert tuple(adapter.mode for adapter in RESOURCE_PROVIDER_ADAPTERS) == RESOURCE_MODES
    assert tuple(adapter.endpoint_mode for adapter in RESOURCE_PROVIDER_ADAPTERS) == (
        "vod1", "vod", "pansou", "tg-search",
    )


@pytest.mark.parametrize("mode", RESOURCE_MODES)
def test_adapter_lookup_normalizes_mode(mode):
    adapter = get_resource_provider_adapter("  %s  " % mode.upper())
    assert adapter is RESOURCE_PROVIDER_ADAPTERS[RESOURCE_MODES.index(mode)]


def test_unknown_mode_is_rejected():
    with pytest.raises(ValueError, match="unsupported resource mode"):
        get_resource_provider_adapter("future")


@pytest.mark.parametrize(
    "mode, expected",
    [
        ("vod1", {"endpoint_mode": "vod1", "params": {"wd": "Title", "pg": 1, "size": 50, "ac": "detail"}}),
        ("vod", {"endpoint_mode": "vod", "params": {"wd": "Title", "pg": 1, "size": 50, "ac": "detail"}}),
        ("pansou", {"endpoint_mode": "pansou", "params": {"wd": "Title", "pg": 1}}),
        ("telegram", {"endpoint_mode": "tg-search", "params": {"wd": "Title", "pg": 1, "web": "true"}}),
    ],
)
def test_search_requests_match_frozen_v70(mode, expected):
    assert get_resource_provider_adapter(mode).search_request(" Title ") == expected


@pytest.mark.parametrize(
    "mode, expected",
    [
        ("vod1", {"endpoint_mode": "vod1", "params": {"ids": "id%2Fvalue", "ac": "detail"}}),
        ("vod", {"endpoint_mode": "vod", "params": {"ids": "id%2Fvalue", "ac": "detail"}}),
        ("pansou", {"endpoint_mode": "pansou", "params": {"id": "id/value"}}),
        ("telegram", {"endpoint_mode": "tg-search", "params": {"id": "id/value", "ac": "detail", "title": "Title", "web": "true"}}),
    ],
)
def test_detail_requests_match_frozen_v70(mode, expected):
    assert get_resource_provider_adapter(mode).detail_request(
        " id%2Fvalue ", " Title ",
    ) == expected


@pytest.mark.parametrize("mode", ("vod1", "vod"))
def test_generic_adapters_register_only_generic_contracts(mode):
    adapter = get_resource_provider_adapter(mode)
    assert adapter.payload_schemas == GENERIC_PAYLOAD_SCHEMAS
    assert adapter.row_schemas == (GENERIC_ROW_SCHEMA,)


@pytest.mark.parametrize("mode", ("pansou", "telegram"))
def test_supplement_adapters_register_only_frozen_supplement_contracts(mode):
    adapter = get_resource_provider_adapter(mode)
    assert adapter.payload_schemas == SUPPLEMENT_PAYLOAD_SCHEMAS
    assert adapter.row_schemas == (GENERIC_ROW_SCHEMA, SUPPLEMENT_ROW_SCHEMA)


@pytest.mark.parametrize("mode", RESOURCE_MODES)
def test_adapter_detection_and_normalization_match_existing_shadow_contract(samples, mode):
    adapter = get_resource_provider_adapter(mode)
    payload = samples["payloads"][mode]

    assert adapter.detect(payload)
    assert all(match.schema_id in adapter.payload_schemas for match in adapter.detect(payload))
    assert adapter.normalize(payload) == map_resource_payload(mode, payload)


@pytest.mark.parametrize("mode", RESOURCE_MODES)
def test_unknown_schema_degrades_without_guessing(mode):
    adapter = get_resource_provider_adapter(mode)
    payload = {"future_container": [{"id": "not-registered"}]}

    assert adapter.detect(payload) == ()
    assert adapter.normalize(payload) == ()

# -*- coding: utf-8 -*-

import copy
from urllib.parse import quote

import pytest

from src.douban_tmdb_follow_single.resource_search_plan import (
    BINDING_LAYER,
    CACHE_LAYER,
    FAST_PROVIDER_LAYER,
    RECENT_SUCCESS_LAYER,
    SUPPLEMENT_PROVIDER_LAYER,
)
from src.douban_tmdb_follow_single.resource_search_v70_adapter import (
    build_v70_layered_resource_rows,
    build_v70_layered_resource_shadow,
    combine_v70_layered_resource_rows,
)


def _pairs(batches):
    return [(batch.step.layer, batch.step.mode) for batch in batches]


def _ids(batch):
    return [candidate.resource_id for candidate in batch.candidates]


def test_v70_rows_are_classified_before_provider_batches():
    cached = {
        "vod_id": quote("https://pan.quark.cn/s/cache", safe=""),
        "vod_name": "Cached",
        "_resource_mode": "pansou",
    }
    rows = [
        dict(cached),
        {"vod_id": "recent-id", "vod_name": "Recent", "_resource_mode": "vod"},
        {"vod_id": "bound-id", "vod_name": "Bound", "_resource_mode": "vod1"},
        {"vod_id": "vod-id", "vod_name": "Vod", "_resource_mode": "vod"},
        {
            "vod_id": quote("https://pan.baidu.com/s/provider", safe=""),
            "vod_name": "PanSou",
            "provider": "baidu",
            "_resource_mode": "pansou",
        },
    ]

    batches = build_v70_layered_resource_shadow(
        rows,
        cached_rows=[{
            "vod_id": "https://pan.quark.cn/s/cache",
            "_resource_mode": "pansou",
        }],
        recent_resource_id="recent-id",
        binding_resource_id="bound-id",
        available_modes=["pansou", "vod", "vod1"],
    )

    assert _pairs(batches) == [
        (CACHE_LAYER, ""),
        (RECENT_SUCCESS_LAYER, ""),
        (BINDING_LAYER, ""),
        (FAST_PROVIDER_LAYER, "vod1"),
        (FAST_PROVIDER_LAYER, "vod"),
        (SUPPLEMENT_PROVIDER_LAYER, "pansou"),
    ]
    assert _ids(batches[0]) == [cached["vod_id"]]
    assert _ids(batches[1]) == ["recent-id"]
    assert _ids(batches[2]) == ["bound-id"]
    assert _ids(batches[3]) == []
    assert _ids(batches[4]) == ["vod-id"]
    assert _ids(batches[5]) == [rows[-1]["vod_id"]]


def test_cache_then_recent_then_binding_is_the_classification_priority():
    row = {"vod_id": "same", "vod_name": "Same", "_resource_mode": "vod"}

    cached = build_v70_layered_resource_shadow(
        [row], cached_rows=[row], recent_resource_id="same",
        binding_resource_id="same", available_modes=["vod"],
    )
    recent = build_v70_layered_resource_shadow(
        [row], recent_resource_id="same", binding_resource_id="same",
        available_modes=["vod"],
    )

    assert _pairs(cached) == [(CACHE_LAYER, ""), (FAST_PROVIDER_LAYER, "vod")]
    assert _ids(cached[0]) == ["same"]
    assert cached[1].candidates == ()
    assert _pairs(recent) == [(RECENT_SUCCESS_LAYER, ""), (FAST_PROVIDER_LAYER, "vod")]
    assert _ids(recent[0]) == ["same"]
    assert recent[1].candidates == ()


def test_available_provider_without_rows_is_retained_as_an_empty_batch():
    batches = build_v70_layered_resource_shadow([], available_modes=["vod1", "telegram"])
    assert _pairs(batches) == [
        (FAST_PROVIDER_LAYER, "vod1"),
        (SUPPLEMENT_PROVIDER_LAYER, "telegram"),
    ]
    assert all(batch.candidates == () for batch in batches)


def test_adapter_does_not_mutate_v70_inputs():
    rows = [{"vod_id": "one", "vod_name": "One", "_resource_mode": "vod"}]
    cached = [{"vod_id": "cached", "_resource_mode": "vod"}]
    before_rows = copy.deepcopy(rows)
    before_cached = copy.deepcopy(cached)

    build_v70_layered_resource_shadow(rows, cached_rows=cached, available_modes=["vod"])

    assert rows == before_rows
    assert cached == before_cached


def test_unknown_v70_mode_is_rejected():
    with pytest.raises(ValueError, match="unsupported resource mode"):
        build_v70_layered_resource_shadow(
            [{"vod_id": "one", "_resource_mode": "future"}],
            available_modes=["vod"],
        )


def test_raw_batches_preserve_complete_rows_and_hide_them_from_repr():
    row = {
        "vod_id": "raw-one",
        "vod_name": "Raw One",
        "_resource_mode": "vod",
        "headers": {"Referer": "https://media.example/"},
        "links": [{"url": "https://media.example/play"}],
        "vod_remarks": "原始备注",
        "private_payload": {"play_id": "opaque"},
    }

    batches = build_v70_layered_resource_rows([row], available_modes=["vod"])

    assert _pairs(batches) == [(FAST_PROVIDER_LAYER, "vod")]
    assert batches[0].rows == (row,)
    assert batches[0].rows[0] is not row
    assert tuple(batches[0].rows[0]) == tuple(row)
    assert "media.example" not in repr(batches[0])


def test_raw_combiner_keeps_layer_priority_and_complete_payloads():
    rows = [
        {
            "vod_id": "cache-low",
            "_resource_mode": "vod",
            "score": 1,
            "preference": (1,),
            "provider": "a",
            "headers": {"X-Cache": "low"},
        },
        {
            "vod_id": "cache-high",
            "_resource_mode": "vod",
            "score": 2,
            "preference": (2,),
            "provider": "b",
            "links": [{"url": "cache-high"}],
        },
        {
            "vod_id": "recent",
            "_resource_mode": "vod1",
            "score": 9,
            "preference": (9,),
            "provider": "c",
            "vod_remarks": "recent-row",
        },
        {
            "vod_id": "provider-vod",
            "_resource_mode": "vod",
            "score": 99,
            "preference": (99,),
            "provider": "d",
            "private_payload": {"play_id": "vod"},
        },
        {
            "vod_id": "provider-pan",
            "_resource_mode": "pansou",
            "score": 100,
            "preference": (100,),
            "provider": "e",
            "private_payload": {"play_id": "pan"},
        },
    ]

    result = combine_v70_layered_resource_rows(
        rows,
        cached_rows=rows[:2],
        recent_resource_id="recent",
        available_modes=("pansou", "vod", "vod1"),
        merge_rows=lambda left, right: dict(left, **right),
        score_row=lambda row: row["score"],
        preference_row=lambda row: row["preference"],
        provider_row=lambda row: row["provider"],
    )

    assert [row["vod_id"] for row in result] == [
        "cache-high", "cache-low", "recent", "provider-vod", "provider-pan",
    ]
    assert result[0]["links"] == [{"url": "cache-high"}]
    assert result[1]["headers"] == {"X-Cache": "low"}
    assert result[2]["vod_remarks"] == "recent-row"
    assert result[-1]["private_payload"] == {"play_id": "pan"}


def test_raw_combiner_reuses_the_frozen_merge_owner_within_a_layer():
    rows = [
        {
            "vod_id": "duplicate",
            "_resource_mode": "vod",
            "score": 4,
            "preference": (1,),
            "provider": "one",
            "headers": {"Referer": "first"},
        },
        {
            "vod_id": "duplicate",
            "_resource_mode": "vod",
            "score": 4,
            "preference": (1,),
            "provider": "one",
            "links": [{"url": "second"}],
        },
    ]
    merge_calls = []

    def merge_rows(left, right):
        merge_calls.append((left["vod_id"], right["vod_id"]))
        merged = dict(left)
        merged.update(right)
        merged["headers"] = left["headers"]
        return merged

    result = combine_v70_layered_resource_rows(
        rows,
        available_modes=("vod",),
        merge_rows=merge_rows,
        score_row=lambda row: row["score"],
        preference_row=lambda row: row["preference"],
        provider_row=lambda row: row["provider"],
    )

    assert merge_calls == [("duplicate", "duplicate")]
    assert len(result) == 1
    assert result[0]["headers"] == {"Referer": "first"}
    assert result[0]["links"] == [{"url": "second"}]

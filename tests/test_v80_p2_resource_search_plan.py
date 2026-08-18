# -*- coding: utf-8 -*-

import itertools

import pytest

from src.douban_tmdb_follow_single.resource_schema import RESOURCE_MODES
from src.douban_tmdb_follow_single.resource_search_plan import (
    BINDING_LAYER,
    CACHE_LAYER,
    FAST_PROVIDER_LAYER,
    RECENT_SUCCESS_LAYER,
    SUPPLEMENT_PROVIDER_LAYER,
    ResourceSearchStep,
    build_resource_search_plan,
)


def _pairs(plan):
    return [(step.layer, step.mode) for step in plan]


def test_complete_plan_uses_the_fixed_layer_and_provider_order():
    plan = build_resource_search_plan(
        ["telegram", "vod", "pansou", "vod1"],
        cache_available=True,
        recent_success_available=True,
        binding_available=True,
    )

    assert _pairs(plan) == [
        (CACHE_LAYER, ""),
        (RECENT_SUCCESS_LAYER, ""),
        (BINDING_LAYER, ""),
        (FAST_PROVIDER_LAYER, "vod1"),
        (FAST_PROVIDER_LAYER, "vod"),
        (SUPPLEMENT_PROVIDER_LAYER, "pansou"),
        (SUPPLEMENT_PROVIDER_LAYER, "telegram"),
    ]


def test_all_layer_and_mode_combinations_are_deterministic():
    for mode_mask in range(1 << len(RESOURCE_MODES)):
        selected = [
            mode for index, mode in enumerate(RESOURCE_MODES)
            if mode_mask & (1 << index)
        ]
        noisy = list(reversed(selected)) + selected
        expected_modes = tuple(mode for mode in RESOURCE_MODES if mode in selected)
        for cache, recent, binding in itertools.product((False, True), repeat=3):
            plan = build_resource_search_plan(
                noisy,
                cache_available=cache,
                recent_success_available=recent,
                binding_available=binding,
            )
            provider_modes = tuple(step.mode for step in plan if step.mode)
            local_layers = tuple(step.layer for step in plan if not step.mode)
            assert provider_modes == expected_modes
            assert len(provider_modes) == len(set(provider_modes))
            assert local_layers == tuple(
                layer for enabled, layer in (
                    (cache, CACHE_LAYER),
                    (recent, RECENT_SUCCESS_LAYER),
                    (binding, BINDING_LAYER),
                ) if enabled
            )


def test_empty_provider_set_can_still_reuse_local_layers():
    assert _pairs(build_resource_search_plan(
        [], cache_available=True, binding_available=True,
    )) == [(CACHE_LAYER, ""), (BINDING_LAYER, "")]


def test_unknown_provider_mode_is_rejected():
    with pytest.raises(ValueError, match="unsupported resource mode"):
        build_resource_search_plan(["vod", "future"])


def test_step_serialization_is_stable():
    assert ResourceSearchStep(FAST_PROVIDER_LAYER, "vod1").to_dict() == {
        "layer": "fast_provider",
        "mode": "vod1",
    }

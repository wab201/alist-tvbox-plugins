# -*- coding: utf-8 -*-

import copy
import json
from pathlib import Path

from src.douban_tmdb_follow_single.resource_models import ResourceCandidate
from src.douban_tmdb_follow_single.resource_search_plan import (
    BINDING_LAYER,
    CACHE_LAYER,
    FAST_PROVIDER_LAYER,
    RECENT_SUCCESS_LAYER,
    SUPPLEMENT_PROVIDER_LAYER,
    ResourceSearchStep,
)
from src.douban_tmdb_follow_single.resource_search_shadow import (
    LayeredResourceBatch,
    build_layered_resource_shadow,
)


ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "v80_p2_resource_samples.json"


def _candidate(resource_id, mode="vod"):
    return ResourceCandidate(
        resource_id=resource_id,
        mode=mode,
        work_title=resource_id,
    )


def _pairs(batches):
    return [(batch.step.layer, batch.step.mode) for batch in batches]


def test_layered_shadow_combines_local_candidates_and_registered_payloads():
    samples = json.loads(FIXTURE.read_text(encoding="utf-8"))
    local = {
        CACHE_LAYER: [_candidate("cached")],
        RECENT_SUCCESS_LAYER: [_candidate("recent", "pansou")],
        BINDING_LAYER: [_candidate("bound")],
    }

    batches = build_layered_resource_shadow(
        local,
        samples["payloads"],
        ["telegram", "vod", "pansou", "vod1"],
    )

    assert _pairs(batches) == [
        (CACHE_LAYER, ""),
        (RECENT_SUCCESS_LAYER, ""),
        (BINDING_LAYER, ""),
        (FAST_PROVIDER_LAYER, "vod1"),
        (FAST_PROVIDER_LAYER, "vod"),
        (SUPPLEMENT_PROVIDER_LAYER, "pansou"),
        (SUPPLEMENT_PROVIDER_LAYER, "telegram"),
    ]
    assert [batch.candidates[0].resource_id for batch in batches[:3]] == [
        "cached", "recent", "bound",
    ]
    assert [len(batch.candidates) for batch in batches[3:]] == [2, 2, 4, 3]


def test_empty_local_layers_are_omitted_but_attempted_provider_is_retained():
    batches = build_layered_resource_shadow(
        {CACHE_LAYER: [], BINDING_LAYER: []},
        {"vod": {"future_container": [{"id": "unknown"}]}},
        ["vod"],
    )

    assert _pairs(batches) == [(FAST_PROVIDER_LAYER, "vod")]
    assert batches[0].candidates == ()


def test_payload_keys_supply_modes_when_the_mode_list_is_omitted():
    batches = build_layered_resource_shadow(
        {},
        {
            "telegram": {"results": []},
            "vod1": {"list": [{"id": "one", "title": "One"}]},
        },
    )

    assert _pairs(batches) == [
        (FAST_PROVIDER_LAYER, "vod1"),
        (SUPPLEMENT_PROVIDER_LAYER, "telegram"),
    ]
    assert batches[0].candidates[0].resource_id == "one"
    assert batches[1].candidates == ()


def test_explicit_empty_mode_list_disables_provider_payloads():
    assert build_layered_resource_shadow(
        {}, {"vod": {"list": [{"id": "one", "title": "One"}]}}, [],
    ) == ()


def test_composition_does_not_mutate_inputs():
    local = {CACHE_LAYER: [_candidate("cached")]}
    payloads = {"vod": {"list": [{"id": "one", "title": "One"}]}}
    local_before = copy.deepcopy(local)
    payloads_before = copy.deepcopy(payloads)

    build_layered_resource_shadow(local, payloads, ["vod"])

    assert local == local_before
    assert payloads == payloads_before


def test_batch_serialization_is_stable():
    batch = LayeredResourceBatch(
        step=ResourceSearchStep(CACHE_LAYER),
        candidates=(_candidate("cached"),),
    )

    assert batch.to_dict() == {
        "step": {"layer": "cache", "mode": ""},
        "candidates": [{
            "resource_id": "cached",
            "mode": "vod",
            "provider": "",
            "work_title": "cached",
            "titles": [],
            "year": "",
            "source": "",
            "timestamp": "",
        }],
    }

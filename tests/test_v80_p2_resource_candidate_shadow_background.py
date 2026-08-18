import hashlib

import pytest

from src.douban_tmdb_follow_single.resource_candidate_shadow_background import (
    RESOURCE_CANDIDATE_SHADOW_ESTIMATED_COST_US,
    build_background_resource_candidate_shadow_inputs,
)
from src.douban_tmdb_follow_single.resource_candidate_shadow_composition import (
    compose_resource_candidate_shadow,
)


class _UnreadableRows:
    def __iter__(self):
        raise AssertionError("rows must not be consumed")


def _expected_key(cache_key, generation):
    material = "resource-candidate-shadow|%d|%s" % (generation, cache_key)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _compose(inputs, **overrides):
    values = {
        "legacy_rows": [],
        "rows": [],
        "merge_rows": lambda _left, right: right,
        "score_row": lambda row: row["score"],
        "preference_row": lambda row: row["preference"],
        "provider_row": lambda row: row.get("provider"),
    }
    values.update(inputs)
    values.update(overrides)
    return compose_resource_candidate_shadow(**values)


def test_defaults_keep_the_background_adapter_disabled_and_unbudgeted():
    cache_key = "resource-search:" + "a" * 64

    result = build_background_resource_candidate_shadow_inputs(
        cache_key=cache_key,
        generation=7,
    )

    assert result == {
        "enabled": False,
        "sample_key": "",
        "sample_every": 1,
        "available_budget_us": 0,
        "estimated_cost_us": RESOURCE_CANDIDATE_SHADOW_ESTIMATED_COST_US,
        "already_sampled": False,
    }
    assert cache_key not in str(result)


def test_same_background_identity_is_process_stable():
    values = {
        "enabled": True,
        "cache_key": "resource-search:" + "b" * 64,
        "generation": 9,
    }

    assert build_background_resource_candidate_shadow_inputs(**values) == (
        build_background_resource_candidate_shadow_inputs(**values)
    )


def test_generation_and_cache_key_are_both_part_of_the_sample_identity():
    cache_key = "resource-search:" + "c" * 64
    first = build_background_resource_candidate_shadow_inputs(
        enabled=True, cache_key=cache_key, generation=1,
    )["sample_key"]
    next_generation = build_background_resource_candidate_shadow_inputs(
        enabled=True, cache_key=cache_key, generation=2,
    )["sample_key"]
    other_cache = build_background_resource_candidate_shadow_inputs(
        enabled=True, cache_key="resource-search:" + "d" * 64, generation=1,
    )["sample_key"]

    assert len({first, next_generation, other_cache}) == 3


def test_unicode_cache_keys_are_hashed_without_entering_the_result():
    private_key = "resource-search:作品-测试-01"

    result = build_background_resource_candidate_shadow_inputs(
        enabled=True,
        cache_key=private_key,
        generation=3,
    )

    assert result["sample_key"] == _expected_key(private_key, 3)
    assert private_key not in str(result)


@pytest.mark.parametrize("cache_key", ["", None, b"resource-search:key"])
def test_missing_or_nontext_cache_keys_produce_a_missing_policy_key(cache_key):
    result = build_background_resource_candidate_shadow_inputs(
        enabled=True,
        cache_key=cache_key,
        generation=3,
    )

    assert result["sample_key"] == ""


@pytest.mark.parametrize("generation", [None, -1, True, 1.5])
def test_invalid_generations_do_not_create_a_sample_identity(generation):
    result = build_background_resource_candidate_shadow_inputs(
        enabled=True,
        cache_key="resource-search:" + "e" * 64,
        generation=generation,
        sampled_generation=generation,
    )

    assert result["sample_key"] == ""
    assert result["already_sampled"] is False


def test_matching_generation_maps_caller_state_to_already_sampled():
    result = build_background_resource_candidate_shadow_inputs(
        enabled=True,
        cache_key="resource-search:" + "f" * 64,
        generation=11,
        sampled_generation=11,
    )

    assert result["already_sampled"] is True
    assert result["sample_key"] == ""


@pytest.mark.parametrize("sampled_generation", [None, 10, 12, True])
def test_other_or_invalid_sampled_generations_remain_eligible(sampled_generation):
    result = build_background_resource_candidate_shadow_inputs(
        enabled=True,
        cache_key="resource-search:" + "0" * 64,
        generation=11,
        sampled_generation=sampled_generation,
    )

    assert result["already_sampled"] is False


def test_disabled_and_already_sampled_paths_do_not_hash_the_cache_key(monkeypatch):
    def fail(*_args, **_kwargs):
        raise AssertionError("sha256 must not run")

    monkeypatch.setattr(hashlib, "sha256", fail)

    disabled = build_background_resource_candidate_shadow_inputs(
        cache_key="resource-search:" + "5" * 64,
        generation=8,
    )
    sampled = build_background_resource_candidate_shadow_inputs(
        enabled=True,
        cache_key="resource-search:" + "6" * 64,
        generation=8,
        sampled_generation=8,
    )

    assert disabled["sample_key"] == ""
    assert sampled["sample_key"] == ""


@pytest.mark.parametrize("enabled", [False, None, 0, 1, "true", True])
def test_enabled_value_is_forwarded_without_truthiness_coercion(enabled):
    result = build_background_resource_candidate_shadow_inputs(enabled=enabled)

    assert result["enabled"] is enabled


def test_dedicated_budget_and_policy_values_are_forwarded_without_recalculation():
    result = build_background_resource_candidate_shadow_inputs(
        sample_every=17,
        shadow_budget_us=7000,
        estimated_cost_us=6000,
    )

    assert result["sample_every"] == 17
    assert result["available_budget_us"] == 7000
    assert result["estimated_cost_us"] == 6000


def test_result_has_exactly_the_policy_input_fields():
    result = build_background_resource_candidate_shadow_inputs()

    assert tuple(result) == (
        "enabled", "sample_key", "sample_every", "available_budget_us",
        "estimated_cost_us", "already_sampled",
    )


def test_default_inputs_short_circuit_composition_without_consuming_rows():
    inputs = build_background_resource_candidate_shadow_inputs(
        cache_key="resource-search:" + "1" * 64,
        generation=1,
    )

    result = _compose(
        inputs,
        legacy_rows=_UnreadableRows(),
        rows=_UnreadableRows(),
    )

    assert result == {
        "decision": {"run": False, "reason": "disabled"},
        "report": None,
    }


def test_explicit_shadow_budget_can_admit_one_background_comparison():
    inputs = build_background_resource_candidate_shadow_inputs(
        enabled=True,
        cache_key="resource-search:" + "2" * 64,
        generation=4,
        sample_every=1,
        shadow_budget_us=RESOURCE_CANDIDATE_SHADOW_ESTIMATED_COST_US,
    )

    result = _compose(inputs)

    assert result["decision"] == {"run": True, "reason": "selected"}
    assert result["report"]["status"] == "equal"


def test_shadow_budget_below_the_fixed_estimate_does_not_consume_rows():
    inputs = build_background_resource_candidate_shadow_inputs(
        enabled=True,
        cache_key="resource-search:" + "3" * 64,
        generation=5,
        shadow_budget_us=RESOURCE_CANDIDATE_SHADOW_ESTIMATED_COST_US - 1,
    )

    result = _compose(
        inputs,
        legacy_rows=_UnreadableRows(),
        rows=_UnreadableRows(),
    )

    assert result == {
        "decision": {"run": False, "reason": "insufficient_budget"},
        "report": None,
    }


def test_matching_sampled_generation_prevents_duplicate_background_work():
    inputs = build_background_resource_candidate_shadow_inputs(
        enabled=True,
        cache_key="resource-search:" + "4" * 64,
        generation=6,
        sampled_generation=6,
        shadow_budget_us=RESOURCE_CANDIDATE_SHADOW_ESTIMATED_COST_US,
    )

    result = _compose(
        inputs,
        legacy_rows=_UnreadableRows(),
        rows=_UnreadableRows(),
    )

    assert result == {
        "decision": {"run": False, "reason": "already_sampled"},
        "report": None,
    }

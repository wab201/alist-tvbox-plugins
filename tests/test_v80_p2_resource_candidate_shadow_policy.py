import hashlib

import pytest

from src.douban_tmdb_follow_single.resource_candidate_shadow_policy import (
    decide_resource_candidate_shadow,
)


def _decide(**overrides):
    values = {
        "enabled": True,
        "sample_key": "work-1",
        "sample_every": 1,
        "available_budget_us": 6000,
        "estimated_cost_us": 5328,
        "already_sampled": False,
    }
    values.update(overrides)
    return decide_resource_candidate_shadow(**values)


@pytest.mark.parametrize("enabled", [False, None, 0, 1, "true"])
def test_only_literal_true_enables_shadow(enabled):
    assert _decide(enabled=enabled) == {"run": False, "reason": "disabled"}


def test_disabled_short_circuits_invalid_policy_values():
    assert _decide(
        enabled=False,
        sample_every=0,
        available_budget_us="invalid",
        estimated_cost_us=0,
    )["reason"] == "disabled"


def test_already_sampled_prevents_duplicate_work_before_policy_validation():
    assert _decide(
        already_sampled=True,
        sample_every=0,
        available_budget_us="invalid",
        estimated_cost_us=0,
    ) == {"run": False, "reason": "already_sampled"}


@pytest.mark.parametrize("sample_key", ["", None, b"work-1"])
def test_missing_or_nontext_keys_are_not_sampled(sample_key):
    assert _decide(sample_key=sample_key) == {"run": False, "reason": "missing_key"}


@pytest.mark.parametrize("sample_every", [0, -1, True, 2.5])
def test_sample_interval_must_be_a_positive_integer(sample_every):
    with pytest.raises(ValueError, match="sample_every"):
        _decide(sample_every=sample_every)


@pytest.mark.parametrize("estimated_cost_us", [0, -1, True, 5327.5])
def test_estimated_cost_must_be_a_positive_integer(estimated_cost_us):
    with pytest.raises(ValueError, match="estimated_cost_us"):
        _decide(estimated_cost_us=estimated_cost_us)


@pytest.mark.parametrize("available_budget_us", [True, 6000.0, "6000"])
def test_available_budget_must_be_an_integer(available_budget_us):
    with pytest.raises(ValueError, match="available_budget_us"):
        _decide(available_budget_us=available_budget_us)


def test_budget_below_estimated_cost_skips_shadow():
    assert _decide(available_budget_us=5327) == {
        "run": False,
        "reason": "insufficient_budget",
    }


def test_exact_budget_is_eligible_for_explicit_every_call_sampling():
    assert _decide(available_budget_us=5328) == {"run": True, "reason": "selected"}


def test_sampling_uses_the_first_sha256_word_and_is_process_stable():
    key = "stable-work"
    every = 17
    expected = int.from_bytes(hashlib.sha256(key.encode("utf-8")).digest()[:8], "big") % every == 0

    first = _decide(sample_key=key, sample_every=every)
    second = _decide(sample_key=key, sample_every=every)

    assert first == second
    assert first == {
        "run": expected,
        "reason": "selected" if expected else "not_selected",
    }


def test_unicode_sample_keys_are_supported_without_appearing_in_the_report():
    private_marker = "作品-" + "测试-01"

    report = _decide(sample_key=private_marker, sample_every=3)

    assert tuple(report) == ("run", "reason")
    assert private_marker not in str(report)

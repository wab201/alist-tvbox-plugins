import pytest

from src.douban_tmdb_follow_single.resource_output_admission import (
    decide_resource_output_admission,
)


REQUIREMENTS = (
    ("development_build_verified", "development_build_unverified"),
    ("candidate_shadow_verified", "candidate_shadow_unverified"),
    ("layered_shadow_verified", "layered_shadow_unverified"),
    ("atvp_compatibility_verified", "atvp_compatibility_unverified"),
    ("dual_runtime_verified", "dual_runtime_unverified"),
    ("fongmi_category_verified", "fongmi_category_unverified"),
    ("public_v70_locked", "public_v70_unlocked"),
    ("public_output_untouched", "public_output_touched"),
)


def _decide(**overrides):
    values = {"enabled": True}
    values.update((name, True) for name, _ in REQUIREMENTS)
    values.update(overrides)
    return decide_resource_output_admission(**values)


@pytest.mark.parametrize("enabled", [False, None, 0, 1, "true"])
def test_only_literal_true_enables_output_admission(enabled):
    assert _decide(enabled=enabled) == {"admit": False, "reason": "disabled"}


def test_disabled_short_circuits_unverified_evidence():
    assert _decide(
        enabled=False,
        development_build_verified=False,
        public_v70_locked=False,
    ) == {"admit": False, "reason": "disabled"}


@pytest.mark.parametrize(
    "missing_index, expected_reason",
    [(index, reason) for index, (_, reason) in enumerate(REQUIREMENTS)],
)
def test_first_unverified_requirement_wins_in_fixed_order(missing_index, expected_reason):
    overrides = {
        name: index < missing_index
        for index, (name, _) in enumerate(REQUIREMENTS)
    }

    assert _decide(**overrides) == {"admit": False, "reason": expected_reason}


@pytest.mark.parametrize("name", [name for name, _ in REQUIREMENTS])
@pytest.mark.parametrize("value", [None, False, 0, 1, "true"])
def test_each_requirement_needs_literal_true(name, value):
    reason = dict(REQUIREMENTS)[name]

    assert _decide(**{name: value}) == {"admit": False, "reason": reason}


def test_all_verified_evidence_is_admitted_with_minimal_report_shape():
    result = _decide()

    assert result == {"admit": True, "reason": "admitted"}
    assert tuple(result) == ("admit", "reason")

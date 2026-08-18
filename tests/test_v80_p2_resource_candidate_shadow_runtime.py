import threading

from src.douban_tmdb_follow_single.resource_candidate_shadow_background import (
    RESOURCE_CANDIDATE_SHADOW_ESTIMATED_COST_US,
)
from src.douban_tmdb_follow_single.resource_candidate_shadow_runtime import (
    run_background_resource_candidate_shadow,
)


class _UnreadableRows:
    def __iter__(self):
        raise AssertionError("rows must not be consumed")


class _Owner:
    def __init__(self):
        self._cache_lock = threading.RLock()
        self._resource_candidate_shadow_lock = threading.Lock()
        self._cache_generation = 7
        self._resource_candidate_shadow_enabled = False
        self._resource_candidate_shadow_sample_every = 1
        self._resource_candidate_shadow_budget_us = 0
        self._resource_candidate_shadow_sampled_generation = None
        self._resource_candidate_shadow_last_report = None
        self.cache_lock_held_during_score = None

    @staticmethod
    def _merge_resource_rows(left, right, _item, _bound):
        merged = dict(left)
        for key, value in right.items():
            if merged.get(key) in (None, "", [], ()):
                merged[key] = value
        return merged

    def _resource_score(self, row, _item, _bound):
        acquired = self._cache_lock.acquire(blocking=False)
        self.cache_lock_held_during_score = not acquired
        if acquired:
            self._cache_lock.release()
        return row.get("score", 0)

    @staticmethod
    def _resource_row_preference(row, _item, _bound):
        return tuple(row.get("preference") or ())

    @staticmethod
    def _resource_provider_key(*values):
        return next((str(value) for value in values if value), "")


def _run(owner, legacy_rows, rows, generation=7):
    return run_background_resource_candidate_shadow(
        owner,
        legacy_rows,
        rows,
        item={"title": "Example", "year": "2026"},
        cache_key="resource-search:" + "a" * 64,
        generation=generation,
        modes=("pansou", "telegram"),
    )


def _rows():
    return [
        {
            "vod_id": "resource-a",
            "_resource_mode": "pansou",
            "provider": "quark",
            "score": 10,
            "preference": (2, 1),
        },
        {
            "vod_id": "resource-b",
            "_resource_mode": "telegram",
            "provider": "baidu",
            "score": 9,
            "preference": (1, 2),
        },
    ]


def test_runtime_defaults_short_circuit_without_consuming_rows():
    owner = _Owner()

    result = _run(owner, _UnreadableRows(), _UnreadableRows())

    assert result == {
        "decision": {"run": False, "reason": "disabled"},
        "report": None,
    }
    assert owner._resource_candidate_shadow_sampled_generation is None
    assert owner._resource_candidate_shadow_last_report is None


def test_runtime_records_one_redacted_report_for_the_active_generation():
    owner = _Owner()
    owner._resource_candidate_shadow_enabled = True
    owner._resource_candidate_shadow_budget_us = (
        RESOURCE_CANDIDATE_SHADOW_ESTIMATED_COST_US
    )
    rows = _rows()

    result = _run(owner, list(rows), rows)

    assert result["decision"] == {"run": True, "reason": "selected"}
    assert result["report"] == {
        "status": "equal",
        "legacy_count": 2,
        "candidate_count": 2,
        "first_difference": -1,
        "error_type": "",
    }
    assert owner._resource_candidate_shadow_sampled_generation == 7
    assert owner._resource_candidate_shadow_last_report == result["report"]
    assert "resource-a" not in str(result)
    assert owner.cache_lock_held_during_score is False


def test_runtime_prevents_duplicate_work_in_one_generation():
    owner = _Owner()
    owner._resource_candidate_shadow_enabled = True
    owner._resource_candidate_shadow_budget_us = (
        RESOURCE_CANDIDATE_SHADOW_ESTIMATED_COST_US
    )
    rows = _rows()
    _run(owner, list(rows), rows)

    result = _run(owner, _UnreadableRows(), _UnreadableRows())

    assert result == {
        "decision": {"run": False, "reason": "already_sampled"},
        "report": None,
    }


def test_runtime_does_not_read_foreground_or_search_budgets():
    owner = _Owner()
    owner._resource_candidate_shadow_enabled = True
    owner._resource_candidate_shadow_budget_us = (
        RESOURCE_CANDIDATE_SHADOW_ESTIMATED_COST_US - 1
    )

    result = _run(owner, _UnreadableRows(), _UnreadableRows())

    assert result == {
        "decision": {"run": False, "reason": "insufficient_budget"},
        "report": None,
    }


def test_runtime_skips_a_generation_that_is_already_stale():
    owner = _Owner()

    assert _run(owner, _UnreadableRows(), _UnreadableRows(), generation=6) is None
    assert owner._resource_candidate_shadow_sampled_generation is None


def test_runtime_does_not_write_after_generation_changes_during_comparison():
    owner = _Owner()
    owner._resource_candidate_shadow_enabled = True
    owner._resource_candidate_shadow_budget_us = (
        RESOURCE_CANDIDATE_SHADOW_ESTIMATED_COST_US
    )
    original_score = owner._resource_score

    def change_generation(row, item, bound):
        result = original_score(row, item, bound)
        owner._cache_generation += 1
        return result

    owner._resource_score = change_generation
    rows = _rows()

    result = _run(owner, list(rows), rows)

    assert result["decision"] == {"run": True, "reason": "selected"}
    assert owner._resource_candidate_shadow_sampled_generation is None
    assert owner._resource_candidate_shadow_last_report is None

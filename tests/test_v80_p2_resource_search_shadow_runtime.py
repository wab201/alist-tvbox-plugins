import threading

from src.douban_tmdb_follow_single import resource_search_shadow_runtime as RUNTIME


class _Owner:
    def __init__(self):
        self._resource_search_layered_shadow_lock = threading.Lock()
        self._cache_lock = threading.Lock()
        self._cache_generation = 3
        self._resource_search_layered_shadow_enabled = False
        self._resource_search_layered_shadow_sample_every = 1
        self._resource_search_layered_shadow_budget_us = 0
        self._resource_search_layered_shadow_sampled_generation = None
        self._resource_search_layered_shadow_last_report = None


def _rows():
    return [
        {"vod_id": "cached", "vod_name": "Cached", "_resource_mode": "vod"},
        {"vod_id": "recent", "vod_name": "Recent", "_resource_mode": "vod"},
        {"vod_id": "bound", "vod_name": "Bound", "_resource_mode": "vod1"},
        {"vod_id": "provider", "vod_name": "Provider", "_resource_mode": "vod"},
    ]


def _run(owner):
    return RUNTIME.run_resource_search_layered_shadow(
        owner,
        _rows(),
        cache_key="resource-search:layered",
        cached_rows=[{"vod_id": "cached", "_resource_mode": "vod"}],
        recent_resource_id="recent",
        binding_resource_id="bound",
        available_modes=("vod1", "vod"),
    )


def test_layered_report_is_ordered_and_redacted():
    report = RUNTIME.build_resource_search_layered_shadow_report(
        _rows(),
        cached_rows=[{"vod_id": "cached", "_resource_mode": "vod"}],
        recent_resource_id="recent",
        binding_resource_id="bound",
        available_modes=("vod1", "vod"),
    )

    assert report == {
        "status": "observed",
        "input_count": 4,
        "candidate_count": 4,
        "batch_count": 5,
        "layers": (
            {"layer": "cache", "mode": "", "candidate_count": 1},
            {"layer": "recent_success", "mode": "", "candidate_count": 1},
            {"layer": "binding", "mode": "", "candidate_count": 1},
            {"layer": "fast_provider", "mode": "vod1", "candidate_count": 0},
            {"layer": "fast_provider", "mode": "vod", "candidate_count": 1},
        ),
        "error_type": "",
    }
    rendered = repr(report)
    assert not any("'%s'" % value in rendered for value in (
        "cached", "recent", "bound", "provider",
    ))


def test_runtime_short_circuits_before_report_when_disabled(monkeypatch):
    owner = _Owner()
    monkeypatch.setattr(
        RUNTIME, "build_resource_search_layered_shadow_report",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not run")),
    )

    assert _run(owner) == {"decision": {"run": False, "reason": "disabled"}, "report": None}


def test_runtime_uses_an_independent_budget(monkeypatch):
    owner = _Owner()
    owner._resource_search_layered_shadow_enabled = True
    monkeypatch.setattr(
        RUNTIME, "build_resource_search_layered_shadow_report",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not run")),
    )

    assert _run(owner) == {
        "decision": {"run": False, "reason": "insufficient_budget"},
        "report": None,
    }


def test_runtime_records_at_most_once_per_generation():
    owner = _Owner()
    owner._resource_search_layered_shadow_enabled = True
    owner._resource_search_layered_shadow_budget_us = (
        RUNTIME.RESOURCE_SEARCH_LAYERED_SHADOW_ESTIMATED_COST_US
    )

    first = _run(owner)
    second = _run(owner)

    assert first["decision"] == {"run": True, "reason": "selected"}
    assert first["report"]["status"] == "observed"
    assert second == {
        "decision": {"run": False, "reason": "already_sampled"},
        "report": None,
    }
    assert owner._resource_search_layered_shadow_sampled_generation == 3
    assert owner._resource_search_layered_shadow_last_report == first["report"]


def test_runtime_discards_a_stale_generation(monkeypatch):
    owner = _Owner()
    owner._resource_search_layered_shadow_enabled = True
    owner._resource_search_layered_shadow_budget_us = (
        RUNTIME.RESOURCE_SEARCH_LAYERED_SHADOW_ESTIMATED_COST_US
    )
    original = RUNTIME.build_resource_search_layered_shadow_report

    def change_generation(*args, **kwargs):
        report = original(*args, **kwargs)
        owner._cache_generation += 1
        return report

    monkeypatch.setattr(RUNTIME, "build_resource_search_layered_shadow_report", change_generation)

    result = _run(owner)

    assert result["report"]["status"] == "observed"
    assert owner._resource_search_layered_shadow_sampled_generation is None
    assert owner._resource_search_layered_shadow_last_report is None


def test_runtime_redacts_report_errors(monkeypatch):
    owner = _Owner()
    owner._resource_search_layered_shadow_enabled = True
    owner._resource_search_layered_shadow_budget_us = (
        RUNTIME.RESOURCE_SEARCH_LAYERED_SHADOW_ESTIMATED_COST_US
    )
    monkeypatch.setattr(
        RUNTIME, "build_resource_search_layered_shadow_report",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(KeyError("private-resource-id")),
    )

    result = _run(owner)

    assert result["report"]["status"] == "error"
    assert result["report"]["error_type"] == "KeyError"
    assert "private-resource-id" not in repr(result)

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from src.douban_tmdb_follow_single.background_bulkhead_contract import (
    BACKGROUND_BULKHEAD_LIMITS,
    BackgroundBulkheadController,
)


def test_fixed_background_lanes_and_limits():
    assert BACKGROUND_BULKHEAD_LIMITS == {
        "resource_completion": 10,
        "history": 1,
        "route_probe": 5,
    }
    assert BackgroundBulkheadController().snapshot() == {
        "generation": 0,
        "limits": BACKGROUND_BULKHEAD_LIMITS,
        "inflight": {
            "resource_completion": 0,
            "history": 0,
            "route_probe": 0,
        },
        "rejected": {
            "resource_completion": 0,
            "history": 0,
            "route_probe": 0,
        },
    }


@pytest.mark.parametrize(
    "limits",
    (
        {"history": 1},
        {
            "resource_completion": 9,
            "history": 1,
            "route_probe": 5,
        },
        {
            "resource_completion": 10,
            "history": 2,
            "route_probe": 5,
        },
        {
            "resource_completion": 10,
            "history": 1,
            "route_probe": 0,
        },
        {
            "resource_completion": 10,
            "history": "bad",
            "route_probe": 5,
        },
    ),
)
def test_contract_rejects_all_lane_limit_overrides(limits):
    with pytest.raises(TypeError):
        BackgroundBulkheadController(limits=limits)


def test_unknown_lane_is_rejected_as_a_programming_error():
    controller = BackgroundBulkheadController()
    with pytest.raises(ValueError, match="unknown"):
        controller.acquire("shared", 0)


def test_lanes_have_independent_capacity_and_rejection_counts():
    controller = BackgroundBulkheadController()
    history = controller.acquire("history", 0)
    routes = [controller.acquire("route_probe", 0) for _ in range(5)]

    assert history is not None
    assert all(lease is not None for lease in routes)
    assert controller.acquire("history", 0) is None
    assert controller.acquire("route_probe", 0) is None
    resource = controller.acquire("resource_completion", 0)
    assert resource is not None
    assert controller.snapshot()["rejected"] == {
        "resource_completion": 0,
        "history": 1,
        "route_probe": 1,
    }

    assert history.finish() is True
    assert resource.finish() is True
    assert all(lease.finish() is True for lease in routes)


def test_lease_releases_exactly_once():
    controller = BackgroundBulkheadController()
    lease = controller.acquire("history", 0)

    assert lease.finish() is True
    assert lease.finish() is False
    assert controller.snapshot()["inflight"]["history"] == 0


def test_generation_mismatch_never_consumes_capacity():
    controller = BackgroundBulkheadController(generation=4)

    assert controller.acquire("history", 3) is None
    assert controller.snapshot()["inflight"]["history"] == 0
    assert controller.snapshot()["rejected"]["history"] == 0


def test_reset_invalidates_old_leases_without_releasing_new_generation():
    controller = BackgroundBulkheadController(generation=1)
    old = controller.acquire("history", 1)
    controller.reset(2)
    current = controller.acquire("history", 2)

    assert old.finish() is False
    assert controller.snapshot()["inflight"]["history"] == 1
    assert current.finish() is True
    assert controller.snapshot()["inflight"]["history"] == 0


def test_concurrent_acquire_never_oversubscribes_lane():
    controller = BackgroundBulkheadController()
    start = threading.Barrier(21)
    attempted = threading.Barrier(21)
    release = threading.Event()
    results = []
    results_lock = threading.Lock()

    def worker():
        start.wait()
        lease = controller.acquire("route_probe", 0)
        with results_lock:
            results.append(lease)
        attempted.wait()
        if lease is not None:
            release.wait(2.0)
            lease.finish()

    with ThreadPoolExecutor(max_workers=20) as executor:
        futures = [executor.submit(worker) for _ in range(20)]
        start.wait()
        attempted.wait()
        with results_lock:
            assert sum(lease is not None for lease in results) == 5
        assert controller.snapshot()["inflight"]["route_probe"] == 5
        assert controller.snapshot()["rejected"]["route_probe"] == 15
        release.set()
        for future in futures:
            future.result(timeout=2.0)

    assert controller.snapshot()["inflight"]["route_probe"] == 0

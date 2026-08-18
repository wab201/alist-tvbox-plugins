import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from src.douban_tmdb_follow_single.reliability_contract import ReliabilityFailure
from src.douban_tmdb_follow_single.timeout_budget_contract import (
    GENERAL_TRANSPORT_RETRY_POLICY,
    TimeoutBudgetController,
    v80_timeout_general_retry_adapter,
)


class Clock(object):
    def __init__(self, value=100.0):
        self.value = float(value)
        self._lock = threading.Lock()

    def __call__(self):
        with self._lock:
            return self.value

    def set(self, value):
        with self._lock:
            self.value = float(value)


class CloseCounter(object):
    def __init__(self):
        self.calls = 0
        self._lock = threading.Lock()

    def close(self):
        with self._lock:
            self.calls += 1


def failure_kind(exc_info):
    return exc_info.value.kind


def test_child_scope_cannot_extend_parent_deadline():
    clock = Clock()
    controller = TimeoutBudgetController(generation=3, clock=clock)

    with controller.scope("parent", 10, expected_generation=3) as parent:
        clock.set(101)
        with controller.scope("child", 60, expected_generation=3) as child:
            assert parent.deadline == 110
            assert child.deadline == parent.deadline

    assert controller.snapshot()["active"] == 0


def test_expired_entry_leaves_no_active_registration():
    clock = Clock()
    controller = TimeoutBudgetController(clock=clock)
    operation = controller.scope("expired", 1, deadline=99)

    with pytest.raises(ReliabilityFailure) as exc_info:
        operation.__enter__()

    assert failure_kind(exc_info) == "budget_exhausted"
    assert controller.snapshot()["active"] == 0
    assert controller.current(required=False) is None


@pytest.mark.parametrize("value", ("bad", object(), float("inf")))
def test_invalid_expected_generation_is_a_structured_configuration_failure(value):
    controller = TimeoutBudgetController()

    with pytest.raises(ReliabilityFailure) as exc_info:
        controller.scope("invalid", 1, expected_generation=value)

    assert failure_kind(exc_info) == "configuration"


def test_request_timeout_uses_remaining_absolute_budget():
    clock = Clock()
    controller = TimeoutBudgetController(clock=clock)

    with controller.scope("request", 10) as operation:
        clock.set(104)
        assert operation.request_timeout(20) == pytest.approx(1.0)


def test_general_retry_phases_remain_inside_original_deadline():
    clock = Clock()
    controller = TimeoutBudgetController(clock=clock)

    with controller.scope("retry", 9) as operation:
        timeout = operation.request_timeout(
            20, requests_left=2, retry_policy=GENERAL_TRANSPORT_RETRY_POLICY,
        )

    phases = GENERAL_TRANSPORT_RETRY_POLICY.request_phases(2)
    backoff = GENERAL_TRANSPORT_RETRY_POLICY.backoff_budget(2)
    assert timeout * phases + backoff <= 9


def test_general_retry_adapter_uses_the_budgeted_policy():
    adapter = v80_timeout_general_retry_adapter()
    retry = adapter.max_retries

    assert retry.total == GENERAL_TRANSPORT_RETRY_POLICY.total
    assert retry.connect == GENERAL_TRANSPORT_RETRY_POLICY.connect
    assert retry.read == GENERAL_TRANSPORT_RETRY_POLICY.read
    assert retry.status == GENERAL_TRANSPORT_RETRY_POLICY.status
    assert adapter._pool_connections == GENERAL_TRANSPORT_RETRY_POLICY.pool_connections
    assert adapter._pool_maxsize == GENERAL_TRANSPORT_RETRY_POLICY.pool_maxsize


def test_reset_cancels_active_scope_and_rejects_next_phase():
    controller = TimeoutBudgetController(generation=1)

    with pytest.raises(ReliabilityFailure) as exc_info:
        with controller.scope("old", 10, expected_generation=1) as operation:
            assert controller.reset(2) == 1
            operation.checkpoint()

    assert failure_kind(exc_info) == "cancelled"
    assert controller.snapshot() == {"generation": 2, "closed": False, "active": 0}


def test_closed_controller_rejects_new_scope_and_reopens_on_new_generation():
    controller = TimeoutBudgetController(generation=1)
    controller.reset(2, closed=True)

    with pytest.raises(ReliabilityFailure) as exc_info:
        with controller.scope("closed", 10, expected_generation=2):
            pytest.fail("closed controller must reject entry")
    assert failure_kind(exc_info) == "cancelled"

    controller.reset(3, closed=False)
    with controller.scope("open", 10, expected_generation=3):
        assert controller.snapshot()["active"] == 1


def test_cancellation_closes_tracked_resource_exactly_once():
    controller = TimeoutBudgetController(generation=1)
    resource = CloseCounter()

    with pytest.raises(ReliabilityFailure) as exc_info:
        with controller.scope("stream", 10, expected_generation=1) as operation:
            assert operation.track(resource) is resource
            controller.reset(2)
            operation.checkpoint()

    assert failure_kind(exc_info) == "cancelled"
    assert resource.calls == 1


def test_close_tracked_does_not_close_again_after_cancellation():
    controller = TimeoutBudgetController(generation=1)
    resource = CloseCounter()
    operation = controller.scope("stream", 10, expected_generation=1)
    operation.__enter__()
    operation.track(resource)

    controller.reset(2)

    assert operation.close_tracked(resource) is False
    operation.__exit__(None, None, None)
    assert resource.calls == 1


def test_old_scope_cannot_affect_new_generation_resource():
    controller = TimeoutBudgetController(generation=1)
    old_resource = CloseCounter()
    new_resource = CloseCounter()

    old = controller.scope("old", 10, expected_generation=1)
    old.__enter__()
    old.track(old_resource)
    controller.reset(2)

    with controller.scope("new", 10, expected_generation=2) as current:
        current.track(new_resource)
        old.cancel()
        assert new_resource.calls == 0
        current.untrack(new_resource)

    old.__exit__(None, None, None)
    assert old_resource.calls == 1
    assert new_resource.calls == 0


def test_thread_local_scope_stacks_are_isolated():
    controller = TimeoutBudgetController(generation=1)
    barrier = threading.Barrier(3)

    def worker(label):
        with controller.scope(label, 10, expected_generation=1) as operation:
            barrier.wait()
            current = controller.current()
            barrier.wait()
            return current is operation, current.operation

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(worker, label) for label in ("one", "two")]
        barrier.wait()
        assert controller.current(required=False) is None
        assert controller.snapshot()["active"] == 2
        barrier.wait()
        results = [future.result(timeout=2) for future in futures]

    assert sorted(results) == [(True, "one"), (True, "two")]
    assert controller.snapshot()["active"] == 0

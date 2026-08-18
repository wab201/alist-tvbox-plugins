import importlib.util
import json
import socket
import ssl
import threading
from concurrent.futures import CancelledError
from pathlib import Path

import pytest
import requests


ROOT = Path(__file__).resolve().parent.parent
CONTRACT_PATH = ROOT / "src" / "douban_tmdb_follow_single" / "reliability_contract.py"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CONTRACT = _load("v80_p3_reliability_contract", CONTRACT_PATH)


def test_failure_kinds_are_stable_and_complete():
    assert CONTRACT.FAILURE_KINDS == frozenset((
        "cancelled", "budget_exhausted", "timeout", "dns", "tls",
        "transport", "auth", "rate_limit", "server", "client",
        "unsupported", "payload", "configuration", "runtime",
        "circuit_open", "bulkhead_rejected",
    ))


def test_structured_failure_keeps_only_redacted_stable_fields():
    failure = CONTRACT.ReliabilityFailure(
        "auth", status=401,
        operation="https://example.invalid/path?" + "to" + "ken=private",
    )

    assert failure.kind == "auth"
    assert failure.status == 401
    assert failure.operation == "operation"
    assert "private" not in str(failure)
    assert "example.invalid" not in str(failure)
    assert not hasattr(failure, "original")


@pytest.mark.parametrize("kind", sorted(CONTRACT.FAILURE_KINDS - {"unsupported"}))
def test_structured_failure_accepts_each_non_capability_kind(kind):
    failure = CONTRACT.ReliabilityFailure(kind, operation="test_operation")
    assert (failure.kind, failure.operation) == (kind, "test_operation")


def test_unknown_failure_kind_is_rejected():
    with pytest.raises(ValueError, match="unknown reliability failure kind"):
        CONTRACT.ReliabilityFailure("other")


@pytest.mark.parametrize("status,explicit", ((404, False), (405, False), (501, False), (400, True), (500, True)))
def test_unsupported_requires_explicit_allowed_http_status(status, explicit):
    with pytest.raises(ValueError, match="unsupported requires"):
        CONTRACT.ReliabilityFailure(
            "unsupported", status=status, explicit_unsupported=explicit,
        )


@pytest.mark.parametrize("status", (404, 405, 501))
def test_explicit_capability_status_can_create_unsupported(status):
    failure = CONTRACT.ReliabilityFailure(
        "unsupported", status=status, operation="resource_api_get",
        explicit_unsupported=True,
    )
    assert (failure.kind, failure.status) == ("unsupported", status)


@pytest.mark.parametrize("status,expected", (
    (200, "runtime"),
    (400, "client"),
    (401, "auth"),
    (403, "auth"),
    (404, "client"),
    (408, "client"),
    (429, "rate_limit"),
    (500, "server"),
    (501, "server"),
    (504, "server"),
))
def test_http_status_classification_without_capability_mark(status, expected):
    assert CONTRACT.v80_reliability_classify(status=status) == expected


@pytest.mark.parametrize("status", (404, 405, 501))
def test_unsupported_is_only_returned_for_explicit_capability_status(status):
    assert CONTRACT.v80_reliability_classify(
        status=status, explicit_unsupported=True,
    ) == "unsupported"


def test_structured_failure_has_priority_over_outer_transport_and_status():
    structured = CONTRACT.ReliabilityFailure(
        "configuration", operation="resource_configuration",
    )
    outer = requests.ConnectionError(structured)
    response = requests.Response()
    response.status_code = 503
    outer.response = response

    assert CONTRACT.v80_reliability_classify(outer) == "configuration"


def test_explicit_status_has_priority_over_exception_type():
    assert CONTRACT.v80_reliability_classify(
        requests.Timeout(), status=401,
    ) == "auth"


def test_http_error_uses_structured_response_status():
    response = requests.Response()
    response.status_code = 429
    error = requests.HTTPError(response=response)
    assert CONTRACT.v80_reliability_classify(error) == "rate_limit"


def test_dns_is_found_in_connection_error_cause():
    try:
        try:
            raise socket.gaierror(socket.EAI_NONAME, "private hostname")
        except socket.gaierror as cause:
            raise requests.ConnectionError("redacted transport") from cause
    except requests.ConnectionError as error:
        assert CONTRACT.v80_reliability_classify(error) == "dns"


@pytest.mark.parametrize("error,expected", (
    (requests.Timeout(), "timeout"),
    (socket.timeout(), "timeout"),
    (requests.exceptions.SSLError(), "tls"),
    (ssl.SSLError(), "tls"),
    (requests.ConnectionError(), "transport"),
    (requests.exceptions.ChunkedEncodingError(), "transport"),
    (requests.exceptions.InvalidURL(), "configuration"),
    (requests.exceptions.MissingSchema(), "configuration"),
    (json.JSONDecodeError("bad", "x", 0), "payload"),
    (CancelledError(), "cancelled"),
    (RuntimeError("opaque"), "runtime"),
))
def test_exception_classification_matrix(error, expected):
    assert CONTRACT.v80_reliability_classify(error) == expected


@pytest.mark.parametrize("status,explicit,expected", (
    (404, False, "client"),
    (404, True, "unsupported"),
    (405, True, "unsupported"),
    (500, True, "server"),
    (501, False, "server"),
    (501, True, "unsupported"),
))
def test_http_failure_factory_applies_explicit_unsupported_rule(status, explicit, expected):
    failure = CONTRACT.v80_reliability_http_failure(
        status, "resource_api_get", explicit_unsupported=explicit,
    )
    assert (failure.kind, failure.status, failure.operation) == (
        expected, status, "resource_api_get",
    )


def test_payload_failure_factory_has_no_sensitive_cause():
    failure = CONTRACT.v80_reliability_payload_failure("resource_api_get")
    assert (failure.kind, failure.status, failure.operation) == (
        "payload", None, "resource_api_get",
    )
    assert failure.__cause__ is None


def test_atvp_transport_retry_policy_matches_existing_get_contract():
    policy = CONTRACT.ATVP_TRANSPORT_RETRY_POLICY

    assert policy.total == 2
    assert policy.connect == 2
    assert policy.read == 2
    assert policy.status == 0
    assert policy.other == 0
    assert policy.backoff_factor == pytest.approx(0.4)
    assert policy.backoff_max == pytest.approx(120.0)
    assert policy.allowed_methods == frozenset(("GET",))
    assert policy.request_phases() == 6
    assert policy.request_phases(2) == 12
    assert policy.backoff_budget() == pytest.approx(0.8)
    assert policy.backoff_budget(2) == pytest.approx(1.6)


def test_atvp_retry_adapter_does_not_retry_http_or_other_failures():
    policy = CONTRACT.ATVP_TRANSPORT_RETRY_POLICY
    adapter = CONTRACT.v80_reliability_atvp_retry_adapter()
    retry = adapter.max_retries

    assert retry.total == policy.total
    assert retry.connect == policy.connect
    assert retry.read == policy.read
    assert retry.status == policy.status
    assert retry.other == policy.other
    assert retry.backoff_factor == pytest.approx(policy.backoff_factor)
    assert set(retry.allowed_methods) == set(policy.allowed_methods)
    assert retry.respect_retry_after_header is False
    assert retry.raise_on_status is False
    assert retry.is_retry("GET", 429, has_retry_after=True) is False
    assert retry.is_retry("GET", 503, has_retry_after=True) is False
    assert adapter._pool_connections == policy.pool_connections
    assert adapter._pool_maxsize == policy.pool_maxsize


def test_atvp_retry_adapter_legacy_signature_preserves_transport_retry(monkeypatch):
    class LegacyRetry(object):
        def __init__(
                self, total, connect, read, status, backoff_factor,
                method_whitelist=None):
            self.total = total
            self.connect = connect
            self.read = read
            self.status = status
            self.backoff_factor = backoff_factor
            self.method_whitelist = method_whitelist

    class Adapter(object):
        def __init__(self, **kwargs):
            self.max_retries = kwargs["max_retries"]
            self.pool_connections = kwargs["pool_connections"]
            self.pool_maxsize = kwargs["pool_maxsize"]

    retry_module = CONTRACT.requests.packages.urllib3.util.retry
    monkeypatch.setattr(retry_module, "Retry", LegacyRetry)
    monkeypatch.setattr(CONTRACT.requests.adapters, "HTTPAdapter", Adapter)

    adapter = CONTRACT.v80_reliability_atvp_retry_adapter()
    retry = adapter.max_retries

    assert retry.total == 2
    assert retry.connect == 2
    assert retry.read == 2
    assert retry.status == 0
    assert retry.backoff_factor == pytest.approx(0.4)
    assert retry.method_whitelist == frozenset(("GET",))
    assert adapter.pool_connections == 4
    assert adapter.pool_maxsize == 4


def test_timeout_budget_remaining_uses_absolute_deadline_and_clamps_zero():
    clock_values = iter((95.5, 101.0))
    budget = CONTRACT.TimeoutBudget(100.0, clock=lambda: next(clock_values))

    assert budget.deadline == 100.0
    assert budget.remaining() == 4.5
    assert budget.remaining() == 0.0


def test_timeout_budget_without_deadline_matches_legacy_integer_allocation():
    budget = CONTRACT.TimeoutBudget(None, clock=lambda: pytest.fail("clock must not run"))
    assert budget.remaining() == float("inf")
    assert budget.request_timeout(5.9, requests_left=99) == 5
    assert budget.request_timeout(0.2) == 1


@pytest.mark.parametrize("remaining,default_timeout,requests_left,expected", (
    (60.0, 12, 1, 10.0),
    (60.0, 12, 2, 5.0),
    (60.0, 4, 1, 4.0),
    (7.0, 12, 1, 7.0 / 6.0),
    (6.0, 12, 1, 1.0),
    (1.0, 12, 1, 1.0 / 6.0),
))
def test_timeout_budget_request_allocation(
        remaining, default_timeout, requests_left, expected):
    budget = CONTRACT.TimeoutBudget(100.0, clock=lambda: 100.0 - remaining)
    assert budget.request_timeout(default_timeout, requests_left) == pytest.approx(expected)


@pytest.mark.parametrize("remaining", (0.0, 0.25, 0.999999))
def test_timeout_budget_fails_before_request_when_less_than_one_second(remaining):
    budget = CONTRACT.TimeoutBudget(100.0, clock=lambda: 100.0 - remaining)
    with pytest.raises(CONTRACT.ReliabilityFailure) as raised:
        budget.request_timeout(12, requests_left=1)
    assert raised.value.kind == "budget_exhausted"
    assert raised.value.status is None


@pytest.mark.parametrize("deadline,default_timeout,requests_left,now", (
    (None, 5.9, 1, 10.0),
    (100.0, 12, 1, 40.0),
    (100.0, 12, 2, 40.0),
    (100.0, 4, 1, 93.0),
))
def test_request_timeout_is_equal_to_v70_legacy_formula(
        deadline, default_timeout, requests_left, now):
    def legacy():
        if deadline is None:
            return max(1, int(default_timeout))
        remaining = deadline - now
        if remaining < 1:
            raise RuntimeError("budget exhausted")
        retry_phases = int(requests_left) * 6
        return max(1, min(float(default_timeout), remaining / retry_phases))

    assert CONTRACT.v80_reliability_request_timeout(
        deadline, default_timeout, requests_left=requests_left, clock=lambda: now,
    ) == legacy()


def test_request_timeout_never_extends_parent_deadline():
    calls = []
    budget = CONTRACT.TimeoutBudget(50.0, clock=lambda: calls.append(49.0) or 49.0)
    assert budget.request_timeout(99, requests_left=1) == pytest.approx(1.0 / 6.0)
    assert budget.deadline == 50.0
    assert calls == [49.0]


@pytest.mark.parametrize("remaining", (1.0, 1.1, 5.9))
def test_request_timeout_phase_allocation_cannot_exceed_parent_budget(remaining):
    budget = CONTRACT.TimeoutBudget(100.0, clock=lambda: 100.0 - remaining)
    timeout = budget.request_timeout(99, requests_left=1)
    assert timeout * 6 == pytest.approx(remaining)


@pytest.mark.parametrize("remaining,requests_left", (
    (1.0, 1),
    (6.0, 1),
    (60.0, 1),
    (60.0, 2),
))
def test_provider_timeout_reserves_retry_backoff_before_io_phases(
        remaining, requests_left):
    policy = CONTRACT.ATVP_TRANSPORT_RETRY_POLICY
    budget = CONTRACT.TimeoutBudget(100.0, clock=lambda: 100.0 - remaining)

    timeout = budget.request_timeout(
        99, requests_left=requests_left, retry_policy=policy,
    )

    assert (
        timeout * policy.request_phases(requests_left)
        + policy.backoff_budget(requests_left)
    ) == pytest.approx(remaining)


def test_provider_timeout_rejects_budget_smaller_than_retry_reserve():
    budget = CONTRACT.TimeoutBudget(100.0, clock=lambda: 99.0)

    with pytest.raises(CONTRACT.ReliabilityFailure) as raised:
        budget.request_timeout(
            12,
            requests_left=2,
            retry_policy=CONTRACT.ATVP_TRANSPORT_RETRY_POLICY,
        )

    assert raised.value.kind == "budget_exhausted"


class _Clock(object):
    def __init__(self, value=0.0):
        self.value = float(value)

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += float(seconds)


def _provider_failure(controller, backend="backend-a", mode="vod", kind="timeout"):
    lease = controller.acquire(backend, mode)
    assert lease.finish(failure_kind=kind) is True
    assert lease.finish(failure_kind=kind) is False


def test_provider_circuit_opens_after_three_transient_failures():
    controller = CONTRACT.ProviderReliabilityController(clock=_Clock())

    for _ in range(3):
        _provider_failure(controller)

    snapshot = controller.snapshot("backend-a", "vod")
    assert snapshot["state"] == "open"
    assert snapshot["consecutive_transient_failures"] == 3
    with pytest.raises(CONTRACT.ReliabilityFailure) as raised:
        controller.acquire("backend-a", "vod")
    assert raised.value.kind == "circuit_open"


def test_provider_half_open_allows_one_probe_and_success_closes():
    clock = _Clock()
    controller = CONTRACT.ProviderReliabilityController(clock=clock)
    for _ in range(3):
        _provider_failure(controller)

    clock.advance(30)
    probe = controller.acquire("backend-a", "vod")
    assert controller.snapshot("backend-a", "vod")["state"] == "half_open"
    with pytest.raises(CONTRACT.ReliabilityFailure) as raised:
        controller.acquire("backend-a", "vod")
    assert raised.value.kind == "circuit_open"

    probe.finish(success=True)
    snapshot = controller.snapshot("backend-a", "vod")
    assert snapshot["state"] == "closed"
    assert snapshot["consecutive_transient_failures"] == 0


def test_provider_half_open_transient_failure_reopens_window():
    clock = _Clock()
    controller = CONTRACT.ProviderReliabilityController(clock=clock)
    for _ in range(3):
        _provider_failure(controller)

    clock.advance(30)
    controller.acquire("backend-a", "vod").finish(failure_kind="server")
    assert controller.snapshot("backend-a", "vod")["state"] == "open"
    with pytest.raises(CONTRACT.ReliabilityFailure) as raised:
        controller.acquire("backend-a", "vod")
    assert raised.value.kind == "circuit_open"


def test_late_pre_open_success_does_not_close_open_circuit():
    clock = _Clock()
    controller = CONTRACT.ProviderReliabilityController(clock=clock, capacity=2)
    late = controller.acquire("backend-a", "vod")
    for _ in range(3):
        _provider_failure(controller)

    late.finish(success=True)
    assert controller.snapshot("backend-a", "vod")["state"] == "open"
    with pytest.raises(CONTRACT.ReliabilityFailure) as raised:
        controller.acquire("backend-a", "vod")
    assert raised.value.kind == "circuit_open"


def test_only_designated_half_open_probe_can_change_circuit_state():
    clock = _Clock()
    controller = CONTRACT.ProviderReliabilityController(clock=clock, capacity=2)
    late = controller.acquire("backend-a", "vod")
    for _ in range(3):
        _provider_failure(controller)

    clock.advance(30)
    probe = controller.acquire("backend-a", "vod")
    late.finish(success=True)
    snapshot = controller.snapshot("backend-a", "vod")
    assert snapshot["state"] == "half_open"
    with pytest.raises(CONTRACT.ReliabilityFailure) as raised:
        controller.acquire("backend-a", "vod")
    assert raised.value.kind == "circuit_open"

    probe.finish(failure_kind="timeout")
    assert controller.snapshot("backend-a", "vod")["state"] == "open"


@pytest.mark.parametrize("kind", (
    "auth", "unsupported", "client", "configuration", "payload", "cancelled",
))
def test_provider_non_transient_failures_never_trip_circuit(kind):
    controller = CONTRACT.ProviderReliabilityController(clock=_Clock())
    for _ in range(5):
        _provider_failure(controller, kind=kind)

    snapshot = controller.snapshot("backend-a", "vod")
    assert snapshot["state"] == "closed"
    assert snapshot["transient_failures"] == 0
    assert snapshot["non_transient_failures"] == 5


def test_provider_bulkhead_isolated_by_backend_and_mode_and_releases_capacity():
    controller = CONTRACT.ProviderReliabilityController(clock=_Clock(), capacity=2)
    first = controller.acquire("backend-a", "vod")
    second = controller.acquire("backend-a", "vod")

    with pytest.raises(CONTRACT.ReliabilityFailure) as raised:
        controller.acquire("backend-a", "vod")
    assert raised.value.kind == "bulkhead_rejected"
    isolated_mode = controller.acquire("backend-a", "vod1")
    isolated_backend = controller.acquire("backend-b", "vod")

    first.finish(success=True)
    replacement = controller.acquire("backend-a", "vod")
    for lease in (second, isolated_mode, isolated_backend, replacement):
        lease.finish(success=True)
    assert controller.snapshot("backend-a", "vod")["in_flight"] == 0


def test_provider_lease_finish_is_atomic_under_concurrent_completion():
    controller = CONTRACT.ProviderReliabilityController(clock=_Clock(), capacity=2)
    first = controller.acquire("backend-a", "vod")
    second = controller.acquire("backend-a", "vod")
    barrier = threading.Barrier(3)
    results = []

    def finish():
        barrier.wait()
        results.append(first.finish(success=True))

    threads = [threading.Thread(target=finish) for _ in range(2)]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join(timeout=2)

    assert sorted(results) == [False, True]
    replacement = controller.acquire("backend-a", "vod")
    with pytest.raises(CONTRACT.ReliabilityFailure) as raised:
        controller.acquire("backend-a", "vod")
    assert raised.value.kind == "bulkhead_rejected"
    second.finish(success=True)
    replacement.finish(success=True)


def test_provider_health_snapshot_is_bounded_and_tracks_ewma():
    controller = CONTRACT.ProviderReliabilityController(
        clock=_Clock(), history_limit=3, ewma_alpha=0.5,
    )
    controller.acquire("backend-a", "vod").finish(success=True)
    _provider_failure(controller, kind="timeout")
    _provider_failure(controller, kind="payload")
    controller.acquire("backend-a", "vod").finish(success=True)

    snapshot = controller.snapshot("backend-a", "vod")
    assert snapshot["requests"] == 4
    assert snapshot["successes"] == 2
    assert snapshot["failures"] == 2
    assert snapshot["health_score"] == pytest.approx(0.75)
    assert len(snapshot["recent"]) == 3


def test_provider_reset_drops_backend_state_and_invalidates_old_leases():
    controller = CONTRACT.ProviderReliabilityController(clock=_Clock())
    stale = controller.acquire("backend-a", "vod")
    _provider_failure(controller, backend="backend-b", mode="vod1", kind="server")

    controller.reset()
    assert controller.snapshot() == []
    assert stale.finish(failure_kind="timeout") is True
    assert controller.snapshot() == []

    fresh = controller.acquire("backend-c", "vod")
    fresh.finish(success=True)
    assert controller.snapshot("backend-c", "vod")["successes"] == 1


def test_request_timeout_rejects_unknown_retry_policy():
    budget = CONTRACT.TimeoutBudget(100.0, clock=lambda: 90.0)

    with pytest.raises(CONTRACT.ReliabilityFailure) as raised:
        budget.request_timeout(12, retry_policy=object())

    assert raised.value.kind == "configuration"


@pytest.mark.parametrize("deadline", (True, float("nan"), float("inf"), float("-inf")))
def test_timeout_budget_rejects_non_finite_or_boolean_deadline(deadline):
    with pytest.raises(CONTRACT.ReliabilityFailure) as raised:
        CONTRACT.TimeoutBudget(deadline)
    assert raised.value.kind == "configuration"


@pytest.mark.parametrize("requests_left", (False, 0, -1, 1.5, "many", object()))
def test_timeout_budget_rejects_non_numeric_requests_left(requests_left):
    budget = CONTRACT.TimeoutBudget(100.0, clock=lambda: 90.0)
    with pytest.raises(CONTRACT.ReliabilityFailure) as raised:
        budget.request_timeout(12, requests_left=requests_left)
    assert raised.value.kind == "configuration"


@pytest.mark.parametrize("default_timeout", (False, 0, -1, float("nan"), float("inf")))
def test_timeout_budget_rejects_invalid_default_timeout(default_timeout):
    budget = CONTRACT.TimeoutBudget(100.0, clock=lambda: 90.0)
    with pytest.raises(CONTRACT.ReliabilityFailure) as raised:
        budget.request_timeout(default_timeout, requests_left=1)
    assert raised.value.kind == "configuration"


@pytest.mark.parametrize("clock_value", ("later", float("nan"), float("inf")))
def test_timeout_budget_rejects_invalid_clock_value(clock_value):
    budget = CONTRACT.TimeoutBudget(100.0, clock=lambda: clock_value)
    with pytest.raises(CONTRACT.ReliabilityFailure) as raised:
        budget.remaining()
    assert raised.value.kind == "configuration"


def test_non_finite_http_status_is_ignored_without_leaking_overflow():
    assert CONTRACT.v80_reliability_classify(status=float("inf")) == "runtime"


def test_contract_has_no_network_side_effect(monkeypatch):
    calls = []
    monkeypatch.setattr(
        requests.sessions.Session,
        "request",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    CONTRACT.v80_reliability_classify(requests.ConnectionError())
    CONTRACT.v80_reliability_http_failure(500, "resource_api_get")
    CONTRACT.v80_reliability_request_timeout(None, 5)
    CONTRACT.v80_reliability_atvp_retry_adapter()

    assert calls == []

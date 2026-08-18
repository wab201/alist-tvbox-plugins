"""Small, deterministic reliability contract for the isolated V80 runtime."""

import json
import inspect
import math
import socket
import ssl
import threading
import time

import requests


FAILURE_KINDS = frozenset((
    "cancelled",
    "budget_exhausted",
    "timeout",
    "dns",
    "tls",
    "transport",
    "auth",
    "rate_limit",
    "server",
    "client",
    "unsupported",
    "payload",
    "configuration",
    "runtime",
    "circuit_open",
    "bulkhead_rejected",
))

UNSUPPORTED_HTTP_STATUSES = frozenset((404, 405, 501))
TRANSIENT_FAILURE_KINDS = frozenset((
    "timeout", "dns", "tls", "transport", "server", "rate_limit",
))
CIRCUIT_CLOSED = "closed"
CIRCUIT_OPEN = "open"
CIRCUIT_HALF_OPEN = "half_open"


class RetryPolicy(object):
    """Fixed transport retry settings shared by adapter and deadline math."""

    __slots__ = (
        "total", "connect", "read", "status", "other", "backoff_factor",
        "backoff_max", "allowed_methods", "pool_connections", "pool_maxsize",
    )

    def __init__(
            self, total, connect, read, status, other, backoff_factor,
            backoff_max, allowed_methods, pool_connections, pool_maxsize):
        self.total = int(total)
        self.connect = int(connect)
        self.read = int(read)
        self.status = int(status)
        self.other = int(other)
        self.backoff_factor = float(backoff_factor)
        self.backoff_max = float(backoff_max)
        self.allowed_methods = frozenset(allowed_methods)
        self.pool_connections = int(pool_connections)
        self.pool_maxsize = int(pool_maxsize)

    def request_phases(self, requests_left=1):
        return int(requests_left) * (self.total + 1) * 2

    def backoff_budget(self, requests_left=1):
        per_request = sum(
            min(self.backoff_max, self.backoff_factor * (2.0 ** (retry_number - 1)))
            for retry_number in range(2, self.total + 1)
        )
        return int(requests_left) * per_request


ATVP_TRANSPORT_RETRY_POLICY = RetryPolicy(
    total=2,
    connect=2,
    read=2,
    status=0,
    other=0,
    backoff_factor=0.4,
    backoff_max=120.0,
    allowed_methods=("GET",),
    pool_connections=4,
    pool_maxsize=4,
)


def v80_reliability_atvp_retry_adapter():
    """Build the sole ATVP transport retry adapter without HTTP retries."""

    policy = ATVP_TRANSPORT_RETRY_POLICY
    from requests.packages.urllib3.util.retry import Retry
    try:
        parameters = inspect.signature(Retry.__init__).parameters
    except (TypeError, ValueError):
        parameters = {}
    retry_kwargs = {
        "total": policy.total,
        "connect": policy.connect,
        "read": policy.read,
        "status": policy.status,
        "backoff_factor": policy.backoff_factor,
    }
    optional_kwargs = {
        "other": policy.other,
        "backoff_max": policy.backoff_max,
        "respect_retry_after_header": False,
        "raise_on_status": False,
    }
    retry_kwargs.update(
        (name, value) for name, value in optional_kwargs.items()
        if name in parameters
    )
    if "allowed_methods" in parameters:
        retry_kwargs["allowed_methods"] = policy.allowed_methods
    elif "method_whitelist" in parameters:
        retry_kwargs["method_whitelist"] = policy.allowed_methods
    retry = Retry(**retry_kwargs)
    return requests.adapters.HTTPAdapter(
        max_retries=retry,
        pool_connections=policy.pool_connections,
        pool_maxsize=policy.pool_maxsize,
    )


def _safe_operation(value):
    text = str(value or "operation").strip()
    if not text or len(text) > 64:
        return "operation"
    for character in text:
        if not (character.isascii() and (character.isalnum() or character in "_.-")):
            return "operation"
    return text


def _safe_status(value):
    if value is None:
        return None
    try:
        status = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return status if 100 <= status <= 599 else None


class ReliabilityFailure(RuntimeError):
    """A redacted failure carrying only stable diagnostic fields."""

    def __init__(self, kind, status=None, operation=None, explicit_unsupported=False):
        normalized_kind = str(kind or "").strip().lower()
        normalized_status = _safe_status(status)
        if normalized_kind not in FAILURE_KINDS:
            raise ValueError("unknown reliability failure kind")
        if normalized_kind == "unsupported" and not (
                explicit_unsupported and normalized_status in UNSUPPORTED_HTTP_STATUSES):
            raise ValueError("unsupported requires an explicit capability status")
        self.kind = normalized_kind
        self.status = normalized_status
        self.operation = _safe_operation(operation)
        suffix = " HTTP %d" % normalized_status if normalized_status is not None else ""
        RuntimeError.__init__(
            self,
            "%s failed: %s%s" % (self.operation, self.kind, suffix),
        )


def _exception_graph(exc):
    pending = [exc] if isinstance(exc, BaseException) else []
    seen = set()
    while pending and len(seen) < 32:
        current = pending.pop(0)
        marker = id(current)
        if marker in seen:
            continue
        seen.add(marker)
        yield current
        for linked in (getattr(current, "__cause__", None), getattr(current, "__context__", None)):
            if isinstance(linked, BaseException):
                pending.append(linked)
        for value in getattr(current, "args", ()):
            if isinstance(value, BaseException):
                pending.append(value)


def _status_from_exception(exc):
    for current in _exception_graph(exc):
        for value in (
                getattr(current, "status", None),
                getattr(current, "status_code", None),
                getattr(getattr(current, "response", None), "status_code", None)):
            status = _safe_status(value)
            if status is not None:
                return status
    return None


def _http_kind(status, explicit_unsupported=False):
    status = _safe_status(status)
    if explicit_unsupported and status in UNSUPPORTED_HTTP_STATUSES:
        return "unsupported"
    if status in (401, 403):
        return "auth"
    if status == 429:
        return "rate_limit"
    if status is not None and 500 <= status <= 599:
        return "server"
    if status is not None and 400 <= status <= 499:
        return "client"
    return "runtime"


def v80_reliability_classify(exc=None, status=None, explicit_unsupported=False):
    """Return a stable failure kind without inspecting exception messages."""

    graph = tuple(_exception_graph(exc))
    for current in graph:
        if isinstance(current, ReliabilityFailure):
            return current.kind

    normalized_status = _safe_status(status)
    if normalized_status is None:
        normalized_status = _status_from_exception(exc)
    if normalized_status is not None:
        return _http_kind(normalized_status, explicit_unsupported=explicit_unsupported)

    if any(type(current).__name__ in ("CancelledError", "Cancelled") for current in graph):
        return "cancelled"
    if any(isinstance(current, socket.gaierror) for current in graph):
        return "dns"
    if any(isinstance(current, (requests.exceptions.Timeout, TimeoutError, socket.timeout))
           for current in graph):
        return "timeout"
    if any(isinstance(current, (requests.exceptions.SSLError, ssl.SSLError))
           for current in graph):
        return "tls"
    if any(isinstance(current, (
            requests.exceptions.InvalidURL,
            requests.exceptions.InvalidSchema,
            requests.exceptions.MissingSchema,
            requests.exceptions.InvalidHeader,
    )) for current in graph):
        return "configuration"
    request_json_error = getattr(requests.exceptions, "JSONDecodeError", ())
    json_types = (json.JSONDecodeError,) + (
        (request_json_error,) if isinstance(request_json_error, type) else ()
    )
    if any(isinstance(current, json_types) for current in graph):
        return "payload"
    if any(isinstance(current, (
            requests.exceptions.ConnectionError,
            requests.exceptions.ChunkedEncodingError,
            requests.exceptions.ContentDecodingError,
            requests.exceptions.TooManyRedirects,
            ConnectionError,
    )) for current in graph):
        return "transport"
    return "runtime"


def v80_reliability_http_failure(status, operation, explicit_unsupported=False):
    normalized_status = _safe_status(status)
    return ReliabilityFailure(
        _http_kind(normalized_status, explicit_unsupported=explicit_unsupported),
        status=normalized_status,
        operation=operation,
        explicit_unsupported=explicit_unsupported,
    )


def v80_reliability_payload_failure(operation, exc=None, deadline=None, clock=None):
    """Wrap bounded-reader failures without hiding transport or budget failures."""

    if isinstance(exc, ReliabilityFailure):
        return exc
    kind = v80_reliability_classify(exc)
    if kind != "runtime":
        return ReliabilityFailure(kind, operation=operation)
    if deadline is not None:
        try:
            now = time.monotonic() if clock is None else float(clock())
            if float(deadline) <= now:
                return ReliabilityFailure("budget_exhausted", operation=operation)
        except (TypeError, ValueError, OverflowError):
            pass
    return ReliabilityFailure("payload", operation=operation)


class ProviderReliabilityLease(object):
    """Idempotent ownership token for one provider transport admission."""

    __slots__ = (
        "_controller", "_key", "_generation", "_probe", "_finished", "_lock",
    )

    def __init__(self, controller, key, generation, probe=False):
        self._controller = controller
        self._key = key
        self._generation = generation
        self._probe = bool(probe)
        self._finished = False
        self._lock = threading.Lock()

    def finish(self, success=False, failure_kind=None):
        with self._lock:
            if self._finished:
                return False
            self._finished = True
        self._controller._finish(
            self._key, self._generation,
            success=bool(success), failure_kind=failure_kind, probe=self._probe,
        )
        return True


class ProviderReliabilityController(object):
    """Provider-scoped circuit breaker, health meter, and transport bulkhead."""

    def __init__(
            self, clock=None, failure_threshold=3, open_seconds=30.0,
            capacity=2, history_limit=16, ewma_alpha=0.25):
        self._clock = time.monotonic if clock is None else clock
        if not callable(self._clock):
            raise ReliabilityFailure("configuration", operation="provider_controller")
        try:
            threshold = int(failure_threshold)
            capacity_value = int(capacity)
            limit = int(history_limit)
            window = float(open_seconds)
            alpha = float(ewma_alpha)
        except (TypeError, ValueError, OverflowError):
            raise ReliabilityFailure("configuration", operation="provider_controller") from None
        if (
                threshold < 1 or capacity_value < 1 or limit < 1
                or not math.isfinite(window) or window <= 0
                or not math.isfinite(alpha) or not 0 < alpha <= 1):
            raise ReliabilityFailure("configuration", operation="provider_controller")
        self.failure_threshold = threshold
        self.open_seconds = window
        self.capacity = capacity_value
        self.history_limit = limit
        self.ewma_alpha = alpha
        self._lock = threading.RLock()
        self._states = {}
        self._generation = 0

    @staticmethod
    def _key(backend_identity, provider_mode):
        backend = str(backend_identity or "").strip()[:128]
        mode = str(provider_mode or "").strip().lower()[:32]
        return backend, mode

    def _state(self, key):
        state = self._states.get(key)
        if state is None:
            state = {
                "state": CIRCUIT_CLOSED,
                "opened_at": None,
                "half_open_probe": False,
                "in_flight": 0,
                "requests": 0,
                "successes": 0,
                "failures": 0,
                "transient_failures": 0,
                "non_transient_failures": 0,
                "consecutive_transient_failures": 0,
                "health_score": 1.0,
                "recent": [],
            }
            self._states[key] = state
        return state

    def acquire(self, backend_identity, provider_mode):
        key = self._key(backend_identity, provider_mode)
        with self._lock:
            state = self._state(key)
            now = float(self._clock())
            if not math.isfinite(now):
                raise ReliabilityFailure("configuration", operation="provider_controller")
            if state["state"] == CIRCUIT_OPEN:
                opened_at = state.get("opened_at")
                if opened_at is None or now - float(opened_at) < self.open_seconds:
                    raise ReliabilityFailure("circuit_open", operation="provider_gate")
                state["state"] = CIRCUIT_HALF_OPEN
                state["half_open_probe"] = False
            if state["state"] == CIRCUIT_HALF_OPEN and state["half_open_probe"]:
                raise ReliabilityFailure("circuit_open", operation="provider_gate")
            if state["in_flight"] >= self.capacity:
                raise ReliabilityFailure("bulkhead_rejected", operation="provider_gate")
            state["in_flight"] += 1
            state["requests"] += 1
            probe = state["state"] == CIRCUIT_HALF_OPEN
            if probe:
                state["half_open_probe"] = True
            return ProviderReliabilityLease(
                self, key, self._generation, probe=probe,
            )

    def _finish(self, key, generation, success=False, failure_kind=None, probe=False):
        with self._lock:
            if generation != self._generation:
                return
            state = self._states.get(key)
            if state is None:
                return
            state["in_flight"] = max(0, state["in_flight"] - 1)
            if success:
                state["successes"] += 1
                state["consecutive_transient_failures"] = 0
                sample = 1.0
                normalized_kind = "success"
            else:
                normalized_kind = str(failure_kind or "runtime").strip().lower()
                state["failures"] += 1
                if normalized_kind in TRANSIENT_FAILURE_KINDS:
                    state["transient_failures"] += 1
                    state["consecutive_transient_failures"] += 1
                    sample = 0.0
                else:
                    state["non_transient_failures"] += 1
                    state["consecutive_transient_failures"] = 0
                    sample = 0.5
            state["health_score"] = (
                self.ewma_alpha * sample
                + (1.0 - self.ewma_alpha) * state["health_score"]
            )
            state["recent"].append({"kind": normalized_kind, "at": float(self._clock())})
            if len(state["recent"]) > self.history_limit:
                del state["recent"][:-self.history_limit]
            if probe and state["state"] == CIRCUIT_HALF_OPEN:
                state["half_open_probe"] = False
                if normalized_kind in TRANSIENT_FAILURE_KINDS:
                    state["state"] = CIRCUIT_OPEN
                    state["opened_at"] = float(self._clock())
                    state["consecutive_transient_failures"] = self.failure_threshold
                else:
                    state["state"] = CIRCUIT_CLOSED
                    state["opened_at"] = None
            elif state["state"] in (CIRCUIT_OPEN, CIRCUIT_HALF_OPEN):
                if state["state"] == CIRCUIT_OPEN:
                    state["consecutive_transient_failures"] = max(
                        self.failure_threshold,
                        state["consecutive_transient_failures"],
                    )
            elif normalized_kind in TRANSIENT_FAILURE_KINDS:
                if state["consecutive_transient_failures"] >= self.failure_threshold:
                    state["state"] = CIRCUIT_OPEN
                    state["opened_at"] = float(self._clock())
            else:
                state["opened_at"] = None

    def snapshot(self, backend_identity=None, provider_mode=None):
        with self._lock:
            if backend_identity is None and provider_mode is None:
                rows = []
                for key, value in self._states.items():
                    rows.append(self._snapshot_row(key, value))
                return rows
            key = self._key(backend_identity, provider_mode)
            state = self._states.get(key)
            return self._snapshot_row(key, state) if state is not None else None

    def _snapshot_row(self, key, state):
        return {
            "backend": key[0],
            "mode": key[1],
            "state": state["state"],
            "in_flight": state["in_flight"],
            "capacity": self.capacity,
            "requests": state["requests"],
            "successes": state["successes"],
            "failures": state["failures"],
            "transient_failures": state["transient_failures"],
            "non_transient_failures": state["non_transient_failures"],
            "consecutive_transient_failures": state["consecutive_transient_failures"],
            "health_score": round(float(state["health_score"]), 6),
            "recent": [dict(item) for item in state["recent"]],
        }

    def reset(self):
        with self._lock:
            self._generation += 1
            self._states.clear()


class TimeoutBudget(object):
    """Absolute monotonic deadline used to allocate request phase timeouts."""

    def __init__(self, deadline=None, clock=None):
        if isinstance(deadline, bool):
            raise ReliabilityFailure("configuration", operation="timeout_budget")
        try:
            self.deadline = None if deadline is None else float(deadline)
        except (TypeError, ValueError, OverflowError):
            raise ReliabilityFailure("configuration", operation="timeout_budget") from None
        if self.deadline is not None and not math.isfinite(self.deadline):
            raise ReliabilityFailure("configuration", operation="timeout_budget")
        self._clock = time.monotonic if clock is None else clock
        if not callable(self._clock):
            raise ReliabilityFailure("configuration", operation="timeout_budget")

    def remaining(self):
        if self.deadline is None:
            return float("inf")
        try:
            now = float(self._clock())
        except (TypeError, ValueError, OverflowError):
            raise ReliabilityFailure("configuration", operation="timeout_budget") from None
        if not math.isfinite(now):
            raise ReliabilityFailure("configuration", operation="timeout_budget")
        return max(0.0, self.deadline - now)

    def request_timeout(self, default_timeout, requests_left=1, retry_policy=None):
        if isinstance(default_timeout, bool) or isinstance(requests_left, bool):
            raise ReliabilityFailure("configuration", operation="request_timeout")
        try:
            timeout = float(default_timeout)
            request_count = int(requests_left)
            exact_request_count = float(requests_left)
        except (TypeError, ValueError, OverflowError):
            raise ReliabilityFailure("configuration", operation="request_timeout") from None
        if (
                not math.isfinite(timeout) or timeout <= 0
                or not math.isfinite(exact_request_count)
                or exact_request_count != request_count or request_count < 1):
            raise ReliabilityFailure("configuration", operation="request_timeout")
        if self.deadline is None:
            return max(1, int(timeout))
        remaining = self.remaining()
        if remaining < 1:
            raise ReliabilityFailure(
                "budget_exhausted", operation="request_timeout",
            )
        if retry_policy is None:
            request_phases = request_count * 6
            backoff_budget = 0.0
        elif isinstance(retry_policy, RetryPolicy):
            request_phases = retry_policy.request_phases(request_count)
            backoff_budget = retry_policy.backoff_budget(request_count)
        else:
            raise ReliabilityFailure("configuration", operation="request_timeout")
        request_budget = remaining - backoff_budget
        if request_budget <= 0:
            raise ReliabilityFailure(
                "budget_exhausted", operation="request_timeout",
            )
        return min(timeout, request_budget / request_phases)


def v80_reliability_request_timeout(
        deadline, default_timeout, requests_left=1, clock=None, retry_policy=None):
    return TimeoutBudget(deadline=deadline, clock=clock).request_timeout(
        default_timeout, requests_left=requests_left, retry_policy=retry_policy,
    )

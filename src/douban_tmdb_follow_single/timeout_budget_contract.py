"""End-to-end timeout and lifecycle cancellation contract for isolated V80."""

import inspect
import math
import threading
import time

import requests


try:
    RetryPolicy
except NameError:
    _reliability_contract = __import__(
        __package__ + ".reliability_contract",
        fromlist=("ReliabilityFailure", "RetryPolicy", "TimeoutBudget"),
    )
    ReliabilityFailure = _reliability_contract.ReliabilityFailure
    RetryPolicy = _reliability_contract.RetryPolicy
    TimeoutBudget = _reliability_contract.TimeoutBudget


GENERAL_TRANSPORT_RETRY_POLICY = RetryPolicy(
    total=1,
    connect=1,
    read=0,
    status=1,
    other=0,
    backoff_factor=0.2,
    backoff_max=120.0,
    allowed_methods=("GET",),
    pool_connections=8,
    pool_maxsize=8,
)


def v80_timeout_general_retry_adapter():
    """Build the general GET adapter from the same policy used by budget math."""

    policy = GENERAL_TRANSPORT_RETRY_POLICY
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
        "status_forcelist": (429, 500, 502, 503, 504),
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


def _v80_timeout_number(value, operation):
    if isinstance(value, bool):
        raise ReliabilityFailure("configuration", operation=operation)
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        raise ReliabilityFailure("configuration", operation=operation) from None
    if not math.isfinite(number):
        raise ReliabilityFailure("configuration", operation=operation)
    return number


class TimeoutOperation(object):
    """One finite operation deadline bound to a Spider lifecycle generation."""

    __slots__ = (
        "_controller", "operation", "generation", "deadline", "_cancelled",
        "_finished", "_tracked", "_lock",
    )

    def __init__(self, controller, operation, generation, deadline):
        self._controller = controller
        self.operation = str(operation or "operation")
        self.generation = int(generation)
        self.deadline = float(deadline)
        self._cancelled = threading.Event()
        self._finished = False
        self._tracked = {}
        self._lock = threading.RLock()

    def __enter__(self):
        self._controller._enter(self)
        try:
            self.checkpoint()
        except Exception:
            self._controller._leave(self)
            raise
        return self

    def __exit__(self, exc_type, exc, traceback):
        self._controller._leave(self)
        return False

    def remaining(self):
        self.checkpoint(check_deadline=False)
        return TimeoutBudget(
            self.deadline, clock=self._controller.clock,
        ).remaining()

    def checkpoint(self, check_deadline=True):
        if (
                self._cancelled.is_set()
                or not self._controller._generation_active(self.generation)):
            raise ReliabilityFailure("cancelled", operation=self.operation)
        if check_deadline and self.remaining() <= 0:
            raise ReliabilityFailure("budget_exhausted", operation=self.operation)
        return True

    def request_timeout(self, default_timeout, requests_left=1, retry_policy=None):
        self.checkpoint()
        return TimeoutBudget(
            self.deadline, clock=self._controller.clock,
        ).request_timeout(
            default_timeout,
            requests_left=requests_left,
            retry_policy=retry_policy,
        )

    def track(self, resource):
        closer = getattr(resource, "close", None)
        if not callable(closer):
            raise ReliabilityFailure("configuration", operation=self.operation)
        close_now = False
        with self._lock:
            if self._cancelled.is_set() or self._finished:
                close_now = True
            else:
                self._tracked[id(resource)] = resource
        if close_now:
            try:
                closer()
            finally:
                raise ReliabilityFailure("cancelled", operation=self.operation)
        self.checkpoint()
        return resource

    def untrack(self, resource):
        with self._lock:
            return self._tracked.pop(id(resource), None) is not None

    def close_tracked(self, resource):
        with self._lock:
            tracked = self._tracked.pop(id(resource), None)
        if tracked is None:
            return False
        try:
            tracked.close()
        except Exception:
            pass
        return True

    def cancel(self):
        self._cancelled.set()
        self._close_tracked()

    def _finish(self):
        with self._lock:
            if self._finished:
                return False
            self._finished = True
        self._close_tracked()
        return True

    def _close_tracked(self):
        with self._lock:
            resources = list(self._tracked.values())
            self._tracked.clear()
        for resource in resources:
            try:
                resource.close()
            except Exception:
                pass


class TimeoutBudgetController(object):
    """Own current-thread budgets and cancel all scopes on lifecycle reset."""

    __slots__ = (
        "_lock", "_local", "_active", "_generation", "_closed", "clock",
    )

    def __init__(self, generation=0, clock=None):
        self._lock = threading.RLock()
        self._local = threading.local()
        self._active = {}
        self._generation = int(generation)
        self._closed = False
        self.clock = time.monotonic if clock is None else clock
        if not callable(self.clock):
            raise ReliabilityFailure("configuration", operation="timeout_controller")

    def scope(self, operation, timeout_seconds, expected_generation=None, deadline=None):
        timeout = _v80_timeout_number(timeout_seconds, "timeout_scope")
        if timeout <= 0:
            raise ReliabilityFailure("configuration", operation="timeout_scope")
        now = _v80_timeout_number(self.clock(), "timeout_scope")
        try:
            requested_generation = (
                None if expected_generation is None else int(expected_generation)
            )
        except (TypeError, ValueError, OverflowError):
            raise ReliabilityFailure(
                "configuration", operation="timeout_scope",
            ) from None
        with self._lock:
            generation = (
                self._generation
                if requested_generation is None else requested_generation
            )
        effective_deadline = now + timeout
        if deadline is not None:
            effective_deadline = min(
                effective_deadline,
                _v80_timeout_number(deadline, "timeout_scope"),
            )
        stack = getattr(self._local, "stack", None) or []
        parent = stack[-1] if stack else None
        if parent is not None and parent.generation == generation:
            parent.checkpoint()
            effective_deadline = min(effective_deadline, parent.deadline)
        return TimeoutOperation(self, operation, generation, effective_deadline)

    def current(self, required=True):
        stack = getattr(self._local, "stack", None) or []
        if not stack:
            if required:
                raise ReliabilityFailure("configuration", operation="timeout_current")
            return None
        operation = stack[-1]
        operation.checkpoint()
        return operation

    def reset(self, generation, closed=False):
        with self._lock:
            self._generation = int(generation)
            self._closed = bool(closed)
            active = list(self._active.values())
            self._active.clear()
        for operation in active:
            operation.cancel()
        return len(active)

    def snapshot(self):
        with self._lock:
            return {
                "generation": self._generation,
                "closed": self._closed,
                "active": len(self._active),
            }

    def _generation_active(self, generation):
        with self._lock:
            return not self._closed and int(generation) == self._generation

    def _enter(self, operation):
        with self._lock:
            if not self._generation_active(operation.generation):
                operation.cancel()
                raise ReliabilityFailure("cancelled", operation=operation.operation)
            self._active[id(operation)] = operation
            stack = list(getattr(self._local, "stack", None) or [])
            stack.append(operation)
            self._local.stack = stack

    def _leave(self, operation):
        with self._lock:
            self._active.pop(id(operation), None)
            stack = list(getattr(self._local, "stack", None) or [])
            if stack and stack[-1] is operation:
                stack.pop()
            else:
                stack = [item for item in stack if item is not operation]
            self._local.stack = stack
        operation._finish()

import importlib.util
import threading
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parent.parent
CONTRACT_PATH = ROOT / "src" / "douban_tmdb_follow_single" / "cache_health_contract.py"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CONTRACT = _load("v80_p3_cache_health_contract", CONTRACT_PATH)


class Clock(object):
    def __init__(self, value=100.0):
        self.value = float(value)

    def __call__(self):
        return self.value


class QueuedTasks(object):
    def __init__(self, error=None):
        self.error = error
        self.rows = []

    def start_thread(self, target, name=""):
        if self.error is not None:
            raise self.error
        self.rows.append((target, name))

    def run(self):
        target, _name = self.rows.pop(0)
        target()


class Owner(object):
    def __init__(self, clock=None):
        self.failure_ttl = 60
        self.stale_ttl = 86400
        self._cache_lock = threading.RLock()
        self._cache_generation = 1
        self._refreshing_cache_keys = {}
        self._failures = {}
        self._failure_attempts = {}
        self._cache_values = {}
        self._lookup = {}
        self._diagnostics = []
        self._tasks = QueuedTasks()
        self._cache_health_controller = CONTRACT.CacheHealthController(
            self, clock=clock,
        )

    @staticmethod
    def _short_error(exc):
        return str(exc)

    def _diagnostic_event(self, *args, **kwargs):
        self._diagnostics.append((args, kwargs))

    def _cache_get(self, key, _ttl, allow_expired=False):
        marker = (key, bool(allow_expired))
        return self._lookup[marker] if marker in self._lookup else None

    def _cache_set(self, key, value):
        self._cache_values[key] = value

    @staticmethod
    def _is_persistable_cache_key(key):
        return str(key).startswith(("json:", "text:", "tmdb-json:"))

    def _load_response_cache(self):
        return None

    def _remember_failure(self, key, exc):
        self._cache_health_controller.remember_failure(key, exc)

    def _clear_cached_failure(self, key):
        self._cache_health_controller.clear_failure(key)

    def _raise_cached_failure(self, key):
        self._cache_health_controller.raise_if_blocked(key)

    def _has_cached_failure(self, key):
        return self._cache_health_controller.failure_active(key)

    def _schedule_cache_refresh(self, key, loader):
        return CONTRACT.v80_cache_schedule_refresh(self, key, loader)


def test_failure_backoff_matches_v70_growth_cap_expiry_and_reset():
    clock = Clock()
    owner = Owner(clock)
    controller = owner._cache_health_controller
    delays = []

    for index in range(7):
        controller.remember_failure("json:key", RuntimeError("failure-%d" % index))
        failed_at, retry_at, message = owner._failures["json:key"]
        delays.append(retry_at - failed_at)
        assert message == "failure-%d" % index

    assert delays == [1.0, 2.0, 4.0, 8.0, 16.0, 32.0, 32.0]
    assert owner._failure_attempts["json:key"] == 6
    assert controller.failure_active("json:key") is True

    clock.value += 33
    assert controller.failure_active("json:key") is False
    assert "json:key" not in owner._failures
    assert "json:key" not in owner._failure_attempts

    controller.remember_failure("json:key", RuntimeError("again"))
    controller.reset()
    assert owner._failures == {}
    assert owner._failure_attempts == {}
    assert controller.snapshot() == []


def test_failure_ttl_caps_each_backoff_delay():
    owner = Owner(Clock())
    owner.failure_ttl = 10

    for _index in range(6):
        owner._cache_health_controller.remember_failure("json:key", RuntimeError("x"))

    failed_at, retry_at, _message = owner._failures["json:key"]
    assert retry_at - failed_at == 10.0


def test_raise_if_blocked_keeps_legacy_short_error_and_expiry():
    clock = Clock()
    owner = Owner(clock)
    owner._cache_health_controller.remember_failure(
        "json:key", RuntimeError("stable short error"),
    )

    with pytest.raises(RuntimeError, match="stable short error"):
        owner._cache_health_controller.raise_if_blocked("json:key")

    clock.value += 2
    owner._cache_health_controller.raise_if_blocked("json:key")
    assert owner._failures == {}


def test_snapshot_is_bounded_and_never_exposes_raw_cache_keys_or_errors(monkeypatch):
    clock = Clock()
    owner = Owner(clock)
    monkeypatch.setattr(CONTRACT, "v80_reliability_classify", lambda _exc: "timeout", raising=False)

    for index in range(70):
        owner._cache_health_controller.remember_failure(
            "https://example.invalid/cache/private-%d" % index,
            RuntimeError("opaque-%d" % index),
        )

    rows = owner._cache_health_controller.snapshot(limit=1000)
    serialized = repr(rows)
    assert len(rows) == CONTRACT.CACHE_HEALTH_SNAPSHOT_LIMIT
    assert all(row["kind"] == "timeout" for row in rows)
    assert "private" not in serialized
    assert "opaque" not in serialized
    assert all(len(row["key"]) == 16 for row in rows)
    assert all(len(row[1]["cache_key"]) == 16 for row in owner._diagnostics)
    assert all("example.invalid" not in row[1]["cache_key"] for row in owner._diagnostics)


@pytest.mark.parametrize("value", ({}, [], "", 0, False))
def test_falsy_fresh_values_are_valid_cache_hits(value):
    owner = Owner(Clock())
    owner._lookup[("json:key", False)] = value
    called = []

    result = CONTRACT.v80_cache_load(
        owner, "json:key", 60, lambda: called.append(True),
    )

    assert result == value
    assert called == []


def test_none_remains_a_miss_and_success_clears_failure_state():
    owner = Owner(Clock())
    owner._cache_health_controller.remember_failure("json:key", RuntimeError("old"))
    owner._cache_health_controller.clear_failure("json:key")

    result = CONTRACT.v80_cache_load(
        owner, "json:key", 60, lambda: {"ok": True},
    )

    assert result == {"ok": True}
    assert owner._cache_values["json:key"] == {"ok": True}
    assert owner._failures == {}


def test_stale_returns_immediately_and_schedules_one_refresh():
    owner = Owner(Clock())
    owner._lookup[("json:key", True)] = {"stale": True}
    loader_calls = []

    result = CONTRACT.v80_cache_load(
        owner, "json:key", 60,
        lambda: loader_calls.append(True) or {"fresh": True},
    )
    duplicate = owner._schedule_cache_refresh("json:key", lambda: None)

    assert result == {"stale": True}
    assert loader_calls == []
    assert len(owner._tasks.rows) == 1
    assert duplicate is False

    owner._tasks.run()
    assert loader_calls == [True]
    assert owner._cache_values["json:key"] == {"fresh": True}
    assert owner._refreshing_cache_keys == {}


def test_active_backoff_suppresses_stale_refresh():
    owner = Owner(Clock())
    owner._lookup[("json:key", True)] = []
    owner._cache_health_controller.remember_failure("json:key", RuntimeError("blocked"))

    result = CONTRACT.v80_cache_load(
        owner, "json:key", 60, lambda: pytest.fail("loader must not run"),
    )

    assert result == []
    assert owner._tasks.rows == []


def test_allow_stale_false_runs_foreground_loader():
    owner = Owner(Clock())
    owner._lookup[("tmdb:key", True)] = {"stale": True}

    result = CONTRACT.v80_cache_load(
        owner, "tmdb:key", 60, lambda: {"fresh": True},
        allow_stale=False,
    )

    assert result == {"fresh": True}
    assert owner._cache_values["tmdb:key"] == {"fresh": True}
    assert owner._tasks.rows == []


def test_foreground_failure_is_cached_and_blocks_the_next_miss():
    owner = Owner(Clock())
    calls = []

    def fail():
        calls.append(True)
        raise RuntimeError("network failed")

    with pytest.raises(RuntimeError, match="network failed"):
        CONTRACT.v80_cache_load(owner, "json:key", 60, fail)
    with pytest.raises(RuntimeError, match="network failed"):
        CONTRACT.v80_cache_load(owner, "json:key", 60, fail)

    assert calls == [True]
    assert owner._failure_attempts["json:key"] == 1


@pytest.mark.parametrize("fails", (False, True))
def test_old_generation_foreground_completion_cannot_commit_health_state(fails):
    owner = Owner(Clock())

    def loader():
        owner._cache_generation += 1
        if fails:
            raise RuntimeError("late failure")
        return {"late": True}

    if fails:
        with pytest.raises(RuntimeError, match="late failure"):
            CONTRACT.v80_cache_load(owner, "json:key", 60, loader)
    else:
        assert CONTRACT.v80_cache_load(owner, "json:key", 60, loader) == {"late": True}

    assert owner._cache_values == {}
    assert owner._failures == {}


@pytest.mark.parametrize("fails", (False, True))
def test_old_generation_background_completion_cannot_commit(fails):
    owner = Owner(Clock())

    def loader():
        if fails:
            raise RuntimeError("late failure")
        return {"late": True}

    assert CONTRACT.v80_cache_schedule_refresh(owner, "json:key", loader) is True
    owner._cache_generation += 1
    owner._tasks.run()

    assert owner._cache_values == {}
    assert owner._failures == {}
    assert owner._refreshing_cache_keys == {}


def test_refresh_start_failure_releases_ownership_without_recording_failure():
    owner = Owner(Clock())
    owner._tasks = QueuedTasks(error=RuntimeError("closed"))

    assert CONTRACT.v80_cache_schedule_refresh(
        owner, "json:key", lambda: None,
    ) is False
    assert owner._refreshing_cache_keys == {}
    assert owner._failures == {}


def _assert_reset_waits_for_atomic_commit(owner, commit, mutation_hook):
    entered = threading.Event()
    release = threading.Event()
    reset_done = threading.Event()
    original = mutation_hook[0]

    def blocking(*args, **kwargs):
        entered.set()
        assert release.wait(2)
        return original(*args, **kwargs)

    mutation_hook[1](blocking)
    worker = threading.Thread(target=commit)
    worker.start()
    assert entered.wait(2)

    def reset_generation():
        with owner._cache_lock:
            owner._cache_generation += 1
            owner._cache_values.clear()
            owner._cache_health_controller.reset()
        reset_done.set()

    resetter = threading.Thread(target=reset_generation)
    resetter.start()
    assert reset_done.wait(0.05) is False
    release.set()
    worker.join(2)
    resetter.join(2)
    assert not worker.is_alive()
    assert not resetter.is_alive()
    assert reset_done.is_set()
    assert owner._cache_values == {}
    assert owner._failures == {}


@pytest.mark.parametrize("background", (False, True))
def test_success_commit_is_atomic_with_generation_reset(background):
    owner = Owner(Clock())
    controller = owner._cache_health_controller
    generation = owner._cache_generation
    job_owner = object()
    if background:
        owner._refreshing_cache_keys["json:key"] = job_owner
        commit = lambda: controller.commit_refresh_success(
            "json:key", {"fresh": True}, generation, job_owner,
        )
    else:
        commit = lambda: controller.commit_foreground_success(
            "json:key", {"fresh": True}, generation,
        )
    original = owner._cache_set
    _assert_reset_waits_for_atomic_commit(
        owner, commit, (original, lambda value: setattr(owner, "_cache_set", value)),
    )


@pytest.mark.parametrize("background", (False, True))
def test_failure_commit_is_atomic_with_generation_reset(background):
    owner = Owner(Clock())
    controller = owner._cache_health_controller
    generation = owner._cache_generation
    job_owner = object()
    if background:
        owner._refreshing_cache_keys["json:key"] = job_owner
        commit = lambda: controller.commit_refresh_failure(
            "json:key", RuntimeError("failed"), generation, job_owner,
        )
    else:
        commit = lambda: controller.commit_foreground_failure(
            "json:key", RuntimeError("failed"), generation,
        )
    original = controller._record_failure_locked
    _assert_reset_waits_for_atomic_commit(
        owner, commit,
        (original, lambda value: setattr(controller, "_record_failure_locked", value)),
    )


def test_refresh_claim_observes_failure_recorded_before_lock_acquisition():
    owner = Owner(Clock())
    entered = threading.Event()
    result = []

    def schedule():
        entered.set()
        result.append(CONTRACT.v80_cache_schedule_refresh(
            owner, "json:key", lambda: None,
        ))

    with owner._cache_lock:
        worker = threading.Thread(target=schedule)
        worker.start()
        assert entered.wait(2)
        owner._cache_health_controller.remember_failure(
            "json:key", RuntimeError("blocked"),
        )
    worker.join(2)

    assert result == [False]
    assert owner._tasks.rows == []

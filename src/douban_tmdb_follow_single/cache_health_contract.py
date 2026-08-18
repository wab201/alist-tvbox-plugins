"""Unified stale-cache and failure-backoff policy for isolated V80 builds."""

import hashlib
import time


CACHE_FAILURE_MAX_ATTEMPTS = 6
CACHE_HEALTH_SNAPSHOT_LIMIT = 64


def _cache_failure_kind(exc):
    classifier = globals().get("v80_reliability_classify")
    if callable(classifier):
        try:
            return classifier(exc)
        except Exception:
            pass
    return "runtime"


def _cache_key_id(key):
    return hashlib.sha256(str(key).encode("utf-8")).hexdigest()[:16]


class CacheHealthController(object):
    """Own legacy failure backoff without owning cached payloads."""

    def __init__(self, owner, clock=None):
        self.owner = owner
        self._clock = time.time if clock is None else clock
        self._failure_kinds = {}

    def _retry_at(self, item):
        if len(item) >= 3:
            return item[1]
        return item[0] + self.owner.failure_ttl

    def _record_failure_locked(self, key, exc, now):
        owner = self.owner
        attempts = min(
            CACHE_FAILURE_MAX_ATTEMPTS,
            int(owner._failure_attempts.get(key, 0)) + 1,
        )
        delay = min(
            float(owner.failure_ttl),
            max(1.0, 2.0 ** (attempts - 1)),
        )
        owner._failure_attempts[key] = attempts
        owner._failures[key] = (now, now + delay, owner._short_error(exc))
        self._failure_kinds[key] = _cache_failure_kind(exc)
        return delay

    def remember_failure(self, key, exc):
        owner = self.owner
        now = float(self._clock())
        with owner._cache_lock:
            delay = self._record_failure_locked(key, exc, now)
        owner._diagnostic_event(
            "cache.failure", "WARN", exc=exc,
            cache_key=_cache_key_id(key), backoff=delay,
        )

    def clear_failure(self, key):
        owner = self.owner
        with owner._cache_lock:
            owner._failures.pop(key, None)
            owner._failure_attempts.pop(key, None)
            self._failure_kinds.pop(key, None)

    def failure_active(self, key):
        owner = self.owner
        now = float(self._clock())
        with owner._cache_lock:
            item = owner._failures.get(key)
            if not item:
                return False
            if now < self._retry_at(item):
                return True
            owner._failures.pop(key, None)
            owner._failure_attempts.pop(key, None)
            self._failure_kinds.pop(key, None)
            return False

    def raise_if_blocked(self, key):
        owner = self.owner
        now = float(self._clock())
        with owner._cache_lock:
            item = owner._failures.get(key)
            if not item:
                return
            if now < self._retry_at(item):
                message = item[-1]
            else:
                owner._failures.pop(key, None)
                owner._failure_attempts.pop(key, None)
                self._failure_kinds.pop(key, None)
                return
        raise RuntimeError(message)

    def reset(self):
        owner = self.owner
        with owner._cache_lock:
            owner._failures.clear()
            owner._failure_attempts.clear()
            self._failure_kinds.clear()

    def claim_refresh(self, key, job_owner):
        owner = self.owner
        now = float(self._clock())
        with owner._cache_lock:
            item = owner._failures.get(key)
            if item and now < self._retry_at(item):
                return None
            if item:
                owner._failures.pop(key, None)
                owner._failure_attempts.pop(key, None)
                self._failure_kinds.pop(key, None)
            if key in owner._refreshing_cache_keys:
                return None
            owner._refreshing_cache_keys[key] = job_owner
            return owner._cache_generation

    def commit_foreground_success(self, key, value, generation):
        owner = self.owner
        if owner._is_persistable_cache_key(key):
            owner._load_response_cache()
        with owner._cache_lock:
            if generation != owner._cache_generation:
                return False
            owner._cache_set(key, value)
            owner._failures.pop(key, None)
            owner._failure_attempts.pop(key, None)
            self._failure_kinds.pop(key, None)
            return True

    def commit_foreground_failure(self, key, exc, generation):
        owner = self.owner
        now = float(self._clock())
        with owner._cache_lock:
            if generation != owner._cache_generation:
                return False
            delay = self._record_failure_locked(key, exc, now)
        owner._diagnostic_event(
            "cache.failure", "WARN", exc=exc,
            cache_key=_cache_key_id(key), backoff=delay,
        )
        return True

    def commit_refresh_success(self, key, value, generation, job_owner):
        owner = self.owner
        if owner._is_persistable_cache_key(key):
            owner._load_response_cache()
        with owner._cache_lock:
            if not (
                    generation == owner._cache_generation
                    and owner._refreshing_cache_keys.get(key) is job_owner):
                return False
            owner._cache_set(key, value)
            owner._failures.pop(key, None)
            owner._failure_attempts.pop(key, None)
            self._failure_kinds.pop(key, None)
            return True

    def commit_refresh_failure(self, key, exc, generation, job_owner):
        owner = self.owner
        now = float(self._clock())
        with owner._cache_lock:
            if not (
                    generation == owner._cache_generation
                    and owner._refreshing_cache_keys.get(key) is job_owner):
                return False
            delay = self._record_failure_locked(key, exc, now)
        owner._diagnostic_event(
            "cache.failure", "WARN", exc=exc,
            cache_key=_cache_key_id(key), backoff=delay,
        )
        return True

    def snapshot(self, limit=32):
        count = max(1, min(int(limit), CACHE_HEALTH_SNAPSHOT_LIMIT))
        now = float(self._clock())
        with self.owner._cache_lock:
            rows = list(self.owner._failures.items())[-count:]
            attempts = dict(self.owner._failure_attempts)
            kinds = dict(self._failure_kinds)
        return [
            {
                "key": _cache_key_id(key),
                "attempts": int(attempts.get(key, 0)),
                "kind": kinds.get(key, "runtime"),
                "retry_in": max(0.0, float(self._retry_at(item)) - now),
                "active": now < self._retry_at(item),
            }
            for key, item in rows
        ]


def v80_cache_load(owner, key, ttl, loader, allow_stale=True):
    """Preserve the legacy fresh/stale/miss decision in one call."""

    cached = owner._cache_get(key, ttl)
    if cached is not None:
        return cached
    stale = None
    if allow_stale:
        stale = owner._cache_get(key, owner.stale_ttl, allow_expired=True)
        if stale is not None:
            owner._schedule_cache_refresh(key, loader)
            return stale
    owner._raise_cached_failure(key)
    with owner._cache_lock:
        generation = owner._cache_generation
    try:
        value = loader()
    except Exception as exc:
        owner._cache_health_controller.commit_foreground_failure(
            key, exc, generation,
        )
        raise
    owner._cache_health_controller.commit_foreground_success(
        key, value, generation,
    )
    return value


def v80_cache_schedule_refresh(owner, key, loader):
    """Run one background refresh and fence its cache-health commits."""

    job_owner = object()
    generation = owner._cache_health_controller.claim_refresh(key, job_owner)
    if generation is None:
        return False

    def worker():
        try:
            value = loader()
        except Exception as exc:
            owner._cache_health_controller.commit_refresh_failure(
                key, exc, generation, job_owner,
            )
        else:
            owner._cache_health_controller.commit_refresh_success(
                key, value, generation, job_owner,
            )
        finally:
            with owner._cache_lock:
                if owner._refreshing_cache_keys.get(key) is job_owner:
                    owner._refreshing_cache_keys.pop(key, None)

    try:
        owner._tasks.start_thread(worker, name="cache-refresh")
    except Exception:
        with owner._cache_lock:
            if owner._refreshing_cache_keys.get(key) is job_owner:
                owner._refreshing_cache_keys.pop(key, None)
        return False
    return True

#!/usr/bin/env python3
"""Insert the P3 cache-health seams into the isolated V80 source."""

import ast
import hashlib


class CacheHealthOverlayError(RuntimeError):
    pass


CACHE_COORDINATOR_ANCHOR = '''class _CacheCoordinator:
    """Coordinate cache failure state without changing the existing cache storage contract."""

    def __init__(self, owner):
        self.owner = owner

    def remember_failure(self, key, exc):
        owner = self.owner
        now = time.time()
        with owner._cache_lock:
            attempts = min(6, int(owner._failure_attempts.get(key, 0)) + 1)
            owner._failure_attempts[key] = attempts
            delay = min(float(owner.failure_ttl), max(1.0, 2.0 ** (attempts - 1)))
            owner._failures[key] = (now, now + delay, owner._short_error(exc))
        owner._diagnostic_event("cache.failure", "WARN", exc=exc, cache_key=key, backoff=delay)

    def clear_failure(self, key):
        owner = self.owner
        with owner._cache_lock:
            owner._failures.pop(key, None)
            owner._failure_attempts.pop(key, None)

    def failure_active(self, key):
        owner = self.owner
        with owner._cache_lock:
            item = owner._failures.get(key)
        if not item:
            return False
        retry_at = item[1] if len(item) >= 3 else item[0] + owner.failure_ttl
        if time.time() < retry_at:
            return True
        self.clear_failure(key)
        return False

    def raise_if_blocked(self, key):
        owner = self.owner
        with owner._cache_lock:
            item = owner._failures.get(key)
        if not item:
            return
        retry_at = item[1] if len(item) >= 3 else item[0] + owner.failure_ttl
        if time.time() < retry_at:
            raise RuntimeError(item[-1])
        self.clear_failure(key)
'''

CACHE_COORDINATOR_REPLACEMENT = '''class _CacheCoordinator:
    """Keep the V70 coordinator API while delegating V80 policy ownership."""

    def __init__(self, owner):
        self.owner = owner

    def remember_failure(self, key, exc):
        self.owner._cache_health_controller.remember_failure(key, exc)

    def clear_failure(self, key):
        self.owner._cache_health_controller.clear_failure(key)

    def failure_active(self, key):
        return self.owner._cache_health_controller.failure_active(key)

    def raise_if_blocked(self, key):
        self.owner._cache_health_controller.raise_if_blocked(key)
'''

TMDB_API_ANCHOR = '''    def api(self, path, params=None, ttl=None, allow_stale=True):
        owner = self.owner
        owner._require_tmdb_credentials()
        query = dict(params or {})
        query.setdefault("language", owner.tmdb_language)
        if not owner.tmdb_access_token:
            query["api_key"] = owner.tmdb_api_key
        cache_query = {key: value for key, value in query.items() if key != "api_key"}
        credential = owner.tmdb_access_token or owner.tmdb_api_key
        cache_scope = hashlib.sha256(
            (owner.tmdb_api_base.rstrip("/") + "|" + credential).encode("utf-8")
        ).hexdigest()[:16]
        key = "tmdb-json:%s:%s?%s" % (
            cache_scope, path, urlencode(sorted(cache_query.items()), doseq=True),
        )
        ttl = owner.list_cache_ttl if ttl is None else ttl
        cached = owner._cache_get(key, ttl)
        if cached is not None:
            return cached
        stale = owner._cache_get(key, owner.stale_ttl, allow_expired=True)
        if stale is not None and allow_stale:
            if not owner._has_cached_failure(key):
                owner._schedule_cache_refresh(key, lambda: owner._request_tmdb(path, query))
            return stale
        owner._raise_cached_failure(key)
        try:
            data = owner._request_tmdb(path, query)
            owner._cache_set(key, data)
            owner._clear_cached_failure(key)
            return data
        except Exception as exc:
            owner._remember_failure(key, exc)
            raise
'''

TMDB_API_REPLACEMENT = '''    def api(self, path, params=None, ttl=None, allow_stale=True):
        owner = self.owner
        owner._require_tmdb_credentials()
        query = dict(params or {})
        query.setdefault("language", owner.tmdb_language)
        if not owner.tmdb_access_token:
            query["api_key"] = owner.tmdb_api_key
        cache_query = {key: value for key, value in query.items() if key != "api_key"}
        credential = owner.tmdb_access_token or owner.tmdb_api_key
        cache_scope = hashlib.sha256(
            (owner.tmdb_api_base.rstrip("/") + "|" + credential).encode("utf-8")
        ).hexdigest()[:16]
        key = "tmdb-json:%s:%s?%s" % (
            cache_scope, path, urlencode(sorted(cache_query.items()), doseq=True),
        )
        ttl = owner.list_cache_ttl if ttl is None else ttl
        return v80_cache_load(
            owner, key, ttl,
            lambda: owner._request_tmdb(path, query),
            allow_stale=allow_stale,
        )
'''

CACHE_STATE_ANCHOR = '''        self._failures = {}
        self._failure_attempts = {}
        self._cache_coordinator = _CacheCoordinator(self)
        self._tmdb_client = _TMDBClient(self)
        self._follow_repository = _FollowRepository(self)
        self._history_coordinator = _HistoryCoordinator(self)
        self._douban_client = _DoubanClient(self)
        self._cache_lock = threading.RLock()
        self._cache_persist_lock = threading.RLock()
'''

CACHE_STATE_REPLACEMENT = CACHE_STATE_ANCHOR + '''        self._cache_health_controller = CacheHealthController(self)
'''

INIT_RESET_ANCHOR = '''        self._failures.clear()
        self._failure_attempts.clear()
'''

INIT_RESET_REPLACEMENT = '''        self._cache_health_controller.reset()
'''

DESTROY_RESET_ANCHOR = '''                self._flush_route_quality_sync()
                self._flush_response_cache_sync()
'''

DESTROY_RESET_REPLACEMENT = DESTROY_RESET_ANCHOR + '''                self._cache_health_controller.reset()
'''

GET_JSON_ANCHOR = '''    def _get_json(self, url, params=None, ttl=None):
        key = "json:" + url + "?" + urlencode(sorted((params or {}).items()), doseq=True)
        ttl = self.cache_ttl if ttl is None else ttl
        cached = self._cache_get(key, ttl)
        if cached is not None:
            return cached
        stale = self._cache_get(key, self.stale_ttl, allow_expired=True)
        if stale is not None:
            if not self._has_cached_failure(key):
                self._schedule_cache_refresh(key, lambda: self._request_json(url, params))
            return stale
        self._raise_cached_failure(key)
        try:
            payload = self._request_json(url, params)
            self._cache_set(key, payload)
            self._clear_cached_failure(key)
            return payload
        except Exception as exc:
            self._remember_failure(key, exc)
            if stale is not None:
                return stale
            raise
'''

GET_JSON_REPLACEMENT = '''    def _get_json(self, url, params=None, ttl=None):
        key = "json:" + url + "?" + urlencode(sorted((params or {}).items()), doseq=True)
        ttl = self.cache_ttl if ttl is None else ttl
        return v80_cache_load(
            self, key, ttl, lambda: self._request_json(url, params),
        )
'''

GET_TEXT_ANCHOR = '''    def _get_text(self, url, params=None, custom_key="", ttl=None):
        key = custom_key or ("text:" + url + "?" + urlencode(sorted((params or {}).items()), doseq=True))
        ttl = self.cache_ttl if ttl is None else ttl
        cached = self._cache_get(key, ttl)
        if cached is not None:
            return cached
        stale = self._cache_get(key, self.stale_ttl, allow_expired=True)
        if stale is not None:
            if not self._has_cached_failure(key):
                self._schedule_cache_refresh(key, lambda: self._request_text(url, params))
            return stale
        self._raise_cached_failure(key)
        try:
            text = self._request_text(url, params)
            self._cache_set(key, text)
            self._clear_cached_failure(key)
            return text
        except Exception as exc:
            self._remember_failure(key, exc)
            if stale is not None:
                return stale
            raise
'''

GET_TEXT_REPLACEMENT = '''    def _get_text(self, url, params=None, custom_key="", ttl=None):
        key = custom_key or ("text:" + url + "?" + urlencode(sorted((params or {}).items()), doseq=True))
        ttl = self.cache_ttl if ttl is None else ttl
        return v80_cache_load(
            self, key, ttl, lambda: self._request_text(url, params),
        )
'''

SCHEDULE_REFRESH_ANCHOR = '''    def _schedule_cache_refresh(self, key, loader):
        job_owner = object()
        with self._cache_lock:
            if key in self._refreshing_cache_keys:
                return False
            self._refreshing_cache_keys[key] = job_owner
            generation = self._cache_generation

        def worker():
            try:
                value = loader()
                with self._cache_lock:
                    active = generation == self._cache_generation
                if active:
                    self._cache_set(key, value)
                    self._clear_cached_failure(key)
            except Exception as exc:
                with self._cache_lock:
                    active = generation == self._cache_generation
                if active:
                    self._remember_failure(key, exc)
            finally:
                with self._cache_lock:
                    if self._refreshing_cache_keys.get(key) is job_owner:
                        self._refreshing_cache_keys.pop(key, None)

        try:
            self._tasks.start_thread(worker, name="cache-refresh")
        except Exception:
            with self._cache_lock:
                if self._refreshing_cache_keys.get(key) is job_owner:
                    self._refreshing_cache_keys.pop(key, None)
            return False
        return True
'''

SCHEDULE_REFRESH_REPLACEMENT = '''    def _schedule_cache_refresh(self, key, loader):
        return v80_cache_schedule_refresh(self, key, loader)
'''

HISTORY_REFRESH_CLAIM_ANCHOR = '''        with self._cache_lock:
            if cache_key in self._refreshing_cache_keys:
                with self._atvp_job_lock:
                    self._atvp_jobs.discard(job_kind)
                return False
            self._refreshing_cache_keys[cache_key] = job_owner
            generation = self._cache_generation
'''

HISTORY_REFRESH_CLAIM_REPLACEMENT = '''        with self._cache_lock:
            if lightweight and self._has_cached_failure(cache_key):
                with self._atvp_job_lock:
                    self._atvp_jobs.discard(job_kind)
                return False
            if cache_key in self._refreshing_cache_keys:
                with self._atvp_job_lock:
                    self._atvp_jobs.discard(job_kind)
                return False
            self._refreshing_cache_keys[cache_key] = job_owner
            generation = self._cache_generation
'''

INSERTIONS = (
    ("coordinator", CACHE_COORDINATOR_ANCHOR, CACHE_COORDINATOR_REPLACEMENT),
    ("tmdb", TMDB_API_ANCHOR, TMDB_API_REPLACEMENT),
    ("state", CACHE_STATE_ANCHOR, CACHE_STATE_REPLACEMENT),
    ("init-reset", INIT_RESET_ANCHOR, INIT_RESET_REPLACEMENT),
    ("destroy-reset", DESTROY_RESET_ANCHOR, DESTROY_RESET_REPLACEMENT),
    ("douban-json", GET_JSON_ANCHOR, GET_JSON_REPLACEMENT),
    ("douban-text", GET_TEXT_ANCHOR, GET_TEXT_REPLACEMENT),
    ("refresh", SCHEDULE_REFRESH_ANCHOR, SCHEDULE_REFRESH_REPLACEMENT),
    ("history", HISTORY_REFRESH_CLAIM_ANCHOR, HISTORY_REFRESH_CLAIM_REPLACEMENT),
)


def _replace_once(text, anchor, replacement, label):
    count = text.count(anchor)
    if count != 1:
        raise CacheHealthOverlayError(
            "cache-health overlay anchor %s must occur once, found %d"
            % (label, count)
        )
    return text.replace(anchor, replacement, 1)


def _class(tree, name):
    rows = [
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == name
    ]
    if len(rows) != 1:
        raise CacheHealthOverlayError(
            "cache-health overlay class %s must occur once" % name
        )
    return rows[0]


def _method(class_node, name):
    rows = [
        node for node in class_node.body
        if isinstance(node, ast.FunctionDef) and node.name == name
    ]
    if len(rows) != 1:
        raise CacheHealthOverlayError(
            "cache-health overlay method %s must occur once" % name
        )
    return rows[0]


def _named_call_count(node, name):
    return sum(
        isinstance(item, ast.Call)
        and isinstance(item.func, ast.Name)
        and item.func.id == name
        for item in ast.walk(node)
    )


def _controller_call_count(node, name):
    return sum(
        isinstance(item, ast.Call)
        and isinstance(item.func, ast.Attribute)
        and item.func.attr == name
        and isinstance(item.func.value, ast.Attribute)
        and item.func.value.attr == "_cache_health_controller"
        for item in ast.walk(node)
    )


def apply_cache_health_overlay(source):
    try:
        text = bytes(source).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CacheHealthOverlayError(
            "cache-health overlay input is not valid UTF-8"
        ) from exc
    input_bytes = text.encode("utf-8")
    for label, anchor, replacement in INSERTIONS:
        text = _replace_once(text, anchor, replacement, label)

    try:
        tree = ast.parse(text, filename="build/v80-dev/cache-health-overlay.py")
        compile(tree, "build/v80-dev/cache-health-overlay.py", "exec")
    except SyntaxError as exc:
        raise CacheHealthOverlayError(
            "cache-health overlay output is invalid: %s" % exc
        ) from exc

    spider = _class(tree, "Spider")
    tmdb = _class(tree, "_TMDBClient")
    coordinator = _class(tree, "_CacheCoordinator")
    checks = (
        (_method(tmdb, "api"), "v80_cache_load"),
        (_method(spider, "_get_json"), "v80_cache_load"),
        (_method(spider, "_get_text"), "v80_cache_load"),
        (_method(spider, "_schedule_cache_refresh"), "v80_cache_schedule_refresh"),
        (_method(spider, "__init__"), "CacheHealthController"),
    )
    for method, call_name in checks:
        if _named_call_count(method, call_name) != 1:
            raise CacheHealthOverlayError(
                "cache-health call %s must occur once at its seam" % call_name
            )
    for method_name, controller_name in (
            ("remember_failure", "remember_failure"),
            ("clear_failure", "clear_failure"),
            ("failure_active", "failure_active"),
            ("raise_if_blocked", "raise_if_blocked")):
        if _controller_call_count(_method(coordinator, method_name), controller_name) != 1:
            raise CacheHealthOverlayError(
                "cache-health coordinator delegation %s is invalid" % method_name
            )
    if _controller_call_count(_method(spider, "_init_locked"), "reset") != 1:
        raise CacheHealthOverlayError("cache-health init reset seam is invalid")
    if _controller_call_count(_method(spider, "destroy"), "reset") != 1:
        raise CacheHealthOverlayError("cache-health destroy reset seam is invalid")
    history = _method(spider, "_schedule_atvp_history_refresh")
    history_backoff = sum(
        isinstance(item, ast.Call)
        and isinstance(item.func, ast.Attribute)
        and item.func.attr == "_has_cached_failure"
        for item in ast.walk(history)
    )
    if history_backoff != 1:
        raise CacheHealthOverlayError("History snapshot backoff seam is invalid")

    output = text.encode("utf-8")
    return {
        "bytes": output,
        "input_size": len(input_bytes),
        "input_sha256": hashlib.sha256(input_bytes).hexdigest().upper(),
        "size": len(output),
        "sha256": hashlib.sha256(output).hexdigest().upper(),
        "insertions": tuple(label for label, _anchor, _replacement in INSERTIONS),
    }


def main():
    raise SystemExit("import apply_cache_health_overlay from the V80 build pipeline")


if __name__ == "__main__":
    main()

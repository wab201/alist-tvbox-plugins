import importlib.util
import threading
from pathlib import Path

import pytest
import requests


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "src" / "douban_tmdb_follow_single" / "history_sync_v145.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("v80_history_event_queue", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


HISTORY = _load_module()


class Response:
    def __init__(self, status=204, value=None):
        self.status_code = status
        self.value = value
        self.closed = False

    def close(self):
        self.closed = True


class Session:
    def __init__(self, responses, hook=None):
        self.responses = list(responses)
        self.hook = hook
        self.calls = []
        self.headers = {}

    def post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs))
        if self.hook:
            self.hook()
        value = self.responses.pop(0)
        if isinstance(value, Exception):
            raise value
        return value


class ManualTimer:
    def __init__(self, interval, function, args=None, kwargs=None):
        self.interval = interval
        self.function = function
        self.args = tuple(args or ())
        self.kwargs = dict(kwargs or {})
        self.daemon = False
        self.cancelled = False
        self.started = False

    def start(self):
        self.started = True

    def cancel(self):
        self.cancelled = True

    def fire(self):
        if not self.cancelled:
            self.function(*self.args, **self.kwargs)


class Tasks:
    def __init__(self):
        self.timers = []

    def track_timer(self, timer):
        self.timers.append(timer)

    def forget_timer(self, timer):
        if timer in self.timers:
            self.timers.remove(timer)


class Owner:
    HISTORY_ROW_LIMIT = 100
    HISTORY_RESPONSE_MAX_BYTES = 1024 * 1024

    def __init__(self, responses, username="user", cache=None, hook=None, tasks=None):
        self.cache = cache if cache is not None else {}
        self._atvp_session = Session(responses, hook=hook)
        self._history_context_lock = threading.RLock()
        self._history_primary_origin = "https://server"
        self._history_selected_origin = "https://server"
        self._v80_history_auth_origin = "https://server"
        self._v80_history_auth_token = "session-token"
        self._v80_history_auth_uid = 1
        self._v80_history_auth_username = username
        self._v80_history_auth_generation = 0
        self._cache_generation = 0
        self.atvp_api = "https://server"
        self.history_api = ""
        self.history_username = username
        self.history_password = "password"
        self.siteKey = "douban_tmdb_follow_single"
        self.timeout = 8
        self.verify_tls = True
        self.events = []
        self.cache_write_count = 0
        self.fail_cache_write_at = None
        self._tasks = tasks

    def _history_write_enabled(self):
        return bool(self.history_username and self.history_password)

    def _history_origin_candidates(self):
        return [self.atvp_api]

    @staticmethod
    def _history_retryable_transport_error(exc, method):
        return isinstance(exc, requests.ConnectionError) and method == "get"

    def _diagnostic_event(self, name, *args, **kwargs):
        self.events.append((name, args, kwargs))

    def getCache(self, key):
        return self.cache.get(key)

    def setCache(self, key, value):
        self.cache_write_count += 1
        if self.fail_cache_write_at == self.cache_write_count:
            raise RuntimeError("cache unavailable")
        self.cache[key] = value

    @staticmethod
    def _read_bounded_json_response(response, label, max_bytes):
        return response.value


def _row(position=10, updated_at=100, key="site-a@@@vod-1@@@7"):
    return {
        "key": key,
        "position": position,
        "duration": 100,
        "createTime": updated_at,
    }


def _queue_key(owner):
    scope = HISTORY._v80_history_queue_scope(owner)
    return HISTORY._v80_history_queue_cache_key(scope)


def test_pending_is_persisted_before_the_first_event_post():
    owner = Owner([Response()])

    def assert_persisted():
        state = owner.cache[_queue_key(owner)]
        assert state["events"][0]["status"] == "pending"

    owner._atvp_session.hook = assert_persisted

    assert HISTORY.v80_history_push(owner, [_row()], lambda rows: None) == 1
    state = HISTORY.v80_history_queue_snapshot(owner)
    assert state["events"] == []
    assert state["acknowledged"][0]["status"] == "ack"


def test_transient_failure_retries_once_with_the_same_idempotency_key(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(HISTORY.time, "time", lambda: now[0])
    owner = Owner([requests.Timeout("slow"), Response()])

    assert HISTORY.v80_history_push(owner, [_row()], lambda rows: None) == 0
    retry = HISTORY.v80_history_queue_snapshot(owner)["events"][0]
    assert retry["status"] == "retry"
    assert retry["attempts"] == 1
    assert retry["nextAttemptAt"] == 1005000
    first_key = owner._atvp_session.calls[0][2]["headers"]["Idempotency-Key"]

    now[0] = 1006.0
    assert HISTORY.v80_history_push(owner, [_row()], lambda rows: None) == 1
    second_key = owner._atvp_session.calls[1][2]["headers"]["Idempotency-Key"]
    assert second_key == first_key
    assert HISTORY.v80_history_queue_snapshot(owner)["events"] == []


def test_permanent_http_failure_moves_event_to_dead_letter():
    owner = Owner([Response(422)])

    assert HISTORY.v80_history_push(owner, [_row()], lambda rows: None) == 0
    state = HISTORY.v80_history_queue_snapshot(owner)
    assert state["events"] == []
    assert state["deadLetter"][0]["status"] == "dead-letter"
    assert state["deadLetter"][0]["lastError"] == "HTTP 422"


def test_newer_same_timestamp_progress_supersedes_retry_monotonically():
    owner = Owner([Response(500), Response()])

    HISTORY.v80_history_push(owner, [_row(position=10)], lambda rows: None)
    old = HISTORY.v80_history_queue_snapshot(owner)["events"][0]
    assert old["payload"]["updatedAt"] == 100

    assert HISTORY.v80_history_push(owner, [_row(position=20)], lambda rows: None) == 1
    posted = owner._atvp_session.calls[1][2]["json"]
    assert posted["positionMs"] == 20
    assert posted["updatedAt"] == 101
    state = HISTORY.v80_history_queue_snapshot(owner)
    assert state["events"] == []
    assert state["acknowledged"][-1]["rank"][0] == 101


def test_delete_retry_freezes_payload_and_idempotency_key(monkeypatch):
    now = [2000.0]
    monkeypatch.setattr(HISTORY.time, "time", lambda: now[0])
    owner = Owner([requests.ConnectionError("offline"), Response()])
    key = "site-a@@@vod-1@@@7"

    assert HISTORY.v80_history_delete(owner, key, lambda value: True) is True
    first_payload = dict(owner._atvp_session.calls[0][2]["json"])
    first_key = owner._atvp_session.calls[0][2]["headers"]["Idempotency-Key"]
    assert first_payload["action"] == "delete"
    assert first_payload["deletedAt"] == 2000000

    now[0] = 2006.0
    scope = HISTORY._v80_history_queue_scope(owner)
    assert HISTORY._v80_history_queue_drain(
        owner, scope=scope, expected_generation=owner._cache_generation,
    ) == 1
    assert owner._atvp_session.calls[1][2]["json"] == first_payload
    assert owner._atvp_session.calls[1][2]["headers"]["Idempotency-Key"] == first_key


def test_explicit_delete_advances_past_newer_ack_when_clock_moves_back(monkeypatch):
    now = [10.0]
    monkeypatch.setattr(HISTORY.time, "time", lambda: now[0])
    owner = Owner([Response(), Response()])
    key = "site-a@@@vod-1@@@7"

    assert HISTORY.v80_history_push(
        owner, [_row(position=50, updated_at=50000, key=key)], lambda rows: None,
    ) == 1
    assert HISTORY.v80_history_delete(owner, key, lambda value: True) is True

    delete_payload = owner._atvp_session.calls[1][2]["json"]
    assert delete_payload["deletedAt"] == 50001
    assert HISTORY.v80_history_queue_snapshot(owner)["acknowledged"][-1]["action"] == "delete"


def test_ack_persistence_failure_keeps_the_same_pending_event_without_resending():
    owner = Owner([Response(), Response()])
    owner.fail_cache_write_at = 2

    with pytest.raises(RuntimeError, match="队列保存失败"):
        HISTORY.v80_history_push(owner, [_row()], lambda rows: None)
    pending = HISTORY.v80_history_queue_snapshot(owner)["events"][0]
    first_key = owner._atvp_session.calls[0][2]["headers"]["Idempotency-Key"]
    assert pending["status"] == "pending"

    owner.fail_cache_write_at = None
    assert HISTORY.v80_history_push(owner, [_row()], lambda rows: None) == 1
    assert len(owner._atvp_session.calls) == 1
    assert HISTORY.v80_history_queue_snapshot(owner)["acknowledged"][0]["id"] == first_key


def test_restart_recovers_retry_and_acknowledges_with_the_same_event_id(monkeypatch):
    now = [3000.0]
    monkeypatch.setattr(HISTORY.time, "time", lambda: now[0])
    cache = {}
    first = Owner([Response(500)], cache=cache)
    HISTORY.v80_history_push(first, [_row()], lambda rows: None)
    event_id = HISTORY.v80_history_queue_snapshot(first)["events"][0]["id"]

    now[0] = 3006.0
    restarted = Owner([Response()], cache=cache)
    assert HISTORY.v80_history_push(restarted, [_row()], lambda rows: None) == 1
    assert restarted._atvp_session.calls[0][2]["headers"]["Idempotency-Key"] == event_id
    assert HISTORY.v80_history_queue_snapshot(restarted)["events"] == []


def test_retry_budget_is_finite_and_exhaustion_moves_to_dead_letter(monkeypatch):
    now = [4000.0]
    monkeypatch.setattr(HISTORY.time, "time", lambda: now[0])
    owner = Owner([Response(500) for _ in range(HISTORY.HISTORY_EVENT_QUEUE_MAX_ATTEMPTS)])

    HISTORY.v80_history_push(owner, [_row()], lambda rows: None)
    scope = HISTORY._v80_history_queue_scope(owner)
    for _ in range(HISTORY.HISTORY_EVENT_QUEUE_MAX_ATTEMPTS - 1):
        retry = HISTORY.v80_history_queue_snapshot(owner)["events"][0]
        now[0] = retry["nextAttemptAt"] / 1000.0 + 0.001
        HISTORY._v80_history_queue_drain(
            owner, scope=scope, expected_generation=owner._cache_generation,
        )

    state = HISTORY.v80_history_queue_snapshot(owner)
    assert state["events"] == []
    assert state["deadLetter"][0]["attempts"] == HISTORY.HISTORY_EVENT_QUEUE_MAX_ATTEMPTS
    assert len(owner._atvp_session.calls) == HISTORY.HISTORY_EVENT_QUEUE_MAX_ATTEMPTS


def test_queue_scope_isolated_by_backend_account_without_storing_username():
    cache = {}
    first = Owner([Response(500)], username="alice", cache=cache)
    second = Owner([], username="bob", cache=cache)

    HISTORY.v80_history_push(first, [_row()], lambda rows: None)

    assert HISTORY.v80_history_queue_snapshot(first)["events"]
    assert HISTORY.v80_history_queue_snapshot(second)["events"] == []
    assert "alice" not in " ".join(cache)
    assert "bob" not in " ".join(cache)


def test_old_generation_response_cannot_ack_persisted_event():
    owner = Owner([])

    def advance_generation():
        owner._cache_generation += 1

    owner._atvp_session = Session([Response()], hook=advance_generation)

    with pytest.raises(HISTORY._V80HistoryQueueCancelled):
        HISTORY.v80_history_push(owner, [_row()], lambda rows: None)
    state = HISTORY.v80_history_queue_snapshot(owner)
    assert state["events"][0]["status"] == "pending"
    assert state["acknowledged"] == []


def test_full_queue_rejects_new_identity_without_dropping_pending(monkeypatch):
    monkeypatch.setattr(HISTORY, "HISTORY_EVENT_QUEUE_MAX_ACTIVE", 1)
    owner = Owner([Response(500)])
    HISTORY.v80_history_push(owner, [_row()], lambda rows: None)

    with pytest.raises(RuntimeError, match="队列已满"):
        HISTORY.v80_history_push(
            owner, [_row(key="site-a@@@vod-2@@@7")], lambda rows: None,
        )
    state = HISTORY.v80_history_queue_snapshot(owner)
    assert len(state["events"]) == 1
    assert state["events"][0]["payload"]["vodId"] == "vod-1"


def test_bulk_queue_defers_overflow_and_drains_all_rows_with_the_active_cap():
    rows = [
        _row(position=index, updated_at=1000 + index, key="site-a@@@vod-%s@@@7" % index)
        for index in range(300)
    ]
    owner = Owner([Response() for _ in rows])
    owner.HISTORY_ROW_LIMIT = len(rows)

    assert HISTORY.v80_history_push(owner, rows, lambda values: None) == 8
    state = HISTORY.v80_history_queue_snapshot(owner)
    deferred = HISTORY._v80_history_queue_deferred_items(
        owner, HISTORY._v80_history_queue_scope(owner),
    )
    assert len(owner._atvp_session.calls) == HISTORY.HISTORY_EVENT_QUEUE_DRAIN_LIMIT
    assert len(state["events"]) <= HISTORY.HISTORY_EVENT_QUEUE_MAX_ACTIVE
    assert len(state["acknowledged"]) + len(state["events"]) + len(deferred) == len(rows)

    while state["events"] or deferred:
        acknowledged = HISTORY._v80_history_queue_drain(
            owner,
            scope=HISTORY._v80_history_queue_scope(owner),
            expected_generation=owner._cache_generation,
        )
        assert acknowledged <= HISTORY.HISTORY_EVENT_QUEUE_DRAIN_LIMIT
        state = HISTORY.v80_history_queue_snapshot(owner)
        deferred = HISTORY._v80_history_queue_deferred_items(
            owner, HISTORY._v80_history_queue_scope(owner),
        )
        assert len(state["events"]) <= HISTORY.HISTORY_EVENT_QUEUE_MAX_ACTIVE

    assert len(owner._atvp_session.calls) == len(rows)
    assert len(state["acknowledged"]) == len(rows)


def test_bulk_deferred_rows_survive_restart_and_drain_without_a_new_push():
    rows = [
        _row(position=index, updated_at=1000 + index, key="site-a@@@vod-%s@@@7" % index)
        for index in range(300)
    ]
    cache = {}
    first = Owner([Response() for _ in rows], cache=cache)
    first.HISTORY_ROW_LIMIT = len(rows)
    HISTORY.v80_history_push(first, rows, lambda values: None)
    first_state = HISTORY.v80_history_queue_snapshot(first)
    assert first_state["deferred"]

    restarted = Owner([Response() for _ in rows], cache=cache)
    restarted.HISTORY_ROW_LIMIT = len(rows)
    restarted_state = HISTORY.v80_history_queue_snapshot(restarted)
    assert len(restarted_state["deferred"]) == len(first_state["deferred"])

    scope = HISTORY._v80_history_queue_scope(restarted)
    while restarted_state["events"] or restarted_state["deferred"]:
        HISTORY._v80_history_queue_drain(
            restarted, scope=scope, expected_generation=restarted._cache_generation,
        )
        restarted_state = HISTORY.v80_history_queue_snapshot(restarted)

    assert len(restarted_state["acknowledged"]) == len(rows)
    assert len(restarted._atvp_session.calls) == len(rows) - len(first._atvp_session.calls)


def test_uid_rotation_quarantines_persisted_deferred_rows_before_new_account_push(monkeypatch):
    monkeypatch.setattr(HISTORY, "HISTORY_EVENT_QUEUE_MAX_ACTIVE", 1)
    cache = {}
    owner = Owner([Response(500), Response()], cache=cache)
    owner.HISTORY_ROW_LIMIT = 3
    rows = [
        _row(position=index, updated_at=1000 + index, key="site-a@@@vod-%s@@@7" % index)
        for index in range(3)
    ]
    HISTORY.v80_history_push(owner, rows, lambda values: None)
    assert HISTORY.v80_history_queue_snapshot(owner)["deferred"]

    owner._v80_history_auth_uid = 2
    assert HISTORY.v80_history_queue_start(owner) is False
    state = HISTORY.v80_history_queue_snapshot(owner)
    assert state["accountUid"] == 2
    assert state["events"] == []
    assert state["deferred"] == []

    assert HISTORY.v80_history_push(
        owner, [_row(key="site-a@@@new-account@@@7")], lambda values: None,
    ) == 1
    assert owner._atvp_session.calls[-1][2]["json"]["vodId"] == "new-account"
    assert all(
        call[2]["json"].get("vodId") != "vod-0"
        for call in owner._atvp_session.calls[1:]
    )


def test_delete_replaces_a_deferred_upsert_for_the_same_identity():
    original_max_active = HISTORY.HISTORY_EVENT_QUEUE_MAX_ACTIVE
    HISTORY.HISTORY_EVENT_QUEUE_MAX_ACTIVE = 1
    try:
        owner = Owner([Response(500), Response()])
        owner.HISTORY_ROW_LIMIT = 3
        rows = [
            _row(position=index, updated_at=1000 + index, key="site-a@@@vod-%s@@@7" % index)
            for index in range(3)
        ]
        HISTORY.v80_history_push(owner, rows, lambda values: None)
        deferred = HISTORY.v80_history_queue_snapshot(owner)["deferred"]
        target = deferred[0]["payload"]["vodId"]

        assert HISTORY.v80_history_delete(
            owner, "site-a@@@%s@@@7" % target, lambda value: None,
        ) is True
        replacement = next(
            item for item in HISTORY.v80_history_queue_snapshot(owner)["deferred"]
            if item["payload"]["vodId"] == target
        )
        assert replacement["action"] == "delete"
    finally:
        HISTORY.HISTORY_EVENT_QUEUE_MAX_ACTIVE = original_max_active


def test_repeated_bulk_push_keeps_equal_deferred_rows_until_they_are_sent():
    original_max_active = HISTORY.HISTORY_EVENT_QUEUE_MAX_ACTIVE
    HISTORY.HISTORY_EVENT_QUEUE_MAX_ACTIVE = 1
    try:
        owner = Owner([Response(500), Response(), Response()])
        owner.HISTORY_ROW_LIMIT = 3
        rows = [
            _row(position=index, updated_at=1000 + index, key="site-a@@@vod-%s@@@7" % index)
            for index in range(3)
        ]
        HISTORY.v80_history_push(owner, rows, lambda values: None)
        first = HISTORY.v80_history_queue_snapshot(owner)
        assert len(first["deferred"]) == 2

        HISTORY.v80_history_push(owner, rows, lambda values: None)
        second = HISTORY.v80_history_queue_snapshot(owner)
        assert len(second["deferred"]) == 2
        assert len(owner._atvp_session.calls) == 1
    finally:
        HISTORY.HISTORY_EVENT_QUEUE_MAX_ACTIVE = original_max_active


def test_single_upsert_merges_a_newer_deferred_identity_when_queue_is_full():
    original_max_active = HISTORY.HISTORY_EVENT_QUEUE_MAX_ACTIVE
    HISTORY.HISTORY_EVENT_QUEUE_MAX_ACTIVE = 1
    try:
        owner = Owner([Response(500)])
        owner.HISTORY_ROW_LIMIT = 3
        rows = [
            _row(position=index, updated_at=1000 + index, key="site-a@@@vod-%s@@@7" % index)
            for index in range(3)
        ]
        HISTORY.v80_history_push(owner, rows, lambda values: None)
        target = HISTORY.v80_history_queue_snapshot(owner)["deferred"][0]["payload"]["vodId"]

        assert HISTORY.v80_history_push(
            owner,
            [_row(position=99, updated_at=2000, key="site-a@@@%s@@@7" % target)],
            lambda values: None,
        ) == 0
        updated = next(
            item for item in HISTORY.v80_history_queue_snapshot(owner)["deferred"]
            if item["payload"]["vodId"] == target
        )
        assert updated["payload"]["positionMs"] == 99
        assert updated["payload"]["updatedAt"] == 2000
    finally:
        HISTORY.HISTORY_EVENT_QUEUE_MAX_ACTIVE = original_max_active


def test_uid_rotation_clears_a_pending_transition_before_reusing_event_id():
    owner = Owner([Response()])
    scope = HISTORY._v80_history_queue_scope(owner)
    events = HISTORY.v80_history_events([_row()], owner=owner)
    added = HISTORY._v80_history_queue_enqueue(owner, "upsert", events, scope=scope)
    owner._v80_history_queue_transition_pending = {
        (scope, added[0]): ("ack", "old-account")
    }
    owner._v80_history_auth_uid = 2

    assert HISTORY.v80_history_push(owner, [_row()], lambda values: None) == 1
    assert len(owner._atvp_session.calls) == 1
    assert owner._v80_history_queue_transition_pending == {}


def test_ack_high_water_covers_the_full_history_sync_window():
    rows = [
        _row(position=index, updated_at=1000 + index, key="site-a@@@vod-%s@@@7" % index)
        for index in range(100)
    ]
    owner = Owner([Response() for _ in rows])

    for _ in range(20):
        HISTORY.v80_history_push(owner, rows, lambda values: None)
        if not HISTORY.v80_history_queue_snapshot(owner)["events"]:
            break

    state = HISTORY.v80_history_queue_snapshot(owner)
    assert len(state["acknowledged"]) == owner.HISTORY_ROW_LIMIT
    calls = len(owner._atvp_session.calls)
    assert HISTORY.v80_history_push(owner, rows, lambda values: None) == 0
    assert len(owner._atvp_session.calls) == calls


def test_ack_high_water_keeps_distinct_identities_during_one_identity_churn():
    rows = [
        _row(position=index, updated_at=1000 + index, key="site-a@@@vod-%s@@@7" % index)
        for index in range(100)
    ]
    owner = Owner([Response() for _ in range(200)])
    for _ in range(20):
        HISTORY.v80_history_push(owner, rows, lambda values: None)
        if not HISTORY.v80_history_queue_snapshot(owner)["events"]:
            break

    for offset in range(100):
        assert HISTORY.v80_history_push(
            owner,
            [_row(position=offset, updated_at=10000 + offset, key="site-a@@@vod-0@@@7")],
            lambda values: None,
        ) == 1

    state = HISTORY.v80_history_queue_snapshot(owner)
    assert len(state["acknowledged"]) == owner.HISTORY_ROW_LIMIT
    assert len({item["identity"] for item in state["acknowledged"]}) == owner.HISTORY_ROW_LIMIT
    calls = len(owner._atvp_session.calls)
    assert HISTORY.v80_history_push(owner, rows, lambda values: None) == 0
    assert len(owner._atvp_session.calls) == calls


def test_login_http_500_is_retried_instead_of_dead_lettered():
    owner = Owner([Response(500)])
    owner._v80_history_auth_origin = ""
    owner._v80_history_auth_token = ""
    owner._v80_history_auth_uid = 0

    assert HISTORY.v80_history_push(owner, [_row()], lambda rows: None) == 0
    state = HISTORY.v80_history_queue_snapshot(owner)
    assert state["events"][0]["status"] == "retry"
    assert state["events"][0]["attempts"] == 1
    assert state["deadLetter"] == []


def test_legacy_http_500_is_retried_after_event_route_fallback():
    owner = Owner([Response(404)])

    def legacy_push(rows):
        raise HISTORY._V80HistoryHttpError(500, "legacy HTTP 500")

    assert HISTORY.v80_history_push(owner, [_row()], legacy_push) == 0
    state = HISTORY.v80_history_queue_snapshot(owner)
    assert state["events"][0]["status"] == "retry"
    assert state["deadLetter"] == []


def test_generation_change_during_timeout_does_not_consume_retry_budget():
    owner = Owner([])

    def advance_generation():
        owner._cache_generation += 1

    owner._atvp_session = Session([requests.Timeout("slow")], hook=advance_generation)
    with pytest.raises(HISTORY._V80HistoryQueueCancelled):
        HISTORY.v80_history_push(owner, [_row()], lambda rows: None)

    state = HISTORY.v80_history_queue_snapshot(owner)
    assert state["events"][0]["status"] == "pending"
    assert state["events"][0]["attempts"] == 0


def test_ack_persistence_failure_recovers_in_background_without_second_post(monkeypatch):
    monkeypatch.setattr(HISTORY.threading, "Timer", ManualTimer)
    tasks = Tasks()
    owner = Owner([Response()], tasks=tasks)
    owner.fail_cache_write_at = 2

    with pytest.raises(HISTORY._V80HistoryQueuePersistenceError):
        HISTORY.v80_history_push(owner, [_row()], lambda rows: None)
    assert len(owner._atvp_session.calls) == 1
    timer = owner._v80_history_queue_timer
    assert timer.started is True

    owner.fail_cache_write_at = None
    timer.fire()
    state = HISTORY.v80_history_queue_snapshot(owner)
    assert state["events"] == []
    assert len(state["acknowledged"]) == 1
    assert len(owner._atvp_session.calls) == 1


def test_uid_binding_persistence_failure_does_not_dead_letter_unsent_event(monkeypatch):
    monkeypatch.setattr(HISTORY.threading, "Timer", ManualTimer)
    tasks = Tasks()
    owner = Owner([
        Response(200, {"authorities": ["USER"], "token": "test-token", "id": 1}),
        Response(),
    ], tasks=tasks)
    owner._v80_history_auth_origin = ""
    owner._v80_history_auth_token = ""
    owner._v80_history_auth_uid = 0
    scope = HISTORY._v80_history_queue_scope(owner)
    added = HISTORY._v80_history_queue_enqueue(
        owner, "upsert", HISTORY.v80_history_events([_row()], owner=owner), scope=scope,
    )
    owner.fail_cache_write_at = 2

    with pytest.raises(HISTORY._V80HistoryQueuePersistenceError):
        HISTORY._v80_history_queue_drain(
            owner, scope=scope, preferred_ids=added,
            expected_generation=owner._cache_generation,
        )
    state = HISTORY.v80_history_queue_snapshot(owner)
    assert state["events"][0]["status"] == "pending"
    assert state["events"][0]["attempts"] == 0
    assert state["deadLetter"] == []
    assert len(owner._atvp_session.calls) == 1

    owner.fail_cache_write_at = None
    owner._v80_history_queue_timer.fire()
    state = HISTORY.v80_history_queue_snapshot(owner)
    assert state["events"] == []
    assert len(state["acknowledged"]) == 1
    assert len(owner._atvp_session.calls) == 2


def test_dead_letter_persistence_failure_recovers_without_reposting(monkeypatch):
    monkeypatch.setattr(HISTORY.threading, "Timer", ManualTimer)
    tasks = Tasks()
    owner = Owner([Response(422)], tasks=tasks)
    owner.fail_cache_write_at = 2

    with pytest.raises(HISTORY._V80HistoryQueuePersistenceError):
        HISTORY.v80_history_push(owner, [_row()], lambda rows: None)
    state = HISTORY.v80_history_queue_snapshot(owner)
    assert state["events"][0]["status"] == "pending"
    assert state["events"][0]["attempts"] == 0
    assert len(owner._atvp_session.calls) == 1

    owner.fail_cache_write_at = None
    owner._v80_history_queue_timer.fire()
    state = HISTORY.v80_history_queue_snapshot(owner)
    assert state["events"] == []
    assert state["deadLetter"][0]["attempts"] == 1
    assert len(owner._atvp_session.calls) == 1


def test_start_recovers_persisted_retry_without_a_new_push(monkeypatch):
    now = [5000.0]
    monkeypatch.setattr(HISTORY.time, "time", lambda: now[0])
    monkeypatch.setattr(HISTORY.threading, "Timer", ManualTimer)
    cache = {}
    first = Owner([Response(500)], cache=cache)
    HISTORY.v80_history_push(first, [_row()], lambda rows: None)
    event_id = HISTORY.v80_history_queue_snapshot(first)["events"][0]["id"]

    now[0] = 5006.0
    tasks = Tasks()
    restarted = Owner([Response()], cache=cache, tasks=tasks)
    assert HISTORY.v80_history_queue_start(restarted) is True
    timer = restarted._v80_history_queue_timer
    timer.fire()

    assert restarted._atvp_session.calls[0][2]["headers"]["Idempotency-Key"] == event_id
    assert HISTORY.v80_history_queue_snapshot(restarted)["events"] == []


def test_corrupt_queue_snapshot_is_quarantined_and_replaced():
    owner = Owner([Response()])
    owner.cache[_queue_key(owner)] = {
        "version": 1,
        "scope": HISTORY._v80_history_queue_scope(owner),
        "nextSequence": 2,
        "events": [{"broken": True}],
        "acknowledged": [],
        "deadLetter": [],
    }

    state = HISTORY.v80_history_queue_snapshot(owner)
    assert state["events"] == []
    assert owner._v80_history_queue_quarantine[-1]["reason"]
    assert HISTORY.v80_history_push(owner, [_row()], lambda rows: None) == 1


def test_account_uid_change_isolates_old_pending_events():
    cache = {}
    first = Owner([Response(500)], cache=cache)
    HISTORY.v80_history_push(first, [_row()], lambda rows: None)
    assert HISTORY.v80_history_queue_snapshot(first)["events"]

    replacement = Owner([], cache=cache)
    replacement._v80_history_auth_uid = 2
    assert HISTORY.v80_history_queue_start(replacement) is False
    state = HISTORY.v80_history_queue_snapshot(replacement)
    assert state["accountUid"] == 2
    assert state["events"] == []
    assert replacement._atvp_session.calls == []


def test_forced_relogin_rechecks_uid_before_resending_event():
    owner = Owner([
        Response(401),
        Response(200, {"authorities": ["USER"], "token": "test-replacement", "id": 2}),
        Response(),
    ])

    with pytest.raises(HISTORY._V80HistoryQueueCancelled):
        HISTORY.v80_history_push(owner, [_row()], lambda rows: None)

    state = HISTORY.v80_history_queue_snapshot(owner)
    assert state["accountUid"] == 2
    assert state["events"] == []
    assert len(owner._atvp_session.calls) == 2

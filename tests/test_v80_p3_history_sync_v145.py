import importlib.util
import sys
import threading
import types
from pathlib import Path

import pytest
import requests


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "src" / "douban_tmdb_follow_single" / "history_sync_v145.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("v80_history_sync_v145", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


HISTORY = _load_module()
REAL_ACTIVE_CID = HISTORY.v80_history_active_cid


@pytest.fixture(autouse=True)
def _active_cid(monkeypatch):
    monkeypatch.setattr(
        HISTORY, "v80_history_active_cid",
        lambda owner: max(0, int(getattr(owner, "_v80_history_cid", 0))),
    )


class Response:
    def __init__(self, status=200, payload=None):
        self.status_code = status
        self.payload = payload
        self.closed = False

    def close(self):
        self.closed = True


class Session:
    def __init__(self, responses=None):
        self.headers = {}
        self.responses = list(responses or [])
        self.calls = []

    def _send(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        value = self.responses.pop(0)
        if isinstance(value, Exception):
            raise value
        return value

    def get(self, url, **kwargs):
        return self._send("GET", url, **kwargs)

    def post(self, url, **kwargs):
        return self._send("POST", url, **kwargs)


class Owner:
    HISTORY_ROW_LIMIT = 100
    HISTORY_RESPONSE_MAX_BYTES = 1024 * 1024
    HISTORY_FIELDS = (
        "key", "vodPic", "vodName", "vodFlag", "vodRemarks", "episodeUrl",
        "revSort", "revPlay", "createTime", "opening", "ending", "position",
        "duration", "speed", "scale", "cid", "episode", "uid",
    )

    def __init__(self, responses, credentials=True, origins=None):
        self._atvp_session = Session(responses)
        self._history_context_lock = threading.RLock()
        self.atvp_api = "https://server"
        self.history_api = ""
        self._history_primary_origin = self.atvp_api
        self._origins = list(origins or [self.atvp_api])
        self._history_selected_origin = self._origins[0]
        self._history_auth_token = "test-session-token" if credentials else ""
        self._v80_history_auth_token = self._history_auth_token
        self._v80_history_auth_origin = self._origins[0] if credentials else ""
        self._v80_history_auth_uid = 1
        self._v80_history_auth_username = "user" if credentials else ""
        self._v80_history_auth_generation = 0
        self._cache_generation = 0
        self._v80_history_cid = 7
        self.history_username = "user" if credentials else ""
        self.history_password = "pass" if credentials else ""
        self.siteKey = "douban_tmdb_follow_single"
        self.timeout = 8
        self.verify_tls = True
        self.events = []
        self.read_error = None
        self.cache = {}
        self.local_rows = []
        self.local_deleted_keys = []

    def _history_write_enabled(self):
        return bool(self.history_username and self.history_password)

    def _history_origin_candidates(self):
        return list(self._origins)

    @staticmethod
    def _history_retryable_transport_error(exc, method):
        return isinstance(exc, (requests.ConnectionError, requests.Timeout)) and method == "get"

    def _read_bounded_json_response(self, response, _label, max_bytes=None):
        if self.read_error:
            raise self.read_error
        response.close()
        return response.payload

    @staticmethod
    def _normalize_history_rows(rows):
        return rows

    def _diagnostic_event(self, name, *args, **kwargs):
        self.events.append((name, args, kwargs))

    def getCache(self, key):
        return self.cache.get(key)

    def setCache(self, key, value):
        self.cache[key] = value

    def _capture_native_history(self):
        return list(self.local_rows)

    def _native_history_delete_java(self, keys):
        keys = list(dict.fromkeys(keys))
        self.local_deleted_keys.extend(keys)
        self.local_rows = [row for row in self.local_rows if row.get("key") not in keys]
        return len(keys)

    @staticmethod
    def _history_identity(row):
        key = str(row.get("key") or "") if isinstance(row, dict) else ""
        parts = key.split("@@@")
        return (parts[0], parts[1]) if len(parts) >= 2 and parts[0] and parts[1] else None


def _login_payload(token="test-renewed-session-token", uid=1):
    return {
        "id": uid,
        "token": token,
        "authorities": [{"authority": "USER"}],
    }


def _page(items=None, deleted=None, next_since="1"):
    return {"items": list(items or []), "deleted": list(deleted or []), "nextSince": next_since}


def test_legacy_key_mapping_and_plugin_identity_fallbacks():
    owner = Owner([])
    site = HISTORY.v80_history_events([{"key": "site-a@@@vod-9@@@3"}], owner=owner)[0]
    plugin = HISTORY.v80_history_events([{
        "key": "douban_tmdb_follow_single@@@tmdb:tv:7@@@3",
    }], owner=owner)[0]
    fallback_plugin = HISTORY.v80_history_events([{"key": "plugin-9@@@vod@@@3"}], owner=owner)[0]
    bare = HISTORY.v80_history_events([{"key": "vod-only"}], owner=owner)[0]

    assert (site["sourceKind"], site["sourceKey"], site["vodId"]) == ("site", "site-a", "vod-9")
    assert (plugin["sourceKind"], plugin["sourceKey"], plugin["vodId"]) == (
        "spider_plugin", "douban_tmdb_follow_single", "tmdb:tv:7",
    )
    assert fallback_plugin["sourceKind"] == "spider_plugin"
    assert (bare["sourceKind"], bare["sourceKey"], bare["vodId"]) == (
        "site", "csp_AList", "vod-only",
    )


def test_explicit_unknown_source_kind_is_rejected_instead_of_reclassified():
    owner = Owner([Response(payload=_page(items=[{
        "sourceKind": "telegram", "sourceKey": "x", "vodId": "v",
    }]))])

    with pytest.raises(RuntimeError):
        HISTORY.v80_history_fetch(owner, lambda: None, stateful=True)
    assert HISTORY.PLAYBACK_STATE_CACHE_KEY not in owner.cache


def test_dedupe_keeps_newest_monotonic_progress_and_picture():
    rows = [
        {"key": "s@@@v@@@1", "createTime": 10, "position": 90, "duration": 100},
        {"key": "s@@@v@@@1", "createTime": 11, "position": 20, "duration": 100},
        {"key": "s@@@v@@@1", "createTime": 11, "position": 30, "duration": 100, "vodPic": "p.jpg"},
    ]

    assert HISTORY.v80_history_events(rows) == [{
        "sourceKind": "site", "sourceKey": "s", "vodId": "v",
        "vodName": "", "vodPic": "p.jpg", "vodFlag": "", "episodeName": "", "episodeUrl": "",
        "episode": -1, "positionMs": 30, "durationMs": 100,
        "openingMs": 0, "endingMs": 0, "speed": 1.0, "updatedAt": 11,
    }]


def test_playback_page_maps_to_active_fongmi_cid():
    owner = Owner([])
    rows = HISTORY.v80_history_rows_from_page(_page(items=[{
        "sourceKind": "site", "sourceKey": "site-a", "vodId": "vod-1",
        "vodName": "Title", "episodeName": "E03", "positionMs": 12,
        "durationMs": 100, "updatedAt": 99,
    }]), cid=HISTORY.v80_history_active_cid(owner), owner=owner)

    assert rows[0]["key"] == "site-a@@@vod-1@@@7"
    assert rows[0]["cid"] == 7
    assert rows[0]["revSort"] is False
    assert rows[0]["revPlay"] is False


def test_1461_optional_drive_and_navigation_fields_keep_legacy_import_forward_compatible():
    owner = Owner([])
    rows = HISTORY.v80_history_rows_from_page(_page(items=[{
        "sourceKind": "spider_plugin",
        "sourceKey": "plugin-9",
        "vodId": "vod-1",
        "vodName": "Title",
        "episodeName": "S02E03",
        "episodeUrl": "1@188076@1@2",
        "sourceGroupIndex": 1,
        "sourceIndex": 0,
        "sourceSubgroupIndex": 1,
        "sourceSubgroupName": "S02",
        "driveDirId": "stable-directory",
        "driveShareKey": "quark@share-id@",
        "drivePath": "/Show/S02/S02E03.mp4",
        "positionMs": 12,
        "durationMs": 100,
        "updatedAt": 99,
    }]), cid=7, owner=owner)

    assert rows == [{
        "key": "plugin-9@@@vod-1@@@7",
        "vodPic": "",
        "vodName": "Title",
        "vodFlag": "",
        "vodRemarks": "S02E03",
        "episodeUrl": "1@188076@1@2",
        "revSort": False,
        "revPlay": False,
        "createTime": 99,
        "opening": 0,
        "ending": 0,
        "position": 12,
        "duration": 100,
        "speed": 1.0,
        "cid": 7,
        "episode": -1,
    }]


def test_history_for_local_rebuilds_key_and_fails_closed_without_cid():
    owner = Owner([])
    row = {"key": "site-a@@@vod-1", "vodName": "Title", "cid": 0}

    assert HISTORY.v80_history_for_local(owner, row)["key"] == "site-a@@@vod-1@@@7"
    owner._v80_history_cid = 0
    assert HISTORY.v80_history_for_local(owner, row) is None


def test_active_cid_does_not_reuse_a_cached_subscription_value(monkeypatch):
    java = types.ModuleType("java")
    java.jclass = lambda _name: type("VodConfig", (), {"getCid": staticmethod(lambda: 0)})
    monkeypatch.setitem(sys.modules, "java", java)
    monkeypatch.setattr(HISTORY, "v80_history_active_cid", REAL_ACTIVE_CID)
    owner = Owner([])
    owner._v80_history_cid = 99

    assert HISTORY.v80_history_active_cid(owner) == 0


def test_page_collision_keeps_newer_identity_and_source_kind():
    source_kinds = {}
    rows = HISTORY.v80_history_rows_from_page(_page(items=[
        {"sourceKind": "site", "sourceKey": "same", "vodId": "v", "updatedAt": 10},
        {"sourceKind": "spider_plugin", "sourceKey": "same", "vodId": "v", "updatedAt": 11},
    ]), cid=7, source_kinds=source_kinds)

    assert len(rows) == 1
    assert source_kinds == {("same", "v"): "spider_plugin"}


def test_lightweight_fetch_uses_latest_without_persisting_or_deleting():
    owner = Owner([Response(payload=_page(items=[{
        "sourceKind": "site", "sourceKey": "s", "vodId": "v",
        "positionMs": 2, "durationMs": 5,
    }]))])
    legacy_calls = []

    rows = HISTORY.v80_history_fetch(owner, lambda: legacy_calls.append(True))

    method, url, kwargs = owner._atvp_session.calls[0]
    assert method == "GET"
    assert url == "https://server/api/playback/changes"
    assert kwargs["headers"] == {
        "X-PlaySync-Since": "0", "X-PlaySync-Limit": "100", "X-PlaySync-Latest": "true",
        "X-PlaySync-Source-Kind": "site,spider_plugin", "Authorization": "test-session-token",
    }
    assert kwargs["allow_redirects"] is False
    assert rows[0]["key"] == "s@@@v@@@7"
    assert HISTORY.PLAYBACK_STATE_CACHE_KEY not in owner.cache
    assert legacy_calls == []


def test_lightweight_fetch_does_not_clear_pending_full_sync_state():
    owner = Owner([
        Response(payload=_page(next_since="9")),
        Response(payload=_page(next_since="10")),
    ])
    HISTORY.v80_history_fetch(owner, lambda: None, stateful=True)
    pending = owner._v80_history_pending_state

    HISTORY.v80_history_fetch(owner, lambda: None, stateful=False)

    assert owner._v80_history_pending_state is pending
    assert owner._v80_history_pending_state["nextSince"] == "9"


def test_lightweight_and_stateful_fetches_share_one_context_boundary():
    owner = Owner([])
    first_entered = threading.Event()
    release_first = threading.Event()
    second_entered = threading.Event()
    second_attempted = threading.Event()

    class BlockingSession(Session):
        def _send(self, method, url, **kwargs):
            self.calls.append((method, url, kwargs))
            if len(self.calls) == 1:
                first_entered.set()
                assert release_first.wait(2)
            else:
                second_entered.set()
            return self.responses.pop(0)

    owner._atvp_session = BlockingSession([
        Response(payload=_page(next_since="1")),
        Response(payload=_page(next_since="2")),
    ])
    errors = []

    def stateful_fetch():
        try:
            HISTORY.v80_history_fetch(owner, lambda: None, stateful=True)
        except Exception as exc:
            errors.append(exc)

    def lightweight_fetch():
        second_attempted.set()
        try:
            HISTORY.v80_history_fetch(owner, lambda: None, stateful=False)
        except Exception as exc:
            errors.append(exc)

    first = threading.Thread(target=stateful_fetch)
    second = threading.Thread(target=lightweight_fetch)
    first.start()
    assert first_entered.wait(1)
    second.start()
    assert second_attempted.wait(1)
    assert not second_entered.wait(0.1)
    release_first.set()
    first.join(2)
    second.join(2)

    assert not first.is_alive() and not second.is_alive()
    assert errors == []
    assert second_entered.is_set()
    assert owner._v80_history_pending_state["nextSince"] == "1"


def test_incremental_pull_applies_tombstone_before_advancing_cursor():
    owner = Owner([Response(payload=_page(items=[{
        "sourceKind": "site", "sourceKey": "s", "vodId": "v", "updatedAt": 10,
    }], next_since="1"))])
    HISTORY.v80_history_fetch(owner, lambda: pytest.fail("unexpected fallback"), stateful=True)
    assert HISTORY.PLAYBACK_STATE_CACHE_KEY not in owner.cache
    assert HISTORY.v80_history_commit(owner, imported=1, expected=1) is True
    owner.local_rows = [{"key": "s@@@v@@@7", "createTime": 10}]
    owner._atvp_session.responses.append(Response(payload=_page(deleted=[{
        "scope": "item", "sourceKind": "site", "sourceKey": "s", "vodId": "v",
        "deletedAt": 20,
    }], next_since="2")))

    rows = HISTORY.v80_history_fetch(
        owner, lambda: pytest.fail("unexpected fallback"), stateful=True,
    )

    second = owner._atvp_session.calls[1][2]["headers"]
    assert second["X-PlaySync-Since"] == "1"
    assert second["X-PlaySync-Latest"] == "false"
    assert owner.local_deleted_keys == ["s@@@v@@@7"]
    assert rows == []
    assert HISTORY.v80_history_refresh_local_rows(
        owner, [{"key": "s@@@v@@@7", "createTime": 10}],
    ) == []
    assert owner._v80_history_pending_state["localDeleted"] == 0
    assert owner.cache[HISTORY.PLAYBACK_STATE_CACHE_KEY]["nextSince"] == "1"
    assert HISTORY.v80_history_commit(owner, imported=0, expected=0) is True
    assert owner.cache[HISTORY.PLAYBACK_STATE_CACHE_KEY]["nextSince"] == "2"


def test_tombstone_does_not_remove_newer_local_or_cloud_progress():
    owner = Owner([Response(payload=_page(items=[{
        "sourceKind": "site", "sourceKey": "s", "vodId": "v", "updatedAt": 10,
    }], next_since="1"))])
    HISTORY.v80_history_fetch(owner, lambda: None, stateful=True)
    HISTORY.v80_history_commit(owner, imported=1, expected=1)
    owner.local_rows = [{"key": "s@@@v@@@7", "createTime": 30}]
    owner._atvp_session.responses.append(Response(payload=_page(items=[{
        "sourceKind": "site", "sourceKey": "s", "vodId": "v", "updatedAt": 30,
    }], deleted=[{
        "scope": "site", "sourceKind": "site", "sourceKey": "s", "deletedAt": 20,
    }], next_since="2")))

    rows = HISTORY.v80_history_fetch(owner, lambda: None, stateful=True)

    assert owner.local_deleted_keys == []
    assert rows[0]["createTime"] == 30


def test_spider_plugin_identity_round_trips_through_push_and_delete():
    owner = Owner([Response(204), Response(204)])
    owner._v80_history_source_kinds = {
        ("douban_tmdb_follow_single", "tmdb:tv:7"): "spider_plugin",
    }
    key = "douban_tmdb_follow_single@@@tmdb:tv:7@@@7"

    HISTORY.v80_history_push(owner, [{"key": key, "position": 8}], lambda rows: None)
    method, url, kwargs = owner._atvp_session.calls[0]
    assert method == "POST"
    assert url == "https://server/api/playback/event"
    assert kwargs["json"]["sourceKind"] == "spider_plugin"
    assert len(kwargs["headers"]["Idempotency-Key"]) == 64

    assert HISTORY.v80_history_delete(owner, key, lambda value: False) is True
    assert owner._atvp_session.calls[1][1] == "https://server/api/playback/event"
    assert owner._atvp_session.calls[1][2]["json"] == {
        "sourceKind": "spider_plugin",
        "sourceKey": "douban_tmdb_follow_single",
        "vodId": "tmdb:tv:7",
        "action": "delete",
        "scope": "item",
        "historyKey": key,
        "deletedAt": owner._atvp_session.calls[1][2]["json"]["deletedAt"],
    }


@pytest.mark.parametrize("operation,status", (
    ("fetch", 404), ("fetch", 405),
    ("push", 404), ("push", 405),
    ("delete", 404), ("delete", 405),
))
def test_missing_new_routes_after_auth_refresh_fall_back(operation, status):
    owner = Owner([Response(401), Response(payload=_login_payload()), Response(status)])
    calls = []

    if operation == "fetch":
        result = HISTORY.v80_history_fetch(owner, lambda: calls.append(operation) or ["legacy"])
        assert result == ["legacy"]
    elif operation == "push":
        HISTORY.v80_history_push(owner, [{"key": "s@@@v@@@7"}], lambda rows: calls.append(operation))
    else:
        assert HISTORY.v80_history_delete(
            owner, "s@@@v@@@7", lambda key: calls.append(operation) or True,
        ) is True
    assert calls == [operation]
    assert owner._atvp_session.calls[-1][2]["headers"]["Authorization"] == "test-renewed-session-token"


def test_token_is_rebound_before_get_failover_to_another_origin():
    owner = Owner([
        requests.ConnectionError("primary unavailable"),
        Response(payload=_login_payload("token-b", uid=2)),
        Response(payload=_page()),
    ], origins=["https://a", "https://b"])
    owner._history_primary_origin = "https://a"

    HISTORY.v80_history_fetch(owner, lambda: pytest.fail("unexpected fallback"))

    assert owner._atvp_session.calls[0][1] == "https://a/api/playback/changes"
    assert owner._atvp_session.calls[0][2]["headers"]["Authorization"] == "test-session-token"
    assert owner._atvp_session.calls[1][1] == "https://b/api/accounts/login"
    assert "Authorization" not in owner._atvp_session.calls[1][2].get("headers", {})
    assert owner._atvp_session.calls[2][1] == "https://b/api/playback/changes"
    assert owner._atvp_session.calls[2][2]["headers"]["Authorization"] == "token-b"


def test_restart_reauthenticates_then_reissues_pull_from_persisted_scope_cursor():
    owner = Owner([
        Response(payload=_login_payload("restart-token", uid=7)),
        Response(payload=_page(next_since="6")),
        Response(payload=_page(next_since="6")),
    ])
    owner._v80_history_auth_token = ""
    owner._v80_history_auth_origin = ""
    owner._v80_history_auth_uid = 0
    owner.cache[HISTORY.PLAYBACK_STATE_CACHE_KEY] = {
        "version": 1,
        "scope": "https://server|7|site,spider_plugin",
        "nextSince": "5",
        "records": [],
    }

    HISTORY.v80_history_fetch(owner, lambda: None, stateful=True)

    assert owner._atvp_session.calls[0][1] == "https://server/api/accounts/login"
    assert owner._atvp_session.calls[1][2]["headers"]["X-PlaySync-Since"] == "0"
    assert owner._atvp_session.calls[2][2]["headers"]["X-PlaySync-Since"] == "5"
    assert owner._atvp_session.calls[2][2]["headers"]["Authorization"] == "restart-token"


def test_decreasing_cursor_clears_scope_and_rebuilds_latest_once():
    owner = Owner([
        Response(payload=_page(next_since="4")),
        Response(payload=_page(next_since="6")),
    ])
    owner.cache[HISTORY.PLAYBACK_STATE_CACHE_KEY] = {
        "version": 1,
        "scope": "https://server|1|site,spider_plugin",
        "nextSince": "5",
        "records": [],
    }

    HISTORY.v80_history_fetch(owner, lambda: None, stateful=True)

    assert owner._atvp_session.calls[0][2]["headers"]["X-PlaySync-Since"] == "5"
    assert owner._atvp_session.calls[1][2]["headers"]["X-PlaySync-Since"] == "0"
    assert owner._atvp_session.calls[1][2]["headers"]["X-PlaySync-Latest"] == "true"
    assert owner._v80_history_pending_state["nextSince"] == "6"
    assert owner.cache[HISTORY.PLAYBACK_STATE_CACHE_KEY] is None


def test_cache_read_failure_stops_before_network_bootstrap():
    owner = Owner([])

    def failed_cache(_key):
        raise OSError("cache unavailable")

    owner.getCache = failed_cache
    with pytest.raises(RuntimeError, match="状态读取失败"):
        HISTORY.v80_history_fetch(owner, lambda: None, stateful=True)
    assert owner._atvp_session.calls == []


@pytest.mark.parametrize(("field", "value"), (
    ("version", 2),
    ("nextSince", "broken"),
    ("records", {}),
    ("records", [{"sourceKind": "telegram", "sourceKey": "x", "vodId": "v"}]),
))
def test_same_scope_corrupt_state_stops_before_network_bootstrap(field, value):
    owner = Owner([])
    state = {
        "version": 1,
        "scope": "https://server|1|site,spider_plugin",
        "nextSince": "5",
        "records": [],
    }
    state[field] = value
    owner.cache[HISTORY.PLAYBACK_STATE_CACHE_KEY] = state

    with pytest.raises(RuntimeError, match="状态损坏"):
        HISTORY.v80_history_fetch(owner, lambda: None, stateful=True)
    assert owner._atvp_session.calls == []


def test_stateful_cursor_is_not_committed_when_import_phase_does_not_commit():
    owner = Owner([Response(payload=_page(next_since="9"))])

    HISTORY.v80_history_fetch(owner, lambda: None, stateful=True)

    assert owner._v80_history_pending_state["nextSince"] == "9"
    assert HISTORY.PLAYBACK_STATE_CACHE_KEY not in owner.cache


def test_incomplete_import_rejects_cursor_commit():
    owner = Owner([Response(payload=_page(items=[{
        "sourceKind": "site", "sourceKey": "s", "vodId": "v", "updatedAt": 1,
    }], next_since="9"))])
    HISTORY.v80_history_fetch(owner, lambda: None, stateful=True)

    with pytest.raises(RuntimeError, match="导入未完成"):
        HISTORY.v80_history_commit(owner, imported=0, expected=1)
    assert HISTORY.PLAYBACK_STATE_CACHE_KEY not in owner.cache


def test_pending_cursor_commit_is_bound_to_the_fetch_scope():
    owner = Owner([Response(payload=_page(next_since="9"))])
    HISTORY.v80_history_fetch(owner, lambda: None, stateful=True)
    owner._v80_history_auth_origin = "https://other"
    owner._v80_history_auth_uid = 2

    with pytest.raises(RuntimeError, match="身份已变化"):
        HISTORY.v80_history_commit(owner, imported=0, expected=0)
    assert HISTORY.PLAYBACK_STATE_CACHE_KEY not in owner.cache


def test_missing_active_cid_rejects_pending_state_and_cursor_commit(monkeypatch):
    owner = Owner([Response(payload=_page(items=[{
        "sourceKind": "site", "sourceKey": "s", "vodId": "v", "updatedAt": 1,
    }], next_since="9"))])
    monkeypatch.setattr(HISTORY, "v80_history_active_cid", lambda _owner: 0)

    with pytest.raises(RuntimeError, match="CID"):
        HISTORY.v80_history_fetch(owner, lambda: None, stateful=True)
    assert getattr(owner, "_v80_history_pending_state", None) is None
    assert HISTORY.v80_history_commit(owner, imported=0, expected=0) is False
    assert HISTORY.PLAYBACK_STATE_CACHE_KEY not in owner.cache


def test_config_generation_change_forces_new_login():
    owner = Owner([Response(payload=_login_payload("fresh-token")), Response(payload=_page())])
    owner._cache_generation = 1

    HISTORY.v80_history_fetch(owner, lambda: None)

    assert owner._atvp_session.calls[0][1].endswith("/api/accounts/login")
    assert owner._atvp_session.calls[1][2]["headers"]["Authorization"] == "fresh-token"


@pytest.mark.parametrize("page", (
    {"items": [], "deleted": {}, "nextSince": "1"},
    {"items": [{"sourceKind": "site"}], "deleted": [], "nextSince": "1"},
    {"items": [], "deleted": [{"scope": "site", "deletedAt": 2}], "nextSince": "1"},
    {"items": [], "deleted": [], "nextSince": "-1"},
))
def test_invalid_delta_page_never_advances_cursor(page):
    owner = Owner([Response(payload=page)])

    with pytest.raises(RuntimeError):
        HISTORY.v80_history_fetch(owner, lambda: None, stateful=True)
    assert HISTORY.PLAYBACK_STATE_CACHE_KEY not in owner.cache


@pytest.mark.parametrize("failure", (
    Response(500),
    Response(501),
    requests.ConnectionError("dns failure"),
))
def test_server_transport_and_501_failures_do_not_masquerade_as_unsupported(failure):
    owner = Owner([failure])
    calls = []

    with pytest.raises(Exception):
        HISTORY.v80_history_fetch(owner, lambda: calls.append(True))
    assert calls == []


def test_auth_and_truncated_json_failures_do_not_fall_back():
    auth_owner = Owner([Response(401), Response(401)])
    truncated_owner = Owner([Response(payload=_page())])
    truncated_owner.read_error = RuntimeError("truncated JSON")

    with pytest.raises(RuntimeError, match="登录 HTTP 401"):
        HISTORY.v80_history_fetch(auth_owner, lambda: pytest.fail("unexpected fallback"))
    with pytest.raises(RuntimeError, match="truncated JSON"):
        HISTORY.v80_history_fetch(truncated_owner, lambda: pytest.fail("unexpected fallback"))


def test_missing_credentials_preserves_legacy_read_only_path():
    owner = Owner([], credentials=False)

    assert HISTORY.v80_history_fetch(owner, lambda: ["legacy-read-only"]) == ["legacy-read-only"]
    assert owner._atvp_session.calls == []


def test_legacy_fallback_performs_a_fresh_login_request():
    owner = Owner([
        Response(404),
        Response(payload=_login_payload("legacy-fresh-token")),
    ])
    owner._atvp_session.headers["Authorization"] = "test-session-token"

    def legacy_fetch():
        assert owner._history_auth_token == ""
        assert "Authorization" not in owner._atvp_session.headers
        response = owner._atvp_session.post(
            "https://server/api/accounts/login",
            json={"username": owner.history_username, "password": owner.history_password},
        )
        payload = owner._read_bounded_json_response(response, "legacy login")
        owner._history_auth_token = payload["token"]
        return ["legacy"]

    assert HISTORY.v80_history_fetch(owner, legacy_fetch) == ["legacy"]
    assert owner._atvp_session.calls[1][1] == "https://server/api/accounts/login"
    assert owner._history_auth_token == "legacy-fresh-token"

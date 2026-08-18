import hashlib
import threading
import time

import requests


PLAYBACK_SYNC_CONTRACT = "alist-tvbox-playback-sync-1.45.1"
PLAYBACK_CHANGES_PATH = "/api/playback/changes"
PLAYBACK_EVENT_PATH = "/api/playback/event"
PLAYBACK_SOURCE_KINDS = ("site", "spider_plugin")
PLAYBACK_SOURCE_KIND_HEADER = "site,spider_plugin"
PLAYBACK_STATE_CACHE_KEY = "douban_tmdb_follow_history_v80_1451"
PLAYBACK_PLUGIN_SITE_KEY = "douban_tmdb_follow_single"
HISTORY_EVENT_QUEUE_CACHE_PREFIX = "douban_tmdb_follow_history_events_v1"
HISTORY_EVENT_QUEUE_MAX_ACTIVE = 256
HISTORY_EVENT_QUEUE_MAX_ACK = 64
HISTORY_EVENT_QUEUE_MAX_DEAD = 64
HISTORY_EVENT_QUEUE_DRAIN_LIMIT = 8
HISTORY_EVENT_QUEUE_MAX_ATTEMPTS = 5
HISTORY_EVENT_QUEUE_BACKOFF_SECONDS = (5, 30, 120, 600)
HISTORY_EVENT_QUEUE_RECOVERY_DELAY_MS = 1000


class _V80PlaybackSyncUnsupported(RuntimeError):
    pass


class _V80PlaybackCursorReset(RuntimeError):
    pass


class _V80HistoryQueueCancelled(RuntimeError):
    pass


class _V80HistoryHttpError(RuntimeError):
    def __init__(self, status_code, message):
        self.status_code = _v80_history_int(status_code, 0)
        super().__init__(message)


class _V80HistoryQueuePersistenceError(RuntimeError):
    pass


def _v80_history_first(row, *keys):
    if not isinstance(row, dict):
        return None
    for key in keys:
        if key in row and row.get(key) is not None:
            return row.get(key)
    return None


def _v80_history_text(value):
    text = str(value or "").strip()
    return "" if text == "null" else text


def _v80_history_int(value, default=0):
    try:
        return int(float(value))
    except Exception:
        return default


def _v80_history_float(value, default=1.0):
    try:
        return float(value)
    except Exception:
        return default


def _v80_history_plugin_site_key(source_key, owner=None):
    source_key = _v80_history_text(source_key)
    if not source_key:
        return False
    runtime_key = _v80_history_text(getattr(owner, "siteKey", "")) if owner is not None else ""
    if source_key in (runtime_key, PLAYBACK_PLUGIN_SITE_KEY):
        return True
    suffix = source_key[7:] if source_key.startswith("plugin-") else ""
    return bool(suffix.isdigit() and int(suffix) > 0)


def _v80_history_source_kind(row, source_key, vod_id, owner=None):
    explicit = _v80_history_text(_v80_history_first(row, "sourceKind", "source_kind"))
    if explicit:
        return explicit
    source_kinds = getattr(owner, "_v80_history_source_kinds", {}) if owner is not None else {}
    mapped = source_kinds.get((source_key, vod_id)) if isinstance(source_kinds, dict) else None
    if mapped in PLAYBACK_SOURCE_KINDS:
        return mapped
    return "spider_plugin" if _v80_history_plugin_site_key(source_key, owner) else "site"


def _v80_history_identity(row, owner=None):
    source_key = _v80_history_text(_v80_history_first(
        row, "sourceKey", "source_key", "siteKey", "site_key",
    ))
    vod_id = _v80_history_text(_v80_history_first(row, "vodId", "vod_id"))
    key = _v80_history_text(_v80_history_first(row, "key", "historyKey", "history_key"))
    if key and (not source_key or not vod_id):
        parts = key.split("@@@")
        if len(parts) >= 2 and parts[0] and parts[1]:
            source_key = source_key or parts[0]
            vod_id = vod_id or parts[1]
        elif not vod_id:
            source_key = source_key or "csp_AList"
            vod_id = key
    if not source_key or not vod_id:
        return None
    source_kind = _v80_history_source_kind(row, source_key, vod_id, owner)
    return source_kind, source_key, vod_id


def _v80_history_event(row, owner=None):
    identity = _v80_history_identity(row, owner)
    if identity is None:
        return None
    source_kind, source_key, vod_id = identity
    event = {
        "sourceKind": source_kind,
        "sourceKey": source_key,
        "vodId": vod_id,
        "vodName": _v80_history_text(_v80_history_first(row, "vodName", "vod_name")),
        "vodPic": _v80_history_text(_v80_history_first(row, "vodPic", "vod_pic")),
        "vodFlag": _v80_history_text(_v80_history_first(row, "vodFlag", "vod_flag")),
        "episodeName": _v80_history_text(_v80_history_first(
            row, "vodRemarks", "vod_remarks", "episodeName", "episode_name",
        )),
        "episodeUrl": _v80_history_text(_v80_history_first(row, "episodeUrl", "episode_url")),
        "episode": _v80_history_int(_v80_history_first(row, "episode", "episodeIndex"), -1),
        "positionMs": max(0, _v80_history_int(_v80_history_first(row, "position", "positionMs"))),
        "durationMs": max(0, _v80_history_int(_v80_history_first(row, "duration", "durationMs"))),
        "openingMs": max(0, _v80_history_int(_v80_history_first(row, "opening", "openingMs"))),
        "endingMs": max(0, _v80_history_int(_v80_history_first(row, "ending", "endingMs"))),
        "speed": _v80_history_float(_v80_history_first(row, "speed"), 1.0),
        "updatedAt": max(0, _v80_history_int(_v80_history_first(
            row, "createTime", "create_time", "updatedAt", "updated_at",
        ))),
    }
    source_name = _v80_history_text(_v80_history_first(row, "sourceName", "source_name"))
    if source_name:
        event["sourceName"] = source_name
    return event


def _v80_history_rank(row):
    return (
        _v80_history_int(row.get("updatedAt"), 0),
        _v80_history_int(row.get("positionMs"), 0),
        _v80_history_int(row.get("durationMs"), 0),
    )


def v80_history_events(rows, limit=2048, owner=None):
    cap = max(1, _v80_history_int(limit, 2048))
    by_identity = {}
    for row in rows if isinstance(rows, (list, tuple)) else ():
        event = _v80_history_event(row, owner)
        if event is None:
            continue
        identity = (event["sourceKind"], event["sourceKey"], event["vodId"])
        previous = by_identity.get(identity)
        if previous is None or _v80_history_rank(event) >= _v80_history_rank(previous):
            by_identity[identity] = event
    values = list(by_identity.values())
    values.sort(key=_v80_history_rank, reverse=True)
    return values[:cap]


def v80_history_delete_input(key, owner=None):
    identity = _v80_history_identity({"key": key}, owner)
    if identity is None:
        return None
    source_kind, source_key, vod_id = identity
    return {
        "sourceKind": source_kind,
        "sourceKey": source_key,
        "vodId": vod_id,
    }


def v80_history_active_cid(owner):
    try:
        from java import jclass
        cid = _v80_history_int(
            jclass("com.fongmi.android.tv.api.config.VodConfig").getCid(), 0,
        )
        return max(0, cid)
    except Exception:
        return 0


def v80_history_for_local(owner, row):
    identity = owner._history_identity(row)
    cid = v80_history_active_cid(owner)
    if not identity or cid <= 0:
        return None
    output = {
        key: row.get(key)
        for key in owner.HISTORY_FIELDS
        if key in row and key not in ("key", "uid")
    }
    output["key"] = "%s@@@%s@@@%s" % (identity[0], identity[1], cid)
    output["cid"] = cid
    return output


def _v80_history_legacy_row(item, cid=0, owner=None):
    if not isinstance(item, dict):
        return None
    identity = _v80_history_identity(item, owner)
    if identity is None or identity[0] not in PLAYBACK_SOURCE_KINDS:
        return None
    _source_kind, source_key, vod_id = identity
    cid = max(0, _v80_history_int(cid, 0))
    return {
        "key": "%s@@@%s@@@%s" % (source_key, vod_id, cid),
        "vodPic": _v80_history_text(_v80_history_first(item, "vodPic", "vod_pic")),
        "vodName": _v80_history_text(_v80_history_first(item, "vodName", "vod_name")),
        "vodFlag": _v80_history_text(_v80_history_first(item, "vodFlag", "vod_flag")),
        "vodRemarks": _v80_history_text(_v80_history_first(
            item, "episodeName", "episode_name", "vodRemarks", "vod_remarks",
        )),
        "episodeUrl": _v80_history_text(_v80_history_first(item, "episodeUrl", "episode_url")),
        "revSort": False,
        "revPlay": False,
        "createTime": max(0, _v80_history_int(_v80_history_first(
            item, "updatedAt", "updated_at", "createTime", "create_time",
        ))),
        "opening": max(0, _v80_history_int(_v80_history_first(item, "openingMs", "opening_ms", "opening"))),
        "ending": max(0, _v80_history_int(_v80_history_first(item, "endingMs", "ending_ms", "ending"))),
        "position": max(0, _v80_history_int(_v80_history_first(item, "positionMs", "position_ms", "position"))),
        "duration": max(0, _v80_history_int(_v80_history_first(item, "durationMs", "duration_ms", "duration"))),
        "speed": _v80_history_float(_v80_history_first(item, "speed"), 1.0),
        "cid": cid,
        "episode": _v80_history_int(_v80_history_first(item, "episode", "episodeIndex"), -1),
    }


def v80_history_rows_from_page(page, limit=2048, cid=0, owner=None, source_kinds=None):
    if not isinstance(page, dict) or not isinstance(page.get("items"), list):
        raise RuntimeError("AList-TVBox 播放记录同步格式无效")
    cap = max(1, _v80_history_int(limit, 2048))
    by_key = {}
    for item in page.get("items"):
        identity = _v80_history_identity(item, owner)
        if not isinstance(item, dict) or identity is None or identity[0] not in PLAYBACK_SOURCE_KINDS:
            raise RuntimeError("AList-TVBox 播放记录同步条目无效")
        row = _v80_history_legacy_row(item, cid=cid, owner=owner)
        if row is None:
            raise RuntimeError("AList-TVBox 播放记录同步条目无效")
        previous = by_key.get(row["key"])
        rank = (row["createTime"], row["position"], row["duration"])
        previous_rank = previous[0] if previous else None
        if previous_rank is None or rank >= previous_rank:
            by_key[row["key"]] = (rank, row, identity)
    values = list(by_key.values())
    values.sort(key=lambda value: value[0], reverse=True)
    values = values[:cap]
    if isinstance(source_kinds, dict):
        source_kinds.clear()
        source_kinds.update({
            (identity[1], identity[2]): identity[0]
            for _rank, _row, identity in values
        })
    return [row for _rank, row, _identity in values]


def _v80_history_close(response):
    closer = getattr(response, "close", None)
    if callable(closer):
        try:
            closer()
        except Exception:
            pass


def _v80_history_endpoint(origin, path):
    base = str(origin or "").rstrip("/")
    if not base:
        raise RuntimeError("AList-TVBox 播放记录同步没有可用地址")
    return base + path


def _v80_history_clear_session_auth(owner):
    headers = getattr(owner._atvp_session, "headers", None)
    if isinstance(headers, dict):
        headers.pop("Authorization", None)


def _v80_history_login(owner, origin, force=False):
    origin = str(origin or "").rstrip("/")
    token = _v80_history_text(getattr(owner, "_v80_history_auth_token", ""))
    bound_origin = _v80_history_text(getattr(owner, "_v80_history_auth_origin", ""))
    username = _v80_history_text(getattr(owner, "history_username", ""))
    generation = _v80_history_int(getattr(owner, "_cache_generation", 0), 0)
    uid = max(0, _v80_history_int(getattr(owner, "_v80_history_auth_uid", 0), 0))
    binding_changed = (
        _v80_history_text(getattr(owner, "_v80_history_auth_username", "")) != username
        or _v80_history_int(getattr(owner, "_v80_history_auth_generation", -1), -1) != generation
    )
    if binding_changed:
        token = ""
        bound_origin = ""
    if (
        not token
        and not binding_changed
        and uid > 0
        and _v80_history_text(getattr(owner, "_history_selected_origin", "")) == origin
    ):
        token = _v80_history_text(getattr(owner, "_history_auth_token", ""))
        bound_origin = origin if token else ""
    if token and bound_origin == origin and uid > 0 and not force:
        return token
    if not owner._history_write_enabled():
        return ""
    _v80_history_clear_session_auth(owner)
    response = owner._atvp_session.post(
        _v80_history_endpoint(origin, "/api/accounts/login"),
        json={"username": owner.history_username, "password": owner.history_password},
        timeout=owner.timeout,
        verify=owner.verify_tls,
        stream=True,
        allow_redirects=False,
    )
    if response.status_code < 200 or response.status_code >= 300:
        try:
            raise _V80HistoryHttpError(
                response.status_code,
                "AList-TVBox 播放记录同步登录 HTTP %s" % response.status_code,
            )
        finally:
            _v80_history_close(response)
    value = owner._read_bounded_json_response(
        response, "AList-TVBox 播放记录同步登录", max_bytes=owner.HISTORY_RESPONSE_MAX_BYTES,
    )
    authorities = value.get("authorities") if isinstance(value, dict) else []
    roles = set()
    for authority in authorities or []:
        if isinstance(authority, dict):
            roles.add(_v80_history_text(authority.get("authority")).upper())
        else:
            roles.add(_v80_history_text(authority).upper())
    if not roles.intersection(("USER", "ADMIN")):
        raise RuntimeError("History 写入账号必须是 AList-TVBox USER 或 ADMIN 角色")
    token = _v80_history_text(value.get("token") if isinstance(value, dict) else "")
    if not token:
        raise RuntimeError("AList-TVBox 播放记录同步登录未返回令牌")
    uid = _v80_history_int(value.get("id"), 0) if isinstance(value, dict) else 0
    if uid <= 0:
        raise RuntimeError("AList-TVBox 播放记录同步登录未返回用户编号")
    owner._v80_history_auth_origin = origin
    owner._v80_history_auth_token = token
    owner._v80_history_auth_uid = uid
    owner._v80_history_auth_username = username
    owner._v80_history_auth_generation = generation
    owner._history_selected_origin = origin
    _v80_history_clear_session_auth(owner)
    return token


def _v80_history_send(owner, method, path, **kwargs):
    with owner._history_context_lock:
        return _v80_history_send_locked(owner, method, path, **kwargs)


def _v80_history_send_locked(owner, method, path, **kwargs):
    method_name = str(method or "GET").strip().lower()
    sender = getattr(owner._atvp_session, method_name)
    queue_scope = _v80_history_text(kwargs.pop("_v80_queue_scope", ""))
    origins = owner._history_origin_candidates() or [owner.atvp_api]
    preferred = _v80_history_text(
        getattr(owner, "_v80_history_auth_origin", "")
        or getattr(owner, "_history_selected_origin", "")
    )
    if preferred in origins:
        origins = [preferred] + [origin for origin in origins if origin != preferred]
    base_headers = dict(kwargs.pop("headers", {}) or {})
    kwargs["allow_redirects"] = False
    last_error = None
    for origin in origins:
        try:
            try:
                token = _v80_history_login(owner, origin, force=False)
            except Exception as exc:
                last_error = exc
                if owner._history_retryable_transport_error(exc, "post"):
                    continue
                raise
            if not token:
                raise RuntimeError("AList-TVBox 播放记录同步认证未启用")
            if queue_scope and not _v80_history_queue_bind_uid(
                owner, queue_scope, getattr(owner, "_v80_history_auth_uid", 0),
            ):
                raise _V80HistoryQueueCancelled("History 事件队列账号已变化")
            headers = dict(base_headers)
            headers["Authorization"] = token
            response = sender(_v80_history_endpoint(origin, path), headers=headers, **kwargs)
            if response.status_code in (401, 403):
                _v80_history_close(response)
                try:
                    token = _v80_history_login(owner, origin, force=True)
                except Exception as exc:
                    last_error = exc
                    if owner._history_retryable_transport_error(exc, "post"):
                        continue
                    raise
                if queue_scope and not _v80_history_queue_bind_uid(
                    owner, queue_scope, getattr(owner, "_v80_history_auth_uid", 0),
                ):
                    raise _V80HistoryQueueCancelled("History 事件队列账号已变化")
                headers["Authorization"] = token
                response = sender(_v80_history_endpoint(origin, path), headers=headers, **kwargs)
            if response.status_code in (404, 405):
                _v80_history_close(response)
                raise _V80PlaybackSyncUnsupported("AList-TVBox 未提供 1.45 播放记录同步路径")
            owner._history_selected_origin = origin
            return response
        except _V80PlaybackSyncUnsupported:
            raise
        except Exception as exc:
            last_error = exc
            if not owner._history_retryable_transport_error(exc, method_name):
                raise
    if last_error is not None:
        raise last_error
    raise RuntimeError("AList-TVBox 播放记录同步没有可用地址")


def _v80_history_prepare_auth(owner):
    return bool(owner._history_write_enabled())


def _v80_history_prepare_legacy_fallback(owner):
    owner._history_auth_token = ""
    _v80_history_clear_session_auth(owner)


def _v80_history_state_scope(owner):
    origin = _v80_history_text(
        getattr(owner, "_v80_history_auth_origin", "")
        or getattr(owner, "_history_selected_origin", "")
        or getattr(owner, "_history_primary_origin", "")
        or getattr(owner, "history_api", "")
        or getattr(owner, "atvp_api", "")
    ).rstrip("/")
    uid = max(0, _v80_history_int(getattr(owner, "_v80_history_auth_uid", 0), 0))
    return "%s|%s|%s" % (origin, uid, PLAYBACK_SOURCE_KIND_HEADER) if origin and uid else ""


def _v80_history_state_get(owner):
    scope = _v80_history_state_scope(owner)
    if not scope:
        return None
    state = getattr(owner, "_v80_history_state", None)
    if not isinstance(state, dict) or state.get("scope") != scope:
        getter = getattr(owner, "getCache", None)
        if callable(getter):
            try:
                state = getter(PLAYBACK_STATE_CACHE_KEY)
            except Exception as exc:
                raise RuntimeError("AList-TVBox 播放记录同步状态读取失败") from exc
        else:
            state = None
    if state is None:
        return None
    if not isinstance(state, dict):
        raise RuntimeError("AList-TVBox 播放记录同步状态损坏")
    if state.get("scope") != scope:
        return None
    records = state.get("records")
    next_since = _v80_history_text(state.get("nextSince"))
    next_value = int(next_since) if next_since.isdigit() else -1
    if state.get("version") != 1 or not isinstance(records, list):
        raise RuntimeError("AList-TVBox 播放记录同步状态损坏")
    if next_value < 0 or next_value > 9223372036854775807:
        raise RuntimeError("AList-TVBox 播放记录同步状态损坏")
    for record in records:
        identity = _v80_history_identity(record, owner)
        if not isinstance(record, dict) or identity is None or identity[0] not in PLAYBACK_SOURCE_KINDS:
            raise RuntimeError("AList-TVBox 播放记录同步状态损坏")
    normalized = {
        "version": 1,
        "scope": scope,
        "nextSince": next_since,
        "records": v80_history_events(records, limit=owner.HISTORY_ROW_LIMIT, owner=owner),
    }
    owner._v80_history_state = normalized
    return normalized


def _v80_history_state_clear(owner, scope):
    state = getattr(owner, "_v80_history_state", None)
    if isinstance(state, dict) and state.get("scope") == scope:
        owner._v80_history_state = None
    setter = getattr(owner, "setCache", None)
    if callable(setter):
        try:
            result = setter(PLAYBACK_STATE_CACHE_KEY, None)
        except Exception as exc:
            raise RuntimeError("AList-TVBox 播放记录同步状态清除失败") from exc
        if result is False or result == "failed":
            raise RuntimeError("AList-TVBox 播放记录同步状态清除失败")


def _v80_history_state_set(owner, next_since, records, scope=None):
    next_since = _v80_history_text(next_since)
    if not next_since or not next_since.isdigit():
        raise RuntimeError("AList-TVBox 播放记录同步游标无效")
    scope = _v80_history_text(scope) or _v80_history_state_scope(owner)
    if not scope:
        raise RuntimeError("AList-TVBox 播放记录同步身份无效")
    state = {
        "version": 1,
        "scope": scope,
        "nextSince": next_since,
        "records": v80_history_events(records, limit=owner.HISTORY_ROW_LIMIT, owner=owner),
    }
    setter = getattr(owner, "setCache", None)
    if callable(setter):
        result = setter(PLAYBACK_STATE_CACHE_KEY, state)
        if result is False or result == "failed":
            raise RuntimeError("AList-TVBox 播放记录同步状态保存失败")
    owner._v80_history_state = state
    return state


def v80_history_commit(owner, imported=0, expected=0):
    pending = getattr(owner, "_v80_history_pending_state", None)
    if not isinstance(pending, dict):
        return False
    if max(0, _v80_history_int(expected, 0)) > max(0, _v80_history_int(imported, 0)):
        raise RuntimeError("FongMi History 导入未完成，未推进播放记录游标")
    scope = _v80_history_state_scope(owner)
    pending_scope = _v80_history_text(pending.get("scope"))
    if not scope or pending_scope != scope:
        raise RuntimeError("AList-TVBox 播放记录同步身份已变化，未推进游标")
    state = _v80_history_state_set(
        owner, pending.get("nextSince"), pending.get("records"), scope=pending_scope,
    )
    owner._v80_history_pending_state = None
    owner._v80_history_source_kinds = {
        (event["sourceKey"], event["vodId"]): event["sourceKind"]
        for event in state["records"]
    }
    return True


def _v80_history_tombstone_matches(tombstone, event):
    if not isinstance(tombstone, dict) or not isinstance(event, dict):
        return False
    deleted_at = max(0, _v80_history_int(_v80_history_first(
        tombstone, "deletedAt", "deleted_at", "updatedAt", "updated_at",
    )))
    if deleted_at <= 0 or _v80_history_int(event.get("updatedAt"), 0) > deleted_at:
        return False
    scope = _v80_history_text(tombstone.get("scope") or "item").lower()
    if scope == "all":
        return True
    if scope == "site":
        source_key = _v80_history_text(_v80_history_first(
            tombstone, "sourceKey", "source_key", "siteKey", "site_key",
        ))
        if not source_key:
            return False
        source_kind = _v80_history_source_kind(tombstone, source_key, "", None)
        return event.get("sourceKind") == source_kind and event.get("sourceKey") == source_key
    identity = _v80_history_identity(tombstone)
    if identity is None:
        return False
    return (
        event.get("sourceKind"), event.get("sourceKey"), event.get("vodId"),
    ) == identity


def _v80_history_apply_local_deletions(owner, deleted):
    tombstones = [row for row in deleted if isinstance(row, dict)] if isinstance(deleted, list) else []
    if not tombstones:
        return 0
    local_rows = owner._capture_native_history()
    keys = []
    for row in local_rows:
        event = _v80_history_event(row, owner)
        key = _v80_history_text(row.get("key")) if isinstance(row, dict) else ""
        if key and event is not None and any(
                _v80_history_tombstone_matches(tombstone, event) for tombstone in tombstones):
            keys.append(key)
    if not keys:
        return 0
    deleted_count = owner._native_history_delete_java(keys)
    if deleted_count is None:
        raise RuntimeError("当前运行时未提供FongMi单条History删除桥")
    return max(0, _v80_history_int(deleted_count, 0))


def _v80_history_merge_page(owner, state, page):
    records = {}
    for event in v80_history_events(
            state.get("records") if isinstance(state, dict) else [],
            limit=owner.HISTORY_ROW_LIMIT, owner=owner):
        records[(event["sourceKind"], event["sourceKey"], event["vodId"])] = event
    tombstones = page.get("deleted") if isinstance(page.get("deleted"), list) else []
    for identity, event in list(records.items()):
        if any(_v80_history_tombstone_matches(tombstone, event) for tombstone in tombstones):
            records.pop(identity, None)
    for event in v80_history_events(page.get("items"), limit=owner.HISTORY_ROW_LIMIT, owner=owner):
        identity = (event["sourceKind"], event["sourceKey"], event["vodId"])
        previous = records.get(identity)
        if previous is None or _v80_history_rank(event) >= _v80_history_rank(previous):
            records[identity] = event
    values = list(records.values())
    values.sort(key=_v80_history_rank, reverse=True)
    return values[:owner.HISTORY_ROW_LIMIT]


def _v80_history_validate_page(owner, page, since):
    if not isinstance(page, dict) or not isinstance(page.get("items"), list):
        raise RuntimeError("AList-TVBox 播放记录同步格式无效")
    if not isinstance(page.get("deleted"), list):
        raise RuntimeError("AList-TVBox 播放记录删除流格式无效")
    next_since = _v80_history_text(page.get("nextSince"))
    since_value = max(0, _v80_history_int(since, 0))
    next_value = int(next_since) if next_since.isdigit() else -1
    if next_value < 0 or next_value > 9223372036854775807:
        raise RuntimeError("AList-TVBox 播放记录同步游标无效")
    if next_value < since_value:
        raise _V80PlaybackCursorReset("AList-TVBox 播放记录同步游标已回退")
    for item in page["items"]:
        identity = _v80_history_identity(item, owner)
        if not isinstance(item, dict) or identity is None or identity[0] not in PLAYBACK_SOURCE_KINDS:
            raise RuntimeError("AList-TVBox 播放记录同步条目无效")
    for tombstone in page["deleted"]:
        if not isinstance(tombstone, dict):
            raise RuntimeError("AList-TVBox 播放记录删除条目无效")
        deleted_at = _v80_history_int(_v80_history_first(
            tombstone, "deletedAt", "deleted_at", "updatedAt", "updated_at",
        ), 0)
        scope = _v80_history_text(tombstone.get("scope") or "item").lower()
        source_kind = _v80_history_text(_v80_history_first(tombstone, "sourceKind", "source_kind"))
        source_key = _v80_history_text(_v80_history_first(
            tombstone, "sourceKey", "source_key", "siteKey", "site_key",
        ))
        valid = deleted_at > 0 and scope in ("all", "site", "item")
        valid = valid and (not source_kind or source_kind in PLAYBACK_SOURCE_KINDS)
        if scope == "site":
            valid = valid and bool(source_key)
        elif scope == "item":
            valid = valid and _v80_history_identity(tombstone, owner) is not None
        if not valid:
            raise RuntimeError("AList-TVBox 播放记录删除条目无效")
    return next_since


def _v80_history_fetch_response(owner, since, latest):
    return _v80_history_send(
        owner,
        "GET",
        PLAYBACK_CHANGES_PATH,
        headers={
            "X-PlaySync-Since": since,
            "X-PlaySync-Limit": str(owner.HISTORY_ROW_LIMIT),
            "X-PlaySync-Latest": "true" if latest else "false",
            "X-PlaySync-Source-Kind": PLAYBACK_SOURCE_KIND_HEADER,
        },
        timeout=owner.timeout,
        verify=owner.verify_tls,
        stream=True,
    )


def _v80_history_read_page(owner, since, latest):
    response = _v80_history_fetch_response(owner, since, latest)
    if response.status_code < 200 or response.status_code >= 300:
        try:
            raise RuntimeError("AList-TVBox 播放记录读取 HTTP %s" % response.status_code)
        finally:
            _v80_history_close(response)
    page = owner._read_bounded_json_response(
        response, "AList-TVBox Playback Sync", max_bytes=owner.HISTORY_RESPONSE_MAX_BYTES,
    )
    return page


def _v80_history_fetch_locked(owner, legacy_fetch, stateful=False):
    if stateful:
        owner._v80_history_pending_state = None
    state = _v80_history_state_get(owner) if stateful else None
    request_scope = _v80_history_state_scope(owner) if stateful else ""
    since = state.get("nextSince") if state else "0"
    try:
        page = _v80_history_read_page(owner, since, state is None)
        actual_scope = _v80_history_state_scope(owner) if stateful else ""
        if stateful and request_scope != actual_scope:
            state = _v80_history_state_get(owner)
            since = state.get("nextSince") if state else "0"
            request_scope = actual_scope
            page = _v80_history_read_page(owner, since, state is None)
        try:
            next_since = _v80_history_validate_page(owner, page, since)
        except _V80PlaybackCursorReset:
            if not stateful or state is None:
                raise
            _v80_history_state_clear(owner, request_scope)
            owner._diagnostic_event(
                "history_transport.cursor_reset", contract=PLAYBACK_SYNC_CONTRACT,
                since=since,
            )
            state = None
            since = "0"
            page = _v80_history_read_page(owner, since, True)
            request_scope = _v80_history_state_scope(owner)
            next_since = _v80_history_validate_page(owner, page, since)
    except _V80PlaybackSyncUnsupported:
        owner._diagnostic_event("history_transport.legacy", contract=PLAYBACK_SYNC_CONTRACT)
        _v80_history_prepare_legacy_fallback(owner)
        return legacy_fetch()
    if stateful and (not request_scope or request_scope != _v80_history_state_scope(owner)):
        raise RuntimeError("AList-TVBox 播放记录同步身份在请求期间发生变化")
    deleted = page.get("deleted") if isinstance(page.get("deleted"), list) else []
    local_deleted = _v80_history_apply_local_deletions(owner, deleted) if stateful else 0
    records = _v80_history_merge_page(owner, state, page) if stateful else v80_history_events(
        page.get("items"), limit=owner.HISTORY_ROW_LIMIT, owner=owner,
    )
    cid = v80_history_active_cid(owner)
    if stateful and records and cid <= 0:
        raise RuntimeError("当前 FongMi 配置 CID 不可用，未推进播放记录游标")
    if stateful:
        owner._v80_history_pending_state = {
            "version": 1,
            "scope": request_scope,
            "nextSince": next_since,
            "records": records,
            "localDeleted": local_deleted,
        }
    source_kinds = {}
    rows = v80_history_rows_from_page(
        {"items": records}, limit=owner.HISTORY_ROW_LIMIT,
        cid=cid, owner=owner, source_kinds=source_kinds,
    )
    existing_source_kinds = getattr(owner, "_v80_history_source_kinds", {})
    existing_source_kinds = dict(existing_source_kinds) if isinstance(existing_source_kinds, dict) else {}
    existing_source_kinds.update(source_kinds)
    owner._v80_history_source_kinds = existing_source_kinds
    owner._diagnostic_event(
        "history_transport.v145", contract=PLAYBACK_SYNC_CONTRACT,
        items=len(rows), deleted=len(deleted), local_deleted=local_deleted,
        since=since, next_since=next_since, latest=state is None, stateful=bool(stateful),
    )
    return owner._normalize_history_rows(rows)


def v80_history_fetch(owner, legacy_fetch, stateful=False):
    if not _v80_history_prepare_auth(owner):
        return legacy_fetch()
    with owner._history_context_lock:
        return _v80_history_fetch_locked(owner, legacy_fetch, stateful=stateful)


def v80_history_refresh_local_rows(owner, local_rows):
    pending = getattr(owner, "_v80_history_pending_state", None)
    deleted = max(0, _v80_history_int(
        pending.get("localDeleted") if isinstance(pending, dict) else 0, 0,
    ))
    if deleted <= 0:
        return local_rows
    rows = owner._capture_native_history()
    if not isinstance(rows, list):
        raise RuntimeError("FongMi History 墓碑删除后的本机快照无效")
    pending["localDeleted"] = 0
    owner._diagnostic_event("history_sync.local_after_delete", count=len(rows), deleted=deleted)
    return rows


def _v80_history_queue_scope(owner):
    origin = _v80_history_text(
        getattr(owner, "_history_primary_origin", "")
        or getattr(owner, "history_api", "")
        or getattr(owner, "atvp_api", "")
    ).rstrip("/")
    username = _v80_history_text(getattr(owner, "history_username", ""))
    if not origin or not username:
        return ""
    raw = "%s|%s|%s" % (origin, username, PLAYBACK_SOURCE_KIND_HEADER)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _v80_history_queue_cache_key(scope):
    return "%s:%s" % (HISTORY_EVENT_QUEUE_CACHE_PREFIX, scope)


def _v80_history_queue_empty(scope):
    return {
        "version": 1,
        "scope": scope,
        "accountUid": 0,
        "nextSequence": 1,
        "events": [],
        "acknowledged": [],
        "deadLetter": [],
        "deferred": [],
    }


def _v80_history_queue_rank_value(value):
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise RuntimeError("History 事件队列排序状态损坏")
    return tuple(_v80_history_int(item, -1) for item in value)


def _v80_history_queue_copy_entry(entry, allowed_statuses):
    if not isinstance(entry, dict):
        raise RuntimeError("History 事件队列条目损坏")
    status = _v80_history_text(entry.get("status"))
    action = _v80_history_text(entry.get("action"))
    event_id = _v80_history_text(entry.get("id"))
    identity = _v80_history_text(entry.get("identity"))
    payload = entry.get("payload")
    rank = _v80_history_queue_rank_value(entry.get("rank"))
    payload_identity = _v80_history_identity(payload)
    payload_action = _v80_history_text(payload.get("action")) if isinstance(payload, dict) else ""
    if (
        status not in allowed_statuses
        or action not in ("upsert", "delete")
        or not event_id
        or not identity
        or not isinstance(payload, dict)
        or payload_identity is None
        or identity != "\x1f".join(payload_identity)
        or rank != _v80_history_queue_rank(action, payload)
        or (payload_action and payload_action != action)
        or (action == "delete" and payload_action != "delete")
    ):
        raise RuntimeError("History 事件队列条目损坏")
    attempts = _v80_history_int(entry.get("attempts"), -1)
    sequence = _v80_history_int(entry.get("sequence"), -1)
    if attempts < 0 or attempts > HISTORY_EVENT_QUEUE_MAX_ATTEMPTS or sequence <= 0:
        raise RuntimeError("History 事件队列条目损坏")
    return {
        "id": event_id,
        "identity": identity,
        "action": action,
        "status": status,
        "payload": dict(payload),
        "rank": list(rank),
        "sequence": sequence,
        "attempts": attempts,
        "queuedAt": max(0, _v80_history_int(entry.get("queuedAt"), 0)),
        "nextAttemptAt": max(0, _v80_history_int(entry.get("nextAttemptAt"), 0)),
        "lastError": _v80_history_text(entry.get("lastError"))[:160],
    }


def _v80_history_queue_copy_ack(entry):
    if not isinstance(entry, dict):
        raise RuntimeError("History 事件队列确认状态损坏")
    action = _v80_history_text(entry.get("action"))
    event_id = _v80_history_text(entry.get("id"))
    identity = _v80_history_text(entry.get("identity"))
    rank = _v80_history_queue_rank_value(entry.get("rank"))
    if action not in ("upsert", "delete") or not event_id or not identity:
        raise RuntimeError("History 事件队列确认状态损坏")
    return {
        "id": event_id,
        "identity": identity,
        "action": action,
        "status": "ack",
        "rank": list(rank),
        "acknowledgedAt": max(0, _v80_history_int(entry.get("acknowledgedAt"), 0)),
    }


def _v80_history_queue_copy_deferred(entry):
    if not isinstance(entry, dict):
        raise RuntimeError("History 事件队列延迟状态损坏")
    action = _v80_history_text(entry.get("action"))
    identity = _v80_history_text(entry.get("identity"))
    payload = entry.get("payload")
    rank = _v80_history_queue_rank_value(entry.get("rank"))
    payload_identity = _v80_history_identity(payload)
    payload_action = _v80_history_text(payload.get("action")) if isinstance(payload, dict) else ""
    if (
        action not in ("upsert", "delete")
        or not identity
        or not isinstance(payload, dict)
        or payload_identity is None
        or identity != "\x1f".join(payload_identity)
        or rank != _v80_history_queue_rank(action, payload)
        or (payload_action and payload_action != action)
        or (action == "delete" and payload_action != "delete")
    ):
        raise RuntimeError("History 事件队列延迟状态损坏")
    return {
        "identity": identity,
        "action": action,
        "payload": dict(payload),
        "rank": list(rank),
    }


def _v80_history_queue_ack_limit(owner):
    return max(
        HISTORY_EVENT_QUEUE_MAX_ACK,
        max(0, _v80_history_int(getattr(owner, "HISTORY_ROW_LIMIT", 0), 0)),
    )


def _v80_history_queue_compact_acknowledged(owner, entries):
    by_identity = {}
    for raw in entries or ():
        item = _v80_history_queue_copy_ack(raw)
        identity = item["identity"]
        previous = by_identity.get(identity)
        rank = _v80_history_queue_rank_value(item["rank"])
        previous_rank = (
            _v80_history_queue_rank_value(previous["rank"])
            if previous is not None else None
        )
        if (
            previous is None
            or rank > previous_rank
            or (
                rank == previous_rank
                and item["acknowledgedAt"] >= previous["acknowledgedAt"]
            )
        ):
            by_identity[identity] = item
    values = list(by_identity.values())
    values.sort(key=lambda item: (
        item["acknowledgedAt"], _v80_history_queue_rank_value(item["rank"]), item["id"],
    ))
    return values[-_v80_history_queue_ack_limit(owner):]


def _v80_history_queue_compact_deferred(owner, entries, active_count=0):
    by_identity = {}
    for raw in entries or ():
        item = _v80_history_queue_copy_deferred(raw)
        identity = item["identity"]
        previous = by_identity.get(identity)
        if (
            previous is None
            or _v80_history_queue_rank_value(item["rank"])
            > _v80_history_queue_rank_value(previous["rank"])
        ):
            by_identity[identity] = item
    values = list(by_identity.values())
    values.sort(key=lambda item: _v80_history_queue_rank_value(item["rank"]), reverse=True)
    history_limit = max(1, _v80_history_int(getattr(owner, "HISTORY_ROW_LIMIT", 1), 1))
    return values[:max(0, history_limit - max(0, active_count))]


def _v80_history_queue_quarantine(owner, scope, value, reason):
    summary = {
        "scope": scope,
        "sha256": hashlib.sha256(repr(value).encode("utf-8", "replace")).hexdigest(),
        "reason": _v80_history_text(reason)[:80],
        "recordedAt": max(1, int(time.time() * 1000)),
    }
    items = list(getattr(owner, "_v80_history_queue_quarantine", ()) or ())
    items.append(summary)
    owner._v80_history_queue_quarantine = items[-2:]
    try:
        owner._diagnostic_event(
            "history_queue.recovered", scope=scope[:12], reason=summary["reason"],
        )
    except Exception:
        pass


def _v80_history_queue_normalize(owner, scope, value):
    if not isinstance(value, dict) or value.get("version") != 1 or value.get("scope") != scope:
        raise RuntimeError("History 事件队列状态损坏")
    account_uid = _v80_history_int(value.get("accountUid"), 0)
    next_sequence = _v80_history_int(value.get("nextSequence"), -1)
    events = value.get("events")
    acknowledged = value.get("acknowledged")
    dead_letter = value.get("deadLetter")
    deferred = value.get("deferred", [])
    if account_uid < 0 or next_sequence <= 0 or not all(isinstance(rows, list) for rows in (
        events, acknowledged, dead_letter, deferred,
    )):
        raise RuntimeError("History 事件队列状态损坏")
    if len(events) > HISTORY_EVENT_QUEUE_MAX_ACTIVE:
        raise RuntimeError("History 事件队列活动条目超限")
    normalized = {
        "version": 1,
        "scope": scope,
        "accountUid": account_uid,
        "nextSequence": next_sequence,
        "events": [
            _v80_history_queue_copy_entry(item, ("pending", "retry")) for item in events
        ],
        "acknowledged": _v80_history_queue_compact_acknowledged(owner, acknowledged),
        "deadLetter": [
            _v80_history_queue_copy_entry(item, ("dead-letter",))
            for item in dead_letter[-HISTORY_EVENT_QUEUE_MAX_DEAD:]
        ],
        "deferred": _v80_history_queue_compact_deferred(owner, deferred, len(events)),
    }
    event_ids = [item["id"] for item in normalized["events"]]
    identities = [item["identity"] for item in normalized["events"]]
    if len(set(event_ids)) != len(event_ids) or len(set(identities)) != len(identities):
        raise RuntimeError("History 事件队列活动条目重复")
    return normalized


def _v80_history_queue_state_get(owner, scope=None):
    scope = _v80_history_text(scope) or _v80_history_queue_scope(owner)
    if not scope:
        raise RuntimeError("History 事件队列身份无效")
    cached = getattr(owner, "_v80_history_event_queue", None)
    if isinstance(cached, dict) and cached.get("scope") == scope:
        value = cached
    else:
        getter = getattr(owner, "getCache", None)
        if not callable(getter):
            raise RuntimeError("History 事件队列缺少持久化读取能力")
        try:
            value = getter(_v80_history_queue_cache_key(scope))
        except Exception as exc:
            raise RuntimeError("History 事件队列读取失败") from exc
    if value is None:
        return _v80_history_queue_empty(scope)
    try:
        return _v80_history_queue_normalize(owner, scope, value)
    except RuntimeError as exc:
        _v80_history_queue_quarantine(owner, scope, value, exc)
        state = _v80_history_queue_empty(scope)
        return _v80_history_queue_state_set(owner, state)


def _v80_history_queue_state_set(owner, state):
    state = dict(state)
    state["events"] = list(state.get("events") or [])
    state["acknowledged"] = _v80_history_queue_compact_acknowledged(
        owner, state.get("acknowledged"),
    )
    state["deadLetter"] = list(state.get("deadLetter") or [])[-HISTORY_EVENT_QUEUE_MAX_DEAD:]
    state["deferred"] = _v80_history_queue_compact_deferred(
        owner, state.get("deferred"), len(state["events"]),
    )
    setter = getattr(owner, "setCache", None)
    if not callable(setter):
        raise _V80HistoryQueuePersistenceError("History 事件队列缺少持久化写入能力")
    try:
        result = setter(_v80_history_queue_cache_key(state["scope"]), state)
    except Exception as exc:
        raise _V80HistoryQueuePersistenceError("History 事件队列保存失败") from exc
    if result is False or result == "failed":
        raise _V80HistoryQueuePersistenceError("History 事件队列保存失败")
    owner._v80_history_event_queue = state
    return state


def _v80_history_queue_current_uid(owner):
    if (
        _v80_history_text(getattr(owner, "_v80_history_auth_username", ""))
        != _v80_history_text(getattr(owner, "history_username", ""))
        or _v80_history_int(getattr(owner, "_v80_history_auth_generation", -1), -1)
        != _v80_history_int(getattr(owner, "_cache_generation", 0), 0)
    ):
        return 0
    return max(0, _v80_history_int(getattr(owner, "_v80_history_auth_uid", 0), 0))


def _v80_history_queue_bind_uid(owner, scope, uid):
    uid = max(0, _v80_history_int(uid, 0))
    if uid <= 0:
        return True
    state = _v80_history_queue_state_get(owner, scope)
    bound_uid = max(0, _v80_history_int(state.get("accountUid"), 0))
    if bound_uid == uid:
        return True
    if bound_uid > 0 and any(state.get(name) for name in (
        "events", "acknowledged", "deadLetter", "deferred",
    )):
        _v80_history_queue_quarantine(owner, scope, state, "account uid changed")
        owner._v80_history_queue_transition_pending = {}
        replacement = _v80_history_queue_empty(scope)
        replacement["accountUid"] = uid
        _v80_history_queue_state_set(owner, replacement)
        return False
    state["accountUid"] = uid
    _v80_history_queue_state_set(owner, state)
    return True


def _v80_history_queue_identity(payload):
    identity = _v80_history_identity(payload)
    if identity is None:
        raise RuntimeError("History 事件身份无效")
    return "\x1f".join(identity)


def _v80_history_queue_rank(action, payload):
    timestamp = _v80_history_int(
        payload.get("deletedAt") if action == "delete" else payload.get("updatedAt"), 0,
    )
    return (
        max(0, timestamp),
        1 if action == "delete" else 0,
        max(0, _v80_history_int(payload.get("positionMs"), 0)),
        max(0, _v80_history_int(payload.get("durationMs"), 0)),
    )


def _v80_history_queue_latest_rank(state, identity, include_deferred=True):
    ranks = []
    names = ("events", "acknowledged", "deadLetter", "deferred")
    if not include_deferred:
        names = names[:-1]
    for name in names:
        for item in state.get(name) or []:
            if item.get("identity") == identity:
                ranks.append(_v80_history_queue_rank_value(item.get("rank")))
    return max(ranks) if ranks else None


def _v80_history_queue_deferred_items(owner, scope):
    return list(_v80_history_queue_state_get(owner, scope).get("deferred") or [])


def _v80_history_queue_defer(owner, state, action, payloads, now_ms):
    by_identity = {}
    for item in state.get("deferred") or []:
        if isinstance(item, dict):
            by_identity[item.get("identity")] = item
    for raw in payloads:
        if not isinstance(raw, dict):
            continue
        payload = dict(raw)
        timestamp_key = "deletedAt" if action == "delete" else "updatedAt"
        if _v80_history_int(payload.get(timestamp_key), 0) <= 0:
            payload[timestamp_key] = now_ms
        identity = _v80_history_queue_identity(payload)
        rank = _v80_history_queue_rank(action, payload)
        previous = by_identity.get(identity)
        if previous is None or rank > _v80_history_queue_rank_value(previous.get("rank")):
            by_identity[identity] = {
                "identity": identity,
                "action": action,
                "payload": payload,
                "rank": list(rank),
            }
    items = list(by_identity.values())
    items.sort(key=lambda item: _v80_history_queue_rank_value(item["rank"]), reverse=True)
    state["deferred"] = _v80_history_queue_compact_deferred(
        owner, items, len(state.get("events") or []),
    )
    return len(state["deferred"])


def _v80_history_queue_enqueue(
    owner, action, payloads, scope=None, defer_overflow=False, from_deferred=False,
):
    scope = _v80_history_text(scope) or _v80_history_queue_scope(owner)
    state = _v80_history_queue_state_get(owner, scope)
    current_uid = _v80_history_queue_current_uid(owner)
    bound_uid = max(0, _v80_history_int(state.get("accountUid"), 0))
    if current_uid > 0 and bound_uid > 0 and current_uid != bound_uid:
        _v80_history_queue_quarantine(owner, scope, state, "account uid changed")
        owner._v80_history_queue_transition_pending = {}
        state = _v80_history_queue_empty(scope)
    if current_uid > 0:
        state["accountUid"] = current_uid
    now_ms = max(1, int(time.time() * 1000))
    added = []
    values = list(payloads) if isinstance(payloads, (list, tuple)) else []
    overflow = []
    changed = False
    for index, raw in enumerate(values):
        if not isinstance(raw, dict):
            continue
        payload = dict(raw)
        timestamp_key = "deletedAt" if action == "delete" else "updatedAt"
        timestamp = max(0, _v80_history_int(payload.get(timestamp_key), 0))
        if timestamp <= 0:
            timestamp = now_ms
            payload[timestamp_key] = timestamp
        identity = _v80_history_queue_identity(payload)
        rank = _v80_history_queue_rank(action, payload)
        deferred_ranks = [
            _v80_history_queue_rank_value(item.get("rank"))
            for item in state["deferred"] if item.get("identity") == identity
        ]
        deferred_rank = max(deferred_ranks) if deferred_ranks else None
        previous_rank = _v80_history_queue_latest_rank(
            state, identity, include_deferred=not from_deferred,
        )
        if previous_rank is not None and action == "delete" and rank <= previous_rank:
            payload[timestamp_key] = previous_rank[0] + 1
            rank = _v80_history_queue_rank(action, payload)
        if previous_rank is not None and rank <= previous_rank:
            if deferred_rank is not None and rank <= deferred_rank and not from_deferred:
                continue
            retained = [
                item for item in state["deferred"] if item.get("identity") != identity
            ]
            if len(retained) != len(state["deferred"]):
                state["deferred"] = retained
                changed = True
            continue
        if previous_rank is not None and rank[0] <= previous_rank[0]:
            payload[timestamp_key] = previous_rank[0] + 1
            rank = _v80_history_queue_rank(action, payload)
        active = [item for item in state["events"] if item.get("identity") != identity]
        if len(active) >= HISTORY_EVENT_QUEUE_MAX_ACTIVE:
            has_deferred = any(
                item.get("identity") == identity for item in state["deferred"]
            )
            if defer_overflow or has_deferred:
                overflow = [payload] + values[index + 1:]
                break
            raise RuntimeError("History 事件队列已满，未丢弃未确认事件")
        state["events"] = active
        state["deferred"] = [
            item for item in state["deferred"] if item.get("identity") != identity
        ]
        state["deadLetter"] = [
            item for item in state["deadLetter"] if item.get("identity") != identity
        ]
        sequence = state["nextSequence"]
        raw_id = "%s|%s|%s|%s|%s" % (
            scope, sequence, identity, action, rank[0],
        )
        event_id = hashlib.sha256(raw_id.encode("utf-8")).hexdigest()
        entry = {
            "id": event_id,
            "identity": identity,
            "action": action,
            "status": "pending",
            "payload": payload,
            "rank": list(rank),
            "sequence": sequence,
            "attempts": 0,
            "queuedAt": now_ms,
            "nextAttemptAt": 0,
            "lastError": "",
        }
        state["events"].append(entry)
        state["nextSequence"] = sequence + 1
        added.append(event_id)
        changed = True
    if overflow:
        _v80_history_queue_defer(owner, state, action, overflow, now_ms)
        changed = True
    if changed:
        _v80_history_queue_state_set(owner, state)
    if added:
        owner._diagnostic_event("history_queue.pending", count=len(added), scope=scope[:12])
    if overflow:
        owner._diagnostic_event(
            "history_queue.deferred", count=len(state["deferred"]), scope=scope[:12],
        )
        _v80_history_queue_schedule(
            owner, scope, now_ms + HISTORY_EVENT_QUEUE_RECOVERY_DELAY_MS,
        )
    return added


def _v80_history_queue_promote_deferred(owner, scope):
    state = _v80_history_queue_state_get(owner, scope)
    items = list(state.get("deferred") or [])
    if not items:
        return 0
    available = max(0, HISTORY_EVENT_QUEUE_MAX_ACTIVE - len(state.get("events") or []))
    if available <= 0:
        return 0
    selected = items[:available]
    added = 0
    for action in ("upsert", "delete"):
        payloads = [item["payload"] for item in selected if item["action"] == action]
        if not payloads:
            continue
        try:
            added += len(_v80_history_queue_enqueue(
                owner, action, payloads, scope=scope, from_deferred=True,
            ))
        except _V80HistoryQueuePersistenceError:
            _v80_history_queue_schedule_persistence(owner, scope)
            raise
    if selected:
        owner._diagnostic_event(
            "history_queue.promoted", count=len(selected), scope=scope[:12],
        )
    return added


def _v80_history_queue_transition(owner, scope, event_id, outcome, detail=""):
    state = _v80_history_queue_state_get(owner, scope)
    entry = next((item for item in state["events"] if item.get("id") == event_id), None)
    if entry is None:
        return state, None
    state["events"] = [item for item in state["events"] if item.get("id") != event_id]
    now_ms = max(1, int(time.time() * 1000))
    if outcome == "ack":
        state["acknowledged"].append({
            "id": entry["id"],
            "identity": entry["identity"],
            "action": entry["action"],
            "status": "ack",
            "rank": list(entry["rank"]),
            "acknowledgedAt": now_ms,
        })
    else:
        entry = dict(entry)
        entry["attempts"] += 1
        entry["lastError"] = _v80_history_text(detail)[:160]
        if outcome == "dead-letter" or entry["attempts"] >= HISTORY_EVENT_QUEUE_MAX_ATTEMPTS:
            entry["status"] = "dead-letter"
            entry["nextAttemptAt"] = 0
            state["deadLetter"].append(entry)
            outcome = "dead-letter"
        else:
            entry["status"] = "retry"
            delay_index = min(entry["attempts"] - 1, len(HISTORY_EVENT_QUEUE_BACKOFF_SECONDS) - 1)
            entry["nextAttemptAt"] = now_ms + HISTORY_EVENT_QUEUE_BACKOFF_SECONDS[delay_index] * 1000
            state["events"].append(entry)
    state = _v80_history_queue_state_set(owner, state)
    owner._diagnostic_event(
        "history_queue.%s" % outcome.replace("-", "_"),
        event_id=event_id[:12], attempts=entry.get("attempts", 0),
    )
    return state, entry


def _v80_history_queue_legacy_row(payload):
    return {
        "key": "%s@@@%s@@@0" % (payload.get("sourceKey"), payload.get("vodId")),
        "vodName": payload.get("vodName") or "",
        "vodPic": payload.get("vodPic") or "",
        "vodFlag": payload.get("vodFlag") or "",
        "vodRemarks": payload.get("episodeName") or "",
        "episodeUrl": payload.get("episodeUrl") or "",
        "episode": payload.get("episode", -1),
        "position": payload.get("positionMs", 0),
        "duration": payload.get("durationMs", 0),
        "opening": payload.get("openingMs", 0),
        "ending": payload.get("endingMs", 0),
        "speed": payload.get("speed", 1.0),
        "createTime": payload.get("updatedAt", 0),
    }


def _v80_history_queue_callbacks(owner, legacy_push=None, legacy_delete=None):
    if not callable(legacy_push):
        coordinator = getattr(owner, "_history_coordinator", None)
        legacy_push = getattr(coordinator, "_legacy_push", None)
    if not callable(legacy_delete):
        legacy_delete = getattr(owner, "_atvp_history_delete_legacy", None)
    return legacy_push, legacy_delete


def _v80_history_queue_send(owner, entry, legacy_push=None, legacy_delete=None):
    try:
        response = _v80_history_send(
            owner,
            "POST",
            PLAYBACK_EVENT_PATH,
            headers={"Idempotency-Key": entry["id"]},
            json=entry["payload"],
            _v80_queue_scope=_v80_history_queue_scope(owner),
            timeout=owner.timeout,
            verify=owner.verify_tls,
            stream=True,
        )
    except _V80PlaybackSyncUnsupported:
        _v80_history_prepare_legacy_fallback(owner)
        legacy_push, legacy_delete = _v80_history_queue_callbacks(
            owner, legacy_push=legacy_push, legacy_delete=legacy_delete,
        )
        if entry["action"] == "delete":
            if not callable(legacy_delete):
                raise
            legacy_delete(entry["payload"].get("historyKey") or (
                "%s@@@%s@@@0" % (
                    entry["payload"].get("sourceKey"), entry["payload"].get("vodId"),
                )
            ))
        else:
            if not callable(legacy_push):
                raise
            legacy_push([_v80_history_queue_legacy_row(entry["payload"])])
        owner._diagnostic_event("history_transport.legacy", contract=PLAYBACK_SYNC_CONTRACT)
        return 204
    try:
        return response.status_code
    finally:
        _v80_history_close(response)


def _v80_history_queue_transient_exception(exc):
    if isinstance(exc, _V80HistoryHttpError):
        status = exc.status_code
        return status in (408, 425, 429) or 500 <= status < 600
    return isinstance(exc, (
        requests.exceptions.ConnectionError,
        requests.exceptions.SSLError,
        requests.exceptions.Timeout,
    ))


def _v80_history_queue_cancel_timer(owner):
    timer = getattr(owner, "_v80_history_queue_timer", None)
    if timer is not None:
        try:
            timer.cancel()
        except Exception:
            pass
        tasks = getattr(owner, "_tasks", None)
        if tasks is not None:
            try:
                tasks.forget_timer(timer)
            except Exception:
                pass
    owner._v80_history_queue_timer = None
    owner._v80_history_queue_timer_token = None
    owner._v80_history_queue_timer_due = 0


def _v80_history_queue_schedule(owner, scope, due_at_ms):
    tasks = getattr(owner, "_tasks", None)
    if tasks is None:
        return False
    generation = _v80_history_int(getattr(owner, "_cache_generation", 0), 0)
    existing = getattr(owner, "_v80_history_queue_timer", None)
    existing_due = _v80_history_int(getattr(owner, "_v80_history_queue_timer_due", 0), 0)
    existing_generation = _v80_history_int(
        getattr(owner, "_v80_history_queue_timer_generation", -1), -1,
    )
    existing_scope = _v80_history_text(getattr(owner, "_v80_history_queue_timer_scope", ""))
    if (
        existing is not None
        and existing_generation == generation
        and existing_scope == scope
        and existing_due > 0
        and existing_due <= due_at_ms
    ):
        return True
    _v80_history_queue_cancel_timer(owner)
    token = object()
    delay = max(1.0, (due_at_ms - int(time.time() * 1000)) / 1000.0)
    timer = None

    def worker():
        try:
            lock = getattr(owner, "_history_context_lock", None)
            if lock is None:
                return
            with lock:
                if getattr(owner, "_v80_history_queue_timer_token", None) is not token:
                    return
                owner._v80_history_queue_timer = None
                owner._v80_history_queue_timer_token = None
                owner._v80_history_queue_timer_due = 0
                if (
                    _v80_history_int(getattr(owner, "_cache_generation", 0), 0) != generation
                    or _v80_history_queue_scope(owner) != scope
                ):
                    return
                _v80_history_queue_drain(owner, scope=scope, expected_generation=generation)
        except Exception as exc:
            try:
                owner._diagnostic_event("history_queue.background", "WARN", exc=exc)
            except Exception:
                pass
        finally:
            try:
                tasks.forget_timer(timer)
            except Exception:
                pass

    timer = threading.Timer(delay, worker)
    timer.daemon = True
    try:
        tasks.track_timer(timer)
        owner._v80_history_queue_timer = timer
        owner._v80_history_queue_timer_token = token
        owner._v80_history_queue_timer_due = due_at_ms
        owner._v80_history_queue_timer_generation = generation
        owner._v80_history_queue_timer_scope = scope
        timer.start()
        return True
    except Exception:
        try:
            tasks.forget_timer(timer)
        except Exception:
            pass
        _v80_history_queue_cancel_timer(owner)
        return False


def _v80_history_queue_schedule_next(owner, scope, state):
    events = state.get("events") or []
    if not events:
        _v80_history_queue_promote_deferred(owner, scope)
        state = _v80_history_queue_state_get(owner, scope)
        events = state.get("events") or []
        if not events:
            _v80_history_queue_cancel_timer(owner)
            return False
    now_ms = max(1, int(time.time() * 1000))
    due_at = min(
        item.get("nextAttemptAt") or (now_ms + 1000)
        for item in events
    )
    return _v80_history_queue_schedule(owner, scope, max(now_ms + 1000, due_at))


def _v80_history_queue_schedule_persistence(
    owner, scope, event_id=None, outcome=None, detail="",
):
    if event_id and outcome:
        pending = dict(
            getattr(owner, "_v80_history_queue_transition_pending", {}) or {},
        )
        pending[(scope, event_id)] = (outcome, _v80_history_text(detail)[:160])
        owner._v80_history_queue_transition_pending = pending
    due_at = max(1, int(time.time() * 1000)) + HISTORY_EVENT_QUEUE_RECOVERY_DELAY_MS
    return _v80_history_queue_schedule(owner, scope, due_at)


def _v80_history_queue_context_valid(owner, scope, expected_generation):
    return (
        _v80_history_int(getattr(owner, "_cache_generation", 0), 0) == expected_generation
        and _v80_history_queue_scope(owner) == scope
    )


def _v80_history_queue_drain(
    owner, scope=None, preferred_ids=None, legacy_push=None, legacy_delete=None,
    expected_generation=None,
):
    scope = _v80_history_text(scope) or _v80_history_queue_scope(owner)
    if not scope:
        raise RuntimeError("History 事件队列身份无效")
    if expected_generation is None:
        expected_generation = _v80_history_int(getattr(owner, "_cache_generation", 0), 0)
    preferred_ids = set(preferred_ids or ())
    processed = set()
    acknowledged = 0
    while len(processed) < HISTORY_EVENT_QUEUE_DRAIN_LIMIT:
        if not _v80_history_queue_context_valid(owner, scope, expected_generation):
            raise _V80HistoryQueueCancelled("History 事件队列身份已变化")
        _v80_history_queue_promote_deferred(owner, scope)
        state = _v80_history_queue_state_get(owner, scope)
        now_ms = max(1, int(time.time() * 1000))
        due = [
            item for item in state["events"]
            if item["id"] not in processed and item.get("nextAttemptAt", 0) <= now_ms
        ]
        if not due:
            _v80_history_queue_schedule_next(owner, scope, state)
            break
        due.sort(key=lambda item: (
            0 if item["id"] in preferred_ids else 1,
            item.get("nextAttemptAt", 0),
            item.get("sequence", 0),
        ))
        entry = due[0]
        processed.add(entry["id"])
        transition_key = (scope, entry["id"])
        transition_pending = dict(
            getattr(owner, "_v80_history_queue_transition_pending", {}) or {},
        )
        if transition_key in transition_pending:
            outcome, detail = transition_pending[transition_key]
            try:
                state, transitioned = _v80_history_queue_transition(
                    owner, scope, entry["id"], outcome, detail,
                )
            except _V80HistoryQueuePersistenceError:
                _v80_history_queue_schedule_persistence(
                    owner, scope, entry["id"], outcome, detail,
                )
                raise
            transition_pending.pop(transition_key, None)
            owner._v80_history_queue_transition_pending = transition_pending
            if outcome == "ack":
                acknowledged += 1
                continue
            if outcome == "retry" and transitioned is not None:
                _v80_history_queue_schedule_next(owner, scope, state)
                break
            continue
        try:
            status = _v80_history_queue_send(
                owner, entry, legacy_push=legacy_push, legacy_delete=legacy_delete,
            )
        except _V80HistoryQueuePersistenceError:
            _v80_history_queue_schedule_persistence(owner, scope)
            raise
        except (_V80PlaybackSyncUnsupported, _V80HistoryQueueCancelled):
            raise
        except Exception as exc:
            if not _v80_history_queue_context_valid(owner, scope, expected_generation):
                raise _V80HistoryQueueCancelled("History 事件队列异常响应已失效")
            if _v80_history_queue_transient_exception(exc):
                try:
                    state, _ = _v80_history_queue_transition(
                        owner, scope, entry["id"], "retry", exc.__class__.__name__,
                    )
                except _V80HistoryQueuePersistenceError:
                    _v80_history_queue_schedule_persistence(
                        owner, scope, entry["id"], "retry", exc.__class__.__name__,
                    )
                    raise
                _v80_history_queue_schedule_next(owner, scope, state)
                break
            try:
                state, _ = _v80_history_queue_transition(
                    owner, scope, entry["id"], "dead-letter", exc.__class__.__name__,
                )
            except _V80HistoryQueuePersistenceError:
                _v80_history_queue_schedule_persistence(
                    owner, scope, entry["id"], "dead-letter", exc.__class__.__name__,
                )
                raise
            continue
        if not _v80_history_queue_context_valid(owner, scope, expected_generation):
            raise _V80HistoryQueueCancelled("History 事件队列响应已失效")
        if 200 <= status < 300:
            try:
                state, _ = _v80_history_queue_transition(owner, scope, entry["id"], "ack")
            except _V80HistoryQueuePersistenceError:
                _v80_history_queue_schedule_persistence(
                    owner, scope, entry["id"], "ack",
                )
                raise
            acknowledged += 1
            continue
        if status in (408, 425, 429) or 500 <= status < 600:
            try:
                state, _ = _v80_history_queue_transition(
                    owner, scope, entry["id"], "retry", "HTTP %s" % status,
                )
            except _V80HistoryQueuePersistenceError:
                _v80_history_queue_schedule_persistence(
                    owner, scope, entry["id"], "retry", "HTTP %s" % status,
                )
                raise
            _v80_history_queue_schedule_next(owner, scope, state)
            break
        try:
            _v80_history_queue_transition(
                owner, scope, entry["id"], "dead-letter", "HTTP %s" % status,
            )
        except _V80HistoryQueuePersistenceError:
            _v80_history_queue_schedule_persistence(
                owner, scope, entry["id"], "dead-letter", "HTTP %s" % status,
            )
            raise
    else:
        state = _v80_history_queue_state_get(owner, scope)
        _v80_history_queue_schedule_next(owner, scope, state)
    return acknowledged


def v80_history_queue_snapshot(owner):
    scope = _v80_history_queue_scope(owner)
    if not scope:
        return None
    with owner._history_context_lock:
        return _v80_history_queue_state_get(owner, scope)


def v80_history_queue_start(owner):
    if not _v80_history_prepare_auth(owner):
        return False
    scope = _v80_history_queue_scope(owner)
    if not scope:
        return False
    with owner._history_context_lock:
        uid = _v80_history_queue_current_uid(owner)
        if uid > 0 and not _v80_history_queue_bind_uid(owner, scope, uid):
            return False
        state = _v80_history_queue_state_get(owner, scope)
        return _v80_history_queue_schedule_next(owner, scope, state)


def v80_history_queue_stop(owner):
    with owner._history_context_lock:
        _v80_history_queue_cancel_timer(owner)
        owner._v80_history_queue_transition_pending = {}


def v80_history_push(owner, rows, legacy_push):
    if not _v80_history_prepare_auth(owner):
        legacy_push(rows)
        return len(v80_history_events(rows, limit=owner.HISTORY_ROW_LIMIT, owner=owner))
    events = v80_history_events(rows, limit=owner.HISTORY_ROW_LIMIT, owner=owner)
    if not events:
        return 0
    with owner._history_context_lock:
        scope = _v80_history_queue_scope(owner)
        generation = _v80_history_int(getattr(owner, "_cache_generation", 0), 0)
        added = _v80_history_queue_enqueue(
            owner, "upsert", events, scope=scope, defer_overflow=len(events) > 1,
        )
        return _v80_history_queue_drain(
            owner, scope=scope, preferred_ids=added, legacy_push=legacy_push,
            expected_generation=generation,
        )


def v80_history_delete(owner, key, legacy_delete):
    delete_input = v80_history_delete_input(key, owner=owner)
    if delete_input is None or not _v80_history_prepare_auth(owner):
        return legacy_delete(key)
    with owner._history_context_lock:
        payload = dict(delete_input)
        payload.update({
            "action": "delete",
            "scope": "item",
            "historyKey": _v80_history_text(key),
            "deletedAt": max(1, int(time.time() * 1000)),
        })
        scope = _v80_history_queue_scope(owner)
        generation = _v80_history_int(getattr(owner, "_cache_generation", 0), 0)
        added = _v80_history_queue_enqueue(owner, "delete", [payload], scope=scope)
        _v80_history_queue_drain(
            owner, scope=scope, preferred_ids=added, legacy_delete=legacy_delete,
            expected_generation=generation,
        )
    return True

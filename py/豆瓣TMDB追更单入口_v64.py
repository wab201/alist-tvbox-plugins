# -*- coding: utf-8 -*-
"""
//@name:豆瓣TMDB追更助手（AList-TVBox专用）
//@id:douban_tmdb_follow_single
//@version:64

AList-TVBox raw Python plugin for Douban/TMDB browsing and follow-up playback.

Deploy this source through AList-TVBox plugin management and load the generated
subscription in FongMi/TvBox. The plugin Extend/data must contain
``atvp_plugin_mode=alist-tvbox-raw`` for follow, History, and cloud-resource
features. With an empty ext the same source remains a direct FongMi metadata
site with category/search/detail and direct-URL player compatibility. The same
source also exports ``Filter`` for AList-TVBox detail/player filter reuse.
"""

import base64
import datetime
import heapq
import hashlib
import http.client
import ipaddress
import json
import math
import re
import socket
import ssl
import threading
import time
import traceback
import unicodedata
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError, as_completed
from urllib.parse import parse_qs, quote, unquote, urlencode, urljoin, urlparse

import requests
from lxml import html
from requests.adapters import HTTPAdapter

from base.spider import Spider as BaseSpider


class _PinnedHTTPConnection(http.client.HTTPConnection):
    def __init__(self, host, connect_host, port=None, **kwargs):
        self._connect_host = str(connect_host)
        super().__init__(host, port=port, **kwargs)

    def connect(self):
        self.sock = socket.create_connection(
            (self._connect_host, self.port), self.timeout, self.source_address,
        )


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host, connect_host, port=None, **kwargs):
        self._connect_host = str(connect_host)
        super().__init__(host, port=port, **kwargs)

    def connect(self):
        raw_socket = socket.create_connection(
            (self._connect_host, self.port), self.timeout, self.source_address,
        )
        try:
            self.sock = self._context.wrap_socket(raw_socket, server_hostname=self.host)
        except Exception:
            raw_socket.close()
            raise


_DNS_EXECUTOR = ThreadPoolExecutor(max_workers=4)
_DNS_SLOTS = threading.BoundedSemaphore(4)
_MEDIA_PROBE_EXECUTOR = ThreadPoolExecutor(max_workers=4)
_MEDIA_PROBE_SLOTS = threading.BoundedSemaphore(4)


FILTER_CONFIG_SCHEMA = {
    "source": "declared",
    "description": "跨站追更选集过滤器，可配置标题统一、自动选集和播放位置注入；独立备选线路不共享直链",
    "allowAdditional": True,
    "example": {"history_cache_ttl": 30, "timeout": 8, "verify_tls": True},
    "fields": [
        {"key": "history_cache_ttl", "label": "History缓存秒数", "type": "number", "required": False, "defaultValue": 30},
        {"key": "timeout", "label": "请求超时秒数", "type": "number", "required": False, "defaultValue": 8},
        {"key": "verify_tls", "label": "校验HTTPS证书", "type": "boolean", "required": False, "defaultValue": True},
        {"key": "canonicalize_title", "label": "统一续播标题", "type": "boolean", "required": False, "defaultValue": True},
        {"key": "auto_select_episode", "label": "自动选中续播集", "type": "boolean", "required": False, "defaultValue": True},
        {"key": "inject_position", "label": "注入播放位置", "type": "boolean", "required": False, "defaultValue": True},
    ],
}

FOLLOWPLAY_PREFIX = "followplay_"
FOLLOWPLAY_LEGACY_PREFIX = "followplay://"
FOLLOWPLAY_PREFIXES = (FOLLOWPLAY_PREFIX, FOLLOWPLAY_LEGACY_PREFIX)

HISTORY_RESPONSE_MAX_BYTES = 4 * 1024 * 1024
HISTORY_ROW_MAX_BYTES = 128 * 1024
HISTORY_CONFIG_MAX_BYTES = 128 * 1024
HISTORY_ROW_LIMIT = 2048
HISTORY_FIELD_MAX_LENGTH = 65536
HISTORY_FIELDS = (
    "key", "vodPic", "vodName", "vodFlag", "vodRemarks", "episodeUrl",
    "revSort", "revPlay", "createTime", "opening", "ending", "position",
    "duration", "speed", "scale", "cid", "episode", "uid",
)
HISTORY_INTEGER_FIELDS = frozenset((
    "revSort", "revPlay", "createTime", "opening", "ending", "position",
    "duration", "cid", "episode", "uid",
))
HISTORY_FIELD_LIMITS = {
    "key": 2048,
    "vodPic": 8192,
    "vodName": 1024,
    "vodFlag": 1024,
    "vodRemarks": 4096,
    "episodeUrl": HISTORY_FIELD_MAX_LENGTH,
    "speed": 64,
    "scale": 64,
}

HISTORY_CLOCK_SKEW_MS = 5 * 60 * 1000
PLAY_GROUP_SCAN_LIMIT = 64
EPISODE_SCAN_LIMIT = 256


def _split_bounded_shared(value, separator, limit):
    text = str(value or "")
    limit = max(0, int(limit))
    if not text or limit <= 0:
        return [], bool(text)
    separator = str(separator or "")
    if not separator:
        return [text], False
    parts = []
    start = 0
    for _index in range(limit):
        found = text.find(separator, start)
        if found < 0:
            parts.append(text[start:])
            return parts, False
        parts.append(text[start:found])
        start = found + len(separator)
    return parts, True


def _history_utf8_size(value):
    return len(str(value or "").encode("utf-8", errors="ignore"))


def _history_clip_text(value, limit):
    text = str(value or "")
    encoded = text.encode("utf-8", errors="ignore")
    if len(encoded) <= limit:
        return text
    return encoded[:limit].decode("utf-8", errors="ignore")


def _normalize_history_row_shared(row):
    if not isinstance(row, dict):
        return None
    output = {}
    for key in HISTORY_FIELDS:
        if key not in row or row.get(key) is None:
            continue
        value = row.get(key)
        if key in HISTORY_INTEGER_FIELDS:
            try:
                output[key] = int(value)
            except Exception:
                try:
                    output[key] = int(float(value))
                except Exception:
                    output[key] = 0
            continue
        if isinstance(value, (dict, list, tuple, set)):
            continue
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            output[key] = value
            continue
        output[key] = _history_clip_text(
            value, HISTORY_FIELD_LIMITS.get(key, HISTORY_FIELD_MAX_LENGTH),
        )
    if not str(output.get("key") or "").strip():
        return None
    try:
        size = _history_utf8_size(json.dumps(output, ensure_ascii=False, separators=(",", ":")))
    except Exception:
        return None
    return output if size <= HISTORY_ROW_MAX_BYTES else None


def _normalize_history_rows_shared(rows):
    output = []
    total_bytes = 2
    for input_index, row in enumerate(rows if isinstance(rows, (list, tuple)) else []):
        if input_index >= HISTORY_ROW_LIMIT:
            break
        normalized = _normalize_history_row_shared(row)
        if not normalized:
            continue
        try:
            row_bytes = _history_utf8_size(json.dumps(normalized, ensure_ascii=False, separators=(",", ":")))
        except Exception:
            continue
        separator_bytes = 1 if output else 0
        if total_bytes + separator_bytes + row_bytes > HISTORY_RESPONSE_MAX_BYTES:
            break
        output.append(normalized)
        total_bytes += separator_bytes + row_bytes
        if len(output) >= HISTORY_ROW_LIMIT:
            break
    return output


def _read_bounded_json_shared(response, label, max_bytes, deadline=None):
    try:
        try:
            content_length = int((getattr(response, "headers", {}) or {}).get("Content-Length") or 0)
        except Exception:
            content_length = 0
        if content_length > max_bytes:
            raise RuntimeError("%s 响应过大" % label)
        chunks = []
        received = 0
        iterator = getattr(response, "iter_content", None)
        parts = iterator(chunk_size=65536) if callable(iterator) else [getattr(response, "content", b"")]
        for chunk in parts:
            if deadline is not None and time.monotonic() >= deadline:
                raise RuntimeError("%s 响应超过总时限" % label)
            if not chunk:
                continue
            received += len(chunk)
            if received > max_bytes:
                raise RuntimeError("%s 响应过大" % label)
            chunks.append(chunk)
        try:
            return json.loads(b"".join(chunks))
        except Exception:
            raise RuntimeError("%s 返回无效 JSON" % label)
    finally:
        closer = getattr(response, "close", None)
        if callable(closer):
            closer()


class _HistorySyncCancelled(RuntimeError):
    pass


class _TaskSupervisor:
    """Track background work and reject new submissions after shutdown."""

    def __init__(self):
        self._lock = threading.RLock()
        self._threads = set()
        self._timers = set()
        self._executors = set()
        self._closed = False

    def register_executor(self, executor):
        with self._lock:
            if not self._closed and executor is not None:
                self._executors.add(executor)
        return executor

    def is_closed(self):
        with self._lock:
            return self._closed

    def start_thread(self, target, args=(), kwargs=None, name="background"):
        kwargs = dict(kwargs or {})
        holder = {}

        def run():
            try:
                target(*args, **kwargs)
            finally:
                with self._lock:
                    self._threads.discard(holder.get("thread"))

        with self._lock:
            if self._closed:
                raise RuntimeError("后台任务管理器已关闭")
            thread = threading.Thread(target=run)
            try:
                thread.name = str(name or "background")
            except Exception:
                pass
            thread.daemon = True
            holder["thread"] = thread
            self._threads.add(thread)
            try:
                thread.start()
            except Exception:
                self._threads.discard(thread)
                raise
        return True

    def track_timer(self, timer):
        with self._lock:
            if self._closed:
                raise RuntimeError("后台任务管理器已关闭")
            if timer is not None:
                self._timers.add(timer)
        return timer

    def forget_timer(self, timer):
        with self._lock:
            self._timers.discard(timer)

    def start_timer(self, delay, target, args=(), name="timer"):
        holder = {}

        def run():
            try:
                target(*args)
            finally:
                with self._lock:
                    self._timers.discard(holder.get("timer"))

        with self._lock:
            if self._closed:
                raise RuntimeError("后台任务管理器已关闭")
            timer = threading.Timer(max(0.0, float(delay)), run)
            timer.daemon = True
            holder["timer"] = timer
            self._timers.add(timer)
        try:
            timer.start()
        except Exception:
            with self._lock:
                self._timers.discard(timer)
            raise
        return timer

    def shutdown(self, wait=False):
        with self._lock:
            self._closed = True
            timers = list(self._timers)
            threads = list(self._threads)
            executors = list(self._executors)
            self._timers.clear()
            self._threads.clear()
            self._executors.clear()
        for timer in timers:
            try:
                timer.cancel()
            except Exception:
                pass
        for executor in executors:
            try:
                executor.shutdown(wait=wait, cancel_futures=True)
            except TypeError:
                try:
                    executor.shutdown(wait=wait)
                except Exception:
                    pass
            except Exception:
                pass
        if wait:
            for thread in threads:
                try:
                    thread.join(1.0)
                except Exception:
                    pass


class _CacheCoordinator:
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


class _TMDBClient:
    """Own TMDB request policy while using Spider's runtime-safe transport hooks."""

    def __init__(self, owner):
        self.owner = owner

    def api(self, path, params=None, ttl=None, allow_stale=True):
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

    def image(self, path):
        owner = self.owner
        value = str(path or "").strip()
        if not value:
            return ""
        if value.startswith(("http://", "https://")):
            return value
        return owner.tmdb_image_base.rstrip("/") + "/" + value.lstrip("/")


class _FollowRepository:
    """Own follow-state persistence while migration and merging stay in Spider."""

    def __init__(self, owner):
        self.owner = owner

    def persist(self, state):
        owner = self.owner
        with owner._follow_enrich_lock:
            if not owner._follow_state_loaded:
                return False
        with owner._follow_state_persist_lock:
            persisted = False
            setter = getattr(owner, "setCache", None)
            if callable(setter):
                try:
                    result = setter(owner.FOLLOW_CACHE_KEY, state)
                    persisted = result != "failed"
                except Exception as exc:
                    owner._diagnostic_event("follow.persist.local", "WARN", exc=exc)
            if owner._follow_cache_origin:
                session = requests.Session()
                session.trust_env = False
                try:
                    response = session.post(
                        owner._follow_cache_origin + "/cache",
                        params={"do": "set", "key": owner.FOLLOW_CACHE_KEY},
                        data={"value": json.dumps(state, ensure_ascii=False)},
                        timeout=1,
                    )
                    persisted = response.status_code == 200 or persisted
                except Exception as exc:
                    owner._diagnostic_event("follow.persist.loopback", "WARN", exc=exc)
                finally:
                    session.close()
            return persisted

class _HistoryCoordinator:
    """Own History fetch/push transport while merge orchestration stays in Spider."""

    def __init__(self, owner):
        self.owner = owner

    def fetch(self):
        owner = self.owner
        response = owner._atvp_history_request("GET", stream=True)
        if response.status_code in (401, 403):
            response.close()
            raise RuntimeError("AList-TVBox 历史令牌无效")
        if response.status_code != 200:
            try:
                raise RuntimeError(owner._atvp_history_http_error(response, "读取"))
            finally:
                response.close()
        value = owner._read_bounded_json_response(
            response, "AList-TVBox History", max_bytes=owner.HISTORY_RESPONSE_MAX_BYTES,
        )
        if not isinstance(value, list):
            raise RuntimeError("AList-TVBox 历史格式无效")
        return owner._normalize_history_rows(value)

    def push(self, rows):
        owner = self.owner
        if not owner._history_write_enabled():
            raise RuntimeError("History 写入未启用：请同时配置用户名和密码")
        response = owner._atvp_history_request("POST", json=owner._history_upload_payload(rows))
        try:
            if response.status_code < 200 or response.status_code >= 300:
                raise RuntimeError(owner._atvp_history_http_error(response, "写入"))
        finally:
            try:
                response.close()
            except Exception:
                pass

    def sync_once(self, expected_generation=None):
        return self.owner._sync_history_once(expected_generation=expected_generation)

class _DoubanClient:
    """Own Douban transport primitives; Spider keeps the legacy proxy methods."""

    def __init__(self, owner):
        self.owner = owner

    def request_json(self, url, params=None):
        owner = self.owner
        response = owner._session.get(
            url, params=params, timeout=owner.timeout, verify=owner.verify_tls,
        )
        payload = owner._json_response(response)
        if response.status_code != 200:
            raise RuntimeError("HTTP %s" % response.status_code)
        return payload

    def request_text(self, url, params=None):
        owner = self.owner
        response = owner._session.get(
            url, params=params, timeout=owner.timeout, verify=owner.verify_tls,
        )
        if response.status_code != 200:
            raise RuntimeError("HTTP %s" % response.status_code)
        text = response.text
        if len(text) < 500:
            raise RuntimeError("页面内容异常短")
        return text


class Filter:
    """AList-TVBox detail/player filter sharing this file with the Spider."""

    FOLLOW_CACHE_KEY = "douban_tmdb_follow_state_v1"
    # Preserve the standard playback headers returned by AList-TVBox for every
    # cloud-drive provider; Quark Cookie rejection is one confirmed example.
    SAFE_ROUTE_HEADERS = frozenset((
        "user-agent", "referer", "origin", "cookie",
        "accept", "range", "content-type",
    ))
    HISTORY_RESPONSE_MAX_BYTES = HISTORY_RESPONSE_MAX_BYTES
    HISTORY_ROW_LIMIT = HISTORY_ROW_LIMIT
    FOLLOWPLAY_MAX_ID_LENGTH = 65536
    FOLLOWPLAY_MAX_DECODED_LENGTH = 49152

    def __init__(self):
        self.history_cache_ttl = 30
        self.timeout = 8
        self.verify_tls = True
        self.trust_env = False
        self.canonicalize_title = True
        self.auto_select_episode = True
        self.inject_position = True
        self._session = requests.Session()
        self._session.trust_env = False
        self._history_cache = []
        self._history_cache_at = 0
        self._history_cache_key = ""
        self._lock = threading.RLock()

    def init(self, extend="", context=None):
        config = self._config(extend)
        self.history_cache_ttl = self._bounded_int(config.get("history_cache_ttl"), 30, 5, 300)
        self.timeout = self._bounded_int(config.get("timeout"), 8, 3, 20)
        self.verify_tls = self._bool(config.get("verify_tls"), True)
        self.trust_env = self._bool(config.get("trust_env"), False)
        self.canonicalize_title = self._bool(config.get("canonicalize_title"), True)
        self.auto_select_episode = self._bool(config.get("auto_select_episode"), True)
        self.inject_position = self._bool(config.get("inject_position"), True)
        self._session.trust_env = self.trust_env
        with self._lock:
            self._history_cache = []
            self._history_cache_at = 0
            self._history_cache_key = ""

    def detail(self, result, context=None):
        if not isinstance(result, dict):
            return result
        rows = self._history_rows(context)
        if not rows:
            return result
        vods = result.get("list")
        if not isinstance(vods, list):
            return result
        output = dict(result)
        output["list"] = [self._filter_vod(vod, rows) if isinstance(vod, dict) else vod for vod in vods]
        return output

    def player(self, result, context=None):
        if not isinstance(result, dict) or not isinstance(context, dict):
            return result
        rows = self._history_rows(context)
        record = self._match_record({
            "vod_name": context.get("vod_name"),
            "vod_year": context.get("vod_year"),
            "vod_play_from": context.get("play_from"),
            "vod_play_url": "%s$%s" % (context.get("episode_name") or "", context.get("id") or ""),
        }, rows, require_episode=False)
        if not record or not self._context_matches_episode(context, record):
            return result
        output = dict(result)
        if (self.inject_position
                and output.get("position") in (None, "", 0, "0")
                and self._can_resume(record["history"])):
            output["position"] = self._int(record["history"].get("position"), 0)
        return output

    @staticmethod
    def _token_hash(token):
        return hashlib.sha256(str(token or "").encode("utf-8")).hexdigest()[:20]

    @staticmethod
    def _first_http_url(value):
        values = value if isinstance(value, (list, tuple)) else [value]
        for item in values:
            text = str(item or "").strip()
            if text.startswith(("http://", "https://")):
                return text
        return ""

    @staticmethod
    def _safe_media_url(value, backend_api):
        try:
            parsed = urlparse(str(value or "").strip())
            if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
                return False
            hostname = parsed.hostname.strip().lower()
            if hostname == "localhost":
                return False
            address = ipaddress.ip_address(hostname)
            if getattr(address, "ipv4_mapped", None) is not None:
                address = address.ipv4_mapped
            if address.is_loopback or address.is_unspecified or address.is_link_local or address.is_multicast or address.is_reserved:
                return False
            backend_host = urlparse(str(backend_api or "")).hostname or ""
            try:
                backend_address = ipaddress.ip_address(backend_host)
                backend_private = backend_address.is_private and not backend_address.is_loopback
            except ValueError:
                backend_private = False
            if address.is_private and not backend_private:
                return False
        except ValueError:
            # Ordinary DNS hostnames are allowed; malformed IP/URL forms are not.
            try:
                parsed = urlparse(str(value or "").strip())
                return bool(parsed.scheme in ("http", "https") and parsed.hostname and "." in parsed.hostname)
            except Exception:
                return False
        except Exception:
            return False
        return True

    def _filter_vod(self, vod, rows):
        record = self._match_record(vod, rows, require_episode=True)
        if not record:
            return vod
        output = dict(vod)
        canonical = str(record["history"].get("vodName") or record["payload"].get("title") or "").strip()
        if canonical and self.canonicalize_title:
            output["vod_name"] = canonical
        self._promote_target_season_group(output, record)
        if self.auto_select_episode and self._can_resume(record["history"]):
            self._select_target_episode(output, record)
        return output

    def _can_resume(self, history):
        position = self._int(history.get("position"), 0) if isinstance(history, dict) else 0
        duration = self._int(history.get("duration"), 0) if isinstance(history, dict) else 0
        return 0 < position < duration

    def _select_target_episode(self, vod, record):
        payload = record.get("payload") if isinstance(record, dict) else {}
        season = self._int(payload.get("season"), 0)
        episode = self._int(payload.get("episode"), 0)
        if season <= 0 or episode <= 0:
            return
        groups = self._episode_groups(vod)
        locations = self._target_episode_locations(vod, groups, season, episode)
        if not locations:
            return
        target_group, _target_episode = locations[0]
        target_episodes = dict(locations)
        flags = []
        for index, group in enumerate(groups):
            source = str(group.get("source") or "")
            source_flag = dict(group.get("flag") or {})
            episodes = []
            for part_index, item in enumerate(group.get("episodes") or []):
                if not isinstance(item, dict):
                    continue
                row = dict(item)
                row["selected"] = target_episodes.get(index) == part_index
                episodes.append(row)
            if not episodes:
                continue
            source_flag["flag"] = str(source_flag.get("flag") or source)
            source_flag["urls"] = self._serialize_episodes(episodes)
            source_flag["selected"] = index == target_group
            source_flag["position"] = target_episodes.get(index, 0)
            source_flag["episodes"] = episodes
            flags.append(source_flag)
        if flags:
            vod["vodFlags"] = flags
            vod["vod_play_from"] = "$$$".join(str(flag.get("flag") or "") for flag in flags)
            vod["vod_play_url"] = "$$$".join(str(flag.get("urls") or "") for flag in flags)

    def _target_episode_locations(self, vod, groups, season, episode):
        candidates = []
        vod_season = self._season(vod.get("vod_name"))
        for group_index, group in enumerate(groups):
            group_season = self._season(group.get("source"))
            preferred = bool((group.get("flag") or {}).get("selected"))
            for episode_index, item in enumerate(group.get("episodes") or []):
                if not isinstance(item, dict) or not str(item.get("url") or "").strip():
                    continue
                label = str(item.get("name") or "")
                found_season, found_episode, explicit = self._episode(label)
                if found_episode != episode:
                    continue
                if explicit:
                    if found_season != season:
                        continue
                    score = 3
                elif group_season == season or vod_season == season:
                    score = 2
                elif not group_season and not vod_season:
                    score = 1
                else:
                    continue
                candidates.append((score, preferred, group_index, episode_index))
        if not candidates:
            return []
        best_score = max(row[0] for row in candidates)
        best = [row for row in candidates if row[0] == best_score]
        if best_score == 1 and len(best) != 1:
            return []
        trusted = best if best_score == 1 else [row for row in candidates if row[0] >= 2]
        trusted.sort(key=lambda row: (-row[0], not row[1], row[2], row[3]))
        locations = []
        seen_groups = set()
        for _score, _preferred, group_index, episode_index in trusted:
            if group_index in seen_groups:
                continue
            seen_groups.add(group_index)
            locations.append((group_index, episode_index))
        return locations

    @staticmethod
    def _parse_episode_group(value):
        episodes = []
        parts, _limited = _split_bounded_shared(value, "#", EPISODE_SCAN_LIMIT)
        for part in parts:
            name, separator, play_id = part.partition("$")
            if separator and play_id:
                episodes.append({"name": name, "url": play_id})
        return episodes

    @staticmethod
    def _serialize_episodes(episodes):
        return "#".join(
            "%s$%s" % (item.get("name") or "", item.get("url") or "")
            for item in episodes
            if isinstance(item, dict) and str(item.get("url") or "").strip()
        )

    def _episode_groups(self, vod):
        sources, _sources_limited = _split_bounded_shared(
            vod.get("vod_play_from"), "$$$", PLAY_GROUP_SCAN_LIMIT,
        )
        urls, _urls_limited = _split_bounded_shared(
            vod.get("vod_play_url"), "$$$", PLAY_GROUP_SCAN_LIMIT,
        )
        existing = vod.get("vodFlags")
        groups = []
        if isinstance(existing, list) and existing:
            for index, value in enumerate(existing[:PLAY_GROUP_SCAN_LIMIT]):
                if not isinstance(value, dict):
                    continue
                flag = dict(value)
                source = str(flag.get("flag") or (sources[index] if index < len(sources) else ""))
                raw_episodes = flag.get("episodes") or []
                episodes = [
                    dict(item) for item in raw_episodes[:EPISODE_SCAN_LIMIT]
                    if isinstance(item, dict)
                ] if isinstance(raw_episodes, list) else []
                if not episodes:
                    episodes = self._parse_episode_group(flag.get("urls"))
                if not episodes and index < len(urls):
                    episodes = self._parse_episode_group(urls[index])
                groups.append({"source": source, "episodes": episodes, "flag": flag})
            if groups:
                return groups
        for index, url_group in enumerate(urls):
            episodes = self._parse_episode_group(url_group)
            if not episodes:
                continue
            source = sources[index] if index < len(sources) else ""
            groups.append({"source": source, "episodes": episodes, "flag": {}})
        return groups

    def _match_record(self, vod, rows, require_episode):
        vod_name = str(vod.get("vod_name") or "").strip()
        normalized = self._normalize_title(vod_name)
        if not normalized:
            return None
        vod_year = self._year(vod.get("vod_year") or vod_name)
        vod_season = self._season(vod_name)
        candidates = []
        for row in rows:
            payload = self._followplay(row.get("episodeUrl"))
            if not payload or str(payload.get("mediaType") or "") == "movie":
                continue
            aliases = {
                self._normalize_title(row.get("vodName")),
                self._normalize_title(payload.get("title")),
                self._normalize_title(payload.get("originalTitle")),
            }
            aliases.update(
                self._normalize_title(value)
                for value in self._payload_title_aliases(payload)
            )
            aliases.discard("")
            title_score = max([self._title_score(normalized, alias) for alias in aliases] or [0])
            if title_score <= 0:
                continue
            payload_year = self._year(payload.get("year"))
            if vod_year and payload_year and vod_year != payload_year:
                continue
            target_season = self._int(payload.get("season"), 0)
            target_episode = self._int(payload.get("episode"), 0)
            if not target_season or not target_episode:
                continue
            if vod_season and vod_season != target_season:
                continue
            record = {"history": row, "payload": payload, "title_score": title_score}
            if require_episode and not self._vod_supports_target(vod, record):
                continue
            candidates.append(record)
        if not candidates:
            return None
        top_score = max(item["title_score"] for item in candidates)
        candidates = [item for item in candidates if item["title_score"] == top_score]
        identities = {
            str(item["payload"].get("tmdbId") or item["payload"].get("sourceId") or "").strip()
            for item in candidates
        }
        identities.discard("")
        if len(identities) > 1:
            return None
        candidates.sort(key=lambda item: self._int(item["history"].get("createTime"), 0), reverse=True)
        return candidates[0]

    def _vod_supports_target(self, vod, record):
        season = self._int(record["payload"].get("season"), 0)
        episode = self._int(record["payload"].get("episode"), 0)
        vod_season = self._season(vod.get("vod_name"))
        exact = False
        target_matches = []
        for group_name, labels in self._vod_groups(vod):
            group_season = self._season(group_name)
            for label in labels:
                found_season, found_episode, explicit = self._episode(label)
                if found_episode != episode:
                    continue
                actual_season = found_season if explicit and found_season else group_season
                target_matches.append(actual_season)
                if explicit:
                    exact = exact or found_season == season
                elif group_season == season or vod_season == season:
                    exact = True
        if exact:
            return True
        if len(target_matches) != 1:
            return False
        return target_matches[0] in (0, season)

    def _promote_target_season_group(self, vod, record):
        season = self._int(record["payload"].get("season"), 0)
        episode = self._int(record["payload"].get("episode"), 0)
        sources, sources_limited = _split_bounded_shared(
            vod.get("vod_play_from"), "$$$", PLAY_GROUP_SCAN_LIMIT,
        )
        urls, urls_limited = _split_bounded_shared(
            vod.get("vod_play_url"), "$$$", PLAY_GROUP_SCAN_LIMIT,
        )
        if not sources_limited and not urls_limited and len(sources) == len(urls) and len(urls) > 1:
            index = self._target_group_index(sources, urls, season, episode)
            if index > 0:
                sources.insert(0, sources.pop(index))
                urls.insert(0, urls.pop(index))
                vod["vod_play_from"] = "$$$".join(sources)
                vod["vod_play_url"] = "$$$".join(urls)
        flags = vod.get("vodFlags")
        if isinstance(flags, list) and len(flags) > 1:
            flag_sources = [str(flag.get("flag") or "") if isinstance(flag, dict) else "" for flag in flags]
            flag_urls = []
            for flag in flags[:PLAY_GROUP_SCAN_LIMIT]:
                if not isinstance(flag, dict):
                    flag_urls.append("")
                    continue
                episodes = flag.get("episodes")
                if isinstance(episodes, list):
                    flag_urls.append("#".join(
                        "%s$%s" % (item.get("name") or "", item.get("url") or "")
                        for item in episodes[:EPISODE_SCAN_LIMIT] if isinstance(item, dict)
                    ))
                else:
                    flag_urls.append(str(flag.get("urls") or ""))
            index = self._target_group_index(flag_sources, flag_urls, season, episode)
            if index > 0:
                updated = list(flags)
                updated.insert(0, updated.pop(index))
                vod["vodFlags"] = updated

    def _target_group_index(self, sources, urls, season, episode):
        ranked = []
        numeric_matches = []
        for index, value in enumerate(list(urls or [])[:PLAY_GROUP_SCAN_LIMIT]):
            source_season = self._season(sources[index] if index < len(sources) else "")
            score = 0
            parts, _limited = _split_bounded_shared(value, "#", EPISODE_SCAN_LIMIT)
            for part in parts:
                label = part.partition("$")[0]
                found_season, found_episode, explicit = self._episode(label)
                if found_episode != episode:
                    continue
                actual_season = found_season if explicit and found_season else source_season
                numeric_matches.append((index, actual_season))
                if explicit and found_season == season:
                    score = max(score, 120)
                elif not explicit and source_season == season:
                    score = max(score, 100)
            if score:
                ranked.append((score, -index, index))
        if ranked:
            ranked.sort(reverse=True)
            return ranked[0][2]
        if len(numeric_matches) == 1 and numeric_matches[0][1] in (0, season):
            return numeric_matches[0][0]
        return -1

    def _context_matches_episode(self, context, record):
        season = self._int(record["payload"].get("season"), 0)
        episode = self._int(record["payload"].get("episode"), 0)
        group_season = self._season(context.get("play_from"))
        found_season, found_episode, explicit = self._episode(context.get("episode_name"))
        if found_episode != episode:
            return False
        actual_season = found_season if explicit and found_season else group_season
        return not actual_season or actual_season == season

    def _history_rows(self, context):
        if not isinstance(context, dict):
            return []
        api = str(context.get("api") or "").rstrip("/")
        token = str(context.get("token") or "").strip()
        cache_key = api + "|" + token
        now = time.time()
        with self._lock:
            if self._history_cache_key == cache_key and now - self._history_cache_at < self.history_cache_ttl:
                return list(self._history_cache)
        rows = self._local_follow_history_rows()
        if rows:
            with self._lock:
                self._history_cache = rows
                self._history_cache_at = now
                self._history_cache_key = cache_key
            return list(rows)
        if not re.match(r"^https?://", api, re.I) or not token:
            return []
        try:
            response = self._session.get(
                api + "/history/" + quote(token, safe=""),
                timeout=self.timeout,
                verify=self.verify_tls,
                headers={"Accept": "application/json"},
                stream=True,
            )
            if response.status_code < 200 or response.status_code >= 300:
                response.close()
                return []
            payload = _read_bounded_json_shared(
                response, "AList-TVBox Filter History", self.HISTORY_RESPONSE_MAX_BYTES,
            )
            rows = _normalize_history_rows_shared(payload)
        except Exception:
            return []
        with self._lock:
            self._history_cache = rows
            self._history_cache_at = now
            self._history_cache_key = cache_key
        return list(rows)

    def _local_follow_history_rows(self):
        try:
            from com.github.catvod import Proxy
            port = int(Proxy.getPort())
            response = self._session.get(
                "http://127.0.0.1:%s/cache" % port,
                params={"do": "get", "key": self.FOLLOW_CACHE_KEY},
                timeout=min(self.timeout, 5),
                stream=True,
            )
            if response.status_code < 200 or response.status_code >= 300:
                response.close()
                return []
            value = _read_bounded_json_shared(
                response, "FongMi 追更缓存", self.HISTORY_RESPONSE_MAX_BYTES,
            )
        except Exception:
            return []
        return self._follow_state_history_rows(value)

    @staticmethod
    def _follow_state_history_rows(state):
        items = state.get("items") if isinstance(state, dict) else None
        if not isinstance(items, dict):
            return []
        rows = []
        state_updated = Filter._int(state.get("updated_at"), 0)
        for index, (key, item) in enumerate(items.items()):
            if index >= Filter.HISTORY_ROW_LIMIT:
                break
            if not isinstance(item, dict):
                continue
            match = re.match(r"^S0*(\d{1,2})E0*(\d{1,3})$", str(item.get("history_episode") or ""), re.I)
            if not match:
                continue
            season, episode = int(match.group(1)), int(match.group(2))
            tmdb_id = Filter._int(item.get("tmdb_id") or key, 0)
            title = _history_clip_text(
                item.get("title") or item.get("history_vod_name") or "", 1024,
            ).strip()
            if not tmdb_id or not title:
                continue
            aliases = item.get("title_aliases")
            if not isinstance(aliases, list):
                aliases = [value.strip() for value in str(aliases or "").split("\n") if value.strip()]
            aliases = [_history_clip_text(value, 1024) for value in aliases[:16]]
            history_title = _history_clip_text(item.get("history_vod_name") or "", 1024).strip()
            if history_title and history_title not in aliases:
                aliases.append(history_title)
            payload = {
                "sourceId": "tmdb:tv:%s" % tmdb_id,
                "mediaType": "tv",
                "tmdbId": str(tmdb_id),
                "title": title,
                "originalTitle": _history_clip_text(item.get("original_title") or "", 1024),
                "titleAliases": json.dumps(aliases, ensure_ascii=False, separators=(",", ":")),
                "year": str(item.get("year") or ""),
                "season": str(season),
                "episode": str(episode),
            }
            encoded = base64.urlsafe_b64encode(urlencode(payload).encode("utf-8")).decode("ascii").rstrip("=")
            if len(encoded) + len(FOLLOWPLAY_PREFIX) > Filter.FOLLOWPLAY_MAX_ID_LENGTH:
                continue
            updated = Filter._int(item.get("history_updated_at"), state_updated)
            rows.append({
                "key": "douban_tmdb_follow_single@@@tmdb:tv:%s@@@1" % tmdb_id,
                "vodName": history_title or title,
                "vodRemarks": "S%02dE%02d" % (season, episode),
                "episodeUrl": FOLLOWPLAY_PREFIX + encoded,
                "position": Filter._int(item.get("history_position"), 0),
                "duration": Filter._int(item.get("history_duration"), 0),
                "createTime": updated * 1000 if updated < 100000000000 else updated,
            })
        return _normalize_history_rows_shared(rows)

    @staticmethod
    def _vod_groups(vod):
        sources, _sources_limited = _split_bounded_shared(
            vod.get("vod_play_from"), "$$$", PLAY_GROUP_SCAN_LIMIT,
        )
        urls, _urls_limited = _split_bounded_shared(
            vod.get("vod_play_url"), "$$$", PLAY_GROUP_SCAN_LIMIT,
        )
        groups = []
        for index, value in enumerate(urls):
            parts, _limited = _split_bounded_shared(value, "#", EPISODE_SCAN_LIMIT)
            labels = [part.partition("$")[0] for part in parts if part]
            groups.append((sources[index] if index < len(sources) else "", labels))
        flags = vod.get("vodFlags")
        if isinstance(flags, list) and flags:
            groups = []
            for flag in flags[:PLAY_GROUP_SCAN_LIMIT]:
                if not isinstance(flag, dict):
                    continue
                episodes = flag.get("episodes") or []
                if isinstance(episodes, list) and episodes:
                    labels = [
                        str(item.get("name") or "")
                        for item in episodes[:EPISODE_SCAN_LIMIT] if isinstance(item, dict)
                    ]
                else:
                    parts, _limited = _split_bounded_shared(
                        flag.get("urls"), "#", EPISODE_SCAN_LIMIT,
                    )
                    labels = [
                        part.partition("$")[0]
                        for part in parts if part
                    ]
                groups.append((str(flag.get("flag") or ""), labels))
        return groups

    @staticmethod
    def _followplay(value):
        text = str(value or "").strip()
        if not text or len(text) > Filter.FOLLOWPLAY_MAX_ID_LENGTH:
            return None
        for _index in range(min(len(text) + 1, 512)):
            if text.startswith(FOLLOWPLAY_PREFIXES):
                break
            decoded = unquote(text)
            if decoded == text:
                break
            text = decoded
            if len(text) > Filter.FOLLOWPLAY_MAX_ID_LENGTH:
                return None
        prefix = next((item for item in FOLLOWPLAY_PREFIXES if text.startswith(item)), "")
        if not prefix:
            return None
        try:
            raw = text[len(prefix):].replace("-", "+").replace("_", "/")
            if len(raw) > Filter.FOLLOWPLAY_MAX_ID_LENGTH:
                return None
            raw += "=" * ((4 - len(raw) % 4) % 4)
            decoded = base64.b64decode(raw)
            if len(decoded) > Filter.FOLLOWPLAY_MAX_DECODED_LENGTH:
                return None
            values = parse_qs(decoded.decode("utf-8"), keep_blank_values=True)
            return {key: items[0] if items else "" for key, items in values.items()}
        except Exception:
            return None

    @staticmethod
    def _payload_title_aliases(payload):
        raw = payload.get("titleAliases") if isinstance(payload, dict) else ""
        if isinstance(raw, list):
            return [str(value or "").strip() for value in raw if str(value or "").strip()]
        text = str(raw or "").strip()
        if not text:
            return []
        try:
            values = json.loads(text)
            if isinstance(values, list):
                return [str(value or "").strip() for value in values if str(value or "").strip()]
        except Exception:
            pass
        return [value.strip() for value in text.split("\n") if value.strip()]

    @staticmethod
    def _normalize_title(value):
        text = unicodedata.normalize("NFKC", str(value or "")).lower()
        text = re.sub(r"[\[【(（][^\]】)）]{0,40}[\]】)）]", " ", text)
        chinese_number = "零〇一二两三四五六七八九十百壹贰叁肆伍陆柒捌玖拾佰"
        text = re.sub(
            r"(?i)(?:第?\s*[%s]+\s*(?:季|部)|第\s*\d+\s*(?:季|部)|season\s*\d+|s\s*0*\d+)\s*$" % chinese_number,
            " ",
            text,
        )
        text = re.sub(r"\b(?:19|20)\d{2}\b|2160p|1080p|720p|4k|全集|完结|更新至.*$", " ", text)
        text = re.sub(r"(?:电视剧|连续剧|剧集|高清版|完整版|国语版|粤语版)\s*$", " ", text)
        return re.sub(r"[^0-9a-z\u3400-\u9fff]+", "", text)

    @staticmethod
    def _title_score(left, right):
        if not left or not right:
            return 0
        if left == right:
            return 100
        if min(len(left), len(right)) >= 2 and (left in right or right in left):
            return 80
        return 0

    @staticmethod
    def _episode(value):
        text = str(value or "")
        found = re.search(r"(?i)S\s*0*(\d{1,2})\s*E(?:P)?\s*0*(\d{1,3})", text)
        if found:
            return int(found.group(1)), int(found.group(2)), True
        season = Filter._season(text)
        found = re.search(r"(?i)(?:第\s*)?(\d{1,3})\s*(?:集|话|期)|\bEP?\s*0*(\d{1,3})\b", text)
        if found:
            return season, int(found.group(1) or found.group(2)), bool(season)
        chinese = re.search(
            r"第?\s*([零〇一二两三四五六七八九十百壹贰叁肆伍陆柒捌玖拾佰]{1,6})\s*(?:集|话|期)",
            text,
        )
        if chinese:
            number = Filter._chinese_number(chinese.group(1))
            if number > 0:
                return season, number, bool(season)
        stripped = re.sub(r"\b(?:19|20)\d{2}\b|2160p|1080p|720p|4k", "", text, flags=re.I)
        numbers = re.findall(r"\d{1,3}", stripped)
        return (0, int(numbers[-1]), False) if len(numbers) == 1 else (0, 0, False)

    @staticmethod
    def _season(value):
        text = str(value or "")
        found = re.search(
            r"(?i)(?:\bS\s*0*(\d{1,2})(?:\b|(?=E))|\bseason\s*0*(\d{1,2})\b|第\s*0*(\d{1,2})\s*(?:季|部))",
            text,
        )
        if found:
            return int(next(value for value in found.groups() if value is not None))
        chinese = re.search(
            r"第?\s*([零〇一二两三四五六七八九十百壹贰叁肆伍陆柒捌玖拾佰]{1,6})\s*(?:季|部)",
            text,
        )
        return Filter._chinese_number(chinese.group(1)) if chinese else 0

    @staticmethod
    def _chinese_number(value):
        text = str(value or "")
        digits = {
            "零": 0, "〇": 0, "一": 1, "壹": 1, "二": 2, "两": 2, "贰": 2,
            "三": 3, "叁": 3, "四": 4, "肆": 4, "五": 5, "伍": 5,
            "六": 6, "陆": 6, "七": 7, "柒": 7, "八": 8, "捌": 8,
            "九": 9, "玖": 9,
        }
        units = {"十": 10, "拾": 10, "百": 100, "佰": 100}
        if not text:
            return 0
        if not any(char in units for char in text):
            values = [str(digits[char]) for char in text if char in digits]
            return int("".join(values)) if values else 0
        total = 0
        current = 0
        for char in text:
            if char in digits:
                current = digits[char]
            elif char in units:
                total += (current or 1) * units[char]
                current = 0
        return total + current

    @staticmethod
    def _year(value):
        found = re.search(r"\b((?:19|20)\d{2})\b", str(value or ""))
        return int(found.group(1)) if found else 0

    @staticmethod
    def _complete(position, duration):
        return duration > 0 and (position >= int(duration * 0.9) or duration - position <= 180000)

    @staticmethod
    def _config(value):
        if isinstance(value, dict):
            return dict(value)
        try:
            parsed = json.loads(str(value or "{}"))
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}

    @staticmethod
    def _bool(value, default):
        if isinstance(value, bool):
            return value
        if value is None or value == "":
            return default
        return str(value).strip().lower() in ("1", "true", "yes", "on")

    @staticmethod
    def _int(value, default=0):
        try:
            return int(float(value))
        except Exception:
            return default

    @classmethod
    def _bounded_int(cls, value, default, minimum, maximum):
        return max(minimum, min(maximum, cls._int(value, default)))


class Spider(BaseSpider):
    name = "豆瓣TMDB追更助手（AList-TVBox专用）"
    host = "https://m.douban.com"
    backend_parse = False
    category_mode = False
    categoryMode = False
    ATVP_PLUGIN_MODE = "alist-tvbox-raw"
    ACTIVITY_PROBE_FAILED = object()

    API = "https://m.douban.com/rexxar/api/v2"
    MOVIE = "https://movie.douban.com"
    ACTION_PREFIX = "douban-wish:add:"
    FOLLOW_ADD_PREFIX = "tmdb-follow:add:"
    DOUBAN_FOLLOW_ADD_PREFIX = "douban-follow:add:"
    FOLLOW_SEEN_PREFIX = "tmdb-follow:seen:"
    FOLLOW_REMOVE_PREFIX = "tmdb-follow:remove:"
    FOLLOW_EXECUTE_PREFIX = "tmdb-follow:execute:"
    FOLLOW_CONFIRM_CANCEL_PREFIX = "tmdb-follow:confirm-cancel:"
    FOLLOW_STATUS_ACK_ACTION = "tmdb-follow:status-ack"
    FOLLOW_CANDIDATE_ADD_PREFIX = "follow-candidate:add:"
    FOLLOW_CANDIDATE_CLEAR_PREFIX = "follow-candidate:clear:"
    GLOBAL_SEARCH_PREFIX = "fongmi-search:"
    SERIES_MODE_PREFIX = "series-mode:"
    SERIES_CARD_PREFIX = "series-card:"
    ATVP_SYNC_ACTION = "atvp-follow:sync"
    ATVP_PROBE_ACTION = "atvp-follow:probe"
    PLAYBACK_EXIT_PREFIX = "playback-exit:"
    HISTORY_SHARE_ACTION_PREFIX = "history-share:"
    KEEP_FOLLOW_ACTION = "local-keep-follow:sync"
    SELECT_PROMPT_ID = "follow-status:select"
    FOLLOWPLAY_MAX_ID_LENGTH = 65536
    FOLLOWPLAY_MAX_DECODED_LENGTH = 49152
    FOLLOWPLAY_MAX_URL_LENGTH = 16 * 1024
    FOLLOWPLAY_ROUTE_FIELD_MAX_LENGTH = 1024
    FOLLOWPLAY_MAX_FALLBACKS = 2
    FOLLOW_ROUTE_LIMIT = 5
    FOLLOWPLAY_PLAY_BUDGET = 60
    PLAYBACK_SYNC_MIN_SECONDS = 8 * 60
    PLAYBACK_SYNC_RETRY_SECONDS = 5
    RESOURCE_PARSE_CANDIDATE_LIMIT = 100
    ROUTE_PROBE_MAX_BYTES = 4096
    ROUTE_PROBE_CACHE_LIMIT = 128
    ROUTE_PROBE_NEGATIVE_TTL = 60
    ROUTE_HEADER_VALUE_MAX_BYTES = 16 * 1024
    ROUTE_COOKIE_MAX_BYTES = 64 * 1024
    ROUTE_HEADERS_TOTAL_MAX_BYTES = 80 * 1024
    ERROR_PREFIX = "douban-error:"
    FILTER_CACHE_KEY = "douban_meta_wish_filters_v12_follow_candidates"
    FOLLOW_CACHE_KEY = "douban_tmdb_follow_state_v1"
    SERIES_MODE_CACHE_KEY = "douban_tmdb_series_mode_v1"
    FOLLOW_STATE_VERSION = 2
    FOLLOW_STATE_MAX_BYTES = 4 * 1024 * 1024
    FOLLOW_STATE_ITEM_MAX_BYTES = 128 * 1024
    FOLLOW_STATE_ITEM_LIMIT = 2048
    FOLLOW_STATE_TEXT_FIELD_LIMITS = {
        "title": 1024,
        "original_title": 1024,
        "history_vod_name": 1024,
        "pic": 8192,
        "source_id": 2048,
        "latest_episode": 64,
        "next_episode": 64,
        "seen_episode": 64,
        "tracked_episode": 64,
        "history_episode": 64,
        "seen_source": 64,
        "next_air_date": 32,
    }
    RESUME_IMPORT_CACHE_KEY = "douban_tmdb_resume_import_v1"
    ATVP_STATUS_CACHE_KEY = "douban_tmdb_atvp_job_status_v1"
    HISTORY_SHARE_POLICY_CACHE_KEY = "douban_tmdb_history_share_policy_v1"
    FOLLOW_ACTION_STATE_CACHE_KEY = "douban_tmdb_follow_action_state_v1"
    FOLLOW_CONFIRM_TTL = 300
    RESPONSE_CACHE_KEY = "douban_tmdb_response_cache_v1"
    RESPONSE_CACHE_VERSION = 1
    RESOURCE_SEARCH_MODES = ("vod1", "vod", "pansou", "telegram")
    RESOURCE_MODE_PRIORITY = {
        "vod1": 0,
        "vod": 1,
        "pansou": 2,
        "telegram": 3,
    }
    RESOURCE_SUPPLEMENT_MODES = frozenset(("pansou", "telegram"))
    RESOURCE_CHECK_LINK_HOSTS = (
        "alipan.com", "aliyundrive.com", "123pan.com", "123pan.cn",
        "123684.com", "123685.com", "123865.com", "123912.com", "123592.com",
        "123684.cn", "123685.cn", "123865.cn", "123912.cn", "123592.cn",
        "guangyapan.com", "mypikpak.com", "xunlei.com", "quark.cn", "139.com",
        "caiyun.feixin.10086.cn",
        "uc.cn", "115.com", "115cdn.com", "anxia.com", "189.cn", "baidu.com",
    )
    RESOURCE_SEARCH_BUDGET = 12
    RESOURCE_DETAIL_BUDGET = 20
    RESOURCE_FOREGROUND_BUDGET = 16
    RESOURCE_DETAIL_ATTEMPT_LIMIT = 8
    RESOURCE_SEARCH_RESULT_LIMIT = 100
    RESOURCE_API_RESPONSE_MAX_BYTES = 2 * 1024 * 1024
    RESOURCE_SEARCH_CACHE_TTL = 900
    RESOURCE_CAPABILITY_CACHE_KEY = "douban_tmdb_resource_capabilities_v1"
    RESOURCE_CAPABILITY_VERSION = 1
    RESOURCE_CAPABILITY_MISSING_STATUSES = frozenset((404, 405, 501))
    RESOURCE_HOT_ROUTE_LIMIT = 5
    RESOURCE_HOT_VALIDATION_BUDGET = 24
    RESOURCE_HOT_VALIDATION_ATTEMPT_LIMIT = 8
    RESOURCE_HOT_JOB_LIMIT = 2
    RESOURCE_HOT_JOB_QUEUE_LIMIT = 8
    RESOURCE_ENTRY_PREHEAT_LIMIT = 3
    RESOURCE_FOREGROUND_MODE_WORKERS = 4
    RESOURCE_FOREGROUND_MODE_QUEUE_LIMIT = 4
    RESOURCE_BACKGROUND_MODE_WORKERS = 2
    RESOURCE_BACKGROUND_MODE_QUEUE_LIMIT = 2
    RESOURCE_PLAY_URL_MAX_LENGTH = 1024 * 1024
    RESOURCE_MERGED_PLAY_URL_BUDGET = RESOURCE_PLAY_URL_MAX_LENGTH // 2 - 8192
    RESOURCE_REWRITE_GROUP_URL_LIMIT = RESOURCE_MERGED_PLAY_URL_BUDGET
    RESOURCE_REWRITTEN_PLAY_URL_MAX_LENGTH = (
        PLAY_GROUP_SCAN_LIMIT * RESOURCE_REWRITE_GROUP_URL_LIMIT
        + (PLAY_GROUP_SCAN_LIMIT - 1) * 3
    )
    RESOURCE_SOURCE_LABEL_MAX_LENGTH = 16 * 1024
    RESOURCE_ID_MAX_LENGTH = 512
    RESOURCE_OFFLINE_ID_MAX_LENGTH = 16 * 1024
    RESOURCE_ENCODED_OFFLINE_ID_MAX_LENGTH = RESOURCE_OFFLINE_ID_MAX_LENGTH * 3
    RESOURCE_METADATA_TITLE_MAX_LENGTH = 1024
    RESOURCE_METADATA_NOTE_MAX_LENGTH = 4096
    RESOURCE_METADATA_SOURCE_MAX_LENGTH = 256
    RESOURCE_METADATA_PROVIDER_MAX_LENGTH = 128
    RESOURCE_PAYLOAD_SCAN_MIN = 32
    RESOURCE_PAYLOAD_SCAN_FACTOR = 8
    RESOURCE_PLAY_GROUP_SCAN_LIMIT = PLAY_GROUP_SCAN_LIMIT
    RESOURCE_GROUP_EPISODE_LIMIT = 256
    RESOURCE_RECORD_LIMIT = 512
    RESOURCE_COMPLETION_LIMIT = 512
    DIAGNOSTIC_LIMIT = 256
    VALIDATED_RESOURCE_DETAIL_CACHE_LIMIT = 64
    ROUTE_QUALITY_CACHE_KEY = "douban_tmdb_route_quality_v1"
    ROUTE_QUALITY_VERSION = 1
    ROUTE_QUALITY_LIMIT = 200
    ROUTE_QUALITY_MAX_AGE = 30 * 86400
    HISTORY_FIELDS = HISTORY_FIELDS
    HISTORY_RESPONSE_MAX_BYTES = HISTORY_RESPONSE_MAX_BYTES
    HISTORY_ROW_MAX_BYTES = HISTORY_ROW_MAX_BYTES
    HISTORY_CONFIG_MAX_BYTES = HISTORY_CONFIG_MAX_BYTES
    HISTORY_LOCAL_PROXY_MAX_BYTES = HISTORY_RESPONSE_MAX_BYTES
    HISTORY_ROW_LIMIT = HISTORY_ROW_LIMIT
    HISTORY_FIELD_MAX_LENGTH = HISTORY_FIELD_MAX_LENGTH
    HISTORY_FIELD_LIMITS = HISTORY_FIELD_LIMITS
    HISTORY_INTEGER_FIELDS = HISTORY_INTEGER_FIELDS
    SYNC_SITE_KEYS = {
        "csp_AList", "douban_tmdb_follow_single", "豆瓣TMDB追更单入口",
    }

    TMDB_API = "https://api.tmdb.org/3"
    TMDB_IMAGE = "https://images.tmdb.org/t/p/w500"

    CATEGORIES = (
        ("follow_updates", "追更动态"),
        ("follow_candidates", "追更确认"),
        ("follow_manage", "追更管理"),
        ("hotmovie", "热门电影"),
        ("hottv", "热门剧集"),
        ("hotzy", "热门综艺"),
        ("movielist", "电影榜单"),
        ("tvlist", "电视榜单"),
        ("moviefilter", "电影筛选"),
        ("tvfilter", "电视筛选"),
        ("anime", "动漫"),
        ("wishlist", "豆瓣想看"),
        ("tmdb_trending", "TMDB趋势"),
        ("tmdb_movie", "TMDB电影"),
        ("tmdb_tv", "TMDB剧集"),
        ("tmdb_anime", "TMDB动漫"),
    )

    TMDB_MOVIE_GENRES = (
        ("全部类型", ""), ("动作", "28"), ("冒险", "12"), ("动画", "16"),
        ("喜剧", "35"), ("犯罪", "80"), ("纪录", "99"), ("剧情", "18"),
        ("家庭", "10751"), ("奇幻", "14"), ("历史", "36"), ("恐怖", "27"),
        ("音乐", "10402"), ("悬疑", "9648"), ("爱情", "10749"),
        ("科幻", "878"), ("惊悚", "53"), ("战争", "10752"),
    )
    TMDB_TV_GENRES = (
        ("全部类型", ""), ("动作冒险", "10759"), ("动画", "16"), ("喜剧", "35"),
        ("犯罪", "80"), ("纪录", "99"), ("剧情", "18"), ("家庭", "10751"),
        ("儿童", "10762"), ("悬疑", "9648"), ("新闻", "10763"),
        ("真人秀", "10764"), ("科幻奇幻", "10765"), ("肥皂剧", "10766"),
        ("脱口秀", "10767"), ("战争政治", "10768"),
    )

    MOVIE_LISTS = (
        ("实时热门电影", "movie_real_time_hotest"),
        ("一周口碑电影榜", "movie_weekly_best"),
        ("豆瓣电影Top250", "top250"),
    )
    TV_LISTS = (
        ("实时热门剧集", "tv_real_time_hotest"),
        ("华语口碑剧集榜", "tv_chinese_best_weekly"),
        ("全球口碑剧集榜", "tv_global_best_weekly"),
        ("国内口碑综艺榜", "show_chinese_best_weekly"),
        ("国外口碑综艺榜", "show_global_best_weekly"),
    )
    AREAS = ("中国大陆", "中国香港", "中国台湾", "美国", "英国", "日本", "韩国", "法国", "德国", "印度", "泰国")
    MOVIE_TYPES = ("剧情", "喜剧", "动作", "爱情", "科幻", "动画", "悬疑", "犯罪", "惊悚", "恐怖", "纪录片", "短片")
    TV_TYPES = ("电视剧", "综艺")
    SERIES_TYPES = ("国产剧", "港剧", "台剧", "日剧", "韩剧", "美剧", "英剧")
    SHOW_TYPES = ("真人秀", "脱口秀", "音乐", "喜剧", "旅行", "竞技")
    TV_GENRES = ("剧情", "喜剧", "爱情", "悬疑", "动画", "武侠", "古装", "家庭", "犯罪", "科幻", "恐怖", "历史", "战争", "动作", "冒险", "传记", "奇幻", "惊悚", "灾难", "歌舞", "音乐")
    TAGS = ("经典", "热门", "高分", "青春", "家庭", "治愈", "女性", "成长", "历史", "战争", "奇幻", "冒险", "推理", "人性", "真实事件改编")
    PLATFORMS = ("Netflix", "HBO", "Disney+", "BBC", "NHK", "TVB", "爱奇艺", "腾讯视频", "优酷", "芒果TV")
    SORTS = (("综合排序", "T"), ("近期热度", "U"), ("首映/首播时间", "R"), ("高分优先", "S"))
    ANIME_SORTS = (("热度", "U"), ("更新时间", "R"), ("评分", "S"))
    ANIME_REGIONS = {
        "cn": "中国大陆",
        "jp": "日本",
        "kr": "韩国",
        "us": "美国",
    }
    LEGACY_ANIME_REGIONS = {
        "anime_cn": "中国大陆",
        "anime_jp": "日本",
        "anime_kr": "韩国",
        "anime_us": "美国",
    }
    ANIME_GENRES = ("热血", "冒险", "奇幻", "科幻", "校园", "治愈", "搞笑", "恋爱", "悬疑", "运动", "音乐", "历史", "机战", "推理")
    ANIME_FORMATS = ("TV动画", "剧场版", "OVA", "网络动画", "动画短片")

    def __init__(self):
        try:
            super().__init__()
        except Exception:
            pass
        self.timeout = 6
        self.cache_ttl = 180
        self.list_cache_ttl = 600
        self.collection_cache_ttl = 1800
        self.detail_cache_ttl = 86400
        self.wishlist_cache_ttl = 20
        self.top250_cache_ttl = 21600
        self.stale_ttl = 86400
        self.cache_max_entries = 256
        self.failure_ttl = 60
        self.filter_cache_ttl = 21600
        self.dynamic_filters = False
        self.persistent_filter_cache = True
        self.image_headers = True
        self.verify_tls = True
        self.trust_env = True
        self.proxy = ""
        self.cookie = ""
        self.ck = ""
        self.user_id = ""
        self.tmdb_access_token = ""
        self.tmdb_api_key = ""
        self.tmdb_api_base = self.TMDB_API
        self.tmdb_image_base = self.TMDB_IMAGE
        self.tmdb_language = "zh-CN"
        self.tmdb_region = "CN"
        self.tmdb_trust_env = False
        self.tmdb_proxy = ""
        self.follow_check_ttl = 21600
        self.follow_page_size = 20
        self.follow_tv_ids = []
        self.keep_follow_scan_limit = 50
        self.atvp_api = ""
        self.history_api = ""
        self.atvp_token = ""
        self._history_primary_origin = ""
        self._history_api_origins = []
        self._history_selected_origin = ""
        self.atvp_plugin_mode = ""
        self._alist_tvbox_plugin = False
        self.history_username = ""
        self.history_password = ""
        self._history_auth_token = ""
        self._history_share_policy = {"follow": True, "watch": True}
        self._history_share_policy_loaded = False
        self.atvp_history_ttl = 60
        self.atvp_trust_env = False
        self.resource_limit = self.FOLLOW_ROUTE_LIMIT
        self.resource_search_modes = ["vod"]
        self.resource_auto_discover = True
        self.resource_capability_ttl = 600
        self.route_preheat = True
        self.route_probe_ttl = 300
        self.follow_alist_bindings = {}
        self.user_agent = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )
        self._session = None
        self._tmdb_session = None
        self._atvp_session = None
        self._cache = OrderedDict()
        self._persistent_cache = OrderedDict()
        self._persistent_cache_loaded = False
        self._persistent_cache_dirty = False
        self._persistent_cache_saving = None
        self._cache_generation = 0
        self._refreshing_cache_keys = {}
        self._resource_search_jobs = {}
        self._resource_entry_preheat_jobs = {}
        self._create_task_runtime()
        self._failures = {}
        self._failure_attempts = {}
        self._cache_coordinator = _CacheCoordinator(self)
        self._tmdb_client = _TMDBClient(self)
        self._follow_repository = _FollowRepository(self)
        self._history_coordinator = _HistoryCoordinator(self)
        self._douban_client = _DoubanClient(self)
        self._cache_lock = threading.RLock()
        self._cache_persist_lock = threading.RLock()
        self._filters = None
        self._filters_at = 0
        self._follow_memory = {"version": self.FOLLOW_STATE_VERSION, "items": {}}
        self._follow_state_loaded = False
        self._follow_cache_origin = ""
        self._follow_state_load_lock = threading.RLock()
        self._follow_enrich_lock = threading.RLock()
        self._follow_state_persist_lock = threading.Lock()
        self._follow_enrich_jobs = {}
        self._follow_candidate_results = {}
        self._follow_action_state_lock = threading.RLock()
        self._follow_action_state_persist_lock = threading.Lock()
        self._follow_action_state = {"version": 1, "last": {}, "pending": {}}
        self._series_action_mode = "add"
        self._resume_imported = {}
        self._atvp_discovery_at = 0
        self._atvp_discovery_error = ""
        self._atvp_job_lock = threading.RLock()
        self._atvp_jobs = set()
        self._atvp_status = {}
        self._atvp_status_persist_lock = threading.Lock()
        self._history_context_lock = threading.RLock()
        self._history_sync_lock = threading.Lock()
        self._history_snapshot_revision = 0
        self._history_ui_refresh_lock = threading.RLock()
        self._history_ui_refresh_token = 0
        self._playback_sync_lock = threading.RLock()
        self._playback_sync_pending = {}
        self._playback_sync_timers = {}
        self._playback_sync_tokens = {}
        self._playback_sync_inflight = {}
        self._route_probe_cache = {}
        self._route_probe_jobs = {}
        # Scope source-switch detection to the concrete playback context. A
        # Spider instance can service several detail pages over its lifetime;
        # comparing only the last flag would incorrectly force-refresh the
        # first request of an unrelated title or episode.
        self._last_player_context = None
        self._resource_search_admissions = 0
        self._validated_resource_details = OrderedDict()
        self._bound_replacement_jobs = {}
        self._resource_capabilities = {}
        self._resource_capabilities_backend = ""
        self._resource_capabilities_revision = 0
        self._route_quality_history = {}
        self._route_quality_loaded = False
        self._route_quality_dirty = False
        self._route_quality_saving = None
        self._native_export_lock = threading.RLock()
        self._native_exports = {}
        self._fongmi_refresh_task_lock = threading.RLock()
        self._fongmi_refresh_task_class = None
        self._follow_refresh_lock = threading.RLock()
        self._follow_refresh_generation = 0
        self._diagnostic_lock = threading.RLock()
        self._diagnostics = []
        self._diagnostic_sequence = 0
        self._reset_session()

    def _create_task_runtime(self):
        self._tasks = _TaskSupervisor()
        self._resource_search_executor = ThreadPoolExecutor(max_workers=self.RESOURCE_HOT_JOB_LIMIT)
        self._follow_refresh_executor = ThreadPoolExecutor(max_workers=4)
        self._resource_foreground_mode_executor = ThreadPoolExecutor(
            max_workers=self.RESOURCE_FOREGROUND_MODE_WORKERS,
        )
        self._resource_foreground_mode_slots = threading.BoundedSemaphore(
            self.RESOURCE_FOREGROUND_MODE_WORKERS + self.RESOURCE_FOREGROUND_MODE_QUEUE_LIMIT,
        )
        self._resource_background_mode_executor = ThreadPoolExecutor(
            max_workers=self.RESOURCE_BACKGROUND_MODE_WORKERS,
        )
        self._resource_background_mode_slots = threading.BoundedSemaphore(
            self.RESOURCE_BACKGROUND_MODE_WORKERS + self.RESOURCE_BACKGROUND_MODE_QUEUE_LIMIT,
        )
        for _executor in (
                self._resource_search_executor,
                self._follow_refresh_executor,
                self._resource_foreground_mode_executor,
                self._resource_background_mode_executor):
            self._tasks.register_executor(_executor)

    def _diagnostic_event(self, event, level="INFO", exc=None, **fields):
        """Store a bounded, redacted diagnostic event without changing runtime output."""
        try:
            payload = {
                "event": str(event or "unknown"),
                "level": str(level or "INFO").upper(),
                "at": time.time(),
            }
            if exc is not None:
                payload["error_kind"] = self._diagnostic_error_kind(exc)
                payload["error"] = self._short_error(exc)
                if payload["level"] in ("ERROR", "CRITICAL"):
                    trace = "".join(traceback.format_exception_only(type(exc), exc)).strip()
                    payload["trace"] = self._short_error(RuntimeError(trace))[:512]
            for key, value in fields.items():
                if value is None:
                    continue
                text = str(value)
                payload[str(key)] = self._short_error(RuntimeError(text)) if any(
                    marker in str(key).lower() for marker in ("token", "cookie", "password", "secret", "proxy", "url", "id")
                ) else text[:512]
            with self._diagnostic_lock:
                self._diagnostic_sequence += 1
                payload["seq"] = self._diagnostic_sequence
                self._diagnostics.append(payload)
                if len(self._diagnostics) > self.DIAGNOSTIC_LIMIT:
                    del self._diagnostics[:-self.DIAGNOSTIC_LIMIT]
            return payload
        except Exception:
            return None

    @staticmethod
    def _diagnostic_error_kind(exc):
        name = type(exc).__name__.lower()
        text = str(exc or "").lower()
        if "timeout" in name or "timed out" in text:
            return "timeout"
        if "connection" in name or "connection" in text or "dns" in text:
            return "transport"
        if "json" in name or "decode" in name or "json" in text:
            return "payload"
        if any(marker in text for marker in ("401", "403", "unauthorized", "forbidden", "token")):
            return "auth"
        if any(marker in text for marker in ("429", "rate limit", "限流")):
            return "rate_limit"
        if any(marker in text for marker in ("cancel", "generation", "已销毁")):
            return "cancelled"
        return "runtime"

    def _diagnostic_snapshot(self, limit=None):
        try:
            count = self.DIAGNOSTIC_LIMIT if limit is None else max(1, min(int(limit), self.DIAGNOSTIC_LIMIT))
        except Exception:
            count = self.DIAGNOSTIC_LIMIT
        with self._diagnostic_lock:
            return [dict(item) for item in self._diagnostics[-count:]]

    def getName(self):
        return self.name

    def init(self, extend=""):
        with self._history_context_lock:
            return self._init_locked(extend)

    def _init_locked(self, extend=""):
        if self._tasks.is_closed():
            self._create_task_runtime()
        config = self._parse_config(extend)
        self.timeout = self._bounded_int(config.get("timeout"), 6, 3, 15)
        self.cache_ttl = self._bounded_int(config.get("cache_ttl"), 180, 0, 3600)
        self.list_cache_ttl = self._bounded_int(config.get("list_cache_ttl"), 600, 10, 1800)
        self.collection_cache_ttl = self._bounded_int(config.get("collection_cache_ttl"), 1800, 30, 3600)
        self.detail_cache_ttl = self._bounded_int(config.get("detail_cache_ttl"), 86400, 300, 604800)
        self.wishlist_cache_ttl = self._bounded_int(config.get("wishlist_cache_ttl"), 20, 5, 300)
        self.top250_cache_ttl = self._bounded_int(config.get("top250_cache_ttl"), 21600, 300, 86400)
        self.stale_ttl = self._bounded_int(config.get("stale_ttl"), 86400, 300, 604800)
        self.cache_max_entries = self._bounded_int(config.get("cache_max_entries"), 256, 32, 1024)
        self.failure_ttl = self._bounded_int(config.get("failure_ttl"), 60, 10, 600)
        self.filter_cache_ttl = self._bounded_int(config.get("filter_cache_ttl"), 21600, 300, 86400)
        self.dynamic_filters = self._bool_value(config.get("dynamic_filters"), False)
        self.persistent_filter_cache = self._bool_value(config.get("persistent_filter_cache"), True)
        self.image_headers = self._bool_value(config.get("image_headers"), True)
        self.verify_tls = self._bool_value(config.get("verify_tls"), True)
        self.trust_env = self._bool_value(config.get("trust_env"), True)
        self.proxy = str(config.get("proxy") or "").strip()
        self.cookie = str(config.get("cookie") or "").strip()
        self.user_id = str(config.get("user_id") or "").strip().strip("/")
        self.ck = str(config.get("ck") or self._cookie_value(self.cookie, "ck") or "").strip()
        self.tmdb_access_token = self._first(config, "tmdb_access_token", "access_token", "accessToken", "readAccessToken")
        self.tmdb_api_key = self._first(config, "tmdb_api_key", "api_key", "apiKey", "apikey")
        self.tmdb_api_base = self._https_base(config.get("tmdb_api_base") or config.get("api_base"), self.TMDB_API)
        self.tmdb_image_base = self._https_base(config.get("tmdb_image_base") or config.get("image_base"), self.TMDB_IMAGE)
        self.tmdb_language = str(config.get("tmdb_language") or config.get("language") or "zh-CN").strip() or "zh-CN"
        self.tmdb_region = str(config.get("tmdb_region") or config.get("region") or "CN").strip().upper() or "CN"
        self.tmdb_trust_env = self._bool_value(config.get("tmdb_trust_env"), False)
        self.tmdb_proxy = str(config.get("tmdb_proxy") or "").strip()
        self.follow_check_ttl = self._bounded_int(config.get("follow_check_ttl"), 21600, 300, 86400)
        self.follow_page_size = self._bounded_int(config.get("follow_page_size"), 20, 5, 40)
        self.follow_tv_ids = self._id_list(config.get("follow_tv_ids") or config.get("followTmdbIds"))
        self.keep_follow_scan_limit = self._bounded_int(config.get("keep_follow_scan_limit"), 50, 1, 200)
        self.atvp_plugin_mode = self._first(config, "atvp_plugin_mode", "runtime_mode", "runtime").strip().lower()
        self._alist_tvbox_plugin = self.atvp_plugin_mode == self.ATVP_PLUGIN_MODE
        self.atvp_api = self._http_base(config.get("atvp_api") or config.get("_atvp_api") or config.get("api"), "")
        self.history_api = self._http_base(
            config.get("history_api") or config.get("historyApi"), "",
        )
        self._history_primary_origin = self.history_api or self.atvp_api
        self._history_api_origins = [
            value for value in (self.history_api, self.atvp_api) if value
        ]
        self._history_selected_origin = ""
        self.atvp_token = self._first(config, "atvp_token", "_atvp_token", "token")
        if self.atvp_token == "-":
            self.atvp_token = ""
        # Public builds accept only the server-generated AList-TVBox raw-plugin context.
        # A manually loaded .py file may still initialize for the FongMi contract, but
        # it cannot use this source's AList-TVBox playback or History integration.
        self.history_username = self._first(config, "history_username")
        self.history_password = self._first(config, "history_password")
        self._history_auth_token = ""
        if not self._alist_tvbox_plugin:
            self.atvp_api = ""
            self.history_api = ""
            self.atvp_token = ""
            self.history_username = ""
            self.history_password = ""
        self.atvp_history_ttl = self._bounded_int(config.get("atvp_history_ttl"), 60, 10, 600)
        self.atvp_trust_env = self._bool_value(config.get("atvp_trust_env"), False)
        self.resource_limit = self._bounded_int(
            config.get("resource_limit"), self.FOLLOW_ROUTE_LIMIT, 1, self.FOLLOW_ROUTE_LIMIT,
        )
        self.resource_search_modes = self._resource_mode_list(config.get("resource_search_modes"))
        self.resource_auto_discover = self._bool_value(config.get("resource_auto_discover"), True)
        self.resource_capability_ttl = self._bounded_int(
            config.get("resource_capability_ttl"), 600, 60, 3600,
        )
        self.route_preheat = self._bool_value(config.get("route_preheat"), self.route_preheat)
        self.route_probe_ttl = self._bounded_int(config.get("route_probe_ttl"), self.route_probe_ttl, 30, 1800)
        self.follow_alist_bindings = self._string_mapping(config.get("follow_alist_bindings"))
        ua = str(config.get("user_agent") or "").strip()
        if ua:
            self.user_agent = ua
        with self._cache_persist_lock:
            with self._cache_lock:
                self._cache.clear()
                self._persistent_cache.clear()
                self._persistent_cache_loaded = False
                self._persistent_cache_dirty = False
                self._persistent_cache_saving = None
                self._refreshing_cache_keys.clear()
                self._resource_search_jobs.clear()
                self._resource_entry_preheat_jobs.clear()
                self._route_probe_cache.clear()
                self._route_probe_jobs.clear()
                self._validated_resource_details.clear()
                self._bound_replacement_jobs.clear()
                self._resource_capabilities.clear()
                self._resource_capabilities_backend = ""
                self._resource_capabilities_revision += 1
                self._route_quality_history.clear()
                self._route_quality_loaded = False
                self._route_quality_dirty = False
                self._route_quality_saving = None
                self._cache_generation += 1
                self._history_snapshot_revision += 1
        with self._history_ui_refresh_lock:
            self._history_ui_refresh_token += 1
        with self._playback_sync_lock:
            for timer in self._playback_sync_timers.values():
                try:
                    timer.cancel()
                except Exception:
                    pass
            self._playback_sync_pending.clear()
            self._playback_sync_timers.clear()
            self._playback_sync_tokens.clear()
            self._playback_sync_inflight.clear()
        self._failures.clear()
        self._failure_attempts.clear()
        self._filters = None
        self._filters_at = 0
        self._resume_imported.clear()
        self._atvp_discovery_at = 0
        self._atvp_discovery_error = ""
        self._reset_session()
        if self._alist_tvbox_plugin:
            self._autofill_atvp_api_from_fongmi()
        else:
            self._atvp_discovery_error = "需要通过 AList-TVBox raw 插件订阅加载"
        self._follow_state_loaded = False
        self._follow_cache_origin = ""
        self._load_follow_state(force=True)
        self._load_history_share_policy()
        self._load_series_action_mode()
        self._load_resume_markers()
        self._load_atvp_status()
        self._load_follow_action_state()
        if not self.user_id and self.cookie:
            self._resolve_user_id()
        self._schedule_entry_resource_preheat()

    def destroy(self):
        with self._history_context_lock:
            with self._cache_persist_lock:
                with self._cache_lock:
                    self._cache_generation += 1
                    self._history_snapshot_revision += 1
                with self._history_ui_refresh_lock:
                    self._history_ui_refresh_token += 1
                self._flush_route_quality_sync()
                self._flush_response_cache_sync()
            with self._playback_sync_lock:
                for timer in self._playback_sync_timers.values():
                    try:
                        timer.cancel()
                    except Exception:
                        pass
                self._playback_sync_pending.clear()
                self._playback_sync_timers.clear()
                self._playback_sync_tokens.clear()
                self._playback_sync_inflight.clear()
            for session in (self._session, self._tmdb_session, self._atvp_session):
                if session is not None:
                    try:
                        session.close()
                    except Exception:
                        pass
            self._tasks.shutdown(wait=False)

    def _autofill_atvp_api_from_fongmi(self):
        if not self._alist_tvbox_plugin:
            return False
        if (self.atvp_api and self.atvp_token) or self._atvp_session is None:
            return bool(self.atvp_api and self.atvp_token and self._atvp_session is not None)
        self._atvp_discovery_at = time.time()
        try:
            config = self._native_subscription_config_java()
            if not config:
                raise RuntimeError("当前运行时未提供FongMi原生配置桥")
            self._apply_native_subscription_config(config)
            self._atvp_discovery_error = ""
        except Exception as exc:
            self._atvp_discovery_error = self._short_error(exc)
        return bool(self.atvp_api and self.atvp_token and self._atvp_session is not None)

    def _ensure_atvp_connection(self, force=False):
        if not self._alist_tvbox_plugin:
            return False
        if self.atvp_api and self.atvp_token and self._atvp_session is not None:
            return True
        if self._atvp_session is None:
            return False
        if force or time.time() - self._atvp_discovery_at >= 10:
            self._autofill_atvp_api_from_fongmi()
        if force and not (self.atvp_api and self.atvp_token):
            first_error = self._atvp_discovery_error
            try:
                exported = self._native_history_export()
                self._apply_native_subscription_config(exported.get("config"))
                self._atvp_discovery_error = ""
            except Exception as exc:
                fallback_error = self._short_error(exc)
                self._atvp_discovery_error = (
                    "%s；History回退：%s" % (first_error, fallback_error)
                    if first_error else fallback_error
                )
        return bool(self.atvp_api and self.atvp_token and self._atvp_session is not None)

    @staticmethod
    def _native_subscription_config_java():
        """Read only the active config; initialization must never export History."""
        try:
            from java import jclass
        except Exception:
            return None
        # VodConfig is renamed by R8 in release builds. Config is a Room/Gson
        # model with stable public methods and remains callable from Chaquopy.
        config = jclass("com.fongmi.android.tv.bean.Config").vod()
        if config is None or not str(config.getUrl() or "").strip():
            raise RuntimeError("FongMi 当前没有活动的影视订阅")
        return str(config.toString() or "")

    def _apply_native_subscription_config(self, raw_config):
        value = raw_config
        if isinstance(value, str):
            if self._utf8_size(value) > self.HISTORY_CONFIG_MAX_BYTES:
                raise RuntimeError("FongMi 当前订阅配置过大")
            try:
                value = json.loads(value)
            except Exception:
                raise RuntimeError("FongMi 当前订阅配置格式无效")
        if not isinstance(value, dict):
            raise RuntimeError("FongMi 未返回当前订阅配置")
        config_url = str(value.get("url") or "").strip()
        parsed = urlparse(config_url)
        raw_parts = [part for part in parsed.path.split("/") if part]
        try:
            index = raw_parts.index("sub")
        except ValueError:
            raise RuntimeError("FongMi 当前配置不是 AList-TVBox 订阅")
        config_token = unquote(raw_parts[index + 1]) if index + 1 < len(raw_parts) else ""
        if not config_token:
            raise RuntimeError("FongMi 当前订阅缺少AList-TVBox令牌")
        if self.atvp_token and config_token != self.atvp_token:
            raise RuntimeError("FongMi 当前订阅令牌与插件令牌不一致")
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise RuntimeError("FongMi 当前订阅地址无效")
        prefix = "/" + "/".join(raw_parts[:index]) if index > 0 else ""
        subscription_origin = ("%s://%s%s" % (parsed.scheme, parsed.netloc, prefix)).rstrip("/")
        self._remember_history_api_origin(subscription_origin)
        self._history_selected_origin = ""
        self.atvp_api = subscription_origin
        self.atvp_token = config_token
        return self.atvp_api

    def homeContent(self, filter=False):
        self._schedule_entry_resource_preheat()
        result = {"class": [{"type_id": key, "type_name": name} for key, name in self.CATEGORIES]}
        if filter:
            result["filters"] = self._get_filters()
        return result

    def homeVideoContent(self):
        self._schedule_entry_resource_preheat()
        try:
            params = {"start": 0, "count": 30, "updated_at": "", "items_only": 1, "for_mobile": 1}
            data = self._get_json(self.API + "/subject_collection/subject_real_time_hotest/items", params=params, ttl=self.list_cache_ttl)
            items = self._parse_collection_items(data)
            if items:
                return self._with_navigation_search({"list": items})
            raise RuntimeError("实时热门列表为空")
        except Exception as primary:
            try:
                fallback = self._category_media("movie", 1, {"sort": "U"})
                if fallback.get("list"):
                    return self._with_navigation_search({"list": fallback["list"]})
            except Exception:
                pass
            return {"list": [self._error_card("首页载入失败", primary)]}

    def categoryContent(self, tid, pg, filter=False, extend=None):
        page = self._positive_int(pg, 1)
        ext = self._parse_extend(extend)
        try:
            if tid in ("follow_updates", "follow_candidates", "follow_sync", "follow_manage"):
                self._flush_playback_sync_on_navigation()
                self._load_follow_state(force=True)
                self._schedule_entry_resource_preheat(page=page)
            if tid == "follow_updates":
                return self._category_follow_updates(page)
            if tid == "follow_candidates":
                return self._category_follow_candidates(page, ext)
            if tid == "follow_sync":
                return self._category_follow_sync(page)
            if tid == "follow_manage":
                return self._category_follow_manage(page, ext)
            if tid == "tmdb_trending":
                return self._with_navigation_search(self._category_tmdb_trending(page, ext))
            if tid == "tmdb_movie":
                return self._with_navigation_search(self._category_tmdb_discover("movie", page, ext))
            if tid == "tmdb_tv":
                return self._with_navigation_search(self._category_tmdb_discover("tv", page, ext))
            if tid == "tmdb_anime":
                return self._with_navigation_search(self._category_tmdb_anime(page, ext))
            if tid == "hotmovie":
                return self._with_navigation_search(self._category_media("movie", page, ext))
            if tid == "hottv":
                return self._with_navigation_search(self._category_media("tv", page, ext))
            if tid == "hotzy":
                return self._with_navigation_search(self._category_media("show", page, ext))
            if tid == "movielist":
                return self._with_navigation_search(
                    self._category_movie_list(page, self._value(ext, "1", "movie_real_time_hotest"), ext)
                )
            if tid == "tvlist":
                return self._with_navigation_search(
                    self._category_collection(page, self._value(ext, "1", "tv_real_time_hotest"), ext)
                )
            if tid == "moviefilter":
                return self._with_navigation_search(self._category_recommend("movie", page, ext))
            if tid == "tvfilter":
                return self._with_navigation_search(self._category_recommend("tv", page, ext))
            if tid == "anime":
                region_key = self._value(ext, "region", "cn")
                result = self._category_anime(self.ANIME_REGIONS.get(region_key, "中国大陆"), page, ext)
                return self._with_navigation_search(result)
            if tid in self.LEGACY_ANIME_REGIONS:
                return self._with_navigation_search(
                    self._category_anime(self.LEGACY_ANIME_REGIONS[tid], page, ext)
                )
            if tid == "wishlist":
                return self._with_navigation_search(self._category_wishlist(page))
            return self._page_result([], page, page, 0, 20)
        except Exception as exc:
            return self._page_result([self._error_card("分类载入失败", exc)], page, page, 1, 20)

    def detailContent(self, ids):
        subject_id = self._first_id(ids)
        if subject_id.startswith("atvp_detail:"):
            subject_id = subject_id[len("atvp_detail:"):]
        if subject_id.startswith("tmdb:"):
            return self._alist_detail_from_metadata(subject_id, self._tmdb_detail(subject_id))
        if subject_id.startswith(self.ERROR_PREFIX):
            text = subject_id[len(self.ERROR_PREFIX):]
            return {"list": [{"vod_id": subject_id, "vod_name": "豆瓣错误", "vod_content": text}]}
        subject_id = self._subject_id(subject_id)
        if not subject_id:
            return {"list": []}
        try:
            data = self._get_json(self.API + "/subject/" + subject_id, params={"for_mobile": 1}, ttl=self.detail_cache_ttl)
            rating = self._rating(data)
            title = str(data.get("title") or "")
            original = str(data.get("original_title") or "")
            names = title if not original or original == title else title + " / " + original
            content = str(data.get("intro") or data.get("card_subtitle") or "").strip()
            honors = self._names(data.get("honor_infos"), "title", 3)
            if honors:
                content = (content + "\n\n榜单：" + honors).strip()
            vod = {
                "vod_id": subject_id,
                "vod_name": names,
                "vod_pic": self._image(self._pic(data, large=True)),
                "type_name": ", ".join(data.get("genres") or []),
                "vod_year": str(data.get("year") or ""),
                "vod_area": ", ".join(data.get("countries") or []),
                "vod_remarks": self._detail_remark(data, rating),
                "vod_actor": self._names(data.get("actors"), "name", 12),
                "vod_director": self._names(data.get("directors"), "name", 6),
                "vod_content": content,
                "vod_play_from": "",
                "vod_play_url": "",
            }
            return self._alist_detail_from_metadata(subject_id, {"list": [vod]})
        except Exception as exc:
            return {"list": [self._error_card("详情载入失败", exc, subject_id)]}

    def searchContent(self, key, quick=False, pg="1"):
        page = self._positive_int(pg, 1)
        query = str(key or "").strip()[:128]
        if not query:
            return self._page_result([], page, page, 0, 20)
        try:
            limit = 20
            data = self._get_json(
                self.API + "/search",
                params={"q": query, "start": (page - 1) * limit, "count": limit},
                ttl=self.list_cache_ttl,
            )
            subjects = data.get("subjects") if isinstance(data.get("subjects"), dict) else {}
            cards = []
            for row in subjects.get("items") or []:
                if not isinstance(row, dict):
                    continue
                target = row.get("target") if isinstance(row.get("target"), dict) else row
                subject_id = self._subject_id(target.get("id") or row.get("target_id"))
                title = str(target.get("title") or row.get("title") or "").strip()
                if not subject_id or not title:
                    continue
                card = self._collection_card(target, {})
                card["vod_id"] = subject_id
                card["vod_name"] = title
                cards.append(card)
            total = self._positive_int(subjects.get("total"), 0)
            pagecount = int(math.ceil(float(total) / limit)) if total else page + (1 if len(cards) >= limit else 0)
            return self._page_result(cards, page, max(page, pagecount), total or len(cards), limit)
        except Exception as exc:
            return self._page_result([self._error_card("搜索失败", exc)], page, page, 1, 20)

    def playerContent(self, flag, id, vipFlags=None):
        if str(id or "").startswith(self.SELECT_PROMPT_ID):
            return {"parse": 0, "jx": 0, "playUrl": "", "url": "", "header": {}, "msg": "请选择具体集数"}
        parsed = self._parse_followplay(id)
        if not parsed:
            if str(id or "").startswith(FOLLOWPLAY_PREFIXES):
                return {"parse": 0, "jx": 0, "playUrl": "", "url": "", "header": {}, "msg": "播放参数无效或已损坏"}
            return {"parse": 0, "jx": 0, "playUrl": "", "url": str(id or ""), "header": {}}
        flag_text = str(flag or "").strip()
        with self._history_context_lock:
            with self._cache_lock:
                player_generation = self._cache_generation
                player_backend = self._resource_capability_identity()
                previous_context = self._last_player_context
                work_identity = (
                    "tmdb:%s" % self._positive_int(parsed.get("tmdbId"), 0)
                    if self._positive_int(parsed.get("tmdbId"), 0) else
                    "source:%s" % str(parsed.get("sourceId") or "").strip()
                    if str(parsed.get("sourceId") or "").strip() else
                    "title:%s:%s" % (
                        self._normalize_media_title(parsed.get("title")),
                        str(parsed.get("year") or "")[:4],
                    )
                )
                current_context = (
                    work_identity,
                    self._positive_int(parsed.get("season"), 0),
                    self._positive_int(parsed.get("episode"), 0),
                    flag_text,
                )
                self._last_player_context = current_context
        # FongMi changes a detail-page source by selecting another vodFlags
        # entry and calling playerContent again. A source switch must not reuse
        # the previous short-lived signed output or probe result.
        force_route_refresh = bool(
            previous_context
            and previous_context[:-1] == current_context[:-1]
            and flag_text
            and previous_context[-1]
            and flag_text != previous_context[-1]
        )
        if force_route_refresh:
            self._invalidate_route_probe(
                parsed.get("url"),
                parsed.get("resourceId"),
                parsed.get("resourceMode") or "vod",
            )
        play_context = (
            {"expected_generation": player_generation, "expected_backend": player_backend}
            if player_backend else {}
        )
        candidates = [{
            "url": str(parsed.get("url") or ""),
            "resourceId": str(parsed.get("resourceId") or ""),
            "resourceMode": str(parsed.get("resourceMode") or "vod"),
            "resourceProvider": str(parsed.get("resourceProvider") or ""),
            "name": str(parsed.get("name") or ""),
        }]
        unique_candidates = []
        for candidate in candidates:
            target = str(candidate.get("url") or "").strip()
            if not target or len(target) > self.FOLLOWPLAY_MAX_URL_LENGTH:
                continue
            if any(row["url"] == target for row in unique_candidates):
                continue
            row = dict(candidate)
            row["url"] = target
            unique_candidates.append(row)
        candidates = self._prepare_player_candidates(unique_candidates)
        errors = []
        total = len(candidates)
        deadline = time.monotonic() + self.FOLLOWPLAY_PLAY_BUDGET
        attempted = 0
        budget_exhausted = False
        for index, candidate in enumerate(candidates):
            now = time.monotonic()
            remaining = deadline - now
            if remaining < 2:
                errors.append("播放线路尝试已超时")
                budget_exhausted = True
                break
            target = candidate["url"]
            quality_id = candidate.get("_route_quality_id") or candidate.get("_route_refresh_target") or target
            candidate_deadline = now + (remaining / max(1, total - index))
            attempted += 1
            quality_probe = None
            try:
                probe = candidate.get("_route_probe") or {}
                cached_output = candidate.get("_route_output")
                output_validated = False
                if (not force_route_refresh
                        and isinstance(cached_output, dict)
                        and str(cached_output.get("url") or "").strip()):
                    cached_output = self._sanitize_route_output(cached_output)
                    if not isinstance(cached_output, dict) or not str(cached_output.get("url") or "").strip():
                        raise RuntimeError("缓存播放请求头无效")
                    if candidate.get("_route_requires_validation"):
                        probe_deadline = min(candidate_deadline, time.monotonic() + 2.5)
                        checked = self._probe_media_output(cached_output, deadline=probe_deadline)
                        if checked is not None and isinstance(checked.get("output"), dict):
                            output = dict(checked["output"])
                            output_validated = True
                            quality_probe = checked
                        else:
                            refresh_target = str(candidate.get("_route_refresh_target") or "").strip()
                            if not refresh_target:
                                raise RuntimeError("缓存线路验活失败")
                            output = dict(self._atvp_play(
                                refresh_target, deadline=candidate_deadline,
                                **play_context,
                            ) or {})
                    else:
                        output = dict(cached_output)
                elif (not force_route_refresh
                        and probe.get("reachable") is True
                        and isinstance(probe.get("output"), dict)):
                    output = dict(probe["output"])
                    output_validated = True
                    quality_probe = probe
                elif (not candidate.get("_route_requires_validation")
                        and target.startswith(("http://", "https://"))
                        and re.search(r"(?i)\.(?:m3u8|mp4|mkv|flv|ts)(?:[?#]|$)", target)):
                    output = {"parse": 0, "jx": 0, "url": target, "header": {}}
                else:
                    output = dict(self._atvp_play(
                        target, deadline=candidate_deadline,
                        **play_context,
                    ) or {})
                if not str(output.get("url") or "").strip():
                    raise RuntimeError("播放地址为空")
                if not output_validated:
                    probe_deadline = min(candidate_deadline, time.monotonic() + 4)
                    checked = self._probe_media_output(output, deadline=probe_deadline)
                    if checked is not None and isinstance(checked.get("output"), dict):
                        output = dict(checked["output"])
                        quality_probe = checked
                    elif self._safe_atvp_play_output(output):
                        # A non-HTTP target is an AList play identifier whose
                        # signed CDN output may already have expired. Re-issue
                        # it once before accepting an unprobed URL. Stable
                        # direct HTTP targets keep the existing weak-network
                        # tolerance.
                        needs_reissue = (
                            str(candidate.get("resourceMode") or "vod").strip().lower() in ("vod", "vod1")
                            and bool(re.match(r"^\d+@", target))
                            and not candidate.get("_route_refresh_attempted")
                        )
                        if needs_reissue:
                            candidate["_route_refresh_attempted"] = True
                            refreshed = dict(self._atvp_play(
                                target, deadline=candidate_deadline,
                                **play_context,
                            ) or {})
                            if not str(refreshed.get("url") or "").strip():
                                raise RuntimeError("媒体Range验证失败")
                            reprobe_deadline = min(
                                candidate_deadline, time.monotonic() + 4,
                            )
                            reprobed = self._probe_media_output(
                                refreshed, deadline=reprobe_deadline,
                            )
                            if reprobed is not None and isinstance(
                                    reprobed.get("output"), dict):
                                output = dict(reprobed["output"])
                                quality_probe = reprobed
                            elif self._safe_atvp_play_output(refreshed):
                                output = self._sanitize_route_output(refreshed)
                            else:
                                raise RuntimeError("媒体Range验证失败")
                        else:
                            # The AT response is parse=0 and the URL passed
                            # the safety gate, but this client cannot prove
                            # CDN reachability. Let FongMi try it and avoid
                            # caching an unverified reachable=True result.
                            output = self._sanitize_route_output(output)
                        if not isinstance(output, dict) or not str(output.get("url") or "").strip():
                            raise RuntimeError("播放请求头无效")
                    else:
                        raise RuntimeError("媒体Range验证失败")
                output.setdefault("parse", 0)
                output.setdefault("jx", 0)
                output.setdefault("playUrl", "")
                output.setdefault("header", {})
                output = self._sanitize_route_output(output)
                if not isinstance(output, dict) or not str(output.get("url") or "").strip():
                    raise RuntimeError("播放请求头无效")
                effective = dict(parsed)
                effective["url"] = target
                effective["resourceId"] = candidate.get("resourceId") or parsed.get("resourceId")
                effective["resourceProvider"] = (
                    candidate.get("resourceProvider") or parsed.get("resourceProvider") or ""
                )
                if candidate.get("name"):
                    effective["name"] = candidate["name"]
                self._inject_resume(output, effective)
                self._record_route_quality(
                    quality_id, True,
                    startup_ms=(quality_probe or {}).get("startup_ms"),
                    signals=quality_probe,
                    expected_generation=player_generation,
                    expected_backend=player_backend,
                )
                self._cache_route_probe(
                    quality_id,
                    quality_probe,
                    resource_id=effective.get("resourceId") or "",
                    resource_mode=effective.get("resourceMode") or "vod",
                    expected_generation=player_generation,
                    expected_backend=player_backend,
                )
                self._remember_successful_follow_route(
                    parsed, candidate, quality_id, quality_probe,
                    expected_generation=player_generation,
                    expected_backend=player_backend,
                )
                with self._history_context_lock:
                    with self._cache_lock:
                        player_is_current = (
                            player_generation == self._cache_generation
                            and player_backend == self._resource_capability_identity()
                        )
                if player_is_current:
                    self._register_playback_sync_window(effective)
                    self._schedule_native_history_ui_refresh()
                return output
            except Exception as exc:
                self._record_route_quality(
                    quality_id, False,
                    expected_generation=player_generation,
                    expected_backend=player_backend,
                )
                errors.append(self._short_error(exc))
        detail = errors[-1] if errors else "未知错误"
        attempt_text = (
            "%d/%d 条线路，因总预算耗尽停止" % (attempted, total)
            if budget_exhausted else "%d 条线路" % attempted
        )
        return {
            "parse": 0,
            "jx": 0,
            "playUrl": "",
            "url": "",
            "header": {},
            "msg": "当前集所有播放源均不可达，已尝试 %s：%s" % (attempt_text, detail),
        }

    def localProxy(self, param):
        value = param
        if isinstance(value, str):
            if self._utf8_size(value) > self.HISTORY_LOCAL_PROXY_MAX_BYTES:
                callback_match = re.search(
                    r'"follow_sync_callback"\s*:\s*"([^"\\]{1,256})"',
                    value[:8192],
                )
                if callback_match:
                    nonce = callback_match.group(1)
                    with self._native_export_lock:
                        pending = self._native_exports.get(nonce)
                    if pending:
                        pending["captured"]["error"] = "FongMi 本机 History 回调请求过大"
                        pending["event"].set()
                return [413, "application/json; charset=utf-8", "{\"error\":\"request too large\"}"]
            try:
                value = json.loads(value)
            except Exception:
                value = {}
        if isinstance(value, dict):
            nonce = str(value.get("follow_sync_callback") or "").strip()
            if nonce:
                with self._native_export_lock:
                    pending = self._native_exports.get(nonce)
                if pending:
                    config_text = str(value.get("config") or "")
                    targets_text = str(value.get("targets") or "[]")
                    if self._utf8_size(config_text) > self.HISTORY_CONFIG_MAX_BYTES:
                        pending["captured"]["error"] = "FongMi 本机订阅配置过大"
                    elif self._utf8_size(targets_text) > self.HISTORY_RESPONSE_MAX_BYTES:
                        pending["captured"]["error"] = "FongMi 本机 History 响应过大"
                    else:
                        pending["captured"].update({
                            "config": config_text,
                            "targets": targets_text,
                        })
                    pending["event"].set()
                    return [200, "application/json; charset=utf-8", "{}"]
            if str(value.get("playback_exit") or value.get("history_sync") or "").strip():
                self._flush_playback_sync_on_navigation()
                return [200, "application/json; charset=utf-8", "{}"]
        return [404, "text/plain; charset=utf-8", "not found"]

    def action(self, action):
        value = str(action or "")
        if (
            value == self.KEEP_FOLLOW_ACTION
            or value.startswith(self.SERIES_CARD_PREFIX)
            or value.startswith(self.DOUBAN_FOLLOW_ADD_PREFIX)
            or value.startswith(self.FOLLOW_ADD_PREFIX)
            or value.startswith(self.FOLLOW_SEEN_PREFIX)
            or value.startswith(self.FOLLOW_REMOVE_PREFIX)
            or value.startswith(self.FOLLOW_EXECUTE_PREFIX)
            or value.startswith(self.FOLLOW_CANDIDATE_ADD_PREFIX)
            or value.startswith(self.FOLLOW_CANDIDATE_CLEAR_PREFIX)
            or value.startswith(self.PLAYBACK_EXIT_PREFIX)
        ):
            self._load_follow_state(force=True)
        if value.startswith(self.PLAYBACK_EXIT_PREFIX):
            self._flush_playback_sync_on_navigation()
            return json.dumps({"msg": "播放记录同步已排队"}, ensure_ascii=False)
        if value == self.KEEP_FOLLOW_ACTION:
            message = "本地收藏已改为追更待选，请进入追更确认操作"
            self._set_follow_action_status("info", message, "candidate")
            self._refresh_follow_categories()
            return json.dumps({"msg": message}, ensure_ascii=False)
        if value == self.ATVP_PROBE_ACTION:
            return self._start_atvp_job("probe")
        if value == self.ATVP_SYNC_ACTION:
            return self._start_atvp_job("sync")
        if value.startswith(self.HISTORY_SHARE_ACTION_PREFIX):
            return self._toggle_history_share_policy(
                value[len(self.HISTORY_SHARE_ACTION_PREFIX):]
            )
        if value.startswith(self.GLOBAL_SEARCH_PREFIX):
            return self._open_global_search(value[len(self.GLOBAL_SEARCH_PREFIX):])
        if value.startswith(self.SERIES_MODE_PREFIX):
            return self._set_series_action_mode(value[len(self.SERIES_MODE_PREFIX):])
        if value.startswith(self.SERIES_CARD_PREFIX):
            return self._run_series_card_action(value[len(self.SERIES_CARD_PREFIX):])
        if value.startswith((self.DOUBAN_FOLLOW_ADD_PREFIX, self.FOLLOW_ADD_PREFIX)):
            message = "旧版直接追更入口已停用，请从收藏或播放记录进入追更确认"
            self._set_follow_action_status("info", message, "candidate")
            self._refresh_follow_categories()
            return json.dumps({"msg": message}, ensure_ascii=False)
        if value.startswith(self.FOLLOW_CANDIDATE_ADD_PREFIX):
            return self._start_follow_candidate_add(value[len(self.FOLLOW_CANDIDATE_ADD_PREFIX):])
        if value.startswith(self.FOLLOW_CANDIDATE_CLEAR_PREFIX):
            return self._request_follow_candidate_clear(
                value[len(self.FOLLOW_CANDIDATE_CLEAR_PREFIX):]
            )
        if value.startswith(self.FOLLOW_SEEN_PREFIX):
            return self._request_follow_confirmation("seen", value[len(self.FOLLOW_SEEN_PREFIX):])
        if value.startswith(self.FOLLOW_REMOVE_PREFIX):
            return self._request_follow_confirmation("remove", value[len(self.FOLLOW_REMOVE_PREFIX):])
        if value.startswith(self.FOLLOW_EXECUTE_PREFIX):
            return self._execute_follow_confirmation(value[len(self.FOLLOW_EXECUTE_PREFIX):])
        if value.startswith(self.FOLLOW_CONFIRM_CANCEL_PREFIX):
            return self._cancel_follow_confirmation(value[len(self.FOLLOW_CONFIRM_CANCEL_PREFIX):])
        if value == self.FOLLOW_STATUS_ACK_ACTION:
            return self._ack_follow_action_status()
        if not value.startswith(self.ACTION_PREFIX):
            return json.dumps({"msg": "不支持的导航操作"}, ensure_ascii=False)
        subject_id = self._subject_id(value[len(self.ACTION_PREFIX):])
        if not subject_id:
            return json.dumps({"msg": "豆瓣条目编号无效"}, ensure_ascii=False)
        if not self.cookie or not self.ck:
            return json.dumps({"msg": "未配置豆瓣 Cookie/ck，无法加入想看"}, ensure_ascii=False)
        try:
            url = self.MOVIE + "/j/subject/%s/interest" % subject_id
            headers = {
                "Referer": self.MOVIE + "/subject/%s/" % subject_id,
                "X-Requested-With": "XMLHttpRequest",
            }
            data = {"interest": "wish", "ck": self.ck, "tags": "", "comment": "", "privacy": "public"}
            response = self._session.post(url, headers=headers, data=data, timeout=self.timeout, verify=self.verify_tls)
            payload = self._json_response(response)
            if response.status_code == 200 and str(payload.get("r", "0")) == "0":
                self._drop_cache_prefix("wishlist:")
                return json.dumps({"msg": "已加入豆瓣想看"}, ensure_ascii=False)
            if response.status_code in (401, 403) or str(payload.get("code", "")) == "403":
                message = "豆瓣登录已失效，请更新 Cookie/ck"
            else:
                message = str(payload.get("msg") or payload.get("error") or "豆瓣未确认收藏成功")
            return json.dumps({"msg": message}, ensure_ascii=False)
        except Exception as exc:
            return json.dumps({"msg": "加入想看失败：%s" % self._short_error(exc)}, ensure_ascii=False)

    def _category_tmdb_trending(self, page, ext):
        media = self._value(ext, "media", "all")
        if media not in ("all", "movie", "tv"):
            media = "all"
        window = self._value(ext, "window", "day")
        if window not in ("day", "week"):
            window = "day"
        data = self._tmdb_api("/trending/%s/%s" % (media, window), {"page": page}, self.list_cache_ttl)
        return self._tmdb_page(data, page, "", self._follow_action_mode(ext))

    def _category_tmdb_discover(self, media_type, page, ext):
        params = {
            "page": page,
            "include_adult": "false",
            "sort_by": self._value(ext, "sort", "popularity.desc"),
        }
        genre = self._value(ext, "genre", "")
        year = self._value(ext, "year", "")
        country = self._value(ext, "country", "")
        if genre:
            params["with_genres"] = genre
        if country:
            params["with_origin_country"] = country
        if year:
            params["primary_release_year" if media_type == "movie" else "first_air_date_year"] = year
        if params["sort_by"] == "vote_average.desc":
            params["vote_count.gte"] = 100
        if media_type == "movie":
            params["region"] = self.tmdb_region
        data = self._tmdb_api("/discover/" + media_type, params, self.list_cache_ttl)
        return self._tmdb_page(data, page, media_type, self._follow_action_mode(ext))

    def _category_tmdb_anime(self, page, ext):
        media_type = self._value(ext, "kind", "tv")
        if media_type not in ("movie", "tv"):
            media_type = "tv"
        params = {
            "page": page,
            "include_adult": "false",
            "sort_by": self._value(ext, "sort", "popularity.desc"),
            "with_genres": "16",
        }
        region = self._value(ext, "region", "")
        year = self._value(ext, "year", "")
        if region:
            params["with_origin_country"] = region
        if year:
            params["primary_release_year" if media_type == "movie" else "first_air_date_year"] = year
        data = self._tmdb_api("/discover/" + media_type, params, self.list_cache_ttl)
        return self._tmdb_page(data, page, media_type, self._follow_action_mode(ext))

    def _tmdb_page(self, data, page, forced_type, action_mode=""):
        items = self._tmdb_cards(data.get("results"), forced_type, action_mode)
        pagecount = min(500, self._positive_int(data.get("total_pages"), page))
        total = self._positive_int(data.get("total_results"), len(items)) if items else int(data.get("total_results") or 0)
        return self._page_result(items, page, max(page, pagecount), total, 20)

    def _tmdb_cards(self, items, forced_type, action_mode=""):
        result = []
        followed = self._follow_memory.get("items") or {}
        for raw in items or []:
            if not isinstance(raw, dict):
                continue
            media_type = forced_type or str(raw.get("media_type") or "")
            if media_type not in ("movie", "tv"):
                continue
            tmdb_id = self._positive_int(raw.get("id"), 0)
            title = str(raw.get("title") or raw.get("name") or raw.get("original_title") or raw.get("original_name") or "").strip()
            if not tmdb_id or not title:
                continue
            date = str(raw.get("release_date") or raw.get("first_air_date") or "")
            score = self._score_text(raw.get("vote_average"))
            remark = " · ".join([value for value in (date[:4], score) if value])
            card = {
                "vod_id": "tmdb:%s:%s" % (media_type, tmdb_id),
                "vod_name": title,
                "vod_pic": self._tmdb_image(raw.get("poster_path") or raw.get("backdrop_path")),
                "vod_remarks": remark,
            }
            if media_type == "tv":
                tracked = str(tmdb_id) in followed
                state = "已追更" if tracked else "全局搜索"
                card["vod_remarks"] = state + ((" · " + remark) if remark else "")
            result.append(card)
        return result

    def _category_follow_candidates(self, page, ext=None):
        mode = self._value(ext or {}, "mode", "view")
        candidates, source_cards = self._native_follow_candidates()
        pending = [candidate for candidate in candidates if not self._candidate_is_followed(candidate)]
        start = (page - 1) * self.follow_page_size
        selected = pending[start:start + self.follow_page_size]
        cards = [self._follow_candidate_card(candidate, mode=mode) for candidate in selected]
        if page == 1:
            cards = self._follow_state_cards() + source_cards + cards
        if not pending and page == 1:
            cards.append({
                "vod_id": self.ERROR_PREFIX + quote("当前没有待确认追更", safe=""),
                "vod_name": "暂无追更待选",
                "vod_pic": "",
                "vod_remarks": "本机收藏和播放记录中没有未追更剧集",
            })
        pagecount = max(1, int(math.ceil(float(len(pending)) / self.follow_page_size)))
        return self._page_result(cards, page, pagecount, len(pending), self.follow_page_size)

    def _native_follow_candidates(self):
        merged = {}
        status_cards = []
        try:
            keeps = self._native_keep_export_java(self.keep_follow_scan_limit)
            if keeps is None:
                raise RuntimeError("当前运行时未提供FongMi收藏读取桥")
            for row in self._recent_follow_candidate_rows(keeps):
                self._merge_follow_candidate(merged, row, "keep")
        except Exception as exc:
            status_cards.append(self._follow_candidate_source_card("收藏读取失败", exc))
        try:
            exported = self._native_history_export_java(self.keep_follow_scan_limit)
            if exported is None:
                raise RuntimeError("当前运行时未提供FongMi播放记录读取桥")
            for row in self._recent_follow_candidate_rows(exported.get("rows")):
                self._merge_follow_candidate(merged, row, "history")
        except Exception as exc:
            status_cards.append(self._follow_candidate_source_card("播放记录读取失败", exc))
        candidates = list(merged.values())
        candidates.sort(key=lambda row: (
            self._positive_int(row.get("create_time"), 0),
            str(row.get("title") or ""),
        ), reverse=True)
        return candidates[:self.keep_follow_scan_limit * 2], status_cards

    def _recent_follow_candidate_rows(self, rows):
        return heapq.nlargest(
            self.keep_follow_scan_limit,
            (row for row in (rows or []) if isinstance(row, dict)),
            key=lambda row: self._positive_int(row.get("create_time") or row.get("createTime"), 0),
        )

    def _merge_follow_candidate(self, merged, row, source):
        if not isinstance(row, dict):
            return
        raw_title = str(row.get("title") or row.get("vodName") or "").strip()[:256]
        title, year, explicit_series = self._keep_search_profile(raw_title)
        title = str(title or raw_title).strip()[:256]
        title_identity = self._normalize_media_title(title)
        if not title_identity:
            return
        identity = "%s|%s" % (title_identity, str(year or "")[:4])
        candidate = merged.setdefault(identity, {
            "title": title,
            "match_title": raw_title,
            "pic": "",
            "create_time": 0,
            "sources": [],
            "keep_keys": [],
            "history_keys": [],
            "site_names": [],
            "history_remark": "",
        })
        if explicit_series or not candidate.get("match_title"):
            candidate["match_title"] = raw_title
        pic = str(row.get("pic") or row.get("vodPic") or "").strip()[:1024]
        if pic and not candidate.get("pic"):
            candidate["pic"] = pic
        created = self._positive_int(row.get("create_time") or row.get("createTime"), 0)
        candidate["create_time"] = max(self._positive_int(candidate.get("create_time"), 0), created)
        source_label = "收藏" if source == "keep" else "播放记录"
        if source_label not in candidate["sources"]:
            candidate["sources"].append(source_label)
        source_key = str(row.get("key") or "").strip()[:256]
        key_name = "keep_keys" if source == "keep" else "history_keys"
        if source_key and source_key not in candidate[key_name] and len(candidate[key_name]) < 3:
            candidate[key_name].append(source_key)
        site_name = str(row.get("site_name") or row.get("siteName") or "").strip()[:128]
        if site_name and site_name not in candidate["site_names"] and len(candidate["site_names"]) < 4:
            candidate["site_names"].append(site_name)
        if source == "history" and not candidate.get("history_remark"):
            candidate["history_remark"] = str(row.get("vodRemarks") or "").strip()[:256]
        if year and not candidate.get("year"):
            candidate["year"] = year

    def _candidate_is_followed(self, candidate):
        keep_keys = set(str(value) for value in candidate.get("keep_keys") or [] if value)
        history_keys = set(str(value) for value in candidate.get("history_keys") or [] if value)
        candidate_title = self._normalize_media_title(candidate.get("title"))
        candidate_year = str(candidate.get("year") or "")[:4]
        for item in (self._follow_memory.get("items") or {}).values():
            if not isinstance(item, dict):
                continue
            if keep_keys.intersection(str(value) for value in item.get("keep_keys") or [] if value):
                return True
            if history_keys.intersection(str(value) for value in item.get("history_keys") or [] if value):
                return True
            for alias in self._follow_title_alias_values(item):
                clean_alias = self._keep_search_profile(alias)[0]
                if candidate_title and candidate_title == self._normalize_media_title(clean_alias):
                    item_year = str(
                        item.get("year") or item.get("first_air_date") or item.get("release_date") or ""
                    )[:4]
                    if candidate_year and item_year and candidate_year != item_year:
                        continue
                    return True
        return False

    def _follow_candidate_card(self, candidate, mode="view"):
        encoded = self._encode_follow_candidate(candidate)
        clear_mode = str(mode or "view") == "clear"
        action = (
            self.FOLLOW_CANDIDATE_CLEAR_PREFIX if clear_mode
            else self.FOLLOW_CANDIDATE_ADD_PREFIX
        ) + encoded
        sources = " + ".join(candidate.get("sources") or ["本机记录"])
        year = str(candidate.get("year") or "")[:4]
        prefix = "清理待选 · 仅清理播放记录" if clear_mode else "追更待选"
        if clear_mode and candidate.get("keep_keys"):
            prefix += " · 收藏保留"
        remark = " · ".join(value for value in (prefix, year, sources) if value)
        history_remark = str(candidate.get("history_remark") or "").strip()
        if history_remark:
            remark += " · " + history_remark
        with self._follow_action_state_lock:
            status = dict((self._follow_action_state or {}).get("last") or {})
        if (
                not clear_mode
                and str(status.get("operation") or "") == "candidate"
                and str(status.get("title") or "") == str(candidate.get("title") or "")):
            state = str(status.get("state") or "")
            if state == "running":
                remark = "正在确认 · " + remark
            elif state in ("done", "failed"):
                remark = str(status.get("message") or remark)
        return {
            "vod_id": action,
            "vod_name": str(candidate.get("title") or "待确认剧集"),
            "vod_pic": str(candidate.get("pic") or ""),
            "vod_remarks": remark,
            "action": action,
        }

    def _follow_candidate_source_card(self, title, exc):
        message = "%s：%s" % (title, self._short_error(exc))
        return {
            "vod_id": self.ERROR_PREFIX + quote(message, safe=""),
            "vod_name": title,
            "vod_pic": "",
            "vod_remarks": message,
        }

    @staticmethod
    def _encode_follow_candidate(candidate):
        payload = {
            "title": str(candidate.get("title") or "")[:256],
            "match_title": str(candidate.get("match_title") or candidate.get("title") or "")[:256],
            "pic": str(candidate.get("pic") or "")[:1024],
            "sources": list(candidate.get("sources") or [])[:2],
            "keep_keys": [str(value)[:256] for value in (candidate.get("keep_keys") or [])[:3]],
            "history_keys": [str(value)[:256] for value in (candidate.get("history_keys") or [])[:3]],
            "site_names": [str(value)[:128] for value in (candidate.get("site_names") or [])[:4]],
            "year": str(candidate.get("year") or "")[:4],
        }
        raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

    @staticmethod
    def _decode_follow_candidate(value):
        try:
            encoded = str(value or "")
            if not encoded or len(encoded) > 8192:
                return None
            raw = encoded + "=" * ((4 - len(encoded) % 4) % 4)
            payload = json.loads(base64.urlsafe_b64decode(raw.encode("ascii")).decode("utf-8"))
            if not isinstance(payload, dict) or not str(payload.get("title") or "").strip():
                return None
            return payload
        except Exception:
            return None

    def _start_follow_candidate_add(self, payload):
        candidate = self._decode_follow_candidate(payload)
        if not candidate:
            result = json.dumps({"msg": "追更待选参数无效"}, ensure_ascii=False)
            return self._remember_follow_action_result(result, "candidate")
        title = str(candidate.get("title") or "").strip()
        if self._candidate_is_followed(candidate):
            result = json.dumps({"msg": "已在追更管理：" + title}, ensure_ascii=False)
            return self._remember_follow_action_result(result, "candidate", title)
        identity = "|".join((
            self._normalize_media_title(title),
            str(candidate.get("year") or "")[:4],
            self._normalize_media_title(candidate.get("match_title")),
        ))
        with self._cache_lock:
            generation = self._cache_generation
        job_key = "candidate:%s:%s" % (
            generation, hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16],
        )
        job_owner = object()
        with self._follow_enrich_lock:
            if job_key in self._follow_enrich_jobs:
                return json.dumps({"msg": "正在确认追更：" + title}, ensure_ascii=False)
            self._follow_enrich_jobs[job_key] = job_owner
            self._set_follow_action_status("running", "正在确认追更：" + title, "candidate", title)
        self._refresh_follow_categories()

        def worker():
            result = None
            try:
                item, reason = self._resolve_follow_candidate(candidate)
                if not isinstance(item, dict):
                    labels = {
                        "empty_title": "标题为空",
                        "no_confident_tv": "未找到可信剧集",
                        "ambiguous_tv": "存在多个同名剧集",
                        "movie_conflict": "匹配结果更可能是电影",
                    }
                    raise RuntimeError(labels.get(str(reason or ""), str(reason or "无法确认剧集")))
                key = str(self._positive_int(item.get("tmdb_id"), 0))
                if not key or key == "0":
                    raise RuntimeError("TMDB剧集编号无效")
                with self._history_context_lock:
                    self._require_history_generation(generation)
                    with self._follow_enrich_lock:
                        items = dict(self._follow_memory.get("items") or {})
                        previous = items.get(key)
                        output = dict(previous) if isinstance(previous, dict) else dict(item)
                        for field in ("keep_keys", "history_keys", "site_names"):
                            values = list(output.get(field) or [])
                            for value in candidate.get(field) or []:
                                text = str(value or "").strip()
                                if text and text not in values:
                                    values.append(text)
                            if values:
                                output[field] = values
                        output.update({
                            "follow_source": output.get("follow_source") or "fongmi_candidate",
                            "candidate_last_confirmed": int(time.time()),
                        })
                        items[key] = output
                        self._save_follow_state(items)
                    message = ("已在追更管理：" if isinstance(previous, dict) else "已加入追更：") + str(output.get("title") or title)
                    result = json.dumps({"msg": message}, ensure_ascii=False)
            except _HistorySyncCancelled:
                result = None
            except Exception as exc:
                result = json.dumps({"msg": "确认追更失败：%s" % self._short_error(exc)}, ensure_ascii=False)
            finally:
                self._finish_follow_candidate_job(job_key, job_owner, generation, result, title)

        try:
            self._tasks.start_thread(worker, name="follow-candidate")
        except Exception as exc:
            result = json.dumps({"msg": "确认追更启动失败：%s" % self._short_error(exc)}, ensure_ascii=False)
            self._finish_follow_candidate_job(job_key, job_owner, generation, result, title)
            return result
        return json.dumps({"msg": "已开始确认追更：" + title}, ensure_ascii=False)

    def _request_follow_candidate_clear(self, payload):
        candidate = self._decode_follow_candidate(payload)
        if not candidate:
            result = json.dumps({"msg": "清理待选参数无效"}, ensure_ascii=False)
            return self._remember_follow_action_result(result, "candidate-clear")
        title = str(candidate.get("title") or "").strip()
        history_keys = [
            str(value or "").strip()[:256]
            for value in candidate.get("history_keys") or []
            if str(value or "").strip()
        ][:3]
        if not history_keys:
            result = json.dumps({"msg": "该待选没有可清理的播放记录"}, ensure_ascii=False)
            return self._remember_follow_action_result(result, "candidate-clear", title)
        identity = hashlib.sha256("\n".join(history_keys).encode("utf-8")).hexdigest()[:16]
        now = int(time.time())
        with self._follow_action_state_lock:
            pending = dict((self._follow_action_state or {}).get("pending") or {})
        if (
                str(pending.get("operation") or "") == "candidate-clear"
                and str(pending.get("identity") or "") == identity
                and now - self._positive_int(pending.get("requested_at"), 0)
                <= self.FOLLOW_CONFIRM_TTL):
            return self._execute_follow_candidate_clear(str(pending.get("nonce") or ""))
        raw_nonce = "%s:%s:%s" % (identity, repr(time.time()), threading.get_ident())
        pending = {
            "nonce": hashlib.sha256(raw_nonce.encode("utf-8")).hexdigest()[:16],
            "operation": "candidate-clear",
            "identity": identity,
            "title": title,
            "history_keys": history_keys,
            "payload": str(payload or "")[:8192],
            "requested_at": now,
        }
        with self._follow_action_state_lock:
            state = dict(self._follow_action_state or {})
            state.update({"version": 1, "pending": pending})
            state.setdefault("last", {})
            self._follow_action_state = state
        self._persist_follow_action_state()
        self._set_follow_action_status(
            "info", "再次点击确认清理播放记录：" + title,
            "candidate-clear", title,
        )
        self._refresh_follow_categories()
        return json.dumps({"msg": "待确认清理播放记录：%s；请再次点击" % title}, ensure_ascii=False)

    def _execute_follow_candidate_clear(self, nonce):
        with self._follow_action_state_lock:
            pending = dict((self._follow_action_state or {}).get("pending") or {})
        requested_at = self._positive_int(pending.get("requested_at"), 0)
        valid = (
            str(pending.get("operation") or "") == "candidate-clear"
            and str(pending.get("nonce") or "") == str(nonce or "")
            and requested_at > 0
            and int(time.time()) - requested_at <= self.FOLLOW_CONFIRM_TTL
        )
        if not valid:
            result = json.dumps({"msg": "清理确认已失效，请重新选择"}, ensure_ascii=False)
            return self._remember_follow_action_result(result, "candidate-clear")
        title = str(pending.get("title") or "待选记录")
        history_keys = [
            str(value or "").strip()
            for value in pending.get("history_keys") or []
            if str(value or "").strip()
        ]
        self._clear_follow_pending_confirmation()
        try:
            cloud_required = bool(self._alist_tvbox_plugin and self._ensure_atvp_connection())
            if cloud_required and not self._history_write_enabled():
                raise RuntimeError("未配置History写入账号，未删除本机记录")
            local_deleted = self._native_history_delete_java(history_keys)
            if local_deleted is None:
                raise RuntimeError("当前运行时未提供FongMi单条History删除桥")
            cloud_deleted = 0
            if cloud_required:
                for key in history_keys:
                    self._atvp_history_delete(key)
                    cloud_deleted += 1
            with self._cache_lock:
                self._cache.pop("atvp-history-snapshot", None)
                self._persistent_cache.pop("atvp-history-snapshot", None)
            message = "已清理播放记录：%s（本机 %d 条%s）" % (
                title,
                local_deleted,
                "，云端 %d 条" % cloud_deleted if cloud_deleted else "",
            )
            result = json.dumps({"msg": message}, ensure_ascii=False)
        except Exception as exc:
            result = json.dumps({
                "msg": "清理播放记录失败：%s" % self._short_error(exc),
            }, ensure_ascii=False)
        return self._remember_follow_action_result(result, "candidate-clear", title)

    def _finish_follow_candidate_job(self, job_key, job_owner, generation, result, title):
        should_refresh = False
        with self._history_context_lock:
            if not self._history_generation_active(generation):
                with self._follow_enrich_lock:
                    if self._follow_enrich_jobs.get(job_key) is job_owner:
                        self._follow_enrich_jobs.pop(job_key, None)
                self._follow_candidate_results.pop(generation, None)
                return
            with self._follow_enrich_lock:
                if self._follow_enrich_jobs.get(job_key) is not job_owner:
                    return
                self._follow_enrich_jobs.pop(job_key, None)
                if result is not None:
                    self._follow_candidate_results.setdefault(generation, []).append((result, title))
                prefix = "candidate:%s:" % generation
                remaining = sum(
                    1 for key in self._follow_enrich_jobs if str(key).startswith(prefix)
                )
                if remaining:
                    self._set_follow_action_status(
                        "running", "正在确认追更：剩余 %d 项" % remaining, "candidate",
                    )
                    should_refresh = True
                else:
                    completed = self._follow_candidate_results.pop(generation, [])
                    if not completed:
                        return
                    messages = [self._follow_action_result_message(value) for value, _name in completed]
                    failed = sum(self._follow_action_message_failed(message) for message in messages)
                    if len(completed) == 1:
                        message = messages[0]
                        final_title = str(completed[0][1] or "")
                    else:
                        succeeded = len(completed) - failed
                        message = "追更确认完成：成功 %d 项，失败 %d 项" % (succeeded, failed)
                        if failed:
                            failures = [
                                value for value in messages if self._follow_action_message_failed(value)
                            ]
                            message += "；" + "；".join(failures[:3])
                        final_title = ""
                    self._set_follow_action_status(
                        "failed" if failed else "done", message, "candidate", final_title,
                    )
                    should_refresh = True
        if should_refresh:
            self._refresh_follow_categories()

    def _resolve_follow_candidate(self, candidate):
        probe = {
            "title": str(candidate.get("match_title") or candidate.get("title") or ""),
            "pic": str(candidate.get("pic") or ""),
        }
        item, reason = self._resolve_keep_follow_item(probe)
        if isinstance(item, dict):
            item = dict(item)
            item["follow_source"] = "fongmi_candidate"
            if not item.get("pic"):
                item["pic"] = probe["pic"]
        return item, reason

    def _category_follow_manage(self, page, ext):
        mode = self._value(ext, "mode", "view")
        followed = list((self._follow_memory.get("items") or {}).values())
        followed.sort(key=lambda item: str(item.get("title") or ""))
        histories = self._atvp_history_snapshot(nonblocking=True) if page == 1 or followed else []
        prefix_cards = self._follow_state_cards(include_pending=True) if page == 1 else []
        if page == 1 and mode == "view":
            prefix_cards.extend(self._history_management_cards())
        elif page == 1:
            prefix_cards = self._history_alert_cards() + prefix_cards
        if not followed:
            if page > 1:
                return self._page_result([], page, 1, 0, self.follow_page_size)
            empty = {
                "vod_id": self.ERROR_PREFIX + quote("当前没有已追更剧集", safe=""),
                "vod_name": "暂无追更剧集",
                "vod_pic": "",
                "vod_remarks": "当前没有已追更剧集",
            }
            return self._page_result(prefix_cards + [empty], 1, 1, 0, self.follow_page_size)
        start = (page - 1) * self.follow_page_size
        self._reconcile_follow_histories(histories)
        followed = list((self._follow_memory.get("items") or {}).values())
        followed.sort(key=lambda item: str(item.get("title") or ""))
        selected = followed[start:start + self.follow_page_size]
        cards = []
        for item in selected:
            cards.append(self._follow_card(
                item,
                mode if mode in ("seen", "remove") else "",
                self._atvp_history_for_item(item, histories),
            ))
        if page == 1:
            cards = prefix_cards + cards
        pagecount = max(1, int(math.ceil(float(len(followed)) / self.follow_page_size)))
        return self._page_result(cards, page, pagecount, len(followed), self.follow_page_size)

    def _category_follow_updates(self, page):
        self._require_tmdb_credentials()
        followed = list((self._follow_memory.get("items") or {}).values())
        start = (page - 1) * self.follow_page_size
        selected = followed[start:start + self.follow_page_size]
        self._refresh_follow_page_async(selected)
        histories = self._atvp_history_snapshot(nonblocking=True)
        self._reconcile_follow_histories(histories)
        state_items = self._follow_memory.get("items") or {}
        refreshed = [state_items.get(str(item.get("tmdb_id")), item) for item in selected]
        paired = [(item, self._atvp_history_for_item(item, histories)) for item in refreshed]
        paired.sort(key=lambda pair: (0 if self._has_follow_update(pair[0], pair[1]) else 1, str(pair[0].get("next_air_date") or "9999"), str(pair[0].get("title") or "")))
        cards = [self._follow_card(item, "", history) for item, history in paired]
        if page == 1:
            cards = self._history_alert_cards() + self._follow_state_cards() + cards
        pagecount = max(1, int(math.ceil(float(len(followed)) / self.follow_page_size)))
        return self._page_result(cards, page, pagecount, len(followed), self.follow_page_size)

    def _refresh_follow_page_async(self, items):
        now = int(time.time())
        due = [
            dict(item) for item in items or []
            if self._positive_int(item.get("tmdb_id"), 0)
            and (
                now - self._positive_int(item.get("last_checked"), 0) >= self.follow_check_ttl
                or (
                    not self._follow_title_alias_values(item, include_primary=False)
                    and not self._positive_int(item.get("title_aliases_checked_at"), 0)
                )
            )
        ]
        if not due:
            return False
        with self._cache_lock:
            generation = self._cache_generation
        job_key = "refresh:%s:%s" % (
            generation, ",".join(sorted(str(item.get("tmdb_id")) for item in due)),
        )
        job_owner = object()
        with self._follow_enrich_lock:
            if job_key in self._follow_enrich_jobs:
                return False
            self._follow_enrich_jobs[job_key] = job_owner

        def worker():
            updates = {}

            def refresh_item(item):
                if not self._follow_job_active(job_key, job_owner, generation):
                    return None
                return self._refresh_follow_item(item)

            try:
                if not self._follow_job_active(job_key, job_owner, generation):
                    return
                futures = {}
                for item in due:
                    if not self._follow_job_active(job_key, job_owner, generation):
                        return
                    futures[self._follow_refresh_executor.submit(refresh_item, item)] = item
                try:
                    for future in as_completed(futures):
                        if not self._follow_job_active(job_key, job_owner, generation):
                            return
                        source = futures[future]
                        key = str(source.get("tmdb_id"))
                        try:
                            updates[key] = future.result()
                        except Exception as exc:
                            failed = dict(source)
                            failed["check_error"] = self._short_error(exc)
                            failed["last_checked"] = int(time.time())
                            updates[key] = failed
                finally:
                    for future in futures:
                        if not future.done():
                            future.cancel()
                if updates:
                    with self._history_context_lock:
                        if not self._follow_generation_active(generation):
                            return
                        with self._follow_enrich_lock:
                            if not self._follow_job_owner_active_locked(job_key, job_owner):
                                return
                            current = dict(self._follow_memory.get("items") or {})
                            for key, item in updates.items():
                                if key in current:
                                    current[key] = item
                            self._save_follow_state(current)
                    self._refresh_follow_categories()
            finally:
                with self._follow_enrich_lock:
                    if self._follow_enrich_jobs.get(job_key) is job_owner:
                        self._follow_enrich_jobs.pop(job_key, None)

        try:
            self._tasks.start_thread(worker, name="follow-refresh")
        except Exception:
            with self._follow_enrich_lock:
                if self._follow_enrich_jobs.get(job_key) is job_owner:
                    self._follow_enrich_jobs.pop(job_key, None)
            return False
        return True

    def _category_follow_sync(self, page):
        # Keep the retired category ID usable for clients with a cached class list.
        return self._category_follow_manage(page, {"mode": "view"})

    def _load_history_share_policy(self):
        current = dict(self._history_share_policy or {"follow": True, "watch": True})
        getter = getattr(self, "getCache", None)
        if not callable(getter):
            with self._history_context_lock:
                self._history_share_policy_loaded = False
            return current
        try:
            value = getter(self.HISTORY_SHARE_POLICY_CACHE_KEY)
        except Exception:
            with self._history_context_lock:
                self._history_share_policy_loaded = False
            return current
        if value is not None and not isinstance(value, dict):
            with self._history_context_lock:
                self._history_share_policy_loaded = False
            return current
        policy = {"follow": True, "watch": True} if value is None else current
        if isinstance(value, dict):
            source = value.get("policy") if isinstance(value.get("policy"), dict) else value
            for kind in policy:
                if kind in source:
                    policy[kind] = self._bool_value(source.get(kind), policy[kind])
        with self._history_context_lock:
            self._history_share_policy = policy
            self._history_share_policy_loaded = True
        return dict(policy)

    def _persist_history_share_policy(self, policy=None):
        setter = getattr(self, "setCache", None)
        if not callable(setter):
            return False
        candidate = dict(policy or self._history_share_policy or {})
        payload = {
            "version": 1,
            "follow": self._bool_value(candidate.get("follow"), True),
            "watch": self._bool_value(candidate.get("watch"), True),
            "updated_at": int(time.time()),
        }
        try:
            result = setter(self.HISTORY_SHARE_POLICY_CACHE_KEY, payload)
            return result is not False and result != "failed"
        except Exception:
            return False

    def _toggle_history_share_policy(self, kind):
        kind = str(kind or "").strip().lower()
        if kind not in ("follow", "watch"):
            return json.dumps({"msg": "History 共享设置无效"}, ensure_ascii=False)
        with self._history_context_lock:
            current = dict(self._history_share_policy or {"follow": True, "watch": True})
            if self._history_share_policy_loaded:
                candidate = dict(current)
                candidate[kind] = not bool(current.get(kind, True))
            else:
                candidate = {"follow": False, "watch": False}
                candidate[kind] = True
            if not self._persist_history_share_policy(candidate):
                return json.dumps({"msg": "History 共享设置未能保存，本机状态未改变"}, ensure_ascii=False)
            self._history_share_policy = {
                "follow": bool(candidate.get("follow", True)),
                "watch": bool(candidate.get("watch", True)),
            }
            self._history_share_policy_loaded = True
            enabled = self._history_share_policy[kind]
        label = "追更播放记录" if kind == "follow" else "观看记录"
        state = "允许" if enabled else "禁止"
        self._refresh_follow_categories()
        return json.dumps({
            "msg": "%s已%s异地同步；仅影响本机未来上传，不影响云端读取、合并和已有记录" % (label, state),
        }, ensure_ascii=False)

    def _history_share_uploads(self, rows):
        if not self._history_share_policy_loaded:
            return []
        policy = dict(self._history_share_policy or {"follow": True, "watch": True})
        output = []
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            is_follow = self._history_has_followplay_reference(row)
            if is_follow and not bool(policy.get("follow", True)):
                continue
            if not is_follow and not bool(policy.get("watch", True)):
                continue
            output.append(row)
        return output

    def _history_management_cards(self):
        ready = bool(self.atvp_api and self.atvp_token and self._atvp_session is not None)
        probe_remark = self._atvp_status_remark("probe")
        sync_remark = self._atvp_status_remark("sync")
        mode = self._history_sync_mode_label()
        sync_card = {
            "vod_id": self.ATVP_SYNC_ACTION,
            "vod_name": "立即同步 History",
            "vod_pic": "",
            "vod_remarks": "%s · %s" % (
                mode,
                sync_remark or ("后台同步已启用" if ready else "等待识别 AList-TVBox 地址"),
            ),
            "action": self.ATVP_SYNC_ACTION,
        }
        policy = dict(self._history_share_policy or {"follow": True, "watch": True})
        policy_loaded = bool(self._history_share_policy_loaded)
        cards = [sync_card]
        for kind, label in (("follow", "追更播放记录"), ("watch", "观看记录")):
            enabled = bool(policy.get(kind, True))
            cards.append({
                "vod_id": self.HISTORY_SHARE_ACTION_PREFIX + kind,
                "vod_name": "%s：%s" % (
                    label,
                    ("允许异地同步" if enabled else "禁止异地同步") if policy_loaded else "暂缓异地同步",
                ),
                "vod_pic": "",
                "vod_remarks": (
                    "本机设置暂未读取，已暂停上传；点击可明确设置"
                    if not policy_loaded else
                    "点击切换 · 仅影响本机未来上传，不影响云端读取、合并和已有记录"
                ),
                "action": self.HISTORY_SHARE_ACTION_PREFIX + kind,
            })
        cards.append(self._atvp_probe_card(probe_remark))
        return cards

    def _history_alert_cards(self):
        status = self._atvp_status.get("sync") if isinstance(self._atvp_status, dict) else None
        if not isinstance(status, dict) or status.get("state") not in ("running", "failed"):
            return []
        state = str(status.get("state") or "")
        message = str(status.get("message") or "").strip()
        updated_at = self._positive_int(status.get("updated_at"), 0)
        timestamp = time.strftime("%m-%d %H:%M", time.localtime(updated_at)) if updated_at else ""
        return [{
            "vod_id": self.ATVP_SYNC_ACTION,
            "vod_name": "History 正在同步" if state == "running" else "History 同步失败",
            "vod_pic": "",
            "vod_remarks": message + ((" · " + timestamp) if timestamp else ""),
            "action": self.ATVP_SYNC_ACTION,
        }]

    def _request_follow_confirmation(self, operation, raw_id):
        operation = str(operation or "").strip().lower()
        tmdb_id = self._positive_int(raw_id, 0)
        if operation not in ("seen", "remove") or not tmdb_id:
            return json.dumps({"msg": "追更确认参数无效"}, ensure_ascii=False)
        item = (self._follow_memory.get("items") or {}).get(str(tmdb_id))
        if not isinstance(item, dict):
            result = json.dumps({"msg": "该剧集尚未追更"}, ensure_ascii=False)
            return self._remember_follow_action_result(result, operation)
        title = str(item.get("title") or tmdb_id)
        requested_at = int(time.time())
        raw_nonce = "%s:%s:%s:%s" % (operation, tmdb_id, repr(time.time()), threading.get_ident())
        pending = {
            "nonce": hashlib.sha256(raw_nonce.encode("utf-8")).hexdigest()[:16],
            "operation": operation,
            "tmdb_id": tmdb_id,
            "title": title,
            "requested_at": requested_at,
        }
        with self._follow_action_state_lock:
            state = dict(self._follow_action_state or {})
            state.update({"version": 1, "pending": pending})
            state.setdefault("last", {})
            self._follow_action_state = state
        self._persist_follow_action_state()
        self._refresh_follow_categories()
        label = "标记已看" if operation == "seen" else "取消追更"
        return json.dumps({"msg": "待确认%s：%s" % (label, title)}, ensure_ascii=False)

    def _execute_follow_confirmation(self, payload):
        parts = str(payload or "").split(":", 2)
        if len(parts) != 3:
            result = json.dumps({"msg": "追更确认参数无效"}, ensure_ascii=False)
            return self._remember_follow_action_result(result, "confirm")
        nonce, operation, raw_id = parts
        tmdb_id = self._positive_int(raw_id, 0)
        with self._follow_action_state_lock:
            pending = dict((self._follow_action_state or {}).get("pending") or {})
        requested_at = self._positive_int(pending.get("requested_at"), 0)
        same_pending = bool(nonce and nonce == str(pending.get("nonce") or ""))
        valid = (
            same_pending
            and operation == str(pending.get("operation") or "")
            and tmdb_id == self._positive_int(pending.get("tmdb_id"), 0)
            and operation in ("seen", "remove")
            and requested_at > 0
            and int(time.time()) - requested_at <= self.FOLLOW_CONFIRM_TTL
        )
        if same_pending:
            self._clear_follow_pending_confirmation()
        if not valid:
            result = json.dumps({"msg": "确认已失效，请重新选择剧集"}, ensure_ascii=False)
            return self._remember_follow_action_result(result, operation or "confirm")
        result = self._follow_action(operation, tmdb_id)
        return self._remember_follow_action_result(result, operation, str(pending.get("title") or ""))

    def _cancel_follow_confirmation(self, nonce):
        with self._follow_action_state_lock:
            pending = dict((self._follow_action_state or {}).get("pending") or {})
        if not pending or str(pending.get("nonce") or "") != str(nonce or ""):
            result = json.dumps({"msg": "确认已失效，无需取消"}, ensure_ascii=False)
            return self._remember_follow_action_result(result, "confirm")
        title = str(pending.get("title") or "")
        operation = str(pending.get("operation") or "")
        self._clear_follow_pending_confirmation()
        label = "标记已看" if operation == "seen" else "取消追更"
        message = "已放弃%s%s" % (label, ("：" + title) if title else "")
        self._set_follow_action_status("info", message, operation, title)
        self._refresh_follow_categories()
        return json.dumps({"msg": message}, ensure_ascii=False)

    def _clear_follow_pending_confirmation(self):
        with self._follow_action_state_lock:
            state = dict(self._follow_action_state or {})
            state.update({"version": 1, "pending": {}})
            state.setdefault("last", {})
            self._follow_action_state = state
        self._persist_follow_action_state()

    def _ack_follow_action_status(self):
        with self._follow_action_state_lock:
            state = dict(self._follow_action_state or {})
            state.update({"version": 1, "last": {}})
            state.setdefault("pending", {})
            self._follow_action_state = state
        self._persist_follow_action_state()
        self._refresh_follow_categories()
        return json.dumps({"msg": "操作状态已清除"}, ensure_ascii=False)

    def _load_follow_action_state(self):
        getter = getattr(self, "getCache", None)
        value = None
        if callable(getter):
            try:
                value = getter(self.FOLLOW_ACTION_STATE_CACHE_KEY)
            except Exception:
                value = None
        last = value.get("last") if isinstance(value, dict) else {}
        pending = value.get("pending") if isinstance(value, dict) else {}
        last = dict(last) if isinstance(last, dict) else {}
        pending = dict(pending) if isinstance(pending, dict) else {}
        interrupted = last.get("state") == "running"
        if interrupted:
            last.update({
                "state": "failed",
                "message": "上次确认追更被中断，请重新操作",
                "updated_at": int(time.time()),
            })
        requested_at = self._positive_int(pending.get("requested_at"), 0)
        if requested_at <= 0 or int(time.time()) - requested_at > self.FOLLOW_CONFIRM_TTL:
            pending = {}
        with self._follow_action_state_lock:
            self._follow_action_state = {"version": 1, "last": last, "pending": pending}
        if interrupted:
            self._persist_follow_action_state()

    def _persist_follow_action_state(self):
        setter = getattr(self, "setCache", None)
        if not callable(setter):
            return False
        with self._follow_action_state_persist_lock:
            with self._follow_action_state_lock:
                payload = {
                    "version": 1,
                    "last": dict((self._follow_action_state or {}).get("last") or {}),
                    "pending": dict((self._follow_action_state or {}).get("pending") or {}),
                }
            try:
                setter(self.FOLLOW_ACTION_STATE_CACHE_KEY, payload)
                return True
            except Exception:
                return False

    def _set_follow_action_status(self, state, message, operation="", title=""):
        status = {
            "state": str(state or "info"),
            "message": str(message or "操作完成"),
            "operation": str(operation or ""),
            "title": str(title or ""),
            "updated_at": int(time.time()),
        }
        with self._follow_action_state_lock:
            value = dict(self._follow_action_state or {})
            value.update({"version": 1, "last": status})
            value.setdefault("pending", {})
            self._follow_action_state = value
        self._persist_follow_action_state()
        return status

    def _remember_follow_action_result(self, result, operation, title=""):
        message = self._follow_action_result_message(result)
        failed = self._follow_action_message_failed(message)
        self._set_follow_action_status("failed" if failed else "done", message, operation, title)
        self._refresh_follow_categories()
        return result

    @staticmethod
    def _follow_action_result_message(result):
        payload = result
        if isinstance(result, str):
            try:
                payload = json.loads(result)
            except Exception:
                payload = {"msg": result}
        return str(payload.get("msg") or "操作完成") if isinstance(payload, dict) else "操作完成"

    @staticmethod
    def _follow_action_message_failed(message):
        return any(word in str(message or "") for word in (
            "失败", "无效", "无法", "未配置", "不可用", "不存在", "超时", "错误", "尚未追更", "已失效",
        ))

    def _follow_state_cards(self, include_pending=False):
        cards = []
        with self._follow_action_state_lock:
            state = dict(self._follow_action_state or {})
            pending = dict(state.get("pending") or {})
            last = dict(state.get("last") or {})
        requested_at = self._positive_int(pending.get("requested_at"), 0)
        if include_pending and pending and requested_at and int(time.time()) - requested_at <= self.FOLLOW_CONFIRM_TTL:
            operation = str(pending.get("operation") or "")
            tmdb_id = self._positive_int(pending.get("tmdb_id"), 0)
            nonce = str(pending.get("nonce") or "")
            title = str(pending.get("title") or tmdb_id)
            if operation in ("seen", "remove") and tmdb_id and nonce:
                label = "标记已看" if operation == "seen" else "取消追更"
                execute = self.FOLLOW_EXECUTE_PREFIX + "%s:%s:%s" % (nonce, operation, tmdb_id)
                cards.extend([
                    {
                        "vod_id": execute,
                        "vod_name": "确认%s：%s" % (label, title),
                        "vod_pic": "",
                        "vod_remarks": "待确认 · %s分钟内有效" % max(1, self.FOLLOW_CONFIRM_TTL // 60),
                        "action": execute,
                    },
                    {
                        "vod_id": self.FOLLOW_CONFIRM_CANCEL_PREFIX + nonce,
                        "vod_name": "放弃本次操作",
                        "vod_pic": "",
                        "vod_remarks": title,
                        "action": self.FOLLOW_CONFIRM_CANCEL_PREFIX + nonce,
                    },
                ])
        message = str(last.get("message") or "").strip()
        if message:
            state_name = str(last.get("state") or "info")
            label = {"done": "操作成功", "failed": "操作失败", "running": "处理中"}.get(state_name, "操作状态")
            updated_at = self._positive_int(last.get("updated_at"), 0)
            timestamp = time.strftime("%m-%d %H:%M", time.localtime(updated_at)) if updated_at else ""
            cards.append({
                "vod_id": self.FOLLOW_STATUS_ACK_ACTION,
                "vod_name": label,
                "vod_pic": "",
                "vod_remarks": message + ((" · " + timestamp) if timestamp else ""),
                "action": self.FOLLOW_STATUS_ACK_ACTION,
            })
        return cards

    def _follow_action(self, operation, raw_id, title=""):
        tmdb_id = self._positive_int(raw_id, 0)
        if not tmdb_id:
            return json.dumps({"msg": "TMDB 剧集编号无效"}, ensure_ascii=False)
        try:
            self._require_tmdb_credentials()
            key = str(tmdb_id)
            if operation == "remove":
                with self._follow_enrich_lock:
                    items = dict(self._follow_memory.get("items") or {})
                    if key not in items:
                        return json.dumps({"msg": "该剧集尚未追更"}, ensure_ascii=False)
                    title = str(items[key].get("title") or key)
                    items.pop(key, None)
                    self._save_follow_state(items)
                return json.dumps({"msg": "已取消追更：" + title}, ensure_ascii=False)
            if operation == "seen":
                with self._follow_enrich_lock:
                    if key not in (self._follow_memory.get("items") or {}):
                        return json.dumps({"msg": "该剧集尚未追更"}, ensure_ascii=False)
                data = self._tmdb_api("/tv/%s" % tmdb_id, {}, self.detail_cache_ttl, allow_stale=False)
                with self._follow_enrich_lock:
                    items = dict(self._follow_memory.get("items") or {})
                    current = dict(items.get(key) or {})
                    if not current:
                        return json.dumps({"msg": "该剧集已取消追更"}, ensure_ascii=False)
                    item = self._follow_item_from_tmdb(data, current)
                    item["seen_episode"] = str(item.get("latest_episode") or item.get("seen_episode") or "")
                    item["tracked_episode"] = str(item.get("latest_episode") or item.get("tracked_episode") or "")
                    item["seen_source"] = "manual"
                    message = "已标记看到 " + (item["seen_episode"] or "当前进度")
                    items[key] = item
                    self._save_follow_state(items)
                return json.dumps({"msg": message}, ensure_ascii=False)
            with self._follow_enrich_lock:
                items = dict(self._follow_memory.get("items") or {})
                existing = items.get(key)
                if isinstance(existing, dict):
                    existing_title = str(existing.get("title") or key)
                    retry_enrichment = bool(existing.get("pending_metadata") or existing.get("enrich_error"))
                else:
                    item = {
                        "tmdb_id": tmdb_id,
                        "title": str(title or ("TMDB剧集 " + key)),
                        "seen_episode": "",
                        "tracked_episode": "",
                        "seen_source": "",
                        "pending_metadata": True,
                        "last_checked": 0,
                    }
                    items[key] = item
                    self._save_follow_state(items)
                    existing_title = item["title"]
                    retry_enrichment = True
            if isinstance(existing, dict):
                if retry_enrichment:
                    self._start_follow_enrichment("tmdb", key, existing_title)
                return json.dumps({"msg": "已经在追更列表：" + existing_title}, ensure_ascii=False)
            self._start_follow_enrichment("tmdb", key, item["title"])
            return json.dumps({"msg": "已加入追更，分集资料正在后台补全：" + item["title"]}, ensure_ascii=False)
        except Exception as exc:
            return json.dumps({"msg": "追更操作失败：%s" % self._short_error(exc)}, ensure_ascii=False)

    def _follow_action_from_douban(self, raw_id, title=""):
        subject_id = self._subject_id(raw_id)
        if not subject_id:
            return json.dumps({"msg": "豆瓣条目编号无效"}, ensure_ascii=False)
        try:
            self._require_tmdb_credentials()
            with self._follow_enrich_lock:
                items = dict(self._follow_memory.get("items") or {})
                existing = next((item for item in items.values() if str(item.get("douban_id") or "") == subject_id), None)
                if isinstance(existing, dict):
                    existing_title = str(existing.get("title") or subject_id)
                    retry_enrichment = bool(existing.get("pending_metadata") or existing.get("enrich_error"))
                else:
                    key = "douban:" + subject_id
                    item = {
                        "tmdb_id": 0,
                        "douban_id": subject_id,
                        "title": str(title or ("豆瓣剧集 " + subject_id)),
                        "seen_episode": "",
                        "tracked_episode": "",
                        "seen_source": "",
                        "pending_metadata": True,
                        "last_checked": 0,
                    }
                    items[key] = item
                    self._save_follow_state(items)
            if isinstance(existing, dict):
                if retry_enrichment:
                    self._start_follow_enrichment("douban", subject_id, existing_title)
                return json.dumps({"msg": "已经在追更列表：" + existing_title}, ensure_ascii=False)
            self._start_follow_enrichment("douban", subject_id, item["title"])
            return json.dumps({"msg": "已加入追更，豆瓣与TMDB正在后台映射：" + item["title"]}, ensure_ascii=False)
        except Exception as exc:
            return json.dumps({"msg": "豆瓣映射追更失败：%s" % self._short_error(exc)}, ensure_ascii=False)

    def _start_follow_enrichment(self, source, item_id, title=""):
        with self._cache_lock:
            generation = self._cache_generation
        job_key = "%s:%s:%s" % (source, generation, item_id)
        job_owner = object()
        with self._follow_enrich_lock:
            if job_key in self._follow_enrich_jobs:
                return False
            self._follow_enrich_jobs[job_key] = job_owner

        def worker():
            try:
                if not self._follow_job_active(job_key, job_owner, generation):
                    return
                if source == "tmdb":
                    self._enrich_tmdb_follow(item_id, job_key, job_owner, generation)
                else:
                    self._enrich_douban_follow(item_id, title, job_key, job_owner, generation)
            except Exception as exc:
                self._mark_follow_enrichment_failed(
                    source, item_id, exc, job_key, job_owner, generation,
                )
            finally:
                refresh = False
                with self._follow_enrich_lock:
                    if self._follow_enrich_jobs.get(job_key) is job_owner:
                        self._follow_enrich_jobs.pop(job_key, None)
                        refresh = True
                refresh = refresh and self._follow_generation_active(generation)
                if refresh:
                    self._refresh_follow_categories()

        try:
            self._tasks.start_thread(worker, name="follow-enrich")
        except Exception:
            with self._follow_enrich_lock:
                if self._follow_enrich_jobs.get(job_key) is job_owner:
                    self._follow_enrich_jobs.pop(job_key, None)
            return False
        return True

    def _follow_generation_active(self, expected_generation):
        with self._cache_lock:
            return expected_generation == self._cache_generation

    def _follow_job_active(self, job_key, job_owner, expected_generation):
        if not self._follow_generation_active(expected_generation):
            return False
        with self._follow_enrich_lock:
            return self._follow_enrich_jobs.get(job_key) is job_owner

    def _follow_job_owner_active_locked(self, job_key, job_owner):
        return self._follow_enrich_jobs.get(job_key) is job_owner

    def _enrich_tmdb_follow(self, raw_id, job_key=None, job_owner=None, generation=None):
        tmdb_id = self._positive_int(raw_id, 0)
        key = str(tmdb_id)
        if job_key is not None and not self._follow_job_active(job_key, job_owner, generation):
            return
        data = self._tmdb_api("/tv/%s" % tmdb_id, {}, self.detail_cache_ttl, allow_stale=False)
        with self._follow_enrich_lock:
            if job_key is not None and not self._follow_job_owner_active_locked(
                    job_key, job_owner):
                return
            items = dict(self._follow_memory.get("items") or {})
            previous = items.get(key)
            if not isinstance(previous, dict):
                return
        item = self._follow_item_from_tmdb(data, previous)
        item["pending_metadata"] = False
        item.pop("enrich_error", None)
        item = self._attach_tmdb_title_aliases(item, data)
        try:
            if job_key is not None and not self._follow_job_active(job_key, job_owner, generation):
                return
            item = self._attach_douban_to_tmdb_item(item, data)
        except Exception as exc:
            item["mapping_error"] = self._short_error(exc)
        with self._history_context_lock:
            if job_key is not None and not self._follow_generation_active(generation):
                return
            with self._follow_enrich_lock:
                if job_key is not None and not self._follow_job_owner_active_locked(
                        job_key, job_owner):
                    return
                items = dict(self._follow_memory.get("items") or {})
                if key not in items:
                    return
                items[key] = item
                self._save_follow_state(items)

    def _enrich_douban_follow(
            self, subject_id, title="", job_key=None, job_owner=None, generation=None):
        pending_key = "douban:" + str(subject_id)
        if job_key is not None and not self._follow_job_active(job_key, job_owner, generation):
            return
        douban = self._get_json(
            self.API + "/subject/" + str(subject_id),
            params={"for_mobile": 1},
            ttl=self.detail_cache_ttl,
        )
        if job_key is not None and not self._follow_job_active(job_key, job_owner, generation):
            return
        matched = self._match_douban_tv_to_tmdb(douban)
        tmdb_id = self._positive_int(matched.get("id"), 0)
        if not tmdb_id:
            raise RuntimeError("未找到可信的TMDB剧集匹配")
        if job_key is not None and not self._follow_job_active(job_key, job_owner, generation):
            return
        detail = self._tmdb_api("/tv/%s" % tmdb_id, {}, self.detail_cache_ttl, allow_stale=False)
        with self._follow_enrich_lock:
            if job_key is not None and not self._follow_job_owner_active_locked(
                    job_key, job_owner):
                return
            items = dict(self._follow_memory.get("items") or {})
            pending = items.get(pending_key)
            if not isinstance(pending, dict):
                return
            previous = items.get(str(tmdb_id)) or pending
        item = self._follow_item_from_tmdb(detail, previous)
        item.update({"douban_id": str(subject_id), "pending_metadata": False})
        item = self._merge_follow_title_aliases(
            item,
            (douban.get("title"), douban.get("original_title")),
        )
        item = self._attach_tmdb_title_aliases(item, detail)
        item.pop("enrich_error", None)
        with self._history_context_lock:
            if job_key is not None and not self._follow_generation_active(generation):
                return
            with self._follow_enrich_lock:
                if job_key is not None and not self._follow_job_owner_active_locked(
                        job_key, job_owner):
                    return
                items = dict(self._follow_memory.get("items") or {})
                if pending_key not in items:
                    return
                items.pop(pending_key, None)
                items[str(tmdb_id)] = item
                self._save_follow_state(items)

    def _mark_follow_enrichment_failed(
            self, source, item_id, exc, job_key=None, job_owner=None, generation=None):
        key = str(item_id) if source == "tmdb" else "douban:" + str(item_id)
        with self._history_context_lock:
            if job_key is not None and not self._follow_generation_active(generation):
                return
            with self._follow_enrich_lock:
                if job_key is not None and not self._follow_job_owner_active_locked(
                        job_key, job_owner):
                    return
                items = dict(self._follow_memory.get("items") or {})
                item = items.get(key)
                if not isinstance(item, dict):
                    return
                item = dict(item)
                item["pending_metadata"] = False
                item["enrich_error"] = self._short_error(exc)
                item["last_checked"] = int(time.time())
                items[key] = item
                self._save_follow_state(items)

    def _refresh_native_view(self, refresh_type):
        refresh_type = str(refresh_type or "").strip().lower()
        if refresh_type not in ("category", "detail"):
            return False
        origins = []
        try:
            origins.append(self._fongmi_local_origin())
        except Exception:
            pass
        origins.extend("http://127.0.0.1:%s" % port for port in range(9978, 9999))
        checked = set()
        session = requests.Session()
        session.trust_env = False
        try:
            for origin in origins:
                if origin in checked:
                    continue
                checked.add(origin)
                try:
                    response = session.get(
                        origin + "/action",
                        params={"do": "refresh", "type": refresh_type},
                        timeout=1.0,
                    )
                    if response.status_code == 200:
                        print("[follow-refresh] fongmi-http type=%s origin=loopback" % refresh_type)
                        return True
                except Exception:
                    continue
            return False
        finally:
            session.close()

    def _refresh_native_category(self):
        return self._refresh_native_view("category")

    @staticmethod
    def _refresh_native_history_views():
        try:
            from java import jclass
            refresh = jclass("com.fongmi.android.tv.event.RefreshEvent")
            refresh.history()
            refresh.home()
            return True
        except Exception:
            return False

    def _invalidate_history_snapshot(self):
        with self._history_context_lock:
            self._history_snapshot_revision += 1
            with self._cache_lock:
                self._cache.pop("atvp-history-snapshot", None)
                self._persistent_cache.pop("atvp-history-snapshot", None)
            return self._history_snapshot_revision

    def _refresh_local_follow_progress(self):
        try:
            histories = self._capture_native_history()
            changed_items = []
            self._reconcile_follow_histories(histories, changed_items)
            if changed_items:
                self._schedule_entry_resource_preheat(changed_items)
            return True
        except Exception as exc:
            self._diagnostic_event("history_ui.local_refresh", "WARN", exc=exc)
            return False

    def _history_ui_refresh_active(self, token, generation):
        with self._history_ui_refresh_lock:
            if token != self._history_ui_refresh_token:
                return False
        return self._history_generation_active(generation) and not self._tasks.is_closed()

    def _schedule_history_ui_refresh_step(self, delay, token, generation, phase, started_at):
        if not self._history_ui_refresh_active(token, generation):
            return False
        try:
            self._tasks.start_timer(
                delay,
                self._native_history_ui_refresh_step,
                args=(token, generation, phase, started_at),
                name="history-ui-refresh",
            )
            return True
        except Exception:
            return False

    def _native_history_ui_refresh_step(self, token, generation, phase, started_at):
        if not self._history_ui_refresh_active(token, generation):
            return
        if phase == "early":
            self._refresh_native_history_views()
            self._schedule_history_ui_refresh_step(
                5.2, token, generation, "persisted", started_at,
            )
            return
        if phase == "persisted":
            # FongMi throttles normal History saves for five seconds.  By this
            # point the selected episode can be read back from its database.
            self._refresh_local_follow_progress()
            self._refresh_native_history_views()
            self._refresh_follow_categories()

    def _schedule_native_history_ui_refresh(self):
        # A new playback supersedes pending refreshes from the previous
        # episode.  Timers are tracked by _TaskSupervisor and are cancelled on
        # destroy; the token also prevents stale callbacks after re-init.
        with self._history_context_lock:
            generation = self._cache_generation
        with self._history_ui_refresh_lock:
            self._history_ui_refresh_token += 1
            token = self._history_ui_refresh_token
        self._invalidate_history_snapshot()
        return self._schedule_history_ui_refresh_step(
            1.2, token, generation, "early", time.monotonic(),
        )

    def _refresh_active_detail(self, item):
        try:
            activity = self._current_fongmi_activity()
            if activity is None or not hasattr(activity, "getIntent"):
                return False
            intent = activity.getIntent()
            current_key = str(intent.getStringExtra("key") or "").strip()
            current_id = str(intent.getStringExtra("id") or "").strip()
            site_key = str(getattr(self, "siteKey", "") or "").strip()
            expected_id = str((item or {}).get("source_id") or "").strip()
            if current_id.startswith("atvp_detail:"):
                current_id = current_id[len("atvp_detail:"):]
            if expected_id.startswith("atvp_detail:"):
                expected_id = expected_id[len("atvp_detail:"):]
            if not site_key or current_key != site_key or not expected_id or current_id != expected_id:
                return False
        except Exception:
            return False
        return self._refresh_native_view("detail")

    def _schedule_active_detail_refresh(self, item):
        try:
            self._tasks.start_thread(
                self._refresh_active_detail, args=(dict(item or {}),), name="detail-refresh",
            )
            return True
        except Exception:
            return False

    def _refresh_follow_categories(self):
        direct = self._queue_instantiated_follow_refresh()
        if direct:
            print("[follow-refresh] direct=true fallback=none")
            return True
        with self._follow_refresh_lock:
            self._follow_refresh_generation += 1
            generation = self._follow_refresh_generation
        try:
            self._tasks.start_thread(
                self._refresh_follow_categories_worker, args=(generation,), name="category-refresh",
            )
        except Exception:
            return False
        print("[follow-refresh] direct=false fallback=scheduled")
        return True

    def _refresh_follow_categories_worker(self, generation):
        time.sleep(1.0)
        with self._follow_refresh_lock:
            if generation != self._follow_refresh_generation:
                return
        if not self._refresh_visible_follow_category():
            self._refresh_native_category()

    def _queue_instantiated_follow_refresh(self):
        try:
            from java import dynamic_proxy, jclass
            activity = self._current_fongmi_activity()
            if activity is None or not hasattr(activity, "getSupportFragmentManager"):
                return False
            completed = threading.Event()
            result = {"count": 0}
            with self._fongmi_refresh_task_lock:
                task_class = self._fongmi_refresh_task_class
                if task_class is None:
                    runnable = jclass("java.lang.Runnable")

                    class RefreshTask(dynamic_proxy(runnable)):
                        def __init__(task_self, owner, target_activity, target_result, target_event):
                            super().__init__()
                            task_self.owner = owner
                            task_self.target_activity = target_activity
                            task_self.target_result = target_result
                            task_self.target_event = target_event

                        def run(task_self):
                            try:
                                task_self.target_result["count"] = task_self.owner._refresh_instantiated_follow_fragments(task_self.target_activity)
                            finally:
                                task_self.target_event.set()

                    task_class = self._fongmi_refresh_task_class = RefreshTask
            task = task_class(self, activity, result, completed)
            looper = jclass("android.os.Looper")
            if looper.myLooper() == looper.getMainLooper():
                task.run()
            else:
                handler = jclass("android.os.Handler")(looper.getMainLooper())
                if not handler.post(task):
                    return False
                completed.wait(0.8)
            return result["count"] > 0
        except Exception:
            return False

    @staticmethod
    def _current_fongmi_activity():
        try:
            from java import jclass
            class_cls = jclass("java.lang.Class")
            modifier_cls = jclass("java.lang.reflect.Modifier")
            app_type = class_cls.forName("com.fongmi.android.tv.App")
            activity_type = class_cls.forName("android.app.Activity")
            app = None
            for field in app_type.getDeclaredFields():
                if not modifier_cls.isStatic(field.getModifiers()):
                    continue
                if not app_type.isAssignableFrom(field.getType()):
                    continue
                field.setAccessible(True)
                app = field.get(None)
                if app is not None:
                    break
            if app is None:
                return Spider.ACTIVITY_PROBE_FAILED
            current = app.getClass()
            activity_field_found = False
            while current is not None:
                for field in current.getDeclaredFields():
                    if modifier_cls.isStatic(field.getModifiers()):
                        continue
                    if not activity_type.isAssignableFrom(field.getType()):
                        continue
                    activity_field_found = True
                    field.setAccessible(True)
                    activity = field.get(app)
                    if activity is not None:
                        return activity
                current = current.getSuperclass()
            if not activity_field_found:
                return Spider.ACTIVITY_PROBE_FAILED
        except Exception:
            return Spider.ACTIVITY_PROBE_FAILED
        return None

    @staticmethod
    def _refresh_instantiated_follow_fragments(activity):
        targets = {"follow_updates", "follow_candidates", "follow_sync", "follow_manage"}
        try:
            if hasattr(activity, "isFinishing") and activity.isFinishing():
                return 0
            if hasattr(activity, "isDestroyed") and activity.isDestroyed():
                return 0
            roots = activity.getSupportFragmentManager().getFragments()
        except Exception:
            return 0
        queue = []
        try:
            queue.extend(roots)
        except Exception:
            try:
                queue.extend(roots.get(index) for index in range(roots.size()))
            except Exception:
                return 0
        refreshed = 0
        # TypeFragment keeps typeId in its Bundle even when R8 renames its class and methods.
        for fragment in queue:
            if fragment is None:
                continue
            try:
                arguments_getter = getattr(fragment, "getArguments", None)
                arguments = arguments_getter() if callable(arguments_getter) else None
                type_id = str(arguments.getString("typeId") or "") if arguments is not None else ""
                if not type_id:
                    type_getter = getattr(fragment, "getType", None)
                    item = type_getter() if callable(type_getter) else None
                    type_id = str(item.getTypeId() or "") if item is not None else ""
                if type_id in targets and Spider._invoke_fragment_refresh_listener(fragment):
                    refreshed += 1
                children = fragment.getChildFragmentManager().getFragments()
                try:
                    queue.extend(children)
                except Exception:
                    queue.extend(children.get(index) for index in range(children.size()))
            except Exception:
                continue
        return refreshed

    @staticmethod
    def _invoke_fragment_refresh_listener(fragment):
        try:
            if hasattr(fragment, "isAdded") and not fragment.isAdded():
                return False
            if hasattr(fragment, "getView") and fragment.getView() is None:
                return False
            candidates = []
            interfaces_getter = getattr(fragment.getClass(), "getInterfaces", None)
            if not callable(interfaces_getter):
                return False
            for interface in interfaces_getter():
                for method in interface.getMethods():
                    parameters = method.getParameterTypes()
                    if len(parameters) == 0 and str(method.getReturnType().getName()) == "void":
                        candidates.append(method)
            if len(candidates) == 1:
                method = candidates[0]
                getattr(fragment, str(method.getName()))()
                return True
        except Exception:
            pass
        return Spider._invoke_fongmi_549_r8_refresh(fragment)

    @staticmethod
    def _invoke_fongmi_549_r8_refresh(fragment):
        """Call TypeFragment.onRefresh after FongMi 5.4.9 R8 removes its interface method."""
        try:
            view = fragment.getView()
            if view is None or str(view.getClass().getName()) != (
                "androidx.swiperefreshlayout.widget.SwipeRefreshLayout"
            ):
                return False
            methods = [
                method for method in fragment.getClass().getDeclaredMethods()
                if str(method.getName()) == "X"
                and len(method.getParameterTypes()) == 0
                and str(method.getReturnType().getName()) == "void"
            ]
            refresh = getattr(fragment, "X", None)
            if len(methods) != 1 or not callable(refresh):
                return False
            refresh()
            print("[follow-refresh] fongmi-5.4.9-r8 method=X")
            return True
        except Exception:
            return False

    def _refresh_visible_follow_category(self):
        try:
            from java import jclass
            activity = self._current_fongmi_activity()
            if activity is None or not hasattr(activity, "findViewById") or not hasattr(activity, "getIntent"):
                return False
            resource_ids = jclass("com.fongmi.android.tv.R$id")
            pager = activity.findViewById(resource_ids.pager)
            result = activity.getIntent().getParcelableExtra("result")
            if pager is None or result is None:
                return False
            current = result.getTypes().get(pager.getCurrentItem())
            type_id = str(current.getTypeId() or "") if current is not None else ""
            if type_id not in ("follow_updates", "follow_candidates", "follow_sync", "follow_manage"):
                return False
            return self._refresh_native_category()
        except Exception:
            return False

    def _match_douban_tv_to_tmdb(self, douban):
        titles = []
        for value in (douban.get("title"), douban.get("original_title")):
            text = str(value or "").strip()
            if text and text not in titles:
                titles.append(text)
        if not titles:
            raise RuntimeError("豆瓣条目缺少标题")
        aliases = {self._normalize_media_title(value) for value in titles} - {""}
        year = self._positive_int(douban.get("year"), 0)
        candidates = {}
        for query in titles:
            data = self._tmdb_api("/search/tv", {"query": query, "page": 1, "include_adult": "false"}, self.detail_cache_ttl)
            for row in data.get("results") or []:
                tmdb_id = self._positive_int(row.get("id"), 0)
                if tmdb_id:
                    candidates[tmdb_id] = row
        ranked = []
        for row in candidates.values():
            names = {
                self._normalize_media_title(row.get("name")),
                self._normalize_media_title(row.get("original_name")),
            } - {""}
            if aliases.intersection(names):
                score = 100
            elif any(min(len(left), len(right)) >= 2 and (left in right or right in left) for left in aliases for right in names):
                score = 55
            else:
                score = 0
            tmdb_year = self._positive_int(str(row.get("first_air_date") or "")[:4], 0)
            if year and tmdb_year:
                difference = abs(year - tmdb_year)
                score += 25 if difference == 0 else (10 if difference == 1 else -30)
            ranked.append((score, float(row.get("popularity") or 0), row))
        ranked.sort(key=lambda value: (value[0], value[1]), reverse=True)
        if not ranked or ranked[0][0] < 90:
            raise RuntimeError("未找到可信的TMDB剧集匹配")
        if len(ranked) > 1 and ranked[0][0] == ranked[1][0]:
            raise RuntimeError("存在多个同名TMDB剧集，请改用TMDB追更管理")
        return ranked[0][2]

    def _attach_douban_to_tmdb_item(self, item, tmdb):
        if str(item.get("douban_id") or ""):
            return item
        try:
            matched = self._match_tmdb_tv_to_douban(tmdb)
            subject_id = self._subject_id(matched.get("id"))
            if not subject_id:
                return item
            output = dict(item)
            output["douban_id"] = subject_id
            output["douban_title"] = str(matched.get("title") or "")
            output = self._merge_follow_title_aliases(
                output,
                (matched.get("title"), matched.get("original_title")),
            )
            return output
        except Exception:
            return item

    def _match_tmdb_tv_to_douban(self, tmdb):
        titles = []
        for value in (tmdb.get("name"), tmdb.get("original_name")):
            text = str(value or "").strip()
            if text and text not in titles:
                titles.append(text)
        if not titles:
            raise RuntimeError("TMDB条目缺少标题")
        aliases = {self._normalize_media_title(value) for value in titles} - {""}
        year = self._positive_int(str(tmdb.get("first_air_date") or "")[:4], 0)
        candidates = {}
        for query in titles:
            data = self._get_json(
                self.API + "/search",
                params={"q": query, "start": 0, "count": 20},
                ttl=self.detail_cache_ttl,
            )
            subjects = data.get("subjects") if isinstance(data.get("subjects"), dict) else {}
            for row in subjects.get("items") or []:
                if str(row.get("target_type") or "") != "tv":
                    continue
                target = row.get("target") if isinstance(row.get("target"), dict) else {}
                subject_id = self._subject_id(target.get("id") or row.get("target_id"))
                if subject_id:
                    candidate = dict(target)
                    candidate["id"] = subject_id
                    candidates[subject_id] = candidate
        ranked = []
        for row in candidates.values():
            name = self._normalize_media_title(row.get("title"))
            if name in aliases:
                score = 100
            elif name and any(min(len(name), len(alias)) >= 2 and (name in alias or alias in name) for alias in aliases):
                score = 60
            else:
                score = 0
            douban_year = self._positive_int(row.get("year"), 0)
            if year and douban_year:
                difference = abs(year - douban_year)
                score += 25 if difference == 0 else (10 if difference == 1 else -30)
            ranked.append((score, row))
        ranked.sort(key=lambda value: value[0], reverse=True)
        if not ranked or ranked[0][0] < 85:
            raise RuntimeError("未找到可信的豆瓣剧集匹配")
        if len(ranked) > 1 and ranked[0][0] == ranked[1][0]:
            raise RuntimeError("存在多个同名豆瓣剧集")
        return ranked[0][1]

    def _load_follow_state(self, force=False):
        with self._follow_state_load_lock:
            return self._load_follow_state_locked(force)

    def _load_follow_state_locked(self, force=False):
        if self._follow_state_loaded and not force:
            return True
        getter = getattr(self, "getCache", None)
        if not callable(getter):
            return bool(self._follow_state_loaded)
        with self._follow_enrich_lock:
            self._follow_state_loaded = False
        state = None
        cache_known = False
        persisted = False
        if callable(getter):
            try:
                value = getter(self.FOLLOW_CACHE_KEY)
                if value is None:
                    cache_known = True
                elif self._valid_follow_state_payload(value):
                    state = value
                    cache_known = True
                    persisted = True
            except Exception:
                cache_known = False
        if not cache_known:
            loopback_state, loopback_origin = self._load_follow_state_from_loopback()
            if loopback_state is not None:
                state = loopback_state
                cache_known = True
                persisted = True
                if loopback_origin != self._follow_cache_origin:
                    print("[follow-cache] loopback=%s items=%s" % (
                        loopback_origin.rsplit(":", 1)[-1], len(loopback_state.get("items") or {}),
                    ))
                self._follow_cache_origin = loopback_origin
        if not cache_known:
            return False
        if state is None:
            state = {"version": self.FOLLOW_STATE_VERSION, "items": {}}
        state_version = self._positive_int(state.get("version"), 1)
        items = dict(state.get("items") or {})
        migrated = persisted and state_version < self.FOLLOW_STATE_VERSION
        if migrated:
            for key, value in list(items.items()):
                if not isinstance(value, dict):
                    continue
                item = dict(value)
                seen = str(item.get("seen_episode") or "")
                latest = str(item.get("latest_episode") or "")
                if "tracked_episode" not in item:
                    item["tracked_episode"] = latest or seen
                item["seen_episode"] = ""
                item["seen_source"] = ""
                items[key] = item
        for key, value in list(items.items()):
            if not isinstance(value, dict):
                continue
            item = self._sanitize_follow_persisted_item(
                self._compact_follow_title_aliases(value)
            )
            if item != value:
                items[key] = item
                migrated = True
        for tmdb_id in self.follow_tv_ids:
            key = str(tmdb_id)
            items.setdefault(key, {"tmdb_id": tmdb_id, "title": "TMDB剧集 " + key, "seen_episode": "", "tracked_episode": ""})
        with self._follow_enrich_lock:
            self._follow_memory = {
                "version": self.FOLLOW_STATE_VERSION,
                "updated_at": int(time.time()),
                "items": items,
            }
            self._follow_state_loaded = True
        if migrated:
            self._persist_follow_state(self._follow_memory)
        return True

    def _valid_follow_state_payload(self, value):
        if not isinstance(value, dict) or not isinstance(value.get("items"), dict):
            return False
        items = value.get("items") or {}
        if len(items) > self.FOLLOW_STATE_ITEM_LIMIT:
            return False
        try:
            if _history_utf8_size(json.dumps(value, ensure_ascii=False, separators=(",", ":"))) > self.FOLLOW_STATE_MAX_BYTES:
                return False
        except Exception:
            return False
        for item in items.values():
            if not isinstance(item, dict):
                continue
            try:
                if _history_utf8_size(json.dumps(item, ensure_ascii=False, separators=(",", ":"))) > self.FOLLOW_STATE_ITEM_MAX_BYTES:
                    return False
            except Exception:
                return False
        return True

    def _load_follow_state_from_loopback(self):
        origins = []
        if self._follow_cache_origin:
            origins.append(self._follow_cache_origin)
        try:
            origins.append(self._fongmi_local_origin())
        except Exception:
            pass
        session = requests.Session()
        session.trust_env = False
        checked = set()
        try:
            for origin in origins:
                if origin in checked:
                    continue
                checked.add(origin)
                try:
                    response = session.get(
                        origin + "/cache",
                        params={"do": "get", "key": self.FOLLOW_CACHE_KEY},
                        timeout=0.15,
                        stream=True,
                    )
                    if response.status_code != 200:
                        response.close()
                        continue
                    value = _read_bounded_json_shared(
                        response, "FongMi 追更缓存", self.FOLLOW_STATE_MAX_BYTES,
                    )
                    if not self._valid_follow_state_payload(value):
                        continue
                    return value, origin
                except Exception:
                    continue
        finally:
            session.close()
        return (None, "")

    def _persist_follow_state(self, state):
        return self._follow_repository.persist(state)

    def _save_follow_state(self, items):
        sanitized_items = {}
        for key, value in dict(items or {}).items():
            if isinstance(value, dict):
                sanitized_items[str(key)] = self._sanitize_follow_persisted_item(value)
        state = {
            "version": self.FOLLOW_STATE_VERSION,
            "updated_at": int(time.time()),
            "items": sanitized_items,
        }
        with self._follow_enrich_lock:
            if not self._follow_state_loaded:
                raise RuntimeError("追更状态尚未成功读取，已暂停修改")
            if not self._persist_follow_state(state):
                raise RuntimeError("追更状态未能持久保存")
            self._follow_memory = state
            self._follow_state_loaded = True
        return True

    def _refresh_follow_item(self, item):
        tmdb_id = self._positive_int(item.get("tmdb_id"), 0)
        if not tmdb_id:
            return item
        data = self._tmdb_api("/tv/%s" % tmdb_id, {}, self.follow_check_ttl, allow_stale=False)
        refreshed = self._follow_item_from_tmdb(data, item)
        if not self._follow_title_alias_values(refreshed, include_primary=False):
            refreshed = self._attach_tmdb_title_aliases(refreshed, data)
        return refreshed

    def _follow_item_from_tmdb(self, data, previous=None):
        previous = previous or {}
        latest = self._aired_episode(data.get("last_episode_to_air"))
        upcoming = data.get("next_episode_to_air") if isinstance(data.get("next_episode_to_air"), dict) else {}
        title = str(data.get("name") or data.get("original_name") or previous.get("title") or "")
        item = dict(previous)
        item.update({
            "tmdb_id": self._positive_int(data.get("id"), self._positive_int(previous.get("tmdb_id"), 0)),
            "title": title,
            "original_title": str(data.get("original_name") or ""),
            "pic": self._tmdb_image(data.get("poster_path") or data.get("backdrop_path")) or str(previous.get("pic") or ""),
            "year": str(data.get("first_air_date") or "")[:4],
            "status": str(data.get("status") or ""),
            "season_count": self._positive_int(
                data.get("number_of_seasons"), self._positive_int(previous.get("season_count"), 0),
            ),
            "latest_episode": self._episode_key(latest),
            "latest_air_date": str(latest.get("air_date") or ""),
            "latest_episode_name": str(latest.get("name") or ""),
            "next_episode": self._episode_key(upcoming),
            "next_air_date": str(upcoming.get("air_date") or ""),
            "last_checked": int(time.time()),
        })
        if "seen_episode" not in item:
            item["seen_episode"] = ""
        if "tracked_episode" not in item or (previous.get("pending_metadata") and not item.get("tracked_episode")):
            item["tracked_episode"] = item["latest_episode"]
        return item

    @staticmethod
    def _follow_title_alias_values(item, include_primary=True):
        if not isinstance(item, dict):
            return []
        values = []
        if include_primary:
            values.append(item.get("title"))
        aliases = item.get("title_aliases")
        if isinstance(aliases, (list, tuple, set)):
            values.extend(aliases)
        elif aliases:
            values.extend(str(aliases).split("\n"))
        if include_primary:
            values.append(item.get("original_title"))
        output = []
        seen = set()
        for value in values:
            text = str(value or "").strip()
            normalized = Spider._normalize_media_title(text)
            if text and normalized and normalized not in seen:
                seen.add(normalized)
                output.append(text)
        return output

    @staticmethod
    def _compact_follow_title_aliases(item):
        output = dict(item or {})
        aliases = Spider._follow_title_alias_values(output, include_primary=False)
        if not aliases:
            return output
        chinese = [value for value in aliases if re.search(r"[\u3400-\u9fff]", value)]
        compact = [
            _history_clip_text(value, 1024)
            for value in (chinese if chinese else aliases)[:6 if chinese else 4]
        ]
        if compact:
            output["title_aliases"] = compact
        else:
            output.pop("title_aliases", None)
        return output

    def _sanitize_follow_persisted_item(self, item):
        output = dict(item or {})
        for key, limit in self.FOLLOW_STATE_TEXT_FIELD_LIMITS.items():
            if key in output and output.get(key) is not None:
                output[key] = _history_clip_text(output.get(key), limit)
        resource_id = str(output.get("alist_vod_id") or "").strip()
        binding_mode = str(output.get("alist_resource_mode") or "vod").strip().lower() or "vod"
        if resource_id and (
                binding_mode not in self.RESOURCE_SEARCH_MODES
                or not self._resource_id_persistable(resource_id, binding_mode)):
            output.pop("alist_vod_id", None)
            output.pop("alist_resource_mode", None)
            output.pop("alist_resource_provider", None)
            output.pop("binding_updated_at", None)
            resource_id = ""
        binding_provider = self._resource_provider_key(output.get("alist_resource_provider")) if resource_id else ""
        if binding_provider:
            output["alist_resource_provider"] = binding_provider
        else:
            output.pop("alist_resource_provider", None)

        route = output.get("last_play_route")
        if not isinstance(route, dict):
            output.pop("last_play_route", None)
            return output
        resource_mode = str(route.get("resourceMode") or "vod").strip().lower() or "vod"
        if resource_mode not in self.RESOURCE_SEARCH_MODES:
            resource_mode = ""
        route_resource_id = str(route.get("resourceId") or "").strip()
        if route_resource_id and (
                not self._resource_id_persistable(route_resource_id, resource_mode)):
            route_resource_id = ""
        play_id = str(route.get("playId") or "").strip()
        decoded_play_id = self._unquote_limited(play_id)
        if (
                len(play_id) > self.FOLLOWPLAY_ROUTE_FIELD_MAX_LENGTH
                or not re.match(r"^(?:\d+@[^\s?#]+|\d+-\d+|\d+)$", play_id)
                or self._contains_url_reference(decoded_play_id.split("@", 1)[-1])):
            play_id = ""
        route_name = str(route.get("name") or "").strip()[:256]
        if self._contains_url_reference(route_name):
            route_name = ""
        if not play_id and not route_resource_id:
            output.pop("last_play_route", None)
            return output
        quality = route.get("quality") if isinstance(route.get("quality"), dict) else {}
        route_provider = self._resource_provider_key(route.get("resourceProvider"))
        sanitized_route = {
            "version": 1,
            "backend": str(route.get("backend") or "")[:64],
            "resourceId": route_resource_id,
            "resourceMode": resource_mode,
            "playId": play_id,
            "season": self._positive_int(route.get("season"), 0),
            "episode": self._positive_int(route.get("episode"), 0),
            "name": route_name,
            "quality": {
                "height": self._positive_int(quality.get("height"), 0),
                "codec": str(quality.get("codec") or "")[:16],
                "subtitle": quality.get("subtitle") if isinstance(quality.get("subtitle"), bool) else None,
                "startupMs": self._positive_int(quality.get("startupMs"), 0),
            },
            "updatedAt": self._positive_int(route.get("updatedAt"), 0),
        }
        if route_provider:
            sanitized_route["resourceProvider"] = route_provider
        output["last_play_route"] = sanitized_route
        return output

    def _merge_follow_title_aliases(self, item, values):
        output = dict(item or {})
        merged = self._follow_title_alias_values(output, include_primary=False)
        merged.extend(values or [])
        aliases = []
        primary = {
            self._normalize_media_title(output.get("title")),
            self._normalize_media_title(output.get("original_title")),
        } - {""}
        seen = set(primary)
        for value in merged:
            text = str(value or "").strip()
            normalized = self._normalize_media_title(text)
            if text and normalized and normalized not in seen:
                seen.add(normalized)
                aliases.append(text)
        if aliases:
            output["title_aliases"] = aliases[:12]
        return output

    def _attach_tmdb_title_aliases(self, item, tmdb=None):
        tmdb_id = self._positive_int((tmdb or {}).get("id"), self._positive_int(item.get("tmdb_id"), 0))
        if not tmdb_id:
            return item
        output = dict(item or {})
        try:
            payload = self._tmdb_api(
                "/tv/%s/alternative_titles" % tmdb_id,
                {},
                self.detail_cache_ttl,
            )
        except Exception:
            output["title_aliases_checked_at"] = int(time.time())
            return output
        preferred_regions = {"CN", "HK", "TW", "SG"}
        preferred = []
        fallback = []
        for row in payload.get("results") or []:
            if not isinstance(row, dict):
                continue
            title = str(row.get("title") or "").strip()
            title_type = str(row.get("type") or "").strip().lower()
            if not title or title_type not in ("", "alternative title", "working title"):
                continue
            target = preferred if str(row.get("iso_3166_1") or "").upper() in preferred_regions else fallback
            target.append(title)
        output = self._merge_follow_title_aliases(output, preferred if preferred else fallback[:4])
        output = self._compact_follow_title_aliases(output)
        output["title_aliases_checked_at"] = int(time.time())
        return output

    def _follow_card(self, item, action_mode="", history=None):
        tmdb_id = self._positive_int(item.get("tmdb_id"), 0)
        title = str(item.get("title") or ("TMDB剧集 %s" % tmdb_id))
        vod_id = "tmdb:tv:%s" % tmdb_id if tmdb_id else str(
            item.get("douban_id") or self.ERROR_PREFIX + quote(title, safe="")
        )
        card = {
            "vod_id": vod_id,
            "vod_name": title,
            "vod_pic": str(item.get("pic") or ""),
            "vod_remarks": self._follow_remark(item, history),
        }
        if action_mode == "seen" and tmdb_id:
            card["action"] = self.FOLLOW_SEEN_PREFIX + str(tmdb_id)
            card["vod_remarks"] = "待确认标记已看 · " + card["vod_remarks"]
        elif action_mode == "remove" and tmdb_id:
            card["action"] = self.FOLLOW_REMOVE_PREFIX + str(tmdb_id)
            card["vod_remarks"] = "待确认取消追更 · " + card["vod_remarks"]
        return card

    def _follow_remark(self, item, history=None):
        if item.get("pending_metadata"):
            return "已加入追更 · 分集资料后台更新中"
        if item.get("enrich_error"):
            return "已加入追更 · 资料更新失败：" + str(item.get("enrich_error") or "未知错误")
        error = str(item.get("check_error") or "")
        if error:
            remark = "检查失败 · " + error
            return self._append_follow_progress(remark, item, history)
        latest = str(item.get("latest_episode") or "")
        seen = self._history_effective_seen(item, history)
        if self._has_follow_update(item, history):
            latest_rank = self._episode_rank(latest)
            baseline = self._follow_update_baseline(item, history)
            baseline_rank = self._episode_rank(baseline)
            if latest[:3] == baseline[:3] and latest_rank > baseline_rank:
                remark = "有 %s 集更新 · 当前更新至 %s" % (latest_rank - baseline_rank, latest)
                return self._append_follow_progress(remark, item, history)
            return self._append_follow_progress("有新季/新集 · 当前更新至 " + latest, item, history)
        next_date = str(item.get("next_air_date") or "")
        if seen and next_date:
            remark = "已看到 %s · 下一级更新时间 %s" % (seen, next_date)
            return self._append_follow_progress(remark, item, history)
        if not seen and latest:
            remark = "已追更 · 当前更新至 %s%s" % (
                latest,
                (" · 下一级更新时间 " + next_date) if next_date else "",
            )
            return self._append_follow_progress(remark, item, history)
        status = str(item.get("status") or "")
        remark = ("已看到 " + seen) if seen else "已追更"
        if status:
            remark += " · " + status
        return self._append_follow_progress(remark, item, history)

    def _atvp_history_snapshot(self, nonblocking=False):
        if not self._ensure_atvp_connection():
            return []
        cache_key = "atvp-history-snapshot"
        cached = self._cache_get(cache_key, self.atvp_history_ttl)
        if isinstance(cached, list):
            return cached
        stale = self._cache_get(cache_key, self.atvp_history_ttl, allow_expired=True)
        if nonblocking:
            # Dynamic/update pages only need the cloud snapshot.  Do not run
            # the full local export/merge/import cycle here; that path is
            # reserved for the explicit "立即同步 History" action.
            self._schedule_atvp_history_refresh(cache_key, lightweight=True)
            return stale if isinstance(stale, list) else []
        try:
            histories = self._atvp_fetch_history()
            self._cache_set(cache_key, histories)
            return histories
        except Exception:
            return stale if isinstance(stale, list) else []

    def _trigger_history_sync_now(self):
        if not self._alist_tvbox_plugin or not self._ensure_atvp_connection():
            return False
        cache_key = "atvp-history-snapshot"
        self._invalidate_history_snapshot()
        return self._schedule_atvp_history_refresh(cache_key)

    def _playback_sync_key(self, parsed):
        if not isinstance(parsed, dict):
            return ""
        identity = str(parsed.get("tmdbId") or parsed.get("sourceId") or "").strip()
        resource_id = str(parsed.get("resourceId") or "").strip()
        season = self._positive_int(parsed.get("season"), 0)
        episode = self._positive_int(parsed.get("episode"), 0)
        if not identity or not resource_id or season <= 0 or episode <= 0:
            return ""
        raw = "%s|%s|%s|%s|%s" % (
            identity, resource_id, str(parsed.get("resourceMode") or "vod"), season, episode,
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _register_playback_sync_window(self, parsed):
        """Delay History sync until a meaningful playback window has elapsed."""
        if not self._alist_tvbox_plugin or not isinstance(parsed, dict):
            return False
        key = self._playback_sync_key(parsed)
        if not key:
            return False
        marker = {
            "owner": object(),
            "started_at": time.time(),
            "tmdb_id": self._positive_int(parsed.get("tmdbId"), 0),
            "source_id": str(parsed.get("sourceId") or "").strip(),
            "title": str(parsed.get("name") or "").strip(),
            "resource_id": str(parsed.get("resourceId") or "").strip(),
            "season": self._positive_int(parsed.get("season"), 0),
            "episode": self._positive_int(parsed.get("episode"), 0),
        }
        with self._playback_sync_lock:
            old = self._playback_sync_pending.get(key)
            if old and float(old.get("started_at") or 0) >= marker["started_at"] - 5:
                return False
            self._playback_sync_pending[key] = marker
        owner = marker["owner"]
        if not self._schedule_playback_sync_check(
                key, self.PLAYBACK_SYNC_MIN_SECONDS, expected_owner=owner):
            with self._playback_sync_lock:
                current = self._playback_sync_pending.get(key)
                if isinstance(current, dict) and current.get("owner") is owner:
                    self._playback_sync_pending.pop(key, None)
            return False
        return True

    def _schedule_playback_sync_check(self, key, delay, expected_owner=None):
        try:
            wait = max(1.0, float(delay))
        except Exception:
            wait = float(self.PLAYBACK_SYNC_RETRY_SECONDS)
        token = object()
        timer = threading.Timer(wait, self._playback_sync_check, args=(key, token))
        timer.daemon = True
        try:
            self._tasks.track_timer(timer)
        except Exception:
            return False
        with self._playback_sync_lock:
            if expected_owner is not None:
                current = self._playback_sync_pending.get(key)
                if not isinstance(current, dict) or current.get("owner") is not expected_owner:
                    self._tasks.forget_timer(timer)
                    return False
            previous = self._playback_sync_timers.get(key)
            if previous is not None:
                try:
                    previous.cancel()
                except Exception:
                    pass
                self._tasks.forget_timer(previous)
            self._playback_sync_timers[key] = timer
            self._playback_sync_tokens[key] = token
        try:
            timer.start()
        except Exception:
            self._tasks.forget_timer(timer)
            with self._playback_sync_lock:
                if self._playback_sync_timers.get(key) is timer:
                    self._playback_sync_timers.pop(key, None)
                    self._playback_sync_tokens.pop(key, None)
            return False
        return True

    def _playback_activity_active(self):
        try:
            activity = self._current_fongmi_activity()
            if activity is self.ACTIVITY_PROBE_FAILED:
                return True
            if activity is None:
                return False
            name = str(activity.getClass().getName() or "").lower()
            return any(marker in name for marker in (
                "player", "videoactivity", "playbackactivity", "videoplay", "vodplay", "playactivity",
            ))
        except Exception:
            # A failed activity probe must not cause a sync while playback may
            # still be active; retry after the short exit window instead.
            return True

    def _playback_sync_marker_current(self, key, marker):
        owner = marker.get("owner") if isinstance(marker, dict) else None
        with self._playback_sync_lock:
            current = self._playback_sync_pending.get(key)
            return bool(owner is not None and isinstance(current, dict) and current.get("owner") is owner)

    def _playback_sync_check(self, key, token=None):
        self._diagnostic_event("playback_sync.check", key=key, token=token)
        with self._playback_sync_lock:
            if key in self._playback_sync_inflight:
                return False
            current_token = self._playback_sync_tokens.get(key)
            if token is not None and current_token is not token:
                return False
            marker = dict(self._playback_sync_pending.get(key) or {})
            completed_timer = self._playback_sync_timers.pop(key, None)
            self._playback_sync_tokens.pop(key, None)
            if marker:
                self._playback_sync_inflight[key] = marker.get("owner")
            inflight_owner = marker.get("owner") if marker else None
        self._tasks.forget_timer(completed_timer)
        if not marker:
            return False
        try:
            return self._playback_sync_check_owned(key, marker)
        except Exception as exc:
            self._diagnostic_event("playback_sync.error", "ERROR", exc=exc, key=key)
            raise
        finally:
            with self._playback_sync_lock:
                if self._playback_sync_inflight.get(key) is inflight_owner:
                    self._playback_sync_inflight.pop(key, None)

    def _playback_sync_check_owned(self, key, marker):
        if not self._playback_sync_marker_current(key, marker):
            return False
        elapsed = time.time() - float(marker.get("started_at") or 0)
        if elapsed < self.PLAYBACK_SYNC_MIN_SECONDS:
            return self._schedule_playback_sync_check(
                key, self.PLAYBACK_SYNC_MIN_SECONDS - elapsed, expected_owner=marker.get("owner"),
            )
        if self._playback_activity_active():
            return self._schedule_playback_sync_check(
                key, self.PLAYBACK_SYNC_RETRY_SECONDS, expected_owner=marker.get("owner"),
            )
        try:
            rows = self._capture_native_history()
            item = {
                "tmdb_id": marker.get("tmdb_id"),
                "source_id": marker.get("source_id"),
                "title": marker.get("title"),
                "trackingSeason": marker.get("season"),
                "alist_vod_id": marker.get("resource_id"),
            }
            history = self._atvp_history_for_item(item, rows)
            position = self._positive_int((history or {}).get("position"), 0)
            if not history or position < self.PLAYBACK_SYNC_MIN_SECONDS * 1000:
                return self._schedule_playback_sync_check(
                    key, self.PLAYBACK_SYNC_RETRY_SECONDS, expected_owner=marker.get("owner"),
                )
        except Exception:
            return self._schedule_playback_sync_check(
                key, self.PLAYBACK_SYNC_RETRY_SECONDS, expected_owner=marker.get("owner"),
            )
        # Linearize the final ownership check with dispatch. A new playback
        # window cannot be installed between validation and the History trigger.
        with self._playback_sync_lock:
            current = self._playback_sync_pending.get(key)
            if not isinstance(current, dict) or current.get("owner") is not marker.get("owner"):
                return False
            if self._playback_activity_active():
                return self._schedule_playback_sync_check(
                    key, self.PLAYBACK_SYNC_RETRY_SECONDS, expected_owner=marker.get("owner"),
                )
            triggered = self._trigger_history_sync_now()
            if triggered:
                current = self._playback_sync_pending.get(key)
                if isinstance(current, dict) and current.get("owner") is marker.get("owner"):
                    self._playback_sync_pending.pop(key, None)
                return True
            current = self._playback_sync_pending.get(key)
            if isinstance(current, dict) and current.get("owner") is marker.get("owner"):
                return self._schedule_playback_sync_check(
                    key, self.PLAYBACK_SYNC_RETRY_SECONDS, expected_owner=marker.get("owner"),
                )
            return False

    def _flush_playback_sync_on_navigation(self):
        with self._playback_sync_lock:
            entries = []
            for key in list(self._playback_sync_pending):
                if key in self._playback_sync_inflight:
                    continue
                timer = self._playback_sync_timers.get(key)
                token = self._playback_sync_tokens.get(key)
                if timer is not None:
                    try:
                        timer.cancel()
                    except Exception:
                        pass
                entries.append((key, token))
        for key, token in entries:
            try:
                self._tasks.start_thread(
                    self._playback_sync_check, args=(key, token), name="playback-sync-flush",
                )
            except Exception:
                continue

    def _schedule_atvp_history_refresh(self, cache_key, lightweight=False):
        lightweight = bool(lightweight)
        job_kind = "snapshot-background" if lightweight else "sync-background"
        job_owner = object()
        with self._atvp_job_lock:
            if "sync" in self._atvp_jobs or "sync-background" in self._atvp_jobs:
                return False
            if job_kind in self._atvp_jobs:
                return False
            self._atvp_jobs.add(job_kind)
        with self._cache_lock:
            if cache_key in self._refreshing_cache_keys:
                with self._atvp_job_lock:
                    self._atvp_jobs.discard(job_kind)
                return False
            self._refreshing_cache_keys[cache_key] = job_owner
            generation = self._cache_generation
        if not lightweight:
            self._set_atvp_status(
                "sync", "running", "History 后台同步中 · %s" % self._history_sync_mode_label(),
                persist=False,
            )

        def worker():
            try:
                with self._history_context_lock:
                    self._require_history_generation(generation)
                    request_revision = self._history_snapshot_revision
                    if not lightweight:
                        self._persist_atvp_status()
                if lightweight:
                    started_at = time.monotonic()
                    self._diagnostic_event("history_snapshot.start")
                    histories = self._atvp_fetch_history()
                    with self._history_sync_lock:
                        with self._history_context_lock:
                            self._require_history_generation(generation)
                            if request_revision != self._history_snapshot_revision:
                                raise _HistorySyncCancelled(
                                    "History 轻量快照已被更新发布失效"
                                )
                            with self._atvp_job_lock:
                                if "sync" in self._atvp_jobs or "sync-background" in self._atvp_jobs:
                                    raise _HistorySyncCancelled(
                                        "History 轻量快照已让位于完整同步"
                                    )
                            self._cache_set(cache_key, histories)
                            self._clear_cached_failure(cache_key)
                            changed_items = []
                            progress = self._reconcile_follow_histories(histories, changed_items)
                            self._require_history_generation(generation)
                            if changed_items:
                                self._schedule_entry_resource_preheat(changed_items)
                    self._diagnostic_event(
                        "history_snapshot.finish",
                        count=len(histories),
                        progress=progress,
                        preheat=len(changed_items),
                        duration_ms=int((time.monotonic() - started_at) * 1000),
                    )
                    self._refresh_follow_categories()
                else:
                    with self._history_sync_lock:
                        result = self._history_coordinator.sync_once(expected_generation=generation)
                    with self._history_context_lock:
                        self._require_history_generation(generation)
                        self._history_snapshot_revision += 1
                        self._apply_history_sync_result(cache_key, result)
                        self._clear_cached_failure(cache_key)
                        state = "failed" if result["errors"] else "done"
                        self._set_atvp_status(state=state, kind="sync", message=self._history_sync_message(result))
                        self._refresh_follow_categories()
            except _HistorySyncCancelled as exc:
                self._diagnostic_event(
                    "history_snapshot.cancelled" if lightweight else "history_sync.cancelled",
                    "INFO", reason=self._short_error(exc),
                )
            except Exception as exc:
                with self._history_context_lock:
                    if self._history_generation_active(generation):
                        self._remember_failure(cache_key, exc)
                        if lightweight:
                            self._diagnostic_event("history_snapshot.error", "WARN", exc=exc)
                        else:
                            self._set_atvp_status(
                                "sync", "failed", "History 后台同步失败：%s" % self._short_error(exc),
                            )
                        self._refresh_follow_categories()
            finally:
                with self._cache_lock:
                    if self._refreshing_cache_keys.get(cache_key) is job_owner:
                        self._refreshing_cache_keys.pop(cache_key, None)
                with self._atvp_job_lock:
                    self._atvp_jobs.discard(job_kind)

        try:
            self._tasks.start_thread(worker, name="history-sync")
        except Exception as exc:
            with self._cache_lock:
                if self._refreshing_cache_keys.get(cache_key) is job_owner:
                    self._refreshing_cache_keys.pop(cache_key, None)
            with self._atvp_job_lock:
                self._atvp_jobs.discard(job_kind)
            if not lightweight:
                self._set_atvp_status(
                    "sync", "failed", "History 后台同步启动失败：%s" % self._short_error(exc),
                )
            return False
        return True

    @staticmethod
    def _utf8_size(value):
        return _history_utf8_size(value)

    @classmethod
    def _normalize_history_rows(cls, rows):
        return _normalize_history_rows_shared(rows)

    def _atvp_fetch_history(self):
        return self._history_coordinator.fetch()

    def _history_write_enabled(self):
        return bool(self.history_username and self.history_password)

    def _history_generation_active(self, expected_generation):
        if expected_generation is None:
            return True
        with self._cache_lock:
            return expected_generation == self._cache_generation

    def _require_history_generation(self, expected_generation):
        if not self._history_generation_active(expected_generation):
            raise _HistorySyncCancelled("History 同步已因配置更新而取消")

    def _history_sync_mode_label(self):
        if self._history_write_enabled():
            return "双向"
        if bool(self.history_username) != bool(self.history_password):
            return "只读（写入账号不完整）"
        return "只读"

    def _sync_history_once(self, expected_generation=None):
        started_at = time.monotonic()
        self._diagnostic_event("history_sync.start", generation=expected_generation)
        errors = []
        try:
            with self._history_context_lock:
                self._require_history_generation(expected_generation)
                self._diagnostic_event("history_sync.local_start")
                local_rows = self._capture_native_history()
                self._diagnostic_event("history_sync.local_finish", count=len(local_rows))
        except _HistorySyncCancelled:
            raise
        except Exception as exc:
            local_rows = []
            errors.append(("本机History读取", self._short_error(exc)))
            self._diagnostic_event("history_sync.local_read", "WARN", exc=exc)
        cloud_available = False
        try:
            with self._history_context_lock:
                self._require_history_generation(expected_generation)
                self._diagnostic_event("history_sync.cloud_start")
                cloud_rows = self._atvp_fetch_history()
                cloud_available = True
                self._diagnostic_event("history_sync.cloud_finish", count=len(cloud_rows))
        except _HistorySyncCancelled:
            raise
        except Exception as exc:
            with self._history_context_lock:
                self._require_history_generation(expected_generation)
                stale = self._cache_get(
                    "atvp-history-snapshot", self.atvp_history_ttl, allow_expired=True,
                )
            cloud_rows = stale if isinstance(stale, list) else []
            errors.append(("云端History读取", self._short_error(exc)))
            self._diagnostic_event("history_sync.cloud_read", "WARN", exc=exc)
        merged, uploads = self._merge_native_history(local_rows, cloud_rows)
        self._diagnostic_event(
            "history_sync.merge_finish", merged=len(merged), uploads=len(uploads),
        )
        permitted_uploads = []
        upload_blocked = 0
        uploaded = 0
        try:
            # Keep policy selection and the outbound POST in one serial section.
            # Once a toggle returns, no older policy snapshot can upload afterward.
            with self._history_context_lock:
                self._require_history_generation(expected_generation)
                permitted_uploads = self._history_share_uploads(uploads)
                upload_blocked = max(0, len(uploads) - len(permitted_uploads))
                if cloud_available and permitted_uploads and self._history_write_enabled():
                    self._diagnostic_event(
                        "history_sync.upload_start", count=len(permitted_uploads),
                    )
                    self._atvp_history_push(permitted_uploads)
                    uploaded = len(permitted_uploads)
                    self._diagnostic_event("history_sync.upload_finish", count=uploaded)
        except _HistorySyncCancelled:
            raise
        except Exception as exc:
            errors.append(("云端History写入", self._short_error(exc)))
            self._diagnostic_event("history_sync.cloud_write", "WARN", exc=exc)
        # Avoid a second Java/HTTP History export when the cloud snapshot has
        # no candidate rows to import.  Keep the race guard for the only case
        # where it matters: a cloud row appears newer than the first local
        # snapshot and could otherwise overwrite playback that just finished.
        import_rows = self._history_import_rows(merged, local_rows)
        if import_rows:
            try:
                latest_local_rows = self._capture_native_history()
                import_rows = self._history_import_rows(merged, latest_local_rows)
                self._diagnostic_event(
                    "history_sync.local_reread", count=len(latest_local_rows),
                )
            except Exception as exc:
                self._diagnostic_event("history_sync.local_reread", "WARN", exc=exc)
            self._diagnostic_event(
                "history_sync.import_delta", count=len(import_rows),
            )
        imported = 0
        try:
            with self._history_context_lock:
                self._require_history_generation(expected_generation)
                # FongMi's sync bridge is expensive and can rewrite the whole
                # local table.  Skip it when the cloud snapshot has no newer
                # rows for this device.
                self._diagnostic_event(
                    "history_sync.import_start", count=len(import_rows),
                )
                # Keep the legacy hook invocation contract with an empty list;
                # _import_native_history returns before touching Java, so this
                # remains cheap when there is no cloud delta.
                imported = self._import_native_history(import_rows)
                self._diagnostic_event("history_sync.import_finish", count=imported)
        except _HistorySyncCancelled:
            raise
        except Exception as exc:
            errors.append(("本机History导入", self._short_error(exc)))
        result = {
            "mode": self._history_sync_mode_label(),
            "local": len(local_rows),
            "cloud": len(cloud_rows),
            "cloud_available": cloud_available,
            "upload_candidates": len(uploads),
            "upload_allowed": len(permitted_uploads),
            "upload_blocked": upload_blocked,
            "uploaded": uploaded,
            "imported": imported,
            # Keep the complete reconciliation snapshot separate from the
            # smaller native-import delta.  An empty import delta must not
            # erase progress already present in the cloud snapshot.
            "merged": merged,
            "import_rows": import_rows,
            "progress": 0,
            "errors": errors,
        }
        self._diagnostic_event(
            "history_sync.finish",
            "WARN" if result.get("errors") else "INFO",
            duration_ms=int((time.monotonic() - started_at) * 1000),
            errors=len(result.get("errors") or []),
        )
        return result

    def _apply_history_sync_result(self, cache_key, result):
        merged = result.get("merged") if isinstance(result, dict) else []
        merged = merged if isinstance(merged, list) else []
        self._cache_set(cache_key, merged)
        try:
            result["progress"] = self._reconcile_follow_histories(merged)
        except Exception as exc:
            result.setdefault("errors", []).append(("追更进度回写", self._short_error(exc)))
        return result

    @staticmethod
    def _history_sync_message(result):
        skipped = max(0, int(result.get("upload_allowed") or 0) - int(result.get("uploaded") or 0))
        blocked = max(0, int(result.get("upload_blocked") or 0))
        detail = "本机 %s，云端 %s，上传 %s，导入 %s，追更进度 %s" % (
            result.get("local", 0), result.get("cloud", 0), result.get("uploaded", 0),
            result.get("imported", 0), result.get("progress", 0),
        )
        if blocked:
            detail += "，本机共享设置跳过上传 %s" % blocked
        if skipped and str(result.get("mode") or "").startswith("只读"):
            detail += "，只读跳过上传 %s" % skipped
        errors = result.get("errors") if isinstance(result.get("errors"), list) else []
        if errors:
            failures = "；".join("%s：%s" % (stage, message) for stage, message in errors)
            return "播放记录同步部分完成，存在失败：%s；%s；模式 %s" % (
                failures, detail, result.get("mode") or "只读",
            )
        return "播放记录同步完成：%s；模式 %s" % (detail, result.get("mode") or "只读")

    def _atvp_probe_card(self, status_remark=""):
        ready = bool(self.atvp_api and self.atvp_token and self._atvp_session is not None)
        return {
            "vod_id": self.ATVP_PROBE_ACTION,
            "vod_name": "检测通讯",
            "vod_pic": "",
            "vod_remarks": status_remark or ("点击验证客户端到 AList-TVBox 的通讯" if ready else "点击自动识别地址并检测通讯"),
            "action": self.ATVP_PROBE_ACTION,
        }

    def _start_atvp_job(self, kind):
        if kind not in ("probe", "sync"):
            message = "收藏和播放记录请在追更确认中选择，确认后才会加入追更"
            self._set_follow_action_status("info", message, "candidate")
            self._refresh_follow_categories()
            return json.dumps({"msg": message}, ensure_ascii=False)
        labels = {
            "probe": "通讯检测",
            "sync": "播放记录同步",
        }
        label = labels.get(kind, "后台任务")
        with self._cache_lock:
            generation = self._cache_generation
        with self._atvp_job_lock:
            if kind == "sync" and "sync-background" in self._atvp_jobs:
                return json.dumps({"msg": "History 后台同步正在进行，请稍后查看管理页状态"}, ensure_ascii=False)
            if kind in self._atvp_jobs:
                return json.dumps({"msg": "%s正在进行，请稍后查看卡片结果" % label}, ensure_ascii=False)
            self._atvp_jobs.add(kind)
            self._set_atvp_status(
                kind, "running", "%s已开始，请稍后查看卡片结果" % label, persist=False,
            )
        try:
            self._tasks.start_thread(
                self._run_atvp_job, args=(kind, generation), name="atvp-%s" % kind,
            )
        except Exception as exc:
            with self._atvp_job_lock:
                self._atvp_jobs.discard(kind)
            self._set_atvp_status(
                kind, "failed", "%s启动失败：%s" % (label, self._short_error(exc)),
            )
            return json.dumps({"msg": "%s启动失败，请重试" % label}, ensure_ascii=False)
        return json.dumps({"msg": "%s已开始，完成后本页会自动刷新" % label}, ensure_ascii=False)

    def _run_atvp_job(self, kind, generation=None):
        try:
            with self._history_context_lock:
                self._require_history_generation(generation)
                self._persist_atvp_status()
            if kind == "probe":
                with self._history_context_lock:
                    self._require_history_generation(generation)
                    raw = self._atvp_probe_history()
            else:
                raw = self._atvp_sync_history(expected_generation=generation)
            result = json.loads(raw) if isinstance(raw, str) else raw
            message = str(result.get("msg") or "操作完成") if isinstance(result, dict) else "操作完成"
            failed = bool(isinstance(result, dict) and result.get("ok") is False)
            if not failed:
                failed = any(word in message for word in (
                    "失败", "未能", "无效", "超时", "不可用", "仅支持",
                ))
            with self._history_context_lock:
                self._require_history_generation(generation)
                self._set_atvp_status(kind, "failed" if failed else "done", message)
        except _HistorySyncCancelled:
            pass
        except Exception as exc:
            with self._history_context_lock:
                if self._history_generation_active(generation):
                    self._set_atvp_status(kind, "failed", "操作失败：%s" % self._short_error(exc))
        finally:
            with self._atvp_job_lock:
                self._atvp_jobs.discard(kind)
            if self._history_generation_active(generation):
                self._refresh_current_category()

    def _load_atvp_status(self):
        getter = getattr(self, "getCache", None)
        value = None
        if callable(getter):
            try:
                value = getter(self.ATVP_STATUS_CACHE_KEY)
            except Exception:
                value = None
        statuses = value.get("statuses") if isinstance(value, dict) else {}
        self._atvp_status = statuses if isinstance(statuses, dict) else {}
        for kind, status in list(self._atvp_status.items()):
            if isinstance(status, dict) and status.get("state") == "running":
                status = dict(status)
                status.update({"state": "failed", "message": "上次任务被中断，请重新点击"})
                self._atvp_status[kind] = status

    def _set_atvp_status(self, kind, state, message, persist=True):
        with self._atvp_job_lock:
            self._atvp_status[kind] = {
                "state": str(state or ""),
                "message": str(message or ""),
                "updated_at": int(time.time()),
            }
        if not persist:
            return
        self._persist_atvp_status()

    def _persist_atvp_status(self):
        setter = getattr(self, "setCache", None)
        if callable(setter):
            with self._atvp_status_persist_lock:
                with self._atvp_job_lock:
                    payload = {"version": 1, "statuses": dict(self._atvp_status)}
                try:
                    setter(self.ATVP_STATUS_CACHE_KEY, payload)
                except Exception:
                    pass

    def _refresh_current_category(self):
        return self._refresh_native_category()

    def _atvp_status_remark(self, kind):
        status = self._atvp_status.get(kind) if isinstance(self._atvp_status, dict) else None
        if not isinstance(status, dict):
            return ""
        message = str(status.get("message") or "").strip()
        if not message:
            return ""
        prefix = {"running": "进行中", "done": "已完成", "failed": "失败"}.get(status.get("state"), "状态")
        updated_at = self._positive_int(status.get("updated_at"), 0)
        timestamp = time.strftime("%m-%d %H:%M", time.localtime(updated_at)) if updated_at else ""
        return "%s · %s%s" % (prefix, message, (" · " + timestamp) if timestamp else "")

    def _atvp_sync_history(self, expected_generation=None):
        with self._history_context_lock:
            self._require_history_generation(expected_generation)
            if not self._ensure_atvp_connection(force=True):
                detail = ("：%s" % self._atvp_discovery_error) if self._atvp_discovery_error else ""
                return json.dumps({
                    "ok": False,
                    "msg": "本插件仅支持通过 AList-TVBox 生成的 raw 插件订阅%s" % detail,
                }, ensure_ascii=False)
        try:
            with self._history_sync_lock:
                result = self._sync_history_once(expected_generation=expected_generation)
                with self._history_context_lock:
                    self._require_history_generation(expected_generation)
                    self._history_snapshot_revision += 1
                    self._apply_history_sync_result("atvp-history-snapshot", result)
            return json.dumps({
                "ok": not result["errors"],
                "msg": self._history_sync_message(result),
                "mode": result["mode"],
                "local": result["local"],
                "cloud": result["cloud"],
                "uploaded": result["uploaded"],
                "imported": result["imported"],
                "progress": result["progress"],
            }, ensure_ascii=False)
        except _HistorySyncCancelled:
            raise
        except Exception as exc:
            return json.dumps({
                "ok": False,
                "msg": "播放记录同步失败：%s" % self._short_error(exc),
            }, ensure_ascii=False)

    def _atvp_history_push(self, rows):
        return self._history_coordinator.push(rows)

    @classmethod
    def _history_upload_payload(cls, rows):
        # The server stores one logical row per History key, but callers may
        # hand us duplicate local rows after a native export/import race.
        # Collapse those duplicates before POST and keep the newest rows only;
        # this bounds growth caused by this plugin without deleting records
        # belonging to other devices.
        by_key = OrderedDict()
        for row in cls._normalize_history_rows(rows):
            upload = dict(row)
            for key in ("vodPic", "vod_pic"):
                upload.pop(key, None)
            key = str(upload.get("key") or "").strip()
            if not key:
                continue
            previous = by_key.get(key)
            if previous is None:
                by_key[key] = upload
                continue
            def rank(value):
                try:
                    return (
                        int(value.get("createTime") or 0),
                        int(value.get("position") or 0),
                        int(value.get("revPlay") or 0),
                    )
                except Exception:
                    return (0, 0, 0)
            if rank(upload) >= rank(previous):
                by_key[key] = upload
        payload = list(by_key.values())
        payload.sort(key=lambda value: (
            int(value.get("createTime") or 0),
            int(value.get("revPlay") or 0),
            int(value.get("position") or 0),
        ), reverse=True)
        return payload[:cls.HISTORY_ROW_LIMIT]

    def _remember_history_api_origin(self, value):
        origin = self._http_base(value, "")
        parsed = urlparse(origin)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            return ""
        if not isinstance(getattr(self, "_history_api_origins", None), list):
            self._history_api_origins = []
        if origin not in self._history_api_origins:
            self._history_api_origins.append(origin)
        return origin

    @staticmethod
    def _history_private_origin_counterpart(origin):
        parsed = urlparse(str(origin or "").strip())
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            return ""
        host = parsed.hostname.strip("[]").lower()
        private = host == "localhost"
        if not private:
            try:
                address = ipaddress.ip_address(host)
                if address.is_loopback:
                    private = True
                elif not (
                        address.is_unspecified
                        or address.is_link_local
                        or address.is_reserved
                        or address.is_multicast):
                    if address.version == 4:
                        private = any(
                            address in network for network in (
                                ipaddress.ip_network("10.0.0.0/8"),
                                ipaddress.ip_network("172.16.0.0/12"),
                                ipaddress.ip_network("192.168.0.0/16"),
                            )
                        )
                    else:
                        private = address in ipaddress.ip_network("fc00::/7")
            except Exception:
                private = False
        if not private:
            return ""
        scheme = "http" if parsed.scheme == "https" else "https"
        return parsed._replace(scheme=scheme).geturl().rstrip("/")

    def _history_origin_candidates(self):
        values = []
        for value in (
                self._history_selected_origin,
                self.history_api,
                self.atvp_api,
                self._history_primary_origin,
                *(self._history_api_origins or []),
        ):
            origin = self._http_base(value, "")
            if not origin or origin in values:
                continue
            values.append(origin)
            counterpart = self._history_private_origin_counterpart(origin)
            if counterpart and counterpart not in values:
                values.append(counterpart)
        return values

    def _atvp_history_endpoint(self, origin, resource="history"):
        base = self._http_base(origin, "")
        if not base:
            return self._atvp_endpoint(resource)
        return "%s/%s/%s" % (
            base.rstrip("/"),
            str(resource or "").strip("/"),
            quote(self.atvp_token, safe=""),
        )

    @staticmethod
    def _history_retryable_transport_error(exc, method):
        if method != "post":
            return isinstance(exc, (
                requests.exceptions.ConnectionError,
                requests.exceptions.SSLError,
                requests.exceptions.Timeout,
            ))
        text = str(exc or "").lower()
        if isinstance(exc, requests.exceptions.SSLError):
            return any(marker in text for marker in (
                "wrong version number",
                "unknown protocol",
                "http request was sent to https port",
            ))
        if not isinstance(exc, requests.exceptions.ConnectionError):
            return False
        return any(marker in text for marker in (
            "failed to establish a new connection",
            "connection refused",
            "name or service not known",
            "nodename nor servname",
            "network is unreachable",
            "no route to host",
        ))

    def _atvp_history_request(self, method, **kwargs):
        if not self._alist_tvbox_plugin:
            raise RuntimeError("本插件仅支持 AList-TVBox raw 插件订阅")
        method_name = str(method or "GET").strip().lower()
        sender = getattr(self._atvp_session, method_name)
        request_kwargs = {
            "timeout": self.timeout,
            "verify": self.verify_tls,
        }
        request_kwargs.update(kwargs)
        request_kwargs.setdefault("stream", True)
        if method_name == "get" and self._history_write_enabled() and not self._history_auth_token:
            self._atvp_history_login(force=False)
        if method_name == "post":
            if not self._history_write_enabled():
                raise RuntimeError("History 写入未启用：请同时配置用户名和密码")
            if not self._history_auth_token:
                self._atvp_history_login(force=True)
        origins = self._history_origin_candidates() or [self.atvp_api]
        response = None
        selected_origin = ""
        last_error = None
        for origin in origins:
            try:
                response = sender(
                    self._atvp_history_endpoint(origin),
                    **request_kwargs
                )
                selected_origin = origin
                self._history_selected_origin = origin
                break
            except Exception as exc:
                last_error = exc
                if not self._history_retryable_transport_error(exc, method_name):
                    raise
        if response is None:
            if last_error is not None:
                raise last_error
            raise RuntimeError("AList-TVBox History 没有可用地址")
        if not self._atvp_history_needs_auth(response):
            return response
        try:
            response.close()
        except Exception:
            pass
        self._history_selected_origin = selected_origin
        if not self._atvp_history_login(force=True):
            return response
        return sender(
            self._atvp_history_endpoint(self._history_selected_origin or selected_origin),
            **request_kwargs
        )

    def _atvp_history_delete(self, key):
        history_key = str(key or "").strip()
        if not history_key:
            raise RuntimeError("History 删除键无效")
        if not self._history_write_enabled():
            raise RuntimeError("History 删除未启用：请同时配置用户名和密码")
        if not self._history_auth_token:
            self._atvp_history_login(force=False)
        origins = self._history_origin_candidates() or [self.atvp_api]
        last_error = None
        for origin in origins:
            try:
                response = self._atvp_session.delete(
                    self._atvp_history_endpoint(origin),
                    params={"key": history_key},
                    timeout=self.timeout,
                    verify=self.verify_tls,
                    stream=True,
                )
                self._history_selected_origin = origin
                if response.status_code in (401, 403):
                    try:
                        response.close()
                    except Exception:
                        pass
                    if not self._atvp_history_login(force=True):
                        raise RuntimeError("AList-TVBox History 删除认证失败")
                    response = self._atvp_session.delete(
                        self._atvp_history_endpoint(self._history_selected_origin or origin),
                        params={"key": history_key},
                        timeout=self.timeout,
                        verify=self.verify_tls,
                        stream=True,
                    )
                if response.status_code >= 500:
                    try:
                        response.close()
                    except Exception:
                        pass
                    if self._atvp_history_delete_by_id(
                            self._history_selected_origin or origin, history_key):
                        return True
                try:
                    if response.status_code < 200 or response.status_code >= 300:
                        raise RuntimeError(self._atvp_history_http_error(response, "删除"))
                finally:
                    try:
                        response.close()
                    except Exception:
                        pass
                return True
            except Exception as exc:
                last_error = exc
                if not self._history_retryable_transport_error(exc, "get"):
                    raise
        if last_error is not None:
            raise last_error
        raise RuntimeError("AList-TVBox History 没有可用删除地址")

    def _atvp_history_delete_by_id(self, origin, history_key):
        response = self._atvp_session.get(
            self._atvp_history_endpoint(origin),
            params={"key": history_key},
            timeout=self.timeout,
            verify=self.verify_tls,
            stream=True,
        )
        if response.status_code < 200 or response.status_code >= 300:
            try:
                response.close()
            except Exception:
                pass
            return False
        row = self._read_bounded_json_response(
            response,
            "AList-TVBox History 删除回退查询",
            max_bytes=self.HISTORY_ROW_MAX_BYTES,
        )
        if not isinstance(row, dict) or str(row.get("key") or "") != history_key:
            return False
        history_id = self._int_value(row.get("id"), 0)
        if history_id <= 0:
            return False
        response = self._atvp_session.delete(
            "%s/api/history/%s" % (
                self._http_base(origin, "").rstrip("/"), history_id,
            ),
            timeout=self.timeout,
            verify=self.verify_tls,
            stream=True,
        )
        try:
            if response.status_code < 200 or response.status_code >= 300:
                return False
        finally:
            try:
                response.close()
            except Exception:
                pass
        self._diagnostic_event(
            "history.delete.fallback", "ok", origin=self._http_base(origin, ""),
        )
        return True

    @classmethod
    def _atvp_history_error_text(cls, response):
        cached = getattr(response, "_atvp_bounded_error_text", None)
        if isinstance(cached, str):
            return cached
        limit = cls.HISTORY_CONFIG_MAX_BYTES
        text = ""
        truncated = False
        try:
            try:
                content_length = int((getattr(response, "headers", {}) or {}).get("Content-Length") or 0)
            except Exception:
                content_length = 0
            if 0 < content_length <= limit:
                iterator = getattr(response, "iter_content", None)
                if callable(iterator):
                    chunks = []
                    received = 0
                    for chunk in iterator(chunk_size=16384):
                        if not chunk:
                            continue
                        received += len(chunk)
                        if received > limit:
                            chunks = []
                            truncated = True
                            break
                        chunks.append(chunk)
                    if chunks:
                        text = b"".join(chunks).decode("utf-8", errors="replace")
            elif content_length == 0:
                iterator = getattr(response, "iter_content", None)
                if callable(iterator):
                    chunks = []
                    received = 0
                    try:
                        for chunk in iterator(chunk_size=16384):
                            if not chunk:
                                continue
                            received += len(chunk)
                            if received > limit:
                                chunks = []
                                truncated = True
                                break
                            chunks.append(chunk)
                    except TypeError:
                        chunks = []
                    if chunks:
                        text = b"".join(chunks).decode("utf-8", errors="replace")
                if not text and not truncated:
                    text = _history_clip_text(getattr(response, "text", "") or "", limit)
        except Exception:
            text = ""
        try:
            setattr(response, "_atvp_bounded_error_text", text)
        except Exception:
            pass
        try:
            response.close()
        except Exception:
            pass
        return text

    @classmethod
    def _atvp_history_needs_auth(cls, response):
        if response.status_code in (401, 403):
            return True
        if response.status_code != 500:
            return False
        text = cls._atvp_history_error_text(response)
        return "WebAuthenticationDetails" in text or "cannot be cast to class java.lang.Integer" in text

    def _atvp_history_login(self, force=False):
        if self._history_auth_token and not force:
            self._atvp_session.headers["Authorization"] = self._history_auth_token
            return True
        if force:
            self._history_auth_token = ""
            self._atvp_session.headers.pop("Authorization", None)
        if not (self.history_username and self.history_password):
            return False
        origins = self._history_origin_candidates() or [self.atvp_api]
        response = None
        selected_origin = ""
        last_error = None
        for origin in origins:
            try:
                response = self._atvp_session.post(
                    self._http_base(origin, "").rstrip("/") + "/api/accounts/login",
                    json={"username": self.history_username, "password": self.history_password},
                    timeout=self.timeout,
                    verify=self.verify_tls,
                    stream=True,
                )
                selected_origin = origin
                break
            except Exception as exc:
                last_error = exc
                if not self._history_retryable_transport_error(exc, "post"):
                    raise
        if response is None:
            if last_error is not None:
                raise last_error
            raise RuntimeError("AList-TVBox History 没有可用登录地址")
        if response.status_code < 200 or response.status_code >= 300:
            try:
                response.close()
            except Exception:
                pass
            raise RuntimeError("AList-TVBox History 用户登录 HTTP %s" % response.status_code)
        value = self._read_bounded_json_response(
            response,
            "AList-TVBox History 用户登录",
            max_bytes=self.HISTORY_CONFIG_MAX_BYTES,
        )
        authorities = value.get("authorities") if isinstance(value, dict) else []
        roles = set()
        for authority in authorities or []:
            if isinstance(authority, dict):
                roles.add(str(authority.get("authority") or "").strip().upper())
            else:
                roles.add(str(authority or "").strip().upper())
        if not roles.intersection(("USER", "ADMIN")):
            raise RuntimeError("History 写入账号必须是 AList-TVBox USER 或 ADMIN 角色")
        token = str(value.get("token") or "").strip() if isinstance(value, dict) else ""
        if not token:
            raise RuntimeError("AList-TVBox History 用户登录未返回令牌")
        self._history_auth_token = token
        self._history_selected_origin = selected_origin
        self._atvp_session.headers["Authorization"] = token
        return True

    @classmethod
    def _atvp_history_http_error(cls, response, operation):
        text = cls._atvp_history_error_text(response)
        if response.status_code == 500 and (
            "WebAuthenticationDetails" in text
            or "cannot be cast to class java.lang.Integer" in text
        ):
            return (
                "AList-TVBox History匿名接口存在用户编号转换缺陷；"
                "请升级到包含History订阅身份修复的服务端版本后重试"
            )
        return "AList-TVBox 历史%s HTTP %s" % (operation, response.status_code)

    def _native_history_export(self):
        native_error = ""
        try:
            native = self._native_history_export_java()
            if native:
                config_text = str(native.get("config") or "")
                if self._utf8_size(config_text) > self.HISTORY_CONFIG_MAX_BYTES:
                    raise RuntimeError("FongMi 当前影视订阅配置过大")
                return {
                    "config": config_text,
                    "rows": self._normalize_history_rows(native.get("rows") or []),
                }
        except Exception as exc:
            native_error = self._short_error(exc)
            self._atvp_discovery_error = native_error
        nonce = "%x%x" % (int(time.time() * 1000), threading.get_ident())
        pending = {"captured": {}, "event": threading.Event()}
        with self._native_export_lock:
            self._native_exports[nonce] = pending
        try:
            device = {"ip": self._native_history_callback_url(nonce)}
            self._post_local_action({
                "do": "sync",
                "mode": "2",
                "type": "history",
                "device": json.dumps(device, ensure_ascii=False),
                "config": json.dumps({"type": 0}, separators=(",", ":")),
            })
            pending["event"].wait(min(12, max(4, self.timeout)))
        finally:
            with self._native_export_lock:
                self._native_exports.pop(nonce, None)
        if not pending["event"].is_set():
            if native_error:
                raise RuntimeError("FongMi 原生History读取失败：%s；本机HTTP导出超时" % native_error)
            raise RuntimeError("FongMi 本机 History 导出超时")
        captured = pending["captured"]
        if captured.get("error"):
            raise RuntimeError(str(captured.get("error")))
        try:
            rows = json.loads(captured.get("targets") or "[]")
        except Exception:
            raise RuntimeError("FongMi 本机 History 格式无效")
        if not isinstance(rows, list):
            raise RuntimeError("FongMi 本机 History 格式无效")
        return {
            "config": captured.get("config") or "",
            "rows": self._normalize_history_rows(rows),
        }

    def _native_history_export_java(self, limit=None):
        """Read FongMi's active VOD config and History through Chaquopy when available."""
        try:
            from java import jclass
        except Exception:
            return None
        config_cls = jclass("com.fongmi.android.tv.bean.Config")
        history_cls = jclass("com.fongmi.android.tv.bean.History")
        config = config_cls.vod()
        config_url = str(config.getUrl() or "").strip() if config is not None else ""
        if not config_url:
            raise RuntimeError("FongMi 当前没有活动的影视订阅")
        # The no-argument method resolves VodConfig.getCid() inside FongMi.
        # Config.vod().id can briefly lag behind the active runtime config.
        rows = history_cls.get()
        values = []
        row_limit = max(0, self._int_value(limit, 0))
        row_limit = min(row_limit or self.HISTORY_ROW_LIMIT, self.HISTORY_ROW_LIMIT)
        if hasattr(rows, "size") and hasattr(rows, "get"):
            count = int(rows.size())
            count = min(count, row_limit)
            source_rows = (rows.get(index) for index in range(count))
        else:
            source_rows = rows
        for index, row in enumerate(source_rows):
            if index >= row_limit:
                break
            if isinstance(row, dict):
                value = row
            else:
                raw = str(row.toString() or "{}")
                if self._utf8_size(raw) > self.HISTORY_ROW_MAX_BYTES:
                    continue
                value = json.loads(raw)
            if isinstance(value, dict):
                values.append(value)
        config_text = str(config.toString() or "")
        if self._utf8_size(config_text) > self.HISTORY_CONFIG_MAX_BYTES:
            raise RuntimeError("FongMi 当前影视订阅配置过大")
        return {
            "config": config_text,
            "rows": self._normalize_history_rows(values),
        }

    @staticmethod
    def _native_history_delete_java(keys):
        try:
            from java import jclass
        except Exception:
            return None
        history_cls = jclass("com.fongmi.android.tv.bean.History")
        deleted = 0
        for key in dict.fromkeys(str(value or "").strip() for value in keys or []):
            if not key:
                continue
            row = history_cls.find(key)
            if row is None:
                continue
            row.delete()
            if history_cls.find(key) is None:
                deleted += 1
        return deleted

    def _native_history_callback_url(self, nonce):
        origin = self._fongmi_local_origin()
        return "%s/proxy?do=py&follow_sync_callback=%s&suffix=" % (
            origin,
            quote(str(nonce or ""), safe=""),
        )

    def _capture_native_history(self):
        exported = self._native_history_export()
        if not self.atvp_api and exported.get("config"):
            self._apply_native_subscription_config(exported.get("config"))
        return self._normalize_history_rows(exported.get("rows") or [])

    def _import_native_history(self, cloud_rows):
        rows = []
        for row in self._normalize_history_rows(cloud_rows):
            normalized = self._history_for_local(row)
            if normalized:
                # FongMi's History model declares revSort/revPlay as booleans;
                # cloud History may contain the legacy numeric 0/1 encoding.
                for key in ("revSort", "revPlay"):
                    if key in normalized:
                        normalized[key] = bool(self._history_int(normalized.get(key), 0))
                rows.append(normalized)
        if not rows:
            return 0
        native_error = ""
        try:
            imported = self._native_history_import_java(rows)
            if imported is not None:
                return imported
        except Exception as exc:
            native_error = self._short_error(exc)
        try:
            self._post_local_action({
                "do": "sync",
                "mode": "1",
                "type": "history",
                "force": "false",
                "config": self._subscription_config(),
                "targets": json.dumps(rows, ensure_ascii=False, separators=(",", ":")),
            })
        except Exception as exc:
            if native_error:
                raise RuntimeError("原生History导入失败：%s；本机HTTP回退失败：%s" % (native_error, self._short_error(exc)))
            raise
        return len(rows)

    def _history_import_rows(self, rows, local_rows):
        candidates = self._normalize_history_rows(rows)
        local = self._normalize_history_rows(local_rows)
        by_title = {}
        for row in local:
            title = self._normalize_media_title(row.get("vodName"))
            if not title:
                continue
            previous = by_title.get(title)
            if previous is None or self._history_semantic_rank(row) > self._history_semantic_rank(previous):
                by_title[title] = row
        output = []
        for row in candidates:
            title = self._normalize_media_title(row.get("vodName"))
            current = by_title.get(title) if title else None
            if current is None or self._history_should_import(row, current):
                output.append(row)
        return output

    def _history_semantic_rank(self, row):
        text = " ".join(
            str(row.get(key) or "")
            for key in ("vodFlag", "vodRemarks", "episodeUrl", "vodName")
        )
        season, episode, explicit = self._episode_from_text_info(text, 1, 1)
        episode_rank = season * 10000 + episode if explicit and season and episode else 0
        position = self._history_int(row.get("position"), 0)
        duration = self._history_int(row.get("duration"), 0)
        completed = 1 if self._history_is_complete(row) else 0
        return episode_rank, completed, position, duration, self._history_int(row.get("createTime"), 0)

    def _history_should_import(self, candidate, local):
        cloud_rank = self._history_semantic_rank(candidate)
        local_rank = self._history_semantic_rank(local)
        if cloud_rank[0] > local_rank[0]:
            return True
        if cloud_rank[0] < local_rank[0]:
            return False
        if cloud_rank[0] > 0:
            if cloud_rank[1] > local_rank[1]:
                return True
            if cloud_rank[1] < local_rank[1]:
                return False
            if cloud_rank[2] > local_rank[2] + 30 * 1000:
                return True
            return False
        if cloud_rank[2] > local_rank[2] + 30 * 1000:
            return True
        cloud_time = self._history_int(candidate.get("createTime"), 0)
        local_time = self._history_int(local.get("createTime"), 0)
        now_ms = int(time.time() * 1000)
        if cloud_time > now_ms + HISTORY_CLOCK_SKEW_MS:
            return False
        return cloud_time > local_time

    @staticmethod
    def _native_history_import_java(rows):
        """Import History through FongMi's Java model without using the loopback server."""
        try:
            from java import jclass
        except Exception:
            return None
        history_cls = jclass("com.fongmi.android.tv.bean.History")
        payload = json.dumps(rows, ensure_ascii=False, separators=(",", ":"))
        history_cls.sync(history_cls.arrayFrom(payload))
        imported = 0
        for row in rows:
            key = str(row.get("key") or "")
            if key and history_cls.find(key) is not None:
                imported += 1
        return imported

    @staticmethod
    def _native_keep_export_java(limit=None):
        """Read FongMi VOD favorites without relying on obfuscated config classes."""
        try:
            from java import jclass
        except Exception:
            return None
        keep_cls = jclass("com.fongmi.android.tv.bean.Keep")
        rows = keep_cls.getVod()
        try:
            row_limit = max(0, int(limit or 0))
        except Exception:
            row_limit = 0
        if hasattr(rows, "size") and hasattr(rows, "get"):
            count = int(rows.size())
            if row_limit:
                count = min(count, row_limit)
            source_rows = (rows.get(index) for index in range(count))
        else:
            source_rows = rows
        values = []
        for index, row in enumerate(source_rows):
            if row_limit and index >= row_limit:
                break
            key = row.getKey()
            title = row.getVodName()
            if key is None or title is None:
                continue
            values.append({
                "key": str(key),
                "title": str(title),
                "pic": "" if row.getVodPic() is None else str(row.getVodPic()),
                "site_name": "" if row.getSiteName() is None else str(row.getSiteName()),
                "create_time": int(row.getCreateTime()),
                "cid": int(row.getCid()),
                "type": int(row.getType()),
            })
        return values

    def _sync_native_keeps_to_follow(self):
        return json.dumps({
            "msg": "本地收藏自动追更已停用，请在追更确认中逐项确认",
        }, ensure_ascii=False)

    def _resolve_keep_follow_item(self, keep):
        match, reason = self._match_keep_to_tmdb(keep)
        if not match:
            return None, reason
        tmdb_id = self._positive_int(match.get("id"), 0)
        detail = self._tmdb_api("/tv/%s" % tmdb_id, {}, self.detail_cache_ttl, allow_stale=False)
        item = self._follow_item_from_tmdb(detail, {
            "tmdb_id": tmdb_id,
            "title": str(detail.get("name") or match.get("name") or keep.get("title") or ""),
            "seen_episode": "",
            "tracked_episode": "",
            "seen_source": "",
        })
        item.update({"pending_metadata": False, "follow_source": "fongmi_keep"})
        try:
            item = self._attach_douban_to_tmdb_item(item, detail)
        except Exception:
            pass
        return item, ""

    def _match_keep_to_tmdb(self, keep):
        title, year, explicit_series = self._keep_search_profile(keep.get("title"))
        normalized = self._normalize_media_title(title)
        if not normalized:
            return None, "empty_title"
        params = {"query": title, "page": 1, "include_adult": "false"}
        tv_rows = self._tmdb_api("/search/tv", params, self.detail_cache_ttl).get("results") or []
        movie_rows = self._tmdb_api("/search/movie", params, self.detail_cache_ttl).get("results") or []
        tv_ranked = self._rank_keep_candidates(tv_rows, normalized, year, True, explicit_series)
        movie_ranked = self._rank_keep_candidates(movie_rows, normalized, year, False, False)
        if not tv_ranked or tv_ranked[0][0] < 90:
            return None, "no_confident_tv"
        if len(tv_ranked) > 1 and tv_ranked[0][0] == tv_ranked[1][0]:
            return None, "ambiguous_tv"
        movie_score = movie_ranked[0][0] if movie_ranked else 0
        if movie_score >= tv_ranked[0][0] and not explicit_series:
            return None, "movie_conflict"
        return tv_ranked[0][2], ""

    def _rank_keep_candidates(self, rows, normalized, year, television, explicit_series):
        ranked = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            names = (
                (row.get("name"), row.get("original_name"))
                if television else (row.get("title"), row.get("original_title"))
            )
            aliases = {self._normalize_media_title(value) for value in names} - {""}
            if normalized in aliases:
                score = 100
            elif any(min(len(normalized), len(alias)) >= 4 and (normalized in alias or alias in normalized) for alias in aliases):
                score = 55
            else:
                score = 0
            date_key = "first_air_date" if television else "release_date"
            candidate_year = self._positive_int(str(row.get(date_key) or "")[:4], 0)
            if score and year and candidate_year:
                difference = abs(year - candidate_year)
                score += 25 if difference == 0 else (10 if difference == 1 else -30)
            if score and television and explicit_series:
                score += 30
            ranked.append((score, float(row.get("popularity") or 0), row))
        ranked.sort(key=lambda value: (value[0], value[1]), reverse=True)
        return ranked

    @staticmethod
    def _keep_search_profile(value):
        raw = unicodedata.normalize("NFKC", str(value or "")).strip()
        year_match = re.search(r"(?<!\d)((?:19|20)\d{2})(?!\d)", raw)
        year = int(year_match.group(1)) if year_match else 0
        explicit_series = bool(re.search(
            r"(?i)(?:\bS\s*0*\d{1,2}(?:\s*E\s*0*\d{1,3})?\b|第\s*[一二三四五六七八九十百零〇两\d]+\s*[季部集话期]|全\s*\d+\s*集|电视剧|连续剧|剧集|番剧)",
            raw,
        ))
        text = re.sub(r"(?i)\.(?:mkv|mp4|avi|mov|wmv|flv|ts|m2ts|webm)\b.*$", " ", raw)
        text = re.sub(r"[\(（\[【]\s*(?:19|20)\d{2}\s*[\)）\]】]", " ", text)
        text = re.split(
            r"(?i)\s*(?:[-_·|]+\s*)?(?:\bS\s*0*\d{1,2}(?:\s*E\s*0*\d{1,3})?\b|第\s*[一二三四五六七八九十百零〇两\d]+\s*[季部集话期])",
            text,
            maxsplit=1,
        )[0]
        text = re.sub(r"(?i)\b(?:2160p|1080p|720p|4k|web[- .]?dl|bluray|x26[45]|h26[45]|aac)\b.*$", " ", text)
        text = text.strip(" -_·|[]【】()（）")
        return (text or raw), year, explicit_series

    def _post_local_action(self, data):
        origin = self._fongmi_local_origin()
        session = requests.Session()
        session.trust_env = False
        try:
            response = session.post(origin + "/action", data=data, timeout=min(15, max(5, self.timeout)))
        finally:
            session.close()
        if response.status_code < 200 or response.status_code >= 300:
            raise RuntimeError("FongMi 本机同步 HTTP %s" % response.status_code)

    def _fongmi_local_origin(self):
        getter = getattr(self, "getProxyUrl", None)
        if not callable(getter):
            raise RuntimeError("当前运行时未提供 FongMi 本机端口")
        parsed = urlparse(str(getter(True) or ""))
        if parsed.scheme != "http" or parsed.hostname not in ("127.0.0.1", "localhost") or not parsed.port:
            raise RuntimeError("FongMi 本机端口地址无效")
        return "http://127.0.0.1:%s" % parsed.port

    def _subscription_config(self):
        url = "%s/sub/%s/0" % (self.atvp_api.rstrip("/"), quote(self.atvp_token, safe=""))
        return json.dumps({"id": 1, "type": 0, "url": url}, ensure_ascii=False, separators=(",", ":"))

    def _merge_native_history(self, local_rows, cloud_rows):
        local_rows = self._normalize_history_rows(local_rows)
        cloud_rows = self._normalize_history_rows(cloud_rows)
        cloud_uid = next((self._history_int(row.get("uid"), 1) for row in cloud_rows if self._history_int(row.get("uid"), 0) > 0), 1)
        merged = {}
        for row in cloud_rows:
            normalized = self._history_for_cloud(row, cloud_uid)
            if normalized:
                identity = self._history_identity(normalized)
                previous = merged.get(identity)
                if previous is None or self._history_merge_rank(normalized) > self._history_merge_rank(previous):
                    merged[identity] = normalized
        uploads = []
        for row in local_rows:
            normalized = self._history_for_cloud(row, cloud_uid)
            if not normalized:
                continue
            identity = self._history_identity(normalized)
            previous = merged.get(identity)
            if previous is None or self._history_merge_rank(normalized) > self._history_merge_rank(previous):
                merged[identity] = normalized
                uploads.append(normalized)
        result = sorted(merged.values(), key=lambda row: self._history_rank(row), reverse=True)
        return result, uploads

    def _history_for_cloud(self, row, uid):
        identity = self._history_identity(row)
        if not identity:
            return None
        output = {key: row.get(key) for key in self.HISTORY_FIELDS if key in row and key != "key"}
        output["key"] = identity[1] if identity[0] == "csp_AList" else "@@@".join(identity)
        output["uid"] = uid
        output["cid"] = 0
        return output

    def _history_for_local(self, row):
        identity = self._history_identity(row)
        if not identity:
            return None
        output = {key: row.get(key) for key in self.HISTORY_FIELDS if key in row and key not in ("key", "uid")}
        output["key"] = "%s@@@%s@@@1" % identity
        output["cid"] = 1
        return output

    def _history_identity(self, row):
        key = str(row.get("key") or "").strip() if isinstance(row, dict) else ""
        if not key:
            return None
        parts = key.split("@@@")
        if len(parts) >= 2 and parts[0] and parts[1]:
            return parts[0], parts[1]
        return "csp_AList", key

    def _sync_site_keys(self):
        keys = set(self.SYNC_SITE_KEYS)
        runtime_key = str(getattr(self, "siteKey", "") or "").strip()
        if runtime_key:
            keys.add(runtime_key)
        return keys

    @staticmethod
    def _history_int(value, default=0):
        try:
            return int(value)
        except Exception:
            return default

    @staticmethod
    def _history_rank(row):
        return (
            Spider._history_int(row.get("createTime")),
            Spider._history_int(row.get("position")),
            Spider._history_int(row.get("duration")),
        )

    def _history_merge_rank(self, row):
        if self._history_has_followplay_reference(row):
            return (1,) + self._history_semantic_rank(row)
        return (0,) + self._history_rank(row)

    def _atvp_probe_history(self):
        stage = "配置桥"
        if not self._ensure_atvp_connection(force=True):
            detail = ("：%s" % self._atvp_discovery_error) if self._atvp_discovery_error else ""
            return json.dumps({
                "ok": False,
                "msg": "本插件仅支持通过 AList-TVBox 生成的 raw 插件订阅%s" % detail,
            }, ensure_ascii=False)
        try:
            stage = "本机History读取"
            try:
                local_rows = self._capture_native_history()
                local_status = "本机History %s 条" % len(local_rows)
            except Exception as exc:
                local_rows = []
                local_status = "本机History桥异常(%s)" % self._short_error(exc)
            stage = "云端History读取"
            histories = self._history_coordinator.fetch()
            self._cache_set("atvp-history-snapshot", histories)
            return json.dumps({
                "ok": True,
                "msg": "AList-TVBox 通讯正常：配置桥正常，地址和令牌已识别，%s，云端GET %s 条" % (
                    local_status, len(histories),
                )
            }, ensure_ascii=False)
        except Exception as exc:
            return json.dumps({
                "ok": False,
                "msg": "AList-TVBox 通讯失败[%s]：%s" % (stage, self._short_error(exc)),
            }, ensure_ascii=False)

    def _atvp_endpoint(self, resource):
        if not self._alist_tvbox_plugin:
            return ""
        return "%s/%s/%s" % (
            self.atvp_api.rstrip("/"),
            str(resource or "").strip("/"),
            quote(self.atvp_token, safe=""),
        )

    def _history_followplay_payload(self, history):
        if not isinstance(history, dict):
            return None
        match = re.search(r"(?:followplay_|followplay://)[A-Za-z0-9_-]+", str(history.get("episodeUrl") or ""))
        return self._parse_followplay(match.group(0)) if match else None

    @staticmethod
    def _history_has_followplay_reference(history):
        if not isinstance(history, dict):
            return False
        return bool(re.search(
            r"(?:^|[$#])(?:followplay_|followplay://)",
            str(history.get("episodeUrl") or ""),
        ))

    def _atvp_history_for_item(self, item, histories):
        if not isinstance(item, dict) or not isinstance(histories, list):
            return None
        tmdb_id = str(self._positive_int(item.get("tmdb_id"), 0))
        source_id = str(item.get("source_id") or item.get("douban_id") or "").strip()
        exact = []
        for history in histories:
            payload = self._history_followplay_payload(history)
            if not payload:
                continue
            payload_tmdb = str(self._positive_int(payload.get("tmdbId"), 0))
            payload_source = str(payload.get("sourceId") or "").strip()
            if (tmdb_id and payload_tmdb == tmdb_id) or (source_id and payload_source == source_id):
                exact.append(history)
        if exact:
            return max(exact, key=self._history_semantic_rank)

        bound_id = str(self.follow_alist_bindings.get(tmdb_id) or item.get("alist_vod_id") or "").strip()
        if bound_id:
            matched = [
                history for history in histories
                if self._history_identity(history) and self._history_identity(history)[1] == bound_id
            ]
            return max(matched, key=self._history_semantic_rank) if matched else None

        aliases = {
            Filter._normalize_title(value)
            for value in self._follow_title_alias_values(item)
        } - {""}
        if not aliases:
            return None
        target_season = self._tracking_season(item)
        ranked = []
        for history in histories:
            history_title = Filter._normalize_title(history.get("vodName"))
            title_score = max([Filter._title_score(history_title, alias) for alias in aliases] or [0])
            if title_score <= 0:
                continue
            history_season = Filter._season(" ".join(
                str(history.get(key) or "") for key in ("vodName", "vodFlag", "vodRemarks")
            ))
            season_score = 20 if history_season and history_season == target_season else 0
            ranked.append((title_score + season_score, history))
        if not ranked:
            return None
        best_score = max(score for score, _history in ranked)
        best = [history for score, history in ranked if score == best_score]
        return best[0] if len(best) == 1 else None

    def _history_resume_fields(self, item, history):
        episode = self._history_episode_key(item, history)
        if not episode:
            return {}
        payload = self._history_followplay_payload(history) or {}
        payload_resource_id = str(payload.get("resourceId") or "").strip()
        payload_resource_mode = str(payload.get("resourceMode") or "vod").strip().lower() or "vod"
        if not self._resource_id_persistable(payload_resource_id, payload_resource_mode):
            payload_resource_id = ""
        resource_id = payload_resource_id or str(item.get("alist_vod_id") or "").strip()
        fields = {
            "history_episode": episode,
            "history_position": self._bounded_int(history.get("position"), 0, 0, 2147483647000),
            "history_duration": self._bounded_int(history.get("duration"), 0, 0, 2147483647000),
            "history_vod_name": str(history.get("vodName") or ""),
            "history_updated_at": int(time.time()),
        }
        if resource_id:
            fields["alist_vod_id"] = resource_id
        if payload_resource_id:
            resource_mode = payload_resource_mode
            fields["alist_resource_mode"] = resource_mode
            fields["alist_resource_provider"] = self._resource_provider_key(
                payload.get("resourceProvider"), payload_resource_id,
            )
        return fields

    def _reconcile_follow_histories(self, histories, changed_items=None):
        if not isinstance(histories, list) or not histories:
            return 0
        with self._follow_enrich_lock:
            items = dict(self._follow_memory.get("items") or {})
            changed = 0
            now = int(time.time())
            for key, value in list(items.items()):
                if not isinstance(value, dict):
                    continue
                history = self._atvp_history_for_item(value, histories)
                resume_fields = self._history_resume_fields(value, history)
                if not resume_fields:
                    continue
                episode = resume_fields["history_episode"]
                current_episode = str(value.get("history_episode") or "")
                candidate_rank = self._episode_rank(episode)
                current_rank = self._episode_rank(current_episode)
                if candidate_rank < current_rank:
                    continue
                if candidate_rank == current_rank and current_rank > 0:
                    candidate_position = self._positive_int(resume_fields.get("history_position"), 0)
                    current_position = self._positive_int(value.get("history_position"), 0)
                    if candidate_position < current_position:
                        continue
                resource_id = str(resume_fields.get("alist_vod_id") or "")
                item = dict(value)
                previous_resource_id = str(item.get("alist_vod_id") or "")
                history_changed = (
                    str(item.get("history_episode") or "") != episode
                    or self._positive_int(item.get("history_position"), 0) != resume_fields["history_position"]
                    or self._positive_int(item.get("history_duration"), 0) != resume_fields["history_duration"]
                    or str(item.get("history_vod_name") or "") != resume_fields["history_vod_name"]
                    or (resource_id and str(item.get("alist_vod_id") or "") != resource_id)
                    or (
                        "alist_resource_mode" in resume_fields
                        and str(item.get("alist_resource_mode") or "vod").strip().lower()
                        != resume_fields["alist_resource_mode"]
                    )
                    or (
                        "alist_resource_provider" in resume_fields
                        and self._resource_provider_key(item.get("alist_resource_provider"))
                        != resume_fields["alist_resource_provider"]
                    )
                )
                if history_changed:
                    resume_fields["history_updated_at"] = now
                    item.update(resume_fields)
                    if (
                            "alist_resource_provider" in resume_fields
                            and not resume_fields["alist_resource_provider"]):
                        item.pop("alist_resource_provider", None)
                    if resource_id and resource_id != previous_resource_id:
                        route = item.get("last_play_route") if isinstance(item.get("last_play_route"), dict) else {}
                        if str(route.get("resourceId") or "").strip() != resource_id:
                            item.pop("last_play_route", None)
                seen_changed = False
                if self._history_is_complete(history):
                    seen = str(item.get("seen_episode") or "")
                    if self._episode_rank(episode) > self._episode_rank(seen):
                        item["seen_episode"] = episode
                        item["seen_source"] = "history"
                        seen_changed = True
                if history_changed or seen_changed:
                    items[key] = item
                    if isinstance(changed_items, list):
                        changed_items.append(dict(item))
                    changed += 1
            if changed:
                self._save_follow_state(items)
            return changed

    def _append_atvp_progress(self, remark, history):
        progress = self._atvp_progress_text(history)
        return str(remark or "") + ((" · " + progress) if progress else "")

    def _append_follow_progress(self, remark, item, history):
        episode = self._history_episode_key(item, history) if history else ""
        if not episode and isinstance(item, dict):
            episode = str(item.get("history_episode") or "")
        if not episode:
            base = self._append_atvp_progress(remark, history)
        else:
            progress = history if isinstance(history, dict) else item
            position_key = "position" if isinstance(history, dict) else "history_position"
            duration_key = "duration" if isinstance(history, dict) else "history_duration"
            position = self._bounded_int(progress.get(position_key), 0, 0, 2147483647000)
            duration = self._bounded_int(progress.get(duration_key), 0, 0, 2147483647000)
            time_text = self._format_millis(position)
            if time_text and duration > 0:
                time_text += "/" + self._format_millis(duration)
            completed = self._history_is_complete({"position": position, "duration": duration})
            progress_parts = ["已观看 " + episode if completed else "观看到 " + episode]
            if completed:
                progress_parts.append("播放完成")
            elif time_text:
                progress_parts.append("播放进度 " + time_text)
            base = str(remark or "") + " · " + " · ".join(progress_parts)

        details = []
        latest = str(item.get("latest_episode") or "") if isinstance(item, dict) else ""
        if latest and latest not in str(remark or ""):
            details.append("更新至 " + latest)
        next_date = str(item.get("next_air_date") or "") if isinstance(item, dict) else ""
        if next_date and next_date not in str(remark or ""):
            details.append("下一级更新时间 " + next_date)
        if details:
            base += " · " + " · ".join(details)
        return base

    def _atvp_progress_text(self, history):
        if not isinstance(history, dict):
            return ""
        label = str(history.get("vodRemarks") or "").strip()
        if len(label) > 24:
            label = label[:24]
        episode = self._bounded_int(history.get("episode"), -1, -1, 100000)
        if not label and episode >= 0:
            label = "第%s项" % (episode + 1)
        position = self._bounded_int(history.get("position"), 0, 0, 2147483647000)
        duration = self._bounded_int(history.get("duration"), 0, 0, 2147483647000)
        time_text = self._format_millis(position)
        if time_text and duration > 0:
            time_text += "/" + self._format_millis(duration)
        parts = [value for value in (label, time_text) if value]
        return ("AList进度 " + " ".join(parts)) if parts else ""

    def _history_effective_seen(self, item, history):
        explicit = str(item.get("seen_episode") or "") if isinstance(item, dict) else ""
        played = self._history_episode_key(item, history)
        if played and self._history_is_complete(history) and self._episode_rank(played) > self._episode_rank(explicit):
            return played
        return explicit

    def _follow_update_baseline(self, item, history=None):
        seen = self._history_effective_seen(item, history)
        tracked = str(item.get("tracked_episode") or "") if isinstance(item, dict) else ""
        return seen if self._episode_rank(seen) >= self._episode_rank(tracked) else tracked

    def _history_episode_key(self, item, history):
        if not isinstance(item, dict) or not isinstance(history, dict):
            return ""
        payload = self._history_followplay_payload(history)
        if payload:
            season = self._positive_int(payload.get("season"), 0)
            episode = self._positive_int(payload.get("episode"), 0)
            if season and episode:
                return "S%02dE%02d" % (season, episode)
        text = " ".join(str(history.get(key) or "") for key in ("vodFlag", "vodRemarks", "episodeUrl", "vodName"))
        season, episode, _explicit = Filter._episode(text)
        if season and episode:
            return "S%02dE%02d" % (season, episode)
        match = re.search(r"(?i)S0*(\d{1,2})\s*E(?:P)?0*(\d{1,3})", text)
        if match:
            return "S%02dE%02d" % (int(match.group(1)), int(match.group(2)))
        match = re.search(r"第\s*(\d{1,2})\s*季.*?第\s*(\d{1,3})\s*[集话]", text)
        if match:
            return "S%02dE%02d" % (int(match.group(1)), int(match.group(2)))

        season_match = re.search(r"(?i)(?:S0*|第\s*)(\d{1,2})(?:\s*季)?", str(history.get("vodFlag") or ""))
        episode_match = re.search(r"(?i)(?:\bEP?\s*0*|第\s*)(\d{1,3})(?:\s*[集话])?", str(history.get("vodRemarks") or ""))
        if not episode_match:
            return ""
        season = int(season_match.group(1)) if season_match else 0
        latest_match = re.match(r"^S(\d{2})E\d{2,3}$", str(item.get("latest_episode") or ""))
        latest_season = int(latest_match.group(1)) if latest_match else 0
        if not season and latest_season == 1:
            season = 1
        return ("S%02dE%02d" % (season, int(episode_match.group(1)))) if season else ""

    @staticmethod
    def _history_is_complete(history):
        if not isinstance(history, dict):
            return False
        try:
            position = max(0, int(history.get("position") or 0))
            duration = max(0, int(history.get("duration") or 0))
        except Exception:
            return False
        return duration > 0 and position > 0 and (float(position) / duration >= 0.9 or duration - position <= 180000)

    @staticmethod
    def _history_can_resume(history):
        if not isinstance(history, dict):
            return False
        try:
            position = int(history.get("position") or 0)
            duration = int(history.get("duration") or 0)
        except Exception:
            return False
        return 0 < position < duration

    @staticmethod
    def _normalize_media_title(value):
        text = unicodedata.normalize("NFKC", str(value or "")).casefold()
        return re.sub(r"[\W_]+", "", text, flags=re.UNICODE)

    @staticmethod
    def _format_millis(value):
        try:
            seconds = max(0, int(value) // 1000)
        except Exception:
            return ""
        if seconds <= 0:
            return ""
        hours, remainder = divmod(seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        if hours:
            return "%d:%02d:%02d" % (hours, minutes, seconds)
        return "%d:%02d" % (minutes, seconds)

    def _has_follow_update(self, item, history=None):
        return self._episode_rank(item.get("latest_episode")) > self._episode_rank(self._follow_update_baseline(item, history))

    @staticmethod
    def _split_resource_vod_groups(vod):
        if not isinstance(vod, dict):
            return []
        sources, _sources_limited = _split_bounded_shared(
            vod.get("vod_play_from") or "AList资源", "$$$", PLAY_GROUP_SCAN_LIMIT,
        )
        urls, _urls_limited = _split_bounded_shared(
            vod.get("vod_play_url"), "$$$", PLAY_GROUP_SCAN_LIMIT,
        )
        list_fields = ("group_seasons", "group_providers", "group_quality")
        output = []
        for index, group_url in enumerate(urls):
            if not group_url:
                continue
            row = dict(vod)
            row["vod_play_from"] = sources[index] if index < len(sources) else "AList资源"
            row["vod_play_url"] = group_url
            for key in list_fields:
                values = vod.get(key) if isinstance(vod.get(key), list) else []
                row[key] = [values[index]] if index < len(values) else []
            output.append(row)
        return output

    def _alist_detail_from_metadata(self, raw_id, metadata):
        rows = metadata.get("list") if isinstance(metadata, dict) else None
        if not isinstance(rows, list) or not rows or not isinstance(rows[0], dict):
            return metadata
        base_vod = dict(rows[0])
        if (str(base_vod.get("vod_id") or "").startswith(self.ERROR_PREFIX)
                or str(base_vod.get("vod_name") or "").endswith("详情载入失败")):
            return metadata
        if not self._alist_tvbox_plugin:
            return {"list": [base_vod]}
        item = self._resource_item(raw_id, base_vod)
        item = dict(item)
        item["_resume_verified"] = False
        try:
            histories = self._atvp_history_snapshot(nonblocking=False)
            history = self._atvp_history_for_item(item, histories)
            resume_fields = self._history_resume_fields(item, history)
            if resume_fields:
                item.update(resume_fields)
                item["_resume_verified"] = self._history_can_resume(history)
        except Exception:
            pass
        try:
            ready = self._ready_resource_detail(raw_id, item, base_vod)
            if ready:
                return {"list": [ready]}
        except Exception:
            pass
        entry_preheat_pending = self._entry_resource_preheat_pending(item)
        try:
            resource_deadline = time.monotonic() + self.RESOURCE_FOREGROUND_BUDGET
            bound_resource = self._bound_resource_row(item)
            bound_resource_id = str((bound_resource or {}).get("vod_id") or "").strip()
            bound_groups = []
            preferred_resource_id = ""
            bound_invalidated = False
            if bound_resource:
                try:
                    cached_bound_detail = self._validated_resource_detail(bound_resource)
                    bound_detail = cached_bound_detail or self._resource_detail(
                        bound_resource, deadline=resource_deadline,
                    )
                    route = item.get("last_play_route") if isinstance(item.get("last_play_route"), dict) else {}
                    remembered_play_id = str(route.get("playId") or "").strip()
                    remembered_probe = self._route_probe_snapshot(
                        remembered_play_id,
                        bound_resource_id,
                        route.get("resourceMode") or bound_resource.get("_resource_mode") or "vod",
                    )
                    # A detail-page entry is allowed to use the long-lived
                    # resource metadata, but its active route is always
                    # re-issued and probed once on first open. This avoids
                    # treating a cached signed CDN URL as permanently valid.
                    validated_bound = self._validated_playable_detail(
                        bound_detail, item, resource_deadline, 1,
                        resource_id=bound_resource_id,
                        resource_mode=bound_resource.get("_resource_mode") or "vod",
                        preferred_route=route,
                        force_refresh=True,
                    )
                    bound_validated = bool(validated_bound)
                    bound_vod = self._payload_first_vod(validated_bound)
                    if not bound_vod:
                        raise RuntimeError("原绑定线路验活失败")
                    if bound_vod:
                        if bound_validated:
                            self._store_validated_resource_detail(bound_resource, validated_bound)
                            item["_bound_route_validated"] = True
                        rewritten = self._rewrite_resource_vod(
                            bound_vod, item, bound_resource_id,
                            mode=bound_resource.get("_resource_mode") or "vod",
                            provider_hint=self._resource_provider_key(
                                bound_resource.get("provider"), bound_vod.get("provider"),
                                bound_vod.get("type"), bound_vod.get("type_name"),
                                bound_vod.get("vod_remarks"), bound_resource_id,
                            ),
                            validated=True,
                        )
                        if rewritten:
                            rewritten["_resource_mode"] = bound_resource.get("_resource_mode") or "vod"
                            bound_groups.append(rewritten)
                            if bound_validated:
                                preferred_resource_id = bound_resource_id
                except Exception:
                    # A stale bound source is deliberately a soft failure; only now
                    # do we prepare independent replacement routes below.
                    if bound_resource_id:
                        self._schedule_bound_route_replacement(item, bound_resource_id)
                        bound_resource = None
                        bound_invalidated = True
            if entry_preheat_pending and bound_groups:
                merged = self._merge_resource_vods(
                    bound_groups, item, raw_id, base_vod,
                    preferred_resource_id=preferred_resource_id,
                )
                if merged:
                    return {"list": [merged]}
            candidates = self._resource_candidates(
                item, deadline=min(resource_deadline, time.monotonic() + self.RESOURCE_SEARCH_BUDGET),
            )
            collected_groups = []
            for group in bound_groups:
                collected_groups.extend(self._split_resource_vod_groups(group))
            resource_error = ""
            detail_deadline = resource_deadline
            for row in candidates[:self.RESOURCE_DETAIL_ATTEMPT_LIMIT]:
                if detail_deadline - time.monotonic() < 1:
                    resource_error = "AList 资源详情超过总时限"
                    break
                resource_id = str(row.get("vod_id") or row.get("id") or "").strip()
                if not resource_id:
                    continue
                if bound_resource_id and resource_id == bound_resource_id:
                    continue
                try:
                    detail = self._resource_detail(row, deadline=detail_deadline)
                    vod = self._payload_first_vod(detail)
                    if vod:
                        rewritten = self._rewrite_resource_vod(
                            vod, item, resource_id, mode=row.get("_resource_mode") or "vod",
                            provider_hint=self._resource_provider_key(
                                row.get("provider"), row.get("type"), row.get("type_name"),
                                row.get("vod_remarks"), row.get("source"), resource_id,
                            ),
                            validated=bool(
                                row.get("_validated_groups")
                                and self._validated_resource_detail(row) is not None
                            ),
                        )
                        if rewritten:
                            rewritten["_resource_mode"] = row.get("_resource_mode") or "vod"
                            collected_groups.extend(self._split_resource_vod_groups(rewritten))
                except Exception as exc:
                    resource_error = "AList 资源失败：%s" % self._short_error(exc)
                    continue
            groups = []
            selected_ids = set()
            selected_modes = set()
            for group in collected_groups:
                mode = str(group.get("_resource_mode") or "vod")
                if mode in selected_modes:
                    continue
                groups.append(group)
                selected_ids.add(id(group))
                selected_modes.add(mode)
            groups.extend(group for group in collected_groups if id(group) not in selected_ids)
            if not groups and bound_resource_id:
                self._schedule_bound_route_replacement(item, bound_resource_id)
            merged = self._merge_resource_vods(
                groups, item, raw_id, base_vod,
                preferred_resource_id=preferred_resource_id,
            )
            if merged:
                return {"list": [merged]}
            if bound_invalidated:
                return {"list": [self._resource_error_vod(
                    base_vod, "原绑定线路失效，后台备选线路验证中",
                )]}
            _ready, pending = self._supplement_resource_state(item)
            if pending:
                return {"list": [self._resource_error_vod(base_vod, "后台线路验证中，当前没有已就绪线路")]}
            if resource_error:
                return {"list": [self._resource_error_vod(base_vod, resource_error)]}
            return {"list": [self._resource_error_vod(base_vod, "没有通过盘检和播放验证的线路")]}
        except Exception as exc:
            return {"list": [self._resource_error_vod(base_vod, "AList 资源失败：%s" % self._short_error(exc))]}

    def _resource_item(self, raw_id, vod):
        raw = str(raw_id or "")
        tmdb_match = re.match(r"^tmdb:(movie|tv):(\d+)$", raw)
        title_parts = [part.strip() for part in str(vod.get("vod_name") or "").split(" / ") if part.strip()]
        media_type = tmdb_match.group(1) if tmdb_match else ("tv" if re.search(r"\d+\s*集", str(vod.get("vod_remarks") or "")) else "movie")
        tmdb_id = int(tmdb_match.group(2)) if tmdb_match else 0
        item = {
            "source_id": raw,
            "media_type": media_type,
            "tmdb_id": tmdb_id,
            "title": title_parts[0] if title_parts else str(vod.get("vod_name") or ""),
            "original_title": title_parts[1] if len(title_parts) > 1 else "",
            "pic": str(vod.get("vod_pic") or ""),
            "year": str(vod.get("vod_year") or "")[:4],
            "season_count": self._positive_int(vod.get("_season_count"), 0),
        }
        followed = (self._follow_memory.get("items") or {}).get(str(tmdb_id)) if tmdb_id else None
        if isinstance(followed, dict):
            enriched = dict(item)
            enriched.update({key: value for key, value in followed.items() if value not in (None, "")})
            enriched["source_id"] = raw
            enriched["media_type"] = media_type
            enriched["tmdb_id"] = tmdb_id
            return enriched
        return item

    def _bound_resource_row(self, item):
        binding_keys = [str(item.get("tmdb_id") or ""), str(item.get("source_id") or "")]
        resource_id = next((
            str(self.follow_alist_bindings.get(key) or "").strip()
            for key in binding_keys
            if key and str(self.follow_alist_bindings.get(key) or "").strip()
        ), "")
        resource_mode = str(item.get("alist_resource_mode") or "vod").strip().lower() or "vod"
        route = item.get("last_play_route") if isinstance(item.get("last_play_route"), dict) else {}
        route_backend = str(route.get("backend") or "")
        current_backend = self._resource_capability_identity()
        route_matches = not route_backend or route_backend == current_backend
        if not resource_id and route_matches:
            resource_id = str(route.get("resourceId") or "").strip()
            resource_mode = str(route.get("resourceMode") or "vod").strip().lower() or "vod"
        if not resource_id and (not route_backend or route_matches):
            resource_id = str(item.get("alist_vod_id") or "").strip()
        if (
                not resource_id
                or not self._resource_id_valid(resource_id, resource_mode)
                or resource_mode not in self.RESOURCE_SEARCH_MODES):
            return None
        route_resource_id = str(route.get("resourceId") or "").strip()
        item_resource_id = str(item.get("alist_vod_id") or "").strip()
        provider = self._resource_provider_key(
            route.get("resourceProvider") if route_matches and route_resource_id == resource_id else "",
            item.get("alist_resource_provider") if item_resource_id == resource_id else "",
            resource_id,
        )
        output = {
            "vod_id": resource_id,
            "vod_name": str(item.get("title") or ""),
            "_resource_mode": resource_mode,
            "_bound_route": True,
        }
        if provider:
            output["provider"] = provider
        return output

    def _bound_replacement_key(self, item, bound_resource_id):
        identity = str(item.get("tmdb_id") or item.get("source_id") or "").strip()
        backend = self._resource_capability_identity()
        raw = "%s|%s|%s" % (backend, identity, str(bound_resource_id or "").strip())
        return "bound-replacement:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _replace_bound_resource(
            self, item, row, expected_generation=None, expected_bound_resource_id=None,
            expected_item_resource_id=None):
        resource_id = str((row or {}).get("vod_id") or (row or {}).get("id") or "").strip()
        resource_mode = str((row or {}).get("_resource_mode") or "vod").strip().lower() or "vod"
        if (
                not resource_id
                or resource_mode not in self.RESOURCE_SEARCH_MODES
                or not self._resource_id_valid(resource_id, resource_mode)
        ):
            return False
        expected_bound = str(expected_bound_resource_id or "").strip()
        with self._history_context_lock:
            with self._cache_lock:
                if expected_generation is not None and expected_generation != self._cache_generation:
                    return False
            with self._follow_enrich_lock:
                items = self._follow_memory.get("items") if isinstance(self._follow_memory, dict) else {}
                if not isinstance(items, dict):
                    return False
                tmdb_id = str(self._positive_int(item.get("tmdb_id"), 0))
                source_id = str(item.get("source_id") or "").strip()
                item_key = tmdb_id if tmdb_id and tmdb_id in items else ""
                if not item_key and source_id:
                    item_key = next((
                        key for key, value in items.items()
                        if isinstance(value, dict) and str(value.get("source_id") or "") == source_id
                    ), "")
                if not item_key:
                    return False
                updated = dict(items.get(item_key) or {})
                if expected_item_resource_id is not None:
                    stored_resource_id = str(updated.get("alist_vod_id") or "").strip()
                    if stored_resource_id != str(expected_item_resource_id or "").strip():
                        return False
                if expected_bound:
                    stored_bound = str(updated.get("alist_vod_id") or "").strip()
                    route = updated.get("last_play_route") if isinstance(updated.get("last_play_route"), dict) else {}
                    route_bound = str(route.get("resourceId") or "").strip()
                    if stored_bound and stored_bound != expected_bound:
                        return False
                    if route_bound and route_bound != expected_bound:
                        return False
                    current_binding = self._bound_resource_row({
                        "tmdb_id": self._positive_int(updated.get("tmdb_id"), 0),
                        "source_id": str(updated.get("source_id") or source_id).strip(),
                        **updated,
                    })
                    current_bound = str((current_binding or {}).get("vod_id") or "").strip()
                    if current_bound != expected_bound:
                        return False
                if str(updated.get("alist_vod_id") or "").strip() == resource_id:
                    return False
                updated["alist_vod_id"] = resource_id
                updated["alist_resource_mode"] = resource_mode
                provider = self._resource_provider_key(
                    (row or {}).get("provider"), (row or {}).get("type"),
                    (row or {}).get("type_name"), (row or {}).get("vod_remarks"),
                    (row or {}).get("source"), resource_id,
                )
                if provider:
                    updated["alist_resource_provider"] = provider
                else:
                    updated.pop("alist_resource_provider", None)
                updated["binding_updated_at"] = int(time.time())
                route = updated.get("last_play_route") if isinstance(updated.get("last_play_route"), dict) else {}
                if expected_bound and str(route.get("resourceId") or "").strip() == expected_bound:
                    updated.pop("last_play_route", None)
                items = dict(items)
                items[item_key] = updated
                self._save_follow_state(items)
        return True

    def _schedule_bound_route_replacement(self, item, bound_resource_id):
        if not self._alist_tvbox_plugin or not isinstance(item, dict) or not bound_resource_id:
            return False
        job_key = self._bound_replacement_key(item, bound_resource_id)
        with self._cache_lock:
            if job_key in self._bound_replacement_jobs:
                return False
            job_owner = object()
            self._bound_replacement_jobs[job_key] = job_owner
            generation = self._cache_generation
        expected_item_resource_id = str(item.get("alist_vod_id") or "").strip()

        def worker():
            try:
                deadline = time.monotonic() + self.RESOURCE_HOT_VALIDATION_BUDGET
                candidates = self._resource_candidates(
                    dict(item), deadline=deadline, background=True,
                )
                candidates = [
                    dict(row) for row in candidates or []
                    if isinstance(row, dict)
                    and str(row.get("vod_id") or row.get("id") or "").strip()
                    and str(row.get("vod_id") or row.get("id") or "").strip() != str(bound_resource_id)
                ][:self.RESOURCE_HOT_VALIDATION_ATTEMPT_LIMIT]
                for row in candidates:
                    if deadline - time.monotonic() < 1:
                        break
                    with self._cache_lock:
                        if generation != self._cache_generation:
                            return
                    try:
                        detail = self._resource_detail(row, deadline=deadline, use_validated_cache=False)
                        validated = self._validated_playable_detail(
                            detail, item, deadline, 1,
                            resource_id=row.get("vod_id") or row.get("id"),
                            resource_mode=row.get("_resource_mode") or "vod",
                            preferred_route=item.get("last_play_route"),
                        )
                        if validated is None:
                            continue
                        checked_row = dict(row)
                        validated_vod = self._payload_first_vod(validated)
                        validated_groups, _limited = _split_bounded_shared(
                            (validated_vod or {}).get("vod_play_url"),
                            "$$$", self.RESOURCE_PLAY_GROUP_SCAN_LIMIT,
                        )
                        checked_row["_validated_groups"] = max(
                            1, len(validated_groups)
                        )
                        if not self._resource_detail_has_complete_target(validated, item):
                            continue
                        if not self._store_validated_resource_detail(
                                checked_row, validated, expected_generation=generation):
                            continue
                        if self._replace_bound_resource(
                                item, checked_row,
                                expected_generation=generation,
                                expected_bound_resource_id=bound_resource_id,
                                expected_item_resource_id=expected_item_resource_id):
                            self._schedule_active_detail_refresh(item)
                        return
                    except Exception:
                        continue
            finally:
                with self._cache_lock:
                    if self._bound_replacement_jobs.get(job_key) is job_owner:
                        self._bound_replacement_jobs.pop(job_key, None)

        try:
            self._tasks.start_thread(worker, name="bound-route-replacement")
        except Exception:
            with self._cache_lock:
                if self._bound_replacement_jobs.get(job_key) is job_owner:
                    self._bound_replacement_jobs.pop(job_key, None)
            return False
        return True

    def _bound_detail_contains_route(self, detail, route):
        if not isinstance(route, dict):
            return False
        play_id = str(route.get("playId") or "").strip()
        season = self._positive_int(route.get("season"), 0)
        episode = self._positive_int(route.get("episode"), 0)
        if not play_id or season <= 0 or episode <= 0:
            return False
        vod = self._payload_first_vod(detail)
        if not isinstance(vod, dict):
            return False
        groups, _groups_limited = _split_bounded_shared(
            vod.get("vod_play_url"), "$$$", self.RESOURCE_PLAY_GROUP_SCAN_LIMIT,
        )
        for group in groups:
            parts, _parts_limited = _split_bounded_shared(
                group, "#", self.RESOURCE_GROUP_EPISODE_LIMIT,
            )
            for index, part in enumerate(parts, 1):
                name, separator, target = part.rpartition("$")
                if not separator or str(target).strip() != play_id:
                    continue
                found_season, found_episode, explicit = self._episode_from_text_info(
                    name, index, season,
                )
                if explicit and (found_season, found_episode) == (season, episode):
                    return True
        return False

    def _resource_error_vod(self, vod, message):
        output = dict(vod)
        director = str(output.get("vod_director") or "").strip()
        status = "线路状态：" + str(message or "暂无可播放资源")
        output["vod_director"] = " · ".join(value for value in (director, status) if value)
        content = str(output.get("vod_content") or "").strip()
        output["vod_content"] = "\n\n".join(value for value in (content, "播放资源状态：" + str(message or "暂无可播放资源")) if value)
        output["vod_play_from"] = ""
        output["vod_play_url"] = ""
        output["vodFlags"] = []
        return output

    def _resource_capability_identity(self):
        api = str(self.atvp_api or "").rstrip("/")
        if not api:
            return ""
        raw = "%s|%s" % (api, Filter._token_hash(self.atvp_token))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _load_resource_capabilities(self):
        identity = self._resource_capability_identity()
        with self._cache_lock:
            if self._resource_capabilities_backend == identity:
                return
            self._resource_capabilities = {}
            self._resource_capabilities_backend = identity
            load_revision = self._resource_capabilities_revision
        if not self.resource_auto_discover or not identity:
            return
        getter = getattr(self, "getCache", None)
        if not callable(getter):
            return
        try:
            value = getter(self.RESOURCE_CAPABILITY_CACHE_KEY)
        except Exception:
            return
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except Exception:
                return
        if isinstance(value, dict) and isinstance(value.get("value"), dict):
            value = value.get("value")
        if not isinstance(value, dict) or value.get("version") != self.RESOURCE_CAPABILITY_VERSION:
            return
        if str(value.get("backend") or "") != identity:
            return
        now = int(time.time())
        modes = {}
        for mode, state in (value.get("modes") or {}).items():
            if mode not in self.RESOURCE_SEARCH_MODES or not isinstance(state, dict):
                continue
            checked_at = self._positive_int(state.get("checkedAt"), 0)
            if checked_at <= 0 or now - checked_at > self.resource_capability_ttl:
                continue
            status = self._positive_int(state.get("status"), 0)
            capability = str(state.get("state") or "")
            if capability in ("present", "missing"):
                modes[mode] = {"state": capability, "status": status, "checkedAt": checked_at}
        with self._cache_lock:
            if (
                    self._resource_capabilities_backend == identity
                    and self._resource_capabilities_revision == load_revision):
                self._resource_capabilities = modes

    def _save_resource_capabilities(self):
        setter = getattr(self, "setCache", None)
        if not callable(setter):
            return
        with self._cache_lock:
            payload = {
                "version": self.RESOURCE_CAPABILITY_VERSION,
                "backend": self._resource_capabilities_backend,
                "modes": {key: dict(value) for key, value in self._resource_capabilities.items()},
            }
        try:
            setter(self.RESOURCE_CAPABILITY_CACHE_KEY, payload)
        except Exception:
            pass

    def _mark_resource_capability(
            self, mode, state, status=0, expected_backend=None, expected_generation=None):
        if not self.resource_auto_discover or mode not in self.RESOURCE_SEARCH_MODES:
            return False
        if expected_backend is None:
            expected_backend = self._resource_capability_identity()
        self._load_resource_capabilities()
        capability = "missing" if state == "missing" else "present"
        with self._cache_lock:
            if expected_generation is not None and expected_generation != self._cache_generation:
                return False
            if (
                    expected_backend != self._resource_capability_identity()
                    or self._resource_capabilities_backend != expected_backend):
                return False
            self._resource_capabilities[mode] = {
                "state": capability,
                "status": self._positive_int(status, 0),
                "checkedAt": int(time.time()),
            }
            self._resource_capabilities_revision += 1
        self._save_resource_capabilities()
        return True

    def _resource_capability(self, mode):
        if not self.resource_auto_discover:
            return "unknown"
        self._load_resource_capabilities()
        with self._cache_lock:
            value = dict(self._resource_capabilities.get(mode) or {})
        checked_at = self._positive_int(value.get("checkedAt"), 0)
        if checked_at <= 0 or time.time() - checked_at > self.resource_capability_ttl:
            return "unknown"
        state = str(value.get("state") or "")
        return state if state in ("present", "missing") else "unknown"

    def _available_resource_modes(self):
        return [
            mode for mode in self.resource_search_modes
            if self._resource_capability(mode) != "missing"
        ]

    def _submit_resource_mode_search(self, mode, queries, deadline, background=False):
        if background:
            executor = self._resource_background_mode_executor
            slots = self._resource_background_mode_slots
            admitted = slots.acquire(False)
        else:
            executor = self._resource_foreground_mode_executor
            slots = self._resource_foreground_mode_slots
            remaining = (
                deadline - time.monotonic()
                if deadline is not None and math.isfinite(deadline)
                else self.RESOURCE_SEARCH_BUDGET
            )
            admitted = remaining > 0 and slots.acquire(timeout=remaining)
        if not admitted:
            return None

        release_lock = threading.Lock()
        released = [False]

        def release_once():
            with release_lock:
                if released[0]:
                    return
                released[0] = True
            slots.release()

        def worker():
            try:
                return self._resource_search_mode(mode, queries, deadline)
            finally:
                release_once()

        try:
            future = executor.submit(worker)
            future.add_done_callback(lambda _future: release_once())
            return future
        except Exception:
            release_once()
            return None

    def _resource_candidates(self, item, deadline=None, background=False):
        started_at = time.monotonic()
        title = str(item.get("title") or "").strip()
        if not title:
            return []
        rows = []
        query_titles = [title] + self._follow_title_alias_values(item, include_primary=False)
        modes = list(self._available_resource_modes())
        mode_rows = {}
        foreground_modes = [mode for mode in modes if mode not in self.RESOURCE_SUPPLEMENT_MODES]
        supplement_modes = [mode for mode in modes if mode in self.RESOURCE_SUPPLEMENT_MODES]
        sync_supplement_modes = False
        if supplement_modes:
            cache_key = self._resource_search_cache_key(item, "supplement")
            cached = self._cache_get(cache_key, self.RESOURCE_SEARCH_CACHE_TTL)
            cached_rows = cached if isinstance(cached, list) else []
            for row in list(cached)[:self.RESOURCE_HOT_ROUTE_LIMIT] if isinstance(cached, list) else []:
                if isinstance(row, dict):
                    mode_rows.setdefault(str(row.get("_resource_mode") or "pansou"), []).append(row)
            # A successful hot update is already authoritative for this cache TTL.
            # Do not let the DETAIL refresh it just triggered create a new refresh loop.
            if self._validated_resource_group_count(cached_rows) <= 0:
                sync_supplement_modes = not cached_rows
                if not sync_supplement_modes:
                    self._schedule_supplement_resource_search(
                        supplement_modes, query_titles[:2], item, cache_key,
                    )
        if sync_supplement_modes:
            foreground_modes.extend(mode for mode in supplement_modes if mode not in foreground_modes)

        deadline = min(
            deadline if deadline is not None else float("inf"),
            time.monotonic() + self.RESOURCE_SEARCH_BUDGET,
        )
        futures = {}
        try:
            if foreground_modes:
                futures = {}
                for mode in foreground_modes:
                    future = self._submit_resource_mode_search(
                        mode, query_titles[:2], deadline, background=background,
                    )
                    if future is None:
                        mode_rows.setdefault(mode, [])
                    else:
                        futures[future] = mode
            if futures:
                try:
                    for future in as_completed(futures, timeout=max(0.1, deadline - time.monotonic())):
                        mode = futures[future]
                        try:
                            mode_rows[mode] = future.result()
                        except Exception:
                            mode_rows[mode] = []
                except FuturesTimeoutError:
                    pass
        finally:
            for future, mode in futures.items():
                if not future.done():
                    future.cancel()
                    mode_rows.setdefault(mode, [])
        for mode in sorted(modes, key=lambda value: self.RESOURCE_MODE_PRIORITY.get(value, 99)):
            for value in mode_rows.get(mode) or []:
                if isinstance(value, dict):
                    row = dict(value)
                    row.setdefault("_resource_mode", mode)
                    rows.append(row)
        binding_keys = [str(item.get("tmdb_id") or ""), str(item.get("source_id") or "")]
        bound = ""
        for key in binding_keys:
            if key and str(self.follow_alist_bindings.get(key) or "").strip():
                bound = str(self.follow_alist_bindings.get(key)).strip()
                break
        if not bound:
            bound = str(item.get("alist_vod_id") or "").strip()
        if bound and all(str(row.get("vod_id") or row.get("id") or "") != bound for row in rows):
            rows.append({"vod_id": bound, "vod_name": title, "_resource_mode": "vod"})
        ordered = self._resource_fair_candidate_order(
            rows,
            item,
            bound=bound,
            modes=sorted(modes, key=lambda value: self.RESOURCE_MODE_PRIORITY.get(value, 99)),
        )
        self._diagnostic_event(
            "resource_candidates.finish", "INFO" if ordered else "WARN",
            duration_ms=int((time.monotonic() - started_at) * 1000),
            count=len(ordered), background=background,
        )
        return ordered

    def _resource_search_cache_key(self, item, mode):
        identity = str(item.get("tmdb_id") or item.get("source_id") or self._normalize_media_title(item.get("title")) or "")
        raw = "%s|%s|%s|%s" % (
            self.atvp_api.rstrip("/"), Filter._token_hash(self.atvp_token), mode, identity,
        )
        return "resource-search:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _entry_resource_preheat_key(self, item):
        raw = "%s|%s" % (
            self._resource_search_cache_key(item, "entry-preheat"),
            self._resource_target_episode(item),
        )
        return "resource-search:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _resource_target_episode(self, item):
        """Return the furthest known season/episode required by a cached route."""
        if not isinstance(item, dict):
            return ""
        candidates = []
        for key in ("latest_episode", "history_episode", "seen_episode", "tracked_episode"):
            value = str(item.get(key) or "").strip()
            if re.match(r"^S0*\d{1,2}E0*\d{1,3}$", value, re.I):
                candidates.append(value)
        route = item.get("last_play_route") if isinstance(item.get("last_play_route"), dict) else {}
        route_season = self._positive_int(route.get("season"), 0)
        route_episode = self._positive_int(route.get("episode"), 0)
        if route_season and route_episode:
            candidates.append("S%02dE%02d" % (route_season, route_episode))
        return max(candidates, key=self._episode_rank) if candidates else ""

    def _resource_detail_covers_target(self, detail, item):
        target = self._resource_target_episode(item)
        if not target or str((item or {}).get("media_type") or "tv") == "movie":
            return True
        match = re.match(r"^S0*(\d{1,2})E0*(\d{1,3})$", target, re.I)
        if not match:
            return True
        target_key = (int(match.group(1)), int(match.group(2)))
        vod = self._payload_first_vod(detail)
        if not isinstance(vod, dict):
            return False
        groups, _limited = _split_bounded_shared(
            vod.get("vod_play_url"), "$$$", self.RESOURCE_PLAY_GROUP_SCAN_LIMIT,
        )
        for group in groups:
            parts, _parts_limited = _split_bounded_shared(
                group, "#", self.RESOURCE_GROUP_EPISODE_LIMIT,
            )
            for index, part in enumerate(parts, 1):
                name, separator, play_id = part.rpartition("$")
                if not separator or not play_id:
                    continue
                payload = self._parse_followplay(play_id)
                if payload:
                    season = self._positive_int(payload.get("season"), 0)
                    episode = self._positive_int(payload.get("episode"), 0)
                    explicit = payload.get("episodeExplicit") is not False
                else:
                    season, episode, explicit = self._episode_from_text_info(
                        name, index, self._tracking_season(item),
                    )
                if explicit and (season, episode) == target_key:
                    return True
        return False

    def _resource_detail_has_complete_target(self, detail, item):
        target = self._resource_target_episode(item)
        if not target or str((item or {}).get("media_type") or "tv") == "movie":
            return True
        match = re.match(r"^S0*(\d{1,2})E0*(\d{1,3})$", target, re.I)
        if not match:
            return True
        target_season = int(match.group(1))
        target_episode = int(match.group(2))
        vod = self._payload_first_vod(detail)
        if not isinstance(vod, dict):
            return False
        groups, _limited = _split_bounded_shared(
            vod.get("vod_play_url"), "$$$", self.RESOURCE_PLAY_GROUP_SCAN_LIMIT,
        )
        coverage_item = dict(item or {})
        coverage_item["latest_episode"] = "S%02dE%02d" % (target_season, target_episode)
        for group in groups:
            complete, contains_target, _count, contiguous = self._resource_group_episode_coverage(
                group, coverage_item,
            )
            if complete and contains_target and contiguous >= target_episode:
                return True
        return False

    @staticmethod
    def _compact_ready_resource_row(row):
        if not isinstance(row, dict):
            return None
        output = {}
        for key in (
                "vod_id", "id", "vod_name", "name", "vod_remarks", "type_name", "type",
                "provider", "source", "_resource_mode", "_validated_groups"):
            value = row.get(key)
            if value not in (None, "") and not isinstance(value, (dict, list, tuple, set)):
                output[key] = value
        resource_id = str(output.get("vod_id") or output.get("id") or "").strip()
        if not resource_id:
            return None
        return output

    def _cache_ready_resource_rows(
            self, item, rows, expected_generation=None, cache_key=None):
        compact = []
        target_row = None
        covers_target = False
        for row in rows or []:
            value = self._compact_ready_resource_row(row)
            detail = self._validated_resource_detail(value)
            if value is None or detail is None:
                continue
            if self._resource_detail_has_complete_target(detail, item):
                covers_target = True
                target_row = value
            if len(compact) < self.RESOURCE_HOT_ROUTE_LIMIT:
                compact.append(value)
        if target_row is not None and all(
                str(row.get("vod_id") or row.get("id") or "")
                != str(target_row.get("vod_id") or target_row.get("id") or "")
                for row in compact):
            if compact:
                compact[-1] = target_row
            else:
                compact.append(target_row)
        if not compact or not covers_target:
            return False
        frozen_key = str(cache_key or self._entry_resource_preheat_key(item))
        with self._cache_lock:
            if expected_generation is not None and expected_generation != self._cache_generation:
                return False
            self._cache_set(frozen_key, compact)
        return True

    def _ready_resource_rows(self, item):
        cached = self._cache_get(
            self._entry_resource_preheat_key(item), self.RESOURCE_SEARCH_CACHE_TTL,
        )
        if not isinstance(cached, list):
            return []
        ready = []
        covers_target = False
        for row in cached[:self.RESOURCE_HOT_ROUTE_LIMIT]:
            value = self._compact_ready_resource_row(row)
            detail = self._validated_resource_detail(value)
            if value is None or detail is None:
                continue
            covers_target = covers_target or self._resource_detail_has_complete_target(detail, item)
            ready.append(value)
        return ready if covers_target else []

    def _target_covering_resource_row(self, rows, item):
        for row in rows or []:
            detail = self._validated_resource_detail(row)
            if detail is not None and self._resource_detail_has_complete_target(detail, item):
                return row
        return None

    def _entry_resource_preheat_pending(self, item):
        key = self._entry_resource_preheat_key(item)
        with self._cache_lock:
            return key in self._resource_entry_preheat_jobs

    def _ready_resource_detail(self, raw_id, item, base_vod):
        groups = []
        for row in self._ready_resource_rows(item):
            detail = self._validated_resource_detail(row)
            vod = self._payload_first_vod(detail)
            if not vod:
                continue
            # Long-lived cache stores resource IDs and play IDs, never trust
            # its previous signed output on a fresh detail open. Re-issue the
            # preferred episode once so an expired CDN URL is replaced before
            # the client renders the detail page.
            preferred_route = (
                item.get("last_play_route")
                if isinstance(item.get("last_play_route"), dict) else None
            )
            refresh_limit = max(
                1,
                min(
                    self.RESOURCE_HOT_ROUTE_LIMIT,
                    self._positive_int(row.get("_validated_groups"), 1),
                ),
            )
            refreshed = None
            try:
                refreshed = self._validated_playable_detail(
                    detail,
                    item,
                    time.monotonic() + self.RESOURCE_FOREGROUND_BUDGET,
                    refresh_limit,
                    resource_id=row.get("vod_id") or row.get("id") or "",
                    resource_mode=row.get("_resource_mode") or "vod",
                    preferred_route=preferred_route,
                    force_refresh=True,
                )
            except Exception:
                refreshed = None
            if refreshed and not self._resource_detail_has_complete_target(refreshed, item):
                refreshed = None
            if refreshed and preferred_route and not self._bound_detail_contains_route(
                    refreshed, preferred_route):
                refreshed = None
            if refreshed:
                detail = refreshed
                vod = self._payload_first_vod(detail)
                self._store_validated_resource_detail(row, detail)
            elif preferred_route:
                if not self._bound_detail_contains_route(detail, preferred_route):
                    # A remembered route that cannot be re-issued and is no
                    # longer present in this snapshot must be replaced.
                    continue
            rewritten = self._rewrite_resource_vod(
                vod, item, row.get("vod_id") or row.get("id"),
                mode=row.get("_resource_mode") or "vod",
                provider_hint=self._resource_provider_key(
                    row.get("provider"), row.get("type"), row.get("type_name"),
                    row.get("vod_remarks"), row.get("source"),
                    row.get("vod_id") or row.get("id"),
                ),
                validated=True,
            )
            if not rewritten:
                continue
            rewritten["_resource_mode"] = row.get("_resource_mode") or "vod"
            groups.extend(self._split_resource_vod_groups(rewritten))
        if not groups:
            return None
        return self._merge_resource_vods(
            groups, item, raw_id, base_vod,
            preferred_resource_id=str(item.get("alist_vod_id") or "").strip(),
        )

    def _schedule_entry_resource_preheat(self, items=None, page=1):
        if (
                not self._alist_tvbox_plugin
                or not self.route_preheat
                or not self.atvp_api
                or not self.atvp_token
                or self._atvp_session is None):
            return False
        source_items = list(items or (self._follow_memory.get("items") or {}).values())
        source_items = [dict(item) for item in source_items if isinstance(item, dict) and item.get("title")]
        for item in source_items:
            tmdb_id = self._positive_int(item.get("tmdb_id"), 0)
            if tmdb_id and not item.get("source_id"):
                item["source_id"] = "tmdb:tv:%s" % tmdb_id
            if tmdb_id and not item.get("media_type"):
                item["media_type"] = "tv"
        if items is None and page > 1:
            start = (self._positive_int(page, 1) - 1) * self.follow_page_size
            source_items = source_items[start:start + self.follow_page_size]
        source_items.sort(key=lambda item: (
            0 if str(item.get("alist_vod_id") or "").strip() else 1,
            0 if self._has_follow_update(item) else 1,
            str(item.get("next_air_date") or "9999"),
            str(item.get("title") or ""),
        ))
        scheduled = False
        for item in source_items[:self.RESOURCE_ENTRY_PREHEAT_LIMIT]:
            if self._ready_resource_rows(item):
                continue
            key = self._entry_resource_preheat_key(item)
            with self._cache_lock:
                if key in self._resource_entry_preheat_jobs:
                    continue
                if len(self._resource_entry_preheat_jobs) >= self.RESOURCE_ENTRY_PREHEAT_LIMIT:
                    break
                owner = object()
                generation = self._cache_generation
                self._resource_entry_preheat_jobs[key] = owner
            expected_resource_id = str(item.get("alist_vod_id") or "").strip()

            def worker(
                    source_item=item, cache_key=key, job_owner=owner,
                    expected_generation=generation, expected_bound=expected_resource_id):
                first_refreshed_groups = 0
                try:
                    deadline = time.monotonic() + self.RESOURCE_HOT_VALIDATION_BUDGET
                    candidates = self._resource_candidates(
                        source_item, deadline=deadline, background=True,
                    )
                    candidates = self._checked_resource_rows(
                        candidates[:self.RESOURCE_HOT_VALIDATION_ATTEMPT_LIMIT], deadline,
                    )

                    def publish_partial(current):
                        nonlocal first_refreshed_groups
                        if self._cache_ready_resource_rows(
                                source_item, current,
                                expected_generation=expected_generation,
                                cache_key=cache_key):
                            group_count = self._validated_resource_group_count(current)
                            if group_count > 0 and first_refreshed_groups <= 0:
                                first_refreshed_groups = group_count
                                self._schedule_active_detail_refresh(source_item)

                    all_playable = self._playable_resource_rows(
                        candidates, source_item, deadline,
                        expected_generation=expected_generation,
                        on_update=publish_partial,
                    )
                    target_row = self._target_covering_resource_row(all_playable, source_item)
                    playable = list(all_playable[:self.RESOURCE_HOT_ROUTE_LIMIT])
                    if target_row is not None and all(
                            str(row.get("vod_id") or row.get("id") or "")
                            != str(target_row.get("vod_id") or target_row.get("id") or "")
                            for row in playable):
                        if playable:
                            playable[-1] = target_row
                        else:
                            playable = [target_row]
                    if self._cache_ready_resource_rows(
                            source_item, playable,
                            expected_generation=expected_generation,
                            cache_key=cache_key):
                        target_row = self._target_covering_resource_row(playable, source_item)
                        if target_row and (
                                not expected_bound
                                or str(target_row.get("vod_id") or target_row.get("id") or "").strip()
                                != expected_bound):
                            self._replace_bound_resource(
                                source_item, target_row,
                                expected_generation=expected_generation,
                                expected_bound_resource_id=expected_bound or None,
                                expected_item_resource_id=expected_bound,
                            )
                        final_group_count = self._validated_resource_group_count(playable)
                        if final_group_count > first_refreshed_groups:
                            self._schedule_active_detail_refresh(source_item)
                except Exception:
                    pass
                finally:
                    with self._cache_lock:
                        if self._resource_entry_preheat_jobs.get(cache_key) is job_owner:
                            self._resource_entry_preheat_jobs.pop(cache_key, None)

            try:
                self._resource_search_executor.submit(worker)
                scheduled = True
            except Exception:
                with self._cache_lock:
                    if self._resource_entry_preheat_jobs.get(key) is owner:
                        self._resource_entry_preheat_jobs.pop(key, None)
        return scheduled

    def _schedule_supplement_resource_search(self, modes, queries, item, cache_key):
        with self._cache_lock:
            if cache_key in self._resource_search_jobs:
                return False
            if self._resource_search_admissions >= self.RESOURCE_HOT_JOB_LIMIT + self.RESOURCE_HOT_JOB_QUEUE_LIMIT:
                return False
            generation = self._cache_generation
            job_id = object()
            self._refreshing_cache_keys[cache_key] = job_id
            self._resource_search_jobs[cache_key] = job_id
            self._resource_search_admissions += 1

        def worker():
            try:
                with self._cache_lock:
                    if generation != self._cache_generation:
                        return
                total_deadline = time.monotonic() + self.RESOURCE_HOT_VALIDATION_BUDGET
                search_deadline = min(
                    total_deadline, time.monotonic() + self.RESOURCE_SEARCH_BUDGET,
                )
                candidates = []
                search_futures = {}
                for mode in modes:
                    future = self._submit_resource_mode_search(
                        mode, queries, search_deadline, background=True,
                    )
                    if future is not None:
                        search_futures[future] = mode
                try:
                    completed = as_completed(
                        search_futures, timeout=max(0.1, search_deadline - time.monotonic()),
                    ) if search_futures else []
                    for future in completed:
                        mode = search_futures[future]
                        try:
                            rows = future.result()
                        except Exception:
                            rows = []
                        for row in rows:
                            row = dict(row)
                            row.setdefault("_resource_mode", mode)
                            candidates.append(row)
                except FuturesTimeoutError:
                    pass
                finally:
                    for future in search_futures:
                        if not future.done():
                            future.cancel()
                with self._cache_lock:
                    if generation != self._cache_generation:
                        return
                candidates = self._resource_fair_candidate_order(
                    candidates,
                    item,
                    modes=sorted(modes, key=lambda value: self.RESOURCE_MODE_PRIORITY.get(value, 99)),
                )
                checked = self._checked_resource_rows(
                    candidates[:self.RESOURCE_HOT_ROUTE_LIMIT * 3], total_deadline,
                )
                validation_deadline = total_deadline
                first_refreshed_groups = 0

                def publish_partial(current):
                    nonlocal first_refreshed_groups
                    with self._cache_lock:
                        active = (
                            generation == self._cache_generation
                            and self._resource_search_jobs.get(cache_key) is job_id
                        )
                        if active:
                            self._cache_set(cache_key, current[:self.RESOURCE_HOT_ROUTE_LIMIT])
                    if active:
                        group_count = self._validated_resource_group_count(current)
                        if group_count > 0 and first_refreshed_groups <= 0:
                            first_refreshed_groups = group_count
                            self._schedule_active_detail_refresh(item)
                playable = self._playable_resource_rows(
                    checked, item, validation_deadline, expected_generation=generation,
                    on_update=publish_partial,
                )[:self.RESOURCE_HOT_ROUTE_LIMIT]
                with self._cache_lock:
                    committed = (
                        generation == self._cache_generation
                        and self._resource_search_jobs.get(cache_key) is job_id
                    )
                    if committed:
                        self._cache_set(cache_key, playable)
                if committed:
                    final_group_count = self._validated_resource_group_count(playable)
                    if final_group_count > first_refreshed_groups:
                        self._schedule_active_detail_refresh(item)
            except Exception:
                pass
            finally:
                with self._cache_lock:
                    if self._resource_search_jobs.get(cache_key) is job_id:
                        self._resource_search_jobs.pop(cache_key, None)
                        if self._refreshing_cache_keys.get(cache_key) is job_id:
                            self._refreshing_cache_keys.pop(cache_key, None)
                    self._resource_search_admissions = max(0, self._resource_search_admissions - 1)

        try:
            self._resource_search_executor.submit(worker)
        except Exception:
            with self._cache_lock:
                if self._resource_search_jobs.get(cache_key) is job_id:
                    self._resource_search_jobs.pop(cache_key, None)
                    if self._refreshing_cache_keys.get(cache_key) is job_id:
                        self._refreshing_cache_keys.pop(cache_key, None)
                self._resource_search_admissions = max(0, self._resource_search_admissions - 1)
            return False
        return True

    def _checked_resource_rows(self, rows, deadline=None):
        selected = []
        positions = {}
        items = []
        for row in rows or []:
            resource_id = str(row.get("vod_id") or row.get("id") or row.get("url") or "").strip()
            target = unquote(resource_id)
            if target.startswith("push://"):
                target = target[7:].strip()
            if not target or len(target) > self.FOLLOWPLAY_MAX_URL_LENGTH:
                continue
            try:
                parsed = urlparse(target)
                host = (parsed.hostname or "").lower()
                port = parsed.port
            except Exception:
                continue
            checkable = target.startswith(("magnet:", "ed2k:")) or (
                parsed.scheme in ("http", "https")
                and port in (None, 80, 443)
                and not parsed.username and not parsed.password
                and any(host == suffix or host.endswith("." + suffix) for suffix in self.RESOURCE_CHECK_LINK_HOSTS)
            )
            identity = self._resource_row_identity(row)
            if not checkable or not identity:
                continue
            if identity in positions:
                index = positions[identity]
                current_target, _current_row = selected[index]
                if self._resource_url_password_score(target) <= self._resource_url_password_score(current_target):
                    continue
                selected[index] = (target, row)
                items[index] = {"url": target}
                continue
            positions[identity] = len(selected)
            selected.append((target, row))
            items.append({"url": target})
        if not items or not self._ensure_atvp_connection(force=True):
            return []
        response = self._atvp_session.post(
            self._atvp_endpoint("check-links"),
            json={"items": items},
            headers={"Accept": "application/json", "X-CLIENT": "com.fongmi.android.tv"},
            timeout=self._atvp_deadline_timeout(
                deadline, max(5, min(12, self.timeout)), requests_left=1,
            ),
            verify=self.verify_tls,
            stream=True,
        )
        if response.status_code < 200 or response.status_code >= 300:
            closer = getattr(response, "close", None)
            if callable(closer):
                closer()
            return []
        try:
            payload = self._read_bounded_json_response(response, "AList check-links", deadline=deadline)
        except Exception:
            return []
        states = {}
        if isinstance(payload, dict):
            for entry in payload.get("results") or []:
                if not isinstance(entry, dict):
                    continue
                identity = self._resource_row_identity(entry.get("url"))
                if identity:
                    states[identity] = str(entry.get("state") or "").lower()
        return [
            row for target, row in selected
            if states.get(self._resource_row_identity(target)) == "ok"
        ]

    def _playable_resource_rows(
            self, rows, item, deadline=None, expected_generation=None, on_update=None):
        playable = []
        contexts = []
        for row in list(rows or [])[:self.RESOURCE_HOT_VALIDATION_ATTEMPT_LIMIT]:
            remaining = self.resource_limit - self._validated_resource_group_count(playable)
            if remaining <= 0:
                break
            if deadline is not None and deadline - time.monotonic() < 1:
                break
            try:
                detail = self._resource_detail(row, deadline=deadline, use_validated_cache=False)
                validated_detail = self._validated_playable_detail(
                    detail, item, deadline, 1,
                    resource_id=row.get("vod_id") or row.get("id"),
                    resource_mode=row.get("_resource_mode") or "vod",
                )
                if validated_detail is None:
                    continue
                checked_row = dict(row)
                validated_vod = self._payload_first_vod(validated_detail)
                validated_groups, _limited = _split_bounded_shared(
                    (validated_vod or {}).get("vod_play_url"),
                    "$$$", self.RESOURCE_PLAY_GROUP_SCAN_LIMIT,
                )
                checked_row["_validated_groups"] = len(validated_groups)
                if not self._store_validated_resource_detail(
                        checked_row, validated_detail, expected_generation=expected_generation):
                    continue
                playable.append(checked_row)
                contexts.append((checked_row, detail))
                if callable(on_update):
                    on_update(list(playable))
            except Exception:
                # Missing/expired CK and provider parse failures are intentionally fail-closed.
                continue
        while self._validated_resource_group_count(playable) < self.resource_limit:
            grew = False
            for checked_row, detail in contexts:
                remaining = self.resource_limit - self._validated_resource_group_count(playable)
                if remaining <= 0:
                    break
                if deadline is not None and deadline - time.monotonic() < 1:
                    return playable
                current_groups = self._positive_int(checked_row.get("_validated_groups"), 0)
                try:
                    expanded_detail = self._validated_playable_detail(
                        detail, item, deadline, current_groups + 1,
                        resource_id=checked_row.get("vod_id") or checked_row.get("id"),
                        resource_mode=checked_row.get("_resource_mode") or "vod",
                    )
                    expanded_vod = self._payload_first_vod(expanded_detail)
                    expanded_groups, _limited = _split_bounded_shared(
                        (expanded_vod or {}).get("vod_play_url"),
                        "$$$", self.RESOURCE_PLAY_GROUP_SCAN_LIMIT,
                    )
                    if len(expanded_groups) <= current_groups:
                        continue
                    checked_row["_validated_groups"] = len(expanded_groups)
                    if not self._store_validated_resource_detail(
                            checked_row, expanded_detail,
                            expected_generation=expected_generation):
                        checked_row["_validated_groups"] = current_groups
                        continue
                    grew = True
                    if callable(on_update):
                        on_update(list(playable))
                except Exception:
                    continue
            if not grew:
                break
        return playable

    @staticmethod
    def _validated_resource_group_count(rows):
        return sum(max(0, Spider._positive_int(row.get("_validated_groups"), 0)) for row in rows or [])

    def _validated_playable_detail(
            self, detail, item, deadline, max_groups, resource_id="", resource_mode="vod",
            preferred_route=None, force_refresh=False):
        vod = self._payload_first_vod(detail)
        if not isinstance(vod, dict) or max_groups <= 0:
            return None
        sources, _sources_limited = _split_bounded_shared(
            vod.get("vod_play_from") or "AList资源", "$$$", self.RESOURCE_PLAY_GROUP_SCAN_LIMIT,
        )
        urls, _urls_limited = _split_bounded_shared(
            vod.get("vod_play_url"), "$$$", self.RESOURCE_PLAY_GROUP_SCAN_LIMIT,
        )
        kept_sources = []
        kept_urls = []
        kept_quality = []
        route = preferred_route if isinstance(preferred_route, dict) else {}
        preferred_play_id = str(route.get("playId") or "").strip()
        preferred_season = self._positive_int(route.get("season"), 0)
        preferred_episode = self._positive_int(route.get("episode"), 0)
        preferred_mode = str(route.get("resourceMode") or "vod").strip().lower() or "vod"

        def preferred_route_matches_group(group):
            if (
                    not preferred_play_id
                    or str(route.get("resourceId") or "").strip() != str(resource_id or "").strip()
                    or preferred_mode != str(resource_mode or "vod").strip().lower()
                    or preferred_season <= 0 or preferred_episode <= 0):
                return False
            parts, _parts_limited = _split_bounded_shared(
                group, "#", self.RESOURCE_GROUP_EPISODE_LIMIT,
            )
            for part_index, part in enumerate(parts, 1):
                name, separator, target = part.rpartition("$")
                if not separator or str(target).strip() != preferred_play_id:
                    continue
                found_season, found_episode, explicit = self._episode_from_text_info(
                    name, part_index, preferred_season or self._tracking_season(item),
                )
                if explicit and (found_season, found_episode) == (preferred_season, preferred_episode):
                    return True
            return False

        ranked_groups = sorted(
            enumerate(urls),
            key=lambda value: (
                1 if preferred_route_matches_group(value[1]) else 0,
                self._resource_group_match_score(value[1], item),
            ),
            reverse=True,
        )
        group_limit = min(max_groups, len(ranked_groups))
        for index, group in ranked_groups:
            if len(kept_urls) >= group_limit:
                break
            if deadline is not None and deadline - time.monotonic() < 1:
                break
            play_ids = self._resource_preferred_play_ids(group, item)
            if preferred_route_matches_group(group):
                play_ids = [preferred_play_id] + [value for value in play_ids if value != preferred_play_id]
            if not play_ids:
                continue
            verified = False
            verified_probe = None
            verified_output = None
            verified_play_id = ""
            for play_index, play_id in enumerate(play_ids):
                play_id = str(play_id or "").strip()
                if not play_id or len(play_id) > self.FOLLOWPLAY_MAX_URL_LENGTH:
                    continue
                remaining = deadline - time.monotonic() if deadline is not None else 15
                if remaining < 1:
                    break
                cached_probe = None if force_refresh else self._route_probe_snapshot(
                    play_id, resource_id, resource_mode,
                )
                if (
                        isinstance(cached_probe, dict)
                        and cached_probe.get("reachable") is True
                        and isinstance(cached_probe.get("output"), dict)):
                    verified = True
                    verified_probe = cached_probe
                    verified_output = dict(cached_probe["output"])
                    verified_play_id = play_id
                    break
                play_deadline = min(
                    deadline if deadline is not None else float("inf"),
                    time.monotonic() + remaining / max(1, len(play_ids) - play_index),
                )
                try:
                    output = self._atvp_play(
                        play_id,
                        timeout_seconds=max(6, min(15, self.timeout)),
                        deadline=play_deadline,
                    )
                except Exception:
                    self._record_route_quality(play_id, False)
                    continue
                media_url = Filter._first_http_url((output or {}).get("url"))
                checked = None
                if self._int_value((output or {}).get("parse"), 0) == 0 and Filter._safe_media_url(media_url, self.atvp_api):
                    checked = self._probe_media_output(output, deadline=play_deadline)
                if checked is not None:
                    verified = True
                    verified_probe = checked
                    verified_output = output
                    verified_play_id = play_id
                    self._cache_route_probe(
                        verified_play_id, checked, resource_id=resource_id, resource_mode=resource_mode,
                    )
                    self._record_route_quality(
                        play_id, True, startup_ms=checked.get("startup_ms"), signals=checked,
                    )
                    break
                # AT has already resolved a safe direct URL.  A desktop-side
                # Range probe can still fail because the CDN only accepts the
                # client network, requires player headers, or blocks this host.
                # Keep the route as parse-verified, but do not cache it as
                # reachable because that would turn an unknown probe into a
                # false positive on the next detail/play request.
                if self._safe_atvp_play_output(output):
                    verified = True
                    verified_probe = None
                    verified_output = output
                    verified_play_id = play_id
                    self._record_route_quality(play_id, True)
                    break
                self._record_route_quality(play_id, False)
            if not verified:
                continue
            kept_sources.append(sources[index] if index < len(sources) else "AList资源")
            kept_urls.append(group)
            kept_quality.append(self._route_quality_score(
                verified_play_id, output=verified_output, probe=verified_probe,
                text="%s %s" % (kept_sources[-1], group),
            ))
        if not kept_urls:
            return None
        validated_vod = {
            key: vod.get(key)
            for key in ("vod_name", "vod_remarks", "type_name", "type")
            if vod.get(key) not in (None, "")
        }
        validated_vod["vod_play_from"] = "$$$".join(kept_sources)
        validated_vod["vod_play_url"] = "$$$".join(kept_urls)
        validated_vod["_route_quality"] = kept_quality
        return self._sanitize_validated_resource_detail({"list": [validated_vod]})

    def _resource_group_match_score(self, group, item):
        targets = []
        for value, score in ((item.get("history_episode"), 3), (item.get("latest_episode"), 2)):
            match = re.match(r"^S0*(\d{1,2})E0*(\d{1,3})$", str(value or ""), re.I)
            if match:
                targets.append(((int(match.group(1)), int(match.group(2))), score))
        best = 1
        default_season = self._tracking_season(item)
        parts, _limited = _split_bounded_shared(
            group, "#", self.RESOURCE_GROUP_EPISODE_LIMIT,
        )
        for index, part in enumerate(parts, 1):
            name, separator, _target = part.rpartition("$")
            if not separator:
                continue
            season, episode, explicit = self._episode_from_text_info(name, index, default_season)
            if explicit:
                best = max(best, next((score for key, score in targets if key == (season, episode)), 1))
        return best

    @staticmethod
    def _resource_first_play_id(vod):
        if not isinstance(vod, dict):
            return ""
        groups, _groups_limited = _split_bounded_shared(
            vod.get("vod_play_url"), "$$$", PLAY_GROUP_SCAN_LIMIT,
        )
        for group in groups:
            parts, _parts_limited = _split_bounded_shared(group, "#", EPISODE_SCAN_LIMIT)
            for part in parts:
                _name, separator, target = part.rpartition("$")
                value = str(target if separator else part).strip()
                if value and not value.startswith(Spider.SELECT_PROMPT_ID):
                    return value
        return ""

    def _resource_preferred_play_ids(self, group, item):
        preferred = []
        for value in (item.get("history_episode"), item.get("latest_episode")):
            match = re.match(r"^S0*(\d{1,2})E0*(\d{1,3})$", str(value or ""), re.I)
            if match:
                key = (int(match.group(1)), int(match.group(2)))
                if key not in preferred:
                    preferred.append(key)
        episode_targets = {}
        first_target = ""
        default_season = self._tracking_season(item)
        parts, _limited = _split_bounded_shared(
            group, "#", self.RESOURCE_GROUP_EPISODE_LIMIT,
        )
        for index, part in enumerate(parts, 1):
            name, separator, target = part.rpartition("$")
            if not separator or not target:
                continue
            season, episode, explicit = self._episode_from_text_info(name, index, default_season)
            target = str(target).strip()
            if not target or len(target) > self.FOLLOWPLAY_MAX_URL_LENGTH:
                continue
            if not first_target:
                first_target = target
            if explicit:
                episode_targets.setdefault((season, episode), target)
        ordered = [episode_targets.get(key, "") for key in preferred] + [first_target]
        return list(dict.fromkeys(value for value in ordered if value))

    def _resource_row_cache_key(self, row):
        mode = str((row or {}).get("_resource_mode") or "vod")
        resource_id = str((row or {}).get("vod_id") or (row or {}).get("id") or "").strip()
        if not resource_id:
            return ""
        raw = "%s|%s|%s|%s" % (
            self.atvp_api.rstrip("/"), Filter._token_hash(self.atvp_token), mode, unquote(resource_id),
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    @classmethod
    def _sanitize_validated_resource_detail(cls, detail):
        vod = cls._payload_first_vod(detail)
        if not isinstance(vod, dict):
            return None
        sources, _sources_limited = _split_bounded_shared(
            vod.get("vod_play_from") or "AList资源", "$$$", cls.RESOURCE_PLAY_GROUP_SCAN_LIMIT,
        )
        groups, _groups_limited = _split_bounded_shared(
            vod.get("vod_play_url"), "$$$", cls.RESOURCE_PLAY_GROUP_SCAN_LIMIT,
        )
        kept_sources = []
        kept_groups = []
        kept_indexes = []
        total_length = 0
        source_item_limit = max(
            1,
            (
                cls.RESOURCE_SOURCE_LABEL_MAX_LENGTH
                - (cls.RESOURCE_PLAY_GROUP_SCAN_LIMIT - 1) * 3
            ) // cls.RESOURCE_PLAY_GROUP_SCAN_LIMIT,
        )
        for group_index, group in enumerate(groups):
            parts, _parts_limited = _split_bounded_shared(
                group, "#", cls.RESOURCE_GROUP_EPISODE_LIMIT,
            )
            kept_parts = []
            group_length = 0
            for part in parts:
                name, separator, target = part.rpartition("$")
                target = str(target or "").strip()
                if not separator or not target or len(target) > cls.FOLLOWPLAY_MAX_URL_LENGTH:
                    continue
                entry = "%s$%s" % (
                    str(name or "").strip()[:cls.RESOURCE_METADATA_TITLE_MAX_LENGTH], target,
                )
                separator_length = 1 if kept_parts else 0
                if group_length + separator_length + len(entry) > cls.RESOURCE_REWRITE_GROUP_URL_LIMIT:
                    break
                kept_parts.append(entry)
                group_length += separator_length + len(entry)
            if not kept_parts:
                continue
            separator_length = 3 if kept_groups else 0
            if (
                    total_length + separator_length + group_length
                    > cls.RESOURCE_REWRITTEN_PLAY_URL_MAX_LENGTH):
                break
            kept_sources.append(
                str(sources[group_index] if group_index < len(sources) else "AList资源").strip()
                [:source_item_limit]
            )
            kept_groups.append("#".join(kept_parts))
            kept_indexes.append(group_index)
            total_length += separator_length + group_length
        if not kept_groups:
            return None
        output = {
            "vod_play_from": "$$$".join(kept_sources),
            "vod_play_url": "$$$".join(kept_groups),
        }
        for key, limit in (
                ("vod_name", cls.RESOURCE_METADATA_TITLE_MAX_LENGTH),
                ("vod_remarks", cls.RESOURCE_METADATA_NOTE_MAX_LENGTH),
                ("type_name", cls.RESOURCE_METADATA_PROVIDER_MAX_LENGTH),
                ("type", cls.RESOURCE_METADATA_PROVIDER_MAX_LENGTH)):
            if vod.get(key) not in (None, "") and not isinstance(
                    vod.get(key), (dict, list, tuple, set)):
                output[key] = str(vod.get(key)).strip()[:limit]
        declared_quality = vod.get("_route_quality") if isinstance(vod.get("_route_quality"), list) else []
        quality = []
        for index in kept_indexes:
            source = declared_quality[index] if index < len(declared_quality) else {}
            if not isinstance(source, dict):
                quality.append({})
                continue
            row = {}
            for key in ("startup", "stability", "codec", "resolution", "subtitle", "total"):
                try:
                    row[key] = max(0, min(int(source.get(key) or 0), 1000000))
                except Exception:
                    continue
            if isinstance(source.get("observed"), bool):
                row["observed"] = source.get("observed")
            quality.append(row)
        if quality:
            output["_route_quality"] = quality
        return {"list": [output]}

    def _prune_validated_resource_details_locked(self, now=None):
        now = time.time() if now is None else now
        for key, cached in list(self._validated_resource_details.items()):
            try:
                checked_at = float(cached.get("checked_at") or 0) if isinstance(cached, dict) else 0
            except Exception:
                checked_at = 0
            if (
                    not isinstance(cached, dict)
                    or now - checked_at > self.RESOURCE_SEARCH_CACHE_TTL):
                self._validated_resource_details.pop(key, None)
        while len(self._validated_resource_details) > self.VALIDATED_RESOURCE_DETAIL_CACHE_LIMIT:
            self._validated_resource_details.popitem(last=False)

    def _store_validated_resource_detail(self, row, detail, expected_generation=None):
        key = self._resource_row_cache_key(row)
        sanitized = self._sanitize_validated_resource_detail(detail)
        if not key or sanitized is None:
            return False
        with self._cache_lock:
            if expected_generation is not None and expected_generation != self._cache_generation:
                return False
            self._prune_validated_resource_details_locked()
            self._validated_resource_details[key] = {
                "checked_at": time.time(),
                "detail": sanitized,
            }
            self._validated_resource_details.move_to_end(key)
            self._prune_validated_resource_details_locked()
        return True

    def _validated_resource_detail(self, row):
        key = self._resource_row_cache_key(row)
        with self._cache_lock:
            self._prune_validated_resource_details_locked()
            cached = self._validated_resource_details.get(key) if key else None
            if not isinstance(cached, dict):
                return None
            detail = cached.get("detail")
            if not isinstance(detail, dict):
                self._validated_resource_details.pop(key, None)
                return None
            self._validated_resource_details.move_to_end(key)
            return detail

    @classmethod
    def _resource_id_kind(cls, value):
        decoded = cls._unquote_limited(value).strip()
        if decoded.startswith("push://"):
            decoded = decoded[7:].strip()
        if re.match(r"^(?:magnet:|ed2k:)", decoded, re.I):
            return "offline", decoded
        if re.match(r"^https?://", decoded, re.I):
            return "share", decoded
        return "opaque", decoded

    @classmethod
    def _resource_id_raw_limit(cls, value, mode="vod"):
        kind, _decoded = cls._resource_id_kind(value)
        if kind in ("offline", "share"):
            return cls.RESOURCE_ENCODED_OFFLINE_ID_MAX_LENGTH
        return cls.RESOURCE_ID_MAX_LENGTH

    @classmethod
    def _resource_id_valid(cls, value, mode="vod"):
        raw = str(value or "").strip()
        if not raw:
            return False
        kind, decoded = cls._resource_id_kind(raw)
        if len(raw) > cls._resource_id_raw_limit(raw, mode):
            return False
        if kind in ("offline", "share"):
            if len(decoded) > cls.RESOURCE_OFFLINE_ID_MAX_LENGTH:
                return False
            return kind == "offline" or str(mode or "").lower() in cls.RESOURCE_SUPPLEMENT_MODES
        return (
            len(decoded) <= cls.RESOURCE_ID_MAX_LENGTH
            and not cls._contains_url_reference(decoded)
        )

    @classmethod
    def _resource_id_persistable(cls, value, mode="vod"):
        if not cls._resource_id_valid(value, mode):
            return False
        kind, decoded = cls._resource_id_kind(value)
        if kind == "offline":
            return False
        if kind == "share":
            return bool(cls._resource_provider_key(decoded))
        return not cls._contains_url_reference(decoded)

    @staticmethod
    def _valid_resource_password(value):
        password = str(value or "").strip()
        return password if 0 < len(password) <= 64 else ""

    @classmethod
    def _resource_url_password_value(cls, raw_url):
        decoded = unquote(str(raw_url or ""))
        chinese = re.search(
            r"(?i)(?:提取码|访问码|密码)\s*[:：=]\s*([^\s&#]{1,64})(?![^\s&#])",
            decoded,
        )
        if chinese:
            password = cls._valid_resource_password(chinese.group(1))
            if password:
                return password
        try:
            parsed = urlparse(decoded)
            for part in parsed.query.split("&") if parsed.query else []:
                key, separator, value = part.partition("=")
                if not separator:
                    continue
                if unquote(key).strip().casefold() not in (
                        "pwd", "password", "passcode", "pass_code", "share_pwd"):
                    continue
                password = cls._valid_resource_password(unquote(value))
                if password:
                    return password
            fragment = unquote(str(parsed.fragment or "")).strip()
        except Exception:
            fragment = ""
        named = re.match(
            r"(?i)^(?:password|pwd|passcode|pass_code|share_pwd|提取码|访问码|密码)\s*[:：=]\s*(.+)$",
            fragment,
        )
        if named:
            return cls._valid_resource_password(named.group(1))
        return cls._valid_resource_password(fragment) if re.fullmatch(r"[A-Za-z0-9_-]{1,64}", fragment) else ""

    @classmethod
    def _resource_url_has_password(cls, raw_url):
        return bool(cls._resource_url_password_value(raw_url))

    @classmethod
    def _resource_url_with_password(cls, raw_url, raw_password):
        url = str(raw_url or "").strip()
        password = str(raw_password or "").strip()
        if not url or not password or len(password) > 64:
            return url
        if cls._resource_url_has_password(url):
            return url
        try:
            parsed = urlparse(url)
            if parsed.scheme in ("http", "https") and parsed.hostname:
                query_parts = []
                for part in parsed.query.split("&") if parsed.query else []:
                    key = unquote(part.split("=", 1)[0]).strip().casefold()
                    if key not in ("pwd", "password", "passcode", "pass_code", "share_pwd"):
                        query_parts.append(part)
                fragment = parsed.fragment
                if re.match(
                        r"(?i)^(?:password|pwd|passcode|pass_code|share_pwd|提取码|访问码|密码)\s*[:：=]",
                        unquote(fragment).strip(),
                ):
                    fragment = ""
                url = parsed._replace(query="&".join(query_parts), fragment=fragment).geturl()
        except Exception:
            pass
        fragment_index = url.find("#")
        base = url[:fragment_index] if fragment_index >= 0 else url
        fragment = url[fragment_index:] if fragment_index >= 0 else ""
        separator = "&" if "?" in base else "?"
        return "%s%spassword=%s%s" % (base, separator, quote(password, safe=""), fragment)

    @classmethod
    def _resource_id_with_password(cls, raw_id, raw_password):
        raw = str(raw_id or "").strip()
        password = cls._valid_resource_password(raw_password)
        if not raw or not password:
            return raw
        decoded = cls._unquote_limited(raw).strip()
        if not re.match(r"^https?://", decoded, re.I):
            return raw
        protected = cls._resource_url_with_password(decoded, password)
        return quote(protected, safe="") if raw != decoded else protected

    @classmethod
    def _resource_url_identity(cls, raw_url):
        value = unquote(str(raw_url or "")).strip().rstrip("，。；;、")
        if not value:
            return ""
        lowered = value.casefold()
        if lowered.startswith("magnet:"):
            try:
                for xt in parse_qs(urlparse(value).query).get("xt", []):
                    match = re.match(r"(?i)^urn:btih:([a-z2-7]{32}|[a-f0-9]{40})$", str(xt or ""))
                    if match:
                        btih = match.group(1)
                        if len(btih) == 32:
                            try:
                                decoded_hash = base64.b32decode(btih.upper(), casefold=True)
                                if len(decoded_hash) == 20:
                                    btih = decoded_hash.hex()
                            except Exception:
                                pass
                        return "magnet:btih:" + btih.casefold()
            except Exception:
                pass
            return "magnet:" + value[len("magnet:"):].casefold()
        if lowered.startswith("ed2k:"):
            hashes = re.findall(r"(?i)\|([a-f0-9]{32})\|", value)
            if hashes:
                return "ed2k:hash:" + hashes[-1].casefold()
            return "ed2k:" + value[len("ed2k:"):].casefold()
        try:
            parsed = urlparse(value)
            if parsed.scheme not in ("http", "https") or not parsed.hostname:
                return value
            host = parsed.hostname.casefold()
            if ":" in host and not host.startswith("["):
                host = "[" + host + "]"
            port = parsed.port
            if port is not None and not (
                    parsed.scheme == "http" and port == 80
                    or parsed.scheme == "https" and port == 443):
                host += ":%s" % port
            path = re.sub(
                r"(?i)(?:提取码|访问码|密码)\s*[:：=]\s*[a-z0-9]{1,64}$", "", parsed.path,
            ).rstrip("/") or "/"
            query_parts = []
            for part in parsed.query.split("&") if parsed.query else []:
                key = unquote(part.split("=", 1)[0]).strip().casefold()
                if key in ("pwd", "password", "passcode", "pass_code", "share_pwd"):
                    continue
                if re.match(r"(?i)^(?:提取码|访问码|密码)\s*[:：=]", unquote(part)):
                    continue
                query_parts.append(part)
            query = "&".join(sorted(query_parts))
            fragment = parsed.fragment
            decoded_fragment = unquote(fragment).strip()
            if re.match(
                    r"(?i)^(?:password|pwd|passcode|pass_code|share_pwd|提取码|访问码|密码)\s*[:：=]",
                    decoded_fragment
            ) or re.fullmatch(r"[A-Za-z0-9_-]{1,64}", decoded_fragment):
                fragment = ""
            return "%s%s%s%s" % (
                host, path,
                "?" + query if query else "",
                "#" + fragment if fragment else "",
            )
        except Exception:
            return value

    @classmethod
    def _resource_row_identity(cls, row_or_id):
        mode = ""
        if isinstance(row_or_id, dict):
            mode = str(row_or_id.get("_resource_mode") or "").strip().lower()
            raw = next((
                str(row_or_id.get(key) or "").strip()
                for key in ("vod_id", "id", "url", "link", "share_url", "target")
                if str(row_or_id.get(key) or "").strip()
            ), "")
        else:
            raw = str(row_or_id or "").strip()
        if not raw:
            return ""
        decoded = cls._unquote_limited(raw).strip()
        if decoded.startswith("push://"):
            decoded = decoded[7:].strip()
        if re.match(r"^(?:https?://|magnet:|ed2k:)", decoded, re.I):
            identity = cls._resource_url_identity(decoded)
            return "url:" + identity if identity else ""
        return "id:%s:%s" % (mode or "unknown", raw)

    @classmethod
    def _resource_url_password_score(cls, raw_url):
        return 1 if cls._resource_url_has_password(raw_url) else 0

    @staticmethod
    def _resource_timestamp_rank(value):
        if value in (None, "") or isinstance(value, bool):
            return 0.0
        if isinstance(value, datetime.datetime):
            parsed = value
        else:
            text = str(value).strip()
            try:
                number = float(text)
                if math.isfinite(number) and number > 0:
                    while number > 99999999999:
                        number /= 1000.0
                    return number
            except Exception:
                pass
            normalized = text[:-1] + "+00:00" if text.endswith(("Z", "z")) else text
            try:
                parsed = datetime.datetime.fromisoformat(normalized)
            except Exception:
                return 0.0
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=datetime.timezone.utc)
        try:
            return float(parsed.astimezone(datetime.timezone.utc).timestamp())
        except Exception:
            return 0.0

    @classmethod
    def _resource_row_timestamp(cls, row):
        if not isinstance(row, dict):
            return 0.0
        return max(
            (cls._resource_timestamp_rank(row.get(key)) for key in (
                "_resource_timestamp", "datetime", "vod_time", "timestamp",
                "created_at", "updated_at", "create_time", "update_time",
            )),
            default=0.0,
        )

    @staticmethod
    def _resource_independent_password(*rows):
        keys = (
            "password", "pwd", "passcode", "pass_code", "share_pwd",
            "提取码", "访问码", "密码",
        )
        for row in rows:
            if not isinstance(row, dict):
                continue
            for key in keys:
                value = str(row.get(key) or "").strip()
                if value and len(value) <= 64:
                    return value
        return ""

    def _resource_row_preference(self, row, item=None, bound=""):
        if not isinstance(row, dict):
            return (0, 0, 0, 0, 0.0, 0, 0)
        match_score = self._resource_score(row, item, bound) if isinstance(item, dict) else 0
        work_title = str(row.get("work_title") or "").strip()
        if isinstance(item, dict) and work_title:
            work_match = self._resource_score({
                "vod_id": row.get("vod_id") or row.get("id"),
                "work_title": work_title,
            }, item, bound)
            work_state = 2 if work_match > 0 else 0
        else:
            work_state = 2 if work_title else 1
        resource_id = str(row.get("vod_id") or row.get("id") or "").strip()
        password_score = self._resource_url_password_score(unquote(resource_id))
        metadata_count = sum(
            1 for key in ("vod_name", "name", "title", "note", "source", "type", "vod_remarks")
            if row.get(key) not in (None, "", [], {})
        )
        return (
            1 if match_score > 0 else 0,
            work_state,
            match_score,
            password_score,
            self._resource_row_timestamp(row),
            1 if self._positive_int(row.get("_validated_groups"), 0) > 0 else 0,
            metadata_count,
        )

    def _merge_resource_rows(self, current, candidate, item=None, bound=""):
        left = dict(current or {})
        right = dict(candidate or {})
        if self._resource_row_preference(right, item, bound) > self._resource_row_preference(left, item, bound):
            primary, secondary = right, left
        else:
            primary, secondary = left, right
        merged = dict(primary)
        for key, value in secondary.items():
            if key.startswith("_") or value in (None, "", [], {}):
                continue
            if isinstance(item, dict) and key in (
                    "work_title", "vod_name", "name", "title", "vod_title", "show_name", "note"):
                continue
            if merged.get(key) in (None, "", [], {}):
                merged[key] = value

        primary_id = str(primary.get("vod_id") or primary.get("id") or "").strip()
        left_id = str(left.get("vod_id") or left.get("id") or "").strip()
        right_id = str(right.get("vod_id") or right.get("id") or "").strip()
        left_password = self._resource_url_password_score(unquote(left_id))
        right_password = self._resource_url_password_score(unquote(right_id))
        if right_password > left_password:
            selected_id = right_id
        elif left_password > right_password:
            selected_id = left_id
        elif self._resource_row_timestamp(right) > self._resource_row_timestamp(left):
            selected_id = right_id
        else:
            selected_id = primary_id or left_id or right_id
        if selected_id:
            merged["vod_id"] = selected_id

        left_timestamp = self._resource_row_timestamp(left)
        right_timestamp = self._resource_row_timestamp(right)
        if max(left_timestamp, right_timestamp) > 0:
            newer = right if right_timestamp > left_timestamp else left
            merged["_resource_timestamp"] = next((
                newer.get(key) for key in (
                    "_resource_timestamp", "datetime", "vod_time", "timestamp",
                    "created_at", "updated_at", "create_time", "update_time",
                ) if newer.get(key) not in (None, "")
            ), max(left_timestamp, right_timestamp))

        if (
                selected_id != primary_id
                or str(merged.get("_resource_mode") or "") != str(primary.get("_resource_mode") or "")):
            merged.pop("_validated_groups", None)
        return merged

    def _merge_resource_candidate_rows(self, rows, item=None, bound=""):
        merged = []
        positions = {}
        for value in rows or []:
            if not isinstance(value, dict):
                continue
            row = dict(value)
            identity = self._resource_row_identity(row)
            if not identity:
                merged.append(row)
                continue
            if identity in positions:
                index = positions[identity]
                merged[index] = self._merge_resource_rows(merged[index], row, item, bound)
            else:
                positions[identity] = len(merged)
                merged.append(row)
        return merged

    def _resource_fair_candidate_order(self, rows, item, bound="", modes=None):
        candidates = self._merge_resource_candidate_rows(rows, item, bound)
        ranked = {}
        order_lookup = {}
        for order, row in enumerate(candidates):
            score = self._resource_score(row, item, bound)
            if score <= 0:
                continue
            mode = str(row.get("_resource_mode") or "vod")
            order_lookup[id(row)] = order
            ranked.setdefault(mode, []).append(row)
        for values in ranked.values():
            values.sort(key=lambda row: (
                self._resource_row_preference(row, item, bound),
                -order_lookup.get(id(row), 0),
            ), reverse=True)

        mode_order = list(modes or self.RESOURCE_SEARCH_MODES)
        mode_order.extend(mode for mode in ranked if mode not in mode_order)
        selected = []
        depth = 0
        while True:
            added = False
            for mode in mode_order:
                values = ranked.get(mode) or []
                if depth < len(values):
                    selected.append(values[depth])
                    added = True
            if not added:
                break
            depth += 1
        return selected

    @staticmethod
    def _resource_title_candidate(*values):
        fallback = ""
        for value in values:
            text = str(value or "").strip()
            if not text:
                continue
            if not fallback:
                fallback = text[:1024]
            for line in text.splitlines() or [text]:
                candidate = re.sub(
                    r"(?i)(?:https?://\S+|magnet:\?\S+|ed2k://\S+)", " ", line,
                )
                candidate = re.sub(r"^(?:名称|资源标题|标题)\s*[:：]\s*", "", candidate).strip()
                candidate = candidate.strip(" \t-—_|·，。；;、")
                if candidate and not re.fullmatch(
                        r"(?i)(?:提取码|访问码|密码|pwd|password)\s*[:：=]?\s*[a-z0-9]{1,64}",
                        candidate):
                    return candidate[:1024]
        return fallback

    @classmethod
    def _resource_payload_rows(cls, value, mode, limit=None):
        max_items = None if limit is None else max(0, cls._int_value(limit, 0))
        if max_items == 0:
            return []
        generic_rows = cls._payload_list(value, limit=max_items)

        def clipped(value, length):
            return str(value or "").strip()[:length]

        def sanitized_row(row):
            if not isinstance(row, dict):
                return None
            output = {}
            password = cls._resource_independent_password(row)
            for key in ("vod_id", "id", "url", "link", "share_url", "target"):
                if key not in row or isinstance(row.get(key), (dict, list, tuple, set)):
                    continue
                raw = str(row.get(key) or "").strip()
                if raw:
                    output[key] = cls._resource_id_with_password(raw, password)
            for key in ("vod_name", "name", "title", "vod_title", "show_name", "work_title"):
                if key in row and not isinstance(row.get(key), (dict, list, tuple, set)):
                    output[key] = clipped(row.get(key), cls.RESOURCE_METADATA_TITLE_MAX_LENGTH)
            for key in ("note", "content", "vod_content", "vod_remarks"):
                if key in row and not isinstance(row.get(key), (dict, list, tuple, set)):
                    output[key] = clipped(row.get(key), cls.RESOURCE_METADATA_NOTE_MAX_LENGTH)
            for key in ("source", "channel"):
                if key in row and not isinstance(row.get(key), (dict, list, tuple, set)):
                    output[key] = clipped(row.get(key), cls.RESOURCE_METADATA_SOURCE_MAX_LENGTH)
            for key in ("provider", "type", "type_name"):
                if key in row and not isinstance(row.get(key), (dict, list, tuple, set)):
                    output[key] = clipped(row.get(key), cls.RESOURCE_METADATA_PROVIDER_MAX_LENGTH)
            for key in (
                    "vod_year", "year", "datetime", "vod_time", "timestamp",
                    "created_at", "updated_at", "create_time", "update_time"):
                if key in row and not isinstance(row.get(key), (dict, list, tuple, set)):
                    output[key] = clipped(row.get(key), 128)
            if row.get("vod_pic") not in (None, "") and not isinstance(
                    row.get("vod_pic"), (dict, list, tuple, set)):
                output["vod_pic"] = clipped(row.get("vod_pic"), 8192)
            if isinstance(row.get("links"), list):
                links = []
                for link in row.get("links")[:cls.RESOURCE_PAYLOAD_SCAN_MIN]:
                    if not isinstance(link, dict):
                        continue
                    normalized = {}
                    for key in ("work_title", "title"):
                        if link.get(key) not in (None, "") and not isinstance(
                                link.get(key), (dict, list, tuple, set)):
                            normalized[key] = clipped(
                                link.get(key), cls.RESOURCE_METADATA_TITLE_MAX_LENGTH,
                            )
                    if link.get("note") not in (None, "") and not isinstance(
                            link.get("note"), (dict, list, tuple, set)):
                        normalized["note"] = clipped(
                            link.get("note"), cls.RESOURCE_METADATA_NOTE_MAX_LENGTH,
                        )
                    if normalized:
                        links.append(normalized)
                if links:
                    output["links"] = links
            resource_id = str(output.get("vod_id") or output.get("id") or "").strip()
            if resource_id and not cls._resource_id_valid(resource_id, mode):
                return None
            for key in ("url", "link", "share_url", "target"):
                target = str(output.get(key) or "").strip()
                if target and not cls._resource_id_valid(target, mode):
                    output.pop(key, None)
            return output

        generic_rows = [
            row for row in (sanitized_row(value) for value in generic_rows) if row is not None
        ]
        if mode not in cls.RESOURCE_SUPPLEMENT_MODES:
            return generic_rows

        rows = []
        positions = {}
        timestamps = {}

        def add_row(row, identity, timestamp=""):
            if not isinstance(row, dict) or not identity:
                return
            if identity in positions:
                index = positions[identity]
                current = rows[index]
                current_resource_id = str(current.get("vod_id") or current.get("id") or "")
                candidate_resource_id = str(row.get("vod_id") or row.get("id") or "")
                stamp = timestamp
                current_stamp = timestamps.get(identity, "")
                candidate_is_newer = (
                    cls._resource_timestamp_rank(stamp)
                    > cls._resource_timestamp_rank(current_stamp)
                )
                current_work_title = clipped(
                    current.get("work_title"), cls.RESOURCE_METADATA_TITLE_MAX_LENGTH,
                )
                candidate_work_title = clipped(
                    row.get("work_title"), cls.RESOURCE_METADATA_TITLE_MAX_LENGTH,
                )
                if candidate_is_newer:
                    replacement = dict(row)
                    for key, current_value in current.items():
                        if replacement.get(key) in (None, "", [], {}):
                            replacement[key] = current_value
                    rows[index] = replacement
                    timestamps[identity] = stamp
                else:
                    for key, candidate in row.items():
                        if current.get(key) in (None, "", [], {}) and candidate not in (None, "", [], {}):
                            current[key] = candidate
                kept = rows[index]
                current_password_score = cls._resource_url_password_score(unquote(current_resource_id))
                candidate_password_score = cls._resource_url_password_score(unquote(candidate_resource_id))
                if (
                        candidate_resource_id
                        and (
                            candidate_password_score > current_password_score
                            or candidate_password_score == current_password_score and candidate_is_newer
                        )):
                    kept["vod_id"] = candidate_resource_id
                elif current_resource_id:
                    kept["vod_id"] = current_resource_id
                if current_work_title and candidate_work_title:
                    selected_work_title = candidate_work_title if candidate_is_newer else current_work_title
                else:
                    selected_work_title = current_work_title or candidate_work_title
                if selected_work_title:
                    kept["work_title"] = selected_work_title
                    kept["vod_name"] = selected_work_title
                    kept["note"] = ""
                    kept["title"] = ""
                return
            if max_items is not None and len(rows) >= max_items:
                return
            positions[identity] = len(rows)
            timestamps[identity] = timestamp
            if timestamp not in (None, ""):
                row["_resource_timestamp"] = timestamp
            rows.append(row)

        def add_link(link, parent=None, provider_hint=""):
            if not isinstance(link, dict):
                return
            parent = parent if isinstance(parent, dict) else {}
            url = str(
                link.get("url") or link.get("link") or link.get("share_url")
                or link.get("target") or ""
            ).strip()
            if not url or not cls._resource_id_valid(url, mode):
                return
            password = clipped(cls._resource_independent_password(link, parent), 64)
            url = cls._resource_url_with_password(url, password)
            provider_value = clipped(
                link.get("type") or link.get("provider") or provider_hint,
                cls.RESOURCE_METADATA_PROVIDER_MAX_LENGTH,
            )
            provider = cls._resource_provider_key(provider_value, url)
            if not provider:
                return
            link_work_title = clipped(
                link.get("work_title"), cls.RESOURCE_METADATA_TITLE_MAX_LENGTH,
            )
            link_note = clipped(link.get("note"), cls.RESOURCE_METADATA_NOTE_MAX_LENGTH)
            parent_work_title = clipped(
                parent.get("work_title"), cls.RESOURCE_METADATA_TITLE_MAX_LENGTH,
            )
            parent_title = clipped(parent.get("title"), cls.RESOURCE_METADATA_TITLE_MAX_LENGTH)
            parent_name = clipped(
                parent.get("vod_name") or parent.get("name"),
                cls.RESOURCE_METADATA_TITLE_MAX_LENGTH,
            )
            parent_note = clipped(parent.get("note"), cls.RESOURCE_METADATA_NOTE_MAX_LENGTH)
            parent_content = clipped(parent.get("content"), cls.RESOURCE_METADATA_NOTE_MAX_LENGTH)
            title = cls._resource_title_candidate(
                link_work_title, link_note, parent_work_title, parent_title,
                parent_name, parent_note, parent_content,
            )
            if not title:
                return
            resource_id = quote(url, safe="")
            has_link_title = bool(link_work_title)
            row = {
                "vod_id": resource_id,
                "vod_name": title,
                "vod_remarks": provider_value or provider,
                "type": provider_value or provider,
                "source": clipped(
                    link.get("source") or parent.get("source") or parent.get("channel"),
                    cls.RESOURCE_METADATA_SOURCE_MAX_LENGTH,
                ),
                "work_title": link_work_title,
                "note": "" if has_link_title else (link_note or parent_note),
                "title": "" if has_link_title else parent_title,
            }
            timestamp = link.get("datetime") or parent.get("datetime") or parent.get("vod_time") or ""
            if timestamp not in (None, ""):
                row["_resource_timestamp"] = timestamp
            add_row(row, cls._resource_row_identity(url), timestamp)

        containers = [value] if isinstance(value, dict) else []
        if containers and isinstance(value.get("data"), dict):
            containers.insert(0, value.get("data"))
        scan_budget = min(
            cls.RESOURCE_RECORD_LIMIT,
            max(
                cls.RESOURCE_PAYLOAD_SCAN_MIN,
                (max_items if max_items is not None else cls.RESOURCE_SEARCH_RESULT_LIMIT)
                * cls.RESOURCE_PAYLOAD_SCAN_FACTOR,
            ),
        )
        scanned_links = 0
        streams = []
        for container in containers:
            results = container.get("results")
            if isinstance(results, list):
                for result in results:
                    if not isinstance(result, dict):
                        continue
                    links = result.get("links")
                    if isinstance(links, list):
                        streams.append([links, 0, result, ""])
                    elif any(result.get(key) for key in ("url", "link", "share_url", "target")):
                        streams.append([[result], 0, {}, ""])
            merged = container.get("merged_by_type")
            if isinstance(merged, dict):
                for provider_hint, links in merged.items():
                    if isinstance(links, list):
                        streams.append([links, 0, {}, provider_hint])
        active = streams
        while active and scanned_links < scan_budget:
            next_active = []
            for stream in active:
                links, index, parent, provider_hint = stream
                if scanned_links >= scan_budget:
                    break
                if index >= len(links):
                    continue
                scanned_links += 1
                add_link(links[index], parent=parent, provider_hint=provider_hint)
                index += 1
                if index < len(links):
                    stream[1] = index
                    next_active.append(stream)
            active = next_active
        for generic in generic_rows:
            resource_id = str(generic.get("vod_id") or generic.get("id") or "").strip()
            if resource_id:
                add_row(
                    dict(generic), cls._resource_row_identity(generic),
                    generic.get("vod_time") or generic.get("datetime"),
                )
            else:
                add_link(generic)
        return rows

    def _resource_search_mode(self, mode, queries, deadline=None):
        started_at = time.monotonic()
        self._diagnostic_event("resource_mode.start", mode=mode, query_count=len(queries or []))
        if self._resource_capability(mode) == "missing":
            return []
        rows = []
        positions = {}
        for query in list(queries or [])[:2]:
            if len(rows) >= self.RESOURCE_SEARCH_RESULT_LIMIT:
                break
            if deadline is not None and deadline - time.monotonic() < 1:
                break
            params = {"wd": query, "pg": 1}
            if mode in ("vod1", "vod"):
                params.update({"size": 50, "ac": "detail"})
            elif mode == "telegram":
                params["web"] = "true"
            try:
                data = self._resource_api_get(mode, params, deadline=deadline)
            except Exception as exc:
                self._diagnostic_event("resource_mode.request", "WARN", exc=exc, mode=mode)
                continue
            remaining_limit = self.RESOURCE_SEARCH_RESULT_LIMIT - len(rows)
            for value in self._resource_payload_rows(data, mode, limit=remaining_limit):
                row = dict(value)
                row["_resource_mode"] = mode
                resource_id = str(row.get("vod_id") or row.get("id") or "").strip()
                if not self._resource_id_valid(resource_id, mode):
                    continue
                identity = self._resource_row_identity(row)
                if identity in positions:
                    index = positions[identity]
                    rows[index] = self._merge_resource_rows(rows[index], row)
                    continue
                positions[identity] = len(rows)
                rows.append(row)
        self._diagnostic_event(
            "resource_mode.finish", "INFO" if rows else "WARN",
            duration_ms=int((time.monotonic() - started_at) * 1000), mode=mode, count=len(rows),
        )
        return rows

    def _resource_detail(self, row, deadline=None, use_validated_cache=True):
        if use_validated_cache:
            cached = self._validated_resource_detail(row)
            if cached is not None:
                return cached
        mode = str(row.get("_resource_mode") or "vod") if isinstance(row, dict) else "vod"
        resource_id = str((row or {}).get("vod_id") or (row or {}).get("id") or "").strip()
        if not resource_id:
            return {"list": []}
        if not self._resource_id_valid(resource_id, mode):
            raise RuntimeError("资源 ID 过长，已拒绝异常线路")
        if mode in ("vod1", "vod"):
            params = {"ids": resource_id, "ac": "detail"}
        elif mode == "pansou":
            params = {"id": unquote(resource_id)}
        elif mode == "telegram":
            params = {
                "id": unquote(resource_id),
                "ac": "detail",
                "title": str(row.get("vod_name") or row.get("name") or ""),
                "web": "true",
            }
        else:
            raise RuntimeError("不支持的资源搜索模式：%s" % mode)
        return self._resource_api_get(mode, params, deadline=deadline)

    @staticmethod
    def _resource_has_denied_variant(value):
        normalized = Spider._normalize_media_title(value)
        return any(marker in normalized for marker in (
            "解说", "剪辑", "预告", "花絮", "幕后", "制作特辑", "特辑", "特别节目", "特别篇",
            "衍生", "番外", "彩蛋", "剧场版", "电影版", "真人版", "重制版", "翻拍",
            "reaction", "react", "recap", "trailer", "behindthescenes", "makingof",
        ))

    @staticmethod
    def _resource_decorated_alias(raw_actual, aliases):
        actual = Spider._normalize_media_title(raw_actual)
        matched = sorted(
            {alias for alias in aliases if len(alias) >= 4 and alias in actual},
            key=len,
            reverse=True,
        )
        if not matched:
            return ""
        remainder = actual
        for alias in sorted(aliases, key=len, reverse=True):
            if len(alias) >= 2:
                remainder = remainder.replace(alias, "")
        allowed = (
            r"(?:电视剧|连续剧|剧集|网剧|短剧|国产剧|美剧|英剧|韩剧|日剧|泰剧|港剧|台剧|"
            r"动画|动漫|纪录片|综艺|合集|全季|电影|动作|剧情|悬疑|奇幻|冒险|科幻|犯罪|家庭|喜剧|爱情|惊悚)",
            r"(?:(?:19|20)\d{2}|tmdb\d+)",
            r"(?:第[零〇一二两三四五六七八九十百壹贰叁肆伍陆柒捌玖拾佰\d]{1,6}(?:季|部)|"
            r"season0*\d{1,2}|s0*\d{1,2}(?!\d)|[零〇一二两三四五六七八九十百\d]{1,4}(?:季|部)(?:全)?)",
            r"(?:附(?:前)?[零〇一二两三四五六七八九十百\d]{1,4}(?:季|部)|附前两季|附前\d+季)",
            r"(?:8k|4k|2160p|1080p|720p|uhd|hdr10plus|hdr10|hdr|dv|dolbyvision|杜比视界|"
            r"高码率|高码|原盘|remux|bluray|webdl|webrip|hdtv|nf|netflix|hbomax)",
            r"(?:s0*\d{1,2}e(?:p)?0*\d{1,3}(?:e(?:p)?0*\d{1,3})?|e(?:p)?0*\d{1,3})",
            r"(?:(?:更新至|更至|更新|首播|更)?第?0*\d{1,3}(?:集|话|期)(?:全|完结)?|"
            r"全0*\d{1,3}(?:集|话|期)|(?:更新至|更至|更新)0*\d{1,3}|完结)",
            r"(?:h26[45]|x26[45]|hevc|avc|aac\d*|ddp\d*|atmos|multi|mkv|mp4|ts)",
            r"(?:内封|内嵌|外挂|官方|官译|精修|简中|繁中|简繁|中英|韩英|英韩|多国|"
            r"中文字幕|字幕|中字|特效|音轨|双语|国语|粤语|英语|韩语|日语)",
            r"(?:\d+(?:tb|gb|mb|g|m))",
            r"(?:更新至|更至|更新|首更至|首更|首播至|首播|附前|附|前|更|至|全)",
            r"(?:hiveweb|telegram|telegraph|tg|pansou|盘搜|电报|电报群|"
            r"网盘|云盘|分享|夸克|阿里|百度|迅雷|天翼|移动|115|123|uc|pikpak|quark|"
            r"baidu|aliyun|alipan|xunlei|drive|cloud)",
        )
        previous = None
        while remainder and remainder != previous:
            previous = remainder
            for pattern in allowed:
                remainder = re.sub(pattern, "", remainder, flags=re.I)
        return matched[0] if not remainder else ""

    @staticmethod
    def _resource_work_title_values(row):
        if not isinstance(row, dict):
            return []
        values = []
        work_title = str(row.get("work_title") or "").strip()
        if work_title:
            values.append(work_title)
        for link in (
                row.get("links")[:Spider.RESOURCE_PAYLOAD_SCAN_MIN]
                if isinstance(row.get("links"), list) else []):
            if not isinstance(link, dict):
                continue
            value = str(link.get("work_title") or "").strip()
            if value and value not in values:
                values.append(value)
        return values

    @staticmethod
    def _resource_title_values(row):
        if not isinstance(row, dict):
            return []
        values = []
        for key in (
                "vod_name", "name", "title", "vod_title", "show_name",
                "work_title", "note",
        ):
            value = str(row.get(key) or "").strip()
            if value and value not in values:
                values.append(value)
        for link in (
                row.get("links")[:Spider.RESOURCE_PAYLOAD_SCAN_MIN]
                if isinstance(row.get("links"), list) else []):
            if not isinstance(link, dict):
                continue
            for key in ("work_title", "title", "note"):
                value = str(link.get(key) or "").strip()
                if value and value not in values:
                    values.append(value)
        return values

    def _resource_score(self, row, item, bound):
        resource_id = str(row.get("vod_id") or row.get("id") or "").strip()
        aliases = {
            self._normalize_media_title(value)
            for value in self._follow_title_alias_values(item)
        } - {""}
        work_titles = self._resource_work_title_values(row)
        title_values = work_titles or self._resource_title_values(row)
        if not title_values:
            return 0
        if all(self._resource_has_denied_variant(value) for value in title_values):
            return 0
        tracking_season = self._tracking_season(item)
        season_count = self._positive_int(item.get("season_count"), 0)
        single_season = season_count == 1 or (season_count <= 0 and tracking_season == 1)
        year = str(item.get("year") or "")[:4]
        if bound and resource_id == bound:
            return 10000
        best = 0
        for raw_actual in title_values:
            actual = self._normalize_media_title(raw_actual)
            if not actual or self._resource_has_denied_variant(raw_actual):
                continue
            row_season = Filter._season(raw_actual)
            if row_season and row_season != tracking_season and not single_season:
                continue
            year_text = " ".join(
                str(row.get(key) or "")
                for key in (
                    "vod_name", "name", "title", "work_title", "note",
                    "vod_year", "vod_remarks",
                )
            )
            row_years = set(re.findall(r"(?<!\d)((?:19|20)\d{2})(?!\d)", year_text))
            if year and row_years and year not in row_years and row_season != tracking_season:
                continue
            if actual in aliases:
                score = 500
            elif self._resource_decorated_alias(raw_actual, aliases):
                score = 470
            else:
                continue
            if row_season == tracking_season:
                score += 80
            if year and year in row_years:
                score += 30
            best = max(best, score)
        return best

    @staticmethod
    def _resource_provider_key(*values):
        providers = (
            ("quark", ("pan.quark.cn",), ("夸克", "quark")),
            ("uc", ("drive.uc.cn", "fast.uc.cn"), ("uc网盘", "uc云盘", "uc分享")),
            ("ali", ("alipan.com", "aliyundrive.com"), ("阿里云盘", "阿里网盘", "阿里分享")),
            ("baidu", ("pan.baidu.com",), ("百度网盘", "百度云盘", "百度分享")),
            ("xunlei", ("pan.xunlei.com",), ("迅雷网盘", "迅雷云盘", "迅雷分享")),
            ("pikpak", ("mypikpak.com",), ("pikpak",)),
            ("pan123", (
                "123pan.com", "123pan.cn", "123684.com", "123685.com", "123865.com",
                "123912.com", "123592.com", "123684.cn", "123685.cn", "123865.cn",
                "123912.cn", "123592.cn",
            ), ("123网盘", "123云盘", "123分享")),
            ("pan115", ("115.com", "115cdn.com", "anxia.com"), ("115网盘", "115云盘", "115分享")),
            ("tianyi", ("cloud.189.cn",), ("天翼网盘", "天翼云盘", "天翼分享")),
            ("mobile", (
                "caiyun.139.com", "yun.139.com", "caiyun.feixin.10086.cn",
            ), ("移动网盘", "移动云盘", "移动分享")),
            ("guangya", ("guangyapan.com",), ("光鸭网盘", "光鸭云盘", "光鸭分享")),
        )
        exact_labels = {
            "夸克": "quark", "quark": "quark", "5": "quark",
            "uc": "uc", "7": "uc",
            "阿里": "ali", "ali": "ali", "alipan": "ali", "aliyun": "ali", "0": "ali",
            "百度": "baidu", "baidu": "baidu", "10": "baidu",
            "迅雷": "xunlei", "xunlei": "xunlei", "2": "xunlei",
            "pikpak": "pikpak", "1": "pikpak",
            "123": "pan123", "pan123": "pan123", "3": "pan123",
            "115": "pan115", "pan115": "pan115", "8": "pan115",
            "天翼": "tianyi", "tianyi": "tianyi", "9": "tianyi",
            "移动": "mobile", "mobile": "mobile", "6": "mobile",
            "光鸭": "guangya", "guangya": "guangya", "12": "guangya",
            "magnet": "magnet", "ed2k": "ed2k",
        }
        resolved = set()
        for value in values:
            normalized = unicodedata.normalize("NFKC", unquote(str(value or ""))).casefold()
            if not normalized:
                continue
            url_candidates = re.findall(r"(?i)(?:https?:)?//[^\s<>\"']+", normalized)
            if not url_candidates and re.match(r"^[a-z0-9.-]+\.[a-z]{2,}(?:[/:?#]|$)", normalized):
                url_candidates = ["//" + normalized]
            matches = set()
            if normalized.startswith("magnet:"):
                matches.add("magnet")
            if normalized.startswith("ed2k:"):
                matches.add("ed2k")
            if url_candidates:
                hosts = set()
                for candidate in url_candidates:
                    parsed = urlparse(candidate if "://" in candidate else "https:" + candidate)
                    host = str(parsed.hostname or "").rstrip(".")
                    if host:
                        hosts.add(host)
                matches.update(
                    provider for provider, domains, _labels in providers
                    if any(host == domain or host.endswith("." + domain) for host in hosts for domain in domains)
                )
            else:
                matches.update(
                    provider for provider, domains, labels in providers
                    if any(label in normalized for label in labels)
                    or any(re.search(r"(?<![a-z0-9.-])%s(?=$|[/:?#])" % re.escape(domain), normalized)
                           for domain in domains)
                )
                exact = exact_labels.get(re.sub(r"[\s._-]+", "", normalized))
                if exact:
                    matches.add(exact)
            if len(matches) > 1:
                return ""
            resolved.update(matches)
            if len(resolved) > 1:
                return ""
        return next(iter(resolved)) if resolved else ""

    @staticmethod
    def _completion_episode_name(name, season, episode):
        value = str(name or "").strip() or "S%02dE%02d" % (season, episode)
        return value if value.endswith("补全") else value + "补全"

    def _complete_same_provider_groups(self, records, completion_char_budget=None):
        grouped = {}
        group_order = []
        coverage = {}
        donors = {}
        for record in records:
            group_index = self._int_value(record.get("group"), -1)
            if group_index not in grouped:
                group_order.append(group_index)
            grouped.setdefault(group_index, []).append(record)
            provider = self._resource_provider_key(record.get("provider"))
            episode_key = record.get("episode_key")
            if (
                    not provider
                    or not isinstance(episode_key, tuple)
                    or len(episode_key) != 2
                    or not isinstance(episode_key[0], int)
                    or not isinstance(episode_key[1], int)
                    or episode_key[0] <= 0
                    or episode_key[1] <= 0):
                continue
            season_key = (provider, episode_key[0])
            coverage.setdefault(season_key, {}).setdefault(group_index, set()).add(episode_key[1])
            donors.setdefault((provider, episode_key[0], episode_key[1]), []).append(record)

        completed = 0
        limited = False
        remaining_chars = (
            self.RESOURCE_MERGED_PLAY_URL_BUDGET
            if completion_char_budget is None
            else max(0, self._int_value(completion_char_budget, 0))
        )
        supplements = {}
        for season_key, group_episodes in coverage.items():
            if len(group_episodes) < 2:
                continue
            provider, season = season_key
            available = set().union(*group_episodes.values())
            for group_index, existing in group_episodes.items():
                for episode in sorted(available - existing):
                    if completed >= self.RESOURCE_COMPLETION_LIMIT:
                        limited = True
                        break
                    candidates = [
                        record for record in donors.get((provider, season, episode), [])
                        if self._int_value(record.get("group"), -1) != group_index
                    ]
                    if not candidates:
                        continue
                    donor = min(candidates, key=lambda record: (
                        self._int_value(record.get("group"), 0),
                        self._int_value(record.get("part"), 0),
                    ))
                    completion_name = self._completion_episode_name(donor.get("name"), season, episode)
                    completion_cost = len(completion_name) + len(str(donor.get("play_id") or "")) + 2
                    if completion_cost > remaining_chars:
                        limited = True
                        break
                    supplement = dict(donor)
                    supplement.update({
                        "group": group_index,
                        "name": completion_name,
                        "completed": True,
                    })
                    supplements.setdefault(group_index, []).append(supplement)
                    completed += 1
                    remaining_chars -= completion_cost
                if limited:
                    break
            if limited:
                break

        if not completed:
            return records, 0, limited
        output = []
        for group_index in group_order:
            group_records = list(grouped[group_index])
            for supplement in sorted(
                    supplements.get(group_index, []), key=lambda record: record.get("episode_key") or (0, 0)):
                supplement_key = supplement.get("episode_key")
                insert_at = len(group_records)
                for index, record in enumerate(group_records):
                    episode_key = record.get("episode_key")
                    if (
                            isinstance(episode_key, tuple)
                            and len(episode_key) == 2
                            and isinstance(episode_key[0], int)
                            and isinstance(episode_key[1], int)
                            and episode_key > supplement_key):
                        insert_at = index
                        break
                group_records.insert(insert_at, supplement)
            for part_index, record in enumerate(group_records):
                record["part"] = part_index
                output.append(record)
        return output, completed, limited

    def _route_resume_episode(self, item):
        if not isinstance(item, dict):
            return ""
        history_episode = str(item.get("history_episode") or "").strip()
        if item.get("_resume_verified") is True and history_episode:
            return history_episode
        if item.get("_bound_route_validated") is not True:
            return ""
        route = item.get("last_play_route") if isinstance(item.get("last_play_route"), dict) else {}
        season = self._positive_int(route.get("season"), 0)
        episode = self._positive_int(route.get("episode"), 0)
        return "S%02dE%02d" % (season, episode) if season and episode else ""

    def _resource_group_episode_coverage(self, group, item, declared_season=0):
        latest = re.match(
            r"^S0*(\d{1,2})E0*(\d{1,3})$", str((item or {}).get("latest_episode") or ""), re.I,
        )
        if not latest or str((item or {}).get("media_type") or "tv") == "movie":
            return (0, 0, 0, 0)
        target_season = int(latest.group(1))
        target_episode = int(latest.group(2))
        if target_episode <= 0:
            return (0, 0, 0, 0)
        default_season = self._positive_int(declared_season, 0) or self._tracking_season(item)
        episodes = set()
        parts, _limited = _split_bounded_shared(
            group, "#", self.RESOURCE_GROUP_EPISODE_LIMIT,
        )
        for index, part in enumerate(parts, 1):
            name, separator, play_id = part.rpartition("$")
            if not separator or not play_id:
                continue
            payload = self._parse_followplay(play_id)
            if payload:
                explicit = payload.get("episodeExplicit") is not False
                season = self._positive_int(payload.get("season"), 0)
                episode = self._positive_int(payload.get("episode"), 0)
            else:
                season, episode, explicit = self._episode_from_text_info(
                    name, index, default_season,
                )
            if explicit and season == target_season and 0 < episode <= target_episode:
                episodes.add(episode)
        contiguous = 0
        while contiguous + 1 in episodes:
            contiguous += 1
        return (
            1 if len(episodes) == target_episode else 0,
            1 if target_episode in episodes else 0,
            len(episodes),
            contiguous,
        )

    def _resource_group_contains_resume(self, group, item, declared_season=0):
        resume = re.match(
            r"^S0*(\d{1,2})E0*(\d{1,3})$", self._route_resume_episode(item), re.I,
        )
        if not resume:
            return False
        target = int(resume.group(1)), int(resume.group(2))
        default_season = self._positive_int(declared_season, 0) or self._tracking_season(item)
        parts, _limited = _split_bounded_shared(
            group, "#", self.RESOURCE_GROUP_EPISODE_LIMIT,
        )
        for index, part in enumerate(parts, 1):
            name, separator, play_id = part.rpartition("$")
            if not separator or not play_id:
                continue
            payload = self._parse_followplay(play_id)
            if payload:
                explicit = payload.get("episodeExplicit") is not False
                season = self._positive_int(payload.get("season"), 0)
                episode = self._positive_int(payload.get("episode"), 0)
            else:
                season, episode, explicit = self._episode_from_text_info(
                    name, index, default_season,
                )
            if explicit and (season, episode) == target:
                return True
        return False

    def _rewrite_resource_vod(
            self, vod, item, resource_id, mode="", provider_hint="", validated=False):
        rewritten_sources = []
        rewritten_urls = []
        rewritten_seasons = []
        rewritten_providers = []
        rewritten_quality = []
        resource_limited = False
        route_candidates_limited = False
        resource_id = str(resource_id or "").strip()
        if not self._resource_id_valid(resource_id, mode or "vod"):
            kind, _decoded_resource_id = self._resource_id_kind(resource_id)
            if kind != "opaque":
                raise RuntimeError("资源 ID 过长或格式无效，已拒绝异常线路")
            resource_id = resource_id[:self.RESOURCE_ID_MAX_LENGTH]
            resource_limited = True
        raw_source = vod.get("vod_play_from")
        if not isinstance(raw_source, str):
            raw_source = ""
        source_seed = raw_source or resource_id or "AList资源"
        if len(source_seed) > self.RESOURCE_SOURCE_LABEL_MAX_LENGTH:
            source_seed = source_seed[:self.RESOURCE_SOURCE_LABEL_MAX_LENGTH]
            resource_limited = True
        source_groups, source_groups_limited = _split_bounded_shared(
            source_seed, "$$$", self.RESOURCE_PLAY_GROUP_SCAN_LIMIT,
        )
        route_candidates_limited = route_candidates_limited or source_groups_limited
        declared_quality = vod.get("_route_quality") if isinstance(vod.get("_route_quality"), list) else []
        tracking_season = self._tracking_season(item)
        vod_season = Filter._season(vod.get("vod_name"))
        resume_season = 0
        resume_episode = self._route_resume_episode(item)
        if resume_episode:
            resume = re.match(r"^S0*(\d{1,2})E0*\d{1,3}$", resume_episode, re.I)
            if resume:
                resume_season = int(resume.group(1))
        raw_play_url = vod.get("vod_play_url")
        if not isinstance(raw_play_url, str) or not raw_play_url:
            return None
        if len(raw_play_url) > self.RESOURCE_PLAY_URL_MAX_LENGTH:
            resource_limited = True
            raw_play_url = raw_play_url[:self.RESOURCE_PLAY_URL_MAX_LENGTH]
            cut_points = [raw_play_url.rfind("#"), raw_play_url.rfind("$$$")]
            cut_at = max(cut_points)
            if cut_at <= 0:
                raise RuntimeError("资源播放项过长，已拒绝异常线路")
            raw_play_url = raw_play_url[:cut_at]
        if not raw_play_url:
            return None
        raw_groups, raw_groups_limited = _split_bounded_shared(
            raw_play_url, "$$$", self.RESOURCE_PLAY_GROUP_SCAN_LIMIT,
        )
        route_candidates_limited = route_candidates_limited or raw_groups_limited
        invalid_entries = 0
        for group_index, group in enumerate(raw_groups):
            parts, parts_limited = _split_bounded_shared(
                group, "#", self.RESOURCE_GROUP_EPISODE_LIMIT,
            )
            resource_limited = resource_limited or parts_limited
            if not parts:
                continue
            group = "#".join(parts)
            source_name = source_groups[group_index] if group_index < len(source_groups) else "AList资源"
            if mode:
                source_name = self._resource_mode_label(mode, source_name, validated=validated)
            group_season = Filter._season(source_name) or vod_season
            default_season = group_season or resume_season or tracking_season
            parsed_entries = []
            for index, part in enumerate(parts, 1):
                name, separator, target = part.rpartition("$")
                if not separator:
                    invalid_entries += 1
                    continue
                season, episode, explicit = self._episode_from_text_info(name, index, default_season)
                label_season = Filter._season(name)
                if label_season and group_season and label_season != group_season:
                    explicit = False
                elif not label_season and not group_season and not resume_season and tracking_season != 1:
                    explicit = False
                parsed_entries.append({
                    "name": name,
                    "target": target,
                    "season": season,
                    "episode": episode,
                    "explicit": explicit,
                    "label_season": label_season,
                })
            latest = re.match(r"^S0*(\d{1,2})E0*(\d{1,3})$", str(item.get("latest_episode") or ""), re.I)
            latest_season = int(latest.group(1)) if latest else 0
            latest_episode = int(latest.group(2)) if latest else 0
            raw_numbers = [row["episode"] for row in parsed_entries]
            if (
                    group_season > 1
                    and latest_season == group_season
                    and latest_episode == len(parsed_entries)
                    and parsed_entries
                    and all(row["explicit"] and not row["label_season"] for row in parsed_entries)
                    and raw_numbers == list(range(raw_numbers[0], raw_numbers[0] + len(raw_numbers)))
                    and raw_numbers[0] > 1):
                offset = raw_numbers[0] - 1
                for row in parsed_entries:
                    row["episode"] -= offset
            metadata_provider = self._resource_provider_key(provider_hint, resource_id, source_name)
            target_providers = {
                provider for provider in (
                    self._resource_provider_key(row.get("target")) for row in parsed_entries
                ) if provider
            }
            unknown_target_url = any(
                urlparse(str(row.get("target") or "")).scheme in ("http", "https")
                and bool(urlparse(str(row.get("target") or "")).hostname)
                and not self._resource_provider_key(row.get("target"))
                for row in parsed_entries
            )
            if unknown_target_url or len(target_providers) > 1:
                resolved_provider = ""
            elif target_providers:
                target_provider = next(iter(target_providers))
                resolved_provider = (
                    target_provider
                    if not metadata_provider or metadata_provider == target_provider
                    else ""
                )
            else:
                resolved_provider = metadata_provider
            entries = []
            kept_parsed_entries = []
            group_rewritten_length = 0
            for row in parsed_entries:
                play_id = self._build_followplay(
                    row["target"], item, resource_id, row["season"], row["episode"], row["name"],
                    resource_mode=mode,
                    resource_provider=resolved_provider,
                    episode_explicit=row["explicit"],
                )
                if play_id:
                    entry = "%s$%s" % (row["name"] or ("第%s集" % row["episode"]), play_id)
                    separator_length = 1 if entries else 0
                    if (
                            group_rewritten_length + separator_length + len(entry)
                            > self.RESOURCE_REWRITE_GROUP_URL_LIMIT):
                        resource_limited = True
                        break
                    entries.append(entry)
                    kept_parsed_entries.append(row)
                    group_rewritten_length += separator_length + len(entry)
                else:
                    invalid_entries += 1
            parsed_entries = kept_parsed_entries
            if entries:
                preferred_keys = []
                for value in (resume_episode, item.get("latest_episode")):
                    match = re.match(r"^S0*(\d{1,2})E0*(\d{1,3})$", str(value or ""), re.I)
                    if match:
                        preferred_keys.append((int(match.group(1)), int(match.group(2))))
                representative = next((
                    row["target"] for key in preferred_keys for row in parsed_entries
                    if row["explicit"] and (row["season"], row["episode"]) == key and row["target"]
                ), "") or next((row["target"] for row in parsed_entries if row["target"]), "")
                quality = (
                    dict(declared_quality[group_index])
                    if group_index < len(declared_quality) and isinstance(declared_quality[group_index], dict)
                    else self._route_quality_score(representative, text="%s %s" % (source_name, group))
                )
                source_name = self._strip_legacy_route_quality_label(source_name)
                rewritten_sources.append(source_name)
                rewritten_urls.append("#".join(entries))
                rewritten_seasons.append(group_season or default_season)
                rewritten_providers.append(resolved_provider)
                rewritten_quality.append(quality)
        if not rewritten_urls:
            if invalid_entries:
                raise RuntimeError("资源播放项无效，已拒绝异常线路")
            return None
        return {
            "vod_play_from": "$$$".join(rewritten_sources),
            "vod_play_url": "$$$".join(rewritten_urls),
            "resource_id": str(resource_id or ""),
            "group_seasons": rewritten_seasons,
            "group_providers": rewritten_providers,
            "group_quality": rewritten_quality,
            "_resource_limited": resource_limited,
            "_route_candidates_limited": route_candidates_limited,
        }

    def _resume_episode_match(self, urls, resource_ids, item):
        resume_episode = self._route_resume_episode(item)
        if not resume_episode:
            return None
        target = re.match(r"^S(\d{2})E(\d{2,3})$", resume_episode)
        if not target:
            return None
        target_season, target_episode = int(target.group(1)), int(target.group(2))
        preferred = str(item.get("alist_vod_id") or "").strip()
        ranked = []
        for group_index, group in enumerate(urls):
            resource_id = resource_ids[group_index] if group_index < len(resource_ids) else ""
            parts, _limited = _split_bounded_shared(
                group, "#", self.RESOURCE_GROUP_EPISODE_LIMIT,
            )
            for part_index, part in enumerate(parts):
                name, separator, play_id = part.rpartition("$")
                if not separator or not play_id:
                    continue
                payload = self._parse_followplay(play_id)
                if payload and payload.get("episodeExplicit") is False:
                    continue
                season = self._positive_int(payload.get("season"), 0) if payload else 0
                episode = self._positive_int(payload.get("episode"), 0) if payload else 0
                if payload:
                    if season != target_season or episode != target_episode:
                        continue
                    score = 1000
                else:
                    explicit = bool(re.search(r"(?i)S\s*0*\d+\s*E(?:P)?\s*0*\d+|第\s*\d+\s*[集话]|\bEP?\s*0*\d+", name))
                    parsed_season, parsed_episode = self._episode_from_text(name, part_index + 1, target_season)
                    if explicit and parsed_season == target_season and parsed_episode == target_episode:
                        score = 900
                    else:
                        continue
                if preferred and resource_id == preferred:
                    score += 100
                ranked.append((score, -group_index, -part_index, group_index, part_index))
        if not ranked:
            return None
        ranked.sort(reverse=True)
        return ranked[0][3], ranked[0][4]

    def _merge_resource_vods(self, vods, item, raw_id, base_vod, preferred_resource_id=""):
        resource_limited = False
        route_candidates_limited = False
        streams = []
        for vod_index, vod in enumerate(vods or []):
            if vod_index >= self.RESOURCE_PLAY_GROUP_SCAN_LIMIT:
                route_candidates_limited = True
                break
            if not isinstance(vod, dict):
                continue
            play_url = vod.get("vod_play_url")
            resource_limited = resource_limited or bool(vod.get("_resource_limited"))
            route_candidates_limited = (
                route_candidates_limited or bool(vod.get("_route_candidates_limited"))
            )
            if not isinstance(play_url, str) or not play_url:
                resource_limited = True
                continue
            if len(play_url) > self.RESOURCE_REWRITTEN_PLAY_URL_MAX_LENGTH:
                resource_limited = True
                continue
            source_groups, source_groups_limited = _split_bounded_shared(
                vod.get("vod_play_from") or "AList资源",
                "$$$", self.RESOURCE_PLAY_GROUP_SCAN_LIMIT,
            )
            group_urls, group_urls_limited = _split_bounded_shared(
                play_url, "$$$", self.RESOURCE_PLAY_GROUP_SCAN_LIMIT,
            )
            route_candidates_limited = (
                route_candidates_limited or source_groups_limited or group_urls_limited
            )
            if not group_urls:
                resource_limited = True
                continue
            streams.append({
                "vod": vod,
                "sources": source_groups,
                "urls": group_urls,
            })
        if not streams:
            return None

        candidates = []
        for depth in range(self.RESOURCE_PLAY_GROUP_SCAN_LIMIT):
            found_at_depth = False
            for stream in streams:
                group_urls = stream["urls"]
                if depth >= len(group_urls):
                    continue
                found_at_depth = True
                vod = stream["vod"]
                source_groups = stream["sources"]
                resource_id = str(vod.get("resource_id") or "").strip()
                declared_seasons = vod.get("group_seasons") if isinstance(vod.get("group_seasons"), list) else []
                declared_providers = vod.get("group_providers") if isinstance(vod.get("group_providers"), list) else []
                declared_quality = vod.get("group_quality") if isinstance(vod.get("group_quality"), list) else []
                base_source = source_groups[depth] if depth < len(source_groups) else "AList资源"
                quality = (
                    dict(declared_quality[depth])
                    if depth < len(declared_quality) and isinstance(declared_quality[depth], dict)
                    else {}
                )
                declared_season = self._positive_int(
                    declared_seasons[depth] if depth < len(declared_seasons) else 0, 0,
                )
                provider = (
                    self._resource_provider_key(declared_providers[depth])
                    if depth < len(declared_providers)
                    else self._resource_provider_key(base_source, resource_id)
                )
                candidates.append({
                    "source": str(base_source or "AList资源").strip() or "AList资源",
                    "url": group_urls[depth],
                    "resource_id": resource_id,
                    "season": declared_season,
                    "provider": provider,
                    "coverage": self._resource_group_episode_coverage(
                        group_urls[depth], item, declared_season,
                    ),
                    "resume": self._resource_group_contains_resume(
                        group_urls[depth], item, declared_season,
                    ),
                    "quality": quality,
                    "mode": str(vod.get("_resource_mode") or "").strip().lower(),
                    "order": len(candidates),
                })
                if len(candidates) >= self.RESOURCE_PLAY_GROUP_SCAN_LIMIT:
                    route_candidates_limited = True
                    break
            if len(candidates) >= self.RESOURCE_PLAY_GROUP_SCAN_LIMIT or not found_at_depth:
                break
        if not candidates:
            return None

        resume_active = bool(self._route_resume_episode(item))

        def candidate_quality(candidate):
            quality = candidate["quality"]
            resume_score = 0
            if candidate.get("resume"):
                resume_score = 2 if (
                    resume_active
                    and preferred_resource_id
                    and candidate["resource_id"] == preferred_resource_id
                ) else 1
            return (
                resume_score,
                *candidate.get("coverage", (0, 0, 0, 0)),
                1 if (
                    not resume_active
                    and preferred_resource_id
                    and candidate["resource_id"] == preferred_resource_id
                ) else 0,
                self._positive_int(quality.get("resolution"), 0),
                self._positive_int(quality.get("total"), 0),
                self._positive_int(quality.get("startup"), 0),
                self._positive_int(quality.get("stability"), 0),
                -candidate["order"],
            )

        best_by_mode = {}
        for candidate in candidates:
            mode = candidate["mode"]
            if mode in self.RESOURCE_SEARCH_MODES and (
                    mode not in best_by_mode
                    or candidate_quality(candidate) > candidate_quality(best_by_mode[mode])):
                best_by_mode[mode] = candidate
        mode_best = sorted(best_by_mode.values(), key=candidate_quality, reverse=True)
        preserved = list(mode_best)
        preferred_candidates = [
            candidate for candidate in candidates
            if preferred_resource_id and candidate["resource_id"] == preferred_resource_id
        ]
        if preferred_candidates:
            preferred_candidate = max(preferred_candidates, key=candidate_quality)
            if all(id(candidate) != id(preferred_candidate) for candidate in preserved):
                preserved.append(preferred_candidate)
        preserved_ids = {id(candidate) for candidate in preserved}
        remaining_candidates = sorted(
            (candidate for candidate in candidates if id(candidate) not in preserved_ids),
            key=candidate_quality,
            reverse=True,
        )
        route_limit = min(self.resource_limit, self.FOLLOW_ROUTE_LIMIT)
        ordered_candidates = sorted(preserved, key=candidate_quality, reverse=True) + remaining_candidates
        if len(ordered_candidates) > route_limit:
            route_candidates_limited = True
        selected_candidates = ordered_candidates[:route_limit]

        output = dict(base_vod)
        sources = []
        urls = []
        resource_ids = []
        group_seasons = []
        group_providers = []
        quality_scores = []
        candidate_parts = []
        for candidate in selected_candidates:
            parts, parts_limited = _split_bounded_shared(
                candidate["url"], "#", self.RESOURCE_GROUP_EPISODE_LIMIT,
            )
            resource_limited = resource_limited or parts_limited
            valid_parts = []
            for part in parts:
                _name, separator, play_id = part.rpartition("$")
                if separator and play_id:
                    valid_parts.append(part)
            candidate_parts.append(valid_parts)

        accepted_parts = [[] for _candidate in selected_candidates]
        accepted_episode_count = 0
        merged_play_length = 0
        max_depth = max([len(parts) for parts in candidate_parts] or [0])
        for depth in range(max_depth):
            for group_index, parts in enumerate(candidate_parts):
                if depth >= len(parts):
                    continue
                if accepted_episode_count >= self.RESOURCE_RECORD_LIMIT:
                    resource_limited = True
                    break
                part = parts[depth]
                separator_length = 1 if accepted_parts[group_index] else (
                    3 if any(accepted_parts) else 0
                )
                if merged_play_length + separator_length + len(part) > self.RESOURCE_MERGED_PLAY_URL_BUDGET:
                    resource_limited = True
                    continue
                accepted_parts[group_index].append(part)
                accepted_episode_count += 1
                merged_play_length += separator_length + len(part)
            if accepted_episode_count >= self.RESOURCE_RECORD_LIMIT:
                break

        for candidate, parts in zip(selected_candidates, accepted_parts):
            if not parts:
                continue
            group_url = "#".join(parts)
            sources.append(candidate["source"])
            urls.append(group_url)
            resource_ids.append(candidate["resource_id"])
            group_seasons.append(candidate["season"] or self._resource_group_season(group_url))
            group_providers.append(candidate["provider"])
            quality_scores.append(candidate["quality"])
        if not urls:
            return None

        resume_match = self._resume_episode_match(urls, resource_ids, item)
        resume_part_index = -1
        if resume_match:
            group_index, resume_part_index = resume_match
            for values in (sources, urls, resource_ids, group_seasons, group_providers, quality_scores):
                values.insert(0, values.pop(group_index))
        source_names = set()
        for group_index, base_source in enumerate(list(sources)):
            base_source = self._resource_source_with_season(
                base_source,
                group_seasons[group_index] if group_index < len(group_seasons) else 0,
            )
            source = self._unique_resource_source(
                base_source, resource_ids[group_index], group_index, source_names,
            )
            source_names.add(source)
            sources[group_index] = source

        records = []
        for group_index, real_group in enumerate(urls):
            resource_id = resource_ids[group_index] if group_index < len(resource_ids) else ""
            parts, _limited = _split_bounded_shared(
                real_group, "#", self.RESOURCE_GROUP_EPISODE_LIMIT,
            )
            for part_index, part in enumerate(parts):
                name, separator, play_id = part.rpartition("$")
                if not separator or not play_id:
                    continue
                payload = self._parse_followplay(play_id)
                if payload:
                    episode_key = (
                        self._positive_int(payload.get("season"), 0),
                        self._positive_int(payload.get("episode"), 0),
                    )
                    explicit = payload.get("episodeExplicit") is not False
                else:
                    season, episode, explicit = self._episode_from_text_info(
                        name, part_index + 1, self._tracking_season(item)
                    )
                    episode_key = (season, episode)
                if not explicit or not episode_key[0] or not episode_key[1]:
                    episode_key = ("unknown", group_index, part_index)
                records.append({
                    "group": group_index,
                    "part": part_index,
                    "name": name,
                    "play_id": play_id,
                    "resource_id": resource_id,
                    "provider": group_providers[group_index] if group_index < len(group_providers) else "",
                    "origin_part": part_index,
                    "episode_key": episode_key,
                    "payload": payload,
                })
        records, completion_total, completion_limited = self._complete_same_provider_groups(
            records,
            self.RESOURCE_MERGED_PLAY_URL_BUDGET - merged_play_length,
        )
        final_records = []
        final_length = 0
        final_group = None
        for record in records:
            group_index = self._int_value(record.get("group"), -1)
            part = "%s$%s" % (record.get("name") or "", record.get("play_id") or "")
            separator_length = 1 if final_group == group_index else (3 if final_records else 0)
            if final_length + separator_length + len(part) > self.RESOURCE_MERGED_PLAY_URL_BUDGET:
                resource_limited = True
                break
            final_records.append(record)
            final_length += separator_length + len(part)
            final_group = group_index
        records = final_records
        if not records:
            return None

        kept_group_order = []
        for record in records:
            group_index = self._int_value(record.get("group"), -1)
            if group_index not in kept_group_order:
                kept_group_order.append(group_index)
        group_remap = {group_index: index for index, group_index in enumerate(kept_group_order)}
        for record in records:
            record["group"] = group_remap[self._int_value(record.get("group"), -1)]
        for values in (sources, urls, resource_ids, group_seasons, group_providers, quality_scores):
            values[:] = [values[index] for index in kept_group_order]

        completion_total = sum(1 for record in records if record.get("completed"))
        self._schedule_route_preheat(records, item)
        rebuilt_groups = {}
        for record in records:
            rebuilt_groups.setdefault(record["group"], []).append(record)
        resume_group_url = ""
        for group_index, group_records in rebuilt_groups.items():
            if resume_match and group_index == 0:
                for record in group_records:
                    if record.get("origin_part", record["part"]) == resume_part_index and not record.get("completed"):
                        target_season, target_episode = record["episode_key"]
                        later_records = [
                            candidate for candidate in group_records
                            if candidate is not record
                            and isinstance(candidate["episode_key"][0], int)
                            and isinstance(candidate["episode_key"][1], int)
                            and candidate["episode_key"][0] == target_season
                            and candidate["episode_key"][1] > target_episode
                        ]
                        later_records.sort(key=lambda candidate: (candidate["episode_key"][1], candidate["part"]))
                        unique_later_records = []
                        seen_episodes = set()
                        for candidate in later_records:
                            episode_number = candidate["episode_key"][1]
                            if episode_number in seen_episodes:
                                continue
                            seen_episodes.add(episode_number)
                            unique_later_records.append(candidate)
                        prioritized_ids = {id(candidate) for candidate in unique_later_records}
                        remaining_records = [
                            candidate for candidate in group_records
                            if candidate is not record and id(candidate) not in prioritized_ids
                        ]
                        resume_records = [record] + unique_later_records + remaining_records
                        resume_parts = []
                        for resume_index, resume_record in enumerate(resume_records):
                            resume_name = resume_record["name"]
                            if resume_index == 0:
                                resume_name = "继续播放 %s（从选集播放记录恢复）" % str(self._route_resume_episode(item) or resume_name)
                            resume_parts.append("%s$%s" % (resume_name, resume_record["play_id"]))
                        resume_group_url = "#".join(resume_parts)
                        break
            urls[group_index] = "#".join(
                "%s$%s" % (record["name"], record["play_id"])
                for record in group_records
            )

        resume_ready = bool(resume_match and resume_group_url)
        flags = []
        output_sources = []
        prompted_urls = []
        if resume_ready:
            resume_source = "继续播放 · " + sources[0]
            resume_episodes = []
            resume_parts, _limited = _split_bounded_shared(
                resume_group_url, "#", self.RESOURCE_RECORD_LIMIT,
            )
            for part in resume_parts:
                name, separator, url = part.rpartition("$")
                if separator and url:
                    resume_episodes.append({"name": name, "url": url, "selected": False})
            output_sources.append(resume_source)
            prompted_urls.append(resume_group_url)
            flags.append({
                "flag": resume_source,
                "urls": resume_group_url,
                "position": 0,
                "selected": False,
                "episodes": resume_episodes,
            })
        for index, source in enumerate(sources):
            if resume_ready and index == 0:
                continue
            real_group = urls[index] if index < len(urls) else ""
            episodes = []
            real_parts, _limited = _split_bounded_shared(
                real_group, "#", self.RESOURCE_RECORD_LIMIT,
            )
            for part_index, part in enumerate(real_parts):
                name, separator, url = part.rpartition("$")
                if separator and url:
                    episodes.append({"name": name, "url": url, "selected": False})
            prompt_id = self.SELECT_PROMPT_ID + ":%s" % index
            prompt = "选集播放$" + prompt_id
            group_url = prompt + (("#" + real_group) if real_group else "")
            prompt_episode = {"name": "选集播放", "url": prompt_id, "selected": not resume_ready and index == 0}
            structured_episodes = [prompt_episode] + episodes
            output_source = ("全部选集 · " + source) if resume_ready else source
            output_sources.append(output_source)
            prompted_urls.append(group_url)
            flags.append({
                "flag": output_source,
                "urls": group_url,
                "position": -1 if resume_ready else 0,
                "selected": not resume_ready and index == 0,
                "episodes": structured_episodes,
            })
        old_remark = str(output.get("vod_remarks") or "").strip()
        resume_remark = ("续播定位 " + str(self._route_resume_episode(item) or "")) if resume_ready else ""
        completion_remark = ("同盘补全 %d 集" % completion_total) if completion_total else ""
        limit_remark = "资源分集过多 已截断" if resource_limited or completion_limited else ""
        route_remark = "线路候选已按清晰度筛选" if route_candidates_limited else ""
        _hot_ready, hot_pending = self._supplement_resource_state(item)
        shown_verified = sum("已验证 ·" in str(source) for source in sources)
        shown_candidates = max(0, len(sources) - shown_verified)
        hot_remark = "当前候选 %d 条 · 当前已验证 %d 条" % (shown_candidates, shown_verified)
        if hot_pending:
            hot_remark = " · ".join(value for value in (hot_remark, "后台线路验证中") if value)
        history_name = str(item.get("history_vod_name") or "").strip()
        title_aliases = {
            Filter._normalize_title(value)
            for value in self._follow_title_alias_values(item)
        } - {""}
        history_title = Filter._normalize_title(history_name)
        if not any(Filter._title_score(history_title, alias) > 0 for alias in title_aliases):
            history_name = ""
        output.update({
            "vod_id": raw_id,
            "vod_name": history_name or str(output.get("vod_name") or item.get("title") or "影视资源"),
            "vod_remarks": " · ".join(value for value in (
                old_remark, "%s 条播放线路" % len(urls), hot_remark, resume_remark,
                completion_remark, limit_remark,
                route_remark,
            ) if value),
            "vod_play_from": "$$$".join(output_sources),
            "vod_play_url": "$$$".join(prompted_urls),
            "vodFlags": flags,
        })
        return output

    @classmethod
    def _payload_list(cls, value, limit=None):
        max_items = None if limit is None else max(0, cls._int_value(limit, 0))
        if max_items == 0:
            return []
        if isinstance(value, dict):
            for key in ("list", "data", "items", "results"):
                candidate = value.get(key)
                if isinstance(candidate, list):
                    rows = []
                    for row in candidate:
                        if isinstance(row, dict):
                            rows.append(row)
                            if max_items is not None and len(rows) >= max_items:
                                break
                    return rows
            if isinstance(value.get("data"), dict):
                return cls._payload_list(value.get("data"), limit=max_items)
        return []

    @classmethod
    def _payload_first_vod(cls, value):
        rows = cls._payload_list(value, limit=1)
        return rows[0] if rows else None

    def _supplement_resource_state(self, item):
        if not any(mode in self.RESOURCE_SUPPLEMENT_MODES for mode in self._available_resource_modes()):
            return 0, False
        cache_key = self._resource_search_cache_key(item, "supplement")
        cached = self._cache_get(cache_key, self.RESOURCE_SEARCH_CACHE_TTL)
        ready = self._validated_resource_group_count(cached if isinstance(cached, list) else [])
        with self._cache_lock:
            pending = cache_key in self._resource_search_jobs
        return ready, pending

    @staticmethod
    def _resource_mode_label(mode, source, validated=False):
        labels = {
            "vod1": "点播候选",
            "vod": "网盘候选",
            "pansou": "盘搜已验证" if validated else "盘搜候选",
            "telegram": "电报已验证" if validated else "电报候选",
        }
        prefix = labels.get(str(mode or ""), "资源")
        value = str(source or "AList资源").strip() or "AList资源"
        return value if value.startswith(prefix + " · ") else "%s · %s" % (prefix, value)

    def _read_bounded_json_response(self, response, label, deadline=None, max_bytes=None):
        max_bytes = self._positive_int(max_bytes, 0) or self.RESOURCE_API_RESPONSE_MAX_BYTES
        return _read_bounded_json_shared(response, label, max_bytes, deadline=deadline)

    def _resource_api_get(self, mode, params, deadline=None):
        if mode not in self.RESOURCE_SEARCH_MODES:
            raise RuntimeError("不支持的资源搜索模式：%s" % mode)
        if self._resource_capability(mode) == "missing":
            raise RuntimeError("AList %s 接口已确认缺失" % mode)
        if not self._ensure_atvp_connection(force=True):
            raise RuntimeError("未配置 AList-TVBox 地址或令牌")
        with self._cache_lock:
            expected_generation = self._cache_generation
            expected_backend = self._resource_capability_identity()
        endpoint_mode = "tg-search" if mode == "telegram" else mode
        response = self._atvp_session.get(
            self._atvp_endpoint(endpoint_mode),
            params=params,
            headers={"Accept": "application/json", "X-CLIENT": "com.fongmi.android.tv"},
            timeout=self._atvp_deadline_timeout(
                deadline, max(5, min(12, self.timeout)), requests_left=1,
            ),
            verify=self.verify_tls,
            stream=True,
        )
        status = int(response.status_code)
        self._mark_resource_capability(
            mode,
            "missing" if status in self.RESOURCE_CAPABILITY_MISSING_STATUSES else "present",
            status,
            expected_backend=expected_backend,
            expected_generation=expected_generation,
        )
        if status < 200 or status >= 300:
            closer = getattr(response, "close", None)
            if callable(closer):
                closer()
            raise RuntimeError("AList %s HTTP %s" % (mode, status))
        value = self._read_bounded_json_response(response, "AList %s" % mode, deadline=deadline)
        return value if isinstance(value, dict) else {"list": value if isinstance(value, list) else []}

    def _atvp_vod(self, params):
        return self._resource_api_get("vod", params)

    @staticmethod
    def _atvp_deadline_timeout(deadline, default_timeout, requests_left=1):
        if deadline is None:
            return max(1, int(default_timeout))
        remaining = deadline - time.monotonic()
        if remaining < 1:
            raise RuntimeError("播放线路总预算已耗尽")
        # The session may retry twice, and a scalar requests timeout applies to
        # connect and read separately. Divide the remaining budget accordingly.
        retry_phases = max(1, int(requests_left)) * 6
        return max(1, min(float(default_timeout), remaining / retry_phases))

    def _atvp_play(self, play_id, timeout_seconds=None, deadline=None,
                   expected_generation=None, expected_backend=None):
        target = str(play_id or "").strip()
        if not target:
            raise RuntimeError("播放线路为空")
        if len(target) > self.FOLLOWPLAY_MAX_URL_LENGTH:
            raise RuntimeError("播放线路过长，已拒绝异常请求")
        with self._history_context_lock:
            if not self._ensure_atvp_connection(force=True):
                raise RuntimeError("未配置 AList-TVBox 地址或令牌")
            with self._cache_lock:
                current_generation = self._cache_generation
                current_backend = self._resource_capability_identity()
                if expected_generation is not None and expected_generation != current_generation:
                    raise RuntimeError("播放后端已切换，请重试")
                if expected_backend is not None and expected_backend != current_backend:
                    raise RuntimeError("播放后端已切换，请重试")
                request_api = str(self.atvp_api or "").rstrip("/")
                request_token = str(self.atvp_token or "")
                request_session = self._atvp_session
        if re.match(r"^(?:https?://|magnet:|ed2k:|thunder:)", target, re.I):
            parsed_target = urlparse(target)
            parsed_api = urlparse(request_api)
            path_parts = [unquote(part) for part in parsed_target.path.split("/") if part]
            api_parts = [unquote(part) for part in parsed_api.path.split("/") if part]
            relative_parts = path_parts[len(api_parts):] if path_parts[:len(api_parts)] == api_parts else []
            same_backend_play = (
                parsed_target.scheme.lower() == parsed_api.scheme.lower()
                and parsed_target.netloc.lower() == parsed_api.netloc.lower()
                and len(relative_parts) == 3
                and relative_parts[0] == "p"
                and relative_parts[1] == request_token
                and re.match(r"^\d+@[^/?#]+$", relative_parts[2])
            )
            if same_backend_play:
                target = relative_parts[2]
            else:
                candidates = self._atvp_parse_candidates(
                    target,
                    timeout_seconds=timeout_seconds,
                    deadline=deadline,
                    request_api=request_api,
                    request_token=request_token,
                    request_session=request_session,
                )
                if not candidates:
                    raise RuntimeError("AList 解析未返回可播放候选")
                target = candidates[0]
        if len(target) > self.FOLLOWPLAY_MAX_URL_LENGTH:
            raise RuntimeError("播放线路过长，已拒绝异常请求")
        request_timeout = self._atvp_deadline_timeout(
            deadline,
            timeout_seconds if timeout_seconds is not None else max(30, self.timeout),
            requests_left=1,
        )
        play_url = "%s/play/%s" % (request_api, quote(request_token, safe=""))
        response = request_session.get(
            play_url,
            params={"id": target, "type": "client-proxy", "from": "jar"},
            headers={"Accept": "application/json", "X-CLIENT": "com.fongmi.android.tv"},
            timeout=request_timeout,
            verify=self.verify_tls,
            stream=True,
        )
        if response.status_code < 200 or response.status_code >= 300:
            closer = getattr(response, "close", None)
            if callable(closer):
                closer()
            raise RuntimeError("AList 播放 HTTP %s" % response.status_code)
        data = self._read_bounded_json_response(response, "AList 播放", deadline=deadline)
        if not isinstance(data, dict) or not data.get("url"):
            raise RuntimeError("AList 播放地址为空")
        output = dict(data)
        if str(output.get("url") or "").startswith("/"):
            output["url"] = request_api + str(output["url"])
        return output

    def _atvp_parse_candidates(self, resource_url, timeout_seconds=None, deadline=None,
                               request_api=None, request_token=None, request_session=None):
        request_api = str(request_api if request_api is not None else self.atvp_api).rstrip("/")
        request_token = str(request_token if request_token is not None else self.atvp_token)
        request_session = request_session if request_session is not None else self._atvp_session
        parse_url = "%s/parse/%s" % (request_api, quote(request_token, safe=""))
        request_timeout = self._atvp_deadline_timeout(
            deadline,
            timeout_seconds if timeout_seconds is not None else max(35, self.timeout),
            requests_left=2,
        )
        response = request_session.post(
            parse_url,
            params={"ac": "play"},
            json={"url": str(resource_url or "")},
            headers={"Content-Type": "application/json", "X-CLIENT": "com.fongmi.android.tv"},
            timeout=request_timeout,
            verify=self.verify_tls,
            stream=True,
        )
        if response.status_code < 200 or response.status_code >= 300:
            closer = getattr(response, "close", None)
            if callable(closer):
                closer()
            raise RuntimeError("AList 解析 HTTP %s" % response.status_code)
        payload = self._read_bounded_json_response(response, "AList 解析", deadline=deadline)
        candidates = []
        for vod in self._payload_list(payload, limit=self.RESOURCE_PARSE_CANDIDATE_LIMIT):
            groups, _groups_limited = _split_bounded_shared(
                vod.get("vod_play_url"), "$$$", self.RESOURCE_PLAY_GROUP_SCAN_LIMIT,
            )
            for group in groups:
                parts, _parts_limited = _split_bounded_shared(
                    group, "#", self.RESOURCE_GROUP_EPISODE_LIMIT,
                )
                for part in parts:
                    _name, separator, target = part.rpartition("$")
                    candidate = str(target if separator else part).strip()
                    if (
                            candidate.startswith("1@")
                            and len(candidate) <= self.FOLLOWPLAY_MAX_URL_LENGTH
                            and candidate not in candidates):
                        candidates.append(candidate)
                        if len(candidates) >= self.RESOURCE_PARSE_CANDIDATE_LIMIT:
                            return candidates
        return candidates

    def _route_probe_key(self, target, resource_id="", resource_mode="vod", backend=None):
        target = str(target or "").strip()
        resource_id = str(resource_id or "").strip()
        mode = str(resource_mode or "vod").strip().lower() or "vod"
        backend = str(backend if backend is not None else self._resource_capability_identity())
        if not target or not resource_id or not backend:
            return ""
        raw = "%s|%s|%s|%s" % (backend, mode, resource_id, target)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _route_probe_snapshot(self, target, resource_id="", resource_mode="vod"):
        key = self._route_probe_key(target, resource_id, resource_mode)
        if not key:
            return None
        with self._cache_lock:
            self._prune_route_probe_cache_locked()
            cached = self._route_probe_cache.get(key)
            if not isinstance(cached, dict):
                return None
            return dict(cached)

    def _invalidate_route_probe(self, target, resource_id="", resource_mode="vod"):
        """Remove one short-lived probe/signed-output entry before a source switch."""
        key = self._route_probe_key(target, resource_id, resource_mode)
        if not key:
            return False
        with self._cache_lock:
            removed = self._route_probe_cache.pop(key, None) is not None
        return removed

    def _prune_route_probe_cache_locked(self):
        now = time.time()
        expired = [
            key for key, value in self._route_probe_cache.items()
            if not isinstance(value, dict)
            or now - float(value.get("checked_at") or 0) > (
                min(self.route_probe_ttl, self.ROUTE_PROBE_NEGATIVE_TTL)
                if value.get("reachable") is False else self.route_probe_ttl
            )
        ]
        for key in expired:
            self._route_probe_cache.pop(key, None)
        overflow = len(self._route_probe_cache) - self.ROUTE_PROBE_CACHE_LIMIT
        if overflow <= 0:
            return
        oldest = sorted(
            self._route_probe_cache,
            key=lambda key: float(self._route_probe_cache[key].get("checked_at") or 0),
        )
        for key in oldest[:overflow]:
            self._route_probe_cache.pop(key, None)

    def _route_quality_key(self, play_id):
        target = str(play_id or "").strip()
        api = str(self.atvp_api or "").rstrip("/")
        if not target or not api:
            return ""
        raw = "%s|%s|%s" % (api, Filter._token_hash(self.atvp_token), target)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _load_route_quality_history(self):
        with self._cache_lock:
            if self._route_quality_loaded:
                return
            self._route_quality_loaded = True
        getter = getattr(self, "getCache", None)
        if not callable(getter):
            return
        try:
            value = getter(self.ROUTE_QUALITY_CACHE_KEY)
        except Exception:
            return
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except Exception:
                return
        if isinstance(value, dict) and isinstance(value.get("value"), dict):
            value = value.get("value")
        if not isinstance(value, dict) or value.get("version") != self.ROUTE_QUALITY_VERSION:
            return
        entries = value.get("entries")
        if not isinstance(entries, dict):
            return
        now = int(time.time())
        restored = {}
        for key, raw in entries.items():
            if not re.fullmatch(r"[0-9a-f]{64}", str(key or "")) or not isinstance(raw, dict):
                continue
            updated_at = self._positive_int(raw.get("updatedAt"), 0)
            if updated_at <= 0 or now - updated_at > self.ROUTE_QUALITY_MAX_AGE:
                continue
            restored[str(key)] = {
                "successes": self._positive_int(raw.get("successes"), 0),
                "failures": self._positive_int(raw.get("failures"), 0),
                "timedSuccesses": self._positive_int(raw.get("timedSuccesses"), 0),
                "avgStartupMs": self._positive_int(raw.get("avgStartupMs"), 0),
                "codec": str(raw.get("codec") or ""),
                "height": self._positive_int(raw.get("height"), 0),
                "subtitle": raw.get("subtitle") if isinstance(raw.get("subtitle"), bool) else None,
                "updatedAt": updated_at,
            }
        with self._cache_lock:
            self._route_quality_history.update(restored)

    def _schedule_route_quality_save(self):
        setter = getattr(self, "setCache", None)
        if not callable(setter):
            return False
        job_owner = object()
        with self._cache_lock:
            self._route_quality_dirty = True
            if self._route_quality_saving:
                return True
            self._route_quality_saving = job_owner
            generation = self._cache_generation

        def worker():
            time.sleep(0.05)
            with self._cache_lock:
                if generation != self._cache_generation:
                    if self._route_quality_saving is job_owner:
                        self._route_quality_saving = None
                    return
                ordered = sorted(
                    self._route_quality_history.items(),
                    key=lambda entry: self._positive_int(entry[1].get("updatedAt"), 0),
                    reverse=True,
                )[:self.ROUTE_QUALITY_LIMIT]
                payload = {
                    "version": self.ROUTE_QUALITY_VERSION,
                    "entries": {key: dict(value) for key, value in ordered},
                }
                self._route_quality_dirty = False
            error = None
            saved = False
            with self._cache_persist_lock:
                try:
                    with self._cache_lock:
                        if (generation != self._cache_generation
                                or self._route_quality_saving is not job_owner):
                            return
                    result = setter(self.ROUTE_QUALITY_CACHE_KEY, payload)
                    saved = str(result or "").strip().lower() != "failed"
                except Exception as exc:
                    error = exc
                with self._cache_lock:
                    if generation != self._cache_generation:
                        if self._route_quality_saving is job_owner:
                            self._route_quality_saving = None
                        return
                    if self._route_quality_saving is not job_owner:
                        return
                    if not saved:
                        self._route_quality_dirty = True
                    repeat = bool(saved and self._route_quality_dirty)
                    self._route_quality_saving = None
            if not saved:
                self._diagnostic_event(
                    "route_quality.save", "WARN", exc=error,
                    generation=generation, count=len(payload["entries"]),
                    result="failed" if error is None else "exception",
                )
            if repeat:
                self._schedule_route_quality_save()

        try:
            self._tasks.start_thread(worker, name="route-quality-save")
        except Exception:
            with self._cache_lock:
                if self._route_quality_saving is job_owner:
                    self._route_quality_saving = None
            return False
        return True

    def _flush_route_quality_sync(self):
        setter = getattr(self, "setCache", None)
        if not callable(setter):
            return False
        with self._cache_lock:
            if not self._route_quality_dirty:
                return False
            ordered = sorted(
                self._route_quality_history.items(),
                key=lambda entry: self._positive_int(entry[1].get("updatedAt"), 0),
                reverse=True,
            )[:self.ROUTE_QUALITY_LIMIT]
            payload = {
                "version": self.ROUTE_QUALITY_VERSION,
                "entries": {key: dict(value) for key, value in ordered},
            }
            self._route_quality_dirty = False
        try:
            with self._cache_persist_lock:
                result = setter(self.ROUTE_QUALITY_CACHE_KEY, payload)
            if str(result or "").strip().lower() == "failed":
                with self._cache_lock:
                    self._route_quality_dirty = True
                self._diagnostic_event(
                    "route_quality.flush", "WARN",
                    count=len(payload["entries"]), result="failed",
                )
                return False
            self._diagnostic_event("route_quality.flush", count=len(payload["entries"]))
            return True
        except Exception as exc:
            with self._cache_lock:
                self._route_quality_dirty = True
            self._diagnostic_event(
                "route_quality.flush", "WARN", exc=exc,
                count=len(payload["entries"]),
            )
            return False

    def _route_quality_record(self, play_id):
        key = self._route_quality_key(play_id)
        if not key:
            return {}
        self._load_route_quality_history()
        with self._cache_lock:
            return dict(self._route_quality_history.get(key) or {})

    def _record_route_quality(self, play_id, success, startup_ms=0, signals=None,
                              expected_generation=None, expected_backend=None):
        key = self._route_quality_key(play_id)
        if not key:
            return
        self._load_route_quality_history()
        signals = signals if isinstance(signals, dict) else {}
        with self._cache_lock:
            if (
                    expected_generation is not None
                    and expected_generation != self._cache_generation):
                return
            if (
                    expected_backend is not None
                    and expected_backend != self._resource_capability_identity()):
                return
            record = dict(self._route_quality_history.get(key) or {})
            successes = self._positive_int(record.get("successes"), 0)
            failures = self._positive_int(record.get("failures"), 0)
            if successes + failures >= 50:
                successes //= 2
                failures //= 2
            if success:
                successes += 1
            else:
                failures += 1
            record["successes"] = successes
            record["failures"] = failures
            startup = self._positive_int(startup_ms or signals.get("startup_ms"), 0)
            if success and startup:
                timed = self._positive_int(record.get("timedSuccesses"), 0)
                average = self._positive_int(record.get("avgStartupMs"), 0)
                record["avgStartupMs"] = int(round((average * timed + startup) / float(timed + 1)))
                record["timedSuccesses"] = min(50, timed + 1)
            codec = str(signals.get("codec") or "").strip().lower()
            if codec:
                record["codec"] = codec
            height = self._positive_int(signals.get("height"), 0)
            if height:
                record["height"] = height
            if isinstance(signals.get("subtitle"), bool):
                record["subtitle"] = signals.get("subtitle")
            record["updatedAt"] = int(time.time())
            self._route_quality_history[key] = record
            if len(self._route_quality_history) > self.ROUTE_QUALITY_LIMIT * 2:
                oldest = sorted(
                    self._route_quality_history,
                    key=lambda item: self._positive_int(self._route_quality_history[item].get("updatedAt"), 0),
                )[:self.ROUTE_QUALITY_LIMIT]
                for item in oldest:
                    self._route_quality_history.pop(item, None)
        self._schedule_route_quality_save()

    @staticmethod
    def _media_quality_signals(text="", content_type="", sample=b""):
        values = [str(text or ""), str(content_type or "")]
        if isinstance(sample, (bytes, bytearray)) and b"#EXTM3U" in bytes(sample[:4096]).upper():
            values.append(bytes(sample[:4096]).decode("utf-8", errors="ignore"))
        haystack = " ".join(values)
        lower = haystack.lower()
        codec = ""
        if re.search(r"(?:avc1|h[ ._-]?264|x264)", lower):
            codec = "h264"
        elif re.search(r"(?:hev1|hvc1|hevc|h[ ._-]?265|x265)", lower):
            codec = "hevc"
        elif re.search(r"(?:vp09|\bvp9\b)", lower):
            codec = "vp9"
        elif re.search(r"(?:av01|\bav1\b)", lower):
            codec = "av1"
        heights = [int(value) for value in re.findall(r"(?i)RESOLUTION\s*=\s*\d{3,5}x(\d{3,5})", haystack)]
        for marker, height in ((r"(?i)(?:2160p|\b4k\b)", 2160), (r"(?i)1440p", 1440),
                               (r"(?i)1080p", 1080), (r"(?i)720p", 720), (r"(?i)480p", 480)):
            if re.search(marker, haystack):
                heights.append(height)
        subtitle = None
        if re.search(r"(?i)(?:TYPE\s*=\s*SUBTITLES|SUBTITLES\s*=|\.(?:ass|ssa|srt|vtt)\b|中字|字幕|双语|内封|简中|繁中|\bCHS\b|\bCHT\b)", haystack):
            subtitle = True
        return {"codec": codec, "height": max(heights) if heights else 0, "subtitle": subtitle}

    def _route_quality_score(self, play_id, output=None, probe=None, text=""):
        record = self._route_quality_record(play_id)
        probe = probe if isinstance(probe, dict) else {}
        output = output if isinstance(output, dict) else {}
        fresh = self._media_quality_signals(
            "%s %s" % (text, Filter._first_http_url(output.get("url"))),
            probe.get("content_type"),
        )
        codec = str(probe.get("codec") or fresh.get("codec") or record.get("codec") or "").lower()
        height = self._positive_int(probe.get("height") or fresh.get("height") or record.get("height"), 0)
        subtitle = probe.get("subtitle")
        if not isinstance(subtitle, bool):
            subtitle = fresh.get("subtitle")
        if not isinstance(subtitle, bool):
            subtitle = record.get("subtitle") if isinstance(record.get("subtitle"), bool) else None
        startup = self._positive_int(probe.get("startup_ms") or record.get("avgStartupMs"), 0)
        if not startup:
            startup_score = 10
        elif startup <= 800:
            startup_score = 25
        elif startup <= 1500:
            startup_score = 22
        elif startup <= 2500:
            startup_score = 18
        elif startup <= 4000:
            startup_score = 13
        elif startup <= 7000:
            startup_score = 7
        else:
            startup_score = 2
        successes = self._positive_int(record.get("successes"), 0)
        failures = self._positive_int(record.get("failures"), 0)
        attempts = successes + failures
        stability_score = int(round(20.0 * (successes + 1) / (attempts + 2))) if attempts else 10
        codec_score = {"h264": 20, "hevc": 17, "vp9": 14, "av1": 10}.get(codec, 12)
        if height >= 2160:
            resolution_score = 20
        elif height >= 1440:
            resolution_score = 18
        elif height >= 1080:
            resolution_score = 16
        elif height >= 720:
            resolution_score = 12
        elif height >= 480:
            resolution_score = 8
        elif height:
            resolution_score = 5
        else:
            resolution_score = 10
        subtitle_score = 15 if subtitle is True else 6
        scores = {
            "startup": startup_score,
            "stability": stability_score,
            "codec": codec_score,
            "resolution": resolution_score,
            "subtitle": subtitle_score,
            "observed": bool(attempts or startup or codec or height or subtitle is True),
        }
        scores["total"] = sum(scores[key] for key in ("startup", "stability", "codec", "resolution", "subtitle"))
        return scores

    @staticmethod
    def _strip_legacy_route_quality_label(source):
        """Remove score prefixes emitted by older versions from visible labels."""
        value = str(source or "AList资源").strip() or "AList资源"
        value = re.sub(
            r"^质量\d+ 首开\d+ 稳定\d+ 编码\d+ 清晰\d+ 字幕\d+ · ", "", value,
        )
        return value

    @staticmethod
    def _resolve_addresses(host, port, deadline=None):
        remaining = (deadline - time.monotonic()) if deadline is not None else 8
        slot = _DNS_SLOTS
        if remaining <= 0 or not slot.acquire(False):
            return set()
        try:
            future = _DNS_EXECUTOR.submit(socket.getaddrinfo, host, port, 0, socket.SOCK_STREAM)
        except Exception:
            slot.release()
            return set()
        future.add_done_callback(lambda _future, owned_slot=slot: owned_slot.release())
        try:
            result = future.result(timeout=remaining)
        except Exception:
            future.cancel()
            return set()
        addresses = set()
        for entry in result:
            try:
                addresses.add(ipaddress.ip_address(entry[4][0]))
            except Exception:
                continue
        return addresses

    @staticmethod
    def _address_allowed(address):
        if getattr(address, "ipv4_mapped", None) is not None:
            address = address.ipv4_mapped
        return bool(address.is_global)

    def _media_url_allowed(self, value, deadline=None):
        return self._resolved_media_target(value, deadline=deadline) is not None

    def _resolved_media_target(self, value, deadline=None):
        if not Filter._safe_media_url(value, self.atvp_api):
            return None
        try:
            parsed = urlparse(str(value or "").strip())
            port = parsed.port or (443 if parsed.scheme == "https" else 80)
            if port not in (80, 443):
                return None
            target_host = (parsed.hostname or "").lower()
            addresses = self._resolve_addresses(target_host, port, deadline)
        except Exception:
            return None
        if not addresses:
            return None
        if not all(self._address_allowed(address) for address in addresses):
            return None
        return parsed, tuple(sorted(addresses, key=lambda address: (address.version, str(address))))

    def _pinned_media_request_blocking(self, parsed, address, headers, deadline, control=None):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return None
        host = (parsed.hostname or "").encode("idna").decode("ascii")
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        context = None
        connection_type = _PinnedHTTPConnection
        if parsed.scheme == "https":
            context = ssl.create_default_context()
            if not self.verify_tls:
                context.check_hostname = False
                context.verify_mode = ssl.CERT_NONE
            connection_type = _PinnedHTTPSConnection
        kwargs = {"timeout": max(0.05, remaining)}
        if context is not None:
            kwargs["context"] = context
        connection = connection_type(host, address, port=port, **kwargs)
        if isinstance(control, dict):
            control["connection"] = connection
        try:
            request_headers = dict(headers or {})
            default_port = 443 if parsed.scheme == "https" else 80
            host_label = "[%s]" % host if ":" in host else host
            request_headers["Host"] = host_label if port == default_port else "%s:%s" % (host_label, port)
            path = parsed.path or "/"
            if parsed.query:
                path += "?" + parsed.query
            connection.request("GET", path, headers=request_headers)
            response = connection.getresponse()
            status = int(response.status)
            response_headers = {str(key): str(value) for key, value in response.getheaders()}
            if status not in (200, 206):
                return {"status": status, "headers": response_headers, "body": b""}
            body = b""
            while len(body) < self.ROUTE_PROBE_MAX_BYTES:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                if connection.sock is not None:
                    connection.sock.settimeout(max(0.05, remaining))
                reader = getattr(response, "read1", None) or response.read
                block = reader(self.ROUTE_PROBE_MAX_BYTES - len(body))
                if not block:
                    break
                body += block
            return {
                "status": status,
                "headers": response_headers,
                "body": body,
            }
        finally:
            connection.close()
            if isinstance(control, dict):
                control.pop("connection", None)

    def _pinned_media_request(self, parsed, address, headers, deadline):
        remaining = deadline - time.monotonic()
        slot = _MEDIA_PROBE_SLOTS
        if remaining <= 0 or not slot.acquire(False):
            return None
        control = {}
        try:
            future = _MEDIA_PROBE_EXECUTOR.submit(
                self._pinned_media_request_blocking,
                parsed, address, headers, deadline, control,
            )
        except Exception:
            slot.release()
            return None
        future.add_done_callback(lambda _future, owned_slot=slot: owned_slot.release())
        try:
            return future.result(timeout=remaining)
        except Exception:
            connection = control.get("connection")
            if connection is not None:
                try:
                    connection.close()
                except Exception:
                    pass
            future.cancel()
            return None

    @staticmethod
    def _sanitize_route_output(output):
        if not isinstance(output, dict):
            return None
        clean = dict(output)
        raw_headers = clean.get("header")
        if raw_headers in (None, ""):
            raw_headers = {}
        if isinstance(raw_headers, str):
            try:
                raw_headers = json.loads(raw_headers)
            except Exception:
                return None
        if not isinstance(raw_headers, dict):
            return None
        canonical_names = {
            "user-agent": "User-Agent",
            "referer": "Referer",
            "origin": "Origin",
            "cookie": "Cookie",
            "accept": "Accept",
            "range": "Range",
            "content-type": "Content-Type",
        }
        headers = {}
        total_bytes = 0
        for raw_key, raw_value in raw_headers.items():
            key = str(raw_key).strip().lower()
            if key not in Filter.SAFE_ROUTE_HEADERS or raw_value is None:
                continue
            value = str(raw_value)
            if not key or "\r" in key or "\n" in key or "\r" in value or "\n" in value:
                return None
            value_bytes = len(value.encode("utf-8", "replace"))
            value_limit = (
                Spider.ROUTE_COOKIE_MAX_BYTES
                if key == "cookie"
                else Spider.ROUTE_HEADER_VALUE_MAX_BYTES
            )
            if value_bytes > value_limit:
                return None
            canonical = canonical_names[key]
            if canonical in headers:
                if headers[canonical] != value:
                    return None
                continue
            total_bytes += len(canonical.encode("ascii")) + value_bytes + 2
            if total_bytes > Spider.ROUTE_HEADERS_TOTAL_MAX_BYTES:
                return None
            headers[canonical] = value
        clean["header"] = headers
        return clean

    @staticmethod
    def _media_origin(value):
        try:
            parsed = urlparse(str(value or "").strip())
            scheme = str(parsed.scheme or "").lower()
            host = str(parsed.hostname or "").rstrip(".").lower()
            if scheme not in ("http", "https") or not host:
                return None
            port = parsed.port or (443 if scheme == "https" else 80)
            return scheme, host, port
        except Exception:
            return None

    def _safe_atvp_play_output(self, output):
        if not isinstance(output, dict):
            return False
        if self._int_value(output.get("parse"), 0) != 0:
            return False
        media_url = Filter._first_http_url(output.get("url"))
        return bool(media_url and Filter._safe_media_url(media_url, self.atvp_api))

    def _probe_media_output(self, output, deadline=None):
        started_at = time.monotonic()
        clean_output = self._sanitize_route_output(output)
        if not isinstance(clean_output, dict):
            return None
        media_url = Filter._first_http_url(clean_output.get("url"))
        if not media_url:
            return None
        playback_headers = dict(clean_output.get("header") or {})
        headers = dict(playback_headers)
        headers.setdefault("User-Agent", self.user_agent)
        headers.setdefault("Accept", "*/*")
        headers["Range"] = "bytes=0-%d" % (self.ROUTE_PROBE_MAX_BYTES - 1)
        current = media_url
        crossed_origin = False

        def redirected_output():
            if not crossed_origin:
                return None
            playback_output = dict(clean_output)
            playback_output["url"] = current
            playback_output["header"] = playback_headers
            playback_output = self._sanitize_route_output(playback_output)
            if not isinstance(playback_output, dict):
                return None
            return {
                "checked_at": time.time(),
                "reachable": None,
                "fingerprint": "",
                "output": playback_output,
                "cross_origin": True,
            }

        absolute_deadline = deadline if deadline is not None else time.monotonic() + 8
        for redirect_count in range(5):
            resolved = self._resolved_media_target(current, deadline=absolute_deadline)
            if resolved is None:
                return redirected_output()
            parsed, addresses = resolved
            if absolute_deadline - time.monotonic() <= 0:
                return redirected_output()
            response = None
            for index, address in enumerate(addresses):
                remaining = absolute_deadline - time.monotonic()
                if remaining <= 0:
                    return redirected_output()
                attempts_left = len(addresses) - index
                attempt_deadline = min(
                    absolute_deadline,
                    time.monotonic() + max(0.2, remaining / max(1, attempts_left)),
                )
                response = self._pinned_media_request(
                    parsed, address, headers, attempt_deadline,
                )
                if response is not None:
                    break
            if response is None:
                return redirected_output()
            status = int(response.get("status") or 0)
            response_headers = response.get("headers") or {}
            if status in (301, 302, 303, 307, 308):
                if redirect_count >= 4:
                    return redirected_output()
                location = str(response_headers.get("Location") or response_headers.get("location") or "").strip()
                if not location:
                    return redirected_output()
                next_url = urljoin(current, location)
                current_origin = self._media_origin(current)
                next_origin = self._media_origin(next_url)
                if current_origin is None or next_origin is None:
                    return redirected_output()
                if current_origin != next_origin:
                    crossed_origin = True
                    for sensitive_header in ("Cookie", "Origin", "Referer"):
                        headers.pop(sensitive_header, None)
                        playback_headers.pop(sensitive_header, None)
                current = next_url
                continue
            if status not in (200, 206):
                return redirected_output()
            chunk = bytes(response.get("body") or b"")[:self.ROUTE_PROBE_MAX_BYTES]
            if not chunk:
                return redirected_output()
            content_type = str(response_headers.get("Content-Type") or response_headers.get("content-type") or "").lower()
            if "text/html" in content_type and b"<html" in chunk[:512].lower():
                return redirected_output()
            content_range = str(response_headers.get("Content-Range") or response_headers.get("content-range") or "")
            total_match = re.search(r"/(\d+)\s*$", content_range)
            total = int(total_match.group(1)) if total_match else 0
            if not total and status == 200:
                total = self._positive_int(
                    response_headers.get("Content-Length") or response_headers.get("content-length"), 0,
                )
            signals = self._media_quality_signals(current, content_type, chunk)
            playback_output = dict(clean_output)
            playback_output["url"] = current
            playback_output["header"] = playback_headers
            playback_output = self._sanitize_route_output(playback_output)
            if not isinstance(playback_output, dict):
                return None
            return {
                "checked_at": time.time(),
                "reachable": True,
                "fingerprint": "range-v1:%s:%s" % (
                    total or "unknown", hashlib.sha256(chunk).hexdigest(),
                ),
                "content_length": total,
                "range_status": status,
                "startup_ms": max(1, int(round((time.monotonic() - started_at) * 1000))),
                "content_type": content_type,
                "codec": signals.get("codec") or "",
                "height": signals.get("height") or 0,
                "subtitle": signals.get("subtitle"),
                "output": playback_output,
            }
        return None

    def _cache_route_probe(self, play_id, probe, resource_id="", resource_mode="vod",
                           expected_generation=None, expected_backend=None):
        key = self._route_probe_key(play_id, resource_id, resource_mode)
        if not key or not isinstance(probe, dict):
            return
        cached_probe = dict(probe)
        if cached_probe.get("reachable") is True or "output" in cached_probe:
            cached_output = self._sanitize_route_output(cached_probe.get("output"))
            if not isinstance(cached_output, dict) or not Filter._first_http_url(cached_output.get("url")):
                return
            cached_probe["output"] = cached_output
        else:
            cached_probe.pop("output", None)
        with self._history_context_lock:
            with self._cache_lock:
                if (
                        expected_generation is not None
                        and expected_generation != self._cache_generation):
                    return
                if (
                        expected_backend is not None
                        and expected_backend != self._resource_capability_identity()):
                    return
                self._route_probe_cache[key] = cached_probe
                self._prune_route_probe_cache_locked()

    def _remember_successful_follow_route(self, parsed, candidate, quality_id, probe,
                                          expected_generation=None, expected_backend=None):
        if not isinstance(parsed, dict) or not isinstance(candidate, dict):
            return
        season = self._positive_int(parsed.get("season"), 0)
        episode = self._positive_int(parsed.get("episode"), 0)
        if season <= 0 or episode <= 0:
            return
        play_id = str(candidate.get("_route_refresh_target") or quality_id or "").strip()
        decoded_play_id = self._unquote_limited(play_id)
        if (
                len(play_id) > self.FOLLOWPLAY_ROUTE_FIELD_MAX_LENGTH
                or not re.match(r"^(?:\d+@[^\s?#]+|\d+-\d+|\d+)$", play_id)
                or self._contains_url_reference(decoded_play_id.split("@", 1)[-1])
        ):
            play_id = ""
        resource_id = str(candidate.get("resourceId") or parsed.get("resourceId") or "").strip()
        resource_mode = str(parsed.get("resourceMode") or "vod").strip().lower() or "vod"
        resource_provider = self._resource_provider_key(
            candidate.get("resourceProvider"), parsed.get("resourceProvider"),
        )
        if resource_mode not in self.RESOURCE_SEARCH_MODES:
            resource_mode = ""
        if (
                resource_id.startswith("filter:")
                or resource_id and not self._resource_id_persistable(resource_id, resource_mode)
        ):
            resource_id = ""
        if not play_id and not resource_id:
            return
        tmdb_id = self._positive_int(parsed.get("tmdbId"), 0)
        source_id = str(parsed.get("sourceId") or "").strip()
        route_name = str(candidate.get("name") or parsed.get("name") or "").strip()[:256]
        decoded_route_name = self._unquote_limited(route_name)
        if self._contains_url_reference(decoded_route_name):
            route_name = ""
        route_probe = probe if isinstance(probe, dict) else {}
        route = {
            "version": 1,
            "backend": expected_backend or self._resource_capability_identity(),
            "resourceId": resource_id,
            "resourceMode": resource_mode,
            "playId": play_id,
            "season": season,
            "episode": episode,
            "name": route_name,
            "quality": {
                "height": self._positive_int(route_probe.get("height"), 0),
                "codec": str(route_probe.get("codec") or "")[:16],
                "subtitle": route_probe.get("subtitle") if isinstance(route_probe.get("subtitle"), bool) else None,
                "startupMs": self._positive_int(route_probe.get("startup_ms"), 0),
            },
            "updatedAt": int(time.time()),
        }
        if resource_provider:
            route["resourceProvider"] = resource_provider
        with self._history_context_lock:
            with self._cache_lock:
                if (
                        expected_generation is not None
                        and expected_generation != self._cache_generation):
                    return
                if (
                        expected_backend is not None
                        and expected_backend != self._resource_capability_identity()):
                    return
            with self._follow_enrich_lock:
                items = self._follow_memory.get("items") if isinstance(self._follow_memory, dict) else {}
                if not isinstance(items, dict):
                    return
                item_key = str(tmdb_id) if tmdb_id and str(tmdb_id) in items else ""
                if not item_key and source_id:
                    item_key = next((
                        key for key, value in items.items()
                        if isinstance(value, dict) and str(value.get("source_id") or "") == source_id
                    ), "")
                if not item_key:
                    return
                state_items = dict(items)
                item = dict(state_items.get(item_key) or {})
                item["last_play_route"] = route
                if resource_id:
                    item["alist_vod_id"] = resource_id
                if resource_provider:
                    item["alist_resource_provider"] = resource_provider
                else:
                    item.pop("alist_resource_provider", None)
                state_items[item_key] = item
                try:
                    self._save_follow_state(state_items)
                except Exception:
                    pass

    def _probe_route_candidate(self, target, expected_generation=None, expected_backend=None):
        output = dict(self._atvp_play(
            target,
            timeout_seconds=max(6, min(15, self.timeout)),
            deadline=time.monotonic() + min(30, self.FOLLOWPLAY_PLAY_BUDGET),
            expected_generation=expected_generation,
            expected_backend=expected_backend,
        ) or {})
        result = self._probe_media_output(
            output, deadline=time.monotonic() + min(15, self.FOLLOWPLAY_PLAY_BUDGET),
        )
        if result is None:
            raise RuntimeError("媒体Range验证失败")
        return result

    def _schedule_route_preheat(self, records, item):
        if not self.route_preheat or not self.atvp_api or not self.atvp_token or self._atvp_session is None:
            return
        resume = re.match(r"^S0*(\d{1,2})E0*(\d{1,3})$", str(item.get("history_episode") or ""), re.I)
        target_key = (int(resume.group(1)), int(resume.group(2))) if resume else None
        if target_key is None:
            target_key = next((
                record.get("episode_key") for record in records
                if isinstance(record.get("episode_key"), tuple)
                and len(record["episode_key"]) == 2
                and all(isinstance(value, int) and value > 0 for value in record["episode_key"])
            ), None)
        if target_key is None:
            return
        targets = []
        for record in records:
            if record.get("episode_key") != target_key:
                continue
            payload = record.get("payload") or {}
            target = str(payload.get("url") or "").strip()
            resource_id = str(record.get("resource_id") or payload.get("resourceId") or "").strip()
            resource_mode = str(payload.get("resourceMode") or "vod").strip().lower() or "vod"
            identity = (target, resource_id, resource_mode)
            if target and identity not in targets:
                targets.append(identity)
            if len(targets) >= self.FOLLOW_ROUTE_LIMIT:
                break
        for target, resource_id, resource_mode in targets:
            with self._history_context_lock:
                with self._cache_lock:
                    generation = self._cache_generation
                    backend = self._resource_capability_identity()
                    probe_key = self._route_probe_key(
                        target, resource_id, resource_mode, backend=backend,
                    )
                    self._prune_route_probe_cache_locked()
                    if (
                            not probe_key
                            or probe_key in self._route_probe_cache
                            or probe_key in self._route_probe_jobs):
                        continue
                    job_owner = object()
                    self._route_probe_jobs[probe_key] = job_owner

            def worker(route=target, route_resource_id=resource_id, route_mode=resource_mode,
                       route_key=probe_key, expected_generation=generation,
                       expected_backend=backend, expected_owner=job_owner):
                with self._history_context_lock:
                    with self._cache_lock:
                        active = (
                            self._route_probe_jobs.get(route_key) is expected_owner
                            and expected_generation == self._cache_generation
                            and expected_backend == self._resource_capability_identity()
                        )
                if not active:
                    return
                try:
                    result = self._probe_route_candidate(
                        route,
                        expected_generation=expected_generation,
                        expected_backend=expected_backend,
                    )
                except Exception as exc:
                    result = {
                        "checked_at": time.time(),
                        "reachable": False,
                        "fingerprint": "",
                        "error": self._short_error(exc),
                    }
                with self._cache_lock:
                    current = self._route_probe_jobs.get(route_key)
                    active = (
                        current is expected_owner
                        and expected_generation == self._cache_generation
                        and expected_backend == self._resource_capability_identity()
                    )
                    if current is expected_owner:
                        self._route_probe_jobs.pop(route_key, None)
                if active:
                    self._record_route_quality(
                        route, result.get("reachable") is True,
                        startup_ms=result.get("startup_ms"), signals=result,
                        expected_generation=expected_generation,
                        expected_backend=expected_backend,
                    )
                    self._cache_route_probe(
                        route, result, route_resource_id, route_mode,
                        expected_generation=expected_generation,
                        expected_backend=expected_backend,
                    )

            try:
                self._tasks.start_thread(worker, name="route-probe")
            except Exception:
                with self._cache_lock:
                    if self._route_probe_jobs.get(probe_key) is job_owner:
                        self._route_probe_jobs.pop(probe_key, None)

    def _prepare_player_candidates(self, candidates):
        prepared = []
        fingerprints = set()
        for order, candidate in enumerate(candidates):
            row = dict(candidate)
            probe = self._route_probe_snapshot(
                row.get("url"), row.get("resourceId"), row.get("resourceMode") or "vod",
            )
            fingerprint = str((probe or {}).get("fingerprint") or "")
            if fingerprint and fingerprint in fingerprints:
                continue
            if fingerprint:
                fingerprints.add(fingerprint)
            row["_route_probe"] = probe
            if probe and probe.get("reachable") is True:
                rank = 0
            elif probe is None:
                rank = 1
            else:
                rank = 2
            quality = self._route_quality_score(
                row.get("_route_quality_id") or row.get("_route_refresh_target") or row.get("url"),
                output=(probe or {}).get("output"), probe=probe,
                text=row.get("name"),
            )
            row["_route_quality"] = quality
            prepared.append((
                rank,
                -self._positive_int(quality.get("resolution"), 0),
                -self._positive_int(quality.get("total"), 0),
                -self._positive_int(quality.get("startup"), 0),
                -self._positive_int(quality.get("stability"), 0),
                order,
                row,
            ))
        prepared.sort(key=lambda value: value[:-1])
        return [value[-1] for value in prepared]

    @staticmethod
    def _episode_from_text_info(text, index, default_season=1):
        label = str(text or "")
        found = re.search(r"(?i)S\s*0*(\d{1,2})\s*E(?:P)?\s*0*(\d{1,3})", label)
        if found:
            return int(found.group(1)), int(found.group(2)), True
        found = re.search(r"第\s*(\d{1,2})\s*季.*?第\s*(\d{1,3})\s*[集话]", label)
        if found:
            return int(found.group(1)), int(found.group(2)), True
        found = re.search(r"(?i)\bSeason\s*0*(\d{1,2}).*?\b(?:Episode|EP?|E)\s*0*(\d{1,3})\b", label)
        if found:
            return int(found.group(1)), int(found.group(2)), True
        found = re.search(r"(?i)\bEP?\s*0*(\d{1,3})\b", label)
        if found:
            return default_season or 1, int(found.group(1)), True
        found = re.search(r"(?i)(?:第\s*)?(\d{1,3})\s*(?:集|话|ep)\b", label)
        if found:
            return default_season or 1, int(found.group(1)), True
        if re.match(r"^\s*\d+(?:\.\d+)?\s*(?:K|M|G|T)i?B\b", label, re.I):
            return default_season or 1, index, False
        found = re.match(r"^\s*0*(\d{1,3})\s*$", label)
        if found:
            return default_season or 1, int(found.group(1)), True
        # Cloud-drive labels commonly append size/resolution text to a leading
        # episode number, e.g. ``01(413.43 MB)`` or ``01.4K.mkv``.
        found = re.match(r"^\s*0*(\d{1,3})(?=\s*[.\-_\[(])", label)
        if found:
            episode = int(found.group(1))
            suffix = label[found.end():]
            common_resolutions = {144, 240, 360, 480, 540, 576, 720}
            bracketed_size = bool(re.match(r"^\s*\(", suffix))
            immediate_size_unit = re.match(r"^\s*[.\-_\[(]*\s*(?:K|M|G|T)?i?B\b", suffix, re.I)
            if (episode not in common_resolutions or bracketed_size) and not immediate_size_unit:
                return default_season or 1, episode, True
        return default_season or 1, index, False

    def _resource_group_season(self, group_url):
        seasons = set()
        parts, _limited = _split_bounded_shared(
            group_url, "#", self.RESOURCE_GROUP_EPISODE_LIMIT,
        )
        for part in parts:
            _name, separator, play_id = part.rpartition("$")
            if not separator or not play_id:
                continue
            payload = self._parse_followplay(play_id)
            season = self._positive_int((payload or {}).get("season"), 0)
            if season:
                seasons.add(season)
        return next(iter(seasons)) if len(seasons) == 1 else 0

    @staticmethod
    def _season_display_name(season):
        names = {
            1: "第一季", 2: "第二季", 3: "第三季", 4: "第四季", 5: "第五季",
            6: "第六季", 7: "第七季", 8: "第八季", 9: "第九季", 10: "第十季",
        }
        value = Spider._positive_int(season, 0)
        return names.get(value, ("第%d季" % value) if value else "")

    @classmethod
    def _resource_source_with_season(cls, source, season):
        base = str(source or "AList资源").strip() or "AList资源"
        if Filter._season(base):
            return base
        label = cls._season_display_name(season)
        return (label + " · " + base) if label else base

    @staticmethod
    def _unique_resource_source(base_source, resource_id, group_index, used):
        base = str(base_source or "AList资源").strip() or "AList资源"
        if base not in used:
            return base
        raw = str(resource_id or "").strip()
        parts = [part for part in raw.split("$") if part]
        suffix = parts[-2] if len(parts) >= 2 else (parts[-1] if parts else "")
        suffix = re.sub(r"[^A-Za-z0-9_-]", "", suffix)[:16]
        suffix = suffix or str(group_index + 1)
        candidate = "%s (%s)" % (base, suffix)
        serial = 2
        while candidate in used:
            candidate = "%s (%s-%d)" % (base, suffix, serial)
            serial += 1
        return candidate

    @staticmethod
    def _episode_from_text(text, index, default_season=1):
        season, episode, _explicit = Spider._episode_from_text_info(text, index, default_season)
        return season, episode

    def _tracking_season(self, item):
        for key in ("trackingSeason", "season"):
            value = self._int_value(item.get(key))
            if value > 0:
                return value
        match = re.match(r"^S(\d{2})E\d{2,3}$", str(item.get("latest_episode") or ""))
        return int(match.group(1)) if match else 1

    @staticmethod
    def _build_followplay(
            url, item, resource_id, season, episode, name, episode_explicit=True,
            resource_mode="vod", resource_provider=""):
        def clipped(value, limit):
            return str(value or "").strip()[:limit]

        primary_url = str(url or "").strip()
        if not primary_url or len(primary_url) > Spider.FOLLOWPLAY_MAX_URL_LENGTH:
            return ""
        title_aliases = [
            clipped(value, 128)
            for value in Spider._follow_title_alias_values(item, include_primary=False)[:8]
            if clipped(value, 128)
        ]
        resume = re.match(r"^S0*(\d{1,2})E0*(\d{1,3})$", str(item.get("history_episode") or ""), re.I)
        resource_mode = clipped(resource_mode or "vod", 16)
        resource_provider = Spider._resource_provider_key(resource_provider)
        values = {
            "url": primary_url,
            "mediaType": clipped(item.get("media_type") or "movie", 16),
            "tmdbId": clipped(item.get("tmdb_id"), 32),
            "sourceId": clipped(item.get("source_id"), 512),
            "resourceId": clipped(
                resource_id, Spider._resource_id_raw_limit(resource_id, resource_mode),
            ),
            "resourceMode": resource_mode,
            "season": season,
            "episode": episode,
            "episodeExplicit": 1 if episode_explicit else 0,
            "title": clipped(item.get("title"), 256),
            "originalTitle": clipped(item.get("original_title"), 256),
            "titleAliases": json.dumps(title_aliases, ensure_ascii=False, separators=(",", ":")),
            "year": str(item.get("year") or item.get("release_date") or item.get("first_air_date") or "")[:4],
            "name": clipped(name, 256),
            "resumePosition": Spider._int_value(item.get("history_position"), 0),
            "resumeDuration": Spider._int_value(item.get("history_duration"), 0),
            "resumeSeason": int(resume.group(1)) if resume else 0,
            "resumeEpisode": int(resume.group(2)) if resume else 0,
            # Independent route groups are selected on the detail page; new IDs
            # never embed another route or a signed media response.
            "fallbacks": "[]",
        }
        if resource_provider:
            values["resourceProvider"] = resource_provider

        def encode(payload_values):
            payload = urlencode(payload_values).encode("utf-8")
            if len(payload) > Spider.FOLLOWPLAY_MAX_DECODED_LENGTH:
                return ""
            return FOLLOWPLAY_PREFIX + base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")

        result = encode(values)
        if result and len(result) <= Spider.FOLLOWPLAY_MAX_ID_LENGTH:
            return result
        values.update({"titleAliases": "[]", "originalTitle": "", "name": ""})
        result = encode(values)
        return result if result and len(result) <= Spider.FOLLOWPLAY_MAX_ID_LENGTH else ""

    def _parse_followplay(self, value):
        encoded = str(value or "")
        if len(encoded) > self.FOLLOWPLAY_MAX_ID_LENGTH:
            return None
        prefix = next((item for item in FOLLOWPLAY_PREFIXES if encoded.startswith(item)), "")
        if not prefix:
            return None
        try:
            raw = encoded[len(prefix):].replace("-", "+").replace("_", "/")
            raw += "=" * ((4 - len(raw) % 4) % 4)
            decoded = base64.b64decode(raw, validate=True)
            if len(decoded) > self.FOLLOWPLAY_MAX_DECODED_LENGTH:
                return None
            parsed = self._parse_query(decoded.decode("utf-8"))
        except Exception:
            return None
        if not parsed.get("url") or len(str(parsed.get("url") or "")) > self.FOLLOWPLAY_MAX_URL_LENGTH:
            return None
        resource_mode = str(parsed.get("resourceMode") or "vod").strip().lower() or "vod"
        if resource_mode not in self.RESOURCE_SEARCH_MODES:
            return None
        resource_id = str(parsed.get("resourceId") or "").strip()
        if resource_id and not self._resource_id_valid(resource_id, resource_mode):
            return None
        parsed["resourceId"] = resource_id
        parsed["resourceMode"] = resource_mode
        parsed["resourceProvider"] = self._resource_provider_key(parsed.get("resourceProvider"))
        for key in ("season", "episode", "tmdbId", "resumeSeason", "resumeEpisode"):
            parsed[key] = self._int_value(parsed.get(key))
        for key in ("resumePosition", "resumeDuration"):
            parsed[key] = self._int_value(parsed.get(key))
        raw_fallbacks = parsed.get("fallbacks")
        try:
            fallbacks = json.loads(raw_fallbacks) if raw_fallbacks else []
        except Exception:
            fallbacks = []
        if not isinstance(fallbacks, list):
            fallbacks = []
        parsed["episodeExplicit"] = str(parsed.get("episodeExplicit") or "1") != "0"
        normalized = []
        current = str(parsed.get("url") or "")
        for candidate in fallbacks:
            if not isinstance(candidate, dict):
                continue
            target = str(candidate.get("url") or "").strip()
            if not target or target == current or len(target) > self.FOLLOWPLAY_MAX_URL_LENGTH:
                continue
            if any(str(row.get("url") or "") == target for row in normalized):
                continue
            normalized.append(candidate)
            if len(normalized) >= self.FOLLOWPLAY_MAX_FALLBACKS:
                break
        parsed["fallbacks"] = normalized
        return parsed

    def _inject_resume(self, output, parsed):
        if parsed.get("mediaType") != "movie" and parsed.get("episodeExplicit") is False:
            return
        marker = "%s|%s|%s|%s" % (
            parsed.get("sourceId") or parsed.get("tmdbId") or "",
            parsed.get("resourceId") or "",
            parsed.get("season") or 0,
            parsed.get("episode") or 0,
        )
        if marker in self._resume_imported:
            return
        item = {
            "tmdb_id": parsed.get("tmdbId"),
            "source_id": parsed.get("sourceId"),
            "title": parsed.get("title"),
            "original_title": parsed.get("originalTitle"),
            "title_aliases": Filter._payload_title_aliases(parsed),
            "alist_vod_id": parsed.get("resourceId"),
        }
        histories = self._atvp_history_snapshot()
        history = self._atvp_history_for_item(item, histories)
        position = 0
        duration = 0
        if history:
            if not self._history_can_resume(history):
                return
            if parsed.get("mediaType") != "movie" and not self._history_episode_matches(
                    history, parsed.get("season"), parsed.get("episode")):
                return
            position = self._int_value(history.get("position"))
            duration = self._int_value(history.get("duration"))
        else:
            if parsed.get("mediaType") != "movie" and (
                    self._int_value(parsed.get("resumeSeason")) != self._int_value(parsed.get("season"))
                    or self._int_value(parsed.get("resumeEpisode")) != self._int_value(parsed.get("episode"))):
                return
            position = self._int_value(parsed.get("resumePosition"))
            duration = self._int_value(parsed.get("resumeDuration"))
            if not self._history_can_resume({"position": position, "duration": duration}):
                return
        if position > 0:
            output["position"] = position
            self._remember_resume_import(marker)

    def _load_resume_markers(self):
        value = None
        getter = getattr(self, "getCache", None)
        if callable(getter):
            try:
                value = getter(self.RESUME_IMPORT_CACHE_KEY)
            except Exception:
                value = None
        now = int(time.time())
        markers = value.get("markers") if isinstance(value, dict) else {}
        if not isinstance(markers, dict):
            markers = {}
        self._resume_imported = {
            str(marker): self._int_value(created)
            for marker, created in markers.items()
            if str(marker) and now - self._int_value(created) <= 604800
        }

    def _remember_resume_import(self, marker):
        now = int(time.time())
        self._resume_imported[marker] = now
        markers = dict(sorted(self._resume_imported.items(), key=lambda entry: entry[1], reverse=True)[:128])
        self._resume_imported = markers
        setter = getattr(self, "setCache", None)
        if callable(setter):
            try:
                setter(self.RESUME_IMPORT_CACHE_KEY, {"version": 1, "markers": markers})
            except Exception:
                pass

    def _history_episode_matches(self, history, season, episode):
        season = Spider._int_value(season)
        episode = Spider._int_value(episode)
        payload = self._history_followplay_payload(history)
        if payload:
            return (
                Spider._int_value(payload.get("season")) == season
                and Spider._int_value(payload.get("episode")) == episode
            )
        text = " ".join(str(history.get(key) or "") for key in ("vodFlag", "vodRemarks", "episodeUrl", "name"))
        parsed = Spider._episode_from_text(text, 0, season or 1)
        if parsed[1] > 0:
            return parsed == (season or parsed[0], episode)
        raw_episode = Spider._int_value(history.get("episode"), -1)
        return raw_episode in (episode - 1, episode)

    @staticmethod
    def _parse_query(value):
        from urllib.parse import parse_qs
        return {key: values[-1] for key, values in parse_qs(value, keep_blank_values=True).items()}

    @staticmethod
    def _int_value(value, fallback=0):
        try:
            return int(value)
        except Exception:
            try:
                return int(float(value))
            except Exception:
                return fallback

    @staticmethod
    def _unquote_limited(value, rounds=None):
        current = str(value or "")
        if rounds is None:
            rounds = min(512, max(32, len(current) + 1))
        for _index in range(max(0, int(rounds))):
            decoded = unquote(current)
            if decoded == current:
                break
            current = decoded
        return current

    @classmethod
    def _contains_url_reference(cls, value):
        text = str(value or "").strip()
        if not text:
            return False
        scheme_pattern = re.compile(
            r"(?i)(?:[a-z][a-z0-9+.-]*:)?//|"
            r"(?<![a-z0-9+.-])(?:https?|ftp|ftps|file|magnet|data|javascript|"
            r"vbscript|rtsp|rtmp|mms|ed2k|thunder|flashget|qqdl|ws|wss|blob|"
            r"content|intent):"
        )
        for _index in range(min(512, max(32, len(text) + 1))):
            if scheme_pattern.search(text):
                return True
            decoded = unquote(text)
            if decoded == text:
                return False
            text = decoded
        return True

    def _tmdb_detail(self, raw_id):
        match = re.match(r"^tmdb:(movie|tv):(\d+)$", str(raw_id or ""))
        if not match:
            return {"list": []}
        media_type, tmdb_id = match.groups()
        try:
            data = self._tmdb_api("/%s/%s" % (media_type, tmdb_id), {"append_to_response": "credits"}, self.detail_cache_ttl)
            title = str(data.get("title") or data.get("name") or "")
            original = str(data.get("original_title") or data.get("original_name") or "")
            names = title if not original or original == title else title + " / " + original
            content = str(data.get("overview") or "").strip()
            remark_parts = [self._score_text(data.get("vote_average"))]
            if media_type == "tv":
                latest = self._aired_episode(data.get("last_episode_to_air"))
                upcoming = data.get("next_episode_to_air") if isinstance(data.get("next_episode_to_air"), dict) else {}
                if latest:
                    remark_parts.append("已播 " + self._episode_key(latest))
                if upcoming.get("air_date"):
                    remark_parts.append("下集 " + str(upcoming.get("air_date")))
                episode_lines = self._tmdb_recent_episode_lines(tmdb_id, latest)
                if episode_lines:
                    content = (content + "\n\n最近分集：\n" + "\n".join(episode_lines)).strip()
            credits = data.get("credits") or {}
            cast = [str(item.get("name")) for item in credits.get("cast") or [] if item.get("name")][:12]
            directors = [str(item.get("name")) for item in credits.get("crew") or [] if item.get("job") in ("Director", "Series Director") and item.get("name")][:6]
            country_values = []
            for item in data.get("production_countries") or data.get("origin_country") or []:
                value = item.get("name") if isinstance(item, dict) else item
                if value:
                    country_values.append(str(value))
            vod = {
                "vod_id": raw_id,
                "vod_name": names,
                "vod_pic": self._tmdb_image(data.get("poster_path") or data.get("backdrop_path")),
                "type_name": ", ".join(str(item.get("name")) for item in data.get("genres") or [] if item.get("name")),
                "vod_year": str(data.get("release_date") or data.get("first_air_date") or "")[:4],
                "vod_area": ", ".join(country_values),
                "vod_remarks": " · ".join(value for value in remark_parts if value),
                "vod_actor": ", ".join(cast),
                "vod_director": ", ".join(directors),
                "vod_content": content,
                "vod_play_from": "",
                "vod_play_url": "",
                "_season_count": self._positive_int(data.get("number_of_seasons"), 0),
            }
            return {"list": [vod]}
        except Exception as exc:
            return {"list": [self._error_card("TMDB详情载入失败", exc, raw_id)]}

    def _tmdb_recent_episode_lines(self, tmdb_id, latest):
        season_number = self._positive_int(latest.get("season_number") if isinstance(latest, dict) else 0, 0)
        if not season_number:
            return []
        try:
            data = self._tmdb_api("/tv/%s/season/%s" % (tmdb_id, season_number), {}, self.detail_cache_ttl)
        except Exception:
            return []
        today = time.strftime("%Y-%m-%d")
        episodes = [item for item in data.get("episodes") or [] if str(item.get("air_date") or "") and str(item.get("air_date")) <= today]
        result = []
        for item in episodes[-5:]:
            label = self._episode_key(item)
            date = str(item.get("air_date") or "")
            name = str(item.get("name") or "")
            result.append("%s %s %s" % (label, date, name))
        return result

    def _tmdb_api(self, path, params=None, ttl=None, allow_stale=True):
        return self._tmdb_client.api(path, params, ttl, allow_stale)

    def _request_tmdb(self, path, query):
        response = self._tmdb_session.get(
            self.tmdb_api_base + path,
            params=query,
            timeout=self.timeout,
            verify=self.verify_tls,
        )
        data = self._json_response(response)
        if response.status_code in (401, 403):
            raise RuntimeError("TMDB API 凭据无效或无权访问")
        if response.status_code == 429:
            raise RuntimeError("TMDB API 请求过于频繁，请稍后刷新")
        if response.status_code != 200:
            raise RuntimeError(str(data.get("status_message") or "TMDB HTTP %s" % response.status_code))
        return data

    def _require_tmdb_credentials(self):
        if not self.tmdb_access_token and not self.tmdb_api_key:
            raise RuntimeError("请在插件 Extend 配置 tmdb_access_token 或 tmdb_api_key")

    def _tmdb_image(self, path):
        return self._tmdb_client.image(path)

    @staticmethod
    def _aired_episode(value):
        if not isinstance(value, dict):
            return {}
        air_date = str(value.get("air_date") or "")
        if air_date and air_date <= time.strftime("%Y-%m-%d"):
            return value
        return {}

    @staticmethod
    def _episode_key(value):
        if not isinstance(value, dict):
            return ""
        try:
            season = int(value.get("season_number") or 0)
            episode = int(value.get("episode_number") or 0)
        except Exception:
            return ""
        return "S%02dE%02d" % (season, episode) if episode > 0 else ""

    @staticmethod
    def _episode_rank(value):
        match = re.match(r"^S(\d+)E(\d+)$", str(value or ""))
        return int(match.group(1)) * 10000 + int(match.group(2)) if match else 0

    @staticmethod
    def _score_text(value):
        try:
            score = float(value or 0)
        except Exception:
            score = 0
        return ("TMDB %.1f" % score) if score > 0 else ""

    def _category_search_subjects(self, kind, page, tag, ext):
        limit = 50
        params = {"type": kind, "tag": tag or "热门", "page_limit": limit, "page_start": (page - 1) * limit}
        data = self._get_json(self.MOVIE + "/j/search_subjects", params=params, ttl=self.list_cache_ttl)
        items = []
        for raw in data.get("subjects") or []:
            card = self._subject_card(raw, ext)
            if kind == "tv":
                self._apply_douban_follow_action(card, ext)
            items.append(card)
        pagecount = page + 1 if len(items) >= limit else page
        return self._page_result(items, page, pagecount, pagecount * limit, limit)

    def _category_media(self, media, page, ext):
        limit = 20
        sort = self._value(ext, "sort", "U")
        if sort not in {item[1] for item in self.ANIME_SORTS}:
            sort = "U"
        area = self._value(ext, "area", "")
        year = self._value(ext, "year", "")
        genre = self._value(ext, "type" if media == "movie" else "genre", "")
        platform = self._value(ext, "platform", "")
        tag = self._value(ext, "tag", "")
        if media == "movie":
            endpoint = "movie"
            selected = {"类型": genre, "地区": area}
            expected_type = "movie"
            tags = [genre, area, year, tag]
        else:
            endpoint = "tv"
            form = "电视剧" if media == "tv" else "综艺"
            selected = {"类型": genre, "形式": form, "地区": area}
            expected_type = "tv"
            tags = [form, genre, area, year, platform, tag]
        params = {
            "refresh": 0,
            "start": (page - 1) * limit,
            "count": limit,
            "selected_categories": json.dumps(selected, ensure_ascii=False, separators=(",", ":")),
            "uncollect": "false",
            "sort": sort,
            "tags": ",".join([item for item in tags if item]),
        }
        data = self._get_json(self.API + "/%s/recommend" % endpoint, params=params, ttl=self.list_cache_ttl)
        items = []
        for raw in data.get("items") or []:
            raw_type = str(raw.get("type") or "")
            if raw_type and raw_type != expected_type:
                continue
            card = self._collection_card(raw, ext)
            if media != "movie":
                self._apply_douban_follow_action(card, ext)
            items.append(card)
        total = self._positive_int(data.get("total"), 0)
        pagecount = int(math.ceil(float(total) / limit)) if total else page + (1 if len(items) >= limit else 0)
        return self._page_result(items, page, max(page, pagecount), total or pagecount * limit, limit)

    def _category_hot_show(self, page, scope, ext):
        if page > 1:
            return self._page_result([], page, 1, 0, 50)
        params = {"start": 0, "count": 50, "updated_at": "", "items_only": 1, "for_mobile": 1}
        data = self._get_json(self.API + "/subject_collection/show_hot/items", params=params, ttl=self.list_cache_ttl)
        items = []
        for raw in data.get("subject_collection_items") or []:
            subtitle = str(raw.get("card_subtitle") or "")
            if scope == "zy_cn" and "中国" not in subtitle:
                continue
            if scope == "zy_other" and "中国" in subtitle:
                continue
            card = self._collection_card(raw, ext)
            self._apply_douban_follow_action(card, ext)
            items.append(card)
        return self._page_result(items, 1, 1, len(items), 50)

    def _category_movie_list(self, page, collection, ext):
        if collection == "top250":
            return self._category_top250(page, ext)
        return self._category_collection(page, collection, ext)

    def _category_collection(self, page, collection, ext):
        limit = 50
        params = {"start": (page - 1) * limit, "count": limit, "updated_at": "", "items_only": 1, "for_mobile": 1}
        data = self._get_json(self.API + "/subject_collection/%s/items" % quote(collection, safe=""), params=params, ttl=self.collection_cache_ttl)
        is_tv = collection in {value for _, value in self.TV_LISTS}
        items = []
        for raw in data.get("subject_collection_items") or []:
            card = self._collection_card(raw, ext)
            if is_tv:
                self._apply_douban_follow_action(card, ext)
            items.append(card)
        total = self._positive_int(data.get("total"), len(items))
        pagecount = max(page, int(math.ceil(float(total) / limit))) if total else page
        return self._page_result(items, page, pagecount, total, limit)

    def _category_top250(self, page, ext):
        limit = 25
        if page > 10:
            return self._page_result([], page, 10, 250, limit)
        text = self._get_text(self.MOVIE + "/top250", params={"start": (page - 1) * limit}, ttl=self.top250_cache_ttl)
        doc = html.fromstring(text)
        items = []
        nodes = doc.xpath("//div[contains(@class,'article')]//ol[contains(@class,'grid_view')]/li")
        for node in nodes:
            href = self._xpath_text(node, ".//div[contains(@class,'pic')]/a/@href")
            subject_id = self._subject_id(href)
            if not subject_id:
                continue
            title = self._xpath_text(node, ".//div[contains(@class,'hd')]//span[contains(@class,'title')][1]")
            pic = self._xpath_text(node, ".//div[contains(@class,'pic')]//img/@src")
            score = self._xpath_text(node, ".//span[contains(@class,'rating_num')]")
            card = {"vod_id": subject_id, "vod_name": title, "vod_pic": self._image(pic), "vod_remarks": (score + "分") if score else "Top250"}
            items.append(card)
        return self._page_result(items, page, 10, 250, limit)

    def _category_recommend(self, kind, page, ext):
        limit = 20
        if kind == "movie":
            type_value = self._value(ext, "1", "")
            area = self._value(ext, "2", "")
            tags = [type_value, area, self._value(ext, "3", ""), self._value(ext, "4", "")]
            selected = {"类型": type_value, "地区": area}
            sort = self._value(ext, "5", "U")
        else:
            form = self._value(ext, "1", "")
            series = self._value(ext, "2", "")
            show = self._value(ext, "3", "")
            area = self._value(ext, "4", "")
            subtype = series if form == "电视剧" else show if form == "综艺" else ""
            tags = [subtype or form, area, self._value(ext, "5", ""), self._value(ext, "6", ""), self._value(ext, "7", "")]
            selected = {"类型": subtype, "形式": form, "地区": area}
            sort = self._value(ext, "8", "U")
        params = {
            "refresh": 0,
            "start": (page - 1) * limit,
            "count": limit,
            "selected_categories": json.dumps(selected, ensure_ascii=False, separators=(",", ":")),
            "uncollect": "false",
            "sort": sort,
            "tags": ",".join([item for item in tags if item]),
        }
        data = self._get_json(self.API + "/%s/recommend" % kind, params=params, ttl=self.list_cache_ttl)
        items = []
        for raw in data.get("items") or []:
            if raw.get("type") and raw.get("type") != kind:
                continue
            card = self._collection_card(raw, ext)
            if kind == "tv":
                self._apply_douban_follow_action(card, ext)
            items.append(card)
        total = self._positive_int(data.get("total"), 0)
        pagecount = int(math.ceil(float(total) / limit)) if total else page + (1 if len(items) >= limit else 0)
        return self._page_result(items, page, max(page, pagecount), total or pagecount * limit, limit)

    def _category_wishlist(self, page):
        user_id = self.user_id or self._resolve_user_id()
        if not user_id:
            message = "请在 ext 中配置 user_id；写回想看还需 cookie，ck 可从 Cookie 自动读取"
            return self._page_result([self._error_card("豆瓣想看未配置", message)], page, page, 1, 15)
        start = (page - 1) * 15
        url = self.MOVIE + "/people/%s/wish" % quote(user_id, safe="")
        cache_key = "wishlist:%s:%s" % (user_id, page)
        text = self._get_text(url, params={"start": start, "sort": "time", "rating": "all", "filter": "all", "mode": "grid"}, custom_key=cache_key, ttl=self.wishlist_cache_ttl)
        doc = html.fromstring(text)
        items = []
        nodes = doc.xpath("//div[contains(concat(' ',normalize-space(@class),' '),' grid-view ')]//div[contains(concat(' ',normalize-space(@class),' '),' item ')]")
        for node in nodes:
            href = self._xpath_text(node, ".//li[contains(@class,'title')]/a/@href")
            subject_id = self._subject_id(href)
            if not subject_id:
                continue
            title = self._xpath_text(node, ".//li[contains(@class,'title')]//em") or self._xpath_text(node, ".//img/@alt")
            pic = self._xpath_text(node, ".//img/@src")
            date = self._xpath_text(node, ".//span[contains(@class,'date')]")
            intro = self._xpath_text(node, ".//li[contains(@class,'intro')]")
            remark = date or (intro[:24] if intro else "想看")
            items.append({"vod_id": subject_id, "vod_name": title, "vod_pic": self._image(pic), "vod_remarks": remark})
        title_text = self._xpath_text(doc, "//title")
        match = re.search(r"\((\d+)\)", title_text)
        total = int(match.group(1)) if match else start + len(items)
        pagecount = max(page, int(math.ceil(float(total) / 15))) if total else page
        return self._page_result(items, page, pagecount, total, 15)

    def _category_anime(self, region, page, ext):
        kind = self._value(ext, "kind", "tv")
        if kind not in ("tv", "movie"):
            kind = "tv"
        sort = self._value(ext, "sort", "U")
        if sort not in {item[1] for item in self.ANIME_SORTS}:
            sort = "U"
        year = self._value(ext, "year", "")
        genre = self._value(ext, "genre", "")
        format_tag = self._value(ext, "format", "")
        limit = 20
        if kind == "movie":
            selected = {"类型": "动画", "地区": region}
        else:
            selected = {"类型": "动画", "形式": "电视剧", "地区": region}
        tags = ["动画", region, year, genre, format_tag]
        params = {
            "refresh": 0,
            "start": (page - 1) * limit,
            "count": limit,
            "selected_categories": json.dumps(selected, ensure_ascii=False, separators=(",", ":")),
            "uncollect": "false",
            "sort": sort,
            "tags": ",".join([item for item in tags if item]),
        }
        data = self._get_json(self.API + "/%s/recommend" % kind, params=params, ttl=self.list_cache_ttl)
        items = []
        for raw in data.get("items") or []:
            raw_type = str(raw.get("type") or "")
            if raw_type and raw_type != kind:
                continue
            card = self._collection_card(raw, ext)
            if kind == "tv":
                self._apply_douban_follow_action(card, ext)
            items.append(card)
        total = self._positive_int(data.get("total"), 0)
        pagecount = int(math.ceil(float(total) / limit)) if total else page + (1 if len(items) >= limit else 0)
        return self._page_result(items, page, max(page, pagecount), total or pagecount * limit, limit)

    def _parse_collection_items(self, data):
        return [self._collection_card(raw, {}) for raw in data.get("subject_collection_items") or []]

    def _subject_card(self, raw, ext):
        score = str(raw.get("rate") or "").strip()
        card = {
            "vod_id": str(raw.get("id") or ""),
            "vod_name": str(raw.get("title") or ""),
            "vod_pic": self._image(str(raw.get("cover") or "")),
            "vod_remarks": (score + "分") if score and score != "0" else "暂无评分",
        }
        return card

    def _collection_card(self, raw, ext):
        rating = self._rating(raw)
        honor = self._names(raw.get("honor_infos"), "title", 1)
        remark = (rating + "分") if rating else "暂无评分"
        if honor:
            remark += " " + honor
        card = {
            "vod_id": str(raw.get("id") or ""),
            "vod_name": str(raw.get("title") or ""),
            "vod_pic": self._image(self._pic(raw)),
            "vod_remarks": remark,
        }
        return card

    def _apply_douban_follow_action(self, card, ext):
        subject_id = self._subject_id(card.get("vod_id"))
        if not subject_id:
            return card
        tracked = any(
            str(item.get("douban_id") or "") == subject_id
            for item in (self._follow_memory.get("items") or {}).values()
        )
        old_remark = str(card.get("vod_remarks") or "")
        card["vod_remarks"] = ("已追更" if tracked else "全局搜索") + ((" · " + old_remark) if old_remark else "")
        return card

    def _with_series_mode_cards(self, result, page):
        return self._with_navigation_search(result)

    def _with_navigation_search(self, result):
        if not isinstance(result, dict) or not isinstance(result.get("list"), list):
            return result
        output = dict(result)
        cards = []
        for source in result.get("list") or []:
            card = dict(source) if isinstance(source, dict) else source
            if isinstance(card, dict) and not str(card.get("vod_id") or "").startswith(self.ERROR_PREFIX):
                self._apply_global_search_action(card)
            cards.append(card)
        output["list"] = cards
        return output

    def _load_series_action_mode(self):
        getter = getattr(self, "getCache", None)
        value = None
        if callable(getter):
            try:
                value = getter(self.SERIES_MODE_CACHE_KEY)
            except Exception:
                value = None
        if isinstance(value, dict):
            value = value.get("mode")
        self._series_action_mode = "browse" if str(value or "") == "browse" else "add"

    def _set_series_action_mode(self, mode):
        self._series_action_mode = "browse"
        return json.dumps({"msg": "导航页已固定为全局搜索；追更请在追更确认操作"}, ensure_ascii=False)

    def _series_card_action(self, source, item_id, title):
        return "%s%s:%s:%s" % (
            self.SERIES_CARD_PREFIX,
            quote(str(source or ""), safe=""),
            quote(str(item_id or ""), safe=""),
            quote(str(title or ""), safe=""),
        )

    def _run_series_card_action(self, payload):
        parts = str(payload or "").split(":", 2)
        if len(parts) != 3:
            return json.dumps({"msg": "剧集操作参数无效"}, ensure_ascii=False)
        source, item_id, title = (unquote(part).strip() for part in parts)
        if source not in ("tmdb", "douban"):
            return json.dumps({"msg": "剧集来源无效"}, ensure_ascii=False)
        return self._open_global_search(quote(title, safe=""))

    def _apply_global_search_action(self, card):
        title = str(card.get("vod_name") or "").strip() if isinstance(card, dict) else ""
        if title:
            card["action"] = self.GLOBAL_SEARCH_PREFIX + quote(title, safe="")
            old_remark = str(card.get("vod_remarks") or "")
            if not old_remark.startswith("全局搜索"):
                card["vod_remarks"] = "全局搜索" + ((" · " + old_remark) if old_remark else "")
        return card

    def _open_global_search(self, raw_title):
        title = unquote(str(raw_title or "")).strip()
        if not title:
            return json.dumps({"msg": "全局搜索标题无效"}, ensure_ascii=False)
        try:
            try:
                from java import jclass
                jclass("com.fongmi.android.tv.event.ServerEvent").search(title)
            except Exception:
                self._post_local_action({"do": "search", "word": title})
            return json.dumps({"msg": "已打开全局搜索：" + title}, ensure_ascii=False)
        except Exception as exc:
            return json.dumps({"msg": "打开全局搜索失败：%s" % self._short_error(exc)}, ensure_ascii=False)

    def _follow_action_mode(self, ext):
        return self._series_action_mode

    def _get_filters(self):
        now = time.time()
        if self._filters is not None and now - self._filters_at < self.filter_cache_ttl:
            return self._filters
        persisted = self._load_persistent_filters()
        if persisted is not None:
            self._filters = persisted
            self._filters_at = now
            return persisted
        filters = self._base_filters()
        if self.dynamic_filters:
            self._merge_dynamic_filters(filters)
        self._filters = filters
        self._filters_at = now
        self._save_persistent_filters(filters)
        return filters

    def _load_persistent_filters(self):
        if not self.persistent_filter_cache:
            return None
        getter = getattr(self, "getCache", None)
        if not callable(getter):
            return None
        try:
            value = getter(self.FILTER_CACHE_KEY)
            if not isinstance(value, dict):
                return None
            filters = value.get("filters")
            if not isinstance(filters, dict):
                return None
            required = {item[0] for item in self.CATEGORIES}
            if not required.issubset(set(filters)):
                return None
            return filters
        except Exception:
            return None

    def _save_persistent_filters(self, filters):
        if not self.persistent_filter_cache:
            return
        setter = getattr(self, "setCache", None)
        if not callable(setter):
            return
        try:
            setter(self.FILTER_CACHE_KEY, {
                "expiresAt": int(time.time() + self.filter_cache_ttl),
                "filters": filters,
            })
        except Exception:
            pass

    def _base_filters(self):
        years = [str(year) for year in range(time.localtime().tm_year, 1979, -1)]
        hot_movie = [
            self._filter("sort", "排序", self.ANIME_SORTS),
            self._filter("type", "类型", [("全部类型", "")] + [(v, v) for v in self.MOVIE_TYPES]),
            self._filter("area", "地区", [("全部地区", "")] + [(v, v) for v in self.AREAS]),
            self._filter("year", "年代", [("全部年代", "")] + [(v, v) for v in years]),
            self._filter("tag", "标签", [("全部标签", "")] + [(v, v) for v in self.TAGS]),
        ]
        hot_tv = [
            self._filter("sort", "排序", self.ANIME_SORTS),
            self._filter("genre", "题材", [("全部题材", "")] + [(v, v) for v in self.TV_GENRES]),
            self._filter("area", "地区", [("全部地区", "")] + [(v, v) for v in self.AREAS]),
            self._filter("year", "年代", [("全部年代", "")] + [(v, v) for v in years]),
            self._filter("platform", "平台", [("全部平台", "")] + [(v, v) for v in self.PLATFORMS]),
            self._filter("tag", "标签", [("全部标签", "")] + [(v, v) for v in self.TAGS]),
        ]
        hot_show = [
            self._filter("sort", "排序", self.ANIME_SORTS),
            self._filter("genre", "类型", [("全部类型", "")] + [(v, v) for v in self.SHOW_TYPES]),
            self._filter("area", "地区", [("全部地区", "")] + [(v, v) for v in self.AREAS]),
            self._filter("year", "年代", [("全部年代", "")] + [(v, v) for v in years]),
            self._filter("platform", "平台", [("全部平台", "")] + [(v, v) for v in self.PLATFORMS]),
        ]
        return {
            "follow_updates": [],
            "follow_candidates": [self._filter("mode", "操作", (
                ("确认加入追更", "view"),
                ("清理播放记录（需再次确认）", "clear"),
            ))],
            "follow_manage": [self._filter("mode", "操作", (
                ("查看追更", "view"),
                ("标记当前集已看（需确认）", "seen"),
                ("取消追更（需确认）", "remove"),
            ))],
            "tmdb_trending": [
                self._filter("media", "内容", (("全部", "all"), ("电影", "movie"), ("剧集", "tv"))),
                self._filter("window", "周期", (("今日", "day"), ("本周", "week"))),
            ],
            "tmdb_movie": [
                self._filter("sort", "排序", (("热度", "popularity.desc"), ("上映时间", "primary_release_date.desc"), ("评分", "vote_average.desc"))),
                self._filter("genre", "类型", self.TMDB_MOVIE_GENRES),
                self._filter("country", "产地", (("全部", ""), ("中国大陆", "CN"), ("日本", "JP"), ("韩国", "KR"), ("美国", "US"), ("英国", "GB"))),
                self._filter("year", "年代", [("全部年代", "")] + [(v, v) for v in years]),
            ],
            "tmdb_tv": [
                self._filter("sort", "排序", (("热度", "popularity.desc"), ("首播时间", "first_air_date.desc"), ("评分", "vote_average.desc"))),
                self._filter("genre", "类型", self.TMDB_TV_GENRES),
                self._filter("country", "产地", (("全部", ""), ("中国大陆", "CN"), ("日本", "JP"), ("韩国", "KR"), ("美国", "US"), ("英国", "GB"))),
                self._filter("year", "年代", [("全部年代", "")] + [(v, v) for v in years]),
            ],
            "tmdb_anime": [
                self._filter("sort", "排序", (("热度", "popularity.desc"), ("更新时间", "first_air_date.desc"), ("评分", "vote_average.desc"))),
                self._filter("region", "地区", (("全部", ""), ("国漫", "CN"), ("日漫", "JP"), ("韩漫", "KR"), ("美漫", "US"))),
                self._filter("kind", "内容", (("动画剧集", "tv"), ("动画电影", "movie"))),
                self._filter("year", "年代", [("全部年代", "")] + [(v, v) for v in years]),
            ],
            "hotmovie": hot_movie,
            "hottv": hot_tv,
            "hotzy": hot_show,
            "movielist": [self._filter("1", "榜单", self.MOVIE_LISTS)],
            "tvlist": [self._filter("1", "榜单", self.TV_LISTS)],
            "moviefilter": [
                self._filter("5", "排序", self.SORTS),
                self._filter("1", "类型", [("全部类型", "")] + [(v, v) for v in self.MOVIE_TYPES]),
                self._filter("2", "地区", [("全部地区", "")] + [(v, v) for v in self.AREAS]),
                self._filter("3", "年代", [("全部年代", "")] + [(v, v) for v in years]),
                self._filter("4", "标签", [("全部标签", "")] + [(v, v) for v in self.TAGS]),
            ],
            "tvfilter": [
                self._filter("8", "排序", self.SORTS),
                self._filter("1", "类型", [("全部类型", "")] + [(v, v) for v in self.TV_TYPES]),
                self._filter("2", "电视剧", [("全部剧集", "")] + [(v, v) for v in self.SERIES_TYPES]),
                self._filter("3", "综艺", [("全部综艺", "")] + [(v, v) for v in self.SHOW_TYPES]),
                self._filter("4", "地区", [("全部地区", "")] + [(v, v) for v in self.AREAS]),
                self._filter("5", "年代", [("全部年代", "")] + [(v, v) for v in years]),
                self._filter("6", "平台", [("全部平台", "")] + [(v, v) for v in self.PLATFORMS]),
                self._filter("7", "标签", [("全部标签", "")] + [(v, v) for v in self.TAGS]),
            ],
            "anime": self._anime_filters(years),
            "wishlist": [],
        }

    def _anime_filters(self, years):
        return [
            self._filter("sort", "排序", self.ANIME_SORTS),
            self._filter("region", "地区", (("国漫", "cn"), ("日漫", "jp"), ("韩漫", "kr"), ("美漫", "us"))),
            self._filter("kind", "内容", (("动画剧集", "tv"), ("动画电影", "movie"))),
            self._filter("year", "年代", [("全部年代", "")] + [(v, v) for v in years]),
            self._filter("genre", "题材", [("全部题材", "")] + [(v, v) for v in self.ANIME_GENRES]),
            self._filter("format", "形式", [("全部形式", "")] + [(v, v) for v in self.ANIME_FORMATS]),
        ]

    def _merge_dynamic_filters(self, filters):
        jobs = {
            "movie_meta": (self.API + "/movie/recommend", {}),
            "tv_meta": (self.API + "/tv/recommend", {}),
        }
        results = {}
        try:
            with ThreadPoolExecutor(max_workers=4) as executor:
                futures = {executor.submit(self._get_json, url, params, self.filter_cache_ttl): key for key, (url, params) in jobs.items()}
                for future in as_completed(futures):
                    try:
                        results[futures[future]] = future.result()
                    except Exception:
                        pass
        except Exception:
            return
        self._merge_recommend_meta(filters.get("moviefilter"), results.get("movie_meta"), False)
        self._merge_recommend_meta(filters.get("tvfilter"), results.get("tv_meta"), True)

    def _merge_recommend_meta(self, target, data, is_tv):
        if not target or not isinstance(data, dict):
            return
        categories = data.get("recommend_categories") or []
        try:
            if is_tv:
                type_data = categories[0].get("data") or []
                if type_data:
                    tags = type_data[0].get("tags") or []
                    values = []
                    for item in tags[1:]:
                        name = str(item).replace("全部剧集", "电视剧").replace("全部综艺", "综艺")
                        values.append((name, name))
                    if values:
                        self._set_filter_values(target, "1", [("全部类型", "")] + values)
                if len(categories) > 1:
                    areas = categories[1].get("data") or []
                    values = [(str(v.get("text")), str(v.get("text"))) for v in areas[1:] if v.get("text")]
                    if values:
                        self._set_filter_values(target, "4", [("全部地区", "")] + values)
            else:
                for index in (0, 1):
                    values = []
                    for item in (categories[index].get("data") or [])[1:]:
                        if item.get("text"):
                            values.append((str(item["text"]), str(item["text"])))
                    if values:
                        self._set_filter_values(target, "1" if index == 0 else "2", [("全部" + ("类型" if index == 0 else "地区"), "")] + values)
            sorts = [(str(v.get("text")), str(v.get("name"))) for v in data.get("sorts") or [] if v.get("text") and v.get("name")]
            if sorts:
                self._set_filter_values(target, "8" if is_tv else "5", sorts)
        except Exception:
            return

    def _set_filter_values(self, filters, key, pairs):
        for item in filters or []:
            if str(item.get("key")) == str(key):
                item["value"] = self._values(pairs)
                return

    def _get_json(self, url, params=None, ttl=None):
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

    def _get_text(self, url, params=None, custom_key="", ttl=None):
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

    def _request_json(self, url, params=None):
        return self._douban_client.request_json(url, params)

    def _request_text(self, url, params=None):
        return self._douban_client.request_text(url, params)

    def _schedule_cache_refresh(self, key, loader):
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

    def _json_response(self, response):
        try:
            value = response.json()
            return value if isinstance(value, dict) else {"data": value}
        except Exception:
            if response.status_code != 200:
                return {"error": "HTTP %s" % response.status_code}
            raise RuntimeError("上游返回了非 JSON 内容")

    def _reset_session(self):
        if self._session is not None:
            try:
                self._session.close()
            except Exception:
                pass
        session = requests.Session()
        session.trust_env = self.trust_env
        session.headers.update({"User-Agent": self.user_agent, "Referer": self.host + "/", "Accept": "application/json,text/html;q=0.9,*/*;q=0.8"})
        if self.cookie:
            session.headers["Cookie"] = self.cookie
        if self.proxy:
            session.proxies.update({"http": self.proxy, "https": self.proxy})
        adapter = self._retry_adapter()
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        self._session = session
        if self._tmdb_session is not None:
            try:
                self._tmdb_session.close()
            except Exception:
                pass
        tmdb = requests.Session()
        tmdb.trust_env = self.tmdb_trust_env
        tmdb.headers.update({"Accept": "application/json", "User-Agent": "Douban-TMDB-Follow-Spider/1.0"})
        if self.tmdb_access_token:
            tmdb.headers["Authorization"] = "Bearer " + self.tmdb_access_token
        if self.tmdb_proxy:
            tmdb.proxies.update({"http": self.tmdb_proxy, "https": self.tmdb_proxy})
        tmdb.mount("https://", self._retry_adapter())
        self._tmdb_session = tmdb
        if self._atvp_session is not None:
            try:
                self._atvp_session.close()
            except Exception:
                pass
        atvp = requests.Session()
        atvp.trust_env = self.atvp_trust_env
        atvp.headers.update({"Accept": "application/json", "User-Agent": "Douban-TMDB-Follow-Spider/2.0"})
        if self._history_auth_token:
            atvp.headers["Authorization"] = self._history_auth_token
        atvp.mount("http://", self._atvp_retry_adapter())
        atvp.mount("https://", self._atvp_retry_adapter())
        self._atvp_session = atvp
    @staticmethod
    def _atvp_retry_adapter():
        try:
            from requests.packages.urllib3.util.retry import Retry
            retry = Retry(
                total=2,
                connect=2,
                read=2,
                status=0,
                backoff_factor=0.4,
                allowed_methods=frozenset(("GET",)),
            )
            return HTTPAdapter(max_retries=retry, pool_connections=4, pool_maxsize=4)
        except TypeError:
            return HTTPAdapter(max_retries=0, pool_connections=4, pool_maxsize=4)

    @staticmethod
    def _retry_adapter():
        try:
            from requests.packages.urllib3.util.retry import Retry
            retry = Retry(
                total=1,
                connect=1,
                read=0,
                status=1,
                backoff_factor=0.2,
                status_forcelist=(429, 500, 502, 503, 504),
                allowed_methods=frozenset(("GET",)),
            )
            return HTTPAdapter(max_retries=retry, pool_connections=8, pool_maxsize=8)
        except TypeError:
            return HTTPAdapter(max_retries=1, pool_connections=8, pool_maxsize=8)

    def _resolve_user_id(self):
        if self.user_id:
            return self.user_id
        if not self.cookie:
            return ""
        try:
            response = self._session.get("https://www.douban.com/mine/", timeout=self.timeout, verify=self.verify_tls, allow_redirects=True)
            match = re.search(r"/people/([^/?#]+)/?", response.url)
            if not match:
                match = re.search(r"https?://www\.douban\.com/people/([^/?#]+)/?", response.text)
            if match:
                self.user_id = match.group(1)
        except Exception:
            pass
        return self.user_id

    def _parse_config(self, extend):
        value = extend
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return {}
            if len(text) >= 2 and text.startswith("'") and text.endswith("'"):
                text = text[1:-1].strip()
            try:
                value = json.loads(text)
            except Exception:
                return {}
        if not isinstance(value, dict):
            return {}
        data = value.get("data")
        if data:
            nested = self._parse_config(data)
            merged = dict(value)
            merged.update(nested)
            if value.get("api"):
                merged["_atvp_api"] = value.get("api")
            if value.get("token") is not None:
                merged["_atvp_token"] = value.get("token")
            return merged
        return dict(value)

    def _parse_extend(self, extend):
        if isinstance(extend, dict):
            return extend
        if isinstance(extend, str):
            text = extend.strip()
            if not text:
                return {}
            try:
                value = json.loads(text)
                return value if isinstance(value, dict) else {}
            except Exception:
                return {}
        return {}

    def _cache_get(self, key, ttl, allow_expired=False):
        now = time.time()
        with self._cache_lock:
            item = self._cache.get(key)
            if item:
                created, value = item
                age = now - created
                limit = self.stale_ttl if allow_expired else ttl
                if age <= limit:
                    self._cache.move_to_end(key)
                    return value
                if age > self.stale_ttl:
                    self._cache.pop(key, None)

        self._load_response_cache()
        with self._cache_lock:
            item = self._persistent_cache.get(key)
            if not item:
                return None
            created, value = item
            age = now - created
            limit = self.stale_ttl if allow_expired else ttl
            if age > limit:
                if age > self.stale_ttl:
                    self._persistent_cache.pop(key, None)
                    self._schedule_response_cache_save()
                return None
            self._persistent_cache.move_to_end(key)
            self._cache[key] = (created, value)
            self._cache.move_to_end(key)
            return value

    def _cache_set(self, key, value):
        coordination_cache = str(key or "").startswith("resource-search:")
        if self.cache_ttl <= 0 and not coordination_cache:
            return
        created = time.time()
        with self._cache_lock:
            self._cache[key] = (created, value)
            self._cache.move_to_end(key)
            while len(self._cache) > self.cache_max_entries:
                self._cache.popitem(last=False)
        if self._is_persistable_cache_key(key):
            self._load_response_cache()
            with self._cache_lock:
                self._persistent_cache[key] = (created, value)
                self._persistent_cache.move_to_end(key)
                limit = min(self.cache_max_entries, 48)
                while len(self._persistent_cache) > limit:
                    self._persistent_cache.popitem(last=False)
            self._schedule_response_cache_save()

    def _drop_cache_prefix(self, prefix):
        self._load_response_cache()
        changed = False
        with self._cache_lock:
            for key in list(self._cache):
                if key.startswith(prefix):
                    self._cache.pop(key, None)
            for key in list(self._persistent_cache):
                if key.startswith(prefix):
                    self._persistent_cache.pop(key, None)
                    changed = True
        if changed:
            self._schedule_response_cache_save()

    @staticmethod
    def _is_persistable_cache_key(key):
        return str(key or "").startswith(("json:", "text:", "tmdb-json:", "wishlist:"))

    def _load_response_cache(self):
        with self._cache_lock:
            if self._persistent_cache_loaded:
                return
            self._persistent_cache_loaded = True
        getter = getattr(self, "getCache", None)
        value = None
        if callable(getter):
            try:
                value = getter(self.RESPONSE_CACHE_KEY)
            except Exception:
                value = None
        entries = value.get("entries") if isinstance(value, dict) else None
        if not isinstance(entries, list):
            return
        restored = OrderedDict()
        now = time.time()
        for entry in entries[-48:]:
            if not isinstance(entry, list) or len(entry) != 3:
                continue
            key, created, payload = entry
            try:
                created = float(created)
            except Exception:
                continue
            if self._is_persistable_cache_key(key) and now - created <= self.stale_ttl:
                restored[str(key)] = (created, payload)
        with self._cache_lock:
            self._persistent_cache.update(restored)

    def _schedule_response_cache_save(self):
        setter = getattr(self, "setCache", None)
        if not callable(setter):
            return False
        job_owner = object()
        with self._cache_lock:
            self._persistent_cache_dirty = True
            if self._persistent_cache_saving:
                return True
            self._persistent_cache_saving = job_owner
            generation = self._cache_generation

        def worker():
            time.sleep(0.05)
            with self._cache_lock:
                if generation != self._cache_generation:
                    if self._persistent_cache_saving is job_owner:
                        self._persistent_cache_saving = None
                    return
                entries = [
                    [key, created, value]
                    for key, (created, value) in list(self._persistent_cache.items())[-48:]
                ]
                self._persistent_cache_dirty = False
            error = None
            saved = False
            with self._cache_persist_lock:
                try:
                    with self._cache_lock:
                        if (generation != self._cache_generation
                                or self._persistent_cache_saving is not job_owner):
                            return
                    result = setter(self.RESPONSE_CACHE_KEY, {
                        "version": self.RESPONSE_CACHE_VERSION,
                        "entries": entries,
                    })
                    saved = str(result or "").strip().lower() != "failed"
                except Exception as exc:
                    error = exc
                with self._cache_lock:
                    if generation != self._cache_generation:
                        if self._persistent_cache_saving is job_owner:
                            self._persistent_cache_saving = None
                        return
                    if self._persistent_cache_saving is not job_owner:
                        return
                    if not saved:
                        self._persistent_cache_dirty = True
                    repeat = bool(saved and self._persistent_cache_dirty)
                    self._persistent_cache_saving = None
            if not saved:
                self._diagnostic_event(
                    "cache.save", "WARN", exc=error,
                    generation=generation, count=len(entries),
                    result="failed" if error is None else "exception",
                )
            if repeat:
                self._schedule_response_cache_save()

        try:
            self._tasks.start_thread(worker, name="response-cache-save")
        except Exception:
            with self._cache_lock:
                if self._persistent_cache_saving is job_owner:
                    self._persistent_cache_saving = None
            return False
        return True

    def _flush_response_cache_sync(self):
        """Best-effort final write for dirty persistable responses during shutdown."""
        setter = getattr(self, "setCache", None)
        if not callable(setter):
            return False
        with self._cache_lock:
            if not self._persistent_cache_dirty and not self._persistent_cache:
                return False
            entries = [
                [key, created, value]
                for key, (created, value) in list(self._persistent_cache.items())[-48:]
            ]
            generation = self._cache_generation
            self._persistent_cache_dirty = False
        try:
            with self._cache_persist_lock:
                result = setter(self.RESPONSE_CACHE_KEY, {
                    "version": self.RESPONSE_CACHE_VERSION,
                    "entries": entries,
                })
            if str(result or "").strip().lower() == "failed":
                with self._cache_lock:
                    self._persistent_cache_dirty = True
                self._diagnostic_event(
                    "cache.flush", "WARN", generation=generation,
                    count=len(entries), result="failed",
                )
                return False
            self._diagnostic_event("cache.flush", generation=generation, count=len(entries))
            return True
        except Exception as exc:
            with self._cache_lock:
                self._persistent_cache_dirty = True
            self._diagnostic_event("cache.flush", "WARN", exc=exc, count=len(entries))
            return False

    def _remember_failure(self, key, exc):
        self._cache_coordinator.remember_failure(key, exc)

    def _clear_cached_failure(self, key):
        self._cache_coordinator.clear_failure(key)

    def _raise_cached_failure(self, key):
        self._cache_coordinator.raise_if_blocked(key)

    def _has_cached_failure(self, key):
        return self._cache_coordinator.failure_active(key)

    def _page_result(self, items, page, pagecount, total, limit):
        return {"list": items, "page": page, "pagecount": max(page, pagecount), "limit": limit, "total": total}

    def _error_card(self, title, exc, subject_id=""):
        message = self._short_error(exc)
        identity = self.ERROR_PREFIX + quote(message[:180], safe="")
        return {"vod_id": subject_id or identity, "vod_name": title, "vod_pic": "", "vod_remarks": message, "vod_content": message}

    def _detail_remark(self, data, rating):
        parts = []
        if rating:
            parts.append(rating + "分")
        parts.extend([str(v) for v in data.get("durations") or []][:1])
        episode_count = self._positive_int(data.get("episodes_count"), 0)
        if episode_count:
            parts.append("%s集" % episode_count)
        return " / ".join(parts)

    def _image(self, url):
        value = str(url or "").strip()
        if not value or not self.image_headers or "doubanio.com" not in value:
            return value
        return value + "@Referer=https://m.douban.com/@User-Agent=" + self.user_agent

    @staticmethod
    def _pic(data, large=False):
        pic = data.get("pic") or {}
        if isinstance(pic, dict):
            return str(pic.get("large" if large else "normal") or pic.get("normal") or pic.get("large") or "")
        return str(data.get("cover_url") or data.get("cover") or "")

    @staticmethod
    def _rating(data):
        rating = data.get("rating")
        if isinstance(rating, dict):
            value = rating.get("value")
        else:
            value = data.get("rate")
        if value in (None, "", 0, "0"):
            return ""
        return str(value)

    @staticmethod
    def _names(items, key, limit):
        values = []
        for item in items or []:
            value = item.get(key) if isinstance(item, dict) else item
            if value:
                values.append(str(value))
            if len(values) >= limit:
                break
        return ", ".join(values)

    @staticmethod
    def _xpath_text(node, xpath):
        try:
            values = node.xpath(xpath)
            if not values:
                return ""
            value = values[0]
            if hasattr(value, "text_content"):
                value = value.text_content()
            return " ".join(str(value).split())
        except Exception:
            return ""

    @staticmethod
    def _subject_id(value):
        match = re.search(r"(?:subject/)?(\d{3,})", str(value or ""))
        return match.group(1) if match else ""

    def _first_id(self, ids):
        value = ids
        if isinstance(value, str):
            text = value.strip()
            if text.startswith("["):
                try:
                    value = json.loads(text)
                except Exception:
                    value = text
        if isinstance(value, (list, tuple)):
            return str(value[0]) if value else ""
        return str(value or "")

    @staticmethod
    def _cookie_value(cookie, name):
        match = re.search(r"(?:^|;\s*)%s=([^;]*)" % re.escape(name), str(cookie or ""))
        return match.group(1) if match else ""

    @staticmethod
    def _value(data, key, default=""):
        if not isinstance(data, dict):
            return default
        value = data.get(key)
        if value is None and str(key).isdigit():
            value = data.get(int(key))
        return default if value is None else str(value)

    @staticmethod
    def _filter(key, name, pairs):
        return {"key": key, "name": name, "value": Spider._values(pairs)}

    @staticmethod
    def _values(pairs):
        result = []
        seen = set()
        for name, value in pairs:
            marker = str(value)
            if marker in seen:
                continue
            seen.add(marker)
            result.append({"n": str(name), "v": marker})
        return result

    @staticmethod
    def _positive_int(value, default):
        try:
            result = int(value)
            return result if result > 0 else default
        except Exception:
            return default

    @staticmethod
    def _bounded_int(value, default, minimum, maximum):
        try:
            result = int(value)
        except Exception:
            return default
        return max(minimum, min(maximum, result))

    @staticmethod
    def _bool_value(value, default):
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in ("1", "true", "yes", "on")

    @staticmethod
    def _first(data, *keys):
        for key in keys:
            value = data.get(key) if isinstance(data, dict) else None
            if value is not None and str(value).strip():
                return str(value).strip()
        return ""

    @staticmethod
    def _https_base(value, default):
        text = str(value or default).strip().rstrip("/")
        return text if text.startswith("https://") else default

    @staticmethod
    def _http_base(value, default):
        text = str(value or default).strip().rstrip("/")
        return text if text.startswith(("http://", "https://")) else default

    @staticmethod
    def _string_mapping(value):
        data = value
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except Exception:
                return {}
        if not isinstance(data, dict):
            return {}
        return {
            str(key).strip(): str(item).strip()
            for key, item in data.items()
            if str(key).strip() and str(item).strip()
        }

    @classmethod
    def _resource_mode_list(cls, value):
        data = value
        if data is None or data == "":
            return ["vod"]
        if isinstance(data, str):
            text = data.strip()
            try:
                parsed = json.loads(text)
                data = parsed if isinstance(parsed, list) else re.split(r"[,;\s]+", text)
            except Exception:
                data = re.split(r"[,;\s]+", text)
        if not isinstance(data, (list, tuple, set)):
            return ["vod"]
        result = []
        for raw in data:
            mode = str(raw or "").strip().lower()
            if mode in cls.RESOURCE_SEARCH_MODES and mode not in result:
                result.append(mode)
        return result or ["vod"]

    @staticmethod
    def _id_list(value):
        values = value if isinstance(value, (list, tuple, set)) else re.split(r"[,;\s]+", str(value or ""))
        result = []
        seen = set()
        for raw in values:
            try:
                item = int(raw)
            except Exception:
                continue
            if item > 0 and item not in seen:
                seen.add(item)
                result.append(item)
        return result

    def _short_error(self, exc):
        text = str(exc or "未知错误").strip().replace("\r", " ").replace("\n", " ")
        text = re.sub(
            r"(?i)([?&](?:api[_-]?key|access[_-]?token|token|secret|ck|cookie|password|proxy[_-]?(?:user|username|password))=)[^&\s]+",
            r"\1***", text,
        )
        text = re.sub(
            r"(?i)\b(ck|cookie|password|proxy[_-]?(?:user|username|password))\s*[:=]\s*([^\s,;&]+)",
            r"\1=***", text,
        )
        text = re.sub(
            r"(?i)(/(?:play|parse|offline_download|p)/)[^/?#\s]+",
            r"\1***", text,
        )
        for secret in (
                getattr(self, "atvp_token", ""), getattr(self, "_history_auth_token", ""),
                getattr(self, "tmdb_api_key", ""), getattr(self, "tmdb_access_token", ""),
                getattr(self, "history_password", ""), getattr(self, "cookie", ""),
                getattr(self, "ck", ""), getattr(self, "proxy", ""),
                getattr(self, "tmdb_proxy", "")):
            value = str(secret or "").strip()
            if len(value) >= 4:
                text = text.replace(value, "***").replace(quote(value, safe=""), "***")
        return text[:220] or "未知错误"

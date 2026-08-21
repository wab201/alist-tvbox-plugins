# coding=utf-8
"""
//@version:3
"""

import ast
import json
import re
import threading
import time
from html.parser import HTMLParser
from urllib.parse import urlencode, urljoin, urlsplit

import requests


SCHEMA_DECLARATION = r'''
FILTER_CONFIG_SCHEMA = {
  "source": "declared",
  "description": "通用番号中文字幕过滤器。识别详情或播放上下文中的番号，并向播放器结果追加 FongMi 原生 subs。",
  "allowAdditional": false,
  "fields": [
    {"key": "enabled", "label": "启用过滤器", "type": "boolean", "required": false, "defaultValue": true},
    {"key": "subtitle_mode", "label": "字幕接入方式", "type": "string", "required": false, "defaultValue": "native"},
    {"key": "subtitle_worker_base_url", "label": "字幕 Worker 地址", "type": "string", "required": false},
    {"key": "subtitle_sources", "label": "字幕来源顺序", "type": "string", "required": false, "defaultValue": "xunlei|subtitlecat"},
    {"key": "timeout", "label": "字幕请求超时秒数", "type": "number", "required": false, "defaultValue": 10},
    {"key": "subtitle_cache_ttl", "label": "字幕缓存秒数", "type": "number", "required": false, "defaultValue": 21600},
    {"key": "mark_detail", "label": "详情标记识别到的番号", "type": "boolean", "required": false, "defaultValue": false},
    {"key": "overwrite_subs", "label": "覆盖站点已有字幕", "type": "boolean", "required": false, "defaultValue": false}
  ]
}
FILTER_SCHEMA_END = 1
'''


FILTER_CONFIG_SCHEMA = {
    "source": "declared",
    "description": "通用番号中文字幕过滤器。识别详情或播放上下文中的番号，并向播放器结果追加 FongMi 原生 subs。",
    "allowAdditional": False,
    "fields": [
        {"key": "enabled", "label": "启用过滤器", "type": "boolean", "required": False, "defaultValue": True},
        {"key": "subtitle_mode", "label": "字幕接入方式", "type": "string", "required": False, "defaultValue": "native"},
        {"key": "subtitle_worker_base_url", "label": "字幕 Worker 地址", "type": "string", "required": False},
        {"key": "subtitle_sources", "label": "字幕来源顺序", "type": "string", "required": False, "defaultValue": "xunlei|subtitlecat"},
        {"key": "timeout", "label": "字幕请求超时秒数", "type": "number", "required": False, "defaultValue": 10},
        {"key": "subtitle_cache_ttl", "label": "字幕缓存秒数", "type": "number", "required": False, "defaultValue": 21600},
        {"key": "mark_detail", "label": "详情标记识别到的番号", "type": "boolean", "required": False, "defaultValue": False},
        {"key": "overwrite_subs", "label": "覆盖站点已有字幕", "type": "boolean", "required": False, "defaultValue": False},
    ],
}


XUNLEI_SUBTITLE_API = "https://api-shoulei-ssl.xunlei.com/oracle/subtitle"
SUBTITLECAT_SITE = "https://subtitlecat.com"
DEFAULT_UA = (
    "Mozilla/5.0 (Linux; Android 11; TV) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
CODE_PATTERNS = (
    re.compile(r"(?<![A-Z0-9])FC2(?:[-_ ]?PPV)?[-_ ]?(\d{5,9})(?![A-Z0-9])", re.I),
    re.compile(r"(?<![A-Z0-9])([A-Z]{2,10})[-_ ]+(\d{2,7})(?![A-Z0-9])", re.I),
    re.compile(r"(?<![A-Z0-9])([A-Z]{2,10})(\d{3,7})(?![A-Z0-9])", re.I),
)
IGNORED_CODE_PREFIXES = frozenset(
    ("AAC", "AVC", "BD", "DVD", "FHD", "FPS", "H264", "H265", "HDR", "HEVC", "UHD", "WEB")
)


def _clean_text(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _bool(value, default=False):
    if isinstance(value, bool):
        return value
    if value is None or value == "":
        return default
    return str(value).strip().lower() in ("1", "true", "yes", "on", "y")


def _bounded_int(value, default, minimum, maximum):
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        return default
    return min(max(number, minimum), maximum)


def _parse_config(value):
    if isinstance(value, dict):
        return dict(value)
    text = str(value or "").strip()
    if not text:
        return {}
    for loader in (json.loads, ast.literal_eval):
        try:
            data = loader(text)
            if isinstance(data, dict):
                return data
        except Exception:
            continue
    return {}


def _normalize_code(prefix, number):
    upper = str(prefix or "").upper().replace("_", "-").strip("- ")
    digits = str(number or "").strip()
    if not upper or not digits:
        return ""
    if upper.startswith("FC2"):
        return "FC2-PPV-" + digits
    if upper in IGNORED_CODE_PREFIXES:
        return ""
    return upper + "-" + digits


def extract_video_code(*values):
    text = " ".join(_clean_text(value).upper() for value in values if value)
    if not text:
        return ""
    for index, pattern in enumerate(CODE_PATTERNS):
        match = pattern.search(text)
        if not match:
            continue
        if index == 0:
            return "FC2-PPV-" + match.group(1)
        code = _normalize_code(match.group(1), match.group(2))
        if code:
            return code
    return ""


def _code_matches(value, code):
    compact_value = re.sub(r"[^A-Z0-9]", "", str(value or "").upper())
    compact_code = re.sub(r"[^A-Z0-9]", "", str(code or "").upper())
    return bool(compact_code and compact_code in compact_value)


def _http_url(value):
    text = str(value or "").strip()
    try:
        parsed = urlsplit(text)
    except Exception:
        return ""
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return ""
    return text


def _subtitle_mime(url):
    path = urlsplit(str(url or "")).path.lower()
    if path.endswith(".vtt"):
        return "text/vtt"
    if path.endswith((".ass", ".ssa")):
        return "text/x-ssa"
    return "application/x-subrip"


class _LinkParser(HTMLParser):
    def __init__(self):
        HTMLParser.__init__(self)
        self.links = []
        self._href = ""
        self._text = []

    def handle_starttag(self, tag, attrs):
        if str(tag).lower() != "a":
            return
        self._href = dict(attrs).get("href") or ""
        self._text = []

    def handle_data(self, data):
        if self._href:
            self._text.append(data)

    def handle_endtag(self, tag):
        if str(tag).lower() == "a" and self._href:
            self.links.append((self._href, "".join(self._text)))
            self._href = ""
            self._text = []


def _html_links(text):
    parser = _LinkParser()
    try:
        parser.feed(str(text or ""))
    except Exception:
        return []
    return parser.links


class SubtitleResolver:
    def _init_subtitle_resolver(self):
        self._subtitle_session = requests.Session()
        self._subtitle_session.headers.update({"User-Agent": DEFAULT_UA, "Accept-Language": "zh-CN,zh;q=0.9"})
        self._subtitle_enabled = True
        self._subtitle_mode = "native"
        self._subtitle_worker = ""
        self._subtitle_sources = ("xunlei", "subtitlecat")
        self._subtitle_timeout = 10
        self._subtitle_cache_ttl = 21600
        self._subtitle_cache = {}
        self._subtitle_lock = threading.RLock()

    def _configure_subtitles(self, config):
        self._subtitle_enabled = _bool(config.get("enabled"), True)
        mode = str(config.get("subtitle_mode") or "native").strip().lower()
        self._subtitle_mode = mode if mode in ("native", "hls") else "native"
        self._subtitle_worker = _http_url(config.get("subtitle_worker_base_url")).rstrip("/")
        requested = [
            item.strip().lower()
            for item in re.split(r"[,|]", str(config.get("subtitle_sources") or "xunlei|subtitlecat"))
        ]
        self._subtitle_sources = tuple(item for item in requested if item in ("xunlei", "subtitlecat")) or ("xunlei",)
        self._subtitle_timeout = _bounded_int(config.get("timeout"), 10, 3, 30)
        self._subtitle_cache_ttl = _bounded_int(config.get("subtitle_cache_ttl"), 21600, 60, 604800)
        with self._subtitle_lock:
            self._subtitle_cache = {}

    def _subtitle_rows(self, payload):
        if isinstance(payload, list):
            return payload
        if not isinstance(payload, dict):
            return []
        for key in ("data", "results", "items", "subtitles"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
            if isinstance(value, dict):
                nested = self._subtitle_rows(value)
                if nested:
                    return nested
        return []

    def _find_xunlei_subtitle(self, code):
        try:
            response = self._subtitle_session.get(
                XUNLEI_SUBTITLE_API,
                params={"name": code},
                timeout=self._subtitle_timeout,
            )
            response.raise_for_status()
            payload = response.json()
        except Exception:
            return ""
        for row in self._subtitle_rows(payload):
            if not isinstance(row, dict):
                continue
            url = _http_url(row.get("url") or row.get("subtitle_url") or row.get("download_url"))
            if not url:
                continue
            haystack = " ".join(str(row.get(key) or "") for key in ("name", "extra_name")) + " " + url
            if _code_matches(haystack, code):
                return url
        return ""

    def _find_subtitlecat_subtitle(self, code):
        try:
            search = self._subtitle_session.get(
                SUBTITLECAT_SITE + "/index.php",
                params={"search": code},
                timeout=self._subtitle_timeout,
            )
            search.raise_for_status()
            detail_url = ""
            for href, label in _html_links(search.text):
                if href and _code_matches(label + " " + href, code):
                    detail_url = _http_url(urljoin(SUBTITLECAT_SITE + "/", href))
                    if detail_url:
                        break
            if not detail_url:
                return ""
            detail = self._subtitle_session.get(detail_url, timeout=self._subtitle_timeout)
            detail.raise_for_status()
        except Exception:
            return ""
        candidates = []
        for href, label in _html_links(detail.text):
            if not re.search(r"\.srt(?:\?|$)|download\.php", href, re.I):
                continue
            url = _http_url(urljoin(detail_url, href))
            if not url:
                continue
            text = href + " " + label
            score = 0
            if re.search(r"zh-CN|zh_CN|simplified|简体", text, re.I):
                score = 3
            elif re.search(r"zh|cn|chinese|中文", text, re.I):
                score = 2
            candidates.append((score, url))
        if not candidates:
            return ""
        candidates.sort(key=lambda item: item[0], reverse=True)
        return candidates[0][1]

    def _resolve_subtitle(self, code):
        normalized = extract_video_code(code)
        if not self._subtitle_enabled or not normalized:
            return ""
        now = time.time()
        with self._subtitle_lock:
            cached = self._subtitle_cache.get(normalized)
            if cached and now - cached[0] < self._subtitle_cache_ttl:
                return cached[1]
        subtitle_url = ""
        for source in self._subtitle_sources:
            if source == "xunlei":
                subtitle_url = self._find_xunlei_subtitle(normalized)
            elif source == "subtitlecat":
                subtitle_url = self._find_subtitlecat_subtitle(normalized)
            if subtitle_url:
                break
        with self._subtitle_lock:
            self._subtitle_cache[normalized] = (now, subtitle_url)
        return subtitle_url

    def _subtitle_track(self, subtitle_url):
        source_url = _http_url(subtitle_url)
        if not source_url:
            return None
        if self._subtitle_worker:
            proxy_url = self._subtitle_worker + "/subtitle.vtt?" + urlencode({"subtitle": source_url})
            return {"name": "中文字幕", "url": proxy_url, "lang": "zh-CN", "format": "text/vtt", "flag": 1}
        return {
            "name": "中文字幕",
            "url": source_url,
            "lang": "zh-CN",
            "format": _subtitle_mime(source_url),
            "flag": 1,
        }

    def _attach_native_subtitle(self, result, subtitle_url, overwrite=False):
        if not isinstance(result, dict):
            return result
        track = self._subtitle_track(subtitle_url)
        if not track:
            return result
        output = dict(result)
        existing = output.get("subs")
        if isinstance(existing, list) and existing and not overwrite:
            urls = {str(item.get("url") or "") for item in existing if isinstance(item, dict)}
            if track["url"] not in urls:
                output["subs"] = list(existing) + [track]
            return output
        output["subs"] = [track]
        return output

    def _attach_hls_subtitle(self, result, subtitle_url):
        if not isinstance(result, dict) or not self._subtitle_worker:
            return result
        output = dict(result)
        value = output.get("url")

        def wrap(item):
            text = str(item or "").strip()
            if not re.search(r"\.m3u8(?:[?#]|$)", text, re.I):
                return item
            if text.startswith(self._subtitle_worker + "/master.m3u8"):
                return item
            return self._subtitle_worker + "/master.m3u8?" + urlencode({"video": text, "subtitle": subtitle_url})

        if isinstance(value, list):
            converted = list(value)
            for index in range(1, len(converted), 2):
                converted[index] = wrap(converted[index])
            output["url"] = converted
        elif isinstance(value, str):
            output["url"] = wrap(value)
        return output

    def _attach_subtitle(self, result, code, overwrite=False):
        subtitle_url = self._resolve_subtitle(code)
        if not subtitle_url:
            return result
        if self._subtitle_mode == "hls":
            return self._attach_hls_subtitle(result, subtitle_url)
        return self._attach_native_subtitle(result, subtitle_url, overwrite=overwrite)


class Filter(SubtitleResolver):
    def __init__(self):
        self._init_subtitle_resolver()
        self.enabled = True
        self.mark_detail = False
        self.overwrite_subs = False
        self._play_codes = {}
        self._play_lock = threading.RLock()

    def init(self, extend="", context=None):
        config = _parse_config(extend)
        self.enabled = _bool(config.get("enabled"), True)
        self.mark_detail = _bool(config.get("mark_detail"), False)
        self.overwrite_subs = _bool(config.get("overwrite_subs"), False)
        self._configure_subtitles(config)
        with self._play_lock:
            self._play_codes = {}

    def detail(self, result, context=None):
        if not self.enabled or not isinstance(result, dict):
            return result
        vods = result.get("list")
        if not isinstance(vods, list):
            return result
        output = dict(result)
        filtered = []
        for vod in vods:
            if not isinstance(vod, dict):
                filtered.append(vod)
                continue
            item = dict(vod)
            code = extract_video_code(
                item.get("vod_name"),
                item.get("vod_remarks"),
                item.get("vod_content"),
                item.get("vod_id"),
                item.get("vod_play_from"),
                item.get("vod_play_url"),
            )
            if code:
                self._remember_play_codes(item, code)
                if self.mark_detail:
                    remarks = _clean_text(item.get("vod_remarks"))
                    if code not in remarks.upper():
                        item["vod_remarks"] = (remarks + " · 字幕候选 " + code).strip(" ·")
            filtered.append(item)
        output["list"] = filtered
        return output

    def player(self, result, context=None):
        if not self.enabled or not isinstance(result, dict) or not isinstance(context, dict):
            return result
        if not result.get("url"):
            return result
        play_id = str(context.get("id") or "").strip()
        with self._play_lock:
            cached_code = self._play_codes.get(play_id, "")
        code = cached_code or extract_video_code(
            context.get("vod_name"),
            context.get("episode_name"),
            context.get("play_from"),
            play_id,
        )
        if not code:
            return result
        return self._attach_subtitle(result, code, overwrite=self.overwrite_subs)

    def _remember_play_codes(self, vod, code):
        values = []
        for group in str(vod.get("vod_play_url") or "").split("$$$"):
            for episode in str(group or "").split("#"):
                label, separator, target = episode.partition("$")
                value = target if separator else label
                if value:
                    values.append(str(value).strip())
        for group in vod.get("group") or []:
            if not isinstance(group, dict):
                continue
            for media in group.get("media") or []:
                if isinstance(media, dict) and media.get("url"):
                    values.append(str(media.get("url")).strip())
        with self._play_lock:
            if len(self._play_codes) >= 4096:
                self._play_codes = {}
            for value in values:
                if value:
                    self._play_codes[value] = code

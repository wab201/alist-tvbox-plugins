# coding=utf-8
# //@name:MissAV 中文字幕
# //@id:missav_subtitle
# //@version:1

import ast
import base64
import json
import re
import threading
import time
from urllib.parse import quote, urlencode, urljoin, urlsplit

import requests
from lxml import html as lxml_html

from base.spider import Spider as BaseSpider


SCHEMA_DECLARATION = r'''
PLUGIN_CONFIG_SCHEMA = {
  "source": "declared",
  "description": "MissAV 直连插件。字幕优先使用 FongMi 原生 subs；Worker 仅用于字幕转码代理或旧客户端 HLS 回退。",
  "allowAdditional": false,
  "fields": [
    {"key": "host", "label": "站点地址", "type": "string", "required": false, "defaultValue": "https://missav.ws"},
    {"key": "cookie", "label": "站点 Cookie", "type": "secret", "required": false, "description": "只在你有权使用的会话中填写；脚本不会尝试绕过验证码或托管挑战。"},
    {"key": "timeout", "label": "请求超时秒数", "type": "number", "required": false, "defaultValue": 12},
    {"key": "subtitle_enabled", "label": "启用中文字幕", "type": "boolean", "required": false, "defaultValue": true},
    {"key": "subtitle_mode", "label": "字幕接入方式", "type": "string", "required": false, "defaultValue": "native", "description": "native=FongMi 原生 subs；hls=Worker 包装视频，仅用于旧客户端。"},
    {"key": "subtitle_worker_base_url", "label": "字幕 Worker 地址", "type": "string", "required": false, "description": "native 模式下用于 SRT 转 VTT；留空时直接使用字幕原地址。"},
    {"key": "subtitle_sources", "label": "字幕来源顺序", "type": "string", "required": false, "defaultValue": "xunlei,subtitlecat"},
    {"key": "subtitle_cache_ttl", "label": "字幕缓存秒数", "type": "number", "required": false, "defaultValue": 21600}
  ]
}
PLUGIN_SCHEMA_END = 1
FILTER_CONFIG_SCHEMA = {
  "source": "declared",
  "description": "通用番号中文字幕过滤器。作用范围由 AList-TVBox 过滤器页面配置，推荐拦截 detail,player。",
  "allowAdditional": false,
  "fields": [
    {"key": "enabled", "label": "启用过滤器", "type": "boolean", "required": false, "defaultValue": true},
    {"key": "subtitle_mode", "label": "字幕接入方式", "type": "string", "required": false, "defaultValue": "native"},
    {"key": "subtitle_worker_base_url", "label": "字幕 Worker 地址", "type": "string", "required": false},
    {"key": "subtitle_sources", "label": "字幕来源顺序", "type": "string", "required": false, "defaultValue": "xunlei,subtitlecat"},
    {"key": "timeout", "label": "字幕请求超时秒数", "type": "number", "required": false, "defaultValue": 10},
    {"key": "subtitle_cache_ttl", "label": "字幕缓存秒数", "type": "number", "required": false, "defaultValue": 21600},
    {"key": "mark_detail", "label": "详情标记识别到的番号", "type": "boolean", "required": false, "defaultValue": false},
    {"key": "overwrite_subs", "label": "覆盖站点已有字幕", "type": "boolean", "required": false, "defaultValue": false}
  ]
}
FILTER_SCHEMA_END = 1
'''


PLUGIN_CONFIG_SCHEMA = {
    "source": "declared",
    "description": "MissAV 直连插件。字幕优先使用 FongMi 原生 subs；Worker 仅用于字幕转码代理或旧客户端 HLS 回退。",
    "allowAdditional": False,
    "fields": [
        {"key": "host", "label": "站点地址", "type": "string", "required": False, "defaultValue": "https://missav.ws"},
        {"key": "cookie", "label": "站点 Cookie", "type": "secret", "required": False, "description": "只在你有权使用的会话中填写；脚本不会尝试绕过验证码或托管挑战。"},
        {"key": "timeout", "label": "请求超时秒数", "type": "number", "required": False, "defaultValue": 12},
        {"key": "subtitle_enabled", "label": "启用中文字幕", "type": "boolean", "required": False, "defaultValue": True},
        {"key": "subtitle_mode", "label": "字幕接入方式", "type": "string", "required": False, "defaultValue": "native", "description": "native=FongMi 原生 subs；hls=Worker 包装视频，仅用于旧客户端。"},
        {"key": "subtitle_worker_base_url", "label": "字幕 Worker 地址", "type": "string", "required": False, "description": "native 模式下用于 SRT 转 VTT；留空时直接使用字幕原地址。"},
        {"key": "subtitle_sources", "label": "字幕来源顺序", "type": "string", "required": False, "defaultValue": "xunlei,subtitlecat"},
        {"key": "subtitle_cache_ttl", "label": "字幕缓存秒数", "type": "number", "required": False, "defaultValue": 21600},
    ],
}

FILTER_CONFIG_SCHEMA = {
    "source": "declared",
    "description": "通用番号中文字幕过滤器。作用范围由 AList-TVBox 过滤器页面配置，推荐拦截 detail,player。",
    "allowAdditional": False,
    "fields": [
        {"key": "enabled", "label": "启用过滤器", "type": "boolean", "required": False, "defaultValue": True},
        {"key": "subtitle_mode", "label": "字幕接入方式", "type": "string", "required": False, "defaultValue": "native"},
        {"key": "subtitle_worker_base_url", "label": "字幕 Worker 地址", "type": "string", "required": False},
        {"key": "subtitle_sources", "label": "字幕来源顺序", "type": "string", "required": False, "defaultValue": "xunlei,subtitlecat"},
        {"key": "timeout", "label": "字幕请求超时秒数", "type": "number", "required": False, "defaultValue": 10},
        {"key": "subtitle_cache_ttl", "label": "字幕缓存秒数", "type": "number", "required": False, "defaultValue": 21600},
        {"key": "mark_detail", "label": "详情标记识别到的番号", "type": "boolean", "required": False, "defaultValue": False},
        {"key": "overwrite_subs", "label": "覆盖站点已有字幕", "type": "boolean", "required": False, "defaultValue": False},
    ],
}


DEFAULT_HOST = "https://missav.ws"
XUNLEI_SUBTITLE_API = "https://api-shoulei-ssl.xunlei.com/oracle/subtitle"
SUBTITLECAT_SITE = "https://subtitlecat.com"
DEFAULT_UA = (
    "Mozilla/5.0 (Linux; Android 11; TV) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
ATVP_DETAIL_PREFIX = "atvp_detail:"
PLAY_PREFIX = "missav-play:"
STATUS_PREFIX = "missav-status:"
CHALLENGE_MARKERS = (
    "just a moment",
    "cf-browser-verification",
    "attention required",
    "turnstile",
    "captcha",
    "cloudflare",
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


def _normalize_origin(value):
    text = str(value or DEFAULT_HOST).strip().rstrip("/")
    try:
        parsed = urlsplit(text)
    except Exception:
        return DEFAULT_HOST
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return DEFAULT_HOST
    return parsed.scheme + "://" + parsed.netloc


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


def _format_duration(seconds):
    try:
        total = int(float(seconds))
    except (TypeError, ValueError):
        return ""
    if total <= 0:
        return ""
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return "%02d:%02d:%02d" % (hours, minutes, secs)


def _subtitle_mime(url):
    path = urlsplit(str(url or "")).path.lower()
    if path.endswith(".vtt"):
        return "text/vtt"
    if path.endswith((".ass", ".ssa")):
        return "text/x-ssa"
    return "application/x-subrip"


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
        self._subtitle_enabled = _bool(config.get("subtitle_enabled", config.get("enabled")), True)
        mode = str(config.get("subtitle_mode") or "native").strip().lower()
        self._subtitle_mode = mode if mode in ("native", "hls") else "native"
        self._subtitle_worker = str(config.get("subtitle_worker_base_url") or "").strip().rstrip("/")
        requested = [item.strip().lower() for item in str(config.get("subtitle_sources") or "xunlei,subtitlecat").split(",")]
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
            url = row.get("url") or row.get("subtitle_url") or row.get("download_url")
            if not url:
                continue
            haystack = " ".join(str(row.get(key) or "") for key in ("name", "extra_name")) + " " + str(url)
            if _code_matches(haystack, code):
                return str(url).strip()
        return ""

    def _find_subtitlecat_subtitle(self, code):
        try:
            search = self._subtitle_session.get(
                SUBTITLECAT_SITE + "/index.php",
                params={"search": code},
                timeout=self._subtitle_timeout,
            )
            search.raise_for_status()
            search_document = lxml_html.fromstring(search.text)
            detail_url = ""
            for link in search_document.xpath("//table//tbody//tr//td//a[@href] | //a[@href]"):
                href = str(link.get("href") or "").strip()
                if href and _code_matches(link.text_content() + " " + href, code):
                    detail_url = urljoin(SUBTITLECAT_SITE + "/", href)
                    break
            if not detail_url:
                return ""
            detail = self._subtitle_session.get(detail_url, timeout=self._subtitle_timeout)
            detail.raise_for_status()
            detail_document = lxml_html.fromstring(detail.text)
        except Exception:
            return ""
        candidates = []
        for link in detail_document.xpath("//a[@href]"):
            href = str(link.get("href") or "").strip()
            text = href + " " + link.text_content()
            if re.search(r"\.srt(?:\?|$)|download\.php", href, re.I):
                score = 0
                if re.search(r"zh-CN|zh_CN|simplified|简体", text, re.I):
                    score = 3
                elif re.search(r"zh|cn|chinese|中文", text, re.I):
                    score = 2
                candidates.append((score, urljoin(detail_url, href)))
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
        source_url = str(subtitle_url or "").strip()
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

    def _worker_master_url(self, video_url, subtitle_url):
        if not self._subtitle_worker:
            return ""
        return self._subtitle_worker + "/master.m3u8?" + urlencode(
            {"video": str(video_url or ""), "subtitle": str(subtitle_url or "")}
        )

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
            return self._worker_master_url(text, subtitle_url)

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


class Spider(BaseSpider, SubtitleResolver):
    name = "MissAV 中文字幕"
    backend_parse = False
    category_mode = False

    CATEGORIES = (
        ("today", "今日热门", "/dm242/cn/today-hot", "today_views"),
        ("weekly", "本周热门", "/dm168/cn/weekly-hot", "weekly_views"),
        ("monthly", "本月热门", "/dm207/cn/monthly-hot", "monthly_views"),
        ("release", "新作上市", "/dm509/cn/release", "released_at"),
        ("chinese", "中文字幕", "/dm265/cn/chinese-subtitle", "released_at"),
        ("uncensored", "无码流出", "/dm621/cn/uncensored-leak", "released_at"),
        ("fc2", "FC2", "/dm99/cn/fc2", "released_at"),
    )
    SORTS = (
        ("released_at", "发行日期"),
        ("published_at", "最近更新"),
        ("today_views", "今日浏览"),
        ("weekly_views", "本周浏览"),
        ("monthly_views", "本月浏览"),
        ("views", "总浏览"),
    )

    def __init__(self):
        BaseSpider.__init__(self)
        self._init_subtitle_resolver()
        self.host = DEFAULT_HOST
        self.timeout = 12
        self.cookie = ""
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": DEFAULT_UA,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.6",
            }
        )

    def init(self, extend=""):
        config = _parse_config(extend)
        self.host = _normalize_origin(config.get("host"))
        self.timeout = _bounded_int(config.get("timeout"), 12, 5, 30)
        self.cookie = str(config.get("cookie") or "").strip()
        self._configure_subtitles(config)
        return None

    def getName(self):
        return self.name

    def homeContent(self, filter=False):
        result = {
            "class": [{"type_id": item[0], "type_name": item[1]} for item in self.CATEGORIES],
            "list": [],
        }
        if filter:
            options = [{"n": label, "v": value} for value, label in self.SORTS]
            result["filters"] = {
                item[0]: [{"key": "sort", "name": "排序", "value": options}]
                for item in self.CATEGORIES
            }
        return result

    def homeVideoContent(self):
        return self.categoryContent("today", "1", False, {})

    def categoryContent(self, tid, pg, filter=False, extend=None):
        page = _bounded_int(pg, 1, 1, 100000)
        options = _parse_config(extend)
        category = next((item for item in self.CATEGORIES if item[0] == str(tid)), None)
        if category is None:
            return self._empty_page(page)
        sort_value = str(options.get("sort") or category[3]).strip()
        allowed_sorts = {item[0] for item in self.SORTS}
        if sort_value not in allowed_sorts:
            sort_value = category[3]
        url = self.host + category[2] + "?" + urlencode({"sort": sort_value, "page": page})
        return self._list_page(url, page)

    def searchContent(self, key, quick=False, pg="1"):
        keyword = _clean_text(key)
        page = _bounded_int(pg, 1, 1, 100000)
        if not keyword:
            return self._empty_page(page)
        url = self.host + "/cn/search/" + quote(keyword, safe="") + "?" + urlencode({"page": page})
        result = self._list_page(url, page)
        requested_code = extract_video_code(keyword)
        if requested_code:
            result["list"] = [
                item for item in result.get("list", [])
                if extract_video_code(item.get("vod_name"), item.get("vod_id")) == requested_code
            ]
            result["limit"] = len(result["list"])
            result["total"] = len(result["list"])
        return result

    def detailContent(self, ids):
        source_id = ids[0] if isinstance(ids, (list, tuple)) and ids else ids
        value = str(source_id or "").strip()
        if value.startswith(ATVP_DETAIL_PREFIX):
            value = value[len(ATVP_DETAIL_PREFIX):]
        if value.startswith(STATUS_PREFIX):
            return {"list": [self._status_detail(value[len(STATUS_PREFIX):])]}
        detail_url = urljoin(self.host + "/", value)
        try:
            html_text, final_url = self._request_html(detail_url, self.host + "/")
            document = lxml_html.fromstring(html_text)
            title = self._meta(document, "property", "og:title") or self._page_title(document)
            title = re.sub(r"\s*-\s*MissAV.*$", "", title, flags=re.I).strip()
            code = extract_video_code(title, final_url)
            if code and not title.upper().startswith(code.replace("-", "")) and code not in title.upper():
                title = code + " " + title
            picture = self._absolute_image(self._meta(document, "property", "og:image"), final_url)
            description = self._meta(document, "property", "og:description") or self._meta(document, "name", "description")
            duration = self._duration_seconds(document)
            uuid = self._extract_uuid(html_text)
            if not uuid:
                return {"list": [self._error_detail(final_url, code, title, picture, "未解析到视频 UUID")]}
            payload = {"detail": final_url, "uuid": uuid, "code": code, "duration": duration}
            play_id = PLAY_PREFIX + self._encode_payload(payload)
            remarks = " · ".join(item for item in (code, _format_duration(duration)) if item)
            return {
                "list": [
                    {
                        "vod_id": final_url,
                        "vod_name": title or code or "MissAV",
                        "vod_pic": picture,
                        "vod_remarks": remarks,
                        "vod_content": _clean_text(description),
                        "vod_play_from": "MissAV",
                        "vod_play_url": "正片$" + play_id,
                    }
                ]
            }
        except Exception as exc:
            return {"list": [self._error_detail(detail_url, extract_video_code(detail_url), "MissAV", "", str(exc))]}

    def playerContent(self, flag, id, vipFlags=None):
        try:
            payload = self._decode_play_id(id)
            detail_url = str(payload.get("detail") or self.host + "/")
            video_url = self._resolve_video_url(str(payload.get("uuid") or ""), detail_url)
            if not video_url:
                raise ValueError("未解析到可播放的 m3u8")
            result = {
                "parse": 0,
                "jx": 0,
                "playUrl": "",
                "url": video_url,
                "header": {"User-Agent": DEFAULT_UA, "Referer": detail_url},
            }
            return self._attach_subtitle(result, payload.get("code") or extract_video_code(detail_url))
        except Exception as exc:
            return {
                "parse": 0,
                "jx": 0,
                "playUrl": "",
                "url": "",
                "header": {},
                "msg": _clean_text(exc) or "播放解析失败",
            }

    def localProxy(self, param):
        return [404, "text/plain", None, "not found"]

    def _request_html(self, url, referer):
        headers = {"Referer": referer or self.host + "/"}
        if self.cookie:
            headers["Cookie"] = self.cookie
        response = self.session.get(url, headers=headers, timeout=self.timeout, allow_redirects=True)
        text = str(response.text or "")
        if response.status_code in (403, 429, 503) or self._looks_blocked(text):
            raise ValueError("站点返回风控或验证页，请在有权访问的浏览器会话中完成验证")
        response.raise_for_status()
        if not text.strip():
            raise ValueError("站点返回空页面")
        return text, response.url

    def _list_page(self, url, page):
        try:
            html_text, final_url = self._request_html(url, self.host + "/")
            items = self._parse_list(html_text, final_url)
            pagecount = self._parse_pagecount(html_text, page)
            return {
                "list": items,
                "page": page,
                "pagecount": pagecount,
                "limit": len(items),
                "total": max(len(items), pagecount * max(len(items), 1)),
            }
        except Exception as exc:
            message = _clean_text(exc) or "列表加载失败"
            return {
                "list": [
                    {
                        "vod_id": STATUS_PREFIX + message,
                        "vod_name": "访问受限：" + message,
                        "vod_pic": "",
                        "vod_remarks": "需要用户可见的浏览器验证或稍后重试",
                    }
                ],
                "page": page,
                "pagecount": page,
                "limit": 1,
                "total": 1,
            }

    def _parse_list(self, html_text, base_url):
        document = lxml_html.fromstring(html_text)
        items = []
        seen = set()
        for link in document.xpath("//a[@href]"):
            images = link.xpath(".//img[1]")
            if not images:
                continue
            image = images[0]
            href = str(link.get("href") or "").strip()
            full_url = urljoin(base_url, href)
            path = urlsplit(full_url).path.rstrip("/")
            match = re.search(r"/(?:dm\d+/)?cn/([a-z0-9][a-z0-9-]+)$", path, re.I)
            if not match:
                continue
            slug = re.sub(r"-(?:chinese-subtitle|uncensored-leak)$", "", match.group(1), flags=re.I)
            title = _clean_text(link.get("title") or image.get("alt") or link.text_content())
            code = extract_video_code(title, slug)
            if not code or full_url in seen:
                continue
            seen.add(full_url)
            picture = self._absolute_image(image.get("data-src") or image.get("src"), base_url)
            parent = link.getparent()
            card_text = _clean_text(parent.text_content() if parent is not None else link.text_content())
            duration_match = re.search(r"(?<!\d)(\d{1,2}:\d{2}(?::\d{2})?)(?!\d)", card_text)
            remarks = duration_match.group(1) if duration_match else code
            if title and code not in title.upper():
                title = code + " " + title
            items.append(
                {
                    "vod_id": full_url,
                    "vod_name": title or code,
                    "vod_pic": picture,
                    "vod_remarks": remarks,
                }
            )
        return items

    def _parse_pagecount(self, html_text, current):
        pages = [current]
        for match in re.finditer(r"[?&]page=(\d+)", str(html_text or ""), re.I):
            pages.append(_bounded_int(match.group(1), current, 1, 100000))
        return max(pages)

    def _resolve_video_url(self, uuid, detail_url):
        if not re.fullmatch(r"[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}", uuid, re.I):
            return ""
        playlist_url = "https://surrit.com/%s/playlist.m3u8" % uuid
        try:
            response = self.session.get(
                playlist_url,
                headers={"User-Agent": DEFAULT_UA, "Referer": detail_url},
                timeout=self.timeout,
            )
            response.raise_for_status()
            return self._pick_best_playlist(response.text, playlist_url)
        except Exception:
            return playlist_url

    @staticmethod
    def _pick_best_playlist(text, playlist_url):
        lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
        candidates = []
        pending_score = 0
        for line in lines:
            if line.startswith("#EXT-X-STREAM-INF:"):
                bandwidth = re.search(r"BANDWIDTH=(\d+)", line, re.I)
                resolution = re.search(r"RESOLUTION=(\d+)x(\d+)", line, re.I)
                pending_score = int(bandwidth.group(1)) if bandwidth else 0
                if resolution:
                    pending_score += int(resolution.group(2)) * 10000000
            elif not line.startswith("#") and ".m3u8" in line.lower():
                candidates.append((pending_score, urljoin(playlist_url, line)))
                pending_score = 0
        if candidates:
            return max(candidates, key=lambda item: item[0])[1]
        return playlist_url

    @staticmethod
    def _extract_uuid(html_text):
        text = str(html_text or "")
        patterns = (
            r"nineyu\.com\\?/([a-f0-9-]{36})\\?/seek\\?/_0\.jpg",
            r"surrit\.com\\?/([a-f0-9-]{36})\\?/",
            r"([a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})",
        )
        for pattern in patterns:
            match = re.search(pattern, text, re.I)
            if match:
                return match.group(1)
        return ""

    @staticmethod
    def _meta(document, attribute, value):
        if attribute not in ("name", "property"):
            return ""
        values = document.xpath("//meta[@%s=$value]/@content" % attribute, value=value)
        return _clean_text(values[0]) if values else ""

    @staticmethod
    def _page_title(document):
        values = document.xpath("//title[1]")
        return _clean_text(values[0].text_content()) if values else ""

    @staticmethod
    def _duration_seconds(document):
        values = document.xpath("//meta[@property='og:video:duration']/@content")
        return _bounded_int(values[0] if values else 0, 0, 0, 86400)

    @staticmethod
    def _absolute_image(url, base_url):
        value = urljoin(base_url, str(url or "").strip())
        return re.sub(r"/cover-t\.jpg(?=([?#]|$))", "/cover-n.jpg", value, flags=re.I)

    @staticmethod
    def _looks_blocked(text):
        lower = str(text or "").lower()
        return not lower.strip() or any(marker in lower for marker in CHALLENGE_MARKERS)

    @staticmethod
    def _encode_payload(payload):
        raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

    @staticmethod
    def _decode_play_id(value):
        text = str(value or "").strip()
        if not text.startswith(PLAY_PREFIX):
            raise ValueError("不支持的播放 ID")
        encoded = text[len(PLAY_PREFIX):]
        encoded += "=" * (-len(encoded) % 4)
        payload = json.loads(base64.urlsafe_b64decode(encoded.encode("ascii")).decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("播放 ID 数据无效")
        return payload

    @staticmethod
    def _empty_page(page):
        return {"list": [], "page": page, "pagecount": page, "limit": 0, "total": 0}

    @staticmethod
    def _status_detail(message):
        return {
            "vod_id": STATUS_PREFIX + str(message or ""),
            "vod_name": "MissAV 状态",
            "vod_pic": "",
            "vod_remarks": "不可播放",
            "vod_content": _clean_text(message),
            "vod_play_from": "",
            "vod_play_url": "",
        }

    @staticmethod
    def _error_detail(vod_id, code, title, picture, message):
        return {
            "vod_id": vod_id,
            "vod_name": title or code or "MissAV",
            "vod_pic": picture,
            "vod_remarks": code or "解析失败",
            "vod_content": _clean_text(message),
            "vod_play_from": "",
            "vod_play_url": "",
        }


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
        if str(result.get("parse") if result.get("parse") is not None else 0) not in ("0", "False", "false"):
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
            for value in values:
                if value:
                    self._play_codes[value] = code

# -*- coding: utf-8 -*-
# //@name:SeedHub磁力与多网盘
# //@id:seedhub
# //@version:1

import ast
import base64
import html as html_lib
import json
import re
from urllib.parse import parse_qs, parse_qsl, quote, urlencode, urljoin, urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup

from base.spider import Spider as BaseSpider


class Spider(BaseSpider):
    name = "SeedHub"
    backend_parse = True
    category_mode = True

    DEFAULT_HOSTS = (
        "https://sidhub.cc",
        "https://seeduck.cc",
        "https://hubdog.cc",
    )
    CATEGORIES = (
        ("1", "电影"),
        ("2", "动漫"),
        ("3", "剧集"),
    )
    SORTS = (
        ("update", "最近更新"),
        ("date", "上映时间"),
        ("score", "豆瓣评分"),
    )
    PROVIDERS = (
        ("magnet", "磁力"),
        ("baidu", "百度"),
        ("quark", "夸克"),
        ("xunlei", "迅雷"),
        ("uc", "UC"),
        ("ali", "阿里"),
        ("115", "115"),
        ("123", "123"),
        ("189", "天翼"),
        ("139", "移动云盘"),
        ("pikpak", "PikPak"),
        ("guangya", "光鸭"),
    )
    PROVIDER_HOSTS = (
        ("baidu", ("pan.baidu.com",)),
        ("quark", ("pan.quark.cn",)),
        ("xunlei", ("pan.xunlei.com",)),
        ("uc", ("drive.uc.cn", "fast.uc.cn")),
        ("ali", ("www.alipan.com", "alipan.com", "www.aliyundrive.com", "aliyundrive.com")),
        ("115", ("115.com", "115cdn.com", "anxia.com")),
        (
            "123",
            (
                "123pan.com",
                "123pan.cn",
                "123684.com",
                "123685.com",
                "123865.com",
                "123912.com",
                "123592.com",
                "123684.cn",
                "123685.cn",
                "123865.cn",
                "123912.cn",
                "123592.cn",
            ),
        ),
        ("189", ("cloud.189.cn", "h5.cloud.189.cn")),
        ("139", ("caiyun.139.com", "yun.139.com", "caiyun.feixin.10086.cn")),
        ("pikpak", ("mypikpak.com",)),
        ("guangya", ("guangyapan.com", "www.guangyapan.com")),
    )
    VIDEO_MARKERS = (
        "4k",
        "2160p",
        "1080p",
        "720p",
        "remux",
        "bluray",
        "web-dl",
        "webrip",
        "hdr",
        "dolby",
        "杜比",
        "蓝光",
        "无损",
    )
    SUBTITLE_MARKERS = (
        "中文字幕",
        "中字",
        "简中",
        "繁中",
        "中英",
        "双语字幕",
        "chs",
        "cht",
        "sub",
        "esub",
    )
    MAGNET_RE = re.compile(
        r"magnet:\?xt=urn:btih:[A-Za-z0-9]{32,40}(?:[^\s\"'<>\\]*)?",
        re.I,
    )
    MOVIE_ID_RE = re.compile(r"(?:^|/)movies/(\d+)(?:/|$)")
    ATVP_DETAIL_PREFIX = "atvp_detail:"
    PUSH_PREFIX = "push://"

    def __init__(self):
        super().__init__()
        self.session = requests.Session()
        self.timeout = 12
        self.hosts = list(self.DEFAULT_HOSTS)
        self.active_origin = self.hosts[0]
        self.max_magnets = 24
        self.max_pan_per_provider = 20
        self._home_cache = None
        self._resource_context = {}
        self._resolved_cache = {}
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Linux; Android 11; TV) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.6",
        }
        self.session.headers.update(self.headers)

    def init(self, extend=""):
        config = self._parse_extend(extend)
        host = str(config.get("host") or "").strip().rstrip("/")
        extra_hosts = config.get("hosts")
        hosts = []
        if host:
            hosts.append(host)
        if isinstance(extra_hosts, (list, tuple)):
            hosts.extend(str(item).strip().rstrip("/") for item in extra_hosts)
        hosts.extend(self.DEFAULT_HOSTS)
        self.hosts = self._valid_content_hosts(hosts)
        self.active_origin = self.hosts[0]
        self.timeout = self._bounded_int(config.get("timeout"), 12, 5, 30)
        self.max_magnets = self._bounded_int(config.get("max_magnets"), 24, 1, 60)
        self.max_pan_per_provider = self._bounded_int(
            config.get("max_pan_per_provider"), 20, 1, 60
        )
        self._home_cache = None
        self._resource_context.clear()
        self._resolved_cache.clear()
        return None

    def getName(self):
        return self.name

    def homeContent(self, filter=False):
        classes = [{"type_id": item[0], "type_name": item[1]} for item in self.CATEGORIES]
        result = {"class": classes, "list": []}
        if filter:
            filters = {}
            for type_id, _ in self.CATEGORIES:
                filters[type_id] = [
                    {
                        "key": "order",
                        "name": "排序",
                        "value": [{"n": label, "v": value} for value, label in self.SORTS],
                    }
                ]
            result["filters"] = filters
        try:
            page = self._fetch_page("/", "cover-container")
            videos = self._parse_list(page[0], page[1])
            result["list"] = videos
            self._home_cache = videos
        except Exception:
            result["list"] = list(self._home_cache or [])
        return result

    def homeVideoContent(self):
        if self._home_cache is not None:
            return {"list": list(self._home_cache)}
        return {"list": self.homeContent(False).get("list", [])}

    def categoryContent(self, tid, pg, filter=False, extend=None):
        page_number = self._bounded_int(pg, 1, 1, 100000)
        options = self._parse_extend_map(extend)
        order = str(options.get("order") or "update").strip().lower()
        if order not in {item[0] for item in self.SORTS}:
            order = "update"
        type_id = str(options.get("type") or options.get("genre") or "").strip()
        category_id = str(tid or "").strip()
        if not category_id.isdigit():
            return self._empty_page(page_number)
        if type_id.isdigit():
            path = "/categories/{}/types/{}/movies/".format(category_id, type_id)
        else:
            path = "/categories/{}/movies/".format(category_id)
        query = urlencode({"page": page_number, "order": order})
        try:
            html_text, final_url = self._fetch_page(path + "?" + query, "cover-container")
            videos = self._parse_list(html_text, final_url)
            pagecount = self._parse_pagecount(html_text, page_number)
            return {
                "list": videos,
                "page": page_number,
                "pagecount": pagecount,
                "limit": len(videos),
                "total": max(pagecount * max(len(videos), 1), len(videos)),
            }
        except Exception:
            return self._empty_page(page_number)

    def searchContent(self, key, quick=False, pg="1"):
        page_number = self._bounded_int(pg, 1, 1, 100000)
        keyword = str(key or "").strip()
        if not keyword:
            return self._empty_page(page_number)
        path = "/s/{}/?{}".format(quote(keyword, safe=""), urlencode({"page": page_number}))
        try:
            html_text, final_url = self._fetch_page(path, "cover-container")
            videos = self._parse_list(html_text, final_url)
            pagecount = self._parse_pagecount(html_text, page_number)
            return {
                "list": videos,
                "page": page_number,
                "pagecount": pagecount,
                "limit": len(videos),
                "total": max(pagecount * max(len(videos), 1), len(videos)),
            }
        except Exception:
            return self._empty_page(page_number)

    def detailContent(self, ids):
        source_id = ids[0] if isinstance(ids, (list, tuple)) and ids else ids
        movie_id = self._movie_id(source_id)
        if not movie_id:
            return {"list": []}
        try:
            html_text, final_url = self._fetch_page(
                "/movies/{}/".format(movie_id), "ul class=\"seeds\""
            )
            detail = self._parse_detail(html_text, final_url, movie_id)
            return {"list": [detail]} if detail else {"list": []}
        except Exception as exc:
            return {"list": [self._error_detail(movie_id, str(exc))]}

    def playerContent(self, flag, id, vipFlags=None):
        value = str(id or "").strip()
        if value.startswith(self.PUSH_PREFIX):
            value = value[len(self.PUSH_PREFIX) :].strip()
        try:
            if self._is_resolver_url(value):
                final_url = self._resolve_resource(value)
            elif self._valid_magnet(value) or self._valid_share_url(value):
                final_url = value
            else:
                raise ValueError("不支持的资源地址")
            return {
                "parse": 0,
                "jx": 0,
                "playUrl": "",
                "url": self.PUSH_PREFIX + final_url,
                "header": {},
            }
        except Exception as exc:
            message = self._clean_text(str(exc)) or "资源解析失败"
            return {
                "parse": 0,
                "jx": 0,
                "playUrl": "",
                "url": "",
                "header": {},
                "msg": message,
                "error": message,
                "content": message,
            }

    def destroy(self):
        try:
            self.session.close()
        except Exception:
            pass
        self._resource_context.clear()
        self._resolved_cache.clear()

    def isVideoFormat(self, url):
        return False

    def manualVideoCheck(self):
        return False

    def localProxy(self, param):
        return [404, "text/plain", None, "not found"]

    def action(self, action):
        return {}

    def _fetch_page(self, path, marker):
        ordered = [self.active_origin] + [item for item in self.hosts if item != self.active_origin]
        last_error = None
        for origin in ordered:
            target = urljoin(origin.rstrip("/") + "/", str(path or "").lstrip("/"))
            try:
                response = self.session.get(target, timeout=self.timeout, allow_redirects=True)
                response.raise_for_status()
                if not self._content_url_allowed(response.url):
                    raise ValueError("站点跳转到未授权域名")
                response.encoding = response.apparent_encoding or response.encoding or "utf-8"
                text = response.text
                if marker and marker not in text:
                    raise ValueError("页面缺少业务标记")
                self.active_origin = self._origin(response.url)
                return text, response.url
            except Exception as exc:
                last_error = exc
        raise ValueError("所有内容入口均不可用: {}".format(last_error or "unknown"))

    def _parse_list(self, html_text, page_url):
        soup = BeautifulSoup(html_text or "", "html.parser")
        videos = []
        seen = set()
        for card in soup.select("div.cover-container > div.cover"):
            anchor = card.select_one("a.image[href*='/movies/']")
            if anchor is None:
                continue
            movie_id = self._movie_id(anchor.get("href"))
            if not movie_id or movie_id in seen:
                continue
            seen.add(movie_id)
            title = self._clean_text(anchor.get("title") or anchor.get_text(" ", strip=True))
            if not title:
                continue
            image = card.select_one("a.image img")
            poster = urljoin(page_url, str(image.get("src") or "")) if image else ""
            summary = ""
            for item in card.select("ul > li"):
                if item.find("h2") is None:
                    text = self._clean_text(item.get_text(" ", strip=True))
                    if text and not text.startswith("类型:") and not text.startswith("类型："):
                        summary = text
                        break
            score_node = card.select_one("a[href*='movie.douban.com/subject/']")
            score = self._clean_text(score_node.get_text(" ", strip=True)) if score_node else ""
            remarks = score if score else self._summary_remark(summary)
            videos.append(
                {
                    "vod_id": movie_id,
                    "vod_name": title,
                    "vod_pic": poster,
                    "vod_remarks": remarks,
                    "vod_content": summary,
                }
            )
        return videos

    def _parse_detail(self, html_text, page_url, movie_id):
        soup = BeautifulSoup(html_text or "", "html.parser")
        title_node = soup.select_one("h1#cover")
        title = self._clean_heading(title_node.get_text(" ", strip=True) if title_node else "")
        if not title:
            raise ValueError("详情页缺少标题")
        poster_node = soup.select_one("div.cover-container > img")
        poster = urljoin(page_url, str(poster_node.get("src") or "")) if poster_node else ""
        metadata = self._parse_metadata(soup)
        description_node = soup.select_one("h2#description")
        description = ""
        if description_node is not None:
            paragraph = description_node.find_next_sibling("p")
            if paragraph is not None:
                description = self._clean_text(paragraph.get_text(" ", strip=True))

        aliases = self._title_aliases(title)
        resources = self._parse_magnets(soup, page_url)
        resources.extend(self._parse_pan_links(soup, page_url, aliases))
        groups = self._build_resource_groups(resources, page_url)
        if not groups:
            raise ValueError("详情页没有可用资源入口")

        play_from = []
        play_url = []
        atvp_groups = []
        for group in groups:
            play_from.append(group["name"])
            episodes = []
            media = []
            for resource in group["resources"]:
                resolver_url = resource["resolver_url"]
                deferred_url = self.PUSH_PREFIX + resolver_url
                label = self._safe_label(resource["label"])
                episodes.append(label + "$" + deferred_url)
                media.append({"name": label, "url": deferred_url})
                self._resource_context[resolver_url] = {
                    "provider": resource["provider"],
                    "referer": page_url,
                    "label": label,
                }
            play_url.append("#".join(episodes))
            atvp_groups.append({"name": group["name"], "media": media})

        resource_summary = " · ".join(
            "{}{}".format(group["name"], len(group["resources"])) for group in groups
        )
        content = description
        if resource_summary:
            content = (content + "\n\n" if content else "") + "资源：" + resource_summary
        return {
            "vod_id": movie_id,
            "vod_name": title,
            "vod_pic": poster,
            "vod_year": self._first_year(metadata.get("首播", "")),
            "vod_area": metadata.get("制片国家/地区", ""),
            "vod_lang": metadata.get("语言", ""),
            "vod_actor": metadata.get("主演", ""),
            "vod_director": metadata.get("导演", ""),
            "vod_remarks": metadata.get("资源更新于", resource_summary),
            "vod_douban_score": metadata.get("豆瓣评分", ""),
            "type_name": metadata.get("类型", ""),
            "vod_content": content,
            "vod_play_from": "$$$".join(play_from),
            "vod_play_url": "$$$".join(play_url),
            "group": atvp_groups,
        }

    def _parse_metadata(self, soup):
        result = {}
        for item in soup.select("div.cover-container > ul > li"):
            text = self._clean_text(item.get_text(" ", strip=True))
            if not text:
                continue
            match = re.match(r"^([^:：]{1,20})[:：]\s*(.*)$", text)
            if match:
                result[match.group(1).strip()] = match.group(2).strip()
        return result

    def _parse_magnets(self, soup, page_url):
        items = []
        for index, row in enumerate(soup.select("ul.seeds > li")):
            anchor = row.select_one("a[href*='seed_id=']")
            if anchor is None:
                continue
            href = str(anchor.get("href") or "").strip()
            if not self._resolver_query_valid(href, "seed_id"):
                continue
            label = self._clean_text(anchor.get("title") or anchor.get_text(" ", strip=True))
            size_node = row.select_one("code.size")
            size = self._clean_text(size_node.get_text(" ", strip=True)) if size_node else ""
            features = [
                self._clean_text(node.get_text(" ", strip=True))
                for node in row.select("code.seed-feature")
            ]
            created_node = row.select_one("span.create-time")
            created = self._clean_text(created_node.get_text(" ", strip=True)) if created_node else ""
            visible = label
            extras = [item for item in features if item and item.lower() not in visible.lower()]
            if size and size.lower() not in visible.lower():
                extras.append(size)
            if extras:
                visible += " [" + " ".join(extras) + "]"
            items.append(
                {
                    "provider": "magnet",
                    "label": visible,
                    "resolver_url": self._canonical_resolver_url(urljoin(page_url, href)),
                    "size": self._size_bytes(size or label),
                    "index": index,
                    "created": created,
                    "first": False,
                }
            )
        items.sort(key=self._resource_rank, reverse=True)
        return items[: self.max_magnets]

    def _parse_pan_links(self, soup, page_url, aliases):
        grouped = {}
        for index, anchor in enumerate(soup.select("ul.pan-links > li > a[data-link]")):
            href = str(anchor.get("href") or "").strip()
            if not self._resolver_query_valid(href, "redirect_to"):
                continue
            provider = self._provider_from_host(str(anchor.get("data-link") or ""))
            if not provider:
                continue
            label = self._clean_text(anchor.get("title") or anchor.get_text(" ", strip=True))
            if not self._matches_title(label, aliases):
                continue
            grouped.setdefault(provider, []).append(
                {
                    "provider": provider,
                    "label": label,
                    "resolver_url": self._canonical_resolver_url(urljoin(page_url, href)),
                    "size": self._size_bytes(label),
                    "index": index,
                    "created": "",
                    "first": "p-first" in (anchor.get("class") or []),
                }
            )
        result = []
        for provider, items in grouped.items():
            items.sort(key=self._resource_rank, reverse=True)
            result.extend(items[: self.max_pan_per_provider])
        return result

    def _build_resource_groups(self, resources, page_url):
        by_provider = {}
        seen = set()
        for item in resources:
            resolver_url = self._strip_fragment(item.get("resolver_url"))
            if resolver_url in seen:
                continue
            seen.add(resolver_url)
            item["resolver_url"] = resolver_url
            by_provider.setdefault(item["provider"], []).append(item)
        labels = dict(self.PROVIDERS)
        groups = []
        for provider, label in self.PROVIDERS:
            items = by_provider.get(provider) or []
            if items:
                groups.append({"name": label, "resources": items})
        for provider, items in by_provider.items():
            if provider not in labels and items:
                groups.append({"name": provider, "resources": items})
        return groups

    def _resolve_resource(self, resolver_url):
        resolver_url = self._canonical_resolver_url(resolver_url)
        cached = self._resolved_cache.get(resolver_url)
        if cached:
            return cached
        if not self._is_resolver_url(resolver_url):
            raise ValueError("解析入口不属于当前站点")
        context = self._resource_context.get(resolver_url) or {}
        original_referer = str(context.get("referer") or self.active_origin).strip()
        expected = str(context.get("provider") or "")
        last_error = None
        for candidate in self._resolver_failover_urls(resolver_url):
            headers = dict(self.headers)
            referer = self._replace_content_origin(original_referer, self._origin(candidate))
            if referer:
                headers["Referer"] = referer
            try:
                response = self.session.get(
                    candidate,
                    headers=headers,
                    timeout=self.timeout,
                    allow_redirects=False,
                )
                if 300 <= response.status_code < 400:
                    location = urljoin(candidate, response.headers.get("Location") or "")
                    if self._valid_magnet(location) or self._valid_share_url(location):
                        final_url = location
                    else:
                        raise ValueError("解析页跳转目标不受支持")
                else:
                    response.raise_for_status()
                    response.encoding = response.apparent_encoding or response.encoding or "utf-8"
                    final_url = self._extract_final_resource(response.text, response.url)
                actual = "magnet" if self._valid_magnet(final_url) else self._valid_share_url(final_url)
                if not actual:
                    raise ValueError("解析页未返回合法磁力或网盘地址")
                if expected and expected != actual:
                    raise ValueError("资源类型漂移: {} -> {}".format(expected, actual))
                self.active_origin = self._origin(candidate)
                self._cache_resolved(resolver_url, final_url)
                return final_url
            except Exception as exc:
                last_error = exc
        raise ValueError("所有资源解析入口均不可用: {}".format(last_error or "unknown"))

    def _resolver_failover_urls(self, resolver_url):
        parsed = urlsplit(str(resolver_url or ""))
        origins = [self._origin(resolver_url), self.active_origin]
        origins.extend(self.hosts)
        result = []
        for origin in origins:
            origin_parts = urlsplit(str(origin or ""))
            if not self._content_host_allowed(origin_parts.hostname or ""):
                continue
            candidate = urlunsplit(
                (origin_parts.scheme, origin_parts.netloc, parsed.path, parsed.query, "")
            )
            if self._is_resolver_url(candidate) and candidate not in result:
                result.append(candidate)
        return result

    def _replace_content_origin(self, value, origin):
        parsed = urlsplit(str(value or ""))
        origin_parts = urlsplit(str(origin or ""))
        if not parsed.scheme or not parsed.netloc:
            return str(value or "")
        if not self._content_host_allowed(parsed.hostname or ""):
            return str(value or "")
        if not self._content_host_allowed(origin_parts.hostname or ""):
            return str(value or "")
        return urlunsplit(
            (origin_parts.scheme, origin_parts.netloc, parsed.path, parsed.query, "")
        )

    def _extract_final_resource(self, body, page_url=""):
        text = html_lib.unescape(str(body or ""))
        match = self.MAGNET_RE.search(text)
        if match:
            magnet = match.group(0).rstrip(".,;)")
            if self._valid_magnet(magnet):
                return magnet

        for match in re.finditer(
            r"(?:const|let|var)\s+data\s*=\s*([\"'])([^\"']+)\1", text, re.I
        ):
            decoded = self._decode_base64_text(match.group(2))
            if self._valid_magnet(decoded):
                return decoded

        soup = BeautifulSoup(text, "html.parser")
        direct = soup.select_one("a.direct-pan[href]")
        candidates = []
        if direct is not None:
            candidates.append(str(direct.get("href") or ""))
        for match in re.finditer(
            r"(?:var|let|const)\s+panLink\s*=\s*([\"'])(.*?)\1\s*;", text, re.I | re.S
        ):
            candidates.append(match.group(2))

        stripped = text.lstrip()
        if stripped.startswith("{"):
            try:
                payload = json.loads(stripped)
            except Exception:
                payload = None
            if isinstance(payload, dict):
                for key in ("url", "link", "panLink", "data"):
                    value = payload.get(key)
                    if isinstance(value, str):
                        candidates.append(value)

        candidates.extend(
            match.group(0)
            for match in re.finditer(r"https://[^\s\"'<>]+", text, re.I)
        )
        for candidate in candidates:
            normalized = self._normalize_share_url(candidate, page_url)
            if normalized:
                return normalized
        raise ValueError("解析页没有最终资源地址")

    def _normalize_share_url(self, value, page_url=""):
        text = html_lib.unescape(str(value or "")).strip()
        markdown = re.match(r"^\[[^\]]+\]\((https://[^)]+)\)$", text)
        if markdown:
            text = markdown.group(1)
        text = text.strip("\"'<> ")
        if text.startswith("/") and page_url:
            text = urljoin(page_url, text)
        if not self._valid_share_url(text):
            return ""
        parsed = urlsplit(text)
        if parsed.scheme.lower() != "https":
            return ""
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parsed.query, ""))

    def _resolver_query_valid(self, href, key):
        parsed = urlsplit(str(href or ""))
        if parsed.path.rstrip("/") != "/link_start":
            return False
        value = (parse_qs(parsed.query).get(key) or [""])[0]
        if key == "seed_id":
            return value.isdigit()
        return bool(re.fullmatch(r"pan_id_\d+", value))

    def _is_resolver_url(self, value):
        parsed = urlsplit(str(value or ""))
        if parsed.scheme.lower() != "https" or parsed.path.rstrip("/") != "/link_start":
            return False
        if not self._content_host_allowed(parsed.hostname or ""):
            return False
        query = parse_qs(parsed.query)
        seed_id = (query.get("seed_id") or [""])[0]
        pan_id = (query.get("redirect_to") or [""])[0]
        return seed_id.isdigit() or bool(re.fullmatch(r"pan_id_\d+", pan_id))

    def _valid_magnet(self, value):
        text = str(value or "").strip()
        match = re.match(r"^magnet:\?xt=urn:btih:([A-Za-z0-9]{32,40})(?:&|$)", text, re.I)
        if not match:
            return False
        btih = match.group(1)
        return bool(re.fullmatch(r"[A-Fa-f0-9]{40}|[A-Za-z2-7]{32}", btih))

    def _provider_from_url(self, value):
        parsed = urlsplit(str(value or ""))
        if parsed.scheme.lower() != "https":
            return ""
        return self._provider_from_host(parsed.hostname or "")

    def _valid_share_url(self, value):
        text = str(value or "").strip()
        provider = self._provider_from_url(text)
        if not provider:
            return ""
        parsed = urlsplit(text)
        path = parsed.path or "/"
        query = parse_qs(parsed.query)
        valid = {
            "baidu": path.startswith("/s/") or (
                path in ("/share/init", "/wap/init") and bool(query.get("surl"))
            ),
            "quark": path.startswith("/s/"),
            "xunlei": path.startswith("/s/"),
            "uc": path.startswith("/s/"),
            "ali": path.startswith("/s/"),
            "115": path.startswith("/s/"),
            "123": path.startswith("/s/") or path.startswith("/123pan/"),
            "189": path.startswith("/t/") or (
                path == "/web/share" and bool(query.get("code"))
            ),
            "139": path.startswith("/w/i/")
            or path.startswith("/m/i")
            or path.startswith("/shareweb/"),
            "pikpak": path.startswith("/s/"),
            "guangya": path.startswith("/s/"),
        }.get(provider, False)
        return provider if valid else ""

    def _provider_from_host(self, host):
        value = str(host or "").strip().lower().rstrip(".")
        for provider, domains in self.PROVIDER_HOSTS:
            for domain in domains:
                if value == domain or value.endswith("." + domain):
                    return provider
        return ""

    def _resource_rank(self, item):
        label = str(item.get("label") or "")
        lower = label.lower()
        subtitle = 1 if any(marker.lower() in lower for marker in self.SUBTITLE_MARKERS) else 0
        quality = sum(1 for marker in self.VIDEO_MARKERS if marker.lower() in lower)
        first = 1 if item.get("first") else 0
        index = int(item.get("index") or 0)
        return first, subtitle, quality, int(item.get("size") or 0), -index

    def _matches_title(self, label, aliases):
        normalized = self._normalize_title(label)
        useful = [item for item in aliases if len(item) >= 2]
        if not useful:
            return True
        return any(item in normalized for item in useful)

    def _title_aliases(self, title):
        value = self._clean_text(title)
        aliases = []
        chinese = "".join(re.findall(r"[\u3400-\u9fff]+", value))
        if chinese:
            aliases.append(self._normalize_title(chinese))
        latin = " ".join(re.findall(r"[A-Za-z]{3,}", value))
        if latin:
            aliases.append(self._normalize_title(latin))
            aliases.extend(self._normalize_title(item) for item in latin.split() if len(item) >= 4)
        return list(dict.fromkeys(item for item in aliases if item))

    def _size_bytes(self, text):
        values = []
        for number, unit in re.findall(r"(?i)(\d+(?:\.\d+)?)\s*(TB|GB|G|MB|M|KB|K)\b", str(text or "")):
            scale = {
                "K": 1024,
                "KB": 1024,
                "M": 1024 ** 2,
                "MB": 1024 ** 2,
                "G": 1024 ** 3,
                "GB": 1024 ** 3,
                "TB": 1024 ** 4,
            }[unit.upper()]
            values.append(int(float(number) * scale))
        return max(values) if values else 0

    def _parse_pagecount(self, html_text, current_page):
        soup = BeautifulSoup(html_text or "", "html.parser")
        pages = [current_page]
        for anchor in soup.select("div.page-nav a[href]"):
            value = (parse_qs(urlsplit(anchor.get("href") or "").query).get("page") or [""])[0]
            if str(value).isdigit():
                pages.append(int(value))
        next_anchor = soup.select_one("div.page-nav span.next > a[href]")
        if next_anchor is not None:
            pages.append(current_page + 1)
        return max(pages)

    def _parse_extend(self, extend):
        if isinstance(extend, dict):
            return dict(extend)
        raw = str(extend or "").strip()
        if not raw:
            return {}
        if raw.startswith("http://") or raw.startswith("https://"):
            return {"host": raw}
        for loader in (json.loads, ast.literal_eval):
            try:
                value = loader(raw)
            except Exception:
                continue
            if isinstance(value, dict):
                data = value.get("data")
                if isinstance(data, dict):
                    merged = dict(data)
                    merged.update({key: item for key, item in value.items() if key != "data"})
                    return merged
                return value
        return {}

    def _parse_extend_map(self, extend):
        if isinstance(extend, dict):
            return dict(extend)
        raw = str(extend or "").strip()
        if not raw:
            return {}
        try:
            value = json.loads(raw)
        except Exception:
            try:
                value = ast.literal_eval(raw)
            except Exception:
                return {}
        return value if isinstance(value, dict) else {}

    def _valid_content_hosts(self, hosts):
        result = []
        for item in hosts:
            parsed = urlsplit(str(item or "").strip())
            if parsed.scheme.lower() != "https" or not self._content_host_allowed(parsed.hostname or ""):
                continue
            origin = self._origin(item)
            if origin and origin not in result:
                result.append(origin)
        return result or list(self.DEFAULT_HOSTS)

    def _content_url_allowed(self, value):
        return self._content_host_allowed(urlsplit(str(value or "")).hostname or "")

    def _content_host_allowed(self, host):
        value = str(host or "").lower().rstrip(".")
        allowed = {urlsplit(item).hostname for item in self.DEFAULT_HOSTS}
        return value in allowed

    def _origin(self, value):
        parsed = urlsplit(str(value or ""))
        if not parsed.scheme or not parsed.netloc:
            return ""
        return "{}://{}".format(parsed.scheme.lower(), parsed.netloc.lower())

    def _movie_id(self, value):
        text = str(value or "").strip()
        if text.startswith(self.ATVP_DETAIL_PREFIX):
            text = text[len(self.ATVP_DETAIL_PREFIX) :]
        if text.isdigit():
            return text
        match = self.MOVIE_ID_RE.search(text)
        return match.group(1) if match else ""

    def _safe_label(self, value):
        text = self._clean_text(value).replace("#", "＃").replace("$", "＄")
        return text[:140] or "资源"

    def _summary_remark(self, summary):
        parts = [self._clean_text(item) for item in str(summary or "").split("/")]
        return " / ".join(item for item in parts[:3] if item)

    def _first_year(self, value):
        match = re.search(r"(?:19|20)\d{2}", str(value or ""))
        return match.group(0) if match else ""

    def _clean_heading(self, value):
        return re.sub(r"^#\s*", "", self._clean_text(value))

    def _clean_text(self, value):
        return re.sub(r"\s+", " ", html_lib.unescape(str(value or ""))).strip()

    def _normalize_title(self, value):
        return re.sub(r"[^a-z0-9\u3400-\u9fff]+", "", str(value or "").lower())

    def _strip_fragment(self, value):
        parsed = urlsplit(str(value or ""))
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parsed.query, ""))

    def _canonical_resolver_url(self, value):
        parsed = urlsplit(str(value or ""))
        query = urlencode(parse_qsl(parsed.query, keep_blank_values=True))
        return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path, query, ""))

    def _decode_base64_text(self, value):
        raw = str(value or "").strip()
        raw += "=" * (-len(raw) % 4)
        for decoder in (base64.b64decode, base64.urlsafe_b64decode):
            try:
                return decoder(raw.encode("ascii")).decode("utf-8").strip()
            except Exception:
                continue
        return ""

    def _cache_resolved(self, key, value):
        if len(self._resolved_cache) >= 256:
            first_key = next(iter(self._resolved_cache))
            self._resolved_cache.pop(first_key, None)
        self._resolved_cache[key] = value

    def _bounded_int(self, value, default, minimum, maximum):
        try:
            result = int(value)
        except (TypeError, ValueError):
            result = int(default)
        return max(minimum, min(maximum, result))

    def _empty_page(self, page):
        return {"list": [], "page": page, "pagecount": page, "limit": 0, "total": 0}

    def _error_detail(self, movie_id, message):
        text = self._safe_label(message or "详情加载失败")
        return {
            "vod_id": movie_id,
            "vod_name": "SeedHub 加载失败",
            "vod_pic": "",
            "vod_remarks": text,
            "vod_content": text,
            "vod_play_from": "错误",
            "vod_play_url": "查看错误$seedhub-error://detail",
        }

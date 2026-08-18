import base64
import json
import re
import unicodedata
from dataclasses import replace
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple
from urllib.parse import parse_qs, quote, unquote, urlsplit

from .resource_models import EpisodeRange, MediaIdentity, PlaySource, ResourceCandidate
from .resource_schema import (
    GENERIC_ROW_SCHEMA,
    LINK_KEYS,
    RESOURCE_MODES,
    SUPPLEMENT_MODES,
    SUPPLEMENT_ROW_SCHEMA,
    classify_resource_row,
    generic_rows,
    supplement_streams,
)


TITLE_KEYS = ("vod_name", "name", "title", "vod_title", "show_name", "work_title", "note", "content")
TIMESTAMP_KEYS = ("datetime", "vod_time", "timestamp", "created_at", "updated_at", "create_time", "update_time")

PROVIDER_ALIASES = {
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

PROVIDER_RULES = (
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
    ("mobile", ("caiyun.139.com", "yun.139.com", "caiyun.feixin.10086.cn"),
     ("移动网盘", "移动云盘", "移动分享")),
    ("guangya", ("guangyapan.com",), ("光鸭网盘", "光鸭云盘", "光鸭分享")),
)

PASSWORD_KEYS = ("pwd", "password", "passcode", "pass_code", "share_pwd")


def _shadow_mode(value: Any) -> str:
    mode = str(value or "").strip().lower()
    if mode not in RESOURCE_MODES:
        raise ValueError("unsupported resource mode: %s" % mode)
    return mode


def _shadow_text(value: Any) -> str:
    if isinstance(value, (dict, list, tuple, set)):
        return ""
    return str(value or "").strip()


def _shadow_first(row: Mapping[str, Any], keys: Iterable[str]) -> str:
    for key in keys:
        value = _shadow_text(row.get(key))
        if value:
            return value
    return ""


def _titles(row: Mapping[str, Any]) -> Tuple[str, ...]:
    values = []
    for key in TITLE_KEYS:
        value = _shadow_text(row.get(key))
        if value and value not in values:
            values.append(value)
    return tuple(values)


def _provider(*values: Any) -> str:
    resolved = set()
    for raw in values:
        value = _shadow_text(raw)
        if not value:
            continue
        normalized = unicodedata.normalize("NFKC", unquote(value)).casefold()
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
                try:
                    host = (urlsplit(candidate if "://" in candidate else "https:" + candidate).hostname or "").rstrip(".")
                except ValueError:
                    host = ""
                if host:
                    hosts.add(host)
            matches.update(
                provider for provider, domains, _labels in PROVIDER_RULES
                if any(host == domain or host.endswith("." + domain) for host in hosts for domain in domains)
            )
        else:
            matches.update(
                provider for provider, domains, labels in PROVIDER_RULES
                if any(label in normalized for label in labels)
                or any(re.search(r"(?<![a-z0-9.-])%s(?=$|[/:?#])" % re.escape(domain), normalized)
                       for domain in domains)
            )
            exact = PROVIDER_ALIASES.get(re.sub(r"[\s._-]+", "", normalized))
            if exact:
                matches.add(exact)
        if len(matches) > 1:
            return ""
        resolved.update(matches)
        if len(resolved) > 1:
            return ""
    return next(iter(resolved)) if resolved else ""


def _password(*rows: Mapping[str, Any]) -> str:
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        for key in PASSWORD_KEYS + ("提取码", "访问码", "密码"):
            value = _shadow_text(row.get(key))
            if value and len(value) <= 64:
                return value
    return ""


def _url_has_password(value: str) -> bool:
    try:
        parsed = urlsplit(unquote(value))
    except ValueError:
        return False
    for part in parsed.query.split("&") if parsed.query else ():
        key, separator, raw_value = part.partition("=")
        if separator and unquote(key).strip().casefold() in PASSWORD_KEYS and 0 < len(unquote(raw_value).strip()) <= 64:
            return True
    fragment = unquote(parsed.fragment).strip()
    return bool(
        re.match(r"(?i)^(?:password|pwd|passcode|pass_code|share_pwd|提取码|访问码|密码)\s*[:：=]\s*.+$", fragment)
        or re.fullmatch(r"[A-Za-z0-9_-]{1,64}", fragment)
    )


def _with_password(value: str, password: str) -> str:
    if not value or not password or _url_has_password(value):
        return value
    decoded = unquote(value).strip()
    if not re.match(r"^https?://", decoded, re.I):
        return value
    separator = "&" if "?" in decoded.split("#", 1)[0] else "?"
    base, marker, fragment = decoded.partition("#")
    protected = "%s%spassword=%s" % (base, separator, quote(password, safe=""))
    if marker:
        protected += "#" + fragment
    return quote(protected, safe="") if value != decoded else protected


def _url_identity(value: str) -> str:
    decoded = unquote(value).strip().rstrip("，。；;、")
    lowered = decoded.casefold()
    if lowered.startswith("magnet:"):
        try:
            for xt in parse_qs(urlsplit(decoded).query).get("xt", ()):
                match = re.match(r"(?i)^urn:btih:([a-z2-7]{32}|[a-f0-9]{40})$", str(xt or ""))
                if not match:
                    continue
                btih = match.group(1)
                if len(btih) == 32:
                    try:
                        raw_hash = base64.b32decode(btih.upper(), casefold=True)
                        if len(raw_hash) == 20:
                            btih = raw_hash.hex()
                    except (ValueError, TypeError):
                        pass
                return "magnet:btih:" + btih.casefold()
        except ValueError:
            pass
        return "magnet:" + decoded[len("magnet:"):].casefold()
    if lowered.startswith("ed2k:"):
        hashes = re.findall(r"(?i)\|([a-f0-9]{32})\|", decoded)
        return "ed2k:hash:" + hashes[-1].casefold() if hashes else "ed2k:" + decoded[len("ed2k:"):].casefold()
    try:
        parsed = urlsplit(decoded)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            return decoded
        host = parsed.hostname.casefold()
        if ":" in host and not host.startswith("["):
            host = "[" + host + "]"
        port = parsed.port
        if port is not None and not (parsed.scheme == "http" and port == 80 or parsed.scheme == "https" and port == 443):
            host += ":%s" % port
        path = re.sub(r"(?i)(?:提取码|访问码|密码)\s*[:：=]\s*[a-z0-9]{1,64}$", "", parsed.path).rstrip("/") or "/"
        query_parts = []
        for part in parsed.query.split("&") if parsed.query else ():
            key = unquote(part.split("=", 1)[0]).strip().casefold()
            if key in PASSWORD_KEYS or re.match(r"(?i)^(?:提取码|访问码|密码)\s*[:：=]", unquote(part)):
                continue
            query_parts.append(part)
        fragment = parsed.fragment
        decoded_fragment = unquote(fragment).strip()
        if (re.match(r"(?i)^(?:password|pwd|passcode|pass_code|share_pwd|提取码|访问码|密码)\s*[:：=]", decoded_fragment)
                or re.fullmatch(r"[A-Za-z0-9_-]{1,64}", decoded_fragment)):
            fragment = ""
        query = "&".join(sorted(query_parts))
        return "%s%s%s%s" % (host, path, "?" + query if query else "", "#" + fragment if fragment else "")
    except ValueError:
        return decoded


def _identity(value: str, mode: str) -> str:
    decoded = unquote(value).strip()
    if decoded.startswith("push://"):
        decoded = decoded[7:].strip()
    if re.match(r"^(?:https?://|magnet:|ed2k:)", decoded, re.I):
        identity = _url_identity(decoded)
        return "url:" + identity if identity else ""
    return "id:%s:%s" % (mode, value)


def _candidate(mode: str, row: Mapping[str, Any], parent: Mapping[str, Any] = None, provider_hint: str = "") -> ResourceCandidate:
    parent = parent or {}
    resource_id = _with_password(_shadow_first(row, ("vod_id", "id")), _password(row, parent))
    titles = _titles(row)
    parent_titles = _titles(parent)
    work_title = _shadow_text(row.get("work_title")) or _shadow_first(parent, ("work_title", "title", "vod_name", "name"))
    if not work_title:
        work_title = titles[0] if titles else (parent_titles[0] if parent_titles else "")
    provider = _provider(
        row.get("provider"), row.get("type"), row.get("type_name"), row.get("vod_remarks"),
        row.get("source"), provider_hint, resource_id,
    )
    return ResourceCandidate(
        resource_id=resource_id,
        mode=mode,
        provider=provider,
        work_title=work_title,
        titles=titles + parent_titles,
        year=_shadow_first(row, ("vod_year", "year")) or _shadow_first(parent, ("vod_year", "year")),
        source=_shadow_first(row, ("source", "channel")) or _shadow_first(parent, ("source", "channel")),
        timestamp=_shadow_first(row, TIMESTAMP_KEYS) or _shadow_first(parent, TIMESTAMP_KEYS),
    )


def _supplement_candidate(
        mode: str, row: Mapping[str, Any], parent: Mapping[str, Any] = None,
        provider_hint: str = "") -> ResourceCandidate:
    parent = parent or {}
    resource_id = _with_password(_shadow_first(row, LINK_KEYS), _password(row, parent))
    title_values = (
        _shadow_text(row.get("work_title")), _shadow_text(row.get("note")),
        _shadow_text(parent.get("work_title")), _shadow_text(parent.get("title")),
        _shadow_first(parent, ("vod_name", "name")), _shadow_text(parent.get("note")),
        _shadow_text(parent.get("content")),
    )
    work_title = next((value for value in title_values if value), "")
    provider = _provider(row.get("type"), row.get("provider"), provider_hint, resource_id)
    return ResourceCandidate(
        resource_id=resource_id if work_title else "",
        mode=mode,
        provider=provider,
        work_title=work_title,
        titles=title_values,
        source=_shadow_first(row, ("source",)) or _shadow_first(parent, ("source", "channel")),
        timestamp=_shadow_text(row.get("datetime")) or _shadow_first(parent, ("datetime", "vod_time")),
    )


def map_media_identity(raw_id: Any, base_vod: Mapping[str, Any], follow_item: Mapping[str, Any]) -> MediaIdentity:
    base_vod = base_vod or {}
    follow_item = follow_item or {}
    aliases = next(
        (follow_item.get(key) for key in ("title_aliases", "titleAliases") if follow_item.get(key) not in (None, "")),
        None,
    )
    if aliases in (None, ""):
        aliases = next(
            (base_vod.get(key) for key in ("title_aliases", "titleAliases") if base_vod.get(key) not in (None, "")),
            (),
        )
    alias_values: Any = aliases
    if isinstance(aliases, str):
        try:
            alias_values = json.loads(aliases)
        except (TypeError, ValueError):
            alias_values = ()
    if not isinstance(alias_values, (list, tuple)):
        alias_values = ()
    source_id = _shadow_first(follow_item, ("source_id", "sourceId")) or _shadow_first(base_vod, ("source_id", "sourceId")) or _shadow_text(raw_id)
    media_type = _shadow_first(follow_item, ("media_type", "mediaType")) or _shadow_first(base_vod, ("media_type", "mediaType")) or "movie"
    tmdb_value = _shadow_first(follow_item, ("tmdb_id", "tmdbId")) or _shadow_first(base_vod, ("tmdb_id", "tmdbId"))
    try:
        tmdb_id = max(0, int(tmdb_value))
    except (TypeError, ValueError):
        tmdb_id = 0
    title = _shadow_text(follow_item.get("title")) or _shadow_first(base_vod, ("vod_name", "title"))
    original_title = _shadow_first(follow_item, ("original_title", "originalTitle")) or _shadow_text(base_vod.get("original_title"))
    year = _shadow_text(follow_item.get("year")) or _shadow_first(base_vod, ("vod_year", "year"))
    return MediaIdentity(
        source_id=source_id,
        media_type=media_type,
        tmdb_id=tmdb_id,
        title=title,
        original_title=original_title,
        title_aliases=alias_values,
        year=year,
    )


def map_resource_payload(mode: Any, payload: Any) -> Tuple[ResourceCandidate, ...]:
    normalized_mode = _shadow_mode(mode)
    if normalized_mode not in SUPPLEMENT_MODES:
        return tuple(
            candidate for row in generic_rows(payload)
            if GENERIC_ROW_SCHEMA in classify_resource_row(normalized_mode, row)
            for candidate in (_candidate(normalized_mode, row),)
            if candidate.resource_id
        )
    output = []
    positions = {}
    streams = [[links, 0, parent, hint] for links, parent, hint in supplement_streams(payload)]
    while streams:
        active = []
        for links, index, parent, hint in streams:
            if index >= len(links):
                continue
            row = links[index]
            if SUPPLEMENT_ROW_SCHEMA in classify_resource_row(normalized_mode, row):
                candidate = _supplement_candidate(normalized_mode, row, parent, hint)
                identity = _identity(candidate.resource_id, normalized_mode) if candidate.resource_id else ""
                if identity and candidate.provider:
                    if identity not in positions:
                        positions[identity] = len(output)
                        output.append(candidate)
                    elif _url_has_password(candidate.resource_id) and not _url_has_password(output[positions[identity]].resource_id):
                        output[positions[identity]] = replace(output[positions[identity]], resource_id=candidate.resource_id)
            if index + 1 < len(links):
                active.append([links, index + 1, parent, hint])
        streams = active
    for row in generic_rows(payload):
        row_schemas = classify_resource_row(normalized_mode, row)
        explicit_id = GENERIC_ROW_SCHEMA in row_schemas
        candidate = (
            _candidate(normalized_mode, row)
            if explicit_id
            else _supplement_candidate(normalized_mode, row)
        )
        identity = _identity(candidate.resource_id, normalized_mode) if candidate.resource_id else ""
        if identity and (explicit_id or SUPPLEMENT_ROW_SCHEMA in row_schemas and candidate.provider):
            if identity not in positions:
                positions[identity] = len(output)
                output.append(candidate)
            elif _url_has_password(candidate.resource_id) and not _url_has_password(output[positions[identity]].resource_id):
                output[positions[identity]] = replace(output[positions[identity]], resource_id=candidate.resource_id)
    return tuple(output)


def _episode(label: str, index: int, default_season: int) -> EpisodeRange:
    match = re.search(r"(?i)S\s*0*(\d{1,2})\s*E(?:P)?\s*0*(\d{1,3})", label)
    if match:
        return EpisodeRange(int(match.group(1)), int(match.group(2)), int(match.group(2)), True)
    match = re.search(r"第\s*(\d{1,2})\s*季.*?第\s*(\d{1,3})\s*[集话]", label)
    if match:
        return EpisodeRange(int(match.group(1)), int(match.group(2)), int(match.group(2)), True)
    match = re.search(r"(?i)\bSeason\s*0*(\d{1,2}).*?\b(?:Episode|EP?|E)\s*0*(\d{1,3})\b", label)
    if match:
        return EpisodeRange(int(match.group(1)), int(match.group(2)), int(match.group(2)), True)
    match = re.search(r"(?i)\bEP?\s*0*(\d{1,3})\b", label)
    if match:
        episode = int(match.group(1))
        return EpisodeRange(default_season or 1, episode, episode, True)
    match = re.search(r"(?i)(?:第\s*)?(\d{1,3})\s*(?:集|话|ep)\b", label)
    if match:
        episode = int(match.group(1))
        return EpisodeRange(default_season or 1, episode, episode, True)
    if re.match(r"^\s*\d+(?:\.\d+)?\s*(?:K|M|G|T)i?B\b", label, re.I):
        return EpisodeRange(default_season or 1, index, index, False)
    match = re.match(r"^\s*0*(\d{1,3})\s*$", label)
    if match:
        episode = int(match.group(1))
        return EpisodeRange(default_season or 1, episode, episode, True)
    match = re.match(r"^\s*0*(\d{1,3})(?=\s*[.\-_\[(])", label)
    if match:
        episode = int(match.group(1))
        suffix = label[match.end():]
        common_resolutions = {144, 240, 360, 480, 540, 576, 720}
        bracketed_size = bool(re.match(r"^\s*\(", suffix))
        immediate_size_unit = re.match(r"^\s*[.\-_\[(]*\s*(?:K|M|G|T)?i?B\b", suffix, re.I)
        if (episode not in common_resolutions or bracketed_size) and not immediate_size_unit:
            return EpisodeRange(default_season or 1, episode, episode, True)
    return EpisodeRange(default_season or 1, index, index, False)


def map_detail_play_sources(mode: Any, resource_id: Any, vod: Mapping[str, Any]) -> Tuple[PlaySource, ...]:
    normalized_mode = _shadow_mode(mode)
    sources = str(vod.get("vod_play_from") or "").split("$$$")
    groups = str(vod.get("vod_play_url") or "").split("$$$")
    seasons = vod.get("group_seasons") if isinstance(vod.get("group_seasons"), list) else []
    providers = vod.get("group_providers") if isinstance(vod.get("group_providers"), list) else []
    output = []
    for group_index, group in enumerate(groups):
        season = int(seasons[group_index]) if group_index < len(seasons) and str(seasons[group_index]).isdigit() and int(seasons[group_index]) > 0 else 1
        provider_hint = providers[group_index] if group_index < len(providers) else ""
        provider = _provider(provider_hint, sources[group_index] if group_index < len(sources) else "", resource_id)
        for episode_index, part in enumerate(group.split("#"), 1):
            label, separator, target = part.rpartition("$")
            if not separator or not target:
                continue
            output.append(PlaySource(
                target=target.strip(),
                label=label.strip(),
                resource_id=_shadow_text(resource_id),
                mode=normalized_mode,
                provider=provider,
                episode=_episode(label, episode_index, season),
            ))
    return tuple(output)


def build_shadow_snapshot(
        raw_id: Any, base_vod: Mapping[str, Any], follow_item: Mapping[str, Any],
        payloads: Mapping[str, Any], details: Mapping[str, Sequence[Mapping[str, Any]]]) -> Dict[str, Any]:
    identity = map_media_identity(raw_id, base_vod, follow_item)
    candidates = []
    play_sources = []
    for mode in RESOURCE_MODES:
        for candidate in map_resource_payload(mode, payloads.get(mode, {})):
            candidates.append(candidate.to_dict())
        for vod in details.get(mode, ()):
            resource_id = _shadow_first(vod, ("resource_id", "vod_id", "id"))
            play_sources.extend(source.to_dict() for source in map_detail_play_sources(mode, resource_id, vod))
    return {
        "identity": identity.to_dict(),
        "candidates": candidates,
        "play_sources": play_sources,
    }

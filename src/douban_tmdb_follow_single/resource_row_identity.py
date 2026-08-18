import base64
import re
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse


_ROW_ID_KEYS = ("vod_id", "id", "url", "link", "share_url", "target")
_PASSWORD_QUERY_KEYS = ("pwd", "password", "passcode", "pass_code", "share_pwd")


def _unquote_limited(value: Any) -> str:
    current = str(value or "")
    rounds = min(512, max(32, len(current) + 1))
    for _index in range(rounds):
        decoded = unquote(current)
        if decoded == current:
            break
        current = decoded
    return current


def _resource_url_identity(raw_url: Any) -> str:
    value = unquote(str(raw_url or "")).strip().rstrip("，。；;、")
    if not value:
        return ""
    lowered = value.casefold()
    if lowered.startswith("magnet:"):
        try:
            for xt in parse_qs(urlparse(value).query).get("xt", []):
                match = re.match(
                    r"(?i)^urn:btih:([a-z2-7]{32}|[a-f0-9]{40})$",
                    str(xt or ""),
                )
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
            r"(?i)(?:提取码|访问码|密码)\s*[:：=]\s*[a-z0-9]{1,64}$",
            "", parsed.path,
        ).rstrip("/") or "/"
        query_parts = []
        for part in parsed.query.split("&") if parsed.query else []:
            key = unquote(part.split("=", 1)[0]).strip().casefold()
            if key in _PASSWORD_QUERY_KEYS:
                continue
            if re.match(r"(?i)^(?:提取码|访问码|密码)\s*[:：=]", unquote(part)):
                continue
            query_parts.append(part)
        query = "&".join(sorted(query_parts))
        fragment = parsed.fragment
        decoded_fragment = unquote(fragment).strip()
        if re.match(
                r"(?i)^(?:password|pwd|passcode|pass_code|share_pwd|提取码|访问码|密码)\s*[:：=]",
                decoded_fragment,
        ) or re.fullmatch(r"[A-Za-z0-9_-]{1,64}", decoded_fragment):
            fragment = ""
        return "%s%s%s%s" % (
            host, path,
            "?" + query if query else "",
            "#" + fragment if fragment else "",
        )
    except Exception:
        return value


def build_resource_row_identity(row_or_id: Any) -> str:
    """Build the frozen V70 identity for one resource row or raw resource ID."""
    mode = ""
    if isinstance(row_or_id, dict):
        mode = str(row_or_id.get("_resource_mode") or "").strip().lower()
        raw = next((
            str(row_or_id.get(key) or "").strip()
            for key in _ROW_ID_KEYS
            if str(row_or_id.get(key) or "").strip()
        ), "")
    else:
        raw = str(row_or_id or "").strip()
    if not raw:
        return ""
    decoded = _unquote_limited(raw).strip()
    if decoded.startswith("push://"):
        decoded = decoded[7:].strip()
    if re.match(r"^(?:https?://|magnet:|ed2k:)", decoded, re.I):
        identity = _resource_url_identity(decoded)
        return "url:" + identity if identity else ""
    return "id:%s:%s" % (mode or "unknown", raw)

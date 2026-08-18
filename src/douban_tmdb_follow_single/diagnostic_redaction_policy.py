"""Pure bounded redaction policy for V80 diagnostic text."""

import re as _v80_redaction_re
from types import MappingProxyType as _v80_redaction_mapping_proxy
from urllib.parse import quote as _v80_redaction_quote
from urllib.parse import quote_plus as _v80_redaction_quote_plus
from urllib.parse import unquote_plus as _v80_redaction_unquote_plus
from urllib.parse import urlsplit as _v80_redaction_urlsplit
from urllib.parse import urlunsplit as _v80_redaction_urlunsplit


V80_DIAGNOSTIC_REDACTION_LIMITS = _v80_redaction_mapping_proxy({
    "max_input_chars": 4096,
    "max_secrets": 32,
    "max_secret_chars": 4096,
})


_V80_REDACTION_MARKER = "***"
_V80_SECRET_NAME = (
    r"(?:authorization|proxy[-_ ]?authorization|cookie|set[-_ ]?cookie|"
    r"token|password|passwd|secret|credential(?:s)?|ck|"
    r"proxy[-_. ]?(?:user|username|password)|"
    r"(?:access|refresh|client|session|id|auth|api|tmdb|ws)[-_. ]?"
    r"(?:token|password|passwd|secret)|"
    r"(?:api|auth|private)[-_. ]?key)"
)
_V80_HEADER = _v80_redaction_re.compile(
    r"(?im)(\b(?:authorization|proxy-authorization|cookie|set-cookie)\b"
    r"\s*[:=]\s*)[^\r\n]+"
)
_V80_ASSIGNMENT = _v80_redaction_re.compile(
    r"(?i)(?P<prefix>(?<![A-Za-z0-9_])[\"']?" + _V80_SECRET_NAME
    + r"[\"']?\s*[:=]\s*)"
    r"(?P<value>\{[^\r\n]*\}|\[[^\r\n]*\]|\([^\r\n]*\)|"
    r"\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'|"
    r"(?:Bearer|Basic)\s+[^\s,;&\]\}\r\n\"']+|"
    r"[^\s,;&\]\}\r\n]+)"
)
_V80_PAIR = _v80_redaction_re.compile(
    r"(?i)(?P<prefix>[\(\[]\s*[\"']?" + _V80_SECRET_NAME
    + r"[\"']?\s*,\s*)"
    r"(?P<value>\{[^\r\n]*\}|\[[^\r\n]*\]|\([^\r\n]*\)|"
    r"\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'|"
    r"(?:Bearer|Basic)\s+[^\s,;&\]\}\r\n\"']+|"
    r"[^\s,;&\]\}\r\n]+)"
)
_V80_AUTH_SCHEME = _v80_redaction_re.compile(
    r"(?i)(\b(?:Bearer|Basic)\s+)[^\s,;&\]\}\r\n\"']+"
)
_V80_URL_USERINFO = _v80_redaction_re.compile(
    r"(?i)(\bhttps?://)[^/@\s<>\"']+@"
)
_V80_SIGNED_QUERY = _v80_redaction_re.compile(
    r"(?i)((?:&amp;|[?&])(?:token|auth|key|sign|sig|signature|auth[-_]?key|expires|"
    r"policy|key[-_]?pair[-_]?id|awsaccesskeyid|googleaccessid|"
    r"wssecret|hdnts|hdnea|x-amz-[a-z0-9-]+|"
    r"x-goog-[a-z0-9-]+|x-oss-[a-z0-9-]+|"
    r"x-bce-[a-z0-9-]+)=)[^&#\s<>\"']*"
)
_V80_PATH_TOKEN = _v80_redaction_re.compile(
    r"(?i)(/(?:play|parse|offline_download|p)/)[^/?#\s<>\"']+"
)
_V80_URL = _v80_redaction_re.compile(r"(?i)\bhttps?://[^\s<>\"']+")
_V80_PERCENT_TOKEN = _v80_redaction_re.compile(r"%(?:25)?[0-9A-Fa-f]{2}")
_V80_SENSITIVE_QUERY_KEYS = frozenset((
    "token", "auth", "key", "sign", "sig", "signature", "auth_key",
    "auth-key", "expires", "policy", "key_pair_id", "key-pair-id",
    "awsaccesskeyid", "googleaccessid", "wssecret", "hdnts", "hdnea",
))
_V80_SENSITIVE_QUERY_PREFIXES = ("x-amz-", "x-goog-", "x-oss-", "x-bce-")
_V80_PATH_ROUTES = frozenset(("play", "parse", "offline_download", "p"))
_V80_INTERNAL_MAX_OUTPUT_CHARS = 12000


def _v80_bounded_text(value, limit):
    try:
        text = value if type(value) is str else ("" if value is None else str(value))
    except Exception:
        text = "<unprintable>"
    return text[:limit]


def _v80_decoded_component(value):
    decoded = value
    for _index in range(2):
        next_value = _v80_redaction_unquote_plus(decoded)
        if next_value == decoded:
            break
        decoded = next_value
    return decoded.lower()


def _v80_sensitive_query_key(value):
    decoded = _v80_decoded_component(value)
    return (
        decoded in _V80_SENSITIVE_QUERY_KEYS
        or decoded.startswith(_V80_SENSITIVE_QUERY_PREFIXES)
    )


def _v80_redact_path(value, marker):
    parts = value.split("/")
    changed = False
    for index in range(len(parts) - 1):
        if _v80_decoded_component(parts[index]) in _V80_PATH_ROUTES and parts[index + 1]:
            parts[index + 1] = marker
            changed = True
    return "/".join(parts), changed


def _v80_redact_query(value, marker):
    parts = []
    changed = False
    for part in value.split("&"):
        key, separator, _item = part.partition("=")
        if separator and _v80_sensitive_query_key(key):
            part = key + separator + marker
            changed = True
        parts.append(part)
    return "&".join(parts), changed


def _v80_redact_malformed_url(value, marker):
    path, separator, tail = value.partition("?")
    query, fragment_separator, fragment = tail.partition("#")
    path, path_changed = _v80_redact_path(path, marker)
    query, query_changed = _v80_redact_query(query, marker)
    if not path_changed and not query_changed:
        return value
    return (
        path
        + (separator + query if separator else "")
        + (fragment_separator + fragment if fragment_separator else "")
    )


def _v80_redact_url(match, marker):
    value = match.group(0)
    try:
        parsed = _v80_redaction_urlsplit(value)
    except ValueError:
        return _v80_redact_malformed_url(value, marker)
    if parsed.scheme.lower() not in ("http", "https"):
        return value

    changed = False
    netloc = parsed.netloc
    if "@" in netloc:
        netloc = marker + "@" + netloc.rsplit("@", 1)[1]
        changed = True

    path, path_changed = _v80_redact_path(parsed.path, marker)
    query, query_changed = _v80_redact_query(parsed.query, marker)
    changed = changed or path_changed or query_changed

    if not changed:
        return value
    return _v80_redaction_urlunsplit((
        parsed.scheme, netloc, path, query, parsed.fragment,
    ))


def _v80_percent_case_pattern(value):
    parts = []
    offset = 0
    for match in _V80_PERCENT_TOKEN.finditer(value):
        parts.append(_v80_redaction_re.escape(value[offset:match.start()]))
        token = match.group(0)
        parts.append("".join(
            "[%s%s]" % (char.lower(), char.upper())
            if char.lower() in "abcdef" else _v80_redaction_re.escape(char)
            for char in token
        ))
        offset = match.end()
    parts.append(_v80_redaction_re.escape(value[offset:]))
    return _v80_redaction_re.compile("".join(parts))


def _v80_replace_secret(text, secret, marker):
    if _V80_PERCENT_TOKEN.search(secret) is None:
        return text.replace(secret, marker)
    return _v80_percent_case_pattern(secret).sub(marker, text)


def _v80_secret_variants(secrets):
    if type(secrets) is str:
        iterator = iter((secrets,))
    else:
        try:
            iterator = iter(secrets)
        except Exception:
            return ()

    max_secrets = V80_DIAGNOSTIC_REDACTION_LIMITS["max_secrets"]
    max_secret_chars = V80_DIAGNOSTIC_REDACTION_LIMITS["max_secret_chars"]
    variants = set()
    for _index in range(max_secrets):
        try:
            secret = next(iterator)
        except StopIteration:
            break
        except Exception:
            break
        if type(secret) is not str or not secret or len(secret) > max_secret_chars:
            continue
        encoded = {
            secret,
            _v80_redaction_quote(secret, safe=""),
            _v80_redaction_quote_plus(secret, safe=""),
        }
        double_encoded = {
            _v80_redaction_quote(item, safe="") for item in encoded
        }
        double_encoded.update(
            _v80_redaction_quote_plus(item, safe="") for item in encoded
        )
        encoded.update(double_encoded)
        variants.update(item for item in encoded if item)
    return tuple(sorted(variants, key=len, reverse=True))


def _v80_assignment_replacement(match, marker):
    value = match.group("value")
    if value[:1] in ("\"", "'") and value[-1:] == value[:1]:
        replacement = value[:1] + marker + value[:1]
    else:
        replacement = marker
    return match.group("prefix") + replacement


def _v80_redact_bounded(value, secrets, limit, marker):
    limit = min(max(int(limit), 1), _V80_INTERNAL_MAX_OUTPUT_CHARS)
    scan_limit = limit + V80_DIAGNOSTIC_REDACTION_LIMITS["max_secret_chars"] - 1
    text = _v80_bounded_text(value, scan_limit)
    variants = _v80_secret_variants(secrets)

    for secret in (item for item in variants if item in marker):
        text = _v80_replace_secret(text, secret, marker)[:scan_limit]
    text = _V80_URL.sub(lambda match: _v80_redact_url(match, marker), text)[:scan_limit]
    text = _V80_HEADER.sub(lambda match: match.group(1) + marker, text)[:scan_limit]
    text = _V80_PAIR.sub(
        lambda match: _v80_assignment_replacement(match, marker), text,
    )[:scan_limit]
    text = _V80_ASSIGNMENT.sub(
        lambda match: _v80_assignment_replacement(match, marker), text,
    )[:scan_limit]
    text = _V80_AUTH_SCHEME.sub(lambda match: match.group(1) + marker, text)[:scan_limit]
    text = _V80_URL_USERINFO.sub(
        lambda match: match.group(1) + marker + "@", text,
    )[:scan_limit]
    text = _V80_SIGNED_QUERY.sub(lambda match: match.group(1) + marker, text)[:scan_limit]
    text = _V80_PATH_TOKEN.sub(lambda match: match.group(1) + marker, text)[:scan_limit]
    for secret in (item for item in variants if item not in marker):
        text = _v80_replace_secret(text, secret, marker)[:scan_limit]
    return text[:limit]


def v80_redact_diagnostic_text(value, secrets=()):
    """Return bounded diagnostic text with credential material removed."""

    return _v80_redact_bounded(
        value,
        secrets,
        V80_DIAGNOSTIC_REDACTION_LIMITS["max_input_chars"],
        _V80_REDACTION_MARKER,
    )

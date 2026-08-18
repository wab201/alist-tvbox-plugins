"""Pure network-zone and redirect policy for isolated V80."""

import ipaddress as _v80_security_ipaddress
from types import MappingProxyType as _v80_security_mapping_proxy
from urllib.parse import urlparse as _v80_security_urlparse


V80_SECURITY_ZONES = frozenset((
    "trusted_backend", "configured_internal", "external_untrusted",
))
V80_SECURITY_REDIRECT_STATUSES = frozenset((301, 302, 303, 307, 308))
V80_SECURITY_LIMITS = _v80_security_mapping_proxy({
    "url_characters": 16 * 1024,
    "redirect_hops": 5,
    "route_probe_bytes": 4096,
    "resource_json_bytes": 2 * 1024 * 1024,
    "history_json_bytes": 4 * 1024 * 1024,
    "history_row_bytes": 128 * 1024,
    "history_config_bytes": 128 * 1024,
    "header_value_bytes": 16 * 1024,
    "cookie_bytes": 64 * 1024,
    "headers_total_bytes": 80 * 1024,
})
V80_SECURITY_SENSITIVE_HEADERS = frozenset((
    "authorization", "cookie", "origin", "proxy-authorization", "referer",
))
V80_SECURITY_CROSS_ORIGIN_HEADERS = frozenset((
    "accept", "accept-language", "range", "user-agent", "x-client",
))


_V80_SECURITY_HEADER_NAMES = _v80_security_mapping_proxy({
    "accept": "Accept",
    "accept-language": "Accept-Language",
    "authorization": "Authorization",
    "content-type": "Content-Type",
    "cookie": "Cookie",
    "idempotency-key": "Idempotency-Key",
    "origin": "Origin",
    "proxy-authorization": "Proxy-Authorization",
    "range": "Range",
    "referer": "Referer",
    "user-agent": "User-Agent",
    "x-client": "X-CLIENT",
    "x-playsync-latest": "X-PlaySync-Latest",
    "x-playsync-limit": "X-PlaySync-Limit",
    "x-playsync-since": "X-PlaySync-Since",
    "x-playsync-source-kind": "X-PlaySync-Source-Kind",
})
_V80_SECURITY_EXPLICIT_INTERNAL_NETWORKS = tuple(
    _v80_security_ipaddress.ip_network(value)
    for value in (
        "10.0.0.0/8", "127.0.0.0/8", "169.254.0.0/16", "172.16.0.0/12",
        "192.168.0.0/16", "::1/128", "fc00::/7", "fe80::/10",
    )
)


class V80SecurityPolicyError(ValueError):
    """Stable configuration/input error without retaining the rejected value."""

    __slots__ = ("reason",)

    def __init__(self, reason):
        reason = str(reason or "invalid_security_input")
        self.reason = reason
        super().__init__("security policy rejected input: %s" % reason)


class V80SecurityTarget(object):
    """Canonical HTTP target identity without path, query, or credentials."""

    __slots__ = ("scheme", "host", "port", "origin")

    def __init__(self, scheme, host, port):
        self.scheme = scheme
        self.host = host
        self.port = int(port)
        host_label = "[%s]" % host if ":" in host else host
        default_port = 443 if scheme == "https" else 80
        self.origin = (
            "%s://%s" % (scheme, host_label)
            if self.port == default_port
            else "%s://%s:%d" % (scheme, host_label, self.port)
        )

    def identity(self):
        return self.scheme, self.host, self.port

    def __repr__(self):
        return "V80SecurityTarget(%s)" % self.origin


class V80SecurityDecision(object):
    """One URL or redirect decision with no retained path/query value."""

    __slots__ = (
        "allowed", "zone", "reason", "target", "addresses", "headers",
        "same_origin",
    )

    def __init__(
            self, allowed, zone, reason, target=None, addresses=(), headers=None,
            same_origin=False):
        self.allowed = bool(allowed)
        self.zone = zone if zone in V80_SECURITY_ZONES else "external_untrusted"
        self.reason = str(reason or "security_decision")
        self.target = target
        self.addresses = tuple(addresses or ())
        self.headers = dict(headers or {})
        self.same_origin = bool(same_origin)

    def __repr__(self):
        return "V80SecurityDecision(allowed=%r, zone=%r, reason=%r)" % (
            self.allowed, self.zone, self.reason,
        )


def _v80_security_reject(reason):
    raise V80SecurityPolicyError(reason)


def _v80_security_host(value):
    host = str(value or "").rstrip(".").lower()
    if not host or "%" in host:
        _v80_security_reject("invalid_host")
    try:
        return _v80_security_ipaddress.ip_address(host).compressed.lower()
    except ValueError:
        pass
    try:
        host = host.encode("idna").decode("ascii").lower()
    except (UnicodeError, ValueError):
        _v80_security_reject("invalid_host")
    if len(host) > 253:
        _v80_security_reject("invalid_host")
    labels = host.split(".")
    for label in labels:
        if (
                not label or len(label) > 63 or label.startswith("-")
                or label.endswith("-")
                or any(not (char.isalnum() or char == "-") for char in label)):
            _v80_security_reject("invalid_host")
    return host


def v80_security_target(value):
    """Parse an absolute HTTP URL into a canonical, credential-free target."""
    if not isinstance(value, str):
        _v80_security_reject("invalid_url")
    if (
            not value or value != value.strip()
            or len(value) > V80_SECURITY_LIMITS["url_characters"]
            or "\\" in value
            or any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in value)):
        _v80_security_reject("invalid_url")
    try:
        parsed = _v80_security_urlparse(value)
        scheme = str(parsed.scheme or "").lower()
        if scheme not in ("http", "https") or not parsed.netloc:
            _v80_security_reject("invalid_url")
        if parsed.username is not None or parsed.password is not None:
            _v80_security_reject("userinfo_forbidden")
        host = _v80_security_host(parsed.hostname)
        port = parsed.port or (443 if scheme == "https" else 80)
    except V80SecurityPolicyError:
        raise
    except (TypeError, ValueError, UnicodeError):
        _v80_security_reject("invalid_url")
    if port < 1 or port > 65535:
        _v80_security_reject("invalid_port")
    return V80SecurityTarget(scheme, host, port)


def _v80_security_origin_set(values):
    if values is None:
        values = ()
    if isinstance(values, str):
        values = (values,)
    origins = set()
    for value in values:
        origins.add(v80_security_target(value).origin)
    return frozenset(origins)


def _v80_security_address(value):
    try:
        address = _v80_security_ipaddress.ip_address(value)
    except (TypeError, ValueError):
        _v80_security_reject("invalid_address")
    mapped = getattr(address, "ipv4_mapped", None)
    return mapped if mapped is not None else address


def _v80_security_addresses(target, values):
    if values is None:
        values = ()
    if isinstance(values, (str, bytes)):
        values = (values,)
    addresses = []
    try:
        numeric_host = _v80_security_address(target.host)
    except V80SecurityPolicyError:
        numeric_host = None
    for value in values:
        address = _v80_security_address(value)
        if address not in addresses:
            addresses.append(address)
    if numeric_host is not None and numeric_host not in addresses:
        addresses.append(numeric_host)
    addresses.sort(key=lambda item: (item.version, str(item)))
    return tuple(addresses)


def _v80_security_address_forbidden(address):
    if address.is_unspecified or address.is_multicast:
        return True
    if any(
            address.version == network.version and address in network
            for network in _V80_SECURITY_EXPLICIT_INTERNAL_NETWORKS):
        return False
    return not address.is_global


def v80_security_filter_headers(headers, same_origin, allow_sensitive=True):
    """Return the fixed request-header allowlist for one redirect hop."""
    if headers in (None, ""):
        return {}
    if not isinstance(headers, dict):
        _v80_security_reject("invalid_headers")
    output = {}
    total_bytes = 0
    for raw_name, raw_value in headers.items():
        name = str(raw_name or "").strip().lower()
        if name not in _V80_SECURITY_HEADER_NAMES or raw_value is None:
            continue
        if isinstance(raw_value, (dict, list, tuple, set)):
            _v80_security_reject("invalid_header_value")
        value = str(raw_value)
        if (
                "\r" in name or "\n" in name or "\r" in value or "\n" in value
                or any(ord(char) < 32 and char != "\t" for char in value)):
            _v80_security_reject("invalid_header_value")
        if not same_origin and name not in V80_SECURITY_CROSS_ORIGIN_HEADERS:
            continue
        if not allow_sensitive and name in V80_SECURITY_SENSITIVE_HEADERS:
            continue
        canonical = _V80_SECURITY_HEADER_NAMES[name]
        value_bytes = len(value.encode("utf-8", "replace"))
        value_limit = (
            V80_SECURITY_LIMITS["cookie_bytes"]
            if name == "cookie"
            else V80_SECURITY_LIMITS["header_value_bytes"]
        )
        if value_bytes > value_limit:
            _v80_security_reject("header_value_too_large")
        if canonical in output:
            if output[canonical] != value:
                _v80_security_reject("conflicting_header")
            continue
        total_bytes += len(canonical.encode("ascii")) + value_bytes + 2
        if total_bytes > V80_SECURITY_LIMITS["headers_total_bytes"]:
            _v80_security_reject("headers_too_large")
        output[canonical] = value
    return output


class V80SecurityPolicy(object):
    """Classify and validate targets without DNS, network, cache, or logging I/O."""

    __slots__ = ("_trusted", "_configured_internal")

    def __init__(self, trusted_backend_origins=(), configured_internal_origins=()):
        trusted = _v80_security_origin_set(trusted_backend_origins)
        configured = _v80_security_origin_set(configured_internal_origins)
        self._trusted = trusted
        self._configured_internal = frozenset(configured.difference(trusted))

    def snapshot(self):
        return {
            "trusted_backend": tuple(sorted(self._trusted)),
            "configured_internal": tuple(sorted(self._configured_internal)),
        }

    def classify(self, value):
        target = value if isinstance(value, V80SecurityTarget) else v80_security_target(value)
        if target.origin in self._trusted:
            return "trusted_backend"
        if target.origin in self._configured_internal:
            return "configured_internal"
        return "external_untrusted"

    def evaluate(self, value, resolved_addresses=()):
        try:
            target = value if isinstance(value, V80SecurityTarget) else v80_security_target(value)
        except V80SecurityPolicyError as exc:
            return V80SecurityDecision(False, "external_untrusted", exc.reason)
        zone = self.classify(target)
        try:
            addresses = _v80_security_addresses(target, resolved_addresses)
        except V80SecurityPolicyError as exc:
            return V80SecurityDecision(False, zone, exc.reason, target=target)
        if not addresses:
            return V80SecurityDecision(False, zone, "resolution_required", target=target)
        if any(_v80_security_address_forbidden(address) for address in addresses):
            return V80SecurityDecision(
                False, zone, "forbidden_address", target=target,
                addresses=tuple(str(address) for address in addresses),
            )
        if zone == "external_untrusted" and not all(address.is_global for address in addresses):
            return V80SecurityDecision(
                False, zone, "external_non_global_address", target=target,
                addresses=tuple(str(address) for address in addresses),
            )
        return V80SecurityDecision(
            True, zone, "allowed_%s" % zone, target=target,
            addresses=tuple(str(address) for address in addresses),
        )

    def redirect(
            self, current_url, next_url, resolved_addresses=(), headers=None,
            redirect_count=0):
        try:
            current = v80_security_target(current_url)
        except V80SecurityPolicyError as exc:
            return V80SecurityDecision(False, "external_untrusted", exc.reason)
        if int(redirect_count) >= V80_SECURITY_LIMITS["redirect_hops"]:
            return V80SecurityDecision(
                False, self.classify(current), "too_many_redirects", target=current,
            )
        decision = self.evaluate(next_url, resolved_addresses=resolved_addresses)
        if not decision.allowed:
            return decision
        source_zone = self.classify(current)
        same_origin = current.identity() == decision.target.identity()
        if source_zone == "external_untrusted" and decision.zone != "external_untrusted":
            return V80SecurityDecision(
                False, decision.zone, "external_to_internal_redirect",
                target=decision.target, addresses=decision.addresses,
            )
        if (
                current.scheme == "https" and decision.target.scheme == "http"
                and decision.zone == "external_untrusted"):
            return V80SecurityDecision(
                False, decision.zone, "https_downgrade", target=decision.target,
                addresses=decision.addresses,
            )
        try:
            filtered = v80_security_filter_headers(
                headers, same_origin=same_origin, allow_sensitive=same_origin,
            )
        except V80SecurityPolicyError as exc:
            return V80SecurityDecision(
                False, decision.zone, exc.reason, target=decision.target,
                addresses=decision.addresses, same_origin=same_origin,
            )
        return V80SecurityDecision(
            True, decision.zone, "allowed_redirect", target=decision.target,
            addresses=decision.addresses, headers=filtered,
            same_origin=same_origin,
        )

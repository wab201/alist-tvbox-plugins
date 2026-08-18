"""Apply the P4 route-probe security policy to the isolated V80 candidate."""

import ast
import hashlib


class RouteSecurityOverlayError(RuntimeError):
    pass


TARGET_ANCHOR = '''    def _media_url_allowed(self, value, deadline=None):
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
'''

TARGET_REPLACEMENT = '''    def _route_security_policy(self):
        origins = []
        configured = (
            getattr(self, "atvp_api", ""),
            getattr(self, "history_api", ""),
        ) + tuple(getattr(self, "_history_api_origins", ()) or ())
        for value in configured:
            value = str(value or "").strip()
            if value and value not in origins:
                origins.append(value)
        return V80SecurityPolicy(trusted_backend_origins=tuple(origins))

    def _media_url_allowed(self, value, deadline=None):
        return self._resolved_media_target(value, deadline=deadline) is not None

    def _resolved_media_target(self, value, deadline=None):
        try:
            target = v80_security_target(str(value or "").strip())
            addresses = self._resolve_addresses(target.host, target.port, deadline)
            decision = self._route_security_policy().evaluate(target, addresses)
            if not decision.allowed:
                return None
            parsed = urlparse(str(value or "").strip())
        except (V80SecurityPolicyError, TypeError, ValueError, UnicodeError):
            return None
        return parsed, tuple(sorted(addresses, key=lambda address: (address.version, str(address))))
'''

SAFE_OUTPUT_ANCHOR = '''    def _safe_atvp_play_output(self, output):
        if not isinstance(output, dict):
            return False
        if self._int_value(output.get("parse"), 0) != 0:
            return False
        media_url = Filter._first_http_url(output.get("url"))
        return bool(media_url and Filter._safe_media_url(media_url, self.atvp_api))
'''

SAFE_OUTPUT_REPLACEMENT = '''    def _safe_atvp_play_output(self, output, deadline=None):
        if not isinstance(output, dict):
            return False
        if self._int_value(output.get("parse"), 0) != 0:
            return False
        media_url = Filter._first_http_url(output.get("url"))
        return bool(media_url and self._media_url_allowed(media_url, deadline=deadline))
'''

PLAYER_OUTPUT_ANCHOR = '''                    elif self._safe_atvp_play_output(output):
'''

PLAYER_OUTPUT_REPLACEMENT = '''                    elif self._safe_atvp_play_output(
                            output, deadline=candidate_deadline):
'''

PLAYER_REFRESHED_OUTPUT_ANCHOR = '''                            elif self._safe_atvp_play_output(refreshed):
'''

PLAYER_REFRESHED_OUTPUT_REPLACEMENT = '''                            elif self._safe_atvp_play_output(
                                    refreshed, deadline=candidate_deadline):
'''

RESOURCE_PROBE_ANCHOR = '''                if self._int_value((output or {}).get("parse"), 0) == 0 and Filter._safe_media_url(media_url, self.atvp_api):
'''

RESOURCE_PROBE_REPLACEMENT = '''                if (self._int_value((output or {}).get("parse"), 0) == 0
                        and self._media_url_allowed(media_url, deadline=play_deadline)):
'''

RESOURCE_OUTPUT_ANCHOR = '''                if self._safe_atvp_play_output(output):
'''

RESOURCE_OUTPUT_REPLACEMENT = '''                if self._safe_atvp_play_output(output, deadline=play_deadline):
'''

HEADERS_ANCHOR = '''        playback_headers = dict(clean_output.get("header") or {})
        headers = dict(playback_headers)
        headers.setdefault("User-Agent", self.user_agent)
        headers.setdefault("Accept", "*/*")
        headers["Range"] = "bytes=0-%d" % (self.ROUTE_PROBE_MAX_BYTES - 1)
        current = media_url
        crossed_origin = False
'''

HEADERS_REPLACEMENT = '''        try:
            security_policy = self._route_security_policy()
            playback_headers = v80_security_filter_headers(
                dict(clean_output.get("header") or {}),
                same_origin=True,
                allow_sensitive=True,
            )
        except V80SecurityPolicyError:
            return None
        headers = dict(playback_headers)
        headers.setdefault("User-Agent", self.user_agent)
        headers.setdefault("Accept", "*/*")
        headers["Range"] = "bytes=0-%d" % (self.ROUTE_PROBE_MAX_BYTES - 1)
        current = media_url
        previous_url = None
        crossed_origin = False
'''

LOOP_ANCHOR = '''        absolute_deadline = deadline if deadline is not None else time.monotonic() + 8
        for redirect_count in range(5):
            resolved = self._resolved_media_target(current, deadline=absolute_deadline)
            if resolved is None:
                return redirected_output()
            parsed, addresses = resolved
            if absolute_deadline - time.monotonic() <= 0:
                return redirected_output()
'''

LOOP_REPLACEMENT = '''        absolute_deadline = deadline if deadline is not None else time.monotonic() + 8
        for redirect_count in range(V80_SECURITY_LIMITS["redirect_hops"] + 1):
            resolved = self._resolved_media_target(current, deadline=absolute_deadline)
            if resolved is None:
                return None
            parsed, addresses = resolved
            if previous_url is not None:
                decision = security_policy.redirect(
                    previous_url,
                    current,
                    resolved_addresses=addresses,
                    headers=headers,
                    redirect_count=redirect_count - 1,
                )
                if not decision.allowed:
                    return None
                if not decision.same_origin:
                    crossed_origin = True
                headers = dict(decision.headers)
                try:
                    playback_headers = v80_security_filter_headers(
                        playback_headers,
                        same_origin=decision.same_origin,
                        allow_sensitive=decision.same_origin,
                    )
                except V80SecurityPolicyError:
                    return None
            if absolute_deadline - time.monotonic() <= 0:
                return redirected_output()
'''

REDIRECT_ANCHOR = '''            if status in (301, 302, 303, 307, 308):
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
'''

REDIRECT_REPLACEMENT = '''            if status in V80_SECURITY_REDIRECT_STATUSES:
                if redirect_count >= V80_SECURITY_LIMITS["redirect_hops"]:
                    return None
                location = str(response_headers.get("Location") or response_headers.get("location") or "").strip()
                if not location:
                    return None
                previous_url = current
                current = urljoin(current, location)
                continue
'''

INSERTIONS = (
    ("target-policy", TARGET_ANCHOR, TARGET_REPLACEMENT),
    ("strict-unprobed-output", SAFE_OUTPUT_ANCHOR, SAFE_OUTPUT_REPLACEMENT),
    ("player-unprobed-output", PLAYER_OUTPUT_ANCHOR, PLAYER_OUTPUT_REPLACEMENT),
    (
        "player-refreshed-unprobed-output",
        PLAYER_REFRESHED_OUTPUT_ANCHOR,
        PLAYER_REFRESHED_OUTPUT_REPLACEMENT,
    ),
    ("resource-probe-policy", RESOURCE_PROBE_ANCHOR, RESOURCE_PROBE_REPLACEMENT),
    ("resource-unprobed-output", RESOURCE_OUTPUT_ANCHOR, RESOURCE_OUTPUT_REPLACEMENT),
    ("probe-headers", HEADERS_ANCHOR, HEADERS_REPLACEMENT),
    ("redirect-decision", LOOP_ANCHOR, LOOP_REPLACEMENT),
    ("redirect-transition", REDIRECT_ANCHOR, REDIRECT_REPLACEMENT),
)


def _replace_once(text, anchor, replacement, label):
    count = text.count(anchor)
    if count != 1:
        raise RouteSecurityOverlayError(
            "route security anchor %s must appear once, found %d" % (label, count)
        )
    return text.replace(anchor, replacement, 1)


def _class(tree, name):
    matches = [node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == name]
    if len(matches) != 1:
        raise RouteSecurityOverlayError("expected one %s class" % name)
    return matches[0]


def _method(node, name):
    matches = [
        item for item in node.body
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == name
    ]
    if len(matches) != 1:
        raise RouteSecurityOverlayError("expected one %s method" % name)
    return matches[0]


def _calls(method, name):
    return [
        node for node in ast.walk(method)
        if isinstance(node, ast.Call)
        and (
            (isinstance(node.func, ast.Name) and node.func.id == name)
            or (isinstance(node.func, ast.Attribute) and node.func.attr == name)
        )
    ]


def apply_route_security_overlay(source):
    try:
        text = bytes(source).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RouteSecurityOverlayError(
            "route security overlay input is not valid UTF-8"
        ) from exc
    input_bytes = text.encode("utf-8")
    for label, anchor, replacement in INSERTIONS:
        text = _replace_once(text, anchor, replacement, label)

    try:
        tree = ast.parse(text, filename="build/v80-dev/route-security-overlay.py")
        compile(tree, "build/v80-dev/route-security-overlay.py", "exec")
    except SyntaxError as exc:
        raise RouteSecurityOverlayError(
            "route security overlay output is invalid: %s" % exc
        ) from exc

    spider = _class(tree, "Spider")
    policy = _method(spider, "_route_security_policy")
    target = _method(spider, "_resolved_media_target")
    safe_output = _method(spider, "_safe_atvp_play_output")
    player = _method(spider, "_v80_playerContent_unbounded")
    resource_detail = _method(spider, "_validated_playable_detail")
    probe = _method(spider, "_v80_probe_media_output_unbounded")
    if len(_calls(policy, "V80SecurityPolicy")) != 1:
        raise RouteSecurityOverlayError("route policy must be constructed exactly once")
    if len(_calls(target, "evaluate")) != 1:
        raise RouteSecurityOverlayError("media target must be evaluated exactly once")
    if len(_calls(safe_output, "_media_url_allowed")) != 1:
        raise RouteSecurityOverlayError("unprobed output must use strict media policy once")
    if _calls(safe_output, "_safe_media_url"):
        raise RouteSecurityOverlayError("weak unprobed output policy remains active")
    player_output_calls = _calls(player, "_safe_atvp_play_output")
    if len(player_output_calls) != 2 or any(
            not any(keyword.arg == "deadline" for keyword in call.keywords)
            for call in player_output_calls):
        raise RouteSecurityOverlayError("player fallback policy seams are invalid")
    resource_output_calls = _calls(resource_detail, "_safe_atvp_play_output")
    if len(resource_output_calls) != 1 or not any(
            keyword.arg == "deadline" for keyword in resource_output_calls[0].keywords):
        raise RouteSecurityOverlayError("resource fallback policy seam is invalid")
    resource_policy_calls = _calls(resource_detail, "_media_url_allowed")
    if len(resource_policy_calls) != 1 or not any(
            keyword.arg == "deadline" for keyword in resource_policy_calls[0].keywords):
        raise RouteSecurityOverlayError("resource probe policy seam is invalid")
    if len(_calls(probe, "redirect")) != 1:
        raise RouteSecurityOverlayError("each redirect hop must use one policy decision")
    if len(_calls(probe, "v80_security_filter_headers")) != 2:
        raise RouteSecurityOverlayError("route probe header policy seams are invalid")
    if _calls(probe, "_media_origin"):
        raise RouteSecurityOverlayError("legacy redirect origin checks remain active")

    output = text.encode("utf-8")
    return {
        "bytes": output,
        "input_size": len(input_bytes),
        "input_sha256": hashlib.sha256(input_bytes).hexdigest().upper(),
        "size": len(output),
        "sha256": hashlib.sha256(output).hexdigest().upper(),
        "insertions": tuple(label for label, _anchor, _replacement in INSERTIONS),
    }


def main():
    raise SystemExit("import apply_route_security_overlay from the V80 build pipeline")


if __name__ == "__main__":
    main()

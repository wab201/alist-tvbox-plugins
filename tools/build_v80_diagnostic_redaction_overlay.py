"""Route diagnostic and error text through the P4 redaction policy."""

import ast
import hashlib


class DiagnosticRedactionOverlayError(RuntimeError):
    pass


DIAGNOSTIC_EVENT_ANCHOR = '''            payload = {
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
'''

DIAGNOSTIC_EVENT_REPLACEMENT = '''            payload = {
                "event": self._short_error(event or "unknown", limit=512),
                "level": self._short_error(level or "INFO", limit=512).upper(),
                "at": time.time(),
            }
            if exc is not None:
                payload["error_kind"] = self._diagnostic_error_kind(exc)
                payload["error"] = self._short_error(exc)
                if payload["level"] in ("ERROR", "CRITICAL"):
                    trace = "".join(traceback.format_exception_only(type(exc), exc)).strip()
                    payload["trace"] = self._short_error(RuntimeError(trace), limit=512)
            for key, value in fields.items():
                if value is None:
                    continue
                safe_key = self._short_error(key, limit=512)
                payload[safe_key] = self._short_error(value, limit=512)
'''

SHORT_ERROR_ANCHOR = '''    def _short_error(self, exc):
        text = str(exc or "未知错误").strip().replace("\\r", " ").replace("\\n", " ")
        text = re.sub(
            r"(?i)([?&](?:api[_-]?key|access[_-]?token|token|secret|ck|cookie|password|proxy[_-]?(?:user|username|password))=)[^&\\s]+",
            r"\\1***", text,
        )
        text = re.sub(
            r"(?i)\\b(ck|cookie|password|proxy[_-]?(?:user|username|password))\\s*[:=]\\s*([^\\s,;&]+)",
            r"\\1=***", text,
        )
        text = re.sub(
            r"(?i)(/(?:play|parse|offline_download|p)/)[^/?#\\s]+",
            r"\\1***", text,
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
'''

SHORT_ERROR_REPLACEMENT = '''    def _short_error(self, exc, limit=220):
        text = v80_redact_diagnostic_text(
            exc if exc is not None else "未知错误",
            (
                getattr(self, "atvp_token", ""), getattr(self, "_history_auth_token", ""),
                getattr(self, "tmdb_api_key", ""), getattr(self, "tmdb_access_token", ""),
                getattr(self, "history_password", ""), getattr(self, "cookie", ""),
                getattr(self, "ck", ""), getattr(self, "proxy", ""),
                getattr(self, "tmdb_proxy", ""),
            ),
        ).strip().replace("\\r", " ").replace("\\n", " ")
        limit = 512 if limit == 512 else 220
        return text[:limit] or "未知错误"
'''

INSERTIONS = (
    ("diagnostic-field-redaction", DIAGNOSTIC_EVENT_ANCHOR, DIAGNOSTIC_EVENT_REPLACEMENT),
    ("short-error-redaction", SHORT_ERROR_ANCHOR, SHORT_ERROR_REPLACEMENT),
)


def _replace_once(text, anchor, replacement, label):
    count = text.count(anchor)
    if count != 1:
        raise DiagnosticRedactionOverlayError(
            "diagnostic redaction anchor %s must appear once, found %d"
            % (label, count)
        )
    return text.replace(anchor, replacement, 1)


def _method(tree, method_name):
    classes = [
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "Spider"
    ]
    if len(classes) != 1:
        raise DiagnosticRedactionOverlayError("expected one Spider class")
    methods = [
        node for node in classes[0].body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == method_name
    ]
    if len(methods) != 1:
        raise DiagnosticRedactionOverlayError(
            "expected one Spider.%s method" % method_name
        )
    return methods[0]


def _calls(method, name):
    return [
        node for node in ast.walk(method)
        if isinstance(node, ast.Call)
        and (
            isinstance(node.func, ast.Name) and node.func.id == name
            or isinstance(node.func, ast.Attribute) and node.func.attr == name
        )
    ]


def _audit_diagnostic_event(tree):
    method = _method(tree, "_diagnostic_event")
    short_error_calls = _calls(method, "_short_error")
    if len(short_error_calls) != 6:
        raise DiagnosticRedactionOverlayError(
            "diagnostic event must route names, error, trace, keys, and fields through _short_error"
        )
    field_calls = [
        call for call in short_error_calls
        if any(
            keyword.arg == "limit"
            and isinstance(keyword.value, ast.Constant)
            and keyword.value.value == 512
            for keyword in call.keywords
        )
    ]
    if len(field_calls) != 5:
        raise DiagnosticRedactionOverlayError(
            "diagnostic names, trace, keys, and fields must use the fixed 512-character path"
        )
    if _calls(method, "v80_redact_diagnostic_text"):
        raise DiagnosticRedactionOverlayError(
            "diagnostic event must keep _short_error as the sole text owner"
        )


def _audit_short_error(tree):
    method = _method(tree, "_short_error")
    if [argument.arg for argument in method.args.args] != ["self", "exc", "limit"]:
        raise DiagnosticRedactionOverlayError("short error signature is invalid")
    if len(method.args.defaults) != 1 or not (
            isinstance(method.args.defaults[0], ast.Constant)
            and method.args.defaults[0].value == 220):
        raise DiagnosticRedactionOverlayError("short error default limit is invalid")
    if len(_calls(method, "v80_redact_diagnostic_text")) != 1:
        raise DiagnosticRedactionOverlayError(
            "short error must call the redaction policy exactly once"
        )
    if _calls(method, "sub") or _calls(method, "quote"):
        raise DiagnosticRedactionOverlayError(
            "short error must not retain a second ad-hoc redaction implementation"
        )
    if any(
            isinstance(node, ast.Constant) and node.value not in (220, 512)
            for node in ast.walk(method)
            if isinstance(node, ast.Constant) and isinstance(node.value, int)):
        raise DiagnosticRedactionOverlayError(
            "short error may expose only the fixed 220 and 512 limits"
        )


def apply_diagnostic_redaction_overlay(source):
    try:
        text = bytes(source).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise DiagnosticRedactionOverlayError(
            "diagnostic redaction input is not valid UTF-8"
        ) from exc
    input_bytes = text.encode("utf-8")
    for label, anchor, replacement in INSERTIONS:
        text = _replace_once(text, anchor, replacement, label)

    try:
        tree = ast.parse(text, filename="build/v80-dev/diagnostic-redaction.py")
        compile(tree, "build/v80-dev/diagnostic-redaction.py", "exec")
    except SyntaxError as exc:
        raise DiagnosticRedactionOverlayError(
            "diagnostic redaction output is invalid: %s" % exc
        ) from exc
    _audit_diagnostic_event(tree)
    _audit_short_error(tree)

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
    raise SystemExit(
        "import apply_diagnostic_redaction_overlay from the V80 build pipeline"
    )


if __name__ == "__main__":
    main()

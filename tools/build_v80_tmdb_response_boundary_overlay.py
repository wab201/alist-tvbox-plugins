"""Apply bounded reading and field limits to the TMDB request family."""

import ast
import hashlib


class TmdbResponseBoundaryOverlayError(RuntimeError):
    pass


JSON_RESPONSE_ANCHOR = '''    def _json_response(self, response):
        try:
            value = response.json()
            return value if isinstance(value, dict) else {"data": value}
        except Exception:
            if response.status_code != 200:
                return {"error": "HTTP %s" % response.status_code}
            raise RuntimeError("上游返回了非 JSON 内容")
'''

JSON_RESPONSE_REPLACEMENT = '''    def _json_response(
            self, response, max_bytes=None, deadline=None,
            close_response=True, label="上游"):
        try:
            if max_bytes is None:
                value = response.json()
            else:
                value = _read_bounded_json_shared(
                    response,
                    label,
                    max_bytes,
                    deadline=deadline,
                    close_response=close_response,
                )
            return value if isinstance(value, dict) else {"data": value}
        except RuntimeError as exc:
            if max_bytes is not None:
                invalid_json = "%s 返回无效 JSON" % label
                oversized = "%s 响应过大" % label
                if response.status_code != 200 and str(exc) in (invalid_json, oversized):
                    return {"error": "HTTP %s" % response.status_code}
                if str(exc) == invalid_json:
                    raise RuntimeError("上游返回了非 JSON 内容")
                raise
            if response.status_code != 200:
                return {"error": "HTTP %s" % response.status_code}
            raise RuntimeError("上游返回了非 JSON 内容")
        except Exception:
            if response.status_code != 200:
                return {"error": "HTTP %s" % response.status_code}
            raise RuntimeError("上游返回了非 JSON 内容")
'''

TMDB_REQUEST_ANCHOR = '''    def _request_tmdb(self, path, query):
        with self._v80_timeout_child_scope("tmdb", self.timeout) as operation:
            response = self._tmdb_session.get(
                self.tmdb_api_base + path,
                params=query,
                timeout=operation.request_timeout(
                    self.timeout, retry_policy=GENERAL_TRANSPORT_RETRY_POLICY,
                ),
                verify=self.verify_tls,
                stream=True,
            )
            operation.track(response)
            try:
                data = self._json_response(response)
                if response.status_code in (401, 403):
                    raise RuntimeError("TMDB API 凭据无效或无权访问")
                if response.status_code == 429:
                    raise RuntimeError("TMDB API 请求过于频繁，请稍后刷新")
                if response.status_code != 200:
                    raise RuntimeError(str(data.get("status_message") or "TMDB HTTP %s" % response.status_code))
                return v80_validate_json_shape(data)
            finally:
                operation.close_tracked(response)
'''

TMDB_REQUEST_REPLACEMENT = '''    def _request_tmdb(self, path, query):
        with self._v80_timeout_child_scope("tmdb", self.timeout) as operation:
            response = self._tmdb_session.get(
                self.tmdb_api_base + path,
                params=query,
                timeout=operation.request_timeout(
                    self.timeout, retry_policy=GENERAL_TRANSPORT_RETRY_POLICY,
                ),
                verify=self.verify_tls,
                allow_redirects=False,
                stream=True,
            )
            operation.track(response)
            try:
                if response.status_code in (401, 403):
                    raise RuntimeError("TMDB API 凭据无效或无权访问")
                if response.status_code == 429:
                    raise RuntimeError("TMDB API 请求过于频繁，请稍后刷新")
                data = self._json_response(
                    response,
                    max_bytes=V80_TMDB_RESPONSE_LIMITS["max_response_bytes"],
                    deadline=operation.deadline,
                    close_response=False,
                    label="TMDB",
                )
                if response.status_code != 200:
                    raise RuntimeError(str(data.get("status_message") or "TMDB HTTP %s" % response.status_code))
                return v80_validate_tmdb_json_fields(v80_validate_json_shape(data))
            finally:
                operation.close_tracked(response)
'''

INSERTIONS = (
    ("json-response-bounded-mode", JSON_RESPONSE_ANCHOR, JSON_RESPONSE_REPLACEMENT),
    ("tmdb-response-boundary", TMDB_REQUEST_ANCHOR, TMDB_REQUEST_REPLACEMENT),
)


def _replace_once(text, anchor, replacement, label):
    count = text.count(anchor)
    if count != 1:
        raise TmdbResponseBoundaryOverlayError(
            "TMDB response boundary anchor %s must appear once, found %d"
            % (label, count)
        )
    return text.replace(anchor, replacement, 1)


def _method(tree, class_name, method_name):
    classes = [
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == class_name
    ]
    if len(classes) != 1:
        raise TmdbResponseBoundaryOverlayError("expected one %s class" % class_name)
    methods = [
        node for node in classes[0].body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == method_name
    ]
    if len(methods) != 1:
        raise TmdbResponseBoundaryOverlayError("expected one %s method" % method_name)
    return methods[0]


def _calls(method, name):
    return [
        node for node in ast.walk(method)
        if isinstance(node, ast.Call)
        and (
            (isinstance(node.func, ast.Name) and node.func.id == name)
            or (isinstance(node.func, ast.Attribute) and node.func.attr == name)
        )
    ]


def _tmdb_session_get_calls(method):
    return [
        node for node in ast.walk(method)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "get"
        and isinstance(node.func.value, ast.Attribute)
        and node.func.value.attr == "_tmdb_session"
        and isinstance(node.func.value.value, ast.Name)
        and node.func.value.value.id == "self"
    ]


def _audit_tmdb_method(tree):
    method = _method(tree, "Spider", "_request_tmdb")
    for name in (
        "_json_response",
        "v80_validate_json_shape",
        "v80_validate_tmdb_json_fields",
        "_v80_timeout_child_scope",
        "request_timeout",
        "track",
        "close_tracked",
    ):
        if len(_calls(method, name)) != 1:
            raise TmdbResponseBoundaryOverlayError(
                "TMDB response owner %s must appear exactly once" % name
            )
    if _calls(method, "_read_bounded_json_shared"):
        raise TmdbResponseBoundaryOverlayError(
            "TMDB request must keep bounded reading inside the JSON response owner"
        )
    session_calls = _tmdb_session_get_calls(method)
    if len(session_calls) != 1:
        raise TmdbResponseBoundaryOverlayError(
            "TMDB transport get owner must remain exactly once"
        )
    request_keywords = {
        keyword.arg: keyword.value for keyword in session_calls[0].keywords
    }
    allow_redirects = request_keywords.get("allow_redirects")
    if not (
            isinstance(allow_redirects, ast.Constant)
            and allow_redirects.value is False):
        raise TmdbResponseBoundaryOverlayError(
            "TMDB transport must disable Requests automatic redirects"
        )

    json_call = _calls(method, "_json_response")[0]
    keyword_values = {keyword.arg: keyword.value for keyword in json_call.keywords}
    if not (
        isinstance(keyword_values.get("max_bytes"), ast.Subscript)
        and isinstance(keyword_values["max_bytes"].value, ast.Name)
        and keyword_values["max_bytes"].value.id == "V80_TMDB_RESPONSE_LIMITS"
        and isinstance(keyword_values.get("deadline"), ast.Attribute)
        and isinstance(keyword_values["deadline"].value, ast.Name)
        and keyword_values["deadline"].value.id == "operation"
        and keyword_values["deadline"].attr == "deadline"
        and isinstance(keyword_values.get("close_response"), ast.Constant)
        and keyword_values["close_response"].value is False
        and isinstance(keyword_values.get("label"), ast.Constant)
        and keyword_values["label"].value == "TMDB"
    ):
        raise TmdbResponseBoundaryOverlayError(
            "TMDB JSON response must reuse the frozen byte, timeout, and close owners"
        )

    field_call = _calls(method, "v80_validate_tmdb_json_fields")[0]
    if len(field_call.args) != 1 or not (
        isinstance(field_call.args[0], ast.Call)
        and isinstance(field_call.args[0].func, ast.Name)
        and field_call.args[0].func.id == "v80_validate_json_shape"
    ):
        raise TmdbResponseBoundaryOverlayError(
            "TMDB field validation must follow JSON shape validation"
        )


def _audit_json_response_method(tree):
    method = _method(tree, "Spider", "_json_response")
    if [argument.arg for argument in method.args.args] != [
            "self", "response", "max_bytes", "deadline", "close_response", "label"]:
        raise TmdbResponseBoundaryOverlayError(
            "JSON response bounded mode signature is invalid"
        )
    if len(_calls(method, "json")) != 1:
        raise TmdbResponseBoundaryOverlayError(
            "existing response.json owner must remain exactly once"
        )
    if len(_calls(method, "_read_bounded_json_shared")) != 1:
        raise TmdbResponseBoundaryOverlayError(
            "bounded JSON reader owner must appear exactly once"
        )
    bounded_call = _calls(method, "_read_bounded_json_shared")[0]
    keyword_values = {keyword.arg: keyword.value for keyword in bounded_call.keywords}
    if not (
        isinstance(keyword_values.get("deadline"), ast.Name)
        and keyword_values["deadline"].id == "deadline"
        and isinstance(keyword_values.get("close_response"), ast.Name)
        and keyword_values["close_response"].id == "close_response"
    ):
        raise TmdbResponseBoundaryOverlayError(
            "bounded JSON reader must forward existing deadline and close ownership"
        )
    if _calls(method, "_v80_timeout_child_scope") or _calls(method, "close_tracked"):
        raise TmdbResponseBoundaryOverlayError(
            "JSON response bounded mode must not create timeout or close owners"
        )


def apply_tmdb_response_boundary_overlay(source):
    try:
        text = bytes(source).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise TmdbResponseBoundaryOverlayError(
            "TMDB response boundary input is not valid UTF-8"
        ) from exc
    input_bytes = text.encode("utf-8")
    for label, anchor, replacement in INSERTIONS:
        text = _replace_once(text, anchor, replacement, label)

    try:
        tree = ast.parse(text, filename="build/v80-dev/tmdb-response-boundary.py")
        compile(tree, "build/v80-dev/tmdb-response-boundary.py", "exec")
    except SyntaxError as exc:
        raise TmdbResponseBoundaryOverlayError(
            "TMDB response boundary output is invalid: %s" % exc
        ) from exc
    _audit_tmdb_method(tree)
    _audit_json_response_method(tree)

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
        "import apply_tmdb_response_boundary_overlay from the V80 build pipeline"
    )


if __name__ == "__main__":
    main()

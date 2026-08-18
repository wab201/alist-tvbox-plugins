"""Apply the P4 JSON shape policy to successful TMDB JSON responses only."""

import ast
import hashlib


class TmdbJsonShapeOverlayError(RuntimeError):
    pass


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
                return data
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

INSERTIONS = (("tmdb-json-shape", TMDB_REQUEST_ANCHOR, TMDB_REQUEST_REPLACEMENT),)


def _replace_once(text, anchor, replacement, label):
    count = text.count(anchor)
    if count != 1:
        raise TmdbJsonShapeOverlayError(
            "TMDB JSON shape anchor %s must appear once, found %d" % (label, count)
        )
    return text.replace(anchor, replacement, 1)


def _method(tree, class_name, method_name):
    classes = [
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == class_name
    ]
    if len(classes) != 1:
        raise TmdbJsonShapeOverlayError("expected one %s class" % class_name)
    methods = [
        node for node in classes[0].body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == method_name
    ]
    if len(methods) != 1:
        raise TmdbJsonShapeOverlayError("expected one %s method" % method_name)
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
    if len(_calls(method, "v80_validate_json_shape")) != 1:
        raise TmdbJsonShapeOverlayError("TMDB response must use one JSON shape decision")
    for name in ("_v80_timeout_child_scope", "request_timeout", "track",
                 "_json_response", "close_tracked"):
        if len(_calls(method, name)) != 1:
            raise TmdbJsonShapeOverlayError(
                "TMDB existing owner %s must remain exactly once" % name
            )
    if len(_tmdb_session_get_calls(method)) != 1:
        raise TmdbJsonShapeOverlayError(
            "TMDB transport get owner must remain exactly once"
        )

    with_nodes = [node for node in method.body if isinstance(node, ast.With)]
    if len(with_nodes) != 1:
        raise TmdbJsonShapeOverlayError("TMDB timeout scope shape is invalid")
    try_nodes = [node for node in with_nodes[0].body if isinstance(node, ast.Try)]
    if len(try_nodes) != 1 or len(try_nodes[0].body) != 5:
        raise TmdbJsonShapeOverlayError("TMDB status and shape decision order is invalid")
    if not all(isinstance(node, ast.If) for node in try_nodes[0].body[1:4]):
        raise TmdbJsonShapeOverlayError("TMDB status checks must precede shape validation")
    return_node = try_nodes[0].body[4]
    if not (
        isinstance(return_node, ast.Return)
        and isinstance(return_node.value, ast.Call)
        and isinstance(return_node.value.func, ast.Name)
        and return_node.value.func.id == "v80_validate_json_shape"
    ):
        raise TmdbJsonShapeOverlayError("TMDB shape validation must be the success return")


def apply_tmdb_json_shape_overlay(source):
    try:
        text = bytes(source).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise TmdbJsonShapeOverlayError(
            "TMDB JSON shape overlay input is not valid UTF-8"
        ) from exc
    input_bytes = text.encode("utf-8")
    for label, anchor, replacement in INSERTIONS:
        text = _replace_once(text, anchor, replacement, label)

    try:
        tree = ast.parse(text, filename="build/v80-dev/tmdb-json-shape-overlay.py")
        compile(tree, "build/v80-dev/tmdb-json-shape-overlay.py", "exec")
    except SyntaxError as exc:
        raise TmdbJsonShapeOverlayError(
            "TMDB JSON shape overlay output is invalid: %s" % exc
        ) from exc
    _audit_tmdb_method(tree)

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
    raise SystemExit("import apply_tmdb_json_shape_overlay from the V80 build pipeline")


if __name__ == "__main__":
    main()

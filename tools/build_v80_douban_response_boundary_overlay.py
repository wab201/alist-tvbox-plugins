"""Apply bounded reading and JSON shape limits to the Douban request family."""

import ast
import hashlib


class DoubanResponseBoundaryOverlayError(RuntimeError):
    pass


DOUBAN_REQUEST_ANCHOR = '''    def request_json(self, url, params=None):
        owner = self.owner
        with owner._v80_timeout_child_scope("douban_json", owner.timeout) as operation:
            response = owner._session.get(
                url,
                params=params,
                timeout=operation.request_timeout(
                    owner.timeout, retry_policy=GENERAL_TRANSPORT_RETRY_POLICY,
                ),
                verify=owner.verify_tls,
                stream=True,
            )
            operation.track(response)
            try:
                payload = owner._json_response(response)
                if response.status_code != 200:
                    raise RuntimeError("HTTP %s" % response.status_code)
                return payload
            finally:
                operation.close_tracked(response)
'''

DOUBAN_REQUEST_REPLACEMENT = '''    def request_json(self, url, params=None):
        owner = self.owner
        with owner._v80_timeout_child_scope("douban_json", owner.timeout) as operation:
            response = owner._session.get(
                url,
                params=params,
                timeout=operation.request_timeout(
                    owner.timeout, retry_policy=GENERAL_TRANSPORT_RETRY_POLICY,
                ),
                verify=owner.verify_tls,
                allow_redirects=False,
                stream=True,
            )
            operation.track(response)
            try:
                payload = owner._json_response(
                    response,
                    max_bytes=V80_DOUBAN_RESPONSE_LIMITS["max_response_bytes"],
                    deadline=operation.deadline,
                    close_response=False,
                    label="豆瓣",
                )
                if response.status_code != 200:
                    raise RuntimeError("HTTP %s" % response.status_code)
                return v80_validate_json_shape(payload)
            finally:
                operation.close_tracked(response)
'''

DOUBAN_ACTION_ANCHOR = '''            with self._v80_timeout_child_scope("douban_wish", self.timeout) as operation:
                response = self._session.post(
                    url,
                    headers=headers,
                    data=data,
                    timeout=operation.request_timeout(self.timeout),
                    verify=self.verify_tls,
                    stream=True,
                )
                operation.track(response)
                try:
                    payload = self._json_response(response)
                    if response.status_code == 200 and str(payload.get("r", "0")) == "0":
                        self._drop_cache_prefix("wishlist:")
                        return json.dumps({"msg": "已加入豆瓣想看"}, ensure_ascii=False)
                    if response.status_code in (401, 403) or str(payload.get("code", "")) == "403":
                        message = "豆瓣登录已失效，请更新 Cookie/ck"
                    else:
                        message = str(payload.get("msg") or payload.get("error") or "豆瓣未确认收藏成功")
                    return json.dumps({"msg": message}, ensure_ascii=False)
                finally:
                    operation.close_tracked(response)
'''

DOUBAN_ACTION_REPLACEMENT = '''            with self._v80_timeout_child_scope("douban_wish", self.timeout) as operation:
                response = self._session.post(
                    url,
                    headers=headers,
                    data=data,
                    timeout=operation.request_timeout(self.timeout),
                    verify=self.verify_tls,
                    allow_redirects=False,
                    stream=True,
                )
                operation.track(response)
                try:
                    payload = self._json_response(
                        response,
                        max_bytes=V80_DOUBAN_RESPONSE_LIMITS["max_response_bytes"],
                        deadline=operation.deadline,
                        close_response=False,
                        label="豆瓣",
                    )
                    action_success = (
                        response.status_code == 200
                        and str(payload.get("r", "0")) == "0"
                    )
                    action_auth_failed = (
                        response.status_code in (401, 403)
                        or str(payload.get("code", "")) == "403"
                    )
                    if not action_auth_failed:
                        payload = v80_validate_json_shape(payload)
                    if action_success:
                        self._drop_cache_prefix("wishlist:")
                        return json.dumps({"msg": "已加入豆瓣想看"}, ensure_ascii=False)
                    if action_auth_failed:
                        message = "豆瓣登录已失效，请更新 Cookie/ck"
                    else:
                        message = str(payload.get("msg") or payload.get("error") or "豆瓣未确认收藏成功")
                    return json.dumps({"msg": message}, ensure_ascii=False)
                finally:
                    operation.close_tracked(response)
'''

INSERTIONS = (
    (
        "douban-json-response-boundary",
        DOUBAN_REQUEST_ANCHOR,
        DOUBAN_REQUEST_REPLACEMENT,
    ),
    (
        "douban-wish-response-boundary",
        DOUBAN_ACTION_ANCHOR,
        DOUBAN_ACTION_REPLACEMENT,
    ),
)


def _replace_once(text, anchor, replacement, label):
    count = text.count(anchor)
    if count != 1:
        raise DoubanResponseBoundaryOverlayError(
            "Douban response boundary anchor %s must appear once, found %d"
            % (label, count)
        )
    return text.replace(anchor, replacement, 1)


def _method(tree, class_name, method_name):
    classes = [
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == class_name
    ]
    if len(classes) != 1:
        raise DoubanResponseBoundaryOverlayError(
            "expected one %s class" % class_name
        )
    methods = [
        node for node in classes[0].body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == method_name
    ]
    if len(methods) != 1:
        raise DoubanResponseBoundaryOverlayError(
            "expected one %s method" % method_name
        )
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


def _session_calls(method, owner_name, verb):
    calls = []
    for node in ast.walk(method):
        if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == verb
                and isinstance(node.func.value, ast.Attribute)
                and node.func.value.attr == "_session"):
            continue
        session_owner = node.func.value.value
        if isinstance(session_owner, ast.Name) and session_owner.id == owner_name:
            calls.append(node)
    return calls


def _audit_json_call(call, owner_label):
    keyword_values = {keyword.arg: keyword.value for keyword in call.keywords}
    max_bytes = keyword_values.get("max_bytes")
    if not (
            isinstance(max_bytes, ast.Subscript)
            and isinstance(max_bytes.value, ast.Name)
            and max_bytes.value.id == "V80_DOUBAN_RESPONSE_LIMITS"
            and isinstance(keyword_values.get("deadline"), ast.Attribute)
            and isinstance(keyword_values["deadline"].value, ast.Name)
            and keyword_values["deadline"].value.id == "operation"
            and keyword_values["deadline"].attr == "deadline"
            and isinstance(keyword_values.get("close_response"), ast.Constant)
            and keyword_values["close_response"].value is False
            and isinstance(keyword_values.get("label"), ast.Constant)
            and keyword_values["label"].value == "豆瓣"):
        raise DoubanResponseBoundaryOverlayError(
            "%s must reuse the frozen byte, timeout, and close owners"
            % owner_label
        )


def _audit_redirect_disabled(call, owner_label):
    keyword_values = {keyword.arg: keyword.value for keyword in call.keywords}
    allow_redirects = keyword_values.get("allow_redirects")
    if not (
            isinstance(allow_redirects, ast.Constant)
            and allow_redirects.value is False):
        raise DoubanResponseBoundaryOverlayError(
            "%s must disable Requests automatic redirects" % owner_label
        )


def _audit_douban_request(tree):
    method = _method(tree, "_DoubanClient", "request_json")
    for name in (
        "_json_response",
        "v80_validate_json_shape",
        "_v80_timeout_child_scope",
        "request_timeout",
        "track",
        "close_tracked",
    ):
        if len(_calls(method, name)) != 1:
            raise DoubanResponseBoundaryOverlayError(
                "Douban request owner %s must appear exactly once" % name
            )
    if _calls(method, "_read_bounded_json_shared") or _calls(method, "json"):
        raise DoubanResponseBoundaryOverlayError(
            "Douban request must keep parsing inside the JSON response owner"
        )
    session_calls = _session_calls(method, "owner", "get")
    if len(session_calls) != 1:
        raise DoubanResponseBoundaryOverlayError(
            "Douban transport get owner must remain exactly once"
        )
    _audit_redirect_disabled(session_calls[0], "Douban transport get")
    _audit_json_call(_calls(method, "_json_response")[0], "Douban JSON response")


def _audit_douban_action(tree):
    method = _method(tree, "Spider", "_v80_action_unbounded")
    for name in (
        "_json_response",
        "v80_validate_json_shape",
        "_v80_timeout_child_scope",
        "request_timeout",
        "track",
        "close_tracked",
    ):
        if len(_calls(method, name)) != 1:
            raise DoubanResponseBoundaryOverlayError(
                "Douban action owner %s must appear exactly once" % name
            )
    if _calls(method, "_read_bounded_json_shared") or _calls(method, "json"):
        raise DoubanResponseBoundaryOverlayError(
            "Douban action must keep parsing inside the JSON response owner"
        )
    session_calls = _session_calls(method, "self", "post")
    if len(session_calls) != 1:
        raise DoubanResponseBoundaryOverlayError(
            "Douban action post owner must remain exactly once"
        )
    _audit_redirect_disabled(session_calls[0], "Douban action post")
    _audit_json_call(_calls(method, "_json_response")[0], "Douban action response")

    assignments = {
        target.id: node
        for node in ast.walk(method)
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name)
        and target.id in ("action_success", "action_auth_failed")
    }
    if set(assignments) != {"action_success", "action_auth_failed"}:
        raise DoubanResponseBoundaryOverlayError(
            "Douban action ordering guards must remain explicit"
        )
    guarded_validation = [
        node for node in ast.walk(method)
        if isinstance(node, ast.If)
        and isinstance(node.test, ast.UnaryOp)
        and isinstance(node.test.op, ast.Not)
        and isinstance(node.test.operand, ast.Name)
        and node.test.operand.id == "action_auth_failed"
        and any(_calls(statement, "v80_validate_json_shape") for statement in node.body)
    ]
    if len(guarded_validation) != 1:
        raise DoubanResponseBoundaryOverlayError(
            "Douban action authentication message ordering is not preserved"
        )


def apply_douban_response_boundary_overlay(source):
    try:
        text = bytes(source).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise DoubanResponseBoundaryOverlayError(
            "Douban response boundary input is not valid UTF-8"
        ) from exc
    input_bytes = text.encode("utf-8")
    for label, anchor, replacement in INSERTIONS:
        text = _replace_once(text, anchor, replacement, label)

    try:
        tree = ast.parse(text, filename="build/v80-dev/douban-response-boundary.py")
        compile(tree, "build/v80-dev/douban-response-boundary.py", "exec")
    except SyntaxError as exc:
        raise DoubanResponseBoundaryOverlayError(
            "Douban response boundary output is invalid: %s" % exc
        ) from exc
    _audit_douban_request(tree)
    _audit_douban_action(tree)

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
        "import apply_douban_response_boundary_overlay from the V80 build pipeline"
    )


if __name__ == "__main__":
    main()

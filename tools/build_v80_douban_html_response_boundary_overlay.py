"""Apply a bounded streaming read to the Douban HTML request owner."""

import ast
import hashlib


class DoubanHtmlResponseBoundaryOverlayError(RuntimeError):
    pass


DOUBAN_TEXT_ANCHOR = '''    def request_text(self, url, params=None):
        owner = self.owner
        with owner._v80_timeout_child_scope("douban_text", owner.timeout) as operation:
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
                if response.status_code != 200:
                    raise RuntimeError("HTTP %s" % response.status_code)
                text = response.text
                if len(text) < 500:
                    raise RuntimeError("页面内容异常短")
                return text
            finally:
                operation.close_tracked(response)
'''

DOUBAN_TEXT_REPLACEMENT = '''    def request_text(self, url, params=None):
        owner = self.owner
        with owner._v80_timeout_child_scope("douban_text", owner.timeout) as operation:
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
                if response.status_code != 200:
                    raise RuntimeError("HTTP %s" % response.status_code)
                max_bytes = V80_DOUBAN_HTML_RESPONSE_LIMITS["max_response_bytes"]
                try:
                    content_length = int(
                        (getattr(response, "headers", {}) or {}).get(
                            "Content-Length", 0,
                        ) or 0
                    )
                except Exception:
                    content_length = 0
                if content_length > max_bytes:
                    raise RuntimeError("豆瓣页面响应过大")
                chunks = []
                received = 0
                for chunk in response.iter_content(chunk_size=65536):
                    if operation.deadline is not None and time.monotonic() >= operation.deadline:
                        raise RuntimeError("豆瓣页面响应超过总时限")
                    if not chunk:
                        continue
                    received += len(chunk)
                    if received > max_bytes:
                        raise RuntimeError("豆瓣页面响应过大")
                    chunks.append(chunk)
                response._content = b"".join(chunks)
                response._content_consumed = True
                text = response.text
                if len(text) < 500:
                    raise RuntimeError("页面内容异常短")
                return text
            finally:
                operation.close_tracked(response)
'''

DOUBAN_USER_ID_ANCHOR = '''    def _resolve_user_id(self):
        if self.user_id:
            return self.user_id
        if not self.cookie:
            return ""
        try:
            with self._v80_timeout_child_scope("douban_user", self.timeout) as operation:
                response = self._session.get(
                    "https://www.douban.com/mine/",
                    timeout=operation.request_timeout(
                        self.timeout, retry_policy=GENERAL_TRANSPORT_RETRY_POLICY,
                    ),
                    verify=self.verify_tls,
                    allow_redirects=True,
                    stream=True,
                )
                operation.track(response)
                try:
                    match = re.search(r"/people/([^/?#]+)/?", response.url)
                    if not match:
                        match = re.search(r"https?://www\\.douban\\.com/people/([^/?#]+)/?", response.text)
                    if match:
                        self.user_id = match.group(1)
                finally:
                    operation.close_tracked(response)
        except Exception:
            pass
        return self.user_id
'''

DOUBAN_USER_ID_REPLACEMENT = '''    def _resolve_user_id(self):
        if self.user_id:
            return self.user_id
        if not self.cookie:
            return ""
        try:
            with self._v80_timeout_child_scope("douban_user", self.timeout) as operation:
                response = self._session.get(
                    "https://www.douban.com/mine/",
                    timeout=operation.request_timeout(
                        self.timeout, retry_policy=GENERAL_TRANSPORT_RETRY_POLICY,
                    ),
                    verify=self.verify_tls,
                    allow_redirects=False,
                    stream=True,
                )
                operation.track(response)
                try:
                    match = None
                    if 300 <= response.status_code < 400:
                        location = str(
                            (getattr(response, "headers", {}) or {}).get(
                                "Location", "",
                            ) or ""
                        ).strip()
                        target = urlparse(urljoin(
                            "https://www.douban.com/mine/", location,
                        ))
                        if (
                                target.scheme == "https"
                                and target.hostname == "www.douban.com"
                                and target.port in (None, 443)):
                            match = re.match(r"^/people/([^/?#]+)/?", target.path)
                    elif response.status_code == 200:
                        response_url = str(getattr(response, "url", "") or "")
                        match = re.search(r"/people/([^/?#]+)/?", response_url)
                        if not match:
                            max_bytes = V80_DOUBAN_HTML_RESPONSE_LIMITS["max_response_bytes"]
                            try:
                                content_length = int(
                                    (getattr(response, "headers", {}) or {}).get(
                                        "Content-Length", 0,
                                    ) or 0
                                )
                            except Exception:
                                content_length = 0
                            if content_length > max_bytes:
                                raise RuntimeError("豆瓣页面响应过大")
                            chunks = []
                            received = 0
                            for chunk in response.iter_content(chunk_size=65536):
                                if operation.deadline is not None and time.monotonic() >= operation.deadline:
                                    raise RuntimeError("豆瓣页面响应超过总时限")
                                if not chunk:
                                    continue
                                received += len(chunk)
                                if received > max_bytes:
                                    raise RuntimeError("豆瓣页面响应过大")
                                chunks.append(chunk)
                            response._content = b"".join(chunks)
                            response._content_consumed = True
                            match = re.search(
                                r"https?://www\\.douban\\.com/people/([^/?#]+)/?",
                                response.text,
                            )
                    if match:
                        self.user_id = match.group(1)
                finally:
                    operation.close_tracked(response)
        except Exception:
            pass
        return self.user_id
'''

INSERTIONS = (
    (
        "douban-html-response-boundary",
        DOUBAN_TEXT_ANCHOR,
        DOUBAN_TEXT_REPLACEMENT,
    ),
    (
        "douban-user-id-response-boundary",
        DOUBAN_USER_ID_ANCHOR,
        DOUBAN_USER_ID_REPLACEMENT,
    ),
)


def _replace_once(text, anchor, replacement, label):
    count = text.count(anchor)
    if count != 1:
        raise DoubanHtmlResponseBoundaryOverlayError(
            "Douban HTML response boundary anchor %s must appear once, found %d"
            % (label, count)
        )
    return text.replace(anchor, replacement, 1)


def _method(tree, class_name, method_name):
    classes = [
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == class_name
    ]
    if len(classes) != 1:
        raise DoubanHtmlResponseBoundaryOverlayError(
            "expected one %s class" % class_name
        )
    methods = [
        node for node in classes[0].body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == method_name
    ]
    if len(methods) != 1:
        raise DoubanHtmlResponseBoundaryOverlayError(
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


def _session_get_calls(method, owner_name):
    return [
        node for node in ast.walk(method)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "get"
        and isinstance(node.func.value, ast.Attribute)
        and node.func.value.attr == "_session"
        and isinstance(node.func.value.value, ast.Name)
        and node.func.value.value.id == owner_name
    ]


def _response_attributes(method, name, context=None):
    nodes = []
    for node in ast.walk(method):
        if not (
                isinstance(node, ast.Attribute)
                and node.attr == name
                and isinstance(node.value, ast.Name)
                and node.value.id == "response"):
            continue
        if context is None or isinstance(node.ctx, context):
            nodes.append(node)
    return nodes


def _audit_request_text(tree):
    method = _method(tree, "_DoubanClient", "request_text")
    for name in (
        "_v80_timeout_child_scope",
        "request_timeout",
        "track",
        "iter_content",
        "close_tracked",
    ):
        if len(_calls(method, name)) != 1:
            raise DoubanHtmlResponseBoundaryOverlayError(
                "Douban HTML request owner %s must appear exactly once" % name
            )
    session_calls = _session_get_calls(method, "owner")
    if len(session_calls) != 1:
        raise DoubanHtmlResponseBoundaryOverlayError(
            "Douban HTML transport get owner must remain exactly once"
        )
    _audit_redirect_disabled(session_calls[0], "Douban HTML transport")
    for forbidden in (
        "_read_bounded_json_shared",
        "_json_response",
        "decode",
        "json",
        "close",
    ):
        if _calls(method, forbidden):
            raise DoubanHtmlResponseBoundaryOverlayError(
                "Douban HTML request must not add %s ownership" % forbidden
            )

    policy_refs = [
        node for node in ast.walk(method)
        if isinstance(node, ast.Subscript)
        and isinstance(node.value, ast.Name)
        and node.value.id == "V80_DOUBAN_HTML_RESPONSE_LIMITS"
    ]
    if len(policy_refs) != 1:
        raise DoubanHtmlResponseBoundaryOverlayError(
            "Douban HTML byte limit must come from the leaf policy exactly once"
        )
    text_reads = _response_attributes(method, "text", ast.Load)
    content_writes = _response_attributes(method, "_content", ast.Store)
    consumed_writes = _response_attributes(method, "_content_consumed", ast.Store)
    if len(text_reads) != 1 or len(content_writes) != 1 or len(consumed_writes) != 1:
        raise DoubanHtmlResponseBoundaryOverlayError(
            "Douban HTML request must rebuild one Requests content body before one text decode"
        )

    content_length = [
        node for node in ast.walk(method)
        if isinstance(node, ast.Constant) and node.value == "Content-Length"
    ]
    if len(content_length) != 1:
        raise DoubanHtmlResponseBoundaryOverlayError(
            "Douban HTML request must inspect Content-Length exactly once"
        )
    monotonic = [
        node for node in _calls(method, "monotonic")
        if isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "time"
    ]
    if len(monotonic) != 1:
        raise DoubanHtmlResponseBoundaryOverlayError(
            "Douban HTML request must reuse the operation deadline exactly once"
        )

    with_nodes = [node for node in method.body if isinstance(node, ast.With)]
    if len(with_nodes) != 1:
        raise DoubanHtmlResponseBoundaryOverlayError(
            "Douban HTML request must retain one timeout scope"
        )
    try_nodes = [node for node in with_nodes[0].body if isinstance(node, ast.Try)]
    if len(try_nodes) != 1 or not try_nodes[0].body:
        raise DoubanHtmlResponseBoundaryOverlayError(
            "Douban HTML request must retain one close-protected body"
        )
    first = try_nodes[0].body[0]
    if not isinstance(first, ast.If):
        raise DoubanHtmlResponseBoundaryOverlayError(
            "Douban HTML HTTP status must be checked before body metadata"
        )
    iter_call = _calls(method, "iter_content")[0]
    if not (
            first.lineno < content_length[0].lineno < iter_call.lineno
            < content_writes[0].lineno < text_reads[0].lineno):
        raise DoubanHtmlResponseBoundaryOverlayError(
            "Douban HTML status, byte read, content rebuild, and decode ordering changed"
        )
    short_messages = [
        node for node in ast.walk(method)
        if isinstance(node, ast.Constant) and node.value == "页面内容异常短"
    ]
    if len(short_messages) != 1 or short_messages[0].lineno <= text_reads[0].lineno:
        raise DoubanHtmlResponseBoundaryOverlayError(
            "Douban HTML short-page validation must remain after decoding"
        )


def _audit_redirect_disabled(call, owner_label):
    keyword_values = {keyword.arg: keyword.value for keyword in call.keywords}
    allow_redirects = keyword_values.get("allow_redirects")
    if not (
            isinstance(allow_redirects, ast.Constant)
            and allow_redirects.value is False):
        raise DoubanHtmlResponseBoundaryOverlayError(
            "%s must disable Requests automatic redirects" % owner_label
        )


def _audit_resolve_user_id(tree):
    method = _method(tree, "Spider", "_resolve_user_id")
    for name, count in (
        ("_v80_timeout_child_scope", 1),
        ("request_timeout", 1),
        ("track", 1),
        ("iter_content", 1),
        ("close_tracked", 1),
        ("urljoin", 1),
        ("urlparse", 1),
    ):
        if len(_calls(method, name)) != count:
            raise DoubanHtmlResponseBoundaryOverlayError(
                "Douban user-id owner %s must appear exactly %d time(s)"
                % (name, count)
            )
    session_calls = _session_get_calls(method, "self")
    if len(session_calls) != 1:
        raise DoubanHtmlResponseBoundaryOverlayError(
            "Douban user-id transport get owner must remain exactly once"
        )
    _audit_redirect_disabled(session_calls[0], "Douban user-id transport")

    policy_refs = [
        node for node in ast.walk(method)
        if isinstance(node, ast.Subscript)
        and isinstance(node.value, ast.Name)
        and node.value.id == "V80_DOUBAN_HTML_RESPONSE_LIMITS"
    ]
    if len(policy_refs) != 1:
        raise DoubanHtmlResponseBoundaryOverlayError(
            "Douban user-id byte limit must reuse the HTML leaf policy once"
        )
    if len(_response_attributes(method, "text", ast.Load)) != 1:
        raise DoubanHtmlResponseBoundaryOverlayError(
            "Douban user-id 200 response must decode one bounded body"
        )
    if len(_response_attributes(method, "_content", ast.Store)) != 1:
        raise DoubanHtmlResponseBoundaryOverlayError(
            "Douban user-id 200 response must rebuild one bounded body"
        )
    if len(_response_attributes(method, "_content_consumed", ast.Store)) != 1:
        raise DoubanHtmlResponseBoundaryOverlayError(
            "Douban user-id response must mark one bounded body consumed"
        )
    if len(_calls(method, "monotonic")) != 1:
        raise DoubanHtmlResponseBoundaryOverlayError(
            "Douban user-id bounded read must reuse the operation deadline"
        )
    for forbidden in ("requests", "Session", "Retry", "HTTPAdapter"):
        if _calls(method, forbidden):
            raise DoubanHtmlResponseBoundaryOverlayError(
                "Douban user-id owner must not add %s" % forbidden
            )


def apply_douban_html_response_boundary_overlay(source):
    try:
        text = bytes(source).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise DoubanHtmlResponseBoundaryOverlayError(
            "Douban HTML response boundary input is not valid UTF-8"
        ) from exc
    input_bytes = text.encode("utf-8")
    for label, anchor, replacement in INSERTIONS:
        text = _replace_once(text, anchor, replacement, label)

    try:
        tree = ast.parse(text, filename="build/v80-dev/douban-html-response-boundary.py")
        compile(tree, "build/v80-dev/douban-html-response-boundary.py", "exec")
    except SyntaxError as exc:
        raise DoubanHtmlResponseBoundaryOverlayError(
            "Douban HTML response boundary output is invalid: %s" % exc
        ) from exc
    _audit_request_text(tree)
    _audit_resolve_user_id(tree)

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
        "import apply_douban_html_response_boundary_overlay from the V80 build pipeline"
    )


if __name__ == "__main__":
    main()

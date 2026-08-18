"""Insert P3 end-to-end timeout and lifecycle cancellation seams into V80."""

import ast
import hashlib


class TimeoutBudgetOverlayError(RuntimeError):
    pass


BOUNDED_JSON_ANCHOR = '''def _read_bounded_json_shared(response, label, max_bytes, deadline=None):
    try:
        try:
            content_length = int((getattr(response, "headers", {}) or {}).get("Content-Length") or 0)
        except Exception:
            content_length = 0
        if content_length > max_bytes:
            raise RuntimeError("%s 响应过大" % label)
        chunks = []
        received = 0
        iterator = getattr(response, "iter_content", None)
        parts = iterator(chunk_size=65536) if callable(iterator) else [getattr(response, "content", b"")]
        for chunk in parts:
            if deadline is not None and time.monotonic() >= deadline:
                raise RuntimeError("%s 响应超过总时限" % label)
            if not chunk:
                continue
            received += len(chunk)
            if received > max_bytes:
                raise RuntimeError("%s 响应过大" % label)
            chunks.append(chunk)
        try:
            return json.loads(b"".join(chunks))
        except Exception:
            raise RuntimeError("%s 返回无效 JSON" % label)
    finally:
        closer = getattr(response, "close", None)
        if callable(closer):
            closer()
'''

BOUNDED_JSON_REPLACEMENT = BOUNDED_JSON_ANCHOR.replace(
    "def _read_bounded_json_shared(response, label, max_bytes, deadline=None):",
    "def _read_bounded_json_shared(\n"
    "        response, label, max_bytes, deadline=None, close_response=True):",
).replace(
    '''    finally:
        closer = getattr(response, "close", None)
        if callable(closer):
            closer()
''',
    '''    finally:
        if close_response:
            closer = getattr(response, "close", None)
            if callable(closer):
                closer()
''',
)

DOUBAN_CLIENT_ANCHOR = '''    def request_json(self, url, params=None):
        owner = self.owner
        response = owner._session.get(
            url, params=params, timeout=owner.timeout, verify=owner.verify_tls,
        )
        payload = owner._json_response(response)
        if response.status_code != 200:
            raise RuntimeError("HTTP %s" % response.status_code)
        return payload

    def request_text(self, url, params=None):
        owner = self.owner
        response = owner._session.get(
            url, params=params, timeout=owner.timeout, verify=owner.verify_tls,
        )
        if response.status_code != 200:
            raise RuntimeError("HTTP %s" % response.status_code)
        text = response.text
        if len(text) < 500:
            raise RuntimeError("页面内容异常短")
        return text
'''

DOUBAN_CLIENT_REPLACEMENT = '''    def request_json(self, url, params=None):
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

    def request_text(self, url, params=None):
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

STATE_ANCHOR = '''        self._background_bulkhead_controller = BackgroundBulkheadController(
            generation=self._cache_generation,
        )
'''

STATE_REPLACEMENT = STATE_ANCHOR + '''        self._timeout_budget_controller = TimeoutBudgetController(
            generation=self._cache_generation,
        )
'''

TIMEOUT_HELPER_ANCHOR = '''    def _submit_background_bulkhead_task(
            self, lane, generation, worker, name, executor=None):
'''

TIMEOUT_HELPER_REPLACEMENT = '''    def _v80_timeout_child_scope(self, operation, timeout_seconds, deadline=None):
        controller = self._timeout_budget_controller
        parent = controller.current(required=False)
        generation = parent.generation if parent is not None else self._cache_generation
        budget = parent.remaining() if parent is not None else timeout_seconds
        return controller.scope(
            operation, budget, expected_generation=generation, deadline=deadline,
        )

    def _v80_timeout_request_timeout(
            self, default_timeout, requests_left=1, retry_policy=None):
        return self._timeout_budget_controller.current().request_timeout(
            default_timeout,
            requests_left=requests_left,
            retry_policy=retry_policy,
        )

''' + TIMEOUT_HELPER_ANCHOR

BACKGROUND_GUARD_ANCHOR = '''        def guarded():
            try:
                return worker()
            finally:
                lease.finish()
'''

BACKGROUND_GUARD_REPLACEMENT = '''        budget_seconds = {
            "resource_completion": self.RESOURCE_HOT_VALIDATION_BUDGET,
            "history": self.RESOURCE_DETAIL_BUDGET,
            "route_probe": self.RESOURCE_FOREGROUND_BUDGET,
        }[lane]

        def guarded():
            try:
                with self._timeout_budget_controller.scope(
                        "background_%s" % lane,
                        budget_seconds,
                        expected_generation=generation):
                    return worker()
            finally:
                lease.finish()
'''

INIT_RESET_ANCHOR = '''                self._cache_generation += 1
                self._background_bulkhead_controller.reset(self._cache_generation)
                self._resource_candidate_shadow_sampled_generation = None
'''

INIT_RESET_REPLACEMENT = '''                self._cache_generation += 1
                self._timeout_budget_controller.reset(
                    self._cache_generation, closed=False,
                )
                self._background_bulkhead_controller.reset(self._cache_generation)
                self._resource_candidate_shadow_sampled_generation = None
'''

DESTROY_RESET_ANCHOR = '''                    self._cache_generation += 1
                    self._background_bulkhead_controller.reset(self._cache_generation)
                    provider_controller = getattr(self, "_provider_reliability_controller", None)
'''

DESTROY_RESET_REPLACEMENT = '''                    self._cache_generation += 1
                    self._timeout_budget_controller.reset(
                        self._cache_generation, closed=True,
                    )
                    self._background_bulkhead_controller.reset(self._cache_generation)
                    provider_controller = getattr(self, "_provider_reliability_controller", None)
'''


def _method_wrapper(anchor, public_name, private_name, operation, budget, arguments=""):
    call_arguments = arguments
    return '''    def {public_name}(self{signature}):
        with self._timeout_budget_controller.scope(
                "{operation}", {budget},
                expected_generation=self._cache_generation):
            return self.{private_name}({call_arguments})

    def {private_name}(self{signature}):
'''.format(
        public_name=public_name,
        private_name=private_name,
        operation=operation,
        budget=budget,
        signature=anchor[len("    def " + public_name + "(self"):-3],
        call_arguments=call_arguments,
    )


HOME_ANCHOR = '''    def homeVideoContent(self):
'''
HOME_REPLACEMENT = _method_wrapper(
    HOME_ANCHOR, "homeVideoContent", "_v80_homeVideoContent_unbounded",
    "home_video", "self.RESOURCE_SEARCH_BUDGET",
)

CATEGORY_ANCHOR = '''    def categoryContent(self, tid, pg, filter=False, extend=None):
'''
CATEGORY_REPLACEMENT = _method_wrapper(
    CATEGORY_ANCHOR, "categoryContent", "_v80_categoryContent_unbounded",
    "category", "self.RESOURCE_FOREGROUND_BUDGET", "tid, pg, filter, extend",
)

DETAIL_ANCHOR = '''    def detailContent(self, ids):
'''
DETAIL_REPLACEMENT = _method_wrapper(
    DETAIL_ANCHOR, "detailContent", "_v80_detailContent_unbounded",
    "detail", "self.RESOURCE_DETAIL_BUDGET", "ids",
)

SEARCH_ANCHOR = '''    def searchContent(self, key, quick=False, pg="1"):
'''
SEARCH_REPLACEMENT = _method_wrapper(
    SEARCH_ANCHOR, "searchContent", "_v80_searchContent_unbounded",
    "search", "self.RESOURCE_SEARCH_BUDGET", "key, quick, pg",
)

PLAYER_ANCHOR = '''    def playerContent(self, flag, id, vipFlags=None):
'''
PLAYER_REPLACEMENT = _method_wrapper(
    PLAYER_ANCHOR, "playerContent", "_v80_playerContent_unbounded",
    "player", "self.FOLLOWPLAY_PLAY_BUDGET", "flag, id, vipFlags",
)

ACTION_ANCHOR = '''    def action(self, action):
'''
ACTION_REPLACEMENT = _method_wrapper(
    ACTION_ANCHOR, "action", "_v80_action_unbounded",
    "action", "self.RESOURCE_DETAIL_BUDGET", "action",
)

WISH_POST_ANCHOR = '''            response = self._session.post(url, headers=headers, data=data, timeout=self.timeout, verify=self.verify_tls)
            payload = self._json_response(response)
            if response.status_code == 200 and str(payload.get("r", "0")) == "0":
                self._drop_cache_prefix("wishlist:")
                return json.dumps({"msg": "已加入豆瓣想看"}, ensure_ascii=False)
            if response.status_code in (401, 403) or str(payload.get("code", "")) == "403":
                message = "豆瓣登录已失效，请更新 Cookie/ck"
            else:
                message = str(payload.get("msg") or payload.get("error") or "豆瓣未确认收藏成功")
            return json.dumps({"msg": message}, ensure_ascii=False)
'''

WISH_POST_REPLACEMENT = '''            with self._v80_timeout_child_scope("douban_wish", self.timeout) as operation:
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

CHECKED_ROWS_ANCHOR = '''    def _checked_resource_rows(self, rows, deadline=None):
'''
CHECKED_ROWS_REPLACEMENT = '''    def _checked_resource_rows(self, rows, deadline=None):
        with self._v80_timeout_child_scope(
                "checked_resource_rows", self.RESOURCE_DETAIL_BUDGET,
                deadline=deadline) as operation:
            return self._v80_checked_resource_rows_unbounded(
                rows, deadline=operation.deadline,
            )

    def _v80_checked_resource_rows_unbounded(self, rows, deadline=None):
'''

BOUNDED_READER_ANCHOR = '''    def _read_bounded_json_response(self, response, label, deadline=None, max_bytes=None):
        max_bytes = self._positive_int(max_bytes, 0) or self.RESOURCE_API_RESPONSE_MAX_BYTES
        return _read_bounded_json_shared(response, label, max_bytes, deadline=deadline)
'''

BOUNDED_READER_REPLACEMENT = '''    def _read_bounded_json_response(self, response, label, deadline=None, max_bytes=None):
        max_bytes = self._positive_int(max_bytes, 0) or self.RESOURCE_API_RESPONSE_MAX_BYTES
        with self._v80_timeout_child_scope(
                "bounded_json", self.timeout, deadline=deadline) as operation:
            operation.track(response)
            try:
                return _read_bounded_json_shared(
                    response,
                    label,
                    max_bytes,
                    deadline=operation.deadline,
                    close_response=False,
                )
            finally:
                operation.close_tracked(response)
'''

RESOURCE_API_ANCHOR = '''    def _resource_api_get(self, mode, params, deadline=None):
'''
RESOURCE_API_REPLACEMENT = '''    def _resource_api_get(self, mode, params, deadline=None):
        with self._v80_timeout_child_scope(
                "resource_api_get", self.RESOURCE_SEARCH_BUDGET,
                deadline=deadline) as operation:
            return self._v80_resource_api_get_unbounded(
                mode, params, deadline=operation.deadline,
            )

    def _v80_resource_api_get_unbounded(self, mode, params, deadline=None):
'''

ATVP_PLAY_ANCHOR = '''    def _atvp_play(self, play_id, timeout_seconds=None, deadline=None,
                   expected_generation=None, expected_backend=None):
'''
ATVP_PLAY_REPLACEMENT = '''    def _atvp_play(self, play_id, timeout_seconds=None, deadline=None,
                   expected_generation=None, expected_backend=None):
        budget = timeout_seconds if timeout_seconds is not None else max(30, self.timeout)
        with self._v80_timeout_child_scope(
                "atvp_play", budget, deadline=deadline) as operation:
            return self._v80_atvp_play_unbounded(
                play_id,
                timeout_seconds=timeout_seconds,
                deadline=operation.deadline,
                expected_generation=expected_generation,
                expected_backend=expected_backend,
            )

    def _v80_atvp_play_unbounded(self, play_id, timeout_seconds=None, deadline=None,
                   expected_generation=None, expected_backend=None):
'''

ATVP_PARSE_ANCHOR = '''    def _atvp_parse_candidates(self, resource_url, timeout_seconds=None, deadline=None,
                               request_api=None, request_token=None, request_session=None):
'''
ATVP_PARSE_REPLACEMENT = '''    def _atvp_parse_candidates(self, resource_url, timeout_seconds=None, deadline=None,
                               request_api=None, request_token=None, request_session=None):
        budget = timeout_seconds if timeout_seconds is not None else max(35, self.timeout)
        with self._v80_timeout_child_scope(
                "atvp_parse", budget, deadline=deadline) as operation:
            return self._v80_atvp_parse_candidates_unbounded(
                resource_url,
                timeout_seconds=timeout_seconds,
                deadline=operation.deadline,
                request_api=request_api,
                request_token=request_token,
                request_session=request_session,
            )

    def _v80_atvp_parse_candidates_unbounded(
            self, resource_url, timeout_seconds=None, deadline=None,
            request_api=None, request_token=None, request_session=None):
'''

PINNED_BLOCKING_SIGNATURE_ANCHOR = '''    def _pinned_media_request_blocking(self, parsed, address, headers, deadline, control=None):
'''
PINNED_BLOCKING_SIGNATURE_REPLACEMENT = '''    def _pinned_media_request_blocking(
            self, parsed, address, headers, deadline, control=None,
            timeout_operation=None):
'''

PINNED_CONNECTION_ANCHOR = '''        connection = connection_type(host, address, port=port, **kwargs)
        if isinstance(control, dict):
            control["connection"] = connection
        try:
'''
PINNED_CONNECTION_REPLACEMENT = '''        connection = connection_type(host, address, port=port, **kwargs)
        try:
            if timeout_operation is not None:
                timeout_operation.track(connection)
            if isinstance(control, dict):
                control["connection"] = connection
'''

PINNED_CLOSE_ANCHOR = '''        finally:
            connection.close()
            if isinstance(control, dict):
                control.pop("connection", None)
'''
PINNED_CLOSE_REPLACEMENT = '''        finally:
            if timeout_operation is None:
                connection.close()
            else:
                timeout_operation.close_tracked(connection)
            if isinstance(control, dict):
                control.pop("connection", None)
'''

PINNED_SUBMIT_ANCHOR = '''        control = {}
        try:
            future = _MEDIA_PROBE_EXECUTOR.submit(
                self._pinned_media_request_blocking,
                parsed, address, headers, deadline, control,
            )
'''
PINNED_SUBMIT_REPLACEMENT = '''        control = {}
        timeout_operation = self._timeout_budget_controller.current(required=False)
        try:
            future = _MEDIA_PROBE_EXECUTOR.submit(
                self._pinned_media_request_blocking,
                parsed, address, headers, deadline, control, timeout_operation,
            )
'''

PINNED_TIMEOUT_CLOSE_ANCHOR = '''            connection = control.get("connection")
            if connection is not None:
                try:
                    connection.close()
                except Exception:
                    pass
            future.cancel()
'''
PINNED_TIMEOUT_CLOSE_REPLACEMENT = '''            connection = control.get("connection")
            if connection is not None:
                if timeout_operation is None:
                    try:
                        connection.close()
                    except Exception:
                        pass
                else:
                    timeout_operation.close_tracked(connection)
            future.cancel()
'''

PROBE_ANCHOR = '''    def _probe_media_output(self, output, deadline=None):
'''
PROBE_REPLACEMENT = '''    def _probe_media_output(self, output, deadline=None):
        with self._v80_timeout_child_scope(
                "probe_media", self.RESOURCE_FOREGROUND_BUDGET,
                deadline=deadline) as operation:
            return self._v80_probe_media_output_unbounded(
                output, deadline=operation.deadline,
            )

    def _v80_probe_media_output_unbounded(self, output, deadline=None):
'''

TMDB_REQUEST_ANCHOR = '''    def _request_tmdb(self, path, query):
        response = self._tmdb_session.get(
            self.tmdb_api_base + path,
            params=query,
            timeout=self.timeout,
            verify=self.verify_tls,
        )
        data = self._json_response(response)
        if response.status_code in (401, 403):
            raise RuntimeError("TMDB API 凭据无效或无权访问")
        if response.status_code == 429:
            raise RuntimeError("TMDB API 请求过于频繁，请稍后刷新")
        if response.status_code != 200:
            raise RuntimeError(str(data.get("status_message") or "TMDB HTTP %s" % response.status_code))
        return data
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
                return data
            finally:
                operation.close_tracked(response)
'''

RETRY_ADAPTER_ANCHOR = '''    @staticmethod
    def _retry_adapter():
        try:
            from requests.packages.urllib3.util.retry import Retry
            retry = Retry(
                total=1,
                connect=1,
                read=0,
                status=1,
                backoff_factor=0.2,
                status_forcelist=(429, 500, 502, 503, 504),
                allowed_methods=frozenset(("GET",)),
            )
            return HTTPAdapter(max_retries=retry, pool_connections=8, pool_maxsize=8)
        except TypeError:
            return HTTPAdapter(max_retries=1, pool_connections=8, pool_maxsize=8)
'''

RETRY_ADAPTER_REPLACEMENT = '''    @staticmethod
    def _retry_adapter():
        return v80_timeout_general_retry_adapter()
'''

RESOLVE_USER_ANCHOR = '''    def _resolve_user_id(self):
        if self.user_id:
            return self.user_id
        if not self.cookie:
            return ""
        try:
            response = self._session.get("https://www.douban.com/mine/", timeout=self.timeout, verify=self.verify_tls, allow_redirects=True)
            match = re.search(r"/people/([^/?#]+)/?", response.url)
            if not match:
                match = re.search(r"https?://www\\.douban\\.com/people/([^/?#]+)/?", response.text)
            if match:
                self.user_id = match.group(1)
        except Exception:
            pass
        return self.user_id
'''

RESOLVE_USER_REPLACEMENT = '''    def _resolve_user_id(self):
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

LEGACY_HISTORY_REQUEST_ANCHOR = '''    def _atvp_history_request(self, method, **kwargs):
'''
LEGACY_HISTORY_REQUEST_REPLACEMENT = '''    def _atvp_history_request(self, method, **kwargs):
        with self._v80_timeout_child_scope(
                "history_legacy_request", self.RESOURCE_DETAIL_BUDGET) as operation:
            return self._v80_atvp_history_request_unbounded(
                method, _v80_timeout_operation=operation, **kwargs
            )

    def _v80_atvp_history_request_unbounded(
            self, method, _v80_timeout_operation=None, **kwargs):
'''

LEGACY_HISTORY_KWARGS_ANCHOR = '''        request_kwargs = {
            "timeout": self.timeout,
            "verify": self.verify_tls,
        }
        request_kwargs.update(kwargs)
        request_kwargs.setdefault("stream", True)
'''
LEGACY_HISTORY_KWARGS_REPLACEMENT = '''        request_kwargs = {"verify": self.verify_tls}
        request_kwargs.update(kwargs)
        request_kwargs.setdefault("stream", True)
        retry_policy = ATVP_TRANSPORT_RETRY_POLICY if method_name == "get" else None
'''

LEGACY_HISTORY_SEND_ANCHOR = '''                response = sender(
                    self._atvp_history_endpoint(origin),
                    **request_kwargs
                )
'''
LEGACY_HISTORY_SEND_REPLACEMENT = '''                request_kwargs["timeout"] = _v80_timeout_operation.request_timeout(
                    request_kwargs.get("timeout", self.timeout),
                    retry_policy=retry_policy,
                )
                response = sender(
                    self._atvp_history_endpoint(origin),
                    **request_kwargs
                )
'''

LEGACY_HISTORY_REAUTH_SEND_ANCHOR = '''        return sender(
            self._atvp_history_endpoint(self._history_selected_origin or selected_origin),
            **request_kwargs
        )
'''
LEGACY_HISTORY_REAUTH_SEND_REPLACEMENT = '''        request_kwargs["timeout"] = _v80_timeout_operation.request_timeout(
            request_kwargs.get("timeout", self.timeout),
            retry_policy=retry_policy,
        )
        return sender(
            self._atvp_history_endpoint(self._history_selected_origin or selected_origin),
            **request_kwargs
        )
'''

LEGACY_HISTORY_LOGIN_ANCHOR = '''    def _atvp_history_login(self, force=False):
'''
LEGACY_HISTORY_LOGIN_REPLACEMENT = '''    def _atvp_history_login(self, force=False):
        with self._v80_timeout_child_scope(
                "history_legacy_login", self.RESOURCE_DETAIL_BUDGET) as operation:
            return self._v80_atvp_history_login_unbounded(
                force=force, _v80_timeout_operation=operation,
            )

    def _v80_atvp_history_login_unbounded(
            self, force=False, _v80_timeout_operation=None):
'''

LEGACY_HISTORY_LOGIN_TIMEOUT_ANCHOR = '''                response = self._atvp_session.post(
                    self._http_base(origin, "").rstrip("/") + "/api/accounts/login",
                    json={"username": self.history_username, "password": self.history_password},
                    timeout=self.timeout,
                    verify=self.verify_tls,
                    stream=True,
                )
'''
LEGACY_HISTORY_LOGIN_TIMEOUT_REPLACEMENT = '''                response = self._atvp_session.post(
                    self._http_base(origin, "").rstrip("/") + "/api/accounts/login",
                    json={"username": self.history_username, "password": self.history_password},
                    timeout=_v80_timeout_operation.request_timeout(self.timeout),
                    verify=self.verify_tls,
                    stream=True,
                )
'''

V145_LOGIN_ANCHOR = '''def _v80_history_login(owner, origin, force=False):
'''
V145_LOGIN_REPLACEMENT = '''def _v80_history_login(owner, origin, force=False):
    with owner._v80_timeout_child_scope(
            "history_login", owner.RESOURCE_DETAIL_BUDGET) as operation:
        return _v80_history_login_unbounded(
            owner, origin, force=force, _v80_timeout_operation=operation,
        )


def _v80_history_login_unbounded(
        owner, origin, force=False, _v80_timeout_operation=None):
'''

V145_LOGIN_TIMEOUT_ANCHOR = '''    response = owner._atvp_session.post(
        _v80_history_endpoint(origin, "/api/accounts/login"),
        json={"username": owner.history_username, "password": owner.history_password},
        timeout=owner.timeout,
        verify=owner.verify_tls,
        stream=True,
        allow_redirects=False,
    )
'''
V145_LOGIN_TIMEOUT_REPLACEMENT = '''    response = owner._atvp_session.post(
        _v80_history_endpoint(origin, "/api/accounts/login"),
        json={"username": owner.history_username, "password": owner.history_password},
        timeout=_v80_timeout_operation.request_timeout(owner.timeout),
        verify=owner.verify_tls,
        stream=True,
        allow_redirects=False,
    )
'''

V145_SEND_ANCHOR = '''def _v80_history_send_locked(owner, method, path, **kwargs):
'''
V145_SEND_REPLACEMENT = '''def _v80_history_send_locked(owner, method, path, **kwargs):
    with owner._v80_timeout_child_scope(
            "history_send", owner.RESOURCE_DETAIL_BUDGET) as operation:
        return _v80_history_send_locked_unbounded(
            owner, method, path, _v80_timeout_operation=operation, **kwargs
        )


def _v80_history_send_locked_unbounded(
        owner, method, path, _v80_timeout_operation=None, **kwargs):
'''

V145_SEND_LOOP_ANCHOR = '''    last_error = None
    for origin in origins:
'''
V145_SEND_LOOP_REPLACEMENT = '''    last_error = None
    retry_policy = ATVP_TRANSPORT_RETRY_POLICY if method_name == "get" else None

    def timed_send(origin, headers):
        request_kwargs = dict(kwargs)
        request_kwargs["headers"] = headers
        request_kwargs["timeout"] = _v80_timeout_operation.request_timeout(
            request_kwargs.get("timeout", owner.timeout),
            retry_policy=retry_policy,
        )
        return sender(_v80_history_endpoint(origin, path), **request_kwargs)

    for origin in origins:
'''

V145_SEND_CALLS_ANCHOR = '''            response = sender(_v80_history_endpoint(origin, path), headers=headers, **kwargs)
            if response.status_code in (401, 403):
                _v80_history_close(response)
                try:
                    token = _v80_history_login(owner, origin, force=True)
                except Exception as exc:
                    last_error = exc
                    if owner._history_retryable_transport_error(exc, "post"):
                        continue
                    raise
                if queue_scope and not _v80_history_queue_bind_uid(
                    owner, queue_scope, getattr(owner, "_v80_history_auth_uid", 0),
                ):
                    raise _V80HistoryQueueCancelled("History 事件队列账号已变化")
                headers["Authorization"] = token
                response = sender(_v80_history_endpoint(origin, path), headers=headers, **kwargs)
'''
V145_SEND_CALLS_REPLACEMENT = '''            response = timed_send(origin, headers)
            if response.status_code in (401, 403):
                _v80_history_close(response)
                try:
                    token = _v80_history_login(owner, origin, force=True)
                except Exception as exc:
                    last_error = exc
                    if owner._history_retryable_transport_error(exc, "post"):
                        continue
                    raise
                if queue_scope and not _v80_history_queue_bind_uid(
                    owner, queue_scope, getattr(owner, "_v80_history_auth_uid", 0),
                ):
                    raise _V80HistoryQueueCancelled("History 事件队列账号已变化")
                headers["Authorization"] = token
                response = timed_send(origin, headers)
'''

V145_FETCH_ANCHOR = '''def v80_history_fetch(owner, legacy_fetch, stateful=False):
'''
V145_FETCH_REPLACEMENT = '''def v80_history_fetch(owner, legacy_fetch, stateful=False):
    with owner._v80_timeout_child_scope(
            "history_fetch", owner.RESOURCE_DETAIL_BUDGET):
        return _v80_history_fetch_unbounded(owner, legacy_fetch, stateful=stateful)


def _v80_history_fetch_unbounded(owner, legacy_fetch, stateful=False):
'''

V145_PUSH_ANCHOR = '''def v80_history_push(owner, rows, legacy_push):
'''
V145_PUSH_REPLACEMENT = '''def v80_history_push(owner, rows, legacy_push):
    with owner._v80_timeout_child_scope(
            "history_push", owner.RESOURCE_DETAIL_BUDGET):
        return _v80_history_push_unbounded(owner, rows, legacy_push)


def _v80_history_push_unbounded(owner, rows, legacy_push):
'''

V145_DELETE_ANCHOR = '''def v80_history_delete(owner, key, legacy_delete):
'''
V145_DELETE_REPLACEMENT = '''def v80_history_delete(owner, key, legacy_delete):
    with owner._v80_timeout_child_scope(
            "history_delete", owner.RESOURCE_DETAIL_BUDGET):
        return _v80_history_delete_unbounded(owner, key, legacy_delete)


def _v80_history_delete_unbounded(owner, key, legacy_delete):
'''


INSERTIONS = (
    ("bounded-json-shared", BOUNDED_JSON_ANCHOR, BOUNDED_JSON_REPLACEMENT),
    ("douban-client", DOUBAN_CLIENT_ANCHOR, DOUBAN_CLIENT_REPLACEMENT),
    ("state", STATE_ANCHOR, STATE_REPLACEMENT),
    ("timeout-helper", TIMEOUT_HELPER_ANCHOR, TIMEOUT_HELPER_REPLACEMENT),
    ("background-guard", BACKGROUND_GUARD_ANCHOR, BACKGROUND_GUARD_REPLACEMENT),
    ("init-reset", INIT_RESET_ANCHOR, INIT_RESET_REPLACEMENT),
    ("destroy-reset", DESTROY_RESET_ANCHOR, DESTROY_RESET_REPLACEMENT),
    ("home", HOME_ANCHOR, HOME_REPLACEMENT),
    ("category", CATEGORY_ANCHOR, CATEGORY_REPLACEMENT),
    ("detail", DETAIL_ANCHOR, DETAIL_REPLACEMENT),
    ("search", SEARCH_ANCHOR, SEARCH_REPLACEMENT),
    ("player", PLAYER_ANCHOR, PLAYER_REPLACEMENT),
    ("action", ACTION_ANCHOR, ACTION_REPLACEMENT),
    ("wish-post", WISH_POST_ANCHOR, WISH_POST_REPLACEMENT),
    ("checked-rows", CHECKED_ROWS_ANCHOR, CHECKED_ROWS_REPLACEMENT),
    ("bounded-reader", BOUNDED_READER_ANCHOR, BOUNDED_READER_REPLACEMENT),
    ("resource-api", RESOURCE_API_ANCHOR, RESOURCE_API_REPLACEMENT),
    ("atvp-play", ATVP_PLAY_ANCHOR, ATVP_PLAY_REPLACEMENT),
    ("atvp-parse", ATVP_PARSE_ANCHOR, ATVP_PARSE_REPLACEMENT),
    ("pinned-blocking-signature", PINNED_BLOCKING_SIGNATURE_ANCHOR, PINNED_BLOCKING_SIGNATURE_REPLACEMENT),
    ("pinned-connection", PINNED_CONNECTION_ANCHOR, PINNED_CONNECTION_REPLACEMENT),
    ("pinned-close", PINNED_CLOSE_ANCHOR, PINNED_CLOSE_REPLACEMENT),
    ("pinned-submit", PINNED_SUBMIT_ANCHOR, PINNED_SUBMIT_REPLACEMENT),
    ("pinned-timeout-close", PINNED_TIMEOUT_CLOSE_ANCHOR, PINNED_TIMEOUT_CLOSE_REPLACEMENT),
    ("probe", PROBE_ANCHOR, PROBE_REPLACEMENT),
    ("tmdb", TMDB_REQUEST_ANCHOR, TMDB_REQUEST_REPLACEMENT),
    ("retry-adapter", RETRY_ADAPTER_ANCHOR, RETRY_ADAPTER_REPLACEMENT),
    ("resolve-user", RESOLVE_USER_ANCHOR, RESOLVE_USER_REPLACEMENT),
    ("legacy-history-request", LEGACY_HISTORY_REQUEST_ANCHOR, LEGACY_HISTORY_REQUEST_REPLACEMENT),
    ("legacy-history-kwargs", LEGACY_HISTORY_KWARGS_ANCHOR, LEGACY_HISTORY_KWARGS_REPLACEMENT),
    ("legacy-history-send", LEGACY_HISTORY_SEND_ANCHOR, LEGACY_HISTORY_SEND_REPLACEMENT),
    ("legacy-history-reauth", LEGACY_HISTORY_REAUTH_SEND_ANCHOR, LEGACY_HISTORY_REAUTH_SEND_REPLACEMENT),
    ("legacy-history-login", LEGACY_HISTORY_LOGIN_ANCHOR, LEGACY_HISTORY_LOGIN_REPLACEMENT),
    ("legacy-history-login-timeout", LEGACY_HISTORY_LOGIN_TIMEOUT_ANCHOR, LEGACY_HISTORY_LOGIN_TIMEOUT_REPLACEMENT),
    ("v145-login", V145_LOGIN_ANCHOR, V145_LOGIN_REPLACEMENT),
    ("v145-login-timeout", V145_LOGIN_TIMEOUT_ANCHOR, V145_LOGIN_TIMEOUT_REPLACEMENT),
    ("v145-send", V145_SEND_ANCHOR, V145_SEND_REPLACEMENT),
    ("v145-send-loop", V145_SEND_LOOP_ANCHOR, V145_SEND_LOOP_REPLACEMENT),
    ("v145-send-calls", V145_SEND_CALLS_ANCHOR, V145_SEND_CALLS_REPLACEMENT),
    ("v145-fetch", V145_FETCH_ANCHOR, V145_FETCH_REPLACEMENT),
    ("v145-push", V145_PUSH_ANCHOR, V145_PUSH_REPLACEMENT),
    ("v145-delete", V145_DELETE_ANCHOR, V145_DELETE_REPLACEMENT),
)


def _replace_once(text, anchor, replacement, label):
    count = text.count(anchor)
    if count != 1:
        raise TimeoutBudgetOverlayError(
            "timeout budget overlay anchor %s must occur once, found %d"
            % (label, count)
        )
    return text.replace(anchor, replacement, 1)


def _class(tree, name):
    values = [
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == name
    ]
    if len(values) != 1:
        raise TimeoutBudgetOverlayError(
            "timeout budget overlay class %s must occur once" % name
        )
    return values[0]


def _method(class_node, name):
    values = [
        node for node in class_node.body
        if isinstance(node, ast.FunctionDef) and node.name == name
    ]
    if len(values) != 1:
        raise TimeoutBudgetOverlayError(
            "timeout budget overlay method %s must occur once" % name
        )
    return values[0]


def apply_timeout_budget_overlay(source):
    try:
        text = bytes(source).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise TimeoutBudgetOverlayError(
            "timeout budget overlay input is not valid UTF-8"
        ) from exc
    input_bytes = text.encode("utf-8")
    labels = []
    for label, anchor, replacement in INSERTIONS:
        text = _replace_once(text, anchor, replacement, label)
        labels.append(label)

    try:
        tree = ast.parse(text, filename="build/v80-dev/timeout-budget-overlay.py")
        compile(tree, "build/v80-dev/timeout-budget-overlay.py", "exec")
    except SyntaxError as exc:
        raise TimeoutBudgetOverlayError(
            "timeout budget overlay output is invalid: %s" % exc
        ) from exc

    spider = _class(tree, "Spider")
    for name in (
            "homeVideoContent", "categoryContent", "detailContent",
            "searchContent", "playerContent", "action",
            "_v80_timeout_child_scope", "_read_bounded_json_response",
            "_resource_api_get", "_atvp_play", "_atvp_parse_candidates",
            "_probe_media_output"):
        _method(spider, name)
    controller_calls = [
        node for node in ast.walk(_method(spider, "__init__"))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "TimeoutBudgetController"
    ]
    if len(controller_calls) != 1:
        raise TimeoutBudgetOverlayError(
            "timeout budget overlay must construct one controller"
        )

    output = text.encode("utf-8")
    return {
        "bytes": output,
        "input_size": len(input_bytes),
        "input_sha256": hashlib.sha256(input_bytes).hexdigest().upper(),
        "size": len(output),
        "sha256": hashlib.sha256(output).hexdigest().upper(),
        "insertions": tuple(labels),
    }

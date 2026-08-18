"""Insert the bounded P3 reliability seams into isolated V80 source."""

import ast
import hashlib


class ReliabilityOverlayError(RuntimeError):
    pass


DEADLINE_ANCHOR = '''    @staticmethod
    def _atvp_deadline_timeout(deadline, default_timeout, requests_left=1):
        if deadline is None:
            return max(1, int(default_timeout))
        remaining = deadline - time.monotonic()
        if remaining < 1:
            raise RuntimeError("播放线路总预算已耗尽")
        # The session may retry twice, and a scalar requests timeout applies to
        # connect and read separately. Divide the remaining budget accordingly.
        retry_phases = max(1, int(requests_left)) * 6
        return max(1, min(float(default_timeout), remaining / retry_phases))
'''

DEADLINE_REPLACEMENT = '''    @staticmethod
    def _atvp_deadline_timeout(
            deadline, default_timeout, requests_left=1, retry_policy=None):
        return v80_reliability_request_timeout(
            deadline, default_timeout, requests_left=requests_left,
            retry_policy=retry_policy,
        )
'''

ATVP_RETRY_ADAPTER_ANCHOR = '''    @staticmethod
    def _atvp_retry_adapter():
        try:
            from requests.packages.urllib3.util.retry import Retry
            retry = Retry(
                total=2,
                connect=2,
                read=2,
                status=0,
                backoff_factor=0.4,
                allowed_methods=frozenset(("GET",)),
            )
            return HTTPAdapter(max_retries=retry, pool_connections=4, pool_maxsize=4)
        except TypeError:
            return HTTPAdapter(max_retries=0, pool_connections=4, pool_maxsize=4)
'''

ATVP_RETRY_ADAPTER_REPLACEMENT = '''    @staticmethod
    def _atvp_retry_adapter():
        return v80_reliability_atvp_retry_adapter()
'''

DIAGNOSTIC_ANCHOR = '''    @staticmethod
    def _diagnostic_error_kind(exc):
        name = type(exc).__name__.lower()
        text = str(exc or "").lower()
        if "timeout" in name or "timed out" in text:
            return "timeout"
        if "connection" in name or "connection" in text or "dns" in text:
            return "transport"
        if "json" in name or "decode" in name or "json" in text:
            return "payload"
        if any(marker in text for marker in ("401", "403", "unauthorized", "forbidden", "token")):
            return "auth"
        if any(marker in text for marker in ("429", "rate limit", "限流")):
            return "rate_limit"
        if any(marker in text for marker in ("cancel", "generation", "已销毁")):
            return "cancelled"
        return "runtime"
'''

DIAGNOSTIC_REPLACEMENT = DIAGNOSTIC_ANCHOR.replace(
    '''    def _diagnostic_error_kind(exc):
''',
    '''    def _diagnostic_error_kind(exc):
        kind = v80_reliability_classify(exc)
        if kind != "runtime":
            return kind
''',
    1,
)

PROVIDER_CONTROLLER_ANCHOR = '''    def _resource_capability_identity(self):
        api = str(self.atvp_api or "").rstrip("/")
        if not api:
            return ""
        raw = "%s|%s" % (api, Filter._token_hash(self.atvp_token))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()
'''

PROVIDER_CONTROLLER_REPLACEMENT = PROVIDER_CONTROLLER_ANCHOR + '''
    def _provider_reliability_for(self, backend_identity, expected_generation=None):
        identity = str(backend_identity or "")
        with self._cache_lock:
            current_generation = self._cache_generation
            current_backend = self._resource_capability_identity()
            if (
                    identity != current_backend
                    or (
                        expected_generation is not None
                        and expected_generation != current_generation
                    )):
                raise ReliabilityFailure("cancelled", operation="provider_gate")
            controller = getattr(self, "_provider_reliability_controller", None)
            active_backend = getattr(self, "_provider_reliability_backend", "")
            if controller is None:
                controller = ProviderReliabilityController()
                self._provider_reliability_controller = controller
            elif active_backend != current_backend:
                controller.reset()
            self._provider_reliability_backend = current_backend
            return controller
'''

PROVIDER_INIT_RESET_ANCHOR = '''                self._resource_capabilities.clear()
                self._resource_capabilities_backend = ""
                self._resource_capabilities_revision += 1
                self._route_quality_history.clear()
'''

PROVIDER_INIT_RESET_REPLACEMENT = '''                self._resource_capabilities.clear()
                self._resource_capabilities_backend = ""
                self._resource_capabilities_revision += 1
                provider_controller = getattr(self, "_provider_reliability_controller", None)
                if provider_controller is not None:
                    provider_controller.reset()
                self._provider_reliability_backend = ""
                self._route_quality_history.clear()
'''

PROVIDER_DESTROY_RESET_ANCHOR = '''                with self._cache_lock:
                    self._cache_generation += 1
                    self._resource_search_layered_shadow_sampled_generation = None
'''

PROVIDER_DESTROY_RESET_REPLACEMENT = '''                with self._cache_lock:
                    self._cache_generation += 1
                    provider_controller = getattr(self, "_provider_reliability_controller", None)
                    if provider_controller is not None:
                        provider_controller.reset()
                    self._provider_reliability_backend = ""
                    self._resource_search_layered_shadow_sampled_generation = None
'''

PROVIDER_TRANSPORT_ANCHOR = '''        with self._cache_lock:
            expected_generation = self._cache_generation
            expected_backend = self._resource_capability_identity()
        endpoint_mode = "tg-search" if mode == "telegram" else mode
        response = self._atvp_session.get(
            self._atvp_endpoint(endpoint_mode),
            params=params,
            headers={"Accept": "application/json", "X-CLIENT": "com.fongmi.android.tv"},
            timeout=self._atvp_deadline_timeout(
                deadline, max(5, min(12, self.timeout)), requests_left=1,
            ),
            verify=self.verify_tls,
            stream=True,
        )
        status = int(response.status_code)
        self._mark_resource_capability(
            mode,
            "missing" if status in self.RESOURCE_CAPABILITY_MISSING_STATUSES else "present",
            status,
            expected_backend=expected_backend,
            expected_generation=expected_generation,
        )
        if status < 200 or status >= 300:
            closer = getattr(response, "close", None)
            if callable(closer):
                closer()
            raise RuntimeError("AList %s HTTP %s" % (mode, status))
        value = self._read_bounded_json_response(response, "AList %s" % mode, deadline=deadline)
        return value if isinstance(value, dict) else {"list": value if isinstance(value, list) else []}
'''

PROVIDER_TRANSPORT_REPLACEMENT = '''        with self._cache_lock:
            expected_generation = self._cache_generation
            expected_backend = self._resource_capability_identity()
            endpoint_mode = "tg-search" if mode == "telegram" else mode
            request_endpoint = self._atvp_endpoint(endpoint_mode)
            request_sender = self._atvp_session.get
            request_verify_tls = self.verify_tls
            request_default_timeout = max(5, min(12, self.timeout))
        request_timeout = self._atvp_deadline_timeout(
            deadline, request_default_timeout, requests_left=1,
            retry_policy=ATVP_TRANSPORT_RETRY_POLICY,
        )
        with self._cache_lock:
            controller = self._provider_reliability_for(
                expected_backend, expected_generation=expected_generation,
            )
            lease = controller.acquire(expected_backend, mode)
        response = None
        try:
            response = request_sender(
                request_endpoint,
                params=params,
                headers={"Accept": "application/json", "X-CLIENT": "com.fongmi.android.tv"},
                timeout=request_timeout,
                verify=request_verify_tls,
                stream=True,
            )
            status = int(response.status_code)
            self._mark_resource_capability(
                mode,
                "missing" if status in self.RESOURCE_CAPABILITY_MISSING_STATUSES else "present",
                status,
                expected_backend=expected_backend,
                expected_generation=expected_generation,
            )
            if status < 200 or status >= 300:
                failure = v80_reliability_http_failure(
                    status,
                    operation="resource_api_get",
                    explicit_unsupported=status in self.RESOURCE_CAPABILITY_MISSING_STATUSES,
                )
                raise failure
            try:
                value = self._read_bounded_json_response(
                    response, "AList %s" % mode, deadline=deadline,
                )
            except Exception as exc:
                failure = v80_reliability_payload_failure(
                    "resource_api_get", exc=exc, deadline=deadline,
                )
                raise failure from None
        except Exception as exc:
            lease.finish(failure_kind=v80_reliability_classify(exc))
            raise
        else:
            lease.finish(success=True)
            return value if isinstance(value, dict) else {"list": value if isinstance(value, list) else []}
        finally:
            closer = getattr(response, "close", None)
            if callable(closer):
                try:
                    closer()
                except Exception:
                    pass
'''

INSERTIONS = (
    ("deadline-timeout", DEADLINE_ANCHOR, DEADLINE_REPLACEMENT),
    ("atvp-retry-adapter", ATVP_RETRY_ADAPTER_ANCHOR, ATVP_RETRY_ADAPTER_REPLACEMENT),
    ("diagnostic-kind", DIAGNOSTIC_ANCHOR, DIAGNOSTIC_REPLACEMENT),
    ("provider-controller", PROVIDER_CONTROLLER_ANCHOR, PROVIDER_CONTROLLER_REPLACEMENT),
    ("provider-init-reset", PROVIDER_INIT_RESET_ANCHOR, PROVIDER_INIT_RESET_REPLACEMENT),
    ("provider-destroy-reset", PROVIDER_DESTROY_RESET_ANCHOR, PROVIDER_DESTROY_RESET_REPLACEMENT),
    ("provider-transport", PROVIDER_TRANSPORT_ANCHOR, PROVIDER_TRANSPORT_REPLACEMENT),
)


def _replace_once(text, anchor, replacement, label):
    count = text.count(anchor)
    if count != 1:
        raise ReliabilityOverlayError(
            "reliability overlay anchor %s must occur once, found %d" % (label, count)
        )
    return text.replace(anchor, replacement, 1)


def _method(spider, name):
    matches = [
        node for node in spider.body
        if isinstance(node, ast.FunctionDef) and node.name == name
    ]
    if len(matches) != 1:
        raise ReliabilityOverlayError(
            "reliability overlay method %s must occur once, found %d" % (name, len(matches))
        )
    return matches[0]


def _named_call_count(node, name):
    return sum(
        1 for item in ast.walk(node)
        if isinstance(item, ast.Call)
        and isinstance(item.func, ast.Name)
        and item.func.id == name
    )


def apply_reliability_overlay(source):
    try:
        text = bytes(source).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ReliabilityOverlayError("reliability overlay input is not valid UTF-8") from exc
    input_bytes = text.encode("utf-8")
    for label, anchor, replacement in INSERTIONS:
        text = _replace_once(text, anchor, replacement, label)

    try:
        tree = ast.parse(text, filename="build/v80-dev/reliability-overlay.py")
        compile(tree, "build/v80-dev/reliability-overlay.py", "exec")
    except SyntaxError as exc:
        raise ReliabilityOverlayError("reliability overlay output is invalid: %s" % exc) from exc

    spiders = [
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "Spider"
    ]
    if len(spiders) != 1:
        raise ReliabilityOverlayError(
            "reliability overlay requires exactly one Spider class"
        )
    spider = spiders[0]
    checks = (
        (_method(spider, "_atvp_deadline_timeout"), "v80_reliability_request_timeout"),
        (_method(spider, "_atvp_retry_adapter"), "v80_reliability_atvp_retry_adapter"),
        (_method(spider, "_diagnostic_error_kind"), "v80_reliability_classify"),
        (_method(spider, "_resource_api_get"), "v80_reliability_http_failure"),
        (_method(spider, "_resource_api_get"), "v80_reliability_payload_failure"),
        (_method(spider, "_provider_reliability_for"), "ProviderReliabilityController"),
    )
    for method, call_name in checks:
        method_count = _named_call_count(method, call_name)
        if method_count != 1:
            raise ReliabilityOverlayError(
                "reliability overlay call %s must occur once at its seam, found %d"
                % (call_name, method_count)
            )

    provider = _method(spider, "_resource_api_get")
    timeout_calls = [
        item for item in ast.walk(provider)
        if isinstance(item, ast.Call)
        and isinstance(item.func, ast.Attribute)
        and item.func.attr == "_atvp_deadline_timeout"
    ]
    if len(timeout_calls) != 1:
        raise ReliabilityOverlayError(
            "reliability overlay Provider timeout seam must occur once, found %d"
            % len(timeout_calls)
        )
    retry_keyword = next(
        (item for item in timeout_calls[0].keywords if item.arg == "retry_policy"),
        None,
    )
    if not (
            retry_keyword is not None
            and isinstance(retry_keyword.value, ast.Name)
            and retry_keyword.value.id == "ATVP_TRANSPORT_RETRY_POLICY"):
        raise ReliabilityOverlayError(
            "reliability overlay Provider timeout is missing the transport retry policy"
        )
    session_get_bindings = [
        item for item in ast.walk(provider)
        if isinstance(item, ast.Attribute)
        and item.attr == "get"
        and isinstance(item.value, ast.Attribute)
        and item.value.attr == "_atvp_session"
    ]
    sender_calls = [
        item for item in ast.walk(provider)
        if isinstance(item, ast.Call)
        and isinstance(item.func, ast.Name)
        and item.func.id == "request_sender"
    ]
    if len(session_get_bindings) != 1 or len(sender_calls) != 1:
        raise ReliabilityOverlayError(
            "reliability overlay Provider must bind and call exactly one session GET"
        )
    retry_loops = [
        item for item in ast.walk(provider)
        if isinstance(item, (ast.For, ast.AsyncFor, ast.While))
    ]
    if retry_loops:
        raise ReliabilityOverlayError(
            "reliability overlay Provider must not add an application retry loop"
        )
    acquire_calls = [
        item for item in ast.walk(provider)
        if isinstance(item, ast.Call)
        and isinstance(item.func, ast.Attribute)
        and item.func.attr == "acquire"
    ]
    finish_calls = [
        item for item in ast.walk(provider)
        if isinstance(item, ast.Call)
        and isinstance(item.func, ast.Attribute)
        and item.func.attr == "finish"
    ]
    if len(acquire_calls) != 1 or len(finish_calls) != 2:
        raise ReliabilityOverlayError(
            "reliability overlay Provider requires one acquire and two finish paths"
        )
    for lifecycle_method in ("_init_locked", "destroy"):
        reset_calls = [
            item for item in ast.walk(_method(spider, lifecycle_method))
            if isinstance(item, ast.Call)
            and isinstance(item.func, ast.Attribute)
            and item.func.attr == "reset"
        ]
        if len(reset_calls) != 1:
            raise ReliabilityOverlayError(
                "reliability overlay %s must reset Provider state once"
                % lifecycle_method
            )

    data = text.encode("utf-8")
    return {
        "bytes": data,
        "size": len(data),
        "sha256": hashlib.sha256(data).hexdigest().upper(),
        "input_size": len(input_bytes),
        "input_sha256": hashlib.sha256(input_bytes).hexdigest().upper(),
        "insertions": tuple(label for label, _anchor, _replacement in INSERTIONS),
    }

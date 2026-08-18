"""Apply the P5-5D search concurrency and ownership fixes."""

import ast
import hashlib


OVERLAY_ALIAS_ZH = "搜索并发所有权覆盖层"


class SearchConcurrencyOwnershipOverlayError(RuntimeError):
    pass


MODULE_RUNTIME_GLOBALS_ANCHOR = '''_DNS_EXECUTOR = ThreadPoolExecutor(max_workers=4)
_DNS_SLOTS = threading.BoundedSemaphore(4)
_MEDIA_PROBE_EXECUTOR = ThreadPoolExecutor(max_workers=4)
_MEDIA_PROBE_SLOTS = threading.BoundedSemaphore(4)
'''


MODULE_RUNTIME_GLOBALS_REPLACEMENT = ''''''


RESOURCE_API_OWNER_ANCHOR = '''    def _resource_api_get(self, mode, params, deadline=None):
        with self._v80_timeout_child_scope(
                "resource_api_get", self.RESOURCE_SEARCH_BUDGET,
                deadline=deadline) as operation:
            return self._v80_resource_api_get_unbounded(
                mode, params, deadline=operation.deadline,
            )

    def _v80_resource_api_get_unbounded(self, mode, params, deadline=None):
        if mode not in self.RESOURCE_SEARCH_MODES:
            raise RuntimeError("不支持的资源搜索模式：%s" % mode)
        if self._resource_capability(mode) == "missing":
            raise RuntimeError("AList %s 接口已确认缺失" % mode)
        if not self._ensure_atvp_connection(force=True):
            raise RuntimeError("未配置 AList-TVBox 地址或令牌")
        with self._cache_lock:
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


RESOURCE_API_OWNER_REPLACEMENT = '''    def _resource_api_get(
            self, mode, params, deadline=None, expected_generation=None):
        with self._cache_lock:
            generation = (
                self._cache_generation
                if expected_generation is None else expected_generation
            )
            if generation != self._cache_generation:
                raise ReliabilityFailure("cancelled", operation="resource_api_get")
        controller = self._timeout_budget_controller
        parent = controller.current(required=False)
        if parent is not None:
            if parent.generation != generation:
                raise ReliabilityFailure("cancelled", operation="resource_api_get")
            budget = parent.remaining()
        else:
            budget = self.RESOURCE_SEARCH_BUDGET
        with controller.scope(
                "resource_api_get", budget,
                expected_generation=generation, deadline=deadline) as operation:
            return self._v80_resource_api_get_unbounded(
                mode, params, deadline=operation.deadline,
                expected_generation=expected_generation,
                timeout_operation=operation,
            )

    def _v80_resource_api_get_unbounded(
            self, mode, params, deadline=None, expected_generation=None,
            timeout_operation=None):
        if mode not in self.RESOURCE_SEARCH_MODES:
            raise RuntimeError("不支持的资源搜索模式：%s" % mode)
        operation = timeout_operation or self._timeout_budget_controller.current()
        explicit_generation = expected_generation is not None
        with self._cache_lock:
            generation = (
                operation.generation
                if expected_generation is None else expected_generation
            )
            if generation != self._cache_generation:
                raise ReliabilityFailure("cancelled", operation="resource_api_get")
            connected = bool(
                self._alist_tvbox_plugin
                and self.atvp_api
                and self.atvp_token
                and self._atvp_session is not None
            )
        if self._resource_capability(mode) == "missing":
            raise RuntimeError("AList %s 接口已确认缺失" % mode)
        if not connected:
            if explicit_generation or not self._ensure_atvp_connection(force=True):
                raise RuntimeError("未配置 AList-TVBox 地址或令牌")
        with self._cache_lock:
            if generation != self._cache_generation:
                raise ReliabilityFailure("cancelled", operation="resource_api_get")
            if not (
                    self._alist_tvbox_plugin
                    and self.atvp_api
                    and self.atvp_token
                    and self._atvp_session is not None):
                raise RuntimeError("未配置 AList-TVBox 地址或令牌")
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
            if generation != self._cache_generation:
                raise ReliabilityFailure("cancelled", operation="resource_api_get")
            controller = self._provider_reliability_for(
                expected_backend, expected_generation=generation,
            )
            lease = controller.acquire(expected_backend, mode)
        response = None
        reader_response = None
        try:
            response = request_sender(
                request_endpoint,
                params=params,
                headers={"Accept": "application/json", "X-CLIENT": "com.fongmi.android.tv"},
                timeout=request_timeout,
                verify=request_verify_tls,
                stream=True,
            )
            reader_response = response
            response = None
            operation.track(reader_response)
            status = int(reader_response.status_code)
            self._mark_resource_capability(
                mode,
                "missing" if status in self.RESOURCE_CAPABILITY_MISSING_STATUSES else "present",
                status,
                expected_backend=expected_backend,
                expected_generation=generation,
            )
            if status < 200 or status >= 300:
                failure = v80_reliability_http_failure(
                    status,
                    operation="resource_api_get",
                    explicit_unsupported=status in self.RESOURCE_CAPABILITY_MISSING_STATUSES,
                )
                raise failure
            try:
                value = _read_bounded_json_shared(
                    reader_response,
                    "AList %s" % mode,
                    self.RESOURCE_API_RESPONSE_MAX_BYTES,
                    deadline=operation.deadline,
                    close_response=False,
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
            if reader_response is not None:
                operation.close_tracked(reader_response)
            closer = getattr(response, "close", None)
            if callable(closer):
                try:
                    closer()
                except Exception:
                    pass
'''


TASK_RUNTIME_ANCHOR = '''    def _create_task_runtime(self):
        self._tasks = _TaskSupervisor()
        self._resource_search_executor = ThreadPoolExecutor(max_workers=self.RESOURCE_HOT_JOB_LIMIT)
        self._follow_refresh_executor = ThreadPoolExecutor(max_workers=4)
        self._resource_foreground_mode_executor = ThreadPoolExecutor(
            max_workers=self.RESOURCE_FOREGROUND_MODE_WORKERS,
        )
        self._resource_foreground_mode_slots = threading.BoundedSemaphore(
            self.RESOURCE_FOREGROUND_MODE_WORKERS + self.RESOURCE_FOREGROUND_MODE_QUEUE_LIMIT,
        )
        self._resource_background_mode_executor = ThreadPoolExecutor(
            max_workers=self.RESOURCE_BACKGROUND_MODE_WORKERS,
        )
        self._resource_background_mode_slots = threading.BoundedSemaphore(
            self.RESOURCE_BACKGROUND_MODE_WORKERS + self.RESOURCE_BACKGROUND_MODE_QUEUE_LIMIT,
        )
        for _executor in (
                self._resource_search_executor,
                self._follow_refresh_executor,
                self._resource_foreground_mode_executor,
                self._resource_background_mode_executor):
            self._tasks.register_executor(_executor)
'''


TASK_RUNTIME_REPLACEMENT = '''    def _create_task_runtime(self):
        self._tasks = _TaskSupervisor()
        self._resource_search_executor = ThreadPoolExecutor(max_workers=self.RESOURCE_HOT_JOB_LIMIT)
        self._follow_refresh_executor = ThreadPoolExecutor(max_workers=4)
        self._resource_foreground_mode_executor = ThreadPoolExecutor(
            max_workers=self.RESOURCE_FOREGROUND_MODE_WORKERS,
        )
        self._resource_foreground_mode_slots = threading.BoundedSemaphore(
            self.RESOURCE_FOREGROUND_MODE_WORKERS + self.RESOURCE_FOREGROUND_MODE_QUEUE_LIMIT,
        )
        self._resource_background_mode_executor = ThreadPoolExecutor(
            max_workers=self.RESOURCE_BACKGROUND_MODE_WORKERS,
        )
        self._resource_background_mode_slots = threading.BoundedSemaphore(
            self.RESOURCE_BACKGROUND_MODE_WORKERS + self.RESOURCE_BACKGROUND_MODE_QUEUE_LIMIT,
        )
        self._dns_executor = ThreadPoolExecutor(max_workers=4)
        self._dns_slots = threading.BoundedSemaphore(4)
        self._media_probe_executor = ThreadPoolExecutor(max_workers=4)
        self._media_probe_slots = threading.BoundedSemaphore(4)
        for _executor in (
                self._resource_search_executor,
                self._follow_refresh_executor,
                self._resource_foreground_mode_executor,
                self._resource_background_mode_executor,
                self._dns_executor,
                self._media_probe_executor):
            self._tasks.register_executor(_executor)
'''


LIVE_INIT_START_ANCHOR = '''    def _init_locked(self, extend=""):
        if self._tasks.is_closed():
            self._create_task_runtime()
        config = self._parse_config(extend)
'''


LIVE_INIT_START_REPLACEMENT = '''    def _init_locked(self, extend=""):
        previous_tasks = self._tasks
        with self._cache_lock:
            self._cache_generation += 1
            init_generation = self._cache_generation
            self._timeout_budget_controller.reset(init_generation, closed=False)
            self._background_bulkhead_controller.reset(init_generation)
        previous_tasks.shutdown(wait=False)
        config = self._parse_config(extend)
'''


LIVE_INIT_RUNTIME_RESET_ANCHOR = '''                self._cache_generation += 1
                self._timeout_budget_controller.reset(
                    self._cache_generation, closed=False,
                )
                self._background_bulkhead_controller.reset(self._cache_generation)
                self._resource_candidate_shadow_sampled_generation = None
'''


LIVE_INIT_RUNTIME_RESET_REPLACEMENT = '''                if self._cache_generation != init_generation:
                    raise ReliabilityFailure("cancelled", operation="init")
                self._create_task_runtime()
                self._resource_candidate_shadow_sampled_generation = None
'''


DNS_RUNTIME_ANCHOR = '''    @staticmethod
    def _resolve_addresses(host, port, deadline=None):
        remaining = (deadline - time.monotonic()) if deadline is not None else 8
        slot = _DNS_SLOTS
        if remaining <= 0 or not slot.acquire(False):
            return set()
        try:
            future = _DNS_EXECUTOR.submit(socket.getaddrinfo, host, port, 0, socket.SOCK_STREAM)
        except Exception:
            slot.release()
            return set()
        future.add_done_callback(lambda _future, owned_slot=slot: owned_slot.release())
        try:
            result = future.result(timeout=remaining)
        except Exception:
            future.cancel()
            return set()
        addresses = set()
        for entry in result:
            try:
                addresses.add(ipaddress.ip_address(entry[4][0]))
            except Exception:
                continue
        return addresses
'''


DNS_RUNTIME_REPLACEMENT = '''    def _resolve_addresses(self, host, port, deadline=None):
        remaining = (deadline - time.monotonic()) if deadline is not None else 8
        slot = self._dns_slots
        if remaining <= 0 or not slot.acquire(False):
            return set()
        try:
            future = self._dns_executor.submit(
                socket.getaddrinfo, host, port, 0, socket.SOCK_STREAM,
            )
        except Exception:
            slot.release()
            return set()
        future.add_done_callback(lambda _future, owned_slot=slot: owned_slot.release())
        try:
            result = future.result(timeout=remaining)
        except Exception:
            future.cancel()
            return set()
        addresses = set()
        for entry in result:
            try:
                addresses.add(ipaddress.ip_address(entry[4][0]))
            except Exception:
                continue
        return addresses
'''


MEDIA_RUNTIME_ANCHOR = '''        remaining = deadline - time.monotonic()
        slot = _MEDIA_PROBE_SLOTS
        if remaining <= 0 or not slot.acquire(False):
            return None
        control = {}
        timeout_operation = self._timeout_budget_controller.current(required=False)
        try:
            future = _MEDIA_PROBE_EXECUTOR.submit(
'''


MEDIA_RUNTIME_REPLACEMENT = '''        remaining = deadline - time.monotonic()
        slot = self._media_probe_slots
        if remaining <= 0 or not slot.acquire(False):
            return None
        control = {}
        timeout_operation = self._timeout_budget_controller.current(required=False)
        try:
            future = self._media_probe_executor.submit(
'''


SUBMIT_MODE_ANCHOR = '''    def _submit_resource_mode_search(self, mode, queries, deadline, background=False):
        if background:
            executor = self._resource_background_mode_executor
            slots = self._resource_background_mode_slots
            admitted = slots.acquire(False)
        else:
            executor = self._resource_foreground_mode_executor
            slots = self._resource_foreground_mode_slots
            remaining = (
                deadline - time.monotonic()
                if deadline is not None and math.isfinite(deadline)
                else self.RESOURCE_SEARCH_BUDGET
            )
            admitted = remaining > 0 and slots.acquire(timeout=remaining)
        if not admitted:
            return None

        release_lock = threading.Lock()
        released = [False]

        def release_once():
            with release_lock:
                if released[0]:
                    return
                released[0] = True
            slots.release()

        def worker():
            try:
                return self._resource_search_mode(mode, queries, deadline)
            finally:
                release_once()

        try:
            future = executor.submit(worker)
            future.add_done_callback(lambda _future: release_once())
            return future
        except Exception:
            release_once()
            return None
'''


SUBMIT_MODE_REPLACEMENT = '''    def _submit_resource_mode_search(
            self, mode, queries, deadline, background=False,
            expected_generation=None):
        with self._cache_lock:
            generation = (
                self._cache_generation
                if expected_generation is None else expected_generation
            )
            if generation != self._cache_generation:
                return None
        if background:
            executor = self._resource_background_mode_executor
            slots = self._resource_background_mode_slots
            admitted = slots.acquire(False)
        else:
            executor = self._resource_foreground_mode_executor
            slots = self._resource_foreground_mode_slots
            remaining = (
                deadline - time.monotonic()
                if deadline is not None and math.isfinite(deadline)
                else self.RESOURCE_SEARCH_BUDGET
            )
            admitted = remaining > 0 and slots.acquire(timeout=remaining)
        if not admitted:
            return None

        release_lock = threading.Lock()
        released = [False]

        def release_once():
            with release_lock:
                if released[0]:
                    return
                released[0] = True
            slots.release()

        def worker():
            try:
                with self._cache_lock:
                    if generation != self._cache_generation:
                        return []
                remaining = (
                    deadline - time.monotonic()
                    if deadline is not None and math.isfinite(deadline)
                    else self.RESOURCE_SEARCH_BUDGET
                )
                if remaining <= 0:
                    return []
                try:
                    with self._timeout_budget_controller.scope(
                            "resource_mode_search",
                            min(self.RESOURCE_SEARCH_BUDGET, remaining),
                            expected_generation=generation,
                            deadline=deadline):
                        with self._cache_lock:
                            if generation != self._cache_generation:
                                return []
                        rows = self._resource_search_mode(
                            mode, queries, deadline,
                            expected_generation=generation,
                        )
                except ReliabilityFailure:
                    with self._cache_lock:
                        if generation != self._cache_generation:
                            return []
                    raise
                with self._cache_lock:
                    if generation != self._cache_generation:
                        return []
                return rows
            finally:
                release_once()

        try:
            future = executor.submit(worker)
            future.add_done_callback(lambda _future: release_once())
            return future
        except Exception:
            release_once()
            return None
'''


RESOURCE_MODE_SIGNATURE_ANCHOR = '''    def _resource_search_mode(self, mode, queries, deadline=None):
        started_at = time.monotonic()
        self._diagnostic_event("resource_mode.start", mode=mode, query_count=len(queries or []))
'''


RESOURCE_MODE_SIGNATURE_REPLACEMENT = '''    def _resource_search_mode(
            self, mode, queries, deadline=None, expected_generation=None):
        with self._cache_lock:
            if expected_generation is None:
                expected_generation = self._cache_generation
            elif expected_generation != self._cache_generation:
                return []
        started_at = time.monotonic()
        self._diagnostic_event("resource_mode.start", mode=mode, query_count=len(queries or []))
'''


RESOURCE_MODE_API_ANCHOR = '''                data = self._resource_api_get(mode, params, deadline=deadline)
            except Exception as exc:
                self._diagnostic_event("resource_mode.request", "WARN", exc=exc, mode=mode)
                continue
'''


RESOURCE_MODE_API_REPLACEMENT = '''                data = self._resource_api_get(
                    mode, params, deadline=deadline,
                    expected_generation=expected_generation,
                )
            except Exception as exc:
                self._diagnostic_event("resource_mode.request", "WARN", exc=exc, mode=mode)
                with self._cache_lock:
                    if expected_generation != self._cache_generation:
                        return []
                continue
'''


RESOURCE_MODE_FINISH_ANCHOR = '''        self._diagnostic_event(
            "resource_mode.finish", "INFO" if rows else "WARN",
            duration_ms=int((time.monotonic() - started_at) * 1000), mode=mode, count=len(rows),
        )
        return rows
'''


RESOURCE_MODE_FINISH_REPLACEMENT = '''        with self._cache_lock:
            if expected_generation != self._cache_generation:
                return []
        self._diagnostic_event(
            "resource_mode.finish", "INFO" if rows else "WARN",
            duration_ms=int((time.monotonic() - started_at) * 1000), mode=mode, count=len(rows),
        )
        return rows
'''


RESOURCE_CANDIDATES_SIGNATURE_ANCHOR = '''    def _resource_candidates(self, item, deadline=None, background=False):
        started_at = time.monotonic()
'''


RESOURCE_CANDIDATES_SIGNATURE_REPLACEMENT = '''    def _resource_candidates(
            self, item, deadline=None, background=False,
            expected_generation=None):
        with self._cache_lock:
            if expected_generation is None:
                expected_generation = self._cache_generation
            elif expected_generation != self._cache_generation:
                return []
        started_at = time.monotonic()
'''


RESOURCE_CANDIDATES_SUPPLEMENT_ANCHOR = '''                    self._schedule_supplement_resource_search(
                        supplement_modes, query_titles[:2], item, cache_key,
                    )
'''


RESOURCE_CANDIDATES_SUPPLEMENT_REPLACEMENT = '''                    self._schedule_supplement_resource_search(
                        supplement_modes, query_titles[:2], item, cache_key,
                        expected_generation=expected_generation,
                    )
'''


RESOURCE_CANDIDATES_SUBMIT_ANCHOR = '''                    future = self._submit_resource_mode_search(
                        mode, query_titles[:2], deadline, background=background,
                    )
'''


RESOURCE_CANDIDATES_SUBMIT_REPLACEMENT = '''                    future = self._submit_resource_mode_search(
                        mode, query_titles[:2], deadline, background=background,
                        expected_generation=expected_generation,
                    )
'''


RESOURCE_CANDIDATES_POST_FENCE_ANCHOR = '''        finally:
            for future, mode in futures.items():
                if not future.done():
                    future.cancel()
                    mode_rows.setdefault(mode, [])
        for mode in sorted(modes, key=lambda value: self.RESOURCE_MODE_PRIORITY.get(value, 99)):
'''


RESOURCE_CANDIDATES_POST_FENCE_REPLACEMENT = '''        finally:
            for future, mode in futures.items():
                if not future.done():
                    future.cancel()
                    mode_rows.setdefault(mode, [])
        with self._cache_lock:
            if expected_generation != self._cache_generation:
                return []
        for mode in sorted(modes, key=lambda value: self.RESOURCE_MODE_PRIORITY.get(value, 99)):
'''


FOREGROUND_GENERATION_ANCHOR = '''            candidates = self._resource_candidates(
                item, deadline=min(resource_deadline, time.monotonic() + self.RESOURCE_SEARCH_BUDGET),
            )
'''


FOREGROUND_GENERATION_REPLACEMENT = '''            with self._cache_lock:
                resource_generation = self._cache_generation
            candidates = self._resource_candidates(
                item,
                deadline=min(
                    resource_deadline, time.monotonic() + self.RESOURCE_SEARCH_BUDGET,
                ),
                expected_generation=resource_generation,
            )
'''


BOUND_REPLACEMENT_GENERATION_ANCHOR = '''                candidates = self._resource_candidates(
                    dict(item), deadline=deadline, background=True,
                )
'''


BOUND_REPLACEMENT_GENERATION_REPLACEMENT = '''                candidates = self._resource_candidates(
                    dict(item), deadline=deadline, background=True,
                    expected_generation=generation,
                )
'''


PREHEAT_GENERATION_ANCHOR = '''                    candidates = self._resource_candidates(
                        source_item, deadline=deadline, background=True,
                    )
'''


PREHEAT_GENERATION_REPLACEMENT = '''                    candidates = self._resource_candidates(
                        source_item, deadline=deadline, background=True,
                        expected_generation=expected_generation,
                    )
'''


DESTROY_JOB_CLEANUP_ANCHOR = '''                    self._provider_reliability_backend = ""
                    self._resource_search_layered_shadow_sampled_generation = None
                    self._resource_search_layered_shadow_last_report = None
                    self._history_snapshot_revision += 1
'''


DESTROY_JOB_CLEANUP_REPLACEMENT = '''                    self._provider_reliability_backend = ""
                    self._resource_search_layered_shadow_sampled_generation = None
                    self._resource_search_layered_shadow_last_report = None
                    for resource_cache_key, resource_job_id in list(
                            self._resource_search_jobs.items()):
                        if self._refreshing_cache_keys.get(resource_cache_key) is resource_job_id:
                            self._refreshing_cache_keys.pop(resource_cache_key, None)
                    self._resource_search_jobs.clear()
                    self._history_snapshot_revision += 1
'''


ADMISSION_ATTRIBUTE_ANCHOR = '''        self._resource_search_admissions = 0
'''
ADMISSION_ATTRIBUTE_REPLACEMENT = ''''''


SUPPLEMENT_ADMISSION_ANCHOR = '''    def _schedule_supplement_resource_search(self, modes, queries, item, cache_key):
        with self._cache_lock:
            if cache_key in self._resource_search_jobs:
                return False
            if self._resource_search_admissions >= self.RESOURCE_HOT_JOB_LIMIT + self.RESOURCE_HOT_JOB_QUEUE_LIMIT:
                return False
            generation = self._cache_generation
            job_id = object()
            self._refreshing_cache_keys[cache_key] = job_id
            self._resource_search_jobs[cache_key] = job_id
            self._resource_search_admissions += 1
'''


SUPPLEMENT_ADMISSION_REPLACEMENT = '''    def _schedule_supplement_resource_search(
            self, modes, queries, item, cache_key, expected_generation=None):
        with self._cache_lock:
            generation = (
                self._cache_generation
                if expected_generation is None else expected_generation
            )
            if generation != self._cache_generation:
                return False
            if cache_key in self._resource_search_jobs:
                return False
            job_id = object()
            self._refreshing_cache_keys[cache_key] = job_id
            self._resource_search_jobs[cache_key] = job_id
'''


SUPPLEMENT_MODE_GENERATION_ANCHOR = '''                    future = self._submit_resource_mode_search(
                        mode, queries, search_deadline, background=True,
                    )
'''


SUPPLEMENT_MODE_GENERATION_REPLACEMENT = '''                    future = self._submit_resource_mode_search(
                        mode, queries, search_deadline, background=True,
                        expected_generation=generation,
                    )
'''


SUPPLEMENT_WORKER_CLEANUP_ANCHOR = '''            finally:
                with self._cache_lock:
                    if self._resource_search_jobs.get(cache_key) is job_id:
                        self._resource_search_jobs.pop(cache_key, None)
                        if self._refreshing_cache_keys.get(cache_key) is job_id:
                            self._refreshing_cache_keys.pop(cache_key, None)
                    self._resource_search_admissions = max(0, self._resource_search_admissions - 1)
                if shadow_payload is not None:
'''


SUPPLEMENT_WORKER_CLEANUP_REPLACEMENT = '''            finally:
                with self._cache_lock:
                    if self._resource_search_jobs.get(cache_key) is job_id:
                        self._resource_search_jobs.pop(cache_key, None)
                        if self._refreshing_cache_keys.get(cache_key) is job_id:
                            self._refreshing_cache_keys.pop(cache_key, None)
                if shadow_payload is not None:
'''


SUPPLEMENT_SUBMIT_CLEANUP_ANCHOR = '''        if not submitted:
            with self._cache_lock:
                if self._resource_search_jobs.get(cache_key) is job_id:
                    self._resource_search_jobs.pop(cache_key, None)
                    if self._refreshing_cache_keys.get(cache_key) is job_id:
                        self._refreshing_cache_keys.pop(cache_key, None)
                self._resource_search_admissions = max(0, self._resource_search_admissions - 1)
            return False
'''


SUPPLEMENT_SUBMIT_CLEANUP_REPLACEMENT = '''        if not submitted:
            with self._cache_lock:
                if self._resource_search_jobs.get(cache_key) is job_id:
                    self._resource_search_jobs.pop(cache_key, None)
                    if self._refreshing_cache_keys.get(cache_key) is job_id:
                        self._refreshing_cache_keys.pop(cache_key, None)
            return False
'''


INSERTIONS = (
    ("remove-module-network-runtime", MODULE_RUNTIME_GLOBALS_ANCHOR,
     MODULE_RUNTIME_GLOBALS_REPLACEMENT),
    ("instance-task-runtime", TASK_RUNTIME_ANCHOR, TASK_RUNTIME_REPLACEMENT),
    ("live-init-runtime-seal", LIVE_INIT_START_ANCHOR,
     LIVE_INIT_START_REPLACEMENT),
    ("live-init-runtime-rebuild", LIVE_INIT_RUNTIME_RESET_ANCHOR,
     LIVE_INIT_RUNTIME_RESET_REPLACEMENT),
    ("instance-dns-runtime", DNS_RUNTIME_ANCHOR, DNS_RUNTIME_REPLACEMENT),
    ("instance-media-probe-runtime", MEDIA_RUNTIME_ANCHOR, MEDIA_RUNTIME_REPLACEMENT),
    ("generation-fenced-mode-submit", SUBMIT_MODE_ANCHOR, SUBMIT_MODE_REPLACEMENT),
    ("resource-mode-generation", RESOURCE_MODE_SIGNATURE_ANCHOR,
     RESOURCE_MODE_SIGNATURE_REPLACEMENT),
    ("resource-mode-api-generation", RESOURCE_MODE_API_ANCHOR,
     RESOURCE_MODE_API_REPLACEMENT),
    ("resource-mode-post-fence", RESOURCE_MODE_FINISH_ANCHOR,
     RESOURCE_MODE_FINISH_REPLACEMENT),
    ("resource-candidates-generation", RESOURCE_CANDIDATES_SIGNATURE_ANCHOR,
     RESOURCE_CANDIDATES_SIGNATURE_REPLACEMENT),
    ("resource-candidates-supplement-generation",
     RESOURCE_CANDIDATES_SUPPLEMENT_ANCHOR,
     RESOURCE_CANDIDATES_SUPPLEMENT_REPLACEMENT),
    ("resource-candidates-mode-generation", RESOURCE_CANDIDATES_SUBMIT_ANCHOR,
     RESOURCE_CANDIDATES_SUBMIT_REPLACEMENT),
    ("resource-candidates-post-fence", RESOURCE_CANDIDATES_POST_FENCE_ANCHOR,
     RESOURCE_CANDIDATES_POST_FENCE_REPLACEMENT),
    ("foreground-generation", FOREGROUND_GENERATION_ANCHOR,
     FOREGROUND_GENERATION_REPLACEMENT),
    ("bound-replacement-generation", BOUND_REPLACEMENT_GENERATION_ANCHOR,
     BOUND_REPLACEMENT_GENERATION_REPLACEMENT),
    ("preheat-generation", PREHEAT_GENERATION_ANCHOR,
     PREHEAT_GENERATION_REPLACEMENT),
    ("resource-api-generation-and-response-owner", RESOURCE_API_OWNER_ANCHOR,
     RESOURCE_API_OWNER_REPLACEMENT),
    ("destroy-search-job-cleanup", DESTROY_JOB_CLEANUP_ANCHOR,
     DESTROY_JOB_CLEANUP_REPLACEMENT),
    ("remove-admission-attribute", ADMISSION_ATTRIBUTE_ANCHOR,
     ADMISSION_ATTRIBUTE_REPLACEMENT),
    ("bulkhead-only-supplement-admission", SUPPLEMENT_ADMISSION_ANCHOR,
     SUPPLEMENT_ADMISSION_REPLACEMENT),
    ("supplement-mode-generation", SUPPLEMENT_MODE_GENERATION_ANCHOR,
     SUPPLEMENT_MODE_GENERATION_REPLACEMENT),
    ("supplement-worker-owner-cleanup", SUPPLEMENT_WORKER_CLEANUP_ANCHOR,
     SUPPLEMENT_WORKER_CLEANUP_REPLACEMENT),
    ("supplement-submit-owner-cleanup", SUPPLEMENT_SUBMIT_CLEANUP_ANCHOR,
     SUPPLEMENT_SUBMIT_CLEANUP_REPLACEMENT),
)


def _replace_once(text, anchor, replacement, label):
    count = text.count(anchor)
    if count != 1:
        raise SearchConcurrencyOwnershipOverlayError(
            "search concurrency ownership anchor %s must appear once, found %d"
            % (label, count)
        )
    return text.replace(anchor, replacement, 1)


def _spider(tree):
    classes = [
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "Spider"
    ]
    if len(classes) != 1:
        raise SearchConcurrencyOwnershipOverlayError("expected one Spider class")
    return classes[0]


def _method(spider, name):
    methods = [
        node for node in spider.body
        if isinstance(node, ast.FunctionDef) and node.name == name
    ]
    if len(methods) != 1:
        raise SearchConcurrencyOwnershipOverlayError(
            "expected one Spider.%s method" % name
        )
    return methods[0]


def _call_name(node):
    if not isinstance(node, ast.Call):
        return None
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None


def _self_attribute(node, name):
    return (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "self"
        and node.attr == name
    )


def _has_keyword(call, name):
    return any(keyword.arg == name for keyword in call.keywords)


def _calls(method, name):
    return [
        node for node in ast.walk(method)
        if isinstance(node, ast.Call) and _call_name(node) == name
    ]


def _require_generation_calls(method, call_name, owner_label):
    calls = _calls(method, call_name)
    if not calls or any(
            not _has_keyword(call, "expected_generation") for call in calls):
        raise SearchConcurrencyOwnershipOverlayError(
            "%s must pass expected_generation to %s" % (owner_label, call_name)
        )


def _audit_output(input_tree, output_tree):
    input_spider = _spider(input_tree)
    output_spider = _spider(output_tree)
    if ast.dump(_method(input_spider, "_read_bounded_json_response")) != ast.dump(
            _method(output_spider, "_read_bounded_json_response")):
        raise SearchConcurrencyOwnershipOverlayError(
            "shared bounded reader must remain unchanged"
        )

    runtime = _method(output_spider, "_create_task_runtime")
    instance_executors = {
        "_resource_search_executor", "_follow_refresh_executor",
        "_resource_foreground_mode_executor",
        "_resource_background_mode_executor",
        "_dns_executor", "_media_probe_executor",
    }
    instance_slots = {
        "_resource_foreground_mode_slots", "_resource_background_mode_slots",
        "_dns_slots", "_media_probe_slots",
    }
    assigned = {
        target.attr
        for node in ast.walk(runtime)
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Attribute)
        and isinstance(target.value, ast.Name)
        and target.value.id == "self"
    }
    loop_executors = set()
    register_calls = 0
    for node in ast.walk(runtime):
        if (
                isinstance(node, ast.For)
                and isinstance(node.target, ast.Name)
                and node.target.id == "_executor"
                and isinstance(node.iter, (ast.Tuple, ast.List))):
            loop_executors.update(
                value.attr for value in node.iter.elts
                if isinstance(value, ast.Attribute)
                and isinstance(value.value, ast.Name)
                and value.value.id == "self"
            )
        if (
                isinstance(node, ast.Call)
                and _call_name(node) == "register_executor"
                and node.args
                and isinstance(node.args[0], ast.Name)
                and node.args[0].id == "_executor"):
            register_calls += 1
    if (
            not instance_executors.issubset(assigned)
            or not instance_slots.issubset(assigned)
            or not instance_executors.issubset(loop_executors)
            or register_calls != 1):
        raise SearchConcurrencyOwnershipOverlayError(
            "all instance executors and slots must be created and registered"
        )
    for method_name, executor_name, slot_name in (
        ("_resolve_addresses", "_dns_executor", "_dns_slots"),
        ("_pinned_media_request", "_media_probe_executor", "_media_probe_slots"),
    ):
        method = _method(output_spider, method_name)
        attributes = {
            node.attr for node in ast.walk(method)
            if isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "self"
        }
        if executor_name not in attributes or slot_name not in attributes:
            raise SearchConcurrencyOwnershipOverlayError(
                "%s must use its instance executor and slot" % method_name
            )
    forbidden_globals = {
        "_DNS_EXECUTOR", "_DNS_SLOTS", "_MEDIA_PROBE_EXECUTOR",
        "_MEDIA_PROBE_SLOTS",
    }
    if any(
        isinstance(node, ast.Name)
        and node.id in forbidden_globals
        for node in ast.walk(output_tree)
    ):
        raise SearchConcurrencyOwnershipOverlayError(
            "module-level DNS/media runtime owners must not exist"
        )

    init_method = _method(output_spider, "_init_locked")
    init_shutdown = _calls(init_method, "shutdown")
    init_create = _calls(init_method, "_create_task_runtime")
    if not (
            len(init_shutdown) == 1
            and len(init_create) == 1
            and init_shutdown[0].lineno < init_create[0].lineno):
        raise SearchConcurrencyOwnershipOverlayError(
            "live init must seal the old task runtime before rebuilding"
        )

    submit = _method(output_spider, "_submit_resource_mode_search")
    if "expected_generation" not in [argument.arg for argument in submit.args.args]:
        raise SearchConcurrencyOwnershipOverlayError(
            "mode submit must accept expected_generation"
        )
    scope_calls = [
        node for node in ast.walk(submit)
        if isinstance(node, ast.Call) and _call_name(node) == "scope"
    ]
    if not (
        len(scope_calls) == 1
        and _has_keyword(scope_calls[0], "expected_generation")
        and _has_keyword(scope_calls[0], "deadline")
    ):
        raise SearchConcurrencyOwnershipOverlayError(
            "mode worker must own one generation-bound timeout scope"
        )
    _require_generation_calls(
        submit, "_resource_search_mode", "mode submit worker",
    )

    resource_mode = _method(output_spider, "_resource_search_mode")
    if "expected_generation" not in [
            argument.arg for argument in resource_mode.args.args]:
        raise SearchConcurrencyOwnershipOverlayError(
            "resource mode must accept expected_generation"
        )
    _require_generation_calls(
        resource_mode, "_resource_api_get", "resource mode",
    )

    resource_api = _method(output_spider, "_resource_api_get")
    unbounded = _method(output_spider, "_v80_resource_api_get_unbounded")
    for method, label in (
            (resource_api, "resource API"),
            (unbounded, "unbounded resource API")):
        if "expected_generation" not in [
                argument.arg for argument in method.args.args]:
            raise SearchConcurrencyOwnershipOverlayError(
                "%s must accept expected_generation" % label
            )
    unbounded_calls = _calls(resource_api, "_v80_resource_api_get_unbounded")
    if not (
            len(unbounded_calls) == 1
            and _has_keyword(unbounded_calls[0], "expected_generation")
            and _has_keyword(unbounded_calls[0], "timeout_operation")):
        raise SearchConcurrencyOwnershipOverlayError(
            "resource API must pass generation and timeout owner to unbounded"
        )
    if _calls(unbounded, "_read_bounded_json_response"):
        raise SearchConcurrencyOwnershipOverlayError(
            "resource API must not reuse the shared bounded reader owner"
        )
    if not (
            len(_calls(unbounded, "_read_bounded_json_shared")) == 1
            and len(_calls(unbounded, "track")) == 1
            and len(_calls(unbounded, "close_tracked")) == 1):
        raise SearchConcurrencyOwnershipOverlayError(
            "resource API must locally track, read, and close its response"
        )

    candidates = _method(output_spider, "_resource_candidates")
    _require_generation_calls(
        candidates, "_submit_resource_mode_search", "resource candidates",
    )
    _require_generation_calls(
        candidates, "_schedule_supplement_resource_search",
        "resource candidates",
    )
    supplement = _method(output_spider, "_schedule_supplement_resource_search")
    if "expected_generation" not in [
            argument.arg for argument in supplement.args.args]:
        raise SearchConcurrencyOwnershipOverlayError(
            "supplement scheduler must accept expected_generation"
        )
    _require_generation_calls(
        supplement, "_submit_resource_mode_search", "supplement scheduler",
    )
    for method_name in (
            "_alist_detail_from_metadata", "_schedule_bound_route_replacement",
            "_schedule_entry_resource_preheat"):
        _require_generation_calls(
            _method(output_spider, method_name),
            "_resource_candidates", method_name,
        )
    if any(
        _self_attribute(node, "_resource_search_admissions")
        for node in ast.walk(output_spider)
    ):
        raise SearchConcurrencyOwnershipOverlayError(
            "resource search capacity must be owned only by the bulkhead"
        )


def apply_search_concurrency_ownership_overlay(source):
    try:
        raw = bytes(source)
        text = raw.decode("utf-8")
    except (TypeError, ValueError, UnicodeDecodeError) as exc:
        raise SearchConcurrencyOwnershipOverlayError(
            "search concurrency ownership input is not valid UTF-8 bytes"
        ) from exc
    output = text
    labels = []
    for label, anchor, replacement in INSERTIONS:
        output = _replace_once(output, anchor, replacement, label)
        labels.append(label)
    try:
        input_tree = ast.parse(text)
    except SyntaxError as exc:
        raise SearchConcurrencyOwnershipOverlayError(
            "search concurrency ownership input is invalid Python: %s" % exc
        ) from exc
    try:
        output_tree = ast.parse(output)
    except SyntaxError as exc:
        raise SearchConcurrencyOwnershipOverlayError(
            "search concurrency ownership overlay produced invalid Python: %s" % exc
        ) from exc
    _audit_output(input_tree, output_tree)
    data = output.encode("utf-8")
    return {
        "bytes": data,
        "size": len(data),
        "sha256": hashlib.sha256(data).hexdigest().upper(),
        "input_size": len(raw),
        "input_sha256": hashlib.sha256(raw).hexdigest().upper(),
        "alias_zh": OVERLAY_ALIAS_ZH,
        "insertions": tuple(labels),
    }

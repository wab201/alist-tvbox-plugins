"""Insert independent P3 background bulkhead seams into isolated V80 source."""

import ast
import hashlib


class BackgroundBulkheadOverlayError(RuntimeError):
    pass


STATE_ANCHOR = '''        self._cache_health_controller = CacheHealthController(self)
'''

STATE_REPLACEMENT = STATE_ANCHOR + '''        self._background_bulkhead_controller = BackgroundBulkheadController(
            generation=self._cache_generation,
        )
'''

TASK_RUNTIME_ANCHOR = '''        for _executor in (
                self._resource_search_executor,
                self._follow_refresh_executor,
                self._resource_foreground_mode_executor,
                self._resource_background_mode_executor):
            self._tasks.register_executor(_executor)

    def _diagnostic_event(self, event, level="INFO", exc=None, **fields):
'''

TASK_RUNTIME_REPLACEMENT = '''        for _executor in (
                self._resource_search_executor,
                self._follow_refresh_executor,
                self._resource_foreground_mode_executor,
                self._resource_background_mode_executor):
            self._tasks.register_executor(_executor)

    def _submit_background_bulkhead_task(
            self, lane, generation, worker, name, executor=None):
        lease = self._background_bulkhead_controller.acquire(lane, generation)
        if lease is None:
            return False

        def guarded():
            try:
                return worker()
            finally:
                lease.finish()

        try:
            if executor is None:
                self._tasks.start_thread(guarded, name=name)
            else:
                executor.submit(guarded)
        except Exception:
            lease.finish()
            raise
        return True

    def _diagnostic_event(self, event, level="INFO", exc=None, **fields):
'''

INIT_RESET_ANCHOR = '''                self._cache_generation += 1
                self._resource_candidate_shadow_sampled_generation = None
'''

INIT_RESET_REPLACEMENT = '''                self._cache_generation += 1
                self._background_bulkhead_controller.reset(self._cache_generation)
                self._resource_candidate_shadow_sampled_generation = None
'''

DESTROY_RESET_ANCHOR = '''                    self._cache_generation += 1
                    provider_controller = getattr(self, "_provider_reliability_controller", None)
'''

DESTROY_RESET_REPLACEMENT = '''                    self._cache_generation += 1
                    self._background_bulkhead_controller.reset(self._cache_generation)
                    provider_controller = getattr(self, "_provider_reliability_controller", None)
'''

BOUND_REPLACEMENT_SUBMIT_ANCHOR = '''        try:
            self._tasks.start_thread(worker, name="bound-route-replacement")
        except Exception:
            with self._cache_lock:
                if self._bound_replacement_jobs.get(job_key) is job_owner:
                    self._bound_replacement_jobs.pop(job_key, None)
            return False
        return True
'''

BOUND_REPLACEMENT_SUBMIT_REPLACEMENT = '''        try:
            submitted = self._submit_background_bulkhead_task(
                "resource_completion", generation, worker, "bound-route-replacement")
        except Exception:
            submitted = False
        if not submitted:
            with self._cache_lock:
                if self._bound_replacement_jobs.get(job_key) is job_owner:
                    self._bound_replacement_jobs.pop(job_key, None)
            return False
        return True
'''

ENTRY_PREHEAT_SUBMIT_ANCHOR = '''            try:
                self._resource_search_executor.submit(worker)
                scheduled = True
            except Exception:
                with self._cache_lock:
                    if self._resource_entry_preheat_jobs.get(key) is owner:
                        self._resource_entry_preheat_jobs.pop(key, None)
        return scheduled
'''

ENTRY_PREHEAT_SUBMIT_REPLACEMENT = '''            try:
                submitted = self._submit_background_bulkhead_task(
                    "resource_completion", generation, worker,
                    "resource-entry-preheat", executor=self._resource_search_executor)
            except Exception:
                with self._cache_lock:
                    if self._resource_entry_preheat_jobs.get(key) is owner:
                        self._resource_entry_preheat_jobs.pop(key, None)
                continue
            if submitted:
                scheduled = True
            else:
                with self._cache_lock:
                    if self._resource_entry_preheat_jobs.get(key) is owner:
                        self._resource_entry_preheat_jobs.pop(key, None)
                break
        return scheduled
'''

SUPPLEMENT_SUBMIT_ANCHOR = '''        try:
            self._resource_search_executor.submit(worker)
        except Exception:
            with self._cache_lock:
                if self._resource_search_jobs.get(cache_key) is job_id:
                    self._resource_search_jobs.pop(cache_key, None)
                    if self._refreshing_cache_keys.get(cache_key) is job_id:
                        self._refreshing_cache_keys.pop(cache_key, None)
                self._resource_search_admissions = max(0, self._resource_search_admissions - 1)
            return False
        return True
'''

SUPPLEMENT_SUBMIT_REPLACEMENT = '''        try:
            submitted = self._submit_background_bulkhead_task(
                "resource_completion", generation, worker,
                "supplement-resource-search", executor=self._resource_search_executor)
        except Exception:
            submitted = False
        if not submitted:
            with self._cache_lock:
                if self._resource_search_jobs.get(cache_key) is job_id:
                    self._resource_search_jobs.pop(cache_key, None)
                    if self._refreshing_cache_keys.get(cache_key) is job_id:
                        self._refreshing_cache_keys.pop(cache_key, None)
                self._resource_search_admissions = max(0, self._resource_search_admissions - 1)
            return False
        return True
'''

HISTORY_REFRESH_SUBMIT_ANCHOR = '''        try:
            self._tasks.start_thread(worker, name="history-sync")
        except Exception as exc:
            with self._cache_lock:
                if self._refreshing_cache_keys.get(cache_key) is job_owner:
                    self._refreshing_cache_keys.pop(cache_key, None)
            with self._atvp_job_lock:
                self._atvp_jobs.discard(job_kind)
            if not lightweight:
                self._set_atvp_status(
                    "sync", "failed", "History 后台同步启动失败：%s" % self._short_error(exc),
                )
            return False
        return True
'''

HISTORY_REFRESH_SUBMIT_REPLACEMENT = '''        try:
            submitted = self._submit_background_bulkhead_task(
                "history", generation, worker, "history-sync")
        except Exception as exc:
            with self._cache_lock:
                if self._refreshing_cache_keys.get(cache_key) is job_owner:
                    self._refreshing_cache_keys.pop(cache_key, None)
            with self._atvp_job_lock:
                self._atvp_jobs.discard(job_kind)
            if not lightweight:
                self._set_atvp_status(
                    "sync", "failed", "History 后台同步启动失败：%s" % self._short_error(exc),
                )
            return False
        if not submitted:
            with self._cache_lock:
                if self._refreshing_cache_keys.get(cache_key) is job_owner:
                    self._refreshing_cache_keys.pop(cache_key, None)
            with self._atvp_job_lock:
                self._atvp_jobs.discard(job_kind)
            if not lightweight:
                self._set_atvp_status(
                    "sync", "failed", "History 后台任务繁忙，请稍后重试",
                )
            return False
        return True
'''

HISTORY_ACTION_SUBMIT_ANCHOR = '''        try:
            self._tasks.start_thread(
                self._run_atvp_job, args=(kind, generation), name="atvp-%s" % kind,
            )
        except Exception as exc:
            with self._atvp_job_lock:
                self._atvp_jobs.discard(kind)
            self._set_atvp_status(
                kind, "failed", "%s启动失败：%s" % (label, self._short_error(exc)),
            )
            return json.dumps({"msg": "%s启动失败，请重试" % label}, ensure_ascii=False)
        return json.dumps({"msg": "%s已开始，完成后本页会自动刷新" % label}, ensure_ascii=False)
'''

HISTORY_ACTION_SUBMIT_REPLACEMENT = '''        def worker():
            return self._run_atvp_job(kind, generation)

        try:
            submitted = self._submit_background_bulkhead_task(
                "history", generation, worker, "atvp-%s" % kind)
        except Exception as exc:
            with self._atvp_job_lock:
                self._atvp_jobs.discard(kind)
            self._set_atvp_status(
                kind, "failed", "%s启动失败：%s" % (label, self._short_error(exc)),
            )
            return json.dumps({"msg": "%s启动失败，请重试" % label}, ensure_ascii=False)
        if not submitted:
            with self._atvp_job_lock:
                self._atvp_jobs.discard(kind)
            self._set_atvp_status(
                kind, "failed", "%s后台任务繁忙，请稍后重试" % label,
            )
            return json.dumps({"msg": "%s后台任务繁忙，请稍后重试" % label}, ensure_ascii=False)
        return json.dumps({"msg": "%s已开始，完成后本页会自动刷新" % label}, ensure_ascii=False)
'''

ROUTE_PROBE_SUBMIT_ANCHOR = '''            try:
                self._tasks.start_thread(worker, name="route-probe")
            except Exception:
                with self._cache_lock:
                    if self._route_probe_jobs.get(probe_key) is job_owner:
                        self._route_probe_jobs.pop(probe_key, None)
'''

ROUTE_PROBE_SUBMIT_REPLACEMENT = '''            try:
                submitted = self._submit_background_bulkhead_task(
                    "route_probe", generation, worker, "route-probe")
            except Exception:
                with self._cache_lock:
                    if self._route_probe_jobs.get(probe_key) is job_owner:
                        self._route_probe_jobs.pop(probe_key, None)
                continue
            if not submitted:
                with self._cache_lock:
                    if self._route_probe_jobs.get(probe_key) is job_owner:
                        self._route_probe_jobs.pop(probe_key, None)
'''

INSERTIONS = (
    ("state", STATE_ANCHOR, STATE_REPLACEMENT),
    ("task-runtime", TASK_RUNTIME_ANCHOR, TASK_RUNTIME_REPLACEMENT),
    ("init-reset", INIT_RESET_ANCHOR, INIT_RESET_REPLACEMENT),
    ("destroy-reset", DESTROY_RESET_ANCHOR, DESTROY_RESET_REPLACEMENT),
    ("bound-replacement", BOUND_REPLACEMENT_SUBMIT_ANCHOR, BOUND_REPLACEMENT_SUBMIT_REPLACEMENT),
    ("entry-preheat", ENTRY_PREHEAT_SUBMIT_ANCHOR, ENTRY_PREHEAT_SUBMIT_REPLACEMENT),
    ("supplement-search", SUPPLEMENT_SUBMIT_ANCHOR, SUPPLEMENT_SUBMIT_REPLACEMENT),
    ("history-refresh", HISTORY_REFRESH_SUBMIT_ANCHOR, HISTORY_REFRESH_SUBMIT_REPLACEMENT),
    ("history-action", HISTORY_ACTION_SUBMIT_ANCHOR, HISTORY_ACTION_SUBMIT_REPLACEMENT),
    ("route-probe", ROUTE_PROBE_SUBMIT_ANCHOR, ROUTE_PROBE_SUBMIT_REPLACEMENT),
)


def _replace_once(text, anchor, replacement, label):
    count = text.count(anchor)
    if count != 1:
        raise BackgroundBulkheadOverlayError(
            "background bulkhead overlay anchor %s must occur once, found %d"
            % (label, count)
        )
    return text.replace(anchor, replacement, 1)


def _class(tree, name):
    values = [
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == name
    ]
    if len(values) != 1:
        raise BackgroundBulkheadOverlayError(
            "background bulkhead overlay class %s must occur once" % name
        )
    return values[0]


def _method(class_node, name):
    values = [
        node for node in class_node.body
        if isinstance(node, ast.FunctionDef) and node.name == name
    ]
    if len(values) != 1:
        raise BackgroundBulkheadOverlayError(
            "background bulkhead overlay method %s must occur once" % name
        )
    return values[0]


def _helper_calls(node):
    return [
        item for item in ast.walk(node)
        if isinstance(item, ast.Call)
        and isinstance(item.func, ast.Attribute)
        and item.func.attr == "_submit_background_bulkhead_task"
    ]


def _controller_calls(node, name):
    return [
        item for item in ast.walk(node)
        if isinstance(item, ast.Call)
        and isinstance(item.func, ast.Attribute)
        and item.func.attr == name
        and isinstance(item.func.value, ast.Attribute)
        and item.func.value.attr == "_background_bulkhead_controller"
    ]


def _lane_literal(call):
    if not call.args or not isinstance(call.args[0], ast.Constant):
        return None
    return call.args[0].value


def apply_background_bulkhead_overlay(source):
    try:
        text = bytes(source).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise BackgroundBulkheadOverlayError(
            "background bulkhead overlay input is not valid UTF-8"
        ) from exc
    input_bytes = text.encode("utf-8")
    for label, anchor, replacement in INSERTIONS:
        text = _replace_once(text, anchor, replacement, label)

    try:
        tree = ast.parse(text, filename="build/v80-dev/background-bulkhead-overlay.py")
        compile(tree, "build/v80-dev/background-bulkhead-overlay.py", "exec")
    except SyntaxError as exc:
        raise BackgroundBulkheadOverlayError(
            "background bulkhead overlay output is invalid: %s" % exc
        ) from exc

    spider = _class(tree, "Spider")
    init = _method(spider, "__init__")
    constructors = [
        item for item in ast.walk(init)
        if isinstance(item, ast.Call)
        and isinstance(item.func, ast.Name)
        and item.func.id == "BackgroundBulkheadController"
    ]
    if len(constructors) != 1:
        raise BackgroundBulkheadOverlayError(
            "background bulkhead controller must be constructed once"
        )

    submit = _method(spider, "_submit_background_bulkhead_task")
    if len(_controller_calls(submit, "acquire")) != 1:
        raise BackgroundBulkheadOverlayError(
            "background bulkhead submit helper must acquire once"
        )
    finishes = [
        item for item in ast.walk(submit)
        if isinstance(item, ast.Call)
        and isinstance(item.func, ast.Attribute)
        and item.func.attr == "finish"
    ]
    if len(finishes) != 2:
        raise BackgroundBulkheadOverlayError(
            "background bulkhead submit helper must release on completion and submit failure"
        )

    for lifecycle in ("_init_locked", "destroy"):
        resets = _controller_calls(_method(spider, lifecycle), "reset")
        if len(resets) != 1:
            raise BackgroundBulkheadOverlayError(
                "background bulkhead %s reset seam is invalid" % lifecycle
            )

    expected_lanes = {
        "_schedule_bound_route_replacement": "resource_completion",
        "_schedule_entry_resource_preheat": "resource_completion",
        "_schedule_supplement_resource_search": "resource_completion",
        "_schedule_atvp_history_refresh": "history",
        "_start_atvp_job": "history",
        "_schedule_route_preheat": "route_probe",
    }
    for method_name, lane in expected_lanes.items():
        calls = _helper_calls(_method(spider, method_name))
        if len(calls) != 1 or _lane_literal(calls[0]) != lane:
            raise BackgroundBulkheadOverlayError(
                "background bulkhead lane %s is invalid" % method_name
            )

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
        "import apply_background_bulkhead_overlay from the V80 build pipeline"
    )


if __name__ == "__main__":
    main()

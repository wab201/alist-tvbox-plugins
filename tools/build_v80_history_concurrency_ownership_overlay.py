"""Apply the P5-5F History task-generation ownership fixes."""

import ast
import hashlib


OVERLAY_ALIAS_ZH = "History 并发所有权覆盖层"
EXPECTED_INPUT_SIZE = 863231
EXPECTED_INPUT_SHA256 = (
    "ACFCBE12924D8A4F2C266CB9370DD24D0B9D0D876FB4A1FF898FF819C3F0BCE6"
)


class HistoryConcurrencyOwnershipOverlayError(RuntimeError):
    pass


JOB_OWNER_ATTRIBUTE_ANCHOR = '''        self._atvp_job_lock = threading.RLock()
        self._atvp_jobs = set()
        self._atvp_status = {}
'''
JOB_OWNER_ATTRIBUTE_REPLACEMENT = '''        self._atvp_job_lock = threading.RLock()
        self._atvp_jobs = set()
        self._atvp_job_owners = {}
        self._atvp_status = {}
'''


LIVE_INIT_OWNER_RESET_ANCHOR = '''    def _init_locked(self, extend=""):
        previous_tasks = self._tasks
        with self._cache_lock:
'''
LIVE_INIT_OWNER_RESET_REPLACEMENT = '''    def _init_locked(self, extend=""):
        previous_tasks = self._tasks
        with self._atvp_job_lock:
            self._atvp_jobs.clear()
            self._atvp_job_owners.clear()
        with self._cache_lock:
'''


DESTROY_OWNER_RESET_ANCHOR = '''    def destroy(self):
        with self._history_context_lock:
            v80_history_queue_stop(self)
'''
DESTROY_OWNER_RESET_REPLACEMENT = '''    def destroy(self):
        with self._history_context_lock:
            with self._atvp_job_lock:
                self._atvp_jobs.clear()
                self._atvp_job_owners.clear()
            v80_history_queue_stop(self)
'''


BACKGROUND_ADMISSION_ANCHOR = '''        job_owner = object()
        with self._atvp_job_lock:
            if "sync" in self._atvp_jobs or "sync-background" in self._atvp_jobs:
                return False
            if job_kind in self._atvp_jobs:
                return False
            self._atvp_jobs.add(job_kind)
        with self._cache_lock:
            if lightweight and self._has_cached_failure(cache_key):
                with self._atvp_job_lock:
                    self._atvp_jobs.discard(job_kind)
                return False
            if cache_key in self._refreshing_cache_keys:
                with self._atvp_job_lock:
                    self._atvp_jobs.discard(job_kind)
                return False
            self._refreshing_cache_keys[cache_key] = job_owner
            generation = self._cache_generation
'''
BACKGROUND_ADMISSION_REPLACEMENT = '''        job_owner = object()
        with self._history_context_lock:
            with self._atvp_job_lock:
                if "sync" in self._atvp_jobs or "sync-background" in self._atvp_jobs:
                    return False
                if job_kind in self._atvp_jobs:
                    return False
                with self._cache_lock:
                    if lightweight and self._has_cached_failure(cache_key):
                        return False
                    if cache_key in self._refreshing_cache_keys:
                        return False
                    self._refreshing_cache_keys[cache_key] = job_owner
                    generation = self._cache_generation
                self._atvp_jobs.add(job_kind)
                self._atvp_job_owners[job_kind] = job_owner
'''


BACKGROUND_FINALLY_ANCHOR = '''            finally:
                with self._cache_lock:
                    if self._refreshing_cache_keys.get(cache_key) is job_owner:
                        self._refreshing_cache_keys.pop(cache_key, None)
                with self._atvp_job_lock:
                    self._atvp_jobs.discard(job_kind)

        try:
'''
BACKGROUND_FINALLY_REPLACEMENT = '''            finally:
                with self._atvp_job_lock:
                    if self._atvp_job_owners.get(job_kind) is job_owner:
                        with self._cache_lock:
                            if self._refreshing_cache_keys.get(cache_key) is job_owner:
                                self._refreshing_cache_keys.pop(cache_key, None)
                        self._atvp_job_owners.pop(job_kind, None)
                        self._atvp_jobs.discard(job_kind)

        try:
'''


BACKGROUND_SUBMIT_EXCEPTION_ANCHOR = '''        except Exception as exc:
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
'''
BACKGROUND_SUBMIT_EXCEPTION_REPLACEMENT = '''        except Exception as exc:
            persist_failure = False
            with self._history_context_lock:
                with self._atvp_job_lock:
                    if self._atvp_job_owners.get(job_kind) is job_owner:
                        with self._cache_lock:
                            if self._refreshing_cache_keys.get(cache_key) is job_owner:
                                self._refreshing_cache_keys.pop(cache_key, None)
                        self._atvp_job_owners.pop(job_kind, None)
                        self._atvp_jobs.discard(job_kind)
                        if not lightweight:
                            self._set_atvp_status(
                                "sync", "failed", "History 后台同步启动失败：%s" % self._short_error(exc),
                                persist=False,
                            )
                            persist_failure = True
            if persist_failure:
                self._persist_atvp_status()
            return False
'''


BACKGROUND_NOT_SUBMITTED_ANCHOR = '''        if not submitted:
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
'''
BACKGROUND_NOT_SUBMITTED_REPLACEMENT = '''        if not submitted:
            persist_failure = False
            with self._history_context_lock:
                with self._atvp_job_lock:
                    if self._atvp_job_owners.get(job_kind) is job_owner:
                        with self._cache_lock:
                            if self._refreshing_cache_keys.get(cache_key) is job_owner:
                                self._refreshing_cache_keys.pop(cache_key, None)
                        self._atvp_job_owners.pop(job_kind, None)
                        self._atvp_jobs.discard(job_kind)
                        if not lightweight:
                            self._set_atvp_status(
                                "sync", "failed", "History 后台任务繁忙，请稍后重试",
                                persist=False,
                            )
                            persist_failure = True
            if persist_failure:
                self._persist_atvp_status()
            return False
'''


MANUAL_ADMISSION_ANCHOR = '''        label = labels.get(kind, "后台任务")
        with self._cache_lock:
            generation = self._cache_generation
        with self._atvp_job_lock:
            if kind == "sync" and "sync-background" in self._atvp_jobs:
                return json.dumps({"msg": "History 后台同步正在进行，请稍后查看管理页状态"}, ensure_ascii=False)
            if kind in self._atvp_jobs:
                return json.dumps({"msg": "%s正在进行，请稍后查看卡片结果" % label}, ensure_ascii=False)
            self._atvp_jobs.add(kind)
            self._set_atvp_status(
                kind, "running", "%s已开始，请稍后查看卡片结果" % label, persist=False,
            )
'''
MANUAL_ADMISSION_REPLACEMENT = '''        label = labels.get(kind, "后台任务")
        job_owner = object()
        with self._history_context_lock:
            with self._atvp_job_lock:
                if kind == "sync" and "sync-background" in self._atvp_jobs:
                    return json.dumps({"msg": "History 后台同步正在进行，请稍后查看管理页状态"}, ensure_ascii=False)
                if kind in self._atvp_jobs:
                    return json.dumps({"msg": "%s正在进行，请稍后查看卡片结果" % label}, ensure_ascii=False)
                with self._cache_lock:
                    generation = self._cache_generation
                self._atvp_jobs.add(kind)
                self._atvp_job_owners[kind] = job_owner
                self._set_atvp_status(
                    kind, "running", "%s已开始，请稍后查看卡片结果" % label, persist=False,
                )
'''


MANUAL_WORKER_CALL_ANCHOR = '''        def worker():
            return self._run_atvp_job(kind, generation)

        try:
'''
MANUAL_WORKER_CALL_REPLACEMENT = '''        def worker():
            return self._run_atvp_job(kind, generation, job_owner)

        try:
'''


MANUAL_SUBMIT_EXCEPTION_ANCHOR = '''        except Exception as exc:
            with self._atvp_job_lock:
                self._atvp_jobs.discard(kind)
            self._set_atvp_status(
                kind, "failed", "%s启动失败：%s" % (label, self._short_error(exc)),
            )
            return json.dumps({"msg": "%s启动失败，请重试" % label}, ensure_ascii=False)
'''
MANUAL_SUBMIT_EXCEPTION_REPLACEMENT = '''        except Exception as exc:
            persist_failure = False
            with self._history_context_lock:
                with self._atvp_job_lock:
                    if self._atvp_job_owners.get(kind) is job_owner:
                        self._atvp_job_owners.pop(kind, None)
                        self._atvp_jobs.discard(kind)
                        self._set_atvp_status(
                            kind, "failed", "%s启动失败：%s" % (label, self._short_error(exc)),
                            persist=False,
                        )
                        persist_failure = True
            if persist_failure:
                self._persist_atvp_status()
            return json.dumps({"msg": "%s启动失败，请重试" % label}, ensure_ascii=False)
'''


MANUAL_NOT_SUBMITTED_ANCHOR = '''        if not submitted:
            with self._atvp_job_lock:
                self._atvp_jobs.discard(kind)
            self._set_atvp_status(
                kind, "failed", "%s后台任务繁忙，请稍后重试" % label,
            )
            return json.dumps({"msg": "%s后台任务繁忙，请稍后重试" % label}, ensure_ascii=False)
'''
MANUAL_NOT_SUBMITTED_REPLACEMENT = '''        if not submitted:
            persist_failure = False
            with self._history_context_lock:
                with self._atvp_job_lock:
                    if self._atvp_job_owners.get(kind) is job_owner:
                        self._atvp_job_owners.pop(kind, None)
                        self._atvp_jobs.discard(kind)
                        self._set_atvp_status(
                            kind, "failed", "%s后台任务繁忙，请稍后重试" % label,
                            persist=False,
                        )
                        persist_failure = True
            if persist_failure:
                self._persist_atvp_status()
            return json.dumps({"msg": "%s后台任务繁忙，请稍后重试" % label}, ensure_ascii=False)
'''


MANUAL_WORKER_SIGNATURE_ANCHOR = '''    def _run_atvp_job(self, kind, generation=None):
'''
MANUAL_WORKER_SIGNATURE_REPLACEMENT = '''    def _run_atvp_job(self, kind, generation=None, job_owner=None):
'''


MANUAL_WORKER_FINALLY_ANCHOR = '''        finally:
            with self._atvp_job_lock:
                self._atvp_jobs.discard(kind)
            if self._history_generation_active(generation):
                self._refresh_current_category()
'''
MANUAL_WORKER_FINALLY_REPLACEMENT = '''        finally:
            with self._atvp_job_lock:
                if self._atvp_job_owners.get(kind) is job_owner:
                    self._atvp_job_owners.pop(kind, None)
                    self._atvp_jobs.discard(kind)
            with self._history_context_lock:
                if self._history_generation_active(generation):
                    self._refresh_current_category()
'''


INSERTIONS = (
    ("history-job-owner-state", JOB_OWNER_ATTRIBUTE_ANCHOR,
     JOB_OWNER_ATTRIBUTE_REPLACEMENT),
    ("live-init-history-job-reset", LIVE_INIT_OWNER_RESET_ANCHOR,
     LIVE_INIT_OWNER_RESET_REPLACEMENT),
    ("destroy-history-job-reset", DESTROY_OWNER_RESET_ANCHOR,
     DESTROY_OWNER_RESET_REPLACEMENT),
    ("background-history-job-admission", BACKGROUND_ADMISSION_ANCHOR,
     BACKGROUND_ADMISSION_REPLACEMENT),
    ("background-history-worker-owner-release", BACKGROUND_FINALLY_ANCHOR,
     BACKGROUND_FINALLY_REPLACEMENT),
    ("background-history-submit-exception-release",
     BACKGROUND_SUBMIT_EXCEPTION_ANCHOR,
     BACKGROUND_SUBMIT_EXCEPTION_REPLACEMENT),
    ("background-history-busy-release", BACKGROUND_NOT_SUBMITTED_ANCHOR,
     BACKGROUND_NOT_SUBMITTED_REPLACEMENT),
    ("manual-history-job-admission", MANUAL_ADMISSION_ANCHOR,
     MANUAL_ADMISSION_REPLACEMENT),
    ("manual-history-worker-owner", MANUAL_WORKER_CALL_ANCHOR,
     MANUAL_WORKER_CALL_REPLACEMENT),
    ("manual-history-submit-exception-release", MANUAL_SUBMIT_EXCEPTION_ANCHOR,
     MANUAL_SUBMIT_EXCEPTION_REPLACEMENT),
    ("manual-history-busy-release", MANUAL_NOT_SUBMITTED_ANCHOR,
     MANUAL_NOT_SUBMITTED_REPLACEMENT),
    ("manual-history-worker-owner-argument", MANUAL_WORKER_SIGNATURE_ANCHOR,
     MANUAL_WORKER_SIGNATURE_REPLACEMENT),
    ("manual-history-worker-owner-release", MANUAL_WORKER_FINALLY_ANCHOR,
     MANUAL_WORKER_FINALLY_REPLACEMENT),
)


def _replace_once(text, anchor, replacement, label):
    count = text.count(anchor)
    if count != 1:
        raise HistoryConcurrencyOwnershipOverlayError(
            "History concurrency anchor %s must appear once, found %d"
            % (label, count)
        )
    return text.replace(anchor, replacement, 1)


def _spider(tree):
    classes = [
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "Spider"
    ]
    if len(classes) != 1:
        raise HistoryConcurrencyOwnershipOverlayError("expected one Spider class")
    return classes[0]


def _method(spider, name):
    methods = [
        node for node in spider.body
        if isinstance(node, ast.FunctionDef) and node.name == name
    ]
    if len(methods) != 1:
        raise HistoryConcurrencyOwnershipOverlayError(
            "expected one Spider.%s method" % name
        )
    return methods[0]


def _self_attribute(node, name):
    return (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "self"
        and node.attr == name
    )


def _call_name(node):
    if not isinstance(node, ast.Call):
        return None
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None


def _lock_name(node):
    if not isinstance(node, ast.With) or len(node.items) != 1:
        return None
    expression = node.items[0].context_expr
    if (
            isinstance(expression, ast.Attribute)
            and isinstance(expression.value, ast.Name)
            and expression.value.id == "self"):
        return expression.attr
    return None


def _audit_lock_order(method):
    order = {
        "_history_context_lock": 0,
        "_atvp_job_lock": 1,
        "_cache_lock": 2,
    }

    def visit(node, held):
        lock = _lock_name(node)
        current = held
        if lock in order:
            if held and order[lock] < max(order[name] for name in held):
                raise HistoryConcurrencyOwnershipOverlayError(
                    "%s reverses the History lock order" % method.name
                )
            current = held + (lock,)
        for child in ast.iter_child_nodes(node):
            visit(child, current)

    visit(method, ())


def _owner_identity_guards(method):
    return [
        node for node in ast.walk(method)
        if isinstance(node, ast.Compare)
        and len(node.ops) == 1
        and isinstance(node.ops[0], ast.Is)
        and any(_self_attribute(child, "_atvp_job_owners") for child in ast.walk(node))
    ]


def _audit_output(input_tree, output_tree):
    input_spider = _spider(input_tree)
    output_spider = _spider(output_tree)
    for unchanged in (
            "_atvp_sync_history", "_sync_history_once",
            "_playback_sync_check", "_schedule_native_history_ui_refresh"):
        if ast.dump(_method(input_spider, unchanged)) != ast.dump(
                _method(output_spider, unchanged)):
            raise HistoryConcurrencyOwnershipOverlayError(
                "%s must remain unchanged" % unchanged
            )

    schedule = _method(output_spider, "_schedule_atvp_history_refresh")
    start = _method(output_spider, "_start_atvp_job")
    worker = _method(output_spider, "_run_atvp_job")
    init = _method(output_spider, "_init_locked")
    destroy = _method(output_spider, "destroy")
    for method in (schedule, start, worker, init, destroy):
        _audit_lock_order(method)

    if len(_owner_identity_guards(schedule)) != 3:
        raise HistoryConcurrencyOwnershipOverlayError(
            "background History release paths must verify the job owner"
        )
    if len(_owner_identity_guards(start)) != 2:
        raise HistoryConcurrencyOwnershipOverlayError(
            "manual History submit failures must verify the job owner"
        )
    if len(_owner_identity_guards(worker)) != 1:
        raise HistoryConcurrencyOwnershipOverlayError(
            "manual History worker must release only its own job"
        )
    worker_args = [argument.arg for argument in worker.args.args]
    if "job_owner" not in worker_args:
        raise HistoryConcurrencyOwnershipOverlayError(
            "manual History worker must accept job_owner"
        )
    worker_calls = [
        node for node in ast.walk(start)
        if isinstance(node, ast.Call) and _call_name(node) == "_run_atvp_job"
    ]
    if not (
            len(worker_calls) == 1
            and len(worker_calls[0].args) == 3
            and isinstance(worker_calls[0].args[2], ast.Name)
            and worker_calls[0].args[2].id == "job_owner"):
        raise HistoryConcurrencyOwnershipOverlayError(
            "manual History scheduler must pass the exact job owner"
        )
    for method, label in ((init, "live init"), (destroy, "destroy")):
        clears = [
            node for node in ast.walk(method)
            if isinstance(node, ast.Call)
            and _call_name(node) == "clear"
            and isinstance(node.func, ast.Attribute)
            and _self_attribute(node.func.value, "_atvp_job_owners")
        ]
        if len(clears) != 1:
            raise HistoryConcurrencyOwnershipOverlayError(
                "%s must clear History job owners once" % label
            )


def apply_history_concurrency_ownership_overlay(source):
    try:
        raw = bytes(source)
        text = raw.decode("utf-8")
    except (TypeError, ValueError, UnicodeDecodeError) as exc:
        raise HistoryConcurrencyOwnershipOverlayError(
            "History concurrency input is not valid UTF-8 bytes"
        ) from exc
    input_sha256 = hashlib.sha256(raw).hexdigest().upper()
    if len(raw) != EXPECTED_INPUT_SIZE or input_sha256 != EXPECTED_INPUT_SHA256:
        raise HistoryConcurrencyOwnershipOverlayError(
            "History concurrency input does not match the P5-5E candidate"
        )
    output = text
    labels = []
    for label, anchor, replacement in INSERTIONS:
        output = _replace_once(output, anchor, replacement, label)
        labels.append(label)
    try:
        input_tree = ast.parse(text)
        output_tree = ast.parse(output)
    except SyntaxError as exc:
        raise HistoryConcurrencyOwnershipOverlayError(
            "History concurrency overlay produced invalid Python: %s" % exc
        ) from exc
    _audit_output(input_tree, output_tree)
    data = output.encode("utf-8")
    return {
        "bytes": data,
        "size": len(data),
        "sha256": hashlib.sha256(data).hexdigest().upper(),
        "input_size": len(raw),
        "input_sha256": input_sha256,
        "alias_zh": OVERLAY_ALIAS_ZH,
        "insertions": tuple(labels),
    }

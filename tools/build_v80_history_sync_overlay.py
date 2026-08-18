"""Route V80 History transport through the AList-TVBox 1.45 compatibility adapter."""

import ast
import hashlib


class HistorySyncOverlayError(RuntimeError):
    pass


FETCH_ANCHOR = '''    def fetch(self):
        owner = self.owner
        response = owner._atvp_history_request("GET", stream=True)
        if response.status_code in (401, 403):
            response.close()
            raise RuntimeError("AList-TVBox 历史令牌无效")
        if response.status_code != 200:
            try:
                raise RuntimeError(owner._atvp_history_http_error(response, "读取"))
            finally:
                response.close()
        value = owner._read_bounded_json_response(
            response, "AList-TVBox History", max_bytes=owner.HISTORY_RESPONSE_MAX_BYTES,
        )
        if not isinstance(value, list):
            raise RuntimeError("AList-TVBox 历史格式无效")
        return owner._normalize_history_rows(value)
'''

FETCH_REPLACEMENT = '''    def fetch(self):
        return v80_history_fetch(self.owner, self._legacy_fetch)

    def _legacy_fetch(self):
        owner = self.owner
        response = owner._atvp_history_request("GET", stream=True)
        if response.status_code in (401, 403):
            response.close()
            raise RuntimeError("AList-TVBox 历史令牌无效")
        if response.status_code != 200:
            try:
                raise RuntimeError(owner._atvp_history_http_error(response, "读取"))
            finally:
                response.close()
        value = owner._read_bounded_json_response(
            response, "AList-TVBox History", max_bytes=owner.HISTORY_RESPONSE_MAX_BYTES,
        )
        if not isinstance(value, list):
            raise RuntimeError("AList-TVBox 历史格式无效")
        return owner._normalize_history_rows(value)
'''

PUSH_ANCHOR = '''    def push(self, rows):
        owner = self.owner
        if not owner._history_write_enabled():
            raise RuntimeError("History 写入未启用：请同时配置用户名和密码")
        response = owner._atvp_history_request("POST", json=owner._history_upload_payload(rows))
        try:
            if response.status_code < 200 or response.status_code >= 300:
                raise RuntimeError(owner._atvp_history_http_error(response, "写入"))
        finally:
            try:
                response.close()
            except Exception:
                pass
'''

PUSH_REPLACEMENT = '''    def push(self, rows):
        return v80_history_push(self.owner, rows, self._legacy_push)

    def _legacy_push(self, rows):
        owner = self.owner
        if not owner._history_write_enabled():
            raise RuntimeError("History 写入未启用：请同时配置用户名和密码")
        response = owner._atvp_history_request("POST", json=owner._history_upload_payload(rows))
        try:
            if response.status_code < 200 or response.status_code >= 300:
                raise RuntimeError(owner._atvp_history_http_error(response, "写入"))
        finally:
            try:
                response.close()
            except Exception:
                pass
'''

DELETE_ANCHOR = '''    def _atvp_history_delete(self, key):
        history_key = str(key or "").strip()
'''

DELETE_REPLACEMENT = '''    def _atvp_history_delete(self, key):
        return v80_history_delete(self, key, self._atvp_history_delete_legacy)

    def _atvp_history_delete_legacy(self, key):
        history_key = str(key or "").strip()
'''

LOCAL_ROW_ANCHOR = '''    def _history_for_local(self, row):
        identity = self._history_identity(row)
        if not identity:
            return None
        output = {key: row.get(key) for key in self.HISTORY_FIELDS if key in row and key not in ("key", "uid")}
        output["key"] = "%s@@@%s@@@1" % identity
        output["cid"] = 1
        return output
'''

LOCAL_ROW_REPLACEMENT = '''    def _history_for_local(self, row):
        return v80_history_for_local(self, row)
'''

CLOUD_FETCH_ANCHOR = '''                cloud_rows = self._atvp_fetch_history()
                cloud_available = True
'''

CLOUD_FETCH_REPLACEMENT = '''                cloud_rows = v80_history_fetch(
                    self, self._history_coordinator._legacy_fetch, stateful=True,
                )
                cloud_available = True
'''

LOCAL_REFRESH_ANCHOR = '''        merged, uploads = self._merge_native_history(local_rows, cloud_rows)
'''

LOCAL_REFRESH_REPLACEMENT = '''        local_rows = v80_history_refresh_local_rows(self, local_rows)
        merged, uploads = self._merge_native_history(local_rows, cloud_rows)
'''

UPLOAD_COUNT_ANCHOR = '''                    self._atvp_history_push(permitted_uploads)
                    uploaded = len(permitted_uploads)
'''

UPLOAD_COUNT_REPLACEMENT = '''                    uploaded = max(
                        0, int(self._atvp_history_push(permitted_uploads) or 0),
                    )
'''

IMPORT_COMMIT_ANCHOR = '''                imported = self._import_native_history(import_rows)
                self._diagnostic_event("history_sync.import_finish", count=imported)
'''

IMPORT_COMMIT_REPLACEMENT = '''                imported = self._import_native_history(import_rows)
                v80_history_commit(self, imported=imported, expected=len(import_rows))
                self._diagnostic_event("history_sync.import_finish", count=imported)
'''

LIFECYCLE_ANCHOR = '''        self._schedule_entry_resource_preheat()

    def destroy(self):
        with self._history_context_lock:
'''

LIFECYCLE_REPLACEMENT = '''        v80_history_queue_start(self)
        self._schedule_entry_resource_preheat()

    def destroy(self):
        with self._history_context_lock:
            v80_history_queue_stop(self)
'''

INSERTIONS = (
    ("fetch", FETCH_ANCHOR, FETCH_REPLACEMENT),
    ("push", PUSH_ANCHOR, PUSH_REPLACEMENT),
    ("delete", DELETE_ANCHOR, DELETE_REPLACEMENT),
    ("local-row", LOCAL_ROW_ANCHOR, LOCAL_ROW_REPLACEMENT),
    ("cloud-fetch", CLOUD_FETCH_ANCHOR, CLOUD_FETCH_REPLACEMENT),
    ("local-refresh", LOCAL_REFRESH_ANCHOR, LOCAL_REFRESH_REPLACEMENT),
    ("upload-count", UPLOAD_COUNT_ANCHOR, UPLOAD_COUNT_REPLACEMENT),
    ("import-commit", IMPORT_COMMIT_ANCHOR, IMPORT_COMMIT_REPLACEMENT),
    ("lifecycle", LIFECYCLE_ANCHOR, LIFECYCLE_REPLACEMENT),
)


def _replace_once(text, anchor, replacement, label):
    count = text.count(anchor)
    if count != 1:
        raise HistorySyncOverlayError(
            "history sync overlay anchor %s must occur once, found %d" % (label, count)
        )
    return text.replace(anchor, replacement, 1)


def _replace_method_http_error(text, method_name, receiver):
    marker = "    def %s(" % method_name
    start = text.find(marker)
    if start < 0:
        raise HistorySyncOverlayError("history sync overlay method %s is missing" % method_name)
    end = text.find("\n    def ", start + len(marker))
    if end < 0:
        raise HistorySyncOverlayError("history sync overlay method %s has no boundary" % method_name)
    block = text[start:end]
    anchor = "raise RuntimeError(%s._atvp_history_http_error(response," % receiver
    replacement = "raise _V80HistoryHttpError(response.status_code, %s._atvp_history_http_error(response," % receiver
    count = block.count(anchor)
    if count != 1:
        raise HistorySyncOverlayError(
            "history sync overlay method %s HTTP error must occur once, found %d"
            % (method_name, count)
        )
    return text[:start] + block.replace(anchor, replacement, 1) + text[end:]


def apply_history_sync_overlay(source):
    try:
        text = bytes(source).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HistorySyncOverlayError("history sync overlay input is not valid UTF-8") from exc
    input_bytes = text.encode("utf-8")
    for label, anchor, replacement in INSERTIONS:
        text = _replace_once(text, anchor, replacement, label)
    text = _replace_method_http_error(text, "_legacy_push", "owner")
    text = _replace_method_http_error(text, "_atvp_history_delete_legacy", "self")
    try:
        tree = ast.parse(text, filename="build/v80-dev/history-sync-overlay.py")
        compile(tree, "build/v80-dev/history-sync-overlay.py", "exec")
    except SyntaxError as exc:
        raise HistorySyncOverlayError("history sync overlay output is invalid: %s" % exc) from exc

    classes = {node.name: node for node in tree.body if isinstance(node, ast.ClassDef)}
    coordinator = classes.get("_HistoryCoordinator")
    spider = classes.get("Spider")
    if coordinator is None or spider is None:
        raise HistorySyncOverlayError("history sync overlay requires coordinator and Spider classes")
    coordinator_methods = {node.name for node in coordinator.body if isinstance(node, ast.FunctionDef)}
    spider_methods = {node.name for node in spider.body if isinstance(node, ast.FunctionDef)}
    if not {"fetch", "_legacy_fetch", "push", "_legacy_push"}.issubset(coordinator_methods):
        raise HistorySyncOverlayError("history sync overlay did not preserve coordinator fallbacks")
    if not {
        "_atvp_history_delete", "_atvp_history_delete_legacy",
        "_history_for_local",
    }.issubset(spider_methods):
        raise HistorySyncOverlayError("history sync overlay did not preserve History fallbacks")

    calls = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    required_calls = {
        "v80_history_fetch", "v80_history_push", "v80_history_delete",
        "v80_history_for_local", "v80_history_refresh_local_rows", "v80_history_commit",
        "v80_history_queue_start", "v80_history_queue_stop",
    }
    if not required_calls.issubset(calls):
        raise HistorySyncOverlayError("history sync overlay is missing adapter calls")

    data = text.encode("utf-8")
    return {
        "bytes": data,
        "size": len(data),
        "sha256": hashlib.sha256(data).hexdigest().upper(),
        "input_size": len(input_bytes),
        "input_sha256": hashlib.sha256(input_bytes).hexdigest().upper(),
        "insertions": tuple(label for label, _anchor, _replacement in INSERTIONS),
    }

"""P5-2 运行时关联字段覆盖层: connect policy to the diagnostic owner."""

import ast
import hashlib


class ObservabilityRuntimeOverlayError(RuntimeError):
    pass


TIMEOUT_OPERATION_CORRELATION_ANCHOR = '''    __slots__ = (
        "_controller", "operation", "generation", "deadline", "_cancelled",
        "_finished", "_tracked", "_lock",
    )

    def __init__(self, controller, operation, generation, deadline):
        self._controller = controller
        self.operation = str(operation or "operation")
        self.generation = int(generation)
        self.deadline = float(deadline)
'''


TIMEOUT_OPERATION_CORRELATION_REPLACEMENT = '''    __slots__ = (
        "_controller", "operation", "generation", "deadline", "request_id",
        "trace_id", "_cancelled", "_finished", "_tracked", "_lock",
    )

    def __init__(
            self, controller, operation, generation, deadline,
            request_id, trace_id):
        self._controller = controller
        self.operation = str(operation or "operation")
        self.generation = int(generation)
        self.deadline = float(deadline)
        self.request_id = str(request_id)
        self.trace_id = str(trace_id)
'''


TIMEOUT_CONTROLLER_SLOT_ANCHOR = '''    __slots__ = (
        "_lock", "_local", "_active", "_generation", "_closed", "clock",
    )
'''


TIMEOUT_CONTROLLER_SLOT_REPLACEMENT = '''    __slots__ = (
        "_lock", "_local", "_active", "_generation", "_closed", "clock",
        "_correlation_sequence",
    )
'''


TIMEOUT_CONTROLLER_INIT_ANCHOR = '''        self._active = {}
        self._generation = int(generation)
        self._closed = False
'''


TIMEOUT_CONTROLLER_INIT_REPLACEMENT = '''        self._active = {}
        self._generation = int(generation)
        self._closed = False
        self._correlation_sequence = 0
'''


TIMEOUT_SCOPE_ANCHOR = '''        with self._lock:
            generation = (
                self._generation
                if requested_generation is None else requested_generation
            )
        effective_deadline = now + timeout
        if deadline is not None:
            effective_deadline = min(
                effective_deadline,
                _v80_timeout_number(deadline, "timeout_scope"),
            )
        stack = getattr(self._local, "stack", None) or []
        parent = stack[-1] if stack else None
        if parent is not None and parent.generation == generation:
            parent.checkpoint()
            effective_deadline = min(effective_deadline, parent.deadline)
        return TimeoutOperation(self, operation, generation, effective_deadline)
'''


TIMEOUT_SCOPE_REPLACEMENT = '''        with self._lock:
            generation = (
                self._generation
                if requested_generation is None else requested_generation
            )
            self._correlation_sequence += 1
            correlation_sequence = self._correlation_sequence
        effective_deadline = now + timeout
        if deadline is not None:
            effective_deadline = min(
                effective_deadline,
                _v80_timeout_number(deadline, "timeout_scope"),
            )
        stack = getattr(self._local, "stack", None) or []
        parent = stack[-1] if stack else None
        if parent is not None and parent.generation == generation:
            parent.checkpoint()
            effective_deadline = min(effective_deadline, parent.deadline)
        request_id = hashlib.sha256(
            ("request|%s|%s" % (generation, correlation_sequence)).encode("utf-8")
        ).hexdigest()[:16]
        trace_id = (
            parent.trace_id
            if parent is not None and parent.generation == generation
            else hashlib.sha256(
                ("trace|%s|%s" % (generation, correlation_sequence)).encode("utf-8")
            ).hexdigest()[:16]
        )
        return TimeoutOperation(
            self, operation, generation, effective_deadline, request_id, trace_id,
        )
'''


TIMEOUT_CONTEXT_ANCHOR = '''    def current(self, required=True):
'''


TIMEOUT_CONTEXT_REPLACEMENT = '''    def _diagnostic_context(self):
        stack = tuple(getattr(self._local, "stack", None) or ())
        if not stack:
            return None
        root = stack[0]
        current = stack[-1]
        with self._lock:
            active_generation = self._generation
            closed = self._closed
        if (
                closed
                or root.generation != active_generation
                or current.generation != active_generation
                or root._cancelled.is_set()
                or current._cancelled.is_set()
                or root._finished
                or current._finished):
            return None
        return {
            "request_id": current.request_id,
            "trace_id": root.trace_id,
            "operation": current.operation,
        }

''' + TIMEOUT_CONTEXT_ANCHOR


DIAGNOSTIC_EVENT_ANCHOR = '''    def _diagnostic_event(self, event, level="INFO", exc=None, **fields):
        """Store a bounded, redacted diagnostic event without changing runtime output."""
        try:
            payload = {
                "event": self._short_error(event or "unknown", limit=512),
                "level": self._short_error(level or "INFO", limit=512).upper(),
                "at": time.time(),
            }
            if exc is not None:
                payload["error_kind"] = self._diagnostic_error_kind(exc)
                payload["error"] = self._short_error(exc)
                if payload["level"] in ("ERROR", "CRITICAL"):
                    trace = "".join(traceback.format_exception_only(type(exc), exc)).strip()
                    payload["trace"] = self._short_error(RuntimeError(trace), limit=512)
            for key, value in fields.items():
                if value is None:
                    continue
                safe_key = self._short_error(key, limit=512)
                payload[safe_key] = self._short_error(value, limit=512)
            with self._diagnostic_lock:
                self._diagnostic_sequence += 1
                payload["seq"] = self._diagnostic_sequence
                self._diagnostics.append(payload)
                if len(self._diagnostics) > self.DIAGNOSTIC_LIMIT:
                    del self._diagnostics[:-self.DIAGNOSTIC_LIMIT]
            return payload
        except Exception:
            return None
'''


DIAGNOSTIC_EVENT_REPLACEMENT = '''    def _diagnostic_event(self, event, level="INFO", exc=None, **fields):
        """Store a bounded, redacted diagnostic event without changing runtime output."""
        try:
            safe_event = self._short_error(event or "unknown", limit=512)
            safe_level = self._short_error(level or "INFO", limit=512).upper()
            if safe_level not in V80_OBSERVABILITY_LEVELS:
                safe_level = "INFO"

            controller = getattr(self, "_timeout_budget_controller", None)
            context = controller._diagnostic_context() if controller is not None else None
            operation_name = str((context or {}).get("operation", "") or "")

            event_stage = safe_event.lower()
            operation_stage = operation_name.lower()
            if event_stage.startswith((
                    "history", "playback_sync.", "history_queue.", "history_transport.",
            )):
                stage = "history"
            elif event_stage.startswith("cache."):
                stage = "cache"
            elif event_stage.startswith(("follow.persist.", "lifecycle.")):
                stage = "lifecycle"
            elif "probe" in event_stage:
                stage = "probe"
            elif event_stage.startswith(("route_quality.", "playback.", "player.")):
                stage = "playback"
            elif "detail" in event_stage:
                stage = "detail"
            elif "match" in event_stage:
                stage = "match"
            elif (
                    event_stage.startswith("resource")
                    or any(marker in event_stage for marker in ("search", "category", "home"))):
                stage = "search"
            elif any(marker in operation_stage for marker in ("history", "sync")):
                stage = "history"
            elif "cache" in operation_stage:
                stage = "cache"
            elif any(marker in operation_stage for marker in ("lifecycle", "init", "destroy")):
                stage = "lifecycle"
            elif "probe" in operation_stage:
                stage = "probe"
            elif any(marker in operation_stage for marker in ("playback", "player", "route")):
                stage = "playback"
            elif "detail" in operation_stage:
                stage = "detail"
            elif "match" in operation_stage:
                stage = "match"
            elif any(marker in operation_stage for marker in (
                    "search", "resource", "category", "home",
            )):
                stage = "search"
            else:
                stage = "request"

            payload = {
                "schema": V80_OBSERVABILITY_SCHEMAS["event"],
                "event": safe_event,
                "level": safe_level,
                "at": time.time(),
                "stage": stage,
            }
            if context is not None:
                payload["request_id"] = context["request_id"]
                payload["trace_id"] = context["trace_id"]

            if exc is not None:
                payload["error_kind"] = self._diagnostic_error_kind(exc)
                payload["error_code"] = v80_observability_error_code(
                    payload["error_kind"]
                )
                payload["error"] = self._short_error(exc)
                if payload["level"] in ("ERROR", "CRITICAL"):
                    trace = "".join(traceback.format_exception_only(type(exc), exc)).strip()
                    payload["trace"] = self._short_error(RuntimeError(trace), limit=512)

            reserved_fields = frozenset(
                V80_OBSERVABILITY_EVENT_FIELDS
                + ("error_kind", "error", "trace", "seq")
            )
            for key, value in fields.items():
                if value is None:
                    continue
                safe_key = self._short_error(key, limit=512)
                if safe_key in reserved_fields:
                    continue
                payload[safe_key] = self._short_error(value, limit=512)

            for managed_key in ("media_id", "episode", "cache", "decision", "count"):
                managed_value = fields.get(managed_key)
                if managed_value is not None:
                    payload[managed_key] = self._short_error(managed_value, limit=512)

            provider = fields.get("provider")
            if provider is None:
                provider = fields.get("mode")
            if provider is not None:
                payload["provider"] = self._short_error(provider, limit=512)

            elapsed = fields.get("elapsed_ms")
            if elapsed is None:
                elapsed = fields.get("duration_ms")
            if elapsed is not None:
                try:
                    elapsed_number = float(elapsed)
                    if math.isfinite(elapsed_number) and elapsed_number >= 0:
                        payload["elapsed_ms"] = int(round(elapsed_number))
                except (TypeError, ValueError, OverflowError):
                    pass

            with self._diagnostic_lock:
                self._diagnostic_sequence += 1
                payload["seq"] = self._diagnostic_sequence
                self._diagnostics.append(payload)
                if len(self._diagnostics) > self.DIAGNOSTIC_LIMIT:
                    del self._diagnostics[:-self.DIAGNOSTIC_LIMIT]
            return dict(payload)
        except Exception:
            return None
'''


INSERTIONS = (
    (
        "timeout-operation-correlation-fields",
        TIMEOUT_OPERATION_CORRELATION_ANCHOR,
        TIMEOUT_OPERATION_CORRELATION_REPLACEMENT,
    ),
    (
        "timeout-controller-correlation-sequence-slot",
        TIMEOUT_CONTROLLER_SLOT_ANCHOR,
        TIMEOUT_CONTROLLER_SLOT_REPLACEMENT,
    ),
    (
        "timeout-controller-correlation-sequence-init",
        TIMEOUT_CONTROLLER_INIT_ANCHOR,
        TIMEOUT_CONTROLLER_INIT_REPLACEMENT,
    ),
    (
        "timeout-controller-correlation-scope",
        TIMEOUT_SCOPE_ANCHOR,
        TIMEOUT_SCOPE_REPLACEMENT,
    ),
    (
        "timeout-controller-diagnostic-context",
        TIMEOUT_CONTEXT_ANCHOR,
        TIMEOUT_CONTEXT_REPLACEMENT,
    ),
    (
        "diagnostic-event-runtime-correlation",
        DIAGNOSTIC_EVENT_ANCHOR,
        DIAGNOSTIC_EVENT_REPLACEMENT,
    ),
)


def _replace_once(text, anchor, replacement, label):
    count = text.count(anchor)
    if count != 1:
        raise ObservabilityRuntimeOverlayError(
            "observability runtime anchor %s must appear once, found %d"
            % (label, count)
        )
    return text.replace(anchor, replacement, 1)


def _method(tree, method_name):
    spider_classes = [
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "Spider"
    ]
    if len(spider_classes) != 1:
        raise ObservabilityRuntimeOverlayError("expected one Spider class")
    methods = [
        node for node in spider_classes[0].body
        if isinstance(node, ast.FunctionDef) and node.name == method_name
    ]
    if len(methods) != 1:
        raise ObservabilityRuntimeOverlayError(
            "expected one Spider.%s method" % method_name
        )
    return methods[0]


def _names(method):
    return {
        node.id for node in ast.walk(method) if isinstance(node, ast.Name)
    }


def _audit_diagnostic_event(tree):
    method = _method(tree, "_diagnostic_event")
    names = _names(method)
    required = {
        "V80_OBSERVABILITY_LEVELS",
        "V80_OBSERVABILITY_SCHEMAS",
        "v80_observability_error_code",
    }
    if not required.issubset(names):
        raise ObservabilityRuntimeOverlayError(
            "diagnostic event is missing P5 policy or correlation owners"
        )
    context_calls = [
        node for node in ast.walk(method)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "_diagnostic_context"
    ]
    if len(context_calls) != 1:
        raise ObservabilityRuntimeOverlayError(
            "diagnostic event must consume one TimeoutBudget diagnostic context"
        )
    if any(
            isinstance(node, ast.Constant)
            and node.value == "v80-diagnostics-snapshot/1"
            for node in ast.walk(method)):
        raise ObservabilityRuntimeOverlayError(
            "P5-2 must not generate Diagnostics Snapshot"
        )


def _audit_timeout_correlation(tree):
    timeout_classes = [
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "TimeoutBudgetController"
    ]
    if len(timeout_classes) != 1:
        raise ObservabilityRuntimeOverlayError(
            "expected one TimeoutBudgetController class"
        )
    methods = {
        node.name: node for node in timeout_classes[0].body
        if isinstance(node, ast.FunctionDef)
    }
    if "_diagnostic_context" not in methods:
        raise ObservabilityRuntimeOverlayError(
            "TimeoutBudgetController is missing diagnostic context"
        )
    context_names = _names(methods["_diagnostic_context"])
    if not {"root", "current", "active_generation"}.issubset(context_names):
        raise ObservabilityRuntimeOverlayError(
            "TimeoutBudgetController diagnostic context is incomplete"
        )


def apply_observability_runtime_overlay(source):
    try:
        text = bytes(source).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ObservabilityRuntimeOverlayError(
            "observability runtime input is not valid UTF-8"
        ) from exc
    input_bytes = text.encode("utf-8")
    for label, anchor, replacement in INSERTIONS:
        text = _replace_once(text, anchor, replacement, label)

    try:
        tree = ast.parse(text, filename="build/v80-dev/observability-runtime.py")
        compile(tree, "build/v80-dev/observability-runtime.py", "exec")
    except SyntaxError as exc:
        raise ObservabilityRuntimeOverlayError(
            "observability runtime output is invalid: %s" % exc
        ) from exc
    _audit_diagnostic_event(tree)
    _audit_timeout_correlation(tree)

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
        "import apply_observability_runtime_overlay from the V80 build pipeline"
    )


if __name__ == "__main__":
    main()

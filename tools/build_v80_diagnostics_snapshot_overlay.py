"""P5-3 诊断快照覆盖层: wrap the existing private diagnostic buffer."""

import ast
import hashlib


class DiagnosticsSnapshotOverlayError(RuntimeError):
    pass


DIAGNOSTIC_SNAPSHOT_ANCHOR = '''    def _diagnostic_snapshot(self, limit=None):
        try:
            count = self.DIAGNOSTIC_LIMIT if limit is None else max(1, min(int(limit), self.DIAGNOSTIC_LIMIT))
        except Exception:
            count = self.DIAGNOSTIC_LIMIT
        with self._diagnostic_lock:
            return [dict(item) for item in self._diagnostics[-count:]]
'''


DIAGNOSTIC_SNAPSHOT_REPLACEMENT = '''    def _diagnostic_snapshot(self, limit=None):
        maximum = V80_OBSERVABILITY_LIMITS["max_snapshot_events"]
        try:
            count = maximum if limit is None else max(1, min(int(limit), maximum))
        except Exception:
            count = maximum
        with self._diagnostic_lock:
            events = [dict(item) for item in self._diagnostics[-count:]]
        return {
            "schema": V80_OBSERVABILITY_SCHEMAS["snapshot"],
            "count": len(events),
            "events": events,
        }
'''


INSERTIONS = ((
    "diagnostics-snapshot-envelope",
    DIAGNOSTIC_SNAPSHOT_ANCHOR,
    DIAGNOSTIC_SNAPSHOT_REPLACEMENT,
),)


def _replace_once(text, anchor, replacement, label):
    count = text.count(anchor)
    if count != 1:
        raise DiagnosticsSnapshotOverlayError(
            "diagnostics snapshot anchor %s must appear once, found %d"
            % (label, count)
        )
    return text.replace(anchor, replacement, 1)


def _snapshot_method(tree):
    spider_classes = [
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "Spider"
    ]
    if len(spider_classes) != 1:
        raise DiagnosticsSnapshotOverlayError("expected one Spider class")
    methods = [
        node for node in spider_classes[0].body
        if isinstance(node, ast.FunctionDef)
        and node.name == "_diagnostic_snapshot"
    ]
    if len(methods) != 1:
        raise DiagnosticsSnapshotOverlayError(
            "expected one Spider._diagnostic_snapshot method"
        )
    return methods[0]


def _called_names(method):
    names = set()
    for node in ast.walk(method):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name):
            names.add(node.func.id)
        elif isinstance(node.func, ast.Attribute):
            names.add(node.func.attr)
    return names


def _audit_snapshot(tree):
    method = _snapshot_method(tree)
    names = {
        node.id for node in ast.walk(method) if isinstance(node, ast.Name)
    }
    if not {
            "V80_OBSERVABILITY_LIMITS", "V80_OBSERVABILITY_SCHEMAS",
            "events",
    }.issubset(names):
        raise DiagnosticsSnapshotOverlayError(
            "diagnostics snapshot is missing its P5 policy owners"
        )

    calls = _called_names(method)
    forbidden = {
        "_diagnostic_event", "_short_error", "time", "monotonic", "open",
        "request", "get", "post", "set", "write",
    }
    added = sorted(calls.intersection(forbidden))
    if added:
        raise DiagnosticsSnapshotOverlayError(
            "diagnostics snapshot added forbidden owner calls: %s" % added
        )

    policy_refs = [
        node for node in ast.walk(method)
        if isinstance(node, ast.Subscript)
        and isinstance(node.value, ast.Name)
        and node.value.id in {
            "V80_OBSERVABILITY_LIMITS", "V80_OBSERVABILITY_SCHEMAS",
        }
    ]
    if len(policy_refs) != 2:
        raise DiagnosticsSnapshotOverlayError(
            "diagnostics snapshot must consume exactly two P5 policy values"
        )

    lock_scopes = [
        node for node in method.body
        if isinstance(node, ast.With)
        and any(
            isinstance(item.context_expr, ast.Attribute)
            and item.context_expr.attr == "_diagnostic_lock"
            for item in node.items
        )
    ]
    if len(lock_scopes) != 1:
        raise DiagnosticsSnapshotOverlayError(
            "diagnostics snapshot must retain one diagnostic lock scope"
        )

    returns = [node for node in method.body if isinstance(node, ast.Return)]
    if len(returns) != 1 or not isinstance(returns[0].value, ast.Dict):
        raise DiagnosticsSnapshotOverlayError(
            "diagnostics snapshot must return one literal envelope"
        )
    keys = [
        node.value if isinstance(node, ast.Constant) else None
        for node in returns[0].value.keys
    ]
    if keys != ["schema", "count", "events"]:
        raise DiagnosticsSnapshotOverlayError(
            "diagnostics snapshot envelope fields changed"
        )


def apply_diagnostics_snapshot_overlay(source):
    try:
        text = bytes(source).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise DiagnosticsSnapshotOverlayError(
            "diagnostics snapshot input is not valid UTF-8"
        ) from exc
    input_bytes = text.encode("utf-8")
    for label, anchor, replacement in INSERTIONS:
        text = _replace_once(text, anchor, replacement, label)

    try:
        tree = ast.parse(text, filename="build/v80-dev/diagnostics-snapshot.py")
        compile(tree, "build/v80-dev/diagnostics-snapshot.py", "exec")
    except SyntaxError as exc:
        raise DiagnosticsSnapshotOverlayError(
            "diagnostics snapshot output is invalid: %s" % exc
        ) from exc
    _audit_snapshot(tree)

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
        "import apply_diagnostics_snapshot_overlay from the V80 build pipeline"
    )


if __name__ == "__main__":
    main()

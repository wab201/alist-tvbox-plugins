"""Apply the narrow P5-5A session-reference cleanup to the V80 candidate."""

import ast
import hashlib


class LifecycleStabilityOverlayError(RuntimeError):
    pass


DESTROY_SESSION_ANCHOR = '''            for session in (self._session, self._tmdb_session, self._atvp_session):
                if session is not None:
                    try:
                        session.close()
                    except Exception:
                        pass
            self._tasks.shutdown(wait=False)
'''


DESTROY_SESSION_REPLACEMENT = '''            for session in (self._session, self._tmdb_session, self._atvp_session):
                if session is not None:
                    try:
                        session.close()
                    except Exception:
                        pass
            self._session = None
            self._tmdb_session = None
            self._atvp_session = None
            self._tasks.shutdown(wait=False)
'''


INSERTIONS = ((
    "destroy-session-reference-clear",
    DESTROY_SESSION_ANCHOR,
    DESTROY_SESSION_REPLACEMENT,
),)


def _replace_once(text, anchor, replacement, label):
    count = text.count(anchor)
    if count != 1:
        raise LifecycleStabilityOverlayError(
            "lifecycle stability anchor %s must appear once, found %d"
            % (label, count)
        )
    return text.replace(anchor, replacement, 1)


class _DestroyRebindingVisitor(ast.NodeVisitor):
    def __init__(self, scope):
        self.scope = scope
        self.found = False

    def visit_FunctionDef(self, node):
        if (
            (self.scope == "class" and node.name == "destroy")
            or (self.scope == "module" and node.name == "Spider")
        ):
            self.found = True
        return None

    def visit_AsyncFunctionDef(self, node):
        if (
            (self.scope == "class" and node.name == "destroy")
            or (self.scope == "module" and node.name == "Spider")
        ):
            self.found = True
        return None

    def visit_ClassDef(self, node):
        if (
            (self.scope == "class" and node.name == "destroy")
            or (self.scope == "module" and node.name == "Spider")
        ):
            self.found = True
        return None

    def visit_Lambda(self, _node):
        return None

    def visit_ListComp(self, _node):
        return None

    def visit_SetComp(self, _node):
        return None

    def visit_DictComp(self, _node):
        return None

    def visit_GeneratorExp(self, _node):
        return None

    def visit_Name(self, node):
        if (
            isinstance(node.ctx, (ast.Store, ast.Del))
            and (
                (self.scope == "class" and node.id == "destroy")
                or (self.scope == "module" and node.id == "Spider")
            )
        ):
            self.found = True

    def visit_Attribute(self, node):
        if (
            self.scope == "module"
            and isinstance(node.ctx, (ast.Store, ast.Del))
            and isinstance(node.value, ast.Name)
            and node.value.id == "Spider"
            and node.attr == "destroy"
        ):
            self.found = True
        self.generic_visit(node)

    def visit_Call(self, node):
        if (
            self.scope == "module"
            and isinstance(node.func, ast.Name)
            and node.func.id in ("setattr", "delattr")
            and len(node.args) >= 2
            and isinstance(node.args[0], ast.Name)
            and node.args[0].id == "Spider"
            and isinstance(node.args[1], ast.Constant)
            and node.args[1].value == "destroy"
        ):
            self.found = True
        self.generic_visit(node)


def _has_destroy_rebinding(statements, scope):
    visitor = _DestroyRebindingVisitor(scope)
    for statement in statements:
        visitor.visit(statement)
    return visitor.found


def _destroy_method(tree):
    spider_classes = [
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "Spider"
    ]
    if len(spider_classes) != 1:
        raise LifecycleStabilityOverlayError("expected one Spider class")
    spider_class = spider_classes[0]
    if spider_class.decorator_list or spider_class.keywords:
        raise LifecycleStabilityOverlayError("Spider class cannot be decorated or customized")
    methods = [
        node for node in spider_class.body
        if isinstance(node, ast.FunctionDef) and node.name == "destroy"
    ]
    if len(methods) != 1:
        raise LifecycleStabilityOverlayError("expected one Spider.destroy method")
    if _has_destroy_rebinding(
        [statement for statement in spider_class.body if statement is not methods[0]],
        "class",
    ):
        raise LifecycleStabilityOverlayError("Spider.destroy cannot be rebound")
    spider_index = tree.body.index(spider_class)
    if _has_destroy_rebinding(tree.body[spider_index + 1:], "module"):
        raise LifecycleStabilityOverlayError("Spider.destroy cannot be rebound")
    return methods[0]


def _self_attribute(node):
    if (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "self"
    ):
        return node.attr
    return None


def _audit_destroy(tree):
    method = _destroy_method(tree)
    if method.decorator_list:
        raise LifecycleStabilityOverlayError("destroy cannot be decorated")
    if any(
        isinstance(node, (ast.Yield, ast.YieldFrom))
        for node in ast.walk(method)
    ):
        raise LifecycleStabilityOverlayError(
            "destroy cannot be a generator"
        )
    session_names = ("_session", "_tmdb_session", "_atvp_session")
    clears = []
    close_loops = []
    shutdown_calls = []

    for statement in ast.walk(method):
        if isinstance(statement, ast.For):
            iter_names = tuple(
                _self_attribute(item)
                for item in statement.iter.elts
            ) if isinstance(statement.iter, ast.Tuple) else ()
            close_calls = [
                node for node in ast.walk(statement)
                if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "close"
            ]
            if iter_names == session_names and len(close_calls) == 1:
                close_loops.append(statement)
        if isinstance(statement, ast.Assign) and len(statement.targets) == 1:
            name = _self_attribute(statement.targets[0])
            if name in session_names and isinstance(statement.value, ast.Constant):
                if statement.value.value is None:
                    clears.append((statement.lineno, name))
        if isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call):
            call = statement.value
            if (
                isinstance(call.func, ast.Attribute)
                and call.func.attr == "shutdown"
                and _self_attribute(call.func.value) == "_tasks"
            ):
                shutdown_calls.append(statement)

    if len(close_loops) != 1 or len(shutdown_calls) != 1:
        raise LifecycleStabilityOverlayError(
            "destroy session close or task shutdown owner changed"
        )
    clears.sort()
    if [name for _index, name in clears] != list(session_names):
        raise LifecycleStabilityOverlayError(
            "destroy must clear exactly the three session references"
        )
    close_line = close_loops[0].lineno
    shutdown_line = shutdown_calls[0].lineno
    if not all(close_line < line < shutdown_line for line, _name in clears):
        raise LifecycleStabilityOverlayError(
            "session references must clear after close and before task shutdown"
        )

    if len(method.body) != 1:
        raise LifecycleStabilityOverlayError(
            "destroy must contain only the direct history-context owner"
        )
    history_owner = method.body[0]
    if not (
        isinstance(history_owner, ast.With)
        and len(history_owner.items) == 1
        and _self_attribute(history_owner.items[0].context_expr)
        == "_history_context_lock"
    ):
        raise LifecycleStabilityOverlayError(
            "destroy must have one direct history-context cleanup block"
        )
    block = history_owner.body
    direct_sequences = []
    for index in range(max(0, len(block) - 4)):
        sequence = block[index:index + 5]
        if (
            sequence[0] is close_loops[0]
            and [
                _self_attribute(statement.targets[0])
                for statement in sequence[1:4]
                if isinstance(statement, ast.Assign)
                and len(statement.targets) == 1
                and isinstance(statement.value, ast.Constant)
                and statement.value.value is None
            ] == list(session_names)
            and sequence[4] is shutdown_calls[0]
        ):
            direct_sequences.append((index, sequence))
    if len(direct_sequences) != 1:
        raise LifecycleStabilityOverlayError(
            "session cleanup must be a direct mandatory destroy sequence"
        )
    sequence_index, _sequence = direct_sequences[0]
    if any(
        isinstance(node, (ast.Return, ast.Raise))
        for statement in block[:sequence_index]
        for node in ast.walk(statement)
    ):
        raise LifecycleStabilityOverlayError(
            "destroy cleanup cannot follow an early return or raise"
        )


def apply_lifecycle_stability_overlay(source):
    try:
        text = bytes(source).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise LifecycleStabilityOverlayError(
            "lifecycle stability input is not valid UTF-8"
        ) from exc
    input_bytes = text.encode("utf-8")
    for label, anchor, replacement in INSERTIONS:
        text = _replace_once(text, anchor, replacement, label)

    try:
        tree = ast.parse(text, filename="build/v80-dev/lifecycle-stability.py")
        compile(tree, "build/v80-dev/lifecycle-stability.py", "exec")
    except SyntaxError as exc:
        raise LifecycleStabilityOverlayError(
            "lifecycle stability output is invalid: %s" % exc
        ) from exc
    _audit_destroy(tree)

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
        "import apply_lifecycle_stability_overlay from the V80 build pipeline"
    )


if __name__ == "__main__":
    main()

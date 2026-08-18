import ast
import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parent.parent
POLICY_PATH = (
    ROOT / "src" / "douban_tmdb_follow_single"
    / "douban_html_response_policy.py"
)


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


POLICY = _load("v80_douban_html_response_policy", POLICY_PATH)


def test_response_limit_is_immutable_and_complete_envelope_backed():
    assert dict(POLICY.V80_DOUBAN_HTML_RESPONSE_LIMITS) == {
        "max_response_bytes": 256 * 1024,
    }
    with pytest.raises(TypeError):
        POLICY.V80_DOUBAN_HTML_RESPONSE_LIMITS["max_response_bytes"] += 1


def test_policy_source_is_standard_library_only_and_has_no_runtime_owners():
    tree = ast.parse(POLICY_PATH.read_text(encoding="utf-8"), filename=str(POLICY_PATH))
    imports = {
        alias.name
        for node in tree.body
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imports.update(
        node.module
        for node in tree.body
        if isinstance(node, ast.ImportFrom)
    )
    calls = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    names = {
        node.id.lower()
        for node in ast.walk(tree)
        if isinstance(node, ast.Name)
    }

    assert imports == {"types"}
    assert not ({"open", "print", "exec", "eval"} & calls)
    assert not ({"retry", "cache", "thread", "request", "response"} & names)

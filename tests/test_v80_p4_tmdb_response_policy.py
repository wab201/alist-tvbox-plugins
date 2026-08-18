import ast
import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parent.parent
POLICY_PATH = (
    ROOT / "src" / "douban_tmdb_follow_single" / "tmdb_response_policy.py"
)


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


POLICY = _load("v80_tmdb_response_policy", POLICY_PATH)


def _nested_list(depth, leaf):
    value = leaf
    for _index in range(depth):
        value = [value]
    return value


def test_limits_are_immutable_and_exact():
    assert dict(POLICY.V80_TMDB_RESPONSE_LIMITS) == {
        "max_response_bytes": 2 * 1024 * 1024,
        "max_key_bytes": 1024,
        "max_string_bytes": 128 * 1024,
    }
    with pytest.raises(TypeError):
        POLICY.V80_TMDB_RESPONSE_LIMITS["max_key_bytes"] = 1025


def test_string_byte_boundary_is_exact():
    limit = POLICY.V80_TMDB_RESPONSE_LIMITS["max_string_bytes"]
    accepted = "a" * limit

    assert POLICY.v80_validate_tmdb_json_fields(accepted) is accepted
    with pytest.raises(POLICY.V80TmdbResponsePolicyError) as exc_info:
        POLICY.v80_validate_tmdb_json_fields(accepted + "a")
    assert exc_info.value.reason == "string_too_long"


def test_object_key_byte_boundary_is_exact():
    limit = POLICY.V80_TMDB_RESPONSE_LIMITS["max_key_bytes"]
    accepted = {"k" * limit: None}

    assert POLICY.v80_validate_tmdb_json_fields(accepted) is accepted
    with pytest.raises(POLICY.V80TmdbResponsePolicyError) as exc_info:
        POLICY.v80_validate_tmdb_json_fields({"k" * (limit + 1): None})
    assert exc_info.value.reason == "key_too_long"


@pytest.mark.parametrize("field", ("key", "value"))
def test_multibyte_text_limits_use_utf8_byte_counts(field):
    limit_name = "max_key_bytes" if field == "key" else "max_string_bytes"
    limit = POLICY.V80_TMDB_RESPONSE_LIMITS[limit_name]
    accepted_text = "\u8c46" * (limit // 3)
    rejected_text = accepted_text + "\u74e3"
    accepted = {accepted_text: None} if field == "key" else {"field": accepted_text}
    rejected = {rejected_text: None} if field == "key" else {"field": rejected_text}

    assert len(accepted_text.encode("utf-8")) <= limit
    assert POLICY.v80_validate_tmdb_json_fields(accepted) is accepted
    with pytest.raises(POLICY.V80TmdbResponsePolicyError):
        POLICY.v80_validate_tmdb_json_fields(rejected)


def test_nested_list_and_dict_descendants_are_checked_iteratively():
    marker = "x" * (POLICY.V80_TMDB_RESPONSE_LIMITS["max_string_bytes"] + 1)
    value = _nested_list(2000, {"result": marker})

    with pytest.raises(POLICY.V80TmdbResponsePolicyError) as exc_info:
        POLICY.v80_validate_tmdb_json_fields(value)
    assert exc_info.value.reason == "string_too_long"


def test_valid_nested_value_returns_the_identical_object():
    value = {"results": [{"title": "text"}, [None, True, 1, 1.5]]}

    assert POLICY.v80_validate_tmdb_json_fields(value) is value


@pytest.mark.parametrize("field", ("key", "value"))
def test_rejection_uses_fixed_reason_without_echoing_input(field):
    marker = "sensitive-marker-"
    limit_name = "max_key_bytes" if field == "key" else "max_string_bytes"
    text = marker + "x" * POLICY.V80_TMDB_RESPONSE_LIMITS[limit_name]
    value = {text: None} if field == "key" else {"field": text}

    with pytest.raises(POLICY.V80TmdbResponsePolicyError) as exc_info:
        POLICY.v80_validate_tmdb_json_fields(value)

    expected_reason = "key_too_long" if field == "key" else "string_too_long"
    assert exc_info.value.reason == expected_reason
    assert marker not in str(exc_info.value)


def test_policy_source_has_no_runtime_owners():
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

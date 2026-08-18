import ast
import importlib.util
import math
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parent.parent
POLICY_PATH = ROOT / "src" / "douban_tmdb_follow_single" / "json_shape_policy.py"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


POLICY = _load("v80_json_shape_policy", POLICY_PATH)


def _nested_list(depth):
    value = 0
    for _index in range(depth):
        value = [value]
    return value


def _node_boundary(extra=0):
    limits = POLICY.V80_JSON_SHAPE_LIMITS
    group_count = 16
    scalar_count = limits["max_nodes"] - 1 - group_count + extra
    groups = []
    for _index in range(group_count):
        size = min(limits["max_collection_items"], scalar_count)
        groups.append([None] * size)
        scalar_count -= size
    assert scalar_count == 0
    return groups


def test_limits_are_immutable_and_exact():
    assert dict(POLICY.V80_JSON_SHAPE_LIMITS) == {
        "max_depth": 64,
        "max_nodes": 128 * 1024,
        "max_collection_items": 8 * 1024,
    }
    with pytest.raises(TypeError):
        POLICY.V80_JSON_SHAPE_LIMITS["max_depth"] = 65


def test_valid_json_returns_the_identical_object_without_normalization():
    value = {
        "items": [None, True, False, 0, 1.5, "text", {"nested": []}],
    }

    assert POLICY.v80_validate_json_shape(value) is value


def test_depth_boundary_is_iterative_and_exact():
    accepted = _nested_list(POLICY.V80_JSON_SHAPE_LIMITS["max_depth"])
    rejected = _nested_list(POLICY.V80_JSON_SHAPE_LIMITS["max_depth"] + 1)

    assert POLICY.v80_validate_json_shape(accepted) is accepted
    with pytest.raises(POLICY.V80JsonShapeError) as exc_info:
        POLICY.v80_validate_json_shape(rejected)
    assert exc_info.value.reason == "too_deep"


def test_collection_item_boundary_is_exact():
    limit = POLICY.V80_JSON_SHAPE_LIMITS["max_collection_items"]
    accepted = [None] * limit

    assert POLICY.v80_validate_json_shape(accepted) is accepted
    with pytest.raises(POLICY.V80JsonShapeError) as exc_info:
        POLICY.v80_validate_json_shape(accepted + [None])
    assert exc_info.value.reason == "collection_too_large"


def test_total_node_boundary_is_exact_across_small_collections():
    accepted = _node_boundary()
    rejected = _node_boundary(extra=1)

    assert POLICY.v80_validate_json_shape(accepted) is accepted
    with pytest.raises(POLICY.V80JsonShapeError) as exc_info:
        POLICY.v80_validate_json_shape(rejected)
    assert exc_info.value.reason == "too_many_nodes"


@pytest.mark.parametrize("value,reason", (
    ({1: "value"}, "invalid_object_key"),
    (("tuple",), "unsupported_value_type"),
    (float("nan"), "non_finite_number"),
    (float("inf"), "non_finite_number"),
    (-float("inf"), "non_finite_number"),
))
def test_non_json_values_are_rejected_with_stable_reasons(value, reason):
    with pytest.raises(POLICY.V80JsonShapeError) as exc_info:
        POLICY.v80_validate_json_shape(value)
    assert exc_info.value.reason == reason


def test_rejection_does_not_echo_the_input_value():
    marker = "sensitive-marker-value"

    with pytest.raises(POLICY.V80JsonShapeError) as exc_info:
        POLICY.v80_validate_json_shape({marker: object()})

    assert marker not in str(exc_info.value)


def test_policy_source_has_no_io_network_cache_or_logging_owner():
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

    assert imports == {"math", "types"}
    assert not ({"open", "print", "exec", "eval"} & calls)
    assert math.isfinite(1.0)

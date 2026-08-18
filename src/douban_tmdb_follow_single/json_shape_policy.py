"""Pure JSON shape policy for isolated V80 response validation."""

import math as _v80_json_math
from types import MappingProxyType as _v80_json_mapping_proxy


V80_JSON_SHAPE_LIMITS = _v80_json_mapping_proxy({
    "max_depth": 64,
    "max_nodes": 128 * 1024,
    "max_collection_items": 8 * 1024,
})


class V80JsonShapeError(ValueError):
    """Stable structural rejection without retaining the rejected value."""

    __slots__ = ("reason",)

    def __init__(self, reason):
        reason = str(reason or "invalid_json_shape")
        self.reason = reason
        super().__init__("JSON shape policy rejected input: %s" % reason)


def _v80_json_reject(reason):
    raise V80JsonShapeError(reason)


def v80_validate_json_shape(value):
    """Return the same JSON value after bounded, iterative structure validation."""

    max_depth = V80_JSON_SHAPE_LIMITS["max_depth"]
    max_nodes = V80_JSON_SHAPE_LIMITS["max_nodes"]
    max_collection_items = V80_JSON_SHAPE_LIMITS["max_collection_items"]
    stack = [(value, 1)]
    nodes = 0

    while stack:
        current, depth = stack.pop()
        nodes += 1
        if nodes > max_nodes:
            _v80_json_reject("too_many_nodes")

        current_type = type(current)
        if current is None or current_type in (str, int, bool):
            continue
        if current_type is float:
            if not _v80_json_math.isfinite(current):
                _v80_json_reject("non_finite_number")
            continue
        if current_type is list:
            if depth > max_depth:
                _v80_json_reject("too_deep")
            if len(current) > max_collection_items:
                _v80_json_reject("collection_too_large")
            stack.extend((item, depth + 1) for item in reversed(current))
            continue
        if current_type is dict:
            if depth > max_depth:
                _v80_json_reject("too_deep")
            if len(current) > max_collection_items:
                _v80_json_reject("collection_too_large")
            values = []
            for key, item in current.items():
                if type(key) is not str:
                    _v80_json_reject("invalid_object_key")
                values.append(item)
            stack.extend((item, depth + 1) for item in reversed(values))
            continue
        _v80_json_reject("unsupported_value_type")

    return value

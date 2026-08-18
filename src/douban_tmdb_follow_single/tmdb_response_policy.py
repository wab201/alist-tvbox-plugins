"""Pure TMDB response field-length policy for isolated V80 validation."""

from types import MappingProxyType as _v80_tmdb_response_mapping_proxy


V80_TMDB_RESPONSE_LIMITS = _v80_tmdb_response_mapping_proxy({
    "max_response_bytes": 2 * 1024 * 1024,
    "max_key_bytes": 1024,
    "max_string_bytes": 128 * 1024,
})


class V80TmdbResponsePolicyError(ValueError):
    """Stable field-length rejection without retaining the rejected value."""

    __slots__ = ("reason",)

    def __init__(self, reason):
        reason = str(reason or "invalid_tmdb_response")
        self.reason = reason
        super().__init__("TMDB response policy rejected input: %s" % reason)


def _v80_tmdb_response_reject(reason):
    raise V80TmdbResponsePolicyError(reason)


def v80_validate_tmdb_json_fields(value):
    """Return the same shape-validated JSON value after field-length checks."""

    max_key_bytes = V80_TMDB_RESPONSE_LIMITS["max_key_bytes"]
    max_string_bytes = V80_TMDB_RESPONSE_LIMITS["max_string_bytes"]
    stack = [value]

    while stack:
        current = stack.pop()
        current_type = type(current)
        if current_type is str:
            if len(current.encode("utf-8")) > max_string_bytes:
                _v80_tmdb_response_reject("string_too_long")
            continue
        if current_type is list:
            stack.extend(reversed(current))
            continue
        if current_type is dict:
            values = []
            for key, item in current.items():
                if type(key) is str and len(key.encode("utf-8")) > max_key_bytes:
                    _v80_tmdb_response_reject("key_too_long")
                values.append(item)
            stack.extend(reversed(values))

    return value

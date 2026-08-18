"""Pure observability schema and error-code policy for isolated V80 diagnostics."""

from types import MappingProxyType as _v80_observability_mapping_proxy


V80_OBSERVABILITY_SCHEMAS = _v80_observability_mapping_proxy({
    "event": "v80-diagnostic-event/1",
    "snapshot": "v80-diagnostics-snapshot/1",
})

V80_OBSERVABILITY_LIMITS = _v80_observability_mapping_proxy({
    "max_snapshot_events": 256,
    "max_text_chars": 512,
})

V80_OBSERVABILITY_CORE_FIELDS = (
    "schema", "event", "level", "at", "seq", "stage", "error_code",
)

V80_OBSERVABILITY_CONTEXT_FIELDS = (
    "request_id", "trace_id", "media_id", "provider", "episode",
)

V80_OBSERVABILITY_MEASUREMENT_FIELDS = (
    "elapsed_ms", "cache", "decision", "count",
)

V80_OBSERVABILITY_EVENT_FIELDS = (
    V80_OBSERVABILITY_CORE_FIELDS
    + V80_OBSERVABILITY_CONTEXT_FIELDS
    + V80_OBSERVABILITY_MEASUREMENT_FIELDS
)

V80_OBSERVABILITY_LEVELS = frozenset((
    "INFO", "WARN", "ERROR", "CRITICAL",
))

V80_OBSERVABILITY_STAGES = frozenset((
    "request", "search", "match", "detail", "probe", "playback",
    "history", "cache", "lifecycle", "snapshot",
))

V80_RELIABILITY_ERROR_CODES = _v80_observability_mapping_proxy({
    "cancelled": "V80-CANCELLED",
    "budget_exhausted": "V80-BUDGET-EXHAUSTED",
    "timeout": "V80-TIMEOUT",
    "dns": "V80-DNS",
    "tls": "V80-TLS",
    "transport": "V80-TRANSPORT",
    "auth": "V80-AUTH",
    "rate_limit": "V80-RATE-LIMIT",
    "server": "V80-SERVER",
    "client": "V80-CLIENT",
    "unsupported": "V80-UNSUPPORTED",
    "payload": "V80-PAYLOAD",
    "configuration": "V80-CONFIGURATION",
    "runtime": "V80-RUNTIME",
    "circuit_open": "V80-CIRCUIT-OPEN",
    "bulkhead_rejected": "V80-BULKHEAD-REJECTED",
})


def v80_observability_error_code(kind):
    """Return the stable V80 error code for one known reliability kind."""
    if not isinstance(kind, str):
        raise TypeError("V80 reliability kind must be text")
    normalized = kind.strip().lower()
    try:
        return V80_RELIABILITY_ERROR_CODES[normalized]
    except KeyError:
        raise ValueError("unknown V80 reliability kind") from None

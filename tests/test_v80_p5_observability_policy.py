import ast
import importlib.util
import re
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType

import pytest


ROOT = Path(__file__).resolve().parent.parent
POLICY_PATH = (
    ROOT / "src" / "douban_tmdb_follow_single" / "observability_policy.py"
)
RELIABILITY_PATH = (
    ROOT / "src" / "douban_tmdb_follow_single" / "reliability_contract.py"
)


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@lru_cache(maxsize=1)
def _policy():
    return _load("v80_p5_observability_policy", POLICY_PATH)


@lru_cache(maxsize=1)
def _reliability():
    return _load("v80_p5_observability_reliability", RELIABILITY_PATH)


def test_policy_module_exists():
    assert POLICY_PATH.is_file()


def test_schema_and_limits_are_fixed_and_immutable():
    policy = _policy()

    assert isinstance(policy.V80_OBSERVABILITY_SCHEMAS, MappingProxyType)
    assert dict(policy.V80_OBSERVABILITY_SCHEMAS) == {
        "event": "v80-diagnostic-event/1",
        "snapshot": "v80-diagnostics-snapshot/1",
    }
    assert isinstance(policy.V80_OBSERVABILITY_LIMITS, MappingProxyType)
    assert dict(policy.V80_OBSERVABILITY_LIMITS) == {
        "max_snapshot_events": 256,
        "max_text_chars": 512,
    }
    with pytest.raises(TypeError):
        policy.V80_OBSERVABILITY_SCHEMAS["event"] = "changed"
    with pytest.raises(TypeError):
        policy.V80_OBSERVABILITY_LIMITS["max_snapshot_events"] = 1


def test_event_field_groups_are_ordered_unique_and_complete():
    policy = _policy()

    assert policy.V80_OBSERVABILITY_CORE_FIELDS == (
        "schema", "event", "level", "at", "seq", "stage", "error_code",
    )
    assert policy.V80_OBSERVABILITY_CONTEXT_FIELDS == (
        "request_id", "trace_id", "media_id", "provider", "episode",
    )
    assert policy.V80_OBSERVABILITY_MEASUREMENT_FIELDS == (
        "elapsed_ms", "cache", "decision", "count",
    )
    expected = (
        policy.V80_OBSERVABILITY_CORE_FIELDS
        + policy.V80_OBSERVABILITY_CONTEXT_FIELDS
        + policy.V80_OBSERVABILITY_MEASUREMENT_FIELDS
    )
    assert policy.V80_OBSERVABILITY_EVENT_FIELDS == expected
    assert len(expected) == len(set(expected))


def test_levels_and_stages_are_fixed_closed_sets():
    policy = _policy()

    assert policy.V80_OBSERVABILITY_LEVELS == frozenset((
        "INFO", "WARN", "ERROR", "CRITICAL",
    ))
    assert policy.V80_OBSERVABILITY_STAGES == frozenset((
        "request", "search", "match", "detail", "probe", "playback",
        "history", "cache", "lifecycle", "snapshot",
    ))


def test_error_code_catalog_exactly_covers_the_reliability_contract():
    policy = _policy()
    reliability = _reliability()

    assert isinstance(policy.V80_RELIABILITY_ERROR_CODES, MappingProxyType)
    assert dict(policy.V80_RELIABILITY_ERROR_CODES) == {
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
    }
    assert frozenset(policy.V80_RELIABILITY_ERROR_CODES) == reliability.FAILURE_KINDS
    codes = tuple(policy.V80_RELIABILITY_ERROR_CODES.values())
    assert len(codes) == len(set(codes))
    assert all(re.fullmatch(r"V80-[A-Z0-9]+(?:-[A-Z0-9]+)*", code) for code in codes)
    with pytest.raises(TypeError):
        policy.V80_RELIABILITY_ERROR_CODES["runtime"] = "changed"


@pytest.mark.parametrize("kind", (
    "cancelled", "budget_exhausted", "timeout", "dns", "tls",
    "transport", "auth", "rate_limit", "server", "client",
    "unsupported", "payload", "configuration", "runtime",
    "circuit_open", "bulkhead_rejected",
))
def test_error_code_lookup_is_stable_and_normalizes_case_and_space(kind):
    policy = _policy()

    expected = policy.V80_RELIABILITY_ERROR_CODES[kind]
    assert policy.v80_observability_error_code(kind) == expected
    assert policy.v80_observability_error_code("  %s  " % kind.upper()) == expected


@pytest.mark.parametrize("value", (None, 1, "", "other"))
def test_error_code_lookup_rejects_unknown_or_non_string_values(value):
    policy = _policy()

    error = TypeError if not isinstance(value, str) else ValueError
    with pytest.raises(error):
        policy.v80_observability_error_code(value)


def test_policy_is_pure_and_has_no_runtime_or_transport_owner():
    tree = ast.parse(POLICY_PATH.read_text(encoding="utf-8"), filename=str(POLICY_PATH))
    imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imports.update(
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    )
    functions = {
        node.name for node in tree.body if isinstance(node, ast.FunctionDef)
    }
    classes = {
        node.name for node in tree.body if isinstance(node, ast.ClassDef)
    }
    direct_calls = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    attribute_calls = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }

    assert imports == {"types"}
    assert functions == {"v80_observability_error_code"}
    assert classes == set()
    assert direct_calls == {
        "TypeError", "ValueError", "_v80_observability_mapping_proxy",
        "frozenset", "isinstance",
    }
    assert attribute_calls == {"lower", "strip"}
    assert not any(isinstance(node, (ast.With, ast.AsyncWith)) for node in ast.walk(tree))

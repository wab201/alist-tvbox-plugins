import ast
import hashlib
import importlib.util
import threading
from pathlib import Path

import pytest
import requests


ROOT = Path(__file__).resolve().parent.parent
OVERLAY_PATH = ROOT / "tools" / "build_v80_reliability_overlay.py"
CONTRACT_PATH = ROOT / "src" / "douban_tmdb_follow_single" / "reliability_contract.py"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


OVERLAY = _load("v80_p3_reliability_overlay", OVERLAY_PATH)


def _source():
    return (
        "import hashlib\n\n"
        "class Filter:\n"
        "    @staticmethod\n"
        "    def _token_hash(value):\n"
        "        return str(value or '')\n\n"
        "class Spider:\n"
        "    RESOURCE_CAPABILITY_MISSING_STATUSES = frozenset((404, 405, 501))\n\n"
        "    RESOURCE_SEARCH_MODES = frozenset(('vod', 'vod1', 'pansou', 'telegram'))\n\n"
        "    def __init__(self):\n"
        "        self._cache_lock = threading.RLock()\n"
        "        self._cache_generation = 1\n"
        "        self._resource_capabilities = {}\n"
        "        self._resource_capabilities_backend = ''\n"
        "        self._resource_capabilities_revision = 0\n"
        "        self._route_quality_history = {}\n"
        "        self.atvp_api = 'https://example.invalid'\n"
        "        self.atvp_token = 'token'\n\n"
        + OVERLAY.DIAGNOSTIC_ANCHOR
        + "\n"
        + OVERLAY.PROVIDER_CONTROLLER_ANCHOR
        + "\n"
        + "    def _init_locked(self):\n"
        + "        with self._cache_lock:\n"
        + "            with self._cache_lock:\n"
        + OVERLAY.PROVIDER_INIT_RESET_ANCHOR
        + "        return True\n\n"
        + "    def destroy(self):\n"
        + "        with self._cache_lock:\n"
        + "            with self._cache_lock:\n"
        + OVERLAY.PROVIDER_DESTROY_RESET_ANCHOR
        + "        return True\n\n"
        + "    def _resource_capability(self, mode):\n"
        + "        return 'unknown'\n\n"
        + "    def _ensure_atvp_connection(self, force=False):\n"
        + "        return True\n\n"
        + "    def _atvp_endpoint(self, mode):\n"
        + "        return 'https://example.invalid/' + str(mode)\n\n"
        + "    def _mark_resource_capability(self, *args, **kwargs):\n"
        + "        return True\n\n"
        + "    def _resource_api_get(self, mode, params, deadline=None):\n"
        + "        if mode not in self.RESOURCE_SEARCH_MODES:\n"
        + "            raise RuntimeError('unsupported mode')\n"
        + "        if self._resource_capability(mode) == 'missing':\n"
        + "            raise RuntimeError('missing capability')\n"
        + "        if not self._ensure_atvp_connection(force=True):\n"
        + "            raise RuntimeError('missing connection')\n"
        + OVERLAY.PROVIDER_TRANSPORT_ANCHOR
        + "\n"
        + OVERLAY.DEADLINE_ANCHOR
        + "\n"
        + OVERLAY.ATVP_RETRY_ADAPTER_ANCHOR
    ).encode("utf-8")


def _calls(node, name):
    return [
        item for item in ast.walk(node)
        if isinstance(item, ast.Call)
        and isinstance(item.func, ast.Name)
        and item.func.id == name
    ]


def _runtime_namespace():
    result = OVERLAY.apply_reliability_overlay(_source())
    namespace = {}
    source = CONTRACT_PATH.read_bytes() + b"\n" + result["bytes"]
    exec(compile(source, "v80-reliability-runtime.py", "exec"), namespace)
    return namespace


def test_overlay_applies_bounded_insertions_and_hashes_output():
    source = _source()
    result = OVERLAY.apply_reliability_overlay(source)

    assert result["insertions"] == (
        "deadline-timeout", "atvp-retry-adapter", "diagnostic-kind",
        "provider-controller", "provider-init-reset", "provider-destroy-reset",
        "provider-transport",
    )
    assert result["input_size"] == len(source)
    assert result["input_sha256"] == hashlib.sha256(source).hexdigest().upper()
    assert result["size"] == len(result["bytes"])
    assert result["sha256"] == hashlib.sha256(result["bytes"]).hexdigest().upper()


def test_overlay_output_is_valid_and_each_call_exists_once_at_its_method():
    tree = ast.parse(OVERLAY.apply_reliability_overlay(_source())["bytes"])
    compile(tree, "v80-reliability-overlay.py", "exec")
    spider = next(
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "Spider"
    )
    methods = {
        node.name: node for node in spider.body if isinstance(node, ast.FunctionDef)
    }
    expected = {
        "v80_reliability_request_timeout": ("_atvp_deadline_timeout", 1),
        "v80_reliability_atvp_retry_adapter": ("_atvp_retry_adapter", 1),
        "v80_reliability_classify": ("_diagnostic_error_kind", 2),
        "v80_reliability_http_failure": ("_resource_api_get", 1),
        "v80_reliability_payload_failure": ("_resource_api_get", 1),
        "ProviderReliabilityController": ("_provider_reliability_for", 1),
    }
    for call_name, (method_name, total_count) in expected.items():
        assert len(_calls(tree, call_name)) == total_count
        assert len(_calls(methods[method_name], call_name)) == 1

    provider = methods["_resource_api_get"]
    session_get_bindings = [
        item for item in ast.walk(provider)
        if isinstance(item, ast.Attribute)
        and item.attr == "get"
        and isinstance(item.value, ast.Attribute)
        and item.value.attr == "_atvp_session"
    ]
    sender_calls = [
        item for item in ast.walk(provider)
        if isinstance(item, ast.Call)
        and isinstance(item.func, ast.Name)
        and item.func.id == "request_sender"
    ]
    assert len(session_get_bindings) == len(sender_calls) == 1
    assert not any(
        isinstance(item, (ast.For, ast.AsyncFor, ast.While))
        for item in ast.walk(provider)
    )
    assert sum(
        isinstance(item, ast.Call)
        and isinstance(item.func, ast.Attribute)
        and item.func.attr == "acquire"
        for item in ast.walk(provider)
    ) == 1
    assert sum(
        isinstance(item, ast.Call)
        and isinstance(item.func, ast.Attribute)
        and item.func.attr == "finish"
        for item in ast.walk(provider)
    ) == 2


def test_http_call_marks_only_existing_capability_missing_statuses_explicitly():
    tree = ast.parse(OVERLAY.apply_reliability_overlay(_source())["bytes"])
    call = _calls(tree, "v80_reliability_http_failure")[0]
    keyword = next(item for item in call.keywords if item.arg == "explicit_unsupported")

    assert isinstance(keyword.value, ast.Compare)
    assert isinstance(keyword.value.ops[0], ast.In)
    assert isinstance(keyword.value.comparators[0], ast.Attribute)
    assert keyword.value.comparators[0].attr == "RESOURCE_CAPABILITY_MISSING_STATUSES"


@pytest.mark.parametrize("label,anchor,_replacement", OVERLAY.INSERTIONS)
def test_overlay_rejects_each_missing_anchor(label, anchor, _replacement):
    source = _source().decode("utf-8").replace(anchor, "", 1).encode("utf-8")
    with pytest.raises(OVERLAY.ReliabilityOverlayError, match="anchor %s" % label):
        OVERLAY.apply_reliability_overlay(source)


@pytest.mark.parametrize("label,anchor,_replacement", OVERLAY.INSERTIONS)
def test_overlay_rejects_each_duplicate_anchor(label, anchor, _replacement):
    source = _source().decode("utf-8").replace(anchor, anchor + anchor, 1).encode("utf-8")
    with pytest.raises(OVERLAY.ReliabilityOverlayError, match="anchor %s" % label):
        OVERLAY.apply_reliability_overlay(source)


def test_overlay_rejects_invalid_utf8():
    with pytest.raises(OVERLAY.ReliabilityOverlayError, match="not valid UTF-8"):
        OVERLAY.apply_reliability_overlay(b"\xff")


class _Response(object):
    def __init__(self, status):
        self.status_code = status
        self.closed = False

    def close(self):
        self.closed = True


class _Session(object):
    def __init__(self, response, error=None):
        self.response = response
        self.error = error
        self.calls = []

    def get(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        if self.error is not None:
            raise self.error
        return self.response


def _runtime_spider(namespace, status, error=None):
    spider = namespace["Spider"]()
    spider.response = _Response(status)
    spider.timeout = 12
    spider.verify_tls = True
    spider._atvp_session = _Session(spider.response, error=error)
    return spider


def _provider_snapshot(spider, mode="vod"):
    identity = spider._resource_capability_identity()
    return spider._provider_reliability_controller.snapshot(identity, mode)


def test_runtime_http_failure_is_structured_and_closes_response():
    namespace = _runtime_namespace()
    spider = _runtime_spider(namespace, 404)
    spider._read_bounded_json_response = lambda *_args, **_kwargs: {}

    with pytest.raises(namespace["ReliabilityFailure"]) as raised:
        spider._resource_api_get("vod", {})

    assert raised.value.kind == "unsupported"
    assert raised.value.status == 404
    assert raised.value.operation == "resource_api_get"
    assert spider.response.closed is True
    assert len(spider._atvp_session.calls) == 1
    assert _provider_snapshot(spider)["in_flight"] == 0


@pytest.mark.parametrize("status,expected", ((429, "rate_limit"), (500, "server"), (503, "server")))
def test_runtime_http_failures_keep_structured_kind_without_status_retry(status, expected):
    namespace = _runtime_namespace()
    spider = _runtime_spider(namespace, status)
    spider._read_bounded_json_response = lambda *_args, **_kwargs: {}

    with pytest.raises(namespace["ReliabilityFailure"]) as raised:
        spider._resource_api_get("vod", {})

    assert raised.value.kind == expected
    assert raised.value.status == status
    assert spider.response.closed is True
    assert len(spider._atvp_session.calls) == 1
    assert _provider_snapshot(spider)["in_flight"] == 0


@pytest.mark.parametrize("error,expected", (
    (requests.exceptions.SSLError("certificate"), "tls"),
    (RuntimeError("unexpected adapter failure"), "runtime"),
))
def test_runtime_session_failures_reach_diagnostic_mapping_once(error, expected):
    namespace = _runtime_namespace()
    spider = _runtime_spider(namespace, 200, error=error)

    with pytest.raises(type(error)) as raised:
        spider._resource_api_get("vod", {})

    assert spider._diagnostic_error_kind(raised.value) == expected
    assert len(spider._atvp_session.calls) == 1
    assert _provider_snapshot(spider)["in_flight"] == 0


def test_runtime_bounded_json_error_is_redacted_payload_failure():
    namespace = _runtime_namespace()
    spider = _runtime_spider(namespace, 200)

    def fail(*_args, **_kwargs):
        raise ValueError("private-payload-value")

    spider._read_bounded_json_response = fail
    with pytest.raises(namespace["ReliabilityFailure"]) as raised:
        spider._resource_api_get("vod", {})

    assert raised.value.kind == "payload"
    assert raised.value.operation == "resource_api_get"
    assert raised.value.__cause__ is None
    assert "private-payload-value" not in str(raised.value)
    assert spider.response.closed is True
    assert _provider_snapshot(spider)["in_flight"] == 0


@pytest.mark.parametrize("error,expected", (
    (requests.Timeout("slow"), "timeout"),
    (requests.exceptions.SSLError("certificate"), "tls"),
    (requests.ConnectionError("socket"), "transport"),
))
def test_runtime_bounded_reader_preserves_non_payload_failure(error, expected):
    namespace = _runtime_namespace()
    spider = _runtime_spider(namespace, 200)
    spider._read_bounded_json_response = lambda *_args, **_kwargs: (_ for _ in ()).throw(error)

    with pytest.raises(namespace["ReliabilityFailure"]) as raised:
        spider._resource_api_get("vod", {})

    assert raised.value.kind == expected
    assert spider.response.closed is True
    assert _provider_snapshot(spider)["in_flight"] == 0


def test_runtime_bounded_reader_marks_expired_parent_deadline_as_budget_exhausted():
    namespace = _runtime_namespace()
    spider = _runtime_spider(namespace, 200)
    spider._atvp_deadline_timeout = lambda *_args, **_kwargs: 1
    spider._read_bounded_json_response = lambda *_args, **_kwargs: (_ for _ in ()).throw(
        RuntimeError("response exceeded total deadline"),
    )

    with pytest.raises(namespace["ReliabilityFailure"]) as raised:
        spider._resource_api_get("vod", {}, deadline=10.0)

    assert raised.value.kind == "budget_exhausted"


def test_runtime_delegates_diagnostic_and_timeout_seams():
    namespace = _runtime_namespace()
    spider = namespace["Spider"]()

    assert spider._diagnostic_error_kind(namespace["ReliabilityFailure"](
        "configuration", operation="test_configuration",
    )) == "configuration"
    assert spider._atvp_deadline_timeout(None, 5.9, requests_left=4) == 5


def test_runtime_provider_timeout_reserves_transport_backoff(monkeypatch):
    namespace = _runtime_namespace()
    spider = _runtime_spider(namespace, 200)
    spider._read_bounded_json_response = lambda *_args, **_kwargs: {}
    monkeypatch.setattr(namespace["time"], "monotonic", lambda: 90.0)

    assert spider._resource_api_get("vod", {}, deadline=100.0) == {}

    timeout = spider._atvp_session.calls[0][1]["timeout"]
    assert timeout == pytest.approx((10.0 - 0.8) / 6.0)
    assert spider.response.closed is True
    assert _provider_snapshot(spider)["in_flight"] == 0


def test_runtime_circuit_short_circuits_after_three_transport_failures():
    namespace = _runtime_namespace()
    spider = _runtime_spider(namespace, 200, error=requests.Timeout("slow"))

    for _ in range(3):
        with pytest.raises(requests.Timeout):
            spider._resource_api_get("vod", {})
    with pytest.raises(namespace["ReliabilityFailure"]) as raised:
        spider._resource_api_get("vod", {})

    assert raised.value.kind == "circuit_open"
    assert len(spider._atvp_session.calls) == 3
    assert _provider_snapshot(spider)["state"] == "open"


def test_runtime_half_open_probe_success_closes_circuit(monkeypatch):
    namespace = _runtime_namespace()
    now = [10.0]
    monkeypatch.setattr(namespace["time"], "monotonic", lambda: now[0])
    spider = _runtime_spider(namespace, 200, error=requests.Timeout("slow"))
    for _ in range(3):
        with pytest.raises(requests.Timeout):
            spider._resource_api_get("vod", {})

    now[0] += 30.0
    spider._atvp_session.error = None
    spider._read_bounded_json_response = lambda *_args, **_kwargs: {}
    assert spider._resource_api_get("vod", {}) == {}
    assert _provider_snapshot(spider)["state"] == "closed"


def test_runtime_half_open_local_preflight_failure_keeps_circuit_open(monkeypatch):
    namespace = _runtime_namespace()
    now = [10.0]
    monkeypatch.setattr(namespace["time"], "monotonic", lambda: now[0])
    spider = _runtime_spider(namespace, 200, error=requests.Timeout("slow"))
    for _ in range(3):
        with pytest.raises(requests.Timeout):
            spider._resource_api_get("vod", {})

    now[0] += 30.0

    def fail_preflight(*_args, **_kwargs):
        raise namespace["ReliabilityFailure"](
            "budget_exhausted", operation="request_timeout",
        )

    spider._atvp_deadline_timeout = fail_preflight
    with pytest.raises(namespace["ReliabilityFailure"]) as raised:
        spider._resource_api_get("vod", {})

    assert raised.value.kind == "budget_exhausted"
    assert len(spider._atvp_session.calls) == 3
    assert _provider_snapshot(spider)["state"] == "open"


def test_runtime_bulkhead_rejection_makes_no_network_call():
    namespace = _runtime_namespace()
    spider = _runtime_spider(namespace, 200)
    identity = spider._resource_capability_identity()
    controller = spider._provider_reliability_for(identity)
    first = controller.acquire(identity, "vod")
    second = controller.acquire(identity, "vod")

    with pytest.raises(namespace["ReliabilityFailure"]) as raised:
        spider._resource_api_get("vod", {})
    assert raised.value.kind == "bulkhead_rejected"
    assert spider._atvp_session.calls == []

    first.finish(success=True)
    second.finish(success=True)
    spider._read_bounded_json_response = lambda *_args, **_kwargs: {}
    assert spider._resource_api_get("vod", {}) == {}


def test_runtime_backend_switch_resets_provider_state():
    namespace = _runtime_namespace()
    spider = _runtime_spider(namespace, 200, error=requests.Timeout("slow"))
    for _ in range(2):
        with pytest.raises(requests.Timeout):
            spider._resource_api_get("vod", {})
    old_identity = spider._resource_capability_identity()
    assert _provider_snapshot(spider)["failures"] == 2

    spider.atvp_api = "https://other.invalid"
    new_identity = spider._resource_capability_identity()
    spider._provider_reliability_for(new_identity)

    assert old_identity != new_identity
    assert spider._provider_reliability_controller.snapshot() == []


def test_runtime_stale_backend_request_cannot_reset_new_backend_state():
    namespace = _runtime_namespace()
    spider = _runtime_spider(namespace, 200)
    entered = threading.Event()
    release = threading.Event()
    errors = []

    def blocked_timeout(*_args, **_kwargs):
        entered.set()
        assert release.wait(2)
        return 1

    spider._atvp_deadline_timeout = blocked_timeout

    def request():
        try:
            spider._resource_api_get("vod", {})
        except Exception as exc:
            errors.append(exc)

    worker = threading.Thread(target=request)
    worker.start()
    assert entered.wait(2)

    with spider._cache_lock:
        spider.atvp_api = "https://other.invalid"
        spider._cache_generation += 1
        generation = spider._cache_generation
        new_identity = spider._resource_capability_identity()
    controller = spider._provider_reliability_for(
        new_identity, expected_generation=generation,
    )
    controller.acquire(new_identity, "vod").finish(failure_kind="server")
    release.set()
    worker.join(timeout=2)

    assert len(errors) == 1
    assert isinstance(errors[0], namespace["ReliabilityFailure"])
    assert errors[0].kind == "cancelled"
    assert spider._atvp_session.calls == []
    snapshot = controller.snapshot(new_identity, "vod")
    assert snapshot["failures"] == 1
    assert snapshot["state"] == "closed"


def test_runtime_destroy_invalidates_provider_state_and_old_lease():
    namespace = _runtime_namespace()
    spider = _runtime_spider(namespace, 200)
    identity = spider._resource_capability_identity()
    controller = spider._provider_reliability_for(
        identity, expected_generation=spider._cache_generation,
    )
    stale = controller.acquire(identity, "vod")

    spider.destroy()
    assert controller.snapshot() == []
    assert stale.finish(failure_kind="timeout") is True
    assert controller.snapshot() == []


def test_runtime_retry_adapter_owns_only_transport_retry():
    namespace = _runtime_namespace()
    retry = namespace["Spider"]()._atvp_retry_adapter().max_retries

    assert retry.total == 2
    assert retry.connect == 2
    assert retry.read == 2
    assert retry.status == 0
    assert retry.other == 0
    assert retry.backoff_factor == pytest.approx(0.4)
    assert set(retry.allowed_methods) == {"GET"}
    assert retry.respect_retry_after_header is False
    assert retry.raise_on_status is False
    assert retry.is_retry("GET", 429, has_retry_after=True) is False
    assert retry.is_retry("GET", 503, has_retry_after=True) is False


@pytest.mark.parametrize("error,expected", (
    (RuntimeError("request timed out"), "timeout"),
    (RuntimeError("connection failed"), "transport"),
    (RuntimeError("invalid JSON"), "payload"),
    (RuntimeError("HTTP 401"), "auth"),
    (RuntimeError("HTTP 429"), "rate_limit"),
    (RuntimeError("服务限流"), "rate_limit"),
    (RuntimeError("generation cancelled"), "cancelled"),
    (RuntimeError("任务已销毁"), "cancelled"),
))
def test_runtime_preserves_legacy_diagnostic_fallbacks(error, expected):
    namespace = _runtime_namespace()
    spider = namespace["Spider"]()

    assert spider._diagnostic_error_kind(error) == expected

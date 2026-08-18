"""Measure repeated lifecycle quiescence for the isolated V80 candidate."""

import argparse
import ast
import builtins
import datetime as dt
import hashlib
import importlib.util
import json
import math
import os
import statistics
import sys
import threading
import time
import types
from functools import lru_cache
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
BUILD_PATH = ROOT / "tools" / "build_follow_plugin.py"
MANIFEST_PATH = ROOT / "src" / "douban_tmdb_follow_single" / "release.json"
DEFAULT_REPORT = ROOT / "work" / "v80-p5-lifecycle-stability.json"
REPORT_SCHEMA = "v80-p5-lifecycle-stability/3"
DEFAULT_CYCLES = 32
MIN_CYCLES = 2
MAX_CYCLES = 64
QUIESCENCE_TIMEOUT = 1.0
SHORT_TASK_SECONDS = 0.20
STUBBED_METHODS = (
    "_load_follow_state",
    "_load_history_share_policy",
    "_load_series_action_mode",
    "_load_resume_markers",
    "_load_atvp_status",
    "_load_follow_action_state",
    "_schedule_entry_resource_preheat",
    "_flush_route_quality_sync",
    "_flush_response_cache_sync",
)
PERSISTENCE_STUBBED_METHODS = (
    "_flush_route_quality_sync",
    "_flush_response_cache_sync",
)
SHORT_CREDENTIAL_FIELDS = (
    "cookie",
    "ck",
    "user_id",
    "tmdb_access_token",
    "tmdb_api_key",
    "atvp_token",
    "history_username",
    "history_password",
    "_history_auth_token",
)
REFERENCE_FIELDS = (
    "_refreshing_cache_keys",
    "_resource_search_jobs",
    "_resource_entry_preheat_jobs",
    "_route_probe_jobs",
    "_bound_replacement_jobs",
    "_native_exports",
)
REFERENCE_SCALAR_FIELDS = (
    "_persistent_cache_saving",
    "_route_quality_saving",
)
DEPLOYMENT_IMPORT_ROOTS = (
    "fabric",
    "ftplib",
    "invoke",
    "paramiko",
    "subprocess",
)
DEPLOYMENT_CALL_PREFIXES = (
    "fabric.",
    "ftplib.",
    "invoke.",
    "os.exec",
    "os.popen",
    "os.spawn",
    "os.startfile",
    "os.system",
    "paramiko.",
    "subprocess.",
)
DEPLOYMENT_OS_CALLS = (
    "popen",
    "startfile",
    "system",
)
MANDATORY_INVARIANTS = (
    "generation_monotonic",
    "task_supervisor_closed",
    "playback_state_cleared",
    "sessions_closed_once",
    "old_generation_callback_rejected",
    "response_references_non_growing",
    "owned_resources_quiescent",
)


class LifecycleAssertionError(AssertionError):
    pass


class IsolationObserver(object):
    def __init__(self):
        self.request_attempts = 0
        self.socket_connect_attempts = 0
        self.credential_values_observed = 0
        self.production_persistence_calls = 0
        self.production_persistence_calls_blocked = 0

    def block_request(self, surface):
        self.request_attempts += 1
        raise LifecycleAssertionError(
            "network access is forbidden through %s" % surface
        )

    def block_socket(self, surface):
        self.socket_connect_attempts += 1
        raise LifecycleAssertionError(
            "socket access is forbidden through %s" % surface
        )

    def observe_credentials(self, spider):
        count = sum(
            bool(str(getattr(spider, name, "") or "").strip())
            for name in SHORT_CREDENTIAL_FIELDS
        )
        self.credential_values_observed += count
        return count

    def block_persistence_call(self):
        self.production_persistence_calls += 1
        self.production_persistence_calls_blocked += 1
        return False

    def snapshot(self):
        production_writes = (
            self.production_persistence_calls
            - self.production_persistence_calls_blocked
        )
        network_requests = self.request_attempts + self.socket_connect_attempts
        return {
            "request_attempts": self.request_attempts,
            "socket_connect_attempts": self.socket_connect_attempts,
            "network_requests": network_requests,
            "credential_values_observed": self.credential_values_observed,
            "production_persistence_calls": self.production_persistence_calls,
            "production_persistence_calls_blocked": (
                self.production_persistence_calls_blocked
            ),
            "production_writes": production_writes > 0,
            "credentials_used": self.credential_values_observed > 0,
        }


class FakeSession(object):
    instances = []
    observer = None

    def __init__(self):
        self.headers = {}
        self.proxies = {}
        self.mounts = {}
        self.trust_env = False
        self.close_calls = 0
        self.__class__.instances.append(self)

    def mount(self, prefix, adapter):
        self.mounts[str(prefix)] = adapter

    def close(self):
        self.close_calls += 1

    def _block(self, method):
        if self.__class__.observer is None:
            raise LifecycleAssertionError("network observer is not installed")
        return self.__class__.observer.block_request("Session.%s" % method)

    def request(self, *_args, **_kwargs):
        return self._block("request")

    def get(self, *_args, **_kwargs):
        return self._block("get")

    def post(self, *_args, **_kwargs):
        return self._block("post")

    def delete(self, *_args, **_kwargs):
        return self._block("delete")


class CancelProbe(object):
    def __init__(self):
        self.cancel_calls = 0

    def cancel(self):
        self.cancel_calls += 1


class RequestsProxy(object):
    def __init__(self, real_module, observer, adapters, packages):
        self.Session = FakeSession
        self.adapters = adapters
        self.exceptions = real_module.exceptions
        self.packages = packages
        self.sessions = self
        self._observer = observer

    def _block(self, method):
        return self._observer.block_request("requests.%s" % method)

    def request(self, *_args, **_kwargs):
        return self._block("request")

    def get(self, *_args, **_kwargs):
        return self._block("get")

    def post(self, *_args, **_kwargs):
        return self._block("post")

    def put(self, *_args, **_kwargs):
        return self._block("put")

    def patch(self, *_args, **_kwargs):
        return self._block("patch")

    def delete(self, *_args, **_kwargs):
        return self._block("delete")

    def head(self, *_args, **_kwargs):
        return self._block("head")

    def options(self, *_args, **_kwargs):
        return self._block("options")


class FakeHTTPAdapter(object):
    observer = None

    def __init__(self, *_args, **_kwargs):
        pass

    def close(self):
        return None

    def init_poolmanager(self, *_args, **_kwargs):
        return None

    def proxy_manager_for(self, *_args, **_kwargs):
        if self.__class__.observer is None:
            raise LifecycleAssertionError("network observer is not installed")
        return self.__class__.observer.block_request("HTTPAdapter.proxy_manager_for")

    def send(self, *_args, **_kwargs):
        if self.__class__.observer is None:
            raise LifecycleAssertionError("network observer is not installed")
        return self.__class__.observer.block_request("HTTPAdapter.send")


class ImportlibProxy(object):
    def __init__(
            self, real_module, requests_proxy, socket_proxy,
            adapters_proxy, retry_proxy):
        self._real_module = real_module
        self._requests_proxy = requests_proxy
        self._socket_proxy = socket_proxy
        self._adapters_proxy = adapters_proxy
        self._retry_proxy = retry_proxy

    def import_module(self, name, package=None):
        name = str(name or "")
        if name == "requests.adapters":
            return self._adapters_proxy
        if name == "requests.packages.urllib3.util.retry":
            return self._retry_proxy
        if name == "requests" or name.startswith("requests."):
            return self._requests_proxy
        if name == "socket" or name.startswith("socket."):
            return self._socket_proxy
        return self._real_module.import_module(name, package)

    def __getattr__(self, name):
        return getattr(self._real_module, name)


class SocketProxy(object):
    def __init__(self, real_module, observer):
        self.SOCK_STREAM = real_module.SOCK_STREAM
        self.gaierror = real_module.gaierror
        self.timeout = real_module.timeout
        self._observer = observer

    def _block(self, method):
        return self._observer.block_socket("socket.%s" % method)

    def socket(self, *_args, **_kwargs):
        return self._block("socket")

    def create_connection(self, *_args, **_kwargs):
        return self._block("create_connection")

    def getaddrinfo(self, *_args, **_kwargs):
        return self._block("getaddrinfo")


def _require(condition, detail):
    if not condition:
        raise LifecycleAssertionError(detail)


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load required module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BUILD = _load("v80_p5_lifecycle_build", BUILD_PATH)


@lru_cache(maxsize=1)
def _build_result():
    return BUILD.build_release(MANIFEST_PATH)


def _runner_provenance():
    path = Path(__file__).resolve()
    payload = path.read_bytes()
    return {
        "path": str(path.relative_to(ROOT)).replace("\\", "/"),
        "size": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest().upper(),
    }


def _runtime_module(observer):
    base_module = types.ModuleType("base")
    spider_module = types.ModuleType("base.spider")

    class BaseSpider(object):
        pass

    spider_module.Spider = BaseSpider
    sys.modules.setdefault("base", base_module)
    sys.modules.setdefault("base.spider", spider_module)
    module = types.ModuleType("v80_p5_lifecycle_runtime")
    candidate_bytes = _build_result()["bytes"]
    deployment_surface = _deployment_surface_evidence(candidate_bytes)
    _require(
        deployment_surface["listed_deployment_surfaces_absent_static_ast"],
        "candidate or runner contains a listed deployment surface",
    )
    real_importlib = builtins.__import__("importlib")
    real_requests = builtins.__import__("requests")
    real_socket = builtins.__import__("socket")
    adapters_proxy = types.SimpleNamespace(HTTPAdapter=FakeHTTPAdapter)
    retry_proxy = types.SimpleNamespace(
        Retry=real_requests.packages.urllib3.util.retry.Retry
    )
    urllib3_proxy = types.SimpleNamespace(
        disable_warnings=lambda *_args, **_kwargs: None,
        util=types.SimpleNamespace(retry=retry_proxy),
    )
    packages_proxy = types.SimpleNamespace(urllib3=urllib3_proxy)
    requests_proxy = RequestsProxy(
        real_requests, observer, adapters_proxy, packages_proxy
    )
    socket_proxy = SocketProxy(real_socket, observer)
    importlib_proxy = ImportlibProxy(
        real_importlib,
        requests_proxy,
        socket_proxy,
        adapters_proxy,
        retry_proxy,
    )
    real_import = builtins.__import__

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
        if level == 0:
            if name == "requests.adapters":
                return adapters_proxy
            if name == "requests.packages.urllib3.util.retry":
                return retry_proxy
            if name == "requests" or name.startswith("requests."):
                return requests_proxy
            if name == "socket" or name.startswith("socket."):
                return socket_proxy
            if name == "importlib" or name.startswith("importlib."):
                return importlib_proxy
        return real_import(name, globals, locals, fromlist, level)

    runtime_builtins = dict(vars(builtins))
    runtime_builtins["__import__"] = guarded_import
    module.__dict__["__builtins__"] = runtime_builtins
    module.requests = requests_proxy
    module.socket = socket_proxy
    FakeSession.observer = observer
    FakeHTTPAdapter.observer = observer
    exec(
        compile(candidate_bytes, "v80-p5-lifecycle-runtime.py", "exec"),
        module.__dict__,
    )
    module._v80_lifecycle_deployment_surface = deployment_surface
    return module


def _install_isolation_stubs(spider, observer):
    for name in STUBBED_METHODS:
        if name in PERSISTENCE_STUBBED_METHODS:
            setattr(
                spider,
                name,
                lambda *_args, **_kwargs: observer.block_persistence_call(),
            )
        else:
            setattr(spider, name, lambda *_args, **_kwargs: False)


def _wait_for(predicate, timeout=1.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return bool(predicate())


def _executor_is_closed(executor):
    try:
        executor.submit(lambda: None)
    except RuntimeError:
        return True
    return False


def _reference_counts(spider):
    counts = {
        name: len(getattr(spider, name))
        for name in REFERENCE_FIELDS
    }
    counts.update({
        name: int(getattr(spider, name) is not None)
        for name in REFERENCE_SCALAR_FIELDS
    })
    return counts


def _expected_reference_counts(index):
    counts = {
        name: 0 for name in REFERENCE_FIELDS + REFERENCE_SCALAR_FIELDS
    }
    if index == 1:
        counts["_refreshing_cache_keys"] = 1
    return counts


def _dotted_name(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _dotted_name(node.value)
        return "%s.%s" % (prefix, node.attr) if prefix else node.attr
    return ""


def _deployment_surface_scan(source, label):
    tree = ast.parse(bytes(source).decode("utf-8"), filename=label)
    findings = []
    module_aliases = {}
    call_aliases = set()
    dynamic_import_aliases = set()
    wildcard_import_roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".", 1)[0]
                module_aliases[alias.asname or root] = root
                if root in DEPLOYMENT_IMPORT_ROOTS:
                    findings.append({
                        "source": label,
                        "line": node.lineno,
                        "surface": "import:%s" % root,
                    })
        elif isinstance(node, ast.ImportFrom):
            root = str(node.module or "").split(".", 1)[0]
            if root in DEPLOYMENT_IMPORT_ROOTS:
                findings.append({
                    "source": label,
                    "line": node.lineno,
                    "surface": "import:%s" % root,
                })
            for alias in node.names:
                if alias.name == "*":
                    if root == "os":
                        wildcard_import_roots.add(root)
                    continue
                local_name = alias.asname or alias.name
                if root in DEPLOYMENT_IMPORT_ROOTS:
                    call_aliases.add(local_name)
                if root == "importlib" and alias.name == "import_module":
                    dynamic_import_aliases.add(local_name)
                if root == "os" and (
                    alias.name in DEPLOYMENT_OS_CALLS
                    or alias.name.startswith(("exec", "spawn"))
                ):
                    call_aliases.add(local_name)
                    findings.append({
                        "source": label,
                        "line": node.lineno,
                        "surface": "import:os.%s" % alias.name,
                    })

    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            targets = tuple(node.targets)
        elif isinstance(node, ast.AnnAssign):
            targets = (node.target,)
        else:
            continue
        value_name = _dotted_name(node.value)
        first = value_name.split(".", 1)[0]
        if first in module_aliases:
            value_name = module_aliases[first] + value_name[len(first):]
        if value_name == "importlib.import_module" or value_name in dynamic_import_aliases:
            dynamic_import_aliases.update(
                target.id for target in targets if isinstance(target, ast.Name)
            )

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _dotted_name(node.func)
        normalized = name
        first = name.split(".", 1)[0]
        if first in module_aliases:
            normalized = module_aliases[first] + name[len(first):]
        if (
            "os" in wildcard_import_roots
            and (name in DEPLOYMENT_OS_CALLS or name.startswith(("exec", "spawn")))
        ):
            findings.append({
                "source": label,
                "line": node.lineno,
                "surface": "call:os.%s" % name,
            })
            continue
        if (
            name in call_aliases
            or any(normalized.startswith(prefix) for prefix in DEPLOYMENT_CALL_PREFIXES)
        ):
            findings.append({
                "source": label,
                "line": node.lineno,
                "surface": "call:%s" % (normalized or name),
            })
            continue
        if (
            normalized in ("__import__", "importlib.import_module")
            or name in dynamic_import_aliases
        ) and node.args:
            module_name = node.args[0]
            if isinstance(module_name, ast.Constant) and isinstance(module_name.value, str):
                root = module_name.value.split(".", 1)[0]
                if root in DEPLOYMENT_IMPORT_ROOTS:
                    findings.append({
                        "source": label,
                        "line": node.lineno,
                        "surface": "dynamic-import:%s" % root,
                    })
    return findings


def _deployment_surface_evidence(candidate_bytes):
    findings = []
    findings.extend(_deployment_surface_scan(
        candidate_bytes,
        "build/v80-dev/candidate.py",
    ))
    findings.extend(_deployment_surface_scan(
        Path(__file__).read_bytes(),
        "tests/v80_p5_lifecycle_stability_runner.py",
    ))
    return {
        "source": "static_ast",
        "guard_phase": "before_candidate_exec",
        "scanned": [
            "build/v80-dev/candidate.py",
            "tests/v80_p5_lifecycle_stability_runner.py",
        ],
        "forbidden_import_roots": list(DEPLOYMENT_IMPORT_ROOTS),
        "forbidden_call_prefixes": list(DEPLOYMENT_CALL_PREFIXES),
        "findings": findings,
        "listed_deployment_surfaces_absent_static_ast": not findings,
    }


def _cycle_row_is_admitted(row, index):
    if not isinstance(row, dict):
        return False
    generation = row.get("generation")
    contract = row.get("controlled_task_contract")
    before = row.get("owned_resources_before_destroy")
    after_destroy = row.get("owned_resources_after_destroy_before_release")
    after = row.get("owned_resources_after_destroy")
    if not all(
        isinstance(section, dict)
        for section in (generation, contract, before, after_destroy, after)
    ):
        return False
    expected_references = _expected_reference_counts(index)
    future_count = before.get("executor_futures_pending")
    worker_count = before.get("executor_worker_threads_alive")
    generation_values = (
        generation.get("before"),
        generation.get("after_init"),
        generation.get("after_destroy"),
    )
    zero_resource_fields = (
        "threads",
        "timers",
        "executors",
        "supervised_threads_alive",
        "executor_futures_pending",
        "executor_worker_threads_alive",
        "owned_timer_alive",
    )
    before_active_fields = ("supervised_threads_alive", "owned_timer_alive")
    after_destroy_active_fields = (
        "supervised_threads_alive",
        "executor_futures_pending",
        "executor_worker_threads_alive",
    )
    after_zero_fields = tuple(zero_resource_fields)
    actual_references = after.get("response_reference_counts")
    reported_expected_references = after.get("expected_response_reference_counts")
    expected_reference_shape = (
        isinstance(actual_references, dict)
        and set(actual_references) == set(expected_references)
        and all(
            type(actual_references[name]) is int
            and actual_references[name] == expected_references[name]
            for name in expected_references
        )
    )
    reported_expected_reference_shape = (
        isinstance(reported_expected_references, dict)
        and set(reported_expected_references) == set(expected_references)
        and all(
            type(reported_expected_references[name]) is int
            and reported_expected_references[name] == expected_references[name]
            for name in expected_references
        )
    )
    return (
        type(row.get("cycle")) is int
        and row.get("cycle") == index
        and row.get("status") == "passed"
        and type(row.get("sessions_created_total")) is int
        and row.get("sessions_created_total") == 3 * (index + 1)
        and all(type(value) is int for value in generation_values)
        and generation_values == (2 * (index - 1), 2 * index - 1, 2 * index)
        and contract.get("active_at_destroy") is True
        and contract.get("active_after_destroy_before_release") is True
        and contract.get("release_owner") == "runner_after_destroy"
        and contract.get("release_after_destroy") is True
        and contract.get("shutdown_cancellation_claimed") is False
        and contract.get("safety_timeout_seconds")
        == QUIESCENCE_TIMEOUT + SHORT_TASK_SECONDS
        and before.get("supervised_threads_alive") == 1
        and before.get("owned_timer_alive") == 1
        and type(future_count) is int
        and future_count > 0
        and type(worker_count) is int
        and worker_count == future_count
        and all(type(before.get(name)) is int for name in before_active_fields)
        and all(type(after_destroy.get(name)) is int for name in after_destroy_active_fields)
        and all(type(after.get(name)) is int for name in after_zero_fields)
        and after_destroy.get("supervised_threads_alive") == 1
        and after_destroy.get("executor_futures_pending") == future_count
        and after_destroy.get("executor_worker_threads_alive") == worker_count
        and all(after.get(name) == 0 for name in zero_resource_fields)
        and after.get("response_references") == sum(expected_references.values())
        and expected_reference_shape
        and reported_expected_reference_shape
        and type(after.get("response_references")) is int
        and type(after.get("response_reference_owner_mismatches")) is int
        and after.get("response_reference_owner_mismatches") == 0
    )


def _candidate_is_admitted(report):
    candidate = report.get("candidate")
    if not isinstance(candidate, dict):
        return False
    build = _build_result()
    expected = {
        "size": build["size"],
        "sha256": build["sha256"],
        "output": str(build["output"].relative_to(ROOT)).replace("\\", "/"),
    }
    return candidate == expected


def _generated_at_is_admitted(report):
    value = report.get("generated_at")
    if not isinstance(value, str) or not value.endswith("Z"):
        return False
    try:
        parsed = dt.datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return False
    return parsed.tzinfo is not None


def _timing_is_admitted(report):
    timing = report.get("timing")
    if not isinstance(timing, dict):
        return False
    values = tuple(timing.get(name) for name in ("min_ms", "median_ms", "p95_ms", "max_ms"))
    return (
        timing.get("source") == "host_wall_clock_observation"
        and timing.get("admission_threshold") is False
        and all(
            type(value) in (int, float)
            and math.isfinite(float(value))
            and value >= 0
            for value in values
        )
        and values[0] <= values[1] <= values[2] <= values[3]
    )


def report_is_admitted(report, allow_pending=False):
    if not isinstance(report, dict):
        return False
    summary = report.get("summary")
    invariants = report.get("invariants")
    isolation = report.get("isolation")
    if not all(isinstance(value, dict) for value in (summary, invariants, isolation)):
        return False
    deployment = isolation.get("deployment_surface")
    if not isinstance(deployment, dict):
        return False
    provenance = report.get("evidence_provenance")
    if not isinstance(provenance, dict):
        return False
    cycles = report.get("cycles")
    rows = report.get("cycle_results")
    request_attempts = isolation.get("request_attempts")
    socket_attempts = isolation.get("socket_connect_attempts")
    network_requests = isolation.get("network_requests")
    credential_values = isolation.get("credential_values_observed")
    persistence_calls = isolation.get("production_persistence_calls")
    persistence_blocked = isolation.get("production_persistence_calls_blocked")
    summary_values = (
        summary.get("total"),
        summary.get("passed"),
        summary.get("failed"),
    )
    valid_cycles = type(cycles) is int and MIN_CYCLES <= cycles <= MAX_CYCLES
    valid_rows = (
        valid_cycles
        and isinstance(rows, list)
        and len(rows) == cycles
        and all(
            _cycle_row_is_admitted(row, index)
            for index, row in enumerate(rows, 1)
        )
    )
    counts = (
        request_attempts,
        socket_attempts,
        network_requests,
        credential_values,
        persistence_calls,
        persistence_blocked,
    )
    valid_counts = all(type(value) is int and value >= 0 for value in counts)
    expected_persistence_calls = (
        cycles * len(PERSISTENCE_STUBBED_METHODS) if valid_cycles else None
    )
    return (
        (
            report.get("overall") == "passed"
            or (allow_pending and report.get("overall") == "pending")
        )
        and report.get("schema") == REPORT_SCHEMA
        and _candidate_is_admitted(report)
        and _generated_at_is_admitted(report)
        and _timing_is_admitted(report)
        and provenance == {"runner": _runner_provenance()}
        and valid_cycles
        and valid_rows
        and valid_counts
        and all(type(value) is int for value in summary_values)
        and summary_values == (cycles, cycles, 0)
        and all(invariants.get(name) is True for name in MANDATORY_INVARIANTS)
        and isolation.get("scope") == "candidate_runtime"
        and isolation.get("session_factory") == "FakeSession"
        and isolation.get("stubbed_methods") == list(STUBBED_METHODS)
        and request_attempts == 0
        and socket_attempts == 0
        and network_requests == request_attempts + socket_attempts == 0
        and credential_values == 0
        and isolation.get("credentials_used") is False
        and persistence_calls == expected_persistence_calls
        and persistence_blocked == persistence_calls
        and isolation.get("production_writes") is False
        and isolation.get("deployment_attempted") is False
        and isolation.get("deployment_attempted_basis")
        == "pre_execution_static_ast_guard"
        and deployment == _deployment_surface_evidence(_build_result()["bytes"])
    )


def _capture_stale_refresh(spider, key):
    callbacks = []
    original_start = spider._tasks.start_thread

    def capture(target, args=(), kwargs=None, name="background"):
        callbacks.append(lambda: target(*tuple(args or ()), **dict(kwargs or {})))
        return True

    spider._tasks.start_thread = capture
    try:
        _require(
            spider._schedule_cache_refresh(key, lambda: {"generation": "old"}),
            "stale callback fixture was not scheduled",
        )
    finally:
        spider._tasks.start_thread = original_start
    _require(len(callbacks) == 1, "stale callback fixture count drifted")
    return callbacks[0]


def _cycle(spider, index, stale_state):
    started = time.perf_counter()
    before_generation = spider._cache_generation
    spider.init({})
    init_generation = spider._cache_generation
    _require(init_generation > before_generation, "generation did not advance on init")

    tasks = spider._tasks
    _require(not tasks.is_closed(), "task supervisor remained closed after init")
    executors = tuple(tasks._executors)
    _require(executors, "task executor ownership is empty")

    task_release = threading.Event()

    def short_task(started):
        started.set()
        return task_release.wait(QUIESCENCE_TIMEOUT + SHORT_TASK_SECONDS)

    future_started = [threading.Event() for _executor in executors]
    executor_futures = [
        executor.submit(short_task, started)
        for executor, started in zip(executors, future_started)
    ]
    _require(
        all(started.wait(QUIESCENCE_TIMEOUT) for started in future_started),
        "executor lifecycle task did not start",
    )

    thread_started = threading.Event()
    probe_name = "lifecycle-probe-%d" % index
    tasks.start_thread(short_task, args=(thread_started,), name=probe_name)
    _require(
        thread_started.wait(QUIESCENCE_TIMEOUT),
        "supervised lifecycle task did not start",
    )
    supervised_threads = tuple(
        thread for thread in tasks._threads if thread.name == probe_name
    )
    _require(len(supervised_threads) == 1, "supervised thread reference was not retained")
    supervised_thread = supervised_threads[0]
    executor_worker_threads = tuple(
        thread
        for executor in executors
        for thread in tuple(executor._threads)
    )
    _require(
        len(executor_worker_threads) == len(executors),
        "executor worker references were not retained",
    )

    owned_timer = tasks.start_timer(60.0, lambda: None, name="lifecycle-probe")
    playback_timer = CancelProbe()
    playback_key = "cycle-%d" % index
    spider._playback_sync_pending[playback_key] = {"owner": object()}
    spider._playback_sync_timers[playback_key] = playback_timer
    spider._playback_sync_tokens[playback_key] = object()
    spider._playback_sync_inflight[playback_key] = object()

    stale_key = "lifecycle-stale-refresh"
    if index == 1:
        stale_state["callback"] = _capture_stale_refresh(spider, stale_key)
        stale_state["generation"] = init_generation
    elif index == 2:
        callback = stale_state.pop("callback")
        callback()
        _require(stale_key not in spider._cache, "old callback mutated new state")
        stale_state["rejected"] = True

    current_sessions = (spider._session, spider._tmdb_session, spider._atvp_session)
    _require(all(session is not None for session in current_sessions), "session set is incomplete")
    _require(all(session.close_calls == 0 for session in current_sessions), "active session was already closed")
    _require(
        stale_state["observer"].observe_credentials(spider) == 0,
        "credential material entered the isolated lifecycle",
    )
    active_before_destroy = {
        "supervised_threads_alive": int(supervised_thread.is_alive()),
        "executor_futures_pending": sum(
            not future.done() for future in executor_futures
        ),
        "executor_worker_threads_alive": sum(
            thread.is_alive() for thread in executor_worker_threads
        ),
        "owned_timer_alive": int(owned_timer.is_alive()),
    }
    _require(
        active_before_destroy == {
            "supervised_threads_alive": 1,
            "executor_futures_pending": len(executor_futures),
            "executor_worker_threads_alive": len(executor_worker_threads),
            "owned_timer_alive": 1,
        },
        "lifecycle resources were not active at destroy",
    )
    _require(not task_release.is_set(), "controlled task released before destroy")

    spider.destroy()
    active_after_destroy_before_release = {
        "supervised_threads_alive": int(supervised_thread.is_alive()),
        "executor_futures_pending": sum(
            not future.done() for future in executor_futures
        ),
        "executor_worker_threads_alive": sum(
            thread.is_alive() for thread in executor_worker_threads
        ),
    }
    _require(
        active_after_destroy_before_release == {
            "supervised_threads_alive": 1,
            "executor_futures_pending": len(executor_futures),
            "executor_worker_threads_alive": len(executor_worker_threads),
        },
        "controlled tasks did not remain active until runner release",
    )
    task_release.set()
    destroy_generation = spider._cache_generation
    _require(destroy_generation > init_generation, "generation did not advance on destroy")
    _require(tasks.is_closed(), "task supervisor did not close")
    _require(not tasks._threads and not tasks._timers and not tasks._executors, "task ownership remained after destroy")
    _require(playback_timer.cancel_calls == 1, "playback timer was not cancelled once")
    _require(
        not spider._playback_sync_pending
        and not spider._playback_sync_timers
        and not spider._playback_sync_tokens
        and not spider._playback_sync_inflight,
        "playback synchronization state remained after destroy",
    )
    _require(all(session.close_calls == 1 for session in current_sessions), "session close count drifted")
    _require(
        spider._session is None and spider._tmdb_session is None and spider._atvp_session is None,
        "destroy retained session references",
    )
    response_reference_counts = _reference_counts(spider)
    expected_reference_counts = _expected_reference_counts(index)
    if index == 1:
        _require(
            set(spider._refreshing_cache_keys) == {stale_key},
            "first-cycle stale refresh owner drifted",
        )
    _require(
        response_reference_counts == expected_reference_counts,
        "response reference ownership drifted",
    )
    response_references = sum(response_reference_counts.values())
    _require(
        _wait_for(lambda: not owned_timer.is_alive(), timeout=QUIESCENCE_TIMEOUT),
        "owned timer thread remained alive",
    )
    _require(
        _wait_for(lambda: not supervised_thread.is_alive(), timeout=QUIESCENCE_TIMEOUT),
        "supervised lifecycle thread remained alive",
    )
    _require(
        _wait_for(
            lambda: all(future.done() for future in executor_futures),
            timeout=QUIESCENCE_TIMEOUT,
        ),
        "executor lifecycle future remained active",
    )
    _require(
        all(future.result(timeout=0) is True for future in executor_futures),
        "executor lifecycle future did not complete normally",
    )
    _require(
        _wait_for(
            lambda: not any(
                thread.is_alive() for thread in executor_worker_threads
            ),
            timeout=QUIESCENCE_TIMEOUT,
        ),
        "executor worker thread remained alive",
    )
    _require(all(_executor_is_closed(executor) for executor in executors), "executor accepted work after destroy")
    _require(
        all(session.close_calls == 1 for session in FakeSession.instances),
        "a replaced session was closed more than once",
    )

    return {
        "cycle": index,
        "status": "passed",
        "generation": {
            "before": before_generation,
            "after_init": init_generation,
            "after_destroy": destroy_generation,
        },
        "sessions_created_total": len(FakeSession.instances),
        "controlled_task_contract": {
            "active_at_destroy": True,
            "active_after_destroy_before_release": True,
            "release_owner": "runner_after_destroy",
            "release_after_destroy": task_release.is_set(),
            "shutdown_cancellation_claimed": False,
            "safety_timeout_seconds": QUIESCENCE_TIMEOUT + SHORT_TASK_SECONDS,
        },
        "owned_resources_before_destroy": active_before_destroy,
        "owned_resources_after_destroy_before_release": (
            active_after_destroy_before_release
        ),
        "owned_resources_after_destroy": {
            "threads": len(tasks._threads),
            "timers": len(tasks._timers),
            "executors": len(tasks._executors),
            "supervised_threads_alive": int(supervised_thread.is_alive()),
            "executor_futures_pending": sum(
                not future.done() for future in executor_futures
            ),
            "executor_worker_threads_alive": sum(
                thread.is_alive() for thread in executor_worker_threads
            ),
            "owned_timer_alive": int(owned_timer.is_alive()),
            "response_references": response_references,
            "response_reference_counts": response_reference_counts,
            "expected_response_reference_counts": expected_reference_counts,
            "response_reference_owner_mismatches": sum(
                response_reference_counts[name] != expected_reference_counts[name]
                for name in expected_reference_counts
            ),
        },
        "duration_ms": round((time.perf_counter() - started) * 1000.0, 3),
    }


def _timing_summary(rows):
    values = sorted(row["duration_ms"] for row in rows if row["status"] == "passed")
    if not values:
        return {"min_ms": None, "median_ms": None, "p95_ms": None, "max_ms": None}
    p95_index = max(0, (95 * len(values) + 99) // 100 - 1)
    return {
        "min_ms": round(values[0], 3),
        "median_ms": round(statistics.median(values), 3),
        "p95_ms": round(values[p95_index], 3),
        "max_ms": round(values[-1], 3),
    }


def run_lifecycle_stability(cycles=DEFAULT_CYCLES):
    cycles = int(cycles)
    if cycles < MIN_CYCLES or cycles > MAX_CYCLES:
        raise ValueError("cycles must be between %d and %d" % (MIN_CYCLES, MAX_CYCLES))

    FakeSession.instances = []
    observer = IsolationObserver()
    module = _runtime_module(observer)
    spider = module.Spider()
    _install_isolation_stubs(spider, observer)
    stale_state = {"rejected": False, "observer": observer}
    rows = []
    try:
        for index in range(1, cycles + 1):
            try:
                rows.append(_cycle(spider, index, stale_state))
            except Exception as exc:
                rows.append({
                    "cycle": index,
                    "status": "failed",
                    "error_type": type(exc).__name__,
                    "error": str(exc) if isinstance(exc, LifecycleAssertionError) else "cycle execution failed",
                })
                try:
                    spider.destroy()
                except Exception:
                    pass
    finally:
        if not spider._tasks.is_closed():
            spider.destroy()

    passed = sum(row["status"] == "passed" for row in rows)
    reference_counts = [
        row["owned_resources_after_destroy"]["response_references"]
        for row in rows if row["status"] == "passed"
    ]
    references_non_growing = (
        len(reference_counts) == cycles
        and all(
            current <= previous
            for previous, current in zip(reference_counts, reference_counts[1:])
        )
    )
    resources_quiescent = (
        len(rows) == cycles
        and all(
            _cycle_row_is_admitted(row, index)
            for index, row in enumerate(rows, 1)
        )
    )
    build = _build_result()
    deployment_surface = module._v80_lifecycle_deployment_surface
    report = {
        "schema": REPORT_SCHEMA,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
        "evidence_provenance": {"runner": _runner_provenance()},
        "candidate": {
            "size": build["size"],
            "sha256": build["sha256"],
            "output": str(build["output"].relative_to(ROOT)).replace("\\", "/"),
        },
        "cycles": cycles,
        "summary": {"total": cycles, "passed": passed, "failed": cycles - passed},
        "timing": dict(
            _timing_summary(rows),
            source="host_wall_clock_observation",
            admission_threshold=False,
        ),
        "invariants": {
            "generation_monotonic": passed == cycles,
            "task_supervisor_closed": passed == cycles,
            "playback_state_cleared": passed == cycles,
            "sessions_closed_once": passed == cycles,
            "old_generation_callback_rejected": stale_state.get("rejected") is True,
            "response_references_non_growing": references_non_growing,
            "owned_resources_quiescent": resources_quiescent,
        },
        "isolation": dict({
            "scope": "candidate_runtime",
            "session_factory": "FakeSession",
            "stubbed_methods": list(STUBBED_METHODS),
            "deployment_surface": deployment_surface,
            "deployment_attempted": not deployment_surface[
                "listed_deployment_surfaces_absent_static_ast"
            ],
            "deployment_attempted_basis": "pre_execution_static_ast_guard",
        }, **observer.snapshot()),
        "cycle_results": rows,
    }
    report["overall"] = "pending"
    admitted = report_is_admitted(report, allow_pending=True)
    report["overall"] = "passed" if admitted else "failed"
    if report_is_admitted(report) is not admitted:
        raise LifecycleAssertionError("final lifecycle admission state drifted")
    return report


def write_report(path, report):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    os.replace(str(temp), str(path))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cycles", type=int, default=DEFAULT_CYCLES)
    parser.add_argument("--json-out", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args(argv)
    try:
        report = run_lifecycle_stability(args.cycles)
    except ValueError as exc:
        parser.error(str(exc))
    write_report(args.json_out, report)
    summary = report["summary"]
    admitted = report_is_admitted(report)
    print(
        "V80 P5 lifecycle stability: %s, %d/%d cycles passed (%s)"
        % (
            "passed" if admitted else "failed",
            summary["passed"],
            summary["total"],
            args.json_out,
        )
    )
    return 0 if admitted else 1


if __name__ == "__main__":
    raise SystemExit(main())

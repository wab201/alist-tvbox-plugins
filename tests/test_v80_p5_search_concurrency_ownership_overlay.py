import ast
import hashlib
import importlib.util
import socket
import sys
import threading
import time
import types
from concurrent.futures import Future
from functools import lru_cache
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parent.parent
BUILD_PATH = ROOT / "tools" / "build_follow_plugin.py"
OVERLAY_PATH = ROOT / "tools" / "build_v80_search_concurrency_ownership_overlay.py"
MANIFEST_PATH = ROOT / "src" / "douban_tmdb_follow_single" / "release.json"
PUBLIC_V70 = ROOT / "py" / "豆瓣TMDB追更单入口.py"
P5_5A_SIZE = 851185
P5_5A_SHA256 = "202240F5A086E4ABAEF5CFCEE09E458E77BDA41761E525566F83B6517146D2F3"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BUILD = _load("v80_search_concurrency_ownership_build", BUILD_PATH)
OVERLAY = _load("v80_search_concurrency_ownership_overlay", OVERLAY_PATH)


@lru_cache(maxsize=1)
def _p5_5a_source():
    manifest = BUILD.load_manifest(MANIFEST_PATH)
    manifest["expected_size"] = P5_5A_SIZE
    manifest["expected_sha256"] = P5_5A_SHA256
    original_search = BUILD._apply_search_concurrency_ownership_overlay
    original_playback = BUILD._apply_playback_concurrency_ownership_overlay
    original_history = BUILD._apply_history_concurrency_ownership_overlay
    BUILD._apply_search_concurrency_ownership_overlay = lambda source: (source, None)
    BUILD._apply_playback_concurrency_ownership_overlay = lambda source: (source, None)
    BUILD._apply_history_concurrency_ownership_overlay = lambda source: (source, None)
    try:
        source = BUILD._assemble(
            manifest, BUILD._find_repo_root(manifest["manifest_path"]),
        )[0]
    finally:
        BUILD._apply_history_concurrency_ownership_overlay = original_history
        BUILD._apply_search_concurrency_ownership_overlay = original_search
        BUILD._apply_playback_concurrency_ownership_overlay = original_playback
    assert len(source) == P5_5A_SIZE
    assert hashlib.sha256(source).hexdigest().upper() == P5_5A_SHA256
    return source


@lru_cache(maxsize=1)
def _final_source():
    return OVERLAY.apply_search_concurrency_ownership_overlay(
        _p5_5a_source(),
    )["bytes"]


def _runtime(source, name):
    base_module = types.ModuleType("base")
    spider_module = types.ModuleType("base.spider")

    class BaseSpider(object):
        pass

    spider_module.Spider = BaseSpider
    sys.modules["base"] = base_module
    sys.modules["base.spider"] = spider_module
    module = types.ModuleType(name)
    exec(compile(source, "%s.py" % name, "exec"), module.__dict__)
    return module


class ResponseFixture(object):
    def __init__(self, body=b'{"list": []}', status=200, blocking=False):
        self.body = bytes(body)
        self.status_code = int(status)
        self.headers = {"Content-Length": str(len(self.body))}
        self.blocking = bool(blocking)
        self.started = threading.Event()
        self.closed = threading.Event()
        self.close_calls = 0
        self._lock = threading.Lock()

    def iter_content(self, chunk_size=65536):
        del chunk_size
        self.started.set()
        if self.blocking:
            self.closed.wait(3.0)
            raise RuntimeError("response closed")
        yield self.body

    def close(self):
        with self._lock:
            self.close_calls += 1
        self.closed.set()


class SessionFixture(object):
    def __init__(self, response):
        self.response = response
        self.calls = 0
        self.close_calls = 0

    def get(self, *args, **kwargs):
        del args, kwargs
        self.calls += 1
        return self.response

    def close(self):
        self.close_calls += 1


class LeaseFixture(object):
    def __init__(self):
        self.finishes = []

    def finish(self, **kwargs):
        self.finishes.append(dict(kwargs))
        return True


class ReliabilityFixture(object):
    def __init__(self, lease):
        self.lease = lease

    def acquire(self, *args, **kwargs):
        del args, kwargs
        return self.lease


class CountingSlot(object):
    def __init__(self, capacity=1):
        self.capacity = int(capacity)
        self.held = 0
        self.acquires = 0
        self.releases = 0

    def acquire(self, blocking=True, timeout=None):
        del timeout
        self.acquires += 1
        if self.held >= self.capacity:
            return False
        self.held += 1
        return True

    def release(self):
        if self.held <= 0:
            raise AssertionError("slot released more than once")
        self.held -= 1
        self.releases += 1


class ImmediateExecutor(object):
    def __init__(self):
        self.calls = 0

    def submit(self, function, *args, **kwargs):
        self.calls += 1
        future = Future()
        try:
            future.set_result(function(*args, **kwargs))
        except BaseException as exc:
            future.set_exception(exc)
        return future


class QueuedExecutor(object):
    def __init__(self):
        self.pending = []

    def submit(self, function, *args, **kwargs):
        future = Future()
        self.pending.append((future, function, args, kwargs))
        return future

    def run_next(self):
        future, function, args, kwargs = self.pending.pop(0)
        if future.cancelled():
            return
        try:
            future.set_result(function(*args, **kwargs))
        except BaseException as exc:
            future.set_exception(exc)


class RejectingExecutor(object):
    def submit(self, function, *args, **kwargs):
        del function, args, kwargs
        raise RuntimeError("executor rejected")


def _resource_spider(module, response):
    spider = module.Spider()
    lease = LeaseFixture()
    spider._alist_tvbox_plugin = True
    spider.atvp_api = "https://example.invalid"
    spider.atvp_token = "test-token"
    spider._atvp_session = SessionFixture(response)
    spider._resource_capability = lambda mode: "present"
    spider._ensure_atvp_connection = lambda force=False: True
    spider._resource_capability_identity = lambda: ("test-backend",)
    spider._atvp_endpoint = lambda mode: "https://example.invalid/%s" % mode
    spider._mark_resource_capability = lambda *args, **kwargs: None
    spider._provider_reliability_for = (
        lambda *args, **kwargs: ReliabilityFixture(lease)
    )
    return spider, lease


def _method_dump(source, method_name):
    tree = ast.parse(source)
    spider = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Spider")
    method = next(node for node in spider.body if isinstance(node, ast.FunctionDef) and node.name == method_name)
    return ast.dump(method)


def _shared_probe_owner_dump(source, method_name):
    tree = ast.parse(source)
    spider = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Spider")
    method = next(node for node in spider.body if isinstance(node, ast.FunctionDef) and node.name == method_name)
    method.decorator_list = []
    if method.args.args and method.args.args[0].arg == "self":
        method.args.args = method.args.args[1:]
    owner_names = {
        "_dns_executor": "_DNS_EXECUTOR",
        "_dns_slots": "_DNS_SLOTS",
        "_media_probe_executor": "_MEDIA_PROBE_EXECUTOR",
        "_media_probe_slots": "_MEDIA_PROBE_SLOTS",
    }

    class OwnerNormalizer(ast.NodeTransformer):
        def visit_Attribute(self, node):
            node = self.generic_visit(node)
            if isinstance(node.value, ast.Name) and node.value.id == "self":
                replacement = owner_names.get(node.attr)
                if replacement:
                    return ast.copy_location(ast.Name(id=replacement, ctx=node.ctx), node)
            return node

    normalized = OwnerNormalizer().visit(method)
    ast.fix_missing_locations(normalized)
    return ast.dump(normalized)


def test_overlay_is_parseable_and_preserves_v70_fingerprint():
    result = OVERLAY.apply_search_concurrency_ownership_overlay(_p5_5a_source())
    assert result["input_size"] == P5_5A_SIZE
    assert result["input_sha256"] == P5_5A_SHA256
    assert result["alias_zh"] == "搜索并发所有权覆盖层"
    assert result["insertions"] == tuple(row[0] for row in OVERLAY.INSERTIONS)
    ast.parse(result["bytes"].decode("utf-8"))
    public = PUBLIC_V70.read_bytes()
    assert len(public) == 616699
    assert hashlib.sha256(public).hexdigest().upper() == (
        "233C73CAE1048210B34872D4A10EA6023662300F70A8657DB82EA65C342182D4"
    )


@pytest.mark.parametrize("index", range(len(OVERLAY.INSERTIONS)))
def test_overlay_rejects_missing_or_duplicate_anchors(index):
    label, anchor, _replacement = OVERLAY.INSERTIONS[index]
    text = _p5_5a_source().decode("utf-8")
    with pytest.raises(
            OVERLAY.SearchConcurrencyOwnershipOverlayError,
            match="anchor %s" % label):
        OVERLAY.apply_search_concurrency_ownership_overlay(
            text.replace(anchor, "", 1).encode("utf-8"),
        )
    with pytest.raises(
            OVERLAY.SearchConcurrencyOwnershipOverlayError,
            match="anchor %s" % label):
        OVERLAY.apply_search_concurrency_ownership_overlay(
            text.replace(anchor, anchor + anchor, 1).encode("utf-8"),
        )


def test_shared_history_and_play_reader_is_byte_semantically_unchanged():
    assert _method_dump(_p5_5a_source(), "_read_bounded_json_response") == _method_dump(
        _final_source(), "_read_bounded_json_response",
    )
    module = _runtime(_final_source(), "v80_p55d_shared_reader")
    spider = module.Spider()
    try:
        for label in ("AList-TVBox History", "AList 播放"):
            response = ResponseFixture()
            assert spider._read_bounded_json_response(response, label) == {"list": []}
            assert response.close_calls == 1
    finally:
        spider.destroy()


@pytest.mark.parametrize(
    "method_name",
    (
        "_resolved_media_target",
        "_pinned_media_request_blocking",
        "_probe_media_output",
        "_v80_probe_media_output_unbounded",
    ),
)
def test_shared_playback_probe_algorithms_are_unchanged(method_name):
    assert _method_dump(_p5_5a_source(), method_name) == _method_dump(
        _final_source(), method_name,
    )


@pytest.mark.parametrize("method_name", ("_resolve_addresses", "_pinned_media_request"))
def test_shared_probe_pool_change_is_owner_only(method_name):
    assert _shared_probe_owner_dump(
        _p5_5a_source(), method_name,
    ) == _shared_probe_owner_dump(_final_source(), method_name)


def test_resource_search_owner_closes_success_response_once():
    module = _runtime(_final_source(), "v80_p55d_response_success")
    response = ResponseFixture()
    spider, lease = _resource_spider(module, response)
    try:
        assert spider._resource_api_get("vod", {"wd": "test"}) == {"list": []}
        assert response.close_calls == 1
        assert lease.finishes == [{"success": True}]
    finally:
        spider.destroy()


def test_resource_search_owner_closes_payload_failure_once():
    module = _runtime(_final_source(), "v80_p55d_response_payload")
    response = ResponseFixture(b"not-json")
    spider, lease = _resource_spider(module, response)
    try:
        with pytest.raises(module.ReliabilityFailure) as raised:
            spider._resource_api_get("vod", {"wd": "test"})
        assert raised.value.kind == "payload"
        assert response.close_calls == 1
        assert lease.finishes == [{"failure_kind": "payload"}]
    finally:
        spider.destroy()


def test_resource_search_owner_keeps_http_failure_outer_close_once():
    module = _runtime(_final_source(), "v80_p55d_response_http")
    response = ResponseFixture(status=503)
    spider, lease = _resource_spider(module, response)
    try:
        with pytest.raises(module.ReliabilityFailure) as raised:
            spider._resource_api_get("vod", {"wd": "test"})
        assert raised.value.kind == "server"
        assert response.close_calls == 1
        assert lease.finishes == [{"failure_kind": "server"}]
    finally:
        spider.destroy()


def test_resource_response_track_cancellation_window_closes_once():
    module = _runtime(_final_source(), "v80_p55d_response_track_cancel")
    response = ResponseFixture()
    spider, lease = _resource_spider(module, response)
    session = spider._atvp_session

    def get_and_cancel(*args, **kwargs):
        value = session.response
        session.calls += 1
        with spider._cache_lock:
            spider._cache_generation += 1
            generation = spider._cache_generation
        spider._timeout_budget_controller.reset(generation)
        return value

    session.get = get_and_cancel
    try:
        with pytest.raises(module.ReliabilityFailure) as raised:
            spider._resource_api_get("vod", {"wd": "test"})
        assert raised.value.kind == "cancelled"
        assert response.close_calls == 1
        assert lease.finishes == [{"failure_kind": "cancelled"}]
    finally:
        spider.destroy()


def test_generation_is_explicitly_forwarded_through_mode_api_chain():
    module = _runtime(_final_source(), "v80_p55d_generation_chain")
    spider = module.Spider()
    with spider._cache_lock:
        generation = spider._cache_generation
    mode_generations = []
    api_generations = []
    spider._resource_capability = lambda mode: "present"
    resource_api_get = module.Spider._resource_api_get.__get__(spider, module.Spider)
    spider._resource_api_get = (
        lambda mode, params, deadline=None, expected_generation=None:
        mode_generations.append(expected_generation) or {"list": []}
    )
    try:
        assert spider._resource_search_mode(
            "vod", ("query",), deadline=time.monotonic() + 5,
            expected_generation=generation,
        ) == []
        assert mode_generations == [generation]

        def unbounded(mode, params, deadline=None, expected_generation=None,
                      timeout_operation=None):
            del mode, params, deadline, timeout_operation
            api_generations.append(expected_generation)
            return {"list": []}

        spider._resource_api_get = resource_api_get
        spider._v80_resource_api_get_unbounded = unbounded
        assert spider._resource_api_get(
            "vod", {"wd": "test"}, expected_generation=generation,
        ) == {"list": []}
        assert api_generations == [generation]
    finally:
        spider.destroy()


def test_resource_api_snapshots_old_session_before_live_session_swap():
    module = _runtime(_final_source(), "v80_p55d_session_snapshot")
    old_response = ResponseFixture()
    new_response = ResponseFixture()
    spider, lease = _resource_spider(module, old_response)
    old_session = spider._atvp_session
    new_session = SessionFixture(new_response)
    ready = threading.Event()
    resume = threading.Event()
    original_timeout = spider._atvp_deadline_timeout

    def pause_after_snapshot(*args, **kwargs):
        ready.set()
        assert resume.wait(2)
        return original_timeout(*args, **kwargs)

    spider._atvp_deadline_timeout = pause_after_snapshot
    result = []

    def worker():
        result.append(spider._resource_api_get(
            "vod", {"wd": "test"}, expected_generation=spider._cache_generation,
        ))

    thread = threading.Thread(target=worker)
    thread.start()
    assert ready.wait(2)
    spider._atvp_session = new_session
    spider.atvp_token = "new-token"
    resume.set()
    thread.join(3)
    try:
        assert not thread.is_alive()
        assert result == [{"list": []}]
        assert old_session.calls == 1
        assert new_session.calls == 0
        assert lease.finishes == [{"success": True}]
    finally:
        spider.destroy()


def test_supplement_scheduler_rejects_stale_generation_inside_cache_lock():
    module = _runtime(_final_source(), "v80_p55d_supplement_generation")
    spider = module.Spider()
    with spider._cache_lock:
        generation = spider._cache_generation
        spider._cache_generation += 1
    try:
        assert spider._schedule_supplement_resource_search(
            ("pansou",), ("query",), {"title": "title"},
            "resource:stale", expected_generation=generation,
        ) is False
        with spider._cache_lock:
            assert spider._resource_search_jobs == {}
            assert spider._refreshing_cache_keys == {}
    finally:
        spider.destroy()


def test_instance_runtime_pools_rebuild_without_old_pool_contamination():
    module = _runtime(_final_source(), "v80_p55d_pool_lifecycle")
    spider = module.Spider()
    executor_names = (
        "_resource_search_executor", "_follow_refresh_executor",
        "_resource_foreground_mode_executor", "_resource_background_mode_executor",
        "_dns_executor", "_media_probe_executor",
    )
    old_executors = {name: getattr(spider, name) for name in executor_names}
    old_tasks = spider._tasks
    old_dns_slots = spider._dns_slots
    old_media_slots = spider._media_probe_slots
    for _ in range(4):
        assert old_dns_slots.acquire(False)
        assert old_media_slots.acquire(False)
    spider.init({})
    assert all(getattr(executor, "_shutdown", False) for executor in old_executors.values())
    try:
        assert old_tasks.is_closed()
        new_executors = {name: getattr(spider, name) for name in executor_names}
        assert all(new_executors[name] is not old_executors[name] for name in executor_names)
        assert all(not getattr(executor, "_shutdown", False) for executor in new_executors.values())
        assert all(spider._dns_slots.acquire(False) for _ in range(4))
        assert not spider._dns_slots.acquire(False)
        assert all(spider._media_probe_slots.acquire(False) for _ in range(4))
        assert not spider._media_probe_slots.acquire(False)
    finally:
        for _ in range(4):
            old_dns_slots.release()
            old_media_slots.release()
        spider.destroy()


def test_dns_and_media_probe_use_instance_pools_not_module_globals(monkeypatch):
    module = _runtime(_final_source(), "v80_p55d_instance_owners")
    spider = module.Spider()
    dns_executor = ImmediateExecutor()
    media_executor = ImmediateExecutor()
    spider._dns_executor = dns_executor
    spider._dns_slots = CountingSlot()
    spider._media_probe_executor = media_executor
    spider._media_probe_slots = CountingSlot()
    assert not hasattr(module, "_DNS_EXECUTOR")
    assert not hasattr(module, "_DNS_SLOTS")
    assert not hasattr(module, "_MEDIA_PROBE_EXECUTOR")
    assert not hasattr(module, "_MEDIA_PROBE_SLOTS")
    module._DNS_EXECUTOR = RejectingExecutor()
    module._MEDIA_PROBE_EXECUTOR = RejectingExecutor()
    monkeypatch.setattr(
        module.socket, "getaddrinfo",
        lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))],
    )
    spider._pinned_media_request_blocking = lambda *args, **kwargs: {"status": 200}
    try:
        addresses = spider._resolve_addresses("example.invalid", 443, deadline=10**9)
        assert any(str(value) == "8.8.8.8" for value in addresses)
        assert spider._dns_slots.acquires == 1
        assert spider._dns_slots.releases == 1
        assert spider._pinned_media_request(
            types.SimpleNamespace(hostname="example.invalid", port=443, scheme="https",
                                  path="/", query=""),
            "8.8.8.8", {}, deadline=10**9,
        ) == {"status": 200}
        assert spider._media_probe_slots.acquires == 1
        assert spider._media_probe_slots.releases == 1
    finally:
        spider.destroy()


@pytest.mark.parametrize("background", (False, True))
def test_queued_old_generation_returns_without_request_or_new_token(background):
    module = _runtime(_final_source(), "v80_p55d_generation_queue_%s" % background)
    spider = module.Spider()
    executor = QueuedExecutor()
    slot = CountingSlot()
    if background:
        spider._resource_background_mode_executor = executor
        spider._resource_background_mode_slots = slot
    else:
        spider._resource_foreground_mode_executor = executor
        spider._resource_foreground_mode_slots = slot
    calls = []
    spider._resource_search_mode = lambda *args, **kwargs: calls.append((args, kwargs)) or [{"id": "must-not-run"}]
    spider.atvp_token = "old-token"
    with spider._cache_lock:
        generation = spider._cache_generation
    try:
        future = spider._submit_resource_mode_search(
            "vod", ("query",), time.monotonic() + 5,
            background=background, expected_generation=generation,
        )
        assert future is not None
        with spider._cache_lock:
            spider._cache_generation += 1
            new_generation = spider._cache_generation
        spider._timeout_budget_controller.reset(new_generation)
        spider.atvp_token = "new-token"
        executor.run_next()
        assert future.result(timeout=1) == []
        assert calls == []
        assert slot.acquires == 1
        assert slot.releases == 1
    finally:
        spider.destroy()


def test_running_old_generation_discards_result_after_token_switch():
    module = _runtime(_final_source(), "v80_p55d_generation_post_fence")
    spider = module.Spider()
    started = threading.Event()
    resume = threading.Event()
    observed = []
    spider.atvp_token = "old-token"

    def search(*args, **kwargs):
        del args, kwargs
        observed.append(spider.atvp_token)
        started.set()
        resume.wait(2)
        return [{"id": "old-result"}]

    spider._resource_search_mode = search
    with spider._cache_lock:
        generation = spider._cache_generation
    try:
        future = spider._submit_resource_mode_search(
            "vod", ("query",), time.monotonic() + 5,
            expected_generation=generation,
        )
        assert future is not None
        assert started.wait(2)
        with spider._cache_lock:
            spider._cache_generation += 1
            new_generation = spider._cache_generation
        spider._timeout_budget_controller.reset(new_generation)
        spider.atvp_token = "new-token"
        resume.set()
        assert future.result(timeout=3) == []
        assert observed == ["old-token"]
    finally:
        resume.set()
        spider.destroy()


@pytest.mark.parametrize("background", (False, True))
@pytest.mark.parametrize("executor_kind", ("success", "reject"))
def test_mode_slot_is_released_exactly_once(background, executor_kind):
    module = _runtime(_final_source(), "v80_p55d_slot_once_%s_%s" % (background, executor_kind))
    spider = module.Spider()
    slot = CountingSlot()
    executor = ImmediateExecutor() if executor_kind == "success" else RejectingExecutor()
    if background:
        spider._resource_background_mode_executor = executor
        spider._resource_background_mode_slots = slot
    else:
        spider._resource_foreground_mode_executor = executor
        spider._resource_foreground_mode_slots = slot
    spider._resource_search_mode = lambda *args, **kwargs: []
    try:
        future = spider._submit_resource_mode_search(
            "vod", ("query",), time.monotonic() + 5, background=background,
        )
        if executor_kind == "success":
            assert future.result(timeout=1) == []
        else:
            assert future is None
        assert slot.acquires == 1
        assert slot.releases == 1
    finally:
        spider.destroy()


def test_resource_completion_bulkhead_is_the_only_search_capacity_owner():
    module = _runtime(_final_source(), "v80_p55d_bulkhead_owner")
    spider = module.Spider()
    executor = QueuedExecutor()
    spider._resource_search_executor = executor
    spider._resource_fair_candidate_order = lambda *args, **kwargs: []
    spider._checked_resource_rows = lambda *args, **kwargs: []
    spider._playable_resource_rows = lambda *args, **kwargs: []
    try:
        assert not hasattr(spider, "_resource_search_admissions")
        accepted = []
        for index in range(10):
            key = "resource:%d" % index
            assert spider._schedule_supplement_resource_search(
                (), (), {"title": "title-%d" % index}, key,
            ) is True
            accepted.append(key)
        assert spider._schedule_supplement_resource_search(
            (), (), {"title": "overflow"}, "resource:overflow",
        ) is False
        snapshot = spider._background_bulkhead_controller.snapshot()
        assert snapshot["inflight"]["resource_completion"] == 10
        assert "resource:overflow" not in spider._resource_search_jobs
    finally:
        spider.destroy()
    assert spider._background_bulkhead_controller.snapshot()["inflight"]["resource_completion"] == 0
    assert spider._resource_search_jobs == {}

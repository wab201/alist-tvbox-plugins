import hashlib
import importlib.util
import json
import sys
import threading
import types
from functools import lru_cache
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parent.parent
BUILD_PATH = ROOT / "tools" / "build_follow_plugin.py"
OVERLAY_PATH = ROOT / "tools" / "build_v80_timeout_budget_overlay.py"
MANIFEST_PATH = ROOT / "src" / "douban_tmdb_follow_single" / "release.json"
PUBLIC_V70 = ROOT / "py" / "豆瓣TMDB追更单入口.py"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BUILD = _load("v80_timeout_budget_build", BUILD_PATH)
OVERLAY = _load("v80_timeout_budget_overlay", OVERLAY_PATH)


@lru_cache(maxsize=1)
def _build_result():
    return BUILD.build_release(MANIFEST_PATH)


def _pre_overlay_source():
    module = _build_result()["timeout_budget_module"]
    return module["input_bytes"] + module["bytes"]


def _load_runtime():
    base_module = types.ModuleType("base")
    spider_module = types.ModuleType("base.spider")

    class BaseSpider(object):
        pass

    spider_module.Spider = BaseSpider
    sys.modules.setdefault("base", base_module)
    sys.modules.setdefault("base.spider", spider_module)
    module = types.ModuleType("v80_timeout_budget_runtime")
    source = _build_result()["bytes"]
    exec(compile(source, "v80-timeout-budget-runtime.py", "exec"), module.__dict__)
    return module


class Clock(object):
    def __init__(self, value=100.0):
        self.value = float(value)
        self._lock = threading.Lock()

    def __call__(self):
        with self._lock:
            return self.value

    def advance(self, seconds):
        with self._lock:
            self.value += float(seconds)


class JsonResponse(object):
    def __init__(self, status=200, payload=None, text="x" * 600):
        self.status_code = status
        self.payload = {} if payload is None else payload
        self.content = json.dumps(self.payload).encode("utf-8")
        self.text = text
        self.url = "https://www.douban.com/people/test-user/"
        self.headers = {}
        self.close_calls = 0

    def json(self):
        return self.payload

    def close(self):
        self.close_calls += 1


class RecordingSession(object):
    def __init__(self, responses=None, on_request=None):
        self.responses = list(responses or [JsonResponse()])
        self.on_request = on_request
        self.calls = []

    def _send(self, method, url, **kwargs):
        self.calls.append((method, url, dict(kwargs)))
        if self.on_request is not None:
            self.on_request(method, url, kwargs)
        return self.responses.pop(0)

    def get(self, url, **kwargs):
        return self._send("GET", url, **kwargs)

    def post(self, url, **kwargs):
        return self._send("POST", url, **kwargs)

    def close(self):
        return None


class BlockingJsonResponse(object):
    def __init__(self):
        self.status_code = 200
        self.headers = {}
        self.started = threading.Event()
        self.closed = threading.Event()
        self.close_calls = 0
        self._lock = threading.Lock()

    def iter_content(self, chunk_size=65536):
        del chunk_size
        self.started.set()
        self.closed.wait(2.0)
        raise RuntimeError("stream closed")

    def close(self):
        with self._lock:
            self.close_calls += 1
        self.closed.set()


class QueuedExecutor(object):
    def __init__(self):
        self.work = []

    def submit(self, worker):
        self.work.append(worker)
        return object()


def _install_clock(module, spider, clock):
    spider._timeout_budget_controller = module.TimeoutBudgetController(
        generation=spider._cache_generation,
        clock=clock,
    )


def test_overlay_matches_security_policy_input_and_frozen_v70():
    source = _pre_overlay_source()
    result = OVERLAY.apply_timeout_budget_overlay(source)
    built = _build_result()
    security_policy = built["security_policy_module"]
    public = PUBLIC_V70.read_bytes()

    assert result["bytes"] == security_policy["input_bytes"]
    assert result["size"] == security_policy["input_size"]
    assert result["sha256"] == security_policy["input_sha256"]
    assert result["input_sha256"] == hashlib.sha256(source).hexdigest().upper()
    assert result["insertions"] == tuple(label for label, _anchor, _replacement in OVERLAY.INSERTIONS)
    assert len(result["insertions"]) == 42
    assert len(public) == 616699
    assert hashlib.sha256(public).hexdigest().upper() == (
        "233C73CAE1048210B34872D4A10EA6023662300F70A8657DB82EA65C342182D4"
    )


@pytest.mark.parametrize("index", (0, 2, 13, 20, 28, 34, 41))
def test_overlay_rejects_representative_missing_anchors(index):
    label, anchor, _replacement = OVERLAY.INSERTIONS[index]
    source = _pre_overlay_source().decode("utf-8").replace(anchor, "", 1)

    with pytest.raises(OVERLAY.TimeoutBudgetOverlayError, match="anchor %s" % label):
        OVERLAY.apply_timeout_budget_overlay(source.encode("utf-8"))


def test_overlay_rejects_duplicate_controller_anchor_and_invalid_utf8():
    label, anchor, _replacement = OVERLAY.INSERTIONS[2]
    source = _pre_overlay_source().decode("utf-8").replace(anchor, anchor + anchor, 1)
    with pytest.raises(OVERLAY.TimeoutBudgetOverlayError, match="anchor %s" % label):
        OVERLAY.apply_timeout_budget_overlay(source.encode("utf-8"))
    with pytest.raises(OVERLAY.TimeoutBudgetOverlayError, match="not valid UTF-8"):
        OVERLAY.apply_timeout_budget_overlay(b"\xff")


@pytest.mark.parametrize(
    "method_name,private_name,args,budget_name",
    (
        ("homeVideoContent", "_v80_homeVideoContent_unbounded", (), "RESOURCE_SEARCH_BUDGET"),
        ("categoryContent", "_v80_categoryContent_unbounded", ("hotmovie", "1", False, {}), "RESOURCE_FOREGROUND_BUDGET"),
        ("detailContent", "_v80_detailContent_unbounded", (["1"],), "RESOURCE_DETAIL_BUDGET"),
        ("searchContent", "_v80_searchContent_unbounded", ("query", False, "1"), "RESOURCE_SEARCH_BUDGET"),
        ("playerContent", "_v80_playerContent_unbounded", ("flag", "id", None), "FOLLOWPLAY_PLAY_BUDGET"),
        ("action", "_v80_action_unbounded", ("local",), "RESOURCE_DETAIL_BUDGET"),
    ),
)
def test_public_foreground_methods_open_one_finite_root_scope(
        monkeypatch, method_name, private_name, args, budget_name):
    module = _load_runtime()
    spider = module.Spider()
    clock = Clock()
    _install_clock(module, spider, clock)
    monkeypatch.setattr(module.time, "monotonic", clock)
    try:
        monkeypatch.setattr(
            spider,
            private_name,
            lambda *unused: spider._timeout_budget_controller.current().deadline,
        )
        deadline = getattr(spider, method_name)(*args)
        assert deadline == 100 + getattr(spider, budget_name)
        assert spider._timeout_budget_controller.snapshot()["active"] == 0
    finally:
        spider.destroy()


def test_one_foreground_deadline_is_inherited_by_all_transport_domains(monkeypatch):
    module = _load_runtime()
    spider = module.Spider()
    clock = Clock()
    _install_clock(module, spider, clock)
    monkeypatch.setattr(module.time, "monotonic", clock)
    tmdb_response = JsonResponse(payload={})
    douban_response = JsonResponse(payload={})
    spider._tmdb_session = RecordingSession([tmdb_response])
    spider._session = RecordingSession([douban_response])
    captured = {}

    def resource_unbounded(
            mode, params, deadline=None, expected_generation=None,
            timeout_operation=None):
        captured["provider"] = deadline
        return {"list": []}

    def play_unbounded(play_id, **kwargs):
        captured["playback"] = kwargs.get("deadline")
        return {"url": play_id}

    monkeypatch.setattr(spider, "_v80_resource_api_get_unbounded", resource_unbounded)
    monkeypatch.setattr(spider, "_v80_atvp_play_unbounded", play_unbounded)
    try:
        with spider._timeout_budget_controller.scope(
                "foreground", 20, expected_generation=spider._cache_generation) as parent:
            spider._request_tmdb("/test", {})
            spider._douban_client.request_json("https://m.douban.com/test")
            spider._resource_api_get("vod", {})
            spider._atvp_play("1@file")
            captured["parent"] = parent.deadline

        assert captured == {
            "provider": 120,
            "playback": 120,
            "parent": 120,
        }
        assert tmdb_response.close_calls == 1
        assert douban_response.close_calls == 1
    finally:
        spider.destroy()


def test_explicit_child_deadline_clamps_the_foreground_parent(monkeypatch):
    module = _load_runtime()
    spider = module.Spider()
    clock = Clock()
    _install_clock(module, spider, clock)
    captured = []
    monkeypatch.setattr(
        spider,
        "_v80_resource_api_get_unbounded",
        lambda mode, params, deadline=None, expected_generation=None,
        timeout_operation=None: (
            captured.append(deadline) or {"list": []}
        ),
    )
    try:
        with spider._timeout_budget_controller.scope(
                "foreground", 20, expected_generation=spider._cache_generation):
            spider._resource_api_get("vod", {}, deadline=105)
        assert captured == [105]
    finally:
        spider.destroy()


def test_lifecycle_reset_prevents_the_next_transport_phase():
    module = _load_runtime()
    spider = module.Spider()
    clock = Clock()
    _install_clock(module, spider, clock)
    session = RecordingSession([JsonResponse(payload={})])
    spider._tmdb_session = session
    operation = spider._timeout_budget_controller.scope(
        "old", 20, expected_generation=spider._cache_generation,
    )
    operation.__enter__()
    spider._cache_generation += 1
    spider._timeout_budget_controller.reset(spider._cache_generation)
    try:
        with pytest.raises(module.ReliabilityFailure) as exc_info:
            spider._request_tmdb("/must-not-run", {})
        assert exc_info.value.kind == "cancelled"
        assert session.calls == []
    finally:
        operation.__exit__(None, None, None)
        spider.destroy()


def test_active_bounded_response_closes_once_on_lifecycle_reset():
    module = _load_runtime()
    spider = module.Spider()
    response = BlockingJsonResponse()
    errors = []

    def worker():
        try:
            with spider._timeout_budget_controller.scope(
                    "foreground", 20,
                    expected_generation=spider._cache_generation):
                spider._read_bounded_json_response(response, "test", max_bytes=1024)
        except Exception as exc:
            errors.append(exc)

    thread = threading.Thread(target=worker)
    thread.start()
    assert response.started.wait(2.0)
    spider._cache_generation += 1
    spider._timeout_budget_controller.reset(spider._cache_generation)
    thread.join(2.0)
    try:
        assert not thread.is_alive()
        assert errors
        assert response.close_calls == 1
        assert spider._timeout_budget_controller.snapshot()["active"] == 0
    finally:
        spider.destroy()


def test_history_reauthentication_uses_remaining_original_budget(monkeypatch):
    module = _load_runtime()
    spider = module.Spider()
    clock = Clock()
    _install_clock(module, spider, clock)
    responses = [JsonResponse(status=401), JsonResponse(status=200)]

    def on_request(_method, _url, _kwargs):
        clock.advance(4)

    session = RecordingSession(responses, on_request=on_request)
    spider._atvp_session = session
    spider.atvp_api = "https://atvp.invalid"
    monkeypatch.setattr(spider, "_history_origin_candidates", lambda: [spider.atvp_api])

    def login(owner, origin, force=False):
        del origin, force
        clock.advance(2)
        owner._v80_history_auth_uid = 1
        return "token"

    monkeypatch.setattr(module, "_v80_history_login", login)
    try:
        with spider._timeout_budget_controller.scope(
                "history", 20, expected_generation=spider._cache_generation) as parent:
            response = module._v80_history_send_locked(
                spider, "GET", module.PLAYBACK_CHANGES_PATH,
                timeout=spider.timeout, verify=True, stream=True,
            )
            assert response.status_code == 200
            assert parent.deadline == 120

        timeouts = [call[2]["timeout"] for call in session.calls]
        assert len(timeouts) == 2
        assert 0 < timeouts[1] < timeouts[0] <= spider.timeout
    finally:
        spider.destroy()


def test_background_lanes_open_independent_finite_scopes():
    module = _load_runtime()
    spider = module.Spider()
    clock = Clock()
    _install_clock(module, spider, clock)
    executor = QueuedExecutor()
    captured = {}

    def worker(label):
        def run():
            operation = spider._timeout_budget_controller.current()
            captured[label] = (operation.operation, operation.deadline)
        return run

    try:
        for lane in ("resource_completion", "history", "route_probe"):
            assert spider._submit_background_bulkhead_task(
                lane,
                spider._cache_generation,
                worker(lane),
                lane,
                executor=executor,
            ) is True
        for queued in executor.work:
            queued()

        assert captured == {
            "resource_completion": ("background_resource_completion", 124),
            "history": ("background_history", 120),
            "route_probe": ("background_route_probe", 110),
        }
        assert spider._timeout_budget_controller.snapshot()["active"] == 0
    finally:
        spider.destroy()

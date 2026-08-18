import importlib.util
import json
import sys
import threading
import time
import types
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parent.parent
CANDIDATE_PATH = ROOT / "build" / "v80-dev" / "豆瓣TMDB追更单入口.py"


def _load_candidate():
    base_module = types.ModuleType("base")
    spider_module = types.ModuleType("base.spider")

    class BaseSpider(object):
        pass

    spider_module.Spider = BaseSpider
    sys.modules.setdefault("base", base_module)
    sys.modules.setdefault("base.spider", spider_module)
    payload = CANDIDATE_PATH.read_bytes()
    spec = importlib.util.spec_from_file_location(
        "v80_p5_playback_concurrency_candidate", CANDIDATE_PATH,
    )
    module = importlib.util.module_from_spec(spec)
    exec(compile(payload, str(CANDIDATE_PATH), "exec"), module.__dict__)
    return module


def _config(token):
    return json.dumps({
        "atvp_plugin_mode": "alist-tvbox-raw",
        "atvp_api": "http://127.0.0.1:5000",
        "atvp_token": token,
        "route_preheat": False,
    })


def _join(thread, timeout=5.0):
    thread.join(timeout)
    assert not thread.is_alive()


def test_player_rejects_unprobed_private_output_outside_backend_origin(monkeypatch):
    module = _load_candidate()
    spider = module.Spider()
    spider.init(_config("private-target"))
    target = "http://10.0.0.8/video.mp4"
    play_id = spider._build_followplay(
        target,
        {
            "media_type": "movie",
            "tmdb_id": 42,
            "source_id": "source-42",
            "title": "Playback Fixture",
            "year": 2026,
        },
        "42", 1, 1, "正片",
    )
    monkeypatch.setattr(spider, "_probe_media_output", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        spider,
        "_resolve_addresses",
        lambda *_args, **_kwargs: {module.ipaddress.ip_address("10.0.0.8")},
    )

    try:
        result = spider.playerContent("不安全线路", play_id, [])
        assert result["url"] == ""
        assert "媒体Range验证失败" in result["msg"]
    finally:
        spider.destroy()


def test_player_resume_side_effect_linearizes_before_live_init(monkeypatch):
    module = _load_candidate()
    spider = module.Spider()
    spider.init(_config("old-token"))
    old_generation = spider._cache_generation
    entered = threading.Event()
    release = threading.Event()
    injected_generations = []
    init_done = threading.Event()
    player_result = {}

    play_id = spider._build_followplay(
        "https://media.example/video.mp4",
        {
            "media_type": "movie",
            "tmdb_id": 42,
            "source_id": "source-42",
            "title": "Playback Fixture",
            "year": 2026,
        },
        "42", 1, 1, "正片",
    )
    assert play_id

    def inject_resume(output, parsed):
        entered.set()
        assert release.wait(5.0)
        injected_generations.append(spider._cache_generation)

    monkeypatch.setattr(spider, "_inject_resume", inject_resume)
    monkeypatch.setattr(
        spider,
        "_probe_media_output",
        lambda output, deadline=None, **_kwargs: {
            "output": dict(output),
            "reachable": True,
            "startup_ms": 1,
        },
    )
    monkeypatch.setattr(spider, "_record_route_quality", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(spider, "_cache_route_probe", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        spider, "_remember_successful_follow_route", lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(spider, "_register_playback_sync_window", lambda *_args: True)
    monkeypatch.setattr(spider, "_schedule_native_history_ui_refresh", lambda: True)

    def run_player():
        player_result["value"] = spider.playerContent("线路A", play_id, [])

    def run_init():
        spider.init(_config("new-token"))
        init_done.set()

    player_thread = threading.Thread(target=run_player)
    init_thread = threading.Thread(target=run_init)
    try:
        player_thread.start()
        assert entered.wait(5.0)
        init_thread.start()
        time.sleep(0.1)
        assert not init_done.is_set()
        release.set()
        _join(player_thread)
        _join(init_thread)
        assert injected_generations == [old_generation]
        assert spider._cache_generation == old_generation + 1
        assert isinstance(player_result.get("value"), dict)
    finally:
        release.set()
        _join(player_thread) if player_thread.is_alive() else None
        _join(init_thread) if init_thread.is_alive() else None
        spider.destroy()


def test_route_quality_save_rejects_stale_generation_after_live_init(monkeypatch):
    module = _load_candidate()
    spider = module.Spider()
    spider.init(_config("old-token"))
    old_generation = spider._cache_generation
    old_backend = spider._resource_capability_identity()
    entered = threading.Event()
    release = threading.Event()
    writes = []
    original_schedule = spider._schedule_route_quality_save

    monkeypatch.setattr(
        spider,
        "setCache",
        lambda key, value: writes.append((key, value)) or "success",
        raising=False,
    )

    def delayed_schedule(*args, **kwargs):
        entered.set()
        assert release.wait(5.0)
        return original_schedule(*args, **kwargs)

    monkeypatch.setattr(spider, "_schedule_route_quality_save", delayed_schedule)

    worker = threading.Thread(
        target=spider._record_route_quality,
        args=("1@old-route", True),
        kwargs={
            "expected_generation": old_generation,
            "expected_backend": old_backend,
        },
    )
    try:
        worker.start()
        assert entered.wait(5.0)
        spider.init(_config("new-token"))
        release.set()
        _join(worker)
        time.sleep(0.1)
        assert not [row for row in writes if row[0] == spider.ROUTE_QUALITY_CACHE_KEY]
        with spider._cache_lock:
            assert spider._route_quality_dirty is False
            assert spider._route_quality_saving is None
    finally:
        release.set()
        _join(worker) if worker.is_alive() else None
        spider.destroy()


def test_route_quality_lazy_load_linearizes_before_live_init(monkeypatch):
    module = _load_candidate()
    spider = module.Spider()
    spider.init(_config("old-token"))
    old_generation = spider._cache_generation
    old_backend = spider._resource_capability_identity()
    load_started = threading.Event()
    load_release = threading.Event()
    init_done = threading.Event()
    worker_done = threading.Event()
    restored_key = "a" * 64

    def get_cache(key):
        assert key == spider.ROUTE_QUALITY_CACHE_KEY
        load_started.set()
        assert load_release.wait(5.0)
        return {
            "version": spider.ROUTE_QUALITY_VERSION,
            "entries": {
                restored_key: {
                    "successes": 1,
                    "failures": 0,
                    "updatedAt": int(time.time()),
                },
            },
        }

    monkeypatch.setattr(spider, "getCache", get_cache, raising=False)
    monkeypatch.setattr(spider, "setCache", lambda *_args: "success", raising=False)

    def run_record():
        spider._record_route_quality(
            "1@old-route", True,
            expected_generation=old_generation,
            expected_backend=old_backend,
        )
        worker_done.set()

    def run_init():
        spider.init(_config("new-token"))
        init_done.set()

    worker = threading.Thread(target=run_record)
    init_thread = threading.Thread(target=run_init)
    try:
        worker.start()
        assert load_started.wait(5.0)
        init_thread.start()
        time.sleep(0.1)
        assert not init_done.is_set()
        load_release.set()
        _join(worker)
        _join(init_thread)
        assert worker_done.is_set()
        with spider._cache_lock:
            assert spider._route_quality_history == {}
            assert spider._route_quality_loaded is False
            assert spider._route_quality_dirty is False
            assert spider._route_quality_saving is None
    finally:
        load_release.set()
        _join(worker) if worker.is_alive() else None
        _join(init_thread) if init_thread.is_alive() else None
        spider.destroy()


def test_media_probe_does_not_submit_to_new_owner_after_live_init(monkeypatch):
    module = _load_candidate()
    spider = module.Spider()
    spider.init(_config("old-token"))
    old_generation = spider._cache_generation
    entered = threading.Event()
    release = threading.Event()
    new_owner_submits = []
    result = {}

    def resolved_target(value, deadline=None, **_kwargs):
        entered.set()
        assert release.wait(5.0)
        return urlparse(value), (module.ipaddress.ip_address("8.8.8.8"),)

    monkeypatch.setattr(spider, "_resolved_media_target", resolved_target)

    def run_probe():
        try:
            with spider._timeout_budget_controller.scope(
                    "player", 10, expected_generation=old_generation):
                result["value"] = spider._probe_media_output(
                    {
                        "parse": 0,
                        "jx": 0,
                        "url": "https://media.example/video.mp4",
                        "header": {},
                    },
                    deadline=time.monotonic() + 5,
                )
        except Exception as exc:
            result["error"] = type(exc).__name__

    probe_thread = threading.Thread(target=run_probe)
    try:
        probe_thread.start()
        assert entered.wait(5.0)
        spider.init(_config("new-token"))
        new_executor = spider._media_probe_executor
        original_submit = new_executor.submit

        def counted_submit(*args, **kwargs):
            new_owner_submits.append(1)
            return original_submit(*args, **kwargs)

        monkeypatch.setattr(new_executor, "submit", counted_submit)
        release.set()
        _join(probe_thread)
        assert new_owner_submits == []
        assert result.get("error") in {"ReliabilityFailure", None}
    finally:
        release.set()
        _join(probe_thread) if probe_thread.is_alive() else None
        spider.destroy()


def test_source_switch_does_not_invalidate_new_generation_probe(monkeypatch):
    module = _load_candidate()
    spider = module.Spider()
    spider.init(_config("old-token"))
    target = "https://media.example/video.mp4"
    resource_id = "42"
    play_id = spider._build_followplay(
        target,
        {
            "media_type": "movie",
            "tmdb_id": 42,
            "source_id": "source-42",
            "title": "Playback Fixture",
            "year": 2026,
        },
        resource_id, 1, 1, "正片",
    )
    probe = {
        "output": {"parse": 0, "jx": 0, "url": target, "header": {}},
        "reachable": True,
        "checked_at": time.time(),
        "startup_ms": 1,
    }
    entered = threading.Event()
    release = threading.Event()
    player_result = {}

    monkeypatch.setattr(
        spider, "_probe_media_output", lambda output, deadline=None, **_kwargs: dict(probe),
    )
    monkeypatch.setattr(spider, "_inject_resume", lambda *_args: None)
    monkeypatch.setattr(spider, "_record_route_quality", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        spider, "_remember_successful_follow_route", lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(spider, "_register_playback_sync_window", lambda *_args: True)
    monkeypatch.setattr(spider, "_schedule_native_history_ui_refresh", lambda: True)

    first = spider.playerContent("线路A", play_id, [])
    assert first.get("url") == target
    original_invalidate = spider._invalidate_route_probe

    def delayed_invalidate(*args, **kwargs):
        entered.set()
        assert release.wait(5.0)
        return original_invalidate(*args, **kwargs)

    monkeypatch.setattr(spider, "_invalidate_route_probe", delayed_invalidate)

    def run_player():
        player_result["value"] = spider.playerContent("线路B", play_id, [])

    player_thread = threading.Thread(target=run_player)
    try:
        player_thread.start()
        assert entered.wait(5.0)
        spider.init(_config("new-token"))
        generation = spider._cache_generation
        backend = spider._resource_capability_identity()
        spider._cache_route_probe(
            target, probe, resource_id=resource_id,
            expected_generation=generation, expected_backend=backend,
        )
        assert spider._route_probe_snapshot(target, resource_id) is not None
        release.set()
        _join(player_thread)
        assert spider._route_probe_snapshot(target, resource_id) is not None
        assert isinstance(player_result.get("value"), dict)
    finally:
        release.set()
        _join(player_thread) if player_thread.is_alive() else None
        spider.destroy()


def test_playback_sync_registration_linearizes_before_live_init(monkeypatch):
    module = _load_candidate()
    spider = module.Spider()
    spider.init(_config("old-token"))
    old_generation = spider._cache_generation
    entered = threading.Event()
    release = threading.Event()
    registration_generations = []
    init_done = threading.Event()
    player_result = {}
    play_id = spider._build_followplay(
        "https://media.example/video.mp4",
        {
            "media_type": "movie",
            "tmdb_id": 42,
            "source_id": "source-42",
            "title": "Playback Fixture",
            "year": 2026,
        },
        "42", 1, 1, "正片",
    )

    monkeypatch.setattr(
        spider,
        "_probe_media_output",
        lambda output, deadline=None, **_kwargs: {
            "output": dict(output), "reachable": True, "startup_ms": 1,
        },
    )
    monkeypatch.setattr(spider, "_inject_resume", lambda *_args: None)
    monkeypatch.setattr(spider, "_record_route_quality", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(spider, "_cache_route_probe", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        spider, "_remember_successful_follow_route", lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(spider, "_schedule_native_history_ui_refresh", lambda: True)

    def register(_effective):
        entered.set()
        assert release.wait(5.0)
        registration_generations.append(spider._cache_generation)
        return True

    monkeypatch.setattr(spider, "_register_playback_sync_window", register)

    def run_player():
        player_result["value"] = spider.playerContent("线路A", play_id, [])

    def run_init():
        spider.init(_config("new-token"))
        init_done.set()

    player_thread = threading.Thread(target=run_player)
    init_thread = threading.Thread(target=run_init)
    try:
        player_thread.start()
        assert entered.wait(5.0)
        init_thread.start()
        time.sleep(0.1)
        assert not init_done.is_set()
        release.set()
        _join(player_thread)
        _join(init_thread)
        assert registration_generations == [old_generation]
        assert isinstance(player_result.get("value"), dict)
    finally:
        release.set()
        _join(player_thread) if player_thread.is_alive() else None
        _join(init_thread) if init_thread.is_alive() else None
        spider.destroy()

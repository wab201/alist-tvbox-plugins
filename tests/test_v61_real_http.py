# -*- coding: utf-8 -*-
"""Real loopback HTTP checks for V61 transport and signed-play recovery."""

import importlib.util
import json
import sys
import threading
import types
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import requests

base_module = types.ModuleType("base")
spider_module = types.ModuleType("base.spider")


class BaseSpider(object):
    pass


spider_module.Spider = BaseSpider
sys.modules.setdefault("base", base_module)
sys.modules.setdefault("base.spider", spider_module)

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "py" / "豆瓣TMDB追更单入口_v61.py"
SPEC = importlib.util.spec_from_file_location("douban_tmdb_follow_v61_real", str(SOURCE))
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class FixtureState(object):
    def __init__(self):
        self.lock = threading.Lock()
        self.play_calls = 0
        self.history = []
        self.posted = []
        self.delete_by_key_calls = 0
        self.delete_by_id_calls = 0


class Handler(BaseHTTPRequestHandler):
    state = None

    def log_message(self, *_args):
        return

    def _json(self, status, value):
        body = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        if self.path == "/api/accounts/login":
            self._json(200, {"authorities": [{"authority": "USER"}], "token": "fixture-auth"})
            return
        if self.path == "/history/sub-token":
            value = json.loads(raw.decode("utf-8") or "[]")
            with self.state.lock:
                self.state.posted.extend(value if isinstance(value, list) else [])
                self.state.history = list(self.state.posted)
            self._json(200, {"ok": True})
            return
        if self.path.startswith("/play/sub-token"):
            with self.state.lock:
                self.state.play_calls += 1
                suffix = "expired" if self.state.play_calls == 1 else "fresh"
            self._json(200, {"parse": 0, "url": "http://127.0.0.1:%d/media-%s.mp4" % (self.server.server_port, suffix), "header": {}})
            return
        self._json(404, {"error": "not found"})

    def do_GET(self):
        if self.path.startswith("/play/sub-token"):
            with self.state.lock:
                self.state.play_calls += 1
                suffix = "expired" if self.state.play_calls == 1 else "fresh"
            self._json(200, {"parse": 0, "url": "http://127.0.0.1:%d/media-%s.mp4" % (self.server.server_port, suffix), "header": {}})
            return
        if self.path.startswith("/history/sub-token") and "key=" in self.path:
            with self.state.lock:
                row = dict(self.state.history[0]) if self.state.history else {}
            row.setdefault("id", 37)
            self._json(200, row)
            return
        if self.path == "/history/sub-token":
            with self.state.lock:
                rows = list(self.state.history)
            self._json(200, rows)
            return
        if self.path == "/api/history/37":
            with self.state.lock:
                row = dict(self.state.history[0]) if self.state.history else {}
            row.setdefault("id", 37)
            self._json(200, row)
            return
        if self.path.startswith("/media-"):
            if self.path.startswith("/media-expired"):
                self.send_response(404)
                self.end_headers()
                return
            body = b"video-fixture"
            self.send_response(206 if self.headers.get("Range") else 200)
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self._json(404, {"error": "not found"})

    def do_DELETE(self):
        if self.path.startswith("/history/sub-token"):
            with self.state.lock:
                self.state.delete_by_key_calls += 1
                # Simulate the known server bug: key delete fails.
            self._json(500, {"error": "server key delete bug"})
            return
        if self.path.startswith("/api/history/"):
            with self.state.lock:
                self.state.delete_by_id_calls += 1
                self.state.history = []
            self._json(200, {"ok": True})
            return
        self._json(404, {"error": "not found"})


class V61RealHttpTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.state = FixtureState()
        Handler.state = cls.state
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.origin = "http://127.0.0.1:%d" % cls.server.server_port

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def setUp(self):
        with self.state.lock:
            self.state.play_calls = 0
            self.state.history = []
            self.state.posted = []
            self.state.delete_by_key_calls = 0
            self.state.delete_by_id_calls = 0
        self.spider = MODULE.Spider()
        self.spider._alist_tvbox_plugin = True
        self.spider.atvp_api = self.origin
        self.spider.atvp_token = "sub-token"
        self.spider.history_api = self.origin
        self.spider.history_username = "fixture-user"
        self.spider.history_password = "fixture-pass"
        self.spider.timeout = 3
        self.spider.verify_tls = False
        self.spider._atvp_session = requests.Session()
        self.spider._atvp_session.trust_env = False

    def tearDown(self):
        self.spider.destroy()

    def test_history_round_trip_over_real_http(self):
        row = {"key": "fixture@@@vod@@@1", "vodName": "测试剧集", "position": 1234}
        response = self.spider._atvp_history_request("POST", json=[row])
        self.assertEqual(response.status_code, 200)
        response.close()
        response = self.spider._atvp_history_request("GET")
        try:
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()[0]["key"], row["key"])
        finally:
            response.close()

    def test_play_reissues_after_expired_signed_output(self):
        item = {"media_type": "tv", "tmdb_id": 101, "title": "测试剧集"}
        play_id = self.spider._build_followplay("1@fixture-episode", item, "fixture-resource", 1, 1, "S01E01")
        # The safety gate intentionally rejects loopback media origins; keep
        # the transport real while allowing this local fixture through it.
        self.spider._safe_atvp_play_output = lambda output: True
        result = self.spider.playerContent("线路A", play_id, [])
        self.assertTrue(result.get("url", "").endswith("media-fresh.mp4"))
        with self.state.lock:
            self.assertEqual(self.state.play_calls, 2)

    def test_delete_falls_back_to_authenticated_management_endpoint(self):
        with self.state.lock:
            self.state.history = [{"id": 37, "key": "fixture@@@vod@@@1"}]
        self.spider._atvp_history_delete("fixture@@@vod@@@1")
        with self.state.lock:
            self.assertEqual(self.state.delete_by_key_calls, 1)
            self.assertEqual(self.state.delete_by_id_calls, 1)


if __name__ == "__main__":
    unittest.main()

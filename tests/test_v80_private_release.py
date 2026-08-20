import ast
import hashlib
import importlib.util
import json
import sys
import types
from pathlib import Path
from urllib.parse import urljoin
from unittest.mock import Mock

import pytest


ROOT = Path(__file__).resolve().parent.parent
BUILDER_PATH = ROOT / "tools" / "build_v80_private_release.py"


def _load():
    spec = importlib.util.spec_from_file_location("v80_private_release", BUILDER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BUILDER = _load()


def test_private_source_is_canonical_v80_and_is_pinned():
    result = BUILDER.build_private_release()
    source = result["source_bytes"]
    assert source == BUILDER.CANONICAL_SOURCE.read_bytes()
    assert len(source) == BUILDER.SOURCE_SIZE
    assert hashlib.sha256(source).hexdigest().upper() == BUILDER.SOURCE_SHA256


def test_private_filter_owner_is_pinned_and_ast_identical_to_canonical():
    result = BUILDER.build_private_release()
    owner = result["source_manifest"]["source_owners"]["filter_normalization"]

    assert owner["path"] == "src/douban_tmdb_follow_v80/parts/02_filter.pyinc"
    assert owner["methods"] == [
        "Filter._normalize_title",
        "Spider._standardize_resource_name",
    ]
    assert len(result["filter_owner"]) == owner["bytes"]
    assert hashlib.sha256(result["filter_owner"]).hexdigest().upper() == owner["sha256"]


def test_private_filter_owner_semantic_drift_is_rejected(monkeypatch):
    source_manifest = BUILDER._read_source_manifest()
    canonical = BUILDER.CANONICAL_SOURCE.read_bytes()
    drifted = BUILDER.FILTER_OWNER.read_bytes().replace(
        b'return text.strip()\n', b'return text\n', 1,
    )
    monkeypatch.setattr(BUILDER, "_read_pinned", lambda *_args, **_kwargs: drifted)

    with pytest.raises(BUILDER.PrivateReleaseError, match="differs from canonical"):
        BUILDER._verify_filter_owner(canonical, source_manifest)


def test_private_builder_has_no_v70_parts_candidate_or_overlay_inputs():
    builder_source = BUILDER_PATH.read_text(encoding="utf-8")
    forbidden = (
        "baseline_v70",
        "douban_tmdb_follow_single/parts",
        "build/v80-dev",
        "build_v80_private_category_refresh_overlay",
        "PUBLIC_V70",
        "PUBLIC_INDEX",
    )

    assert all(token not in builder_source for token in forbidden)


def test_private_owners_are_based_on_frozen_v80_baseline():
    result = BUILDER.build_private_release()
    assert result["source_manifest"]["baseline"] == {
        "path": "src/douban_tmdb_follow_v80/parts/00_runtime_v80.pyinc",
        "bytes": 872002,
        "sha256": "B6319D2925AF60F5068DC84C2AA6B1AF753666CA4DA294533EB39736B5004CD7",
    }
    for owner_bytes in result["owner_bytes"].values():
        owner = json.loads(owner_bytes.decode("utf-8"))
        assert owner["base"] == "parts/00_runtime_v80.pyinc"
    builder_source = BUILDER_PATH.read_text(encoding="utf-8")
    assert "00_runtime_v83.pyinc" not in builder_source


def test_private_index_is_independent_and_resolves_relative_to_itself():
    result = BUILDER.build_private_release()
    index = json.loads(result["index_bytes"].decode("utf-8"))

    assert index == [{
        "id": BUILDER.PRIVATE_ID,
        "file": "staging/豆瓣TMDB追更单入口.py",
        "version": BUILDER.PRIVATE_VERSION,
        "valid": True,
    }]
    assert urljoin(
        "https://example.invalid/private/v80/spiders_v2.json",
        index[0]["file"],
    ) == "https://example.invalid/private/v80/staging/豆瓣TMDB追更单入口.py"


def test_private_manifest_binds_only_independent_v80_and_upstream_targets():
    manifest = BUILDER.build_private_release()["manifest"]

    assert manifest["schema"] == "v80-private-release/3"
    assert manifest["contract"] == "independent_v80_modular"
    assert manifest["id"] == "douban_tmdb_follow_single_v80_private"
    assert manifest["version"] == 90
    assert manifest["build"]["canonical_is_generated"] is True
    assert manifest["build"]["canonical_is_source_input"] is False
    assert manifest["build"]["owner_order"] == list(BUILDER.OWNER_KEYS)
    assert manifest["build"]["baseline"] == BUILDER.build_private_release()["source_manifest"]["baseline"]
    lineage = manifest["release_lineage"]
    assert lineage == BUILDER.build_private_release()["source_manifest"]["release_lineage"]
    assert lineage["strategy"] == "frozen_v80_baseline_plus_owner_deltas"
    assert lineage["policy"] == {
        "historical_packages_immutable": True,
        "baseline_writable": False,
        "owner_files_are_development_source": True,
        "canonical_and_staging_are_generated": True,
    }
    assert [item["version"] for item in lineage["versions"]] == [80, 81, 82, 83, 84, 85, 86, 87, 88, 89, 90]
    assert lineage["versions"][0]["sha256"] == BUILDER.build_private_release()[
        "source_manifest"
    ]["baseline"]["sha256"]
    assert lineage["versions"][-1]["generated_from"]["owners"] == list(BUILDER.OWNER_KEYS)
    assert manifest["canonical_source"] == {
        "path": "src/douban_tmdb_follow_v80/豆瓣TMDB追更单入口.py",
        "manifest": "src/douban_tmdb_follow_v80/release.json",
        "bytes": BUILDER.SOURCE_SIZE,
        "sha256": BUILDER.SOURCE_SHA256,
    }
    assert manifest["staged_source"]["sha256"] == BUILDER.SOURCE_SHA256
    assert manifest["staged_source"]["byte_identical_to_canonical"] is True
    assert manifest["compatibility_targets"] == BUILDER.build_private_release()[
        "source_manifest"
    ]["compatibility_targets"]
    assert manifest["source_owners"] == BUILDER.build_private_release()[
        "source_manifest"
    ]["source_owners"]
    assert manifest["deployment"] == {
        "scope": "build_time_initial_state",
        "server": "not_executed_by_builder",
        "mumu": "not_executed_by_builder",
        "runtime_evidence": "tracked_outside_manifest",
    }
    assert "v70" not in json.dumps(manifest, ensure_ascii=False).lower()


def test_canonical_v80_has_valid_ast_and_no_duplicate_spider_or_filter_methods():
    source = BUILDER.build_private_release()["source_bytes"].decode("utf-8")
    tree = ast.parse(source, filename=str(BUILDER.CANONICAL_SOURCE))

    for node in tree.body:
        if not isinstance(node, ast.ClassDef) or node.name not in ("Spider", "Filter"):
            continue
        names = [
            child.name for child in node.body
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]
        duplicates = sorted({name for name in names if names.count(name) > 1})
        assert duplicates == []


def test_checked_private_release_matches_the_fixed_builder():
    result = BUILDER.check_private_release()

    assert result["source_path"].read_bytes() == result["source_bytes"]
    assert result["index_path"].read_bytes() == result["index_bytes"]
    assert result["manifest_path"].read_bytes() == result["manifest_bytes"]
    assert result["canonical_path"].read_bytes() == result["canonical_bytes"]


def test_modular_builder_rejects_owner_anchor_drift(monkeypatch):
    source_manifest = BUILDER._read_source_manifest()
    owner = source_manifest["source_owners"]["playlist_output"]
    original = BUILDER.ROOT / owner["path"]
    drifted = json.loads(original.read_text(encoding="utf-8"))
    drifted["replacements"][0]["before"] += "# drift"
    monkeypatch.setattr(BUILDER, "_read_pinned", lambda path, *_args, **_kwargs: (
        (json.dumps(drifted, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        if path == original else path.read_bytes()
    ))

    with pytest.raises(BUILDER.PrivateReleaseError, match="fingerprint drifted|source owner"):
        BUILDER.build_private_release()


def _load_private_spider(source, tmp_path, monkeypatch):
    base_module = types.ModuleType("base")
    spider_module = types.ModuleType("base.spider")

    class BaseSpider(object):
        pass

    spider_module.Spider = BaseSpider
    monkeypatch.setitem(sys.modules, "base", base_module)
    monkeypatch.setitem(sys.modules, "base.spider", spider_module)
    source_path = tmp_path / "private_v80.py"
    source_path.write_bytes(source)
    spec = importlib.util.spec_from_file_location("private_v80_refresh_test", source_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_private_category_refresh_suppresses_only_recursive_background_sources(
    tmp_path, monkeypatch,
):
    module = _load_private_spider(
        BUILDER.build_private_release()["source_bytes"], tmp_path, monkeypatch,
    )
    spider = module.Spider()
    queue_refresh = Mock(return_value=False)
    start_thread = Mock(return_value=None)
    spider._queue_instantiated_follow_refresh = queue_refresh
    spider._tasks.start_thread = start_thread
    spider._follow_native_category_refresh_at = 100.0
    monkeypatch.setattr(module.time, "monotonic", lambda: 101.0)

    try:
        assert spider._refresh_follow_categories("history-snapshot") is False
        assert spider._refresh_follow_categories("follow-page") is False
        queue_refresh.assert_not_called()
        start_thread.assert_not_called()

        assert spider._refresh_follow_categories() is True
        queue_refresh.assert_called_once()
        start_thread.assert_called_once()
    finally:
        spider.destroy()


def test_private_category_refresh_marks_native_refresh_before_loopback(
    tmp_path, monkeypatch,
):
    module = _load_private_spider(
        BUILDER.build_private_release()["source_bytes"], tmp_path, monkeypatch,
    )
    spider = module.Spider()
    native_refresh = Mock(return_value=True)
    spider._refresh_native_view = native_refresh
    monkeypatch.setattr(module.time, "monotonic", lambda: 200.0)

    try:
        assert spider._refresh_native_category() is True
        assert spider._follow_native_category_refresh_at == 200.0
        native_refresh.assert_called_once_with("category")
    finally:
        spider.destroy()


@pytest.mark.parametrize("uid_key, uid", (("userId", 7), ("id", 8)))
def test_private_history_login_accepts_current_and_legacy_user_id_fields(
    uid_key, uid, tmp_path, monkeypatch,
):
    module = _load_private_spider(
        BUILDER.build_private_release()["source_bytes"], tmp_path, monkeypatch,
    )

    class Response:
        status_code = 200

        def close(self):
            pass

    class Session:
        def __init__(self):
            self.headers = {"Authorization": "stale"}

        def post(self, _url, **_kwargs):
            return Response()

    owner = types.SimpleNamespace(
        _atvp_session=Session(),
        _v80_history_auth_token="",
        _v80_history_auth_origin="",
        _v80_history_auth_uid=0,
        _v80_history_auth_username="",
        _v80_history_auth_generation=-1,
        _cache_generation=0,
        _history_selected_origin="",
        _history_auth_token="",
        history_username="user",
        history_password="pass",
        timeout=8,
        verify_tls=True,
        HISTORY_RESPONSE_MAX_BYTES=1024,
        _history_write_enabled=lambda: True,
        _read_bounded_json_response=lambda *_args, **_kwargs: {
            uid_key: uid,
            "token": "token",
            "authorities": [{"authority": "USER"}],
        },
    )
    operation = types.SimpleNamespace(request_timeout=lambda timeout: timeout)

    assert module._v80_history_login_unbounded(
        owner, "https://server", _v80_timeout_operation=operation,
    ) == "token"
    assert owner._v80_history_auth_uid == uid


@pytest.mark.parametrize("vod_cid", (0, None))
def test_private_history_active_cid_falls_back_to_persisted_vod_config(
    vod_cid, tmp_path, monkeypatch,
):
    module = _load_private_spider(
        BUILDER.build_private_release()["source_bytes"], tmp_path, monkeypatch,
    )

    class VodConfig:
        @staticmethod
        def getCid():
            if vod_cid is None:
                raise AttributeError("getCid unavailable")
            return vod_cid

    class Config:
        @staticmethod
        def vod():
            return types.SimpleNamespace(getId=lambda: 37)

    java_module = types.ModuleType("java")
    java_module.jclass = lambda name: {
        "com.fongmi.android.tv.api.config.VodConfig": VodConfig,
        "com.fongmi.android.tv.bean.Config": Config,
    }[name]
    monkeypatch.setitem(sys.modules, "java", java_module)

    assert module.v80_history_active_cid(types.SimpleNamespace()) == 37


def test_private_history_active_cid_prefers_live_vod_config(
    tmp_path, monkeypatch,
):
    module = _load_private_spider(
        BUILDER.build_private_release()["source_bytes"], tmp_path, monkeypatch,
    )

    class VodConfig:
        @staticmethod
        def getCid():
            return 41

    class Config:
        @staticmethod
        def vod():
            raise AssertionError("persisted config fallback should not run")

    java_module = types.ModuleType("java")
    java_module.jclass = lambda name: {
        "com.fongmi.android.tv.api.config.VodConfig": VodConfig,
        "com.fongmi.android.tv.bean.Config": Config,
    }[name]
    monkeypatch.setitem(sys.modules, "java", java_module)

    assert module.v80_history_active_cid(types.SimpleNamespace()) == 41


def test_private_history_cursor_commit_uses_native_sync_completion():
    source = BUILDER.build_private_release()["source_bytes"].decode("utf-8")

    assert source.count(
        "v80_history_commit(self, imported=imported, expected=0)"
    ) == 1
    assert "expected=len(import_rows)" not in source


@pytest.mark.parametrize(
    "tampered_path_key",
    ("source_path", "index_path", "manifest_path"),
)
def test_checked_private_release_rejects_tampered_artifact(
    tmp_path, monkeypatch, tampered_path_key,
):
    result = BUILDER.build_private_release()
    for path_key, bytes_key in (
        ("source_path", "source_bytes"),
        ("index_path", "index_bytes"),
        ("manifest_path", "manifest_bytes"),
    ):
        target = tmp_path / Path(result[path_key]).name
        target.write_bytes(result[bytes_key])
        result[path_key] = target
    result[tampered_path_key].write_bytes(
        result[tampered_path_key].read_bytes() + b"tampered\n"
    )
    monkeypatch.setattr(BUILDER, "build_private_release", lambda: result)

    with pytest.raises(BUILDER.PrivateReleaseError, match="staged artifact differs"):
        BUILDER.check_private_release()

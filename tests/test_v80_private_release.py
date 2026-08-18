import hashlib
import importlib.util
import json
from pathlib import Path
from urllib.parse import urljoin

import pytest


ROOT = Path(__file__).resolve().parent.parent
BUILDER_PATH = ROOT / "tools" / "build_v80_private_release.py"


def _load():
    spec = importlib.util.spec_from_file_location("v80_private_release", BUILDER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BUILDER = _load()


def test_private_source_changes_only_fixed_metadata_and_is_pinned():
    result = BUILDER.build_private_release()
    source = result["source_bytes"]
    restored = source.replace(
        "//@name:豆瓣TMDB追更助手（V80私有）".encode("utf-8"),
        "//@name:豆瓣TMDB追更助手（AList-TVBox专用）".encode("utf-8"),
    ).replace(
        b"//@id:douban_tmdb_follow_single_v80_private",
        b"//@id:douban_tmdb_follow_single",
    ).replace(b"//@version:80", b"//@version:70")

    assert restored == BUILDER._candidate_path().read_bytes()
    assert len(source) == BUILDER.PRIVATE_SOURCE_SIZE
    assert hashlib.sha256(source).hexdigest().upper() == BUILDER.PRIVATE_SOURCE_SHA256


def test_private_index_is_independent_and_resolves_relative_to_itself():
    result = BUILDER.build_private_release()
    index = json.loads(result["index_bytes"].decode("utf-8"))

    assert index == [{
        "id": BUILDER.PRIVATE_ID,
        "file": "staging/豆瓣TMDB追更单入口.py",
        "version": 80,
        "valid": True,
    }]
    assert urljoin(
        "https://example.invalid/private/v80/spiders_v2.json",
        index[0]["file"],
    ) == "https://example.invalid/private/v80/staging/豆瓣TMDB追更单入口.py"
    assert json.loads(BUILDER.PUBLIC_INDEX.read_text(encoding="utf-8"))[0] == {
        "id": "douban_tmdb_follow_single",
        "file": "py/豆瓣TMDB追更单入口.py",
        "version": 70,
        "valid": True,
    }


def test_private_manifest_binds_candidate_switch_evidence_and_public_locks():
    manifest = BUILDER.build_private_release()["manifest"]

    assert manifest["id"] == "douban_tmdb_follow_single_v80_private"
    assert manifest["version"] == 80
    assert manifest["source_candidate"]["sha256"] == BUILDER.CANDIDATE_SHA256
    assert manifest["staged_source"]["sha256"] == BUILDER.PRIVATE_SOURCE_SHA256
    assert manifest["controlled_switch"] == {
        "default_enabled": False,
        "required_extend": {
            "atvp_plugin_mode": "alist-tvbox-raw",
            "v80_resource_layered_output": True,
        },
    }
    assert manifest["evidence"]["sha256"] == BUILDER.EVIDENCE_SHA256
    assert manifest["public_v70"]["modified"] is False
    assert manifest["public_index"]["modified"] is False
    assert manifest["deployment"]["public_v70_rollback"] == "not_applicable"


def test_checked_private_release_matches_the_fixed_builder():
    result = BUILDER.check_private_release()

    assert result["source_path"].read_bytes() == result["source_bytes"]
    assert result["index_path"].read_bytes() == result["index_bytes"]
    assert result["manifest_path"].read_bytes() == result["manifest_bytes"]


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

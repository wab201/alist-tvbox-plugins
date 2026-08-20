import ast
import hashlib
import importlib.util
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
SPEC = importlib.util.spec_from_file_location(
    "build_v90_public_release",
    ROOT / "tools" / "build_v90_public_release.py",
)
BUILDER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILDER)


def test_public_v90_is_generated_from_modular_canonical():
    result = BUILDER.build_public_release()
    source = result["source_bytes"]
    assert len(source) == BUILDER.PUBLIC_SIZE
    assert hashlib.sha256(source).hexdigest().upper() == BUILDER.PUBLIC_SHA256
    text = source.decode("utf-8")
    assert "//@id:douban_tmdb_follow_single\n" in text
    assert "//@version:90\n" in text
    assert "V80.1私有" not in text
    ast.parse(text)


def test_public_v90_index_and_manifest_contracts():
    result = BUILDER.build_public_release()
    index = json.loads(result["index_bytes"].decode("utf-8"))
    assert index[0] == {
        "id": "douban_tmdb_follow_single",
        "file": "py/豆瓣TMDB追更单入口.py",
        "version": 90,
        "valid": True,
    }
    manifest = result["manifest_payload"]
    assert manifest["architecture"]["development"] == "modular owners"
    assert manifest["architecture"]["runtime"] == "single generated Python file"
    assert manifest["built_from"]["sha256"] == (
        BUILDER.modular_builder.SOURCE_SHA256
    )
    assert manifest["public_source"]["sha256"] == BUILDER.PUBLIC_SHA256


def test_checked_in_public_v90_matches_generator():
    result = BUILDER.check_public_release()
    assert result["source_path"].read_bytes() == result["source_bytes"]

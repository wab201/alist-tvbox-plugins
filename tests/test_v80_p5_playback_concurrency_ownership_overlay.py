import hashlib
import importlib.util
from functools import lru_cache
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parent.parent
BUILD_PATH = ROOT / "tools" / "build_follow_plugin.py"
OVERLAY_PATH = ROOT / "tools" / "build_v80_playback_concurrency_ownership_overlay.py"
MANIFEST_PATH = ROOT / "src" / "douban_tmdb_follow_single" / "release.json"
PUBLIC_V70 = ROOT / "py" / "豆瓣TMDB追更单入口.py"
P5_5D_SIZE = 857478
P5_5D_SHA256 = "1BC3509C37DCB550F39A4324A2A17B4834029FFD6096C4366C46F05247B16DBA"
FINAL_SIZE = 859733
FINAL_SHA256 = "DFCDAEFBAEF0C6F2389E721EB377F1FA0DB34E889ED5D5E01E98B4A32DB308C0"
INSERTIONS = (
    "source-switch-generation",
    "source-switch-invalidation-owner",
    "route-quality-save-owner",
    "route-quality-repeat-generation",
    "route-quality-record-generation",
    "player-resume-generation",
    "player-finalize-generation",
)


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BUILD = _load("v80_playback_concurrency_build", BUILD_PATH)
OVERLAY = _load("v80_playback_concurrency_overlay", OVERLAY_PATH)


@lru_cache(maxsize=1)
def _p5_5d_source():
    manifest = BUILD.load_manifest(MANIFEST_PATH)
    manifest["expected_size"] = P5_5D_SIZE
    manifest["expected_sha256"] = P5_5D_SHA256
    original_playback = BUILD._apply_playback_concurrency_ownership_overlay
    original_history = BUILD._apply_history_concurrency_ownership_overlay
    BUILD._apply_playback_concurrency_ownership_overlay = lambda source: (source, None)
    BUILD._apply_history_concurrency_ownership_overlay = lambda source: (source, None)
    try:
        source = BUILD._assemble(
            manifest, BUILD._find_repo_root(manifest["manifest_path"]),
        )[0]
    finally:
        BUILD._apply_history_concurrency_ownership_overlay = original_history
        BUILD._apply_playback_concurrency_ownership_overlay = original_playback
    assert len(source) == P5_5D_SIZE
    assert hashlib.sha256(source).hexdigest().upper() == P5_5D_SHA256
    return source


def test_playback_overlay_is_deterministic_and_pinned_to_p5_5d():
    first = OVERLAY.apply_playback_concurrency_ownership_overlay(_p5_5d_source())
    second = OVERLAY.apply_playback_concurrency_ownership_overlay(_p5_5d_source())
    assert first == second
    assert first["input_size"] == P5_5D_SIZE
    assert first["input_sha256"] == P5_5D_SHA256
    assert first["size"] == FINAL_SIZE
    assert first["sha256"] == FINAL_SHA256
    assert first["alias_zh"] == "播放并发所有权覆盖层"
    assert first["insertions"] == INSERTIONS


@pytest.mark.parametrize("label,anchor,_replacement", OVERLAY.INSERTIONS)
def test_playback_overlay_rejects_missing_or_duplicate_anchor(label, anchor, _replacement):
    with pytest.raises(
        OVERLAY.PlaybackConcurrencyOwnershipOverlayError,
        match="playback concurrency anchor %s must appear once" % label,
    ):
        OVERLAY._replace_once("", anchor, _replacement, label)
    with pytest.raises(
        OVERLAY.PlaybackConcurrencyOwnershipOverlayError,
        match="playback concurrency anchor %s must appear once" % label,
    ):
        OVERLAY._replace_once(anchor + anchor, anchor, _replacement, label)


def test_playback_overlay_rejects_unpinned_or_invalid_input():
    with pytest.raises(
        OVERLAY.PlaybackConcurrencyOwnershipOverlayError,
        match="does not match the P5-5D candidate",
    ):
        OVERLAY.apply_playback_concurrency_ownership_overlay(_p5_5d_source() + b"\n")
    with pytest.raises(
        OVERLAY.PlaybackConcurrencyOwnershipOverlayError,
        match="not valid UTF-8 bytes",
    ):
        OVERLAY.apply_playback_concurrency_ownership_overlay(b"\xff")


def test_playback_overlay_does_not_touch_public_v70():
    before = PUBLIC_V70.read_bytes()
    OVERLAY.apply_playback_concurrency_ownership_overlay(_p5_5d_source())
    after = PUBLIC_V70.read_bytes()
    assert len(after) == len(before) == 616699
    assert hashlib.sha256(after).hexdigest().upper() == (
        "233C73CAE1048210B34872D4A10EA6023662300F70A8657DB82EA65C342182D4"
    )
    assert after == before

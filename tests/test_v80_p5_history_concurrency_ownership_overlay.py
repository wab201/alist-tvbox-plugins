import hashlib
import importlib.util
from functools import lru_cache
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parent.parent
BUILD_PATH = ROOT / "tools" / "build_follow_plugin.py"
OVERLAY_PATH = ROOT / "tools" / "build_v80_history_concurrency_ownership_overlay.py"
MANIFEST_PATH = ROOT / "src" / "douban_tmdb_follow_single" / "release.json"
PUBLIC_V70 = ROOT / "py" / "豆瓣TMDB追更单入口.py"
P5_5E_SIZE = 859733
P5_5E_SHA256 = "DFCDAEFBAEF0C6F2389E721EB377F1FA0DB34E889ED5D5E01E98B4A32DB308C0"
FINAL_SIZE = 862377
FINAL_SHA256 = "C1ACAB802121E3F69ADEA0EBF1AB271C14015124AA28D2D1F8F58F97C8481B7D"
INSERTIONS = (
    "history-job-owner-state",
    "live-init-history-job-reset",
    "destroy-history-job-reset",
    "background-history-job-admission",
    "background-history-worker-owner-release",
    "background-history-submit-exception-release",
    "background-history-busy-release",
    "manual-history-job-admission",
    "manual-history-worker-owner",
    "manual-history-submit-exception-release",
    "manual-history-busy-release",
    "manual-history-worker-owner-argument",
    "manual-history-worker-owner-release",
)


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BUILD = _load("v80_history_concurrency_build", BUILD_PATH)
OVERLAY = _load("v80_history_concurrency_overlay", OVERLAY_PATH)


@lru_cache(maxsize=1)
def _p5_5e_source():
    manifest = BUILD.load_manifest(MANIFEST_PATH)
    manifest["expected_size"] = P5_5E_SIZE
    manifest["expected_sha256"] = P5_5E_SHA256
    original = BUILD._apply_history_concurrency_ownership_overlay
    BUILD._apply_history_concurrency_ownership_overlay = lambda source: (source, None)
    try:
        source = BUILD._assemble(
            manifest, BUILD._find_repo_root(manifest["manifest_path"]),
        )[0]
    finally:
        BUILD._apply_history_concurrency_ownership_overlay = original
    assert len(source) == P5_5E_SIZE
    assert hashlib.sha256(source).hexdigest().upper() == P5_5E_SHA256
    return source


def test_history_concurrency_overlay_is_deterministic_and_pinned_to_p5_5e():
    first = OVERLAY.apply_history_concurrency_ownership_overlay(_p5_5e_source())
    second = OVERLAY.apply_history_concurrency_ownership_overlay(_p5_5e_source())
    assert first == second
    assert first["input_size"] == P5_5E_SIZE
    assert first["input_sha256"] == P5_5E_SHA256
    assert first["size"] == FINAL_SIZE
    assert first["sha256"] == FINAL_SHA256
    assert first["alias_zh"] == "History 并发所有权覆盖层"
    assert first["insertions"] == INSERTIONS


@pytest.mark.parametrize("label,anchor,_replacement", OVERLAY.INSERTIONS)
def test_history_concurrency_overlay_rejects_missing_or_duplicate_anchor(
        label, anchor, _replacement):
    pattern = "History concurrency anchor %s must appear once" % label
    with pytest.raises(OVERLAY.HistoryConcurrencyOwnershipOverlayError, match=pattern):
        OVERLAY._replace_once("", anchor, _replacement, label)
    with pytest.raises(OVERLAY.HistoryConcurrencyOwnershipOverlayError, match=pattern):
        OVERLAY._replace_once(anchor + anchor, anchor, _replacement, label)


def test_history_concurrency_overlay_rejects_unpinned_or_invalid_input():
    with pytest.raises(
        OVERLAY.HistoryConcurrencyOwnershipOverlayError,
        match="does not match the P5-5E candidate",
    ):
        OVERLAY.apply_history_concurrency_ownership_overlay(_p5_5e_source() + b"\n")
    with pytest.raises(
        OVERLAY.HistoryConcurrencyOwnershipOverlayError,
        match="not valid UTF-8 bytes",
    ):
        OVERLAY.apply_history_concurrency_ownership_overlay(b"\xff")


def test_history_concurrency_overlay_does_not_touch_public_v70():
    before = PUBLIC_V70.read_bytes()
    OVERLAY.apply_history_concurrency_ownership_overlay(_p5_5e_source())
    after = PUBLIC_V70.read_bytes()
    assert len(after) == len(before) == 616699
    assert hashlib.sha256(after).hexdigest().upper() == (
        "233C73CAE1048210B34872D4A10EA6023662300F70A8657DB82EA65C342182D4"
    )
    assert after == before

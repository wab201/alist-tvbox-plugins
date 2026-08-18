import hashlib
import importlib.util
from functools import lru_cache
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parent.parent
BUILD_PATH = ROOT / "tools" / "build_follow_plugin.py"
OVERLAY_PATH = ROOT / "tools" / "build_v80_resource_output_switch_overlay.py"
MANIFEST_PATH = ROOT / "src" / "douban_tmdb_follow_single" / "release.json"
PUBLIC_V70 = ROOT / "py" / "豆瓣TMDB追更单入口.py"
INPUT_SIZE = 865875
INPUT_SHA256 = "DCD2CE50277119998BE2D92631CC90C11B3DDC733CB7B397E072E62FE117E773"
FINAL_SIZE = 870797
FINAL_SHA256 = "0CEBC73A78BCC8C7853A6BD0F0C78F4D95DD786C861425F9E0A4EC40FA0583F9"
INSERTIONS = (
    "controlled-switch-state",
    "private-raw-plugin-config",
    "shared-output-owner",
    "shared-binding-owner",
    "shared-recent-owner",
    "foreground-production-owner",
    "background-production-owner",
    "background-shadow-legacy-owner",
    "background-shadow-candidate-owner",
)


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BUILD = _load("v80_resource_output_switch_build", BUILD_PATH)
OVERLAY = _load("v80_resource_output_switch_overlay", OVERLAY_PATH)


@lru_cache(maxsize=1)
def _pre_switch_source():
    manifest = BUILD.load_manifest(MANIFEST_PATH)
    manifest["expected_size"] = INPUT_SIZE
    manifest["expected_sha256"] = INPUT_SHA256
    original = BUILD._apply_resource_output_switch_overlay
    BUILD._apply_resource_output_switch_overlay = lambda source: (source, None)
    try:
        source = BUILD._assemble(
            manifest, BUILD._find_repo_root(manifest["manifest_path"]),
        )[0]
    finally:
        BUILD._apply_resource_output_switch_overlay = original
    assert len(source) == INPUT_SIZE
    assert hashlib.sha256(source).hexdigest().upper() == INPUT_SHA256
    return source


def test_resource_output_switch_overlay_is_deterministic_and_pinned():
    first = OVERLAY.apply_resource_output_switch_overlay(_pre_switch_source())
    second = OVERLAY.apply_resource_output_switch_overlay(_pre_switch_source())

    assert first == second
    assert first["input_size"] == INPUT_SIZE
    assert first["input_sha256"] == INPUT_SHA256
    assert first["size"] == FINAL_SIZE
    assert first["sha256"] == FINAL_SHA256
    assert first["alias_zh"] == "P2 私有 V80 资源输出受控切换覆盖层"
    assert first["insertions"] == INSERTIONS


@pytest.mark.parametrize("label,anchor,replacement", OVERLAY.INSERTIONS)
def test_resource_output_switch_overlay_rejects_anchor_drift(
        label, anchor, replacement):
    pattern = "resource output switch anchor %s must appear once" % label
    with pytest.raises(OVERLAY.ResourceOutputSwitchOverlayError, match=pattern):
        OVERLAY._replace_once("", anchor, replacement, label)
    with pytest.raises(OVERLAY.ResourceOutputSwitchOverlayError, match=pattern):
        OVERLAY._replace_once(anchor + anchor, anchor, replacement, label)


def test_resource_output_switch_overlay_rejects_unpinned_input():
    with pytest.raises(
        OVERLAY.ResourceOutputSwitchOverlayError,
        match="does not match the pinned V80 candidate",
    ):
        OVERLAY.apply_resource_output_switch_overlay(_pre_switch_source() + b"\n")


def test_resource_output_switch_overlay_keeps_public_v70_unchanged():
    before = PUBLIC_V70.read_bytes()
    OVERLAY.apply_resource_output_switch_overlay(_pre_switch_source())
    after = PUBLIC_V70.read_bytes()

    assert after == before
    assert len(after) == 616699
    assert hashlib.sha256(after).hexdigest().upper() == (
        "233C73CAE1048210B34872D4A10EA6023662300F70A8657DB82EA65C342182D4"
    )

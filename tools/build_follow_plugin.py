#!/usr/bin/env python3
"""Deterministically assemble and audit the Douban/TMDB follow plugin."""

import argparse
import ast
import hashlib
import importlib.util
import json
import os
import re
import stat
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = REPO_ROOT / "src" / "douban_tmdb_follow_single" / "release.json"
BASELINE_MANIFEST = REPO_ROOT / "src" / "douban_tmdb_follow_single" / "baseline_v70.json"
PUBLIC_V70_OUTPUT = Path("py/豆瓣TMDB追更单入口.py")
V80_DEV_OUTPUT_ROOT = Path("build/v80-dev")
RESOURCE_SHADOW_VENDOR_SCRIPT = REPO_ROOT / "tools" / "build_v80_resource_shadow_vendor.py"
RESOURCE_SHADOW_OVERLAY_SCRIPT = REPO_ROOT / "tools" / "build_v80_resource_shadow_overlay.py"
RESOURCE_SHADOW_VENDOR_MANIFEST = Path("resource_candidate_shadow_vendor.json")
HISTORY_SYNC_MODULE = REPO_ROOT / "src" / "douban_tmdb_follow_single" / "history_sync_v145.py"
HISTORY_SYNC_OVERLAY_SCRIPT = REPO_ROOT / "tools" / "build_v80_history_sync_overlay.py"
RELIABILITY_MODULE = REPO_ROOT / "src" / "douban_tmdb_follow_single" / "reliability_contract.py"
RELIABILITY_OVERLAY_SCRIPT = REPO_ROOT / "tools" / "build_v80_reliability_overlay.py"
CACHE_HEALTH_MODULE = REPO_ROOT / "src" / "douban_tmdb_follow_single" / "cache_health_contract.py"
CACHE_HEALTH_OVERLAY_SCRIPT = REPO_ROOT / "tools" / "build_v80_cache_health_overlay.py"
BACKGROUND_BULKHEAD_MODULE = (
    REPO_ROOT / "src" / "douban_tmdb_follow_single" / "background_bulkhead_contract.py"
)
BACKGROUND_BULKHEAD_OVERLAY_SCRIPT = (
    REPO_ROOT / "tools" / "build_v80_background_bulkhead_overlay.py"
)
TIMEOUT_BUDGET_MODULE = (
    REPO_ROOT / "src" / "douban_tmdb_follow_single" / "timeout_budget_contract.py"
)
TIMEOUT_BUDGET_OVERLAY_SCRIPT = (
    REPO_ROOT / "tools" / "build_v80_timeout_budget_overlay.py"
)
SECURITY_POLICY_MODULE = (
    REPO_ROOT / "src" / "douban_tmdb_follow_single" / "security_policy.py"
)
ROUTE_SECURITY_OVERLAY_SCRIPT = (
    REPO_ROOT / "tools" / "build_v80_route_security_overlay.py"
)
JSON_SHAPE_POLICY_MODULE = (
    REPO_ROOT / "src" / "douban_tmdb_follow_single" / "json_shape_policy.py"
)
TMDB_JSON_SHAPE_OVERLAY_SCRIPT = (
    REPO_ROOT / "tools" / "build_v80_tmdb_json_shape_overlay.py"
)
TMDB_RESPONSE_POLICY_MODULE = (
    REPO_ROOT / "src" / "douban_tmdb_follow_single" / "tmdb_response_policy.py"
)
TMDB_RESPONSE_BOUNDARY_OVERLAY_SCRIPT = (
    REPO_ROOT / "tools" / "build_v80_tmdb_response_boundary_overlay.py"
)
DIAGNOSTIC_REDACTION_POLICY_MODULE = (
    REPO_ROOT / "src" / "douban_tmdb_follow_single" / "diagnostic_redaction_policy.py"
)
DIAGNOSTIC_REDACTION_OVERLAY_SCRIPT = (
    REPO_ROOT / "tools" / "build_v80_diagnostic_redaction_overlay.py"
)
DOUBAN_RESPONSE_POLICY_MODULE = (
    REPO_ROOT / "src" / "douban_tmdb_follow_single" / "douban_response_policy.py"
)
DOUBAN_RESPONSE_BOUNDARY_OVERLAY_SCRIPT = (
    REPO_ROOT / "tools" / "build_v80_douban_response_boundary_overlay.py"
)
DOUBAN_HTML_RESPONSE_POLICY_MODULE = (
    REPO_ROOT / "src" / "douban_tmdb_follow_single"
    / "douban_html_response_policy.py"
)
DOUBAN_HTML_RESPONSE_BOUNDARY_OVERLAY_SCRIPT = (
    REPO_ROOT / "tools" / "build_v80_douban_html_response_boundary_overlay.py"
)
OBSERVABILITY_POLICY_MODULE = (
    REPO_ROOT / "src" / "douban_tmdb_follow_single" / "observability_policy.py"
)
OBSERVABILITY_RUNTIME_OVERLAY_SCRIPT = (
    REPO_ROOT / "tools" / "build_v80_observability_runtime_overlay.py"
)
DIAGNOSTICS_SNAPSHOT_OVERLAY_SCRIPT = (
    REPO_ROOT / "tools" / "build_v80_diagnostics_snapshot_overlay.py"
)
LIFECYCLE_STABILITY_OVERLAY_SCRIPT = (
    REPO_ROOT / "tools" / "build_v80_lifecycle_stability_overlay.py"
)
SEARCH_CONCURRENCY_OWNERSHIP_OVERLAY_SCRIPT = (
    REPO_ROOT / "tools" / "build_v80_search_concurrency_ownership_overlay.py"
)
PLAYBACK_CONCURRENCY_OWNERSHIP_OVERLAY_SCRIPT = (
    REPO_ROOT / "tools" / "build_v80_playback_concurrency_ownership_overlay.py"
)
HISTORY_CONCURRENCY_OWNERSHIP_OVERLAY_SCRIPT = (
    REPO_ROOT / "tools" / "build_v80_history_concurrency_ownership_overlay.py"
)
RESOURCE_OUTPUT_SWITCH_OVERLAY_SCRIPT = (
    REPO_ROOT / "tools" / "build_v80_resource_output_switch_overlay.py"
)
METADATA_PATTERN = re.compile(
    r"(?m)^\s*//@(?P<key>name|id|version):(?P<value>.*?)\s*$"
)


class BuildError(RuntimeError):
    """Raised when the release manifest or assembled source fails an audit."""


def _load_resource_shadow_vendor_builder():
    spec = importlib.util.spec_from_file_location(
        "v80_resource_shadow_vendor_builder", RESOURCE_SHADOW_VENDOR_SCRIPT
    )
    if spec is None or spec.loader is None:
        raise BuildError(
            "cannot load resource shadow vendor builder: %s"
            % RESOURCE_SHADOW_VENDOR_SCRIPT
        )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_resource_shadow_overlay_builder():
    spec = importlib.util.spec_from_file_location(
        "v80_resource_shadow_overlay_builder", RESOURCE_SHADOW_OVERLAY_SCRIPT
    )
    if spec is None or spec.loader is None:
        raise BuildError(
            "cannot load resource shadow overlay builder: %s"
            % RESOURCE_SHADOW_OVERLAY_SCRIPT
        )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_history_sync_overlay_builder():
    spec = importlib.util.spec_from_file_location(
        "v80_history_sync_overlay_builder", HISTORY_SYNC_OVERLAY_SCRIPT
    )
    if spec is None or spec.loader is None:
        raise BuildError(
            "cannot load history sync overlay builder: %s"
            % HISTORY_SYNC_OVERLAY_SCRIPT
        )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_reliability_overlay_builder():
    spec = importlib.util.spec_from_file_location(
        "v80_reliability_overlay_builder", RELIABILITY_OVERLAY_SCRIPT
    )
    if spec is None or spec.loader is None:
        raise BuildError(
            "cannot load reliability overlay builder: %s"
            % RELIABILITY_OVERLAY_SCRIPT
        )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_cache_health_overlay_builder():
    spec = importlib.util.spec_from_file_location(
        "v80_cache_health_overlay_builder", CACHE_HEALTH_OVERLAY_SCRIPT
    )
    if spec is None or spec.loader is None:
        raise BuildError(
            "cannot load cache-health overlay builder: %s"
            % CACHE_HEALTH_OVERLAY_SCRIPT
        )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_background_bulkhead_overlay_builder():
    spec = importlib.util.spec_from_file_location(
        "v80_background_bulkhead_overlay_builder",
        BACKGROUND_BULKHEAD_OVERLAY_SCRIPT,
    )
    if spec is None or spec.loader is None:
        raise BuildError(
            "cannot load background bulkhead overlay builder: %s"
            % BACKGROUND_BULKHEAD_OVERLAY_SCRIPT
        )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_timeout_budget_overlay_builder():
    spec = importlib.util.spec_from_file_location(
        "v80_timeout_budget_overlay_builder",
        TIMEOUT_BUDGET_OVERLAY_SCRIPT,
    )
    if spec is None or spec.loader is None:
        raise BuildError(
            "cannot load timeout budget overlay builder: %s"
            % TIMEOUT_BUDGET_OVERLAY_SCRIPT
        )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_route_security_overlay_builder():
    spec = importlib.util.spec_from_file_location(
        "v80_route_security_overlay_builder",
        ROUTE_SECURITY_OVERLAY_SCRIPT,
    )
    if spec is None or spec.loader is None:
        raise BuildError(
            "cannot load route security overlay builder: %s"
            % ROUTE_SECURITY_OVERLAY_SCRIPT
        )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_tmdb_json_shape_overlay_builder():
    spec = importlib.util.spec_from_file_location(
        "v80_tmdb_json_shape_overlay_builder",
        TMDB_JSON_SHAPE_OVERLAY_SCRIPT,
    )
    if spec is None or spec.loader is None:
        raise BuildError(
            "cannot load TMDB JSON shape overlay builder: %s"
            % TMDB_JSON_SHAPE_OVERLAY_SCRIPT
        )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_tmdb_response_boundary_overlay_builder():
    spec = importlib.util.spec_from_file_location(
        "v80_tmdb_response_boundary_overlay_builder",
        TMDB_RESPONSE_BOUNDARY_OVERLAY_SCRIPT,
    )
    if spec is None or spec.loader is None:
        raise BuildError(
            "cannot load TMDB response boundary overlay builder: %s"
            % TMDB_RESPONSE_BOUNDARY_OVERLAY_SCRIPT
        )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_diagnostic_redaction_overlay_builder():
    spec = importlib.util.spec_from_file_location(
        "v80_diagnostic_redaction_overlay_builder",
        DIAGNOSTIC_REDACTION_OVERLAY_SCRIPT,
    )
    if spec is None or spec.loader is None:
        raise BuildError(
            "cannot load diagnostic redaction overlay builder: %s"
            % DIAGNOSTIC_REDACTION_OVERLAY_SCRIPT
        )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_douban_response_boundary_overlay_builder():
    spec = importlib.util.spec_from_file_location(
        "v80_douban_response_boundary_overlay_builder",
        DOUBAN_RESPONSE_BOUNDARY_OVERLAY_SCRIPT,
    )
    if spec is None or spec.loader is None:
        raise BuildError(
            "cannot load Douban response boundary overlay builder: %s"
            % DOUBAN_RESPONSE_BOUNDARY_OVERLAY_SCRIPT
        )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_douban_html_response_boundary_overlay_builder():
    spec = importlib.util.spec_from_file_location(
        "v80_douban_html_response_boundary_overlay_builder",
        DOUBAN_HTML_RESPONSE_BOUNDARY_OVERLAY_SCRIPT,
    )
    if spec is None or spec.loader is None:
        raise BuildError(
            "cannot load Douban HTML response boundary overlay builder: %s"
            % DOUBAN_HTML_RESPONSE_BOUNDARY_OVERLAY_SCRIPT
        )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_observability_runtime_overlay_builder():
    spec = importlib.util.spec_from_file_location(
        "v80_observability_runtime_overlay_builder",
        OBSERVABILITY_RUNTIME_OVERLAY_SCRIPT,
    )
    if spec is None or spec.loader is None:
        raise BuildError(
            "cannot load observability runtime overlay builder: %s"
            % OBSERVABILITY_RUNTIME_OVERLAY_SCRIPT
        )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_diagnostics_snapshot_overlay_builder():
    spec = importlib.util.spec_from_file_location(
        "v80_diagnostics_snapshot_overlay_builder",
        DIAGNOSTICS_SNAPSHOT_OVERLAY_SCRIPT,
    )
    if spec is None or spec.loader is None:
        raise BuildError(
            "cannot load diagnostics snapshot overlay builder: %s"
            % DIAGNOSTICS_SNAPSHOT_OVERLAY_SCRIPT
        )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_lifecycle_stability_overlay_builder():
    spec = importlib.util.spec_from_file_location(
        "v80_lifecycle_stability_overlay_builder",
        LIFECYCLE_STABILITY_OVERLAY_SCRIPT,
    )
    if spec is None or spec.loader is None:
        raise BuildError(
            "cannot load lifecycle stability overlay builder: %s"
            % LIFECYCLE_STABILITY_OVERLAY_SCRIPT
        )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_search_concurrency_ownership_overlay_builder():
    spec = importlib.util.spec_from_file_location(
        "v80_search_concurrency_ownership_overlay_builder",
        SEARCH_CONCURRENCY_OWNERSHIP_OVERLAY_SCRIPT,
    )
    if spec is None or spec.loader is None:
        raise BuildError(
            "cannot load search concurrency ownership overlay builder: %s"
            % SEARCH_CONCURRENCY_OWNERSHIP_OVERLAY_SCRIPT
        )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_playback_concurrency_ownership_overlay_builder():
    spec = importlib.util.spec_from_file_location(
        "v80_playback_concurrency_ownership_overlay_builder",
        PLAYBACK_CONCURRENCY_OWNERSHIP_OVERLAY_SCRIPT,
    )
    if spec is None or spec.loader is None:
        raise BuildError(
            "cannot load playback concurrency ownership overlay builder: %s"
            % PLAYBACK_CONCURRENCY_OWNERSHIP_OVERLAY_SCRIPT
        )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_history_concurrency_ownership_overlay_builder():
    spec = importlib.util.spec_from_file_location(
        "v80_history_concurrency_ownership_overlay_builder",
        HISTORY_CONCURRENCY_OWNERSHIP_OVERLAY_SCRIPT,
    )
    if spec is None or spec.loader is None:
        raise BuildError(
            "cannot load History concurrency ownership overlay builder: %s"
            % HISTORY_CONCURRENCY_OWNERSHIP_OVERLAY_SCRIPT
        )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_resource_output_switch_overlay_builder():
    spec = importlib.util.spec_from_file_location(
        "v80_resource_output_switch_overlay_builder",
        RESOURCE_OUTPUT_SWITCH_OVERLAY_SCRIPT,
    )
    if spec is None or spec.loader is None:
        raise BuildError(
            "cannot load resource output switch overlay builder: %s"
            % RESOURCE_OUTPUT_SWITCH_OVERLAY_SCRIPT
        )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _read_utf8(path, label):
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise BuildError("cannot read %s %s: %s" % (label, path, exc)) from exc
    if data.startswith(b"\xef\xbb\xbf"):
        raise BuildError("%s must be UTF-8 without BOM: %s" % (label, path))
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise BuildError("%s is not valid UTF-8: %s" % (label, path)) from exc
    return data, text


def _load_json(path, label):
    _, text = _read_utf8(path, label)
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise BuildError("invalid %s JSON %s: %s" % (label, path, exc)) from exc


def _relative_path(value, label):
    if not isinstance(value, str) or not value or "\\" in value:
        raise BuildError("%s must be a non-empty forward-slash path" % label)
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise BuildError("%s must stay within its declared root: %s" % (label, value))
    return path


def _inside(root, path, label):
    root = root.resolve()
    path = path.resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise BuildError("%s escapes %s: %s" % (label, root, path)) from exc
    return path


def _absolute_path(path):
    return Path(os.path.abspath(os.fspath(path)))


def _resolved_path(path, label):
    try:
        return path.resolve(strict=False)
    except (OSError, RuntimeError) as exc:
        raise BuildError("cannot resolve %s %s: %s" % (label, path, exc)) from exc


def _lstat(path, label):
    try:
        return path.lstat()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise BuildError("cannot inspect %s %s: %s" % (label, path, exc)) from exc


def _is_reparse_or_symlink(path_stat):
    if path_stat is None:
        return False
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x0400)
    file_attributes = getattr(path_stat, "st_file_attributes", 0)
    return stat.S_ISLNK(path_stat.st_mode) or bool(file_attributes & reparse_flag)


def _path_identity(path_stat):
    if path_stat is None:
        return None
    return (
        path_stat.st_dev,
        path_stat.st_ino,
        stat.S_IFMT(path_stat.st_mode),
        getattr(path_stat, "st_file_attributes", 0),
    )


def _snapshot_path(path, label):
    path = _absolute_path(path)
    path_stat = _lstat(path, label)
    return {
        "path": path,
        "resolved": _resolved_path(path, label),
        "identity": _path_identity(path_stat),
        "exists": path_stat is not None,
    }


def _assert_no_reparse_components(repo_root, path, label):
    repo_root = _absolute_path(repo_root)
    path = _absolute_path(path)
    try:
        relative = path.relative_to(repo_root)
    except ValueError as exc:
        raise BuildError("%s escapes repository root: %s" % (label, path)) from exc

    current = repo_root
    for part in relative.parts:
        current = current / part
        path_stat = _lstat(current, label)
        if _is_reparse_or_symlink(path_stat):
            raise BuildError("%s contains a symlink or reparse point: %s" % (label, current))


def _assert_regular_or_missing(path, label):
    path_stat = _lstat(path, label)
    if path_stat is None:
        return
    if _is_reparse_or_symlink(path_stat):
        raise BuildError("%s is a symlink or reparse point: %s" % (label, path))
    if not stat.S_ISREG(path_stat.st_mode):
        raise BuildError("%s must be a regular file or absent: %s" % (label, path))


def _protected_digest(path):
    path_stat = _lstat(path, "protected V70 output")
    if path_stat is None or not stat.S_ISREG(path_stat.st_mode):
        return None
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest().upper()
    except OSError as exc:
        raise BuildError("cannot read protected V70 output %s: %s" % (path, exc)) from exc


def _assert_write_layout(repo_root, output_root, parent, target, protected_output, stage):
    for path, label in (
        (output_root, "V80 output root"),
        (parent, "release output parent"),
        (target, "release output target"),
        (protected_output, "protected V70 output"),
    ):
        _assert_no_reparse_components(repo_root, path, "%s during %s" % (label, stage))

    resolved_repo = _resolved_path(repo_root, "repository root")
    resolved_output_root = _resolved_path(output_root, "V80 output root")
    resolved_parent = _resolved_path(parent, "release output parent")
    resolved_target = _resolved_path(target, "release output target")
    resolved_protected = _resolved_path(protected_output, "protected V70 output")
    try:
        resolved_output_root.relative_to(resolved_repo)
        resolved_parent.relative_to(resolved_output_root)
        resolved_target.relative_to(resolved_output_root)
    except ValueError as exc:
        raise BuildError("write path escaped its approved root during %s" % stage) from exc
    if resolved_target == resolved_protected:
        raise BuildError("refusing to write the frozen V70 public output: %s" % target)
    _assert_regular_or_missing(target, "release output target during %s" % stage)


def _capture_write_state(repo_root, output_root, parent, target, protected_output):
    state = {
        "repo_root": _snapshot_path(repo_root, "repository root"),
        "output_root": _snapshot_path(output_root, "V80 output root"),
        "parent": _snapshot_path(parent, "release output parent"),
        "target": _snapshot_path(target, "release output target"),
        "protected_parent": _snapshot_path(protected_output.parent, "protected V70 parent"),
        "protected": _snapshot_path(protected_output, "protected V70 output"),
        "protected_digest": _protected_digest(protected_output),
    }
    return state


def _assert_snapshot_unchanged(expected, label):
    current = _snapshot_path(expected["path"], label)
    if current["resolved"] != expected["resolved"] or current["identity"] != expected["identity"]:
        raise BuildError("%s identity or resolution changed" % label)


def _assert_write_state(state, stage, check_target=True):
    repo_root = state["repo_root"]["path"]
    output_root = state["output_root"]["path"]
    parent = state["parent"]["path"]
    target = state["target"]["path"]
    protected_output = state["protected"]["path"]
    _assert_write_layout(
        repo_root, output_root, parent, target, protected_output, stage
    )
    keys = ["repo_root", "output_root", "parent", "protected_parent", "protected"]
    if check_target:
        keys.append("target")
    for key in keys:
        _assert_snapshot_unchanged(state[key], "%s during %s" % (key, stage))
    if _protected_digest(protected_output) != state["protected_digest"]:
        raise BuildError("protected V70 output changed during %s" % stage)


def _assert_pre_mkdir_state(initial, stage):
    for key in ("repo_root", "protected_parent", "protected"):
        _assert_snapshot_unchanged(initial[key], "%s during %s" % (key, stage))
    for key in ("output_root", "parent", "target"):
        if initial[key]["exists"]:
            _assert_snapshot_unchanged(initial[key], "%s during %s" % (key, stage))
    if not initial["target"]["exists"] and _lstat(initial["target"]["path"], "release target"):
        raise BuildError("release output target appeared during %s" % stage)
    if _protected_digest(initial["protected"]["path"]) != initial["protected_digest"]:
        raise BuildError("protected V70 output changed during %s" % stage)


def _safe_cleanup_temp(temp_path, temp_identity, parent_snapshot):
    if temp_path is None or temp_identity is None:
        return
    try:
        current_parent = _snapshot_path(parent_snapshot["path"], "temporary file parent")
        current_temp_stat = _lstat(temp_path, "temporary file")
        if (
            current_parent["resolved"] == parent_snapshot["resolved"]
            and current_parent["identity"] == parent_snapshot["identity"]
            and _path_identity(current_temp_stat) == temp_identity
            and not _is_reparse_or_symlink(current_temp_stat)
        ):
            temp_path.unlink()
    except (BuildError, OSError):
        pass


def load_manifest(manifest_path=DEFAULT_MANIFEST):
    """Load and validate the release manifest and return its normalized data."""
    manifest_path = Path(manifest_path).resolve()
    manifest = _load_json(manifest_path, "manifest")
    if not isinstance(manifest, dict):
        raise BuildError("manifest root must be an object")

    required = {
        "schema_version",
        "contract",
        "id",
        "version",
        "output",
        "writable",
        "index_contract",
        "encoding",
        "expected_size",
        "expected_sha256",
        "chunks",
    }
    missing = sorted(required.difference(manifest))
    extra = sorted(set(manifest).difference(required))
    if missing:
        raise BuildError("manifest is missing fields: %s" % ", ".join(missing))
    if extra:
        raise BuildError("manifest has unknown fields: %s" % ", ".join(extra))
    if manifest["schema_version"] != 1:
        raise BuildError("unsupported manifest schema_version: %r" % manifest["schema_version"])
    if manifest["contract"] not in ("baseline_v70", "v80_development"):
        raise BuildError("unsupported manifest contract: %r" % manifest["contract"])
    if not isinstance(manifest["id"], str) or not manifest["id"].strip():
        raise BuildError("manifest id must be a non-empty string")
    if not isinstance(manifest["version"], int) or isinstance(manifest["version"], bool):
        raise BuildError("manifest version must be an integer")
    if manifest["version"] < 1:
        raise BuildError("manifest version must be positive")
    if manifest["encoding"] != "utf-8":
        raise BuildError("manifest encoding must be utf-8")
    if not isinstance(manifest["expected_size"], int) or manifest["expected_size"] < 1:
        raise BuildError("manifest expected_size must be a positive integer")
    expected_hash = manifest["expected_sha256"]
    if not isinstance(expected_hash, str) or not re.fullmatch(r"[0-9A-Fa-f]{64}", expected_hash):
        raise BuildError("manifest expected_sha256 must contain 64 hex characters")

    output_value = manifest["output"]
    output_path = _relative_path(output_value, "manifest output")
    if not isinstance(manifest["writable"], bool):
        raise BuildError("manifest writable must be a boolean")
    if manifest["index_contract"] not in ("required", "none"):
        raise BuildError("manifest index_contract must be required or none")
    if manifest["contract"] == "baseline_v70":
        if output_path != PUBLIC_V70_OUTPUT:
            raise BuildError("baseline_v70 output must be %s" % PUBLIC_V70_OUTPUT)
        if manifest["writable"] is not False:
            raise BuildError("baseline_v70 manifest must have writable=false")
        if manifest["index_contract"] != "required":
            raise BuildError("baseline_v70 manifest must require the repository index")
    else:
        try:
            output_path.relative_to(V80_DEV_OUTPUT_ROOT)
        except ValueError as exc:
            raise BuildError(
                "v80_development output must stay under %s" % V80_DEV_OUTPUT_ROOT
            ) from exc
        if manifest["writable"] is not True:
            raise BuildError("v80_development manifest must have writable=true")
        if manifest["index_contract"] != "none":
            raise BuildError("v80_development manifest must not require the repository index")
    chunks = manifest["chunks"]
    if not isinstance(chunks, list) or len(chunks) != 10:
        raise BuildError("manifest chunks must contain exactly 10 paths")
    for index, value in enumerate(chunks):
        _relative_path(value, "manifest chunk %d" % index)
    if len(set(chunks)) != len(chunks):
        raise BuildError("manifest chunks must not contain duplicates")

    normalized = dict(manifest)
    normalized["expected_sha256"] = expected_hash.upper()
    normalized["manifest_path"] = manifest_path
    return normalized


def _find_repo_root(manifest_path):
    for candidate in (manifest_path.parent,) + tuple(manifest_path.parents):
        if (candidate / "spiders_v2.json").is_file():
            return candidate.resolve()
    raise BuildError("cannot find repository root containing spiders_v2.json")


def _assert_resource_shadow_vendor_namespace(base_text, base_path, vendor, builder):
    try:
        base_tree = ast.parse(base_text, filename=str(base_path))
        base_namespace = builder.describe_top_level_namespace(base_tree, base_path)
    except (SyntaxError, builder.VendorBuildError) as exc:
        raise BuildError("cannot audit V70 namespace before vendor insertion: %s" % exc) from exc

    base_symbols = set(base_namespace["symbols"])
    base_imports = base_namespace["import_bindings"]
    vendor_symbols = set(vendor["symbols"])
    vendor_imports = vendor["import_bindings"]

    symbol_collisions = sorted(vendor_symbols.intersection(base_symbols | set(base_imports)))
    if symbol_collisions:
        raise BuildError(
            "resource shadow vendor would replace V70 bindings: %s"
            % ", ".join(symbol_collisions)
        )

    import_symbol_collisions = sorted(set(vendor_imports).intersection(base_symbols))
    if import_symbol_collisions:
        raise BuildError(
            "resource shadow vendor imports would replace V70 symbols: %s"
            % ", ".join(import_symbol_collisions)
        )

    import_conflicts = sorted(
        name
        for name, target in vendor_imports.items()
        if name in base_imports and base_imports[name] != target
    )
    if import_conflicts:
        raise BuildError(
            "resource shadow vendor imports conflict with V70 imports: %s"
            % ", ".join(import_conflicts)
        )


def _append_resource_shadow_vendor(base_source, manifest):
    builder = _load_resource_shadow_vendor_builder()
    manifest_dir = manifest["manifest_path"].parent
    vendor_manifest = _inside(
        manifest_dir,
        manifest_dir / RESOURCE_SHADOW_VENDOR_MANIFEST,
        "resource shadow vendor manifest",
    )
    try:
        vendor = builder.build_vendor(vendor_manifest)
    except builder.VendorBuildError as exc:
        raise BuildError("resource shadow vendor build failed: %s" % exc) from exc
    try:
        base_text = base_source.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise BuildError("assembled V70 prefix is not valid UTF-8") from exc
    _assert_resource_shadow_vendor_namespace(
        base_text, manifest["manifest_path"], vendor, builder
    )
    return base_source + vendor["bytes"], vendor


def _apply_resource_shadow_runtime_overlay(source):
    builder = _load_resource_shadow_overlay_builder()
    try:
        result = builder.apply_runtime_overlay(source)
    except builder.RuntimeOverlayError as exc:
        raise BuildError("resource shadow runtime overlay failed: %s" % exc) from exc
    metadata = {key: value for key, value in result.items() if key != "bytes"}
    return result["bytes"], metadata


def _append_audited_module(base_source, module_path, module_label, input_filename):
    namespace_builder = _load_resource_shadow_vendor_builder()
    module_bytes, module_text = _read_utf8(module_path, module_label)
    try:
        base_text = base_source.decode("utf-8")
        base_tree = ast.parse(base_text, filename=input_filename)
        module_tree = ast.parse(module_text, filename=str(module_path))
        base_namespace = namespace_builder.describe_top_level_namespace(
            base_tree, Path(input_filename)
        )
        module_namespace = namespace_builder.describe_top_level_namespace(
            module_tree, module_path
        )
    except (UnicodeDecodeError, SyntaxError, namespace_builder.VendorBuildError) as exc:
        raise BuildError("cannot audit %s namespace: %s" % (module_label, exc)) from exc

    base_symbols = set(base_namespace["symbols"])
    base_imports = base_namespace["import_bindings"]
    module_symbols = set(module_namespace["symbols"])
    module_imports = module_namespace["import_bindings"]
    collisions = sorted(module_symbols.intersection(base_symbols | set(base_imports)))
    collisions.extend(sorted(set(module_imports).intersection(base_symbols)))
    conflicts = sorted(
        name
        for name, target in module_imports.items()
        if name in base_imports and base_imports[name] != target
    )
    if collisions or conflicts:
        names = sorted(set(collisions + conflicts))
        raise BuildError(
            "%s would replace existing bindings: %s"
            % (module_label, ", ".join(names))
        )

    data = base_source + module_bytes
    return data, {
        "bytes": module_bytes,
        "input_bytes": base_source,
        "size": len(module_bytes),
        "sha256": hashlib.sha256(module_bytes).hexdigest().upper(),
        "input_size": len(base_source),
        "input_sha256": hashlib.sha256(base_source).hexdigest().upper(),
        "output_size": len(data),
        "output_sha256": hashlib.sha256(data).hexdigest().upper(),
        "symbols": tuple(module_namespace["symbols"]),
        "import_bindings": dict(module_imports),
    }


def _append_history_sync_module(base_source):
    return _append_audited_module(
        base_source,
        HISTORY_SYNC_MODULE,
        "P3 History module",
        "build/v80-dev/pre-history.py",
    )


def _append_reliability_module(base_source):
    return _append_audited_module(
        base_source,
        RELIABILITY_MODULE,
        "P3 Reliability module",
        "build/v80-dev/pre-reliability.py",
    )


def _append_cache_health_module(base_source):
    return _append_audited_module(
        base_source,
        CACHE_HEALTH_MODULE,
        "P3 Cache Health module",
        "build/v80-dev/pre-cache-health.py",
    )


def _append_background_bulkhead_module(base_source):
    return _append_audited_module(
        base_source,
        BACKGROUND_BULKHEAD_MODULE,
        "P3 Background Bulkhead module",
        "build/v80-dev/pre-background-bulkhead.py",
    )


def _append_timeout_budget_module(base_source):
    return _append_audited_module(
        base_source,
        TIMEOUT_BUDGET_MODULE,
        "P3 Timeout Budget module",
        "build/v80-dev/pre-timeout-budget.py",
    )


def _append_security_policy_module(base_source):
    return _append_audited_module(
        base_source,
        SECURITY_POLICY_MODULE,
        "P4 Security Policy module",
        "build/v80-dev/pre-security-policy.py",
    )


def _append_json_shape_policy_module(base_source):
    return _append_audited_module(
        base_source,
        JSON_SHAPE_POLICY_MODULE,
        "P4 JSON Shape Policy module",
        "build/v80-dev/pre-json-shape-policy.py",
    )


def _append_tmdb_response_policy_module(base_source):
    return _append_audited_module(
        base_source,
        TMDB_RESPONSE_POLICY_MODULE,
        "P4 TMDB Response Policy module",
        "build/v80-dev/pre-tmdb-response-policy.py",
    )


def _append_diagnostic_redaction_policy_module(base_source):
    return _append_audited_module(
        base_source,
        DIAGNOSTIC_REDACTION_POLICY_MODULE,
        "P4 Diagnostic Redaction Policy module",
        "build/v80-dev/pre-diagnostic-redaction-policy.py",
    )


def _append_douban_response_policy_module(base_source):
    return _append_audited_module(
        base_source,
        DOUBAN_RESPONSE_POLICY_MODULE,
        "P4 Douban Response Policy module",
        "build/v80-dev/pre-douban-response-policy.py",
    )


def _append_douban_html_response_policy_module(base_source):
    return _append_audited_module(
        base_source,
        DOUBAN_HTML_RESPONSE_POLICY_MODULE,
        "P4 Douban HTML Response Policy module",
        "build/v80-dev/pre-douban-html-response-policy.py",
    )


def _append_observability_policy_module(base_source):
    return _append_audited_module(
        base_source,
        OBSERVABILITY_POLICY_MODULE,
        "P5 Observability Policy module",
        "build/v80-dev/pre-observability-policy.py",
    )


def _apply_history_sync_overlay(source):
    builder = _load_history_sync_overlay_builder()
    try:
        result = builder.apply_history_sync_overlay(source)
    except builder.HistorySyncOverlayError as exc:
        raise BuildError("history sync overlay failed: %s" % exc) from exc
    metadata = {key: value for key, value in result.items() if key != "bytes"}
    return result["bytes"], metadata


def _apply_reliability_overlay(source):
    builder = _load_reliability_overlay_builder()
    try:
        result = builder.apply_reliability_overlay(source)
    except builder.ReliabilityOverlayError as exc:
        raise BuildError("reliability overlay failed: %s" % exc) from exc
    metadata = {key: value for key, value in result.items() if key != "bytes"}
    return result["bytes"], metadata


def _apply_cache_health_overlay(source):
    builder = _load_cache_health_overlay_builder()
    try:
        result = builder.apply_cache_health_overlay(source)
    except builder.CacheHealthOverlayError as exc:
        raise BuildError("cache-health overlay failed: %s" % exc) from exc
    metadata = {key: value for key, value in result.items() if key != "bytes"}
    return result["bytes"], metadata


def _apply_background_bulkhead_overlay(source):
    builder = _load_background_bulkhead_overlay_builder()
    try:
        result = builder.apply_background_bulkhead_overlay(source)
    except builder.BackgroundBulkheadOverlayError as exc:
        raise BuildError("background bulkhead overlay failed: %s" % exc) from exc
    metadata = {key: value for key, value in result.items() if key != "bytes"}
    return result["bytes"], metadata


def _apply_timeout_budget_overlay(source):
    builder = _load_timeout_budget_overlay_builder()
    try:
        result = builder.apply_timeout_budget_overlay(source)
    except builder.TimeoutBudgetOverlayError as exc:
        raise BuildError("timeout budget overlay failed: %s" % exc) from exc
    metadata = {key: value for key, value in result.items() if key != "bytes"}
    return result["bytes"], metadata


def _apply_route_security_overlay(source):
    builder = _load_route_security_overlay_builder()
    try:
        result = builder.apply_route_security_overlay(source)
    except builder.RouteSecurityOverlayError as exc:
        raise BuildError("route security overlay failed: %s" % exc) from exc
    metadata = {key: value for key, value in result.items() if key != "bytes"}
    return result["bytes"], metadata


def _apply_tmdb_json_shape_overlay(source):
    builder = _load_tmdb_json_shape_overlay_builder()
    try:
        result = builder.apply_tmdb_json_shape_overlay(source)
    except builder.TmdbJsonShapeOverlayError as exc:
        raise BuildError("TMDB JSON shape overlay failed: %s" % exc) from exc
    metadata = {key: value for key, value in result.items() if key != "bytes"}
    return result["bytes"], metadata


def _apply_tmdb_response_boundary_overlay(source):
    builder = _load_tmdb_response_boundary_overlay_builder()
    try:
        result = builder.apply_tmdb_response_boundary_overlay(source)
    except builder.TmdbResponseBoundaryOverlayError as exc:
        raise BuildError("TMDB response boundary overlay failed: %s" % exc) from exc
    metadata = {key: value for key, value in result.items() if key != "bytes"}
    return result["bytes"], metadata


def _apply_diagnostic_redaction_overlay(source):
    builder = _load_diagnostic_redaction_overlay_builder()
    try:
        result = builder.apply_diagnostic_redaction_overlay(source)
    except builder.DiagnosticRedactionOverlayError as exc:
        raise BuildError("diagnostic redaction overlay failed: %s" % exc) from exc
    metadata = {key: value for key, value in result.items() if key != "bytes"}
    return result["bytes"], metadata


def _apply_douban_response_boundary_overlay(source):
    builder = _load_douban_response_boundary_overlay_builder()
    try:
        result = builder.apply_douban_response_boundary_overlay(source)
    except builder.DoubanResponseBoundaryOverlayError as exc:
        raise BuildError("Douban response boundary overlay failed: %s" % exc) from exc
    metadata = {key: value for key, value in result.items() if key != "bytes"}
    return result["bytes"], metadata


def _apply_douban_html_response_boundary_overlay(source):
    builder = _load_douban_html_response_boundary_overlay_builder()
    try:
        result = builder.apply_douban_html_response_boundary_overlay(source)
    except builder.DoubanHtmlResponseBoundaryOverlayError as exc:
        raise BuildError(
            "Douban HTML response boundary overlay failed: %s" % exc
        ) from exc
    metadata = {key: value for key, value in result.items() if key != "bytes"}
    return result["bytes"], metadata


def _apply_observability_runtime_overlay(source):
    builder = _load_observability_runtime_overlay_builder()
    try:
        result = builder.apply_observability_runtime_overlay(source)
    except builder.ObservabilityRuntimeOverlayError as exc:
        raise BuildError("observability runtime overlay failed: %s" % exc) from exc
    metadata = {key: value for key, value in result.items() if key != "bytes"}
    return result["bytes"], metadata


def _apply_diagnostics_snapshot_overlay(source):
    builder = _load_diagnostics_snapshot_overlay_builder()
    try:
        result = builder.apply_diagnostics_snapshot_overlay(source)
    except builder.DiagnosticsSnapshotOverlayError as exc:
        raise BuildError("diagnostics snapshot overlay failed: %s" % exc) from exc
    metadata = {key: value for key, value in result.items() if key != "bytes"}
    return result["bytes"], metadata


def _apply_lifecycle_stability_overlay(source):
    builder = _load_lifecycle_stability_overlay_builder()
    try:
        result = builder.apply_lifecycle_stability_overlay(source)
    except builder.LifecycleStabilityOverlayError as exc:
        raise BuildError("lifecycle stability overlay failed: %s" % exc) from exc
    metadata = {key: value for key, value in result.items() if key != "bytes"}
    return result["bytes"], metadata


def _apply_search_concurrency_ownership_overlay(source):
    builder = _load_search_concurrency_ownership_overlay_builder()
    try:
        result = builder.apply_search_concurrency_ownership_overlay(source)
    except builder.SearchConcurrencyOwnershipOverlayError as exc:
        raise BuildError(
            "search concurrency ownership overlay failed: %s" % exc
        ) from exc
    metadata = {key: value for key, value in result.items() if key != "bytes"}
    return result["bytes"], metadata


def _apply_playback_concurrency_ownership_overlay(source):
    builder = _load_playback_concurrency_ownership_overlay_builder()
    try:
        result = builder.apply_playback_concurrency_ownership_overlay(source)
    except builder.PlaybackConcurrencyOwnershipOverlayError as exc:
        raise BuildError(
            "playback concurrency ownership overlay failed: %s" % exc
        ) from exc
    metadata = {key: value for key, value in result.items() if key != "bytes"}
    return result["bytes"], metadata


def _apply_history_concurrency_ownership_overlay(source):
    builder = _load_history_concurrency_ownership_overlay_builder()
    try:
        result = builder.apply_history_concurrency_ownership_overlay(source)
    except builder.HistoryConcurrencyOwnershipOverlayError as exc:
        raise BuildError(
            "History concurrency ownership overlay failed: %s" % exc
        ) from exc
    metadata = {key: value for key, value in result.items() if key != "bytes"}
    return result["bytes"], metadata


def _apply_resource_output_switch_overlay(source):
    builder = _load_resource_output_switch_overlay_builder()
    try:
        result = builder.apply_resource_output_switch_overlay(source)
    except builder.ResourceOutputSwitchOverlayError as exc:
        raise BuildError(
            "resource output switch overlay failed: %s" % exc
        ) from exc
    metadata = {key: value for key, value in result.items() if key != "bytes"}
    return result["bytes"], metadata


def _assemble(manifest, repo_root):
    manifest_dir = manifest["manifest_path"].parent
    chunks = []
    for index, value in enumerate(manifest["chunks"]):
        path = _inside(manifest_dir, manifest_dir / Path(value), "chunk %d" % index)
        data, _ = _read_utf8(path, "chunk")
        chunks.append(data)
    source = b"".join(chunks)
    vendor = None
    overlay = None
    history_module = None
    history_overlay = None
    reliability_module = None
    reliability_overlay = None
    cache_health_module = None
    cache_health_overlay = None
    background_bulkhead_module = None
    background_bulkhead_overlay = None
    timeout_budget_module = None
    timeout_budget_overlay = None
    security_policy_module = None
    route_security_overlay = None
    json_shape_policy_module = None
    tmdb_json_shape_overlay = None
    tmdb_response_policy_module = None
    tmdb_response_boundary_overlay = None
    diagnostic_redaction_policy_module = None
    diagnostic_redaction_overlay = None
    douban_response_policy_module = None
    douban_response_boundary_overlay = None
    douban_html_response_policy_module = None
    douban_html_response_boundary_overlay = None
    observability_policy_module = None
    observability_runtime_overlay = None
    diagnostics_snapshot_overlay = None
    lifecycle_stability_overlay = None
    search_concurrency_ownership_overlay = None
    playback_concurrency_ownership_overlay = None
    history_concurrency_ownership_overlay = None
    resource_output_switch_overlay = None
    if manifest["contract"] == "v80_development":
        source, vendor = _append_resource_shadow_vendor(source, manifest)
        source, overlay = _apply_resource_shadow_runtime_overlay(source)
        source, history_module = _append_history_sync_module(source)
        source, history_overlay = _apply_history_sync_overlay(source)
        source, reliability_module = _append_reliability_module(source)
        source, reliability_overlay = _apply_reliability_overlay(source)
        source, cache_health_module = _append_cache_health_module(source)
        source, cache_health_overlay = _apply_cache_health_overlay(source)
        source, background_bulkhead_module = _append_background_bulkhead_module(source)
        source, background_bulkhead_overlay = _apply_background_bulkhead_overlay(source)
        source, timeout_budget_module = _append_timeout_budget_module(source)
        source, timeout_budget_overlay = _apply_timeout_budget_overlay(source)
        source, security_policy_module = _append_security_policy_module(source)
        source, route_security_overlay = _apply_route_security_overlay(source)
        source, json_shape_policy_module = _append_json_shape_policy_module(source)
        source, tmdb_json_shape_overlay = _apply_tmdb_json_shape_overlay(source)
        source, tmdb_response_policy_module = _append_tmdb_response_policy_module(source)
        source, tmdb_response_boundary_overlay = _apply_tmdb_response_boundary_overlay(source)
        source, diagnostic_redaction_policy_module = (
            _append_diagnostic_redaction_policy_module(source)
        )
        source, diagnostic_redaction_overlay = _apply_diagnostic_redaction_overlay(source)
        source, douban_response_policy_module = _append_douban_response_policy_module(
            source
        )
        source, douban_response_boundary_overlay = (
            _apply_douban_response_boundary_overlay(source)
        )
        source, douban_html_response_policy_module = (
            _append_douban_html_response_policy_module(source)
        )
        source, douban_html_response_boundary_overlay = (
            _apply_douban_html_response_boundary_overlay(source)
        )
        source, observability_policy_module = _append_observability_policy_module(
            source
        )
        source, observability_runtime_overlay = _apply_observability_runtime_overlay(
            source
        )
        source, diagnostics_snapshot_overlay = _apply_diagnostics_snapshot_overlay(
            source
        )
        source, lifecycle_stability_overlay = _apply_lifecycle_stability_overlay(
            source
        )
        source, search_concurrency_ownership_overlay = (
            _apply_search_concurrency_ownership_overlay(source)
        )
        source, playback_concurrency_ownership_overlay = (
            _apply_playback_concurrency_ownership_overlay(source)
        )
        source, history_concurrency_ownership_overlay = (
            _apply_history_concurrency_ownership_overlay(source)
        )
        source, resource_output_switch_overlay = (
            _apply_resource_output_switch_overlay(source)
        )
    try:
        text = source.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise BuildError("assembled source is not valid UTF-8") from exc

    size = len(source)
    digest = hashlib.sha256(source).hexdigest().upper()
    if size != manifest["expected_size"]:
        raise BuildError(
            "assembled size mismatch: expected %d, got %d"
            % (manifest["expected_size"], size)
        )
    if digest != manifest["expected_sha256"]:
        raise BuildError(
            "assembled SHA256 mismatch: expected %s, got %s"
            % (manifest["expected_sha256"], digest)
        )

    output_root = repo_root
    if manifest["contract"] == "v80_development":
        output_root = repo_root / V80_DEV_OUTPUT_ROOT
        _inside(repo_root, output_root, "V80 output root")
    output = repo_root / Path(manifest["output"])
    _inside(output_root, output, "release output")
    return (
        source,
        text,
        output,
        digest,
        vendor,
        overlay,
        history_module,
        history_overlay,
        reliability_module,
        reliability_overlay,
        cache_health_module,
        cache_health_overlay,
        background_bulkhead_module,
        background_bulkhead_overlay,
        timeout_budget_module,
        timeout_budget_overlay,
        security_policy_module,
        route_security_overlay,
        json_shape_policy_module,
        tmdb_json_shape_overlay,
        tmdb_response_policy_module,
        tmdb_response_boundary_overlay,
        diagnostic_redaction_policy_module,
        diagnostic_redaction_overlay,
        douban_response_policy_module,
        douban_response_boundary_overlay,
        douban_html_response_policy_module,
        douban_html_response_boundary_overlay,
        observability_policy_module,
        observability_runtime_overlay,
        diagnostics_snapshot_overlay,
        lifecycle_stability_overlay,
        search_concurrency_ownership_overlay,
        playback_concurrency_ownership_overlay,
        history_concurrency_ownership_overlay,
        resource_output_switch_overlay,
    )


def _audit_ast(text, output):
    try:
        tree = ast.parse(text, filename=str(output))
    except SyntaxError as exc:
        raise BuildError("assembled source has invalid Python syntax: %s" % exc) from exc

    top_level_classes = {}
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            top_level_classes.setdefault(node.name, []).append(node)
    for class_name in ("Spider", "Filter"):
        classes = top_level_classes.get(class_name, [])
        if len(classes) != 1:
            raise BuildError(
                "assembled source must define exactly one top-level %s class" % class_name
            )
        methods = {}
        for node in classes[0].body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                methods.setdefault(node.name, []).append(node.lineno)
        duplicates = {name: lines for name, lines in methods.items() if len(lines) > 1}
        if duplicates:
            detail = ", ".join(
                "%s at lines %s" % (name, "/".join(str(line) for line in lines))
                for name, lines in sorted(duplicates.items())
            )
            raise BuildError("duplicate %s methods: %s" % (class_name, detail))


def _metadata(text):
    values = {}
    for match in METADATA_PATTERN.finditer(text):
        key = match.group("key")
        values.setdefault(key, []).append(match.group("value").strip())
    for key in ("name", "id", "version"):
        rows = values.get(key, [])
        if len(rows) != 1 or not rows[0]:
            raise BuildError("assembled source must contain one non-empty //@%s field" % key)
    return {key: rows[0] for key, rows in values.items()}


def _audit_metadata_and_index(text, manifest, repo_root):
    metadata = _metadata(text)
    if metadata["id"] != manifest["id"]:
        raise BuildError(
            "source metadata id mismatch: expected %s, got %s"
            % (manifest["id"], metadata["id"])
        )
    if metadata["version"] != str(manifest["version"]):
        raise BuildError(
            "source metadata version mismatch: expected %s, got %s"
            % (manifest["version"], metadata["version"])
        )

    if manifest["index_contract"] == "none":
        return metadata

    index_path = repo_root / "spiders_v2.json"
    index = _load_json(index_path, "repository index")
    if not isinstance(index, list):
        raise BuildError("repository index root must be an array")
    entries = [row for row in index if isinstance(row, dict) and row.get("id") == manifest["id"]]
    if len(entries) != 1:
        raise BuildError(
            "repository index must contain exactly one %s entry" % manifest["id"]
        )
    entry = entries[0]
    if entry.get("file") != manifest["output"]:
        raise BuildError(
            "repository index file mismatch: expected %s, got %r"
            % (manifest["output"], entry.get("file"))
        )
    if entry.get("version") != manifest["version"]:
        raise BuildError(
            "repository index version mismatch: expected %s, got %r"
            % (manifest["version"], entry.get("version"))
        )
    if entry.get("valid") is not True:
        raise BuildError("repository index entry must have valid=true")
    return metadata


def build_release(manifest_path=DEFAULT_MANIFEST):
    """Assemble and fully audit release bytes without writing the output."""
    manifest = load_manifest(manifest_path)
    repo_root = _find_repo_root(manifest["manifest_path"])
    (
        source,
        text,
        output,
        digest,
        vendor,
        overlay,
        history_module,
        history_overlay,
        reliability_module,
        reliability_overlay,
        cache_health_module,
        cache_health_overlay,
        background_bulkhead_module,
        background_bulkhead_overlay,
        timeout_budget_module,
        timeout_budget_overlay,
        security_policy_module,
        route_security_overlay,
        json_shape_policy_module,
        tmdb_json_shape_overlay,
        tmdb_response_policy_module,
        tmdb_response_boundary_overlay,
        diagnostic_redaction_policy_module,
        diagnostic_redaction_overlay,
        douban_response_policy_module,
        douban_response_boundary_overlay,
        douban_html_response_policy_module,
        douban_html_response_boundary_overlay,
        observability_policy_module,
        observability_runtime_overlay,
        diagnostics_snapshot_overlay,
        lifecycle_stability_overlay,
        search_concurrency_ownership_overlay,
        playback_concurrency_ownership_overlay,
        history_concurrency_ownership_overlay,
        resource_output_switch_overlay,
    ) = _assemble(manifest, repo_root)
    _audit_ast(text, output)
    metadata = _audit_metadata_and_index(text, manifest, repo_root)
    return {
        "bytes": source,
        "sha256": digest,
        "size": len(source),
        "output": output,
        "repo_root": repo_root,
        "manifest": manifest,
        "metadata": metadata,
        "vendor": vendor,
        "overlay": overlay,
        "history_module": history_module,
        "history_overlay": history_overlay,
        "reliability_module": reliability_module,
        "reliability_overlay": reliability_overlay,
        "cache_health_module": cache_health_module,
        "cache_health_overlay": cache_health_overlay,
        "background_bulkhead_module": background_bulkhead_module,
        "background_bulkhead_overlay": background_bulkhead_overlay,
        "timeout_budget_module": timeout_budget_module,
        "timeout_budget_overlay": timeout_budget_overlay,
        "security_policy_module": security_policy_module,
        "route_security_overlay": route_security_overlay,
        "json_shape_policy_module": json_shape_policy_module,
        "tmdb_json_shape_overlay": tmdb_json_shape_overlay,
        "tmdb_response_policy_module": tmdb_response_policy_module,
        "tmdb_response_boundary_overlay": tmdb_response_boundary_overlay,
        "diagnostic_redaction_policy_module": diagnostic_redaction_policy_module,
        "diagnostic_redaction_overlay": diagnostic_redaction_overlay,
        "douban_response_policy_module": douban_response_policy_module,
        "douban_response_boundary_overlay": douban_response_boundary_overlay,
        "douban_html_response_policy_module": douban_html_response_policy_module,
        "douban_html_response_boundary_overlay": douban_html_response_boundary_overlay,
        "observability_policy_module": observability_policy_module,
        "observability_runtime_overlay": observability_runtime_overlay,
        "diagnostics_snapshot_overlay": diagnostics_snapshot_overlay,
        "lifecycle_stability_overlay": lifecycle_stability_overlay,
        "search_concurrency_ownership_overlay": search_concurrency_ownership_overlay,
        "playback_concurrency_ownership_overlay": playback_concurrency_ownership_overlay,
        "history_concurrency_ownership_overlay": history_concurrency_ownership_overlay,
        "resource_output_switch_overlay": resource_output_switch_overlay,
    }


def check_release(manifest_path=DEFAULT_MANIFEST):
    """Audit the build and require the checked-in output to match byte-for-byte."""
    result = build_release(manifest_path)
    try:
        current = result["output"].read_bytes()
    except OSError as exc:
        raise BuildError("cannot read release output %s: %s" % (result["output"], exc)) from exc
    if current != result["bytes"]:
        current_hash = hashlib.sha256(current).hexdigest().upper()
        raise BuildError(
            "release output differs from assembled bytes: %s (current SHA256 %s)"
            % (result["output"], current_hash)
        )
    return result


def write_release(manifest_path=DEFAULT_MANIFEST):
    """Audit and atomically write the deterministic release output."""
    result = build_release(manifest_path)
    if result["manifest"]["writable"] is not True:
        raise BuildError("manifest is read-only and cannot be written")

    repo_root = _absolute_path(result["repo_root"])
    output_root = _absolute_path(repo_root / V80_DEV_OUTPUT_ROOT)
    output = _absolute_path(repo_root / Path(result["manifest"]["output"]))
    protected_output = _absolute_path(repo_root / PUBLIC_V70_OUTPUT)
    if _absolute_path(result["output"]) != output:
        raise BuildError("build output does not match the manifest output path")

    _assert_write_layout(
        repo_root, output_root, output.parent, output, protected_output, "initial approval"
    )
    initial = _capture_write_state(
        repo_root, output_root, output.parent, output, protected_output
    )
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise BuildError("cannot create release output parent %s: %s" % (output.parent, exc)) from exc
    _assert_write_layout(
        repo_root, output_root, output.parent, output, protected_output, "after mkdir"
    )
    _assert_pre_mkdir_state(initial, "after mkdir")
    approved = _capture_write_state(
        repo_root, output_root, output.parent, output, protected_output
    )
    _assert_write_state(approved, "before existing output read")
    if approved["target"]["exists"]:
        try:
            current = output.read_bytes()
        except OSError as exc:
            raise BuildError("cannot read release output %s: %s" % (output, exc)) from exc
        _assert_write_state(approved, "after existing output read")
        if current == result["bytes"]:
            result["changed"] = False
            return result

    temp_path = None
    temp_identity = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", prefix=output.name + ".", suffix=".tmp", dir=output.parent, delete=False
        ) as handle:
            temp_path = Path(handle.name)
            temp_identity = _path_identity(os.fstat(handle.fileno()))
            handle.write(result["bytes"])
            handle.flush()
            os.fsync(handle.fileno())
        temp_stat = _lstat(temp_path, "temporary release output")
        if (
            temp_stat is None
            or _is_reparse_or_symlink(temp_stat)
            or not stat.S_ISREG(temp_stat.st_mode)
        ):
            raise BuildError("temporary release output is not a regular file: %s" % temp_path)
        if _path_identity(temp_stat) != temp_identity:
            raise BuildError("temporary release output identity changed after creation")
        if _resolved_path(temp_path.parent, "temporary file parent") != approved["parent"]["resolved"]:
            raise BuildError("temporary release output parent changed")
        _assert_write_state(approved, "after temporary file creation")
        if _path_identity(_lstat(temp_path, "temporary release output")) != temp_identity:
            raise BuildError("temporary release output identity changed")
        _assert_write_state(approved, "before replace")
        if _path_identity(_lstat(temp_path, "temporary release output")) != temp_identity:
            raise BuildError("temporary release output identity changed before replace")
        os.replace(str(temp_path), str(output))
        temp_path = None
        temp_identity = None
        _assert_write_state(approved, "after replace", check_target=False)
    finally:
        _safe_cleanup_temp(temp_path, temp_identity, approved["parent"])
    result["changed"] = True
    return result


def _parser():
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--check", action="store_true", help="audit and compare the output")
    action.add_argument("--write", action="store_true", help="audit and atomically write the output")
    action.add_argument(
        "--baseline-check",
        action="store_true",
        help="audit the frozen V70 source and repository index without writing",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_MANIFEST,
        help="release manifest path (default: %(default)s)",
    )
    return parser


def main(argv=None):
    args = _parser().parse_args(argv)
    try:
        if args.baseline_check:
            if args.manifest != DEFAULT_MANIFEST:
                raise BuildError("--baseline-check does not accept --manifest")
            result = check_release(BASELINE_MANIFEST)
        else:
            result = check_release(args.manifest) if args.check else write_release(args.manifest)
    except BuildError as exc:
        print("build error: %s" % exc, file=sys.stderr)
        return 1
    verb = "checked" if (args.check or args.baseline_check) else (
        "written" if result["changed"] else "unchanged"
    )
    print(
        "%s: %s bytes, SHA256 %s, output %s"
        % (verb, result["size"], result["sha256"], result["output"])
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

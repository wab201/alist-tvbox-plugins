import ast
import hashlib
import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BUILD = _load(ROOT / "tools" / "build_follow_plugin.py", "follow_build_p3_test")


def test_build_pipeline_preserves_v70_and_layers_history_after_p2():
    baseline = BUILD.check_release(BUILD.BASELINE_MANIFEST)
    manifest = BUILD.load_manifest(BUILD.DEFAULT_MANIFEST)
    manifest_dir = manifest["manifest_path"].parent
    source = b"".join((manifest_dir / value).read_bytes() for value in manifest["chunks"])
    frozen_hash = hashlib.sha256(source).hexdigest().upper()

    source, vendor = BUILD._append_resource_shadow_vendor(source, manifest)
    source, p2_overlay = BUILD._apply_resource_shadow_runtime_overlay(source)
    source, history_module = BUILD._append_history_sync_module(source)
    history_overlay_input = source
    source, history_overlay = BUILD._apply_history_sync_overlay(source)
    tree = ast.parse(source.decode("utf-8"))

    assert frozen_hash == baseline["sha256"]
    assert history_module["input_sha256"] == p2_overlay["sha256"]
    assert history_overlay["input_size"] == len(history_overlay_input)
    assert history_overlay["input_sha256"] == hashlib.sha256(history_overlay_input).hexdigest().upper()
    assert vendor["modules"]
    coordinator = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "_HistoryCoordinator")
    spider = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Spider")
    assert {node.name for node in coordinator.body if isinstance(node, ast.FunctionDef)}.issuperset({
        "fetch", "_legacy_fetch", "push", "_legacy_push",
    })
    assert {node.name for node in spider.body if isinstance(node, ast.FunctionDef)}.issuperset({
        "_atvp_history_delete", "_atvp_history_delete_legacy",
        "_history_for_local",
    })
    init = next(node for node in spider.body if isinstance(node, ast.FunctionDef) and node.name == "_init_locked")
    destroy = next(node for node in spider.body if isinstance(node, ast.FunctionDef) and node.name == "destroy")
    assert any(
        isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        and node.func.id == "v80_history_queue_start"
        for node in ast.walk(init)
    )
    assert any(
        isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        and node.func.id == "v80_history_queue_stop"
        for node in ast.walk(destroy)
    )
    assert "_history_for_local_legacy" not in {
        node.name for node in spider.body if isinstance(node, ast.FunctionDef)
    }
    sync = next(
        node for node in spider.body
        if isinstance(node, ast.FunctionDef) and node.name == "_sync_history_once"
    )
    refresh = next(
        node for node in ast.walk(sync)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "v80_history_refresh_local_rows"
    )
    merge = next(
        node for node in ast.walk(sync)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "_merge_native_history"
    )
    assert refresh.lineno < merge.lineno
    push = next(
        node for node in ast.walk(sync)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "_atvp_history_push"
    )
    uploaded_assignment = next(
        node for node in ast.walk(sync)
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "uploaded" for target in node.targets)
        and push in tuple(ast.walk(node.value))
    )
    assert uploaded_assignment.lineno > merge.lineno


def test_history_module_namespace_is_isolated_from_v70_and_p2():
    manifest = BUILD.load_manifest(BUILD.DEFAULT_MANIFEST)
    manifest_dir = manifest["manifest_path"].parent
    source = b"".join((manifest_dir / value).read_bytes() for value in manifest["chunks"])
    source, _vendor = BUILD._append_resource_shadow_vendor(source, manifest)
    source, _overlay = BUILD._apply_resource_shadow_runtime_overlay(source)

    _output, metadata = BUILD._append_history_sync_module(source)

    assert "v80_history_fetch" in metadata["symbols"]
    assert "v80_history_push" in metadata["symbols"]
    assert "v80_history_delete" in metadata["symbols"]
    assert "v80_history_for_local" in metadata["symbols"]
    assert "v80_history_refresh_local_rows" in metadata["symbols"]
    assert "v80_history_commit" in metadata["symbols"]
    assert "v80_history_queue_snapshot" in metadata["symbols"]
    assert metadata["import_bindings"] == {
        "hashlib": "import:hashlib",
        "requests": "import:requests",
        "threading": "import:threading",
        "time": "import:time",
    }

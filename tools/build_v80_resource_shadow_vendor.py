#!/usr/bin/env python3
"""Build the minimal P2 resource-candidate shadow closure as one Python module."""

import argparse
import ast
import hashlib
import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = REPO_ROOT / "src" / "douban_tmdb_follow_single"
DEFAULT_MANIFEST = SOURCE_DIR / "resource_candidate_shadow_vendor.json"
EXPECTED_CONTRACT = "v80_p2_resource_candidate_shadow_vendor"
EXPECTED_OUTPUT = Path("build/v80-dev/vendor-proof/resource_candidate_shadow_vendor.py")
EXPECTED_MODULES = (
    "resource_row_identity.py",
    "resource_candidate_merge.py",
    "resource_candidate_ordering.py",
    "resource_candidate_pipeline.py",
    "resource_candidate_shadow.py",
    "resource_candidate_shadow_policy.py",
    "resource_candidate_shadow_composition.py",
    "resource_candidate_shadow_background.py",
    "resource_candidate_shadow_runtime.py",
    "resource_models.py",
    "resource_schema.py",
    "resource_shadow.py",
    "resource_provider.py",
    "resource_search_plan.py",
    "resource_search_shadow.py",
    "resource_search_v70_adapter.py",
    "resource_search_shadow_runtime.py",
)
ALLOWED_TOP_LEVEL_NODES = (
    ast.Import,
    ast.ImportFrom,
    ast.Assign,
    ast.AnnAssign,
    ast.FunctionDef,
    ast.AsyncFunctionDef,
    ast.ClassDef,
)


class VendorBuildError(RuntimeError):
    """Raised when the fixed shadow closure cannot be flattened safely."""


def _read_utf8(path, label):
    try:
        data = Path(path).read_bytes()
    except OSError as exc:
        raise VendorBuildError("cannot read %s %s: %s" % (label, path, exc)) from exc
    if data.startswith(b"\xef\xbb\xbf"):
        raise VendorBuildError("%s must be UTF-8 without BOM: %s" % (label, path))
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise VendorBuildError("%s is not valid UTF-8: %s" % (label, path)) from exc


def load_manifest(manifest_path=DEFAULT_MANIFEST):
    manifest_path = Path(manifest_path)
    try:
        manifest = json.loads(_read_utf8(manifest_path, "vendor manifest"))
    except json.JSONDecodeError as exc:
        raise VendorBuildError("invalid vendor manifest %s: %s" % (manifest_path, exc)) from exc
    if not isinstance(manifest, dict):
        raise VendorBuildError("vendor manifest root must be an object")

    required = {"schema_version", "contract", "encoding", "output", "modules"}
    missing = sorted(required.difference(manifest))
    extra = sorted(set(manifest).difference(required))
    if missing:
        raise VendorBuildError("vendor manifest is missing fields: %s" % ", ".join(missing))
    if extra:
        raise VendorBuildError("vendor manifest has unknown fields: %s" % ", ".join(extra))
    if manifest["schema_version"] != 1:
        raise VendorBuildError("unsupported vendor schema_version: %r" % manifest["schema_version"])
    if manifest["contract"] != EXPECTED_CONTRACT:
        raise VendorBuildError("unsupported vendor contract: %r" % manifest["contract"])
    if manifest["encoding"] != "utf-8":
        raise VendorBuildError("vendor encoding must be utf-8")
    if manifest["output"] != EXPECTED_OUTPUT.as_posix():
        raise VendorBuildError("vendor output must be %s" % EXPECTED_OUTPUT.as_posix())
    if not isinstance(manifest["modules"], list):
        raise VendorBuildError("vendor modules must be an array")
    if tuple(manifest["modules"]) != EXPECTED_MODULES:
        raise VendorBuildError("vendor modules must match the fixed shadow closure order")
    return dict(manifest)


def _assigned_names(target):
    if isinstance(target, ast.Name):
        return [target.id]
    raise VendorBuildError("vendor modules require simple top-level assignment targets")


def _check_top_level_nodes(tree, path):
    unsupported = [
        type(node).__name__
        for node in tree.body
        if not isinstance(node, ALLOWED_TOP_LEVEL_NODES)
    ]
    if unsupported:
        raise VendorBuildError(
            "%s uses unsupported top-level statements: %s"
            % (path.name, ", ".join(unsupported))
        )


def _defined_names(tree, path):
    names = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.append(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                names.extend(_assigned_names(target))
        elif isinstance(node, ast.AnnAssign):
            names.extend(_assigned_names(node.target))
    duplicates = sorted(name for name in set(names) if names.count(name) > 1)
    if duplicates:
        raise VendorBuildError(
            "%s defines top-level symbols more than once: %s"
            % (path.name, ", ".join(duplicates))
        )
    return tuple(names)


def _absolute_import_bindings(tree, path):
    bindings = {}
    for node in tree.body:
        rows = []
        if isinstance(node, ast.Import):
            rows = [
                (alias.asname or alias.name.split(".", 1)[0], "import:%s" % alias.name)
                for alias in node.names
            ]
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            if node.module == "__future__":
                raise VendorBuildError("future imports are not supported in %s" % path.name)
            if any(alias.name == "*" for alias in node.names):
                raise VendorBuildError("absolute star imports are not supported in %s" % path.name)
            rows = [
                (alias.asname or alias.name, "from:%s.%s" % (node.module, alias.name))
                for alias in node.names
            ]
        for local_name, target in rows:
            previous = bindings.get(local_name)
            if previous is not None and previous != target:
                raise VendorBuildError(
                    "%s binds import name %s to both %s and %s"
                    % (path.name, local_name, previous, target)
                )
            bindings[local_name] = target
    return bindings


def describe_top_level_namespace(tree, path):
    """Return the fixed symbol and import bindings used by build isolation checks."""
    return {
        "symbols": _defined_names(tree, path),
        "import_bindings": _absolute_import_bindings(tree, path),
    }


def _relative_imports(tree, path, earlier_symbols):
    top_level_ids = {id(node) for node in tree.body}
    replacements = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or node.level <= 0:
            continue
        if id(node) not in top_level_ids:
            raise VendorBuildError("relative imports must stay at module top level: %s" % path.name)
        if node.level != 1 or not node.module:
            raise VendorBuildError("unsupported relative import in %s" % path.name)
        for other in tree.body:
            if other is node:
                continue
            if other.lineno <= node.end_lineno and other.end_lineno >= node.lineno:
                raise VendorBuildError(
                    "relative imports must occupy complete physical lines in %s" % path.name
                )
        dependency = node.module
        if dependency not in earlier_symbols:
            raise VendorBuildError(
                "%s depends on unavailable or later module %s" % (path.name, dependency)
            )
        for alias in node.names:
            if alias.name == "*" or alias.asname is not None:
                raise VendorBuildError("relative import aliases are not supported in %s" % path.name)
            if alias.name not in earlier_symbols[dependency]:
                raise VendorBuildError(
                    "%s imports missing symbol %s.%s" % (path.name, dependency, alias.name)
                )
        replacements[node.lineno - 1] = node.end_lineno
    return replacements


def _without_relative_imports(text, replacements):
    lines = text.splitlines()
    output = []
    index = 0
    while index < len(lines):
        end = replacements.get(index)
        if end is None:
            output.append(lines[index])
            index += 1
        else:
            index = end
    return output


def build_vendor(manifest_path=DEFAULT_MANIFEST, source_dir=None):
    manifest = load_manifest(manifest_path)
    source_dir = Path(source_dir) if source_dir is not None else Path(manifest_path).parent
    sections = [
        "# -*- coding: utf-8 -*-",
        "# Generated by tools/build_v80_resource_shadow_vendor.py.",
        "# The listed source modules are authoritative; do not edit generated bytes.",
        "",
    ]
    earlier_symbols = {}
    symbol_owners = {}
    import_bindings = {}
    closure_hash = hashlib.sha256(b"v80-p2-resource-shadow-vendor\0")

    for filename in manifest["modules"]:
        path = source_dir / filename
        text = _read_utf8(path, "vendor module")
        try:
            tree = ast.parse(text, filename=str(path))
        except SyntaxError as exc:
            raise VendorBuildError("invalid Python source %s: %s" % (path, exc)) from exc
        module_name = path.stem
        _check_top_level_nodes(tree, path)
        namespace = describe_top_level_namespace(tree, path)
        names = namespace["symbols"]
        imports = namespace["import_bindings"]
        collisions = sorted(name for name in names if name in symbol_owners)
        if collisions:
            detail = ", ".join(
                "%s (%s)" % (name, symbol_owners[name]) for name in collisions
            )
            raise VendorBuildError("top-level vendor symbol collision in %s: %s" % (filename, detail))
        binding_collisions = sorted(
            name for name in names if name in import_bindings or name in imports
        )
        if binding_collisions:
            raise VendorBuildError(
                "top-level vendor definitions collide with imports in %s: %s"
                % (filename, ", ".join(binding_collisions))
            )
        for local_name, target in imports.items():
            if local_name in symbol_owners:
                raise VendorBuildError(
                    "import %s in %s would replace top-level symbol from %s"
                    % (local_name, filename, symbol_owners[local_name])
                )
            previous = import_bindings.get(local_name)
            if previous is not None and previous != target:
                raise VendorBuildError(
                    "import %s in %s conflicts with %s"
                    % (local_name, filename, previous)
                )
        replacements = _relative_imports(tree, path, earlier_symbols)
        body = _without_relative_imports(text, replacements)

        sections.append("# begin vendored module: %s" % filename)
        sections.extend(body)
        sections.append("# end vendored module: %s" % filename)
        sections.append("")

        earlier_symbols[module_name] = frozenset(names)
        for name in names:
            symbol_owners[name] = filename
        import_bindings.update(imports)
        source_bytes = text.encode("utf-8")
        closure_hash.update(filename.encode("ascii"))
        closure_hash.update(b"\0")
        closure_hash.update(source_bytes)
        closure_hash.update(b"\0")

    rendered = "\n".join(sections).rstrip() + "\n"
    try:
        tree = ast.parse(rendered, filename=EXPECTED_OUTPUT.as_posix())
        compile(tree, EXPECTED_OUTPUT.as_posix(), "exec")
    except SyntaxError as exc:
        raise VendorBuildError("generated vendor source is invalid: %s" % exc) from exc
    if any(isinstance(node, ast.ImportFrom) and node.level for node in ast.walk(tree)):
        raise VendorBuildError("generated vendor source still contains relative imports")

    data = rendered.encode("utf-8")
    return {
        "bytes": data,
        "size": len(data),
        "sha256": hashlib.sha256(data).hexdigest().upper(),
        "closure_sha256": closure_hash.hexdigest().upper(),
        "modules": tuple(manifest["modules"]),
        "output": REPO_ROOT / EXPECTED_OUTPUT,
        "symbols": tuple(symbol_owners),
        "import_bindings": dict(import_bindings),
    }


def _parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    return parser


def main(argv=None):
    args = _parser().parse_args(argv)
    try:
        result = build_vendor(args.manifest)
    except VendorBuildError as exc:
        print("vendor build error: %s" % exc)
        return 1
    print(
        "V80 P2 resource shadow vendor: %d bytes, SHA256 %s, closure %s, modules %d"
        % (result["size"], result["sha256"], result["closure_sha256"], len(result["modules"]))
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

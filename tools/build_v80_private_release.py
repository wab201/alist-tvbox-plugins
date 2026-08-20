"""Build the modular private V80 source into one runtime file."""

import argparse
import ast
import hashlib
import json
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT / "src" / "douban_tmdb_follow_v80"
SOURCE_MANIFEST = SOURCE_ROOT / "release.json"
BASELINE_SOURCE = SOURCE_ROOT / "parts" / "00_runtime_v80.pyinc"
CANONICAL_SOURCE = SOURCE_ROOT / "豆瓣TMDB追更单入口.py"
PRIVATE_ROOT = ROOT / "private" / "v80"
PRIVATE_INDEX = PRIVATE_ROOT / "spiders_v2.json"
PRIVATE_MANIFEST = PRIVATE_ROOT / "private-release.json"
STAGED_SOURCE = PRIVATE_ROOT / "staging" / CANONICAL_SOURCE.name
FILTER_OWNER = SOURCE_ROOT / "parts" / "02_filter.pyinc"

PRIVATE_ID = "douban_tmdb_follow_single_v80_private"
PRIVATE_VERSION = 90
SOURCE_SIZE = 981757
SOURCE_SHA256 = "B81CCB95119B6A676CA7CBE93166EE2A7FC4D5AECE79EE78FC1852FBA0619CA9"
FILTER_OWNER_METHODS = (
    ("Filter", "_normalize_title"),
    ("Spider", "_standardize_resource_name"),
)
OWNER_KEYS = (
    "version_metadata",
    "follow_interaction",
    "candidate_recognition",
    "history_merge",
    "route_preheat_restore",
    "playlist_output",
)


class PrivateReleaseError(RuntimeError):
    pass


def _sha256(data):
    return hashlib.sha256(data).hexdigest().upper()


def _json_bytes(payload):
    return (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _read_pinned(path, size, sha256, label):
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise PrivateReleaseError("cannot read %s: %s" % (label, exc)) from exc
    actual_sha256 = _sha256(data)
    if len(data) != size or actual_sha256 != sha256:
        raise PrivateReleaseError(
            "%s fingerprint drifted: %d / %s" % (label, len(data), actual_sha256)
        )
    return data


def _read_source_manifest():
    try:
        payload = json.loads(SOURCE_MANIFEST.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PrivateReleaseError("cannot read V80 source manifest: %s" % exc) from exc
    expected = {
        "schema": "v80-source/2",
        "contract": "independent_v80_modular",
        "id": PRIVATE_ID,
        "version": PRIVATE_VERSION,
        "entry": CANONICAL_SOURCE.name,
        "expected_size": SOURCE_SIZE,
        "expected_sha256": SOURCE_SHA256,
    }
    for key, value in expected.items():
        if payload.get(key) != value:
            raise PrivateReleaseError("V80 source manifest field drifted: %s" % key)
    baseline = payload.get("baseline")
    if not isinstance(baseline, dict):
        raise PrivateReleaseError("V80 modular baseline is missing")
    if baseline.get("path") != BASELINE_SOURCE.relative_to(ROOT).as_posix():
        raise PrivateReleaseError("V80 modular baseline path drifted")
    if not isinstance(baseline.get("bytes"), int) or not isinstance(baseline.get("sha256"), str):
        raise PrivateReleaseError("V80 modular baseline fingerprint is invalid")
    lineage = payload.get("release_lineage")
    if not isinstance(lineage, dict):
        raise PrivateReleaseError("V80 release lineage is missing")
    if lineage.get("schema") != "v80-release-lineage/1":
        raise PrivateReleaseError("V80 release lineage schema drifted")
    if lineage.get("strategy") != "frozen_v80_baseline_plus_owner_deltas":
        raise PrivateReleaseError("V80 release lineage strategy drifted")
    if lineage.get("policy") != {
        "historical_packages_immutable": True,
        "baseline_writable": False,
        "owner_files_are_development_source": True,
        "canonical_and_staging_are_generated": True,
    }:
        raise PrivateReleaseError("V80 release lineage policy drifted")
    versions = lineage.get("versions")
    if not isinstance(versions, list) or [item.get("version") for item in versions] != [80, 81, 82, 83, 84, 85, 86, 87, 88, 89, 90]:
        raise PrivateReleaseError("V80 release lineage versions drifted")
    for item in versions:
        if not isinstance(item, dict):
            raise PrivateReleaseError("V80 release lineage entry is invalid")
        if not isinstance(item.get("bytes"), int) or item["bytes"] <= 0:
            raise PrivateReleaseError("V80 release lineage bytes are invalid")
        if not isinstance(item.get("sha256"), str) or len(item["sha256"]) != 64:
            raise PrivateReleaseError("V80 release lineage SHA256 is invalid")
        evidence = item.get("evidence")
        if evidence is not None and (
                not isinstance(evidence, dict)
                or not isinstance(evidence.get("path"), str)
                or not isinstance(evidence.get("sha256"), str)
                or len(evidence["sha256"]) != 64):
            raise PrivateReleaseError("V80 release lineage evidence is invalid")
    frozen = versions[0]
    if frozen.get("role") != "frozen_baseline":
        raise PrivateReleaseError("V80 frozen baseline role drifted")
    if frozen.get("source") != BASELINE_SOURCE.relative_to(ROOT).as_posix():
        raise PrivateReleaseError("V80 frozen baseline source drifted")
    if frozen.get("bytes") != baseline["bytes"] or frozen.get("sha256") != baseline["sha256"]:
        raise PrivateReleaseError("V80 frozen lineage fingerprint differs from baseline")
    candidate = versions[-1]
    generated_from = candidate.get("generated_from")
    if (
            candidate.get("role") != "generated_candidate"
            or candidate.get("bytes") != SOURCE_SIZE
            or candidate.get("sha256") != SOURCE_SHA256
            or not isinstance(generated_from, dict)
            or generated_from.get("baseline_version") != 80
            or generated_from.get("owners") != list(OWNER_KEYS)):
        raise PrivateReleaseError("V80 generated lineage entry drifted")
    owners = payload.get("source_owners")
    if not isinstance(owners, dict):
        raise PrivateReleaseError("V80 source owners are missing")
    for key in OWNER_KEYS:
        owner = owners.get(key)
        if not isinstance(owner, dict):
            raise PrivateReleaseError("V80 source owner is missing: %s" % key)
        if not isinstance(owner.get("path"), str):
            raise PrivateReleaseError("V80 source owner path is missing: %s" % key)
        if not isinstance(owner.get("bytes"), int) or owner["bytes"] <= 0:
            raise PrivateReleaseError("V80 source owner bytes are invalid: %s" % key)
        if not isinstance(owner.get("sha256"), str) or len(owner["sha256"]) != 64:
            raise PrivateReleaseError("V80 source owner SHA256 is invalid: %s" % key)
    filter_owner = owners.get("filter_normalization")
    expected_filter = {
        "path": FILTER_OWNER.relative_to(ROOT).as_posix(),
        "methods": ["%s.%s" % value for value in FILTER_OWNER_METHODS],
    }
    if not isinstance(filter_owner, dict):
        raise PrivateReleaseError("V80 filter source owner is missing")
    for key, value in expected_filter.items():
        if filter_owner.get(key) != value:
            raise PrivateReleaseError("V80 filter source owner field drifted: %s" % key)
    if not isinstance(filter_owner.get("bytes"), int) or filter_owner["bytes"] <= 0:
        raise PrivateReleaseError("V80 filter source owner bytes are invalid")
    if not isinstance(filter_owner.get("sha256"), str) or len(filter_owner["sha256"]) != 64:
        raise PrivateReleaseError("V80 filter source owner SHA256 is invalid")
    return payload


def _class_methods(source, filename):
    try:
        tree = ast.parse(source.decode("utf-8"), filename=str(filename))
    except (UnicodeError, SyntaxError) as exc:
        raise PrivateReleaseError("cannot parse V80 source owner contract: %s" % exc) from exc
    methods = {}
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        for child in node.body:
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                key = (node.name, child.name)
                if key in methods:
                    raise PrivateReleaseError("duplicate V80 owner method: %s.%s" % key)
                methods[key] = child
    return methods


def _verify_filter_owner(canonical_source, source_manifest):
    owner = source_manifest["source_owners"]["filter_normalization"]
    owner_source = _read_pinned(
        FILTER_OWNER, owner["bytes"], owner["sha256"], "V80 filter source owner",
    )
    owner_methods = _class_methods(owner_source, FILTER_OWNER)
    canonical_methods = _class_methods(canonical_source, CANONICAL_SOURCE)
    if set(owner_methods) != set(FILTER_OWNER_METHODS):
        raise PrivateReleaseError("V80 filter source owner method set drifted")
    for key in FILTER_OWNER_METHODS:
        canonical_method = canonical_methods.get(key)
        if canonical_method is None:
            raise PrivateReleaseError("canonical V80 filter method is missing: %s.%s" % key)
        if ast.dump(owner_methods[key], include_attributes=False) != ast.dump(
            canonical_method, include_attributes=False,
        ):
            raise PrivateReleaseError(
                "V80 filter source owner differs from canonical method: %s.%s" % key
            )
    return owner_source


def _build_modular_source(source_manifest):
    baseline = source_manifest["baseline"]
    source = _read_pinned(
        BASELINE_SOURCE, baseline["bytes"], baseline["sha256"], "V80 modular baseline",
    ).decode("utf-8")
    replacements = []
    owner_bytes = {}
    owners = source_manifest["source_owners"]
    for key in OWNER_KEYS:
        owner = owners[key]
        path = ROOT / owner["path"]
        data = _read_pinned(path, owner["bytes"], owner["sha256"], "V80 source owner %s" % key)
        owner_bytes[key] = data
        try:
            payload = json.loads(data.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise PrivateReleaseError("V80 source owner is not valid JSON: %s" % key) from exc
        if payload.get("schema") != "v80-source-owner/1" or payload.get("key") != key:
            raise PrivateReleaseError("V80 source owner contract drifted: %s" % key)
        for replacement in payload.get("replacements") or []:
            if not isinstance(replacement, dict):
                raise PrivateReleaseError("V80 source owner replacement is invalid: %s" % key)
            order = replacement.get("order")
            before = replacement.get("before")
            after = replacement.get("after")
            if not isinstance(order, int) or not isinstance(before, str) or not isinstance(after, str):
                raise PrivateReleaseError("V80 source owner replacement fields are invalid: %s" % key)
            replacements.append((order, key, before, after))
    orders = [item[0] for item in replacements]
    if len(orders) != len(set(orders)):
        raise PrivateReleaseError("V80 source owner replacement order is duplicated")
    for _order, key, before, after in sorted(replacements, key=lambda item: item[0]):
        count = source.count(before)
        if count != 1:
            raise PrivateReleaseError("V80 source owner anchor count %d: %s" % (count, key))
        source = source.replace(before, after, 1)
    result = source.encode("utf-8")
    if len(result) != SOURCE_SIZE or _sha256(result) != SOURCE_SHA256:
        raise PrivateReleaseError(
            "V80 modular output fingerprint mismatch: %d / %s" % (len(result), _sha256(result))
        )
    return result, owner_bytes


def build_private_release():
    source_manifest = _read_source_manifest()
    canonical_source, owner_bytes = _build_modular_source(source_manifest)
    filter_owner = _verify_filter_owner(canonical_source, source_manifest)
    index_payload = [{
        "id": PRIVATE_ID,
        "file": "staging/" + CANONICAL_SOURCE.name,
        "version": PRIVATE_VERSION,
        "valid": True,
    }]
    index_bytes = _json_bytes(index_payload)
    manifest_payload = {
        "schema": "v80-private-release/3",
        "contract": "independent_v80_modular",
        "id": PRIVATE_ID,
        "version": PRIVATE_VERSION,
        "build": {
            "baseline": source_manifest["baseline"],
            "owner_order": list(OWNER_KEYS),
            "canonical_is_generated": True,
            "canonical_is_source_input": False,
        },
        "release_lineage": source_manifest["release_lineage"],
        "canonical_source": {
            "path": CANONICAL_SOURCE.relative_to(ROOT).as_posix(),
            "manifest": SOURCE_MANIFEST.relative_to(ROOT).as_posix(),
            "bytes": len(canonical_source),
            "sha256": _sha256(canonical_source),
        },
        "staged_source": {
            "path": STAGED_SOURCE.relative_to(ROOT).as_posix(),
            "bytes": len(canonical_source),
            "sha256": _sha256(canonical_source),
            "byte_identical_to_canonical": True,
        },
        "private_index": {
            "path": PRIVATE_INDEX.relative_to(ROOT).as_posix(),
            "bytes": len(index_bytes),
            "sha256": _sha256(index_bytes),
            "file_is_relative_to_index": True,
        },
        "compatibility_targets": source_manifest["compatibility_targets"],
        "source_owners": source_manifest["source_owners"],
        "deployment": {
            "scope": "build_time_initial_state",
            "server": "not_executed_by_builder",
            "mumu": "not_executed_by_builder",
            "runtime_evidence": "tracked_outside_manifest",
        },
    }
    return {
        "canonical_path": CANONICAL_SOURCE,
        "canonical_bytes": canonical_source,
        "source_path": STAGED_SOURCE,
        "source_bytes": canonical_source,
        "index_path": PRIVATE_INDEX,
        "index_bytes": index_bytes,
        "manifest_path": PRIVATE_MANIFEST,
        "manifest_bytes": _json_bytes(manifest_payload),
        "manifest": manifest_payload,
        "source_manifest": source_manifest,
        "filter_owner": filter_owner,
        "owner_bytes": owner_bytes,
    }


def _atomic_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_bytes(data)
    os.replace(str(temp), str(path))


def write_private_release():
    result = build_private_release()
    _atomic_write(result["canonical_path"], result["canonical_bytes"])
    _atomic_write(result["source_path"], result["source_bytes"])
    _atomic_write(result["index_path"], result["index_bytes"])
    _atomic_write(result["manifest_path"], result["manifest_bytes"])
    return result


def check_private_release():
    result = build_private_release()
    for path_key, bytes_key in (
        ("canonical_path", "canonical_bytes"),
        ("source_path", "source_bytes"),
        ("index_path", "index_bytes"),
        ("manifest_path", "manifest_bytes"),
    ):
        path = result[path_key]
        try:
            current = path.read_bytes()
        except OSError as exc:
            raise PrivateReleaseError("cannot read staged artifact %s: %s" % (path, exc)) from exc
        if current != result[bytes_key]:
            raise PrivateReleaseError("staged artifact differs from fixed build: %s" % path)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--write", action="store_true")
    action.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = check_private_release() if args.check else write_private_release()
    except PrivateReleaseError as exc:
        print("private release error: %s" % exc)
        return 1
    verb = "checked" if args.check else "written"
    print(
        "%s: %s / version %d / %d bytes / SHA256 %s"
        % (verb, PRIVATE_ID, PRIVATE_VERSION, len(result["source_bytes"]), _sha256(result["source_bytes"]))
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

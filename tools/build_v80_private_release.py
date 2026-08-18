"""Build or verify the fixed private-only V80 staging package."""

import argparse
import hashlib
import json
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PRIVATE_ROOT = ROOT / "private" / "v80"
PRIVATE_INDEX = PRIVATE_ROOT / "spiders_v2.json"
PRIVATE_MANIFEST = PRIVATE_ROOT / "private-release.json"
PUBLIC_V70 = ROOT / "py" / "豆瓣TMDB追更单入口.py"
PUBLIC_INDEX = ROOT / "spiders_v2.json"
EVIDENCE = ROOT / "work" / "v80-p2-controlled-output-switch-evidence-20260818.json"

PRIVATE_ID = "douban_tmdb_follow_single_v80_private"
PRIVATE_VERSION = 80
CANDIDATE_SIZE = 870797
CANDIDATE_SHA256 = "0CEBC73A78BCC8C7853A6BD0F0C78F4D95DD786C861425F9E0A4EC40FA0583F9"
PRIVATE_SOURCE_SIZE = 870801
PRIVATE_SOURCE_SHA256 = "049C722515F6851C379969C2886FA466EDD9FC9478B6B6F591E757DEEEDDCB97"
PUBLIC_V70_SIZE = 616699
PUBLIC_V70_SHA256 = "233C73CAE1048210B34872D4A10EA6023662300F70A8657DB82EA65C342182D4"
PUBLIC_INDEX_SIZE = 230
PUBLIC_INDEX_SHA256 = "436AD14B4CA2E2B5241C90F4FC10973B866FB06E950488C60362EB12ADEB7445"
EVIDENCE_SHA256 = "40167BAF2EFDDAAC9F52D43AAFEAD70C55D3171EEC0051A59BBAC409FD2313E3"


class PrivateReleaseError(RuntimeError):
    pass


def _sha256(data):
    return hashlib.sha256(data).hexdigest().upper()


def _json_bytes(payload):
    return (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _candidate_path():
    matches = list((ROOT / "build" / "v80-dev").glob("*.py"))
    if len(matches) != 1:
        raise PrivateReleaseError("expected exactly one V80 development candidate")
    return matches[0]


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


def _private_source_bytes(candidate):
    replacements = (
        (
            "//@name:豆瓣TMDB追更助手（AList-TVBox专用）".encode("utf-8"),
            "//@name:豆瓣TMDB追更助手（V80私有）".encode("utf-8"),
        ),
        (
            b"//@id:douban_tmdb_follow_single",
            b"//@id:douban_tmdb_follow_single_v80_private",
        ),
        (b"//@version:70", b"//@version:80"),
    )
    staged = candidate
    for old, new in replacements:
        if staged.count(old) != 1:
            raise PrivateReleaseError("private metadata anchor must appear exactly once")
        staged = staged.replace(old, new)
    if len(staged) != PRIVATE_SOURCE_SIZE or _sha256(staged) != PRIVATE_SOURCE_SHA256:
        raise PrivateReleaseError("private source fingerprint drifted")
    return staged


def build_private_release():
    candidate_path = _candidate_path()
    candidate = _read_pinned(
        candidate_path, CANDIDATE_SIZE, CANDIDATE_SHA256, "V80 candidate",
    )
    public_v70 = _read_pinned(
        PUBLIC_V70, PUBLIC_V70_SIZE, PUBLIC_V70_SHA256, "public V70",
    )
    public_index = _read_pinned(
        PUBLIC_INDEX, PUBLIC_INDEX_SIZE, PUBLIC_INDEX_SHA256, "public index",
    )
    evidence = _read_pinned(
        EVIDENCE, EVIDENCE.stat().st_size, EVIDENCE_SHA256, "controlled-switch evidence",
    )
    staged_source = _private_source_bytes(candidate)
    staged_path = PRIVATE_ROOT / "staging" / candidate_path.name
    index_payload = [{
        "id": PRIVATE_ID,
        "file": "staging/" + candidate_path.name,
        "version": PRIVATE_VERSION,
        "valid": True,
    }]
    index_bytes = _json_bytes(index_payload)
    manifest_payload = {
        "schema": "v80-private-release/1",
        "contract": "private_v80_only",
        "id": PRIVATE_ID,
        "version": PRIVATE_VERSION,
        "source_candidate": {
            "path": candidate_path.relative_to(ROOT).as_posix(),
            "bytes": len(candidate),
            "sha256": _sha256(candidate),
        },
        "staged_source": {
            "path": staged_path.relative_to(ROOT).as_posix(),
            "bytes": len(staged_source),
            "sha256": _sha256(staged_source),
        },
        "private_index": {
            "path": PRIVATE_INDEX.relative_to(ROOT).as_posix(),
            "bytes": len(index_bytes),
            "sha256": _sha256(index_bytes),
            "file_is_relative_to_index": True,
        },
        "controlled_switch": {
            "default_enabled": False,
            "required_extend": {
                "atvp_plugin_mode": "alist-tvbox-raw",
                "v80_resource_layered_output": True,
            },
        },
        "public_v70": {
            "path": PUBLIC_V70.relative_to(ROOT).as_posix(),
            "bytes": len(public_v70),
            "sha256": _sha256(public_v70),
            "modified": False,
        },
        "public_index": {
            "path": PUBLIC_INDEX.relative_to(ROOT).as_posix(),
            "bytes": len(public_index),
            "sha256": _sha256(public_index),
            "modified": False,
        },
        "evidence": {
            "path": EVIDENCE.relative_to(ROOT).as_posix(),
            "bytes": len(evidence),
            "sha256": _sha256(evidence),
        },
        "deployment": {
            "server": "not_executed",
            "mumu": "not_executed",
            "public_v70_rollback": "not_applicable",
        },
    }
    manifest_bytes = _json_bytes(manifest_payload)
    return {
        "source_path": staged_path,
        "source_bytes": staged_source,
        "index_path": PRIVATE_INDEX,
        "index_bytes": index_bytes,
        "manifest_path": PRIVATE_MANIFEST,
        "manifest_bytes": manifest_bytes,
        "manifest": manifest_payload,
    }


def _atomic_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_bytes(data)
    os.replace(str(temp), str(path))


def write_private_release():
    result = build_private_release()
    _atomic_write(result["source_path"], result["source_bytes"])
    _atomic_write(result["index_path"], result["index_bytes"])
    _atomic_write(result["manifest_path"], result["manifest_bytes"])
    return result


def check_private_release():
    result = build_private_release()
    for path_key, bytes_key in (
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

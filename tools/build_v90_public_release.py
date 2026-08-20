"""Generate the public V90 repository artifacts from the modular V80 source."""

import argparse
import hashlib
import json
import os
from pathlib import Path

import build_v80_private_release as modular_builder


ROOT = Path(__file__).resolve().parents[1]
PUBLIC_SOURCE = ROOT / "py" / "豆瓣TMDB追更单入口.py"
PUBLIC_INDEX = ROOT / "spiders_v2.json"
PUBLIC_MANIFEST = ROOT / "plugins" / "douban_tmdb_follow_single" / "public-release.json"

PUBLIC_ID = "douban_tmdb_follow_single"
PUBLIC_VERSION = 90
PUBLIC_SIZE = 981711
PUBLIC_SHA256 = "C5FA2CDD02ABAC809099769758D8CE50053C9AE09D11DDAA0F65719AD12ECA82"

METADATA_REPLACEMENTS = (
    (
        "//@name:豆瓣TMDB追更助手（V80.1私有 v90）",
        "//@name:豆瓣TMDB追更助手 v90",
    ),
    (
        "//@id:douban_tmdb_follow_single_v80_private",
        "//@id:douban_tmdb_follow_single",
    ),
    (
        '    name = "豆瓣TMDB追更助手（V80.1私有 v90）"',
        '    name = "豆瓣TMDB追更助手 v90"',
    ),
)


class PublicReleaseError(RuntimeError):
    pass


def _sha256(data):
    return hashlib.sha256(data).hexdigest().upper()


def _json_bytes(payload):
    return (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _public_source(canonical_source):
    try:
        source = canonical_source.decode("utf-8")
    except UnicodeError as exc:
        raise PublicReleaseError("V90 canonical source is not UTF-8") from exc
    for before, after in METADATA_REPLACEMENTS:
        count = source.count(before)
        if count != 1:
            raise PublicReleaseError(
                "public metadata anchor count %d: %s" % (count, before)
            )
        source = source.replace(before, after, 1)
    result = source.encode("utf-8")
    if len(result) != PUBLIC_SIZE or _sha256(result) != PUBLIC_SHA256:
        raise PublicReleaseError(
            "public V90 fingerprint mismatch: %d / %s"
            % (len(result), _sha256(result))
        )
    return result


def build_public_release():
    modular = modular_builder.build_private_release()
    canonical_source = modular["canonical_bytes"]
    source_bytes = _public_source(canonical_source)
    index_payload = [
        {
            "id": PUBLIC_ID,
            "file": "py/豆瓣TMDB追更单入口.py",
            "version": PUBLIC_VERSION,
            "valid": True,
        },
        {
            "id": "seedhub",
            "file": "py/SeedHub.py",
            "version": 1,
            "valid": True,
        },
    ]
    index_bytes = _json_bytes(index_payload)
    manifest_payload = {
        "schema": "v90-public-release/1",
        "id": PUBLIC_ID,
        "version": PUBLIC_VERSION,
        "architecture": {
            "development": "modular owners",
            "runtime": "single generated Python file",
            "public_source_is_generated": True,
            "canonical_and_private_staging_are_not_edited": True,
        },
        "built_from": {
            "path": modular["canonical_path"].relative_to(ROOT).as_posix(),
            "bytes": len(canonical_source),
            "sha256": _sha256(canonical_source),
            "owner_order": list(modular_builder.OWNER_KEYS),
        },
        "public_source": {
            "path": PUBLIC_SOURCE.relative_to(ROOT).as_posix(),
            "bytes": len(source_bytes),
            "sha256": _sha256(source_bytes),
        },
        "public_index": {
            "path": PUBLIC_INDEX.relative_to(ROOT).as_posix(),
            "bytes": len(index_bytes),
            "sha256": _sha256(index_bytes),
        },
        "compatibility": modular["manifest"]["compatibility_targets"],
        "evidence": {
            "targeted_contracts": "20 passed",
            "atvp_direct_play": "work/v90-public-atvp-direct-play-20260820.json",
            "fongmi_dual_runtime": "work/v90-public-dual-runtime-20260820.json",
            "closure": "work/v90-selective-tmdb-hedge-closure-20260820.json",
        },
    }
    manifest_bytes = _json_bytes(manifest_payload)
    return {
        "source_path": PUBLIC_SOURCE,
        "source_bytes": source_bytes,
        "index_path": PUBLIC_INDEX,
        "index_bytes": index_bytes,
        "manifest_path": PUBLIC_MANIFEST,
        "manifest_bytes": manifest_bytes,
        "manifest_payload": manifest_payload,
    }


def _atomic_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp-v90")
    try:
        temporary.write_bytes(data)
        os.replace(str(temporary), str(path))
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def write_public_release():
    result = build_public_release()
    _atomic_write(result["source_path"], result["source_bytes"])
    _atomic_write(result["index_path"], result["index_bytes"])
    _atomic_write(result["manifest_path"], result["manifest_bytes"])
    return result


def check_public_release():
    result = build_public_release()
    for path_key, bytes_key in (
        ("source_path", "source_bytes"),
        ("index_path", "index_bytes"),
        ("manifest_path", "manifest_bytes"),
    ):
        path = result[path_key]
        try:
            actual = path.read_bytes()
        except OSError as exc:
            raise PublicReleaseError("cannot read public artifact %s" % path) from exc
        if actual != result[bytes_key]:
            raise PublicReleaseError("public artifact drifted: %s" % path)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    result = write_public_release() if args.write else check_public_release()
    print(
        "%s %d bytes %s"
        % (
            result["source_path"].relative_to(ROOT),
            len(result["source_bytes"]),
            _sha256(result["source_bytes"]),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

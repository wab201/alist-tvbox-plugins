#!/usr/bin/env python3
"""Verify the official AList-TVBox 1.51.1 leaf from pinned GitHub evidence."""

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
BASE_VERIFIER_PATH = HERE / "verify_alist_tvbox_1500_contract.py"
DEFAULT_EVIDENCE = (
    HERE.parent / "work" / "v80-upstream-1511-github-evidence-20260818.json"
)


def _load_base_verifier():
    spec = importlib.util.spec_from_file_location(
        "alist_tvbox_1500_contract", BASE_VERIFIER_PATH,
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BASE = _load_base_verifier()
DEFAULT_LEGACY_VERIFIER = BASE.DEFAULT_LEGACY_VERIFIER

EXPECTED_EVIDENCE_SHA256 = (
    "E6AF69979CDF5587592ABD33000CC9EACDFAA9077FE70B93062BC9CB4AD3DF1B"
)
EXPECTED_TAG = "1.51.1"
EXPECTED_COMMIT = "47432df300c1ee54e799fe9c7a3eb169823c2f0e"
EXPECTED_BASE_TAG = "1.50.0"
EXPECTED_BASE_COMMIT = "7ba1119e1e71bb427fb281f534a4c111ff7b500c"
EXPECTED_PUBLISHED_AT = "2026-08-18T12:39:48Z"
EXPECTED_RELEASE_DELTA = (
    "RELEASE_NOTES.md",
    "src/main/java/cn/har01d/alist_tvbox/config/AppProperties.java",
    "src/main/java/cn/har01d/alist_tvbox/config/WebSecurityConfiguration.java",
    "src/main/java/cn/har01d/alist_tvbox/dto/qqmusic/QqMusicLoginStatus.java",
    "src/main/java/cn/har01d/alist_tvbox/dto/qqmusic/QqMusicQrCode.java",
    "src/main/java/cn/har01d/alist_tvbox/entity/PlaybackTombstoneRepository.java",
    "src/main/java/cn/har01d/alist_tvbox/model/PluginFilterConfigField.java",
    "src/main/java/cn/har01d/alist_tvbox/service/PlaybackSyncService.java",
    "src/main/java/cn/har01d/alist_tvbox/service/QqMusicService.java",
    "src/main/java/cn/har01d/alist_tvbox/util/ConfigSchemaParser.java",
    "src/main/java/cn/har01d/alist_tvbox/web/PlaybackSyncController.java",
    "src/main/java/cn/har01d/alist_tvbox/web/QqMusicController.java",
    "src/main/resources/META-INF/native-image/reflect-config.json",
    "src/test/java/cn/har01d/alist_tvbox/service/PlaybackSyncServiceTest.java",
    "src/test/java/cn/har01d/alist_tvbox/service/QqMusicServiceTest.java",
    "src/test/java/cn/har01d/alist_tvbox/util/ConfigSchemaParserTest.java",
    "web-ui/src/components/PluginFilterConfigFieldEditor.vue",
    "web-ui/src/components/QqMusicQrLoginDialog.vue",
    "web-ui/src/views/SubscriptionsView.test.mjs",
    "web-ui/src/views/SubscriptionsView.vue",
)
EXPECTED_ADDED_PATHS = frozenset((
    "src/main/java/cn/har01d/alist_tvbox/dto/qqmusic/QqMusicLoginStatus.java",
    "src/main/java/cn/har01d/alist_tvbox/dto/qqmusic/QqMusicQrCode.java",
    "src/main/java/cn/har01d/alist_tvbox/service/QqMusicService.java",
    "src/main/java/cn/har01d/alist_tvbox/web/QqMusicController.java",
    "src/test/java/cn/har01d/alist_tvbox/service/QqMusicServiceTest.java",
    "web-ui/src/components/QqMusicQrLoginDialog.vue",
))
EXPECTED_UNCHANGED_BLOBS = {
    "src/main/resources/static/Atvp.py": (
        "9d47b50a6160a4301b37865a14f212e77165f84f"
    ),
    "src/main/resources/static/spring.jar": (
        "408f78f43a2603a5ca6edb147a11bbb887094bf3"
    ),
    "src/main/java/cn/har01d/alist_tvbox/entity/History.java": (
        "71aa330238387555a72bd19999a3e72f05b11b2e"
    ),
    "src/main/java/cn/har01d/alist_tvbox/dto/playback/PlaybackSyncInput.java": (
        "e4aaaca32316d7a3cc4aca9c009924bae7bac63c"
    ),
    "src/main/java/cn/har01d/alist_tvbox/service/PluginService.java": (
        "7ae6d7b0642ff042fe98ba7d7881c2a107412e0c"
    ),
    "src/main/java/cn/har01d/alist_tvbox/service/SubscriptionService.java": (
        "ad8f4577edbe415bae67d573d6a8ad2002192785"
    ),
}
EXPECTED_CHANGED_BLOBS = {
    "src/main/java/cn/har01d/alist_tvbox/config/AppProperties.java": (
        "bef18950728233c169347397fd54deb2da447fd5"
    ),
    "src/main/java/cn/har01d/alist_tvbox/config/WebSecurityConfiguration.java": (
        "5cbb8cb6f000f0b38d348ab58c75ef7aec6ad9c5"
    ),
    "src/main/java/cn/har01d/alist_tvbox/entity/PlaybackTombstoneRepository.java": (
        "d4c4630f47544a35355542007adeab6def6b5911"
    ),
    "src/main/java/cn/har01d/alist_tvbox/model/PluginFilterConfigField.java": (
        "c5538ace7494a5cb45de32f0165a686d634cbe54"
    ),
    "src/main/java/cn/har01d/alist_tvbox/service/PlaybackSyncService.java": (
        "081de7285e0d010ef0a0c77fce85e3dcd39abeb2"
    ),
    "src/main/java/cn/har01d/alist_tvbox/util/ConfigSchemaParser.java": (
        "4a9c9e1d04e7205528fd166202aee3f1f7032212"
    ),
    "src/main/java/cn/har01d/alist_tvbox/web/PlaybackSyncController.java": (
        "b3e9d563c5638613cf7507e9b5cc4bf3453aeb78"
    ),
}
EXPECTED_SEMANTIC_MARKERS = {
    "release_notes_multi_device_playback_fix": True,
    "playback_delete_throttle_default_ms": 600000,
    "delete_echo_suppression": True,
    "cross_scope_tombstone_purge": True,
    "tombstone_admin_endpoint": "/api/playback/tombstones/-/delete",
    "tombstone_endpoint_requires_user_or_admin": True,
    "plugin_config_list_type": True,
    "qqmusic_qr_login": True,
}
EXPECTED_SOURCES = {
    "release_api": (
        "https://api.github.com/repos/power721/alist-tvbox/releases/tags/1.51.1"
    ),
    "tag_api": (
        "https://api.github.com/repos/power721/alist-tvbox/git/ref/tags/1.51.1"
    ),
    "compare_api": (
        "https://api.github.com/repos/power721/alist-tvbox/compare/1.50.0...1.51.1"
    ),
}


def inherited_1500_compatibility_ok(payload):
    if not isinstance(payload, dict) or payload.get("ok") is not True:
        return False
    checks = payload.get("checks")
    declared = payload.get("failures")
    if not isinstance(checks, list) or not isinstance(declared, list):
        return False
    if any(
        not isinstance(row, dict)
        or not isinstance(row.get("name"), str)
        or type(row.get("ok")) is not bool
        for row in checks
    ):
        return False
    names = [row["name"] for row in checks]
    failures = [row["name"] for row in checks if row["ok"] is not True]
    return (
        len(names) == len(set(names))
        and declared == failures
        and not failures
    )


def _read_evidence(path):
    try:
        payload = Path(path).read_bytes()
    except OSError as exc:
        return {}, "", str(exc)
    digest = hashlib.sha256(payload).hexdigest().upper()
    try:
        return json.loads(payload.decode("utf-8")), digest, None
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return {}, digest, str(exc)


def verify(
        root, evidence_path=DEFAULT_EVIDENCE,
        legacy_verifier=DEFAULT_LEGACY_VERIFIER):
    root = Path(root).resolve()
    evidence_path = Path(evidence_path).resolve()
    checks = []

    def add(name, ok, detail=None):
        row = {"name": name, "ok": bool(ok)}
        if detail not in (None, ""):
            row["detail"] = str(detail)
        checks.append(row)

    inherited = BASE.verify(root, legacy_verifier)
    inherited_ok = inherited_1500_compatibility_ok(inherited)
    add(
        "exact AList-TVBox 1.50.0 base contract remains green",
        inherited_ok,
        ", ".join(inherited.get("failures") or ()),
    )

    evidence, evidence_sha256, evidence_error = _read_evidence(evidence_path)
    add("GitHub evidence JSON is readable", evidence_error is None, evidence_error)
    add(
        "GitHub evidence SHA256 matches the fixed 1.51.1 capture",
        evidence_sha256 == EXPECTED_EVIDENCE_SHA256,
        evidence_sha256,
    )
    add(
        "GitHub evidence schema and repository are exact",
        evidence.get("schema") == "alist-tvbox-1.51.1-github-evidence/1"
        and evidence.get("repository") == "power721/alist-tvbox",
    )

    release = evidence.get("release") if isinstance(evidence, dict) else None
    add(
        "official release tag, commit and publication time match 1.51.1",
        isinstance(release, dict)
        and release.get("tag") == EXPECTED_TAG
        and release.get("commit") == EXPECTED_COMMIT
        and release.get("published_at") == EXPECTED_PUBLISHED_AT
        and release.get("target_commitish") == "master",
        json.dumps(release, sort_keys=True) if isinstance(release, dict) else None,
    )

    compare = evidence.get("compare") if isinstance(evidence, dict) else None
    add(
        "1.50.0 to 1.51.1 compare metadata is exact",
        isinstance(compare, dict)
        and compare.get("base_tag") == EXPECTED_BASE_TAG
        and compare.get("base_commit") == EXPECTED_BASE_COMMIT
        and compare.get("status") == "ahead"
        and compare.get("ahead_by") == 6
        and compare.get("behind_by") == 0
        and compare.get("total_commits") == 6,
    )
    file_rows = compare.get("files") if isinstance(compare, dict) else None
    rows_valid = (
        isinstance(file_rows, list)
        and all(
            isinstance(row, dict)
            and isinstance(row.get("path"), str)
            and isinstance(row.get("status"), str)
            and isinstance(row.get("blob"), str)
            and len(row["blob"]) == 40
            for row in file_rows
        )
    )
    release_delta = tuple(row["path"] for row in file_rows) if rows_valid else ()
    added_paths = frozenset(
        row["path"] for row in file_rows if row["status"] == "added"
    ) if rows_valid else frozenset()
    statuses_valid = rows_valid and all(
        row["status"] == ("added" if row["path"] in EXPECTED_ADDED_PATHS else "modified")
        for row in file_rows
    )
    add(
        "1.50.0 to 1.51.1 changed-file set is exactly 20 paths",
        rows_valid
        and len(release_delta) == len(set(release_delta))
        and release_delta == EXPECTED_RELEASE_DELTA,
        ", ".join(release_delta),
    )
    add(
        "1.50.0 to 1.51.1 added-file set is exactly 6 paths",
        statuses_valid and added_paths == EXPECTED_ADDED_PATHS,
        ", ".join(sorted(added_paths)),
    )

    unchanged = evidence.get("unchanged_owner_blobs") if isinstance(evidence, dict) else None
    changed = evidence.get("changed_owner_blobs") if isinstance(evidence, dict) else None
    add(
        "raw plugin, spring.jar, History and stable service owners are unchanged",
        unchanged == EXPECTED_UNCHANGED_BLOBS,
        json.dumps(unchanged, sort_keys=True) if isinstance(unchanged, dict) else None,
    )
    add(
        "playback tombstone and plugin list-schema changed owners are pinned",
        changed == EXPECTED_CHANGED_BLOBS,
        json.dumps(changed, sort_keys=True) if isinstance(changed, dict) else None,
    )
    add(
        "1.51.1 playback, tombstone, list-schema and QQ Music markers are pinned",
        evidence.get("semantic_markers") == EXPECTED_SEMANTIC_MARKERS,
    )
    add(
        "evidence sources are the official GitHub release, tag and compare APIs",
        evidence.get("sources") == EXPECTED_SOURCES,
    )

    failures = [row["name"] for row in checks if not row["ok"]]
    return {
        "ok": not failures,
        "source_root": str(root),
        "evidence_path": str(evidence_path),
        "evidence_sha256": evidence_sha256,
        "release_contract": "AList-TVBox 1.51.1",
        "base_contract": "AList-TVBox 1.50.0",
        "expected_tag": EXPECTED_TAG,
        "expected_commit": EXPECTED_COMMIT,
        "expected_release_delta": list(EXPECTED_RELEASE_DELTA),
        "checks": checks,
        "failures": failures,
        "summary": {
            "legacy_raw_plugin_contract": "preserved" if inherited_ok else "failed",
            "playback_and_resume_contract": (
                "changed and pinned by official evidence" if not failures else "unverified"
            ),
            "release_scope": (
                "playback tombstone cleanup, plugin list schema and QQ Music QR login"
            ),
            "production_changes": False,
            "deployment_attempted": False,
        },
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_root", type=Path)
    parser.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE)
    parser.add_argument(
        "--legacy-verifier", type=Path, default=DEFAULT_LEGACY_VERIFIER,
    )
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args(argv)
    result = verify(args.source_root, args.evidence, args.legacy_verifier)
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

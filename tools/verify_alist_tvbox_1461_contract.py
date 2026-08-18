#!/usr/bin/env python3
"""Verify the AList-TVBox 1.46.1 source contract used by V80."""

import argparse
import hashlib
import importlib.util
import json
import re
import sys
import zipfile
from pathlib import Path


HERE = Path(__file__).resolve().parent
BASE_VERIFIER_PATH = HERE / "verify_alist_tvbox_1451_contract.py"


def _load_base_verifier():
    spec = importlib.util.spec_from_file_location(
        "alist_tvbox_1451_contract", BASE_VERIFIER_PATH,
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BASE = _load_base_verifier()
EXPECTED_TAG = "1.46.1"
EXPECTED_COMMIT = "8d601fd1e0fc25f92cca48e96a32bb0155046fd0"
EXPECTED_BASE_TAG = "1.45.1"
EXPECTED_BASE_COMMIT = "9cd22bb91bbaaf2bb4f4e0cd9b9d8da00841db81"
EXPECTED_1451_VERSION_FAILURES = frozenset((
    "release notes identify 1.45.1",
    "Git commit matches AList-TVBox 1.45.1",
    "Git tag matches AList-TVBox 1.45.1",
))
EXPECTED_RELEASE_DELTA = (
    "AGENTS.md",
    "RELEASE_NOTES.md",
    "src/main/java/cn/har01d/alist_tvbox/config/NativeFlywayMigrationConfig.java",
    "src/main/java/cn/har01d/alist_tvbox/dto/playback/PlaybackSyncInput.java",
    "src/main/java/cn/har01d/alist_tvbox/entity/History.java",
    "src/main/java/cn/har01d/alist_tvbox/service/PlaybackSyncService.java",
    "src/main/java/cn/har01d/alist_tvbox/service/SubscriptionService.java",
    "src/main/java/db/migration/current/V17__FixChangeSequenceWatermark.java",
    "src/main/java/db/migration/current/V18__PlaybackDrivePath.java",
    "src/main/resources/META-INF/services/org.flywaydb.core.api.migration.JavaMigration",
    "src/main/resources/static/Atvp.py",
    "src/main/resources/static/spring.jar",
    "src/main/resources/static/spring.md5",
    "src/test/java/cn/har01d/alist_tvbox/service/PlaybackSyncServiceTest.java",
    "src/test/java/cn/har01d/alist_tvbox/service/SubscriptionServiceTest.java",
    "web-ui/src/components/SubscriptionConfigEditor.vue",
)
EXPECTED_ATVP_BLOB = "9d47b50a6160a4301b37865a14f212e77165f84f"
EXPECTED_ATVP_CANONICAL_BYTES = 67750
EXPECTED_ATVP_CANONICAL_SHA256 = (
    "3C73B5CEA7276B0A26D56EDF8A2625CF15477BC905105A013DD62E1D328D4B34"
)
EXPECTED_SPRING_BLOB = "370a7069f6decb5226f49d9d657227f26cdadb98"
EXPECTED_SPRING_BYTES = 374208
EXPECTED_SPRING_SHA256 = (
    "BC68D079FA53B4087FDB5B7F1A69A8900AF4F4634AFEAD6C701541DDEBBC9DB9"
)
EXPECTED_SPRING_MD5 = "44d8a3a64d477459be90895825820861"
SPRING_RUNTIME_MARKERS = (
    b"PlaybackSyncer",
    b"PyProxy",
    b"playerContent",
    b"atvp_resume:",
    b"groupIndex",
    b"sourceIndex",
    b"subgroupIndex",
    b"subgroupName",
)


def _text(root, relative):
    return BASE._text(root, relative)


def _bytes(root, relative):
    return BASE._bytes(root, relative)


def _canonical_text_bytes(root, relative):
    text = _text(root, relative)
    return text.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")


def inherited_1451_compatibility_ok(payload):
    if not isinstance(payload, dict):
        return False
    return set(payload.get("failures") or ()) == EXPECTED_1451_VERSION_FAILURES


def spring_runtime_markers(spring_bytes):
    try:
        from io import BytesIO

        with zipfile.ZipFile(BytesIO(spring_bytes)) as archive:
            dex = archive.read("classes.dex")
    except (KeyError, OSError, zipfile.BadZipFile):
        return {marker.decode("ascii"): False for marker in SPRING_RUNTIME_MARKERS}
    return {
        marker.decode("ascii"): marker in dex
        for marker in SPRING_RUNTIME_MARKERS
    }


def _ordered(text, first, second):
    left = text.find(first)
    right = text.find(second)
    return left >= 0 and right > left


def verify(root, legacy_verifier=BASE.DEFAULT_LEGACY_VERIFIER):
    root = Path(root).resolve()
    checks = []

    def add(name, ok, detail=None):
        row = {"name": name, "ok": bool(ok)}
        if detail not in (None, ""):
            row["detail"] = str(detail)
        checks.append(row)

    inherited = BASE.verify(root, legacy_verifier)
    add(
        "1.45.1 contract remains green except expected release identity checks",
        inherited_1451_compatibility_ok(inherited),
        ", ".join(inherited.get("failures") or ()),
    )

    commit = BASE._git_value(root, "rev-parse", "HEAD")
    tag = BASE._git_value(root, "describe", "--tags", "--exact-match")
    add("Git checkout metadata is available", commit is not None)
    add("Git commit matches AList-TVBox 1.46.1", commit == EXPECTED_COMMIT, commit)
    add("Git tag matches AList-TVBox 1.46.1", tag == EXPECTED_TAG, tag)
    base_commit = BASE._git_value(root, "rev-parse", "%s^{commit}" % EXPECTED_BASE_TAG)
    add("1.45.1 base tag resolves to the pinned commit", base_commit == EXPECTED_BASE_COMMIT, base_commit)
    release_delta = tuple(filter(None, BASE._git_value(
        root, "diff", "--name-only", "%s..%s" % (EXPECTED_BASE_TAG, EXPECTED_TAG),
    ).splitlines()))
    add(
        "1.45.1 to 1.46.1 changed-file set is exact",
        release_delta == EXPECTED_RELEASE_DELTA,
        ", ".join(release_delta),
    )

    notes = _text(root, "RELEASE_NOTES.md")
    add("release notes identify 1.46.1", bool(re.search(
        r"(?m)^#\s+Release Notes\s+-\s+1\.46\.1\s*$", notes,
    )))
    add("release notes scope the change to playback synchronization", all(
        marker in notes for marker in (
            "修复播放记录同步问题",
            "续播 ID 携带多级导航信息",
            "播放历史新增记录网盘路径",
            "修复播放记录数据迁移的序列水位问题",
        )
    ))

    atvp_relative = "src/main/resources/static/Atvp.py"
    atvp = _text(root, atvp_relative)
    atvp_bytes = _canonical_text_bytes(root, atvp_relative)
    atvp_blob = BASE._git_value(root, "rev-parse", "HEAD:%s" % atvp_relative)
    add("Atvp.py Git blob matches 1.46.1", atvp_blob == EXPECTED_ATVP_BLOB, atvp_blob)
    add(
        "Atvp.py canonical LF bytes match 1.46.1",
        len(atvp_bytes) == EXPECTED_ATVP_CANONICAL_BYTES
        and hashlib.sha256(atvp_bytes).hexdigest().upper() == EXPECTED_ATVP_CANONICAL_SHA256,
        "%s bytes / %s" % (len(atvp_bytes), hashlib.sha256(atvp_bytes).hexdigest().upper()),
    )
    add("Atvp resume ids retain the legacy id plus playlist core", all(
        marker in atvp for marker in (
            'payload = {\n            "id": str(context.get("id") or ""),',
            '"playlist": int(context.get("playlist") or 0)',
            'context = {"id": source_id, "playlist": playlist_index}',
        )
    ))
    add("Atvp resume ids carry optional group, source and subgroup coordinates", all(
        marker in atvp for marker in (
            'for key in ("group", "source", "subgroup"):',
            'context[key] = int(value)',
            'payload["subgroupName"] = name',
            'context["subgroupName"] = name',
        )
    ))
    add("Atvp resume target prefers coordinates and falls back to flat playlist", all(
        marker in atvp for marker in (
            "def _select_resume_target(self, vod, context):",
            'group_index = context.get("group")',
            'source_index = context.get("source")',
            "targets = [target for media_urls in entries for target in media_urls]",
            'playlist_index = int(context.get("playlist") or 0)',
        )
    ))
    add("Atvp reorders the recorded subgroup before applying the resume id", all(
        marker in atvp for marker in (
            "def _reorder_resume_lines(self, parsed_result, context):",
            "parsed_result = self._reorder_resume_lines(parsed_result, context)",
            "parsed_result = self._apply_resume_context(parsed_result, context)",
        )
    ) and _ordered(
        atvp,
        "parsed_result = self._reorder_resume_lines(parsed_result, context)",
        "parsed_result = self._apply_resume_context(parsed_result, context)",
    ))

    input_dto = _text(
        root, "src/main/java/cn/har01d/alist_tvbox/dto/playback/PlaybackSyncInput.java"
    )
    history = _text(root, "src/main/java/cn/har01d/alist_tvbox/entity/History.java")
    service = _text(root, "src/main/java/cn/har01d/alist_tvbox/service/PlaybackSyncService.java")
    add("playback DTO accepts canonical drive share and path aliases", all(
        marker in input_dto for marker in (
            "private String driveShareKey;",
            "private String drivePath;",
            'str(m, "driveShareKey", "drive_share_key")',
            'str(m, "drivePath", "drive_path")',
        )
    ))
    add("History persists canonical drive share and path", all(
        marker in history for marker in (
            "private String driveShareKey;",
            "private String drivePath;",
            '@Column(columnDefinition = "TEXT")',
        )
    ))
    add("playback service canonicalizes drive ids through ProxyService", all(
        marker in service for marker in (
            "private final ProxyService proxyService;",
            "canonicalizeDrivePath(in);",
            "proxyService.getPath(id)",
            'path.indexOf("/temp/")',
            "in.setDriveShareKey(ref.shareKey());",
            "in.setDrivePath(ref.path());",
        )
    ))
    add("playback service clears stale navigation only for different content", all(
        marker in service for marker in (
            "isDifferentContent(in, exist)",
            "h.setSourceGroupIndex(null);",
            "h.setSourceIndex(null);",
            "h.setDriveDirId(null);",
            "Objects.equals(in.getDriveShareKey(), exist.getDriveShareKey())",
        )
    ))
    add("playback change sequence is monotonic above wall-clock time", (
        "Math.max(sequence.getNextVal() + 1, System.currentTimeMillis())" in service
    ))
    add("playback pull returns canonical drive share and path", all(
        marker in service for marker in (
            "in.setDriveShareKey(h.getDriveShareKey());",
            "in.setDrivePath(h.getDrivePath());",
        )
    ))

    migration_registry = _text(
        root, "src/main/resources/META-INF/services/org.flywaydb.core.api.migration.JavaMigration"
    )
    native_config = _text(
        root, "src/main/java/cn/har01d/alist_tvbox/config/NativeFlywayMigrationConfig.java"
    )
    for version, name in (
        (17, "FixChangeSequenceWatermark"),
        (18, "PlaybackDrivePath"),
    ):
        class_name = "db.migration.current.V%d__%s" % (version, name)
        relative = "src/main/java/%s.java" % class_name.replace(".", "/")
        add("migration source present: %s" % class_name, (root / relative).is_file())
        add("migration service registered: %s" % class_name, class_name in migration_registry)
        add("migration Native Image registered: %s" % class_name, (
            "new V%d__%s()" % (version, name) in native_config
        ))
    add("Native Flyway explicitly registers playback migrations V10 through V18", all(
        "new V%d__" % version in native_config for version in range(10, 19)
    ))

    subscription = _text(
        root, "src/main/java/cn/har01d/alist_tvbox/service/SubscriptionService.java"
    )
    add("subscription loader revision is resume-group-v1", (
        'ATVP_RUNTIME_REVISION = "resume-group-v1"' in subscription
    ))

    spring_relative = "src/main/resources/static/spring.jar"
    spring = _bytes(root, spring_relative)
    declared_md5 = _text(root, "src/main/resources/static/spring.md5").strip().lower()
    spring_sha256 = hashlib.sha256(spring).hexdigest().upper() if spring else ""
    spring_md5 = hashlib.md5(spring).hexdigest() if spring else ""
    spring_blob = BASE._git_value(root, "rev-parse", "HEAD:%s" % spring_relative)
    add("spring.jar Git blob matches 1.46.1", spring_blob == EXPECTED_SPRING_BLOB, spring_blob)
    add(
        "spring.jar bytes and SHA256 match 1.46.1",
        len(spring) == EXPECTED_SPRING_BYTES and spring_sha256 == EXPECTED_SPRING_SHA256,
        "%s bytes / %s" % (len(spring), spring_sha256),
    )
    add(
        "spring.jar MD5 matches both pinned and declared values",
        spring_md5 == EXPECTED_SPRING_MD5 and declared_md5 == EXPECTED_SPRING_MD5,
        "%s / %s" % (spring_md5, declared_md5),
    )
    marker_status = spring_runtime_markers(spring)
    add(
        "spring.jar keeps PyProxy/playerContent and adds multi-level resume markers",
        bool(marker_status) and all(marker_status.values()),
        json.dumps(marker_status, ensure_ascii=False, sort_keys=True),
    )

    playback_tests = _text(
        root, "src/test/java/cn/har01d/alist_tvbox/service/PlaybackSyncServiceTest.java"
    )
    subscription_tests = _text(
        root, "src/test/java/cn/har01d/alist_tvbox/service/SubscriptionServiceTest.java"
    )
    add("upstream tests cover changed-content clearing and canonical-path retention", all(
        marker in playback_tests for marker in (
            "crossClientPushWithNewEpisodeUrlDropsStaleNavigationFields",
            "sameEpisodeReplayKeepsNavigationFields",
            "drivePlayIdIsCanonicalizedToShareKeyAndRelativePath",
            "sameFileWithDifferentProxyIdKeepsNavigationFields",
            "staleRowIsBackfilledAndComparedByCanonicalPath",
            "nonDriveEpisodeUrlIsNotCanonicalized",
        )
    ))
    add("upstream subscription tests pin the new Atvp revision", (
        'Atvp.py?v=resume-group-v1' in subscription_tests
    ))

    failures = [row["name"] for row in checks if not row["ok"]]
    return {
        "ok": not failures,
        "source_root": str(root),
        "release_contract": "AList-TVBox 1.46.1",
        "base_contract": "AList-TVBox 1.45.1",
        "expected_tag": EXPECTED_TAG,
        "expected_commit": EXPECTED_COMMIT,
        "expected_release_delta": list(EXPECTED_RELEASE_DELTA),
        "checks": checks,
        "failures": failures,
        "summary": {
            "legacy_raw_plugin_contract": "preserved" if inherited_1451_compatibility_ok(inherited) else "failed",
            "playback_routes_and_auth": "preserved" if inherited_1451_compatibility_ok(inherited) else "unverified",
            "resume_contract": "extended with backward-compatible coordinates" if not failures else "unverified",
            "history_wire_contract": "adds optional driveShareKey and drivePath",
            "subscription_loader_revision": "resume-group-v1",
            "production_changes": False,
            "deployment_attempted": False,
        },
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_root", type=Path)
    parser.add_argument("--legacy-verifier", type=Path, default=BASE.DEFAULT_LEGACY_VERIFIER)
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args(argv)
    result = verify(args.source_root, args.legacy_verifier)
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

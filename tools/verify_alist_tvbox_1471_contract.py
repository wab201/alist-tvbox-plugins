#!/usr/bin/env python3
"""Verify the AList-TVBox 1.47.1 source contract used by V80."""

import argparse
import hashlib
import importlib.util
import json
import re
import subprocess
import zipfile
from io import BytesIO
from pathlib import Path


HERE = Path(__file__).resolve().parent
BASE_VERIFIER_PATH = HERE / "verify_alist_tvbox_1461_contract.py"


def _load_base_verifier():
    spec = importlib.util.spec_from_file_location(
        "alist_tvbox_1461_contract", BASE_VERIFIER_PATH,
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BASE = _load_base_verifier()
EXPECTED_TAG = "1.47.1"
EXPECTED_COMMIT = "05397d10cd1b8085670a628eb56cb94182fa885e"
EXPECTED_BASE_TAG = "1.46.1"
EXPECTED_BASE_COMMIT = "8d601fd1e0fc25f92cca48e96a32bb0155046fd0"
EXPECTED_1450_COMMIT = "b9b96b0e18458179764cf636826212c1a7bc4da3"
EXPECTED_1461_VERSION_FAILURES = frozenset((
    "Git commit matches AList-TVBox 1.46.1",
    "Git tag matches AList-TVBox 1.46.1",
    "release notes identify 1.46.1",
    "release notes scope the change to playback synchronization",
    "spring.jar Git blob matches 1.46.1",
    "spring.jar bytes and SHA256 match 1.46.1",
    "spring.jar MD5 matches both pinned and declared values",
))
EXPECTED_RELEASE_DELTA = (
    ".zcode/plans/plan-sess_a019431e-2050-45cd-b560-d27224d22c63.md",
    "RELEASE_NOTES.md",
    "docs/live-follow.md",
    "src/main/java/cn/har01d/alist_tvbox/config/NativeFlywayMigrationConfig.java",
    "src/main/java/cn/har01d/alist_tvbox/config/WebSecurityConfiguration.java",
    "src/main/java/cn/har01d/alist_tvbox/dto/LiveFollowDto.java",
    "src/main/java/cn/har01d/alist_tvbox/entity/LiveFollow.java",
    "src/main/java/cn/har01d/alist_tvbox/entity/LiveFollowRepository.java",
    "src/main/java/cn/har01d/alist_tvbox/live/model/BilibiliRoomInfo.java",
    "src/main/java/cn/har01d/alist_tvbox/live/service/BilibiliService.java",
    "src/main/java/cn/har01d/alist_tvbox/live/service/HuyaService.java",
    "src/main/java/cn/har01d/alist_tvbox/live/service/LiveFollowService.java",
    "src/main/java/cn/har01d/alist_tvbox/live/service/LiveService.java",
    "src/main/java/cn/har01d/alist_tvbox/live/web/LiveController.java",
    "src/main/java/cn/har01d/alist_tvbox/live/web/LiveFollowController.java",
    "src/main/java/cn/har01d/alist_tvbox/web/ImageController.java",
    "src/main/java/db/migration/current/V19__LiveFollow.java",
    "src/main/resources/META-INF/native-image/reflect-config.json",
    "src/main/resources/META-INF/services/org.flywaydb.core.api.migration.JavaMigration",
    "src/main/resources/static/spring.jar",
    "src/main/resources/static/spring.md5",
    "web-ui/src/views/LiveView.vue",
)
EXPECTED_UNCHANGED_BLOBS = {
    "src/main/resources/static/Atvp.py": "9d47b50a6160a4301b37865a14f212e77165f84f",
    "src/main/java/cn/har01d/alist_tvbox/entity/History.java": "71aa330238387555a72bd19999a3e72f05b11b2e",
    "src/main/java/cn/har01d/alist_tvbox/dto/playback/PlaybackSyncInput.java": (
        "e4aaaca32316d7a3cc4aca9c009924bae7bac63c"
    ),
    "src/main/java/cn/har01d/alist_tvbox/service/PlaybackSyncService.java": (
        "ca7badd7a49eea8cc1cb84b1af4552eec9ee88c3"
    ),
}
EXPECTED_SPRING_BLOB = "0dbefae36d9d41c313ad50ad9de1fb1b98067e47"
EXPECTED_SPRING_BYTES = 374888
EXPECTED_SPRING_SHA256 = (
    "F329B05DD2B92FCF40F69FEEC85641079A916064929AF87E011D0A80D15607FD"
)
EXPECTED_SPRING_MD5 = "3ef2c42368e57a86786a614213197c76"
EXPECTED_DEX_BYTES = 1334504
EXPECTED_DEX_SHA256 = (
    "1FECE3B9CFB57723A59D7C22AE259F61D765B725F73D64F13822B7F0BE26C2C3"
)


def _text(root, relative):
    return BASE._text(root, relative)


def _bytes(root, relative):
    return BASE._bytes(root, relative)


def inherited_1461_compatibility_ok(payload):
    if not isinstance(payload, dict):
        return False
    return set(payload.get("failures") or ()) == EXPECTED_1461_VERSION_FAILURES


def spring_dex_identity(spring_bytes):
    try:
        with zipfile.ZipFile(BytesIO(spring_bytes)) as archive:
            dex = archive.read("classes.dex")
    except (KeyError, OSError, zipfile.BadZipFile):
        return {"bytes": 0, "sha256": ""}
    return {
        "bytes": len(dex),
        "sha256": hashlib.sha256(dex).hexdigest().upper(),
    }


def _reflect_entries(root):
    try:
        payload = json.loads(_text(
            root, "src/main/resources/META-INF/native-image/reflect-config.json",
        ))
    except (json.JSONDecodeError, OSError):
        return {}
    if not isinstance(payload, list):
        return {}
    return {
        row.get("name"): row for row in payload
        if isinstance(row, dict) and isinstance(row.get("name"), str)
    }


def _complete_reflect_entry(entries, name):
    row = entries.get(name) if isinstance(entries, dict) else None
    return isinstance(row, dict) and all(
        row.get(key) is True for key in (
            "allDeclaredConstructors", "allDeclaredMethods", "allDeclaredFields",
        )
    )


def _git_worktree_status(root):
    root = Path(root).resolve()
    if not (root / ".git").exists():
        return None, "Git metadata is missing"
    try:
        completed = subprocess.run(
            [
                "git", "-c", "safe.directory=%s" % root.as_posix(),
                "status", "--porcelain=v1", "--untracked-files=all",
            ],
            cwd=str(root), capture_output=True, text=True,
            encoding="utf-8", errors="replace", check=False, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, type(exc).__name__
    if completed.returncode != 0:
        return None, "git exited with %s" % completed.returncode
    return completed.stdout.strip(), None


def _ordered_method(text, start_marker, markers, end_marker):
    start = text.find(start_marker)
    if start < 0:
        return False
    end = text.find(end_marker, start + len(start_marker))
    if end < 0:
        end = len(text)
    cursor = start
    for marker in markers:
        cursor = text.find(marker, cursor + 1, end)
        if cursor < 0:
            return False
    return True


def verify(root, legacy_verifier=BASE.BASE.DEFAULT_LEGACY_VERIFIER):
    root = Path(root).resolve()
    checks = []

    def add(name, ok, detail=None):
        row = {"name": name, "ok": bool(ok)}
        if detail not in (None, ""):
            row["detail"] = str(detail)
        checks.append(row)

    inherited = BASE.verify(root, legacy_verifier)
    add(
        "1.46.1 contract remains green except expected release and spring identity checks",
        inherited_1461_compatibility_ok(inherited),
        ", ".join(inherited.get("failures") or ()),
    )

    commit = BASE.BASE._git_value(root, "rev-parse", "HEAD")
    tag = BASE.BASE._git_value(root, "describe", "--tags", "--exact-match")
    worktree_status, worktree_error = _git_worktree_status(root)
    add("Git checkout metadata is available", commit is not None)
    add("Git worktree status is available", worktree_status is not None, worktree_error)
    add(
        "Git worktree is clean",
        worktree_status == "",
        "%d status line(s)" % len((worktree_status or "").splitlines()),
    )
    add("Git commit matches AList-TVBox 1.47.1", commit == EXPECTED_COMMIT, commit)
    add("Git tag matches AList-TVBox 1.47.1", tag == EXPECTED_TAG, tag)
    legacy_base_commit = BASE.BASE._git_value(root, "rev-parse", "1.45.0^{commit}")
    add(
        "1.45.0 history base tag resolves to the pinned commit",
        legacy_base_commit == EXPECTED_1450_COMMIT,
        legacy_base_commit,
    )
    base_commit = BASE.BASE._git_value(root, "rev-parse", "%s^{commit}" % EXPECTED_BASE_TAG)
    add("1.46.1 base tag resolves to the pinned commit", base_commit == EXPECTED_BASE_COMMIT, base_commit)
    release_delta_value = BASE.BASE._git_value(
        root, "diff", "--name-only", "%s..%s" % (EXPECTED_BASE_TAG, EXPECTED_TAG),
    )
    release_delta = tuple(filter(None, (release_delta_value or "").splitlines()))
    add(
        "1.46.1 to 1.47.1 changed-file set is exact",
        release_delta == EXPECTED_RELEASE_DELTA,
        ", ".join(release_delta),
    )

    notes = _text(root, "RELEASE_NOTES.md")
    add("release notes identify 1.47.1", bool(re.search(
        r"(?m)^#\s+Release Notes\s+-\s+1\.47\.1\s*$", notes,
    )))
    add("release notes scope the change to network live follows", all(
        marker in notes for marker in (
            "网络直播支持关注主播",
            "快速查看已关注主播的开播状态并进入直播间",
            "优化网络直播关注管理体验",
        )
    ))

    for relative, expected_blob in EXPECTED_UNCHANGED_BLOBS.items():
        head_blob = BASE.BASE._git_value(root, "rev-parse", "HEAD:%s" % relative)
        base_blob = BASE.BASE._git_value(
            root, "rev-parse", "%s:%s" % (EXPECTED_BASE_TAG, relative),
        )
        add(
            "%s is unchanged from 1.46.1" % relative,
            head_blob == expected_blob and base_blob == expected_blob,
            "%s / %s" % (base_blob, head_blob),
        )

    spring_relative = "src/main/resources/static/spring.jar"
    spring = _bytes(root, spring_relative)
    spring_blob = BASE.BASE._git_value(root, "rev-parse", "HEAD:%s" % spring_relative)
    spring_sha256 = hashlib.sha256(spring).hexdigest().upper() if spring else ""
    spring_md5 = hashlib.md5(spring).hexdigest() if spring else ""
    declared_md5 = _text(root, "src/main/resources/static/spring.md5").strip().lower()
    add("spring.jar Git blob matches 1.47.1", spring_blob == EXPECTED_SPRING_BLOB, spring_blob)
    add(
        "spring.jar bytes and SHA256 match 1.47.1",
        len(spring) == EXPECTED_SPRING_BYTES and spring_sha256 == EXPECTED_SPRING_SHA256,
        "%s bytes / %s" % (len(spring), spring_sha256),
    )
    add(
        "spring.jar MD5 matches both pinned and declared values",
        spring_md5 == EXPECTED_SPRING_MD5 and declared_md5 == EXPECTED_SPRING_MD5,
        "%s / %s" % (spring_md5, declared_md5),
    )
    dex_identity = spring_dex_identity(spring)
    add(
        "spring.jar classes.dex identity matches 1.47.1",
        dex_identity == {
            "bytes": EXPECTED_DEX_BYTES,
            "sha256": EXPECTED_DEX_SHA256,
        },
        json.dumps(dex_identity, sort_keys=True),
    )
    marker_status = BASE.spring_runtime_markers(spring)
    add(
        "spring.jar preserves PyProxy/playerContent and multi-level resume markers",
        bool(marker_status) and all(marker_status.values()),
        json.dumps(marker_status, ensure_ascii=False, sort_keys=True),
    )

    migration_class = "db.migration.current.V19__LiveFollow"
    migration_source = _text(root, "src/main/java/db/migration/current/V19__LiveFollow.java")
    migration_registry = _text(
        root, "src/main/resources/META-INF/services/org.flywaydb.core.api.migration.JavaMigration",
    )
    native_config = _text(
        root, "src/main/java/cn/har01d/alist_tvbox/config/NativeFlywayMigrationConfig.java",
    )
    reflect_entries = _reflect_entries(root)
    add("V19 live-follow migration source and unique owner key are present", all(
        marker in migration_source for marker in (
            "public class V19__LiveFollow",
            "CREATE TABLE IF NOT EXISTS live_follow",
            'createIndexIfMissing(connection, "live_follow", "uk_live_follow", true, "uid", "platform", "room_id")',
        )
    ))
    add("V19 live-follow migration is registered for JVM and Native Image", (
        migration_class in migration_registry
        and "new V19__LiveFollow()" in native_config
        and _complete_reflect_entry(reflect_entries, migration_class)
        and _complete_reflect_entry(
            reflect_entries, "cn.har01d.alist_tvbox.entity.LiveFollow",
        )
    ))

    security = _text(
        root, "src/main/java/cn/har01d/alist_tvbox/config/WebSecurityConfiguration.java",
    )
    live_controller = _text(
        root, "src/main/java/cn/har01d/alist_tvbox/live/web/LiveController.java",
    )
    management_controller = _text(
        root, "src/main/java/cn/har01d/alist_tvbox/live/web/LiveFollowController.java",
    )
    follow_service = _text(
        root, "src/main/java/cn/har01d/alist_tvbox/live/service/LiveFollowService.java",
    )
    permit_all_blocks = re.findall(
        r"\.requestMatchers\((.*?)\)\s*\.permitAll\(\)", security, re.DOTALL,
    )
    plugin_routes_permitted = any(all(
        marker in block for marker in (
            '"/live/follow"',
            '"/live/unfollow"',
            '"/live/*/follow"',
            '"/live/*/unfollow"',
        )
    ) for block in permit_all_blocks)
    add("TVBox shared follow routes delegate an explicit empty subscription context", (
        plugin_routes_permitted and all(
            marker in live_controller for marker in (
                '@PostMapping("/live/follow")',
                'return follow("", dto);',
                '@PostMapping("/live/unfollow")',
                'return unfollow("", dto);',
            )
        )
    ))
    add("TVBox tokenized follow routes validate subscription context before uid resolution", (
        plugin_routes_permitted
        and _ordered_method(
            live_controller,
            '@PostMapping("/live/{token}/follow")',
            (
                "subscriptionService.checkToken(token);",
                "int uid = liveFollowService.resolveUid(token);",
                "liveFollowService.follow(uid, dto.getPlatform(), dto.getRoomId());",
            ),
            '@PostMapping("/live/{token}/unfollow")',
        )
        and _ordered_method(
            live_controller,
            '@PostMapping("/live/{token}/unfollow")',
            (
                "subscriptionService.checkToken(token);",
                "int uid = liveFollowService.resolveUid(token);",
                "liveFollowService.unfollow(uid, dto.getPlatform(), dto.getRoomId());",
            ),
            "\n}",
        )
    ))
    add("web live-follow management endpoints require ADMIN or USER authority", bool(re.search(
        r'\.requestMatchers\(\s*"/api/live/follows",\s*"/api/live/follows/\*\*"\s*\)\s*'
        r'\.hasAnyAuthority\(Role\.ADMIN\.name\(\),\s*Role\.USER\.name\(\)\)',
        security, re.DOTALL,
    )) and all(
        marker in management_controller for marker in (
            '@RequestMapping("/api/live/follows")',
            "SecurityContextHolder.getContext().getAuthentication().getDetails()",
            "liveFollowService.listDto(currentUid())",
            "liveFollowService.follow(currentUid()",
            "liveFollowService.unfollow(currentUid()",
        )
    ))
    add("live-follow persistence remains isolated by uid, platform and room id", all(
        marker in follow_service for marker in (
            "findByUidAndPlatformAndRoomId(uid, platform, roomId)",
            "findByUidOrderByCreatedTimeDesc(uid)",
            "countByUid(uid)",
            'public static final String CATEGORY_ID = "follow";',
        )
    ))

    failures = [row["name"] for row in checks if not row["ok"]]
    return {
        "ok": not failures,
        "source_root": str(root),
        "release_contract": "AList-TVBox 1.47.1",
        "base_contract": "AList-TVBox 1.46.1",
        "expected_tag": EXPECTED_TAG,
        "expected_commit": EXPECTED_COMMIT,
        "expected_release_delta": list(EXPECTED_RELEASE_DELTA),
        "checks": checks,
        "failures": failures,
        "summary": {
            "legacy_raw_plugin_contract": (
                "preserved" if inherited_1461_compatibility_ok(inherited) else "failed"
            ),
            "playback_and_resume_contract": (
                "preserved" if inherited_1461_compatibility_ok(inherited) else "unverified"
            ),
            "release_scope": "network live follow",
            "live_follow_management_auth": "ADMIN or USER",
            "tvbox_live_follow_owner": (
                "public shared-or-token subscription context plus uid fallback"
            ),
            "upstream_live_follow_tests": "not present in 1.47.1 source",
            "production_changes": False,
            "deployment_attempted": False,
        },
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_root", type=Path)
    parser.add_argument("--legacy-verifier", type=Path, default=BASE.BASE.DEFAULT_LEGACY_VERIFIER)
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

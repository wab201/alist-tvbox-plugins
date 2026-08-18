#!/usr/bin/env python3
"""Verify the exact AList-TVBox 1.50.0 source leaf used by V80."""

import argparse
import hashlib
import importlib.util
import json
import re
from pathlib import Path


HERE = Path(__file__).resolve().parent
BASE_VERIFIER_PATH = HERE / "verify_alist_tvbox_1480_contract.py"


def _load_base_verifier():
    spec = importlib.util.spec_from_file_location(
        "alist_tvbox_1480_contract", BASE_VERIFIER_PATH,
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BASE = _load_base_verifier()
GIT_BASE = BASE.BASE.BASE.BASE
WORKTREE_BASE = BASE.BASE
SPRING_BASE = BASE.BASE
MARKER_BASE = BASE.BASE.BASE
DEFAULT_LEGACY_VERIFIER = GIT_BASE.DEFAULT_LEGACY_VERIFIER

EXPECTED_TAG = "1.50.0"
EXPECTED_COMMIT = "7ba1119e1e71bb427fb281f534a4c111ff7b500c"
EXPECTED_BASE_TAG = "1.48.0"
EXPECTED_BASE_COMMIT = "8f01c0f7521c172c439b31a89731764346f15f63"
EXPECTED_1480_VERSION_FAILURES = frozenset((
    "Git commit matches AList-TVBox 1.48.0",
    "Git tag matches AList-TVBox 1.48.0",
    "release notes identify 1.48.0",
    "release notes scope the change to live danmaku and Kuaishou playback",
    "spring.jar Git blob matches 1.48.0",
    "spring.jar bytes and SHA256 match 1.48.0",
    "spring.jar MD5 matches both pinned and declared values",
    "spring.jar classes.dex identity matches 1.48.0",
    "danmaku service supports the four declared live platforms",
))
EXPECTED_RELEASE_DELTA = (
    "RELEASE_NOTES.md",
    "src/main/java/cn/har01d/alist_tvbox/live/danmaku/AbstractDanmakuClient.java",
    "src/main/java/cn/har01d/alist_tvbox/live/danmaku/BilibiliDanmakuClient.java",
    "src/main/java/cn/har01d/alist_tvbox/live/danmaku/LiveDanmakuService.java",
    "src/main/java/cn/har01d/alist_tvbox/live/danmaku/TwitchDanmakuClient.java",
    "src/main/java/cn/har01d/alist_tvbox/live/service/LiveFollowService.java",
    "src/main/java/cn/har01d/alist_tvbox/live/service/LiveProxyService.java",
    "src/main/java/cn/har01d/alist_tvbox/live/service/LiveService.java",
    "src/main/java/cn/har01d/alist_tvbox/live/service/SoopService.java",
    "src/main/java/cn/har01d/alist_tvbox/live/service/TwitchService.java",
    "src/main/java/cn/har01d/alist_tvbox/live/web/LiveController.java",
    "src/main/resources/META-INF/native-image/reflect-config.json",
    "src/main/resources/static/spring.jar",
    "src/main/resources/static/spring.md5",
    "src/test/java/cn/har01d/alist_tvbox/live/danmaku/DanmakuProtocolTest.java",
    "src/test/java/cn/har01d/alist_tvbox/live/service/LiveFollowServiceTest.java",
    "src/test/java/cn/har01d/alist_tvbox/live/service/LiveServiceTest.java",
    "web-ui/package-lock.json",
    "web-ui/package.json",
    "web-ui/src/views/LiveView.vue",
)
EXPECTED_ADDED_PATHS = frozenset((
    "src/main/java/cn/har01d/alist_tvbox/live/danmaku/TwitchDanmakuClient.java",
    "src/main/java/cn/har01d/alist_tvbox/live/service/LiveProxyService.java",
    "src/main/java/cn/har01d/alist_tvbox/live/service/SoopService.java",
    "src/main/java/cn/har01d/alist_tvbox/live/service/TwitchService.java",
    "src/test/java/cn/har01d/alist_tvbox/live/service/LiveFollowServiceTest.java",
    "src/test/java/cn/har01d/alist_tvbox/live/service/LiveServiceTest.java",
))
EXPECTED_UNCHANGED_BLOBS = {
    "src/main/resources/static/Atvp.py": (
        "9d47b50a6160a4301b37865a14f212e77165f84f"
    ),
    "src/main/java/cn/har01d/alist_tvbox/entity/History.java": (
        "71aa330238387555a72bd19999a3e72f05b11b2e"
    ),
    "src/main/java/cn/har01d/alist_tvbox/web/PlaybackSyncController.java": (
        "d679b97643e7b0d3f14b9b9112b4b195c908572f"
    ),
    "src/main/java/cn/har01d/alist_tvbox/dto/playback/PlaybackSyncInput.java": (
        "e4aaaca32316d7a3cc4aca9c009924bae7bac63c"
    ),
    "src/main/java/cn/har01d/alist_tvbox/service/PlaybackSyncService.java": (
        "ca7badd7a49eea8cc1cb84b1af4552eec9ee88c3"
    ),
    "src/main/java/cn/har01d/alist_tvbox/service/PluginService.java": (
        "7ae6d7b0642ff042fe98ba7d7881c2a107412e0c"
    ),
    "src/main/java/cn/har01d/alist_tvbox/service/SubscriptionService.java": (
        "ad8f4577edbe415bae67d573d6a8ad2002192785"
    ),
}
EXPECTED_SPRING_BLOB = "408f78f43a2603a5ca6edb147a11bbb887094bf3"
EXPECTED_SPRING_BYTES = 386956
EXPECTED_SPRING_SHA256 = (
    "81F9C1A585438E32411F33C6DD636ED3CDA3938F777DDBAA5AFE58A684B922DA"
)
EXPECTED_SPRING_MD5 = "6e210d29d7c93e606e76c25fc485e4f5"
EXPECTED_DEX_BYTES = 1366596
EXPECTED_DEX_SHA256 = (
    "1DFFE4E107DC452C91EC48AA26A0F058649E18897C8A40B7F01681CBF019F63F"
)


def _text(root, relative):
    return BASE._text(root, relative)


def _bytes(root, relative):
    return BASE._bytes(root, relative)


def inherited_1480_compatibility_ok(payload):
    if not isinstance(payload, dict) or payload.get("ok") is not False:
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
    failures = [row["name"] for row in checks if row["ok"] is not True]
    return (
        declared == failures
        and len(failures) == len(EXPECTED_1480_VERSION_FAILURES)
        and set(failures) == EXPECTED_1480_VERSION_FAILURES
    )


def verify(root, legacy_verifier=DEFAULT_LEGACY_VERIFIER):
    root = Path(root).resolve()
    checks = []

    def add(name, ok, detail=None):
        row = {"name": name, "ok": bool(ok)}
        if detail not in (None, ""):
            row["detail"] = str(detail)
        checks.append(row)

    inherited = BASE.verify(root, legacy_verifier)
    inherited_ok = inherited_1480_compatibility_ok(inherited)
    add(
        "1.48.0 contract remains green except exact 1.50.0 leaf changes",
        inherited_ok,
        ", ".join(inherited.get("failures") or ()),
    )

    git_value = GIT_BASE._git_value
    commit = git_value(root, "rev-parse", "HEAD")
    tag = git_value(root, "describe", "--tags", "--exact-match")
    worktree_status, worktree_error = WORKTREE_BASE._git_worktree_status(root)
    add("Git checkout metadata is available", commit is not None)
    add("Git worktree status is available", worktree_status is not None, worktree_error)
    add(
        "Git worktree is clean",
        worktree_status == "",
        "%d status line(s)" % len((worktree_status or "").splitlines()),
    )
    add("Git commit matches AList-TVBox 1.50.0", commit == EXPECTED_COMMIT, commit)
    add("Git tag matches AList-TVBox 1.50.0", tag == EXPECTED_TAG, tag)
    base_commit = git_value(root, "rev-parse", "%s^{commit}" % EXPECTED_BASE_TAG)
    add(
        "1.48.0 base tag resolves to the pinned commit",
        base_commit == EXPECTED_BASE_COMMIT,
        base_commit,
    )

    release_delta_value = git_value(
        root, "diff", "--name-only", "%s..%s" % (EXPECTED_BASE_TAG, EXPECTED_TAG),
    )
    release_delta = tuple(filter(None, (release_delta_value or "").splitlines()))
    add(
        "1.48.0 to 1.50.0 changed-file set is exact",
        release_delta == EXPECTED_RELEASE_DELTA,
        ", ".join(release_delta),
    )
    added_value = git_value(
        root, "diff", "--diff-filter=A", "--name-only",
        "%s..%s" % (EXPECTED_BASE_TAG, EXPECTED_TAG),
    )
    added_paths = frozenset(filter(None, (added_value or "").splitlines()))
    add(
        "1.48.0 to 1.50.0 added-file set is exact",
        added_paths == EXPECTED_ADDED_PATHS,
        ", ".join(sorted(added_paths)),
    )

    notes = _text(root, "RELEASE_NOTES.md")
    add("release notes identify 1.50.0", bool(re.search(
        r"(?m)^#\s+Release Notes\s+-\s+1\.50\.0\s*$", notes,
    )))
    add(
        "release notes scope 1.50.0 to live search",
        "\u7f51\u7edc\u76f4\u64ad\u65b0\u589e\u641c\u7d22\u529f\u80fd" in notes,
    )

    for relative, expected_blob in EXPECTED_UNCHANGED_BLOBS.items():
        head_blob = git_value(root, "rev-parse", "HEAD:%s" % relative)
        base_blob = git_value(
            root, "rev-parse", "%s:%s" % (EXPECTED_BASE_TAG, relative),
        )
        add(
            "%s is unchanged from 1.48.0" % relative,
            head_blob == expected_blob and base_blob == expected_blob,
            "%s / %s" % (base_blob, head_blob),
        )

    spring_relative = "src/main/resources/static/spring.jar"
    spring = _bytes(root, spring_relative)
    spring_blob = git_value(root, "rev-parse", "HEAD:%s" % spring_relative)
    spring_sha256 = hashlib.sha256(spring).hexdigest().upper() if spring else ""
    spring_md5 = hashlib.md5(spring).hexdigest() if spring else ""
    declared_md5 = _text(root, "src/main/resources/static/spring.md5").strip().lower()
    add("spring.jar Git blob matches 1.50.0", spring_blob == EXPECTED_SPRING_BLOB, spring_blob)
    add(
        "spring.jar bytes and SHA256 match 1.50.0",
        len(spring) == EXPECTED_SPRING_BYTES and spring_sha256 == EXPECTED_SPRING_SHA256,
        "%s bytes / %s" % (len(spring), spring_sha256),
    )
    add(
        "spring.jar MD5 matches both pinned and declared values",
        spring_md5 == EXPECTED_SPRING_MD5 and declared_md5 == EXPECTED_SPRING_MD5,
        "%s / %s" % (spring_md5, declared_md5),
    )
    dex_identity = SPRING_BASE.spring_dex_identity(spring)
    add(
        "spring.jar classes.dex identity matches 1.50.0",
        dex_identity == {"bytes": EXPECTED_DEX_BYTES, "sha256": EXPECTED_DEX_SHA256},
        json.dumps(dex_identity, sort_keys=True),
    )
    marker_status = MARKER_BASE.spring_runtime_markers(spring)
    add(
        "spring.jar preserves PyProxy/playerContent and multi-level resume markers",
        bool(marker_status) and all(marker_status.values()),
        json.dumps(marker_status, ensure_ascii=False, sort_keys=True),
    )

    live_service = _text(root, "src/main/java/cn/har01d/alist_tvbox/live/service/LiveService.java")
    live_controller = _text(root, "src/main/java/cn/har01d/alist_tvbox/live/web/LiveController.java")
    danmaku_service = _text(
        root, "src/main/java/cn/har01d/alist_tvbox/live/danmaku/LiveDanmakuService.java",
    )
    twitch = _text(root, "src/main/java/cn/har01d/alist_tvbox/live/service/TwitchService.java")
    soop = _text(root, "src/main/java/cn/har01d/alist_tvbox/live/service/SoopService.java")
    proxy = _text(root, "src/main/java/cn/har01d/alist_tvbox/live/service/LiveProxyService.java")
    live_test = _text(
        root, "src/test/java/cn/har01d/alist_tvbox/live/service/LiveServiceTest.java",
    )
    follow_test = _text(
        root, "src/test/java/cn/har01d/alist_tvbox/live/service/LiveFollowServiceTest.java",
    )
    add("live search aggregates platform results with per-platform isolation", all(
        marker in live_service for marker in (
            "public MovieList search(String wd) throws IOException",
            "for (LivePlatform platform : platforms)",
            "list.addAll(platformResult.getList());",
            'log.warn("{} search failed: {}", platform.getName(), wd, e);',
        )
    ) and "return liveService.search(wd);" in live_controller)
    add("Twitch and SOOP are registered as live platforms", all(
        marker in live_service for marker in (
            "platforms.add(twitchService);",
            "platforms.add(soopService);",
        )
    ) and "public class TwitchService implements LivePlatform" in twitch
      and "public class SoopService implements LivePlatform" in soop)
    add("Twitch danmaku and authenticated live proxy routes are present", all(
        marker in danmaku_service for marker in (
            'Set.of("huya", "douyu", "bili", "douyin", "twitch")',
            'case "twitch":',
            "return new TwitchDanmakuClient(roomId, okHttpClient, scheduler);",
        )
    ) and "public class LiveProxyService" in proxy
      and '@GetMapping("/live-proxy/{token}")' in live_controller
      and "subscriptionService.checkToken(token);" in live_controller)
    add("upstream source tests cover search isolation and playback-track ordering", all(
        marker in live_test for marker in (
            "searchCombinesAvailablePlatformResultsWhenOnePlatformFails",
            'when(douyuService.search("test")).thenThrow',
        )
    ) and "liveRoomKeepsPlatformTracksFirst" in follow_test)

    failures = [row["name"] for row in checks if not row["ok"]]
    return {
        "ok": not failures,
        "source_root": str(root),
        "release_contract": "AList-TVBox 1.50.0",
        "base_contract": "AList-TVBox 1.48.0",
        "expected_tag": EXPECTED_TAG,
        "expected_commit": EXPECTED_COMMIT,
        "expected_release_delta": list(EXPECTED_RELEASE_DELTA),
        "checks": checks,
        "failures": failures,
        "summary": {
            "legacy_raw_plugin_contract": "preserved" if inherited_ok else "failed",
            "playback_and_resume_contract": "preserved" if inherited_ok else "unverified",
            "release_scope": "live search, Twitch/SOOP, danmaku and live proxy",
            "production_changes": False,
            "deployment_attempted": False,
        },
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_root", type=Path)
    parser.add_argument(
        "--legacy-verifier", type=Path, default=DEFAULT_LEGACY_VERIFIER,
    )
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

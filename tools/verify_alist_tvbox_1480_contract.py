#!/usr/bin/env python3
"""Verify the AList-TVBox 1.48.0 source contract used by V80."""

import argparse
import hashlib
import importlib.util
import json
import re
from pathlib import Path


HERE = Path(__file__).resolve().parent
BASE_VERIFIER_PATH = HERE / "verify_alist_tvbox_1471_contract.py"


def _load_base_verifier():
    spec = importlib.util.spec_from_file_location(
        "alist_tvbox_1471_contract", BASE_VERIFIER_PATH,
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BASE = _load_base_verifier()
EXPECTED_TAG = "1.48.0"
EXPECTED_COMMIT = "8f01c0f7521c172c439b31a89731764346f15f63"
EXPECTED_BASE_TAG = "1.47.1"
EXPECTED_BASE_COMMIT = "05397d10cd1b8085670a628eb56cb94182fa885e"
EXPECTED_1471_VERSION_FAILURES = frozenset((
    "Git commit matches AList-TVBox 1.47.1",
    "Git tag matches AList-TVBox 1.47.1",
    "release notes identify 1.47.1",
    "release notes scope the change to network live follows",
    "spring.jar Git blob matches 1.47.1",
    "spring.jar bytes and SHA256 match 1.47.1",
    "spring.jar MD5 matches both pinned and declared values",
    "spring.jar classes.dex identity matches 1.47.1",
))
EXPECTED_RELEASE_DELTA = (
    ".gitignore",
    ".zcode/plans/plan-sess_5af9dab6-8edf-4b21-8d8c-41934579d565.md",
    "RELEASE_NOTES.md",
    "docs/huya-danmaku-protocol.md",
    "pom.xml",
    "src/main/java/cn/har01d/alist_tvbox/AListApplication.java",
    "src/main/java/cn/har01d/alist_tvbox/config/AppProperties.java",
    "src/main/java/cn/har01d/alist_tvbox/dto/DanmakuConfig.java",
    "src/main/java/cn/har01d/alist_tvbox/dto/LiveDanmaku.java",
    "src/main/java/cn/har01d/alist_tvbox/live/danmaku/AbstractDanmakuClient.java",
    "src/main/java/cn/har01d/alist_tvbox/live/danmaku/BilibiliDanmakuClient.java",
    "src/main/java/cn/har01d/alist_tvbox/live/danmaku/DouyinDanmakuClient.java",
    "src/main/java/cn/har01d/alist_tvbox/live/danmaku/DouyuDanmakuClient.java",
    "src/main/java/cn/har01d/alist_tvbox/live/danmaku/HuyaDanmakuClient.java",
    "src/main/java/cn/har01d/alist_tvbox/live/danmaku/LiveDanmakuService.java",
    "src/main/java/cn/har01d/alist_tvbox/live/danmaku/MiniProto.java",
    "src/main/java/cn/har01d/alist_tvbox/live/danmaku/TarsReader.java",
    "src/main/java/cn/har01d/alist_tvbox/live/danmaku/TarsWriter.java",
    "src/main/java/cn/har01d/alist_tvbox/live/danmaku/XBogus.java",
    "src/main/java/cn/har01d/alist_tvbox/live/service/BilibiliService.java",
    "src/main/java/cn/har01d/alist_tvbox/live/service/DouyinService.java",
    "src/main/java/cn/har01d/alist_tvbox/live/service/HuyaService.java",
    "src/main/java/cn/har01d/alist_tvbox/live/service/KuaishouService.java",
    "src/main/java/cn/har01d/alist_tvbox/live/web/LiveDanmakuController.java",
    "src/main/java/cn/har01d/alist_tvbox/service/BiliBiliService.java",
    "src/main/java/cn/har01d/alist_tvbox/service/SettingService.java",
    "src/main/java/cn/har01d/alist_tvbox/web/LogFilter.java",
    "src/main/resources/META-INF/native-image/reflect-config.json",
    "src/main/resources/static/spring.jar",
    "src/main/resources/static/spring.md5",
    "src/test/java/cn/har01d/alist_tvbox/live/danmaku/BiliProbeTest.java",
    "src/test/java/cn/har01d/alist_tvbox/live/danmaku/DanmakuProtocolTest.java",
    "src/test/java/cn/har01d/alist_tvbox/live/danmaku/HuyaProbeTest.java",
    "web-ui/src/views/LiveView.vue",
)
EXPECTED_UNCHANGED_BLOBS = {
    "src/main/resources/static/Atvp.py": "9d47b50a6160a4301b37865a14f212e77165f84f",
    "src/main/java/cn/har01d/alist_tvbox/entity/History.java": (
        "71aa330238387555a72bd19999a3e72f05b11b2e"
    ),
    "src/main/java/cn/har01d/alist_tvbox/dto/playback/PlaybackSyncInput.java": (
        "e4aaaca32316d7a3cc4aca9c009924bae7bac63c"
    ),
    "src/main/java/cn/har01d/alist_tvbox/service/PlaybackSyncService.java": (
        "ca7badd7a49eea8cc1cb84b1af4552eec9ee88c3"
    ),
}
EXPECTED_SPRING_BLOB = "6d144e3b69ddad8606e7518a21ead7a630bb9001"
EXPECTED_SPRING_BYTES = 386120
EXPECTED_SPRING_SHA256 = (
    "FF4CED5C99786B0AFD8D2BFE44E78D6299647E59F7D23886B6846E34F0619E96"
)
EXPECTED_SPRING_MD5 = "fe356c2873db42e210fdc1866a2cfb06"
EXPECTED_DEX_BYTES = 1363108
EXPECTED_DEX_SHA256 = (
    "338BC29B032149AA76E3329825945A6CB9077C1DA58D321539A9755481CEB889"
)


def _text(root, relative):
    return BASE._text(root, relative)


def _bytes(root, relative):
    return BASE._bytes(root, relative)


def inherited_1471_compatibility_ok(payload):
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
        and len(failures) == len(EXPECTED_1471_VERSION_FAILURES)
        and set(failures) == EXPECTED_1471_VERSION_FAILURES
    )


def verify(root, legacy_verifier=BASE.BASE.BASE.DEFAULT_LEGACY_VERIFIER):
    root = Path(root).resolve()
    checks = []

    def add(name, ok, detail=None):
        row = {"name": name, "ok": bool(ok)}
        if detail not in (None, ""):
            row["detail"] = str(detail)
        checks.append(row)

    inherited = BASE.verify(root, legacy_verifier)
    add(
        "1.47.1 contract remains green except expected release and spring identity checks",
        inherited_1471_compatibility_ok(inherited),
        ", ".join(inherited.get("failures") or ()),
    )

    git_value = BASE.BASE.BASE._git_value
    commit = git_value(root, "rev-parse", "HEAD")
    tag = git_value(root, "describe", "--tags", "--exact-match")
    worktree_status, worktree_error = BASE._git_worktree_status(root)
    add("Git checkout metadata is available", commit is not None)
    add("Git worktree status is available", worktree_status is not None, worktree_error)
    add(
        "Git worktree is clean",
        worktree_status == "",
        "%d status line(s)" % len((worktree_status or "").splitlines()),
    )
    add("Git commit matches AList-TVBox 1.48.0", commit == EXPECTED_COMMIT, commit)
    add("Git tag matches AList-TVBox 1.48.0", tag == EXPECTED_TAG, tag)
    base_commit = git_value(root, "rev-parse", "%s^{commit}" % EXPECTED_BASE_TAG)
    add("1.47.1 base tag resolves to the pinned commit", base_commit == EXPECTED_BASE_COMMIT, base_commit)

    release_delta_value = git_value(
        root, "diff", "--name-only", "%s..%s" % (EXPECTED_BASE_TAG, EXPECTED_TAG),
    )
    release_delta = tuple(filter(None, (release_delta_value or "").splitlines()))
    add(
        "1.47.1 to 1.48.0 changed-file set is exact",
        release_delta == EXPECTED_RELEASE_DELTA,
        ", ".join(release_delta),
    )

    notes = _text(root, "RELEASE_NOTES.md")
    add("release notes identify 1.48.0", bool(re.search(
        r"(?m)^#\s+Release Notes\s+-\s+1\.48\.0\s*$", notes,
    )))
    add("release notes scope the change to live danmaku and Kuaishou playback", all(
        marker in notes for marker in (
            "网络直播支持实时弹幕",
            "覆盖虎牙、斗鱼、哔哩哔哩、抖音",
            "新增弹幕管理配置",
            "修复快手直播无法播放的问题",
        )
    ))

    for relative, expected_blob in EXPECTED_UNCHANGED_BLOBS.items():
        head_blob = git_value(root, "rev-parse", "HEAD:%s" % relative)
        base_blob = git_value(
            root, "rev-parse", "%s:%s" % (EXPECTED_BASE_TAG, relative),
        )
        add(
            "%s is unchanged from 1.47.1" % relative,
            head_blob == expected_blob and base_blob == expected_blob,
            "%s / %s" % (base_blob, head_blob),
        )

    spring_relative = "src/main/resources/static/spring.jar"
    spring = _bytes(root, spring_relative)
    spring_blob = git_value(root, "rev-parse", "HEAD:%s" % spring_relative)
    spring_sha256 = hashlib.sha256(spring).hexdigest().upper() if spring else ""
    spring_md5 = hashlib.md5(spring).hexdigest() if spring else ""
    declared_md5 = _text(root, "src/main/resources/static/spring.md5").strip().lower()
    add("spring.jar Git blob matches 1.48.0", spring_blob == EXPECTED_SPRING_BLOB, spring_blob)
    add(
        "spring.jar bytes and SHA256 match 1.48.0",
        len(spring) == EXPECTED_SPRING_BYTES and spring_sha256 == EXPECTED_SPRING_SHA256,
        "%s bytes / %s" % (len(spring), spring_sha256),
    )
    add(
        "spring.jar MD5 matches both pinned and declared values",
        spring_md5 == EXPECTED_SPRING_MD5 and declared_md5 == EXPECTED_SPRING_MD5,
        "%s / %s" % (spring_md5, declared_md5),
    )
    dex_identity = BASE.spring_dex_identity(spring)
    add(
        "spring.jar classes.dex identity matches 1.48.0",
        dex_identity == {"bytes": EXPECTED_DEX_BYTES, "sha256": EXPECTED_DEX_SHA256},
        json.dumps(dex_identity, sort_keys=True),
    )
    marker_status = BASE.BASE.spring_runtime_markers(spring)
    add(
        "spring.jar preserves PyProxy/playerContent and multi-level resume markers",
        bool(marker_status) and all(marker_status.values()),
        json.dumps(marker_status, ensure_ascii=False, sort_keys=True),
    )

    config = _text(root, "src/main/java/cn/har01d/alist_tvbox/dto/DanmakuConfig.java")
    controller = _text(root, "src/main/java/cn/har01d/alist_tvbox/live/web/LiveDanmakuController.java")
    service = _text(root, "src/main/java/cn/har01d/alist_tvbox/live/danmaku/LiveDanmakuService.java")
    protocol_test = _text(
        root, "src/test/java/cn/har01d/alist_tvbox/live/danmaku/DanmakuProtocolTest.java",
    )
    kuaishou = _text(root, "src/main/java/cn/har01d/alist_tvbox/live/service/KuaishouService.java")
    add("danmaku configuration is bounded and hot-loadable", all(
        marker in config for marker in (
            "private boolean enabled = true;",
            "private int rows = 0;",
            "private int speed = 1;",
            "private int fontSize = 100;",
            "private int opacity = 100;",
            "private boolean showOnline = true;",
            "public void normalize()",
        )
    ))
    add("shared and tokenized danmaku routes validate subscription context", all(
        marker in controller for marker in (
            '@GetMapping("/live/danmaku")',
            'return danmaku("", platform, roomId, after);',
            '@GetMapping("/live/danmaku/{token}")',
            "subscriptionService.checkToken(token);",
            'result.put("config", liveDanmakuService.resolvedConfig());',
        )
    ))
    add("danmaku service supports the four declared live platforms", all(
        marker in service for marker in (
            'Set.of("huya", "douyu", "bili", "douyin")',
            "new DouyuDanmakuClient",
            "new HuyaDanmakuClient",
            "new BilibiliDanmakuClient",
            "new DouyinDanmakuClient",
            "private static final int BUFFER_LIMIT = 500;",
            "private static final long IDLE_MILLIS = 60_000;",
        )
    ))
    add("danmaku protocol unit source covers all four declared platforms", all(
        marker in protocol_test for marker in (
            "douyuSerialize()",
            "huyaSubscribeFrame()",
            "biliEncodePacket()",
            "douyinSignature()",
            "protoWriterReaderRoundTrip()",
        )
    ))
    add("Kuaishou playback fix carries and refreshes its session identity", all(
        marker in kuaishou for marker in (
            "private final Map<String, String> cookieStore = new ConcurrentHashMap<>();",
            "private synchronized void refreshSession()",
            "private void registerDid()",
            "private void captureCookies(ResponseEntity<String> response)",
            "private String buildCookieHeader()",
            "parseWatchingCount",
        )
    ))

    failures = [row["name"] for row in checks if not row["ok"]]
    return {
        "ok": not failures,
        "source_root": str(root),
        "release_contract": "AList-TVBox 1.48.0",
        "base_contract": "AList-TVBox 1.47.1",
        "expected_tag": EXPECTED_TAG,
        "expected_commit": EXPECTED_COMMIT,
        "expected_release_delta": list(EXPECTED_RELEASE_DELTA),
        "checks": checks,
        "failures": failures,
        "summary": {
            "legacy_raw_plugin_contract": (
                "preserved" if inherited_1471_compatibility_ok(inherited) else "failed"
            ),
            "playback_and_resume_contract": (
                "preserved" if inherited_1471_compatibility_ok(inherited) else "unverified"
            ),
            "release_scope": "live danmaku and Kuaishou playback",
            "danmaku_platforms": ["huya", "douyu", "bili", "douyin"],
            "upstream_protocol_tests": "source present; execution is a separate gate",
            "production_changes": False,
            "deployment_attempted": False,
        },
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_root", type=Path)
    parser.add_argument(
        "--legacy-verifier", type=Path, default=BASE.BASE.BASE.DEFAULT_LEGACY_VERIFIER,
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

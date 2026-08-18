#!/usr/bin/env python3
"""Verify the AList-TVBox 1.45.1 source contract used by V80 P3."""

import argparse
import hashlib
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path


EXPECTED_COMMIT = "9cd22bb91bbaaf2bb4f4e0cd9b9d8da00841db81"
EXPECTED_TAG = "1.45.1"
EXPECTED_RELEASE_DELTA = (
    "RELEASE_NOTES.md",
    "src/main/resources/META-INF/native-image/reflect-config.json",
)
EXPECTED_LEGACY_FAILURES = frozenset((
    "source file present: src/main/java/cn/har01d/alist_tvbox/web/HistoryController.java",
    "History token pull/push routes remain available",
))
DEFAULT_LEGACY_VERIFIER = None
FROZEN_LEGACY_FILES = {
    "atvp": "src/main/resources/static/Atvp.py",
    "plugin": "src/main/java/cn/har01d/alist_tvbox/service/PluginService.java",
    "subscription": "src/main/java/cn/har01d/alist_tvbox/service/SubscriptionService.java",
    "pan115": "src/main/java/cn/har01d/alist_tvbox/service/offline/Pan115OfflineDownloadHandler.java",
    "parse": "src/main/java/cn/har01d/alist_tvbox/web/ParseController.java",
    "play": "src/main/java/cn/har01d/alist_tvbox/web/PlayController.java",
    "history": "src/main/java/cn/har01d/alist_tvbox/web/HistoryController.java",
    "download_target": "src/main/java/cn/har01d/alist_tvbox/model/DownloadTarget.java",
    "stored_config": "src/main/java/cn/har01d/alist_tvbox/model/StoredConfig.java",
    "reflection": "src/main/resources/META-INF/native-image/reflect-config.json",
    "driver_account": "src/main/java/cn/har01d/alist_tvbox/web/DriverAccountController.java",
    "security": "src/main/java/cn/har01d/alist_tvbox/config/WebSecurityConfiguration.java",
    "drive": "src/main/java/cn/har01d/alist_tvbox/service/DriveService.java",
}


def _text(root, relative):
    path = Path(root) / relative
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def _bytes(root, relative):
    try:
        return (Path(root) / relative).read_bytes()
    except OSError:
        return b""


def _frozen_legacy_result(root):
    root = Path(root)
    checks = []

    def add(name, ok):
        checks.append({"name": name, "ok": bool(ok)})

    sources = {}
    for name, relative in FROZEN_LEGACY_FILES.items():
        path = root / relative
        present = path.is_file()
        add("source file present: %s" % relative, present)
        sources[name] = _text(root, relative) if present else ""

    atvp = sources["atvp"]
    subscription = sources["subscription"]
    pan115 = sources["pan115"]
    add("Atvp raw=true bypasses secspider decryption", all(marker in atvp for marker in (
        'payload.get("raw") is True',
        "package_text if self._is_raw_source(payload) else self._decrypt_secspider_source(package_text)",
    )))
    add("Atvp category wrapping uses backend_parse", 'getattr(self._inner, "backend_parse", False)' in atvp)
    add("Atvp keeps atvp_detail prefix", 'DETAIL_PREFIX = "atvp_detail:"' in atvp)
    add("raw Python site api remains csp_PyProxy", 'return "csp_PyProxy";' in subscription)
    add("raw Python ext keeps revisioned loader", all(marker in subscription for marker in (
        'map.put("loader", atvpUrl(baseUrl))',
        'return baseUrl + "/Atvp.py?v=" + ATVP_RUNTIME_REVISION;',
        'map.put("source", contentUrl)',
        'map.put("raw", true)',
        'map.put("local_proxy_config"',
    )))
    add("parse token route remains available", '@PostMapping("/parse/{token}")' in sources["parse"])
    add("play token route remains available", '@GetMapping("/play/{token}")' in sources["play"])
    add("History token pull/push routes remain available", all(marker in sources["history"] for marker in (
        '@GetMapping("/history/{token}")', '@PostMapping("/history/{token}")',
    )))
    add("PAN115 keeps normalized task identity and URL fallback", all(marker in pan115 for marker in (
        'raw.matches("[0-9A-Fa-f]{40}")',
        "taskHash.equalsIgnoreCase(infoHash)",
        'Objects.equals(item.path("url").asText(""), url)',
    )))
    add("Native Image offline models remain top-level records", (
        "public record DownloadTarget(String path, boolean folder)" in sources["download_target"]
        and "public record StoredConfig(boolean enabled, String driverType, Integer accountId, String offlineFolderId)"
        in sources["stored_config"]
    ))
    try:
        reflection = json.loads(sources["reflection"])
        reflected = {row.get("name"): row for row in reflection if isinstance(row, dict)}
    except (json.JSONDecodeError, TypeError):
        reflected = {}
    add("Native Image reflection keeps offline models", all(
        all(reflected.get(name, {}).get(key) is True for key in (
            "allDeclaredConstructors", "allDeclaredMethods", "allDeclaredFields",
        ))
        for name in (
            "cn.har01d.alist_tvbox.model.DownloadTarget",
            "cn.har01d.alist_tvbox.model.StoredConfig",
        )
    ))
    add("pan account info remains authenticated management API", all(marker in sources["driver_account"] for marker in (
        '@RequestMapping("/api/pan/accounts")', '@PostMapping("/-/info")',
    )) and '.requestMatchers("/api/**").hasAnyAuthority(Role.ADMIN.name(), Role.CLIENT.name())' in sources["security"])
    add("Drive API resolves numeric playurlId to the real path", all(marker in sources["drive"] for marker in (
        'pathPart.matches("\\\\d+")', "proxyService.getPath(Integer.parseInt(pathPart))",
    )))

    failures = [row["name"] for row in checks if not row["ok"]]
    return {"checks": checks, "failures": failures}


def _legacy_result(root, verifier=DEFAULT_LEGACY_VERIFIER):
    if verifier is None:
        return _frozen_legacy_result(root), None
    verifier = Path(verifier)
    if not verifier.is_file():
        return None, "legacy compatibility verifier is missing: %s" % verifier
    with tempfile.TemporaryDirectory(prefix="alist-tvbox-1451-") as name:
        report = Path(name) / "legacy.json"
        try:
            completed = subprocess.run(
                [sys.executable, str(verifier), str(root), "--json-out", str(report)],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                check=False, timeout=120,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return None, "legacy compatibility verifier failed to run: %s" % exc
        try:
            payload = json.loads(report.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            detail = (completed.stderr or completed.stdout or "").strip()
            return None, "legacy compatibility report is invalid: %s; %s" % (exc, detail)
    return payload, None


def legacy_compatibility_ok(payload):
    if not isinstance(payload, dict) or not isinstance(payload.get("checks"), list):
        return False
    failures = {
        row.get("name") for row in payload["checks"]
        if isinstance(row, dict) and row.get("ok") is not True
    }
    declared = set(payload.get("failures") or [])
    return failures == EXPECTED_LEGACY_FAILURES and declared == EXPECTED_LEGACY_FAILURES


def _git_value(root, *args):
    root = Path(root).resolve()
    if not (root / ".git").exists():
        return None
    try:
        completed = subprocess.run(
            ["git", "-c", "safe.directory=%s" % root.as_posix(), *args],
            cwd=str(root), capture_output=True, text=True,
            encoding="utf-8", errors="replace", check=False, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return completed.stdout.strip() if completed.returncode == 0 else ""


def verify(root, legacy_verifier=DEFAULT_LEGACY_VERIFIER):
    root = Path(root).resolve()
    checks = []

    def add(name, ok, detail=None):
        row = {"name": name, "ok": bool(ok)}
        if detail:
            row["detail"] = str(detail)
        checks.append(row)

    legacy, legacy_error = _legacy_result(root, legacy_verifier)
    add(
        "frozen 1.42 compatibility remains green except removed legacy History routes",
        legacy_compatibility_ok(legacy), legacy_error,
    )

    required = (
        "src/main/java/cn/har01d/alist_tvbox/web/PlaybackSyncController.java",
        "src/main/java/cn/har01d/alist_tvbox/service/PlaybackSyncService.java",
        "src/main/java/cn/har01d/alist_tvbox/dto/playback/PlaybackDeleteInput.java",
        "src/main/java/cn/har01d/alist_tvbox/dto/playback/PlaybackSyncInput.java",
        "src/main/java/cn/har01d/alist_tvbox/dto/playback/PlaybackSyncPage.java",
        "src/main/java/cn/har01d/alist_tvbox/dto/playback/PlaybackTokenDto.java",
        "src/main/java/cn/har01d/alist_tvbox/entity/PlaybackChangeSequence.java",
        "src/main/java/cn/har01d/alist_tvbox/entity/PlaybackToken.java",
        "src/main/java/cn/har01d/alist_tvbox/entity/PlaybackTombstone.java",
    )
    for relative in required:
        add("source file present: %s" % relative, (root / relative).is_file())

    controller = _text(root, required[0])
    routes = (
        '@PostMapping("/api/playback/event")',
        '@PostMapping("/api/playback/events")',
        '@GetMapping("/api/playback/changes")',
        '@PostMapping("/api/playback/sync")',
        '@GetMapping("/api/playback/sync")',
        '@GetMapping("/api/playback/records")',
        '@GetMapping("/api/playback/records/-/item")',
        '@PostMapping("/api/playback/records/-/delete")',
        '@DeleteMapping("/api/playback/records")',
        '@GetMapping("/api/playback/tokens")',
        '@PostMapping("/api/playback/tokens")',
        '@DeleteMapping("/api/playback/tokens/{id}")',
    )
    for marker in routes:
        add("route mapping present: %s" % marker, marker in controller)
    auth_markers = (
        'request.getHeader("X-PlaySync-Token")',
        'request.getHeader("X-WebHTV-Token")',
        'request.getHeader("Authorization")',
        'regionMatches(true, 0, "Bearer ", 0, 7)',
    )
    add("sync authentication accepts playback, WebHTV and Authorization headers",
        all(marker in controller for marker in auth_markers))
    add("pull accepts monotonic cursor, limit and latest headers", all(marker in controller for marker in (
        '"X-PlaySync-Since"', '"X-PlaySync-Limit"', '"X-PlaySync-Latest"',
    )))

    security = _text(
        root, "src/main/java/cn/har01d/alist_tvbox/config/WebSecurityConfiguration.java"
    )
    add("sync transport routes are permit-all token-authenticated endpoints", all(
        marker in security for marker in (
            '"/api/playback/event"', '"/api/playback/events"',
            '"/api/playback/changes"', '"/api/playback/sync"',
            ").permitAll()",
        )
    ))
    add("record and token management routes require USER or ADMIN", all(
        marker in security for marker in (
            '"/api/playback/tokens/**", "/api/playback/records", "/api/playback/records/**"',
            ".hasAnyAuthority(Role.ADMIN.name(), Role.USER.name())",
        )
    ))

    token_filter = _text(root, "src/main/java/cn/har01d/alist_tvbox/auth/TokenFilter.java")
    add("TokenFilter defers playback-token validation only on sync transport routes", all(
        marker in token_filter for marker in (
            "if (!PLAYBACK_SYNC_PATHS.contains(uri))",
            '"/api/playback/event", "/api/playback/events", "/api/playback/changes"',
            "filterChain.doFilter(request, response)",
        )
    ) and '"/api/playback/records"' not in token_filter.split("PLAYBACK_SYNC_PATHS", 1)[-1])

    service = _text(root, required[1])
    add("playback tokens and session tokens resolve to uid", all(marker in service for marker in (
        "tokenRepository.findByToken(token)",
        "tokenService.extractToken(token).getUserId()",
    )))
    add("push accepts FongMi, webhtv and atv-player record maps", all(marker in service for marker in (
        "PlaybackSyncInput.fromMap(record)", "PlaybackDeleteInput.fromMap(record)", "applyAll",
    )))
    add("pull uses change sequence and nextSince", all(marker in service for marker in (
        "nextChangeSeq()", "setChangeSeq", "setNextSince", "changeSeq",
    )))
    add("delete tombstones and LWW protection are present", all(marker in service for marker in (
        "tombstoneWatermark", "updatedAt <= deletedAt", "removeHistory", "saveTombstone",
    )))
    add("playback sync scope isolation is present", all(marker in service for marker in (
        "syncScope", "findAllSync", "forceUidGlobalScope",
    )))

    input_dto = _text(root, required[3])
    add("playback input aliases cover legacy and normalized identities", all(marker in input_dto for marker in (
        '"key"', '"sourceKind"', '"sourceKey"', '"vodId"', '"positionMs"', '"durationMs"',
    )))
    add("normalized input reconstructs the sourceKey/vodId identity from FongMi keys", all(
        marker in input_dto for marker in (
            'key.split("@@@", -1)', "in.sourceKey = parts[0]", "in.vodId = parts[1]",
        )
    ))
    history_repository = _text(
        root, "src/main/java/cn/har01d/alist_tvbox/entity/HistoryRepository.java"
    )
    add("HistoryRepository uses uid plus sourceKind/sourceKey/vodId identity", all(
        marker in history_repository for marker in (
            "findAllByUidAndSourceKindAndSourceKeyAndVodId",
            "h.sourceKind = :sourceKind AND h.sourceKey = :sourceKey AND h.vodId = :vodId",
            "findSyncByIdentity",
        )
    ))
    page_dto = _text(root, required[4])
    add("pull page exposes nextSince, items and deleted", all(marker in page_dto for marker in (
        "nextSince", "items", "deleted",
    )))

    migrations = tuple(
        "db.migration.current.V%d__%s" % pair for pair in (
            (10, "PlaybackSync"), (11, "PlaybackChangeSequence"),
            (12, "WidenPlaybackVodId"), (13, "PlaybackSourceName"),
            (14, "PlaybackSelectionContext"), (15, "PlaybackSyncScope"),
            (16, "MigrateLegacyHistory"),
        )
    )
    migration_registry = _text(
        root, "src/main/resources/META-INF/services/org.flywaydb.core.api.migration.JavaMigration"
    )
    reflect_text = _text(root, "src/main/resources/META-INF/native-image/reflect-config.json")
    for class_name in migrations:
        relative = "src/main/java/%s.java" % class_name.replace(".", "/")
        add("migration source present: %s" % class_name, (root / relative).is_file())
        add("migration registered: %s" % class_name, class_name in migration_registry)
    try:
        reflect_names = {
            row.get("name") for row in json.loads(reflect_text)
            if isinstance(row, dict)
        }
    except (json.JSONDecodeError, TypeError):
        reflect_names = set()
    add("V16 legacy history migration is registered for Native Image",
        "db.migration.current.V16__MigrateLegacyHistory" in reflect_names)
    add("playback DTOs are registered for Native Image", all(name in reflect_names for name in (
        "cn.har01d.alist_tvbox.dto.playback.PlaybackDeleteInput",
        "cn.har01d.alist_tvbox.dto.playback.PlaybackSyncInput",
        "cn.har01d.alist_tvbox.dto.playback.PlaybackSyncPage",
        "cn.har01d.alist_tvbox.dto.playback.PlaybackTokenDto",
    )))

    subscription = _text(
        root, "src/main/java/cn/har01d/alist_tvbox/service/SubscriptionService.java"
    )
    add("subscription EXT injects playback token and config URL", all(marker in subscription for marker in (
        'map.put("playbackToken"', 'map.put("playbackConfigUrl"',
    )))
    add("plugin EXT injects stable playback source identity", all(marker in subscription for marker in (
        'map.put("playbackSourceKind", "spider_plugin")',
        'map.put("playbackSourceKey"', 'map.put("playbackSourceName"',
    )))
    add("plugin site key and playback source key share pluginSiteKey linkage", all(
        marker in subscription for marker in (
            'map.put("playbackSourceKey", pluginSiteKey(plugin))',
            'site.put("key", pluginSiteKey(plugin))',
            "return plugin.getExternalId()", 'return "plugin-" + plugin.getId()',
        )
    ))

    add("legacy History controller is absent", not (
        root / "src/main/java/cn/har01d/alist_tvbox/web/HistoryController.java"
    ).exists())
    add("legacy History service is absent", not (
        root / "src/main/java/cn/har01d/alist_tvbox/service/HistoryService.java"
    ).exists())

    spring = _bytes(root, "src/main/resources/static/spring.jar")
    declared_md5 = _text(root, "src/main/resources/static/spring.md5").strip().lower()
    actual_md5 = hashlib.md5(spring).hexdigest() if spring else ""
    add("spring.jar MD5 matches spring.md5", bool(actual_md5) and actual_md5 == declared_md5)

    notes = _text(root, "RELEASE_NOTES.md")
    add("release notes identify 1.45.1", bool(re.search(
        r"(?m)^#\s+Release Notes\s+-\s+1\.45\.1\s*$", notes,
    )))
    commit = _git_value(root, "rev-parse", "HEAD")
    tag = _git_value(root, "describe", "--tags", "--exact-match")
    if commit is not None:
        add("Git commit matches AList-TVBox 1.45.1", commit == EXPECTED_COMMIT, commit)
        add("Git tag matches AList-TVBox 1.45.1", tag == EXPECTED_TAG, tag)
        release_delta = tuple(filter(None, _git_value(
            root, "diff", "--name-only", "1.45.0..1.45.1",
        ).splitlines()))
        add(
            "1.45.1 changes only release notes and Native Image reflection",
            release_delta == EXPECTED_RELEASE_DELTA,
            ", ".join(release_delta),
        )

    failures = [row["name"] for row in checks if not row["ok"]]
    return {
        "ok": not failures,
        "source_root": str(root),
        "release_contract": "AList-TVBox 1.45.1",
        "expected_tag": EXPECTED_TAG,
        "expected_commit": EXPECTED_COMMIT,
        "checks": checks,
        "failures": failures,
        "summary": {
            "legacy_compatibility": "verified with two intentional History removals"
                if legacy_compatibility_ok(legacy) else "failed",
            "playback_sync": "verified" if not failures else "unverified",
            "legacy_fallback": "/history/{token} is client-side compatibility only",
        },
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_root", type=Path)
    parser.add_argument("--legacy-verifier", type=Path, default=DEFAULT_LEGACY_VERIFIER)
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

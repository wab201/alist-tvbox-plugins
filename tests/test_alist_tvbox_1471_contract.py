import hashlib
import importlib.util
import zipfile
from io import BytesIO
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "verify_alist_tvbox_1471_contract.py"


def _load():
    spec = importlib.util.spec_from_file_location("alist_tvbox_1471_contract", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


VERIFY = _load()


def test_1471_inherits_1461_except_exact_release_and_spring_identity_checks():
    payload = {"failures": list(VERIFY.EXPECTED_1461_VERSION_FAILURES)}
    assert VERIFY.inherited_1461_compatibility_ok(payload)

    payload["failures"].append("raw plugin regression")
    assert not VERIFY.inherited_1461_compatibility_ok(payload)


def test_1471_release_delta_is_pinned_to_the_observed_22_files():
    assert len(VERIFY.EXPECTED_RELEASE_DELTA) == 22
    assert "docs/live-follow.md" in VERIFY.EXPECTED_RELEASE_DELTA
    assert "src/main/java/db/migration/current/V19__LiveFollow.java" in VERIFY.EXPECTED_RELEASE_DELTA
    assert "src/main/resources/static/spring.jar" in VERIFY.EXPECTED_RELEASE_DELTA
    assert "src/main/resources/static/Atvp.py" not in VERIFY.EXPECTED_RELEASE_DELTA


def test_1471_pins_unchanged_playback_contract_blobs():
    assert set(VERIFY.EXPECTED_UNCHANGED_BLOBS) == {
        "src/main/resources/static/Atvp.py",
        "src/main/java/cn/har01d/alist_tvbox/entity/History.java",
        "src/main/java/cn/har01d/alist_tvbox/dto/playback/PlaybackSyncInput.java",
        "src/main/java/cn/har01d/alist_tvbox/service/PlaybackSyncService.java",
    }
    assert all(len(value) == 40 for value in VERIFY.EXPECTED_UNCHANGED_BLOBS.values())


def test_spring_dex_identity_reads_only_classes_dex():
    payload = BytesIO()
    dex = b"real classes"
    with zipfile.ZipFile(payload, "w") as archive:
        archive.writestr("classes.dex", dex)
        archive.writestr("decoy.dex", b"different")

    assert VERIFY.spring_dex_identity(payload.getvalue()) == {
        "bytes": len(dex),
        "sha256": hashlib.sha256(dex).hexdigest().upper(),
    }

    missing = BytesIO()
    with zipfile.ZipFile(missing, "w") as archive:
        archive.writestr("decoy.dex", dex)
    assert VERIFY.spring_dex_identity(missing.getvalue()) == {"bytes": 0, "sha256": ""}


def test_native_reflect_contract_requires_all_declared_capabilities():
    name = "db.migration.current.V19__LiveFollow"
    entries = {
        name: {
            "name": name,
            "allDeclaredConstructors": True,
            "allDeclaredMethods": True,
            "allDeclaredFields": True,
        },
    }
    assert VERIFY._complete_reflect_entry(entries, name)

    entries[name]["allDeclaredMethods"] = False
    assert not VERIFY._complete_reflect_entry(entries, name)


def test_tokenized_route_contract_requires_validation_before_uid_and_write():
    source = """
@PostMapping("/live/{token}/follow")
subscriptionService.checkToken(token);
int uid = liveFollowService.resolveUid(token);
liveFollowService.follow(uid, dto.getPlatform(), dto.getRoomId());
@PostMapping("/live/{token}/unfollow")
"""
    markers = (
        "subscriptionService.checkToken(token);",
        "int uid = liveFollowService.resolveUid(token);",
        "liveFollowService.follow(uid, dto.getPlatform(), dto.getRoomId());",
    )
    assert VERIFY._ordered_method(
        source,
        '@PostMapping("/live/{token}/follow")',
        markers,
        '@PostMapping("/live/{token}/unfollow")',
    )

    reordered = source.replace(
        "subscriptionService.checkToken(token);\nint uid",
        "int uid",
    ) + "subscriptionService.checkToken(token);"
    assert not VERIFY._ordered_method(
        reordered,
        '@PostMapping("/live/{token}/follow")',
        markers,
        '@PostMapping("/live/{token}/unfollow")',
    )


def test_verify_rejects_a_dirty_git_worktree(monkeypatch, tmp_path):
    monkeypatch.setattr(
        VERIFY.BASE,
        "verify",
        lambda *args, **kwargs: {
            "failures": list(VERIFY.EXPECTED_1461_VERSION_FAILURES),
        },
    )

    monkeypatch.setattr(
        VERIFY, "_git_worktree_status",
        lambda root: ("M src/main/java/example.java", None),
    )
    monkeypatch.setattr(VERIFY.BASE.BASE, "_git_value", lambda *args: "")
    monkeypatch.setattr(VERIFY, "_text", lambda *args: "")
    monkeypatch.setattr(VERIFY, "_bytes", lambda *args: b"")

    result = VERIFY.verify(tmp_path)

    assert not result["ok"]
    assert "Git worktree is clean" in result["failures"]


def test_verify_rejects_an_unavailable_git_worktree_status(monkeypatch, tmp_path):
    monkeypatch.setattr(
        VERIFY.BASE,
        "verify",
        lambda *args, **kwargs: {
            "failures": list(VERIFY.EXPECTED_1461_VERSION_FAILURES),
        },
    )
    monkeypatch.setattr(
        VERIFY, "_git_worktree_status",
        lambda root: (None, "git exited with 128"),
    )
    monkeypatch.setattr(VERIFY.BASE.BASE, "_git_value", lambda *args: "")
    monkeypatch.setattr(VERIFY, "_text", lambda *args: "")
    monkeypatch.setattr(VERIFY, "_bytes", lambda *args: b"")

    result = VERIFY.verify(tmp_path)

    assert "Git worktree status is available" in result["failures"]
    assert "Git worktree is clean" in result["failures"]


def test_1471_pins_the_1450_history_base_commit():
    assert VERIFY.EXPECTED_1450_COMMIT == "b9b96b0e18458179764cf636826212c1a7bc4da3"

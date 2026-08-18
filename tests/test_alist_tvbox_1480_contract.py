import hashlib
import importlib.util
import zipfile
from io import BytesIO
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "verify_alist_tvbox_1480_contract.py"


def _load():
    spec = importlib.util.spec_from_file_location("alist_tvbox_1480_contract", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


VERIFY = _load()


def _inherited_payload(failures=None):
    failures = list(
        sorted(VERIFY.EXPECTED_1471_VERSION_FAILURES)
        if failures is None
        else failures
    )
    checks = [{"name": name, "ok": False} for name in failures]
    checks.append({"name": "unchanged 1.47.1 compatibility check", "ok": True})
    return {"ok": False, "checks": checks, "failures": failures}


def test_1480_inherits_1471_except_exact_release_and_spring_identity_checks():
    payload = _inherited_payload()
    assert VERIFY.inherited_1471_compatibility_ok(payload)

    payload = _inherited_payload(payload["failures"] + ["raw plugin regression"])
    assert not VERIFY.inherited_1471_compatibility_ok(payload)


def test_1480_rejects_inconsistent_inherited_failure_projection():
    payload = _inherited_payload()
    payload["checks"].append({"name": "undeclared raw plugin regression", "ok": False})

    assert not VERIFY.inherited_1471_compatibility_ok(payload)


def test_1480_rejects_duplicate_or_malformed_inherited_failures():
    payload = _inherited_payload()
    duplicate = payload["failures"][0]
    payload["checks"].append({"name": duplicate, "ok": False})
    payload["failures"].append(duplicate)
    assert not VERIFY.inherited_1471_compatibility_ok(payload)

    payload = _inherited_payload()
    payload["ok"] = True
    assert not VERIFY.inherited_1471_compatibility_ok(payload)

    payload = _inherited_payload()
    payload["checks"].append({"name": "malformed inherited row"})
    assert not VERIFY.inherited_1471_compatibility_ok(payload)


def test_1480_release_delta_is_pinned_to_the_observed_34_files():
    assert len(VERIFY.EXPECTED_RELEASE_DELTA) == 34
    assert "docs/huya-danmaku-protocol.md" in VERIFY.EXPECTED_RELEASE_DELTA
    assert "src/main/java/cn/har01d/alist_tvbox/live/web/LiveDanmakuController.java" in VERIFY.EXPECTED_RELEASE_DELTA
    assert "src/main/java/cn/har01d/alist_tvbox/live/service/KuaishouService.java" in VERIFY.EXPECTED_RELEASE_DELTA
    assert "src/main/resources/static/spring.jar" in VERIFY.EXPECTED_RELEASE_DELTA
    assert "src/main/resources/static/Atvp.py" not in VERIFY.EXPECTED_RELEASE_DELTA


def test_1480_pins_unchanged_playback_contract_blobs():
    assert set(VERIFY.EXPECTED_UNCHANGED_BLOBS) == {
        "src/main/resources/static/Atvp.py",
        "src/main/java/cn/har01d/alist_tvbox/entity/History.java",
        "src/main/java/cn/har01d/alist_tvbox/dto/playback/PlaybackSyncInput.java",
        "src/main/java/cn/har01d/alist_tvbox/service/PlaybackSyncService.java",
    }
    assert all(len(value) == 40 for value in VERIFY.EXPECTED_UNCHANGED_BLOBS.values())


def test_1480_spring_identity_is_pinned():
    assert VERIFY.EXPECTED_SPRING_BYTES == 386120
    assert VERIFY.EXPECTED_SPRING_SHA256 == (
        "FF4CED5C99786B0AFD8D2BFE44E78D6299647E59F7D23886B6846E34F0619E96"
    )
    assert VERIFY.EXPECTED_SPRING_MD5 == "fe356c2873db42e210fdc1866a2cfb06"
    assert VERIFY.EXPECTED_DEX_BYTES == 1363108


def test_spring_dex_identity_reads_only_classes_dex():
    payload = BytesIO()
    dex = b"real classes"
    with zipfile.ZipFile(payload, "w") as archive:
        archive.writestr("classes.dex", dex)
        archive.writestr("decoy.dex", b"different")

    assert VERIFY.BASE.spring_dex_identity(payload.getvalue()) == {
        "bytes": len(dex),
        "sha256": hashlib.sha256(dex).hexdigest().upper(),
    }


def test_verify_rejects_a_dirty_git_worktree(monkeypatch, tmp_path):
    monkeypatch.setattr(
        VERIFY.BASE,
        "verify",
        lambda *args, **kwargs: _inherited_payload(),
    )
    monkeypatch.setattr(
        VERIFY.BASE,
        "_git_worktree_status",
        lambda root: ("M src/main/java/example.java", None),
    )
    monkeypatch.setattr(VERIFY.BASE.BASE.BASE, "_git_value", lambda *args: "")
    monkeypatch.setattr(VERIFY, "_text", lambda *args: "")
    monkeypatch.setattr(VERIFY, "_bytes", lambda *args: b"")

    result = VERIFY.verify(tmp_path)

    assert not result["ok"]
    assert "Git worktree is clean" in result["failures"]


def test_1480_pins_the_1471_base_commit():
    assert VERIFY.EXPECTED_BASE_COMMIT == "05397d10cd1b8085670a628eb56cb94182fa885e"

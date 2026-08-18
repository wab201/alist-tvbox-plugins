import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "verify_alist_tvbox_1511_contract.py"


def _load():
    spec = importlib.util.spec_from_file_location("alist_tvbox_1511_contract", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


VERIFY = _load()


def _inherited_payload():
    return {
        "ok": True,
        "checks": [{"name": "exact 1.50.0 leaf", "ok": True}],
        "failures": [],
    }


def test_1511_inherits_an_exact_green_1500_base():
    payload = _inherited_payload()
    assert VERIFY.inherited_1500_compatibility_ok(payload)

    payload["checks"].append({"name": "raw plugin regression", "ok": False})
    payload["failures"].append("raw plugin regression")
    payload["ok"] = False
    assert not VERIFY.inherited_1500_compatibility_ok(payload)


def test_1511_rejects_inconsistent_duplicate_or_malformed_base_evidence():
    payload = _inherited_payload()
    payload["failures"].append("undeclared failure")
    assert not VERIFY.inherited_1500_compatibility_ok(payload)

    payload = _inherited_payload()
    payload["checks"].append({"name": "exact 1.50.0 leaf", "ok": True})
    assert not VERIFY.inherited_1500_compatibility_ok(payload)

    payload = _inherited_payload()
    payload["checks"].append({"name": "malformed"})
    assert not VERIFY.inherited_1500_compatibility_ok(payload)


def test_1511_evidence_sha_and_release_delta_are_pinned():
    assert VERIFY.DEFAULT_EVIDENCE.is_file()
    assert VERIFY.EXPECTED_EVIDENCE_SHA256 == (
        "E6AF69979CDF5587592ABD33000CC9EACDFAA9077FE70B93062BC9CB4AD3DF1B"
    )
    assert len(VERIFY.EXPECTED_RELEASE_DELTA) == 20
    assert len(VERIFY.EXPECTED_ADDED_PATHS) == 6
    assert "src/main/resources/static/Atvp.py" not in VERIFY.EXPECTED_RELEASE_DELTA
    assert "src/main/resources/static/spring.jar" not in VERIFY.EXPECTED_RELEASE_DELTA


def test_1511_owner_and_semantic_boundaries_are_explicit():
    assert set(VERIFY.EXPECTED_UNCHANGED_BLOBS) == {
        "src/main/resources/static/Atvp.py",
        "src/main/resources/static/spring.jar",
        "src/main/java/cn/har01d/alist_tvbox/entity/History.java",
        "src/main/java/cn/har01d/alist_tvbox/dto/playback/PlaybackSyncInput.java",
        "src/main/java/cn/har01d/alist_tvbox/service/PluginService.java",
        "src/main/java/cn/har01d/alist_tvbox/service/SubscriptionService.java",
    }
    assert set(VERIFY.EXPECTED_CHANGED_BLOBS) == {
        "src/main/java/cn/har01d/alist_tvbox/config/AppProperties.java",
        "src/main/java/cn/har01d/alist_tvbox/config/WebSecurityConfiguration.java",
        "src/main/java/cn/har01d/alist_tvbox/entity/PlaybackTombstoneRepository.java",
        "src/main/java/cn/har01d/alist_tvbox/model/PluginFilterConfigField.java",
        "src/main/java/cn/har01d/alist_tvbox/service/PlaybackSyncService.java",
        "src/main/java/cn/har01d/alist_tvbox/util/ConfigSchemaParser.java",
        "src/main/java/cn/har01d/alist_tvbox/web/PlaybackSyncController.java",
    }
    assert VERIFY.EXPECTED_SEMANTIC_MARKERS["playback_delete_throttle_default_ms"] == 600000
    assert VERIFY.EXPECTED_SEMANTIC_MARKERS["tombstone_admin_endpoint"] == (
        "/api/playback/tombstones/-/delete"
    )
    assert VERIFY.EXPECTED_SEMANTIC_MARKERS["plugin_config_list_type"] is True


def test_verify_accepts_the_pinned_github_evidence(monkeypatch, tmp_path):
    monkeypatch.setattr(VERIFY.BASE, "verify", lambda *args, **kwargs: _inherited_payload())

    result = VERIFY.verify(tmp_path)

    assert result["ok"] is True
    assert result["release_contract"] == "AList-TVBox 1.51.1"
    assert result["evidence_sha256"] == VERIFY.EXPECTED_EVIDENCE_SHA256


def test_verify_rejects_modified_evidence_bytes(monkeypatch, tmp_path):
    monkeypatch.setattr(VERIFY.BASE, "verify", lambda *args, **kwargs: _inherited_payload())
    payload = json.loads(VERIFY.DEFAULT_EVIDENCE.read_text(encoding="utf-8"))
    changed = tmp_path / "evidence.json"
    changed.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")

    result = VERIFY.verify(tmp_path, changed)

    assert result["ok"] is False
    assert "GitHub evidence SHA256 matches the fixed 1.51.1 capture" in result["failures"]

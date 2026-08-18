import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "verify_alist_tvbox_1451_contract.py"


def _load():
    spec = importlib.util.spec_from_file_location("alist_tvbox_1451_contract", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


VERIFY = _load()


def _legacy_payload(failures):
    checks = [{"name": name, "ok": False} for name in failures]
    checks.append({"name": "unchanged raw plugin check", "ok": True})
    return {"checks": checks, "failures": list(failures)}


def test_legacy_verifier_allows_only_the_two_intentional_history_removals():
    assert VERIFY.legacy_compatibility_ok(
        _legacy_payload(VERIFY.EXPECTED_LEGACY_FAILURES)
    )


def test_legacy_verifier_rejects_any_additional_regression():
    failures = set(VERIFY.EXPECTED_LEGACY_FAILURES)
    failures.add("raw plugin regression")

    assert not VERIFY.legacy_compatibility_ok(_legacy_payload(failures))


def test_default_legacy_contract_is_project_local_and_frozen():
    assert VERIFY.DEFAULT_LEGACY_VERIFIER is None
    assert VERIFY.FROZEN_LEGACY_FILES["history"].endswith("HistoryController.java")


def test_1451_release_delta_is_intentionally_narrow():
    assert VERIFY.EXPECTED_RELEASE_DELTA == (
        "RELEASE_NOTES.md",
        "src/main/resources/META-INF/native-image/reflect-config.json",
    )

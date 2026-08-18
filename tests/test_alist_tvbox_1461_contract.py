import importlib.util
import zipfile
from io import BytesIO
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "verify_alist_tvbox_1461_contract.py"


def _load():
    spec = importlib.util.spec_from_file_location("alist_tvbox_1461_contract", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


VERIFY = _load()


def test_1461_inherits_1451_except_exact_release_identity_checks():
    payload = {"failures": list(VERIFY.EXPECTED_1451_VERSION_FAILURES)}
    assert VERIFY.inherited_1451_compatibility_ok(payload)

    payload["failures"].append("raw plugin regression")
    assert not VERIFY.inherited_1451_compatibility_ok(payload)


def test_1461_release_delta_is_pinned_to_the_observed_16_files():
    assert len(VERIFY.EXPECTED_RELEASE_DELTA) == 16
    assert "src/main/resources/static/Atvp.py" in VERIFY.EXPECTED_RELEASE_DELTA
    assert "src/main/resources/static/spring.jar" in VERIFY.EXPECTED_RELEASE_DELTA
    assert "src/main/java/db/migration/current/V17__FixChangeSequenceWatermark.java" in VERIFY.EXPECTED_RELEASE_DELTA
    assert "src/main/java/db/migration/current/V18__PlaybackDrivePath.java" in VERIFY.EXPECTED_RELEASE_DELTA


def test_spring_runtime_marker_probe_reads_only_classes_dex():
    payload = BytesIO()
    with zipfile.ZipFile(payload, "w") as archive:
        archive.writestr("classes.dex", b"\0".join(VERIFY.SPRING_RUNTIME_MARKERS))
        archive.writestr("decoy.txt", b"unused")

    assert all(VERIFY.spring_runtime_markers(payload.getvalue()).values())

    missing = BytesIO()
    with zipfile.ZipFile(missing, "w") as archive:
        archive.writestr("classes.dex", b"PlaybackSyncer")
        archive.writestr("decoy.txt", b"\0".join(VERIFY.SPRING_RUNTIME_MARKERS))
    status = VERIFY.spring_runtime_markers(missing.getvalue())
    assert status["PlaybackSyncer"] is True
    assert status["sourceIndex"] is False

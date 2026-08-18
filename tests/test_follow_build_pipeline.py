# -*- coding: utf-8 -*-

import ast
import hashlib
import importlib.util
import json
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parent.parent
SOURCE_DIR = ROOT / "src" / "douban_tmdb_follow_single"
DEV_MANIFEST_PATH = SOURCE_DIR / "release.json"
BASELINE_MANIFEST_PATH = SOURCE_DIR / "baseline_v70.json"
DEPENDENCY_CONTRACT_PATH = SOURCE_DIR / "dependency_contract.json"
SOURCE_README_PATH = SOURCE_DIR / "README.md"
PARTS_DIR = SOURCE_DIR / "parts"
BUILD_SCRIPT = ROOT / "tools" / "build_follow_plugin.py"
FINGERPRINT_PROBE_SCRIPT = ROOT / "work" / "probe_v80_build_fingerprint.py"
PUBLIC_RELEASE_PATH = ROOT / "py" / "豆瓣TMDB追更单入口.py"
INDEX_PATH = ROOT / "spiders_v2.json"

EXPECTED_ID = "douban_tmdb_follow_single"
EXPECTED_VERSION = 70
EXPECTED_PUBLIC_OUTPUT = "py/豆瓣TMDB追更单入口.py"
EXPECTED_DEV_OUTPUT = "build/v80-dev/豆瓣TMDB追更单入口.py"
EXPECTED_V70_SIZE = 616699
EXPECTED_V70_SHA256 = "233C73CAE1048210B34872D4A10EA6023662300F70A8657DB82EA65C342182D4"
EXPECTED_P2_OVERLAY_SIZE = 681512
EXPECTED_P2_OVERLAY_SHA256 = "52C9ABA52F9572790B268CF0DB95B4302952EE3CACA9A4ED337CA843E69F92BE"
EXPECTED_RELIABILITY_OVERLAY_SIZE = 776229
EXPECTED_RELIABILITY_OVERLAY_SHA256 = "9A3008A774FACE213EDC337E3B92CDBF088C4A79CB8961D04DD24F133A02C5C6"
EXPECTED_CACHE_HEALTH_MODULE_SIZE = 8699
EXPECTED_CACHE_HEALTH_MODULE_SHA256 = "0DB3E86FBBA0535D5810A9CB1E2D0AD227BC77B9F6F7255F0E9055786A710A59"
EXPECTED_CACHE_HEALTH_MODULE_OUTPUT_SIZE = 784928
EXPECTED_CACHE_HEALTH_MODULE_OUTPUT_SHA256 = "E9CC403823F3CA7FFAAE9803A6F1F3230607304D44F66E010A15B065B770E4DD"
EXPECTED_CACHE_HEALTH_OVERLAY_SIZE = 781140
EXPECTED_CACHE_HEALTH_OVERLAY_SHA256 = "50572D6304283CE39AA17AA2F25D1ED3EE9CEE88BB4DEB1C5B81D06EC6D79FBE"
EXPECTED_BACKGROUND_BULKHEAD_MODULE_SIZE = 2766
EXPECTED_BACKGROUND_BULKHEAD_MODULE_SHA256 = "07901732FEB335C1540A6D8220F15F5E16AF1E009B9D41B5B2D3AAC4C63DAEB0"
EXPECTED_BACKGROUND_BULKHEAD_MODULE_OUTPUT_SIZE = 783906
EXPECTED_BACKGROUND_BULKHEAD_MODULE_OUTPUT_SHA256 = "D7DABB19F6DEB71D32791CB068601CC177091232955424AC13FE3E19353137ED"
EXPECTED_BACKGROUND_BULKHEAD_OVERLAY_SIZE = 786881
EXPECTED_BACKGROUND_BULKHEAD_OVERLAY_SHA256 = "694B39E802BBD3D18D7006B81E48C439449FD80032EACDEBC052DD488261ED3F"
EXPECTED_TIMEOUT_BUDGET_MODULE_SIZE = 9995
EXPECTED_TIMEOUT_BUDGET_MODULE_SHA256 = "3EC7A85672936E0A24EF24137FF542C022813DE0CD223B10C34AB408B6564867"
EXPECTED_TIMEOUT_BUDGET_MODULE_OUTPUT_SIZE = 796876
EXPECTED_TIMEOUT_BUDGET_MODULE_OUTPUT_SHA256 = "2263C7E779473A4199C0B0310E0EC22D68A7D6AD78B06F50392E57E9E419AA2B"
EXPECTED_TIMEOUT_BUDGET_OVERLAY_SIZE = 808647
EXPECTED_TIMEOUT_BUDGET_OVERLAY_SHA256 = "9DF8697F950068A56E42BFC4331A5E0ED1520FE91F7C156B30BEF8B2C58187B9"
EXPECTED_SECURITY_POLICY_MODULE_SIZE = 13919
EXPECTED_SECURITY_POLICY_MODULE_SHA256 = "8BB1DF6C481E6EC6FDA2A0DEE2B2EE52D562C9430F2C6FD049E06758C14D26B8"
EXPECTED_SECURITY_POLICY_OUTPUT_SIZE = 822566
EXPECTED_SECURITY_POLICY_OUTPUT_SHA256 = "A1C922715DDA59168D9EB12D0D820A345341840BA9DCF0856F7238CF1C8B8F76"
EXPECTED_ROUTE_SECURITY_OVERLAY_SIZE = 823561
EXPECTED_ROUTE_SECURITY_OVERLAY_SHA256 = "D8B2E08B80DCD24CF55205ABA8CE441136587FEBE2BCA216D90A29EEC9520D2F"
EXPECTED_JSON_SHAPE_POLICY_MODULE_SIZE = 2383
EXPECTED_JSON_SHAPE_POLICY_MODULE_SHA256 = "91AAD2A2417D226C87DD750D7C2C825E01D176A7BE699857B9239C5EBFCF3EAF"
EXPECTED_P4_3_SIZE = 825944
EXPECTED_P4_3_SHA256 = "8FB4EEDAB97057412D622881A074BDA6D04F76617B81CA6802B6D34525FB70F0"
EXPECTED_P4_4_SIZE = 825969
EXPECTED_P4_4_SHA256 = "4746D9EB74B6351EFBF8764985BA295F6936914A7F0A47CFACD6AC52257E86C7"
EXPECTED_TMDB_RESPONSE_POLICY_MODULE_SIZE = 1735
EXPECTED_TMDB_RESPONSE_POLICY_MODULE_SHA256 = "C2D56B1432AB66163591953BA0ACD532A71BE0D963984EAF78C31F70DF3BD375"
EXPECTED_TMDB_RESPONSE_POLICY_OUTPUT_SIZE = 827704
EXPECTED_TMDB_RESPONSE_POLICY_OUTPUT_SHA256 = "3CDCB55A06A9BA862DBE541AAD8CF36E32887B7A98F2F4487E78BA29A5668443"
EXPECTED_P4_5_SIZE = 829079
EXPECTED_P4_5_SHA256 = "115A00A5182C9AFAC802708DA0E8FBBFFFC1BB4320FE923097B16C91439F6AB9"
EXPECTED_DIAGNOSTIC_REDACTION_POLICY_MODULE_SIZE = 9503
EXPECTED_DIAGNOSTIC_REDACTION_POLICY_MODULE_SHA256 = (
    "4A05F0910BEF7FCFA70CFEAA4D25B5B9B05482150A004CB3AFF9D5C1CD17A831"
)
EXPECTED_DIAGNOSTIC_REDACTION_POLICY_OUTPUT_SIZE = 838582
EXPECTED_DIAGNOSTIC_REDACTION_POLICY_OUTPUT_SHA256 = (
    "39B28FE248515D51F52541A29C372DE06ADE703FAF19D6CDE805B8272B3987A0"
)
EXPECTED_P4_6_SIZE = 837970
EXPECTED_P4_6_SHA256 = "96A7A5900870DFBD10A0063392DFB4649AB81EBE9255A9FF94FBC1282A4F2E00"
EXPECTED_DOUBAN_RESPONSE_POLICY_MODULE_SIZE = 251
EXPECTED_DOUBAN_RESPONSE_POLICY_MODULE_SHA256 = (
    "69C7AEF61E8724616A6621CF74C7686D702D34A8A6E3C207DB430D50301A4170"
)
EXPECTED_DOUBAN_RESPONSE_POLICY_OUTPUT_SIZE = 838221
EXPECTED_DOUBAN_RESPONSE_POLICY_OUTPUT_SHA256 = (
    "BB9C41865178B8F498872F8F0B51A8B06E043E5E49542526D766E7B932E2389C"
)
EXPECTED_P4_7_SIZE = 839214
EXPECTED_P4_7_SHA256 = "6A62E667F23EB395BA7ACAC71F0A2AF11772D2E25DC703B35CFA731ED964579D"
EXPECTED_DOUBAN_HTML_RESPONSE_POLICY_MODULE_SIZE = 271
EXPECTED_DOUBAN_HTML_RESPONSE_POLICY_MODULE_SHA256 = (
    "DBBA0B73239F25884A4FECD9CCB3014D0AC2772D5B3334C76EBCCE98D018EDB8"
)
EXPECTED_DOUBAN_HTML_RESPONSE_POLICY_OUTPUT_SIZE = 839485
EXPECTED_DOUBAN_HTML_RESPONSE_POLICY_OUTPUT_SHA256 = (
    "5CDF2CBFFB9A10D66BAD94707DE05F0A1C81D98D6EA4C3C2187F234EEA451759"
)
EXPECTED_P4_8_SIZE = 843188
EXPECTED_P4_8_SHA256 = "70FFFECDD0166A8263E793502421EA06BA0AD0D1D19FB10F5ECE6CB6A3708740"
EXPECTED_OBSERVABILITY_POLICY_MODULE_SIZE = 2138
EXPECTED_OBSERVABILITY_POLICY_MODULE_SHA256 = (
    "FDFA66B624DD9C5405A77B8FAAC1D2A3973B83AB7EBFB241AFBC99319AAE4C59"
)
EXPECTED_P5_1_SIZE = 845326
EXPECTED_P5_1_SHA256 = "15F08B2372FA9ECC4C7C8D11D81E769E9CC3D1F782A306CC3065B526E200419F"
EXPECTED_P5_2_SIZE = 850898
EXPECTED_P5_2_SHA256 = "B273E4ED166E1DA6C2212555C98A3EE94E6CC6557D7E12BB745EFB1859031ABC"
EXPECTED_P5_3_SIZE = 851076
EXPECTED_P5_3_SHA256 = "0653EE7722D7A0B0D0194E8605BC70BADC5AE5BCA93A7649825E7AC2ECB80B89"
EXPECTED_P5_5A_SIZE = 851185
EXPECTED_P5_5A_SHA256 = "202240F5A086E4ABAEF5CFCEE09E458E77BDA41761E525566F83B6517146D2F3"
EXPECTED_P5_5D_SIZE = 857478
EXPECTED_P5_5D_SHA256 = "1BC3509C37DCB550F39A4324A2A17B4834029FFD6096C4366C46F05247B16DBA"
EXPECTED_P5_5E_SIZE = 859733
EXPECTED_P5_5E_SHA256 = "DFCDAEFBAEF0C6F2389E721EB377F1FA0DB34E889ED5D5E01E98B4A32DB308C0"
EXPECTED_DEV_SIZE = 862377
EXPECTED_DEV_SHA256 = "C1ACAB802121E3F69ADEA0EBF1AB271C14015124AA28D2D1F8F58F97C8481B7D"
EXPECTED_VENDOR_SIZE = 61679
EXPECTED_VENDOR_SHA256 = "53C6A87F2CFF65C4B9FABADF800D3D0F2291D90E3122174699F1DA4C2C8EF857"
EXPECTED_VENDOR_CLOSURE_SHA256 = (
    "BD591DFEC19FA242F779AE93EBC9B01EB2787A63C25CECFBF0319D682DF355E8"
)
EXPECTED_PRE_OVERLAY_SIZE = 678378
EXPECTED_PRE_OVERLAY_SHA256 = "3A8AD7ADB62372858A03E6B3790C85B6F17336CC8C00029B0E485A9E9593C253"
EXPECTED_HISTORY_MODULE_SIZE = 70504
EXPECTED_HISTORY_MODULE_SHA256 = "D921FAE2FB9AD3F9FDFDBCF9FAFAB1603CD0096EE3088021710C510547AF3395"
EXPECTED_HISTORY_OVERLAY_INPUT_SIZE = 752016
EXPECTED_HISTORY_OVERLAY_INPUT_SHA256 = "9651D2973DEDFC4D8C61D361150BF65790AE6559BB3CD6EC9D17DE7A43C0E98A"
EXPECTED_RELIABILITY_MODULE_SIZE = 21353
EXPECTED_RELIABILITY_MODULE_SHA256 = "50C14C730645EA766D41F7C9C1FAD0273B85FF5A873311C6E44EE10020DC69E6"
EXPECTED_RELIABILITY_MODULE_INPUT_SIZE = 752496
EXPECTED_RELIABILITY_MODULE_INPUT_SHA256 = "90D99BAA0AED88CB61112571D894E47CC323CD1A11ABBCFFF321F6A5F02061D5"
EXPECTED_RELIABILITY_MODULE_OUTPUT_SIZE = 773849
EXPECTED_RELIABILITY_MODULE_OUTPUT_SHA256 = "8ADE556C756571FCD2E14DCAC424400B600D7A137066CA1EF9D23026DFD482BA"
EXPECTED_RELIABILITY_OVERLAY_INPUT_SIZE = 773849
EXPECTED_RELIABILITY_OVERLAY_INPUT_SHA256 = "8ADE556C756571FCD2E14DCAC424400B600D7A137066CA1EF9D23026DFD482BA"
EXPECTED_CHUNKS = [
    "parts/00_module_prelude.pyinc",
    "parts/01_runtime_components.pyinc",
    "parts/02_filter.pyinc",
    "parts/03_spider_runtime.pyinc",
    "parts/04_follow_workflows.pyinc",
    "parts/05_history_sync.pyinc",
    "parts/06_resource_discovery.pyinc",
    "parts/07_resource_ranking.pyinc",
    "parts/08_playback_transport.pyinc",
    "parts/09_metadata_and_utilities.pyinc",
]


def _load_build_module():
    spec = importlib.util.spec_from_file_location("follow_build_pipeline", BUILD_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BUILD = _load_build_module()


def _load_fingerprint_probe_module():
    spec = importlib.util.spec_from_file_location(
        "v80_build_fingerprint_probe", FINGERPRINT_PROBE_SCRIPT,
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


FINGERPRINT_PROBE = _load_fingerprint_probe_module()


def _manifest(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _assembled_bytes(manifest):
    return b"".join((SOURCE_DIR / chunk).read_bytes() for chunk in manifest["chunks"])


def _top_level_class(tree, name):
    matches = [node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == name]
    assert len(matches) == 1, "expected exactly one top-level %s class" % name
    return matches[0]


def _fake_write_result(repo_root):
    output = repo_root / EXPECTED_DEV_OUTPUT
    return {
        "bytes": b"deterministic-v80-development-output\n",
        "sha256": hashlib.sha256(b"deterministic-v80-development-output\n")
        .hexdigest()
        .upper(),
        "size": len(b"deterministic-v80-development-output\n"),
        "output": output,
        "repo_root": repo_root,
        "manifest": {
            "writable": True,
            "output": EXPECTED_DEV_OUTPUT,
        },
        "metadata": {},
    }


def _install_build_result(monkeypatch, repo_root):
    protected = repo_root / EXPECTED_PUBLIC_OUTPUT
    protected.parent.mkdir(parents=True)
    protected.write_bytes(b"frozen-v70-public-output\n")
    monkeypatch.setattr(BUILD, "build_release", lambda manifest_path: _fake_write_result(repo_root))
    return protected


def _symlink_or_skip(link, target, target_is_directory=False):
    try:
        link.symlink_to(target, target_is_directory=target_is_directory)
    except (NotImplementedError, OSError) as exc:
        pytest.skip("symlink creation is unavailable on this platform: %s" % exc)


def test_baseline_manifest_freezes_v70_public_contract():
    manifest = _manifest(BASELINE_MANIFEST_PATH)

    assert manifest["schema_version"] == 1
    assert manifest["contract"] == "baseline_v70"
    assert manifest["id"] == EXPECTED_ID
    assert manifest["version"] == EXPECTED_VERSION
    assert manifest["output"] == EXPECTED_PUBLIC_OUTPUT
    assert manifest["writable"] is False
    assert manifest["index_contract"] == "required"
    assert manifest["expected_size"] == EXPECTED_V70_SIZE
    assert manifest["expected_sha256"] == EXPECTED_V70_SHA256


def test_development_manifest_uses_isolated_output():
    manifest = _manifest(DEV_MANIFEST_PATH)

    assert manifest["contract"] == "v80_development"
    assert manifest["output"] == EXPECTED_DEV_OUTPUT
    assert manifest["writable"] is True
    assert manifest["index_contract"] == "none"
    assert manifest["expected_size"] == EXPECTED_DEV_SIZE
    assert manifest["expected_sha256"] == EXPECTED_DEV_SHA256
    assert manifest["chunks"] == EXPECTED_CHUNKS


def test_manifests_list_all_ten_chunks_once_in_frozen_order():
    for path in (BASELINE_MANIFEST_PATH, DEV_MANIFEST_PATH):
        manifest = _manifest(path)
        assert manifest["chunks"] == EXPECTED_CHUNKS
        assert len(set(manifest["chunks"])) == 10
    assert sorted(path.name for path in PARTS_DIR.glob("*.pyinc")) == [
        Path(chunk).name for chunk in EXPECTED_CHUNKS
    ]


def test_chunks_reconstruct_frozen_v70_byte_for_byte():
    assembled = _assembled_bytes(_manifest(BASELINE_MANIFEST_PATH))

    assert assembled == PUBLIC_RELEASE_PATH.read_bytes()
    assert len(assembled) == EXPECTED_V70_SIZE
    assert hashlib.sha256(assembled).hexdigest().upper() == EXPECTED_V70_SHA256


def test_baseline_check_validates_public_source_and_index():
    result = BUILD.check_release(BASELINE_MANIFEST_PATH)
    index = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    row = next(item for item in index if item.get("id") == EXPECTED_ID)

    assert result["output"] == PUBLIC_RELEASE_PATH.resolve()
    assert result["sha256"] == EXPECTED_V70_SHA256
    assert row == {
        "id": EXPECTED_ID,
        "file": EXPECTED_PUBLIC_OUTPUT,
        "version": EXPECTED_VERSION,
        "valid": True,
    }


def test_development_write_is_deterministic_and_preserves_public_files():
    public_before = PUBLIC_RELEASE_PATH.read_bytes()
    index_before = INDEX_PATH.read_bytes()

    first = BUILD.write_release(DEV_MANIFEST_PATH)
    second = BUILD.write_release(DEV_MANIFEST_PATH)

    assert first["output"].relative_to(ROOT.resolve()).as_posix() == EXPECTED_DEV_OUTPUT
    assert first["output"].read_bytes() == first["bytes"]
    assert first["overlay"]["input_size"] == EXPECTED_PRE_OVERLAY_SIZE
    assert first["overlay"]["input_sha256"] == EXPECTED_PRE_OVERLAY_SHA256
    assert first["overlay"]["size"] == EXPECTED_P2_OVERLAY_SIZE
    assert first["overlay"]["sha256"] == EXPECTED_P2_OVERLAY_SHA256
    assert first["overlay"]["insertions"] == (
        "state", "reset", "destroy", "worker", "order", "payload", "call", "layered",
    )
    assert first["size"] == EXPECTED_DEV_SIZE
    assert first["sha256"] == EXPECTED_DEV_SHA256
    assert first["vendor"]["size"] == EXPECTED_VENDOR_SIZE
    assert first["vendor"]["sha256"] == EXPECTED_VENDOR_SHA256
    assert first["vendor"]["closure_sha256"] == EXPECTED_VENDOR_CLOSURE_SHA256
    assert first["history_module"]["input_size"] == EXPECTED_P2_OVERLAY_SIZE
    assert first["history_module"]["input_sha256"] == EXPECTED_P2_OVERLAY_SHA256
    assert first["history_module"]["size"] == EXPECTED_HISTORY_MODULE_SIZE
    assert first["history_module"]["sha256"] == EXPECTED_HISTORY_MODULE_SHA256
    assert first["history_overlay"]["input_size"] == EXPECTED_HISTORY_OVERLAY_INPUT_SIZE
    assert first["history_overlay"]["input_sha256"] == EXPECTED_HISTORY_OVERLAY_INPUT_SHA256
    assert first["history_overlay"]["insertions"] == (
        "fetch", "push", "delete", "local-row", "cloud-fetch", "local-refresh",
        "upload-count", "import-commit", "lifecycle",
    )
    assert first["history_overlay"]["size"] == EXPECTED_RELIABILITY_MODULE_INPUT_SIZE
    assert first["history_overlay"]["sha256"] == EXPECTED_RELIABILITY_MODULE_INPUT_SHA256
    assert first["reliability_module"]["input_size"] == EXPECTED_RELIABILITY_MODULE_INPUT_SIZE
    assert first["reliability_module"]["input_sha256"] == EXPECTED_RELIABILITY_MODULE_INPUT_SHA256
    assert first["reliability_module"]["size"] == EXPECTED_RELIABILITY_MODULE_SIZE
    assert first["reliability_module"]["sha256"] == EXPECTED_RELIABILITY_MODULE_SHA256
    assert first["reliability_module"]["output_size"] == EXPECTED_RELIABILITY_MODULE_OUTPUT_SIZE
    assert first["reliability_module"]["output_sha256"] == EXPECTED_RELIABILITY_MODULE_OUTPUT_SHA256
    assert first["reliability_overlay"]["input_size"] == EXPECTED_RELIABILITY_OVERLAY_INPUT_SIZE
    assert first["reliability_overlay"]["input_sha256"] == EXPECTED_RELIABILITY_OVERLAY_INPUT_SHA256
    assert first["reliability_overlay"]["insertions"] == (
        "deadline-timeout", "atvp-retry-adapter", "diagnostic-kind",
        "provider-controller", "provider-init-reset", "provider-destroy-reset",
        "provider-transport",
    )
    assert first["reliability_overlay"]["size"] == EXPECTED_RELIABILITY_OVERLAY_SIZE
    assert first["reliability_overlay"]["sha256"] == EXPECTED_RELIABILITY_OVERLAY_SHA256
    assert first["cache_health_module"]["input_size"] == EXPECTED_RELIABILITY_OVERLAY_SIZE
    assert first["cache_health_module"]["input_sha256"] == EXPECTED_RELIABILITY_OVERLAY_SHA256
    assert first["cache_health_module"]["size"] == EXPECTED_CACHE_HEALTH_MODULE_SIZE
    assert first["cache_health_module"]["sha256"] == EXPECTED_CACHE_HEALTH_MODULE_SHA256
    assert first["cache_health_module"]["output_size"] == EXPECTED_CACHE_HEALTH_MODULE_OUTPUT_SIZE
    assert first["cache_health_module"]["output_sha256"] == EXPECTED_CACHE_HEALTH_MODULE_OUTPUT_SHA256
    assert first["cache_health_overlay"]["input_size"] == EXPECTED_CACHE_HEALTH_MODULE_OUTPUT_SIZE
    assert first["cache_health_overlay"]["input_sha256"] == EXPECTED_CACHE_HEALTH_MODULE_OUTPUT_SHA256
    assert first["cache_health_overlay"]["insertions"] == (
        "coordinator", "tmdb", "state", "init-reset", "destroy-reset",
        "douban-json", "douban-text", "refresh", "history",
    )
    assert first["cache_health_overlay"]["size"] == EXPECTED_CACHE_HEALTH_OVERLAY_SIZE
    assert first["cache_health_overlay"]["sha256"] == EXPECTED_CACHE_HEALTH_OVERLAY_SHA256
    assert first["background_bulkhead_module"]["input_size"] == EXPECTED_CACHE_HEALTH_OVERLAY_SIZE
    assert first["background_bulkhead_module"]["input_sha256"] == EXPECTED_CACHE_HEALTH_OVERLAY_SHA256
    assert first["background_bulkhead_module"]["size"] == EXPECTED_BACKGROUND_BULKHEAD_MODULE_SIZE
    assert first["background_bulkhead_module"]["sha256"] == EXPECTED_BACKGROUND_BULKHEAD_MODULE_SHA256
    assert first["background_bulkhead_module"]["output_size"] == EXPECTED_BACKGROUND_BULKHEAD_MODULE_OUTPUT_SIZE
    assert first["background_bulkhead_module"]["output_sha256"] == EXPECTED_BACKGROUND_BULKHEAD_MODULE_OUTPUT_SHA256
    assert first["background_bulkhead_overlay"]["input_size"] == EXPECTED_BACKGROUND_BULKHEAD_MODULE_OUTPUT_SIZE
    assert first["background_bulkhead_overlay"]["input_sha256"] == EXPECTED_BACKGROUND_BULKHEAD_MODULE_OUTPUT_SHA256
    assert first["background_bulkhead_overlay"]["insertions"] == (
        "state", "task-runtime", "init-reset", "destroy-reset",
        "bound-replacement", "entry-preheat", "supplement-search",
        "history-refresh", "history-action", "route-probe",
    )
    assert first["background_bulkhead_overlay"]["size"] == EXPECTED_BACKGROUND_BULKHEAD_OVERLAY_SIZE
    assert first["background_bulkhead_overlay"]["sha256"] == EXPECTED_BACKGROUND_BULKHEAD_OVERLAY_SHA256
    assert first["timeout_budget_module"]["input_size"] == EXPECTED_BACKGROUND_BULKHEAD_OVERLAY_SIZE
    assert first["timeout_budget_module"]["input_sha256"] == EXPECTED_BACKGROUND_BULKHEAD_OVERLAY_SHA256
    assert first["timeout_budget_module"]["size"] == EXPECTED_TIMEOUT_BUDGET_MODULE_SIZE
    assert first["timeout_budget_module"]["sha256"] == EXPECTED_TIMEOUT_BUDGET_MODULE_SHA256
    assert first["timeout_budget_module"]["output_size"] == EXPECTED_TIMEOUT_BUDGET_MODULE_OUTPUT_SIZE
    assert first["timeout_budget_module"]["output_sha256"] == EXPECTED_TIMEOUT_BUDGET_MODULE_OUTPUT_SHA256
    assert first["timeout_budget_overlay"]["input_size"] == EXPECTED_TIMEOUT_BUDGET_MODULE_OUTPUT_SIZE
    assert first["timeout_budget_overlay"]["input_sha256"] == EXPECTED_TIMEOUT_BUDGET_MODULE_OUTPUT_SHA256
    assert first["timeout_budget_overlay"]["insertions"] == (
        "bounded-json-shared", "douban-client", "state", "timeout-helper",
        "background-guard", "init-reset", "destroy-reset", "home", "category",
        "detail", "search", "player", "action", "wish-post", "checked-rows",
        "bounded-reader", "resource-api", "atvp-play", "atvp-parse",
        "pinned-blocking-signature", "pinned-connection", "pinned-close",
        "pinned-submit", "pinned-timeout-close", "probe", "tmdb",
        "retry-adapter", "resolve-user", "legacy-history-request",
        "legacy-history-kwargs", "legacy-history-send", "legacy-history-reauth",
        "legacy-history-login", "legacy-history-login-timeout", "v145-login",
        "v145-login-timeout", "v145-send", "v145-send-loop",
        "v145-send-calls", "v145-fetch", "v145-push", "v145-delete",
    )
    assert first["timeout_budget_overlay"]["size"] == EXPECTED_TIMEOUT_BUDGET_OVERLAY_SIZE
    assert first["timeout_budget_overlay"]["sha256"] == EXPECTED_TIMEOUT_BUDGET_OVERLAY_SHA256
    assert first["security_policy_module"]["input_size"] == EXPECTED_TIMEOUT_BUDGET_OVERLAY_SIZE
    assert first["security_policy_module"]["input_sha256"] == EXPECTED_TIMEOUT_BUDGET_OVERLAY_SHA256
    assert first["security_policy_module"]["size"] == EXPECTED_SECURITY_POLICY_MODULE_SIZE
    assert first["security_policy_module"]["sha256"] == EXPECTED_SECURITY_POLICY_MODULE_SHA256
    assert first["security_policy_module"]["output_size"] == EXPECTED_SECURITY_POLICY_OUTPUT_SIZE
    assert first["security_policy_module"]["output_sha256"] == EXPECTED_SECURITY_POLICY_OUTPUT_SHA256
    assert first["route_security_overlay"]["input_size"] == EXPECTED_SECURITY_POLICY_OUTPUT_SIZE
    assert first["route_security_overlay"]["input_sha256"] == EXPECTED_SECURITY_POLICY_OUTPUT_SHA256
    assert first["route_security_overlay"]["insertions"] == (
        "target-policy", "probe-headers", "redirect-decision", "redirect-transition",
    )
    assert first["route_security_overlay"]["size"] == EXPECTED_ROUTE_SECURITY_OVERLAY_SIZE
    assert first["route_security_overlay"]["sha256"] == EXPECTED_ROUTE_SECURITY_OVERLAY_SHA256
    assert first["json_shape_policy_module"]["input_size"] == EXPECTED_ROUTE_SECURITY_OVERLAY_SIZE
    assert first["json_shape_policy_module"]["input_sha256"] == EXPECTED_ROUTE_SECURITY_OVERLAY_SHA256
    assert first["json_shape_policy_module"]["size"] == EXPECTED_JSON_SHAPE_POLICY_MODULE_SIZE
    assert first["json_shape_policy_module"]["sha256"] == EXPECTED_JSON_SHAPE_POLICY_MODULE_SHA256
    assert first["json_shape_policy_module"]["output_size"] == EXPECTED_P4_3_SIZE
    assert first["json_shape_policy_module"]["output_sha256"] == EXPECTED_P4_3_SHA256
    assert first["tmdb_json_shape_overlay"]["input_size"] == EXPECTED_P4_3_SIZE
    assert first["tmdb_json_shape_overlay"]["input_sha256"] == EXPECTED_P4_3_SHA256
    assert first["tmdb_json_shape_overlay"]["insertions"] == ("tmdb-json-shape",)
    assert first["tmdb_json_shape_overlay"]["size"] == EXPECTED_P4_4_SIZE
    assert first["tmdb_json_shape_overlay"]["sha256"] == EXPECTED_P4_4_SHA256
    assert first["tmdb_response_policy_module"]["input_size"] == EXPECTED_P4_4_SIZE
    assert first["tmdb_response_policy_module"]["input_sha256"] == EXPECTED_P4_4_SHA256
    assert first["tmdb_response_policy_module"]["size"] == EXPECTED_TMDB_RESPONSE_POLICY_MODULE_SIZE
    assert first["tmdb_response_policy_module"]["sha256"] == EXPECTED_TMDB_RESPONSE_POLICY_MODULE_SHA256
    assert first["tmdb_response_policy_module"]["output_size"] == EXPECTED_TMDB_RESPONSE_POLICY_OUTPUT_SIZE
    assert first["tmdb_response_policy_module"]["output_sha256"] == EXPECTED_TMDB_RESPONSE_POLICY_OUTPUT_SHA256
    assert first["tmdb_response_boundary_overlay"]["input_size"] == EXPECTED_TMDB_RESPONSE_POLICY_OUTPUT_SIZE
    assert first["tmdb_response_boundary_overlay"]["input_sha256"] == EXPECTED_TMDB_RESPONSE_POLICY_OUTPUT_SHA256
    assert first["tmdb_response_boundary_overlay"]["insertions"] == (
        "json-response-bounded-mode", "tmdb-response-boundary",
    )
    assert first["tmdb_response_boundary_overlay"]["size"] == EXPECTED_P4_5_SIZE
    assert first["tmdb_response_boundary_overlay"]["sha256"] == EXPECTED_P4_5_SHA256
    assert first["diagnostic_redaction_policy_module"]["input_size"] == EXPECTED_P4_5_SIZE
    assert first["diagnostic_redaction_policy_module"]["input_sha256"] == EXPECTED_P4_5_SHA256
    assert first["diagnostic_redaction_policy_module"]["size"] == (
        EXPECTED_DIAGNOSTIC_REDACTION_POLICY_MODULE_SIZE
    )
    assert first["diagnostic_redaction_policy_module"]["sha256"] == (
        EXPECTED_DIAGNOSTIC_REDACTION_POLICY_MODULE_SHA256
    )
    assert first["diagnostic_redaction_policy_module"]["output_size"] == (
        EXPECTED_DIAGNOSTIC_REDACTION_POLICY_OUTPUT_SIZE
    )
    assert first["diagnostic_redaction_policy_module"]["output_sha256"] == (
        EXPECTED_DIAGNOSTIC_REDACTION_POLICY_OUTPUT_SHA256
    )
    assert first["diagnostic_redaction_overlay"]["input_size"] == (
        EXPECTED_DIAGNOSTIC_REDACTION_POLICY_OUTPUT_SIZE
    )
    assert first["diagnostic_redaction_overlay"]["input_sha256"] == (
        EXPECTED_DIAGNOSTIC_REDACTION_POLICY_OUTPUT_SHA256
    )
    assert first["diagnostic_redaction_overlay"]["insertions"] == (
        "diagnostic-field-redaction", "short-error-redaction",
    )
    assert first["diagnostic_redaction_overlay"]["size"] == EXPECTED_P4_6_SIZE
    assert first["diagnostic_redaction_overlay"]["sha256"] == EXPECTED_P4_6_SHA256
    assert first["douban_response_policy_module"]["input_size"] == EXPECTED_P4_6_SIZE
    assert first["douban_response_policy_module"]["input_sha256"] == EXPECTED_P4_6_SHA256
    assert first["douban_response_policy_module"]["size"] == (
        EXPECTED_DOUBAN_RESPONSE_POLICY_MODULE_SIZE
    )
    assert first["douban_response_policy_module"]["sha256"] == (
        EXPECTED_DOUBAN_RESPONSE_POLICY_MODULE_SHA256
    )
    assert first["douban_response_policy_module"]["output_size"] == (
        EXPECTED_DOUBAN_RESPONSE_POLICY_OUTPUT_SIZE
    )
    assert first["douban_response_policy_module"]["output_sha256"] == (
        EXPECTED_DOUBAN_RESPONSE_POLICY_OUTPUT_SHA256
    )
    assert first["douban_response_boundary_overlay"]["input_size"] == (
        EXPECTED_DOUBAN_RESPONSE_POLICY_OUTPUT_SIZE
    )
    assert first["douban_response_boundary_overlay"]["input_sha256"] == (
        EXPECTED_DOUBAN_RESPONSE_POLICY_OUTPUT_SHA256
    )
    assert first["douban_response_boundary_overlay"]["insertions"] == (
        "douban-json-response-boundary", "douban-wish-response-boundary",
    )
    assert first["douban_response_boundary_overlay"]["size"] == EXPECTED_P4_7_SIZE
    assert first["douban_response_boundary_overlay"]["sha256"] == EXPECTED_P4_7_SHA256
    assert first["douban_html_response_policy_module"]["input_size"] == (
        EXPECTED_P4_7_SIZE
    )
    assert first["douban_html_response_policy_module"]["input_sha256"] == (
        EXPECTED_P4_7_SHA256
    )
    assert first["douban_html_response_policy_module"]["size"] == (
        EXPECTED_DOUBAN_HTML_RESPONSE_POLICY_MODULE_SIZE
    )
    assert first["douban_html_response_policy_module"]["sha256"] == (
        EXPECTED_DOUBAN_HTML_RESPONSE_POLICY_MODULE_SHA256
    )
    assert first["douban_html_response_policy_module"]["output_size"] == (
        EXPECTED_DOUBAN_HTML_RESPONSE_POLICY_OUTPUT_SIZE
    )
    assert first["douban_html_response_policy_module"]["output_sha256"] == (
        EXPECTED_DOUBAN_HTML_RESPONSE_POLICY_OUTPUT_SHA256
    )
    assert first["douban_html_response_boundary_overlay"]["input_size"] == (
        EXPECTED_DOUBAN_HTML_RESPONSE_POLICY_OUTPUT_SIZE
    )
    assert first["douban_html_response_boundary_overlay"]["input_sha256"] == (
        EXPECTED_DOUBAN_HTML_RESPONSE_POLICY_OUTPUT_SHA256
    )
    assert first["douban_html_response_boundary_overlay"]["insertions"] == (
        "douban-html-response-boundary",
        "douban-user-id-response-boundary",
    )
    assert first["douban_html_response_boundary_overlay"]["size"] == (
        EXPECTED_P4_8_SIZE
    )
    assert first["douban_html_response_boundary_overlay"]["sha256"] == (
        EXPECTED_P4_8_SHA256
    )
    assert first["observability_policy_module"]["input_size"] == EXPECTED_P4_8_SIZE
    assert first["observability_policy_module"]["input_sha256"] == EXPECTED_P4_8_SHA256
    assert first["observability_policy_module"]["size"] == (
        EXPECTED_OBSERVABILITY_POLICY_MODULE_SIZE
    )
    assert first["observability_policy_module"]["sha256"] == (
        EXPECTED_OBSERVABILITY_POLICY_MODULE_SHA256
    )
    assert first["observability_policy_module"]["output_size"] == EXPECTED_P5_1_SIZE
    assert first["observability_policy_module"]["output_sha256"] == EXPECTED_P5_1_SHA256
    assert first["observability_runtime_overlay"]["input_size"] == EXPECTED_P5_1_SIZE
    assert first["observability_runtime_overlay"]["input_sha256"] == EXPECTED_P5_1_SHA256
    assert first["observability_runtime_overlay"]["insertions"] == (
        "timeout-operation-correlation-fields",
        "timeout-controller-correlation-sequence-slot",
        "timeout-controller-correlation-sequence-init",
        "timeout-controller-correlation-scope",
        "timeout-controller-diagnostic-context",
        "diagnostic-event-runtime-correlation",
    )
    assert first["observability_runtime_overlay"]["size"] == EXPECTED_P5_2_SIZE
    assert first["observability_runtime_overlay"]["sha256"] == EXPECTED_P5_2_SHA256
    assert first["diagnostics_snapshot_overlay"]["input_size"] == EXPECTED_P5_2_SIZE
    assert first["diagnostics_snapshot_overlay"]["input_sha256"] == EXPECTED_P5_2_SHA256
    assert first["diagnostics_snapshot_overlay"]["insertions"] == (
        "diagnostics-snapshot-envelope",
    )
    assert first["diagnostics_snapshot_overlay"]["size"] == EXPECTED_P5_3_SIZE
    assert first["diagnostics_snapshot_overlay"]["sha256"] == EXPECTED_P5_3_SHA256
    assert first["lifecycle_stability_overlay"]["input_size"] == EXPECTED_P5_3_SIZE
    assert first["lifecycle_stability_overlay"]["input_sha256"] == EXPECTED_P5_3_SHA256
    assert first["lifecycle_stability_overlay"]["insertions"] == (
        "destroy-session-reference-clear",
    )
    assert first["lifecycle_stability_overlay"]["size"] == EXPECTED_P5_5A_SIZE
    assert first["lifecycle_stability_overlay"]["sha256"] == EXPECTED_P5_5A_SHA256
    assert first["search_concurrency_ownership_overlay"]["input_size"] == (
        EXPECTED_P5_5A_SIZE
    )
    assert first["search_concurrency_ownership_overlay"]["input_sha256"] == (
        EXPECTED_P5_5A_SHA256
    )
    assert first["search_concurrency_ownership_overlay"]["alias_zh"] == (
        "搜索并发所有权覆盖层"
    )
    assert first["search_concurrency_ownership_overlay"]["insertions"] == (
        "remove-module-network-runtime",
        "instance-task-runtime",
        "live-init-runtime-seal",
        "live-init-runtime-rebuild",
        "instance-dns-runtime",
        "instance-media-probe-runtime",
        "generation-fenced-mode-submit",
        "resource-mode-generation",
        "resource-mode-api-generation",
        "resource-mode-post-fence",
        "resource-candidates-generation",
        "resource-candidates-supplement-generation",
        "resource-candidates-mode-generation",
        "resource-candidates-post-fence",
        "foreground-generation",
        "bound-replacement-generation",
        "preheat-generation",
        "resource-api-generation-and-response-owner",
        "destroy-search-job-cleanup",
        "remove-admission-attribute",
        "bulkhead-only-supplement-admission",
        "supplement-mode-generation",
        "supplement-worker-owner-cleanup",
        "supplement-submit-owner-cleanup",
    )
    assert first["search_concurrency_ownership_overlay"]["size"] == EXPECTED_P5_5D_SIZE
    assert first["search_concurrency_ownership_overlay"]["sha256"] == EXPECTED_P5_5D_SHA256
    assert first["playback_concurrency_ownership_overlay"]["input_size"] == (
        EXPECTED_P5_5D_SIZE
    )
    assert first["playback_concurrency_ownership_overlay"]["input_sha256"] == (
        EXPECTED_P5_5D_SHA256
    )
    assert first["playback_concurrency_ownership_overlay"]["alias_zh"] == (
        "播放并发所有权覆盖层"
    )
    assert first["playback_concurrency_ownership_overlay"]["insertions"] == (
        "source-switch-generation",
        "source-switch-invalidation-owner",
        "route-quality-save-owner",
        "route-quality-repeat-generation",
        "route-quality-record-generation",
        "player-resume-generation",
        "player-finalize-generation",
    )
    assert first["playback_concurrency_ownership_overlay"]["size"] == EXPECTED_P5_5E_SIZE
    assert first["playback_concurrency_ownership_overlay"]["sha256"] == EXPECTED_P5_5E_SHA256
    assert first["history_concurrency_ownership_overlay"]["input_size"] == (
        EXPECTED_P5_5E_SIZE
    )
    assert first["history_concurrency_ownership_overlay"]["input_sha256"] == (
        EXPECTED_P5_5E_SHA256
    )
    assert first["history_concurrency_ownership_overlay"]["alias_zh"] == (
        "History 并发所有权覆盖层"
    )
    assert first["history_concurrency_ownership_overlay"]["insertions"] == (
        "history-job-owner-state",
        "live-init-history-job-reset",
        "destroy-history-job-reset",
        "background-history-job-admission",
        "background-history-worker-owner-release",
        "background-history-submit-exception-release",
        "background-history-busy-release",
        "manual-history-job-admission",
        "manual-history-worker-owner",
        "manual-history-submit-exception-release",
        "manual-history-busy-release",
        "manual-history-worker-owner-argument",
        "manual-history-worker-owner-release",
    )
    assert first["history_concurrency_ownership_overlay"]["size"] == EXPECTED_DEV_SIZE
    assert first["history_concurrency_ownership_overlay"]["sha256"] == EXPECTED_DEV_SHA256
    assert second["changed"] is False
    assert PUBLIC_RELEASE_PATH.read_bytes() == public_before
    assert INDEX_PATH.read_bytes() == index_before


def test_baseline_manifest_is_never_writable():
    with pytest.raises(BUILD.BuildError, match="read-only"):
        BUILD.write_release(BASELINE_MANIFEST_PATH)


def test_source_readme_has_exact_unique_chinese_aliases_for_all_maintenance_units():
    header = "| 路径 | 中文别名 | 阶段 | 类型 |"
    lines = SOURCE_README_PATH.read_text(encoding="utf-8").splitlines()
    start = lines.index(header) + 2
    rows = []
    for line in lines[start:]:
        if not line.startswith("|"):
            break
        path, alias, stage, kind = [cell.strip().strip("`") for cell in line.strip("|").split("|")]
        rows.append((path, alias, stage, kind))

    contract = json.loads(DEPENDENCY_CONTRACT_PATH.read_text(encoding="utf-8"))
    expected_chunks = {item["path"] for item in contract["chunks"]}
    expected_modules = {path.name for path in SOURCE_DIR.glob("*.py")}
    paths = [path for path, _, _, _ in rows]
    aliases = [alias for _, alias, _, _ in rows]

    assert len(rows) == 46
    assert len(paths) == len(set(paths))
    assert set(paths) == expected_chunks | expected_modules
    assert len(aliases) == len(set(aliases))
    assert all(any("\u4e00" <= char <= "\u9fff" for char in alias) for alias in aliases)
    assert {path for path, _, _, kind in rows if kind == "chunk"} == expected_chunks
    assert {path for path, _, _, kind in rows if kind == "module"} == expected_modules
    assert sum(stage == "P1" for _, _, stage, _ in rows) == 10
    assert sum(stage == "P2" for _, _, stage, _ in rows) == 24
    assert sum(stage in {"P3", "P4", "P5"} for _, _, stage, _ in rows) == 12


def test_development_manifest_rejects_public_output(tmp_path):
    manifest = _manifest(DEV_MANIFEST_PATH)
    manifest["output"] = EXPECTED_PUBLIC_OUTPUT
    path = tmp_path / "release.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(BUILD.BuildError, match="must stay under"):
        BUILD.load_manifest(path)


def test_generated_source_has_valid_ast_and_no_duplicate_spider_or_filter_methods():
    assembled = BUILD.build_release(DEV_MANIFEST_PATH)["bytes"]
    tree = ast.parse(assembled.decode("utf-8"), filename=str(PUBLIC_RELEASE_PATH))

    for class_name in ("Spider", "Filter"):
        class_node = _top_level_class(tree, class_name)
        method_names = [
            node.name
            for node in class_node.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]
        assert len(method_names) == len(set(method_names))


def test_vendor_namespace_allows_identical_imports_and_rejects_v70_replacement(tmp_path):
    builder = BUILD._load_resource_shadow_vendor_builder()
    vendor = builder.build_vendor()
    BUILD._assert_resource_shadow_vendor_namespace(
        "import hashlib\nfrom urllib.parse import urlparse\n",
        tmp_path / "same-imports.py",
        vendor,
        builder,
    )

    with pytest.raises(BUILD.BuildError, match="replace V70 bindings"):
        BUILD._assert_resource_shadow_vendor_namespace(
            "compose_resource_candidate_shadow = None\n",
            tmp_path / "symbol-collision.py",
            vendor,
            builder,
        )

    with pytest.raises(BUILD.BuildError, match="conflict with V70 imports"):
        BUILD._assert_resource_shadow_vendor_namespace(
            "import json as hashlib\n",
            tmp_path / "import-collision.py",
            vendor,
            builder,
        )


def test_chunk_boundaries_do_not_split_decorators_from_methods():
    for path in sorted(PARTS_DIR.glob("*.pyinc")):
        lines = path.read_text(encoding="utf-8").splitlines()
        non_empty = [line for line in lines if line.strip()]
        assert not non_empty[-1].lstrip().startswith("@"), path.name


def test_checked_in_release_metadata_remains_version_70():
    source = PUBLIC_RELEASE_PATH.read_text(encoding="utf-8")
    assert source.count("//@version:70") == 1
    assert "//@id:%s" % EXPECTED_ID in source


def test_windows_reparse_attribute_is_rejected_even_without_symlink_mode():
    fake_stat = SimpleNamespace(
        st_mode=stat.S_IFREG,
        st_file_attributes=getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x0400),
    )

    assert BUILD._is_reparse_or_symlink(fake_stat) is True


def test_fingerprint_probe_uses_overlay_size_and_sha256_as_final_output_identity():
    source = b"final"
    digest = hashlib.sha256(source).hexdigest().upper()
    previous = {"size": 4, "sha256": "A" * 64}
    final = {
        "input_size": 4,
        "input_sha256": "A" * 64,
        "size": len(source),
        "sha256": digest,
    }

    FINGERPRINT_PROBE.validate_fingerprint_chain(source, digest, previous, final)

    final["sha256"] = "B" * 64
    with pytest.raises(RuntimeError, match="assembled source fingerprints"):
        FINGERPRINT_PROBE.validate_fingerprint_chain(source, digest, previous, final)


def test_write_rejects_existing_symlink_target_without_replace(monkeypatch, tmp_path):
    protected = _install_build_result(monkeypatch, tmp_path)
    protected_before = protected.read_bytes()
    output = tmp_path / EXPECTED_DEV_OUTPUT
    output.parent.mkdir(parents=True)
    _symlink_or_skip(output, protected)
    replace_calls = []
    monkeypatch.setattr(BUILD.os, "replace", lambda *args: replace_calls.append(args))

    with pytest.raises(BUILD.BuildError, match="symlink or reparse point"):
        BUILD.write_release(tmp_path / "release.json")

    assert replace_calls == []
    assert protected.read_bytes() == protected_before


def test_write_rejects_symlink_output_parent_without_replace(monkeypatch, tmp_path):
    protected = _install_build_result(monkeypatch, tmp_path)
    protected_before = protected.read_bytes()
    redirect = tmp_path / "redirect"
    redirect.mkdir()
    build_dir = tmp_path / "build"
    build_dir.mkdir()
    _symlink_or_skip(build_dir / "v80-dev", redirect, target_is_directory=True)
    replace_calls = []
    monkeypatch.setattr(BUILD.os, "replace", lambda *args: replace_calls.append(args))

    with pytest.raises(BUILD.BuildError, match="symlink or reparse point"):
        BUILD.write_release(tmp_path / "release.json")

    assert replace_calls == []
    assert protected.read_bytes() == protected_before
    assert not (redirect / Path(EXPECTED_DEV_OUTPUT).name).exists()


def test_write_aborts_when_final_path_check_fails_before_replace(monkeypatch, tmp_path):
    protected = _install_build_result(monkeypatch, tmp_path)
    protected_before = protected.read_bytes()
    output = tmp_path / EXPECTED_DEV_OUTPUT
    replace_calls = []
    monkeypatch.setattr(BUILD.os, "replace", lambda *args: replace_calls.append(args))
    original_assert = BUILD._assert_write_state

    def fail_before_replace(state, stage, check_target=True):
        original_assert(state, stage, check_target=check_target)
        if stage == "before replace":
            raise BUILD.BuildError("simulated resolution change before replace")

    monkeypatch.setattr(BUILD, "_assert_write_state", fail_before_replace)

    with pytest.raises(BUILD.BuildError, match="simulated resolution change"):
        BUILD.write_release(tmp_path / "release.json")

    assert replace_calls == []
    assert protected.read_bytes() == protected_before
    assert not output.exists()
    assert list(output.parent.glob("*.tmp")) == []

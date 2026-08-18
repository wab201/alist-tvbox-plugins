# -*- coding: utf-8 -*-

import copy
import importlib.util
import json
import hashlib
import os
import re
import subprocess
from argparse import Namespace
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parent.parent
GATE_SCRIPT = ROOT / "tools" / "run_v80_stage_gate.py"
DIFFERENTIAL_SCRIPT = ROOT / "work" / "run_v80_p2_macro_a_differential.py"
MACRO_B_DIFFERENTIAL_SCRIPT = ROOT / "work" / "run_v80_p2_macro_b_differential.py"


def _load_gate_module():
    spec = importlib.util.spec_from_file_location("v80_stage_gate", GATE_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


GATE = _load_gate_module()


def _load_differential_module():
    spec = importlib.util.spec_from_file_location("v80_p2_macro_a_differential", DIFFERENTIAL_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


DIFFERENTIAL = _load_differential_module()


def _load_macro_b_differential_module():
    spec = importlib.util.spec_from_file_location(
        "v80_p2_macro_b_differential", MACRO_B_DIFFERENTIAL_SCRIPT,
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MACRO_B_DIFFERENTIAL = _load_macro_b_differential_module()

EXPECTED_P1_MANAGED_FILES = {
    ".gitattributes", ".gitignore", "README.md", "docs/V80_REFACTOR_PLAN.md",
    "plugins/douban_tmdb_follow_single/DEPLOYMENT.md",
    "plugins/douban_tmdb_follow_single/STATUS.md",
    "src/douban_tmdb_follow_single/README.md",
    "src/douban_tmdb_follow_single/baseline_v70.json",
    "src/douban_tmdb_follow_single/dependency_contract.json",
    "src/douban_tmdb_follow_single/release.json",
    "tools/build_follow_plugin.py", "tools/run_v80_stage_gate.py",
    "tests/test_follow_build_pipeline.py", "tests/test_follow_behavior_golden.py",
    "tests/test_v80_stage_gate.py", "tests/fixtures/v70_behavior_golden.json",
    "tests/fixtures/v70_behavior_golden_README.md",
}
EXPECTED_P2_MANAGED_FILES = {
    "src/douban_tmdb_follow_single/resource_candidate_shadow_vendor.json",
    "src/douban_tmdb_follow_single/resource_candidate_merge.py",
    "src/douban_tmdb_follow_single/resource_candidate_ordering.py",
    "src/douban_tmdb_follow_single/resource_candidate_pipeline.py",
    "src/douban_tmdb_follow_single/resource_candidate_shadow_background.py",
    "src/douban_tmdb_follow_single/resource_candidate_shadow_composition.py",
    "src/douban_tmdb_follow_single/resource_candidate_shadow.py",
    "src/douban_tmdb_follow_single/resource_candidate_shadow_policy.py",
    "src/douban_tmdb_follow_single/resource_candidate_shadow_runtime.py",
    "src/douban_tmdb_follow_single/resource_candidate_preference.py",
    "src/douban_tmdb_follow_single/resource_matching.py",
    "src/douban_tmdb_follow_single/resource_models.py",
    "src/douban_tmdb_follow_single/resource_normalization.py",
    "src/douban_tmdb_follow_single/resource_output_admission.py",
    "src/douban_tmdb_follow_single/resource_provider.py",
    "src/douban_tmdb_follow_single/resource_row_identity.py",
    "src/douban_tmdb_follow_single/resource_row_scoring.py",
    "src/douban_tmdb_follow_single/resource_row_merge.py",
    "src/douban_tmdb_follow_single/resource_scoring.py",
    "src/douban_tmdb_follow_single/resource_search_plan.py",
    "src/douban_tmdb_follow_single/resource_search_shadow.py",
    "src/douban_tmdb_follow_single/resource_search_v70_adapter.py",
    "src/douban_tmdb_follow_single/resource_search_shadow_runtime.py",
    "src/douban_tmdb_follow_single/resource_schema.py",
    "src/douban_tmdb_follow_single/resource_shadow.py",
    "tests/fixtures/v80_p2_resource_samples.json",
    "tests/fixtures/v80_p2_resource_samples_README.md",
    "tests/test_v80_p2_resource_candidate_merge.py",
    "tests/test_v80_p2_resource_candidate_pipeline.py",
    "tests/test_v80_p2_resource_candidate_shadow_background.py",
    "tests/test_v80_p2_resource_candidate_shadow_composition.py",
    "tests/test_v80_p2_resource_candidate_shadow.py",
    "tests/test_v80_p2_resource_candidate_shadow_policy.py",
    "tests/test_v80_p2_resource_shadow_vendor.py",
    "tests/test_v80_p2_resource_shadow_overlay.py",
    "tests/test_v80_p2_resource_output_switch_overlay.py",
    "tests/test_v80_p2_resource_candidate_shadow_runtime.py",
    "tests/test_v80_p2_resource_matching.py",
    "tests/test_v80_p2_resource_models.py",
    "tests/test_v80_p2_resource_normalization.py",
    "tests/test_v80_p2_resource_output_admission.py",
    "tests/test_v80_p2_resource_provider.py",
    "tests/test_v80_p2_resource_row_identity.py",
    "tests/test_v80_p2_resource_candidate_ordering.py",
    "tests/test_v80_p2_resource_candidate_preference.py",
    "tests/test_v80_p2_resource_row_scoring.py",
    "tests/test_v80_p2_resource_row_merge.py",
    "tests/test_v80_p2_resource_scoring.py",
    "tests/test_v80_p2_resource_search_plan.py",
    "tests/test_v80_p2_resource_search_shadow.py",
    "tests/test_v80_p2_resource_search_v70_adapter.py",
    "tests/test_v80_p2_resource_search_shadow_runtime.py",
    "tests/test_v80_p2_resource_schema.py",
    "tools/build_v80_resource_shadow_vendor.py",
    "tools/build_v80_resource_shadow_overlay.py",
    "tools/build_v80_resource_output_switch_overlay.py",
    "work/run_v80_p2_19_differential.py",
    "work/run_v80_p2_macro_a_differential.py",
    "work/run_v80_p2_macro_b_differential.py",
}
EXPECTED_P3_MANAGED_FILES = {
    "docs/ALIST_TVBOX_1461_SOURCE_DELTA.md",
    "docs/ALIST_TVBOX_1471_SOURCE_DELTA.md",
    "docs/ALIST_TVBOX_1480_SOURCE_DELTA.md",
    "src/douban_tmdb_follow_single/history_sync_v145.py",
    "tools/build_v80_history_sync_overlay.py",
    "tools/verify_alist_tvbox_1451_contract.py",
    "tools/verify_alist_tvbox_1461_contract.py",
    "tools/verify_alist_tvbox_1471_contract.py",
    "tools/verify_alist_tvbox_1480_contract.py",
    "tools/verify_alist_tvbox_1500_contract.py",
    "tests/test_v80_p3_history_event_queue.py",
    "tests/test_v80_p3_history_sync_v145.py",
    "tests/test_v80_p3_history_sync_overlay.py",
    "tests/test_alist_tvbox_1451_contract.py",
    "tests/test_alist_tvbox_1461_contract.py",
    "tests/test_alist_tvbox_1471_contract.py",
    "tests/test_alist_tvbox_1480_contract.py",
    "tests/test_alist_tvbox_1500_contract.py",
    "src/douban_tmdb_follow_single/reliability_contract.py",
    "tools/build_v80_reliability_overlay.py",
    "tests/test_v80_p3_reliability_contract.py",
    "tests/test_v80_p3_reliability_overlay.py",
    "src/douban_tmdb_follow_single/cache_health_contract.py",
    "tools/build_v80_cache_health_overlay.py",
    "tests/test_v80_p3_cache_health_contract.py",
    "tests/test_v80_p3_cache_health_overlay.py",
    "src/douban_tmdb_follow_single/background_bulkhead_contract.py",
    "tools/build_v80_background_bulkhead_overlay.py",
    "tests/test_v80_p3_background_bulkhead_contract.py",
    "tests/test_v80_p3_background_bulkhead_overlay.py",
    "tools/run_v80_p3_chaos_recovery.py",
    "tests/test_v80_p3_chaos_recovery.py",
    "src/douban_tmdb_follow_single/timeout_budget_contract.py",
    "tools/build_v80_timeout_budget_overlay.py",
    "tests/test_v80_p3_timeout_budget_contract.py",
    "tests/test_v80_p3_timeout_budget_overlay.py",
}
EXPECTED_P4_MANAGED_FILES = {
    "src/douban_tmdb_follow_single/security_policy.py",
    "tests/test_v80_p4_security_policy.py",
    "tools/build_v80_route_security_overlay.py",
    "tests/test_v80_p4_route_security_overlay.py",
    "src/douban_tmdb_follow_single/json_shape_policy.py",
    "tests/test_v80_p4_json_shape_policy.py",
    "tools/build_v80_tmdb_json_shape_overlay.py",
    "tests/test_v80_p4_tmdb_json_shape_overlay.py",
    "src/douban_tmdb_follow_single/tmdb_response_policy.py",
    "tests/test_v80_p4_tmdb_response_policy.py",
    "tools/build_v80_tmdb_response_boundary_overlay.py",
    "tests/test_v80_p4_tmdb_response_boundary_overlay.py",
    "src/douban_tmdb_follow_single/diagnostic_redaction_policy.py",
    "tests/test_v80_p4_diagnostic_redaction_policy.py",
    "tools/build_v80_diagnostic_redaction_overlay.py",
    "tests/test_v80_p4_diagnostic_redaction_overlay.py",
    "tests/fixtures/v80_p4_douban_json_response_fixtures.json",
    "tests/test_v80_p4_douban_response_fixtures.py",
    "src/douban_tmdb_follow_single/douban_response_policy.py",
    "tests/test_v80_p4_douban_response_policy.py",
    "tools/build_v80_douban_response_boundary_overlay.py",
    "tests/test_v80_p4_douban_response_boundary_overlay.py",
    "tests/fixtures/v80_p4_douban_html_response_fixtures.json",
    "tests/fixtures/v80_p4_douban_top250.html",
    "tests/fixtures/v80_p4_douban_wishlist.html",
    "tests/test_v80_p4_douban_html_response_fixtures.py",
    "src/douban_tmdb_follow_single/douban_html_response_policy.py",
    "tests/test_v80_p4_douban_html_response_policy.py",
    "tools/build_v80_douban_html_response_boundary_overlay.py",
    "tests/test_v80_p4_douban_html_response_boundary_overlay.py",
    "docs/V80_P4_SECURITY_POLICY.md",
}
EXPECTED_P5_MANAGED_FILES = {
    "docs/V80_P5_2_RUNTIME_CORRELATION_DECISION.md",
    "docs/V80_P5_3_DIAGNOSTICS_SNAPSHOT_DECISION.md",
    "src/douban_tmdb_follow_single/observability_policy.py",
    "tests/test_v80_p5_observability_policy.py",
    "tools/build_v80_observability_runtime_overlay.py",
    "tests/test_v80_p5_runtime_correlation_overlay.py",
    "tools/build_v80_diagnostics_snapshot_overlay.py",
    "tests/test_v80_p5_diagnostics_snapshot_overlay.py",
    "tools/build_v80_lifecycle_stability_overlay.py",
    "tests/v80_p5_lifecycle_stability_runner.py",
    "tests/test_v80_p5_lifecycle_stability.py",
    "tools/build_v80_search_concurrency_ownership_overlay.py",
    "tests/v80_p5_search_concurrency_runner.py",
    "tests/test_v80_p5_search_concurrency.py",
    "tests/test_v80_p5_search_concurrency_ownership_overlay.py",
    "tools/build_v80_playback_concurrency_ownership_overlay.py",
    "tests/v80_p5_playback_concurrency_runner.py",
    "tests/test_v80_p5_playback_concurrency.py",
    "tests/test_v80_p5_playback_concurrency_ownership_overlay.py",
    "tests/test_v80_p5_playback_concurrency_regressions.py",
    "tools/build_v80_history_concurrency_ownership_overlay.py",
    "tests/v80_p5_history_concurrency_runner.py",
    "tests/test_v80_p5_history_concurrency.py",
    "tests/test_v80_p5_history_concurrency_ownership_overlay.py",
    "work/probe_v80_build_fingerprint.py",
}
EXPECTED_SEARCH_CONCURRENCY_OWNERSHIP_INSERTIONS = [
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
]
EXPECTED_PLAYBACK_CONCURRENCY_OWNERSHIP_INSERTIONS = [
    "source-switch-generation",
    "source-switch-invalidation-owner",
    "route-quality-save-owner",
    "route-quality-repeat-generation",
    "route-quality-record-generation",
    "player-resume-generation",
    "player-finalize-generation",
]
EXPECTED_HISTORY_CONCURRENCY_OWNERSHIP_INSERTIONS = [
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
]
EXPECTED_P1_PARTS = {
    "src/douban_tmdb_follow_single/parts/00_module_prelude.pyinc",
    "src/douban_tmdb_follow_single/parts/01_runtime_components.pyinc",
    "src/douban_tmdb_follow_single/parts/02_filter.pyinc",
    "src/douban_tmdb_follow_single/parts/03_spider_runtime.pyinc",
    "src/douban_tmdb_follow_single/parts/04_follow_workflows.pyinc",
    "src/douban_tmdb_follow_single/parts/05_history_sync.pyinc",
    "src/douban_tmdb_follow_single/parts/06_resource_discovery.pyinc",
    "src/douban_tmdb_follow_single/parts/07_resource_ranking.pyinc",
    "src/douban_tmdb_follow_single/parts/08_playback_transport.pyinc",
    "src/douban_tmdb_follow_single/parts/09_metadata_and_utilities.pyinc",
}


def _args(**overrides):
    values = {
        "report": ROOT / "work" / "test-v80-gate.json",
        "resume_from": None,
        "resume_source_sha256": None,
        "pytest_node": [],
        "partial": True,
        "skip_tests": False,
        "fongmi_root": None,
        "atvp": None,
        "upstream_root": None,
        "command_timeout": GATE.DEFAULT_COMMAND_TIMEOUT,
    }
    values.update(overrides)
    return Namespace(**values)


@pytest.fixture(scope="module")
def release_builds():
    build = GATE._load_build_module()
    return {
        "baseline": build.check_release(GATE.BASELINE_MANIFEST),
        "development": build.build_release(GATE.DEV_MANIFEST),
    }


def _fake_build(baseline, development):
    class FakeBuild(object):
        @staticmethod
        def check_release(_manifest):
            return copy.deepcopy(baseline)

        @staticmethod
        def build_release(_manifest):
            return copy.deepcopy(development)

    return FakeBuild()


def _copy_frozen_structure(tmp_path):
    source = tmp_path / "src"
    for name in ("baseline_v70.json", "release.json", "dependency_contract.json"):
        target = source / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((GATE.SOURCE_DIR / name).read_bytes())
    for relative in GATE.EXPECTED_CHUNKS:
        target = source / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((GATE.SOURCE_DIR / relative).read_bytes())
    return source


def _differential_payload():
    payload = dict(GATE.EXPECTED_MACRO_A_DIFFERENTIAL)
    payload.update({
        "equal": 45000,
        "different": 5000,
        "scenario_counts": dict(GATE.EXPECTED_MACRO_A_SCENARIO_COUNTS),
        "scenario_differences": {
            name: 5000 if name == "selected_different" else 0
            for name in GATE.EXPECTED_MACRO_A_SCENARIO_COUNTS
        },
        "decision_counts": dict(GATE.EXPECTED_MACRO_A_DECISION_COUNTS),
        "report_status_counts": dict(GATE.EXPECTED_MACRO_A_REPORT_STATUS_COUNTS),
        "first_failures": [],
    })
    return payload


def _differential_builds():
    expected = GATE.EXPECTED_MACRO_A_DIFFERENTIAL
    vendor = {
        "size": expected["vendor_size"],
        "sha256": expected["vendor_sha256"],
        "closure_sha256": expected["closure_sha256"],
        "modules": tuple(range(expected["module_count"])),
    }
    return {
        "baseline": {
            "size": expected["baseline_size"],
            "sha256": expected["baseline_sha256"],
        },
        "development": {
            "size": expected["development_size"],
            "sha256": expected["development_sha256"],
            "vendor": vendor,
            "overlay": {
                "input_size": expected["overlay_input_size"],
                "input_sha256": expected["overlay_input_sha256"],
                "insertions": tuple(range(expected["overlay_insertion_count"])),
            },
            "resource_output_switch_overlay": {
                "input_size": expected["output_switch_input_size"],
                "input_sha256": expected["output_switch_input_sha256"],
                "size": expected["output_switch_size"],
                "sha256": expected["output_switch_sha256"],
                "insertions": tuple(range(expected["output_switch_insertion_count"])),
            },
        },
    }


def _macro_b_differential_payload():
    payload = dict(GATE.EXPECTED_MACRO_B_DIFFERENTIAL)
    payload.update({
        "scenario_counts": dict(GATE.EXPECTED_MACRO_B_SCENARIO_COUNTS),
        "decision_counts": dict(GATE.EXPECTED_MACRO_B_DECISION_COUNTS),
        "report_status_counts": dict(GATE.EXPECTED_MACRO_B_REPORT_STATUS_COUNTS),
        "first_failures": [],
    })
    return payload


def _macro_b_differential_builds():
    expected = GATE.EXPECTED_MACRO_B_DIFFERENTIAL
    vendor = {
        "size": expected["vendor_size"],
        "sha256": expected["vendor_sha256"],
        "closure_sha256": expected["closure_sha256"],
        "modules": tuple(range(expected["module_count"])),
    }
    return {
        "baseline": {
            "size": expected["baseline_size"],
            "sha256": expected["baseline_sha256"],
        },
        "development": {
            "size": expected["development_size"],
            "sha256": expected["development_sha256"],
            "vendor": vendor,
            "overlay": {
                "input_size": expected["overlay_input_size"],
                "input_sha256": expected["overlay_input_sha256"],
                "insertions": tuple(range(expected["overlay_insertion_count"])),
            },
            "resource_output_switch_overlay": {
                "input_size": expected["output_switch_input_size"],
                "input_sha256": expected["output_switch_input_sha256"],
                "size": expected["output_switch_size"],
                "sha256": expected["output_switch_sha256"],
                "insertions": tuple(range(expected["output_switch_insertion_count"])),
            },
        },
    }


def _output_admission_steps():
    names = (
        "git_v70_tag", "structure_and_dependency", "p2_module_dag",
        "sensitive_data", "implementation_tree", "build_contracts", "behavior_diff",
        "macro_a_runtime_differential", "macro_b_runtime_differential",
        "chaos_recovery",
        "pytest", "resource_shadow_vendor", "atvp_compatibility",
        "dual_runtime", "fongmi_category_contract", "upstream_contract",
    )
    return [GATE._step(name, "passed") for name in names]


def _source_lock_context(tmp_path):
    repo_root = tmp_path.resolve()
    source_dir = repo_root / "src" / "douban_tmdb_follow_single"
    source_dir.mkdir(parents=True)
    public_relative = Path("py/public-v70.py")
    development_relative = Path("build/v80-dev/development.py")
    public_path = repo_root / public_relative
    public_path.parent.mkdir(parents=True)
    public_bytes = b"frozen-v70\n"
    public_path.write_bytes(public_bytes)
    public_sha256 = hashlib.sha256(public_bytes).hexdigest().upper()
    baseline_manifest = source_dir / "baseline_v70.json"
    dev_manifest = source_dir / "release.json"
    baseline_manifest.write_text(json.dumps({
        "contract": "baseline_v70", "id": "douban_tmdb_follow_single",
        "version": 70, "output": public_relative.as_posix(),
        "writable": False, "index_contract": "required",
        "expected_size": len(public_bytes), "expected_sha256": public_sha256,
    }), encoding="utf-8")
    dev_manifest.write_text(json.dumps({
        "contract": "v80_development", "id": "douban_tmdb_follow_single",
        "version": 70, "output": development_relative.as_posix(),
        "writable": True, "index_contract": "none",
    }), encoding="utf-8")
    index_path = repo_root / "spiders_v2.json"
    index_path.write_text(json.dumps([{
        "id": "douban_tmdb_follow_single", "file": public_relative.as_posix(),
        "version": 70, "valid": True,
    }]), encoding="utf-8")
    builds = {
        "baseline": {
            "output": public_path.resolve(), "bytes": public_bytes,
            "size": len(public_bytes), "sha256": public_sha256,
        },
        "development": {
            "output": (repo_root / development_relative).resolve(),
        },
    }
    steps = [
        GATE._step("git_v70_tag", "passed", actual_commit=GATE.EXPECTED_V70_TAG),
        GATE._step("structure_and_dependency", "passed"),
        GATE._step(
            "output_admission_dry_run", "skipped", admit=False,
            reason="candidate_shadow_unverified",
            evidence={"public_output_untouched": True},
        ),
    ]
    return {
        "steps": steps, "builds": builds, "repo_root": repo_root,
        "baseline_manifest": baseline_manifest, "dev_manifest": dev_manifest,
        "index_path": index_path, "public_path": public_path,
        "expected_size": len(public_bytes), "expected_sha256": public_sha256,
    }


def test_git_tag_mismatch_fails_without_requiring_a_branch(tmp_path):
    (tmp_path / ".git").mkdir()

    def runner(command, **kwargs):
        assert command == ["git", "rev-parse", "refs/tags/v70^{commit}"]
        return subprocess.CompletedProcess(command, 0, stdout="0" * 40 + "\n", stderr="")

    result = GATE.check_git_tag(tmp_path, runner=runner)

    assert result["status"] == "failed"
    assert result["actual_commit"] == "0" * 40
    assert result["expected_commit"] == GATE.EXPECTED_V70_TAG


def test_git_tag_is_skipped_when_git_metadata_is_absent(tmp_path):
    result = GATE.check_git_tag(tmp_path)

    assert result["status"] == "skipped"
    assert result["required"] is False


def test_sensitive_scan_reports_location_without_secret_value(tmp_path):
    source = tmp_path / "settings.json"
    secret = "real-" + "credential-value-123456"
    source.write_text('{"token": "%s"}\n' % secret, encoding="utf-8")

    findings = GATE.scan_sensitive_files([source], repo_root=tmp_path)
    result = GATE.check_sensitive(tmp_path, paths=[source])

    assert findings == [{"path": "settings.json", "line": 1, "rule": "literal_token"}]
    assert result["status"] == "failed"
    assert secret not in json.dumps(result)


def test_sensitive_scan_allows_placeholders_and_test_values(tmp_path):
    source = tmp_path / "example.txt"
    source.write_text(
        'Authorization: "<token>"\npassword="test-password"\n'
        'token="fixture-token"\n'
        'url="https://example.com/subscription/<token>"\n',
        encoding="utf-8",
    )

    assert GATE.scan_sensitive_files([source], repo_root=tmp_path) == []


def test_sensitive_scan_allows_credentials_only_on_reserved_test_hosts(tmp_path):
    source = tmp_path / "reserved-hosts.txt"
    source.write_text(
        'url="https://api.example/path?token=opaque-value"\n'
        'url="https://api.example.test/path?password=opaque-value"\n'
        'url="https://api.invalid/path?sig=opaque-value"\n',
        encoding="utf-8",
    )

    assert GATE.scan_sensitive_files([source], repo_root=tmp_path) == []


def test_sensitive_scan_detects_unquoted_authorization_header(tmp_path):
    source = tmp_path / "request.txt"
    credential = "Bearer " + "credential-value-123456"
    source.write_text("Authorization: %s\n" % credential, encoding="utf-8")

    findings = GATE.scan_sensitive_files([source], repo_root=tmp_path)

    assert findings == [{"path": "request.txt", "line": 1, "rule": "literal_authorization"}]
    assert credential not in json.dumps(findings)


def test_redact_covers_structured_headers_tokens_and_url_credentials():
    secrets = ["bearer-value-123", "basic-value-456", "access-value-789", "pw-value-012"]
    raw = json.dumps(dict([
        ("Author" + "ization", "Bearer " + secrets[0]),
        ("coo" + "kie", "session=" + secrets[1]),
        ("access" + "_token", secrets[2]),
        ("url", "https" + "://user:%s@127.0.0.1/api?refresh_token=%s&ok=1" % (secrets[3], secrets[2])),
    ]))

    redacted = GATE._redact(raw)

    assert all(secret not in redacted for secret in secrets)
    assert "127.0.0.1" in redacted
    assert "ok=1" in redacted


@pytest.mark.parametrize("key", (
    "auth", "key", "sign", "sig", "signature", "auth_key", "auth-key", "expires", "policy",
    "key_pair_id", "Key-Pair-Id", "AWSAccessKeyId", "GoogleAccessId", "wsSecret",
    "hdnts", "hdnea", "X-Amz-Credential", "x-goog-signature",
    "x-oss-signature", "X-Bce-Signature",
))
def test_redact_covers_signed_query_keys(key):
    secret = "".join(("signed", "-", "query", "-", "fixture"))
    raw = "https://example.test/media?%s=%s&ok=1" % (key, secret)

    redacted = GATE._redact(raw)

    assert secret not in redacted
    assert "ok=1" in redacted


@pytest.mark.parametrize("value,secret", (
    ("https://e.test/v?%2578-goog-signature=DOUBLE_QUERY_SECRET", "DOUBLE_QUERY_SECRET"),
    ("https://e.test/%70lay/ENCODED_PATH_SECRET/file.m3u8", "ENCODED_PATH_SECRET"),
    ("https://e.test/%2570arse/DOUBLE_PATH_SECRET/file.m3u8", "DOUBLE_PATH_SECRET"),
    ("https://e.test/v?ok=1&amp;token=HTML_QUERY_SECRET", "HTML_QUERY_SECRET"),
))
def test_redact_reuses_policy_for_encoded_url_structures(value, secret):
    result = GATE._redact(value)

    assert secret not in result
    assert "<redacted>" in result


@pytest.mark.parametrize("route", ("play", "parse", "offline_download", "p"))
def test_redact_covers_credential_path_tokens(route):
    secret = "".join(("path", "-", "value", "-", route))
    raw = "https://example.test/api/%s/%s/file.m3u8?ok=1" % (
        route, secret,
    )
    raw += " relative=/%s/%s/file.m3u8" % (route, secret)

    redacted = GATE._redact(raw)

    assert secret not in redacted
    assert "/%s/<redacted>/file.m3u8" % route in redacted
    assert "ok=1" in redacted


def test_sanitize_redacts_sensitive_dict_values_recursively():
    payload = dict([
        ("Author" + "ization", "Bearer visible"),
        ("nested", [{"client" + "_secret": "visible", "safe": "kept"}]),
        ("refresh" + "-token", {"even": "structured"}),
        ("Set" + "-Cookie", ["sid=visible"]),
        ("Proxy" + "-Authorization", "Basic visible"),
        ("api.key", "visible"),
        ("to" + "ken=visible-key", "safe"),
    ])

    result = GATE._sanitize(payload)

    assert result == {
        "Authorization": "<redacted>",
        "nested": [{"client_secret": "<redacted>", "safe": "kept"}],
        "refresh-token": "<redacted>",
        "Set-Cookie": "<redacted>",
        "Proxy-Authorization": "<redacted>",
        "api.key": "<redacted>",
        ("to" + "ken=<redacted>"): "safe",
    }


def test_sanitize_redacts_sensitive_key_value_pairs():
    result = GATE._sanitize([("Cookie", "sid=visible")])

    assert result == [["Cookie", "<redacted>"]]


@pytest.mark.parametrize("value", (
    "http://example.test:bad/path?" + "to" + "ken=opaque-token",
    "http://example.test:99999/path?" + "to" + "ken=opaque-token",
    "http://user:opaque-user@[invalid",
))
def test_redact_fails_closed_for_malformed_urls(value):
    result = GATE._redact(value)

    assert "opaque" not in result
    assert "<redacted" in result


def test_redact_work_is_bounded_before_pattern_processing():
    result = GATE._redact("x" * (GATE.MAX_OUTPUT * 4))

    assert len(result) == GATE.MAX_OUTPUT + len("\n...<truncated>")


def test_sensitive_scan_handles_unquoted_values_and_local_url_credentials(tmp_path):
    source = tmp_path / "settings.txt"
    first = "client" + "_secret=credential-value-123\n"
    second = "url=http" + "://127.0.0.1:8080/api?access" + "_token=credential-value-456\n"
    source.write_text(
        first + second,
        encoding="utf-8",
    )

    findings = GATE.scan_sensitive_files([source], repo_root=tmp_path)

    assert {item["rule"] for item in findings} == {"literal_client_secret", "credential_url"}


def test_sensitive_scan_ignores_canonical_protocol_header_names(tmp_path):
    source = tmp_path / "header-map.py"
    source.write_text(
        '"authorization": "Authorization",\n'
        '"proxy-authorization": "Proxy-Authorization",\n',
        encoding="utf-8",
    )

    assert GATE.scan_sensitive_files([source], repo_root=tmp_path) == []


def test_managed_sensitive_paths_cover_v80_inventory():
    relative = {path.relative_to(ROOT).as_posix() for path in GATE.managed_sensitive_paths()}
    test_tree = {
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "tests").rglob("*")
        if path.is_file()
        and "__pycache__" not in path.parts
        and path.suffix.lower() != ".pyc"
    }

    assert relative == (
        EXPECTED_P1_MANAGED_FILES | EXPECTED_P2_MANAGED_FILES
        | EXPECTED_P3_MANAGED_FILES | EXPECTED_P4_MANAGED_FILES
        | EXPECTED_P5_MANAGED_FILES | EXPECTED_P1_PARTS | test_tree
    )
    assert relative == {
        path.relative_to(ROOT).as_posix()
        for path in GATE.implementation_tree_paths()
    }


def test_structure_rejects_changed_chunk_order(tmp_path):
    source = tmp_path / "src"
    parts = source / "parts"
    parts.mkdir(parents=True)
    chunks = list(GATE.EXPECTED_CHUNKS)
    for index, relative in enumerate(chunks):
        path = source / relative
        path.write_text("import os\n" if index == 0 else "value_%d = %d\n" % (index, index), encoding="utf-8")
    changed = list(reversed(chunks))
    for name in ("baseline_v70.json", "release.json"):
        (source / name).write_text(json.dumps({"chunks": changed}), encoding="utf-8")

    result = GATE.check_structure(source)

    assert result["status"] == "failed"
    assert "chunk order" in result["detail"]


def test_structure_rejects_import_outside_prelude(tmp_path):
    source = tmp_path / "src"
    (source / "parts").mkdir(parents=True)
    for index, relative in enumerate(GATE.EXPECTED_CHUNKS):
        text = "import os\n" if index in (0, 1) else "value_%d = %d\n" % (index, index)
        (source / relative).write_text(text, encoding="utf-8")
    # Keep class definitions unique so the late import remains a distinct failure.
    (source / GATE.EXPECTED_CHUNKS[-1]).write_text("class Spider:\n    pass\nclass Filter:\n    pass\n", encoding="utf-8")
    manifest = {"chunks": GATE.EXPECTED_CHUNKS}
    for name in ("baseline_v70.json", "release.json"):
        (source / name).write_text(json.dumps(manifest), encoding="utf-8")

    result = GATE.check_structure(source)

    assert result["status"] == "failed"
    assert "outside the prelude" in result["detail"]


def test_structure_verifies_all_frozen_part_hashes(tmp_path):
    result = GATE.check_structure(_copy_frozen_structure(tmp_path))

    assert result["status"] == "passed"
    assert result["frozen_part_sha256_matches"] == 10
    assert result["frozen_part_sha256_expected"] == 10


def test_structure_rejects_shifted_part_boundary_with_identical_assembled_bytes(tmp_path):
    source = _copy_frozen_structure(tmp_path)
    first = source / GATE.EXPECTED_CHUNKS[0]
    second = source / GATE.EXPECTED_CHUNKS[1]
    original = b"".join((source / relative).read_bytes() for relative in GATE.EXPECTED_CHUNKS)
    first_bytes = first.read_bytes()
    second_bytes = second.read_bytes()
    assert first_bytes.endswith(b"\n")
    first.write_bytes(first_bytes[:-1])
    second.write_bytes(b"\n" + second_bytes)

    assert b"".join((source / relative).read_bytes() for relative in GATE.EXPECTED_CHUNKS) == original
    result = GATE.check_structure(source)

    assert result["status"] == "failed"
    assert result["frozen_part_sha256_matches"] == 8
    assert "SHA256 differs from the frozen V70 contract" in result["detail"]


def test_dependency_contract_rejects_reverse_dependency(tmp_path):
    contract = json.loads(GATE.DEPENDENCY_CONTRACT.read_text(encoding="utf-8"))
    contract["chunks"][0]["allowed_dependencies"] = [GATE.EXPECTED_CHUNKS[-1]]
    path = tmp_path / "dependency.json"
    path.write_text(json.dumps(contract), encoding="utf-8")

    try:
        GATE._load_dependency_contract(path)
    except GATE.GateError as exc:
        assert "reverse or unknown" in str(exc)
    else:
        raise AssertionError("reverse dependency was accepted")


def _write_p2_module_dag(source):
    source.mkdir(parents=True)
    (source / "resource_candidate_merge.py").write_text(
        "from .resource_row_identity import IDENTITY\nMERGE = 1\n",
        encoding="utf-8",
    )
    (source / "resource_candidate_ordering.py").write_text("ORDER = 1\n", encoding="utf-8")
    (source / "resource_candidate_pipeline.py").write_text(
        "from .resource_candidate_merge import MERGE\n"
        "from .resource_candidate_ordering import ORDER\n"
        "PIPELINE = 1\n",
        encoding="utf-8",
    )
    (source / "resource_candidate_shadow.py").write_text(
        "from .resource_candidate_ordering import ORDER\n"
        "from .resource_candidate_pipeline import PIPELINE\n"
        "SHADOW = 1\n",
        encoding="utf-8",
    )
    (source / "resource_candidate_shadow_background.py").write_text(
        "BACKGROUND = 1\n", encoding="utf-8",
    )
    (source / "resource_candidate_shadow_composition.py").write_text(
        "from .resource_candidate_ordering import ORDER\n"
        "from .resource_candidate_shadow import SHADOW\n"
        "from .resource_candidate_shadow_policy import POLICY\n"
        "COMPOSITION = 1\n",
        encoding="utf-8",
    )
    (source / "resource_candidate_shadow_policy.py").write_text(
        "POLICY = 1\n", encoding="utf-8",
    )
    (source / "resource_candidate_preference.py").write_text("PREFERENCE = 1\n", encoding="utf-8")
    (source / "resource_matching.py").write_text(
        "from .resource_normalization import TITLE\n",
        encoding="utf-8",
    )
    (source / "resource_models.py").write_text("MODEL = 1\n", encoding="utf-8")
    (source / "resource_normalization.py").write_text("TITLE = 'title'\n", encoding="utf-8")
    (source / "resource_output_admission.py").write_text("ADMISSION = 1\n", encoding="utf-8")
    (source / "resource_provider.py").write_text(
        "from .resource_models import MODEL\n"
        "from .resource_schema import SCHEMA\n"
        "from .resource_shadow import SHADOW_MAP\n"
        "PROVIDER = 1\n",
        encoding="utf-8",
    )
    (source / "resource_row_identity.py").write_text("IDENTITY = 1\n", encoding="utf-8")
    (source / "resource_row_scoring.py").write_text(
        "from .resource_matching import MATCH\n"
        "from .resource_normalization import TITLE\n"
        "from .resource_scoring import SCORE\n",
        encoding="utf-8",
    )
    (source / "resource_row_merge.py").write_text("MERGE = 1\n", encoding="utf-8")
    (source / "resource_scoring.py").write_text(
        "from .resource_matching import MATCH\nfrom .resource_normalization import TITLE\nSCORE = 1\n",
        encoding="utf-8",
    )
    (source / "resource_search_plan.py").write_text(
        "from .resource_provider import PROVIDER\n"
        "from .resource_schema import SCHEMA\n"
        "PLAN = 1\n",
        encoding="utf-8",
    )
    (source / "resource_search_shadow.py").write_text(
        "from .resource_models import MODEL\n"
        "from .resource_provider import PROVIDER\n"
        "from .resource_search_plan import PLAN\n"
        "SEARCH_SHADOW = 1\n",
        encoding="utf-8",
    )
    (source / "resource_search_v70_adapter.py").write_text(
        "from .resource_provider import PROVIDER\n"
        "from .resource_row_identity import IDENTITY\n"
        "from .resource_search_plan import PLAN\n"
        "from .resource_search_shadow import SEARCH_SHADOW\n"
        "V70_ADAPTER = 1\n",
        encoding="utf-8",
    )
    (source / "resource_search_shadow_runtime.py").write_text(
        "from .resource_candidate_shadow_background import BACKGROUND\n"
        "from .resource_candidate_shadow_policy import POLICY\n"
        "from .resource_search_v70_adapter import V70_ADAPTER\n"
        "SEARCH_RUNTIME = 1\n",
        encoding="utf-8",
    )
    (source / "resource_schema.py").write_text("SCHEMA = 1\n", encoding="utf-8")
    (source / "resource_shadow.py").write_text(
        "from .resource_models import MODEL\nfrom .resource_schema import SCHEMA\nSHADOW_MAP = 1\n",
        encoding="utf-8",
    )
    for name in ("baseline_v70.json", "release.json"):
        (source / name).write_text(json.dumps({"chunks": []}), encoding="utf-8")


def test_p2_module_dag_accepts_current_modules():
    result = GATE.check_p2_module_dag()

    assert result["status"] == "passed"
    assert "candidate ordering/shadow background/shadow policy/models/normalization/output admission/preference/row identity/row merge/schema are leaves" in result["detail"]
    assert "candidate merge imports row identity" in result["detail"]
    assert "candidate pipeline imports merge/ordering" in result["detail"]
    assert "candidate shadow imports ordering/pipeline" in result["detail"]
    assert "shadow composition imports ordering/shadow/policy" in result["detail"]
    assert "row scoring imports matching/normalization/scoring" in result["detail"]
    assert "provider imports models/schema/shadow" in result["detail"]
    assert "search plan imports provider/schema" in result["detail"]
    assert "search shadow imports models/provider/plan" in result["detail"]
    assert "V70 search adapter imports provider/identity/plan/search shadow" in result["detail"]
    assert "layered search runtime imports background/policy/V70 adapter" in result["detail"]


def test_p2_module_dag_rejects_missing_module(tmp_path):
    source = tmp_path / "src"
    _write_p2_module_dag(source)
    (source / "resource_schema.py").unlink()

    result = GATE.check_p2_module_dag(source)

    assert result["status"] == "failed"
    assert "P2 resource modules differ" in result["detail"]


def test_p2_module_dag_rejects_reverse_relative_import(tmp_path):
    source = tmp_path / "src"
    _write_p2_module_dag(source)
    (source / "resource_models.py").write_text(
        "from .resource_schema import SCHEMA\n",
        encoding="utf-8",
    )

    result = GATE.check_p2_module_dag(source)

    assert result["status"] == "failed"
    assert "resource_models.py dependencies differ" in result["detail"]


def test_p2_module_dag_rejects_non_sibling_relative_import(tmp_path):
    source = tmp_path / "src"
    _write_p2_module_dag(source)
    (source / "resource_shadow.py").write_text(
        "from ..resource_models import MODEL\nfrom .resource_schema import SCHEMA\n",
        encoding="utf-8",
    )

    result = GATE.check_p2_module_dag(source)

    assert result["status"] == "failed"
    assert "non-sibling relative import" in result["detail"]


def test_p2_module_dag_rejects_release_chunk(tmp_path):
    source = tmp_path / "src"
    _write_p2_module_dag(source)
    (source / "release.json").write_text(
        json.dumps({"chunks": ["resource_schema.py"]}),
        encoding="utf-8",
    )

    result = GATE.check_p2_module_dag(source)

    assert result["status"] == "failed"
    assert "release.json includes P2 modules" in result["detail"]


def test_p2_module_dag_rejects_mixed_case_release_chunk(tmp_path):
    source = tmp_path / "src"
    _write_p2_module_dag(source)
    (source / "release.json").write_text(
        json.dumps({"chunks": ["RESOURCE_SCHEMA.PY"]}),
        encoding="utf-8",
    )

    result = GATE.check_p2_module_dag(source)

    assert result["status"] == "failed"
    assert "release.json includes P2 modules" in result["detail"]


def test_command_builder_marks_missing_external_gates_incomplete(tmp_path):
    minimal = GATE.build_commands(_args(skip_tests=True), tmp_path / "artifact.py", tmp_path)
    names = [name for name, _, _ in minimal]

    assert names == ["resource_shadow_vendor", "atvp_compatibility", "dual_runtime"]
    skipped = {row["name"]: row for row in GATE._skipped_command_steps(_args(skip_tests=True))}
    assert skipped["pytest"]["status"] == "skipped"
    assert skipped["upstream_contract"]["required"] is True
    assert skipped["fongmi_category_contract"]["required"] is True


def test_complete_mode_requires_upstream_contract(tmp_path):
    args = _args(
        partial=False,
        fongmi_root=tmp_path / "fongmi",
        atvp=tmp_path / "Atvp.py",
    )

    with pytest.raises(GATE.GateError, match="--upstream-root"):
        GATE._validate_args(args)


def test_implementation_tree_fingerprint_is_stable_and_content_bound(tmp_path):
    first = tmp_path / "first.py"
    second = tmp_path / "second.json"
    first.write_text("value = 1\n", encoding="utf-8")
    second.write_text('{"value": 2}\n', encoding="utf-8")

    initial = GATE.check_implementation_tree(tmp_path, paths=[second, first])
    repeated = GATE.check_implementation_tree(tmp_path, paths=[first, second])

    assert initial["status"] == "passed"
    assert initial["tree_sha256"] == repeated["tree_sha256"]
    assert [row["path"] for row in initial["manifest"]] == ["first.py", "second.json"]

    second.write_text('{"value": 3}\n', encoding="utf-8")
    changed = GATE.check_implementation_tree(tmp_path, paths=[first, second])
    assert changed["tree_sha256"] != initial["tree_sha256"]


def test_default_implementation_tree_covers_managed_docs_and_full_test_tree():
    relative = {
        path.relative_to(ROOT).as_posix()
        for path in GATE.implementation_tree_paths()
    }

    assert EXPECTED_P1_MANAGED_FILES | EXPECTED_P2_MANAGED_FILES | EXPECTED_P1_PARTS <= relative
    assert "tests/test_follow_operation_v51.py" in relative
    assert "tests/test_v61_real_http.py" in relative


def test_implementation_tree_stability_rejects_mid_gate_drift():
    initial = GATE._step(
        "implementation_tree", "passed", file_count=2, tree_sha256="A", manifest=[{"path": "a.py"}],
    )
    current = GATE._step(
        "implementation_tree", "passed", file_count=2, tree_sha256="B", manifest=[{"path": "a.py"}],
    )

    stable = GATE.verify_implementation_tree_stable(initial, initial)
    changed = GATE.verify_implementation_tree_stable(initial, current)

    assert stable["status"] == "passed"
    assert stable["stable_after_commands"] is True
    assert changed["status"] == "failed"
    assert changed["stable_after_commands"] is False
    assert changed["final_tree_sha256"] == "B"


def test_build_contract_records_the_p2_through_p5_build_chain(release_builds):
    step, builds = GATE.check_builds(_fake_build(
        release_builds["baseline"], release_builds["development"],
    ))

    assert step["status"] == "passed"
    assert step["vendor_module_count"] == 17
    assert step["overlay_insertion_count"] == 8
    assert step["overlay_input_sha256"] == builds["development"]["overlay"]["input_sha256"]
    assert step["history_module_sha256"] == builds["development"]["history_module"]["sha256"]
    assert step["history_overlay_insertion_count"] == 9
    assert step["history_overlay_input_sha256"] == (
        builds["development"]["history_overlay"]["input_sha256"]
    )
    assert step["reliability_module_sha256"] == builds["development"]["reliability_module"]["sha256"]
    assert step["reliability_module_input_sha256"] == (
        builds["development"]["reliability_module"]["input_sha256"]
    )
    assert step["reliability_overlay_insertion_count"] == 7
    assert step["reliability_overlay_input_sha256"] == (
        builds["development"]["reliability_overlay"]["input_sha256"]
    )
    assert step["cache_health_module_sha256"] == (
        builds["development"]["cache_health_module"]["sha256"]
    )
    assert step["cache_health_module_input_sha256"] == (
        builds["development"]["cache_health_module"]["input_sha256"]
    )
    assert step["cache_health_overlay_insertion_count"] == 9
    assert step["cache_health_overlay_input_sha256"] == (
        builds["development"]["cache_health_overlay"]["input_sha256"]
    )
    assert step["background_bulkhead_module_sha256"] == (
        builds["development"]["background_bulkhead_module"]["sha256"]
    )
    assert step["background_bulkhead_module_input_sha256"] == (
        builds["development"]["background_bulkhead_module"]["input_sha256"]
    )
    assert step["background_bulkhead_overlay_insertion_count"] == 10
    assert step["background_bulkhead_overlay_input_sha256"] == (
        builds["development"]["background_bulkhead_overlay"]["input_sha256"]
    )
    assert step["timeout_budget_module_sha256"] == (
        builds["development"]["timeout_budget_module"]["sha256"]
    )
    assert step["timeout_budget_module_input_sha256"] == (
        builds["development"]["timeout_budget_module"]["input_sha256"]
    )
    assert step["timeout_budget_overlay_insertion_count"] == 42
    assert step["timeout_budget_overlay_input_sha256"] == (
        builds["development"]["timeout_budget_overlay"]["input_sha256"]
    )
    assert step["security_policy_module_sha256"] == (
        builds["development"]["security_policy_module"]["sha256"]
    )
    assert step["security_policy_module_input_sha256"] == (
        builds["development"]["security_policy_module"]["input_sha256"]
    )
    assert step["route_security_overlay_insertion_count"] == 9
    assert step["route_security_overlay_input_sha256"] == (
        builds["development"]["route_security_overlay"]["input_sha256"]
    )
    assert step["route_security_overlay_sha256"] == (
        builds["development"]["route_security_overlay"]["sha256"]
    )
    assert step["json_shape_policy_module_sha256"] == (
        builds["development"]["json_shape_policy_module"]["sha256"]
    )
    assert step["json_shape_policy_module_input_sha256"] == (
        builds["development"]["json_shape_policy_module"]["input_sha256"]
    )
    assert step["tmdb_json_shape_overlay_insertion_count"] == 1
    assert step["tmdb_json_shape_overlay_input_sha256"] == (
        builds["development"]["tmdb_json_shape_overlay"]["input_sha256"]
    )
    assert step["tmdb_json_shape_overlay_sha256"] == (
        builds["development"]["tmdb_json_shape_overlay"]["sha256"]
    )
    assert step["tmdb_response_policy_module_sha256"] == (
        builds["development"]["tmdb_response_policy_module"]["sha256"]
    )
    assert step["tmdb_response_policy_module_input_sha256"] == (
        builds["development"]["tmdb_response_policy_module"]["input_sha256"]
    )
    assert step["tmdb_response_boundary_overlay_insertion_count"] == 2
    assert step["tmdb_response_boundary_overlay_input_sha256"] == (
        builds["development"]["tmdb_response_boundary_overlay"]["input_sha256"]
    )
    assert step["tmdb_response_boundary_overlay_sha256"] == (
        builds["development"]["tmdb_response_boundary_overlay"]["sha256"]
    )
    assert step["diagnostic_redaction_policy_module_sha256"] == (
        builds["development"]["diagnostic_redaction_policy_module"]["sha256"]
    )
    assert step["diagnostic_redaction_policy_module_input_sha256"] == (
        builds["development"]["diagnostic_redaction_policy_module"]["input_sha256"]
    )
    assert step["diagnostic_redaction_overlay_insertion_count"] == 2
    assert step["diagnostic_redaction_overlay_input_sha256"] == (
        builds["development"]["diagnostic_redaction_overlay"]["input_sha256"]
    )
    assert step["diagnostic_redaction_overlay_sha256"] == (
        builds["development"]["diagnostic_redaction_overlay"]["sha256"]
    )
    assert step["douban_response_policy_module_sha256"] == (
        builds["development"]["douban_response_policy_module"]["sha256"]
    )
    assert step["douban_response_policy_module_input_sha256"] == (
        builds["development"]["douban_response_policy_module"]["input_sha256"]
    )
    assert step["douban_response_boundary_overlay_insertion_count"] == 2
    assert step["douban_response_boundary_overlay_input_sha256"] == (
        builds["development"]["douban_response_boundary_overlay"]["input_sha256"]
    )
    assert step["douban_response_boundary_overlay_sha256"] == (
        builds["development"]["douban_response_boundary_overlay"]["sha256"]
    )
    assert step["douban_html_response_policy_module_sha256"] == (
        builds["development"]["douban_html_response_policy_module"]["sha256"]
    )
    assert step["douban_html_response_policy_module_input_sha256"] == (
        builds["development"]["douban_html_response_policy_module"][
            "input_sha256"
        ]
    )
    assert step["douban_html_response_boundary_overlay_insertion_count"] == 2
    assert step["douban_html_response_boundary_overlay_input_sha256"] == (
        builds["development"]["douban_html_response_boundary_overlay"][
            "input_sha256"
        ]
    )
    assert step["douban_html_response_boundary_overlay_sha256"] == (
        builds["development"]["douban_html_response_boundary_overlay"]["sha256"]
    )
    assert step["observability_policy_module_sha256"] == (
        builds["development"]["observability_policy_module"]["sha256"]
    )
    assert step["observability_policy_module_size"] == (
        builds["development"]["observability_policy_module"]["size"]
    )
    assert step["observability_policy_module_input_sha256"] == (
        builds["development"]["observability_policy_module"]["input_sha256"]
    )
    assert step["observability_runtime_overlay_insertion_count"] == 6
    assert step["observability_runtime_overlay_input_sha256"] == (
        builds["development"]["observability_runtime_overlay"]["input_sha256"]
    )
    assert step["observability_runtime_overlay_sha256"] == (
        builds["development"]["observability_runtime_overlay"]["sha256"]
    )
    assert step["diagnostics_snapshot_overlay_insertion_count"] == 1
    assert step["diagnostics_snapshot_overlay_input_sha256"] == (
        builds["development"]["diagnostics_snapshot_overlay"]["input_sha256"]
    )
    assert step["diagnostics_snapshot_overlay_sha256"] == (
        builds["development"]["diagnostics_snapshot_overlay"]["sha256"]
    )
    assert step["lifecycle_stability_overlay_insertion_count"] == 1
    assert step["lifecycle_stability_overlay_input_sha256"] == (
        builds["development"]["lifecycle_stability_overlay"]["input_sha256"]
    )
    assert step["lifecycle_stability_overlay_sha256"] == (
        builds["development"]["lifecycle_stability_overlay"]["sha256"]
    )
    assert step["search_concurrency_ownership_overlay_insertion_count"] == 24
    assert step["search_concurrency_ownership_overlay_insertions"] == (
        EXPECTED_SEARCH_CONCURRENCY_OWNERSHIP_INSERTIONS
    )
    assert step["search_concurrency_ownership_overlay_input_sha256"] == (
        builds["development"]["search_concurrency_ownership_overlay"][
            "input_sha256"
        ]
    )
    assert step["search_concurrency_ownership_overlay_sha256"] == (
        builds["development"]["search_concurrency_ownership_overlay"]["sha256"]
    )
    assert step["playback_concurrency_ownership_overlay_insertion_count"] == 7
    assert step["playback_concurrency_ownership_overlay_insertions"] == (
        EXPECTED_PLAYBACK_CONCURRENCY_OWNERSHIP_INSERTIONS
    )
    assert step["playback_concurrency_ownership_overlay_input_sha256"] == (
        builds["development"]["playback_concurrency_ownership_overlay"][
            "input_sha256"
        ]
    )
    assert step["playback_concurrency_ownership_overlay_sha256"] == (
        builds["development"]["playback_concurrency_ownership_overlay"]["sha256"]
    )
    assert step["history_concurrency_ownership_overlay_insertion_count"] == 13
    assert step["history_concurrency_ownership_overlay_insertions"] == (
        EXPECTED_HISTORY_CONCURRENCY_OWNERSHIP_INSERTIONS
    )
    assert step["history_concurrency_ownership_overlay_input_sha256"] == (
        builds["development"]["history_concurrency_ownership_overlay"][
            "input_sha256"
        ]
    )
    assert step["history_concurrency_ownership_overlay_sha256"] == (
        builds["development"]["history_concurrency_ownership_overlay"]["sha256"]
    )
    assert step["resource_output_switch_overlay_insertion_count"] == 9
    assert step["resource_output_switch_overlay_insertions"] == [
        "controlled-switch-state",
        "private-raw-plugin-config",
        "shared-output-owner",
        "shared-binding-owner",
        "shared-recent-owner",
        "foreground-production-owner",
        "background-production-owner",
        "background-shadow-legacy-owner",
        "background-shadow-candidate-owner",
    ]
    assert step["resource_output_switch_overlay_input_sha256"] == (
        builds["development"]["resource_output_switch_overlay"]["input_sha256"]
    )
    assert step["resource_output_switch_overlay_sha256"] == (
        builds["development"]["resource_output_switch_overlay"]["sha256"]
    )


def test_build_contract_rejects_an_overlay_not_based_on_v70_plus_vendor():
    class FakeBuild(object):
        @staticmethod
        def check_release(_manifest):
            return {"bytes": b"v70\n", "sha256": "A", "size": 4}

        @staticmethod
        def build_release(_manifest):
            return {
                "bytes": b"vendor\n",
                "sha256": "B",
                "size": 7,
                "output": Path("missing-development-output.py"),
                "vendor": {
                    "bytes": b"vendor\n",
                    "sha256": "C",
                    "closure_sha256": "D",
                    "size": 7,
                    "modules": ("one.py",),
                },
                "overlay": {
                    "input_size": 1,
                    "input_sha256": "wrong",
                    "size": 7,
                    "sha256": "B",
                    "insertions": ("call",),
                },
            }

    step, builds = GATE.check_builds(FakeBuild())

    assert step["status"] == "failed"
    assert "overlay input size" in step["detail"]
    assert builds is None


def _tamper_reliability_chain_consistently(development):
    module = development["reliability_module"]
    module_bytes = b"# consistently tampered reliability module\n"
    module_output = module["input_bytes"] + module_bytes
    module.update({
        "bytes": module_bytes,
        "size": len(module_bytes),
        "sha256": hashlib.sha256(module_bytes).hexdigest().upper(),
        "output_size": len(module_output),
        "output_sha256": hashlib.sha256(module_output).hexdigest().upper(),
    })
    rebuilt = GATE._load_reliability_overlay_builder().apply_reliability_overlay(
        module_output
    )
    development["reliability_overlay"].update({
        key: value for key, value in rebuilt.items() if key != "bytes"
    })


@pytest.mark.parametrize("mutation,expected_detail", (
    (
        lambda development: development["reliability_module"].update(input_sha256="0" * 64),
        "Reliability module is not based on the History overlay output",
    ),
    (
        lambda development: development["reliability_module"].update(bytes=b"changed"),
        "Reliability module size metadata is invalid",
    ),
    (
        lambda development: development["reliability_overlay"].update(input_sha256="0" * 64),
        "Reliability overlay is not based on the appended module output",
    ),
    (
        lambda development: development["reliability_overlay"].update(sha256="0" * 64),
        "Reliability overlay sha256 metadata is invalid",
    ),
    (
        _tamper_reliability_chain_consistently,
        "Reliability overlay output bytes do not match the Cache Health module input",
    ),
))
def test_build_contract_rejects_tampered_reliability_chain(
        release_builds, mutation, expected_detail):
    development = copy.deepcopy(release_builds["development"])
    mutation(development)

    step, builds = GATE.check_builds(_fake_build(
        release_builds["baseline"], development,
    ))

    assert step["status"] == "failed"
    assert expected_detail in step["detail"]
    assert builds is None


def _tamper_cache_health_chain_consistently(development):
    module = development["cache_health_module"]
    module_bytes = b"# consistently tampered cache-health module\n"
    module_output = module["input_bytes"] + module_bytes
    module.update({
        "bytes": module_bytes,
        "size": len(module_bytes),
        "sha256": hashlib.sha256(module_bytes).hexdigest().upper(),
        "output_size": len(module_output),
        "output_sha256": hashlib.sha256(module_output).hexdigest().upper(),
    })
    rebuilt = GATE._load_cache_health_overlay_builder().apply_cache_health_overlay(
        module_output
    )
    development["cache_health_overlay"].update({
        key: value for key, value in rebuilt.items() if key != "bytes"
    })


@pytest.mark.parametrize("mutation,expected_detail", (
    (
        lambda development: development["cache_health_module"].update(input_sha256="0" * 64),
        "Cache Health module is not based on the Reliability overlay output",
    ),
    (
        lambda development: development["cache_health_module"].update(bytes=b"changed"),
        "Cache Health module size metadata is invalid",
    ),
    (
        lambda development: development["cache_health_overlay"].update(input_sha256="0" * 64),
        "Cache Health overlay is not based on the appended module output",
    ),
    (
        lambda development: development["cache_health_overlay"].update(sha256="0" * 64),
        "Cache Health overlay sha256 metadata is invalid",
    ),
    (
        _tamper_cache_health_chain_consistently,
        "Cache Health overlay output bytes do not match the Background Bulkhead module input",
    ),
))
def test_build_contract_rejects_tampered_cache_health_chain(
        release_builds, mutation, expected_detail):
    development = copy.deepcopy(release_builds["development"])
    mutation(development)

    step, builds = GATE.check_builds(_fake_build(
        release_builds["baseline"], development,
    ))

    assert step["status"] == "failed"
    assert expected_detail in step["detail"]
    assert builds is None


def _tamper_background_bulkhead_chain_consistently(development):
    module = development["background_bulkhead_module"]
    module_bytes = b"# consistently tampered background bulkhead module\n"
    module_output = module["input_bytes"] + module_bytes
    module.update({
        "bytes": module_bytes,
        "size": len(module_bytes),
        "sha256": hashlib.sha256(module_bytes).hexdigest().upper(),
        "output_size": len(module_output),
        "output_sha256": hashlib.sha256(module_output).hexdigest().upper(),
    })
    rebuilt = (
        GATE._load_background_bulkhead_overlay_builder()
        .apply_background_bulkhead_overlay(module_output)
    )
    development["background_bulkhead_overlay"].update({
        key: value for key, value in rebuilt.items() if key != "bytes"
    })


@pytest.mark.parametrize("mutation,expected_detail", (
    (
        lambda development: development["background_bulkhead_module"].update(
            input_sha256="0" * 64,
        ),
        "Background Bulkhead module is not based on the Cache Health overlay output",
    ),
    (
        lambda development: development["background_bulkhead_module"].update(
            bytes=b"changed",
        ),
        "Background Bulkhead module size metadata is invalid",
    ),
    (
        lambda development: development["background_bulkhead_overlay"].update(
            input_sha256="0" * 64,
        ),
        "Background Bulkhead overlay is not based on the appended module output",
    ),
    (
        lambda development: development["background_bulkhead_overlay"].update(
            sha256="0" * 64,
        ),
        "Background Bulkhead overlay sha256 metadata is invalid",
    ),
    (
        _tamper_background_bulkhead_chain_consistently,
        "Background Bulkhead overlay output bytes do not match the Timeout Budget module input",
    ),
))
def test_build_contract_rejects_tampered_background_bulkhead_chain(
        release_builds, mutation, expected_detail):
    development = copy.deepcopy(release_builds["development"])
    mutation(development)

    step, builds = GATE.check_builds(_fake_build(
        release_builds["baseline"], development,
    ))

    assert step["status"] == "failed"
    assert expected_detail in step["detail"]
    assert builds is None


def _tamper_timeout_budget_chain_consistently(development):
    module = development["timeout_budget_module"]
    module_bytes = b"# consistently tampered timeout budget module\n"
    module_output = module["input_bytes"] + module_bytes
    module.update({
        "bytes": module_bytes,
        "size": len(module_bytes),
        "sha256": hashlib.sha256(module_bytes).hexdigest().upper(),
        "output_size": len(module_output),
        "output_sha256": hashlib.sha256(module_output).hexdigest().upper(),
    })
    rebuilt = (
        GATE._load_timeout_budget_overlay_builder()
        .apply_timeout_budget_overlay(module_output)
    )
    development["timeout_budget_overlay"].update({
        key: value for key, value in rebuilt.items() if key != "bytes"
    })


@pytest.mark.parametrize("mutation,expected_detail", (
    (
        lambda development: development["timeout_budget_module"].update(
            input_sha256="0" * 64,
        ),
        "Timeout Budget module is not based on the Background Bulkhead overlay output",
    ),
    (
        lambda development: development["timeout_budget_module"].update(bytes=b"changed"),
        "Timeout Budget module size metadata is invalid",
    ),
    (
        lambda development: development["timeout_budget_overlay"].update(
            input_sha256="0" * 64,
        ),
        "Timeout Budget overlay is not based on the appended module output",
    ),
    (
        lambda development: development["timeout_budget_overlay"].update(
            sha256="0" * 64,
        ),
        "Timeout Budget overlay sha256 metadata is invalid",
    ),
    (
        _tamper_timeout_budget_chain_consistently,
        "Timeout Budget overlay output bytes do not match the Security Policy module input",
    ),
))
def test_build_contract_rejects_tampered_timeout_budget_chain(
        release_builds, mutation, expected_detail):
    development = copy.deepcopy(release_builds["development"])
    mutation(development)

    step, builds = GATE.check_builds(_fake_build(
        release_builds["baseline"], development,
    ))

    assert step["status"] == "failed"
    assert expected_detail in step["detail"]
    assert builds is None


def _tamper_security_policy_chain_consistently(development):
    module = development["security_policy_module"]
    module_bytes = b"# consistently forged security policy module\n"
    module_output = module["input_bytes"] + module_bytes
    module.update({
        "bytes": module_bytes,
        "size": len(module_bytes),
        "sha256": hashlib.sha256(module_bytes).hexdigest().upper(),
        "output_size": len(module_output),
        "output_sha256": hashlib.sha256(module_output).hexdigest().upper(),
    })
    development.update({
        "bytes": module_output,
        "size": len(module_output),
        "sha256": hashlib.sha256(module_output).hexdigest().upper(),
    })


@pytest.mark.parametrize("mutation,expected_detail", (
    (
        lambda development: development.pop("security_policy_module"),
        "missing the P4 Security Policy module",
    ),
    (
        lambda development: development["security_policy_module"].update(
            input_sha256="0" * 64,
        ),
        "Security Policy module is not based on the Timeout Budget overlay output",
    ),
    (
        lambda development: development["security_policy_module"].update(bytes=b"changed"),
        "Security Policy module bytes do not match the managed source",
    ),
    (
        _tamper_security_policy_chain_consistently,
        "Security Policy module bytes do not match the managed source",
    ),
))
def test_build_contract_rejects_tampered_security_policy_chain(
        release_builds, mutation, expected_detail):
    development = copy.deepcopy(release_builds["development"])
    mutation(development)

    step, builds = GATE.check_builds(_fake_build(
        release_builds["baseline"], development,
    ))

    assert step["status"] == "failed"
    assert expected_detail in step["detail"]
    assert builds is None


def _tamper_route_security_chain_consistently(development):
    forged_output = development["bytes"] + b"# consistently forged route output\n"
    development["route_security_overlay"].update({
        "size": len(forged_output),
        "sha256": hashlib.sha256(forged_output).hexdigest().upper(),
    })
    development.update({
        "bytes": forged_output,
        "size": len(forged_output),
        "sha256": hashlib.sha256(forged_output).hexdigest().upper(),
    })


@pytest.mark.parametrize("mutation,expected_detail", (
    (
        lambda development: development.pop("route_security_overlay"),
        "missing the P4 Route Security overlay",
    ),
    (
        lambda development: development["route_security_overlay"].update(
            input_sha256="0" * 64,
        ),
        "Route Security overlay is not based on the Security Policy module output",
    ),
    (
        lambda development: development["route_security_overlay"].update(
            insertions=("changed",),
        ),
        "Route Security overlay insertions metadata is invalid",
    ),
    (
        _tamper_route_security_chain_consistently,
        "Route Security overlay size metadata is invalid",
    ),
))
def test_build_contract_rejects_tampered_route_security_chain(
        release_builds, mutation, expected_detail):
    development = copy.deepcopy(release_builds["development"])
    mutation(development)

    step, builds = GATE.check_builds(_fake_build(
        release_builds["baseline"], development,
    ))

    assert step["status"] == "failed"
    assert expected_detail in step["detail"]
    assert builds is None


def _tamper_json_shape_policy_chain_consistently(development):
    module = development["json_shape_policy_module"]
    module_bytes = b"# consistently forged JSON shape policy module\n"
    module_output = module["input_bytes"] + module_bytes
    module.update({
        "bytes": module_bytes,
        "size": len(module_bytes),
        "sha256": hashlib.sha256(module_bytes).hexdigest().upper(),
        "output_size": len(module_output),
        "output_sha256": hashlib.sha256(module_output).hexdigest().upper(),
    })
    development.update({
        "bytes": module_output,
        "size": len(module_output),
        "sha256": hashlib.sha256(module_output).hexdigest().upper(),
    })


@pytest.mark.parametrize("mutation,expected_detail", (
    (
        lambda development: development.pop("json_shape_policy_module"),
        "missing the P4 JSON Shape Policy module",
    ),
    (
        lambda development: development["json_shape_policy_module"].update(
            input_sha256="0" * 64,
        ),
        "JSON Shape Policy module is not based on the Route Security overlay output",
    ),
    (
        lambda development: development["json_shape_policy_module"].update(bytes=b"changed"),
        "JSON Shape Policy module bytes do not match the managed source",
    ),
    (
        _tamper_json_shape_policy_chain_consistently,
        "JSON Shape Policy module bytes do not match the managed source",
    ),
))
def test_build_contract_rejects_tampered_json_shape_policy_chain(
        release_builds, mutation, expected_detail):
    development = copy.deepcopy(release_builds["development"])
    mutation(development)

    step, builds = GATE.check_builds(_fake_build(
        release_builds["baseline"], development,
    ))

    assert step["status"] == "failed"
    assert expected_detail in step["detail"]
    assert builds is None


def _tamper_tmdb_json_shape_overlay_consistently(development):
    policy = development["tmdb_response_policy_module"]
    forged_output = bytearray(policy["input_bytes"])
    forged_output[-1] = ord(" ")
    forged_output = bytes(forged_output)
    forged_sha256 = hashlib.sha256(forged_output).hexdigest().upper()
    development["tmdb_json_shape_overlay"].update({
        "size": len(forged_output),
        "sha256": forged_sha256,
    })


@pytest.mark.parametrize("mutation,expected_detail", (
    (
        lambda development: development.pop("tmdb_json_shape_overlay"),
        "missing the P4 TMDB JSON Shape overlay",
    ),
    (
        lambda development: development["tmdb_json_shape_overlay"].update(
            input_sha256="0" * 64,
        ),
        "TMDB JSON Shape overlay is not based on the JSON Shape Policy output",
    ),
    (
        lambda development: development["tmdb_json_shape_overlay"].update(
            insertions=("changed",),
        ),
        "TMDB JSON Shape overlay insertions metadata is invalid",
    ),
    (
        _tamper_tmdb_json_shape_overlay_consistently,
        "TMDB JSON Shape overlay sha256 metadata is invalid",
    ),
))
def test_build_contract_rejects_tampered_tmdb_json_shape_overlay(
        release_builds, mutation, expected_detail):
    development = copy.deepcopy(release_builds["development"])
    mutation(development)

    step, builds = GATE.check_builds(_fake_build(
        release_builds["baseline"], development,
    ))

    assert step["status"] == "failed"
    assert expected_detail in step["detail"]
    assert builds is None


def _tamper_tmdb_response_policy_chain_consistently(development):
    module = development["tmdb_response_policy_module"]
    module_bytes = b"# consistently forged TMDB response policy module\n"
    module_output = module["input_bytes"] + module_bytes
    module.update({
        "bytes": module_bytes,
        "size": len(module_bytes),
        "sha256": hashlib.sha256(module_bytes).hexdigest().upper(),
        "output_size": len(module_output),
        "output_sha256": hashlib.sha256(module_output).hexdigest().upper(),
    })
    rebuilt = GATE._load_tmdb_response_boundary_overlay_builder().apply_tmdb_response_boundary_overlay(
        module_output
    )
    development["tmdb_response_boundary_overlay"].update({
        key: value for key, value in rebuilt.items() if key != "bytes"
    })
    development.update({
        "bytes": rebuilt["bytes"],
        "size": rebuilt["size"],
        "sha256": rebuilt["sha256"],
    })


@pytest.mark.parametrize("mutation,expected_detail", (
    (
        lambda development: development.pop("tmdb_response_policy_module"),
        "missing the P4 TMDB Response Policy module",
    ),
    (
        lambda development: development["tmdb_response_policy_module"].update(
            input_sha256="0" * 64,
        ),
        "TMDB Response Policy module is not based on the TMDB JSON Shape overlay output",
    ),
    (
        lambda development: development["tmdb_response_policy_module"].update(
            bytes=b"changed",
        ),
        "TMDB Response Policy module bytes do not match the managed source",
    ),
    (
        _tamper_tmdb_response_policy_chain_consistently,
        "TMDB Response Policy module bytes do not match the managed source",
    ),
))
def test_build_contract_rejects_tampered_tmdb_response_policy_chain(
        release_builds, mutation, expected_detail):
    development = copy.deepcopy(release_builds["development"])
    mutation(development)

    step, builds = GATE.check_builds(_fake_build(
        release_builds["baseline"], development,
    ))

    assert step["status"] == "failed"
    assert expected_detail in step["detail"]
    assert builds is None


def _tamper_tmdb_response_boundary_consistently(development):
    forged_output = bytearray(
        development["diagnostic_redaction_policy_module"]["input_bytes"]
    )
    forged_output[-1] = ord(" ")
    forged_output = bytes(forged_output)
    forged_sha256 = hashlib.sha256(forged_output).hexdigest().upper()
    development["tmdb_response_boundary_overlay"].update({
        "size": len(forged_output),
        "sha256": forged_sha256,
    })
    development.update({
        "bytes": forged_output,
        "size": len(forged_output),
        "sha256": forged_sha256,
    })


@pytest.mark.parametrize("mutation,expected_detail", (
    (
        lambda development: development.pop("tmdb_response_boundary_overlay"),
        "missing the P4 TMDB Response Boundary overlay",
    ),
    (
        lambda development: development["tmdb_response_boundary_overlay"].update(
            input_sha256="0" * 64,
        ),
        "TMDB Response Boundary overlay is not based on the policy output",
    ),
    (
        lambda development: development["tmdb_response_boundary_overlay"].update(
            insertions=("changed",),
        ),
        "TMDB Response Boundary overlay insertions metadata is invalid",
    ),
    (
        _tamper_tmdb_response_boundary_consistently,
        "TMDB Response Boundary overlay sha256 metadata is invalid",
    ),
))
def test_build_contract_rejects_tampered_tmdb_response_boundary(
        release_builds, mutation, expected_detail):
    development = copy.deepcopy(release_builds["development"])
    mutation(development)

    step, builds = GATE.check_builds(_fake_build(
        release_builds["baseline"], development,
    ))

    assert step["status"] == "failed"
    assert expected_detail in step["detail"]
    assert builds is None


def _tamper_diagnostic_redaction_policy_consistently(development):
    module = development["diagnostic_redaction_policy_module"]
    module_bytes = b"# consistently forged diagnostic redaction policy module\n"
    module_output = module["input_bytes"] + module_bytes
    module.update({
        "bytes": module_bytes,
        "size": len(module_bytes),
        "sha256": hashlib.sha256(module_bytes).hexdigest().upper(),
        "output_size": len(module_output),
        "output_sha256": hashlib.sha256(module_output).hexdigest().upper(),
    })
    rebuilt = (
        GATE._load_diagnostic_redaction_overlay_builder()
        .apply_diagnostic_redaction_overlay(module_output)
    )
    development["diagnostic_redaction_overlay"].update({
        key: value for key, value in rebuilt.items() if key != "bytes"
    })
    development.update({
        "bytes": rebuilt["bytes"],
        "size": rebuilt["size"],
        "sha256": rebuilt["sha256"],
    })


@pytest.mark.parametrize("mutation,expected_detail", (
    (
        lambda development: development.pop("diagnostic_redaction_policy_module"),
        "missing the P4 Diagnostic Redaction Policy module",
    ),
    (
        lambda development: development["diagnostic_redaction_policy_module"].update(
            input_sha256="0" * 64,
        ),
        "Diagnostic Redaction Policy module is not based on the TMDB Response Boundary overlay output",
    ),
    (
        _tamper_diagnostic_redaction_policy_consistently,
        "Diagnostic Redaction Policy module bytes do not match the managed source",
    ),
))
def test_build_contract_rejects_tampered_diagnostic_redaction_policy(
        release_builds, mutation, expected_detail):
    development = copy.deepcopy(release_builds["development"])
    mutation(development)

    step, builds = GATE.check_builds(_fake_build(
        release_builds["baseline"], development,
    ))

    assert step["status"] == "failed"
    assert expected_detail in step["detail"]
    assert builds is None


def _tamper_diagnostic_redaction_overlay_output(development):
    forged_output = bytearray(
        development["douban_response_policy_module"]["input_bytes"]
    )
    forged_output[-1] = ord(" ")
    forged_output = bytes(forged_output)
    forged_sha256 = hashlib.sha256(forged_output).hexdigest().upper()
    development["diagnostic_redaction_overlay"].update({
        "size": len(forged_output),
        "sha256": forged_sha256,
    })


@pytest.mark.parametrize("mutation,expected_detail", (
    (
        lambda development: development.pop("diagnostic_redaction_overlay"),
        "missing the P4 Diagnostic Redaction overlay",
    ),
    (
        lambda development: development["diagnostic_redaction_overlay"].update(
            input_sha256="0" * 64,
        ),
        "Diagnostic Redaction overlay is not based on the policy output",
    ),
    (
        lambda development: development["diagnostic_redaction_overlay"].update(
            insertions=("changed",),
        ),
        "Diagnostic Redaction overlay insertions metadata is invalid",
    ),
    (
        _tamper_diagnostic_redaction_overlay_output,
        "Diagnostic Redaction overlay sha256 metadata is invalid",
    ),
))
def test_build_contract_rejects_tampered_diagnostic_redaction_overlay(
        release_builds, mutation, expected_detail):
    development = copy.deepcopy(release_builds["development"])
    mutation(development)

    step, builds = GATE.check_builds(_fake_build(
        release_builds["baseline"], development,
    ))

    assert step["status"] == "failed"
    assert expected_detail in step["detail"]
    assert builds is None


def _tamper_douban_response_policy_consistently(development):
    module = development["douban_response_policy_module"]
    module_bytes = b"# consistently forged Douban response policy module\n"
    module_output = module["input_bytes"] + module_bytes
    module.update({
        "bytes": module_bytes,
        "size": len(module_bytes),
        "sha256": hashlib.sha256(module_bytes).hexdigest().upper(),
        "output_size": len(module_output),
        "output_sha256": hashlib.sha256(module_output).hexdigest().upper(),
    })
    rebuilt = (
        GATE._load_douban_response_boundary_overlay_builder()
        .apply_douban_response_boundary_overlay(module_output)
    )
    development["douban_response_boundary_overlay"].update({
        key: value for key, value in rebuilt.items() if key != "bytes"
    })
    development.update({
        "bytes": rebuilt["bytes"],
        "size": rebuilt["size"],
        "sha256": rebuilt["sha256"],
    })


@pytest.mark.parametrize("mutation,expected_detail", (
    (
        lambda development: development.pop("douban_response_policy_module"),
        "missing the P4 Douban Response Policy module",
    ),
    (
        lambda development: development["douban_response_policy_module"].update(
            input_sha256="0" * 64,
        ),
        "Douban Response Policy module is not based on the Diagnostic Redaction overlay output",
    ),
    (
        lambda development: development["douban_response_policy_module"].update(
            bytes=b"changed",
        ),
        "Douban Response Policy module bytes do not match the managed source",
    ),
    (
        _tamper_douban_response_policy_consistently,
        "Douban Response Policy module bytes do not match the managed source",
    ),
))
def test_build_contract_rejects_tampered_douban_response_policy(
        release_builds, mutation, expected_detail):
    development = copy.deepcopy(release_builds["development"])
    mutation(development)

    step, builds = GATE.check_builds(_fake_build(
        release_builds["baseline"], development,
    ))

    assert step["status"] == "failed"
    assert expected_detail in step["detail"]
    assert builds is None


def _tamper_douban_response_boundary_output(development):
    forged_output = bytearray(
        development["douban_html_response_policy_module"]["input_bytes"]
    )
    forged_output[-1] = ord(" ")
    forged_output = bytes(forged_output)
    forged_sha256 = hashlib.sha256(forged_output).hexdigest().upper()
    development["douban_response_boundary_overlay"].update({
        "size": len(forged_output),
        "sha256": forged_sha256,
    })
    development["douban_html_response_policy_module"].update({
        "input_bytes": forged_output,
        "input_size": len(forged_output),
        "input_sha256": forged_sha256,
    })


@pytest.mark.parametrize("mutation,expected_detail", (
    (
        lambda development: development.pop("douban_response_boundary_overlay"),
        "missing the P4 Douban Response Boundary overlay",
    ),
    (
        lambda development: development["douban_response_boundary_overlay"].update(
            input_sha256="0" * 64,
        ),
        "Douban Response Boundary overlay is not based on the policy output",
    ),
    (
        lambda development: development["douban_response_boundary_overlay"].update(
            insertions=("changed",),
        ),
        "Douban Response Boundary overlay insertions metadata is invalid",
    ),
    (
        _tamper_douban_response_boundary_output,
        "Douban Response Boundary overlay sha256 metadata is invalid",
    ),
))
def test_build_contract_rejects_tampered_douban_response_boundary(
        release_builds, mutation, expected_detail):
    development = copy.deepcopy(release_builds["development"])
    mutation(development)

    step, builds = GATE.check_builds(_fake_build(
        release_builds["baseline"], development,
    ))

    assert step["status"] == "failed"
    assert expected_detail in step["detail"]
    assert builds is None


def _tamper_douban_html_response_policy_consistently(development):
    module = development["douban_html_response_policy_module"]
    module_bytes = b"# consistently forged Douban HTML response policy module\n"
    module_output = module["input_bytes"] + module_bytes
    module.update({
        "bytes": module_bytes,
        "size": len(module_bytes),
        "sha256": hashlib.sha256(module_bytes).hexdigest().upper(),
        "output_size": len(module_output),
        "output_sha256": hashlib.sha256(module_output).hexdigest().upper(),
    })
    rebuilt = (
        GATE._load_douban_html_response_boundary_overlay_builder()
        .apply_douban_html_response_boundary_overlay(module_output)
    )
    development["douban_html_response_boundary_overlay"].update({
        key: value for key, value in rebuilt.items() if key != "bytes"
    })
    development.update({
        "bytes": rebuilt["bytes"],
        "size": rebuilt["size"],
        "sha256": rebuilt["sha256"],
    })


@pytest.mark.parametrize("mutation,expected_detail", (
    (
        lambda development: development.pop("douban_html_response_policy_module"),
        "missing the P4 Douban HTML Response Policy module",
    ),
    (
        lambda development: development["douban_html_response_policy_module"].update(
            input_sha256="0" * 64,
        ),
        "Douban HTML Response Policy module is not based on the Douban Response Boundary overlay output",
    ),
    (
        lambda development: development["douban_html_response_policy_module"].update(
            bytes=b"changed",
        ),
        "Douban HTML Response Policy module bytes do not match the managed source",
    ),
    (
        _tamper_douban_html_response_policy_consistently,
        "Douban HTML Response Policy module bytes do not match the managed source",
    ),
))
def test_build_contract_rejects_tampered_douban_html_response_policy(
        release_builds, mutation, expected_detail):
    development = copy.deepcopy(release_builds["development"])
    mutation(development)

    step, builds = GATE.check_builds(_fake_build(
        release_builds["baseline"], development,
    ))

    assert step["status"] == "failed"
    assert expected_detail in step["detail"]
    assert builds is None


def _tamper_douban_html_response_boundary_output(development):
    observability = development["observability_policy_module"]
    forged_output = bytearray(observability["input_bytes"])
    forged_output[-1] = ord(" ")
    forged_output = bytes(forged_output)
    forged_sha256 = hashlib.sha256(forged_output).hexdigest().upper()
    development["douban_html_response_boundary_overlay"].update({
        "size": len(forged_output),
        "sha256": forged_sha256,
    })
    observability_output = forged_output + observability["bytes"]
    observability.update({
        "input_bytes": forged_output,
        "input_size": len(forged_output),
        "input_sha256": forged_sha256,
        "output_size": len(observability_output),
        "output_sha256": hashlib.sha256(observability_output).hexdigest().upper(),
    })
    development.update({
        "bytes": observability_output,
        "size": len(observability_output),
        "sha256": hashlib.sha256(observability_output).hexdigest().upper(),
    })


@pytest.mark.parametrize("mutation,expected_detail", (
    (
        lambda development: development.pop("douban_html_response_boundary_overlay"),
        "missing the P4 Douban HTML Response Boundary overlay",
    ),
    (
        lambda development: development[
            "douban_html_response_boundary_overlay"
        ].update(input_sha256="0" * 64),
        "Douban HTML Response Boundary overlay is not based on the policy output",
    ),
    (
        lambda development: development[
            "douban_html_response_boundary_overlay"
        ].update(insertions=("changed",)),
        "Douban HTML Response Boundary overlay insertions metadata is invalid",
    ),
    (
        _tamper_douban_html_response_boundary_output,
        "Douban HTML Response Boundary overlay sha256 metadata is invalid",
    ),
))
def test_build_contract_rejects_tampered_douban_html_response_boundary(
        release_builds, mutation, expected_detail):
    development = copy.deepcopy(release_builds["development"])
    mutation(development)

    step, builds = GATE.check_builds(_fake_build(
        release_builds["baseline"], development,
    ))

    assert step["status"] == "failed"
    assert expected_detail in step["detail"]
    assert builds is None


def _forge_observability_policy_consistently(development):
    forged_module = b"# forged observability policy\n"
    module = development["observability_policy_module"]
    forged_output = module["input_bytes"] + forged_module
    module.update({
        "bytes": forged_module,
        "size": len(forged_module),
        "sha256": hashlib.sha256(forged_module).hexdigest().upper(),
        "output_size": len(forged_output),
        "output_sha256": hashlib.sha256(forged_output).hexdigest().upper(),
    })
    development.update({
        "bytes": forged_output,
        "size": len(forged_output),
        "sha256": hashlib.sha256(forged_output).hexdigest().upper(),
    })


@pytest.mark.parametrize("mutation,expected_detail", (
    (
        lambda development: development.pop("observability_policy_module"),
        "missing the P5 Observability Policy module",
    ),
    (
        lambda development: development["observability_policy_module"].update(
            input_sha256="0" * 64,
        ),
        "P5 Observability Policy module is not based on the Douban HTML Response Boundary overlay output",
    ),
    (
        lambda development: development["observability_policy_module"].update(
            input_bytes=b"changed",
        ),
        "P4 Douban HTML Response Boundary overlay output bytes do not match the P5 Observability Policy module input",
    ),
    (
        lambda development: development["observability_policy_module"].update(
            bytes=b"changed",
        ),
        "P5 Observability Policy module bytes do not match the managed source",
    ),
    (
        _forge_observability_policy_consistently,
        "P5 Observability Policy module bytes do not match the managed source",
    ),
))
def test_build_contract_rejects_tampered_observability_policy(
        release_builds, mutation, expected_detail):
    development = copy.deepcopy(release_builds["development"])
    mutation(development)

    step, builds = GATE.check_builds(_fake_build(
        release_builds["baseline"], development,
    ))

    assert step["status"] == "failed"
    assert expected_detail in step["detail"]
    assert builds is None


@pytest.mark.parametrize("mutation,expected_detail", (
    (
        lambda development: development.pop("observability_runtime_overlay"),
        "missing the P5 Observability Runtime overlay",
    ),
    (
        lambda development: development["observability_runtime_overlay"].update(
            input_sha256="0" * 64,
        ),
        "P5 Observability Runtime overlay is not based on the policy output",
    ),
    (
        lambda development: development["observability_runtime_overlay"].update(
            insertions=("changed",),
        ),
        "P5 Observability Runtime overlay insertions metadata is invalid",
    ),
    (
        lambda development: development["observability_runtime_overlay"].update(
            sha256="0" * 64,
        ),
        "P5 Observability Runtime overlay sha256 metadata is invalid",
    ),
))
def test_build_contract_rejects_tampered_observability_runtime_overlay(
        release_builds, mutation, expected_detail):
    development = copy.deepcopy(release_builds["development"])
    mutation(development)

    step, builds = GATE.check_builds(_fake_build(
        release_builds["baseline"], development,
    ))

    assert step["status"] == "failed"
    assert expected_detail in step["detail"]
    assert builds is None


def _forge_diagnostics_snapshot_output(development):
    forged_output = bytearray(development["bytes"])
    forged_output[-1] = ord(" ")
    forged_output = bytes(forged_output)
    forged_sha256 = hashlib.sha256(forged_output).hexdigest().upper()
    development["diagnostics_snapshot_overlay"].update({
        "size": len(forged_output),
        "sha256": forged_sha256,
    })
    development.update({
        "bytes": forged_output,
        "size": len(forged_output),
        "sha256": forged_sha256,
    })


@pytest.mark.parametrize("mutation,expected_detail", (
    (
        lambda development: development.pop("diagnostics_snapshot_overlay"),
        "missing the P5 Diagnostics Snapshot overlay",
    ),
    (
        lambda development: development["diagnostics_snapshot_overlay"].update(
            input_sha256="0" * 64,
        ),
        "P5 Diagnostics Snapshot overlay is not based on the runtime overlay",
    ),
    (
        lambda development: development["diagnostics_snapshot_overlay"].update(
            insertions=("changed",),
        ),
        "P5 Diagnostics Snapshot overlay insertions metadata is invalid",
    ),
    (
        _forge_diagnostics_snapshot_output,
        "P5 Diagnostics Snapshot overlay size metadata is invalid",
    ),
))
def test_build_contract_rejects_tampered_diagnostics_snapshot_overlay(
        release_builds, mutation, expected_detail):
    development = copy.deepcopy(release_builds["development"])
    mutation(development)

    step, builds = GATE.check_builds(_fake_build(
        release_builds["baseline"], development,
    ))

    assert step["status"] == "failed"
    assert expected_detail in step["detail"]
    assert builds is None


def _forge_lifecycle_stability_output(development):
    forged_output = bytearray(development["bytes"])
    forged_output[-1] = ord(" ")
    forged_output = bytes(forged_output)
    forged_sha256 = hashlib.sha256(forged_output).hexdigest().upper()
    development["lifecycle_stability_overlay"].update({
        "size": len(forged_output),
        "sha256": forged_sha256,
    })
    development.update({
        "bytes": forged_output,
        "size": len(forged_output),
        "sha256": forged_sha256,
    })


@pytest.mark.parametrize("mutation,expected_detail", (
    (
        lambda development: development.pop("lifecycle_stability_overlay"),
        "missing the P5-5A Lifecycle Stability overlay",
    ),
    (
        lambda development: development["lifecycle_stability_overlay"].update(
            input_sha256="0" * 64,
        ),
        "P5-5A Lifecycle Stability overlay is not based on the diagnostics snapshot output",
    ),
    (
        lambda development: development["lifecycle_stability_overlay"].update(
            insertions=("changed",),
        ),
        "P5-5A Lifecycle Stability overlay insertions metadata is invalid",
    ),
    (
        _forge_lifecycle_stability_output,
        "P5-5A Lifecycle Stability overlay size metadata is invalid",
    ),
))
def test_build_contract_rejects_tampered_lifecycle_stability_overlay(
        release_builds, mutation, expected_detail):
    development = copy.deepcopy(release_builds["development"])
    mutation(development)

    step, builds = GATE.check_builds(_fake_build(
        release_builds["baseline"], development,
    ))

    assert step["status"] == "failed"
    assert expected_detail in step["detail"]
    assert builds is None


def _forge_search_concurrency_ownership_output(development):
    development["search_concurrency_ownership_overlay"].update(
        sha256="F" * 64,
    )


@pytest.mark.parametrize("mutation,expected_detail", (
    (
        lambda development: development.pop(
            "search_concurrency_ownership_overlay"
        ),
        "missing the P5-5D Search Concurrency Ownership overlay",
    ),
    (
        lambda development: development[
            "search_concurrency_ownership_overlay"
        ].update(input_sha256="0" * 64),
        "P5-5D Search Concurrency Ownership overlay is not based on the lifecycle output",
    ),
    (
        lambda development: development[
            "search_concurrency_ownership_overlay"
        ].update(insertions=("changed",)),
        "P5-5D Search Concurrency Ownership overlay insertions metadata is invalid",
    ),
    (
        _forge_search_concurrency_ownership_output,
        "P5-5D Search Concurrency Ownership overlay sha256 metadata is invalid",
    ),
))
def test_build_contract_rejects_tampered_search_concurrency_ownership_overlay(
        release_builds, mutation, expected_detail):
    development = copy.deepcopy(release_builds["development"])
    mutation(development)

    step, builds = GATE.check_builds(_fake_build(
        release_builds["baseline"], development,
    ))

    assert step["status"] == "failed"
    assert expected_detail in step["detail"]
    assert builds is None


def _forge_playback_concurrency_ownership_output(development):
    development["playback_concurrency_ownership_overlay"]["sha256"] = "0" * 64


@pytest.mark.parametrize("mutation,expected_detail", (
    (
        lambda development: development.pop(
            "playback_concurrency_ownership_overlay"
        ),
        "missing the P5-5E Playback Concurrency Ownership overlay",
    ),
    (
        lambda development: development[
            "playback_concurrency_ownership_overlay"
        ].update(input_sha256="0" * 64),
        "P5-5E Playback Concurrency Ownership overlay is not based on the search ownership output",
    ),
    (
        lambda development: development[
            "playback_concurrency_ownership_overlay"
        ].update(insertions=("changed",)),
        "P5-5E Playback Concurrency Ownership overlay insertions metadata is invalid",
    ),
    (
        _forge_playback_concurrency_ownership_output,
        "P5-5E Playback Concurrency Ownership overlay sha256 metadata is invalid",
    ),
))
def test_build_contract_rejects_tampered_playback_concurrency_ownership_overlay(
        release_builds, mutation, expected_detail):
    development = copy.deepcopy(release_builds["development"])
    mutation(development)

    step, builds = GATE.check_builds(_fake_build(
        release_builds["baseline"], development,
    ))

    assert step["status"] == "failed"
    assert expected_detail in step["detail"]
    assert builds is None


def _forge_history_concurrency_ownership_output(development):
    current = development["history_concurrency_ownership_overlay"]["sha256"]
    replacement = ("0" if current[0] != "0" else "1") + current[1:]
    development["history_concurrency_ownership_overlay"]["sha256"] = replacement


@pytest.mark.parametrize("mutation,expected_detail", (
    (
        lambda development: development.pop(
            "history_concurrency_ownership_overlay"
        ),
        "missing the P5-5F History Concurrency Ownership overlay",
    ),
    (
        lambda development: development[
            "history_concurrency_ownership_overlay"
        ].update(input_sha256="0" * 64),
        "P5-5F History Concurrency Ownership overlay is not based on the playback ownership output",
    ),
    (
        lambda development: development[
            "history_concurrency_ownership_overlay"
        ].update(insertions=("changed",)),
        "P5-5F History Concurrency Ownership overlay insertions metadata is invalid",
    ),
    (
        _forge_history_concurrency_ownership_output,
        "P5-5F History Concurrency Ownership overlay sha256 metadata is invalid",
    ),
))
def test_build_contract_rejects_tampered_history_concurrency_ownership_overlay(
        release_builds, mutation, expected_detail):
    development = copy.deepcopy(release_builds["development"])
    mutation(development)

    step, builds = GATE.check_builds(_fake_build(
        release_builds["baseline"], development,
    ))

    assert step["status"] == "failed"
    assert expected_detail in step["detail"]
    assert builds is None


@pytest.mark.parametrize("mutation,expected_detail", (
    (
        lambda development: development.pop("resource_output_switch_overlay"),
        "missing the P2 private resource output switch overlay",
    ),
    (
        lambda development: development["resource_output_switch_overlay"].update(
            input_sha256="0" * 64,
        ),
        "P2 resource output switch overlay is not based on the History ownership output",
    ),
    (
        lambda development: development["resource_output_switch_overlay"].update(
            insertions=("changed",),
        ),
        "P2 resource output switch overlay insertions metadata is invalid",
    ),
    (
        lambda development: development["resource_output_switch_overlay"].update(
            sha256="0" * 64,
        ),
        "P2 resource output switch overlay sha256 metadata is invalid",
    ),
))
def test_build_contract_rejects_tampered_resource_output_switch_overlay(
        release_builds, mutation, expected_detail):
    development = copy.deepcopy(release_builds["development"])
    mutation(development)

    step, builds = GATE.check_builds(_fake_build(
        release_builds["baseline"], development,
    ))

    assert step["status"] == "failed"
    assert expected_detail in step["detail"]
    assert builds is None


def test_command_builder_constructs_all_requested_commands(tmp_path):
    args = _args(
        fongmi_root=tmp_path / "fongmi",
        atvp=tmp_path / "Atvp.py",
        upstream_root=tmp_path / "upstream",
    )

    commands = GATE.build_commands(args, tmp_path / "artifact.py", tmp_path)
    by_name = {name: [str(item) for item in command] for name, command, _ in commands}

    assert list(by_name) == [
        "pytest", "resource_shadow_vendor", "atvp_compatibility", "dual_runtime",
        "fongmi_category_contract", "upstream_contract",
    ]
    assert by_name["pytest"][3:5] == ["-p", "no:cacheprovider"]
    assert by_name["pytest"][5:7] == [
        "-p", GATE.PYTEST_EVIDENCE_PLUGIN_NAME,
    ]
    assert by_name["pytest"][7:9] == [
        "-c", str(tmp_path / "pytest-private" / "pytest.ini"),
    ]
    assert by_name["pytest"][9:11] == [
        "--confcutdir", str(GATE.REPO_ROOT / "tests"),
    ]
    assert by_name["pytest"][11:13] == ["-o", "addopts="]
    assert by_name["pytest"][13:15] == [
        "--basetemp", str(tmp_path / "pytest"),
    ]
    assert by_name["pytest"][15:17] == [
        "--junitxml", str(tmp_path / "pytest-junit.xml"),
    ]
    assert by_name["pytest"][-2:] == ["--durations=30", "tests"]
    assert Path(by_name["resource_shadow_vendor"][1]).name == "build_v80_resource_shadow_vendor.py"
    assert "--runtime" in by_name["atvp_compatibility"]
    assert "upstream-1.25-raw" in by_name["atvp_compatibility"]
    assert "--fongmi-root" in by_name["dual_runtime"]
    assert "--atvp" in by_name["fongmi_category_contract"]


def _write_pytest_junit(command, tests=3, skipped=1, failures=0, errors=0):
    output = Path(command[command.index("--junitxml") + 1])
    output.write_text(
        '<testsuites><testsuite name="pytest" tests="%d" skipped="%d" '
        'failures="%d" errors="%d" time="0.1" /></testsuites>'
        % (tests, skipped, failures, errors),
        encoding="utf-8",
    )


def _write_pytest_selection(
        environment, collected=3, selected=3, deselected=0, exitstatus=0,
        failed_nodeids=None):
    output = Path(environment[GATE.PYTEST_EVIDENCE_ENV])
    output.write_text(json.dumps({
        "schema": GATE.PYTEST_SELECTION_SCHEMA,
        "collected": collected,
        "selected": selected,
        "deselected": deselected,
        "exitstatus": exitstatus,
        "failed_nodeids": list(failed_nodeids or ()),
    }), encoding="utf-8")


def _passed_pytest_step():
    return GATE._step(
        "pytest", "passed",
        pytest_junit={
            "path": "fake-pytest-junit.xml", "collected": 1,
            "executed": 1, "skipped": 0, "failures": 0, "errors": 0,
        },
        pytest_selection={
            "collected": 1, "selected": 1, "deselected": 0,
            "exitstatus": 0, "failed_nodeids": [],
        },
    )


def test_pytest_subprocess_uses_sanitized_environment_and_junit_evidence(
        tmp_path, monkeypatch):
    monkeypatch.setenv("PYTEST_ADDOPTS", "--collect-only")
    monkeypatch.setenv("PYTEST_PLUGINS", "untrusted_plugin")
    monkeypatch.setenv("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "0")
    monkeypatch.setenv("V80_TEST_MARKER", "preserved")

    def runner(command, **kwargs):
        environment = kwargs["env"]
        assert "PYTEST_ADDOPTS" not in environment
        assert "PYTEST_PLUGINS" not in environment
        assert environment["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] == "1"
        assert environment["V80_TEST_MARKER"] == "preserved"
        private_root = Path(environment["PYTHONPATH"].split(os.pathsep)[0])
        assert private_root == tmp_path / "pytest-private"
        assert (private_root / "pytest.ini").read_text(encoding="utf-8") == (
            GATE.PYTEST_PRIVATE_CONFIG_TEXT
        )
        assert (
            private_root / (GATE.PYTEST_EVIDENCE_PLUGIN_NAME + ".py")
        ).read_text(encoding="utf-8") == GATE.PYTEST_EVIDENCE_PLUGIN_TEXT
        _write_pytest_junit(command)
        _write_pytest_selection(environment)
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    result = GATE._run_pytest(tmp_path, runner=runner)

    assert result["status"] == "passed"
    assert result["pytest_junit"] == {
        "path": str(tmp_path / "pytest-junit.xml"),
        "collected": 3,
        "executed": 2,
        "skipped": 1,
        "failures": 0,
        "errors": 0,
    }
    assert result["pytest_selection"] == {
        "path": str(tmp_path / "pytest-selection.json"),
        "collected": 3,
        "selected": 3,
        "deselected": 0,
        "exitstatus": 0,
        "failed_nodeids": [],
    }
    assert result["pytest_isolation"]["confcutdir"] == str(
        GATE.REPO_ROOT / "tests"
    )
    assert result["pytest_isolation"]["addopts_override"] == ""
    assert re.fullmatch(
        r"[0-9A-F]{64}", result["pytest_isolation"]["command_sha256"],
    )
    assert re.fullmatch(
        r"[0-9A-F]{64}",
        result["pytest_isolation"]["private_config_sha256"],
    )
    assert re.fullmatch(
        r"[0-9A-F]{64}",
        result["pytest_isolation"]["evidence_plugin_sha256"],
    )


@pytest.mark.parametrize("tests,skipped,failures,errors,expected_detail", (
    (0, 0, 0, 0, "collected no tests"),
    (2, 2, 0, 0, "executed no tests"),
    (2, 0, 1, 0, "reported 1 failures and 0 errors"),
    (2, 0, 0, 1, "reported 0 failures and 1 errors"),
))
def test_pytest_rejects_success_exit_with_invalid_junit_counts(
        tmp_path, tests, skipped, failures, errors, expected_detail):
    def runner(command, **kwargs):
        _write_pytest_junit(
            command, tests=tests, skipped=skipped,
            failures=failures, errors=errors,
        )
        _write_pytest_selection(
            kwargs["env"], collected=tests, selected=tests,
        )
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    result = GATE._run_pytest(tmp_path, runner=runner)

    assert result["status"] == "failed"
    assert expected_detail in result["detail"]


def test_pytest_rejects_success_exit_without_junit_evidence(tmp_path):
    def runner(command, **kwargs):
        _write_pytest_selection(kwargs["env"])
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    result = GATE._run_pytest(
        tmp_path, runner=runner,
    )

    assert result["status"] == "failed"
    assert "JUnit evidence" in result["detail"]


def test_pytest_rejects_success_exit_with_deselected_machine_evidence(tmp_path):
    def runner(command, **kwargs):
        _write_pytest_junit(command, tests=2, skipped=0)
        _write_pytest_selection(
            kwargs["env"], collected=3, selected=2, deselected=1,
        )
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    result = GATE._run_pytest(tmp_path, runner=runner)

    assert result["status"] == "failed"
    assert result["pytest_selection"]["deselected"] == 1
    assert "deselected 1 tests" in result["detail"]


def test_targeted_pytest_resume_records_legacy_explicit_closure(tmp_path):
    nodeid = "tests/test_sample.py::test_failure"
    resume_source = {
        "sha256": "A" * 64,
        "steps": {"pytest": GATE._step("pytest", "failed")},
    }

    def runner(command, **kwargs):
        assert command[-1] == nodeid
        _write_pytest_junit(command, tests=1, skipped=0)
        _write_pytest_selection(kwargs["env"], collected=1, selected=1)
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    result = GATE._run_pytest(
        tmp_path, runner=runner, selected_nodeids=(nodeid,),
        resume_source=resume_source,
    )

    assert result["status"] == "passed"
    assert result["pytest_resume"]["failure_coverage"] == "legacy-explicit"
    assert result["pytest_resume"]["selected_nodeids"] == [nodeid]
    assert result["pytest_resume"]["unselected_source_evidence_reused"] is True


def test_targeted_pytest_resume_must_cover_recorded_source_failures(tmp_path):
    source_failure = "tests/test_sample.py::test_source_failure"
    selected = "tests/test_sample.py::test_other"
    resume_source = {
        "sha256": "A" * 64,
        "steps": {
            "pytest": GATE._step(
                "pytest", "failed",
                pytest_selection={"failed_nodeids": [source_failure]},
            ),
        },
    }

    def runner(command, **kwargs):
        _write_pytest_junit(command, tests=1, skipped=0)
        _write_pytest_selection(kwargs["env"], collected=1, selected=1)
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    result = GATE._run_pytest(
        tmp_path, runner=runner, selected_nodeids=(selected,),
        resume_source=resume_source,
    )

    assert result["status"] == "failed"
    assert result["pytest_resume"]["failure_coverage"] == "verified"
    assert result["pytest_resume"]["missing_source_failures"] == [source_failure]


def test_failed_pytest_command_still_records_failed_nodeids(tmp_path):
    failed = "tests/test_sample.py::test_failure"

    def runner(command, **kwargs):
        _write_pytest_junit(command, tests=1, skipped=0, failures=1)
        _write_pytest_selection(
            kwargs["env"], collected=1, selected=1, exitstatus=1,
            failed_nodeids=[failed],
        )
        return subprocess.CompletedProcess(command, 1, stdout="", stderr="")

    result = GATE._run_pytest(tmp_path, runner=runner)

    assert result["status"] == "failed"
    assert result["pytest_selection"]["failed_nodeids"] == [failed]


def _write_private_pytest_repo(root):
    test_file = root / "tests" / "test_sample.py"
    test_file.parent.mkdir(parents=True)
    test_file.write_text(
        "def test_first():\n    assert True\n\n"
        "def test_second():\n    assert True\n",
        encoding="utf-8",
    )


def test_pytest_private_config_neutralizes_root_addopts_selection(tmp_path):
    repo = tmp_path / "repo"
    _write_private_pytest_repo(repo)
    (repo / "pytest.ini").write_text(
        "[pytest]\naddopts = -k first\n", encoding="utf-8",
    )

    result = GATE._run_pytest(
        tmp_path / "report-addopts", repo_root=repo, timeout=30,
    )

    assert result["status"] == "passed"
    assert result["pytest_selection"]["selected"] == 2
    assert result["pytest_selection"]["deselected"] == 0


def test_pytest_confcutdir_neutralizes_root_conftest_deselection(tmp_path):
    repo = tmp_path / "repo"
    _write_private_pytest_repo(repo)
    (repo / "conftest.py").write_text(
        "def pytest_collection_modifyitems(items):\n"
        "    items[:] = items[:1]\n",
        encoding="utf-8",
    )

    result = GATE._run_pytest(
        tmp_path / "report-conftest", repo_root=repo, timeout=30,
    )

    assert result["status"] == "passed"
    assert result["pytest_selection"]["selected"] == 2
    assert result["pytest_selection"]["deselected"] == 0


def test_command_failure_is_bounded_redacted_and_required():
    secret = "super-" + "credential-value"

    def runner(command, **kwargs):
        return subprocess.CompletedProcess(
            command, 7, stdout="token=%s\n" % secret, stderr="x" * (GATE.MAX_OUTPUT + 100)
        )

    result = GATE._run_command("example", ["tool"], runner=runner)

    assert result["status"] == "failed"
    assert result["required"] is True
    assert result["exit_code"] == 7
    assert secret not in result["stdout"]
    assert len(result["stderr"]) <= GATE.MAX_OUTPUT + 20


def test_command_timeout_is_a_required_failure_and_redacts_output():
    credential = "timeout-" + "credential-value"

    def runner(command, **kwargs):
        assert kwargs["timeout"] == 3
        raise subprocess.TimeoutExpired(command, 3, output="token=%s" % credential, stderr="late")

    result = GATE._run_command("slow", ["tool"], runner=runner, timeout=3)

    assert result["status"] == "failed"
    assert "timed out" in result["detail"]
    assert credential not in result["stdout"]


def test_invalid_command_timeout_fails_without_calling_runner():
    result = GATE._run_command("bad-timeout", ["tool"], runner=lambda *_a, **_k: None, timeout=float("inf"))

    assert result["status"] == "failed"
    assert "finite" in result["detail"]


def test_git_commit_tolerates_timeout_and_oserror(tmp_path):
    (tmp_path / ".git").mkdir()
    for error in (subprocess.TimeoutExpired(["git"], 1), OSError("missing")):
        def runner(*_args, **_kwargs):
            raise error
        assert GATE._git_commit(tmp_path, runner=runner) is None


def test_behavior_diff_rejects_success_exit_with_difference_report(tmp_path):
    baseline = b"baseline"
    candidate = b"candidate"
    builds = {"baseline": {"bytes": baseline}, "development": {"bytes": candidate}}
    fixture = json.loads(GATE.BEHAVIOR_FIXTURE.read_text(encoding="utf-8"))
    expected = {case["name"]: case["expected"] for case in fixture["cases"]}
    rows = [
        {
            "domain": case["domain"], "name": case["name"], "status": "equal",
            "public": case["expected"], "candidate": case["expected"], "difference": None,
        }
        for case in fixture["cases"]
    ]

    def payload():
        return {
            "schema_version": 1,
            "fixture": {"schema_version": 2, "sha256": hashlib.sha256(GATE.BEHAVIOR_FIXTURE.read_bytes()).hexdigest()},
            "baseline": {"sha256": hashlib.sha256(baseline).hexdigest()},
            "candidate": {"sha256": hashlib.sha256(candidate).hexdigest()},
            "cases": json.loads(json.dumps(rows)),
            "public_results": json.loads(json.dumps(expected)),
            "dev_results": json.loads(json.dumps(expected)),
            "summary": {"total": len(rows), "equal": len(rows), "different": 0},
            "differences": [], "approval_required": False, "approval": None, "overall": "pass",
        }

    mutations = [
        lambda report: report.update(cases=[], public_results={}, dev_results={}, summary={"total": 0, "equal": 0, "different": 0}),
        lambda report: report["cases"].pop(),
        lambda report: report["cases"].append(dict(report["cases"][0])),
        lambda report: report.update(summary={"total": len(rows), "equal": len(rows) - 1, "different": 1}),
        lambda report: report["dev_results"].update({rows[0]["name"]: "wrong"}),
        lambda report: report["cases"][0].update(candidate="wrong"),
    ]

    for mutate in mutations:
        report = payload()
        mutate(report)

        def runner(command, **kwargs):
            output = Path(command[command.index("--json-out") + 1])
            output.write_text(json.dumps(report), encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

        result = GATE.check_behavior_diff(builds, tmp_path, runner=runner, timeout=3)

        assert result["status"] == "failed"
        assert "evidence failed" in result["detail"]


def test_macro_a_differential_script_exit_contract_checks_all_evidence_groups():
    assert DIFFERENTIAL.validation_errors(_differential_payload()) == []
    mutations = [
        lambda report: report.update(baseline_sha256="0" * 64),
        lambda report: report.update(module_count=8),
        lambda report: report["scenario_counts"].pop("disabled"),
        lambda report: report["decision_counts"].pop("selected"),
        lambda report: report["report_status_counts"].update(error=0),
        lambda report: report["scenario_differences"].update(selected_error=1),
        lambda report: report.update(controlled_switch_active=False),
        lambda report: report["first_failures"].append({"index": 1}),
    ]

    for mutate in mutations:
        report = _differential_payload()
        mutate(report)
        assert DIFFERENTIAL.validation_errors(report)


def test_macro_fixed_development_fingerprints_match_release_manifest():
    release = json.loads(GATE.DEV_MANIFEST.read_text(encoding="utf-8"))
    expected = {
        "development_size": release["expected_size"],
        "development_sha256": release["expected_sha256"],
    }

    assert {
        name: DIFFERENTIAL.EXPECTED_FIXED_FIELDS[name] for name in expected
    } == expected
    assert {
        name: GATE.EXPECTED_MACRO_A_DIFFERENTIAL[name] for name in expected
    } == expected
    assert {
        name: GATE.EXPECTED_MACRO_B_DIFFERENTIAL[name] for name in expected
    } == expected


def test_stage_gate_validates_macro_a_differential_report_and_current_build(tmp_path):
    builds = _differential_builds()

    def runner(command, **kwargs):
        output = Path(command[command.index("--json-out") + 1])
        output.write_text(json.dumps(_differential_payload()), encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    result = GATE.check_macro_a_runtime_differential(builds, tmp_path, runner=runner)

    assert result["status"] == "passed"
    assert result["evidence"]["equal"] == 45000
    assert result["evidence"]["module_count"] == 17

    builds["development"]["vendor"]["sha256"] = "0" * 64
    result = GATE.check_macro_a_runtime_differential(builds, tmp_path, runner=runner)
    assert result["status"] == "failed"
    assert "current build fingerprints" in result["detail"]


def test_stage_gate_rejects_success_exit_with_incomplete_macro_a_coverage(tmp_path):
    builds = _differential_builds()
    mutations = [
        lambda report: report["scenario_counts"].pop("disabled"),
        lambda report: report["decision_counts"].pop("selected"),
        lambda report: report["report_status_counts"].pop("different"),
    ]

    for mutate in mutations:
        def runner(command, **kwargs):
            report = _differential_payload()
            mutate(report)
            output = Path(command[command.index("--json-out") + 1])
            output.write_text(json.dumps(report), encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

        result = GATE.check_macro_a_runtime_differential(builds, tmp_path, runner=runner)
        assert result["status"] == "failed"
        assert "evidence failed" in result["detail"]


def test_macro_b_differential_script_exit_contract_checks_all_evidence_groups():
    assert MACRO_B_DIFFERENTIAL.validation_errors(_macro_b_differential_payload()) == []
    mutations = [
        lambda report: report.update(baseline_sha256="g" * 64),
        lambda report: report.update(module_count=16),
        lambda report: report["scenario_counts"].pop("selected_provider"),
        lambda report: report["decision_counts"].pop("selected"),
        lambda report: report["report_status_counts"].pop("observed"),
        lambda report: report.update(exception_calls=0),
        lambda report: report.update(controlled_switch_active=False),
        lambda report: report["first_failures"].append({"case": 1}),
    ]

    for mutate in mutations:
        report = _macro_b_differential_payload()
        mutate(report)
        assert MACRO_B_DIFFERENTIAL.validation_errors(report)


def test_stage_gate_validates_macro_b_differential_report_and_current_build(tmp_path):
    builds = _macro_b_differential_builds()

    def runner(command, **kwargs):
        output = Path(command[command.index("--json-out") + 1])
        output.write_text(json.dumps(_macro_b_differential_payload()), encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    result = GATE.check_macro_b_runtime_differential(builds, tmp_path, runner=runner)

    assert result["status"] == "passed"
    assert result["evidence"]["equal"] == 50000
    assert result["evidence"]["exception_calls"] == 5000

    builds["development"]["overlay"]["input_sha256"] = "0" * 64
    result = GATE.check_macro_b_runtime_differential(builds, tmp_path, runner=runner)
    assert result["status"] == "failed"
    assert "current build fingerprints" in result["detail"]


def test_stage_gate_rejects_success_exit_with_incomplete_macro_b_coverage(tmp_path):
    builds = _macro_b_differential_builds()
    mutations = [
        lambda report: report["scenario_counts"].pop("selected_provider"),
        lambda report: report["decision_counts"].pop("selected"),
        lambda report: report["report_status_counts"].pop("observed"),
    ]

    for mutate in mutations:
        def runner(command, **kwargs):
            report = _macro_b_differential_payload()
            mutate(report)
            output = Path(command[command.index("--json-out") + 1])
            output.write_text(json.dumps(report), encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

        result = GATE.check_macro_b_runtime_differential(builds, tmp_path, runner=runner)
        assert result["status"] == "failed"
        assert "evidence failed" in result["detail"]


def _chaos_payload():
    scenario_count = len(GATE.EXPECTED_CHAOS_RECOVERY_MS)
    return {
        "schema": "v80-p3-chaos-recovery/1",
        "candidate": {
            "size": 839093,
            "sha256": "B1F980E71AC95CF9C6F143C568CA0B724917E0D8F98B43F09FDBD1B1A6284145",
            "output": "build/v80-dev/豆瓣TMDB追更单入口.py",
        },
        "clock": "virtual",
        "performance_baseline": {
            "source": "virtual_fault_fixture",
            "cold_start_ms": 250,
            "hot_cache_ms": 0,
            "note": "Synthetic transport latency; not a real-device benchmark.",
        },
        "summary": {"total": scenario_count, "passed": scenario_count, "failed": 0},
        "scenarios": [
            {
                "name": name,
                "status": "passed",
                "expected_recovery_ms": value,
                "recovery_ms": value,
                "evidence": {},
            }
            for name, value in GATE.EXPECTED_CHAOS_RECOVERY_MS.items()
        ],
        "oversized_json_scope": "existing_stream_boundary_only_p4_unified_security_pending",
        "production_writes": False,
        "deployment_attempted": False,
    }


def test_stage_gate_validates_chaos_recovery_report_and_current_build(tmp_path):
    builds = {
        "development": {
            "size": 839093,
            "sha256": "B1F980E71AC95CF9C6F143C568CA0B724917E0D8F98B43F09FDBD1B1A6284145",
        },
    }

    def runner(command, **kwargs):
        output = Path(command[command.index("--json-out") + 1])
        output.write_text(json.dumps(_chaos_payload()), encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    result = GATE.check_chaos_recovery(builds, tmp_path, runner=runner)

    assert result["status"] == "passed"
    scenario_count = len(GATE.EXPECTED_CHAOS_RECOVERY_MS)
    assert result["evidence"]["summary"] == {
        "total": scenario_count, "passed": scenario_count, "failed": 0,
    }
    assert result["evidence"]["recovery_ms"] == GATE.EXPECTED_CHAOS_RECOVERY_MS


def test_stage_gate_rejects_tampered_chaos_recovery_report(tmp_path):
    builds = {
        "development": {
            "size": 839093,
            "sha256": "B1F980E71AC95CF9C6F143C568CA0B724917E0D8F98B43F09FDBD1B1A6284145",
        },
    }

    def runner(command, **kwargs):
        payload = _chaos_payload()
        payload["scenarios"][0]["recovery_ms"] = 999
        output = Path(command[command.index("--json-out") + 1])
        output.write_text(json.dumps(payload), encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    result = GATE.check_chaos_recovery(builds, tmp_path, runner=runner)

    assert result["status"] == "failed"
    assert "scenario evidence" in result["detail"]


def test_output_admission_dry_run_admits_complete_in_memory_evidence():
    result = GATE.check_output_admission_dry_run(_output_admission_steps())

    assert result["status"] == "passed"
    assert result["admit"] is True
    assert result["reason"] == "admitted"
    assert all(result["evidence"].values())


def test_output_admission_dry_run_rejects_invalid_private_release():
    def reject_private_release():
        raise RuntimeError("staged artifact differs from fixed build")

    result = GATE.check_output_admission_dry_run(
        _output_admission_steps(), private_release_checker=reject_private_release,
    )

    assert result["status"] == "failed"
    assert result["admit"] is False
    assert result["reason"] == "private_release_invalid"
    assert result["evidence"]["private_release_verified"] is False


@pytest.mark.parametrize(
    "step_name, expected_reason",
    [
        ("build_contracts", "development_build_unverified"),
        ("macro_a_runtime_differential", "candidate_shadow_unverified"),
        ("macro_b_runtime_differential", "layered_shadow_unverified"),
        ("chaos_recovery", "development_build_unverified"),
        ("atvp_compatibility", "atvp_compatibility_unverified"),
        ("dual_runtime", "dual_runtime_unverified"),
        ("fongmi_category_contract", "fongmi_category_unverified"),
        ("upstream_contract", "development_build_unverified"),
        ("git_v70_tag", "public_v70_unlocked"),
    ],
)
def test_output_admission_dry_run_maps_failed_evidence_in_policy_order(
    step_name, expected_reason,
):
    steps = _output_admission_steps()
    next(row for row in steps if row["name"] == step_name)["status"] = "failed"

    result = GATE.check_output_admission_dry_run(steps)

    assert result["status"] == "failed"
    assert result["admit"] is False
    assert result["reason"] == expected_reason


@pytest.mark.parametrize(
    "step_name, expected_reason",
    [
        ("fongmi_category_contract", "fongmi_category_unverified"),
        ("upstream_contract", "development_build_unverified"),
        ("git_v70_tag", "public_v70_unlocked"),
    ],
)
def test_output_admission_dry_run_keeps_partial_evidence_incomplete(
    step_name, expected_reason,
):
    steps = _output_admission_steps()
    next(row for row in steps if row["name"] == step_name)["status"] = "skipped"

    result = GATE.check_output_admission_dry_run(steps)

    assert result["status"] == "skipped"
    assert result["reason"] == expected_reason


def test_output_admission_dry_run_requires_public_output_to_remain_untouched():
    for flags in (
        {"production_writes": True},
        {"deployment_attempted": True},
    ):
        result = GATE.check_output_admission_dry_run(_output_admission_steps(), **flags)

        assert result["status"] == "failed"
        assert result["admit"] is False
        assert result["reason"] == "public_output_touched"


def test_output_admission_dry_run_rejects_missing_or_duplicate_evidence():
    missing = _output_admission_steps()[1:]
    duplicate = _output_admission_steps()
    duplicate.append(GATE._step("build_contracts", "passed"))

    assert GATE.check_output_admission_dry_run(missing)["reason"] == "missing_evidence"
    assert GATE.check_output_admission_dry_run(duplicate)["reason"] == "ambiguous_evidence"


def test_output_admission_dry_run_rejects_a_malformed_policy_decision():
    result = GATE.check_output_admission_dry_run(
        _output_admission_steps(), decider=lambda **_kwargs: {"admit": True},
    )

    assert result["status"] == "failed"
    assert result["reason"] == "evaluation_failed"


def test_v70_source_lock_passes_even_when_v80_admission_is_denied(
    tmp_path, monkeypatch,
):
    context = _source_lock_context(tmp_path)
    monkeypatch.setitem(
        GATE.EXPECTED_MACRO_A_DIFFERENTIAL,
        "baseline_size", context.pop("expected_size"),
    )
    monkeypatch.setitem(
        GATE.EXPECTED_MACRO_A_DIFFERENTIAL,
        "baseline_sha256", context.pop("expected_sha256"),
    )
    context.pop("public_path")

    result = GATE.check_v70_source_lock(**context)

    assert result["status"] == "passed"
    assert result["public_version"] == 70
    assert result["source_lock_verified"] is True


def test_v70_source_lock_rejects_public_source_or_index_drift(
    tmp_path, monkeypatch,
):
    for case in ("source", "index"):
        context = _source_lock_context(tmp_path / case)
        monkeypatch.setitem(
            GATE.EXPECTED_MACRO_A_DIFFERENTIAL,
            "baseline_size", context.pop("expected_size"),
        )
        monkeypatch.setitem(
            GATE.EXPECTED_MACRO_A_DIFFERENTIAL,
            "baseline_sha256", context.pop("expected_sha256"),
        )
        if case == "source":
            context.pop("public_path").write_bytes(b"changed\n")
        else:
            context.pop("public_path")
            index = json.loads(context["index_path"].read_text(encoding="utf-8"))
            index[0]["version"] = 80
            context["index_path"].write_text(json.dumps(index), encoding="utf-8")

        result = GATE.check_v70_source_lock(**context)

        assert result["status"] == "failed"
        assert result["source_lock_verified"] is False


def test_v70_source_lock_rejects_unisolated_output_or_write_markers(
    tmp_path, monkeypatch,
):
    for case in ("output", "write", "deploy", "admission"):
        context = _source_lock_context(tmp_path / case)
        monkeypatch.setitem(
            GATE.EXPECTED_MACRO_A_DIFFERENTIAL,
            "baseline_size", context.pop("expected_size"),
        )
        monkeypatch.setitem(
            GATE.EXPECTED_MACRO_A_DIFFERENTIAL,
            "baseline_sha256", context.pop("expected_sha256"),
        )
        public_path = context.pop("public_path")
        if case == "output":
            context["builds"]["development"]["output"] = public_path.resolve()
        elif case == "write":
            context["production_writes"] = True
        elif case == "deploy":
            context["deployment_attempted"] = True
        else:
            context["steps"][-1]["evidence"]["public_output_untouched"] = False

        result = GATE.check_v70_source_lock(**context)

        assert result["status"] == "failed"
        assert result["source_lock_verified"] is False


@pytest.mark.parametrize(
    "case", ("baseline_manifest", "dev_manifest", "index", "public_source", "development_output"),
)
def test_v70_source_lock_rejects_reparse_evidence_paths(tmp_path, monkeypatch, case):
    context = _source_lock_context(tmp_path)
    monkeypatch.setitem(
        GATE.EXPECTED_MACRO_A_DIFFERENTIAL,
        "baseline_size", context.pop("expected_size"),
    )
    monkeypatch.setitem(
        GATE.EXPECTED_MACRO_A_DIFFERENTIAL,
        "baseline_sha256", context.pop("expected_sha256"),
    )
    public_path = context.pop("public_path")

    if case in ("baseline_manifest", "dev_manifest", "index"):
        key = "index_path" if case == "index" else case
        path = context[key]
        target = path.with_name(path.name + ".target")
        path.replace(target)
        try:
            path.symlink_to(target)
        except OSError as exc:
            pytest.skip("symlink creation is unavailable: %s" % exc)
    elif case == "public_source":
        target = public_path.with_name("public-v70-target.py")
        public_path.replace(target)
        try:
            public_path.symlink_to(target)
        except OSError as exc:
            pytest.skip("symlink creation is unavailable: %s" % exc)
        context["builds"]["baseline"]["output"] = target.resolve()
    else:
        build_root = context["repo_root"] / "build"
        build_root.mkdir()
        target = context["repo_root"] / "physical-v80-output"
        target.mkdir()
        link = build_root / "v80-dev"
        try:
            link.symlink_to(target, target_is_directory=True)
        except OSError as exc:
            pytest.skip("directory symlink creation is unavailable: %s" % exc)
        context["builds"]["development"]["output"] = (target / "development.py").resolve()

    result = GATE.check_v70_source_lock(**context)

    assert result["status"] == "failed"
    assert result["source_lock_verified"] is False
    assert "symlink or reparse" in result["detail"]


@pytest.mark.parametrize(
    "case", ("baseline_manifest", "dev_manifest", "index", "public_source", "development_output"),
)
def test_v70_source_lock_deterministically_rejects_reparse_paths(
    tmp_path, monkeypatch, case,
):
    context = _source_lock_context(tmp_path)
    monkeypatch.setitem(
        GATE.EXPECTED_MACRO_A_DIFFERENTIAL,
        "baseline_size", context.pop("expected_size"),
    )
    monkeypatch.setitem(
        GATE.EXPECTED_MACRO_A_DIFFERENTIAL,
        "baseline_sha256", context.pop("expected_sha256"),
    )
    public_path = context.pop("public_path")
    targets = {
        "baseline_manifest": context["baseline_manifest"],
        "dev_manifest": context["dev_manifest"],
        "index": context["index_path"],
        "public_source": public_path,
        "development_output": context["builds"]["development"]["output"],
    }
    target = Path(targets[case]).resolve(strict=False)

    def reject_selected(path):
        if Path(path).resolve(strict=False) == target:
            raise GATE.GateError("path contains a symlink or reparse component: %s" % target)

    monkeypatch.setattr(GATE, "_verify_no_reparse_components", reject_selected)

    result = GATE.check_v70_source_lock(**context)

    assert result["status"] == "failed"
    assert result["source_lock_verified"] is False
    assert "symlink or reparse" in result["detail"]


def test_link_inspection_permission_error_is_not_treated_as_missing(tmp_path, monkeypatch):
    def denied(_path):
        raise PermissionError("denied")

    monkeypatch.setattr(Path, "lstat", denied)

    try:
        GATE._is_link_or_reparse(tmp_path / "report.json")
    except GATE.GateError as exc:
        assert "cannot inspect" in str(exc)
    else:
        raise AssertionError("permission failure was treated as a missing path")


def test_report_path_cannot_overwrite_managed_inputs_or_symlink_target(tmp_path):
    for protected in (GATE.REPO_ROOT / "spiders_v2.json", GATE.GATE_SCRIPT if hasattr(GATE, "GATE_SCRIPT") else GATE.BUILD_SCRIPT):
        try:
            GATE.atomic_write_report(protected, {"overall": "passed"})
        except GATE.GateError:
            pass
        else:
            raise AssertionError("managed report target was accepted: %s" % protected)

    link = tmp_path / "report-link.json"
    try:
        link.symlink_to(GATE.REPO_ROOT / "spiders_v2.json")
    except OSError:
        return
    try:
        GATE.atomic_write_report(link, {"overall": "passed"})
    except GATE.GateError:
        pass
    else:
        raise AssertionError("symlink to managed input was accepted")


def test_report_path_cannot_overwrite_v80_development_output():
    manifest = json.loads(GATE.DEV_MANIFEST.read_text(encoding="utf-8"))
    development_output = GATE.REPO_ROOT / manifest["output"]

    with pytest.raises(GATE.GateError, match="managed input directory"):
        GATE._assert_report_path_allowed(development_output)


def test_atomic_report_replaces_existing_file_and_failure_aggregation(tmp_path, monkeypatch):
    report_path = tmp_path / "nested" / "report.json"
    report_path.parent.mkdir()
    report_path.write_text('{"old": true}\n', encoding="utf-8")
    GATE.atomic_write_report(report_path, {"schema": GATE.REPORT_SCHEMA, "overall": "failed"})

    assert json.loads(report_path.read_text(encoding="utf-8"))["overall"] == "failed"
    assert not list(report_path.parent.glob("*.tmp"))

    monkeypatch.setattr(GATE, "check_git_tag", lambda *a, **k: GATE._step("git_v70_tag", "passed"))
    monkeypatch.setattr(GATE, "check_structure", lambda: GATE._step("structure_and_dependency", "passed"))
    monkeypatch.setattr(GATE, "check_p2_module_dag", lambda: GATE._step("p2_module_dag", "passed"))
    monkeypatch.setattr(GATE, "check_sensitive", lambda: GATE._step("sensitive_data", "failed"))
    tree_calls = []

    def implementation_tree():
        tree_calls.append(None)
        return GATE._step(
            "implementation_tree", "passed", file_count=1,
            tree_sha256="A", manifest=[{"path": "source.py"}],
        )

    monkeypatch.setattr(GATE, "check_implementation_tree", implementation_tree)
    monkeypatch.setattr(GATE, "check_builds", lambda: (GATE._step("build_contracts", "failed"), None))
    monkeypatch.setattr(GATE, "_git_commit", lambda: "abc")
    args = _args(report=report_path, skip_tests=True)

    report = GATE.run_gate(args)

    assert report["overall"] == "failed"
    assert report["production_writes"] is False
    assert report["deployment_attempted"] is False
    assert json.loads(report_path.read_text(encoding="utf-8"))["overall"] == "failed"
    assert len(tree_calls) == 2
    names = [step["name"] for step in report["steps"]]
    assert len(names) == len(set(names))


def test_run_gate_records_an_admitted_dry_run_without_switching_output(
    tmp_path, monkeypatch,
):
    monkeypatch.setattr(
        GATE, "check_git_tag",
        lambda *a, **k: GATE._step("git_v70_tag", "passed"),
    )
    monkeypatch.setattr(
        GATE, "check_structure",
        lambda: GATE._step("structure_and_dependency", "passed"),
    )
    monkeypatch.setattr(
        GATE, "check_p2_module_dag",
        lambda: GATE._step("p2_module_dag", "passed"),
    )
    monkeypatch.setattr(
        GATE, "check_sensitive",
        lambda: GATE._step("sensitive_data", "passed"),
    )
    tree_calls = []

    def implementation_tree():
        tree_calls.append(None)
        return GATE._step(
            "implementation_tree", "passed", file_count=1,
            tree_sha256="A", manifest=[{"path": "source.py"}],
        )

    monkeypatch.setattr(GATE, "check_implementation_tree", implementation_tree)
    monkeypatch.setattr(
        GATE, "check_builds",
        lambda: (
            GATE._step("build_contracts", "passed"),
            {"development": {"bytes": b"isolated-development"}},
        ),
    )
    monkeypatch.setattr(
        GATE, "check_behavior_diff",
        lambda *a, **k: GATE._step("behavior_diff", "passed"),
    )
    monkeypatch.setattr(
        GATE, "check_macro_a_runtime_differential",
        lambda *a, **k: GATE._step("macro_a_runtime_differential", "passed"),
    )
    monkeypatch.setattr(
        GATE, "check_macro_b_runtime_differential",
        lambda *a, **k: GATE._step("macro_b_runtime_differential", "passed"),
    )
    monkeypatch.setattr(
        GATE, "check_chaos_recovery",
        lambda *a, **k: GATE._step("chaos_recovery", "passed"),
    )
    monkeypatch.setattr(
        GATE, "_run_command",
        lambda name, _command, required=True, **_kwargs: GATE._step(
            name, "passed", required=required,
        ),
    )
    monkeypatch.setattr(
        GATE, "_run_pytest", lambda *_args, **_kwargs: _passed_pytest_step(),
    )
    monkeypatch.setattr(
        GATE, "check_v70_source_lock",
        lambda *a, **k: GATE._step(
            "v70_source_lock", "passed", source_lock_verified=True,
        ),
    )
    monkeypatch.setattr(GATE, "_git_commit", lambda: "abc")
    report_path = tmp_path / "c2-stage-gate.json"
    fongmi_root = tmp_path / "fongmi"
    atvp = tmp_path / "Atvp.py"
    upstream_root = tmp_path / "upstream"
    _write_resume_fongmi_inputs(fongmi_root)
    atvp.write_text("source", encoding="utf-8")
    _write_resume_upstream_git(upstream_root)
    args = _args(
        report=report_path,
        partial=False,
        fongmi_root=fongmi_root,
        atvp=atvp,
        upstream_root=upstream_root,
    )

    report = GATE.run_gate(args)
    admission = next(
        row for row in report["steps"]
        if row["name"] == "output_admission_dry_run"
    )

    assert report["overall"] == "passed"
    assert admission["status"] == "passed"
    assert admission["admit"] is True
    assert admission["reason"] == "admitted"
    source_lock = next(
        row for row in report["steps"]
        if row["name"] == "v70_source_lock"
    )
    assert source_lock["status"] == "passed"
    assert source_lock["source_lock_verified"] is True
    assert report["production_writes"] is False
    assert report["deployment_attempted"] is False
    assert json.loads(report_path.read_text(encoding="utf-8"))["overall"] == "passed"
    assert len(tree_calls) == 2
    tree = next(row for row in report["steps"] if row["name"] == "implementation_tree")
    assert tree["stable_after_commands"] is True


def _write_legacy_resume_report(path):
    payload = {
        "schema": GATE.REPORT_SCHEMA,
        "generated_at": "2026-08-16T00:00:00Z",
        "overall": "passed",
        "steps": [GATE._step(name, "passed") for name in GATE.STEP_ORDER],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return payload


def _install_resume_gate_stubs(monkeypatch, calls, statuses=None):
    statuses = statuses if statuses is not None else {}

    def step(name, status="passed", **extra):
        calls.append(name)
        return GATE._step(name, statuses.get(name, status), **extra)

    monkeypatch.setattr(
        GATE, "check_git_tag", lambda *a, **k: step("git_v70_tag"),
    )
    monkeypatch.setattr(
        GATE, "check_structure", lambda: step("structure_and_dependency"),
    )
    monkeypatch.setattr(
        GATE, "check_p2_module_dag", lambda: step("p2_module_dag"),
    )
    monkeypatch.setattr(
        GATE, "check_sensitive", lambda: step("sensitive_data"),
    )

    def implementation_tree():
        return step(
            "implementation_tree", file_count=1, tree_sha256="A" * 64,
            manifest=[{"path": "source.py", "size": 1, "sha256": "B" * 64}],
        )

    monkeypatch.setattr(GATE, "check_implementation_tree", implementation_tree)

    baseline = b"baseline"
    development = b"development"

    build_payload = {
        "baseline": {
            "bytes": baseline, "size": len(baseline),
            "sha256": hashlib.sha256(baseline).hexdigest().upper(),
        },
        "development": {
            "bytes": development, "size": len(development),
            "sha256": hashlib.sha256(development).hexdigest().upper(),
        },
    }

    def builds():
        row = step(
            "build_contracts",
            baseline_size=len(baseline),
            baseline_sha256=hashlib.sha256(baseline).hexdigest().upper(),
            development_size=len(development),
            development_sha256=hashlib.sha256(development).hexdigest().upper(),
        )
        return row, build_payload

    monkeypatch.setattr(GATE, "check_builds", builds)
    monkeypatch.setattr(GATE, "_materialize_builds", lambda: build_payload)
    monkeypatch.setattr(
        GATE, "check_behavior_diff",
        lambda *a, **k: step("behavior_diff", evidence={"marker": "behavior"}),
    )
    monkeypatch.setattr(
        GATE, "check_macro_a_runtime_differential",
        lambda *a, **k: step("macro_a_runtime_differential"),
    )
    monkeypatch.setattr(
        GATE, "check_macro_b_runtime_differential",
        lambda *a, **k: step("macro_b_runtime_differential"),
    )
    monkeypatch.setattr(
        GATE, "check_chaos_recovery", lambda *a, **k: step("chaos_recovery"),
    )
    monkeypatch.setattr(
        GATE, "_run_command",
        lambda name, _command, required=True, **_kwargs: step(
            name, required=required,
        ),
    )
    monkeypatch.setattr(
        GATE, "_run_pytest",
        lambda *_args, **_kwargs: step(
            "pytest",
            pytest_junit={
                "path": "fake-pytest-junit.xml", "collected": 1,
                "executed": 1, "skipped": 0, "failures": 0, "errors": 0,
            },
        ),
    )
    monkeypatch.setattr(
        GATE, "check_v70_source_lock",
        lambda *a, **k: step(
            "v70_source_lock", source_lock_verified=True,
        ),
    )
    monkeypatch.setattr(GATE, "_git_commit", lambda: "abc")


def _write_resume_fongmi_inputs(root):
    root.mkdir(exist_ok=True)
    for relative in GATE._FONGMI_REQUIREMENTS + GATE._FONGMI_CATEGORY_SOURCES:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("source", encoding="utf-8")


def test_dual_runtime_fingerprints_existing_requirement_candidates(tmp_path):
    root = tmp_path / "fongmi"
    primary = root / GATE._FONGMI_REQUIREMENTS[0]
    secondary = root / GATE._FONGMI_REQUIREMENTS[1]
    primary.parent.mkdir(parents=True)
    primary.write_text("requests", encoding="utf-8")

    scopes = GATE._step_input_scopes(
        "dual_runtime", _args(fongmi_root=root), GATE._InputFingerprinter(),
    )
    requirements = next(
        scope for scope in scopes if scope.get("name") == "fongmi_requirements"
    )
    assert requirements["valid"] is True
    assert requirements["file_count"] == 1
    primary_sha256 = requirements["sha256"]

    secondary.parent.mkdir(parents=True)
    secondary.write_text("beautifulsoup4", encoding="utf-8")
    primary.unlink()
    scopes = GATE._step_input_scopes(
        "dual_runtime", _args(fongmi_root=root), GATE._InputFingerprinter(),
    )
    requirements = next(
        scope for scope in scopes if scope.get("name") == "fongmi_requirements"
    )
    assert requirements["valid"] is True
    assert requirements["file_count"] == 1
    assert requirements["sha256"] != primary_sha256

    primary.mkdir()
    scopes = GATE._step_input_scopes(
        "dual_runtime", _args(fongmi_root=root), GATE._InputFingerprinter(),
    )
    requirements = next(
        scope for scope in scopes if scope.get("name") == "fongmi_requirements"
    )
    assert requirements["valid"] is False
    assert requirements["file_count"] == 2
    assert any(error.get("path", "").endswith("chaquo/requirements.txt")
               for error in requirements["errors"])

    primary.rmdir()
    secondary.unlink()
    scopes = GATE._step_input_scopes(
        "dual_runtime", _args(fongmi_root=root), GATE._InputFingerprinter(),
    )
    requirements = next(
        scope for scope in scopes if scope.get("name") == "fongmi_requirements"
    )
    assert requirements["valid"] is False
    assert requirements["file_count"] == 0


def _write_resume_upstream_git(root):
    root.mkdir(exist_ok=True)
    setup_commands = (
        ("init", "-q"),
        ("config", "user.email", "resume@example.invalid"),
        ("config", "user.name", "Resume Test"),
    )
    for command in setup_commands:
        subprocess.run(
            ["git"] + list(command), cwd=str(root), check=True,
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
    for tag, content in (
        ("1.45.0", "1450"),
        ("1.45.1", "1451"),
        ("1.46.1", "1461"),
        ("1.47.1", "1471"),
        ("1.48.0", "1480"),
        ("1.50.0", "1500"),
    ):
        (root / "source.go").write_text(content, encoding="utf-8")
        for command in (
            ("add", "source.go"),
            ("commit", "-q", "-m", "resume input %s" % tag),
            ("tag", tag),
        ):
            subprocess.run(
                ["git"] + list(command), cwd=str(root), check=True,
                capture_output=True, text=True, encoding="utf-8", errors="replace",
            )


def test_upstream_git_state_fingerprint_changes_when_worktree_becomes_dirty(tmp_path):
    upstream = tmp_path / "upstream"
    _write_resume_upstream_git(upstream)
    clean = GATE._git_repository_state_input(
        GATE._InputFingerprinter(), "upstream_git_state", upstream,
    )

    (upstream / "source.go").write_text("dirty", encoding="utf-8")
    dirty = GATE._git_repository_state_input(
        GATE._InputFingerprinter(), "upstream_git_state", upstream,
    )

    assert clean["value"]["worktree_status"] == ""
    assert dirty["value"]["worktree_status"]
    assert clean["sha256"] != dirty["sha256"]


def test_upstream_git_state_fingerprint_covers_the_complete_verifier_chain(tmp_path):
    upstream = tmp_path / "upstream"
    _write_resume_upstream_git(upstream)
    original = GATE._git_repository_state_input(
        GATE._InputFingerprinter(), "upstream_git_state", upstream,
    )

    assert set(original["value"]) == {
        "root", "head", "exact_tag", "worktree_status",
        "tag_1450_commit", "tag_1451_commit", "tag_1461_commit",
        "tag_1471_commit", "tag_1480_commit", "tag_1500_commit",
        "delta_1450_1451", "delta_1451_1461", "delta_1461_1471",
        "delta_1471_1480", "delta_1480_1500",
    }
    assert original["valid"]

    subprocess.run(
        ["git", "tag", "-f", "1.45.1", "1.46.1^{commit}"],
        cwd=str(upstream), check=True, capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    drifted = GATE._git_repository_state_input(
        GATE._InputFingerprinter(), "upstream_git_state", upstream,
    )

    assert original["value"]["tag_1451_commit"] != drifted["value"]["tag_1451_commit"]
    assert original["value"]["delta_1451_1461"] != drifted["value"]["delta_1451_1461"]
    assert original["sha256"] != drifted["sha256"]


def test_executed_step_rejects_invalid_input_evidence():
    input_record = {
        "input_schema": GATE.STEP_INPUT_SCHEMA,
        "input_manifest": [{
            "name": "upstream_git_state", "kind": "value",
            "sha256": "A" * 64, "valid": False,
        }],
        "input_dependencies": [],
        "input_sha256": "B" * 64,
        "input_valid": False,
    }

    row = GATE._annotate_step(
        GATE._step("upstream_contract", "passed"),
        "upstream_contract", input_record, "executed",
    )

    assert row["status"] == "failed"
    assert row["required"] is True
    assert "upstream_git_state" in row["detail"]


def test_executed_step_rejects_failed_dependency_evidence():
    input_record = {
        "input_schema": GATE.STEP_INPUT_SCHEMA,
        "input_manifest": [{
            "name": "gate_tool", "kind": "file_set",
            "sha256": "A" * 64, "valid": True,
        }],
        "input_dependencies": [{
            "name": "upstream_contract", "status": "failed",
            "input_sha256": "B" * 64, "result_sha256": "C" * 64,
        }],
        "input_sha256": "D" * 64,
        "input_valid": False,
    }

    row = GATE._annotate_step(
        GATE._step("output_admission_dry_run", "passed"),
        "output_admission_dry_run", input_record, "executed",
    )

    assert row["status"] == "failed"
    assert "upstream_contract" in row["detail"]


@pytest.mark.parametrize("invalid_kind", ("scope", "dependency"))
def test_intentional_skipped_step_preserves_partial_semantics(invalid_kind):
    input_record = {
        "input_schema": GATE.STEP_INPUT_SCHEMA,
        "input_manifest": [{
            "name": "upstream_git_state", "kind": "value",
            "sha256": "A" * 64, "valid": invalid_kind != "scope",
        }],
        "input_dependencies": [],
        "input_sha256": "B" * 64,
        "input_valid": False,
    }
    if invalid_kind == "dependency":
        input_record["input_dependencies"] = [{
            "name": "upstream_contract", "status": "failed",
            "input_sha256": "C" * 64, "result_sha256": "D" * 64,
        }]

    row = GATE._annotate_step(
        GATE._step(
            "output_admission_dry_run", "skipped",
            detail="partial evidence is intentionally incomplete",
        ),
        "output_admission_dry_run", input_record, "executed",
    )

    assert row["status"] == "skipped"
    assert row["detail"] == "partial evidence is intentionally incomplete"


def test_resume_step_catalog_is_exact_and_acyclic():
    assert tuple(GATE.STEP_DEPENDENCIES) == GATE.STEP_ORDER
    assert len(GATE.STEP_ORDER) == 18
    assert len(set(GATE.STEP_ORDER)) == 18
    assert GATE.ALWAYS_EXECUTE_STEPS == frozenset()
    assert tuple(GATE.STEP_GATE_CONTRACTS) == GATE.STEP_ORDER
    assert all(GATE.STEP_GATE_CONTRACTS.values())

    visiting = set()
    visited = set()

    def visit(name):
        if name in visiting:
            raise AssertionError("cycle at %s" % name)
        if name in visited:
            return
        visiting.add(name)
        for dependency in GATE.STEP_DEPENDENCIES[name]:
            assert dependency in GATE.STEP_DEPENDENCIES
            visit(dependency)
        visiting.remove(name)
        visited.add(name)

    for step_name in GATE.STEP_ORDER:
        visit(step_name)


def test_output_admission_input_scope_binds_private_release_artifacts():
    scopes = GATE._step_input_scopes(
        "output_admission_dry_run", _args(), GATE._InputFingerprinter(),
    )
    private_scope = next(
        scope for scope in scopes if scope["name"] == "private_release_inputs"
    )

    assert private_scope["valid"] is True
    assert set(private_scope["paths"]) == {
        path.resolve().relative_to(GATE.REPO_ROOT.resolve()).as_posix()
        for path in (
            GATE.PRIVATE_RELEASE_SCRIPT,
            GATE.PRIVATE_RELEASE_MANIFEST,
            GATE.PRIVATE_RELEASE_INDEX,
            GATE.PRIVATE_RELEASE_SOURCE,
            GATE.CONTROLLED_SWITCH_EVIDENCE,
        )
    }


def test_current_upstream_contract_is_1500_leaf_with_explicit_base_chain():
    assert GATE.UPSTREAM_CONTRACT_SCRIPT.name == "verify_alist_tvbox_1500_contract.py"

    args = _args(upstream_root=Path("upstream"))
    scopes = GATE._step_input_scopes(
        "upstream_contract", args, GATE._InputFingerprinter(),
    )
    manifest_paths = {
        path
        for scope in scopes if scope.get("name") == "upstream_verifier"
        for path in scope.get("paths", ())
    }
    assert manifest_paths == {
        "tools/verify_alist_tvbox_1451_contract.py",
        "tools/verify_alist_tvbox_1461_contract.py",
        "tools/verify_alist_tvbox_1471_contract.py",
        "tools/verify_alist_tvbox_1480_contract.py",
        "tools/verify_alist_tvbox_1500_contract.py",
    }


def test_parser_accepts_resume_from():
    args = GATE._parser().parse_args([
        "--partial", "--resume-from", "source.json",
        "--resume-source-sha256", "A" * 64,
        "--pytest-node", "tests/test_sample.py::test_failure",
    ])

    assert args.resume_from == Path("source.json")
    assert args.resume_source_sha256 == "A" * 64
    assert args.pytest_node == ["tests/test_sample.py::test_failure"]


def test_pytest_node_requires_resume_source():
    args = _args(pytest_node=["tests/test_sample.py::test_failure"])

    with pytest.raises(GATE.GateError, match="requires --resume-from"):
        GATE._validate_args(args)


@pytest.mark.parametrize("value", (
    "../tests/test_sample.py::test_failure",
    "work/test_sample.py::test_failure",
    "tests/not-python.txt::test_failure",
))
def test_pytest_node_rejects_non_test_targets(value):
    args = _args(
        resume_from=Path("source.json"),
        resume_source_sha256="A" * 64,
        pytest_node=[value],
    )

    with pytest.raises(GATE.GateError, match="relative tests"):
        GATE._validate_args(args)


def test_resume_from_requires_a_pinned_source_sha256():
    args = _args(resume_from=Path("source.json"))

    with pytest.raises(GATE.GateError, match="requires --resume-source-sha256"):
        GATE._validate_args(args)


def test_resume_source_sha256_requires_a_resume_source_path():
    args = _args(resume_source_sha256="A" * 64)

    with pytest.raises(GATE.GateError, match="requires --resume-from"):
        GATE._validate_args(args)


@pytest.mark.parametrize("value", ("A" * 63, "G" * 64))
def test_resume_source_sha256_requires_64_hex_characters(value):
    args = _args(
        resume_from=Path("source.json"),
        resume_source_sha256=value,
    )

    with pytest.raises(GATE.GateError, match="64-character SHA256"):
        GATE._validate_args(args)


def test_unverified_resume_source_cannot_reuse_passed_evidence():
    source = {
        "sha256_verified": False,
        "steps": {
            "structure_and_dependency": {
                "name": "structure_and_dependency",
                "status": "passed",
                "input_sha256": "A" * 64,
            },
        },
    }
    row, reason = GATE._resume_decision(
        "structure_and_dependency",
        {"input_valid": True, "input_sha256": "A" * 64},
        source,
    )

    assert row is None
    assert reason == "source report SHA256 was not verified"


def test_resume_source_cannot_equal_report_target(tmp_path):
    report_path = tmp_path / "report.json"
    _write_legacy_resume_report(report_path)

    with pytest.raises(GATE.GateError, match="same file"):
        GATE._load_resume_source(report_path, report_path.parent / "." / report_path.name)


def test_resume_source_sha256_can_be_pinned(tmp_path):
    source_path = tmp_path / "source.json"
    _write_legacy_resume_report(source_path)
    actual = hashlib.sha256(source_path.read_bytes()).hexdigest().upper()

    loaded = GATE._load_resume_source(
        source_path, tmp_path / "closure.json", expected_sha256=actual,
    )
    assert loaded["sha256_verified"] is True

    with pytest.raises(GATE.GateError, match="does not match"):
        GATE._load_resume_source(
            source_path, tmp_path / "closure.json", expected_sha256="0" * 64,
        )


def test_input_fingerprint_is_deterministic_and_content_bound(tmp_path):
    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    first.write_text("a", encoding="utf-8")
    second.write_text("b", encoding="utf-8")

    left = GATE._InputFingerprinter(tmp_path).files("scope", (first, second))
    right = GATE._InputFingerprinter(tmp_path).files("scope", (second, first))
    second.write_text("changed", encoding="utf-8")
    changed = GATE._InputFingerprinter(tmp_path).files("scope", (first, second))

    assert left["sha256"] == right["sha256"]
    assert left["sha256"] != changed["sha256"]
    assert re.fullmatch(r"[0-9A-F]{64}", left["sha256"])


def test_command_timeout_is_execution_budget_not_resume_input():
    def scope_map(name, args):
        return {
            scope["name"]: scope
            for scope in GATE._step_input_scopes(
                name, args, GATE._InputFingerprinter(),
            )
        }

    short = _args(command_timeout=900)
    long = _args(command_timeout=2700)

    assert scope_map("behavior_diff", short) == scope_map("behavior_diff", long)
    assert scope_map("pytest", short) == scope_map("pytest", long)
    assert "command_options" not in scope_map("behavior_diff", short)
    assert scope_map("pytest", short)["command_options"]["value"] == {
        "skip_tests": False,
        "selected_nodeids": [],
    }
    assert (
        scope_map("pytest", short)["command_options"]["sha256"]
        != scope_map("pytest", _args(skip_tests=True))["command_options"]["sha256"]
    )


def test_pytest_runtime_fingerprint_tracks_auto_loaded_plugins(monkeypatch):
    class Distribution(object):
        def __init__(self, version):
            self.metadata = {"Name": "example-plugin"}
            self.version = version

    class EntryPoint(object):
        name = "example"
        value = "example.plugin"

        def __init__(self, version):
            self.dist = Distribution(version)

    class EntryPoints(list):
        def select(self, **kwargs):
            return self if kwargs == {"group": "pytest11"} else []

    monkeypatch.setattr(
        GATE.importlib_metadata, "entry_points", lambda: EntryPoints([EntryPoint("1.0")]),
    )
    pytest_before = GATE._runtime_input(
        GATE._InputFingerprinter(), include_pytest_plugins=True,
    )
    non_pytest_before = GATE._runtime_input(
        GATE._InputFingerprinter(), include_pytest_plugins=False,
    )
    monkeypatch.setattr(
        GATE.importlib_metadata, "entry_points", lambda: EntryPoints([EntryPoint("2.0")]),
    )
    pytest_after = GATE._runtime_input(
        GATE._InputFingerprinter(), include_pytest_plugins=True,
    )
    non_pytest_after = GATE._runtime_input(
        GATE._InputFingerprinter(), include_pytest_plugins=False,
    )

    assert pytest_before["sha256"] != pytest_after["sha256"]
    assert pytest_before["value"]["pytest11_plugins"] == [{
        "name": "example", "value": "example.plugin",
        "distribution": "example-plugin", "version": "1.0",
    }]
    assert non_pytest_before["sha256"] == non_pytest_after["sha256"]


def test_extra_structure_and_p2_members_invalidate_input_scopes(tmp_path, monkeypatch):
    source = tmp_path / "source"
    parts = source / "parts"
    parts.mkdir(parents=True)
    monkeypatch.setattr(GATE, "SOURCE_DIR", source)

    structure_before = GATE._InputFingerprinter().files(
        "structure", GATE._structure_input_paths(),
    )
    extra_part = parts / "99_extra.pyinc"
    extra_part.write_text("extra", encoding="utf-8")
    structure_after = GATE._InputFingerprinter().files(
        "structure", GATE._structure_input_paths(),
    )

    p2_before = GATE._InputFingerprinter().files("p2", GATE._p2_input_paths())
    extra_module = source / "resource_unmanaged.py"
    extra_module.write_text("extra", encoding="utf-8")
    p2_after = GATE._InputFingerprinter().files("p2", GATE._p2_input_paths())

    assert extra_part in GATE._structure_input_paths()
    assert structure_before["sha256"] != structure_after["sha256"]
    assert extra_module in GATE._p2_input_paths()
    assert p2_before["sha256"] != p2_after["sha256"]


def test_pytest_input_scope_includes_public_index(tmp_path, monkeypatch):
    monkeypatch.setattr(GATE, "REPO_ROOT", tmp_path)
    index = tmp_path / "spiders_v2.json"
    index.write_text("[]", encoding="utf-8")

    before = GATE._step_input_scopes(
        "pytest", _args(), GATE._InputFingerprinter(tmp_path),
    )
    index.write_text('[{"id":"changed"}]', encoding="utf-8")
    after = GATE._step_input_scopes(
        "pytest", _args(), GATE._InputFingerprinter(tmp_path),
    )
    before_public = next(row for row in before if row["name"] == "pytest_public_inputs")
    after_public = next(row for row in after if row["name"] == "pytest_public_inputs")

    assert "spiders_v2.json" in before_public["paths"]
    assert before_public["sha256"] != after_public["sha256"]


def test_pytest_input_scope_hashes_the_local_test_dependency_tree(
        tmp_path, monkeypatch):
    dependencies = tmp_path / "work" / "python-test-deps"
    package = dependencies / "example" / "__init__.py"
    metadata = dependencies / "example-1.0.dist-info" / "METADATA"
    for path, content in ((package, "VALUE = 1\n"), (metadata, "Version: 1.0\n")):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    monkeypatch.setattr(GATE, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(GATE, "LOCAL_TEST_DEPS", dependencies)

    before = GATE._step_input_scopes(
        "pytest", _args(), GATE._InputFingerprinter(tmp_path),
    )
    package.write_text("VALUE = 2\n", encoding="utf-8")
    after = GATE._step_input_scopes(
        "pytest", _args(), GATE._InputFingerprinter(tmp_path),
    )
    before_dependencies = next(
        row for row in before if row["name"] == "pytest_local_test_deps"
    )
    after_dependencies = next(
        row for row in after if row["name"] == "pytest_local_test_deps"
    )

    assert before_dependencies["kind"] == "tree"
    assert before_dependencies["file_count"] == 2
    assert before_dependencies["valid"] is True
    assert before_dependencies["sha256"] != after_dependencies["sha256"]


def test_pytest_code_scope_excludes_nontest_documentation(tmp_path):
    docs = tmp_path / "docs" / "V80_REFACTOR_PLAN.md"
    fixture_readme = tmp_path / "tests" / "fixtures" / "fixture_README.md"
    code = tmp_path / "src" / "douban_tmdb_follow_single" / "security_policy.py"
    for path in (docs, fixture_readme, code):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("content", encoding="utf-8")

    paths = set(GATE._pytest_input_paths(tmp_path))

    assert docs not in paths
    assert fixture_readme in paths
    assert code in paths


def test_external_input_change_is_rejected_before_report_closure(tmp_path):
    fongmi = tmp_path / "fongmi"
    _write_resume_fongmi_inputs(fongmi)
    atvp = tmp_path / "Atvp.py"
    atvp.write_text("first", encoding="utf-8")
    args = _args(fongmi_root=fongmi, atvp=atvp)
    input_record = GATE._step_input_record(
        "fongmi_category_contract", args, [], GATE._InputFingerprinter(),
    )
    row = GATE._annotate_step(
        GATE._step("fongmi_category_contract", "passed"),
        "fongmi_category_contract", input_record, "executed",
    )
    atvp.write_text("second", encoding="utf-8")

    GATE._verify_step_inputs_stable([row], args)

    assert row["status"] == "failed"
    assert row["input_stable_after_gate"] is False
    assert row["started_input_sha256"] != row["final_input_sha256"]
    assert row["input_sha256"] == row["final_input_sha256"]


def test_legacy_resume_steps_are_not_reused(tmp_path):
    source_path = tmp_path / "legacy.json"
    _write_legacy_resume_report(source_path)
    source = GATE._load_resume_source(source_path, tmp_path / "closure.json")
    record = {"input_valid": True, "input_sha256": "A" * 64}

    row, reason = GATE._resume_decision(
        "structure_and_dependency", record, source,
    )

    assert row is None
    assert "predates" in reason


def test_tampered_resume_step_input_is_rejected(tmp_path):
    source_path = tmp_path / "tampered.json"
    payload = _write_legacy_resume_report(source_path)
    row = payload["steps"][0]
    row.update({
        "execution": "executed",
        "input_schema": GATE.STEP_INPUT_SCHEMA,
        "input_manifest": [],
        "input_dependencies": [],
        "input_sha256": "0" * 64,
    })
    source_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(GATE.GateError, match="input evidence is invalid"):
        GATE._load_resume_source(source_path, tmp_path / "closure.json")


@pytest.mark.parametrize("field,value", [
    ("status", "unknown"),
    ("required", None),
])
def test_malformed_resume_step_semantics_are_rejected(tmp_path, field, value):
    source_path = tmp_path / "malformed-step.json"
    payload = _write_legacy_resume_report(source_path)
    row = payload["steps"][0]
    row.update({
        "execution": "executed",
        "input_schema": GATE.STEP_INPUT_SCHEMA,
        "input_manifest": [],
        "input_dependencies": [],
    })
    row[field] = value
    row["input_sha256"] = GATE._source_step_input_sha256(row)
    source_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(GATE.GateError, match="input evidence is invalid"):
        GATE._load_resume_source(source_path, tmp_path / "closure.json")


def test_malformed_resume_dependency_rows_are_rejected(tmp_path):
    source_path = tmp_path / "malformed-dependencies.json"
    payload = _write_legacy_resume_report(source_path)
    row = payload["steps"][0]
    row.update({
        "execution": "executed",
        "input_schema": GATE.STEP_INPUT_SCHEMA,
        "input_manifest": [],
        "input_dependencies": [None],
    })
    row["input_sha256"] = GATE._source_step_input_sha256(row)
    source_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(GATE.GateError, match="dependencies are invalid"):
        GATE._load_resume_source(source_path, tmp_path / "closure.json")


def test_dependency_and_external_input_changes_are_scoped(tmp_path):
    fongmi = tmp_path / "fongmi"
    upstream = tmp_path / "upstream"
    _write_resume_fongmi_inputs(fongmi)
    _write_resume_upstream_git(upstream)
    atvp = tmp_path / "Atvp.py"
    atvp.write_text("first", encoding="utf-8")
    args = _args(fongmi_root=fongmi, atvp=atvp, upstream_root=upstream)

    category_before = GATE._step_input_record(
        "fongmi_category_contract", args, [], GATE._InputFingerprinter(),
    )
    upstream_before = GATE._step_input_record(
        "upstream_contract", args, [], GATE._InputFingerprinter(),
    )
    atvp.write_text("second", encoding="utf-8")
    category_after = GATE._step_input_record(
        "fongmi_category_contract", args, [], GATE._InputFingerprinter(),
    )
    upstream_after = GATE._step_input_record(
        "upstream_contract", args, [], GATE._InputFingerprinter(),
    )

    assert category_before["input_sha256"] != category_after["input_sha256"]
    assert upstream_before["input_sha256"] == upstream_after["input_sha256"]

    build_a = GATE._annotate_step(
        GATE._step("build_contracts", "passed", development_sha256="A" * 64),
        "build_contracts",
        {
            "input_schema": GATE.STEP_INPUT_SCHEMA,
            "input_manifest": [], "input_dependencies": [],
            "input_sha256": "1" * 64,
        },
        "executed",
    )
    build_b = copy.deepcopy(build_a)
    build_b["input_sha256"] = "2" * 64
    behavior_a = GATE._step_input_record(
        "behavior_diff", args, [build_a], GATE._InputFingerprinter(),
    )
    behavior_b = GATE._step_input_record(
        "behavior_diff", args, [build_b], GATE._InputFingerprinter(),
    )

    assert behavior_a["input_sha256"] != behavior_b["input_sha256"]


def test_matching_resume_reuses_only_non_anchor_steps_and_keeps_source_read_only(
    tmp_path, monkeypatch,
):
    fongmi = tmp_path / "fongmi"
    upstream = tmp_path / "upstream"
    _write_resume_fongmi_inputs(fongmi)
    _write_resume_upstream_git(upstream)
    atvp = tmp_path / "Atvp.py"
    atvp.write_text("source", encoding="utf-8")

    calls = []
    _install_resume_gate_stubs(monkeypatch, calls)
    source_path = tmp_path / "source.json"
    common = {
        "partial": False,
        "fongmi_root": fongmi,
        "atvp": atvp,
        "upstream_root": upstream,
    }
    source_report = GATE.run_gate(_args(report=source_path, **common))
    source_bytes = source_path.read_bytes()
    source_sha256 = hashlib.sha256(source_bytes).hexdigest().upper()
    calls[:] = []

    closure_path = tmp_path / "closure.json"
    closure = GATE.run_gate(_args(
        report=closure_path, resume_from=source_path,
        resume_source_sha256=source_sha256, **common
    ))

    assert source_report["overall"] == "passed"
    assert closure["overall"] == "passed"
    assert source_path.read_bytes() == source_bytes
    assert closure["resume"]["source_report_sha256"] == source_sha256
    assert closure["resume"]["source_sha256_verified"] is True
    assert closure["resume"]["executed_steps"] == []
    assert set(closure["resume"]["reused_steps"]) == set(GATE.STEP_ORDER)
    assert closure["resume"]["materialized_steps"] == ["build_contracts"]
    assert not closure["resume"]["legacy_steps"]
    assert set(calls) == {"implementation_tree"}
    source_by_name = {row["name"]: row for row in source_report["steps"]}
    closure_by_name = {row["name"]: row for row in closure["steps"]}
    assert closure_by_name["behavior_diff"]["evidence"] == (
        source_by_name["behavior_diff"]["evidence"]
    )
    assert closure_by_name["behavior_diff"]["reuse_reason"] == (
        "passed evidence and dependency fingerprints are unchanged"
    )
    for row in closure["steps"]:
        assert row["execution"] in ("executed", "reused")
        assert re.fullmatch(r"[0-9A-F]{64}", row["input_sha256"])
        if row["execution"] == "reused":
            assert row["status"] == "passed"
            assert row["reused_from"]["report_sha256"] == source_sha256
            assert re.fullmatch(r"[0-9A-F]{64}", row["reused_from"]["step_sha256"])


def test_partial_resume_with_trusted_pin_reuses_matching_internal_steps(
    tmp_path, monkeypatch,
):
    calls = []
    _install_resume_gate_stubs(monkeypatch, calls)
    source_path = tmp_path / "partial-source.json"
    source = GATE.run_gate(_args(report=source_path, partial=True))
    source_sha256 = hashlib.sha256(source_path.read_bytes()).hexdigest().upper()
    calls[:] = []

    closure = GATE.run_gate(_args(
        report=tmp_path / "partial-closure.json",
        partial=True,
        resume_from=source_path,
        resume_source_sha256=source_sha256,
    ))
    by_name = {row["name"]: row for row in closure["steps"]}

    assert source["overall"] == "incomplete"
    assert closure["overall"] == "incomplete"
    assert closure["resume"]["source_sha256_verified"] is True
    assert by_name["behavior_diff"]["execution"] == "reused"
    assert by_name["behavior_diff"]["status"] == "passed"


def test_failed_step_resumes_without_reexecuting_independent_passes(
    tmp_path, monkeypatch,
):
    fongmi = tmp_path / "fongmi"
    upstream = tmp_path / "upstream"
    _write_resume_fongmi_inputs(fongmi)
    _write_resume_upstream_git(upstream)
    atvp = tmp_path / "Atvp.py"
    atvp.write_text("source", encoding="utf-8")

    calls = []
    statuses = {"macro_a_runtime_differential": "failed"}
    _install_resume_gate_stubs(monkeypatch, calls, statuses=statuses)
    common = {
        "partial": False,
        "fongmi_root": fongmi,
        "atvp": atvp,
        "upstream_root": upstream,
    }
    source_path = tmp_path / "failed-source.json"
    source = GATE.run_gate(_args(report=source_path, **common))
    assert source["overall"] == "failed"

    statuses["macro_a_runtime_differential"] = "passed"
    calls[:] = []
    source_sha256 = hashlib.sha256(source_path.read_bytes()).hexdigest().upper()
    closure = GATE.run_gate(_args(
        report=tmp_path / "closure.json",
        resume_from=source_path,
        resume_source_sha256=source_sha256,
        **common
    ))
    by_name = {row["name"]: row for row in closure["steps"]}

    assert closure["overall"] == "passed"
    assert by_name["macro_a_runtime_differential"]["execution"] == "executed"
    assert by_name["macro_a_runtime_differential"]["status"] == "passed"
    assert by_name["macro_b_runtime_differential"]["execution"] == "reused"
    assert by_name["chaos_recovery"]["execution"] == "reused"
    assert set(calls) == {
        "implementation_tree", "macro_a_runtime_differential",
        "v70_source_lock",
    }
    invalidation = by_name["macro_a_runtime_differential"]["resume_invalidation"]
    assert invalidation["source_status"] == "failed"
    assert invalidation["source_input_sha256"]
    assert invalidation["current_input_sha256"]
    assert invalidation["propagation_paths"] == [["macro_a_runtime_differential"]]
    admission = by_name["output_admission_dry_run"]["resume_invalidation"]
    assert ["macro_a_runtime_differential", "output_admission_dry_run"] in (
        admission["propagation_paths"]
    )


def test_implementation_tree_failure_report_remains_a_valid_resume_source(
    tmp_path, monkeypatch,
):
    fongmi = tmp_path / "fongmi"
    upstream = tmp_path / "upstream"
    _write_resume_fongmi_inputs(fongmi)
    _write_resume_upstream_git(upstream)
    atvp = tmp_path / "Atvp.py"
    atvp.write_text("source", encoding="utf-8")

    calls = []
    _install_resume_gate_stubs(monkeypatch, calls)
    tree_hashes = iter(("A" * 64, "B" * 64))

    def changing_tree():
        calls.append("implementation_tree")
        value = next(tree_hashes)
        return GATE._step(
            "implementation_tree", "passed", file_count=1,
            tree_sha256=value,
            manifest=[{"path": "source.py", "size": 1, "sha256": value}],
        )

    monkeypatch.setattr(GATE, "check_implementation_tree", changing_tree)
    source_path = tmp_path / "tree-failure.json"
    report = GATE.run_gate(_args(
        report=source_path,
        partial=False,
        fongmi_root=fongmi,
        atvp=atvp,
        upstream_root=upstream,
    ))

    assert report["overall"] == "failed"
    tree = next(row for row in report["steps"] if row["name"] == "implementation_tree")
    pytest_row = next(row for row in report["steps"] if row["name"] == "pytest")
    assert tree["status"] == "failed"
    assert [item["name"] for item in pytest_row["input_dependencies"]] == [
        "build_contracts"
    ]
    loaded = GATE._load_resume_source(source_path, tmp_path / "closure.json")
    assert loaded["report"]["overall"] == "failed"

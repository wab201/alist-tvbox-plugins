#!/usr/bin/env python3
"""Run the local, non-deploying V80 stage gate and write a JSON report."""

import argparse
import ast
import copy
import datetime as dt
import hashlib
import importlib.metadata as importlib_metadata
import importlib.util
import json
import math
import os
import re
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit
from xml.etree import ElementTree


REPO_ROOT = Path(__file__).resolve().parents[1]
GATE_SCRIPT = Path(__file__).resolve()
LOCAL_TEST_DEPS = REPO_ROOT / "work" / "python-test-deps"


def _activate_local_test_deps():
    if not LOCAL_TEST_DEPS.is_dir():
        return False
    value = str(LOCAL_TEST_DEPS.resolve())
    if value not in sys.path:
        sys.path.insert(0, value)
    current = [item for item in os.environ.get("PYTHONPATH", "").split(os.pathsep) if item]
    if value not in current:
        os.environ["PYTHONPATH"] = os.pathsep.join([value] + current)
    return True


LOCAL_TEST_DEPS_ACTIVE = _activate_local_test_deps()
BUILD_SCRIPT = REPO_ROOT / "tools" / "build_follow_plugin.py"
RESOURCE_SHADOW_VENDOR_SCRIPT = REPO_ROOT / "tools" / "build_v80_resource_shadow_vendor.py"
RELIABILITY_OVERLAY_SCRIPT = REPO_ROOT / "tools" / "build_v80_reliability_overlay.py"
CACHE_HEALTH_OVERLAY_SCRIPT = REPO_ROOT / "tools" / "build_v80_cache_health_overlay.py"
BACKGROUND_BULKHEAD_OVERLAY_SCRIPT = (
    REPO_ROOT / "tools" / "build_v80_background_bulkhead_overlay.py"
)
TIMEOUT_BUDGET_OVERLAY_SCRIPT = (
    REPO_ROOT / "tools" / "build_v80_timeout_budget_overlay.py"
)
ROUTE_SECURITY_OVERLAY_SCRIPT = (
    REPO_ROOT / "tools" / "build_v80_route_security_overlay.py"
)
TMDB_JSON_SHAPE_OVERLAY_SCRIPT = (
    REPO_ROOT / "tools" / "build_v80_tmdb_json_shape_overlay.py"
)
TMDB_RESPONSE_BOUNDARY_OVERLAY_SCRIPT = (
    REPO_ROOT / "tools" / "build_v80_tmdb_response_boundary_overlay.py"
)
DIAGNOSTIC_REDACTION_OVERLAY_SCRIPT = (
    REPO_ROOT / "tools" / "build_v80_diagnostic_redaction_overlay.py"
)
DOUBAN_RESPONSE_BOUNDARY_OVERLAY_SCRIPT = (
    REPO_ROOT / "tools" / "build_v80_douban_response_boundary_overlay.py"
)
DOUBAN_HTML_RESPONSE_BOUNDARY_OVERLAY_SCRIPT = (
    REPO_ROOT / "tools" / "build_v80_douban_html_response_boundary_overlay.py"
)
OBSERVABILITY_RUNTIME_OVERLAY_SCRIPT = (
    REPO_ROOT / "tools" / "build_v80_observability_runtime_overlay.py"
)
DIAGNOSTICS_SNAPSHOT_OVERLAY_SCRIPT = (
    REPO_ROOT / "tools" / "build_v80_diagnostics_snapshot_overlay.py"
)
LIFECYCLE_STABILITY_OVERLAY_SCRIPT = (
    REPO_ROOT / "tools" / "build_v80_lifecycle_stability_overlay.py"
)
SEARCH_CONCURRENCY_OWNERSHIP_OVERLAY_SCRIPT = (
    REPO_ROOT / "tools" / "build_v80_search_concurrency_ownership_overlay.py"
)
PLAYBACK_CONCURRENCY_OWNERSHIP_OVERLAY_SCRIPT = (
    REPO_ROOT / "tools" / "build_v80_playback_concurrency_ownership_overlay.py"
)
HISTORY_CONCURRENCY_OWNERSHIP_OVERLAY_SCRIPT = (
    REPO_ROOT / "tools" / "build_v80_history_concurrency_ownership_overlay.py"
)
RESOURCE_OUTPUT_SWITCH_OVERLAY_SCRIPT = (
    REPO_ROOT / "tools" / "build_v80_resource_output_switch_overlay.py"
)
PRIVATE_RELEASE_SCRIPT = REPO_ROOT / "tools" / "build_v80_private_release.py"
PRIVATE_RELEASE_ROOT = REPO_ROOT / "private" / "v80"
PRIVATE_RELEASE_MANIFEST = PRIVATE_RELEASE_ROOT / "private-release.json"
PRIVATE_RELEASE_INDEX = PRIVATE_RELEASE_ROOT / "spiders_v2.json"
PRIVATE_RELEASE_SOURCE = PRIVATE_RELEASE_ROOT / "staging" / "豆瓣TMDB追更单入口.py"
CONTROLLED_SWITCH_EVIDENCE = (
    REPO_ROOT / "work" / "v80-p2-controlled-output-switch-evidence-20260818.json"
)
UPSTREAM_CONTRACT_SCRIPT = REPO_ROOT / "tools" / "verify_alist_tvbox_1511_contract.py"
UPSTREAM_CONTRACT_EVIDENCE = (
    REPO_ROOT / "work" / "v80-upstream-1511-github-evidence-20260818.json"
)
MACRO_A_DIFFERENTIAL_SCRIPT = REPO_ROOT / "work" / "run_v80_p2_macro_a_differential.py"
MACRO_B_DIFFERENTIAL_SCRIPT = REPO_ROOT / "work" / "run_v80_p2_macro_b_differential.py"
CHAOS_RECOVERY_SCRIPT = REPO_ROOT / "tools" / "run_v80_p3_chaos_recovery.py"
BEHAVIOR_SCRIPT = REPO_ROOT / "tests" / "test_follow_behavior_golden.py"
BEHAVIOR_FIXTURE = REPO_ROOT / "tests" / "fixtures" / "v70_behavior_golden.json"
SOURCE_DIR = REPO_ROOT / "src" / "douban_tmdb_follow_single"
BASELINE_MANIFEST = SOURCE_DIR / "baseline_v70.json"
DEV_MANIFEST = SOURCE_DIR / "release.json"
DEPENDENCY_CONTRACT = SOURCE_DIR / "dependency_contract.json"
OUTPUT_ADMISSION_POLICY = SOURCE_DIR / "resource_output_admission.py"
SECURITY_POLICY_MODULE = SOURCE_DIR / "security_policy.py"
JSON_SHAPE_POLICY_MODULE = SOURCE_DIR / "json_shape_policy.py"
TMDB_RESPONSE_POLICY_MODULE = SOURCE_DIR / "tmdb_response_policy.py"
DIAGNOSTIC_REDACTION_POLICY_MODULE = SOURCE_DIR / "diagnostic_redaction_policy.py"
DOUBAN_RESPONSE_POLICY_MODULE = SOURCE_DIR / "douban_response_policy.py"
DOUBAN_HTML_RESPONSE_POLICY_MODULE = (
    SOURCE_DIR / "douban_html_response_policy.py"
)
OBSERVABILITY_POLICY_MODULE = SOURCE_DIR / "observability_policy.py"
_DIAGNOSTIC_REDACTION_POLICY = None
EXPECTED_V70_TAG = "612617b35f08b98234c6e20c8137d8dea9035e97"
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
EXPECTED_CHUNK_SHA256 = {
    "parts/00_module_prelude.pyinc": "4F744ABEC953EFAF094ADA4F0D4FD12ADB56BC315B8C68BC3CB2E7658BF21E14",
    "parts/01_runtime_components.pyinc": "23B5EBC9192B05AA00D717EA007BE168C95C7EE1D09F848EF7C44360CBD952FE",
    "parts/02_filter.pyinc": "1A58E5A0C4A44139D529A85C24BA57C20F747CA1EEB82FBE31AEE5CFF1DAC9C1",
    "parts/03_spider_runtime.pyinc": "9FF7F46FA801A606796CE1A332128C03182DA05EFCA80952DC04A44FE5661934",
    "parts/04_follow_workflows.pyinc": "FAF3CAFA738E07B383D19EF9D37E4C403EFE75C718423164768CE08720F2942D",
    "parts/05_history_sync.pyinc": "36815D9C160BFD5C10D255B3B4F23635319456C59F0A655B922288B6E6D8DC8A",
    "parts/06_resource_discovery.pyinc": "84CCD7F323D38EC02FD0EBB94A8BE360130DAAA3834AD3B90F817C6E1A94ACC5",
    "parts/07_resource_ranking.pyinc": "81575EEA708E471ED2BFCF5B600236BF17DE1A868DF07A4B11CD9B5E03EAF5D5",
    "parts/08_playback_transport.pyinc": "4C686571AD4C354720C15704DAD1D61DCA82CF4F2488B2B539036CACA34A6B4E",
    "parts/09_metadata_and_utilities.pyinc": "7AD85F6C97EA496D998498E48B5F4A5215EDD7AE97D4CC4BAE727AF9B1055E20",
}
EXPECTED_MACRO_A_DIFFERENTIAL = {
    "schema": "v80-p2-macro-a-runtime-differential/1",
    "seed": 8020,
    "cases": 50000,
    "errors": 0,
    "baseline_size": 616699,
    "baseline_sha256": "233C73CAE1048210B34872D4A10EA6023662300F70A8657DB82EA65C342182D4",
    "development_size": 870797,
    "development_sha256": "0CEBC73A78BCC8C7853A6BD0F0C78F4D95DD786C861425F9E0A4EC40FA0583F9",
    "vendor_size": 64973,
    "vendor_sha256": "5405EE86F10155B717852E3578750BFA9DE89073AB9BAD8FF3E92C58ACC77601",
    "closure_sha256": "484FCBC3EB079CE3739AD08928D21F82E24101210AED012FC5FA6487553A7968",
    "module_count": 17,
    "overlay_input_size": 681672,
    "overlay_input_sha256": "761EB09F5184A9B9914295A43B0A2F5AF1C46A414F8B0D0456477CA9A3639C01",
    "overlay_insertion_count": 8,
    "output_switch_input_size": 865875,
    "output_switch_input_sha256": "DCD2CE50277119998BE2D92631CC90C11B3DDC733CB7B397E072E62FE117E773",
    "output_switch_size": 870797,
    "output_switch_sha256": "0CEBC73A78BCC8C7853A6BD0F0C78F4D95DD786C861425F9E0A4EC40FA0583F9",
    "output_switch_insertion_count": 9,
    "controlled_switch_active": True,
    "shadow_calls": 30000,
    "disabled_shadow_calls": 0,
    "redacted_reports": True,
    "production_writes": False,
    "deployment_attempted": False,
}
EXPECTED_MACRO_A_SCENARIO_COUNTS = {
    "already_sampled": 5000,
    "disabled": 5000,
    "duplicate_job": 5000,
    "insufficient_budget": 5000,
    "not_selected": 5000,
    "selected_different": 5000,
    "selected_equal": 5000,
    "selected_error": 5000,
    "stale_worker": 5000,
    "submit_failure": 5000,
}
EXPECTED_MACRO_A_DECISION_COUNTS = {
    "already_sampled": 5000,
    "insufficient_budget": 5000,
    "not_selected": 5000,
    "selected": 15000,
}
EXPECTED_MACRO_A_REPORT_STATUS_COUNTS = {
    "different": 5000,
    "equal": 10000,
}
EXPECTED_MACRO_A_ZERO_DIFFERENCE_SCENARIOS = frozenset((
    "duplicate_job", "selected_equal", "selected_error",
    "stale_worker", "submit_failure",
))
EXPECTED_MACRO_B_DIFFERENTIAL = {
    "schema": "v80-p2-macro-b-runtime-differential/1",
    "seed": 8021,
    "cases": 50000,
    "equal": 50000,
    "different": 0,
    "errors": 0,
    "baseline_size": 616699,
    "baseline_sha256": "233C73CAE1048210B34872D4A10EA6023662300F70A8657DB82EA65C342182D4",
    "development_size": 870797,
    "development_sha256": "0CEBC73A78BCC8C7853A6BD0F0C78F4D95DD786C861425F9E0A4EC40FA0583F9",
    "vendor_size": 64973,
    "vendor_sha256": "5405EE86F10155B717852E3578750BFA9DE89073AB9BAD8FF3E92C58ACC77601",
    "closure_sha256": "484FCBC3EB079CE3739AD08928D21F82E24101210AED012FC5FA6487553A7968",
    "module_count": 17,
    "overlay_input_size": 681672,
    "overlay_input_sha256": "761EB09F5184A9B9914295A43B0A2F5AF1C46A414F8B0D0456477CA9A3639C01",
    "overlay_insertion_count": 8,
    "output_switch_input_size": 865875,
    "output_switch_input_sha256": "DCD2CE50277119998BE2D92631CC90C11B3DDC733CB7B397E072E62FE117E773",
    "output_switch_size": 870797,
    "output_switch_sha256": "0CEBC73A78BCC8C7853A6BD0F0C78F4D95DD786C861425F9E0A4EC40FA0583F9",
    "output_switch_insertion_count": 9,
    "controlled_switch_active": True,
    "shadow_calls": 40000,
    "disabled_shadow_calls": 0,
    "exception_calls": 5000,
    "redacted_reports": True,
    "production_writes": False,
    "deployment_attempted": False,
}
EXPECTED_MACRO_B_SCENARIO_COUNTS = {
    "already_sampled": 5000,
    "disabled": 5000,
    "empty_title": 5000,
    "insufficient_budget": 5000,
    "selected_binding": 5000,
    "selected_binding_only": 5000,
    "selected_cache": 5000,
    "selected_provider": 5000,
    "selected_recent": 5000,
    "shadow_exception": 5000,
}
EXPECTED_MACRO_B_DECISION_COUNTS = {
    "already_sampled": 5000,
    "insufficient_budget": 5000,
    "selected": 25000,
}
EXPECTED_MACRO_B_REPORT_STATUS_COUNTS = {"observed": 25000}
EXPECTED_CHAOS_RECOVERY_MS = {
    "tmdb_500_stale": 1000,
    "tmdb_timeout_stale": 1000,
    "pansou_timeout": 30000,
    "history_401_reauth": 0,
    "history_500_isolation": 1000,
    "alist_502": 30000,
    "dns_failure": 30000,
    "ipv6_unreachable": 30000,
    "expired_play_url": 0,
    "truncated_json": 0,
    "oversized_json_boundary": 0,
    "stale_lifecycle_task": 0,
    "resource_combiner_fail_open": 0,
}
P2_MODULE_DAG = {
    "resource_candidate_merge.py": frozenset(("resource_row_identity",)),
    "resource_candidate_ordering.py": frozenset(),
    "resource_candidate_pipeline.py": frozenset((
        "resource_candidate_merge", "resource_candidate_ordering",
    )),
    "resource_candidate_shadow_background.py": frozenset(),
    "resource_candidate_shadow_composition.py": frozenset((
        "resource_candidate_ordering", "resource_candidate_shadow",
        "resource_candidate_shadow_policy",
    )),
    "resource_candidate_shadow.py": frozenset((
        "resource_candidate_ordering", "resource_candidate_pipeline",
    )),
    "resource_candidate_shadow_policy.py": frozenset(),
    "resource_candidate_shadow_runtime.py": frozenset((
        "resource_candidate_shadow_background",
        "resource_candidate_shadow_composition",
    )),
    "resource_candidate_preference.py": frozenset(),
    "resource_matching.py": frozenset(("resource_normalization",)),
    "resource_models.py": frozenset(),
    "resource_normalization.py": frozenset(),
    "resource_output_admission.py": frozenset(),
    "resource_provider.py": frozenset((
        "resource_models", "resource_schema", "resource_shadow",
    )),
    "resource_row_identity.py": frozenset(),
    "resource_row_scoring.py": frozenset((
        "resource_matching", "resource_normalization", "resource_scoring",
    )),
    "resource_row_merge.py": frozenset(),
    "resource_scoring.py": frozenset(("resource_matching", "resource_normalization")),
    "resource_search_plan.py": frozenset(("resource_provider", "resource_schema")),
    "resource_search_shadow.py": frozenset((
        "resource_models", "resource_provider", "resource_search_plan",
    )),
    "resource_search_v70_adapter.py": frozenset((
        "resource_candidate_ordering", "resource_candidate_pipeline",
        "resource_provider", "resource_row_identity", "resource_search_plan",
        "resource_search_shadow",
    )),
    "resource_search_shadow_runtime.py": frozenset((
        "resource_candidate_shadow_background", "resource_candidate_shadow_policy",
        "resource_search_v70_adapter",
    )),
    "resource_schema.py": frozenset(),
    "resource_shadow.py": frozenset(("resource_models", "resource_schema")),
}
P1_MANAGED_FILES = (
    ".gitattributes",
    ".gitignore",
    "README.md",
    "docs/V80_REFACTOR_PLAN.md",
    "plugins/douban_tmdb_follow_single/DEPLOYMENT.md",
    "plugins/douban_tmdb_follow_single/STATUS.md",
    "src/douban_tmdb_follow_single/README.md",
    "src/douban_tmdb_follow_single/baseline_v70.json",
    "src/douban_tmdb_follow_single/dependency_contract.json",
    "src/douban_tmdb_follow_single/release.json",
    "tools/build_follow_plugin.py",
    "tools/run_v80_stage_gate.py",
    "tests/test_follow_build_pipeline.py",
    "tests/test_follow_behavior_golden.py",
    "tests/test_v80_stage_gate.py",
    "tests/fixtures/v70_behavior_golden.json",
    "tests/fixtures/v70_behavior_golden_README.md",
)
P2_MANAGED_FILES = (
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
)
P3_MANAGED_FILES = (
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
    "tools/verify_alist_tvbox_1511_contract.py",
    "work/v80-upstream-1511-github-evidence-20260818.json",
    "tests/test_v80_p3_history_event_queue.py",
    "tests/test_v80_p3_history_sync_v145.py",
    "tests/test_v80_p3_history_sync_overlay.py",
    "tests/test_alist_tvbox_1451_contract.py",
    "tests/test_alist_tvbox_1461_contract.py",
    "tests/test_alist_tvbox_1471_contract.py",
    "tests/test_alist_tvbox_1480_contract.py",
    "tests/test_alist_tvbox_1500_contract.py",
    "tests/test_alist_tvbox_1511_contract.py",
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
)
P4_MANAGED_FILES = (
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
)
P5_MANAGED_FILES = (
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
)
COMPAT_TOOLS = Path.home() / ".codex" / "skills" / "alist-tvbox-compatibility-check" / "tools"
MAX_OUTPUT = 12000
DEFAULT_COMMAND_TIMEOUT = 900
GIT_COMMAND_TIMEOUT = 10
REPORT_SCHEMA = "v80-stage-gate/1"
STEP_INPUT_SCHEMA = "v80-stage-step-input/1"
PYTEST_SELECTION_SCHEMA = "v80-pytest-selection/1"
PYTEST_EVIDENCE_PLUGIN_NAME = "v80_pytest_gate_evidence"
PYTEST_EVIDENCE_ENV = "V80_PYTEST_GATE_EVIDENCE"
PYTEST_PRIVATE_CONFIG_TEXT = "[pytest]\naddopts =\n"
PYTEST_EVIDENCE_PLUGIN_TEXT = '''import json
import os

import pytest


_STATE = {"collected": None, "failed_nodeids": set()}


@pytest.hookimpl(hookwrapper=True, tryfirst=True)
def pytest_collection_modifyitems(session, config, items):
    _STATE["collected"] = len(items)
    yield


def pytest_runtest_logreport(report):
    if report.failed:
        _STATE["failed_nodeids"].add(report.nodeid)


@pytest.hookimpl(hookwrapper=True, tryfirst=True)
def pytest_sessionfinish(session, exitstatus):
    yield
    selected = len(getattr(session, "items", ()))
    collected = _STATE["collected"]
    if collected is None:
        collected = selected
    payload = {
        "schema": "v80-pytest-selection/1",
        "collected": collected,
        "selected": selected,
        "deselected": collected - selected,
        "exitstatus": int(exitstatus),
        "failed_nodeids": sorted(_STATE["failed_nodeids"]),
    }
    with open(os.environ["V80_PYTEST_GATE_EVIDENCE"], "w", encoding="utf-8") as handle:
        json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
'''
MAX_RESUME_REPORT_BYTES = 8 * 1024 * 1024
STEP_ORDER = (
    "git_v70_tag",
    "structure_and_dependency",
    "p2_module_dag",
    "sensitive_data",
    "implementation_tree",
    "build_contracts",
    "behavior_diff",
    "macro_a_runtime_differential",
    "macro_b_runtime_differential",
    "chaos_recovery",
    "pytest",
    "resource_shadow_vendor",
    "atvp_compatibility",
    "dual_runtime",
    "fongmi_category_contract",
    "upstream_contract",
    "output_admission_dry_run",
    "v70_source_lock",
)
STEP_DEPENDENCIES = {
    "git_v70_tag": (),
    "structure_and_dependency": (),
    "p2_module_dag": (),
    "sensitive_data": (),
    "implementation_tree": (),
    "build_contracts": (
        "structure_and_dependency", "p2_module_dag",
    ),
    "behavior_diff": ("build_contracts",),
    "macro_a_runtime_differential": ("build_contracts",),
    "macro_b_runtime_differential": ("build_contracts",),
    "chaos_recovery": ("build_contracts",),
    "pytest": ("build_contracts",),
    "resource_shadow_vendor": ("build_contracts",),
    "atvp_compatibility": ("build_contracts",),
    "dual_runtime": ("build_contracts",),
    "fongmi_category_contract": (),
    "upstream_contract": (),
    "output_admission_dry_run": STEP_ORDER[:16],
    "v70_source_lock": (
        "git_v70_tag", "structure_and_dependency", "build_contracts",
        "output_admission_dry_run",
    ),
}
# Explicit per-step gate contracts keep an unrelated gate-tool edit from invalidating
# every step. Bump only the contract whose validation semantics changed.
STEP_GATE_CONTRACTS = {
    name: "1" for name in STEP_ORDER
}
STEP_GATE_CONTRACTS.update({
    "sensitive_data": "2",
    "chaos_recovery": "2",
    "upstream_contract": "2",
    "output_admission_dry_run": "2",
})
# Kept as a compatibility surface for existing report/test consumers; no step is
# unconditionally executed during a resume.
ALWAYS_EXECUTE_STEPS = frozenset()
_FINGERPRINT_EXCLUDED_DIRS = frozenset((
    ".git", ".gradle", ".idea", ".mypy_cache", ".pytest_cache",
    ".ruff_cache", ".venv", ".vscode", "__pycache__", "build",
    "node_modules", "out", "target", "venv",
))
_FONGMI_REQUIREMENTS = (
    Path("chaquo/requirements.txt"),
    Path("chaquo/src/main/python/requirements.txt"),
)
_FONGMI_CATEGORY_SOURCES = (
    Path("app/src/leanback/java/com/fongmi/android/tv/ui/fragment/TypeFragment.java"),
    Path("app/src/main/java/com/fongmi/android/tv/api/SiteApi.java"),
    Path("chaquo/src/main/java/com/fongmi/chaquo/Spider.java"),
    Path("catvod/src/main/java/com/github/catvod/crawler/Spider.java"),
)
_SECRET_NAMES = (
    "authorization", "proxy-authorization", "cookie", "set-cookie",
    "password", "passwd", "token", "secret",
    "api_key", "api-key", "access_token", "refresh_token", "client_secret",
)
_SECRET_NAME_PATTERN = "|".join(re.escape(item) for item in _SECRET_NAMES)
_SENSITIVE_FIELD_KEYS = {
    re.sub(r"[-.\s]+", "_", item.lower()) for item in _SECRET_NAMES
}
_SENSITIVE_QUERY_KEYS = {
    "authorization", "auth", "cookie", "password", "passwd", "token", "secret",
    "key", "api_key", "api-key", "access_token", "refresh_token", "client_secret",
    "sign", "sig", "signature", "auth_key", "auth-key", "expires", "policy",
    "key_pair_id", "key-pair-id", "awsaccesskeyid", "googleaccessid", "wssecret",
    "hdnts", "hdnea",
}


class GateError(RuntimeError):
    """Raised when a local gate assertion fails."""


def _load_build_module():
    spec = importlib.util.spec_from_file_location("v80_follow_build", BUILD_SCRIPT)
    if spec is None or spec.loader is None:
        raise GateError("cannot load build script: %s" % BUILD_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_reliability_overlay_builder():
    spec = importlib.util.spec_from_file_location(
        "v80_reliability_overlay_builder", RELIABILITY_OVERLAY_SCRIPT,
    )
    if spec is None or spec.loader is None:
        raise GateError("cannot load reliability overlay builder: %s" % RELIABILITY_OVERLAY_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_cache_health_overlay_builder():
    spec = importlib.util.spec_from_file_location(
        "v80_cache_health_overlay_builder", CACHE_HEALTH_OVERLAY_SCRIPT,
    )
    if spec is None or spec.loader is None:
        raise GateError(
            "cannot load cache-health overlay builder: %s"
            % CACHE_HEALTH_OVERLAY_SCRIPT
        )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_background_bulkhead_overlay_builder():
    spec = importlib.util.spec_from_file_location(
        "v80_background_bulkhead_overlay_builder",
        BACKGROUND_BULKHEAD_OVERLAY_SCRIPT,
    )
    if spec is None or spec.loader is None:
        raise GateError(
            "cannot load background bulkhead overlay builder: %s"
            % BACKGROUND_BULKHEAD_OVERLAY_SCRIPT
        )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_timeout_budget_overlay_builder():
    spec = importlib.util.spec_from_file_location(
        "v80_timeout_budget_overlay_builder",
        TIMEOUT_BUDGET_OVERLAY_SCRIPT,
    )
    if spec is None or spec.loader is None:
        raise GateError(
            "cannot load timeout budget overlay builder: %s"
            % TIMEOUT_BUDGET_OVERLAY_SCRIPT
        )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_route_security_overlay_builder():
    spec = importlib.util.spec_from_file_location(
        "v80_route_security_overlay_builder",
        ROUTE_SECURITY_OVERLAY_SCRIPT,
    )
    if spec is None or spec.loader is None:
        raise GateError(
            "cannot load route security overlay builder: %s"
            % ROUTE_SECURITY_OVERLAY_SCRIPT
        )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_tmdb_json_shape_overlay_builder():
    spec = importlib.util.spec_from_file_location(
        "v80_tmdb_json_shape_overlay_builder",
        TMDB_JSON_SHAPE_OVERLAY_SCRIPT,
    )
    if spec is None or spec.loader is None:
        raise GateError(
            "cannot load TMDB JSON shape overlay builder: %s"
            % TMDB_JSON_SHAPE_OVERLAY_SCRIPT
        )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_tmdb_response_boundary_overlay_builder():
    spec = importlib.util.spec_from_file_location(
        "v80_tmdb_response_boundary_overlay_builder",
        TMDB_RESPONSE_BOUNDARY_OVERLAY_SCRIPT,
    )
    if spec is None or spec.loader is None:
        raise GateError(
            "cannot load TMDB response boundary overlay builder: %s"
            % TMDB_RESPONSE_BOUNDARY_OVERLAY_SCRIPT
        )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_diagnostic_redaction_overlay_builder():
    spec = importlib.util.spec_from_file_location(
        "v80_diagnostic_redaction_overlay_builder",
        DIAGNOSTIC_REDACTION_OVERLAY_SCRIPT,
    )
    if spec is None or spec.loader is None:
        raise GateError(
            "cannot load diagnostic redaction overlay builder: %s"
            % DIAGNOSTIC_REDACTION_OVERLAY_SCRIPT
        )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_douban_response_boundary_overlay_builder():
    spec = importlib.util.spec_from_file_location(
        "v80_douban_response_boundary_overlay_builder",
        DOUBAN_RESPONSE_BOUNDARY_OVERLAY_SCRIPT,
    )
    if spec is None or spec.loader is None:
        raise GateError(
            "cannot load Douban response boundary overlay builder: %s"
            % DOUBAN_RESPONSE_BOUNDARY_OVERLAY_SCRIPT
        )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_douban_html_response_boundary_overlay_builder():
    spec = importlib.util.spec_from_file_location(
        "v80_douban_html_response_boundary_overlay_builder",
        DOUBAN_HTML_RESPONSE_BOUNDARY_OVERLAY_SCRIPT,
    )
    if spec is None or spec.loader is None:
        raise GateError(
            "cannot load Douban HTML response boundary overlay builder: %s"
            % DOUBAN_HTML_RESPONSE_BOUNDARY_OVERLAY_SCRIPT
        )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_observability_runtime_overlay_builder():
    spec = importlib.util.spec_from_file_location(
        "v80_observability_runtime_overlay_builder",
        OBSERVABILITY_RUNTIME_OVERLAY_SCRIPT,
    )
    if spec is None or spec.loader is None:
        raise GateError(
            "cannot load observability runtime overlay builder: %s"
            % OBSERVABILITY_RUNTIME_OVERLAY_SCRIPT
        )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_diagnostics_snapshot_overlay_builder():
    spec = importlib.util.spec_from_file_location(
        "v80_diagnostics_snapshot_overlay_builder",
        DIAGNOSTICS_SNAPSHOT_OVERLAY_SCRIPT,
    )
    if spec is None or spec.loader is None:
        raise GateError(
            "cannot load diagnostics snapshot overlay builder: %s"
            % DIAGNOSTICS_SNAPSHOT_OVERLAY_SCRIPT
        )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_lifecycle_stability_overlay_builder():
    spec = importlib.util.spec_from_file_location(
        "v80_lifecycle_stability_overlay_builder",
        LIFECYCLE_STABILITY_OVERLAY_SCRIPT,
    )
    if spec is None or spec.loader is None:
        raise GateError(
            "cannot load lifecycle stability overlay builder: %s"
            % LIFECYCLE_STABILITY_OVERLAY_SCRIPT
        )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_search_concurrency_ownership_overlay_builder():
    spec = importlib.util.spec_from_file_location(
        "v80_search_concurrency_ownership_overlay_builder",
        SEARCH_CONCURRENCY_OWNERSHIP_OVERLAY_SCRIPT,
    )
    if spec is None or spec.loader is None:
        raise GateError(
            "cannot load search concurrency ownership overlay builder: %s"
            % SEARCH_CONCURRENCY_OWNERSHIP_OVERLAY_SCRIPT
        )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_playback_concurrency_ownership_overlay_builder():
    spec = importlib.util.spec_from_file_location(
        "v80_playback_concurrency_ownership_overlay_builder",
        PLAYBACK_CONCURRENCY_OWNERSHIP_OVERLAY_SCRIPT,
    )
    if spec is None or spec.loader is None:
        raise GateError(
            "cannot load playback concurrency ownership overlay builder: %s"
            % PLAYBACK_CONCURRENCY_OWNERSHIP_OVERLAY_SCRIPT
        )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_history_concurrency_ownership_overlay_builder():
    spec = importlib.util.spec_from_file_location(
        "v80_history_concurrency_ownership_overlay_builder",
        HISTORY_CONCURRENCY_OWNERSHIP_OVERLAY_SCRIPT,
    )
    if spec is None or spec.loader is None:
        raise GateError(
            "cannot load History concurrency ownership overlay builder: %s"
            % HISTORY_CONCURRENCY_OWNERSHIP_OVERLAY_SCRIPT
        )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_resource_output_switch_overlay_builder():
    spec = importlib.util.spec_from_file_location(
        "v80_resource_output_switch_overlay_builder",
        RESOURCE_OUTPUT_SWITCH_OVERLAY_SCRIPT,
    )
    if spec is None or spec.loader is None:
        raise GateError(
            "cannot load resource output switch overlay builder: %s"
            % RESOURCE_OUTPUT_SWITCH_OVERLAY_SCRIPT
        )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_private_release_builder():
    spec = importlib.util.spec_from_file_location(
        "v80_private_release_builder", PRIVATE_RELEASE_SCRIPT,
    )
    if spec is None or spec.loader is None:
        raise GateError("cannot load private release builder: %s" % PRIVATE_RELEASE_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_diagnostic_redaction_policy():
    global _DIAGNOSTIC_REDACTION_POLICY
    if _DIAGNOSTIC_REDACTION_POLICY is not None:
        return _DIAGNOSTIC_REDACTION_POLICY
    spec = importlib.util.spec_from_file_location(
        "v80_diagnostic_redaction_policy",
        DIAGNOSTIC_REDACTION_POLICY_MODULE,
    )
    if spec is None or spec.loader is None:
        raise GateError(
            "cannot load diagnostic redaction policy: %s"
            % DIAGNOSTIC_REDACTION_POLICY_MODULE
        )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _DIAGNOSTIC_REDACTION_POLICY = module
    return module


def _load_output_admission_policy():
    spec = importlib.util.spec_from_file_location(
        "v80_resource_output_admission", OUTPUT_ADMISSION_POLICY,
    )
    if spec is None or spec.loader is None:
        raise GateError("cannot load output admission policy: %s" % OUTPUT_ADMISSION_POLICY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.decide_resource_output_admission


def _redact(text):
    raw = str(text or "")
    policy = _load_diagnostic_redaction_policy()
    redacted = policy._v80_redact_bounded(raw, (), MAX_OUTPUT, "<redacted>")
    if len(raw) > MAX_OUTPUT:
        redacted = redacted[:MAX_OUTPUT] + "\n...<truncated>"
    return redacted


def _sensitive_field_key(value):
    normalized = re.sub(r"[-.\s]+", "_", str(value).strip().lower())
    return normalized in _SENSITIVE_FIELD_KEYS


def _sanitize(value):
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            safe_key = _redact(key)
            result[safe_key] = "<redacted>" if _sensitive_field_key(key) else _sanitize(item)
        return result
    if isinstance(value, (list, tuple)):
        if (
                len(value) == 2
                and isinstance(value[0], (str, Path))
                and _sensitive_field_key(value[0])):
            return [_redact(value[0]), "<redacted>"]
        return [_sanitize(item) for item in value]
    if isinstance(value, (str, Path)):
        return _redact(value)
    return value


def _step(name, status, required=True, detail="", **extra):
    row = {"name": name, "status": status, "required": bool(required), "detail": _redact(detail)}
    row.update(_sanitize(extra))
    return row


def _valid_timeout(timeout):
    return isinstance(timeout, (int, float)) and not isinstance(timeout, bool) and math.isfinite(timeout) and timeout > 0


def _run_command(
        name, command, required=True, cwd=REPO_ROOT, runner=None,
        timeout=DEFAULT_COMMAND_TIMEOUT, env=None):
    if not _valid_timeout(timeout):
        return _step(name, "failed", required=required, detail="command timeout must be finite and greater than zero")
    started = time.monotonic()
    runner = runner or subprocess.run
    try:
        options = {
            "cwd": str(cwd), "capture_output": True, "text": True,
            "encoding": "utf-8", "errors": "replace", "check": False,
            "timeout": timeout,
        }
        if env is not None:
            options["env"] = env
        result = runner([str(item) for item in command], **options)
        return _step(
            name, "passed" if result.returncode == 0 else "failed", required=required,
            detail="command completed", command=list(command), exit_code=result.returncode,
            duration_seconds=round(time.monotonic() - started, 3),
            stdout=result.stdout, stderr=result.stderr,
        )
    except subprocess.TimeoutExpired as exc:
        return _step(
            name, "failed", required=required, detail="command timed out after %s seconds" % timeout,
            command=list(command), exit_code=None, duration_seconds=round(time.monotonic() - started, 3),
            stdout=exc.stdout, stderr=exc.stderr,
        )
    except OSError as exc:
        return _step(
            name, "failed", required=required, detail="cannot start command: %s" % exc,
            command=list(command), exit_code=None, duration_seconds=round(time.monotonic() - started, 3),
            stdout="", stderr="",
        )


def check_git_tag(repo_root=REPO_ROOT, runner=None):
    repo_root = Path(repo_root)
    if not (repo_root / ".git").exists():
        return _step("git_v70_tag", "skipped", required=False, detail="Git metadata is not present")
    row = _run_command(
        "git_v70_tag", ["git", "rev-parse", "refs/tags/v70^{commit}"], cwd=repo_root,
        runner=runner, timeout=GIT_COMMAND_TIMEOUT,
    )
    if row["status"] == "passed":
        actual = row["stdout"].strip().splitlines()[-1] if row["stdout"].strip() else ""
        row.update(expected_commit=EXPECTED_V70_TAG, actual_commit=actual)
        if actual.lower() != EXPECTED_V70_TAG.lower():
            row.update(status="failed", detail="refs/tags/v70 does not match the frozen commit")
        else:
            row["detail"] = "refs/tags/v70 matches the frozen commit"
    return row


def _method_duplicates(class_node):
    methods = {}
    for node in class_node.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            methods.setdefault(node.name, []).append(node.lineno)
    return {name: lines for name, lines in methods.items() if len(lines) > 1}


def _load_dependency_contract(path):
    contract = json.loads(Path(path).read_text(encoding="utf-8"))
    if contract.get("contract") != "p1_include_dependency_contract":
        raise GateError("dependency contract kind is invalid")
    rows = contract.get("chunks")
    if not isinstance(rows, list):
        raise GateError("dependency contract chunks must be a list")
    paths = [row.get("path") for row in rows]
    if paths != EXPECTED_CHUNKS:
        raise GateError("dependency contract does not cover the exact chunk order")
    seen = set()
    previous_layer = -1
    adapters = {}
    for row in rows:
        path = row["path"]
        layer = row.get("layer")
        if not isinstance(layer, int) or layer <= previous_layer:
            raise GateError("dependency contract layers must be strictly increasing")
        previous_layer = layer
        allowed = row.get("allowed_dependencies")
        if not isinstance(allowed, list) or len(allowed) != len(set(allowed)):
            raise GateError("%s has invalid allowed_dependencies" % path)
        if any(item not in seen for item in allowed):
            raise GateError("%s declares a reverse or unknown dependency" % path)
        adapter = row.get("exports_adapter")
        if adapter:
            if adapter not in ("Filter", "Spider") or adapter in adapters:
                raise GateError("invalid or duplicate adapter export in %s" % path)
            adapters[adapter] = (path, layer)
        seen.add(path)
    if set(adapters) != {"Filter", "Spider"}:
        raise GateError("dependency contract must locate Filter and Spider adapters")
    return contract, adapters


def check_structure(source_dir=SOURCE_DIR, contract_path=None):
    source_dir = Path(source_dir)
    contract_path = Path(contract_path) if contract_path else source_dir / "dependency_contract.json"
    errors = []
    try:
        contract, adapters = _load_dependency_contract(contract_path)
    except (OSError, json.JSONDecodeError, GateError) as exc:
        contract, adapters = None, {}
        errors.append("invalid P1 dependency contract: %s" % exc)
    for name in ("baseline_v70.json", "release.json"):
        try:
            manifest = json.loads((source_dir / name).read_text(encoding="utf-8"))
            if manifest.get("chunks") != EXPECTED_CHUNKS:
                errors.append("%s chunk order differs from the P1 contract" % name)
        except (OSError, json.JSONDecodeError) as exc:
            errors.append("cannot load %s: %s" % (name, exc))

    parts_dir = source_dir / "parts"
    actual_parts = sorted(path.name for path in parts_dir.glob("*.pyinc"))
    if actual_parts != [Path(item).name for item in EXPECTED_CHUNKS]:
        errors.append("parts directory does not exactly match the ten declared chunks")

    chunks = []
    matching_chunk_hashes = 0
    for relative in EXPECTED_CHUNKS:
        path = source_dir / relative
        try:
            data = path.read_bytes()
            text = data.decode("utf-8")
            chunks.append(data)
            actual_sha256 = hashlib.sha256(data).hexdigest().upper()
            if actual_sha256 == EXPECTED_CHUNK_SHA256[relative]:
                matching_chunk_hashes += 1
            else:
                errors.append("%s SHA256 differs from the frozen V70 contract" % relative)
            non_empty = [line for line in text.splitlines() if line.strip()]
            if non_empty and non_empty[-1].lstrip().startswith("@"):
                errors.append("%s ends with a split decorator" % relative)
            if contract:
                layer = next(row["layer"] for row in contract["chunks"] if row["path"] == relative)
                for adapter, (adapter_path, adapter_layer) in adapters.items():
                    if layer < adapter_layer:
                        explicit = re.compile(
                            r"(?m)^(?:class\s+%s\b|%s\s*=|(?:from\s+\S+\s+)?import\s+%s\b(?!\s+as\s+\w+))"
                            % (adapter, adapter, adapter)
                        )
                        if explicit.search(text):
                            errors.append("%s explicitly depends on later %s adapter in %s" % (relative, adapter, adapter_path))
        except (OSError, UnicodeDecodeError) as exc:
            errors.append("cannot read %s: %s" % (relative, exc))

    if len(chunks) == len(EXPECTED_CHUNKS):
        try:
            prelude_lines = len(chunks[0].decode("utf-8").splitlines())
            tree = ast.parse(b"".join(chunks).decode("utf-8"))
            late_imports = [
                node.lineno for node in tree.body
                if isinstance(node, (ast.Import, ast.ImportFrom)) and node.lineno > prelude_lines
            ]
            if late_imports:
                errors.append("top-level imports appear outside the prelude at lines %s" % late_imports)
            for class_name in ("Spider", "Filter"):
                classes = [node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == class_name]
                if len(classes) != 1:
                    errors.append("expected exactly one top-level %s class" % class_name)
                elif _method_duplicates(classes[0]):
                    errors.append("%s contains duplicate methods" % class_name)
        except (UnicodeDecodeError, SyntaxError) as exc:
            errors.append("assembled chunks do not parse: %s" % exc)

    detail = "; ".join(errors) if errors else (
        "P1 include dependency contract passed: exact order, strictly increasing layers, "
        "earlier-only declarations, adapter boundaries, imports, and assembled structure"
    )
    return _step(
        "structure_and_dependency",
        "failed" if errors else "passed",
        detail=detail,
        frozen_part_sha256_matches=matching_chunk_hashes,
        frozen_part_sha256_expected=len(EXPECTED_CHUNK_SHA256),
    )


def check_p2_module_dag(source_dir=SOURCE_DIR):
    source_dir = Path(source_dir)
    errors = []
    expected_files = set(P2_MODULE_DAG)
    actual_files = {path.name for path in source_dir.glob("resource_*.py")}
    if actual_files != expected_files:
        errors.append(
            "P2 resource modules differ: expected %s, found %s"
            % (sorted(expected_files), sorted(actual_files))
        )

    module_names = {Path(name).stem for name in expected_files}
    for filename, expected_dependencies in P2_MODULE_DAG.items():
        path = source_dir / filename
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, UnicodeDecodeError, SyntaxError) as exc:
            errors.append("cannot parse %s: %s" % (filename, exc))
            continue

        dependencies = set()
        absolute_local_imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.level:
                    if node.level != 1:
                        errors.append(
                            "%s uses non-sibling relative import at line %d" % (filename, node.lineno)
                        )
                    dependencies.add(node.module or ".")
                else:
                    module = node.module or ""
                    base = module.rsplit(".", 1)[-1]
                    if base in module_names:
                        absolute_local_imports.add(module)
                    absolute_local_imports.update(alias.name for alias in node.names if alias.name in module_names)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.rsplit(".", 1)[-1] in module_names:
                        absolute_local_imports.add(alias.name)

        if absolute_local_imports:
            errors.append(
                "%s uses non-relative P2 imports: %s" % (filename, sorted(absolute_local_imports))
            )
        if dependencies != set(expected_dependencies):
            errors.append(
                "%s dependencies differ: expected %s, found %s"
                % (filename, sorted(expected_dependencies), sorted(dependencies))
            )

    expected_by_fold = {name.casefold(): name for name in expected_files}
    for manifest_name in ("baseline_v70.json", "release.json"):
        try:
            manifest = json.loads((source_dir / manifest_name).read_text(encoding="utf-8"))
            chunks = manifest.get("chunks")
            if not isinstance(chunks, list):
                raise GateError("chunks must be a list")
            included = sorted({
                expected_by_fold[basename]
                for basename in (Path(str(item)).name.casefold() for item in chunks)
                if basename in expected_by_fold
            })
            if included:
                errors.append("%s includes P2 modules: %s" % (manifest_name, included))
        except (OSError, json.JSONDecodeError, GateError) as exc:
            errors.append("cannot inspect %s for P2 modules: %s" % (manifest_name, exc))

    detail = "; ".join(errors) if errors else (
        "fixed P2 module DAG passed: candidate ordering/shadow background/shadow policy/models/normalization/output admission/preference/row identity/row merge/schema are leaves, candidate merge imports row identity, candidate pipeline imports merge/ordering, candidate shadow imports ordering/pipeline, shadow composition imports ordering/shadow/policy, matching imports normalization, "
        "scoring imports matching/normalization, row scoring imports matching/normalization/scoring, "
        "provider imports models/schema/shadow, search plan imports provider/schema, "
        "search shadow imports models/provider/plan, shadow imports models/schema, "
        "V70 search adapter imports provider/identity/plan/search shadow, layered search runtime imports background/policy/V70 adapter, and no P2 module is released"
    )
    return _step("p2_module_dag", "failed" if errors else "passed", detail=detail)


_QUOTED_ASSIGNMENT = re.compile(
    r'''(?ix)["']?\b(%s)\b["']?\s*[:=]\s*(?:[rubf]{0,2})?(["'])(.*?)\2''' % _SECRET_NAME_PATTERN
)
_UNQUOTED_ASSIGNMENT = re.compile(
    r'''(?ix)\b(%s)\b\s*[:=]\s*(?:Bearer\s+|Basic\s+)?([^\s,;&\]\}]+)''' % _SECRET_NAME_PATTERN
)
_HEADER_SECRET = re.compile(r"(?i)^\s*(authorization|cookie)\s*:\s*(.+?)\s*$")
_URL = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
_PLACEHOLDER = re.compile(
    r"(?i)^(?:<[^>]+>|\$\{[^}]+\}|%(?:s|\([^)]+\)s)|none|null|empty|example|sample|"
    r"placeholder|dummy|redacted|changeme|fixture(?:[-_].*)?|test(?:[-_].*)?|your[-_].*)$"
)


def _looks_placeholder(value):
    value = value.strip().strip("\"'")
    if not value or _PLACEHOLDER.fullmatch(value):
        return True
    lower = value.lower()
    return any(marker in lower for marker in ("<token>", "<secret>", "<password>", "${", "example.com"))


def _looks_protocol_header_name(value):
    return value.strip().strip("\"'").casefold() in (
        "authorization", "proxy-authorization",
    )


def _is_reserved_test_host(hostname):
    hostname = (hostname or "").rstrip(".").casefold()
    return hostname in ("example", "invalid", "localhost", "test") or hostname.endswith(
        (".example", ".invalid", ".localhost", ".test")
    )


def _url_has_credential(url):
    try:
        parsed = urlsplit(url)
    except ValueError:
        return False
    if _is_reserved_test_host(parsed.hostname):
        return False
    if parsed.username is not None and not _looks_placeholder(parsed.username):
        return True
    if parsed.password is not None and not _looks_placeholder(parsed.password):
        return True
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        if key.lower() in _SENSITIVE_QUERY_KEYS and not _looks_placeholder(value):
            return True
    return bool(re.search(r"/(?:subscribe|subscription)/([^/?#]{8,})", parsed.path, re.I)) and not _looks_placeholder(parsed.path.rsplit("/", 1)[-1])


def _managed_test_paths(repo_root):
    test_root = Path(repo_root) / "tests"
    return tuple(sorted(
        (
            path for path in test_root.rglob("*")
            if path.is_file()
            and "__pycache__" not in path.parts
            and path.suffix.lower() != ".pyc"
        ),
        key=lambda path: path.relative_to(repo_root).as_posix(),
    ))


def managed_sensitive_paths(repo_root=REPO_ROOT):
    repo_root = Path(repo_root)
    paths = [
        repo_root / item
        for item in (
            P1_MANAGED_FILES + P2_MANAGED_FILES + P3_MANAGED_FILES
            + P4_MANAGED_FILES + P5_MANAGED_FILES
        )
    ]
    paths.extend(sorted((repo_root / "src/douban_tmdb_follow_single/parts").glob("*.pyinc")))
    paths.extend(_managed_test_paths(repo_root))
    return tuple(sorted(
        set(paths), key=lambda path: path.relative_to(repo_root).as_posix(),
    ))


def implementation_tree_paths(repo_root=REPO_ROOT):
    repo_root = Path(repo_root)
    return managed_sensitive_paths(repo_root)


def check_implementation_tree(repo_root=REPO_ROOT, paths=None):
    repo_root = Path(repo_root).resolve()
    paths = implementation_tree_paths(repo_root) if paths is None else tuple({Path(path) for path in paths})
    digest = hashlib.sha256()
    entries = []
    errors = []
    for path in paths:
        path = Path(path)
        try:
            relative = path.resolve().relative_to(repo_root).as_posix()
            payload = _read_no_reparse_bytes(path, "implementation tree file")
        except (OSError, ValueError, GateError) as exc:
            errors.append(_redact(exc))
            continue
        file_sha256 = hashlib.sha256(payload).hexdigest().upper()
        entries.append((relative, payload, file_sha256))
    entries.sort(key=lambda item: item[0])
    manifest = []
    for relative, payload, file_sha256 in entries:
        manifest.append({"path": relative, "size": len(payload), "sha256": file_sha256})
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(len(payload)).encode("ascii"))
        digest.update(b"\0")
        digest.update(payload)
        digest.update(b"\0")
    if not manifest:
        errors.append("implementation tree is empty")
    return _step(
        "implementation_tree", "failed" if errors else "passed",
        detail=(
            "; ".join(errors)
            if errors else "content-addressed V80 implementation tree recorded"
        ),
        schema="v80-implementation-tree/1",
        file_count=len(manifest),
        tree_sha256=digest.hexdigest().upper() if manifest else None,
        manifest=manifest,
    )


def verify_implementation_tree_stable(initial, current):
    result = dict(initial)
    stable = (
        initial.get("status") == "passed"
        and current.get("status") == "passed"
        and initial.get("file_count") == current.get("file_count")
        and initial.get("tree_sha256") == current.get("tree_sha256")
        and initial.get("manifest") == current.get("manifest")
    )
    result["stable_after_commands"] = stable
    if stable:
        result["detail"] = "content-addressed V80 implementation tree remained stable through all gates"
    else:
        result.update(
            status="failed",
            detail="V80 implementation tree changed while the stage gate was running",
            final_file_count=current.get("file_count"),
            final_tree_sha256=current.get("tree_sha256"),
        )
    return result


def scan_sensitive_files(paths, repo_root=REPO_ROOT):
    repo_root = Path(repo_root).resolve()
    findings = []
    for path in paths:
        path = Path(path)
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError) as exc:
            findings.append({"path": str(path), "line": 0, "rule": "unreadable", "error": _redact(exc)})
            continue
        try:
            display_path = path.resolve().relative_to(repo_root).as_posix()
        except ValueError:
            display_path = path.name
        for line_number, line in enumerate(lines, 1):
            line_without_urls = _URL.sub("<url>", line)
            header = _HEADER_SECRET.match(line_without_urls)
            if (
                header
                and not _looks_placeholder(header.group(2))
                and not _looks_protocol_header_name(header.group(2))
                and len(header.group(2).strip()) >= 8
            ):
                findings.append({"path": display_path, "line": line_number, "rule": "literal_%s" % header.group(1).lower()})
                continue
            occupied = []
            for match in _QUOTED_ASSIGNMENT.finditer(line_without_urls):
                occupied.append(match.span())
                value = match.group(3).strip()
                if (
                    not _looks_placeholder(value)
                    and not _looks_protocol_header_name(value)
                    and len(value) >= 8
                ):
                    findings.append({"path": display_path, "line": line_number, "rule": "literal_%s" % match.group(1).lower()})
            for match in _UNQUOTED_ASSIGNMENT.finditer(line_without_urls):
                if any(start <= match.start() < end for start, end in occupied):
                    continue
                value = match.group(2).strip().strip("\"'")
                if "(" in value or value.startswith(("self.", "cls.", "context.", "config.")):
                    continue
                if not _looks_placeholder(value) and len(value) >= 8:
                    findings.append({"path": display_path, "line": line_number, "rule": "literal_%s" % match.group(1).lower()})
            for match in _URL.finditer(line):
                if _url_has_credential(match.group(0).rstrip(".,);]")):
                    findings.append({"path": display_path, "line": line_number, "rule": "credential_url"})
    return findings


def check_sensitive(repo_root=REPO_ROOT, paths=None):
    managed = paths is None
    paths = managed_sensitive_paths(repo_root) if managed else list(paths)
    missing = [Path(path) for path in paths if not Path(path).is_file()]
    findings = scan_sensitive_files(paths, repo_root=repo_root)
    if managed and missing:
        findings.extend({"path": str(path), "line": 0, "rule": "missing_managed_file"} for path in missing)
    return _step(
        "sensitive_data", "failed" if findings else "passed",
        detail="%d sensitive scan finding(s)" % len(findings) if findings else "all managed V80 files contain no obvious committed credentials",
        findings=findings, files_scanned=len(paths), managed_files=[str(Path(path)) for path in paths],
    )


def check_builds(build=None):
    build = build or _load_build_module()
    started = time.monotonic()
    try:
        baseline = build.check_release(BASELINE_MANIFEST)
        development = build.build_release(DEV_MANIFEST)
        vendor = development.get("vendor")
        if not isinstance(vendor, dict):
            raise GateError("V80 development build is missing the P2 resource shadow vendor")
        overlay = development.get("overlay")
        if not isinstance(overlay, dict):
            raise GateError("V80 development build is missing the runtime shadow overlay")
        pre_overlay = baseline["bytes"] + vendor.get("bytes", b"")
        if overlay.get("input_size") != len(pre_overlay):
            raise GateError("runtime shadow overlay input size does not match V70 plus vendor")
        if overlay.get("input_sha256") != hashlib.sha256(pre_overlay).hexdigest().upper():
            raise GateError("runtime shadow overlay input is not the frozen V70 plus vendor")
        history_module = development.get("history_module")
        if not isinstance(history_module, dict):
            raise GateError("V80 development build is missing the P3 History module")
        history_overlay = development.get("history_overlay")
        if not isinstance(history_overlay, dict):
            raise GateError("V80 development build is missing the P3 History overlay")
        if history_module.get("input_size") != overlay.get("size"):
            raise GateError("P3 History module input size does not match the P2 overlay output")
        if history_module.get("input_sha256") != overlay.get("sha256"):
            raise GateError("P3 History module is not based on the P2 overlay output")
        module_bytes = history_module.get("bytes", b"")
        if history_module.get("size") != len(module_bytes):
            raise GateError("P3 History module size metadata is invalid")
        if history_module.get("sha256") != hashlib.sha256(module_bytes).hexdigest().upper():
            raise GateError("P3 History module hash metadata is invalid")
        if history_overlay.get("input_size") != history_module.get("output_size"):
            raise GateError("P3 History overlay input size does not match the appended module output")
        if history_overlay.get("input_sha256") != history_module.get("output_sha256"):
            raise GateError("P3 History overlay is not based on the appended module output")
        reliability_module = development.get("reliability_module")
        if not isinstance(reliability_module, dict):
            raise GateError("V80 development build is missing the P3 Reliability module")
        reliability_overlay = development.get("reliability_overlay")
        if not isinstance(reliability_overlay, dict):
            raise GateError("V80 development build is missing the P3 Reliability overlay")
        if reliability_module.get("input_size") != history_overlay.get("size"):
            raise GateError("P3 Reliability module input size does not match the History overlay output")
        if reliability_module.get("input_sha256") != history_overlay.get("sha256"):
            raise GateError("P3 Reliability module is not based on the History overlay output")
        reliability_input = reliability_module.get("input_bytes")
        if not isinstance(reliability_input, bytes):
            raise GateError("P3 Reliability module input bytes are unavailable")
        if reliability_module.get("input_size") != len(reliability_input):
            raise GateError("P3 Reliability module input size metadata is invalid")
        if reliability_module.get("input_sha256") != hashlib.sha256(reliability_input).hexdigest().upper():
            raise GateError("P3 Reliability module input hash metadata is invalid")
        reliability_bytes = reliability_module.get("bytes", b"")
        if reliability_module.get("size") != len(reliability_bytes):
            raise GateError("P3 Reliability module size metadata is invalid")
        if reliability_module.get("sha256") != hashlib.sha256(reliability_bytes).hexdigest().upper():
            raise GateError("P3 Reliability module hash metadata is invalid")
        reliability_module_output = reliability_input + reliability_bytes
        if reliability_module.get("output_size") != len(reliability_module_output):
            raise GateError("P3 Reliability module output size metadata is invalid")
        if reliability_module.get("output_sha256") != hashlib.sha256(reliability_module_output).hexdigest().upper():
            raise GateError("P3 Reliability module output hash metadata is invalid")
        if reliability_overlay.get("input_size") != len(reliability_module_output):
            raise GateError("P3 Reliability overlay input size does not match the appended module output")
        if reliability_overlay.get("input_sha256") != hashlib.sha256(reliability_module_output).hexdigest().upper():
            raise GateError("P3 Reliability overlay is not based on the appended module output")
        overlay_builder = _load_reliability_overlay_builder()
        rebuilt_overlay = overlay_builder.apply_reliability_overlay(reliability_module_output)
        for key in ("size", "sha256", "input_size", "input_sha256", "insertions"):
            if reliability_overlay.get(key) != rebuilt_overlay.get(key):
                raise GateError("P3 Reliability overlay %s metadata is invalid" % key)
        cache_health_module = development.get("cache_health_module")
        if not isinstance(cache_health_module, dict):
            raise GateError("V80 development build is missing the P3 Cache Health module")
        cache_health_overlay = development.get("cache_health_overlay")
        if not isinstance(cache_health_overlay, dict):
            raise GateError("V80 development build is missing the P3 Cache Health overlay")
        cache_health_input = cache_health_module.get("input_bytes")
        if not isinstance(cache_health_input, bytes):
            raise GateError("P3 Cache Health module input bytes are unavailable")
        if rebuilt_overlay["bytes"] != cache_health_input:
            raise GateError("P3 Reliability overlay output bytes do not match the Cache Health module input")
        if cache_health_module.get("input_size") != rebuilt_overlay.get("size"):
            raise GateError("P3 Cache Health module input size does not match the Reliability overlay output")
        if cache_health_module.get("input_sha256") != rebuilt_overlay.get("sha256"):
            raise GateError("P3 Cache Health module is not based on the Reliability overlay output")
        cache_health_bytes = cache_health_module.get("bytes", b"")
        if cache_health_module.get("size") != len(cache_health_bytes):
            raise GateError("P3 Cache Health module size metadata is invalid")
        if cache_health_module.get("sha256") != hashlib.sha256(cache_health_bytes).hexdigest().upper():
            raise GateError("P3 Cache Health module hash metadata is invalid")
        cache_health_module_output = cache_health_input + cache_health_bytes
        if cache_health_module.get("output_size") != len(cache_health_module_output):
            raise GateError("P3 Cache Health module output size metadata is invalid")
        if cache_health_module.get("output_sha256") != hashlib.sha256(cache_health_module_output).hexdigest().upper():
            raise GateError("P3 Cache Health module output hash metadata is invalid")
        if cache_health_overlay.get("input_size") != len(cache_health_module_output):
            raise GateError("P3 Cache Health overlay input size does not match the appended module output")
        if cache_health_overlay.get("input_sha256") != hashlib.sha256(cache_health_module_output).hexdigest().upper():
            raise GateError("P3 Cache Health overlay is not based on the appended module output")
        cache_health_builder = _load_cache_health_overlay_builder()
        rebuilt_cache_health = cache_health_builder.apply_cache_health_overlay(
            cache_health_module_output
        )
        for key in ("size", "sha256", "input_size", "input_sha256", "insertions"):
            if cache_health_overlay.get(key) != rebuilt_cache_health.get(key):
                raise GateError("P3 Cache Health overlay %s metadata is invalid" % key)
        background_bulkhead_module = development.get("background_bulkhead_module")
        if not isinstance(background_bulkhead_module, dict):
            raise GateError("V80 development build is missing the P3 Background Bulkhead module")
        background_bulkhead_overlay = development.get("background_bulkhead_overlay")
        if not isinstance(background_bulkhead_overlay, dict):
            raise GateError("V80 development build is missing the P3 Background Bulkhead overlay")
        background_bulkhead_input = background_bulkhead_module.get("input_bytes")
        if not isinstance(background_bulkhead_input, bytes):
            raise GateError("P3 Background Bulkhead module input bytes are unavailable")
        if rebuilt_cache_health["bytes"] != background_bulkhead_input:
            raise GateError(
                "P3 Cache Health overlay output bytes do not match the Background Bulkhead module input"
            )
        if background_bulkhead_module.get("input_size") != rebuilt_cache_health.get("size"):
            raise GateError(
                "P3 Background Bulkhead module input size does not match the Cache Health overlay output"
            )
        if background_bulkhead_module.get("input_sha256") != rebuilt_cache_health.get("sha256"):
            raise GateError(
                "P3 Background Bulkhead module is not based on the Cache Health overlay output"
            )
        background_bulkhead_bytes = background_bulkhead_module.get("bytes", b"")
        if background_bulkhead_module.get("size") != len(background_bulkhead_bytes):
            raise GateError("P3 Background Bulkhead module size metadata is invalid")
        if (
            background_bulkhead_module.get("sha256")
            != hashlib.sha256(background_bulkhead_bytes).hexdigest().upper()
        ):
            raise GateError("P3 Background Bulkhead module hash metadata is invalid")
        background_bulkhead_module_output = (
            background_bulkhead_input + background_bulkhead_bytes
        )
        if (
            background_bulkhead_module.get("output_size")
            != len(background_bulkhead_module_output)
        ):
            raise GateError("P3 Background Bulkhead module output size metadata is invalid")
        if (
            background_bulkhead_module.get("output_sha256")
            != hashlib.sha256(background_bulkhead_module_output).hexdigest().upper()
        ):
            raise GateError("P3 Background Bulkhead module output hash metadata is invalid")
        if background_bulkhead_overlay.get("input_size") != len(background_bulkhead_module_output):
            raise GateError(
                "P3 Background Bulkhead overlay input size does not match the appended module output"
            )
        if (
            background_bulkhead_overlay.get("input_sha256")
            != hashlib.sha256(background_bulkhead_module_output).hexdigest().upper()
        ):
            raise GateError(
                "P3 Background Bulkhead overlay is not based on the appended module output"
            )
        background_bulkhead_builder = _load_background_bulkhead_overlay_builder()
        rebuilt_background_bulkhead = (
            background_bulkhead_builder.apply_background_bulkhead_overlay(
                background_bulkhead_module_output
            )
        )
        timeout_budget_module = development.get("timeout_budget_module")
        if not isinstance(timeout_budget_module, dict):
            raise GateError("V80 development build is missing the P3 Timeout Budget module")
        timeout_budget_overlay = development.get("timeout_budget_overlay")
        if not isinstance(timeout_budget_overlay, dict):
            raise GateError("V80 development build is missing the P3 Timeout Budget overlay")
        timeout_budget_input = timeout_budget_module.get("input_bytes")
        if not isinstance(timeout_budget_input, bytes):
            raise GateError("P3 Timeout Budget module input bytes are unavailable")
        if rebuilt_background_bulkhead["bytes"] != timeout_budget_input:
            raise GateError(
                "P3 Background Bulkhead overlay output bytes do not match the Timeout Budget module input"
            )
        for key in ("size", "sha256", "input_size", "input_sha256", "insertions"):
            if background_bulkhead_overlay.get(key) != rebuilt_background_bulkhead.get(key):
                raise GateError(
                    "P3 Background Bulkhead overlay %s metadata is invalid" % key
                )
        if timeout_budget_module.get("input_size") != rebuilt_background_bulkhead.get("size"):
            raise GateError(
                "P3 Timeout Budget module input size does not match the Background Bulkhead overlay output"
            )
        if timeout_budget_module.get("input_sha256") != rebuilt_background_bulkhead.get("sha256"):
            raise GateError(
                "P3 Timeout Budget module is not based on the Background Bulkhead overlay output"
            )
        timeout_budget_bytes = timeout_budget_module.get("bytes", b"")
        if timeout_budget_module.get("size") != len(timeout_budget_bytes):
            raise GateError("P3 Timeout Budget module size metadata is invalid")
        if (
            timeout_budget_module.get("sha256")
            != hashlib.sha256(timeout_budget_bytes).hexdigest().upper()
        ):
            raise GateError("P3 Timeout Budget module hash metadata is invalid")
        timeout_budget_module_output = timeout_budget_input + timeout_budget_bytes
        if timeout_budget_module.get("output_size") != len(timeout_budget_module_output):
            raise GateError("P3 Timeout Budget module output size metadata is invalid")
        if (
            timeout_budget_module.get("output_sha256")
            != hashlib.sha256(timeout_budget_module_output).hexdigest().upper()
        ):
            raise GateError("P3 Timeout Budget module output hash metadata is invalid")
        if timeout_budget_overlay.get("input_size") != len(timeout_budget_module_output):
            raise GateError(
                "P3 Timeout Budget overlay input size does not match the appended module output"
            )
        if (
            timeout_budget_overlay.get("input_sha256")
            != hashlib.sha256(timeout_budget_module_output).hexdigest().upper()
        ):
            raise GateError(
                "P3 Timeout Budget overlay is not based on the appended module output"
            )
        timeout_budget_builder = _load_timeout_budget_overlay_builder()
        rebuilt_timeout_budget = timeout_budget_builder.apply_timeout_budget_overlay(
            timeout_budget_module_output
        )
        security_policy_module = development.get("security_policy_module")
        if not isinstance(security_policy_module, dict):
            raise GateError("V80 development build is missing the P4 Security Policy module")
        security_policy_input = security_policy_module.get("input_bytes")
        if not isinstance(security_policy_input, bytes):
            raise GateError("P4 Security Policy module input bytes are unavailable")
        if rebuilt_timeout_budget["bytes"] != security_policy_input:
            raise GateError(
                "P3 Timeout Budget overlay output bytes do not match the Security Policy module input"
            )
        for key in ("size", "sha256", "input_size", "input_sha256", "insertions"):
            if timeout_budget_overlay.get(key) != rebuilt_timeout_budget.get(key):
                raise GateError(
                    "P3 Timeout Budget overlay %s metadata is invalid" % key
                )
        if (
            security_policy_module.get("input_size") != rebuilt_timeout_budget.get("size")
            or security_policy_module.get("input_sha256") != rebuilt_timeout_budget.get("sha256")
        ):
            raise GateError(
                "P4 Security Policy module is not based on the Timeout Budget overlay output"
            )
        security_policy_bytes = security_policy_module.get("bytes", b"")
        managed_security_policy_bytes = _read_no_reparse_bytes(
            SECURITY_POLICY_MODULE, "P4 Security Policy module"
        )
        if security_policy_bytes != managed_security_policy_bytes:
            raise GateError("P4 Security Policy module bytes do not match the managed source")
        if security_policy_module.get("size") != len(security_policy_bytes):
            raise GateError("P4 Security Policy module size metadata is invalid")
        if (
            security_policy_module.get("sha256")
            != hashlib.sha256(security_policy_bytes).hexdigest().upper()
        ):
            raise GateError("P4 Security Policy module hash metadata is invalid")
        security_policy_output = security_policy_input + security_policy_bytes
        if security_policy_module.get("output_size") != len(security_policy_output):
            raise GateError("P4 Security Policy module output size metadata is invalid")
        if (
            security_policy_module.get("output_sha256")
            != hashlib.sha256(security_policy_output).hexdigest().upper()
        ):
            raise GateError("P4 Security Policy module output hash metadata is invalid")
        route_security_overlay = development.get("route_security_overlay")
        if not isinstance(route_security_overlay, dict):
            raise GateError("V80 development build is missing the P4 Route Security overlay")
        if route_security_overlay.get("input_size") != len(security_policy_output):
            raise GateError(
                "P4 Route Security overlay input size does not match the Security Policy module output"
            )
        if (
            route_security_overlay.get("input_sha256")
            != hashlib.sha256(security_policy_output).hexdigest().upper()
        ):
            raise GateError(
                "P4 Route Security overlay is not based on the Security Policy module output"
            )
        route_security_builder = _load_route_security_overlay_builder()
        rebuilt_route_security = route_security_builder.apply_route_security_overlay(
            security_policy_output
        )
        for key in ("size", "sha256", "input_size", "input_sha256", "insertions"):
            if route_security_overlay.get(key) != rebuilt_route_security.get(key):
                raise GateError(
                    "P4 Route Security overlay %s metadata is invalid" % key
                )
        json_shape_policy_module = development.get("json_shape_policy_module")
        if not isinstance(json_shape_policy_module, dict):
            raise GateError("V80 development build is missing the P4 JSON Shape Policy module")
        json_shape_policy_input = json_shape_policy_module.get("input_bytes")
        if not isinstance(json_shape_policy_input, bytes):
            raise GateError("P4 JSON Shape Policy module input bytes are unavailable")
        if rebuilt_route_security["bytes"] != json_shape_policy_input:
            raise GateError(
                "P4 Route Security overlay output bytes do not match the JSON Shape Policy module input"
            )
        if (
            json_shape_policy_module.get("input_size") != rebuilt_route_security.get("size")
            or json_shape_policy_module.get("input_sha256") != rebuilt_route_security.get("sha256")
        ):
            raise GateError(
                "P4 JSON Shape Policy module is not based on the Route Security overlay output"
            )
        json_shape_policy_bytes = json_shape_policy_module.get("bytes", b"")
        managed_json_shape_policy_bytes = _read_no_reparse_bytes(
            JSON_SHAPE_POLICY_MODULE, "P4 JSON Shape Policy module"
        )
        if json_shape_policy_bytes != managed_json_shape_policy_bytes:
            raise GateError("P4 JSON Shape Policy module bytes do not match the managed source")
        if json_shape_policy_module.get("size") != len(json_shape_policy_bytes):
            raise GateError("P4 JSON Shape Policy module size metadata is invalid")
        if (
            json_shape_policy_module.get("sha256")
            != hashlib.sha256(json_shape_policy_bytes).hexdigest().upper()
        ):
            raise GateError("P4 JSON Shape Policy module hash metadata is invalid")
        json_shape_policy_output = json_shape_policy_input + json_shape_policy_bytes
        if json_shape_policy_module.get("output_size") != len(json_shape_policy_output):
            raise GateError("P4 JSON Shape Policy module output size metadata is invalid")
        if (
            json_shape_policy_module.get("output_sha256")
            != hashlib.sha256(json_shape_policy_output).hexdigest().upper()
        ):
            raise GateError("P4 JSON Shape Policy module output hash metadata is invalid")
        tmdb_json_shape_overlay = development.get("tmdb_json_shape_overlay")
        if not isinstance(tmdb_json_shape_overlay, dict):
            raise GateError("V80 development build is missing the P4 TMDB JSON Shape overlay")
        if tmdb_json_shape_overlay.get("input_size") != len(json_shape_policy_output):
            raise GateError(
                "P4 TMDB JSON Shape overlay input size does not match the JSON Shape Policy output"
            )
        if (
            tmdb_json_shape_overlay.get("input_sha256")
            != hashlib.sha256(json_shape_policy_output).hexdigest().upper()
        ):
            raise GateError(
                "P4 TMDB JSON Shape overlay is not based on the JSON Shape Policy output"
            )
        tmdb_json_shape_builder = _load_tmdb_json_shape_overlay_builder()
        rebuilt_tmdb_json_shape = tmdb_json_shape_builder.apply_tmdb_json_shape_overlay(
            json_shape_policy_output
        )
        for key in ("size", "sha256", "input_size", "input_sha256", "insertions"):
            if tmdb_json_shape_overlay.get(key) != rebuilt_tmdb_json_shape.get(key):
                raise GateError(
                    "P4 TMDB JSON Shape overlay %s metadata is invalid" % key
                )
        tmdb_response_policy_module = development.get("tmdb_response_policy_module")
        if not isinstance(tmdb_response_policy_module, dict):
            raise GateError("V80 development build is missing the P4 TMDB Response Policy module")
        tmdb_response_policy_input = tmdb_response_policy_module.get("input_bytes")
        if not isinstance(tmdb_response_policy_input, bytes):
            raise GateError("P4 TMDB Response Policy module input bytes are unavailable")
        if rebuilt_tmdb_json_shape["bytes"] != tmdb_response_policy_input:
            raise GateError(
                "P4 TMDB JSON Shape overlay output bytes do not match the TMDB Response Policy module input"
            )
        if (
            tmdb_response_policy_module.get("input_size")
            != rebuilt_tmdb_json_shape.get("size")
            or tmdb_response_policy_module.get("input_sha256")
            != rebuilt_tmdb_json_shape.get("sha256")
        ):
            raise GateError(
                "P4 TMDB Response Policy module is not based on the TMDB JSON Shape overlay output"
            )
        tmdb_response_policy_bytes = tmdb_response_policy_module.get("bytes", b"")
        managed_tmdb_response_policy_bytes = _read_no_reparse_bytes(
            TMDB_RESPONSE_POLICY_MODULE, "P4 TMDB Response Policy module"
        )
        if tmdb_response_policy_bytes != managed_tmdb_response_policy_bytes:
            raise GateError(
                "P4 TMDB Response Policy module bytes do not match the managed source"
            )
        if tmdb_response_policy_module.get("size") != len(tmdb_response_policy_bytes):
            raise GateError("P4 TMDB Response Policy module size metadata is invalid")
        if (
            tmdb_response_policy_module.get("sha256")
            != hashlib.sha256(tmdb_response_policy_bytes).hexdigest().upper()
        ):
            raise GateError("P4 TMDB Response Policy module hash metadata is invalid")
        tmdb_response_policy_output = (
            tmdb_response_policy_input + tmdb_response_policy_bytes
        )
        if (
            tmdb_response_policy_module.get("output_size")
            != len(tmdb_response_policy_output)
        ):
            raise GateError("P4 TMDB Response Policy module output size metadata is invalid")
        if (
            tmdb_response_policy_module.get("output_sha256")
            != hashlib.sha256(tmdb_response_policy_output).hexdigest().upper()
        ):
            raise GateError("P4 TMDB Response Policy module output hash metadata is invalid")
        tmdb_response_boundary_overlay = development.get("tmdb_response_boundary_overlay")
        if not isinstance(tmdb_response_boundary_overlay, dict):
            raise GateError("V80 development build is missing the P4 TMDB Response Boundary overlay")
        if (
            tmdb_response_boundary_overlay.get("input_size")
            != len(tmdb_response_policy_output)
        ):
            raise GateError(
                "P4 TMDB Response Boundary overlay input size does not match the policy output"
            )
        if (
            tmdb_response_boundary_overlay.get("input_sha256")
            != hashlib.sha256(tmdb_response_policy_output).hexdigest().upper()
        ):
            raise GateError(
                "P4 TMDB Response Boundary overlay is not based on the policy output"
            )
        tmdb_response_boundary_builder = _load_tmdb_response_boundary_overlay_builder()
        rebuilt_tmdb_response_boundary = (
            tmdb_response_boundary_builder.apply_tmdb_response_boundary_overlay(
                tmdb_response_policy_output
            )
        )
        for key in ("size", "sha256", "input_size", "input_sha256", "insertions"):
            if (
                tmdb_response_boundary_overlay.get(key)
                != rebuilt_tmdb_response_boundary.get(key)
            ):
                raise GateError(
                    "P4 TMDB Response Boundary overlay %s metadata is invalid" % key
                )
        diagnostic_redaction_policy_module = development.get(
            "diagnostic_redaction_policy_module"
        )
        if not isinstance(diagnostic_redaction_policy_module, dict):
            raise GateError(
                "V80 development build is missing the P4 Diagnostic Redaction Policy module"
            )
        diagnostic_redaction_policy_input = diagnostic_redaction_policy_module.get(
            "input_bytes"
        )
        if not isinstance(diagnostic_redaction_policy_input, bytes):
            raise GateError(
                "P4 Diagnostic Redaction Policy module input bytes are unavailable"
            )
        if rebuilt_tmdb_response_boundary["bytes"] != diagnostic_redaction_policy_input:
            raise GateError(
                "P4 TMDB Response Boundary overlay output bytes do not match the Diagnostic Redaction Policy module input"
            )
        if (
            diagnostic_redaction_policy_module.get("input_size")
            != rebuilt_tmdb_response_boundary.get("size")
            or diagnostic_redaction_policy_module.get("input_sha256")
            != rebuilt_tmdb_response_boundary.get("sha256")
        ):
            raise GateError(
                "P4 Diagnostic Redaction Policy module is not based on the TMDB Response Boundary overlay output"
            )
        diagnostic_redaction_policy_bytes = diagnostic_redaction_policy_module.get(
            "bytes", b""
        )
        managed_diagnostic_redaction_policy_bytes = _read_no_reparse_bytes(
            DIAGNOSTIC_REDACTION_POLICY_MODULE,
            "P4 Diagnostic Redaction Policy module",
        )
        if diagnostic_redaction_policy_bytes != managed_diagnostic_redaction_policy_bytes:
            raise GateError(
                "P4 Diagnostic Redaction Policy module bytes do not match the managed source"
            )
        if (
            diagnostic_redaction_policy_module.get("size")
            != len(diagnostic_redaction_policy_bytes)
        ):
            raise GateError(
                "P4 Diagnostic Redaction Policy module size metadata is invalid"
            )
        if (
            diagnostic_redaction_policy_module.get("sha256")
            != hashlib.sha256(diagnostic_redaction_policy_bytes).hexdigest().upper()
        ):
            raise GateError(
                "P4 Diagnostic Redaction Policy module hash metadata is invalid"
            )
        diagnostic_redaction_policy_output = (
            diagnostic_redaction_policy_input + diagnostic_redaction_policy_bytes
        )
        if (
            diagnostic_redaction_policy_module.get("output_size")
            != len(diagnostic_redaction_policy_output)
        ):
            raise GateError(
                "P4 Diagnostic Redaction Policy module output size metadata is invalid"
            )
        if (
            diagnostic_redaction_policy_module.get("output_sha256")
            != hashlib.sha256(diagnostic_redaction_policy_output).hexdigest().upper()
        ):
            raise GateError(
                "P4 Diagnostic Redaction Policy module output hash metadata is invalid"
            )
        diagnostic_redaction_overlay = development.get("diagnostic_redaction_overlay")
        if not isinstance(diagnostic_redaction_overlay, dict):
            raise GateError(
                "V80 development build is missing the P4 Diagnostic Redaction overlay"
            )
        if (
            diagnostic_redaction_overlay.get("input_size")
            != len(diagnostic_redaction_policy_output)
            or diagnostic_redaction_overlay.get("input_sha256")
            != hashlib.sha256(diagnostic_redaction_policy_output).hexdigest().upper()
        ):
            raise GateError(
                "P4 Diagnostic Redaction overlay is not based on the policy output"
            )
        diagnostic_redaction_builder = _load_diagnostic_redaction_overlay_builder()
        rebuilt_diagnostic_redaction = (
            diagnostic_redaction_builder.apply_diagnostic_redaction_overlay(
                diagnostic_redaction_policy_output
            )
        )
        for key in ("size", "sha256", "input_size", "input_sha256", "insertions"):
            if (
                diagnostic_redaction_overlay.get(key)
                != rebuilt_diagnostic_redaction.get(key)
            ):
                raise GateError(
                    "P4 Diagnostic Redaction overlay %s metadata is invalid" % key
                )
        douban_response_policy_module = development.get(
            "douban_response_policy_module"
        )
        if not isinstance(douban_response_policy_module, dict):
            raise GateError(
                "V80 development build is missing the P4 Douban Response Policy module"
            )
        douban_response_policy_input = douban_response_policy_module.get(
            "input_bytes"
        )
        if not isinstance(douban_response_policy_input, bytes):
            raise GateError(
                "P4 Douban Response Policy module input bytes are unavailable"
            )
        if rebuilt_diagnostic_redaction["bytes"] != douban_response_policy_input:
            raise GateError(
                "P4 Diagnostic Redaction overlay output bytes do not match the Douban Response Policy module input"
            )
        if (
            douban_response_policy_module.get("input_size")
            != rebuilt_diagnostic_redaction.get("size")
            or douban_response_policy_module.get("input_sha256")
            != rebuilt_diagnostic_redaction.get("sha256")
        ):
            raise GateError(
                "P4 Douban Response Policy module is not based on the Diagnostic Redaction overlay output"
            )
        douban_response_policy_bytes = douban_response_policy_module.get("bytes", b"")
        managed_douban_response_policy_bytes = _read_no_reparse_bytes(
            DOUBAN_RESPONSE_POLICY_MODULE,
            "P4 Douban Response Policy module",
        )
        if douban_response_policy_bytes != managed_douban_response_policy_bytes:
            raise GateError(
                "P4 Douban Response Policy module bytes do not match the managed source"
            )
        if (
            douban_response_policy_module.get("size")
            != len(douban_response_policy_bytes)
        ):
            raise GateError(
                "P4 Douban Response Policy module size metadata is invalid"
            )
        if (
            douban_response_policy_module.get("sha256")
            != hashlib.sha256(douban_response_policy_bytes).hexdigest().upper()
        ):
            raise GateError(
                "P4 Douban Response Policy module hash metadata is invalid"
            )
        douban_response_policy_output = (
            douban_response_policy_input + douban_response_policy_bytes
        )
        if (
            douban_response_policy_module.get("output_size")
            != len(douban_response_policy_output)
        ):
            raise GateError(
                "P4 Douban Response Policy module output size metadata is invalid"
            )
        if (
            douban_response_policy_module.get("output_sha256")
            != hashlib.sha256(douban_response_policy_output).hexdigest().upper()
        ):
            raise GateError(
                "P4 Douban Response Policy module output hash metadata is invalid"
            )
        douban_response_boundary_overlay = development.get(
            "douban_response_boundary_overlay"
        )
        if not isinstance(douban_response_boundary_overlay, dict):
            raise GateError(
                "V80 development build is missing the P4 Douban Response Boundary overlay"
            )
        if (
            douban_response_boundary_overlay.get("input_size")
            != len(douban_response_policy_output)
            or douban_response_boundary_overlay.get("input_sha256")
            != hashlib.sha256(douban_response_policy_output).hexdigest().upper()
        ):
            raise GateError(
                "P4 Douban Response Boundary overlay is not based on the policy output"
            )
        douban_response_boundary_builder = (
            _load_douban_response_boundary_overlay_builder()
        )
        rebuilt_douban_response_boundary = (
            douban_response_boundary_builder.apply_douban_response_boundary_overlay(
                douban_response_policy_output
            )
        )
        for key in ("size", "sha256", "input_size", "input_sha256", "insertions"):
            if (
                douban_response_boundary_overlay.get(key)
                != rebuilt_douban_response_boundary.get(key)
            ):
                raise GateError(
                    "P4 Douban Response Boundary overlay %s metadata is invalid" % key
                )
        douban_html_response_policy_module = development.get(
            "douban_html_response_policy_module"
        )
        if not isinstance(douban_html_response_policy_module, dict):
            raise GateError(
                "V80 development build is missing the P4 Douban HTML Response Policy module"
            )
        douban_html_response_policy_input = douban_html_response_policy_module.get(
            "input_bytes"
        )
        if not isinstance(douban_html_response_policy_input, bytes):
            raise GateError(
                "P4 Douban HTML Response Policy module input bytes are unavailable"
            )
        if (
            rebuilt_douban_response_boundary["bytes"]
            != douban_html_response_policy_input
        ):
            raise GateError(
                "P4 Douban Response Boundary overlay output bytes do not match the Douban HTML Response Policy module input"
            )
        if (
            douban_html_response_policy_module.get("input_size")
            != rebuilt_douban_response_boundary.get("size")
            or douban_html_response_policy_module.get("input_sha256")
            != rebuilt_douban_response_boundary.get("sha256")
        ):
            raise GateError(
                "P4 Douban HTML Response Policy module is not based on the Douban Response Boundary overlay output"
            )
        douban_html_response_policy_bytes = douban_html_response_policy_module.get(
            "bytes", b""
        )
        managed_douban_html_response_policy_bytes = _read_no_reparse_bytes(
            DOUBAN_HTML_RESPONSE_POLICY_MODULE,
            "P4 Douban HTML Response Policy module",
        )
        if (
            douban_html_response_policy_bytes
            != managed_douban_html_response_policy_bytes
        ):
            raise GateError(
                "P4 Douban HTML Response Policy module bytes do not match the managed source"
            )
        if (
            douban_html_response_policy_module.get("size")
            != len(douban_html_response_policy_bytes)
        ):
            raise GateError(
                "P4 Douban HTML Response Policy module size metadata is invalid"
            )
        if (
            douban_html_response_policy_module.get("sha256")
            != hashlib.sha256(
                douban_html_response_policy_bytes
            ).hexdigest().upper()
        ):
            raise GateError(
                "P4 Douban HTML Response Policy module hash metadata is invalid"
            )
        douban_html_response_policy_output = (
            douban_html_response_policy_input + douban_html_response_policy_bytes
        )
        if (
            douban_html_response_policy_module.get("output_size")
            != len(douban_html_response_policy_output)
        ):
            raise GateError(
                "P4 Douban HTML Response Policy module output size metadata is invalid"
            )
        if (
            douban_html_response_policy_module.get("output_sha256")
            != hashlib.sha256(
                douban_html_response_policy_output
            ).hexdigest().upper()
        ):
            raise GateError(
                "P4 Douban HTML Response Policy module output hash metadata is invalid"
            )
        douban_html_response_boundary_overlay = development.get(
            "douban_html_response_boundary_overlay"
        )
        if not isinstance(douban_html_response_boundary_overlay, dict):
            raise GateError(
                "V80 development build is missing the P4 Douban HTML Response Boundary overlay"
            )
        if (
            douban_html_response_boundary_overlay.get("input_size")
            != len(douban_html_response_policy_output)
            or douban_html_response_boundary_overlay.get("input_sha256")
            != hashlib.sha256(
                douban_html_response_policy_output
            ).hexdigest().upper()
        ):
            raise GateError(
                "P4 Douban HTML Response Boundary overlay is not based on the policy output"
            )
        douban_html_response_boundary_builder = (
            _load_douban_html_response_boundary_overlay_builder()
        )
        rebuilt_douban_html_response_boundary = (
            douban_html_response_boundary_builder.apply_douban_html_response_boundary_overlay(
                douban_html_response_policy_output
            )
        )
        for key in ("size", "sha256", "input_size", "input_sha256", "insertions"):
            if (
                douban_html_response_boundary_overlay.get(key)
                != rebuilt_douban_html_response_boundary.get(key)
            ):
                raise GateError(
                    "P4 Douban HTML Response Boundary overlay %s metadata is invalid"
                    % key
                )
        observability_policy_module = development.get(
            "observability_policy_module"
        )
        if not isinstance(observability_policy_module, dict):
            raise GateError(
                "V80 development build is missing the P5 Observability Policy module"
            )
        observability_policy_input = observability_policy_module.get("input_bytes")
        if not isinstance(observability_policy_input, bytes):
            raise GateError(
                "P5 Observability Policy module input bytes are unavailable"
            )
        if rebuilt_douban_html_response_boundary["bytes"] != observability_policy_input:
            raise GateError(
                "P4 Douban HTML Response Boundary overlay output bytes do not match the P5 Observability Policy module input"
            )
        if (
            observability_policy_module.get("input_size")
            != rebuilt_douban_html_response_boundary.get("size")
            or observability_policy_module.get("input_sha256")
            != rebuilt_douban_html_response_boundary.get("sha256")
        ):
            raise GateError(
                "P5 Observability Policy module is not based on the Douban HTML Response Boundary overlay output"
            )
        observability_policy_bytes = observability_policy_module.get("bytes", b"")
        managed_observability_policy_bytes = _read_no_reparse_bytes(
            OBSERVABILITY_POLICY_MODULE,
            "P5 Observability Policy module",
        )
        if observability_policy_bytes != managed_observability_policy_bytes:
            raise GateError(
                "P5 Observability Policy module bytes do not match the managed source"
            )
        if observability_policy_module.get("size") != len(observability_policy_bytes):
            raise GateError(
                "P5 Observability Policy module size metadata is invalid"
            )
        if (
            observability_policy_module.get("sha256")
            != hashlib.sha256(observability_policy_bytes).hexdigest().upper()
        ):
            raise GateError(
                "P5 Observability Policy module hash metadata is invalid"
            )
        observability_policy_output = (
            observability_policy_input + observability_policy_bytes
        )
        if (
            observability_policy_module.get("output_size")
            != len(observability_policy_output)
        ):
            raise GateError(
                "P5 Observability Policy module output size metadata is invalid"
            )
        if (
            observability_policy_module.get("output_sha256")
            != hashlib.sha256(observability_policy_output).hexdigest().upper()
        ):
            raise GateError(
                "P5 Observability Policy module output hash metadata is invalid"
            )
        observability_runtime_overlay = development.get(
            "observability_runtime_overlay"
        )
        if not isinstance(observability_runtime_overlay, dict):
            raise GateError(
                "V80 development build is missing the P5 Observability Runtime overlay"
            )
        if (
            observability_runtime_overlay.get("input_size")
            != len(observability_policy_output)
            or observability_runtime_overlay.get("input_sha256")
            != hashlib.sha256(observability_policy_output).hexdigest().upper()
        ):
            raise GateError(
                "P5 Observability Runtime overlay is not based on the policy output"
            )
        observability_runtime_builder = (
            _load_observability_runtime_overlay_builder()
        )
        rebuilt_observability_runtime = (
            observability_runtime_builder.apply_observability_runtime_overlay(
                observability_policy_output
            )
        )
        for key in ("size", "sha256", "input_size", "input_sha256", "insertions"):
            if (
                observability_runtime_overlay.get(key)
                != rebuilt_observability_runtime.get(key)
            ):
                raise GateError(
                    "P5 Observability Runtime overlay %s metadata is invalid" % key
                )
        diagnostics_snapshot_overlay = development.get(
            "diagnostics_snapshot_overlay"
        )
        if not isinstance(diagnostics_snapshot_overlay, dict):
            raise GateError(
                "V80 development build is missing the P5 Diagnostics Snapshot overlay"
            )
        if (
            diagnostics_snapshot_overlay.get("input_size")
            != observability_runtime_overlay.get("size")
            or diagnostics_snapshot_overlay.get("input_sha256")
            != observability_runtime_overlay.get("sha256")
        ):
            raise GateError(
                "P5 Diagnostics Snapshot overlay is not based on the runtime overlay"
            )
        diagnostics_snapshot_builder = _load_diagnostics_snapshot_overlay_builder()
        rebuilt_diagnostics_snapshot = (
            diagnostics_snapshot_builder.apply_diagnostics_snapshot_overlay(
                rebuilt_observability_runtime["bytes"]
            )
        )
        for key in ("size", "sha256", "input_size", "input_sha256", "insertions"):
            if (
                diagnostics_snapshot_overlay.get(key)
                != rebuilt_diagnostics_snapshot.get(key)
            ):
                raise GateError(
                    "P5 Diagnostics Snapshot overlay %s metadata is invalid" % key
                )
        lifecycle_stability_overlay = development.get(
            "lifecycle_stability_overlay"
        )
        if not isinstance(lifecycle_stability_overlay, dict):
            raise GateError(
                "V80 development build is missing the P5-5A Lifecycle Stability overlay"
            )
        if (
            lifecycle_stability_overlay.get("input_size")
            != diagnostics_snapshot_overlay.get("size")
            or lifecycle_stability_overlay.get("input_sha256")
            != diagnostics_snapshot_overlay.get("sha256")
        ):
            raise GateError(
                "P5-5A Lifecycle Stability overlay is not based on the diagnostics snapshot output"
            )
        lifecycle_stability_builder = _load_lifecycle_stability_overlay_builder()
        rebuilt_lifecycle_stability = (
            lifecycle_stability_builder.apply_lifecycle_stability_overlay(
                rebuilt_diagnostics_snapshot["bytes"]
            )
        )
        for key in ("size", "sha256", "input_size", "input_sha256", "insertions"):
            if (
                lifecycle_stability_overlay.get(key)
                != rebuilt_lifecycle_stability.get(key)
            ):
                raise GateError(
                    "P5-5A Lifecycle Stability overlay %s metadata is invalid" % key
                )
        search_concurrency_ownership_overlay = development.get(
            "search_concurrency_ownership_overlay"
        )
        if not isinstance(search_concurrency_ownership_overlay, dict):
            raise GateError(
                "V80 development build is missing the P5-5D Search Concurrency Ownership overlay"
            )
        if (
            search_concurrency_ownership_overlay.get("input_size")
            != lifecycle_stability_overlay.get("size")
            or search_concurrency_ownership_overlay.get("input_sha256")
            != lifecycle_stability_overlay.get("sha256")
        ):
            raise GateError(
                "P5-5D Search Concurrency Ownership overlay is not based on the lifecycle output"
            )
        search_concurrency_builder = (
            _load_search_concurrency_ownership_overlay_builder()
        )
        rebuilt_search_concurrency = (
            search_concurrency_builder.apply_search_concurrency_ownership_overlay(
                rebuilt_lifecycle_stability["bytes"]
            )
        )
        for key in ("size", "sha256", "input_size", "input_sha256", "insertions"):
            if (
                search_concurrency_ownership_overlay.get(key)
                != rebuilt_search_concurrency.get(key)
            ):
                raise GateError(
                    "P5-5D Search Concurrency Ownership overlay %s metadata is invalid"
                    % key
                )
        playback_concurrency_ownership_overlay = development.get(
            "playback_concurrency_ownership_overlay"
        )
        if not isinstance(playback_concurrency_ownership_overlay, dict):
            raise GateError(
                "V80 development build is missing the P5-5E Playback Concurrency Ownership overlay"
            )
        if (
            playback_concurrency_ownership_overlay.get("input_size")
            != search_concurrency_ownership_overlay.get("size")
            or playback_concurrency_ownership_overlay.get("input_sha256")
            != search_concurrency_ownership_overlay.get("sha256")
        ):
            raise GateError(
                "P5-5E Playback Concurrency Ownership overlay is not based on the search ownership output"
            )
        playback_concurrency_builder = (
            _load_playback_concurrency_ownership_overlay_builder()
        )
        rebuilt_playback_concurrency = (
            playback_concurrency_builder.apply_playback_concurrency_ownership_overlay(
                rebuilt_search_concurrency["bytes"]
            )
        )
        for key in (
                "size", "sha256", "input_size", "input_sha256", "alias_zh",
                "insertions"):
            if (
                playback_concurrency_ownership_overlay.get(key)
                != rebuilt_playback_concurrency.get(key)
            ):
                raise GateError(
                    "P5-5E Playback Concurrency Ownership overlay %s metadata is invalid"
                    % key
                )
        history_concurrency_ownership_overlay = development.get(
            "history_concurrency_ownership_overlay"
        )
        if not isinstance(history_concurrency_ownership_overlay, dict):
            raise GateError(
                "V80 development build is missing the P5-5F History Concurrency Ownership overlay"
            )
        if (
            history_concurrency_ownership_overlay.get("input_size")
            != playback_concurrency_ownership_overlay.get("size")
            or history_concurrency_ownership_overlay.get("input_sha256")
            != playback_concurrency_ownership_overlay.get("sha256")
        ):
            raise GateError(
                "P5-5F History Concurrency Ownership overlay is not based on the playback ownership output"
            )
        history_concurrency_builder = (
            _load_history_concurrency_ownership_overlay_builder()
        )
        rebuilt_history_concurrency = (
            history_concurrency_builder.apply_history_concurrency_ownership_overlay(
                rebuilt_playback_concurrency["bytes"]
            )
        )
        for key in (
                "size", "sha256", "input_size", "input_sha256", "alias_zh",
                "insertions"):
            if (
                history_concurrency_ownership_overlay.get(key)
                != rebuilt_history_concurrency.get(key)
            ):
                raise GateError(
                    "P5-5F History Concurrency Ownership overlay %s metadata is invalid"
                    % key
                )
        resource_output_switch_overlay = development.get(
            "resource_output_switch_overlay"
        )
        if not isinstance(resource_output_switch_overlay, dict):
            raise GateError(
                "V80 development build is missing the P2 private resource output switch overlay"
            )
        if (
            resource_output_switch_overlay.get("input_size")
            != history_concurrency_ownership_overlay.get("size")
            or resource_output_switch_overlay.get("input_sha256")
            != history_concurrency_ownership_overlay.get("sha256")
        ):
            raise GateError(
                "P2 resource output switch overlay is not based on the History ownership output"
            )
        resource_output_switch_builder = (
            _load_resource_output_switch_overlay_builder()
        )
        rebuilt_resource_output_switch = (
            resource_output_switch_builder.apply_resource_output_switch_overlay(
                rebuilt_history_concurrency["bytes"]
            )
        )
        for key in (
                "size", "sha256", "input_size", "input_sha256", "alias_zh",
                "insertions"):
            if (
                resource_output_switch_overlay.get(key)
                != rebuilt_resource_output_switch.get(key)
            ):
                raise GateError(
                    "P2 resource output switch overlay %s metadata is invalid"
                    % key
                )
        if rebuilt_resource_output_switch["bytes"] != development["bytes"]:
            raise GateError(
                "P2 resource output switch overlay bytes do not match the development build"
            )
        if (
            resource_output_switch_overlay.get("size") != development["size"]
            or resource_output_switch_overlay.get("sha256")
            != development["sha256"]
        ):
            raise GateError(
                "P2 resource output switch overlay fingerprint does not match the development build"
            )
        output = development["output"]
        existing = output.is_file()
        if existing and output.read_bytes() != development["bytes"]:
            raise GateError("existing V80 development output differs from the in-memory build")
        return _step(
            "build_contracts", "passed", detail="frozen V70, P2 vendor/shadow/private-output-switch chain, P3 reliability chains, P4 security/response boundaries, and the P5 observability/runtime/snapshot/lifecycle/search/playback/History ownership chain are valid",
            duration_seconds=round(time.monotonic() - started, 3), baseline_sha256=baseline["sha256"],
            baseline_size=baseline["size"], development_sha256=development["sha256"],
            development_size=development["size"], development_output_present=existing,
            vendor_sha256=vendor["sha256"], vendor_closure_sha256=vendor["closure_sha256"],
            vendor_size=vendor["size"], vendor_module_count=len(vendor["modules"]),
            overlay_input_sha256=overlay["input_sha256"],
            overlay_insertion_count=len(overlay["insertions"]),
            history_module_sha256=history_module["sha256"],
            history_module_size=history_module["size"],
            history_overlay_input_sha256=history_overlay["input_sha256"],
            history_overlay_insertion_count=len(history_overlay["insertions"]),
            reliability_module_sha256=reliability_module["sha256"],
            reliability_module_size=reliability_module["size"],
            reliability_module_input_sha256=reliability_module["input_sha256"],
            reliability_overlay_input_sha256=reliability_overlay["input_sha256"],
            reliability_overlay_insertion_count=len(reliability_overlay["insertions"]),
            cache_health_module_sha256=cache_health_module["sha256"],
            cache_health_module_size=cache_health_module["size"],
            cache_health_module_input_sha256=cache_health_module["input_sha256"],
            cache_health_overlay_input_sha256=cache_health_overlay["input_sha256"],
            cache_health_overlay_insertion_count=len(cache_health_overlay["insertions"]),
            background_bulkhead_module_sha256=background_bulkhead_module["sha256"],
            background_bulkhead_module_size=background_bulkhead_module["size"],
            background_bulkhead_module_input_sha256=background_bulkhead_module["input_sha256"],
            background_bulkhead_overlay_input_sha256=background_bulkhead_overlay["input_sha256"],
            background_bulkhead_overlay_insertion_count=len(background_bulkhead_overlay["insertions"]),
            timeout_budget_module_sha256=timeout_budget_module["sha256"],
            timeout_budget_module_size=timeout_budget_module["size"],
            timeout_budget_module_input_sha256=timeout_budget_module["input_sha256"],
            timeout_budget_overlay_input_sha256=timeout_budget_overlay["input_sha256"],
            timeout_budget_overlay_insertion_count=len(timeout_budget_overlay["insertions"]),
            security_policy_module_sha256=security_policy_module["sha256"],
            security_policy_module_size=security_policy_module["size"],
            security_policy_module_input_sha256=security_policy_module["input_sha256"],
            route_security_overlay_sha256=route_security_overlay["sha256"],
            route_security_overlay_input_sha256=route_security_overlay["input_sha256"],
            route_security_overlay_insertion_count=len(route_security_overlay["insertions"]),
            json_shape_policy_module_sha256=json_shape_policy_module["sha256"],
            json_shape_policy_module_size=json_shape_policy_module["size"],
            json_shape_policy_module_input_sha256=json_shape_policy_module["input_sha256"],
            tmdb_json_shape_overlay_sha256=tmdb_json_shape_overlay["sha256"],
            tmdb_json_shape_overlay_input_sha256=tmdb_json_shape_overlay["input_sha256"],
            tmdb_json_shape_overlay_insertion_count=len(tmdb_json_shape_overlay["insertions"]),
            tmdb_response_policy_module_sha256=tmdb_response_policy_module["sha256"],
            tmdb_response_policy_module_size=tmdb_response_policy_module["size"],
            tmdb_response_policy_module_input_sha256=tmdb_response_policy_module["input_sha256"],
            tmdb_response_boundary_overlay_sha256=tmdb_response_boundary_overlay["sha256"],
            tmdb_response_boundary_overlay_input_sha256=tmdb_response_boundary_overlay["input_sha256"],
            tmdb_response_boundary_overlay_insertion_count=len(
                tmdb_response_boundary_overlay["insertions"]
            ),
            diagnostic_redaction_policy_module_sha256=(
                diagnostic_redaction_policy_module["sha256"]
            ),
            diagnostic_redaction_policy_module_size=(
                diagnostic_redaction_policy_module["size"]
            ),
            diagnostic_redaction_policy_module_input_sha256=(
                diagnostic_redaction_policy_module["input_sha256"]
            ),
            diagnostic_redaction_overlay_sha256=diagnostic_redaction_overlay["sha256"],
            diagnostic_redaction_overlay_input_sha256=(
                diagnostic_redaction_overlay["input_sha256"]
            ),
            diagnostic_redaction_overlay_insertion_count=len(
                diagnostic_redaction_overlay["insertions"]
            ),
            douban_response_policy_module_sha256=(
                douban_response_policy_module["sha256"]
            ),
            douban_response_policy_module_size=(
                douban_response_policy_module["size"]
            ),
            douban_response_policy_module_input_sha256=(
                douban_response_policy_module["input_sha256"]
            ),
            douban_response_boundary_overlay_sha256=(
                douban_response_boundary_overlay["sha256"]
            ),
            douban_response_boundary_overlay_input_sha256=(
                douban_response_boundary_overlay["input_sha256"]
            ),
            douban_response_boundary_overlay_insertion_count=len(
                douban_response_boundary_overlay["insertions"]
            ),
            douban_html_response_policy_module_sha256=(
                douban_html_response_policy_module["sha256"]
            ),
            douban_html_response_policy_module_size=(
                douban_html_response_policy_module["size"]
            ),
            douban_html_response_policy_module_input_sha256=(
                douban_html_response_policy_module["input_sha256"]
            ),
            douban_html_response_boundary_overlay_sha256=(
                douban_html_response_boundary_overlay["sha256"]
            ),
            douban_html_response_boundary_overlay_input_sha256=(
                douban_html_response_boundary_overlay["input_sha256"]
            ),
            douban_html_response_boundary_overlay_insertion_count=len(
                douban_html_response_boundary_overlay["insertions"]
            ),
            observability_policy_module_sha256=(
                observability_policy_module["sha256"]
            ),
            observability_policy_module_size=(
                observability_policy_module["size"]
            ),
            observability_policy_module_input_sha256=(
                observability_policy_module["input_sha256"]
            ),
            observability_runtime_overlay_sha256=(
                observability_runtime_overlay["sha256"]
            ),
            observability_runtime_overlay_input_sha256=(
                observability_runtime_overlay["input_sha256"]
            ),
            observability_runtime_overlay_insertion_count=len(
                observability_runtime_overlay["insertions"]
            ),
            diagnostics_snapshot_overlay_sha256=(
                diagnostics_snapshot_overlay["sha256"]
            ),
            diagnostics_snapshot_overlay_input_sha256=(
                diagnostics_snapshot_overlay["input_sha256"]
            ),
            diagnostics_snapshot_overlay_insertion_count=len(
                diagnostics_snapshot_overlay["insertions"]
            ),
            lifecycle_stability_overlay_sha256=(
                lifecycle_stability_overlay["sha256"]
            ),
            lifecycle_stability_overlay_input_sha256=(
                lifecycle_stability_overlay["input_sha256"]
            ),
            lifecycle_stability_overlay_insertion_count=len(
                lifecycle_stability_overlay["insertions"]
            ),
            search_concurrency_ownership_overlay_sha256=(
                search_concurrency_ownership_overlay["sha256"]
            ),
            search_concurrency_ownership_overlay_input_sha256=(
                search_concurrency_ownership_overlay["input_sha256"]
            ),
            search_concurrency_ownership_overlay_insertion_count=len(
                search_concurrency_ownership_overlay["insertions"]
            ),
            search_concurrency_ownership_overlay_insertions=(
                search_concurrency_ownership_overlay["insertions"]
            ),
            playback_concurrency_ownership_overlay_sha256=(
                playback_concurrency_ownership_overlay["sha256"]
            ),
            playback_concurrency_ownership_overlay_input_sha256=(
                playback_concurrency_ownership_overlay["input_sha256"]
            ),
            playback_concurrency_ownership_overlay_insertion_count=len(
                playback_concurrency_ownership_overlay["insertions"]
            ),
            playback_concurrency_ownership_overlay_insertions=(
                playback_concurrency_ownership_overlay["insertions"]
            ),
            history_concurrency_ownership_overlay_sha256=(
                history_concurrency_ownership_overlay["sha256"]
            ),
            history_concurrency_ownership_overlay_input_sha256=(
                history_concurrency_ownership_overlay["input_sha256"]
            ),
            history_concurrency_ownership_overlay_insertion_count=len(
                history_concurrency_ownership_overlay["insertions"]
            ),
            history_concurrency_ownership_overlay_insertions=(
                history_concurrency_ownership_overlay["insertions"]
            ),
            resource_output_switch_overlay_sha256=(
                resource_output_switch_overlay["sha256"]
            ),
            resource_output_switch_overlay_input_sha256=(
                resource_output_switch_overlay["input_sha256"]
            ),
            resource_output_switch_overlay_insertion_count=len(
                resource_output_switch_overlay["insertions"]
            ),
            resource_output_switch_overlay_insertions=(
                resource_output_switch_overlay["insertions"]
            ),
        ), {"baseline": baseline, "development": development}
    except Exception as exc:
        return _step(
            "build_contracts", "failed", detail=str(exc),
            duration_seconds=round(time.monotonic() - started, 3),
        ), None


def _materialize_builds():
    """Load build bytes for dependent checks without rerunning the build gate."""
    build = _load_build_module()
    return {
        "baseline": build.check_release(BASELINE_MANIFEST),
        "development": build.build_release(DEV_MANIFEST),
    }


def _materialized_builds_match_step(source_row, builds):
    if not isinstance(source_row, dict) or not isinstance(builds, dict):
        return False
    baseline = builds.get("baseline") or {}
    development = builds.get("development") or {}
    expected = {
        "baseline_size": baseline.get("size"),
        "baseline_sha256": baseline.get("sha256"),
        "development_size": development.get("size"),
        "development_sha256": development.get("sha256"),
    }
    return all(
        source_row.get(key) == value
        for key, value in expected.items()
    )


def check_behavior_diff(builds, report_dir, runner=None, timeout=DEFAULT_COMMAND_TIMEOUT):
    if builds is None:
        return _step("behavior_diff", "skipped", detail="build contracts are unavailable")
    report_dir = Path(report_dir)
    baseline_path = report_dir / "behavior-baseline.py"
    candidate_path = report_dir / "behavior-candidate.py"
    report_path = report_dir / "behavior-diff.json"
    baseline_bytes = builds["baseline"]["bytes"]
    candidate_bytes = builds["development"]["bytes"]
    baseline_path.write_bytes(baseline_bytes)
    candidate_path.write_bytes(candidate_bytes)
    command = [
        sys.executable, BEHAVIOR_SCRIPT, "--baseline", baseline_path, "--candidate", candidate_path,
        "--fixture", BEHAVIOR_FIXTURE, "--json-out", report_path,
    ]
    row = _run_command("behavior_diff", command, runner=runner, timeout=timeout)
    errors = []
    evidence = {}
    try:
        fixture = json.loads(BEHAVIOR_FIXTURE.read_text(encoding="utf-8"))
        payload = json.loads(report_path.read_text(encoding="utf-8"))
        fixture_hash = hashlib.sha256(BEHAVIOR_FIXTURE.read_bytes()).hexdigest()
        baseline_hash = hashlib.sha256(baseline_bytes).hexdigest()
        candidate_hash = hashlib.sha256(candidate_bytes).hexdigest()
        expected = {case["name"]: (case["domain"], case["expected"]) for case in fixture["cases"]}
        cases = payload.get("cases")
        rows = cases if isinstance(cases, list) else []
        row_names = [row.get("name") for row in rows if isinstance(row, dict)]
        unique_rows = (
            len(rows) == len(row_names)
            and all(isinstance(name, str) for name in row_names)
            and len(row_names) == len(set(row_names))
        )
        cases_valid = unique_rows and set(row_names) == set(expected)
        if cases_valid:
            cases_valid = all(
                row.get("domain") == expected[row["name"]][0]
                and row.get("status") == "equal"
                and row.get("public") == expected[row["name"]][1]
                and row.get("candidate") == expected[row["name"]][1]
                and row.get("difference") is None
                for row in rows
            )
        expected_results = {name: value for name, (_domain, value) in expected.items()}
        summary = {"total": len(expected), "equal": len(expected), "different": 0}
        required_values = {
            "schema_version": payload.get("schema_version") == 1,
            "fixture schema": fixture.get("schema_version") == 2 and payload.get("fixture", {}).get("schema_version") == 2,
            "fixture hash": str(payload.get("fixture", {}).get("sha256", "")).lower() == fixture_hash,
            "baseline hash": str(payload.get("baseline", {}).get("sha256", "")).lower() == baseline_hash,
            "candidate hash": str(payload.get("candidate", {}).get("sha256", "")).lower() == candidate_hash,
            "case evidence": cases_valid,
            "public results": payload.get("public_results") == expected_results,
            "candidate results": payload.get("dev_results") == expected_results,
            "summary": payload.get("summary") == summary,
            "overall": payload.get("overall") == "pass",
            "differences": payload.get("differences") == [],
            "approval": payload.get("approval_required") is False and payload.get("approval") is None,
        }
        errors.extend(name for name, valid in required_values.items() if not valid)
        evidence = {
            "fixture_sha256": fixture_hash, "baseline_sha256": baseline_hash,
            "candidate_sha256": candidate_hash, "summary": payload.get("summary"),
            "approval_required": payload.get("approval_required"), "overall": payload.get("overall"),
        }
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        errors.append("cannot validate behavior report: %s" % exc)
    if row["status"] != "passed":
        errors.insert(0, "behavior command failed")
    if errors:
        row.update(status="failed", detail="behavior comparison evidence failed: %s" % "; ".join(errors))
    else:
        row["detail"] = "Golden behavior comparison recorded zero differences and requires no approval"
    row["evidence"] = _sanitize(evidence)
    return row


def check_macro_a_runtime_differential(
    builds, report_dir, runner=None, timeout=DEFAULT_COMMAND_TIMEOUT
):
    if builds is None:
        return _step(
            "macro_a_runtime_differential",
            "skipped",
            detail="build contracts are unavailable",
        )
    report_path = Path(report_dir) / "macro-a-runtime-differential.json"
    command = [
        sys.executable,
        MACRO_A_DIFFERENTIAL_SCRIPT,
        "--json-out",
        report_path,
    ]
    row = _run_command(
        "macro_a_runtime_differential",
        command,
        runner=runner,
        timeout=timeout,
    )
    errors = []
    evidence = {}
    try:
        payload = json.loads(report_path.read_text(encoding="utf-8"))
        vendor = builds["development"]["vendor"]
        overlay = builds["development"]["overlay"]
        output_switch = builds["development"]["resource_output_switch_overlay"]
        expected_build = {
            "baseline_size": builds["baseline"]["size"],
            "baseline_sha256": builds["baseline"]["sha256"],
            "development_size": builds["development"]["size"],
            "development_sha256": builds["development"]["sha256"],
            "vendor_size": vendor["size"],
            "vendor_sha256": vendor["sha256"],
            "closure_sha256": vendor["closure_sha256"],
            "module_count": len(vendor["modules"]),
            "overlay_input_size": overlay["input_size"],
            "overlay_input_sha256": overlay["input_sha256"],
            "overlay_insertion_count": len(overlay["insertions"]),
            "output_switch_input_size": output_switch["input_size"],
            "output_switch_input_sha256": output_switch["input_sha256"],
            "output_switch_size": output_switch["size"],
            "output_switch_sha256": output_switch["sha256"],
            "output_switch_insertion_count": len(output_switch["insertions"]),
        }
        scenario_differences = payload.get("scenario_differences")
        equal = payload.get("equal")
        different = payload.get("different")
        runtime_errors = payload.get("errors")
        required_values = {
            "fixed evidence": all(
                payload.get(name) == expected
                for name, expected in EXPECTED_MACRO_A_DIFFERENTIAL.items()
            ),
            "current build fingerprints": all(
                payload.get(name) == expected for name, expected in expected_build.items()
            ),
            "scenario coverage": (
                payload.get("scenario_counts") == EXPECTED_MACRO_A_SCENARIO_COUNTS
            ),
            "decision coverage": (
                payload.get("decision_counts") == EXPECTED_MACRO_A_DECISION_COUNTS
            ),
            "report-state coverage": (
                payload.get("report_status_counts")
                == EXPECTED_MACRO_A_REPORT_STATUS_COUNTS
            ),
            "outcome counts": (
                type(equal) is int
                and type(different) is int
                and type(runtime_errors) is int
                and equal + different + runtime_errors
                == EXPECTED_MACRO_A_DIFFERENTIAL["cases"]
                and different
                >= EXPECTED_MACRO_A_SCENARIO_COUNTS["selected_different"]
            ),
            "controlled switch differences": (
                isinstance(scenario_differences, dict)
                and set(scenario_differences) == set(EXPECTED_MACRO_A_SCENARIO_COUNTS)
                and sum(scenario_differences.values()) == different
                and scenario_differences.get("selected_different")
                == EXPECTED_MACRO_A_SCENARIO_COUNTS["selected_different"]
                and all(
                    scenario_differences.get(name) == 0
                    for name in EXPECTED_MACRO_A_ZERO_DIFFERENCE_SCENARIOS
                )
            ),
            "failure detail": payload.get("first_failures") == [],
        }
        errors.extend(name for name, valid in required_values.items() if not valid)
        evidence = {
            "seed": payload.get("seed"),
            "cases": payload.get("cases"),
            "equal": payload.get("equal"),
            "different": payload.get("different"),
            "errors": payload.get("errors"),
            "baseline_sha256": payload.get("baseline_sha256"),
            "development_sha256": payload.get("development_sha256"),
            "vendor_sha256": payload.get("vendor_sha256"),
            "closure_sha256": payload.get("closure_sha256"),
            "module_count": payload.get("module_count"),
            "overlay_input_sha256": payload.get("overlay_input_sha256"),
            "overlay_insertion_count": payload.get("overlay_insertion_count"),
            "output_switch_sha256": payload.get("output_switch_sha256"),
            "output_switch_insertion_count": payload.get("output_switch_insertion_count"),
            "controlled_switch_active": payload.get("controlled_switch_active"),
            "scenario_counts": payload.get("scenario_counts"),
            "scenario_differences": scenario_differences,
            "decision_counts": payload.get("decision_counts"),
            "report_status_counts": payload.get("report_status_counts"),
            "shadow_calls": payload.get("shadow_calls"),
            "disabled_shadow_calls": payload.get("disabled_shadow_calls"),
            "redacted_reports": payload.get("redacted_reports"),
        }
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        errors.append("cannot validate Macro A differential report: %s" % exc)
    if row["status"] != "passed":
        errors.insert(0, "Macro A differential command failed")
    if errors:
        row.update(
            status="failed",
            detail="Macro A runtime differential evidence failed: %s" % "; ".join(errors),
        )
    else:
        row["detail"] = (
            "50,000 controlled background cases preserved state and reported actual layered output"
        )
    row["evidence"] = _sanitize(evidence)
    return row


def check_macro_b_runtime_differential(
    builds, report_dir, runner=None, timeout=DEFAULT_COMMAND_TIMEOUT
):
    if builds is None:
        return _step(
            "macro_b_runtime_differential",
            "skipped",
            detail="build contracts are unavailable",
        )
    report_path = Path(report_dir) / "macro-b-runtime-differential.json"
    command = [
        sys.executable,
        MACRO_B_DIFFERENTIAL_SCRIPT,
        "--json-out",
        report_path,
    ]
    row = _run_command(
        "macro_b_runtime_differential",
        command,
        runner=runner,
        timeout=timeout,
    )
    errors = []
    evidence = {}
    try:
        payload = json.loads(report_path.read_text(encoding="utf-8"))
        vendor = builds["development"]["vendor"]
        overlay = builds["development"]["overlay"]
        output_switch = builds["development"]["resource_output_switch_overlay"]
        expected_build = {
            "baseline_size": builds["baseline"]["size"],
            "baseline_sha256": builds["baseline"]["sha256"],
            "development_size": builds["development"]["size"],
            "development_sha256": builds["development"]["sha256"],
            "vendor_size": vendor["size"],
            "vendor_sha256": vendor["sha256"],
            "closure_sha256": vendor["closure_sha256"],
            "module_count": len(vendor["modules"]),
            "overlay_input_size": overlay["input_size"],
            "overlay_input_sha256": overlay["input_sha256"],
            "overlay_insertion_count": len(overlay["insertions"]),
            "output_switch_input_size": output_switch["input_size"],
            "output_switch_input_sha256": output_switch["input_sha256"],
            "output_switch_size": output_switch["size"],
            "output_switch_sha256": output_switch["sha256"],
            "output_switch_insertion_count": len(output_switch["insertions"]),
        }
        required_values = {
            "fixed evidence": all(
                payload.get(name) == expected
                for name, expected in EXPECTED_MACRO_B_DIFFERENTIAL.items()
            ),
            "current build fingerprints": all(
                payload.get(name) == expected for name, expected in expected_build.items()
            ),
            "scenario coverage": (
                payload.get("scenario_counts") == EXPECTED_MACRO_B_SCENARIO_COUNTS
            ),
            "decision coverage": (
                payload.get("decision_counts") == EXPECTED_MACRO_B_DECISION_COUNTS
            ),
            "report-state coverage": (
                payload.get("report_status_counts")
                == EXPECTED_MACRO_B_REPORT_STATUS_COUNTS
            ),
            "failure detail": payload.get("first_failures") == [],
        }
        errors.extend(name for name, valid in required_values.items() if not valid)
        evidence = {
            "seed": payload.get("seed"),
            "cases": payload.get("cases"),
            "equal": payload.get("equal"),
            "different": payload.get("different"),
            "errors": payload.get("errors"),
            "baseline_sha256": payload.get("baseline_sha256"),
            "development_sha256": payload.get("development_sha256"),
            "vendor_sha256": payload.get("vendor_sha256"),
            "closure_sha256": payload.get("closure_sha256"),
            "module_count": payload.get("module_count"),
            "overlay_input_sha256": payload.get("overlay_input_sha256"),
            "overlay_insertion_count": payload.get("overlay_insertion_count"),
            "output_switch_sha256": payload.get("output_switch_sha256"),
            "output_switch_insertion_count": payload.get("output_switch_insertion_count"),
            "controlled_switch_active": payload.get("controlled_switch_active"),
            "scenario_counts": payload.get("scenario_counts"),
            "decision_counts": payload.get("decision_counts"),
            "report_status_counts": payload.get("report_status_counts"),
            "shadow_calls": payload.get("shadow_calls"),
            "disabled_shadow_calls": payload.get("disabled_shadow_calls"),
            "exception_calls": payload.get("exception_calls"),
            "redacted_reports": payload.get("redacted_reports"),
        }
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        errors.append("cannot validate Macro B differential report: %s" % exc)
    if row["status"] != "passed":
        errors.insert(0, "Macro B differential command failed")
    if errors:
        row.update(
            status="failed",
            detail="Macro B runtime differential evidence failed: %s" % "; ".join(errors),
        )
    else:
        row["detail"] = (
            "50,000 controlled foreground cases preserved V70 output with complete shadow coverage"
        )
    row["evidence"] = _sanitize(evidence)
    return row


def check_chaos_recovery(
    builds, report_dir, runner=None, timeout=DEFAULT_COMMAND_TIMEOUT
):
    if builds is None:
        return _step(
            "chaos_recovery", "skipped",
            detail="build contracts are unavailable",
        )
    report_path = Path(report_dir) / "p3-chaos-recovery.json"
    command = [
        sys.executable, CHAOS_RECOVERY_SCRIPT, "--json-out", report_path,
    ]
    row = _run_command(
        "chaos_recovery", command, runner=runner, timeout=timeout,
    )
    errors = []
    evidence = {}
    try:
        payload = json.loads(report_path.read_text(encoding="utf-8"))
        scenarios = payload.get("scenarios")
        rows = scenarios if isinstance(scenarios, list) else []
        names = [item.get("name") for item in rows if isinstance(item, dict)]
        expected_names = list(EXPECTED_CHAOS_RECOVERY_MS)
        scenario_evidence = (
            len(rows) == len(names)
            and names == expected_names
            and len(names) == len(set(names))
            and all(
                item.get("status") == "passed"
                and item.get("expected_recovery_ms")
                == EXPECTED_CHAOS_RECOVERY_MS[item["name"]]
                and item.get("recovery_ms")
                == EXPECTED_CHAOS_RECOVERY_MS[item["name"]]
                for item in rows
            )
        )
        manifest = json.loads(DEV_MANIFEST.read_text(encoding="utf-8"))
        candidate = payload.get("candidate")
        expected_candidate = {
            "size": builds["development"]["size"],
            "sha256": builds["development"]["sha256"],
            "output": manifest["output"],
        }
        required_values = {
            "schema": payload.get("schema") == "v80-p3-chaos-recovery/1",
            "current candidate": candidate == expected_candidate,
            "virtual clock": payload.get("clock") == "virtual",
            "scenario evidence": scenario_evidence,
            "summary": payload.get("summary") == {
                "total": len(expected_names),
                "passed": len(expected_names),
                "failed": 0,
            },
            "cold/hot separation": payload.get("performance_baseline") == {
                "source": "virtual_fault_fixture",
                "cold_start_ms": 250,
                "hot_cache_ms": 0,
                "note": "Synthetic transport latency; not a real-device benchmark.",
            },
            "P4 boundary": payload.get("oversized_json_scope")
            == "existing_stream_boundary_only_p4_unified_security_pending",
            "no production side effects": (
                payload.get("production_writes") is False
                and payload.get("deployment_attempted") is False
            ),
        }
        errors.extend(name for name, valid in required_values.items() if not valid)
        evidence = {
            "candidate_sha256": (candidate or {}).get("sha256")
            if isinstance(candidate, dict) else None,
            "summary": payload.get("summary"),
            "recovery_ms": {
                item.get("name"): item.get("recovery_ms")
                for item in rows if isinstance(item, dict)
            },
            "performance_baseline": payload.get("performance_baseline"),
            "oversized_json_scope": payload.get("oversized_json_scope"),
            "production_writes": payload.get("production_writes"),
            "deployment_attempted": payload.get("deployment_attempted"),
        }
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        errors.append("cannot validate chaos report: %s" % exc)
    if row["status"] != "passed":
        errors.insert(0, "chaos recovery command failed")
    if errors:
        row.update(
            status="failed",
            detail="P3 chaos recovery evidence failed: %s" % "; ".join(errors),
        )
    else:
        row["detail"] = (
            "13 deterministic faults met their recovery baselines without production side effects"
        )
    row["evidence"] = _sanitize(evidence)
    return row


def check_output_admission_dry_run(
    steps, *, production_writes=False, deployment_attempted=False, decider=None,
    private_release_checker=None,
):
    by_name = {}
    duplicates = []
    for row in steps:
        name = row.get("name") if isinstance(row, dict) else None
        if not isinstance(name, str):
            continue
        if name in by_name:
            duplicates.append(name)
        by_name[name] = row
    if duplicates:
        return _step(
            "output_admission_dry_run", "failed",
            detail="duplicate evidence steps: %s" % sorted(set(duplicates)),
            admit=False, reason="ambiguous_evidence",
        )

    development_steps = (
        "structure_and_dependency", "p2_module_dag", "sensitive_data", "implementation_tree",
        "build_contracts", "behavior_diff", "pytest", "resource_shadow_vendor",
        "upstream_contract", "chaos_recovery",
    )
    public_v70_steps = ("git_v70_tag", "structure_and_dependency", "build_contracts")
    source_steps = development_steps + (
        "macro_a_runtime_differential", "macro_b_runtime_differential",
        "atvp_compatibility", "dual_runtime", "fongmi_category_contract",
        "git_v70_tag",
    )
    missing = sorted(set(name for name in source_steps if name not in by_name))
    if missing:
        return _step(
            "output_admission_dry_run", "failed",
            detail="missing evidence steps: %s" % missing,
            admit=False, reason="missing_evidence",
        )

    def passed(name):
        return by_name[name].get("status") == "passed"

    public_v70_locked = all(passed(name) for name in public_v70_steps)
    evidence = {
        "development_build_verified": all(passed(name) for name in development_steps),
        "candidate_shadow_verified": passed("macro_a_runtime_differential"),
        "layered_shadow_verified": passed("macro_b_runtime_differential"),
        "atvp_compatibility_verified": passed("atvp_compatibility"),
        "dual_runtime_verified": passed("dual_runtime"),
        "fongmi_category_verified": passed("fongmi_category_contract"),
        "public_v70_locked": public_v70_locked,
        "public_output_untouched": (
            public_v70_locked
            and production_writes is False
            and deployment_attempted is False
        ),
    }
    try:
        checker = private_release_checker or _load_private_release_builder().check_private_release
        private_release = checker()
        manifest = private_release["manifest"]
        evidence["private_release_verified"] = True
        evidence["private_release"] = {
            "schema": manifest["schema"],
            "id": manifest["id"],
            "version": manifest["version"],
            "source_sha256": hashlib.sha256(
                private_release["source_bytes"]
            ).hexdigest().upper(),
            "index_sha256": hashlib.sha256(
                private_release["index_bytes"]
            ).hexdigest().upper(),
            "manifest_sha256": hashlib.sha256(
                private_release["manifest_bytes"]
            ).hexdigest().upper(),
        }
    except Exception as exc:
        evidence["private_release_verified"] = False
        return _step(
            "output_admission_dry_run", "failed",
            detail="private V80 release is not deployable: %s" % _redact(exc),
            admit=False, reason="private_release_invalid", evidence=evidence,
        )
    try:
        decide = decider or _load_output_admission_policy()
        decision = decide(
            enabled=True,
            development_build_verified=evidence["development_build_verified"],
            candidate_shadow_verified=evidence["candidate_shadow_verified"],
            layered_shadow_verified=evidence["layered_shadow_verified"],
            atvp_compatibility_verified=evidence["atvp_compatibility_verified"],
            dual_runtime_verified=evidence["dual_runtime_verified"],
            fongmi_category_verified=evidence["fongmi_category_verified"],
            public_v70_locked=evidence["public_v70_locked"],
            public_output_untouched=evidence["public_output_untouched"],
        )
        if (
            not isinstance(decision, dict)
            or tuple(decision) != ("admit", "reason")
            or type(decision.get("admit")) is not bool
            or not isinstance(decision.get("reason"), str)
        ):
            raise GateError("output admission policy returned an invalid decision")
    except Exception as exc:
        return _step(
            "output_admission_dry_run", "failed",
            detail="cannot evaluate output admission: %s" % exc,
            admit=False, reason="evaluation_failed", evidence=evidence,
        )

    if decision["admit"] is True:
        status = "passed"
        detail = "isolated development output is admitted for a future controlled switch"
    else:
        statuses = [by_name[name].get("status") for name in source_steps]
        output_violation = production_writes is not False or deployment_attempted is not False
        status = "failed" if "failed" in statuses or output_violation else "skipped"
        detail = "isolated development output is not admitted: %s" % decision["reason"]
    return _step(
        "output_admission_dry_run", status, detail=detail,
        admit=decision["admit"], reason=decision["reason"], evidence=evidence,
    )


def check_v70_source_lock(
    steps, builds, *, repo_root=REPO_ROOT, baseline_manifest=BASELINE_MANIFEST,
    dev_manifest=DEV_MANIFEST, index_path=None, production_writes=False,
    deployment_attempted=False,
):
    started = time.monotonic()
    repo_root = Path(repo_root).resolve()
    index_path = Path(index_path) if index_path else repo_root / "spiders_v2.json"

    def one_step(name):
        matches = [
            row for row in steps
            if isinstance(row, dict) and row.get("name") == name
        ]
        if len(matches) != 1:
            raise GateError("V70 source-lock evidence requires exactly one %s step" % name)
        return matches[0]

    def load_manifest(path, label):
        payload = json.loads(_read_no_reparse_bytes(path, label).decode("utf-8"))
        if not isinstance(payload, dict):
            raise GateError("%s must be a JSON object" % label)
        return payload

    def output_path(value, label):
        if not isinstance(value, str) or not value or "\\" in value:
            raise GateError("%s output must be a forward-slash relative path" % label)
        relative = Path(value)
        if relative.is_absolute() or ".." in relative.parts:
            raise GateError("%s output escapes the repository" % label)
        absolute = repo_root / relative
        _verify_no_reparse_components(absolute)
        resolved = absolute.resolve()
        _verify_no_reparse_components(absolute)
        try:
            resolved.relative_to(repo_root)
        except ValueError as exc:
            raise GateError("%s output escapes the repository" % label) from exc
        return relative, resolved

    try:
        if builds is None:
            raise GateError("build contracts are unavailable")
        tag_step = one_step("git_v70_tag")
        structure_step = one_step("structure_and_dependency")
        admission_step = one_step("output_admission_dry_run")
        if tag_step.get("status") != "passed":
            raise GateError("frozen v70 tag is not verified")
        if structure_step.get("status") != "passed":
            raise GateError("frozen V70 parts are not verified")
        if admission_step.get("evidence", {}).get("public_output_untouched") is not True:
            raise GateError("output admission did not prove the public output remained untouched")
        if production_writes is not False or deployment_attempted is not False:
            raise GateError("V70 source lock requires zero production writes and deployments")

        baseline = load_manifest(baseline_manifest, "baseline manifest")
        development = load_manifest(dev_manifest, "development manifest")
        expected_size = EXPECTED_MACRO_A_DIFFERENTIAL["baseline_size"]
        expected_sha256 = EXPECTED_MACRO_A_DIFFERENTIAL["baseline_sha256"]
        if (
            baseline.get("contract") != "baseline_v70"
            or baseline.get("version") != 70
            or baseline.get("writable") is not False
            or baseline.get("index_contract") != "required"
            or baseline.get("expected_size") != expected_size
            or baseline.get("expected_sha256") != expected_sha256
        ):
            raise GateError("baseline manifest differs from the frozen V70 source contract")
        if (
            development.get("contract") != "v80_development"
            or development.get("version") != 70
            or development.get("writable") is not True
            or development.get("index_contract") != "none"
        ):
            raise GateError("development manifest is not an isolated V80 contract")

        public_relative, public_path = output_path(baseline.get("output"), "baseline")
        dev_relative, dev_path = output_path(development.get("output"), "development")
        if dev_relative.parts[:2] != ("build", "v80-dev") or dev_path == public_path:
            raise GateError("development output is not isolated from the public V70 source")

        baseline_build = builds["baseline"]
        development_build = builds["development"]
        if Path(baseline_build["output"]).resolve() != public_path:
            raise GateError("baseline build output does not match the public V70 source")
        if Path(development_build["output"]).resolve() != dev_path:
            raise GateError("development build output does not match its isolated manifest")
        public_bytes = _read_no_reparse_bytes(public_path, "public V70 source")
        public_sha256 = hashlib.sha256(public_bytes).hexdigest().upper()
        if (
            public_bytes != baseline_build["bytes"]
            or len(public_bytes) != expected_size
            or public_sha256 != expected_sha256
            or baseline_build["size"] != expected_size
            or baseline_build["sha256"] != expected_sha256
        ):
            raise GateError("public source is not the frozen V70 artifact")

        index = json.loads(_read_no_reparse_bytes(index_path, "public index").decode("utf-8"))
        if not isinstance(index, list):
            raise GateError("public index must be a JSON list")
        expected_row = {
            "id": baseline.get("id"), "file": public_relative.as_posix(),
            "version": 70, "valid": True,
        }
        matching_rows = [
            row for row in index
            if isinstance(row, dict) and row.get("id") == baseline.get("id")
        ]
        if matching_rows != [expected_row]:
            raise GateError("public index does not contain the unique frozen V70 record")

        return _step(
            "v70_source_lock", "passed",
            detail="public V70 source/index remain unchanged and V80 output stays isolated",
            duration_seconds=round(time.monotonic() - started, 3),
            public_size=expected_size, public_sha256=expected_sha256,
            public_version=70, public_file=public_relative.as_posix(),
            development_file=dev_relative.as_posix(),
            source_lock_verified=True, restore_action_planned=False,
        )
    except Exception as exc:
        return _step(
            "v70_source_lock", "failed", detail=str(exc),
            duration_seconds=round(time.monotonic() - started, 3),
            source_lock_verified=False, restore_action_planned=False,
        )


def _pytest_private_paths(report_dir):
    report_dir = Path(report_dir)
    private_root = report_dir / "pytest-private"
    return {
        "root": private_root,
        "config": private_root / "pytest.ini",
        "plugin": private_root / (PYTEST_EVIDENCE_PLUGIN_NAME + ".py"),
        "selection": report_dir / "pytest-selection.json",
        "junit": report_dir / "pytest-junit.xml",
    }


def _prepare_pytest_private_runtime(report_dir):
    paths = _pytest_private_paths(report_dir)
    paths["root"].mkdir(parents=True, exist_ok=True)
    _verify_no_reparse_components(paths["root"])
    paths["config"].write_bytes(PYTEST_PRIVATE_CONFIG_TEXT.encode("utf-8"))
    paths["plugin"].write_bytes(PYTEST_EVIDENCE_PLUGIN_TEXT.encode("utf-8"))
    return paths


def _pytest_command(report_dir, repo_root=REPO_ROOT, selected_nodeids=()):
    paths = _pytest_private_paths(report_dir)
    tests_root = Path(repo_root).resolve() / "tests"
    targets = list(selected_nodeids) if selected_nodeids else ["tests"]
    return [
        sys.executable, "-m", "pytest", "-p", "no:cacheprovider",
        "-p", PYTEST_EVIDENCE_PLUGIN_NAME,
        "-c", paths["config"],
        "--confcutdir", tests_root,
        "-o", "addopts=",
        "--basetemp", report_dir / "pytest",
        "--junitxml", paths["junit"],
        "--durations=30",
    ] + targets


def _pytest_environment(private_root, evidence_path):
    environment = os.environ.copy()
    environment.pop("PYTEST_ADDOPTS", None)
    environment.pop("PYTEST_PLUGINS", None)
    environment["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    private_value = str(Path(private_root).resolve())
    pythonpath = [
        item for item in environment.get("PYTHONPATH", "").split(os.pathsep)
        if item and item != private_value
    ]
    environment["PYTHONPATH"] = os.pathsep.join([private_value] + pythonpath)
    environment[PYTEST_EVIDENCE_ENV] = str(Path(evidence_path).resolve())
    return environment


def _pytest_private_evidence(paths, command, repo_root):
    config = _read_no_reparse_bytes(paths["config"], "pytest private config")
    plugin = _read_no_reparse_bytes(paths["plugin"], "pytest evidence plugin")
    return {
        "private_config_path": str(paths["config"]),
        "private_config_size": len(config),
        "private_config_sha256": hashlib.sha256(config).hexdigest().upper(),
        "evidence_plugin_path": str(paths["plugin"]),
        "evidence_plugin_size": len(plugin),
        "evidence_plugin_sha256": hashlib.sha256(plugin).hexdigest().upper(),
        "confcutdir": str(Path(repo_root).resolve() / "tests"),
        "addopts_override": "",
        "command_sha256": _canonical_sha256([str(item) for item in command]),
    }


def _pytest_junit_evidence(path):
    path = Path(path)
    payload = _read_no_reparse_bytes(path, "pytest JUnit evidence")
    try:
        root = ElementTree.fromstring(payload)
    except ElementTree.ParseError as exc:
        raise GateError("pytest JUnit evidence is not valid XML: %s" % exc) from exc

    def tag_name(element):
        return element.tag.rsplit("}", 1)[-1]

    root_name = tag_name(root)
    if root_name == "testsuite":
        suites = [root]
    elif root_name == "testsuites":
        suites = [child for child in root if tag_name(child) == "testsuite"]
    else:
        raise GateError("pytest JUnit evidence has an unexpected root element")
    if not suites:
        raise GateError("pytest JUnit evidence contains no test suites")

    totals = {name: 0 for name in ("tests", "skipped", "failures", "errors")}
    for suite in suites:
        for name in totals:
            value = suite.get(name)
            try:
                count = int(value)
            except (TypeError, ValueError) as exc:
                raise GateError(
                    "pytest JUnit evidence has an invalid %s count" % name
                ) from exc
            if count < 0:
                raise GateError(
                    "pytest JUnit evidence has an invalid %s count" % name
                )
            totals[name] += count
    return {
        "path": str(path),
        "collected": totals["tests"],
        "executed": totals["tests"] - totals["skipped"],
        "skipped": totals["skipped"],
        "failures": totals["failures"],
        "errors": totals["errors"],
    }


def _pytest_selection_evidence(path):
    path = Path(path)
    payload = _read_no_reparse_bytes(path, "pytest selection evidence")
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GateError("pytest selection evidence is not valid JSON") from exc
    if not isinstance(value, dict) or value.get("schema") != PYTEST_SELECTION_SCHEMA:
        raise GateError("pytest selection evidence schema is invalid")
    counts = {}
    for name in ("collected", "selected", "deselected", "exitstatus"):
        count = value.get(name)
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            raise GateError(
                "pytest selection evidence has an invalid %s count" % name
            )
        counts[name] = count
    if counts["collected"] != counts["selected"] + counts["deselected"]:
        raise GateError("pytest selection evidence counts are inconsistent")
    failed_nodeids = value.get("failed_nodeids", [])
    if (
            not isinstance(failed_nodeids, list)
            or not all(isinstance(item, str) and item for item in failed_nodeids)
            or len(failed_nodeids) != len(set(failed_nodeids))
    ):
        raise GateError("pytest selection evidence has invalid failed node ids")
    return {"path": str(path), **counts, "failed_nodeids": failed_nodeids}


def _run_pytest(
        report_dir, runner=None, timeout=DEFAULT_COMMAND_TIMEOUT,
        repo_root=None, selected_nodeids=(), resume_source=None):
    report_dir = Path(report_dir)
    repo_root = Path(repo_root) if repo_root is not None else REPO_ROOT
    try:
        paths = _prepare_pytest_private_runtime(report_dir)
        for output in (paths["junit"], paths["selection"]):
            if output.exists() or output.is_symlink():
                output.unlink()
        command = _pytest_command(
            report_dir, repo_root=repo_root, selected_nodeids=selected_nodeids,
        )
        isolation = _pytest_private_evidence(paths, command, repo_root)
    except (OSError, GateError) as exc:
        return _step(
            "pytest", "failed",
            detail="cannot prepare isolated pytest evidence: %s" % exc,
        )
    row = _run_command(
        "pytest", command, cwd=repo_root, runner=runner, timeout=timeout,
        env=_pytest_environment(paths["root"], paths["selection"]),
    )
    row["pytest_isolation"] = isolation
    try:
        final_isolation = _pytest_private_evidence(paths, command, repo_root)
    except (OSError, GateError) as exc:
        row.update({
            "status": "failed",
            "detail": _redact("pytest isolation evidence is invalid: %s" % exc),
        })
        return row
    if final_isolation != isolation:
        row.update({
            "status": "failed",
            "detail": "pytest private configuration changed while tests were running",
        })
        return row
    try:
        evidence = _pytest_junit_evidence(paths["junit"])
    except (OSError, GateError) as exc:
        row.update({
            "status": "failed",
            "detail": _redact("pytest JUnit evidence is invalid: %s" % exc),
        })
        return row
    try:
        selection = _pytest_selection_evidence(paths["selection"])
    except (OSError, GateError) as exc:
        row.update({
            "status": "failed",
            "detail": _redact("pytest selection evidence is invalid: %s" % exc),
        })
        return row
    row["pytest_junit"] = evidence
    row["pytest_selection"] = selection
    if selected_nodeids:
        source_step = (
            resume_source["steps"].get("pytest")
            if resume_source is not None else None
        )
        source_status = source_step.get("status") if source_step else None
        source_failed_nodeids = (
            (source_step.get("pytest_selection") or {}).get("failed_nodeids")
            if isinstance(source_step, dict) else None
        )
        if source_status == "failed":
            coverage = (
                "verified" if source_failed_nodeids is not None
                else "legacy-explicit"
            )
            missing = sorted(
                set(source_failed_nodeids or ()) - set(selected_nodeids)
            )
            selection_basis = "source_failures"
        elif source_status == "passed":
            coverage = "changed-input-explicit"
            missing = []
            selection_basis = "changed_inputs"
        else:
            coverage = "invalid-source"
            missing = []
            selection_basis = "invalid_source"
        row["pytest_resume"] = {
            "source_report_sha256": (
                resume_source.get("sha256") if resume_source is not None else None
            ),
            "source_step_sha256": (
                _canonical_sha256(source_step) if source_step is not None else None
            ),
            "source_status": source_status,
            "source_failed_nodeids": source_failed_nodeids,
            "selected_nodeids": list(selected_nodeids),
            "failure_coverage": coverage,
            "selection_basis": selection_basis,
            "missing_source_failures": missing,
            "unselected_source_evidence_reused": True,
        }
        if source_status not in ("failed", "passed"):
            row.update({
                "status": "failed",
                "detail": (
                    "targeted pytest resume requires a passed or failed pytest "
                    "source step"
                ),
            })
            return row
        if missing:
            row.update({
                "status": "failed",
                "detail": "targeted pytest resume omitted source failed node ids",
            })
            return row
    if selection["exitstatus"] != 0:
        row.update({
            "status": "failed",
            "detail": "pytest selection evidence recorded a nonzero exit status",
        })
    elif selection["collected"] <= 0:
        row.update({
            "status": "failed",
            "detail": "pytest selection evidence collected no tests",
        })
    elif selection["selected"] <= 0:
        row.update({
            "status": "failed",
            "detail": "pytest selection evidence selected no tests",
        })
    elif selection["deselected"] > 0:
        row.update({
            "status": "failed",
            "detail": "pytest selection evidence deselected %d tests"
            % selection["deselected"],
        })
    elif evidence["collected"] != selection["selected"]:
        row.update({
            "status": "failed",
            "detail": "pytest JUnit and selection evidence counts do not match",
        })
    elif evidence["collected"] <= 0:
        row.update({
            "status": "failed",
            "detail": "pytest JUnit evidence collected no tests",
        })
    elif evidence["executed"] <= 0:
        row.update({
            "status": "failed",
            "detail": "pytest JUnit evidence executed no tests",
        })
    elif evidence["failures"] or evidence["errors"]:
        row.update({
            "status": "failed",
            "detail": (
                "pytest JUnit evidence reported %d failures and %d errors"
                % (evidence["failures"], evidence["errors"])
            ),
        })
    return row


def build_commands(args, artifact, report_dir):
    commands = []
    if not args.skip_tests:
        commands.append((
            "pytest",
            _pytest_command(
                report_dir, selected_nodeids=_pytest_selected_nodeids(args),
            ),
            True,
        ))
    commands.append((
        "resource_shadow_vendor",
        [sys.executable, RESOURCE_SHADOW_VENDOR_SCRIPT], True,
    ))
    commands.append((
        "atvp_compatibility",
        [sys.executable, COMPAT_TOOLS / "atvp_compat_gate.py", artifact, "--scenario", "direct-play",
         "--runtime", "upstream-1.25-raw", "--json-out", report_dir / "atvp.json"], True,
    ))
    dual = [sys.executable, COMPAT_TOOLS / "verify_dual_runtime.py", artifact]
    if args.fongmi_root:
        dual.extend(["--fongmi-root", args.fongmi_root])
    dual.extend(["--json-out", report_dir / "dual_runtime.json"])
    commands.append(("dual_runtime", dual, True))
    if args.fongmi_root and args.atvp:
        commands.append((
            "fongmi_category_contract",
            [sys.executable, COMPAT_TOOLS / "verify_fongmi_category_contract.py", args.fongmi_root,
             "--atvp", args.atvp, "--json-out", report_dir / "category.json"], True,
        ))
    if args.upstream_root:
        commands.append((
            "upstream_contract",
            [sys.executable, UPSTREAM_CONTRACT_SCRIPT, args.upstream_root,
             "--evidence", UPSTREAM_CONTRACT_EVIDENCE,
             "--json-out", report_dir / "upstream.json"], True,
        ))
    return commands


def _skipped_command_steps(args):
    steps = []
    if args.skip_tests:
        steps.append(_step("pytest", "skipped", detail="disabled by --skip-tests; this run is incomplete"))
    if not (args.fongmi_root and args.atvp):
        steps.append(_step(
            "fongmi_category_contract", "skipped",
            detail="partial mode: both --fongmi-root and --atvp are required for this gate",
        ))
    if not args.upstream_root:
        steps.append(_step(
            "upstream_contract", "skipped",
            detail="partial mode: --upstream-root is required for the complete gate",
        ))
    return steps


def _git_commit(repo_root=REPO_ROOT, runner=None):
    if not (Path(repo_root) / ".git").exists():
        return None
    runner = runner or subprocess.run
    try:
        result = runner(
            ["git", "rev-parse", "HEAD"], cwd=str(repo_root), capture_output=True, text=True,
            encoding="utf-8", errors="replace", check=False, timeout=GIT_COMMAND_TIMEOUT,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return _redact(result.stdout.strip()) if result.returncode == 0 else None


def _is_link_or_reparse(path):
    path = Path(path)
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise GateError("cannot inspect path component %s: %s" % (path, exc)) from exc
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & 0x400)


def _verify_no_reparse_components(path):
    absolute = Path(os.path.abspath(str(path)))
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current = current / part
        if current.exists() or current.is_symlink():
            if _is_link_or_reparse(current):
                raise GateError("path contains a symlink or reparse component: %s" % current)


def _read_no_reparse_bytes(path, label):
    path = Path(os.path.abspath(str(path)))
    _verify_no_reparse_components(path)
    resolved = path.resolve(strict=True)
    _verify_no_reparse_components(path)
    payload = path.read_bytes()
    _verify_no_reparse_components(path)
    if path.resolve(strict=True) != resolved:
        raise GateError("%s path changed while it was being read" % label)
    return payload


def _canonical_sha256(value):
    payload = json.dumps(
        _sanitize(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest().upper()


def _display_input_path(path, repo_root=REPO_ROOT):
    path = Path(os.path.abspath(str(path))).resolve(strict=False)
    try:
        return path.relative_to(Path(repo_root).resolve()).as_posix()
    except ValueError:
        return path.as_posix()


class _InputFingerprinter(object):
    """Builds ephemeral, content-addressed input scopes for one gate run."""

    def __init__(self, repo_root=REPO_ROOT):
        self.repo_root = Path(repo_root).resolve()
        self._file_cache = {}
        self._tree_cache = {}

    def value(self, name, value):
        safe = _sanitize(value)
        return {
            "name": name, "kind": "value", "value": safe,
            "sha256": _canonical_sha256(safe), "valid": True,
        }

    def files(self, name, paths, include_paths=True):
        normalized = tuple(sorted({
            Path(os.path.abspath(str(path))).resolve(strict=False)
            for path in paths
        }, key=lambda path: path.as_posix()))
        cache_key = (normalized, bool(include_paths))
        cached = self._file_cache.get(cache_key)
        if cached is not None:
            result = copy.deepcopy(cached)
            result["name"] = name
            return result

        digest = hashlib.sha256()
        displays = []
        errors = []
        for path in normalized:
            display = _display_input_path(path, self.repo_root)
            displays.append(display)
            try:
                payload = _read_no_reparse_bytes(path, "resume input")
                entry = {
                    "path": display, "size": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest().upper(),
                }
            except (OSError, GateError) as exc:
                entry = {"path": display, "error": _redact(exc)}
                errors.append(entry)
            digest.update(json.dumps(
                entry, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            ).encode("utf-8"))
            digest.update(b"\0")
        if not normalized:
            errors.append({"error": "input scope is empty"})
        result = {
            "name": name, "kind": "file_set", "file_count": len(normalized),
            "sha256": digest.hexdigest().upper(), "valid": not errors,
        }
        if include_paths:
            result["paths"] = displays
        if errors:
            result["errors"] = errors
        self._file_cache[cache_key] = copy.deepcopy(result)
        return result

    def tree(self, name, root):
        root = Path(os.path.abspath(str(root))).resolve(strict=False)
        cache_key = root
        cached = self._tree_cache.get(cache_key)
        if cached is not None:
            result = copy.deepcopy(cached)
            result["name"] = name
            return result
        errors = []
        paths = []
        try:
            _verify_no_reparse_components(root)
            if not root.is_dir():
                raise GateError("input tree is not a directory: %s" % root)
            for path in root.rglob("*"):
                relative = path.relative_to(root)
                if any(part in _FINGERPRINT_EXCLUDED_DIRS for part in relative.parts):
                    continue
                if _is_link_or_reparse(path):
                    raise GateError("input tree contains a symlink or reparse point: %s" % path)
                if path.is_file() and path.suffix.lower() not in (".pyc", ".pyo"):
                    paths.append(path)
        except (OSError, ValueError, GateError) as exc:
            errors.append(_redact(exc))
        files = self.files(name, paths, include_paths=False)
        errors.extend(item.get("error", "unreadable input") for item in files.get("errors", ()))
        result = {
            "name": name, "kind": "tree", "path": _display_input_path(root, self.repo_root),
            "file_count": files["file_count"], "sha256": files["sha256"],
            "valid": files["valid"] and not errors,
        }
        if errors:
            result["errors"] = errors
        self._tree_cache[cache_key] = copy.deepcopy(result)
        return result


def _pytest_plugin_versions():
    entry_points = importlib_metadata.entry_points()
    if hasattr(entry_points, "select"):
        plugins = entry_points.select(group="pytest11")
    else:
        plugins = entry_points.get("pytest11", ())
    rows = []
    for plugin in plugins:
        distribution = getattr(plugin, "dist", None)
        distribution_name = None
        distribution_version = None
        if distribution is not None:
            distribution_name = distribution.metadata.get("Name")
            distribution_version = distribution.version
        rows.append({
            "name": plugin.name,
            "value": plugin.value,
            "distribution": distribution_name,
            "version": distribution_version,
        })
    return sorted(rows, key=lambda row: (
        row["name"], row["distribution"] or "", row["value"],
    ))


def _runtime_input(fingerprinter, include_pytest_plugins=False):
    executable = Path(sys.executable).resolve(strict=False)
    executable_scope = fingerprinter.files("python_executable", (executable,))
    package_versions = {}
    for distribution in (
            "pytest", "requests", "lxml", "beautifulsoup4", "pycryptodome"):
        try:
            package_versions[distribution] = importlib_metadata.version(distribution)
        except importlib_metadata.PackageNotFoundError:
            package_versions[distribution] = None
    return fingerprinter.value("python_runtime", {
        "executable": executable.as_posix(),
        "executable_sha256": executable_scope.get("sha256"),
        "version": sys.version,
        "implementation": getattr(sys.implementation, "name", None),
        "cache_tag": getattr(sys.implementation, "cache_tag", None),
        "platform": sys.platform,
        "os_name": os.name,
        "pythonpath": os.environ.get("PYTHONPATH", ""),
        "pytest_addopts": os.environ.get("PYTEST_ADDOPTS", ""),
        "pytest_plugins": os.environ.get("PYTEST_PLUGINS", ""),
        "pytest_disable_plugin_autoload": os.environ.get(
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD", "",
        ),
        "pytest11_plugins": (
            _pytest_plugin_versions() if include_pytest_plugins else []
        ),
        "package_versions": package_versions,
    })


def _structure_input_paths():
    expected = [SOURCE_DIR / relative for relative in EXPECTED_CHUNKS]
    actual = list((SOURCE_DIR / "parts").glob("*.pyinc"))
    return tuple(
        [BASELINE_MANIFEST, DEV_MANIFEST, DEPENDENCY_CONTRACT]
        + sorted(set(expected + actual), key=lambda path: path.as_posix())
    )


def _p2_input_paths():
    expected = [SOURCE_DIR / name for name in sorted(P2_MODULE_DAG)]
    actual = list(SOURCE_DIR.glob("resource_*.py"))
    paths = expected + actual + [
        BASELINE_MANIFEST, DEV_MANIFEST,
        SOURCE_DIR / "resource_candidate_shadow_vendor.json",
    ]
    return tuple(sorted(set(paths), key=lambda path: path.as_posix()))


def _build_input_paths():
    source_paths = [
        path for path in SOURCE_DIR.rglob("*")
        if path.is_file() and path.suffix.lower() in (".json", ".py", ".pyinc")
    ]
    tool_paths = [
        path for path in (REPO_ROOT / "tools").glob("build_v80_*.py")
        if path.is_file()
    ]
    return tuple(
        source_paths + tool_paths
        + [BUILD_SCRIPT, _public_v70_path(), _development_output_path()]
    )


def _pytest_input_paths(repo_root=REPO_ROOT):
    repo_root = Path(repo_root).resolve()
    test_root = repo_root / "tests"
    paths = []
    for path in implementation_tree_paths(repo_root):
        try:
            in_tests = path.resolve(strict=False).is_relative_to(test_root)
        except AttributeError:
            try:
                path.resolve(strict=False).relative_to(test_root)
                in_tests = True
            except ValueError:
                in_tests = False
        if path.suffix.lower() == ".md" and not in_tests:
            continue
        if path.name in (".gitattributes", ".gitignore"):
            continue
        paths.append(path)
    return tuple(paths)


def _normalized_argument_path(path):
    if path is None:
        return None
    return Path(os.path.abspath(str(path))).resolve(strict=False).as_posix()


def _git_repository_state_input(fingerprinter, name, root):
    root = Path(os.path.abspath(str(root))).resolve(strict=False)
    commands = (
        ("head", ("rev-parse", "HEAD")),
        ("exact_tag", ("describe", "--tags", "--exact-match")),
        ("worktree_status", ("status", "--porcelain=v1", "--untracked-files=all")),
        ("tag_1450_commit", ("rev-parse", "1.45.0^{commit}")),
        ("tag_1451_commit", ("rev-parse", "1.45.1^{commit}")),
        ("tag_1461_commit", ("rev-parse", "1.46.1^{commit}")),
        ("tag_1471_commit", ("rev-parse", "1.47.1^{commit}")),
        ("tag_1480_commit", ("rev-parse", "1.48.0^{commit}")),
        ("tag_1500_commit", ("rev-parse", "1.50.0^{commit}")),
        ("delta_1450_1451", ("diff", "--name-only", "1.45.0..1.45.1")),
        ("delta_1451_1461", ("diff", "--name-only", "1.45.1..1.46.1")),
        ("delta_1461_1471", ("diff", "--name-only", "1.46.1..1.47.1")),
        ("delta_1471_1480", ("diff", "--name-only", "1.47.1..1.48.0")),
        ("delta_1480_1500", ("diff", "--name-only", "1.48.0..1.50.0")),
    )
    values = {"root": root.as_posix()}
    errors = []
    for key, arguments in commands:
        try:
            result = subprocess.run(
                ["git"] + list(arguments), cwd=str(root), capture_output=True,
                text=True, encoding="utf-8", errors="replace", check=False,
                timeout=GIT_COMMAND_TIMEOUT,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            values[key] = None
            errors.append("%s: %s" % (key, _redact(exc)))
            continue
        values[key] = result.stdout.strip() if result.returncode == 0 else None
        if result.returncode != 0:
            errors.append("%s: git exited with %s" % (key, result.returncode))
    scope = fingerprinter.value(name, values)
    scope["valid"] = not errors
    if errors:
        scope["errors"] = errors
    return scope


def _public_v70_path():
    try:
        manifest = json.loads(BASELINE_MANIFEST.read_text(encoding="utf-8"))
        output = manifest.get("output") if isinstance(manifest, dict) else None
        if isinstance(output, str) and output and not Path(output).is_absolute():
            return REPO_ROOT / output
    except (OSError, json.JSONDecodeError):
        pass
    return REPO_ROOT / "py" / "豆瓣TMDB追更单入口.py"


def _development_output_path():
    try:
        manifest = json.loads(DEV_MANIFEST.read_text(encoding="utf-8"))
        output = manifest.get("output") if isinstance(manifest, dict) else None
        if isinstance(output, str) and output and not Path(output).is_absolute():
            return REPO_ROOT / output
    except (OSError, json.JSONDecodeError):
        pass
    return REPO_ROOT / "build" / "v80-dev" / "豆瓣TMDB追更单入口.py"


def _step_input_scopes(name, args, fingerprinter):
    scopes = [fingerprinter.value(
        "step_gate_contract", STEP_GATE_CONTRACTS[name],
    )]
    command_steps = {
        "behavior_diff", "macro_a_runtime_differential",
        "macro_b_runtime_differential", "chaos_recovery", "pytest",
        "resource_shadow_vendor", "atvp_compatibility", "dual_runtime",
        "fongmi_category_contract", "upstream_contract",
    }
    if name == "git_v70_tag":
        scopes.append(fingerprinter.value("v70_tag_contract", EXPECTED_V70_TAG))
    elif name == "structure_and_dependency":
        scopes.append(fingerprinter.files("p1_structure", _structure_input_paths()))
    elif name == "p2_module_dag":
        scopes.append(fingerprinter.files("p2_modules", _p2_input_paths()))
    elif name == "sensitive_data":
        scopes.append(fingerprinter.files(
            "managed_sensitive_inputs", managed_sensitive_paths(REPO_ROOT),
        ))
    elif name == "implementation_tree":
        scopes.append(fingerprinter.files(
            "implementation_tree_inputs", implementation_tree_paths(REPO_ROOT),
        ))
    elif name == "pytest":
        scopes.append(fingerprinter.files(
            "pytest_code_test_inputs", _pytest_input_paths(REPO_ROOT),
        ))
        if LOCAL_TEST_DEPS.is_dir():
            scopes.append(fingerprinter.tree(
                "pytest_local_test_deps", LOCAL_TEST_DEPS,
            ))
    elif name == "build_contracts":
        scopes.append(fingerprinter.files("build_inputs", _build_input_paths()))
    elif name == "behavior_diff":
        scopes.append(fingerprinter.files(
            "behavior_inputs", (BEHAVIOR_SCRIPT, BEHAVIOR_FIXTURE),
        ))
    elif name == "macro_a_runtime_differential":
        scopes.append(fingerprinter.files("macro_a_tool", (MACRO_A_DIFFERENTIAL_SCRIPT,)))
    elif name == "macro_b_runtime_differential":
        scopes.append(fingerprinter.files("macro_b_tool", (MACRO_B_DIFFERENTIAL_SCRIPT,)))
    elif name == "chaos_recovery":
        scopes.append(fingerprinter.files(
            "chaos_inputs", (CHAOS_RECOVERY_SCRIPT, DEV_MANIFEST),
        ))
    elif name == "resource_shadow_vendor":
        scopes.append(fingerprinter.files(
            "resource_vendor_inputs", (RESOURCE_SHADOW_VENDOR_SCRIPT,) + _p2_input_paths(),
        ))
    elif name in ("atvp_compatibility", "dual_runtime", "fongmi_category_contract"):
        scopes.append(fingerprinter.tree("compatibility_tools", COMPAT_TOOLS))
    elif name == "upstream_contract":
        scopes.append(fingerprinter.files(
            "upstream_verifier",
            (
                UPSTREAM_CONTRACT_SCRIPT,
                REPO_ROOT / "tools" / "verify_alist_tvbox_1500_contract.py",
                REPO_ROOT / "tools" / "verify_alist_tvbox_1480_contract.py",
                REPO_ROOT / "tools" / "verify_alist_tvbox_1471_contract.py",
                REPO_ROOT / "tools" / "verify_alist_tvbox_1461_contract.py",
                REPO_ROOT / "tools" / "verify_alist_tvbox_1451_contract.py",
            ),
        ))
        scopes.append(fingerprinter.files(
            "upstream_release_evidence", (UPSTREAM_CONTRACT_EVIDENCE,),
        ))
    elif name == "output_admission_dry_run":
        scopes.append(fingerprinter.files("output_admission_policy", (OUTPUT_ADMISSION_POLICY,)))
        scopes.append(fingerprinter.files(
            "private_release_inputs",
            (
                PRIVATE_RELEASE_SCRIPT,
                PRIVATE_RELEASE_MANIFEST,
                PRIVATE_RELEASE_INDEX,
                PRIVATE_RELEASE_SOURCE,
                CONTROLLED_SWITCH_EVIDENCE,
            ),
        ))
    elif name == "v70_source_lock":
        scopes.append(fingerprinter.files(
            "v70_public_inputs",
            (BASELINE_MANIFEST, DEV_MANIFEST, REPO_ROOT / "spiders_v2.json", _public_v70_path()),
        ))

    if name in command_steps:
        scopes.append(_runtime_input(
            fingerprinter, include_pytest_plugins=name == "pytest",
        ))
    if name == "pytest":
        scopes.append(fingerprinter.value("command_options", {
            "skip_tests": bool(args.skip_tests),
            "selected_nodeids": list(_pytest_selected_nodeids(args)),
        }))
        scopes.append(fingerprinter.files(
            "pytest_public_inputs",
            (REPO_ROOT / "spiders_v2.json", _public_v70_path()),
        ))
    if name == "atvp_compatibility":
        scopes.append(fingerprinter.value("atvp_options", {
            "scenario": "direct-play", "runtime": "upstream-1.25-raw",
        }))
    if name == "dual_runtime":
        scopes.append(fingerprinter.value("fongmi_root", _normalized_argument_path(args.fongmi_root)))
        if args.fongmi_root is not None:
            root = Path(args.fongmi_root)
            requirement_paths = tuple(
                root / item for item in _FONGMI_REQUIREMENTS
                if (root / item).exists()
            )
            scopes.append(fingerprinter.files(
                "fongmi_requirements", requirement_paths,
            ))
    if name == "fongmi_category_contract":
        scopes.append(fingerprinter.value("fongmi_root", _normalized_argument_path(args.fongmi_root)))
        if args.fongmi_root is not None:
            root = Path(args.fongmi_root)
            scopes.append(fingerprinter.files(
                "fongmi_category_sources",
                tuple(root / item for item in _FONGMI_CATEGORY_SOURCES),
            ))
        scopes.append(fingerprinter.value("atvp_path", _normalized_argument_path(args.atvp)))
        if args.atvp is not None:
            scopes.append(fingerprinter.files("atvp_source", (args.atvp,)))
    if name == "upstream_contract":
        scopes.append(fingerprinter.value("upstream_root", _normalized_argument_path(args.upstream_root)))
        if args.upstream_root is not None:
            scopes.append(fingerprinter.tree("upstream_source", args.upstream_root))
            scopes.append(_git_repository_state_input(
                fingerprinter, "upstream_git_state", args.upstream_root,
            ))
    if name in ("output_admission_dry_run", "v70_source_lock"):
        scopes.append(fingerprinter.value("side_effect_contract", {
            "production_writes": False, "deployment_attempted": False,
        }))
    return scopes


_STEP_RUNTIME_KEYS = frozenset((
    "duration_seconds", "execution", "input_dependencies", "input_manifest",
    "input_schema", "input_sha256", "resume_blocked_reason", "reuse_reason",
    "resume_invalidation", "reused_from", "source_duration_seconds", "stable_after_commands",
    "final_file_count", "final_input_sha256", "final_tree_sha256",
    "input_stable_after_gate", "started_input_sha256",
))


def _step_semantic_sha256(row):
    payload = {
        key: value for key, value in row.items()
        if key not in _STEP_RUNTIME_KEYS
    }
    if row.get("name") == "implementation_tree":
        payload.pop("detail", None)
    return _canonical_sha256(payload)


def _step_input_record(name, args, steps, fingerprinter):
    by_name = {
        row.get("name"): row for row in steps
        if isinstance(row, dict) and isinstance(row.get("name"), str)
    }
    dependencies = []
    valid = True
    for dependency in STEP_DEPENDENCIES[name]:
        row = by_name.get(dependency)
        if row is None:
            dependencies.append({"name": dependency, "status": "missing"})
            valid = False
            continue
        dependencies.append({
            "name": dependency,
            "status": row.get("status"),
            "input_sha256": row.get("input_sha256"),
            "result_sha256": _step_semantic_sha256(row),
        })
        if row.get("status") != "passed" or not row.get("input_sha256"):
            valid = False
    scopes = _step_input_scopes(name, args, fingerprinter)
    if not all(scope.get("valid") is True for scope in scopes):
        valid = False
    descriptor = {
        "schema": STEP_INPUT_SCHEMA, "step": name,
        "inputs": scopes, "dependencies": dependencies,
    }
    return {
        "input_schema": STEP_INPUT_SCHEMA,
        "input_manifest": scopes,
        "input_dependencies": dependencies,
        "input_sha256": _canonical_sha256(descriptor),
        "input_valid": valid,
    }


def _source_step_input_sha256(row):
    descriptor = {
        "schema": row.get("input_schema"), "step": row.get("name"),
        "inputs": row.get("input_manifest"),
        "dependencies": row.get("input_dependencies"),
    }
    return _canonical_sha256(descriptor)


_RESUME_IGNORED_SCOPE_NAMES = frozenset(("gate_tool", "step_gate_contract"))


def _resume_normalized_input_sha256(row, by_name, memo=None):
    """Compare step-local evidence while allowing the old global gate scope to migrate."""
    if memo is None:
        memo = {}
    name = row.get("name")
    if name in memo:
        return memo[name]
    scopes = [
        scope for scope in row.get("input_manifest", ())
        if scope.get("name") not in _RESUME_IGNORED_SCOPE_NAMES
    ]
    dependencies = []
    for dependency in row.get("input_dependencies", ()):
        dependency_name = dependency.get("name")
        dependency_row = by_name.get(dependency_name)
        dependencies.append({
            "name": dependency_name,
            "status": dependency.get("status"),
            "input_sha256": (
                _resume_normalized_input_sha256(dependency_row, by_name, memo)
                if dependency_row is not None else None
            ),
            "result_sha256": dependency.get("result_sha256"),
        })
    descriptor = {
        "schema": row.get("input_schema"),
        "step": name,
        "inputs": scopes,
        "dependencies": dependencies,
    }
    digest = _canonical_sha256(descriptor)
    memo[name] = digest
    return digest


def _resume_scope_changes(source_row, current_row):
    source_scopes = {
        scope.get("name"): scope for scope in source_row.get("input_manifest", ())
        if isinstance(scope, dict)
    }
    current_scopes = {
        scope.get("name"): scope for scope in current_row.get("input_manifest", ())
        if isinstance(scope, dict)
    }
    changes = []
    for name in sorted(set(source_scopes) | set(current_scopes)):
        if name in _RESUME_IGNORED_SCOPE_NAMES:
            continue
        source_scope = source_scopes.get(name)
        current_scope = current_scopes.get(name)
        if source_scope == current_scope:
            continue
        changes.append({
            "name": name,
            "source_sha256": source_scope.get("sha256") if source_scope else None,
            "current_sha256": current_scope.get("sha256") if current_scope else None,
            "source_valid": source_scope.get("valid") if source_scope else None,
            "current_valid": current_scope.get("valid") if current_scope else None,
        })
    return changes


def _resume_dependency_changes(name, source, current_row, resume_source, current_by_name):
    source_by_name = resume_source["steps"]
    source_memo = {}
    current_memo = {}
    changes = []
    for dependency_name in STEP_DEPENDENCIES[name]:
        source_dependency = source_by_name.get(dependency_name)
        current_dependency = current_by_name.get(dependency_name)
        source_normalized = (
            _resume_normalized_input_sha256(source_dependency, source_by_name, source_memo)
            if source_dependency is not None else None
        )
        current_normalized = (
            _resume_normalized_input_sha256(current_dependency, current_by_name, current_memo)
            if current_dependency is not None else None
        )
        source_result = (
            _step_semantic_sha256(source_dependency)
            if source_dependency is not None else None
        )
        current_result = (
            _step_semantic_sha256(current_dependency)
            if current_dependency is not None else None
        )
        if (
                source_dependency is None
                or current_dependency is None
                or source_dependency.get("status") != current_dependency.get("status")
                or source_normalized != current_normalized
                or source_result != current_result
        ):
            changes.append({
                "name": dependency_name,
                "source_status": source_dependency.get("status") if source_dependency else None,
                "current_status": current_dependency.get("status") if current_dependency else None,
                "source_input_sha256": source_normalized,
                "current_input_sha256": current_normalized,
                "source_result_sha256": source_result,
                "current_result_sha256": current_result,
            })
    return changes


def _resume_invalidation_evidence(
        name, input_record, resume_source, reason, current_steps,
):
    if resume_source is None:
        return None
    source = resume_source["steps"].get(name)
    current_row = {
        "name": name,
        "input_schema": input_record.get("input_schema"),
        "input_manifest": input_record.get("input_manifest", ()),
        "input_dependencies": input_record.get("input_dependencies", ()),
    }
    current_by_name = {
        row.get("name"): row for row in current_steps
        if isinstance(row, dict) and isinstance(row.get("name"), str)
    }
    current_by_name[name] = current_row
    source_by_name = resume_source["steps"]
    source_normalized = (
        _resume_normalized_input_sha256(source, source_by_name)
        if source is not None else None
    )
    current_normalized = _resume_normalized_input_sha256(current_row, current_by_name)
    scope_changes = _resume_scope_changes(source or {}, current_row)
    dependency_changes = (
        _resume_dependency_changes(
            name, source, current_row, resume_source, current_by_name,
        )
        if source is not None else []
    )
    return {
        "reason": _redact(reason),
        "source_status": source.get("status") if source else None,
        "source_input_sha256": source.get("input_sha256") if source else None,
        "current_input_sha256": input_record.get("input_sha256"),
        "source_normalized_input_sha256": source_normalized,
        "current_normalized_input_sha256": current_normalized,
        "direct_failure": source is None or source.get("status") != "passed",
        "changed_scopes": scope_changes,
        "changed_dependencies": dependency_changes,
        "propagation_paths": [],
    }


def _load_resume_source(path, report_path, expected_sha256=None):
    if path is None:
        return None
    source_path = Path(os.path.abspath(str(path)))
    target_path = Path(os.path.abspath(str(report_path)))
    _verify_no_reparse_components(source_path)
    if source_path.resolve(strict=False) == target_path.resolve(strict=False):
        raise GateError("--resume-from cannot be the same file as --report")
    payload_bytes = _read_no_reparse_bytes(source_path, "resume source report")
    if len(payload_bytes) > MAX_RESUME_REPORT_BYTES:
        raise GateError("resume source report exceeds the size limit")
    try:
        report = json.loads(payload_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GateError("resume source report is not valid UTF-8 JSON: %s" % exc) from exc
    if not isinstance(report, dict) or report.get("schema") != REPORT_SCHEMA:
        raise GateError("resume source report schema is invalid")
    rows = report.get("steps")
    if not isinstance(rows, list):
        raise GateError("resume source report steps must be a list")
    names = [row.get("name") for row in rows if isinstance(row, dict)]
    if len(names) != len(rows) or len(names) != len(set(names)):
        raise GateError("resume source report contains invalid or duplicate step names")
    if set(names) != set(STEP_ORDER):
        raise GateError("resume source report does not contain the fixed 18-step catalog")
    by_name = {row["name"]: row for row in rows}
    for name, row in by_name.items():
        input_sha256 = row.get("input_sha256")
        if input_sha256 is None:
            continue
        if (
                not isinstance(input_sha256, str)
                or not re.fullmatch(r"[0-9A-F]{64}", input_sha256)
                or row.get("input_schema") != STEP_INPUT_SCHEMA
                or row.get("execution") not in ("executed", "reused")
                or row.get("status") not in ("passed", "failed", "skipped")
                or not isinstance(row.get("required"), bool)
                or _source_step_input_sha256(row) != input_sha256):
            raise GateError("resume source step input evidence is invalid: %s" % name)
        dependency_rows = row.get("input_dependencies")
        if not isinstance(dependency_rows, list):
            raise GateError("resume source step dependencies are invalid: %s" % name)
        if not all(isinstance(item, dict) for item in dependency_rows):
            raise GateError("resume source step dependencies are invalid: %s" % name)
        dependency_names = [item.get("name") for item in dependency_rows]
        if dependency_names != list(STEP_DEPENDENCIES[name]):
            raise GateError("resume source step dependency catalog is invalid: %s" % name)
        for dependency in dependency_rows:
            source_dependency = by_name.get(dependency["name"])
            if source_dependency is None:
                raise GateError("resume source dependency is missing: %s" % dependency["name"])
            if dependency.get("input_sha256") != source_dependency.get("input_sha256"):
                raise GateError("resume source dependency input evidence is inconsistent: %s" % name)
            if dependency.get("result_sha256") != _step_semantic_sha256(source_dependency):
                raise GateError("resume source dependency result evidence is inconsistent: %s" % name)
    actual_sha256 = hashlib.sha256(payload_bytes).hexdigest().upper()
    if expected_sha256 is not None and actual_sha256 != expected_sha256.upper():
        raise GateError("resume source report SHA256 does not match --resume-source-sha256")
    return {
        "path": source_path.resolve(strict=True),
        "bytes": payload_bytes,
        "sha256": actual_sha256,
        "sha256_verified": expected_sha256 is not None,
        "report": report,
        "steps": by_name,
    }


def _resume_decision(name, input_record, resume_source, current_steps=None):
    if resume_source is None:
        return None, None
    source = resume_source["steps"].get(name)
    if source is None:
        return None, "source step is missing"
    if source.get("status") != "passed":
        return None, "source step did not pass"
    if source.get("input_sha256") is None:
        return None, "source step predates content-addressed resume evidence"
    if resume_source.get("sha256_verified") is not True:
        return None, "source report SHA256 was not verified"
    if input_record.get("input_valid") is not True:
        return None, "current input or dependency evidence is incomplete"
    if source.get("input_sha256") != input_record.get("input_sha256"):
        if current_steps is not None:
            current_row = {
                "name": name,
                "input_schema": input_record.get("input_schema"),
                "input_manifest": input_record.get("input_manifest", ()),
                "input_dependencies": input_record.get("input_dependencies", ()),
            }
            current_by_name = {
                row.get("name"): row for row in current_steps
                if isinstance(row, dict) and isinstance(row.get("name"), str)
            }
            current_by_name[name] = current_row
            source_normalized = _resume_normalized_input_sha256(
                source, resume_source["steps"],
            )
            current_normalized = _resume_normalized_input_sha256(
                current_row, current_by_name,
            )
            if source_normalized == current_normalized:
                return source, (
                    "legacy gate-tool scope changed; step-local inputs and dependency "
                    "result evidence are unchanged"
                )
        return None, "current input or dependency fingerprint changed"
    return source, None


def _annotate_step(
        row, name, input_record, execution, blocked_reason=None,
        resume_source=None, resume_invalidation=None,
):
    row = copy.deepcopy(row)
    if row.get("name") != name:
        row = _step(
            name, "failed",
            detail="step returned unexpected name: %s" % row.get("name"),
        )
    invalid_scopes = [
        scope.get("name", "unknown")
        for scope in input_record.get("input_manifest", ())
        if scope.get("valid") is not True
    ]
    failed_dependencies = [
        dependency.get("name", "unknown")
        for dependency in input_record.get("input_dependencies", ())
        if dependency.get("status") in ("failed", "missing")
    ]
    if row.get("status") == "passed" and (invalid_scopes or failed_dependencies):
        incomplete = invalid_scopes + failed_dependencies
        row = _step(
            name, "failed", required=row.get("required", True),
            detail="step input evidence is incomplete: %s" % ", ".join(incomplete),
        )
    row.update({
        "execution": execution,
        "input_schema": input_record["input_schema"],
        "input_manifest": input_record["input_manifest"],
        "input_dependencies": input_record["input_dependencies"],
        "input_sha256": input_record["input_sha256"],
    })
    if blocked_reason is not None and resume_source is not None:
        row["resume_blocked_reason"] = _redact(blocked_reason)
    if resume_invalidation is not None:
        row["resume_invalidation"] = resume_invalidation
    return row


def _reuse_step(source, name, input_record, resume_source, reuse_reason=None):
    row = copy.deepcopy(source)
    original_duration = row.get("source_duration_seconds", row.get("duration_seconds"))
    for key in (
            "execution", "input_schema", "input_manifest", "input_dependencies",
            "input_sha256", "resume_blocked_reason", "reuse_reason", "reused_from",
            "source_duration_seconds"):
        row.pop(key, None)
    row["duration_seconds"] = 0.0
    if original_duration is not None:
        row["source_duration_seconds"] = original_duration
    row = _annotate_step(row, name, input_record, "reused")
    row["reuse_reason"] = reuse_reason or (
        "passed evidence and dependency fingerprints are unchanged"
    )
    row["reused_from"] = {
        "report_sha256": resume_source["sha256"],
        "step_sha256": _canonical_sha256(source),
        "generated_at": resume_source["report"].get("generated_at"),
    }
    return row


def _attach_resume_propagation_paths(steps):
    by_name = {row.get("name"): row for row in steps}
    memo = {}

    def paths_for(name):
        if name in memo:
            return memo[name]
        row = by_name.get(name)
        if row is None:
            return []
        paths = []
        invalidation = row.get("resume_invalidation")
        if isinstance(invalidation, dict) and (
                invalidation.get("direct_failure")
                or invalidation.get("changed_scopes")
        ):
            paths.append([name])
        for dependency in STEP_DEPENDENCIES.get(name, ()):
            for path in paths_for(dependency):
                paths.append(path + [name])
        unique = []
        seen = set()
        for path in paths:
            key = tuple(path)
            if key not in seen:
                seen.add(key)
                unique.append(path)
        memo[name] = unique
        return unique

    for row in steps:
        invalidation = row.get("resume_invalidation")
        if isinstance(invalidation, dict):
            invalidation["propagation_paths"] = paths_for(row["name"])


def _assert_resume_source_unchanged(resume_source):
    if resume_source is None:
        return
    current = _read_no_reparse_bytes(resume_source["path"], "resume source report")
    if current != resume_source["bytes"]:
        raise GateError("resume source report changed while the gate was running")


def _verify_step_inputs_stable(steps, args):
    fingerprinter = _InputFingerprinter(REPO_ROOT)
    for row in steps:
        name = row["name"]
        current = _step_input_record(name, args, steps, fingerprinter)
        if current["input_sha256"] == row.get("input_sha256"):
            continue
        started_input_sha256 = row.get("input_sha256")
        row.update({
            "status": "failed",
            "detail": "step inputs or dependency evidence changed while the gate was running",
            "started_input_sha256": started_input_sha256,
            "final_input_sha256": current["input_sha256"],
            "input_stable_after_gate": False,
            "input_schema": current["input_schema"],
            "input_manifest": current["input_manifest"],
            "input_dependencies": current["input_dependencies"],
            "input_sha256": current["input_sha256"],
        })


def _assert_report_path_allowed(path, repo_root=REPO_ROOT):
    path = Path(os.path.abspath(str(path)))
    _verify_no_reparse_components(path)
    resolved = path.resolve(strict=False)
    repo_root = Path(repo_root).resolve()
    protected_files = {
        (repo_root / "py" / "豆瓣TMDB追更单入口.py").resolve(strict=False),
        (repo_root / "spiders_v2.json").resolve(strict=False),
    }
    protected_files.update(item.resolve(strict=False) for item in managed_sensitive_paths(repo_root))
    protected_roots = [
        (repo_root / "src" / "douban_tmdb_follow_single").resolve(strict=False),
        (repo_root / "tools").resolve(strict=False), (repo_root / "tests").resolve(strict=False),
        (repo_root / "build" / "v80-dev").resolve(strict=False),
    ]
    if resolved in protected_files:
        raise GateError("report path cannot overwrite a managed input: %s" % path)
    for root in protected_roots:
        try:
            resolved.relative_to(root)
        except ValueError:
            continue
        raise GateError("report path cannot be inside a managed input directory: %s" % path)
    return resolved


def atomic_write_report(path, report, repo_root=REPO_ROOT):
    path = Path(os.path.abspath(str(path)))
    approved = _assert_report_path_allowed(path, repo_root=repo_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    if _assert_report_path_allowed(path, repo_root=repo_root) != approved:
        raise GateError("report target changed while preparing its parent")
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="\n", prefix=path.name + ".", suffix=".tmp",
            dir=str(path.parent), delete=False,
        ) as handle:
            temp_path = Path(handle.name)
            json.dump(_sanitize(report), handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        if _is_link_or_reparse(temp_path):
            raise GateError("temporary report unexpectedly became a link or reparse point")
        if _assert_report_path_allowed(path, repo_root=repo_root) != approved:
            raise GateError("report target changed before atomic replace")
        os.replace(str(temp_path), str(path))
        temp_path = None
    finally:
        if temp_path is not None and temp_path.exists() and not _is_link_or_reparse(temp_path):
            temp_path.unlink()


def _pytest_selected_nodeids(args):
    raw = tuple(getattr(args, "pytest_node", ()) or ())
    normalized = []
    for item in raw:
        value = str(item).strip().replace("\\", "/")
        base = value.split("::", 1)[0]
        parts = base.split("/")
        if (
                not value
                or not base.startswith("tests/")
                or not base.endswith(".py")
                or any(part in ("", ".", "..") for part in parts)
                or Path(base).is_absolute()
        ):
            raise GateError("--pytest-node must name a relative tests/*.py path or node id")
        normalized.append(value)
    if len(normalized) != len(set(normalized)):
        raise GateError("--pytest-node values must be unique")
    return tuple(sorted(normalized))


def _validate_args(args):
    if not _valid_timeout(args.command_timeout):
        raise GateError("--command-timeout must be finite and greater than zero")
    partial = bool(getattr(args, "partial", False))
    if bool(args.fongmi_root) != bool(args.atvp):
        raise GateError("--fongmi-root and --atvp must be supplied together")
    if not partial and not (args.fongmi_root and args.atvp):
        raise GateError("complete mode requires both --fongmi-root and --atvp; use --partial for an incomplete diagnostic run")
    if not partial and not args.upstream_root:
        raise GateError("complete mode requires --upstream-root; use --partial for an incomplete diagnostic run")
    expected_resume_sha256 = getattr(args, "resume_source_sha256", None)
    pytest_nodeids = _pytest_selected_nodeids(args)
    if pytest_nodeids and getattr(args, "resume_from", None) is None:
        raise GateError("--pytest-node requires --resume-from")
    if getattr(args, "resume_from", None) is not None and expected_resume_sha256 is None:
        raise GateError("--resume-from requires --resume-source-sha256")
    if expected_resume_sha256 is not None:
        if getattr(args, "resume_from", None) is None:
            raise GateError("--resume-source-sha256 requires --resume-from")
        if not re.fullmatch(r"[0-9A-Fa-f]{64}", expected_resume_sha256):
            raise GateError("--resume-source-sha256 must be a 64-character SHA256")


def run_gate(args, runner=None):
    _validate_args(args)
    _assert_report_path_allowed(args.report)
    resume_source = _load_resume_source(
        getattr(args, "resume_from", None), args.report,
        expected_sha256=getattr(args, "resume_source_sha256", None),
    )
    pytest_nodeids = _pytest_selected_nodeids(args)
    if (
            resume_source is not None
            and resume_source["steps"]["pytest"].get("status") == "failed"
            and not pytest_nodeids
            and not args.skip_tests
    ):
        raise GateError(
            "resuming a failed pytest step requires one or more --pytest-node targets"
        )
    started_at = dt.datetime.now(dt.timezone.utc)
    fingerprinter = _InputFingerprinter(REPO_ROOT)
    steps = []

    def add_step(name, producer):
        input_record = _step_input_record(name, args, steps, fingerprinter)
        source, blocked_reason = _resume_decision(
            name, input_record, resume_source, current_steps=steps,
        )
        if source is not None:
            row = _reuse_step(
                source, name, input_record, resume_source,
                reuse_reason=blocked_reason,
            )
        else:
            invalidation = _resume_invalidation_evidence(
                name, input_record, resume_source, blocked_reason, steps,
            )
            row = _annotate_step(
                producer(), name, input_record, "executed",
                blocked_reason=blocked_reason, resume_source=resume_source,
                resume_invalidation=invalidation,
            )
        steps.append(row)
        return row

    add_step("git_v70_tag", lambda: check_git_tag(REPO_ROOT, runner=runner))
    add_step("structure_and_dependency", check_structure)
    add_step("p2_module_dag", check_p2_module_dag)
    add_step("sensitive_data", check_sensitive)
    implementation_tree_step = add_step(
        "implementation_tree", check_implementation_tree,
    )
    implementation_tree_index = len(steps) - 1

    build_input = _step_input_record("build_contracts", args, steps, fingerprinter)
    build_source, build_blocked_reason = _resume_decision(
        "build_contracts", build_input, resume_source, current_steps=steps,
    )
    builds = None
    materialized_builds = False
    if build_source is not None:
        try:
            candidate_builds = _materialize_builds()
        except Exception as exc:
            build_source = None
            build_blocked_reason = "current build materialization failed: %s" % _redact(exc)
        else:
            if _materialized_builds_match_step(build_source, candidate_builds):
                builds = candidate_builds
                materialized_builds = True
            else:
                build_source = None
                build_blocked_reason = (
                    "current materialized build evidence changed from the passed source"
                )
    if build_source is not None:
        build_row = _reuse_step(
            build_source, "build_contracts", build_input, resume_source,
            reuse_reason=build_blocked_reason,
        )
    else:
        build_step, builds = check_builds()
        build_row = _annotate_step(
            build_step, "build_contracts", build_input, "executed",
            blocked_reason=build_blocked_reason, resume_source=resume_source,
            resume_invalidation=_resume_invalidation_evidence(
                "build_contracts", build_input, resume_source,
                build_blocked_reason, steps,
            ),
        )
    steps.append(build_row)

    with tempfile.TemporaryDirectory(prefix="v80-stage-gate-") as temp_name:
        temp_dir = Path(temp_name)
        add_step(
            "behavior_diff",
            lambda: check_behavior_diff(
                builds, temp_dir, runner=runner, timeout=args.command_timeout,
            ),
        )
        add_step(
            "macro_a_runtime_differential",
            lambda: check_macro_a_runtime_differential(
                builds,
                temp_dir,
                runner=runner,
                timeout=args.command_timeout,
            ),
        )
        add_step(
            "macro_b_runtime_differential",
            lambda: check_macro_b_runtime_differential(
                builds,
                temp_dir,
                runner=runner,
                timeout=args.command_timeout,
            ),
        )
        add_step(
            "chaos_recovery",
            lambda: check_chaos_recovery(
                builds,
                temp_dir,
                runner=runner,
                timeout=args.command_timeout,
            ),
        )

        command_rows = {}
        if builds is not None:
            artifact = temp_dir / "v80-development.py"
            artifact.write_bytes(builds["development"]["bytes"])
            for name, command, required in build_commands(args, artifact, temp_dir):
                if name == "pytest":
                    command_rows[name] = lambda: _run_pytest(
                        temp_dir, runner=runner, timeout=args.command_timeout,
                        selected_nodeids=pytest_nodeids,
                        resume_source=resume_source,
                    )
                else:
                    command_rows[name] = lambda n=name, c=command, r=required: _run_command(
                        n, c, required=r, runner=runner,
                        timeout=args.command_timeout,
                    )
            command_rows.update({
                row["name"]: (lambda item=row: item)
                for row in _skipped_command_steps(args)
            })
        else:
            if args.skip_tests:
                command_rows["pytest"] = lambda: _step(
                    "pytest", "skipped",
                    detail="disabled by --skip-tests; this run is incomplete",
                )
            else:
                command_rows["pytest"] = lambda: _run_pytest(
                    temp_dir, runner=runner,
                    timeout=args.command_timeout,
                    selected_nodeids=pytest_nodeids,
                    resume_source=resume_source,
                )
            for name in (
                    "resource_shadow_vendor", "atvp_compatibility", "dual_runtime",
                    "fongmi_category_contract"):
                command_rows[name] = lambda n=name: _step(
                    n, "skipped", detail="development build is unavailable",
                )
            if args.upstream_root:
                command = [
                    sys.executable, UPSTREAM_CONTRACT_SCRIPT, args.upstream_root,
                    "--evidence", UPSTREAM_CONTRACT_EVIDENCE,
                    "--json-out", temp_dir / "upstream.json",
                ]
                command_rows["upstream_contract"] = lambda: _run_command(
                    "upstream_contract", command, runner=runner,
                    timeout=args.command_timeout,
                )
            else:
                command_rows["upstream_contract"] = lambda: _step(
                    "upstream_contract", "skipped",
                    detail="partial mode: --upstream-root is required for the complete gate",
                )

        for name in (
                "pytest", "resource_shadow_vendor", "atvp_compatibility", "dual_runtime",
                "fongmi_category_contract", "upstream_contract"):
            producer = command_rows.get(name)
            if producer is None:
                producer = lambda n=name: _step(
                    n, "skipped", detail="step command is unavailable",
                )
            add_step(name, producer)

    steps[implementation_tree_index] = verify_implementation_tree_stable(
        implementation_tree_step, check_implementation_tree(),
    )
    add_step(
        "output_admission_dry_run",
        lambda: check_output_admission_dry_run(
            steps, production_writes=False, deployment_attempted=False,
        ),
    )
    add_step(
        "v70_source_lock",
        lambda: check_v70_source_lock(
            steps, builds, production_writes=False, deployment_attempted=False,
        ),
    )
    _verify_step_inputs_stable(steps, args)
    _attach_resume_propagation_paths(steps)

    names = [row.get("name") for row in steps]
    if tuple(names) != STEP_ORDER:
        raise GateError("stage gate did not produce the fixed 18-step order")

    required_failed = any(row["required"] and row["status"] == "failed" for row in steps)
    required_incomplete = any(row["required"] and row["status"] != "passed" for row in steps)
    explicitly_partial = bool(getattr(args, "partial", False) or args.skip_tests)
    overall = "failed" if required_failed else "incomplete" if required_incomplete or explicitly_partial else "passed"
    resume_metadata = {"enabled": resume_source is not None}
    if resume_source is not None:
        source_report = resume_source["report"]
        resume_metadata.update({
            "source": resume_source["path"].as_posix(),
            "source_report_sha256": resume_source["sha256"],
            "source_sha256_verified": resume_source["sha256_verified"],
            "source_schema": source_report.get("schema"),
            "source_generated_at": source_report.get("generated_at"),
            "source_overall": source_report.get("overall"),
            "reused_steps": [
                row["name"] for row in steps if row.get("execution") == "reused"
            ],
            "executed_steps": [
                row["name"] for row in steps if row.get("execution") == "executed"
            ],
            "legacy_steps": [
                name for name in STEP_ORDER
                if resume_source["steps"][name].get("input_sha256") is None
            ],
            "materialized_steps": [
                "build_contracts" if materialized_builds else None
            ] if materialized_builds else [],
        })
    report = {
        "schema": REPORT_SCHEMA, "generated_at": started_at.isoformat().replace("+00:00", "Z"),
        "repository": str(REPO_ROOT), "commit": _git_commit(), "mode": "partial" if explicitly_partial else "complete",
        "steps": steps, "overall": overall, "resume": resume_metadata,
        "duration_seconds": round((dt.datetime.now(dt.timezone.utc) - started_at).total_seconds(), 3),
        "production_writes": False, "deployment_attempted": False,
    }
    _assert_resume_source_unchanged(resume_source)
    atomic_write_report(args.report, report)
    return report


def _parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, default=REPO_ROOT / "work" / "v80-stage-gate.json")
    parser.add_argument(
        "--resume-from", type=Path,
        help=(
            "reuse passed steps from a prior content-addressed report; "
            "requires --resume-source-sha256"
        ),
    )
    parser.add_argument(
        "--resume-source-sha256",
        help=(
            "trusted 64-character SHA256 required with --resume-from"
        ),
    )
    parser.add_argument(
        "--pytest-node", action="append", default=[],
        help=(
            "repeatable tests/*.py path or node id used to close a failed or "
            "input-invalidated pytest step without rerunning the full suite"
        ),
    )
    parser.add_argument("--partial", action="store_true", help="allow an explicitly incomplete diagnostic run")
    parser.add_argument("--skip-tests", action="store_true", help="skip full pytest and force an incomplete result")
    parser.add_argument("--fongmi-root", type=Path, help="FongMi source checkout for dual/category gates")
    parser.add_argument("--atvp", type=Path, help="Atvp.py used with --fongmi-root")
    parser.add_argument(
        "--upstream-root", type=Path,
        help="AList-TVBox upstream source checkout; required in complete mode",
    )
    parser.add_argument(
        "--command-timeout", type=float, default=DEFAULT_COMMAND_TIMEOUT,
        help="per-command timeout in seconds (default: %(default)s)",
    )
    return parser


def main(argv=None):
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        _validate_args(args)
    except GateError as exc:
        parser.error(str(exc))
    report = run_gate(args)
    print("V80 stage gate: %s (%s)" % (report["overall"], args.report))
    return 0 if report["overall"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())

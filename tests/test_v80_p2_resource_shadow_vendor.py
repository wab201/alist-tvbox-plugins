import ast
import importlib.util
import json
import sys
from pathlib import Path

import pytest

from src.douban_tmdb_follow_single.resource_candidate_pipeline import (
    order_resource_candidate_rows,
)
from src.douban_tmdb_follow_single.resource_candidate_shadow_background import (
    RESOURCE_CANDIDATE_SHADOW_ESTIMATED_COST_US,
    build_background_resource_candidate_shadow_inputs,
)
from src.douban_tmdb_follow_single.resource_candidate_shadow_composition import (
    compose_resource_candidate_shadow,
)
from src.douban_tmdb_follow_single.resource_search_v70_adapter import (
    build_v70_layered_resource_rows,
    build_v70_layered_resource_shadow,
    combine_v70_layered_resource_rows,
)


ROOT = Path(__file__).resolve().parent.parent
SOURCE_DIR = ROOT / "src" / "douban_tmdb_follow_single"
MANIFEST_PATH = SOURCE_DIR / "resource_candidate_shadow_vendor.json"
BUILD_SCRIPT = ROOT / "tools" / "build_v80_resource_shadow_vendor.py"
PUBLIC_SOURCE = ROOT / "py" / "豆瓣TMDB追更单入口.py"
RELEASE_MANIFEST = SOURCE_DIR / "release.json"
PARTS_DIR = SOURCE_DIR / "parts"
INDEX_PATH = ROOT / "spiders_v2.json"


def _load_builder():
    spec = importlib.util.spec_from_file_location("v80_resource_shadow_vendor_builder", BUILD_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BUILDER = _load_builder()


def _load_vendor(tmp_path):
    result = BUILDER.build_vendor()
    path = tmp_path / "resource_candidate_shadow_vendor.py"
    path.write_bytes(result["bytes"])
    module_name = "v80_resource_candidate_shadow_vendor_test"
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(module_name, None)
    return result, module


def _copy_sources(tmp_path):
    for filename in BUILDER.EXPECTED_MODULES:
        (tmp_path / filename).write_bytes((SOURCE_DIR / filename).read_bytes())


def _merge_rows(left, right):
    merged = dict(left)
    for key, value in right.items():
        if merged.get(key) in (None, "", [], ()):
            merged[key] = value
    return merged


def _score_row(row):
    if row.get("raise_score"):
        raise RuntimeError("private row marker must not escape")
    return row.get("score", 0)


def _preference_row(row):
    return tuple(row.get("preference") or ())


def _provider_row(row):
    return row.get("provider")


def _rows():
    return [
        {
            "vod_id": "alpha",
            "vod_name": "Alpha",
            "_resource_mode": "vod1",
            "provider": "quark",
            "score": 12,
            "preference": (2, 1),
        },
        {
            "vod_id": "beta",
            "vod_name": "Beta",
            "_resource_mode": "vod",
            "provider": "baidu",
            "score": 11,
            "preference": (1, 2),
        },
        {
            "vod_id": "alpha",
            "vod_year": "2026",
            "_resource_mode": "vod1",
            "provider": "quark",
            "score": 12,
            "preference": (2, 1),
        },
    ]


def test_vendor_manifest_freezes_the_fixed_shadow_closure():
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

    assert manifest == {
        "schema_version": 1,
        "contract": "v80_p2_resource_candidate_shadow_vendor",
        "encoding": "utf-8",
        "output": "build/v80-dev/vendor-proof/resource_candidate_shadow_vendor.py",
        "modules": list(BUILDER.EXPECTED_MODULES),
    }
    assert len(manifest["modules"]) == 17


def test_vendor_build_is_deterministic_and_has_no_relative_or_dynamic_imports():
    first = BUILDER.build_vendor()
    second = BUILDER.build_vendor()
    text = first["bytes"].decode("utf-8")
    tree = ast.parse(text)

    assert first["bytes"] == second["bytes"]
    assert first["sha256"] == second["sha256"]
    assert first["closure_sha256"] == second["closure_sha256"]
    assert first["size"] == len(first["bytes"])
    assert not any(isinstance(node, ast.ImportFrom) and node.level for node in ast.walk(tree))
    assert all(token not in text for token in ("exec(", "eval(", "__import__", "sys.modules", "importlib"))


def test_vendor_module_imports_from_an_independent_path(tmp_path):
    result, vendor = _load_vendor(tmp_path)

    assert len(result["modules"]) == 17
    assert vendor.RESOURCE_CANDIDATE_SHADOW_ESTIMATED_COST_US == 5328
    assert callable(vendor.build_resource_candidate_shadow_report)
    assert callable(vendor.decide_resource_candidate_shadow)
    assert callable(vendor.compose_resource_candidate_shadow)
    assert callable(vendor.build_background_resource_candidate_shadow_inputs)
    assert callable(vendor.run_background_resource_candidate_shadow)
    assert callable(vendor.get_resource_provider_adapter)
    assert callable(vendor.build_resource_search_plan)
    assert callable(vendor.build_layered_resource_shadow)
    assert callable(vendor.build_v70_layered_resource_rows)
    assert callable(vendor.build_v70_layered_resource_shadow)
    assert callable(vendor.combine_v70_layered_resource_rows)
    assert callable(vendor.build_resource_search_layered_shadow_report)
    assert callable(vendor.run_resource_search_layered_shadow)


def test_vendored_v70_layered_search_matches_the_source(tmp_path):
    _, vendor = _load_vendor(tmp_path)
    rows = [
        {
            "vod_id": "https%3A%2F%2Fpan.quark.cn%2Fs%2Fcache",
            "vod_name": "Cached",
            "_resource_mode": "pansou",
        },
        {"vod_id": "recent-id", "vod_name": "Recent", "_resource_mode": "vod"},
        {"vod_id": "bound-id", "vod_name": "Bound", "_resource_mode": "vod1"},
        {"vod_id": "vod-id", "vod_name": "Vod", "_resource_mode": "vod"},
    ]
    kwargs = {
        "cached_rows": [{
            "vod_id": "https://pan.quark.cn/s/cache",
            "_resource_mode": "pansou",
        }],
        "recent_resource_id": "recent-id",
        "binding_resource_id": "bound-id",
        "available_modes": ["pansou", "vod", "vod1"],
    }

    expected = [batch.to_dict() for batch in build_v70_layered_resource_shadow(rows, **kwargs)]
    actual = [batch.to_dict() for batch in vendor.build_v70_layered_resource_shadow(rows, **kwargs)]

    assert actual == expected


def test_vendored_raw_layered_rows_and_combiner_match_the_source(tmp_path):
    _, vendor = _load_vendor(tmp_path)
    rows = _rows()
    kwargs = {
        "available_modes": ("vod1", "vod"),
        "merge_rows": _merge_rows,
        "score_row": _score_row,
        "preference_row": _preference_row,
        "provider_row": _provider_row,
    }

    source_batches = build_v70_layered_resource_rows(
        rows, available_modes=kwargs["available_modes"],
    )
    vendor_batches = vendor.build_v70_layered_resource_rows(
        rows, available_modes=kwargs["available_modes"],
    )
    assert [
        (batch.step.to_dict(), list(batch.rows)) for batch in vendor_batches
    ] == [
        (batch.step.to_dict(), list(batch.rows)) for batch in source_batches
    ]
    assert vendor.combine_v70_layered_resource_rows(rows, **kwargs) == (
        combine_v70_layered_resource_rows(rows, **kwargs)
    )


@pytest.mark.parametrize(
    "kwargs",
    [
        {},
        {"enabled": False, "cache_key": "resource-search:key", "generation": 3},
        {"enabled": True, "cache_key": "resource-search:key", "generation": 3},
        {
            "enabled": True,
            "cache_key": "resource-search:key",
            "generation": 3,
            "sampled_generation": 3,
        },
        {
            "enabled": True,
            "cache_key": "资源缓存键",
            "generation": 4,
            "sampled_generation": 3,
            "shadow_budget_us": 5328,
        },
    ],
)
def test_vendored_background_inputs_match_the_source(tmp_path, kwargs):
    _, vendor = _load_vendor(tmp_path)

    assert vendor.build_background_resource_candidate_shadow_inputs(**kwargs) == (
        build_background_resource_candidate_shadow_inputs(**kwargs)
    )


def test_vendored_merge_pipeline_matches_the_source(tmp_path):
    _, vendor = _load_vendor(tmp_path)
    rows = _rows()
    kwargs = {
        "merge_rows": _merge_rows,
        "score_row": _score_row,
        "preference_row": _preference_row,
        "provider_row": _provider_row,
    }

    assert vendor.order_resource_candidate_rows(rows, **kwargs) == order_resource_candidate_rows(
        rows, **kwargs
    )


@pytest.mark.parametrize("report_state", ["equal", "different", "error"])
def test_vendored_shadow_composition_matches_the_source(tmp_path, report_state):
    _, vendor = _load_vendor(tmp_path)
    rows = _rows()
    callbacks = {
        "merge_rows": _merge_rows,
        "score_row": _score_row,
        "preference_row": _preference_row,
        "provider_row": _provider_row,
    }
    if report_state == "error":
        rows = [{"vod_id": "private-row-marker", "raise_score": True}]
        legacy = []
    else:
        legacy = order_resource_candidate_rows(rows, **callbacks)
        if report_state == "different":
            legacy = list(reversed(legacy))
    inputs = build_background_resource_candidate_shadow_inputs(
        enabled=True,
        cache_key="resource-search:already-redacted",
        generation=9,
        sample_every=1,
        shadow_budget_us=RESOURCE_CANDIDATE_SHADOW_ESTIMATED_COST_US,
    )

    expected = compose_resource_candidate_shadow(legacy, rows, **inputs, **callbacks)
    actual = vendor.compose_resource_candidate_shadow(legacy, rows, **inputs, **callbacks)

    assert actual == expected
    assert actual["report"]["status"] == report_state
    assert "private-row-marker" not in repr(actual)
    assert "already-redacted" not in repr(actual)


def test_vendored_composition_preserves_policy_short_circuit(tmp_path):
    _, vendor = _load_vendor(tmp_path)

    def unexpected(*_args, **_kwargs):
        raise AssertionError("shadow callbacks must not run")

    result = vendor.compose_resource_candidate_shadow(
        unexpected,
        unexpected,
        enabled=False,
        sample_key="",
        sample_every=1,
        available_budget_us=0,
        estimated_cost_us=5328,
        merge_rows=unexpected,
        score_row=unexpected,
        preference_row=unexpected,
        provider_row=unexpected,
    )

    assert result == {"decision": {"run": False, "reason": "disabled"}, "report": None}


def test_vendor_builder_rejects_a_later_dependency(tmp_path):
    _copy_sources(tmp_path)
    path = tmp_path / "resource_row_identity.py"
    path.write_text(
        "from .resource_candidate_pipeline import order_resource_candidate_rows\n"
        + path.read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    with pytest.raises(BUILDER.VendorBuildError, match="later module"):
        BUILDER.build_vendor(source_dir=tmp_path)


def test_vendor_builder_rejects_top_level_symbol_collisions(tmp_path):
    _copy_sources(tmp_path)
    path = tmp_path / "resource_candidate_shadow_background.py"
    path.write_text(
        path.read_text(encoding="utf-8") + "\nRESOURCE_MODE_ORDER = ()\n",
        encoding="utf-8",
    )

    with pytest.raises(BUILDER.VendorBuildError, match="symbol collision"):
        BUILDER.build_vendor(source_dir=tmp_path)


def test_vendor_builder_rejects_conflicting_import_bindings(tmp_path):
    _copy_sources(tmp_path)
    path = tmp_path / "resource_candidate_shadow_background.py"
    path.write_text(
        "import json as hashlib\n" + path.read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    with pytest.raises(BUILDER.VendorBuildError, match="binds import name"):
        BUILDER.build_vendor(source_dir=tmp_path)


def test_vendor_builder_rejects_missing_imported_symbols(tmp_path):
    _copy_sources(tmp_path)
    path = tmp_path / "resource_candidate_merge.py"
    text = path.read_text(encoding="utf-8").replace(
        "build_resource_row_identity", "missing_resource_row_identity"
    )
    path.write_text(text, encoding="utf-8")

    with pytest.raises(BUILDER.VendorBuildError, match="missing symbol"):
        BUILDER.build_vendor(source_dir=tmp_path)


def test_vendor_builder_rejects_code_sharing_a_relative_import_line(tmp_path):
    _copy_sources(tmp_path)
    path = tmp_path / "resource_candidate_shadow_composition.py"
    text = path.read_text(encoding="utf-8").replace(
        "from .resource_candidate_ordering import RESOURCE_MODE_ORDER",
        "from .resource_candidate_ordering import RESOURCE_MODE_ORDER; SURVIVING = 1",
    )
    path.write_text(text, encoding="utf-8")

    with pytest.raises(BUILDER.VendorBuildError, match="complete physical lines"):
        BUILDER.build_vendor(source_dir=tmp_path)


@pytest.mark.parametrize(
    "statement",
    [
        "if True:\n    hidden_binding = 1\n",
        "try:\n    hidden_binding = 1\nexcept Exception:\n    pass\n",
        "for hidden_binding in ():\n    pass\n",
        "with open(__file__) as hidden_binding:\n    pass\n",
        "match 1:\n    case hidden_binding:\n        pass\n",
        "del RESOURCE_MODE_ORDER\n",
        "RESOURCE_MODE_ORDER += ()\n",
    ],
)
def test_vendor_builder_rejects_dynamic_top_level_statements(tmp_path, statement):
    _copy_sources(tmp_path)
    path = tmp_path / "resource_candidate_shadow_background.py"
    path.write_text(path.read_text(encoding="utf-8") + "\n" + statement, encoding="utf-8")

    with pytest.raises(BUILDER.VendorBuildError, match="unsupported top-level statements"):
        BUILDER.build_vendor(source_dir=tmp_path)


def test_vendor_proof_is_not_referenced_by_runtime_or_release_inputs():
    targets = [PUBLIC_SOURCE, RELEASE_MANIFEST, INDEX_PATH]
    targets.extend(sorted(PARTS_DIR.glob("*.pyinc")))
    combined = b"\n".join(path.read_bytes() for path in targets)

    assert b"resource_candidate_shadow_vendor" not in combined
    assert b"build_v80_resource_shadow_vendor" not in combined
    assert b"build/v80-dev/vendor-proof" not in combined

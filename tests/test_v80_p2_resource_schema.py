import pytest

from src.douban_tmdb_follow_single.resource_schema import (
    GENERIC_ROW_SCHEMA,
    MERGED_SCHEMA,
    RESULTS_DIRECT_SCHEMA,
    RESULTS_LINKS_SCHEMA,
    SUPPLEMENT_ROW_SCHEMA,
    classify_resource_row,
    detect_resource_payload,
    generic_rows,
)
from src.douban_tmdb_follow_single.resource_shadow import map_resource_payload


def _matches(mode, payload):
    return [(item.schema_id, item.path, item.row_count) for item in detect_resource_payload(mode, payload)]


@pytest.mark.parametrize(("payload", "schema_id", "path"), [
    ({"list": [{"id": "x"}]}, "v70.generic.list.v1", "$.list"),
    ({"data": [{"id": "x"}]}, "v70.generic.data-list.v1", "$.data"),
    ({"items": [{"id": "x"}]}, "v70.generic.items.v1", "$.items"),
    ({"results": [{"id": "x"}]}, "v70.generic.results.v1", "$.results"),
    ({"data": {"data": {"items": [{"id": "x"}]}}}, "v70.generic.items.v1", "$.data.data.items"),
])
def test_generic_schema_ids_and_data_depth(payload, schema_id, path):
    assert _matches("vod", payload) == [(schema_id, path, 1)]


def test_generic_priority_matches_v70_first_list_rule():
    assert _matches("vod", {
        "list": [],
        "data": [{"id": "data"}],
        "items": [{"id": "items"}],
    }) == [("v70.generic.list.v1", "$.list", 0)]
    assert generic_rows({
        "list": {"wrong": "type"},
        "data": [{"id": "data"}],
        "items": [{"id": "items"}],
    }) == ({"id": "data"},)
    assert generic_rows({
        "data": {"list": [{"id": "nested"}]},
        "items": [{"id": "outer"}],
    }) == ({"id": "outer"},)


def test_generic_rows_skip_non_mappings_and_count_kept_rows():
    payload = {"list": [None, "text", {"id": "one"}, ["nested"], {"id": "two"}]}
    assert _matches("vod", payload) == [("v70.generic.list.v1", "$.list", 2)]
    assert generic_rows(payload) == ({"id": "one"}, {"id": "two"})


@pytest.mark.parametrize("payload", [
    [{"id": "x"}],
    {"rows": [{"id": "x"}]},
    {"payload": {"list": [{"id": "x"}]}},
    {"data": {"rows": [{"id": "x"}]}},
    {"response": {"results": [{"id": "x"}]}},
])
def test_unknown_container_shapes_are_not_registered(payload):
    assert detect_resource_payload("vod", payload) == ()
    assert map_resource_payload("vod", payload) == ()


def test_supplement_facets_are_mode_scoped():
    payload = {"results": [{"url": "https://pan.quark.cn/s/a", "note": "A"}]}
    assert _matches("vod", payload) == [("v70.generic.results.v1", "$.results", 1)]
    assert _matches("pansou", payload) == [
        ("v70.generic.results.v1", "$.results", 1),
        (RESULTS_DIRECT_SCHEMA, "$.results", 1),
    ]
    assert map_resource_payload("vod", payload) == ()
    assert [item.resource_id for item in map_resource_payload("pansou", payload)] == [
        "https://pan.quark.cn/s/a",
    ]


def test_supplement_facets_preserve_data_before_root_and_results_before_merged():
    payload = {
        "data": {
            "results": [{"links": [{"url": "https://pan.quark.cn/s/data", "note": "Data"}]}],
            "merged_by_type": {"百度": [{"url": "https://pan.baidu.com/s/data", "note": "Data merged"}]},
        },
        "results": [{"url": "https://pan.xunlei.com/s/root", "note": "Root"}],
        "merged_by_type": {"uc": [{"url": "https://drive.uc.cn/s/root", "note": "Root merged"}]},
    }
    assert _matches("telegram", payload) == [
        ("v70.generic.results.v1", "$.results", 1),
        (RESULTS_LINKS_SCHEMA, "$.data.results", 1),
        (MERGED_SCHEMA, "$.data.merged_by_type", 1),
        (RESULTS_DIRECT_SCHEMA, "$.results", 1),
        (MERGED_SCHEMA, "$.merged_by_type", 1),
    ]
    assert [item.resource_id for item in map_resource_payload("telegram", payload)] == [
        "https://pan.quark.cn/s/data",
        "https://pan.baidu.com/s/data",
        "https://pan.xunlei.com/s/root",
        "https://drive.uc.cn/s/root",
    ]


def test_empty_known_facets_are_registered_without_rows():
    assert _matches("vod", {"list": []}) == [("v70.generic.list.v1", "$.list", 0)]
    assert _matches("pansou", {"results": [{"links": []}]}) == [
        ("v70.generic.results.v1", "$.results", 1),
        (RESULTS_LINKS_SCHEMA, "$.results", 0),
    ]
    assert _matches("pansou", {"merged_by_type": {}}) == [
        (MERGED_SCHEMA, "$.merged_by_type", 0),
    ]


def test_invalid_facet_types_do_not_register_the_facet():
    payload = {
        "results": [{"links": {"url": "ignored"}, "url": "https://pan.quark.cn/s/direct", "note": "Direct"}],
        "merged_by_type": {"quark": {"url": "ignored"}},
    }
    assert _matches("pansou", payload) == [
        ("v70.generic.results.v1", "$.results", 1),
        (RESULTS_DIRECT_SCHEMA, "$.results", 1),
    ]


def test_row_classification_is_fixed_and_mode_specific():
    row = {"id": "opaque", "url": "https://pan.quark.cn/s/a"}
    assert classify_resource_row("vod", row) == (GENERIC_ROW_SCHEMA,)
    assert classify_resource_row("pansou", row) == (GENERIC_ROW_SCHEMA, SUPPLEMENT_ROW_SCHEMA)
    assert classify_resource_row("vod", {"url": "https://pan.quark.cn/s/a"}) == ()
    assert classify_resource_row("pansou", {"url": "https://pan.quark.cn/s/a"}) == (
        SUPPLEMENT_ROW_SCHEMA,
    )
    assert classify_resource_row("pansou", {"records": []}) == ()


def test_root_generic_and_immediate_data_supplement_can_coexist():
    payload = {
        "list": [{"id": "generic", "work_title": "Generic"}],
        "data": {"results": [{"url": "https://pan.quark.cn/s/a", "note": "Supplement"}]},
    }
    assert _matches("pansou", payload) == [
        ("v70.generic.list.v1", "$.list", 1),
        (RESULTS_DIRECT_SCHEMA, "$.data.results", 1),
    ]
    assert [(item.resource_id, item.provider) for item in map_resource_payload("pansou", payload)] == [
        ("https://pan.quark.cn/s/a", "quark"),
        ("generic", ""),
    ]


def test_same_results_row_can_take_supplement_and_generic_paths():
    payload = {"results": [{
        "id": "opaque",
        "url": "https://pan.quark.cn/s/a",
        "work_title": "A",
    }]}
    assert [(item.resource_id, item.provider) for item in map_resource_payload("pansou", payload)] == [
        ("https://pan.quark.cn/s/a", "quark"),
        ("opaque", ""),
    ]


def test_deep_data_results_is_generic_only_but_row_kind_still_applies():
    payload = {"data": {"data": {"results": [
        {"url": "https://pan.quark.cn/s/deep", "note": "Deep"},
    ]}}}
    assert _matches("pansou", payload) == [
        ("v70.generic.results.v1", "$.data.data.results", 1),
    ]
    assert [item.resource_id for item in map_resource_payload("pansou", payload)] == [
        "https://pan.quark.cn/s/deep",
    ]


def test_invalid_modes_are_rejected_by_schema_entry_points():
    with pytest.raises(ValueError):
        detect_resource_payload("future", {"list": []})
    with pytest.raises(ValueError):
        classify_resource_row("future", {"id": "x"})

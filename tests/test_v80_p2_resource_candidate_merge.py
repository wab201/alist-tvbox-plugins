import importlib.util
import sys
import types
from collections import UserDict
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from urllib.parse import unquote

import pytest

import src.douban_tmdb_follow_single.resource_candidate_merge as candidate_merge_module
from src.douban_tmdb_follow_single.resource_candidate_merge import (
    merge_resource_candidate_rows,
)
from src.douban_tmdb_follow_single.resource_candidate_preference import (
    build_resource_row_preference,
)
from src.douban_tmdb_follow_single.resource_row_merge import merge_resource_rows


ROOT = Path(__file__).resolve().parents[1]
PUBLIC_SOURCE = ROOT / "py" / "豆瓣TMDB追更单入口.py"


@contextmanager
def _load_v70():
    base_module = types.ModuleType("base")
    spider_module = types.ModuleType("base.spider")
    spider_module.Spider = type("BaseSpider", (object,), {})
    base_module.spider = spider_module
    saved = (sys.modules.get("base"), sys.modules.get("base.spider"))
    sys.modules["base"] = base_module
    sys.modules["base.spider"] = spider_module
    try:
        spec = importlib.util.spec_from_file_location("v70_resource_candidate_merge_reference", PUBLIC_SOURCE)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        yield module
    finally:
        for name, previous in zip(("base", "base.spider"), saved):
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous


@pytest.fixture(scope="module")
def v70():
    with _load_v70() as module:
        yield module


def _preference_from_v70(spider, row, item=None, bound=""):
    item_is_dict = isinstance(item, dict)
    row_score = spider._resource_score(row, item, bound) if item_is_dict else 0
    work_title = str(row.get("work_title") or "").strip()
    work_title_score = None
    if item_is_dict and work_title:
        work_title_score = spider._resource_score({
            "vod_id": row.get("vod_id") or row.get("id"),
            "work_title": work_title,
        }, item, bound)
    resource_id = str(row.get("vod_id") or row.get("id") or "").strip()
    return build_resource_row_preference(
        row,
        row_score=row_score,
        work_title_score=work_title_score,
        password_score=spider._resource_url_password_score(unquote(resource_id)),
        timestamp_rank=spider._resource_row_timestamp(row),
    )


def _actual_from_v70_evidence(v70, rows, item=None, bound=""):
    spider = v70.Spider.__new__(v70.Spider)

    def merge_rows(current, candidate):
        return merge_resource_rows(
            current,
            candidate,
            current_preference=_preference_from_v70(spider, current, item, bound),
            candidate_preference=_preference_from_v70(spider, candidate, item, bound),
            item_is_dict=isinstance(item, dict),
        )

    return merge_resource_candidate_rows(rows, merge_rows=merge_rows)


def _assert_v70_equal(v70, rows, item=None, bound=""):
    spider = v70.Spider.__new__(v70.Spider)
    expected = spider._merge_resource_candidate_rows(rows, item, bound)
    actual = _actual_from_v70_evidence(v70, rows, item, bound)
    assert actual == expected
    return actual


@pytest.mark.parametrize(("rows", "item", "bound"), [
    (None, None, ""),
    (False, None, ""),
    ([], None, ""),
    (({"vod_id": "a"}, {"vod_id": "b"}), None, ""),
    ([None, 1, "skip", UserDict({"vod_id": "wrapped"})], None, ""),
    ([{"vod_id": "", "name": "first"}, {"id": "", "name": "second"}], None, ""),
    ([{"vod_id": "same", "name": "first"}, {"vod_id": "same", "source": "second"}], None, ""),
    ([
        {"vod_id": "same", "name": "first"},
        {"vod_id": "other", "name": "other"},
        {"vod_id": "same", "source": "second"},
        {"vod_id": "same", "note": "third"},
    ], None, ""),
    ([
        {"vod_id": "bound", "name": "left"},
        {"vod_id": "bound", "name": "right", "work_title": "测试剧集"},
    ], {"title": "测试剧集"}, "bound"),
    ([
        {"_resource_mode": "vod", "id": "same", "name": "vod"},
        {"_resource_mode": "pansou", "id": "same", "name": "pansou"},
    ], None, ""),
])
def test_candidate_merge_matches_v70_for_fixed_contract_cases(v70, rows, item, bound):
    _assert_v70_equal(v70, rows, item, bound)


@pytest.mark.parametrize("rows", [None, False, 0, "", [], (), {}])
def test_falsey_containers_return_empty_list(rows):
    assert merge_resource_candidate_rows(rows, merge_rows=lambda left, right: left) == []


@pytest.mark.parametrize("rows", [1, object()])
def test_truthy_noniterable_containers_keep_native_type_error(rows):
    with pytest.raises(TypeError):
        merge_resource_candidate_rows(rows, merge_rows=lambda left, right: left)


def test_dict_container_iterates_keys_and_therefore_adds_no_rows():
    assert merge_resource_candidate_rows(
        {"first": {"vod_id": "a"}},
        merge_rows=lambda left, right: left,
    ) == []


def test_generator_input_is_consumed_once_in_order():
    rows = ({"vod_id": value} for value in ("a", "b", "a"))
    calls = []

    result = merge_resource_candidate_rows(
        rows,
        merge_rows=lambda left, right: calls.append((left, right)) or left,
    )

    assert [row["vod_id"] for row in result] == ["a", "b"]
    assert len(calls) == 1
    assert list(rows) == []


def test_non_dict_rows_are_skipped_and_dict_subclasses_become_plain_dicts():
    class RowDict(dict):
        pass

    row = RowDict({"vod_id": "a"})
    result = merge_resource_candidate_rows(
        [None, UserDict({"vod_id": "wrapped"}), row],
        merge_rows=lambda left, right: left,
    )

    assert result == [{"vod_id": "a"}]
    assert type(result[0]) is dict


def test_identity_is_computed_once_per_accepted_copied_row(monkeypatch):
    class RowDict(dict):
        pass

    nested = {"shared": True}
    first = RowDict({"vod_id": "first", "marker": "first", "nested": nested})
    second = {"vod_id": "second", "marker": "second"}
    calls = []

    def identity(row):
        calls.append(row)
        return row["vod_id"]

    monkeypatch.setattr(candidate_merge_module, "build_resource_row_identity", identity)
    result = merge_resource_candidate_rows(
        [first, UserDict({"vod_id": "skip"}), second],
        merge_rows=lambda left, right: left,
    )

    assert [row["marker"] for row in calls] == ["first", "second"]
    assert all(type(row) is dict for row in calls)
    assert calls[0] is not first and calls[1] is not second
    assert calls[0]["nested"] is nested
    assert result == [dict(first), second]


def test_rows_without_identity_are_retained_separately_at_their_positions():
    rows = [
        {"name": "empty-1"},
        {"vod_id": "same", "name": "first"},
        {"id": "", "name": "empty-2"},
        {"vod_id": "same", "source": "second"},
    ]

    result = merge_resource_candidate_rows(
        rows,
        merge_rows=lambda left, right: dict(left, source=right["source"]),
    )

    assert [row.get("name") for row in result] == ["empty-1", "first", "empty-2"]
    assert result[1]["source"] == "second"


def test_duplicate_keeps_first_position_and_unique_rows_keep_input_order():
    rows = [
        {"vod_id": "a", "name": "first-a"},
        {"vod_id": "b", "name": "b"},
        {"vod_id": "a", "name": "second-a"},
        {"vod_id": "c", "name": "c"},
    ]

    result = merge_resource_candidate_rows(
        rows,
        merge_rows=lambda left, right: dict(left, name=right["name"]),
    )

    assert [(row["vod_id"], row["name"]) for row in result] == [
        ("a", "second-a"), ("b", "b"), ("c", "c"),
    ]


def test_third_duplicate_receives_the_previous_merge_result():
    seen_left = []

    def merge_rows(left, right):
        seen_left.append(deepcopy(left))
        output = dict(left)
        output.setdefault("seen", []).append(right["name"])
        return output

    result = merge_resource_candidate_rows(
        [
            {"vod_id": "same", "name": "first"},
            {"vod_id": "same", "name": "second"},
            {"vod_id": "same", "name": "third"},
        ],
        merge_rows=merge_rows,
    )

    assert "seen" not in seen_left[0]
    assert seen_left[1]["seen"] == ["second"]
    assert result[0]["seen"] == ["second", "third"]


def test_identity_positions_remain_bound_when_merger_changes_the_left_id():
    calls = []

    def merge_rows(left, right):
        calls.append((dict(left), dict(right)))
        return {"vod_id": "changed", "count": len(calls)}

    result = merge_resource_candidate_rows(
        [
            {"vod_id": "same"},
            {"vod_id": "same"},
            {"vod_id": "same"},
        ],
        merge_rows=merge_rows,
    )

    assert len(calls) == 2
    assert calls[1][0] == {"vod_id": "changed", "count": 1}
    assert result == [{"vod_id": "changed", "count": 2}]


def test_url_variants_merge_across_modes_but_plain_ids_do_not():
    result = merge_resource_candidate_rows(
        [
            {"_resource_mode": "vod", "url": "http://Example.com/a/", "name": "url-1"},
            {"_resource_mode": "pansou", "url": "https://example.com/a", "source": "url-2"},
            {"_resource_mode": "vod", "id": "plain", "name": "id-1"},
            {"_resource_mode": "pansou", "id": "plain", "name": "id-2"},
        ],
        merge_rows=lambda left, right: dict(left, source=right.get("source")),
    )

    assert len(result) == 3
    assert result[0]["source"] == "url-2"
    assert [row["name"] for row in result[1:]] == ["id-1", "id-2"]


def test_inputs_are_not_mutated_and_rows_are_shallow_copied():
    nested = {"value": 1}
    rows = [{"vod_id": "a", "nested": nested}, {"vod_id": "b"}]
    originals = [dict(row) for row in rows]

    result = merge_resource_candidate_rows(rows, merge_rows=lambda left, right: left)

    assert result[0] is not rows[0] and result[1] is not rows[1]
    assert result[0]["nested"] is nested
    assert rows == originals


def test_merger_is_called_only_for_duplicate_nonempty_identities():
    calls = []
    result = merge_resource_candidate_rows(
        [
            {"name": "empty-1"},
            {"name": "empty-2"},
            {"vod_id": "a"},
            {"vod_id": "b"},
            {"vod_id": "a"},
        ],
        merge_rows=lambda left, right: calls.append((left, right)) or left,
    )

    assert len(calls) == 1
    assert len(result) == 4


def test_merger_exception_propagates_without_wrapping():
    def merge_rows(_left, _right):
        raise RuntimeError("merge failed")

    with pytest.raises(RuntimeError, match="merge failed"):
        merge_resource_candidate_rows(
            [{"vod_id": "same"}, {"vod_id": "same"}],
            merge_rows=merge_rows,
        )

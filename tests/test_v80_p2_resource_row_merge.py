import importlib.util
import sys
import types
from collections import UserDict
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import unquote

import pytest

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
        spec = importlib.util.spec_from_file_location("v70_resource_row_merge_reference", PUBLIC_SOURCE)
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


def _actual_from_v70_evidence(v70, current, candidate, item=None, bound=""):
    left = dict(current or {})
    right = dict(candidate or {})
    spider = v70.Spider()
    return merge_resource_rows(
        current,
        candidate,
        current_preference=_preference_from_v70(spider, left, item, bound),
        candidate_preference=_preference_from_v70(spider, right, item, bound),
        item_is_dict=isinstance(item, dict),
    )


def _assert_v70_equal(v70, current, candidate, item=None, bound=""):
    expected = v70.Spider()._merge_resource_rows(current, candidate, item, bound)
    actual = _actual_from_v70_evidence(v70, current, candidate, item, bound)
    assert actual == expected
    return actual


@pytest.mark.parametrize(("current", "candidate", "item", "bound"), [
    (None, {"vod_id": "right", "name": "candidate"}, None, ""),
    ({}, {"vod_id": "right", "name": "candidate"}, None, ""),
    (UserDict({"vod_id": "left", "name": "current"}), {"vod_id": "right"}, None, ""),
    ({"vod_id": "left", "vod_name": "测试剧集"}, {"vod_id": "right", "name": "补充"}, None, ""),
    ({"vod_id": "left", "vod_name": ""}, {"vod_id": "right", "vod_name": "补充"}, {}, ""),
    ({"vod_id": "left", "vod_name": ""}, {"vod_id": "right", "vod_name": "补充"}, None, ""),
    ({"vod_id": "left", "_validated_groups": 1}, {"vod_id": "right", "name": "补充"}, None, ""),
    ({"id": "left"}, {"id": "right", "updated_at": "2026-08-13T12:00:00Z"}, None, ""),
    ({"vod_id": "bound", "name": "left"}, {"vod_id": "right", "name": "right"}, {"title": "测试剧集"}, "bound"),
])
def test_merge_matches_v70_for_fixed_contract_cases(v70, current, candidate, item, bound):
    _assert_v70_equal(v70, current, candidate, item, bound)


@pytest.mark.parametrize("falsey", [None, False, 0, "", [], {}])
def test_falsey_inputs_keep_v70_empty_dict_normalization(v70, falsey):
    assert _assert_v70_equal(
        v70, falsey, {"vod_id": "right", "source": "candidate"}, None,
    ) == {"vod_id": "right", "source": "candidate"}


def test_convertible_key_value_sequence_keeps_v70_dict_normalization(v70):
    current = [("vod_id", "left"), ("source", "current")]

    assert _assert_v70_equal(v70, current, {}, None) == {
        "vod_id": "left", "source": "current",
    }


def test_item_dict_subclass_protects_titles_but_userdict_does_not(v70):
    class ItemDict(dict):
        pass

    current = {"vod_id": "same", "vod_name": "", "source": "current"}
    candidate = {"vod_id": "same", "vod_name": "secondary"}

    assert _assert_v70_equal(v70, current, candidate, ItemDict())["vod_name"] == ""
    assert _assert_v70_equal(
        v70, current, candidate, UserDict(),
    )["vod_name"] == "secondary"


def _preference(match=0, work_state=1, score=0, password=0, timestamp=0.0,
                validated=0, metadata=0):
    return (match, work_state, score, password, timestamp, validated, metadata)


def test_candidate_must_strictly_win_preference_or_current_stays_primary():
    current = {"vod_id": "left", "name": "left"}
    candidate = {"vod_id": "right", "name": "right"}
    tied = _preference()

    assert merge_resource_rows(
        current, candidate,
        current_preference=tied,
        candidate_preference=tied,
        item_is_dict=False,
    )["name"] == "left"
    assert merge_resource_rows(
        current, candidate,
        current_preference=tied,
        candidate_preference=_preference(match=1),
        item_is_dict=False,
    )["name"] == "right"


@pytest.mark.parametrize("empty", [None, "", [], {}])
def test_secondary_fills_only_v70_empty_sentinels(empty):
    result = merge_resource_rows(
        {"vod_id": "same", "source": empty},
        {"vod_id": "same", "source": "secondary"},
        current_preference=_preference(),
        candidate_preference=_preference(),
        item_is_dict=False,
    )

    assert result["source"] == "secondary"


@pytest.mark.parametrize("present", [0, False, (), set(), "   "])
def test_other_falsy_or_blank_values_are_not_empty_sentinels(present):
    result = merge_resource_rows(
        {"vod_id": "same", "source": present},
        {"vod_id": "same", "source": "secondary"},
        current_preference=_preference(),
        candidate_preference=_preference(),
        item_is_dict=False,
    )

    assert result["source"] == present


@pytest.mark.parametrize("empty", [None, "", [], {}])
def test_secondary_empty_sentinels_are_skipped(empty):
    result = merge_resource_rows(
        {"vod_id": "same"},
        {"vod_id": "same", "source": empty},
        current_preference=_preference(),
        candidate_preference=_preference(),
        item_is_dict=False,
    )

    assert "source" not in result


def test_secondary_private_fields_never_fill_primary():
    result = merge_resource_rows(
        {"vod_id": "same"},
        {"vod_id": "same", "_validated_groups": 3, "_resource_mode": "telegram"},
        current_preference=_preference(),
        candidate_preference=_preference(),
        item_is_dict=False,
    )

    assert "_validated_groups" not in result
    assert "_resource_mode" not in result


@pytest.mark.parametrize("key", [
    "work_title", "vod_name", "name", "title", "vod_title", "show_name", "note",
])
def test_item_dict_protects_the_frozen_title_fields(key):
    current = {"vod_id": "same", key: ""}
    candidate = {"vod_id": "same", key: "secondary"}

    protected = merge_resource_rows(
        current, candidate,
        current_preference=_preference(),
        candidate_preference=_preference(),
        item_is_dict=True,
    )
    unprotected = merge_resource_rows(
        current, candidate,
        current_preference=_preference(),
        candidate_preference=_preference(),
        item_is_dict=False,
    )

    assert protected[key] == ""
    assert unprotected[key] == "secondary"


def test_password_score_selects_resource_id_before_timestamp():
    current = {"vod_id": "left", "_validated_groups": 1}
    candidate = {"vod_id": "right", "updated_at": 999}

    left_password = merge_resource_rows(
        current, candidate,
        current_preference=_preference(password=1, timestamp=1.0),
        candidate_preference=_preference(password=0, timestamp=999.0),
        item_is_dict=False,
    )
    right_password = merge_resource_rows(
        current, candidate,
        current_preference=_preference(password=0, timestamp=999.0),
        candidate_preference=_preference(password=1, timestamp=1.0),
        item_is_dict=False,
    )

    assert left_password["vod_id"] == "left"
    assert right_password["vod_id"] == "right"


def test_equal_password_uses_strictly_newer_right_then_primary_fallback():
    current = {"vod_id": "left"}
    candidate = {"vod_id": "right"}

    newer_right = merge_resource_rows(
        current, candidate,
        current_preference=_preference(timestamp=1.0),
        candidate_preference=_preference(timestamp=2.0),
        item_is_dict=False,
    )
    tied_left = merge_resource_rows(
        current, candidate,
        current_preference=_preference(timestamp=2.0),
        candidate_preference=_preference(timestamp=2.0),
        item_is_dict=False,
    )

    assert newer_right["vod_id"] == "right"
    assert tied_left["vod_id"] == "left"


def test_equal_password_and_timestamp_fall_back_to_candidate_primary():
    result = merge_resource_rows(
        {"vod_id": "left", "name": "left"},
        {"vod_id": "right", "name": "right"},
        current_preference=_preference(timestamp=2.0),
        candidate_preference=_preference(match=1, timestamp=2.0),
        item_is_dict=False,
    )

    assert result["name"] == "right"
    assert result["vod_id"] == "right"


def test_id_fallback_uses_vod_id_or_id_without_retry_after_strip():
    result = merge_resource_rows(
        {"vod_id": "   ", "id": "left-id"},
        {"id": "right-id"},
        current_preference=_preference(),
        candidate_preference=_preference(),
        item_is_dict=False,
    )

    assert result["vod_id"] == "right-id"
    assert result["id"] == "left-id"


def test_id_only_selection_writes_vod_id_and_keeps_original_id():
    result = merge_resource_rows(
        {"id": "left-id"},
        {},
        current_preference=_preference(),
        candidate_preference=_preference(),
        item_is_dict=False,
    )

    assert result["id"] == "left-id"
    assert result["vod_id"] == "left-id"


def test_empty_selected_id_does_not_create_vod_id():
    result = merge_resource_rows(
        {}, {},
        current_preference=_preference(),
        candidate_preference=_preference(),
        item_is_dict=False,
    )

    assert "vod_id" not in result


def test_timestamp_uses_strict_newer_side_and_first_nonempty_raw_field():
    current = {"vod_id": "same", "datetime": "left-time"}
    candidate = {
        "vod_id": "same",
        "_resource_timestamp": 0,
        "updated_at": "right-rank-source",
    }

    result = merge_resource_rows(
        current, candidate,
        current_preference=_preference(timestamp=1.0),
        candidate_preference=_preference(timestamp=2.0),
        item_is_dict=False,
    )

    assert result["_resource_timestamp"] == 0


def test_timestamp_tie_uses_left_and_missing_raw_value_falls_back_to_rank():
    tied = merge_resource_rows(
        {"vod_id": "same", "updated_at": "left-raw"},
        {"vod_id": "same", "updated_at": "right-raw"},
        current_preference=_preference(timestamp=2.0),
        candidate_preference=_preference(timestamp=2.0),
        item_is_dict=False,
    )
    fallback = merge_resource_rows(
        {"vod_id": "same"}, {"vod_id": "same"},
        current_preference=_preference(timestamp=3.0),
        candidate_preference=_preference(timestamp=2.0),
        item_is_dict=False,
    )

    assert tied["_resource_timestamp"] == "left-raw"
    assert fallback["_resource_timestamp"] == 3.0


def test_zero_timestamp_ranks_do_not_synthesize_timestamp():
    result = merge_resource_rows(
        {"vod_id": "same"}, {"vod_id": "same"},
        current_preference=_preference(),
        candidate_preference=_preference(),
        item_is_dict=False,
    )

    assert "_resource_timestamp" not in result


def test_validated_groups_survives_same_id_and_is_removed_when_id_changes():
    same_id = merge_resource_rows(
        {"vod_id": "same", "_validated_groups": 2},
        {"vod_id": "same"},
        current_preference=_preference(),
        candidate_preference=_preference(),
        item_is_dict=False,
    )
    changed_id = merge_resource_rows(
        {"vod_id": "left", "_validated_groups": 2},
        {"vod_id": "right"},
        current_preference=_preference(timestamp=1.0),
        candidate_preference=_preference(timestamp=2.0),
        item_is_dict=False,
    )

    assert same_id["_validated_groups"] == 2
    assert "_validated_groups" not in changed_id


def test_primary_candidate_loses_validation_when_left_password_reclaims_id():
    result = merge_resource_rows(
        {"vod_id": "left"},
        {"vod_id": "right", "_validated_groups": 4},
        current_preference=_preference(password=1),
        candidate_preference=_preference(match=1, password=0),
        item_is_dict=False,
    )

    assert result["vod_id"] == "left"
    assert "_validated_groups" not in result


def test_merge_returns_new_plain_shallow_dict_without_mutating_inputs():
    nested = {"value": 1}
    current = UserDict({"vod_id": "same", "nested": nested})
    candidate = {"vod_id": "same", "source": "secondary"}

    result = merge_resource_rows(
        current, candidate,
        current_preference=_preference(),
        candidate_preference=_preference(),
        item_is_dict=False,
    )

    assert type(result) is dict
    assert result is not current and result is not candidate
    assert result["nested"] is nested
    assert current == {"vod_id": "same", "nested": nested}
    assert candidate == {"vod_id": "same", "source": "secondary"}


@pytest.mark.parametrize(("invalid", "error_type"), [
    (1, TypeError),
    (object(), TypeError),
    ([('key', 'value', 'extra')], ValueError),
])
def test_truthy_nonconvertible_inputs_keep_v70_error_type(v70, invalid, error_type):
    with pytest.raises(error_type):
        v70.Spider()._merge_resource_rows(invalid, {}, None, "")
    with pytest.raises(error_type):
        merge_resource_rows(
            invalid, {},
            current_preference=_preference(),
            candidate_preference=_preference(),
            item_is_dict=False,
        )

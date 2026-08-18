import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
FIXTURE_PATH = (
    ROOT / "tests" / "fixtures" / "v80_p4_douban_json_response_fixtures.json"
)

EXPECTED_CASE_IDS = (
    "collection_list",
    "recommend_filter_list",
    "mobile_search_list",
    "movie_search_subjects_list",
    "subject_detail",
    "action_success",
    "action_auth_expired",
    "action_rejected",
)


def _fixture():
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _canonical_bytes(payload):
    return json.dumps(
        payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True,
    ).encode("utf-8")


def test_fixture_inventory_and_serialization_contract_are_frozen():
    fixture = _fixture()

    assert fixture["schema"] == "v80-p4-douban-json-response-fixtures/1"
    assert fixture["serialization"] == {
        "ensure_ascii": False,
        "separators": [",", ":"],
        "sort_keys": True,
    }
    assert tuple(case["id"] for case in fixture["cases"]) == EXPECTED_CASE_IDS
    assert len(EXPECTED_CASE_IDS) == len(set(EXPECTED_CASE_IDS))


def test_fixture_canonical_byte_sizes_are_exact():
    fixture = _fixture()

    actual = {
        case["id"]: len(_canonical_bytes(case["payload"]))
        for case in fixture["cases"]
    }
    expected = {
        case["id"]: case["expected_canonical_bytes"]
        for case in fixture["cases"]
    }

    assert actual == expected == {
        "collection_list": 339,
        "recommend_filter_list": 205,
        "mobile_search_list": 214,
        "movie_search_subjects_list": 101,
        "subject_detail": 561,
        "action_success": 7,
        "action_auth_expired": 50,
        "action_rejected": 34,
    }


def test_fixture_shapes_cover_all_frozen_douban_json_consumers():
    cases = {case["id"]: case["payload"] for case in _fixture()["cases"]}

    assert isinstance(cases["collection_list"]["subject_collection_items"], list)
    assert isinstance(cases["recommend_filter_list"]["items"], list)
    assert isinstance(cases["mobile_search_list"]["subjects"]["items"], list)
    assert isinstance(cases["movie_search_subjects_list"]["subjects"], list)
    assert cases["subject_detail"]["title"] == "详情剧集"
    assert cases["action_success"] == {"r": 0}
    assert cases["action_auth_expired"]["code"] == "403"
    assert cases["action_rejected"]["r"] == 1


def test_ceiling_candidate_has_measured_headroom_without_copying_tmdb_limit():
    fixture = _fixture()
    ceiling = fixture["ceiling_candidate_bytes"]
    largest_fixture = max(
        case["expected_canonical_bytes"] for case in fixture["cases"]
    )
    projected_page = largest_fixture * fixture["maximum_endpoint_page_size"]

    assert fixture["maximum_endpoint_page_size"] == 50
    assert largest_fixture == 561
    assert projected_page == 28050
    assert ceiling == 512 * 1024
    assert ceiling >= projected_page * 16
    assert ceiling < 2 * 1024 * 1024

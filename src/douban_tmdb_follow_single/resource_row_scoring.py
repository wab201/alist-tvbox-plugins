from typing import Any, Tuple

from .resource_matching import _resource_years, _tracking_season
from .resource_normalization import extract_season
from .resource_scoring import BOUND_RESOURCE_SCORE, score_resource_title


RESOURCE_LINK_SCAN_LIMIT = 32
_DIRECT_TITLE_KEYS = (
    "vod_name", "name", "title", "vod_title", "show_name", "work_title", "note",
)
_LINK_TITLE_KEYS = ("work_title", "title", "note")
_YEAR_TEXT_KEYS = (
    "vod_name", "name", "title", "work_title", "note", "vod_year", "vod_remarks",
)


def _append_unique(values, value: Any) -> None:
    text = str(value or "").strip()
    if text and text not in values:
        values.append(text)


def _links(row: dict):
    values = row.get("links")
    return values[:RESOURCE_LINK_SCAN_LIMIT] if isinstance(values, list) else ()


def resource_work_title_values(row: Any) -> Tuple[str, ...]:
    if not isinstance(row, dict):
        return ()
    values = []
    _append_unique(values, row.get("work_title"))
    for link in _links(row):
        if isinstance(link, dict):
            _append_unique(values, link.get("work_title"))
    return tuple(values)


def resource_title_values(row: Any) -> Tuple[str, ...]:
    if not isinstance(row, dict):
        return ()
    values = []
    for key in _DIRECT_TITLE_KEYS:
        _append_unique(values, row.get(key))
    for link in _links(row):
        if not isinstance(link, dict):
            continue
        for key in _LINK_TITLE_KEYS:
            _append_unique(values, link.get(key))
    return tuple(values)


def score_resource_row(
        row: Any,
        aliases: Any,
        target_year: Any = "",
        tracking_season: Any = 1,
        season_count: Any = 0,
        bound_resource_id: Any = "") -> int:
    if not isinstance(row, dict):
        return 0
    work_titles = resource_work_title_values(row)
    title_values = work_titles or resource_title_values(row)
    if not title_values:
        return 0

    resource_id = str(row.get("vod_id") or row.get("id") or "").strip()
    year = str(target_year or "")[:4]
    row_years = _resource_years(" ".join(str(row.get(key) or "") for key in _YEAR_TEXT_KEYS))
    season = _tracking_season(tracking_season)
    best = 0
    for raw_title in title_values:
        result = score_resource_title(
            raw_title,
            aliases,
            tracking_season=tracking_season,
            season_count=season_count,
            resource_id=resource_id,
            bound_resource_id=bound_resource_id,
        )
        if result.score == BOUND_RESOURCE_SCORE:
            return BOUND_RESOURCE_SCORE
        if result.score <= 0:
            continue

        candidate_season = extract_season(raw_title)
        if year and row_years and year not in row_years and candidate_season != season:
            continue
        score = result.score + (30 if year and year in row_years else 0)
        best = max(best, score)
    return best

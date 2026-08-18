from dataclasses import dataclass
from typing import Any, Tuple

from .resource_matching import (
    MATCH,
    _resource_years,
    _tracking_season,
    match_resource_title,
)
from .resource_normalization import extract_season


BOUND_RESOURCE_SCORE = 10000
EXACT_TITLE_SCORE = 500
DECORATED_TITLE_SCORE = 470
EXACT_SEASON_SCORE = 80
EXACT_YEAR_SCORE = 30


@dataclass(frozen=True)
class ResourceScore:
    score: int
    outcome: str
    reason: str
    components: Tuple[Tuple[str, int], ...] = ()


def score_resource_title(
        raw_title: Any,
        aliases: Any,
        target_year: Any = "",
        tracking_season: Any = 1,
        season_count: Any = 0,
        candidate_year_text: Any = "",
        resource_id: Any = "",
        bound_resource_id: Any = "") -> ResourceScore:
    decision = match_resource_title(
        raw_title,
        aliases,
        target_year=target_year,
        tracking_season=tracking_season,
        season_count=season_count,
        candidate_year_text=candidate_year_text,
    )
    raw_title_present = bool(str(raw_title or "").strip())
    if not raw_title_present or decision.reason == "denied_variant":
        return ResourceScore(0, decision.outcome, decision.reason)

    normalized_resource_id = str(resource_id or "").strip()
    if bound_resource_id and normalized_resource_id == bound_resource_id:
        return ResourceScore(
            BOUND_RESOURCE_SCORE,
            MATCH,
            "bound_resource",
            (("bound_resource", BOUND_RESOURCE_SCORE),),
        )

    if decision.outcome != MATCH:
        return ResourceScore(0, decision.outcome, decision.reason)

    title_score = EXACT_TITLE_SCORE if decision.reason == "exact_title" else DECORATED_TITLE_SCORE
    title_component = "exact_title" if decision.reason == "exact_title" else "decorated_title"
    components = [(title_component, title_score)]

    season = _tracking_season(tracking_season)
    candidate_season = extract_season(raw_title)
    if candidate_season == season:
        components.append(("exact_season", EXACT_SEASON_SCORE))

    year = str(target_year or "")[:4]
    candidate_years = _resource_years("%s %s" % (str(raw_title or ""), str(candidate_year_text or "")))
    if year and year in candidate_years:
        components.append(("exact_year", EXACT_YEAR_SCORE))

    return ResourceScore(
        sum(points for _name, points in components),
        MATCH,
        decision.reason,
        tuple(components),
    )

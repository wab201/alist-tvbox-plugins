import re
from dataclasses import dataclass
from typing import Any

from .resource_normalization import extract_season, normalize_media_title


MATCH = "match"
CONFLICT = "conflict"
INSUFFICIENT = "insufficient"
_DENIED_VARIANTS = (
    "解说", "剪辑", "预告", "花絮", "幕后", "制作特辑", "特辑", "特别节目", "特别篇",
    "衍生", "番外", "彩蛋", "剧场版", "电影版", "真人版", "重制版", "翻拍",
    "reaction", "react", "recap", "trailer", "behindthescenes", "makingof",
)


@dataclass(frozen=True)
class MatchDecision:
    outcome: str
    reason: str


def _positive_int(value: Any, default: int) -> int:
    try:
        result = int(value)
    except Exception:
        return default
    return result if result > 0 else default


def _tracking_season(value: Any) -> int:
    try:
        result = int(value)
    except Exception:
        try:
            result = int(float(value))
        except Exception:
            return 1
    return result if result > 0 else 1


def _resource_years(value: Any):
    return frozenset(re.findall(r"(?<!\d)((?:19|20)\d{2})(?!\d)", str(value or "")))


def _alias_values(value: Any):
    if isinstance(value, (list, tuple, set)):
        return value
    return str(value).split("\n") if value else ()


def _decorated_alias(raw_title: Any, aliases) -> str:
    actual = normalize_media_title(raw_title)
    matched = sorted(
        {alias for alias in aliases if len(alias) >= 4 and alias in actual},
        key=len,
        reverse=True,
    )
    if not matched:
        return ""
    remainder = actual
    for alias in sorted(aliases, key=len, reverse=True):
        if len(alias) >= 2:
            remainder = remainder.replace(alias, "")
    allowed = (
        r"(?:电视剧|连续剧|剧集|网剧|短剧|国产剧|美剧|英剧|韩剧|日剧|泰剧|港剧|台剧|"
        r"动画|动漫|纪录片|综艺|合集|全季|电影|动作|剧情|悬疑|奇幻|冒险|科幻|犯罪|家庭|喜剧|爱情|惊悚)",
        r"(?:(?:19|20)\d{2}|tmdb\d+)",
        r"(?:第[零〇一二两三四五六七八九十百壹贰叁肆伍陆柒捌玖拾佰\d]{1,6}(?:季|部)|"
        r"season0*\d{1,2}|s0*\d{1,2}(?!\d)|[零〇一二两三四五六七八九十百\d]{1,4}(?:季|部)(?:全)?)",
        r"(?:附(?:前)?[零〇一二两三四五六七八九十百\d]{1,4}(?:季|部)|附前两季|附前\d+季)",
        r"(?:8k|4k|2160p|1080p|720p|uhd|hdr10plus|hdr10|hdr|dv|dolbyvision|杜比视界|"
        r"高码率|高码|原盘|remux|bluray|webdl|webrip|hdtv|nf|netflix|hbomax)",
        r"(?:s0*\d{1,2}e(?:p)?0*\d{1,3}(?:e(?:p)?0*\d{1,3})?|e(?:p)?0*\d{1,3})",
        r"(?:(?:更新至|更至|更新|首播|更)?第?0*\d{1,3}(?:集|话|期)(?:全|完结)?|"
        r"全0*\d{1,3}(?:集|话|期)|(?:更新至|更至|更新)0*\d{1,3}|完结)",
        r"(?:h26[45]|x26[45]|hevc|avc|aac\d*|ddp\d*|atmos|multi|mkv|mp4|ts)",
        r"(?:内封|内嵌|外挂|官方|官译|精修|简中|繁中|简繁|中英|韩英|英韩|多国|"
        r"中文字幕|字幕|中字|特效|音轨|双语|国语|粤语|英语|韩语|日语)",
        r"(?:\d+(?:tb|gb|mb|g|m))",
        r"(?:更新至|更至|更新|首更至|首更|首播至|首播|附前|附|前|更|至|全)",
        r"(?:hiveweb|telegram|telegraph|tg|pansou|盘搜|电报|电报群|"
        r"网盘|云盘|分享|夸克|阿里|百度|迅雷|天翼|移动|115|123|uc|pikpak|quark|"
        r"baidu|aliyun|alipan|xunlei|drive|cloud)",
    )
    previous = None
    while remainder and remainder != previous:
        previous = remainder
        for pattern in allowed:
            remainder = re.sub(pattern, "", remainder, flags=re.I)
    return matched[0] if not remainder else ""


def match_resource_title(
        raw_title: Any,
        aliases: Any,
        target_year: Any = "",
        tracking_season: Any = 1,
        season_count: Any = 0,
        candidate_year_text: Any = "") -> MatchDecision:
    actual = normalize_media_title(raw_title)
    if not actual:
        return MatchDecision(INSUFFICIENT, "missing_title")
    if any(marker in actual for marker in _DENIED_VARIANTS):
        return MatchDecision(CONFLICT, "denied_variant")

    normalized_aliases = set()
    for value in _alias_values(aliases):
        normalized = normalize_media_title(value)
        if normalized:
            normalized_aliases.add(normalized)

    season = _tracking_season(tracking_season)
    count = _positive_int(season_count, 0)
    single_season = count == 1 or (count <= 0 and season == 1)
    candidate_season = extract_season(raw_title)
    if candidate_season and candidate_season != season and not single_season:
        return MatchDecision(CONFLICT, "season_conflict")

    year = str(target_year or "")[:4]
    candidate_years = _resource_years("%s %s" % (str(raw_title or ""), str(candidate_year_text or "")))
    if year and candidate_years and year not in candidate_years and candidate_season != season:
        return MatchDecision(CONFLICT, "year_conflict")

    if not normalized_aliases:
        return MatchDecision(INSUFFICIENT, "missing_aliases")
    if actual in normalized_aliases:
        return MatchDecision(MATCH, "exact_title")
    if _decorated_alias(raw_title, normalized_aliases):
        return MatchDecision(MATCH, "decorated_title")
    return MatchDecision(INSUFFICIENT, "non_exact_title")

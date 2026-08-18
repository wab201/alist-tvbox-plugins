from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Tuple


def _model_text(value: Any) -> str:
    return str(value or "").strip()


def _model_text_tuple(value: Any) -> Tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    result = []
    for item in value:
        text = _model_text(item)
        if text and text not in result:
            result.append(text)
    return tuple(result)


def _model_non_negative_int(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


@dataclass(frozen=True)
class MediaIdentity:
    source_id: str = ""
    media_type: str = "movie"
    tmdb_id: int = 0
    title: str = ""
    original_title: str = ""
    title_aliases: Tuple[str, ...] = ()
    year: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "title_aliases", _model_text_tuple(self.title_aliases))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_id": self.source_id,
            "media_type": self.media_type,
            "tmdb_id": self.tmdb_id,
            "title": self.title,
            "original_title": self.original_title,
            "title_aliases": list(self.title_aliases),
            "year": self.year,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "MediaIdentity":
        return cls(
            source_id=_model_text(value.get("source_id")),
            media_type=_model_text(value.get("media_type")) or "movie",
            tmdb_id=_model_non_negative_int(value.get("tmdb_id")),
            title=_model_text(value.get("title")),
            original_title=_model_text(value.get("original_title")),
            title_aliases=value.get("title_aliases"),
            year=_model_text(value.get("year")),
        )


@dataclass(frozen=True)
class ResourceCandidate:
    resource_id: str = ""
    mode: str = "vod"
    provider: str = ""
    work_title: str = ""
    titles: Tuple[str, ...] = ()
    year: str = ""
    source: str = ""
    timestamp: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "titles", _model_text_tuple(self.titles))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "resource_id": self.resource_id,
            "mode": self.mode,
            "provider": self.provider,
            "work_title": self.work_title,
            "titles": list(self.titles),
            "year": self.year,
            "source": self.source,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ResourceCandidate":
        return cls(
            resource_id=_model_text(value.get("resource_id")),
            mode=_model_text(value.get("mode")) or "vod",
            provider=_model_text(value.get("provider")),
            work_title=_model_text(value.get("work_title")),
            titles=value.get("titles"),
            year=_model_text(value.get("year")),
            source=_model_text(value.get("source")),
            timestamp=_model_text(value.get("timestamp")),
        )


@dataclass(frozen=True)
class EpisodeRange:
    season: int = 1
    start_episode: int = 0
    end_episode: int = 0
    explicit: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "season": self.season,
            "start_episode": self.start_episode,
            "end_episode": self.end_episode,
            "explicit": self.explicit,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "EpisodeRange":
        season = _model_non_negative_int(value.get("season")) or 1
        return cls(
            season=season,
            start_episode=_model_non_negative_int(value.get("start_episode")),
            end_episode=_model_non_negative_int(value.get("end_episode")),
            explicit=bool(value.get("explicit", False)),
        )


@dataclass(frozen=True)
class PlaySource:
    target: str = ""
    label: str = ""
    resource_id: str = ""
    mode: str = "vod"
    provider: str = ""
    episode: EpisodeRange = field(default_factory=EpisodeRange)

    def __post_init__(self) -> None:
        if isinstance(self.episode, Mapping):
            object.__setattr__(self, "episode", EpisodeRange.from_dict(self.episode))
        elif not isinstance(self.episode, EpisodeRange):
            object.__setattr__(self, "episode", EpisodeRange())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "target": self.target,
            "label": self.label,
            "resource_id": self.resource_id,
            "mode": self.mode,
            "provider": self.provider,
            "episode": self.episode.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PlaySource":
        return cls(
            target=_model_text(value.get("target")),
            label=_model_text(value.get("label")),
            resource_id=_model_text(value.get("resource_id")),
            mode=_model_text(value.get("mode")) or "vod",
            provider=_model_text(value.get("provider")),
            episode=value.get("episode"),
        )

from dataclasses import dataclass
from typing import Any, Mapping, Sequence, Tuple


RESOURCE_MODES = ("vod1", "vod", "pansou", "telegram")
SUPPLEMENT_MODES = ("pansou", "telegram")
GENERIC_ID_KEYS = ("vod_id", "id")
LINK_KEYS = ("url", "link", "share_url", "target")

GENERIC_SCHEMAS = (
    ("list", "v70.generic.list.v1"),
    ("data", "v70.generic.data-list.v1"),
    ("items", "v70.generic.items.v1"),
    ("results", "v70.generic.results.v1"),
)
RESULTS_LINKS_SCHEMA = "v70.supplement.results-links.v1"
RESULTS_DIRECT_SCHEMA = "v70.supplement.results-direct.v1"
MERGED_SCHEMA = "v70.supplement.merged-by-type.v1"
GENERIC_ROW_SCHEMA = "v70.row.generic-id.v1"
SUPPLEMENT_ROW_SCHEMA = "v70.row.supplement-link.v1"


@dataclass(frozen=True)
class SchemaMatch:
    schema_id: str
    path: str
    row_count: int

    def to_dict(self):
        return {
            "schema_id": self.schema_id,
            "path": self.path,
            "row_count": self.row_count,
        }


def _schema_mode(value: Any) -> str:
    mode = str(value or "").strip().lower()
    if mode not in RESOURCE_MODES:
        raise ValueError("unsupported resource mode: %s" % mode)
    return mode


def _schema_text(value: Any) -> str:
    if isinstance(value, (dict, list, tuple, set)):
        return ""
    return str(value or "").strip()


def _schema_first(row: Mapping[str, Any], keys: Sequence[str]) -> str:
    for key in keys:
        value = _schema_text(row.get(key))
        if value:
            return value
    return ""


def _mapping_rows(values: Sequence[Any]) -> Tuple[Mapping[str, Any], ...]:
    return tuple(value for value in values if isinstance(value, Mapping))


def _locate_generic(payload: Any, path: str = "$"):
    if not isinstance(payload, Mapping):
        return None, ()
    for key, schema_id in GENERIC_SCHEMAS:
        values = payload.get(key)
        if isinstance(values, list):
            rows = _mapping_rows(values)
            return SchemaMatch(schema_id, path + "." + key, len(rows)), rows
    nested = payload.get("data")
    if isinstance(nested, Mapping):
        return _locate_generic(nested, path + ".data")
    return None, ()


def _supplement_locations(payload: Any):
    if not isinstance(payload, Mapping):
        return (), ()
    containers = []
    if isinstance(payload.get("data"), Mapping):
        containers.append((payload["data"], "$.data"))
    containers.append((payload, "$"))
    matches = []
    streams = []
    for container, path in containers:
        results = container.get("results")
        if isinstance(results, list):
            links_seen = False
            direct_seen = False
            links_count = 0
            direct_count = 0
            for result in results:
                if not isinstance(result, Mapping):
                    continue
                links = result.get("links")
                if isinstance(links, list):
                    links_seen = True
                    links_count += len(_mapping_rows(links))
                    streams.append((links, result, ""))
                elif _schema_first(result, LINK_KEYS):
                    direct_seen = True
                    direct_count += 1
                    streams.append(((result,), {}, ""))
            if links_seen:
                matches.append(SchemaMatch(RESULTS_LINKS_SCHEMA, path + ".results", links_count))
            if direct_seen:
                matches.append(SchemaMatch(RESULTS_DIRECT_SCHEMA, path + ".results", direct_count))
        merged = container.get("merged_by_type")
        if isinstance(merged, Mapping):
            valid = [(hint, links) for hint, links in merged.items() if isinstance(links, list)]
            if not merged or valid:
                matches.append(SchemaMatch(
                    MERGED_SCHEMA,
                    path + ".merged_by_type",
                    sum(len(_mapping_rows(links)) for _hint, links in valid),
                ))
            for hint, links in valid:
                streams.append((links, {}, _schema_text(hint)))
    return tuple(matches), tuple(streams)


def detect_resource_payload(mode: Any, payload: Any) -> Tuple[SchemaMatch, ...]:
    normalized_mode = _schema_mode(mode)
    generic, _rows = _locate_generic(payload)
    matches = [generic] if generic is not None else []
    if normalized_mode in SUPPLEMENT_MODES:
        supplements, _streams = _supplement_locations(payload)
        matches.extend(supplements)
    return tuple(matches)


def classify_resource_row(mode: Any, row: Any) -> Tuple[str, ...]:
    normalized_mode = _schema_mode(mode)
    if not isinstance(row, Mapping):
        return ()
    schemas = []
    if _schema_first(row, GENERIC_ID_KEYS):
        schemas.append(GENERIC_ROW_SCHEMA)
    if normalized_mode in SUPPLEMENT_MODES and _schema_first(row, LINK_KEYS):
        schemas.append(SUPPLEMENT_ROW_SCHEMA)
    return tuple(schemas)


def generic_rows(payload: Any) -> Tuple[Mapping[str, Any], ...]:
    _match, rows = _locate_generic(payload)
    return rows


def supplement_streams(payload: Any):
    _matches, streams = _supplement_locations(payload)
    return streams

from dataclasses import dataclass
from typing import Any, Dict, Tuple
from urllib.parse import unquote

from .resource_models import ResourceCandidate
from .resource_schema import (
    GENERIC_ROW_SCHEMA,
    GENERIC_SCHEMAS,
    MERGED_SCHEMA,
    RESULTS_DIRECT_SCHEMA,
    RESULTS_LINKS_SCHEMA,
    SUPPLEMENT_ROW_SCHEMA,
    SchemaMatch,
    detect_resource_payload,
)
from .resource_shadow import map_resource_payload


GENERIC_PAYLOAD_SCHEMAS = tuple(schema_id for _key, schema_id in GENERIC_SCHEMAS)
SUPPLEMENT_PAYLOAD_SCHEMAS = GENERIC_PAYLOAD_SCHEMAS + (
    RESULTS_LINKS_SCHEMA,
    RESULTS_DIRECT_SCHEMA,
    MERGED_SCHEMA,
)


def _provider_text(value: Any) -> str:
    return str(value or "").strip()


@dataclass(frozen=True)
class ResourceProviderAdapter:
    mode: str
    endpoint_mode: str
    payload_schemas: Tuple[str, ...]
    row_schemas: Tuple[str, ...]

    def search_request(self, query: Any) -> Dict[str, Any]:
        params = {"wd": _provider_text(query), "pg": 1}
        if self.mode in ("vod1", "vod"):
            params.update({"size": 50, "ac": "detail"})
        elif self.mode == "telegram":
            params["web"] = "true"
        return {"endpoint_mode": self.endpoint_mode, "params": params}

    def detail_request(self, resource_id: Any, title: Any = "") -> Dict[str, Any]:
        value = _provider_text(resource_id)
        if self.mode in ("vod1", "vod"):
            params = {"ids": value, "ac": "detail"}
        elif self.mode == "pansou":
            params = {"id": unquote(value)}
        else:
            params = {
                "id": unquote(value),
                "ac": "detail",
                "title": _provider_text(title),
                "web": "true",
            }
        return {"endpoint_mode": self.endpoint_mode, "params": params}

    def detect(self, payload: Any) -> Tuple[SchemaMatch, ...]:
        return tuple(
            match for match in detect_resource_payload(self.mode, payload)
            if match.schema_id in self.payload_schemas
        )

    def normalize(self, payload: Any) -> Tuple[ResourceCandidate, ...]:
        if not self.detect(payload):
            return ()
        return map_resource_payload(self.mode, payload)


RESOURCE_PROVIDER_ADAPTERS = (
    ResourceProviderAdapter(
        "vod1", "vod1", GENERIC_PAYLOAD_SCHEMAS, (GENERIC_ROW_SCHEMA,),
    ),
    ResourceProviderAdapter(
        "vod", "vod", GENERIC_PAYLOAD_SCHEMAS, (GENERIC_ROW_SCHEMA,),
    ),
    ResourceProviderAdapter(
        "pansou", "pansou", SUPPLEMENT_PAYLOAD_SCHEMAS,
        (GENERIC_ROW_SCHEMA, SUPPLEMENT_ROW_SCHEMA),
    ),
    ResourceProviderAdapter(
        "telegram", "tg-search", SUPPLEMENT_PAYLOAD_SCHEMAS,
        (GENERIC_ROW_SCHEMA, SUPPLEMENT_ROW_SCHEMA),
    ),
)
_RESOURCE_PROVIDER_BY_MODE = {
    "vod1": RESOURCE_PROVIDER_ADAPTERS[0],
    "vod": RESOURCE_PROVIDER_ADAPTERS[1],
    "pansou": RESOURCE_PROVIDER_ADAPTERS[2],
    "telegram": RESOURCE_PROVIDER_ADAPTERS[3],
}


def get_resource_provider_adapter(mode: Any) -> ResourceProviderAdapter:
    normalized = _provider_text(mode).lower()
    try:
        return _RESOURCE_PROVIDER_BY_MODE[normalized]
    except KeyError:
        raise ValueError("unsupported resource mode: %s" % normalized) from None

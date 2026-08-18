"""Pure Douban HTML response byte policy for isolated V80 validation."""

from types import MappingProxyType as _v80_douban_html_response_mapping_proxy


V80_DOUBAN_HTML_RESPONSE_LIMITS = _v80_douban_html_response_mapping_proxy({
    "max_response_bytes": 256 * 1024,
})

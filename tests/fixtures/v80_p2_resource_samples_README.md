# V80 P2 resource samples

This fixture is a synthetic contract sample for the P2 shadow models. It was
derived from the field shapes already handled by the frozen V70 source, not
from captured production traffic.

All hosts use either reserved `.invalid` names or public provider host shapes
with invented paths. There are no credentials, subscription URLs, cookies,
tokens, signed media URLs, or deployment identifiers. Password query fields
contain dummy values only so identity deduplication can be tested.

The fixture covers `vod1`, `vod`, `pansou`, and `telegram`, including aliases,
missing optional fields, duplicate share links, and multi-group detail data.
These shadow assertions observe deterministic mapping only. They do not take
over V70 routing, scoring, validation, playback, networking, or cache behavior.

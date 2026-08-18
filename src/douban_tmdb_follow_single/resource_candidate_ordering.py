from dataclasses import dataclass
from typing import Any, Iterable, Tuple


RESOURCE_MODE_ORDER = ("vod1", "vod", "pansou", "telegram")


@dataclass(frozen=True)
class CandidateOrderEntry:
    """One precomputed candidate used by the pure ordering contract."""

    row: Any
    score: int
    preference: Tuple[Any, ...] = ()
    mode: str = "vod"
    provider: str = ""


def _provider_bucket(provider: Any) -> str:
    return provider or "unknown"


def order_resource_candidates(
        entries: Iterable[CandidateOrderEntry],
        modes: Iterable[str] = RESOURCE_MODE_ORDER,
) -> Tuple[Any, ...]:
    """Filter and fairly order candidates using only precomputed metadata.

    The input sequence supplies the stable tie-break order. No identity merge,
    score calculation, provider detection, or candidate mutation occurs here.
    """
    candidates = tuple(entries or ())
    ranked = {}
    for input_index, entry in enumerate(candidates):
        if entry.score <= 0:
            continue
        mode = entry.mode or "vod"
        ranked.setdefault(mode, []).append((entry, input_index))

    for mode_entries in ranked.values():
        mode_entries.sort(key=lambda value: (value[0].preference, -value[1]), reverse=True)

    fair_by_mode = {}
    for mode, mode_entries in ranked.items():
        provider_queues = {}
        provider_order = []
        for entry, _input_index in mode_entries:
            provider = _provider_bucket(entry.provider)
            if provider not in provider_queues:
                provider_order.append(provider)
            provider_queues.setdefault(provider, []).append(entry)
        fair_entries = []
        provider_depth = 0
        while True:
            added = False
            for provider in provider_order:
                queue = provider_queues.get(provider) or ()
                if provider_depth < len(queue):
                    fair_entries.append(queue[provider_depth])
                    added = True
            if not added:
                break
            provider_depth += 1
        fair_by_mode[mode] = tuple(fair_entries)

    mode_order = list(modes or RESOURCE_MODE_ORDER)
    mode_order.extend(mode for mode in ranked if mode not in mode_order)
    ordered = []
    mode_depth = 0
    while True:
        added = False
        for mode in mode_order:
            mode_entries = fair_by_mode.get(mode) or ()
            if mode_depth < len(mode_entries):
                ordered.append(mode_entries[mode_depth])
                added = True
        if not added:
            break
        mode_depth += 1
    return tuple(entry.row for entry in ordered)

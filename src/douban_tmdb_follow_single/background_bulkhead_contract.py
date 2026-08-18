"""Independent admission limits for isolated V80 background work."""

import threading


BACKGROUND_BULKHEAD_LIMITS = {
    "resource_completion": 10,
    "history": 1,
    "route_probe": 5,
}


class BackgroundBulkheadLease(object):
    """Release one admitted task exactly once."""

    __slots__ = (
        "_controller", "_lane", "_generation", "_finished", "_lock",
    )

    def __init__(self, controller, lane, generation):
        self._controller = controller
        self._lane = lane
        self._generation = generation
        self._finished = False
        self._lock = threading.Lock()

    def finish(self):
        with self._lock:
            if self._finished:
                return False
            self._finished = True
        return self._controller._release(self._lane, self._generation)


class BackgroundBulkheadController(object):
    """Non-blocking, generation-fenced capacity for fixed background lanes."""

    __slots__ = (
        "_lock", "_limits", "_generation", "_inflight", "_rejected",
    )

    def __init__(self, generation=0):
        limits = dict(BACKGROUND_BULKHEAD_LIMITS)
        self._lock = threading.RLock()
        self._limits = limits
        self._generation = int(generation)
        self._inflight = dict((lane, 0) for lane in limits)
        self._rejected = dict((lane, 0) for lane in limits)

    def reset(self, generation):
        with self._lock:
            self._generation = int(generation)
            self._inflight = dict((lane, 0) for lane in self._limits)
            self._rejected = dict((lane, 0) for lane in self._limits)
            return self._generation

    def acquire(self, lane, expected_generation):
        lane = str(lane or "")
        if lane not in self._limits:
            raise ValueError("unknown background bulkhead lane")
        generation = int(expected_generation)
        with self._lock:
            if generation != self._generation:
                return None
            if self._inflight[lane] >= self._limits[lane]:
                self._rejected[lane] += 1
                return None
            self._inflight[lane] += 1
            return BackgroundBulkheadLease(self, lane, generation)

    def _release(self, lane, generation):
        with self._lock:
            if generation != self._generation:
                return False
            if self._inflight.get(lane, 0) <= 0:
                return False
            self._inflight[lane] -= 1
            return True

    def snapshot(self):
        with self._lock:
            return {
                "generation": self._generation,
                "limits": dict(self._limits),
                "inflight": dict(self._inflight),
                "rejected": dict(self._rejected),
            }

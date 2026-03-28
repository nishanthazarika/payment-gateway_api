import itertools
from enum import Enum
from gateway.config import Target


class Strategy(str, Enum):
    ROUND_ROBIN = "round_robin"
    WEIGHTED_ROUND_ROBIN = "weighted_round_robin"
    LEAST_CONNECTIONS = "least_connections"


class LoadBalancer:
    def __init__(self, strategy: Strategy = Strategy.WEIGHTED_ROUND_ROBIN):
        self.strategy = strategy
        self._rr_counters: dict[str, itertools.cycle] = {}
        self._connections: dict[str, int] = {}  # url -> active count

    def pick_target(self, service: str, targets: list[Target]) -> Target | None:
        healthy = [t for t in targets if t.healthy]
        if not healthy:
            return None

        if self.strategy == Strategy.ROUND_ROBIN:
            return self._round_robin(service, healthy)
        elif self.strategy == Strategy.WEIGHTED_ROUND_ROBIN:
            return self._weighted_round_robin(service, healthy)
        elif self.strategy == Strategy.LEAST_CONNECTIONS:
            return self._least_connections(healthy)

    def _round_robin(self, service: str, targets: list[Target]) -> Target:
        if service not in self._rr_counters:
            self._rr_counters[service] = itertools.cycle(targets)
        return next(self._rr_counters[service])

    def _weighted_round_robin(self, service: str, targets: list[Target]) -> Target:
        # expand targets by weight: [A(w=3), B(w=1)] -> [A, A, A, B]
        key = f"{service}_weighted"
        if key not in self._rr_counters:
            expanded = []
            for t in targets:
                expanded.extend([t] * t.weight)
            self._rr_counters[key] = itertools.cycle(expanded)
        return next(self._rr_counters[key])

    def _least_connections(self, targets: list[Target]) -> Target:
        return min(targets, key=lambda t: self._connections.get(t.url, 0))

    def on_request_start(self, url: str):
        self._connections[url] = self._connections.get(url, 0) + 1

    def on_request_end(self, url: str):
        self._connections[url] = max(0, self._connections.get(url, 0) - 1)

    def invalidate(self, service: str):
        """Call when targets change (health check failure, etc.)."""
        self._rr_counters.pop(service, None)
        self._rr_counters.pop(f"{service}_weighted", None)
import time
from enum import Enum
from dataclasses import dataclass, field


class CircuitState(str, Enum):
    CLOSED = "closed"        # normal operation, requests flow through
    OPEN = "open"            # failures exceeded threshold, reject fast
    HALF_OPEN = "half_open"  # testing if service recovered


@dataclass
class CircuitStats:
    state: CircuitState = CircuitState.CLOSED
    failure_count: int = 0
    success_count: int = 0
    last_failure_time: float = 0.0
    half_open_calls: int = 0


class CircuitBreaker:
    """
    Per-service circuit breaker implementing the three-state pattern:
    
    CLOSED  --[failures >= threshold]--> OPEN
    OPEN    --[timeout elapsed]-------->  HALF_OPEN
    HALF_OPEN --[success]--------------> CLOSED
    HALF_OPEN --[failure]--------------> OPEN
    """

    def __init__(self, failure_threshold: int = 5, recovery_timeout: int = 30, half_open_max: int = 3):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max = half_open_max
        self._circuits: dict[str, CircuitStats] = {}

    def get_circuit(self, service: str) -> CircuitStats:
        if service not in self._circuits:
            self._circuits[service] = CircuitStats()
        return self._circuits[service]

    def can_execute(self, service: str) -> bool:
        """Check if a request to this service is allowed."""
        circuit = self.get_circuit(service)

        if circuit.state == CircuitState.CLOSED:
            return True

        if circuit.state == CircuitState.OPEN:
            # check if recovery timeout has elapsed
            if time.time() - circuit.last_failure_time >= self.recovery_timeout:
                circuit.state = CircuitState.HALF_OPEN
                circuit.half_open_calls = 0
                circuit.success_count = 0
                return True
            return False

        if circuit.state == CircuitState.HALF_OPEN:
            return circuit.half_open_calls < self.half_open_max

        return False

    def on_success(self, service: str):
        """Record a successful request."""
        circuit = self.get_circuit(service)

        if circuit.state == CircuitState.HALF_OPEN:
            circuit.success_count += 1
            circuit.half_open_calls += 1
            # if enough successes, close the circuit
            if circuit.success_count >= self.half_open_max:
                self._reset(circuit)
        elif circuit.state == CircuitState.CLOSED:
            # reset failure count on success
            circuit.failure_count = 0

    def on_failure(self, service: str):
        """Record a failed request."""
        circuit = self.get_circuit(service)
        circuit.failure_count += 1
        circuit.last_failure_time = time.time()

        if circuit.state == CircuitState.HALF_OPEN:
            # any failure in half-open immediately opens
            circuit.state = CircuitState.OPEN

        elif circuit.state == CircuitState.CLOSED:
            if circuit.failure_count >= self.failure_threshold:
                circuit.state = CircuitState.OPEN

    def get_state(self, service: str) -> CircuitState:
        return self.get_circuit(service).state

    def get_all_states(self) -> dict[str, dict]:
        """For the admin dashboard / health endpoint."""
        return {
            svc: {
                "state": c.state.value,
                "failures": c.failure_count,
                "last_failure": c.last_failure_time,
            }
            for svc, c in self._circuits.items()
        }

    @staticmethod
    def _reset(circuit: CircuitStats):
        circuit.state = CircuitState.CLOSED
        circuit.failure_count = 0
        circuit.success_count = 0
        circuit.half_open_calls = 0
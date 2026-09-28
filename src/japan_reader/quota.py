from japan_reader.errors import QuotaExceeded
from japan_reader.state import StateStore


class DailyQuota:
    """Límite diario de gasto o llamadas guardado en `counters`."""

    def __init__(self, state: StateStore, key: str, limit: float) -> None:
        self._state = state
        self.key = key
        self.limit = limit

    def check(self) -> None:
        if self._state.get_counter(self.key) >= self.limit:
            raise QuotaExceeded(f"límite diario alcanzado: {self.key} ({self.limit})")

    def add(self, amount: float) -> None:
        self._state.add_counter(self.key, amount)

class SimulationCache:
    def __init__(self):
        self._store = {}

    def generate_key(self, scenario: str, ue_count: int) -> str:
        return f"{scenario}_ue_{ue_count}"

    def get(self, scenario: str, ue_count: int) -> dict:
        return self._store.get(self.generate_key(scenario, ue_count))

    def set(self, scenario: str, ue_count: int, data: dict):
        self._store[self.generate_key(scenario, ue_count)] = data

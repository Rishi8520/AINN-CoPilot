import os
import re
from dataclasses import dataclass
from typing import Optional


VALID_MODES = {"replay", "live"}
DEFAULT_REPLAY_FIXTURE = "phase_bootstrap_normal"
FIXTURE_ID = re.compile(r"^[A-Za-z0-9_-]+$")


def _clean(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _bool_env(name: str, default: bool) -> bool:
    value = _clean(os.environ.get(name))
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class SimulationModeSettings:
    default_mode: str
    replay_fixture: str
    replay_strict_checksums: bool
    live_enabled: bool

    def resolve_mode(self, requested_mode: Optional[str]) -> str:
        requested = _clean(requested_mode)
        if requested in VALID_MODES:
            return requested
        if requested:
            raise ValueError(f"Unsupported simulation mode: {requested}")
        if self.default_mode in VALID_MODES:
            return self.default_mode
        return "replay"


def sanitize_fixture_id(fixture_id: str) -> str:
    cleaned = _clean(fixture_id) or DEFAULT_REPLAY_FIXTURE
    if not FIXTURE_ID.match(cleaned):
        raise ValueError("fixture id must contain only letters, numbers, underscores, and hyphens")
    return cleaned


def get_mode_settings() -> SimulationModeSettings:
    configured_default = _clean(os.environ.get("SIMULATION_DEFAULT_MODE"))
    default_mode = configured_default if configured_default in VALID_MODES else "replay"
    return SimulationModeSettings(
        default_mode=default_mode,
        replay_fixture=sanitize_fixture_id(
            _clean(os.environ.get("SIMULATION_REPLAY_FIXTURE")) or DEFAULT_REPLAY_FIXTURE
        ),
        replay_strict_checksums=_bool_env("SIMULATION_REPLAY_STRICT_CHECKSUMS", True),
        live_enabled=_bool_env("SIMULATION_LIVE_ENABLED", False),
    )

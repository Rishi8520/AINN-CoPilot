import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

from app.simulator.kpi_parser import KPIParser
from app.simulator.mode_config import sanitize_fixture_id


SIMULATION_ROOT = Path(__file__).resolve().parents[2]
REPLAY_ROOT = SIMULATION_ROOT / "fixtures" / "replay"
APP_SCENARIOS_ROOT = SIMULATION_ROOT / "app" / "scenarios"

REPLAY_SCENARIO_ALIASES = {
    "baseline": "phase_bootstrap_normal",
    "normal": "phase_bootstrap_normal",
    "normal_operation": "phase_bootstrap_normal",
    "bootstrap_normal": "phase_bootstrap_normal",
    "phase_bootstrap_normal": "phase_bootstrap_normal",
}


class ReplayError(RuntimeError):
    def __init__(self, code: str, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_fixture_dir(fixture_root: Path, fixture_id: str) -> Path:
    try:
        safe_id = sanitize_fixture_id(fixture_id)
    except ValueError as exc:
        raise ReplayError("invalid_fixture_id", "Replay fixture id is not allowed.") from exc
    fixture_dir = (fixture_root / safe_id).resolve()
    replay_root = fixture_root.resolve()
    if fixture_dir != replay_root / safe_id:
        raise ReplayError("invalid_fixture_id", "Replay fixture id is not allowed.")
    return fixture_dir


def resolve_replay_fixture_for_scenario(scenario: str, configured_fixture: str) -> str:
    alias = (scenario or "").strip()
    fixture_id = REPLAY_SCENARIO_ALIASES.get(alias)
    if not fixture_id:
        raise ReplayError(
            "unsupported_replay_scenario",
            (
                f"Replay scenario '{scenario}' is not supported by the recorded fixtures. "
                "Supported replay scenarios are: "
                + ", ".join(sorted(REPLAY_SCENARIO_ALIASES))
            ),
            {"supported_scenarios": sorted(REPLAY_SCENARIO_ALIASES)},
        )
    configured = sanitize_fixture_id(configured_fixture)
    if fixture_id != configured:
        raise ReplayError(
            "replay_fixture_unavailable",
            f"Scenario '{scenario}' maps to fixture '{fixture_id}', but '{configured}' is configured.",
            {"scenario_fixture": fixture_id, "configured_fixture": configured},
        )
    return fixture_id


class ReplayFixtureService:
    def __init__(self, fixture_root: Path = REPLAY_ROOT, parser=KPIParser):
        self.fixture_root = fixture_root
        self.parser = parser

    def validate_fixture(self, fixture_id: str, *, strict_checksums: bool) -> Dict[str, Any]:
        fixture_dir = _safe_fixture_dir(self.fixture_root, fixture_id)
        manifest_path = fixture_dir / "manifest.json"
        if not manifest_path.exists():
            raise ReplayError("missing_manifest", "Replay fixture manifest.json is missing.")

        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ReplayError("malformed_manifest", f"Replay fixture manifest is malformed: {exc}") from exc

        self._validate_manifest_shape(manifest, fixture_id)
        files = manifest["files"]
        checksum_failures = []
        source_artifacts = []
        scalar_artifact = None

        for entry in files:
            filename = entry["filename"]
            file_path = fixture_dir / filename
            if file_path.resolve().parent != fixture_dir.resolve():
                raise ReplayError("invalid_fixture_file", f"Fixture file path is not allowed: {filename}")
            if not file_path.exists():
                raise ReplayError("missing_fixture_file", f"Replay fixture file is missing: {filename}")
            if file_path.stat().st_size != entry.get("size_bytes"):
                checksum_failures.append(f"{filename}: size mismatch")
            if strict_checksums:
                actual = _sha256(file_path)
                if actual != entry.get("sha256"):
                    checksum_failures.append(f"{filename}: sha256 mismatch")
            source_artifacts.append(filename)
            if entry.get("role") == "omnet_scalar_output":
                scalar_artifact = filename

        if checksum_failures:
            raise ReplayError(
                "checksum_validation_failed",
                "Replay fixture checksum validation failed.",
                {"failures": checksum_failures},
            )
        if not scalar_artifact:
            raise ReplayError("missing_scalar_artifact", "Replay fixture manifest does not identify a scalar output.")

        return {
            "fixture_id": fixture_id,
            "fixture_dir": fixture_dir,
            "manifest": manifest,
            "source_artifacts": source_artifacts,
            "scalar_artifact": scalar_artifact,
            "checksums_verified": bool(strict_checksums),
        }

    def replay(self, fixture_id: str, *, strict_checksums: bool) -> Dict[str, Any]:
        validation = self.validate_fixture(fixture_id, strict_checksums=strict_checksums)
        sca_path = validation["fixture_dir"] / validation["scalar_artifact"]
        parsed = self.parser.parse_sca_file(str(sca_path))
        if parsed.get("error") or not parsed.get("aggregate"):
            raise ReplayError(
                "fixture_parse_failed",
                "The production KPI parser could not parse the replay scalar artifact.",
                {"parser_error": parsed.get("error")},
            )

        manifest = validation["manifest"]
        return {
            "metrics": parsed,
            "recorded_fixture_parameters": self._read_recorded_parameters(
                validation["fixture_dir"], manifest.get("files", [])
            ),
            "provenance": {
                "fixture_id": validation["fixture_id"],
                "label": "recorded_replay",
                "live_simulation": False,
                "created_from_existing_repository_artifact": True,
                "source_artifacts": validation["source_artifacts"],
                "checksums_verified": validation["checksums_verified"],
                "parser": "app.simulator.kpi_parser.KPIParser.parse_sca_file",
                "result_reference": (
                    f"fixtures/replay/{validation['fixture_id']}/{validation['scalar_artifact']}"
                ),
                "manifest_reference": f"fixtures/replay/{validation['fixture_id']}/manifest.json",
                "recorded_run_identifier": manifest.get("run_identifier"),
            },
        }

    @staticmethod
    def _validate_manifest_shape(manifest: Dict[str, Any], expected_fixture_id: str) -> None:
        required = [
            "fixture_id",
            "created_from_existing_repository_artifact",
            "live_simulation",
            "files",
        ]
        missing = [field for field in required if field not in manifest]
        if missing:
            raise ReplayError("malformed_manifest", "Replay manifest is missing required fields.", {"missing": missing})
        if manifest["fixture_id"] != expected_fixture_id:
            raise ReplayError("malformed_manifest", "Replay manifest fixture_id does not match its directory.")
        if manifest["live_simulation"] is not False:
            raise ReplayError("malformed_manifest", "Replay manifest must set live_simulation=false.")
        if manifest["created_from_existing_repository_artifact"] is not True:
            raise ReplayError(
                "malformed_manifest",
                "Replay manifest must mark created_from_existing_repository_artifact=true.",
            )
        if not isinstance(manifest["files"], list) or not manifest["files"]:
            raise ReplayError("malformed_manifest", "Replay manifest files must be a non-empty list.")
        for entry in manifest["files"]:
            for field in ["filename", "role", "size_bytes", "sha256"]:
                if field not in entry:
                    raise ReplayError(
                        "malformed_manifest",
                        "Replay manifest file entry is missing required fields.",
                        {"missing_field": field},
                    )

    @staticmethod
    def _read_recorded_parameters(fixture_dir: Path, files: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
        ini_name = next(
            (entry["filename"] for entry in files if entry.get("role") == "generated_configuration"),
            None,
        )
        if not ini_name:
            return {}
        ini_path = fixture_dir / ini_name
        if not ini_path.exists():
            return {}
        recorded: Dict[str, Any] = {}
        for line in ini_path.read_text(encoding="utf-8", errors="replace").splitlines():
            stripped = line.strip()
            if stripped.startswith("*.numUe"):
                recorded["ue_count"] = stripped.split("=", 1)[1].strip()
            elif stripped.startswith("sim-time-limit"):
                recorded["sim_time_limit"] = stripped.split("=", 1)[1].strip()
            elif stripped.startswith("output-scalar-file"):
                recorded["output_scalar_file"] = stripped.split("=", 1)[1].strip()
            elif stripped.startswith("output-vector-file"):
                recorded["output_vector_file"] = stripped.split("=", 1)[1].strip()
        return recorded

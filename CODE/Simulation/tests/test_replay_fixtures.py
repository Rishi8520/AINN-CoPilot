import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path


SIM_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = SIM_ROOT.parents[1]
FIXTURE_ROOT = SIM_ROOT / "fixtures" / "replay" / "phase_bootstrap_normal"
RUNTIME_RESULTS = SIM_ROOT / "app" / "scenarios" / "results"

sys.path.insert(0, str(SIM_ROOT))
for module_name in list(sys.modules):
    if module_name == "app" or module_name.startswith("app."):
        sys.modules.pop(module_name, None)

from app.simulator.kpi_parser import KPIParser  # noqa: E402
from app.simulator.replay_service import ReplayError, ReplayFixtureService  # noqa: E402


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class ReplayFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest_path = FIXTURE_ROOT / "manifest.json"
        with cls.manifest_path.open("r", encoding="utf-8") as handle:
            cls.manifest = json.load(handle)

    def test_manifest_loads_and_identifies_recorded_fixture(self):
        self.assertEqual(self.manifest["fixture_id"], "phase_bootstrap_normal")
        self.assertTrue(self.manifest["created_from_existing_repository_artifact"])
        self.assertFalse(self.manifest["live_simulation"])

    def test_manifest_files_exist_with_expected_hashes(self):
        for entry in self.manifest["files"]:
            path = FIXTURE_ROOT / entry["filename"]
            self.assertTrue(path.exists(), entry["filename"])
            self.assertEqual(path.stat().st_size, entry["size_bytes"])
            self.assertEqual(sha256(path), entry["sha256"])

    def test_fixture_paths_do_not_point_to_runtime_directory(self):
        for entry in self.manifest["files"]:
            path = (FIXTURE_ROOT / entry["filename"]).resolve()
            self.assertNotIn(RUNTIME_RESULTS.resolve(), path.parents)

    def test_production_kpi_parser_reads_recorded_scalar_fixture(self):
        parsed = KPIParser.parse_sca_file(str(FIXTURE_ROOT / "phase_bootstrap_normal.sca"))
        expected = self.manifest["expected_parser_outputs"]

        self.assertEqual(parsed["raw_scalar_count"], expected["raw_scalar_count"])
        self.assertEqual(len(parsed["per_gnb"]), expected["per_gnb_count"])
        self.assertEqual(len(parsed["per_ue"]), expected["per_ue_count"])
        self.assertEqual(parsed["aggregate"], expected["aggregate"])

        self.assertIsInstance(parsed["per_gnb"], dict)
        self.assertIsInstance(parsed["per_ue"], dict)
        self.assertIn("macCellThroughputDl:simu5g_rateavg", parsed["per_gnb"][0])
        self.assertIn("macDelayDl:mean", parsed["per_ue"][0])

    def test_missing_scalar_file_reports_parser_error(self):
        parsed = KPIParser.parse_sca_file(str(FIXTURE_ROOT / "missing.sca"))

        self.assertEqual(parsed["aggregate"], {})
        self.assertEqual(parsed["per_gnb"], {})
        self.assertEqual(parsed["per_ue"], {})
        self.assertEqual(parsed["raw_scalar_count"], 0)
        self.assertIn("not found", parsed["error"])

    def test_replay_service_validates_manifest_and_uses_production_parser(self):
        service = ReplayFixtureService()

        replayed = service.replay("phase_bootstrap_normal", strict_checksums=True)

        self.assertEqual(replayed["metrics"]["aggregate"], self.manifest["expected_parser_outputs"]["aggregate"])
        self.assertFalse(replayed["provenance"]["live_simulation"])
        self.assertTrue(replayed["provenance"]["checksums_verified"])
        self.assertEqual(
            replayed["provenance"]["parser"],
            "app.simulator.kpi_parser.KPIParser.parse_sca_file",
        )

    def test_replay_service_rejects_path_traversal_fixture_id(self):
        service = ReplayFixtureService()

        with self.assertRaises(ReplayError) as ctx:
            service.validate_fixture("../phase_bootstrap_normal", strict_checksums=True)

        self.assertEqual(ctx.exception.code, "invalid_fixture_id")

    def test_replay_service_checksum_mismatch_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "replay"
            copied = root / "phase_bootstrap_normal"
            shutil.copytree(FIXTURE_ROOT, copied)
            sca_path = copied / "phase_bootstrap_normal.sca"
            with sca_path.open("ab") as handle:
                handle.write(b"\n# checksum mismatch test\n")

            service = ReplayFixtureService(fixture_root=root)
            with self.assertRaises(ReplayError) as ctx:
                service.validate_fixture("phase_bootstrap_normal", strict_checksums=True)

        self.assertEqual(ctx.exception.code, "checksum_validation_failed")

    def test_replay_service_missing_manifest_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "replay"
            copied = root / "phase_bootstrap_normal"
            shutil.copytree(FIXTURE_ROOT, copied)
            (copied / "manifest.json").unlink()

            service = ReplayFixtureService(fixture_root=root)
            with self.assertRaises(ReplayError) as ctx:
                service.validate_fixture("phase_bootstrap_normal", strict_checksums=True)

        self.assertEqual(ctx.exception.code, "missing_manifest")

    def test_replay_service_missing_sca_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "replay"
            copied = root / "phase_bootstrap_normal"
            shutil.copytree(FIXTURE_ROOT, copied)
            (copied / "phase_bootstrap_normal.sca").unlink()

            service = ReplayFixtureService(fixture_root=root)
            with self.assertRaises(ReplayError) as ctx:
                service.validate_fixture("phase_bootstrap_normal", strict_checksums=True)

        self.assertEqual(ctx.exception.code, "missing_fixture_file")

    def test_replay_service_malformed_manifest_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "replay"
            copied = root / "phase_bootstrap_normal"
            shutil.copytree(FIXTURE_ROOT, copied)
            (copied / "manifest.json").write_text('{"fixture_id": "phase_bootstrap_normal"}', encoding="utf-8")

            service = ReplayFixtureService(fixture_root=root)
            with self.assertRaises(ReplayError) as ctx:
                service.validate_fixture("phase_bootstrap_normal", strict_checksums=True)

        self.assertEqual(ctx.exception.code, "malformed_manifest")


if __name__ == "__main__":
    unittest.main()

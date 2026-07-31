import hashlib
import json
import sys
import unittest
from pathlib import Path


SIM_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = SIM_ROOT.parents[1]
FIXTURE_ROOT = SIM_ROOT / "fixtures" / "replay" / "phase_bootstrap_normal"
RUNTIME_RESULTS = SIM_ROOT / "app" / "scenarios" / "results"

sys.path.insert(0, str(SIM_ROOT))

from app.simulator.kpi_parser import KPIParser  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()


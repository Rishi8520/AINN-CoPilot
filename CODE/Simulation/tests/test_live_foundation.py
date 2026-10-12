import importlib.util
from pathlib import Path
import tempfile
import subprocess
import unittest
from unittest.mock import patch


MODULE = Path(__file__).resolve().parents[1] / "live" / "run.py"
SPEC = importlib.util.spec_from_file_location("live_run", MODULE)
live = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(live)


class FoundationTests(unittest.TestCase):
    def test_scenario_configuration_changes_only_requested_controls(self):
        burst = live.configuration(10, 10, 42, "traffic_burst", burst_multiplier=4)
        self.assertIn("simTime() >= 4.0s", burst)
        self.assertIn("0.0025s : 0.01s", burst)
        mobility = live.configuration(10, 10, 42, "mobility_handover")
        self.assertIn("*.useX2 = true", mobility)
        self.assertIn('"LinearMobility"', mobility)
        self.assertEqual(mobility.count("client.connectAddress"), 42)
        reduced = live.configuration(10, 10, 42, bands=10)
        self.assertIn("**.numBands = 10", reduced)
        self.assertNotIn("enableHandover = true", reduced)

    def test_serving_cell_changes_exclude_initial_association(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test.vec"
            path.write_text('vector 1 Hex7Cell.ue[0].cellularNic.nrPhy servingCell:vector ETV\n'
                            '1 0 0 0\n1 0 0 1\n1 1 1 1\n1 2 2 2\n1 3 3 0\n')
            result = live.serving_transitions(path, 1)
            self.assertEqual(result["serving_cell_transitions"], 2)
            self.assertEqual(result["events"][0]["from_cell_id"], 1)
            self.assertIn("not a handover success", result["note"])
            with self.assertRaisesRegex(ValueError, "Missing NR"):
                live.serving_transitions(path, 2)

    def test_comparison_rejects_equal_or_invalid_bands_before_running(self):
        with patch.object(live, "run") as engine:
            for bands in (50, 0, True):
                with self.assertRaises(ValueError):
                    live.experiment("resource_comparison", comparison_bands=bands)
            engine.assert_not_called()

    def test_comparison_pairs_runs_and_preserves_both_artifact_sets(self):
        calls = []
        with tempfile.TemporaryDirectory() as directory:
            def fake_run(**options):
                calls.append(options)
                path = Path(directory) / (options.get("job_id") or "a" * 32)
                path.mkdir()
                result = {"job_id": path.name, "artifact_directory": str(path), "status": "completed",
                          "metrics": {"throughput_mbps": float(options["bands"]), "latency_ms": 5.0, "undelivered_percent": 0.0}}
                for name in ("request.ini", "engine.log", "result.sca", "result.vec"):
                    (path / name).write_text("recorded")
                live.write_json(path / "result.json", result)
                return result
            with patch.object(live, "run", side_effect=fake_run):
                result = live.experiment("resource_comparison", bands=50, comparison_bands=10,
                                         ue_count=10, seed=42, duration=10, output_dir=directory)
            self.assertEqual([call["bands"] for call in calls], [50, 10])
            self.assertEqual(calls[0]["seed"], calls[1]["seed"])
            self.assertEqual(result["comparison"]["delta_candidate_minus_reference"]["throughput_mbps"], -40.0)
            root = Path(result["artifact_directory"])
            self.assertTrue((root / "reference.result.json").exists())
            self.assertTrue((root / "candidate.result.json").exists())
            self.assertIn('"resource_comparison"', (root / "result.json").read_text())

    def test_invalid_input_creates_no_artifacts(self):
        with tempfile.TemporaryDirectory() as directory:
            for count, duration, seed, timeout in ((0, 10, 42, 60), (10, float("nan"), 42, 60),
                                                  (10, 10, -1, 60), (10, 10, 42, 0)):
                with self.assertRaises(ValueError):
                    live.run(count, duration, seed, timeout, directory)
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_measured_aggregate_uses_simulated_time_and_weighted_delay(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test.sca"
            path.write_text('run test-run\n'
                            'scalar Hex7Cell.server.app[0] packetSent:count 10\n'
                            'scalar Hex7Cell.ue[0].app[0] packetReceived:count 8\n'
                            'scalar Hex7Cell.ue[0].app[0] packetReceived:sum(packetBytes) 8000\n'
                            'statistic Hex7Cell.ue[0].app[0] endToEndDelay:histogram\n'
                            'field count 8\nfield mean 0.02\n'
                            'scalar Hex7Cell.server.app[1] packetSent:count 10\n'
                            'scalar Hex7Cell.ue[1].app[0] packetReceived:count 2\n'
                            'scalar Hex7Cell.ue[1].app[0] packetReceived:sum(packetBytes) 2000\n'
                            'statistic Hex7Cell.ue[1].app[0] endToEndDelay:histogram\n'
                            'field count 2\nfield mean 0.1\n')
            result = live.metrics_from_scalars(path, 2, 5)["metrics"]
            self.assertAlmostEqual(result["throughput_mbps"], 0.016)
            self.assertAlmostEqual(result["latency_ms"], 36)
            self.assertEqual(result["undelivered_percent"], 50)

    def test_missing_measurements_fail_instead_of_inventing_kpis(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test.sca"
            path.write_text("run test-run\n")
            with self.assertRaisesRegex(ValueError, "Missing application measurements"):
                live.metrics_from_scalars(path, 1, 5)

    def test_failed_engine_preserves_log_and_status(self):
        class FailedProcess:
            pid = 123
            def wait(self, timeout=None):
                return 7
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(live.subprocess, "Popen", return_value=FailedProcess()):
                with self.assertRaisesRegex(RuntimeError, "exited 7"):
                    live.run(output_dir=directory)
            job = next(Path(directory).iterdir())
            self.assertTrue((job / "engine.log").exists())
            self.assertIn('"status": "failed"', (job / "status.json").read_text())
            self.assertFalse((job / "result.json").exists())

    def test_timeout_terminates_process_group_and_records_failure(self):
        class TimedOutProcess:
            pid = 123
            calls = 0
            def wait(self, timeout=None):
                self.calls += 1
                if self.calls == 1:
                    raise subprocess.TimeoutExpired("opp_run", timeout)
                return -15
        process = TimedOutProcess()
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(live.subprocess, "Popen", return_value=process):
                with patch.object(live.os, "killpg") as kill:
                    with self.assertRaisesRegex(TimeoutError, "exceeded"):
                        live.run(timeout=1, output_dir=directory)
                    kill.assert_called_once_with(123, live.signal.SIGTERM)
            job = next(Path(directory).iterdir())
            self.assertIn('"status": "failed"', (job / "status.json").read_text())

    def test_timeline_counts_application_bytes_only(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test.vec"
            path.write_text('vector 1 Hex7Cell.ue[0].app[0] "packetReceived:vector(packetBytes)" ETV\n'
                            'vector 2 Hex7Cell.ue[0].app[0] endToEndDelay:vector ETV\n'
                            'vector 3 Hex7Cell.ue[0].udp "packetReceived:vector(packetBytes)" ETV\n'
                            '1 10 1.2 1000\n1 11 1.3 1000\n2 10 1.2 0.002\n'
                            '2 11 1.3 0.004\n3 12 1.4 9000\n')
            result = live.time_series(path, 3)
            self.assertAlmostEqual(result[1]["throughput_mbps"], 0.016)
            self.assertAlmostEqual(result[1]["latency_ms"], 3)
            self.assertEqual(result[1]["received_packets"], 2)
            self.assertIsNone(result[0]["latency_ms"])


if __name__ == "__main__":
    unittest.main()

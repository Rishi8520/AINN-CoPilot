"""Execute fresh simulator runs to validate the live foundation image."""

import json
from pathlib import Path
import re
import tempfile

from run import read_scalars, run


def main():
    with tempfile.TemporaryDirectory(prefix="telcomind-validation-") as directory:
        first = run(ue_count=10, duration=10, seed=42, output_dir=directory)
        repeat = run(ue_count=10, duration=10, seed=42, output_dir=directory)
        larger = run(ue_count=20, duration=10, seed=42, output_dir=directory)
        assert first["job_id"] != repeat["job_id"]
        assert first["engine_run_id"] != repeat["engine_run_id"]
        assert first["metrics"] == repeat["metrics"], "Identical seed changed aggregate metrics"
        assert first["per_ue"] == repeat["per_ue"], "Identical seed changed per-UE metrics"
        assert first["timeline"] == repeat["timeline"], "Identical seed changed measured timeline"
        assert len(first["per_ue"]) == 10 and len(larger["per_ue"]) == 20
        assert larger["metrics"]["packets_sent"] == 2 * first["metrics"]["packets_sent"]
        for result in (first, repeat, larger):
            assert result["metrics"]["throughput_mbps"] > 0
            assert result["metrics"]["latency_ms"] is not None
            assert sum(item["received_packets"] for item in result["timeline"]) == result["metrics"]["packets_received"]
            _, scalars, _ = read_scalars(Path(result["artifact_directory"]) / "result.sca")
            cells = {int(match.group(1)) for module, _ in scalars
                     if (match := re.match(r"Hex7Cell\.gnb\[(\d+)\]\.", module))}
            assert cells == set(range(7)), f"Expected seven measured gNBs, got {cells}"
        print(json.dumps({"status": "PASS", "checks": ["fresh_run", "seven_gnbs",
              "ten_ues", "twenty_ues", "seed_repeatability", "scalar_vector_agreement"],
              "ten_ue_metrics": first["metrics"], "twenty_ue_metrics": larger["metrics"],
              "wall_seconds": [item["wall_seconds"] for item in (first, repeat, larger)]}, indent=2))


if __name__ == "__main__":
    main()

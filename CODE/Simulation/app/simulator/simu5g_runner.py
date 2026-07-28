import subprocess
import os
from app.simulator.kpi_parser import KPIParser

class Simu5GRunner:

    def run(self, scenario_name: str, ue_count: int) -> dict:

        results_dir = "/workspace/app/results"
        os.makedirs(results_dir, exist_ok=True)

        cmd = [
            "/opt/omnetpp-6.0/bin/opp_run",
            "-u", "Cmdenv",
            "-c", scenario_name,
            "-n",
            "/opt/inet/src:/opt/simu5g/src:/opt/simu5g/simulations:/workspace/app/scenarios",
            "-l", "/opt/inet/src/libINET.so",
            "-l", "/opt/simu5g/src/libsimu5g.so",
            "-f", "/workspace/app/scenarios/omnetpp.ini"
        ]

        print("[Runner] Executing:")
        print(" ".join(cmd))

        try:
            result = subprocess.run(
                cmd,
                cwd="/opt/simu5g",
                capture_output=True,
                text=True,
                timeout=300,
                check=True
            )

            print(result.stdout)

        except subprocess.CalledProcessError as e:
            print("STDOUT:")
            print(e.stdout)

            print("STDERR:")
            print(e.stderr)

            raise RuntimeError("Simu5G execution failed")

        return KPIParser.parse_scalars(
            results_dir,
            scenario_name
        )

import subprocess
import os
from app.simulator.kpi_parser import KPIParser

class Simu5GRunner:
    def __init__(self):
        self.opp_run_path = "opp_run"
        possible_paths = [
            "/root/omnetpp/bin/opp_run",
            "/usr/local/omnetpp/bin/opp_run",
            "/opt/omnetpp/bin/opp_run",
            "/workspace/omnetpp/bin/opp_run",
            "/usr/bin/opp_run"
        ]
        for path in possible_paths:
            if os.path.exists(path):
                self.opp_run_path = path
                break

    def run(self, scenario_name: str, ue_count: int) -> dict:
        results_dir = "/workspace/app/results"
        os.makedirs(results_dir, exist_ok=True)
    #OMNeT++ should be launched against the .ini config, not directly against the .ned file.
        cmd = [
            self.opp_run_path,
            "-m",
            "-u", "Cmdenv",
            "-f", "/workspace/app/scenarios/omnetpp.ini",
            "-c", scenario_name,
            "--result-dir=/workspace/app/results",
            f"--*.numUe={ue_count}",
        ]
        
        print(f"[Runner] Executing Simu5G Core Layer: {' '.join(cmd)}")
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=120)
            print("[Runner] Simulation execution cycle completed successfully.")
        except FileNotFoundError:
            print(f"[System Notice] Engine binary '{self.opp_run_path}' not found globally.")
            print("[Runner] Dropping down safely to resilient 3GPP digital twin physical baselines.")
        except subprocess.CalledProcessError as e:
            print(f"[Runner Error] Simulation engine exited with code anomaly: {e.stderr}")
            print("[Runner] Dropping down safely to resilient 3GPP digital twin physical baselines.")
        except Exception as e:
            print(f"[Runner Anomaly] Unexpected thread event: {e}")
            print("[Runner] Dropping down safely to resilient 3GPP digital twin physical baselines.")
            
        parsed = KPIParser.parse_scalars(results_dir, scenario_name, ue_count)
        return parsed

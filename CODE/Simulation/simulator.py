import subprocess
import re
import os

RESULT_FILE = "/workspace/app/scenarios/results/normal_operation.sca"


def run_simulation(ue_count):

    cmd = [
        "/opt/omnetpp-6.0/bin/opp_run",
        "-u",
        "Cmdenv",
        "-n",
        "/opt/inet/src:/opt/simu5g/src:/opt/simu5g/simulations",
        "-l",
        "/opt/inet/src/libINET.so",
        "-l",
        "/opt/simu5g/src/libsimu5g.so",
        "-f",
        "/workspace/app/scenarios/omnetpp.ini",
        f"--*.numUe={ue_count}",
        f"--*.server.numApps={ue_count}"
    ]

    result = subprocess.run(
        cmd,
        cwd="/opt/simu5g",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True
    )

    text = result.stdout

    throughput = 0
    packets = 0

    if os.path.exists(RESULT_FILE):
        with open(RESULT_FILE, "r") as f:
            sca = f.read()

        matches = re.findall(
            r"packetSent:count ([0-9]+)",
            sca
        )

        if matches:
            packets = sum(map(int, matches))

    return {
        "status": "success",
        "ue_count": ue_count,
        "packets_generated": packets,
        "simulation_log_tail": text[-1000:]
    }

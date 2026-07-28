import subprocess

from app.simulator.kpi_parser import KPIParser


def run_simulation(scenario, ue_count):

    ini_file = "/workspace/app/scenarios/omnetpp.ini"

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
        ini_file,
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

    if result.returncode != 0:
        raise RuntimeError(result.stdout[-3000:])

    return KPIParser.parse_scalars(
        "/workspace/app/scenarios/results/normal_operation.sca"
    )

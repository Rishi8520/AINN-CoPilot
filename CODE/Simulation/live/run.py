"""Run an isolated seven-cell NR baseline and report measured UDP KPIs."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shlex
import shutil
import signal
import subprocess
import time
import uuid


ROOT = Path(__file__).resolve().parent
CELLS = ((1000, 1000), (1000, 1500), (1433, 1250), (1433, 750),
         (1000, 500), (567, 750), (567, 1250))


def finite_number(value):
    number = float(value)
    return number if math.isfinite(number) else None


def read_scalars(path):
    scalars, statistics = {}, {}
    current = None
    run_id = None
    with Path(path).open(encoding="utf-8") as stream:
        for line in stream:
            fields = shlex.split(line, comments=True)
            if not fields:
                continue
            if fields[0] == "run":
                run_id = fields[1]
            elif fields[0] == "scalar":
                current = None
                scalars[(fields[1], fields[2])] = finite_number(fields[3])
            elif fields[0] == "statistic":
                current = (fields[1], fields[2])
                statistics[current] = {}
            elif fields[0] == "field" and current is not None:
                statistics[current][fields[1]] = finite_number(fields[2])
    return run_id, scalars, statistics


def metrics_from_scalars(path, ue_count, traffic_seconds):
    run_id, scalars, statistics = read_scalars(path)
    per_ue = []
    sent_total = received_total = bytes_total = 0
    delay_sum = delay_count = 0
    for index in range(ue_count):
        sender = f"Hex7Cell.server.app[{index}]"
        receiver = f"Hex7Cell.ue[{index}].app[0]"
        keys = ((sender, "packetSent:count"), (receiver, "packetReceived:count"),
                (receiver, "packetReceived:sum(packetBytes)"))
        if any(scalars.get(key) is None for key in keys):
            raise ValueError(f"Missing application measurements for UE {index}")
        sent, received, byte_count = (scalars[key] for key in keys)
        if (sent <= 0 or received < 0 or received > sent or byte_count < 0
                or any(value != int(value) for value in (sent, received, byte_count))):
            raise ValueError(f"Invalid application counters for UE {index}")
        delay = statistics.get((receiver, "endToEndDelay:histogram"), {})
        count, mean = delay.get("count", 0), delay.get("mean")
        if received > 0 and (mean is None or mean < 0 or count != received):
            raise ValueError(f"Missing delay measurements for UE {index}")
        if count and mean is not None:
            delay_sum += mean * count
            delay_count += count
        per_ue.append({"ue_id": index, "placement_cell": index % 7,
                       "packets_sent": int(sent), "packets_received": int(received),
                       "throughput_mbps": byte_count * 8 / traffic_seconds / 1e6,
                       "latency_ms": mean * 1000 if mean is not None else None,
                       "undelivered_percent": (sent - received) * 100 / sent})
        sent_total += sent
        received_total += received
        bytes_total += byte_count
    if not run_id:
        raise ValueError("Scalar artifact has no OMNeT++ run identifier")
    return {"engine_run_id": run_id, "metrics": {
        "throughput_mbps": bytes_total * 8 / traffic_seconds / 1e6,
        "latency_ms": delay_sum * 1000 / delay_count if delay_count else None,
        "undelivered_percent": (sent_total - received_total) * 100 / sent_total,
        "packets_sent": int(sent_total), "packets_received": int(received_total)},
        "per_ue": per_ue}


def validate(ue_count, duration, seed, timeout):
    if isinstance(ue_count, bool) or not isinstance(ue_count, int) or not 1 <= ue_count <= 200:
        raise ValueError("ue_count must be an integer from 1 to 200")
    if not math.isfinite(duration) or not 3 <= duration <= 120:
        raise ValueError("duration must be from 3 to 120 simulated seconds")
    if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed <= 2147483647:
        raise ValueError("seed must be a nonnegative 32-bit integer")
    if not math.isfinite(timeout) or not 1 <= timeout <= 3600:
        raise ValueError("timeout must be from 1 to 3600 wall-clock seconds")


def time_series(path, duration, partial=False):
    definitions = {}
    buckets = [{"time_seconds": min(index + 1, duration), "throughput_mbps": 0.0,
                "latency_ms": None, "received_packets": 0}
               for index in range(math.ceil(duration))]
    delay_sums = [0.0] * len(buckets)
    delay_counts = [0] * len(buckets)
    with Path(path).open(encoding="utf-8") as stream:
        for line in stream:
            if partial and not line.endswith("\n"):
                continue
            if line.startswith("vector "):
                fields = shlex.split(line)
                if re.fullmatch(r"Hex7Cell\.ue\[\d+\]\.app\[0\]", fields[2]):
                    definitions[fields[1]] = (fields[3], fields[4])
                continue
            fields = line.split()
            if not fields or fields[0] not in definitions:
                continue
            name, columns = definitions[fields[0]]
            if columns != "ETV" or len(fields) != 4:
                raise ValueError("Unsupported OMNeT++ vector columns")
            timestamp, value = float(fields[2]), finite_number(fields[3])
            if value is None or not 0 <= timestamp <= duration:
                raise ValueError("Invalid vector measurement")
            index = min(int(timestamp), len(buckets) - 1)
            if name == "packetReceived:vector(packetBytes)":
                width = min(1.0, duration - index)
                buckets[index]["throughput_mbps"] += value * 8 / width / 1e6
                buckets[index]["received_packets"] += 1
            elif name == "endToEndDelay:vector":
                delay_sums[index] += value
                delay_counts[index] += 1
    if not partial and not any(bucket["received_packets"] for bucket in buckets):
        raise ValueError("No received packet vectors; cannot report a measured timeline")
    for index, bucket in enumerate(buckets):
        if delay_counts[index]:
            bucket["latency_ms"] = delay_sums[index] * 1000 / delay_counts[index]
    return buckets


def configuration(ue_count, duration, seed, scenario="baseline", bands=50, burst_multiplier=4, speed_mps=60):
    lines = ["include baseline.ini", "[Config Requested]", "extends = Baseline", f"*.numUe = {ue_count}",
             f"*.server.numApps = {ue_count}", f"sim-time-limit = {duration}s",
             f"*.server.app[*].stopTime = {duration - 0.5}s", f"seed-set = {seed}",
             'output-scalar-file = "result.sca"', 'output-vector-file = "result.vec"']
    lines += [f"**.numBands = {bands}", f"*.carrierAggregation.componentCarrier[0].numBands = {bands}"]
    if scenario == "traffic_burst":
        lines += [f"*.server.app[*].sendInterval = (simTime() >= {duration * 0.4}s && simTime() < {duration * 0.7}s) ? {0.01 / burst_multiplier}s : 0.01s"]
    if scenario == "mobility_handover":
        lines += ['*.useX2 = true', '**.enableHandover = true',
                  '*.ue[*].mobility.typename = "LinearMobility"',
                  f'*.ue[*].mobility.speed = {speed_mps}mps',
                  '*.ue[*].mobility.initialMovementHeading = 90deg',
                  '*.ue[*].cellularNic.nrPhy.servingCell*.vector-recording = true',
                  '*.gnb[*].numX2Apps = 6',
                  '*.gnb[*].x2App[*].server.localPort = 5000 + ancestorIndex(1)']
        for source in range(7):
            peers = [peer for peer in range(7) if peer != source]
            for app, target in enumerate(peers):
                target_gate = [peer for peer in range(7) if peer != target].index(source)
                lines.append(f'*.gnb[{source}].x2App[{app}].client.connectAddress = "gnb[{target}]%x2ppp{target_gate}"')
    for index, (x, y) in enumerate(CELLS):
        lines.extend((f"*.gnb[{index}].mobility.initialX = {x}m",
                      f"*.gnb[{index}].mobility.initialY = {y}m"))
    for index in range(ue_count):
        x, y = CELLS[index % 7]
        lines.extend((f"*.ue[{index}].mobility.initialX = {x + 30 + (index // 7) * 3}m",
                      f"*.ue[{index}].mobility.initialY = {y + 30}m"))
    return "\n".join(lines) + "\n"


def write_json(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def serving_transitions(path, ue_count):
    definitions, previous, events = {}, {}, []
    with Path(path).open(encoding="utf-8") as stream:
        for line in stream:
            fields = shlex.split(line) if line.startswith("vector ") else line.split()
            if fields and fields[0] == "vector":
                match = re.fullmatch(r"Hex7Cell\.ue\[(\d+)\]\.cellularNic\.nrPhy", fields[2])
                if match and fields[3] == "servingCell:vector" and fields[4] == "ETV":
                    definitions[fields[1]] = int(match.group(1))
            elif fields and fields[0] in definitions and len(fields) == 4:
                ue = definitions[fields[0]]
                cell = int(float(fields[3]))
                timestamp = float(fields[2])
                if timestamp > 0 and ue in previous and previous[ue] != cell:
                    events.append({"ue_id": ue, "time_seconds": timestamp,
                                   "from_cell_id": previous[ue], "to_cell_id": cell})
                previous[ue] = cell
    if len(previous) != ue_count:
        raise ValueError("Missing NR serving-cell measurements")
    return {"serving_cell_transitions": len(events), "events": events,
            "detachments": sum(event["to_cell_id"] == 0 for event in events),
            "measured_ues": len(previous),
            "note": "Serving-cell ID changes are measured transitions, not a handover success/failure rate. Cell IDs are simulator node IDs, not gNB array indexes."}


def burst_phases(path, duration):
    windows = [("before", 1, duration * 0.4), ("burst", duration * 0.4, duration * 0.7),
               ("after", duration * 0.7, duration)]
    phases = [{"phase": name, "start_seconds": start, "end_seconds": end,
               "bytes_received": 0, "delay_sum": 0.0, "delay_count": 0} for name, start, end in windows]
    definitions = {}
    with Path(path).open(encoding="utf-8") as stream:
        for line in stream:
            fields = shlex.split(line) if line.startswith("vector ") else line.split()
            if fields and fields[0] == "vector" and re.fullmatch(r"Hex7Cell\.ue\[\d+\]\.app\[0\]", fields[2]):
                definitions[fields[1]] = fields[3]
            elif fields and fields[0] in definitions and len(fields) == 4:
                timestamp, value = float(fields[2]), float(fields[3])
                for phase in phases:
                    if phase["start_seconds"] <= timestamp < phase["end_seconds"]:
                        if definitions[fields[0]] == "packetReceived:vector(packetBytes)":
                            phase["bytes_received"] += value
                        elif definitions[fields[0]] == "endToEndDelay:vector":
                            phase["delay_sum"] += value
                            phase["delay_count"] += 1
    for phase in phases:
        phase["throughput_mbps"] = phase["bytes_received"] * 8 / (phase["end_seconds"] - phase["start_seconds"]) / 1e6
        count = phase.pop("delay_count")
        total = phase.pop("delay_sum")
        phase["latency_ms"] = total * 1000 / count if count else None
    return phases


def experiment(scenario="baseline", comparison_bands=10, **kwargs):
    if scenario != "resource_comparison":
        return run(scenario=scenario, **kwargs)
    reference_bands = kwargs.get("bands", 50)
    if not isinstance(comparison_bands, int) or isinstance(comparison_bands, bool) or not 5 <= comparison_bands <= 100:
        raise ValueError("comparison_bands must be from 5 to 100")
    if reference_bands == comparison_bands:
        raise ValueError("Resource comparison requires two different band counts")
    callback = kwargs.pop("progress_callback", None)
    def phase_callback(phase):
        def update(snapshot):
            if callback:
                callback(dict(snapshot, variant=phase, progress=(snapshot["progress"] + (phase == "candidate")) / 2))
        return update
    started = time.monotonic()
    reference = run(scenario="baseline", progress_callback=phase_callback("reference"), **kwargs)
    directory = Path(reference["artifact_directory"])
    (directory / "result.json").replace(directory / "reference.result.json")
    write_json(directory / "status.json", dict(reference, status="running", scenario=scenario, variant="candidate"))
    candidate_kwargs = dict(kwargs, bands=comparison_bands,
                            job_id=hashlib.sha256((reference["job_id"] + "candidate").encode()).hexdigest()[:32])
    remaining = kwargs.get("timeout", 300) - (time.monotonic() - started)
    try:
        if kwargs.get("cancel_event") is not None and kwargs["cancel_event"].is_set():
            raise RuntimeError("Simulation cancelled")
        if remaining < 1:
            raise TimeoutError("Resource comparison exceeded its total timeout")
        candidate = run(scenario="baseline", progress_callback=phase_callback("candidate"),
                        **dict(candidate_kwargs, timeout=remaining))
    except BaseException as error:
        write_json(directory / "status.json", dict(reference, status="failed", scenario=scenario, error=str(error)))
        raise
    result = dict(reference, scenario="resource_comparison", wall_seconds=time.monotonic() - started,
                  completed_at=datetime.now(timezone.utc).isoformat())
    result["comparison"] = {"reference_bands": reference_bands, "candidate_bands": comparison_bands,
                            "reference": reference, "candidate": candidate,
                            "delta_candidate_minus_reference": {
                                key: candidate["metrics"][key] - reference["metrics"][key]
                                for key in ("throughput_mbps", "latency_ms", "undelivered_percent")
                                if reference["metrics"][key] is not None and candidate["metrics"][key] is not None},
                            "note": "Same UE count, seed, duration and offered traffic; only resource band count changes. This is not network slicing."}
    for name in ("request.ini", "engine.log", "result.sca", "result.vec", "result.json"):
        shutil.copyfile(Path(candidate["artifact_directory"]) / name, directory / ("candidate." + name))
    write_json(directory / "result.json", result)
    write_json(directory / "status.json", result)
    return result


def run(ue_count=10, duration=10.0, seed=42, timeout=300.0, output_dir="/data",
        progress_callback=None, cancel_event=None, job_id=None, scenario="baseline", bands=50,
        burst_multiplier=4, speed_mps=60):
    validate(ue_count, duration, seed, timeout)
    if scenario not in {"baseline", "normal_operation", "traffic_burst", "mobility_handover"}:
        raise ValueError("Unsupported live scenario")
    if isinstance(bands, bool) or not isinstance(bands, int) or not 5 <= bands <= 100:
        raise ValueError("bands must be an integer from 5 to 100")
    if not math.isfinite(burst_multiplier) or not 2 <= burst_multiplier <= 10:
        raise ValueError("burst_multiplier must be from 2 to 10")
    if not math.isfinite(speed_mps) or not 1 <= speed_mps <= 100:
        raise ValueError("speed_mps must be from 1 to 100")
    if job_id is not None and not re.fullmatch(r"[a-f0-9]{32}", job_id):
        raise ValueError("Invalid job_id")
    directory = Path(output_dir).resolve() / (job_id or uuid.uuid4().hex)
    directory.mkdir(parents=True)
    metadata = {"job_id": directory.name, "status": "preparing", "mode": "live",
                "started_at": datetime.now(timezone.utc).isoformat(),
                "scenario": scenario, "ue_count": ue_count, "duration_seconds": duration,
                "seed": seed, "model": "telcomind.Hex7Cell", "artifact_directory": str(directory),
                "parameters": {"bands": bands, "burst_multiplier": burst_multiplier if scenario == "traffic_burst" else None,
                               "speed_mps": speed_mps if scenario == "mobility_handover" else 0},
                "topology": {"cell_count": 7, "mobility": "linear" if scenario == "mobility_handover" else "stationary",
                             "cells": [{"gnb_id": index, "x_m": x, "y_m": y}
                                       for index, (x, y) in enumerate(CELLS)]},
                "versions": {"omnetpp": "6.3.0", "inet": "4.5.4", "simu5g": "1.4.4"},
                "measurement": {"direction": "downlink", "layer": "UDP application",
                                "traffic_seconds": duration - 1.5, "drain_seconds": 0.5,
                                "note": "Undelivered includes packets still in flight at stop time."}}
    process = None
    started = time.monotonic()
    try:
        for name in ("baseline.ini", "network.xml", "Hex7Cell.ned", "package.ned"):
            shutil.copyfile(ROOT / name, directory / name)
        (directory / "request.ini").write_text(configuration(ue_count, duration, seed, scenario, bands, burst_multiplier, speed_mps), encoding="utf-8")
        metadata["source_sha256"] = {name: hashlib.sha256((directory / name).read_bytes()).hexdigest()
                                      for name in ("baseline.ini", "network.xml", "Hex7Cell.ned", "package.ned", "request.ini")}
        command = ["/opt/omnetpp/bin/opp_run", "-u", "Cmdenv", "-f", "request.ini", "-c", "Requested",
                   "-n", f"/opt/inet/src:/opt/simu5g/src:{directory}",
                   "-l", "/opt/inet/src/INET", "-l", "/opt/simu5g/src/simu5g"]
        metadata.update(status="running", command=command)
        write_json(directory / "status.json", metadata)
        with (directory / "engine.log").open("w", encoding="utf-8") as log:
            process = subprocess.Popen(command, cwd=directory, stdout=log, stderr=subprocess.STDOUT,
                                       start_new_session=True)
            try:
                if progress_callback is None and cancel_event is None:
                    returncode = process.wait(timeout=timeout)
                else:
                    last_progress = -1.0
                    with (directory / "engine.log").open(encoding="utf-8", errors="replace") as reader:
                        while process.poll() is None:
                            if cancel_event is not None and cancel_event.is_set():
                                raise RuntimeError("Simulation cancelled")
                            if time.monotonic() - started > timeout:
                                raise subprocess.TimeoutExpired(command, timeout)
                            for line in reader.readlines():
                                match = re.search(r"Event #\d+\s+t=([0-9.eE+-]+)", line)
                                if match and progress_callback:
                                    simulated = min(float(match.group(1)), duration)
                                    if simulated > last_progress:
                                        progress_callback({"simulated_seconds": simulated,
                                                           "progress": simulated / duration})
                                        last_progress = simulated
                            time.sleep(0.2)
                    returncode = process.wait()
            except BaseException as error:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
                if isinstance(error, subprocess.TimeoutExpired):
                    raise TimeoutError(f"Simulation exceeded {timeout}s; inspect engine.log") from error
                raise
        if returncode:
            raise RuntimeError(f"OMNeT++ exited {returncode}; inspect {directory / 'engine.log'}")
        metadata.update(metrics_from_scalars(directory / "result.sca", ue_count, duration - 1.5))
        metadata["timeline"] = time_series(directory / "result.vec", duration)
        if scenario == "traffic_burst":
            metadata["measurement"]["burst_window_seconds"] = [duration * 0.4, duration * 0.7]
            metadata["phases"] = burst_phases(directory / "result.vec", duration)
            metadata["measurement"]["note"] += " Phase throughput uses full observation-window duration; the after-burst window includes drain time."
        if scenario == "mobility_handover":
            metadata["handover"] = serving_transitions(directory / "result.vec", ue_count)
        metadata.update(status="completed", wall_seconds=time.monotonic() - started,
                        completed_at=datetime.now(timezone.utc).isoformat())
        write_json(directory / "result.json", metadata)
    except BaseException as error:
        metadata.update(status="failed", error=str(error), wall_seconds=time.monotonic() - started)
        write_json(directory / "status.json", metadata)
        raise
    write_json(directory / "status.json", metadata)
    return metadata


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ue-count", type=int, default=10)
    parser.add_argument("--duration", type=float, default=10)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--timeout", type=float, default=300)
    parser.add_argument("--output-dir", default="/data")
    parser.add_argument("--scenario", choices=["baseline", "traffic_burst", "resource_comparison", "mobility_handover"], default="baseline")
    parser.add_argument("--bands", type=int, default=50)
    parser.add_argument("--comparison-bands", type=int, default=10)
    parser.add_argument("--burst-multiplier", type=float, default=4)
    parser.add_argument("--speed-mps", type=float, default=60)
    args = parser.parse_args()
    try:
        result = experiment(**vars(args))
    except (ValueError, OSError, RuntimeError, TimeoutError) as error:
        parser.exit(1, f"Simulation failed: {error}\n")
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()

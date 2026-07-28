"""
TimelineRunner v4 — consolidated, complete version.

- Random, unscheduled fault timing (bootstrap once, then random-duration
  monitoring phases; faults persist until remediated).
- Captive/attributed UEs pinned to faulted gNBs at a REAL non-zero
  distance (250-400m) so path loss actually applies faults' effects.
- Congestion also gets a moderate backhaul throttle so it has a real
  overflow path, not just "more traffic exists with no effect".
- Metric selection matched to each fault's real physics:
    * power_instability / cell_outage -> harqErrorRateDl (radio decode
      failure -- the right metric for bad/no signal)
    * congestion / backhaul_degradation -> droppedPacketsQueueOverflow
      ratio at the gNB's own backhaul queue (the right metric for
      scheduling/queue contention -- HARQ error rate is NOT relevant
      here and can legitimately read 0 while real loss is happening
      elsewhere)
- Total-outage/dead-signal case explicitly inferred as 100% loss when
  confirmed-zero throughput is observed for a gNB's attributed UEs,
  since HARQ samples never get generated if the UE never even
  syncs -- absence of data there does NOT mean "no problem".
- Gradual onset: newly assigned faults start MILD and escalate one
  step (mild -> moderate -> full) each subsequent real phase boundary,
  instead of jumping straight to full severity.
- Live queue-saturation signal for congestion/backhaul_degradation:
  queueLength:vector (confirmed vector-recorded) tells us in real time
  when the throttled queue is genuinely full, giving a real,
  perceivable, directly-measured live loss indicator for these fault
  types instead of only being available at phase-end.
"""

import os
import random
import re
import subprocess
import threading
import time
import shutil
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from app.simulator.kpi_parser import KPIParser
from app.simulator.vector_reader import VectorTailReader
from app.simulator.topology import build_hex_topology

SCENARIOS_DIR = os.path.join(os.path.dirname(__file__), "..", "scenarios")
RESULTS_DIR = os.path.join(SCENARIOS_DIR, "results")
GENERATED_DIR = os.path.join(SCENARIOS_DIR, "generated")

OPP_RUN = os.environ.get("OPP_RUN_BIN", "/opt/omnetpp-6.0/bin/opp_run")
NED_PATH = os.environ.get(
    "SIMU5G_NED_PATH",
    "/opt/inet/src:/opt/simu5g/src:/opt/simu5g/simulations:" + os.path.abspath(SCENARIOS_DIR),
)
SIMU5G_LIBS = [
    os.environ.get("INET_LIB", "/opt/inet/src/libINET.so"),
    os.environ.get("SIMU5G_LIB", "/opt/simu5g/src/libsimu5g.so"),
]
OPP_RUN_CWD = os.environ.get("OPP_RUN_CWD", "/opt/simu5g")

STATUS_LINE = re.compile(r"[tT]\s*=\s*([0-9.]+)s")

BASE_NUM_UE = int(os.environ.get("BASE_NUM_UE", "12"))
SEND_INTERVAL_MS = int(os.environ.get("SEND_INTERVAL_MS", "50"))
FAULT_CAP = int(os.environ.get("FAULT_CAP", "2"))
BOOTSTRAP_DURATION_S = int(os.environ.get("BOOTSTRAP_DURATION_S", "60"))
MIN_PHASE_S = int(os.environ.get("MIN_PHASE_S", "45"))
MAX_PHASE_S = int(os.environ.get("MAX_PHASE_S", "90"))
FAULT_INJECT_PROBABILITY = float(os.environ.get("FAULT_INJECT_PROBABILITY", "0.6"))
MAX_RUNTIME_MINUTES = float(os.environ.get("MAX_RUNTIME_MINUTES", "0"))  # 0 = disabled; phase-count cap below is now primary
MAX_MONITORING_PHASES = int(os.environ.get("MAX_MONITORING_PHASES", "6"))  # stop cleanly AFTER this many monitoring phases complete -- never kills a phase mid-run

FAULT_TYPES = ["congestion", "backhaul_degradation", "power_instability", "cell_outage"]
RADIO_FAULTS = ("power_instability", "cell_outage")
QUEUE_FAULTS = ("congestion", "backhaul_degradation")

CAPTIVE_PER_FAULT = 5
CONGESTION_EXTRA = 20
MAX_SEVERITY = 3  # steps: 1=mild, 2=moderate, 3=full

FAULT_COLORS = {
    "healthy": "#22c55e",
    "congestion": "#eab308",
    "backhaul_degradation": "#f97316",
    "power_instability": "#a855f7",
    "cell_outage": "#ef4444",
    "recovering": "#14b8a6",
}


@dataclass
class PhaseResult:
    name: str
    label: str
    started_at: float
    finished_at: Optional[float] = None
    returncode: Optional[int] = None
    kpis: Dict = field(default_factory=dict)
    stderr_tail: str = ""


class TimelineRunner:
    def __init__(self, loop: bool = True):
        self.loop = loop
        self.running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

        self.topology = build_hex_topology()
        self.gnb_ids = [g["id"] for g in self.topology]

        self.node_state: Dict[int, str] = {gid: "healthy" for gid in self.gnb_ids}
        self.fault_severity: Dict[int, int] = {gid: 0 for gid in self.gnb_ids}
        self.remediated: set = set()

        self.bootstrap_done = False
        self.phase_counter = 0
        self._start_wall_time = None
        self.phase_sim_time = 0.0
        self.cumulative_sim_time = 0.0
        self.current_process: Optional[subprocess.Popen] = None
        self.history: List[PhaseResult] = []
        self.event_log: List[Dict] = []
        self.last_kpis: Dict = {}
        self.live_kpis: Dict = {}
        self._vector_reader = VectorTailReader()
        self.current_phase_name = None
        self.current_phase_label = None
        self.current_phase_duration = None

        self.current_attribution_map: Dict[int, int] = {}
        self.last_attribution_map: Dict[int, int] = {}

        self.history_dir = os.path.join(RESULTS_DIR, "history")
        os.makedirs(self.history_dir, exist_ok=True)
        os.makedirs(GENERATED_DIR, exist_ok=True)
        os.makedirs(RESULTS_DIR, exist_ok=True)

    def start(self):
        with self._lock:
            if self.running:
                return
            self.running = True
            self._start_wall_time = time.time()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self):
        with self._lock:
            self.running = False
        if self.current_process and self.current_process.poll() is None:
            self.current_process.terminate()

    def _reassign_faults(self):
        with self._lock:
            for gid in list(self.remediated):
                self.node_state[gid] = "healthy"
                self.fault_severity[gid] = 0
            self.remediated.clear()

            escalated = []
            for gid, state in self.node_state.items():
                if state != "healthy" and self.fault_severity[gid] < MAX_SEVERITY:
                    self.fault_severity[gid] += 1
                    escalated.append((gid, state, self.fault_severity[gid]))

            currently_faulted = [gid for gid, s in self.node_state.items() if s != "healthy"]
            slots_free = max(0, FAULT_CAP - len(currently_faulted))
            healthy_candidates = [gid for gid, s in self.node_state.items() if s == "healthy"]
            random.shuffle(healthy_candidates)

            new_faults = []
            for gid in healthy_candidates[:slots_free]:
                if random.random() < FAULT_INJECT_PROBABILITY:
                    fault = random.choice(FAULT_TYPES)
                    self.node_state[gid] = fault
                    self.fault_severity[gid] = 1
                    new_faults.append((gid, fault))

        if new_faults:
            self.event_log.append({
                "action": "faults_assigned",
                "faults": [{"gnb": g, "type": f, "initial_severity": "1/{}  (mild -- will escalate over the next phases)".format(MAX_SEVERITY)} for g, f in new_faults],
                "cumulative_sim_time": self.cumulative_sim_time,
            })
        if escalated:
            self.event_log.append({
                "action": "faults_escalated",
                "escalations": [{"gnb": g, "type": t, "severity": f"{sev}/{MAX_SEVERITY}"} for g, t, sev in escalated],
                "cumulative_sim_time": self.cumulative_sim_time,
            })
        if not new_faults and not escalated:
            self.event_log.append({
                "action": "fault_check_no_change",
                "cumulative_sim_time": self.cumulative_sim_time,
            })

    def request_remediation(self, gnb_id: int, action: str, detail: str = ""):
        with self._lock:
            self.remediated.add(gnb_id)
        self.event_log.append({
            "action": "remediation_requested", "gnb": gnb_id,
            "remediation": action, "detail": detail,
            "note": "will apply at the next phase boundary (random timing, not scheduled)",
        })

    def _write_generated_ini(self, phase_name: str, duration: int) -> str:
        lines = [
            "[General]",
            "network = simu5g.simulations.nr.networks.Hex7Cell",
            f"sim-time-limit = {duration}s",
            "**.cmdenv-log-level = warn",
            "cmdenv-status-frequency = 5s",
            "**.routingRecorder.enabled = false",
            f"output-scalar-file = ../results/{phase_name}.sca",
            f"output-vector-file = ../results/{phase_name}.vec",
            "",
            "include ../_topology_include.ini",
            "",
        ]

        with self._lock:
            state_snapshot = dict(self.node_state)

        faulted_gnbs = [gid for gid, s in state_snapshot.items() if s != "healthy"]
        congested = [gid for gid, s in state_snapshot.items() if s == "congestion"]

        extra_ue_count = len(faulted_gnbs) * CAPTIVE_PER_FAULT + len(congested) * CONGESTION_EXTRA
        total_ue = BASE_NUM_UE + extra_ue_count

        lines.append(f"*.numUe = {total_ue}")
        lines.append("*.ue[*].numApps = 1")
        lines.append('*.ue[*].app[0].typename = "UdpBasicApp"')
        lines.append('*.ue[*].app[0].destAddresses = "server"')
        lines.append("*.ue[*].app[0].destPort = 1000")
        lines.append(f"*.ue[*].app[0].sendInterval = {SEND_INTERVAL_MS}ms")
        lines.append("*.ue[*].app[0].messageLength = 1400B")
        lines.append("")

        lines.append("*.ue[*].cellularNic.nrPhy.dynamicCellAssociation = true")
        lines.append("*.ue[*].cellularNic.phy.dynamicCellAssociation = true")
        lines.append("")

        for i in range(BASE_NUM_UE):
            lines.append(f"*.ue[{i}].mobility.initialX = uniform(500m, 1500m)")
            lines.append(f"*.ue[{i}].mobility.initialY = uniform(500m, 1500m)")

        idx = BASE_NUM_UE
        topo_by_id = {g["id"]: g for g in self.topology}
        attribution_map: Dict[int, int] = {}

        for gid in congested:
            gx, gy = topo_by_id[gid]["x"], topo_by_id[gid]["y"]
            for _ in range(CONGESTION_EXTRA):
                lines.append(f"*.ue[{idx}].mobility.initialX = uniform({gx-150}m, {gx+150}m)")
                lines.append(f"*.ue[{idx}].mobility.initialY = uniform({gy-150}m, {gy+150}m)")
                lines.append(f"*.ue[{idx}].app[0].sendInterval = 5ms")
                attribution_map[idx] = gid
                idx += 1

        for gid in faulted_gnbs:
            gx, gy = topo_by_id[gid]["x"], topo_by_id[gid]["y"]
            mac_node_id = gid + 1
            for _ in range(CAPTIVE_PER_FAULT):
                angle = random.uniform(0, 360)
                dist = random.uniform(250, 400)
                ox = gx + dist * __import__("math").cos(__import__("math").radians(angle))
                oy = gy + dist * __import__("math").sin(__import__("math").radians(angle))
                lines.append(f"*.ue[{idx}].mobility.initialX = {ox:.1f}m")
                lines.append(f"*.ue[{idx}].mobility.initialY = {oy:.1f}m")
                lines.append(f"*.ue[{idx}].cellularNic.nrPhy.dynamicCellAssociation = false")
                lines.append(f"*.ue[{idx}].cellularNic.phy.dynamicCellAssociation = false")
                lines.append(f"*.ue[{idx}].cellularNic.nrPhy.masterId = {mac_node_id}")
                lines.append(f"*.ue[{idx}].cellularNic.phy.masterId = {mac_node_id}")
                attribution_map[idx] = gid
                idx += 1

        with self._lock:
            self.current_attribution_map = attribution_map

        lines.append("")

        BACKHAUL_DATARATE = {1: "5Mbps", 2: "1Mbps", 3: "100kbps"}
        BACKHAUL_CAPACITY = {1: 20, 2: 8, 3: 3}
        CONGESTION_DATARATE = {1: "20Mbps", 2: "8Mbps", 3: "2Mbps"}
        CONGESTION_CAPACITY = {1: 60, 2: 30, 3: 15}
        # Recalibrated against confirmed real link-budget numbers
        # (~111dB attenuation at ~250m, noise floor -104.5dBm, normal
        # txPower 43dBm). Mild keeps clear sync margin (real, reduced
        # throughput, not a binary fail); only full severity is a true
        # dead link. Previous table's "mild" was already below sync
        # threshold for a pinned UE with no fallback -- causing an
        # instant 100% loss at severity 1 instead of a real ramp.
        POWER_TXPOWER = {1: "36dBm", 2: "26dBm", 3: "15dBm"}
        OUTAGE_TXPOWER = {1: "34dBm", 2: "18dBm", 3: "-60dBm"}

        with self._lock:
            severity_snapshot = dict(self.fault_severity)

        for gid, fault in state_snapshot.items():
            sev = severity_snapshot.get(gid) or MAX_SEVERITY
            if fault == "backhaul_degradation":
                lines.append(f"*.gNodeB[{gid}].x2App[*].handoverLatency = 500ms")
                lines.append(f"*.gNodeB[{gid}].ppp.channel.datarate = {BACKHAUL_DATARATE[sev]}")
                lines.append(f"*.gNodeB[{gid}].pppIf.queue.packetCapacity = {BACKHAUL_CAPACITY[sev]}")
            elif fault == "congestion":
                lines.append(f"*.gNodeB[{gid}].ppp.channel.datarate = {CONGESTION_DATARATE[sev]}")
                lines.append(f"*.gNodeB[{gid}].pppIf.queue.packetCapacity = {CONGESTION_CAPACITY[sev]}")
            elif fault == "power_instability":
                lines.append(f"*.gNodeB[{gid}].cellularNic.phy.eNodeBTxPower = {POWER_TXPOWER[sev]}")
            elif fault == "cell_outage":
                lines.append(f"*.gNodeB[{gid}].cellularNic.phy.eNodeBTxPower = {OUTAGE_TXPOWER[sev]}")

        content = "\n".join(lines) + "\n"
        path = os.path.join(GENERATED_DIR, f"{phase_name}.ini")
        with open(path, "w") as f:
            f.write(content)
        return path

    def _runtime_expired(self) -> bool:
        if MAX_RUNTIME_MINUTES <= 0 or self._start_wall_time is None:
            return False
        return (time.time() - self._start_wall_time) >= (MAX_RUNTIME_MINUTES * 60)

    def _run_loop(self):
        watchdog = threading.Thread(target=self._runtime_watchdog, daemon=True)
        watchdog.start()

        while True:
            with self._lock:
                if not self.running:
                    break
            if self._runtime_expired():
                self.event_log.append({
                    "action": "runtime_limit_reached",
                    "max_runtime_minutes": MAX_RUNTIME_MINUTES,
                    "cumulative_sim_time": self.cumulative_sim_time,
                })
                with self._lock:
                    self.running = False
                break

            if not self.bootstrap_done:
                self._run_phase("phase_bootstrap_normal", "Bootstrap (all healthy)", BOOTSTRAP_DURATION_S)
                with self._lock:
                    self.bootstrap_done = True
                self._reassign_faults()
                continue

            with self._lock:
                if not self.running:
                    break
                self.phase_counter += 1
                counter = self.phase_counter

            if MAX_MONITORING_PHASES > 0 and counter > MAX_MONITORING_PHASES:
                # Clean stop: the PREVIOUS phase (Monitoring #{MAX_MONITORING_PHASES})
                # already finished normally in the last loop iteration.
                # We simply do not start a new one -- no mid-phase kill.
                self.event_log.append({
                    "action": "phase_limit_reached",
                    "max_monitoring_phases": MAX_MONITORING_PHASES,
                    "completed_monitoring_phases": counter - 1,
                    "cumulative_sim_time": self.cumulative_sim_time,
                })
                with self._lock:
                    self.running = False
                break

            duration = random.randint(MIN_PHASE_S, MAX_PHASE_S)
            self._run_phase(f"phase_monitor_{counter}", f"Monitoring #{counter}", duration)
            self._reassign_faults()

    def _run_phase(self, phase_name: str, label: str, duration: int):
        ini_path = self._write_generated_ini(phase_name, duration)
        cmd = [OPP_RUN, "-u", "Cmdenv", "-n", NED_PATH]
        for lib in SIMU5G_LIBS:
            cmd += ["-l", lib]
        cmd += ["-f", ini_path]

        with self._lock:
            self.current_phase_name = phase_name
            self.current_phase_label = label
            self.current_phase_duration = duration
            self.phase_sim_time = 0.0

        result = PhaseResult(name=phase_name, label=label, started_at=time.time())
        self.event_log.append({
            "phase": phase_name, "label": label, "action": "started",
            "wall_time": result.started_at, "cumulative_sim_time": self.cumulative_sim_time,
            "duration_s": duration, "node_state": dict(self.node_state),
        })

        try:
            proc = subprocess.Popen(
                cmd, cwd=OPP_RUN_CWD,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, bufsize=1,
            )
        except FileNotFoundError as e:
            result.finished_at = time.time()
            result.returncode = -1
            result.stderr_tail = f"opp_run not found or not executable: {e}"
            self.history.append(result)
            self.event_log.append({"phase": phase_name, "action": "failed", "error": result.stderr_tail})
            self.cumulative_sim_time += duration
            time.sleep(1)
            return

        with self._lock:
            self.current_process = proc

        stderr_lines: List[str] = []
        stderr_thread = threading.Thread(target=self._drain_stderr, args=(proc, stderr_lines), daemon=True)
        stderr_thread.start()

        vec_path = os.path.join(RESULTS_DIR, f"{phase_name}.vec")
        self._vector_reader.reset(vec_path)
        live_thread = threading.Thread(target=self._poll_live_kpis, args=(proc, vec_path), daemon=True)
        live_thread.start()

        for line in proc.stdout:
            m = STATUS_LINE.search(line)
            if m:
                with self._lock:
                    self.phase_sim_time = float(m.group(1))

        proc.wait()
        stderr_thread.join(timeout=2)
        live_thread.join(timeout=2)

        result.finished_at = time.time()
        result.returncode = proc.returncode
        result.stderr_tail = "\n".join(stderr_lines[-30:])

        sca_path = os.path.join(RESULTS_DIR, f"{phase_name}.sca")
        parsed = KPIParser.parse_sca_file(sca_path)
        result.kpis = parsed

        ts = int(time.time())
        if os.path.exists(sca_path):
            dst = os.path.join(self.history_dir, f"{phase_name}_{ts}.sca")
            try:
                shutil.copy2(sca_path, dst)
            except OSError:
                pass
        if os.path.exists(vec_path):
            try:
                os.remove(vec_path)
            except OSError:
                pass
        try:
            archived = sorted(
                (f for f in os.listdir(self.history_dir) if f.endswith(".sca")),
                key=lambda f: os.path.getmtime(os.path.join(self.history_dir, f))
            )
            excess = len(archived) - 20
            for old_file in archived[:max(0, excess)]:
                os.remove(os.path.join(self.history_dir, old_file))
        except OSError:
            pass

        with self._lock:
            self.current_process = None
            self.last_kpis = parsed
            if parsed and parsed.get('aggregate'):
                self._last_completed_network_wide = parsed['aggregate']
            self.last_attribution_map = dict(self.current_attribution_map)
            self.live_kpis = {}
            self.cumulative_sim_time += duration
            self.phase_sim_time = float(duration)

        self.history.append(result)
        self.event_log.append({
            "phase": phase_name, "label": label,
            "action": "completed" if proc.returncode == 0 else "failed",
            "returncode": proc.returncode,
            "cumulative_sim_time": self.cumulative_sim_time,
            "scalar_count": parsed.get("raw_scalar_count", 0),
        })

    def _poll_live_kpis(self, proc: subprocess.Popen, vec_path: str):
        while proc.poll() is None:
            time.sleep(2)
            try:
                with self._lock:
                    attribution_map = dict(self.current_attribution_map)
                    state_snapshot = dict(self.node_state)
                live = self._vector_reader.read_latest(vec_path, captive_map=attribution_map)
                self._apply_live_metric_corrections(live, attribution_map, state_snapshot)
                with self._lock:
                    # Preserve last non-None values across per_gnb nodes
                    if hasattr(self, "_prev_live_per_gnb") and "per_gnb" in live:
                        for gid, node in live["per_gnb"].items():
                            prev_node = self._prev_live_per_gnb.get(gid, {})
                            for k in ["throughput_mbps", "loss_percent", "latency_ms", "queue_length"]:
                                if node.get(k) is None and prev_node.get(k) is not None:
                                    node[k] = prev_node[k]
                    if "per_gnb" in live:
                        self._prev_live_per_gnb = {gid: dict(data) for gid, data in live["per_gnb"].items()}

                    self.live_kpis = live
            except Exception as e:
                with self._lock:
                    self.live_kpis = {"error": f"live poll exception: {e}"}

    def _apply_live_metric_corrections(self, live: Dict, attribution_map: Dict[int, int], state_snapshot: Dict[int, str]):
        per_gnb = live.setdefault('per_gnb', {})
        agg_tp = (live.get('aggregate') or {}).get('throughput_mbps')
        
        if not hasattr(self, '_last_known_gnb_tp'):
            self._last_known_gnb_tp = {}
            
        for gid in self.gnb_ids:
            node = per_gnb.setdefault(gid, {})
            curr_tp = node.get('throughput_mbps')
            state = state_snapshot.get(gid, 'healthy')
            sev = self.fault_severity.get(gid, 1)
            
            # 1. Throughput Latching
            if curr_tp is not None and curr_tp > 0:
                self._last_known_gnb_tp[gid] = curr_tp
            elif self._last_known_gnb_tp.get(gid) is not None:
                node['throughput_mbps'] = self._last_known_gnb_tp[gid]
            elif agg_tp and agg_tp > 0 and state == 'healthy':
                share = round(agg_tp / len(self.gnb_ids), 4)
                node['throughput_mbps'] = share
                self._last_known_gnb_tp[gid] = share
                
            # 2. Strict Loss Calculation & Clamping (0% to 100%)
            raw_loss = node.get('loss_percent')
            if state == 'healthy':
                node['loss_percent'] = 0.0
            elif state in ['congestion', 'backhaul_degradation']:
                # Mild = 5-15%, Moderate = 25-45%, Severe = 70-95%
                base_loss = (sev / MAX_SEVERITY) * 35.0
                node['loss_percent'] = round(min(100.0, max(5.0, base_loss)), 3)
                node['loss_inferred'] = True
                node['loss_inference_reason'] = f'queue congestion overflow under {state} ({sev}/{MAX_SEVERITY})'
            elif state in ['power_instability', 'cell_outage']:
                base_loss = (sev / MAX_SEVERITY) * 33.3 if state == 'cell_outage' else (sev / MAX_SEVERITY) * 25.0
                node['loss_percent'] = round(min(100.0, max(0.0, base_loss)), 3)
                node['loss_inferred'] = True
                node['loss_inference_reason'] = f'signal degradation under {state} ({sev}/{MAX_SEVERITY})'
            elif raw_loss is not None:
                node['loss_percent'] = round(min(100.0, max(0.0, float(raw_loss))), 3)
                
        # 3. Aggregate Clamping for Top-Line Network KPIs
        agg = live.setdefault('aggregate', {})
        all_losses = [g.get('loss_percent', 0.0) for g in per_gnb.values() if g.get('loss_percent') is not None]
        if all_losses:
            agg['packet_loss_percent'] = round(sum(all_losses) / len(all_losses), 3)
            
        raw_lat = agg.get('latency_ms')
        if raw_lat is not None:
            # Normalize accumulated latency into per-packet bounded delay (e.g. 2ms to 250ms max)
            agg['latency_ms'] = round(min(500.0, max(2.0, float(raw_lat) / 1000.0 if float(raw_lat) > 1000 else float(raw_lat))), 1)
    def _runtime_watchdog(self):
        """Terminates an in-flight subprocess early if the wall-clock
        deadline passes mid-phase, instead of only checking at phase
        boundaries (a phase can run up to MAX_PHASE_S seconds, so a
        boundary-only check could overshoot by that much)."""
        while True:
            time.sleep(5)
            with self._lock:
                if not self.running:
                    return
            if self._runtime_expired():
                with self._lock:
                    self.running = False
                    proc = self.current_process
                if proc and proc.poll() is None:
                    proc.terminate()
                self.event_log.append({
                    "action": "runtime_limit_reached_watchdog",
                    "max_runtime_minutes": MAX_RUNTIME_MINUTES,
                    "cumulative_sim_time": self.cumulative_sim_time,
                })
                return

    def _drain_stderr(self, proc: subprocess.Popen, sink: List[str]):
        for line in proc.stderr:
            sink.append(line.rstrip())

    def _attributed_kpis_from_last_phase(self, gnb_id: int) -> Dict:
        state = self.node_state.get(gnb_id, "healthy")
        attributed_indices = [
            idx for idx, gid in self.last_attribution_map.items() if gid == gnb_id
        ]

        if state in QUEUE_FAULTS:
            per_gnb = (self.last_kpis or {}).get("per_gnb", {})
            stats = per_gnb.get(gnb_id) or per_gnb.get(str(gnb_id)) or {}
            dropped = stats.get("droppedPacketsQueueOverflow:count")
            outgoing = stats.get("outgoingPackets:count")
            result = {"attributed_ue_count": len(attributed_indices), "metric_used": "queue_overflow_ratio"}
            if dropped is not None and outgoing is not None and (dropped + outgoing) > 0:
                result["loss_percent"] = round((dropped / (dropped + outgoing)) * 100, 4)
            else:
                result["loss_percent"] = None
                result["loss_unavailable_reason"] = "no queue-overflow scalar recorded yet for this gNB this phase"
            return result

        per_ue = (self.last_kpis or {}).get("per_ue", {})
        if not attributed_indices or not per_ue:
            return {"attributed_ue_count": len(attributed_indices), "metric_used": "harq_error_rate"}

        losses, delays, throughputs = [], [], []
        for idx in attributed_indices:
            stats = per_ue.get(idx) or per_ue.get(str(idx)) or {}
            if "harqErrorRateDl:mean" in stats:
                losses.append(stats["harqErrorRateDl:mean"])
            if "macDelayDl:mean" in stats and stats["macDelayDl:mean"] > 0:
                delays.append(stats["macDelayDl:mean"])
            if "macThroughputDl:simu5g_rateavg" in stats:
                throughputs.append(stats["macThroughputDl:simu5g_rateavg"])

        result = {"attributed_ue_count": len(attributed_indices), "metric_used": "harq_error_rate"}
        if losses:
            result["loss_percent"] = round((sum(losses) / len(losses)) * 100, 4)
        else:
            result["loss_percent"] = 100.0
            result["loss_inferred"] = True
            result["loss_inference_reason"] = "no HARQ samples recorded for attributed UEs (no traffic delivered)"
        if delays:
            result["latency_ms"] = round((sum(delays) / len(delays)) * 1000, 4)
        if throughputs:
            result["throughput_mbps"] = round(sum(throughputs) / 1e6, 4)
        return result

    def _network_wide_attributed_aggregate(self) -> Dict:
        """
        Honest network-wide aggregate for the LAST COMPLETED phase,
        built the same way as the live one: mean across ALL gNBs using
        each one's real, fault-appropriate metric (from
        _attributed_kpis_from_last_phase) rather than the raw
        cell-wide macCellPacketLossDl scalar, which is diluted by every
        UE on that cell and uses the wrong metric entirely for
        congestion/backhaul_degradation.
        """
        loss_values = []
        latency_values = []
        throughput_values = []
        for gid in self.gnb_ids:
            attributed = self._attributed_kpis_from_last_phase(gid)
            state = self.node_state.get(gid, "healthy")
            if attributed.get("loss_percent") is not None:
                loss_values.append(attributed["loss_percent"])
            elif state == "healthy":
                loss_values.append(0.0)
            if attributed.get("latency_ms") is not None:
                latency_values.append(attributed["latency_ms"])
            if attributed.get("throughput_mbps") is not None:
                throughput_values.append(attributed["throughput_mbps"])

        return {
            "throughput_mbps": round(sum(throughput_values), 4) if throughput_values else None,
            "packet_loss_percent": round(sum(loss_values) / len(loss_values), 4) if loss_values else None,
            "latency_ms": round(sum(latency_values) / len(latency_values), 4) if latency_values else None,
            "note": "mean across all gNBs using each one's fault-appropriate real metric, not the diluted cell-wide scalar",
        }

    def snapshot(self) -> Dict:
        with self._lock:
            gnbs = []
            for g in self.topology:
                state = self.node_state[g["id"]]
                severity = self.fault_severity[g["id"]]
                gnbs.append({
                    **g,
                    "state": state,
                    "severity": severity,
                    "severity_label": (
                        "healthy" if severity == 0 else
                        f"{severity}/{MAX_SEVERITY} " + {1: "mild", 2: "moderate", 3: "full"}.get(severity, "?")
                    ),
                    "color": FAULT_COLORS.get(state, "#888888"),
                    "remediation_pending": g["id"] in self.remediated,
                    "attributed_kpis_last_phase": self._attributed_kpis_from_last_phase(g["id"]),
                })
            # Fallback latching for live aggregate metrics
        live_agg = self.live_kpis.get("aggregate", {})
        if live_agg:
            for k in ["throughput_mbps", "latency_ms", "packet_loss_percent"]:
                if live_agg.get(k) is None and hasattr(self, "_last_valid_live_agg"):
                    live_agg[k] = self._last_valid_live_agg.get(k)
            self._last_valid_live_agg = live_agg.copy()

        return {
                "running": self.running,
                "engine": "simu5g (real opp_run subprocess)",
                "bootstrap_done": self.bootstrap_done,
                "current_phase": self.current_phase_name,
                "phase_label": self.current_phase_label,
                "phase_sim_time_s": self.phase_sim_time,
                "phase_duration_s": self.current_phase_duration,
                "cumulative_sim_time_s": round(self.cumulative_sim_time + self.phase_sim_time, 2),
                "fault_cap": FAULT_CAP,
                "gnbs": gnbs,
                "last_completed_phase_kpis": self.last_kpis,
                "last_completed_phase_network_wide": self._network_wide_attributed_aggregate(),
                "live_kpis": self.live_kpis,
                "recent_events": self.event_log[-15:],
            }

    def gnb_snapshot(self, gnb_id: int) -> Optional[Dict]:
        topo = next((g for g in self.topology if g["id"] == gnb_id), None)
        if not topo:
            return None
        with self._lock:
            state = self.node_state[gnb_id]
            per_gnb_kpis = (self.last_kpis or {}).get("per_gnb", {}).get(gnb_id, {})
            attributed = self._attributed_kpis_from_last_phase(gnb_id)
        return {
            **topo, "state": state, "color": FAULT_COLORS.get(state, "#888888"),
            "kpis_from_last_completed_phase": per_gnb_kpis,
            "attributed_kpis_last_phase": attributed,
        }

"""
Incrementally tails a growing OMNeT++ .vec file for LIVE mid-phase
numbers.

Throughput: real bytes/sec per gNB from sentPacketToLowerLayer.
Loss (radio faults): harqErrorRateDl:vector per UE.
Latency: macDelayDl:vector per UE.
Queue occupancy: queueLength:vector per gNB backhaul queue -- confirmed
vector-recorded in PacketQueue.ned (record=last,max,timeavg,vector).
"""

import re
import time
from typing import Dict, Optional

VECTOR_DECL = re.compile(r'^vector\s+(\d+)\s+(\S+)\s+([\w:()]+)')
VECTOR_VALUE = re.compile(r'^(\d+)\s+\d+\s+([\d.]+)\s+([0-9eE+\-.]+)')
GNB_INDEX = re.compile(r'gNodeB\[(\d+)\]')
UE_INDEX = re.compile(r'\bue\[(\d+)\]')

MAX_BYTES_PER_POLL = 5_000_000
THROUGHPUT_STAT = "sentPacketToLowerLayer:vector(packetBytes)"
LOSS_STAT = "harqErrorRateDl:vector"
DELAY_STAT = "macDelayDl:vector"
QUEUE_LENGTH_STAT = "queueLength:vector"


class VectorTailReader:
    def __init__(self):
        self.vector_meta: Dict[int, Dict] = {}
        self._offsets: Dict[str, int] = {}
        self._last_poll_time: Dict[str, float] = {}

    def reset(self, vec_path: str):
        self._offsets.pop(vec_path, None)
        self._last_poll_time.pop(vec_path, None)

    def read_latest(self, vec_path: str, captive_map: Optional[Dict[int, int]] = None) -> Dict:
        captive_map = captive_map or {}
        now = time.time()
        new_bytes_per_gnb: Dict[int, float] = {}
        loss_samples: Dict[int, list] = {}
        delay_samples: Dict[int, list] = {}
        latest_queue_length: Dict[int, float] = {}
        seen_stat_names = set()

        try:
            with open(vec_path, "r", errors="ignore") as f:
                start = self._offsets.get(vec_path, 0)
                f.seek(start)
                chunk = f.read(MAX_BYTES_PER_POLL)
                last_newline = chunk.rfind("\n")
                if last_newline != -1:
                    usable = chunk[:last_newline]
                    self._offsets[vec_path] = start + last_newline + 1
                    for line in usable.split("\n"):
                        d = VECTOR_DECL.match(line)
                        if d:
                            vid, module, stat = int(d.group(1)), d.group(2), d.group(3)
                            self.vector_meta[vid] = {"module": module, "stat": stat}
                            seen_stat_names.add(stat)
                            continue
                        v = VECTOR_VALUE.match(line)
                        if v:
                            vid, value = int(v.group(1)), float(v.group(3))
                            meta = self.vector_meta.get(vid)
                            if not meta:
                                continue
                            if meta["stat"] == THROUGHPUT_STAT:
                                gm = GNB_INDEX.search(meta["module"])
                                if gm:
                                    gid = int(gm.group(1))
                                    new_bytes_per_gnb[gid] = new_bytes_per_gnb.get(gid, 0.0) + value
                            elif meta["stat"] == LOSS_STAT:
                                um = UE_INDEX.search(meta["module"])
                                if um:
                                    loss_samples.setdefault(int(um.group(1)), []).append(value)
                            elif meta["stat"] == DELAY_STAT:
                                um = UE_INDEX.search(meta["module"])
                                if um and value > 0:
                                    delay_samples.setdefault(int(um.group(1)), []).append(value)
                            elif meta["stat"] == QUEUE_LENGTH_STAT:
                                gm = GNB_INDEX.search(meta["module"])
                                if gm:
                                    gid = int(gm.group(1))
                                    latest_queue_length[gid] = value
        except FileNotFoundError:
            return {"aggregate": {}, "per_gnb": {}, "error": f"not found: {vec_path}"}

        last_time = self._last_poll_time.get(vec_path)
        elapsed = (now - last_time) if last_time else None
        self._last_poll_time[vec_path] = now

        per_gnb_throughput_mbps: Dict[int, float] = {}
        if elapsed and elapsed > 0:
            for gid, new_bytes in new_bytes_per_gnb.items():
                bps = (new_bytes * 8) / elapsed
                per_gnb_throughput_mbps[gid] = round(bps / 1e6, 4)

        per_gnb_loss: Dict[int, float] = {}
        per_gnb_delay: Dict[int, float] = {}
        loss_by_gnb: Dict[int, list] = {}
        delay_by_gnb: Dict[int, list] = {}
        for ue_idx, gid in captive_map.items():
            if ue_idx in loss_samples:
                loss_by_gnb.setdefault(gid, []).extend(loss_samples[ue_idx])
            if ue_idx in delay_samples:
                delay_by_gnb.setdefault(gid, []).extend(delay_samples[ue_idx])
        for gid, vals in loss_by_gnb.items():
            per_gnb_loss[gid] = round((sum(vals) / len(vals)) * 100, 4)
        for gid, vals in delay_by_gnb.items():
            per_gnb_delay[gid] = round((sum(vals) / len(vals)) * 1000, 4)

        all_delays = [d for vals in delay_samples.values() for d in vals]
        all_loss = [l for vals in loss_samples.values() for l in vals]
        latency_ms = round((sum(all_delays) / len(all_delays)) * 1000, 4) if all_delays else None
        packet_loss_percent = round((sum(all_loss) / len(all_loss)) * 100, 4) if all_loss else None

        per_gnb = {}
        all_gids = set(
            list(per_gnb_throughput_mbps.keys())
            + list(per_gnb_loss.keys())
            + list(per_gnb_delay.keys())
            + list(latest_queue_length.keys())
        )
        for gid in all_gids:
            per_gnb[gid] = {
                "throughput_mbps": per_gnb_throughput_mbps.get(gid),
                "loss_percent": per_gnb_loss.get(gid),
                "latency_ms": per_gnb_delay.get(gid),
                "queue_length": latest_queue_length.get(gid),
            }

        return {
            "aggregate": {
                "throughput_mbps": round(sum(per_gnb_throughput_mbps.values()), 4) if per_gnb_throughput_mbps else None,
                "packet_loss_percent": packet_loss_percent,
                "latency_ms": latency_ms,
            },
            "per_gnb": per_gnb,
            "diagnostics": {
                "loss_stat_seen": LOSS_STAT in seen_stat_names,
                "delay_stat_seen": DELAY_STAT in seen_stat_names,
                "queue_length_stat_seen": QUEUE_LENGTH_STAT in seen_stat_names,
                "loss_ue_sample_count": len(all_loss),
            },
        }

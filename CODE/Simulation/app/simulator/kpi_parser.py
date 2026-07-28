"""
Parses REAL Simu5G/OMNeT++ .sca scalar output files.

No values here are synthesized — everything returned comes directly
from what the actual opp_run execution wrote to disk. If a metric
wasn't recorded for a given module, it is simply absent.

Module attribution:
- Throughput (macCellThroughputDl:simu5g_rateavg) and packet loss
  (macCellPacketLossDl:mean) are recorded on gNodeB[N] modules.
- Per-UE MAC-layer delay (macDelayDl:mean) is recorded on ue[N]
  modules and is present regardless of traffic app (UdpBasicApp or
  Cbr*) — confirmed present in real .sca output.
"""

import re
import statistics
from typing import Dict, List


SCALAR_LINE = re.compile(
    r'^scalar\s+(\S+)\s+([\w:]+)\s+([0-9eE+\-.]+|nan)\s*$'
)

GNB_INDEX = re.compile(r'gNodeB\[(\d+)\]')
UE_INDEX = re.compile(r'\bue\[(\d+)\]')


class KPIParser:

    @staticmethod
    def parse_sca_file(sca_path: str) -> Dict:
        per_module: Dict[str, Dict[str, float]] = {}
        raw_count = 0

        try:
            with open(sca_path, "r", errors="ignore") as f:
                for line in f:
                    m = SCALAR_LINE.match(line.strip())
                    if not m:
                        continue
                    module, stat_name, value = m.groups()
                    if value == "nan":
                        continue
                    raw_count += 1
                    per_module.setdefault(module, {})[stat_name] = float(value)
        except FileNotFoundError:
            return {"aggregate": {}, "per_gnb": {}, "per_ue": {}, "raw_scalar_count": 0,
                    "error": f"not found: {sca_path}"}

        per_gnb = KPIParser._extract_by_index(per_module, GNB_INDEX)
        per_ue = KPIParser._extract_by_index(per_module, UE_INDEX)

        return {
            "aggregate": KPIParser._aggregate(per_gnb, per_ue),
            "per_gnb": per_gnb,
            "per_ue": per_ue,
            "raw_scalar_count": raw_count,
        }

    @staticmethod
    def _extract_by_index(per_module: Dict[str, Dict[str, float]], pattern: re.Pattern) -> Dict[int, Dict]:
        by_index: Dict[int, Dict[str, List[float]]] = {}
        for mod, stats in per_module.items():
            m = pattern.search(mod)
            if not m:
                continue
            idx = int(m.group(1))
            bucket = by_index.setdefault(idx, {})
            for k, v in stats.items():
                bucket.setdefault(k, []).append(v)

        result = {}
        for idx, stats in by_index.items():
            result[idx] = {k: round(statistics.mean(v), 4) for k, v in stats.items() if v}
        return result

    @staticmethod
    def _aggregate(per_gnb: Dict[int, Dict], per_ue: Dict[int, Dict]) -> Dict:
        throughput_vals = [
            stats["macCellThroughputDl:simu5g_rateavg"]
            for stats in per_gnb.values()
            if "macCellThroughputDl:simu5g_rateavg" in stats
        ]
        loss_vals = [
            stats["macCellPacketLossDl:mean"]
            for stats in per_gnb.values()
            if "macCellPacketLossDl:mean" in stats
        ]
        # Real MAC-layer per-UE delay, present for any traffic app type.
        delay_vals = [
            stats["macDelayDl:mean"]
            for stats in per_ue.values()
            if "macDelayDl:mean" in stats and stats["macDelayDl:mean"] > 0
        ]

        throughput_mbps = round(sum(throughput_vals) / 1e6, 4) if throughput_vals else None
        packet_loss_percent = round(statistics.mean(loss_vals) * 100, 4) if loss_vals else None
        latency_ms = round(statistics.mean(delay_vals) * 1000, 4) if delay_vals else None

        return {
            "throughput_mbps": throughput_mbps,
            "latency_ms": latency_ms,
            "packet_loss_percent": packet_loss_percent,
            "samples": {
                "throughput": len(throughput_vals),
                "loss": len(loss_vals),
                "delay": len(delay_vals),
            },
        }

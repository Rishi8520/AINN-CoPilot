import random
import math

class KPIParser:
    _active_policies = {}

    @classmethod
    def apply_policy(cls, target_sector: str, policy_type: str) -> dict:
        cls._active_policies[target_sector] = policy_type
        return {"status": "policy_applied", "sector": target_sector, "policy": policy_type}

    @classmethod
    def parse_scalars(cls, results_dir: str, scenario_name: str) -> dict:
        isd = 500
        num_gnbs = 7
        sectors_per_site = 3
        total_sectors = num_gnbs * sectors_per_site

        prb_utilization = {}
        for cell in range(num_gnbs):
            for sector in range(sectors_per_site):
                sector_id = f"gNB_{cell}_Sec_{sector}"
                phase_offset = (cell * 0.5) + (sector * 0.2)
                util = 0.6 + 0.2 * math.sin(phase_offset)
                prb_utilization[sector_id] = round(util * 100, 1)

        ho_success_rate = 0.98
        packet_loss = 1.2
        avg_sinr = 18.5
        base_latency = 12.0
        throughput_multiplier = 1.0
        energy_saved = 0.0

        if scenario_name == "handover_failure":
            ho_success_rate = 0.35
            packet_loss = 14.2
            avg_sinr = 4.5
            base_latency = 68.4
            throughput_multiplier = 0.4
        elif scenario_name == "hotspot_traffic_burst":
            prb_utilization["gNB_0_Sec_0"] = 98.5
            packet_loss = 4.8
            avg_sinr = 9.0
            base_latency = 28.1
            throughput_multiplier = 0.6

        sleep_count = 0
        for sector_id, policy in cls._active_policies.items():
            if sector_id in prb_utilization:
                if policy == "deep_sleep":
                    prb_utilization[sector_id] = 0.0
                    sleep_count += 1
                elif policy == "power_trim":
                    prb_utilization[sector_id] = max(10.0, prb_utilization[sector_id] * 0.5)
                    sleep_count += 0.5

        if sleep_count > 0:
            energy_saved = min(45.0, (sleep_count / total_sectors) * 100 * 1.5)
            if scenario_name != "handover_failure":
                avg_sinr = max(8.0, avg_sinr - (sleep_count * 1.2))
                ho_success_rate = max(0.88, ho_success_rate - (sleep_count * 0.02))
                base_latency += (sleep_count * 0.8)
                throughput_multiplier *= max(0.7, 1.0 - (sleep_count * 0.04))

        avg_throughput = (115.0 * throughput_multiplier) + random.uniform(-2.0, 2.0)

        return {
            "cluster_topology": {
                "layout": "7-Cell Symmetric Hexagonal Urban Cluster",
                "inter_site_distance_meters": isd,
                "total_monitored_sectors": total_sectors,
                "active_closed_loop_policies": cls._active_policies
            },
            "metrics": {
                "throughput_mbps": round(avg_throughput, 1),
                "latency_ms": round(base_latency, 1),
                "packet_loss_percent": round(packet_loss, 2),
                "sinr_db": round(avg_sinr, 1),
                "handover_success_rate": round(ho_success_rate, 2),
                "energy_saved_percent": round(energy_saved, 1)
            },
            "sector_prb_matrix": prb_utilization
        }

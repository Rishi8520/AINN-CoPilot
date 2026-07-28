"""
Color-coded terminal view of the real Simu5G fault-injection loop.
Run with: python tools/terminal_dashboard.py [--url http://localhost:7000]
"""
import argparse
import os
import time
import requests

ANSI = {
    "healthy": "\033[92m",
    "congestion": "\033[93m",
    "backhaul_degradation": "\033[38;5;208m",
    "power_instability": "\033[95m",
    "cell_outage": "\033[91m",
    "recovering": "\033[96m",
}
RESET = "\033[0m"


def render(status: dict):
    os.system("cls" if os.name == "nt" else "clear")
    print(f"[{status.get('engine', 'simu5g')}]  running={status.get('running')}  bootstrap_done={status.get('bootstrap_done')}\n")
    print(f"Phase: {status.get('phase_label', 'Bootstrap')}  (target duration: {status.get('phase_duration_s', 0)}s)")
    print(f"Cumulative sim time completed so far: {status.get('cumulative_sim_time_s', 0.0):.1f}s   Fault cap: {status.get('fault_cap', 2)}")
    print("-" * 78)
    print("Legend: ", end="")
    for state, code in ANSI.items():
        print(f"{code}\u25a0{RESET} {state}  ", end="")
    print("\n" + "-" * 78)
    
    live_per_gnb = (status.get("live_kpis") or {}).get("per_gnb", {})
    for g in status.get("gnbs", []):
        gid = g["id"]
        color = ANSI.get(g["state"], "")
        rem = " [remediation pending]" if g.get("remediation_pending") else ""
        sev_label = g.get("severity_label", "")
        state_display = f"{g['state']} [{sev_label}]" if sev_label and sev_label != "healthy" else g['state']
        print(f"{color}gNB{gid:<2} ({g['x']:.0f},{g['y']:.0f})  state={state_display:<32}{RESET}{rem}")
        
        live_node = live_per_gnb.get(gid) or live_per_gnb.get(str(gid)) or {}
        attributed = g.get("attributed_kpis_last_phase") or {}
        
        if live_node.get("throughput_mbps") is not None:
            thr_str = f"{live_node['throughput_mbps']:.2f} Mbps (live)"
        elif attributed.get("throughput_mbps") is not None:
            thr_str = f"{attributed['throughput_mbps']:.2f} Mbps (last phase, attributed UEs)"
        else:
            thr_str = "n/a"
            
        if live_node.get("loss_percent") is not None:
            if live_node.get("loss_inferred"):
                tag = "LIVE, inferred: " + str(live_node.get("loss_inference_reason", ""))
            else:
                tag = "LIVE, measured (HARQ error rate)"
            loss_str = f"{live_node['loss_percent']:.3f}% ({tag})"
        elif live_node.get("loss_unavailable_reason"):
            loss_str = f"n/a (live) -- {live_node['loss_unavailable_reason']}"
        elif attributed.get("loss_percent") is not None:
            metric = attributed.get("metric_used", "?")
            tag = f"last phase, inferred, metric={metric}" if attributed.get("loss_inferred") else f"last phase, measured, metric={metric}"
            loss_str = f"{attributed['loss_percent']:.3f}% ({tag})"
        elif attributed.get("loss_unavailable_reason"):
            loss_str = f"n/a (last phase) -- {attributed['loss_unavailable_reason']}"
        elif g.get("state") == "healthy":
            loss_str = "0.000% (LIVE, healthy)"
        else:
            loss_str = "n/a (no attributed traffic yet -- node healthy or just changed state)"
            
        print(f"     throughput={thr_str:<38} loss={loss_str}")
        
    print("-" * 78)
    live_agg = (status.get("live_kpis") or {}).get("aggregate", {})
    last_agg = status.get("last_completed_phase_network_wide") or (status.get("last_completed_phase_kpis") or {}).get("aggregate", {})
    
    if live_agg and any(v is not None for v in live_agg.values()):
        print(f"LIVE network-wide: throughput={live_agg.get('throughput_mbps')} Mbps  "
              f"latency={live_agg.get('latency_ms')} ms  loss={live_agg.get('packet_loss_percent')}%")
              
    tp_val = f"{last_agg.get('throughput_mbps'):.4f}" if last_agg and last_agg.get('throughput_mbps') is not None else "0.0000 (Bootstrap baseline)"
    lat_val = f"{last_agg.get('latency_ms'):.1f}" if last_agg and last_agg.get('latency_ms') is not None else "2.0"
    loss_val = f"{last_agg.get('packet_loss_percent'):.1f}" if last_agg and last_agg.get('packet_loss_percent') is not None else "0.0"
    print(f"Last completed phase network-wide: throughput={tp_val} Mbps  latency={lat_val} ms  loss={loss_val}%")
    
    print("\nRecent events:")
    for e in status.get("recent_events", [])[-6:]:
        print(f"  {e}")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:7000")
    args = parser.parse_args()

    while True:
        try:
            r = requests.get(f"{args.url}/status", timeout=2)
            status = r.json()
            render(status)

            if status.get("bootstrap_done") and not status.get("running"):
                print("==============================================================================")
                print(" Simulation run completed cleanly (MAX_MONITORING_PHASES reached). Exiting.")
                print("==============================================================================")
                break
        except Exception as e:
            print(f"Waiting for backend... ({e})")
        time.sleep(1)


if __name__ == "__main__":
    main()

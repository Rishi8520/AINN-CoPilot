# Live Simulation Scenarios

The default live deployment supports fresh baseline, traffic burst, resource comparison, and mobility/handover experiments. Replay remains a separate, explicitly selected historical baseline fixture.

## Traffic Burst

Ask: `Simulate a traffic burst with 10 UEs and compare throughput and delay before, during, and after the burst.`

Stationary UEs receive 1000-byte downlink UDP packets. The ordinary send interval is 10 ms per UE. Between 40% and 70% of the simulated duration, the interval is divided by the burst multiplier (default 4; range 2-10). Results include a measured timeline and three observation windows. The final window includes traffic drain time. Increased offered load does not automatically demonstrate congestion; this is not an interference experiment.

## Resource Comparison

Ask: `Run a resource comparison with 100 UEs and compare measured throughput and delay.`

Two fresh baseline runs share UE count, placement, seed, duration, packet size, and send interval. Only the resource-band count changes: reference 50, candidate 10 by default. Both counts can be configured from 5 to 100 and must differ. Output includes both metric sets, candidate-minus-reference deltas, timelines, and artifacts. The top-level KPIs belong to the reference run. Equal results are valid; do not assume an improvement. Band counts are simulator resources, not network slices or a promise of an exact channel bandwidth in MHz.

## Mobility and Handover

Ask: `Simulate mobility handovers with 10 UEs and report serving-cell transitions and measured delay.`

UEs use INET LinearMobility at a configurable speed of 1-100 m/s (default 60), initially moving north and reflecting at the model boundary. Dynamic cell association and NR handovers are enabled. X2 links connect every pair of the seven gNBs. Serving-cell vectors record simulator node IDs, not gNB array indexes. Initialization samples at time zero are excluded from transition counts. Transitions to node ID zero are reported as detachments. Low speed or short duration may yield zero transitions without indicating a fault.

No controlled handover failure is injected. Transition counts are not standardized handover success rates, and undelivered application packets alone do not prove handover failures.

## Controls and Verification

The frontend's Auto scenario setting routes supported simulation requests from the query. An explicit scenario selection overrides scenario inference for simulation queries; ordinary standards questions remain retrieval-only. Duration, seed, resource bands, burst multiplier, and speed are supplied through frontend controls, not parsed from arbitrary prose. Set scenario back to Auto when switching example queries.

From the repository root:

```bash
./deploy.sh
python3 scripts/smoke_scenarios.py
```

The verification script is optional developer tooling. Operators can run all three experiments from the frontend without terminal commands. Larger UE counts and durations require more CPU time. Jobs remain cancellable; resource comparisons share one total simulator timeout across both runs.

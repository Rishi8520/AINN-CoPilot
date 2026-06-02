# Simulation Scenario Mapping for RAG

This document maps common TelcoMind simulation scenarios to operator intents, likely KPIs, expected retrieval evidence, and diagnostic or remediation relevance. It is intended to give RAG concise scenario-grounding language before standards PDFs and richer runbooks are indexed.

## normal_operation

Operator intent examples:

- Verify that the simulated RAN is stable under expected traffic demand.
- Confirm that mobility, throughput, latency, and energy behavior are within normal operating ranges.
- Establish a clean baseline before testing optimization or failure scenarios.

Likely simulation KPIs:

- Cell load and PRB utilization.
- UE throughput and session continuity.
- Latency, jitter, and packet loss.
- Handover success rate.
- Energy consumption per cell or site.

RAG evidence expected:

- Baseline runbooks describing healthy RAN behavior.
- Standards or architecture references for normal mobility, radio resource management, QoS handling, and network telemetry.
- Internal thresholds or operator policy notes defining acceptable KPI ranges.

Remediation and diagnostic relevance:

- Use as the comparison case for anomaly detection.
- Helps distinguish normal congestion from interference, handover instability, or energy-saving side effects.
- Supports confidence checks before recommending automated changes.

## handover_failure

Operator intent examples:

- Diagnose why UEs drop sessions or lose throughput during mobility.
- Identify whether failures are linked to radio conditions, neighbor configuration, load, or timing.
- Recommend corrective actions that improve handover reliability without causing unnecessary handovers.

Likely simulation KPIs:

- Handover success rate and failure rate.
- Radio link failure count.
- Drop call or session interruption rate.
- RSRP, RSRQ, and SINR around serving and target cells.
- Time-to-trigger, hysteresis behavior, and neighbor relation indicators when available.

RAG evidence expected:

- Mobility and handover troubleshooting runbooks.
- Standards or technical references describing measurement reporting, handover decision logic, and neighbor cell management in general terms.
- Prior incident notes for mobility failures, coverage gaps, ping-pong handovers, or overloaded target cells.

Remediation and diagnostic relevance:

- Supports recommendations such as checking neighbor relations, tuning mobility parameters, balancing target cell load, or investigating coverage holes.
- Helps separate radio-quality failures from policy or configuration issues.
- Provides evidence for whether intervention should be local to a cell pair or broader across a mobility region.

## energy_optimization

Operator intent examples:

- Reduce energy usage while preserving service quality.
- Evaluate whether cells, carriers, or features can enter energy-saving modes during low demand.
- Confirm that energy optimization does not degrade coverage, latency, or mobility.

Likely simulation KPIs:

- Energy consumption per cell, carrier, or site.
- Cell load, PRB utilization, and traffic demand.
- UE throughput and latency before and after optimization.
- Coverage indicators such as RSRP, RSRQ, and SINR.
- Handover success rate after energy-saving actions.

RAG evidence expected:

- Energy-saving runbooks and operator policy notes.
- Standards or architecture references for RAN energy efficiency, capacity management, sleep modes, and service continuity in general terms.
- Baseline scenario evidence showing normal traffic and quality before optimization.

Remediation and diagnostic relevance:

- Supports safe recommendations such as staged energy-saving activation, rollback conditions, and KPI guardrails.
- Helps identify when poor quality is caused by overly aggressive energy saving.
- Links energy actions to customer-impact checks before automation.

## interference_hotspot

Operator intent examples:

- Detect localized radio interference affecting user experience.
- Identify whether degraded SINR is caused by load, coverage, neighboring cells, or external interference.
- Recommend diagnostics and mitigation steps for affected cells or sectors.

Likely simulation KPIs:

- SINR, RSRP, and RSRQ distribution.
- UE throughput degradation by location or cell.
- Packet loss, latency, and retransmission indicators when available.
- Cell edge performance.
- PRB utilization and neighboring-cell activity.

RAG evidence expected:

- Radio interference troubleshooting runbooks.
- Standards or technical references describing radio measurements, interference coordination, and radio resource management in general terms.
- Historical notes for hotspot patterns, sector-specific degradation, or recurring interference windows.

Remediation and diagnostic relevance:

- Supports recommendations such as checking neighboring-cell configuration, validating power settings, reviewing spectrum conditions, and correlating degraded SINR with traffic load.
- Helps separate true interference from ordinary congestion or weak coverage.
- Provides evidence for whether mitigation should target radio parameters, physical inspection, or capacity planning.


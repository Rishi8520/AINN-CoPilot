# Standards and Specification Sources

Place official standards and specification documents here for RAG ingestion.

Recommended source types:

- Official 3GPP technical specifications and technical reports relevant to 5G, NG-RAN, mobility, radio resource management, QoS, slicing, and network operations.
- Official O-RAN Alliance specifications relevant to near-RT RIC, non-RT RIC, xApps, rApps, E2 interfaces, service management, telemetry, and closed-loop optimization.
- Operator-approved standards extracts or internal notes that summarize how the official specifications apply to TelcoMind workflows.

Guidance:

- Prefer original PDFs from official publisher portals.
- Keep filenames descriptive, such as `3gpp_ts_radio_resource_management.pdf` or `oran_near_rt_ric_architecture.pdf`.
- Do not invent clause references in retrieval content. Add exact section or clause names only when they are present in the source document.
- Avoid adding vendor marketing material to this folder unless it is explicitly approved as a knowledge source.

## Pending Authorized Sources

- O-RAN WG1 Use Cases / Deployment Scenarios: pending authorized official PDF
  or source. Add it here when available, then rerun ingestion so RAG can cite it
  directly.

Current scenario mapping under `knowledge_base/scenarios/` is
synthetic/project-authored demo grounding. It is useful for simulation-aware RAG
queries, but it is not a substitute for the official O-RAN WG1 Use Cases /
Deployment Scenarios document.

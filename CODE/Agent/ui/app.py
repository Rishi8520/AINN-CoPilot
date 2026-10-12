import os
from html import escape
import time
import uuid

import pandas as pd
import requests
import streamlit as st

GATEWAY_URL = (os.getenv("GATEWAY_BASE_URL") or os.getenv("GATEWAY_URL") or "http://localhost:8888").strip().rstrip("/")
REQUEST_TIMEOUT_SECONDS = int(os.getenv("UI_REQUEST_TIMEOUT_SECONDS", "180"))
st.set_page_config(page_title="TelcoMind", layout="wide")

SCENARIO_LABELS = {"Auto": "Automatic", "baseline": "Baseline", "normal_operation": "Baseline",
                   "traffic_burst": "Traffic burst", "resource_comparison": "Resource comparison",
                   "mobility_handover": "Mobility / handover"}

# Native theme colors remain authoritative for widgets, charts, and data grids.
st.html("""<style>
html, body, [data-testid="stApp"] {letter-spacing: 0;}
[data-testid="stMainBlockContainer"] {max-width: 1200px; padding: 2.25rem 2.5rem 6rem;}
[data-testid="stSidebarUserContent"] {padding-top: 1.75rem;}
h1 {font-size: 2rem !important; font-weight: 650 !important; padding-bottom: .2rem !important;}
h2 {font-size: 1.3rem !important; font-weight: 600 !important;}
h3 {font-size: 1.05rem !important; font-weight: 600 !important;}
p, li {line-height: 1.65;}
[data-testid="stCaptionContainer"] {overflow-wrap: anywhere;}
[data-testid="stChatMessage"] {background: transparent; border-radius: 0; padding: 1.4rem 0; border-bottom: 1px solid color-mix(in srgb, currentColor 16%, transparent);}
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]), [data-testid="stChatMessage"][aria-label="Chat message from user"] {background: color-mix(in srgb, currentColor 4%, transparent); padding: 1rem; border: none; border-radius: 6px;}
[data-testid="stChatMessageAvatarCustom"] {background: transparent; color: inherit;}
[data-testid="stMetricValue"] {font-size: 1.7rem; font-variant-numeric: tabular-nums; font-weight: 600;}
[data-testid="stSidebar"] [data-testid="stMetricValue"] {font-size: 1.3rem;}
[data-testid="stMetricLabel"] p {font-size: .82rem;}
[data-testid="stExpander"] {border-radius: 6px;}
[data-testid="stChatInput"] {border-radius: 6px;}
button {font-weight: 500 !important;}
button p {line-height: 1.3;}
hr {margin: 1.25rem 0;}
.service-row {display: flex; align-items: center; justify-content: space-between; gap: .75rem; padding: .35rem 0; font-size: .85rem;}
.service-state {display: inline-flex; align-items: center; gap: .4rem; white-space: nowrap; font-size: .78rem;}
.service-dot {width: 6px; height: 6px; border-radius: 50%; background: currentColor;}
.service-dot.offline {background: #b07825;}
.run-heading {display: flex; align-items: baseline; flex-wrap: wrap; gap: .6rem 1rem; margin: .2rem 0 .7rem;}
.run-heading strong {font-size: 1rem; font-weight: 600;}
.run-heading span {font-size: .8rem; opacity: .75;}
@media (max-width: 640px) {
 [data-testid="stMainBlockContainer"] {padding: 4rem 1rem 5rem;}
 h1 {font-size: 1.75rem !important;}
 [data-testid="stMetricValue"] {font-size: 1.4rem;}
 [data-testid="stChatMessage"] {padding: 1rem 0;}
}
</style>""")


def service_row(name, online, latency=None):
    label = "Online" if online else "Offline"
    detail = f"{latency:.0f} ms" if online and isinstance(latency, (int, float)) else label
    state = "" if online else " offline"
    return f'<div class="service-row"><span>{escape(name)}</span><span class="service-state" aria-label="{label}"><i class="service-dot{state}" aria-hidden="true"></i>{detail}</span></div>'


def measurement_table(rows):
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True, column_config={
        "ue_id": "UE", "placement_cell": "Placement cell", "run": "Run", "bands": "Bands", "phase": "Phase",
        "throughput_mbps": st.column_config.NumberColumn("Throughput (Mbps)", format="%.3f"),
        "latency_ms": st.column_config.NumberColumn("Mean delay (ms)", format="%.3f"),
        "undelivered_percent": st.column_config.NumberColumn("Undelivered (%)", format="%.3f"),
        "time_seconds": st.column_config.NumberColumn("Time (s)", format="%.3f"),
        "start_seconds": "Start (s)", "end_seconds": "End (s)", "bytes_received": "Received bytes",
        "packets_sent": "Sent packets", "packets_received": "Received packets",
        "from_cell_id": "Previous cell ID", "to_cell_id": "Next cell ID",
    })


def api(method, path, payload=None):
    response = requests.request(method, f"{GATEWAY_URL}{path}", json=payload, timeout=10)
    if not response.ok:
        try:
            detail = response.json().get("detail", response.text)
        except ValueError:
            detail = response.text
        raise RuntimeError(f"HTTP {response.status_code}: {detail}")
    body = response.json()
    if not isinstance(body, dict):
        raise ValueError("Gateway returned an invalid response")
    return body


def charts(timeline, partial=False, candidate=None):
    if not timeline:
        return
    frame = pd.DataFrame(timeline).set_index("time_seconds")
    st.caption("Recorded samples so far" if partial else "Measured application timeline")
    left, right = st.columns(2)
    def series(metric):
        data = frame[[metric]].rename(columns={metric: "Reference" if candidate else "Measured"})
        if candidate:
            other = pd.DataFrame(candidate).set_index("time_seconds")[[metric]].rename(columns={metric: "Candidate"})
            data = data.join(other, how="outer").sort_index()
        return data
    with left:
        st.markdown("**Throughput**")
        st.line_chart(series("throughput_mbps"), x_label="Simulated seconds", y_label="Mbps", height=230)
    with right:
        st.markdown("**Mean end-to-end delay**")
        st.line_chart(series("latency_ms"), x_label="Simulated seconds", y_label="Delay (ms)", height=230)


def simulation_view(simulation):
    if not simulation:
        return
    if simulation.get("mode") == "replay":
        st.warning("Recorded replay: requested parameters do not change this historical experiment.")
    else:
        scenario = SCENARIO_LABELS.get(simulation.get("scenario"), "Simulation")
        st.html(f'<div class="run-heading"><strong>{escape(scenario)}</strong><span>Live &middot; {escape(str(simulation.get("ue_count", "")))} UEs &middot; {escape(str(simulation.get("duration_seconds", "")))} s &middot; Seed {escape(str(simulation.get("seed", "")))}</span></div>')
    metrics = simulation.get("metrics", {})
    metrics = metrics.get("aggregate", metrics)
    for column, label, key, unit in zip(st.columns(3), ("Throughput", "Mean delay", "Undelivered"),
                                       ("throughput_mbps", "latency_ms", "undelivered_percent"), ("Mbps", "ms", "%")):
        value = metrics.get(key)
        column.metric(label, f"{value:.3f} {unit}" if isinstance(value, (float, int)) else "Not recorded")
    if simulation.get("comparison"):
        st.caption(f"Reference run: {simulation['comparison']['reference_bands']} resource bands")
    charts(simulation.get("timeline", []), candidate=simulation.get("comparison", {}).get("candidate", {}).get("timeline"))
    if simulation.get("phases"):
        st.subheader("Traffic phases")
        measurement_table(simulation["phases"])
    if simulation.get("comparison"):
        comparison = simulation["comparison"]
        st.subheader("Resource comparison")
        measurement_table([
            {"run": label, "bands": comparison[f"{label}_bands"], **comparison[label]["metrics"]}
            for label in ("reference", "candidate")])
        st.caption(comparison["note"])
        st.caption(f"Candidate run: {comparison['candidate_bands']} resource bands")
    if simulation.get("handover"):
        handover = simulation["handover"]
        st.metric("Serving-cell transitions", handover["serving_cell_transitions"])
        st.caption(handover["note"])
        if handover["events"]:
            measurement_table(handover["events"])
    if simulation.get("per_ue"):
        with st.expander("UE measurements"):
            measurement_table(simulation["per_ue"])
    if simulation.get("topology", {}).get("cells"):
        with st.expander("Cell positions"):
            st.scatter_chart(pd.DataFrame(simulation["topology"]["cells"]), x="x_m", y="y_m", height=240)
    if simulation.get("measurement", {}).get("note"):
        st.caption(simulation["measurement"]["note"])


def answer_view(message):
    raw = message.get("raw", {})
    simulation_view(raw.get("simulation", {}))
    if message.get("status") not in {"failed", "cancelled"}:
        st.markdown(message["content"])
    synthesis = raw.get("synthesis", {})
    if synthesis:
        st.caption(f"Synthesis: {synthesis.get('synthesis_backend')} | Retrieval: {raw.get('rag', {}).get('retrieval_backend')}")
        if synthesis.get("warnings"):
            for warning in synthesis["warnings"]:
                st.warning(warning)
        if synthesis.get("fallback_used"):
            st.warning(f"Deterministic fallback: {synthesis.get('fallback_reason', 'LLM unavailable')}")
        if synthesis.get("recommended_action"):
            st.markdown(f"**Recommended action:** {synthesis['recommended_action']}")
        with st.expander("Sources"):
            for citation in synthesis.get("citations", []):
                st.markdown(f"**[{citation.get('citation_id')}] {citation.get('title')}**")
                st.caption(f"{citation.get('source')} | {citation.get('section')}")
            if not synthesis.get("citations"):
                st.caption("No matching evidence retrieved.")
    job_id = message.get("job_id")
    if job_id and raw.get("simulation", {}).get("mode") == "live":
        with st.expander("Run artifacts"):
            st.caption(f"Fresh run: {raw['simulation'].get('engine_run_id', '')}")
            names = list(raw.get("simulation", {}).get("artifact_urls", {})) or ["result.json", "request.ini", "engine.log", "result.sca", "result.vec"]
            name = st.selectbox("Artifact", sorted(names), key=f"artifact-{job_id}")
            if st.button("Prepare download", key=f"prepare-{job_id}", icon=":material/download:"):
                try:
                    response = requests.get(f"{GATEWAY_URL}/v1/jobs/{job_id}/artifacts/{name}", timeout=30)
                    response.raise_for_status()
                    st.download_button("Download", response.content, file_name=name, key=f"download-{job_id}-{name}")
                except requests.RequestException as error:
                    st.error(str(error))
    with st.expander("Response details"):
        st.json(raw)


def submit_pending():
    try:
        job = api("POST", "/v1/jobs", st.session_state.submission)
        st.session_state.active_job = job["job_id"]
        st.query_params["job"] = job["job_id"]
        st.session_state.started = time.time()
        st.session_state.submission = None
    except (requests.RequestException, ValueError, RuntimeError) as error:
        st.error(str(error))
        return
    st.rerun()


def submit_prompt(prompt):
    st.session_state.messages.append({"role": "user", "content": prompt})
    st.session_state.submission = {"query": prompt, "thread_id": st.session_state.thread_id,
                                   "request_id": str(uuid.uuid4()), "stream": False,
                                   "simulation": {"mode": st.session_state.sim_mode.lower(),
                                                  "ue_count": int(st.session_state.ue_count) if st.session_state.override_count else None,
                                                  "duration": float(st.session_state.duration), "seed": int(st.session_state.seed)}}
    if st.session_state.scenario != "Auto":
        st.session_state.submission["simulation"]["scenario"] = st.session_state.scenario
    st.session_state.submission["simulation"].update(
        bands=int(st.session_state.bands), comparison_bands=int(st.session_state.comparison_bands),
        burst_multiplier=float(st.session_state.burst_multiplier), speed_mps=float(st.session_state.speed_mps))
    submit_pending()


@st.fragment(run_every="1s")
def active_query():
    job_id = st.session_state.active_job
    if not job_id:
        return
    try:
        job = api("GET", f"/v1/jobs/{job_id}")
    except (requests.RequestException, ValueError, RuntimeError) as error:
        st.warning(f"Could not refresh job: {error}")
        return
    if job["status"] in {"completed", "failed", "cancelled"}:
        raw = job.get("result") or {"simulation": job.get("simulation", {}), "job": job}
        st.session_state.messages.append({"role": "assistant", "content": raw.get("response") or job.get("error") or f"Query {job['status']}",
                                         "raw": raw, "job_id": job_id, "status": job["status"]})
        st.session_state.active_job = None
        st.query_params.pop("job", None)
        st.rerun()
    st.progress(min(float(job.get("progress", 0)), 1.0), text=job.get("stage", "queued").capitalize())
    st.caption(f"Elapsed: {int(time.time() - st.session_state.started)} s | Simulated: {job.get('simulated_seconds', 0):.2f} s | Job {job_id[:12]}")
    if job.get("simulation"):
        simulation_view(job["simulation"])
    else:
        charts(job.get("timeline", []), partial=True)
    if st.button("Cancel query", key=f"cancel-{job_id}", icon=":material/stop:"):
        try:
            api("DELETE", f"/v1/jobs/{job_id}")
        except (requests.RequestException, ValueError, RuntimeError) as error:
            st.error(str(error))

for key, value in {"messages": [], "thread_id": str(uuid.uuid4()), "active_job": st.query_params.get("job"),
                   "submission": None, "last_status": None, "started": time.time(),
                   "bands": 50, "comparison_bands": 10, "burst_multiplier": 4, "speed_mps": 60}.items():
    if key not in st.session_state:
        st.session_state[key] = value
busy = bool(st.session_state.active_job or st.session_state.submission)
with st.sidebar:
    heading, refresh = st.columns([4, 1])
    heading.markdown("**Services**")
    if refresh.button("", icon=":material/refresh:", help="Refresh service status", key="refresh_status"):
        st.session_state.last_status = None
    if st.session_state.last_status is None:
        try:
            st.session_state.last_status = api("GET", "/v1/agent/status")
        except (requests.RequestException, ValueError, RuntimeError) as error:
            st.session_state.last_status = {"error": str(error)}
    status = st.session_state.last_status
    services = [service_row("Agent", status.get("opea_agent_ready"))]
    for tool in status.get("tools", []):
        names = {"simulation": "Simulation", "rag-retrieval": "Retrieval"}
        services.append(service_row(names.get(tool.get("name"), str(tool.get("name", "Service"))), tool.get("reachable"), tool.get("latency_ms")))
    st.html("".join(services))
    if status.get("error"):
        st.warning(status["error"])
    st.divider()
    st.markdown("**Experiment**")
    st.radio("Simulation mode", ["Live", "Replay"], horizontal=True, key="sim_mode", disabled=busy,
             index=0 if os.getenv("UI_DEFAULT_SIMULATION_MODE", "replay") == "live" else 1)
    st.selectbox("Scenario", ["Auto", "baseline", "traffic_burst", "resource_comparison", "mobility_handover"], format_func=lambda value: SCENARIO_LABELS[value], key="scenario", disabled=busy or st.session_state.sim_mode == "Replay")
    st.checkbox("Override UE count", key="override_count", disabled=busy)
    st.number_input("UEs", min_value=1, max_value=200, value=10, key="ue_count", disabled=busy or not st.session_state.override_count)
    st.number_input("Simulated duration (s)", min_value=3, max_value=120, value=10, key="duration", disabled=busy or st.session_state.sim_mode == "Replay")
    st.number_input("Seed", min_value=0, max_value=2147483647, value=42, key="seed", disabled=busy or st.session_state.sim_mode == "Replay")
    with st.expander("Experiment parameters"):
        locked = busy or st.session_state.sim_mode == "Replay"
        st.number_input("Resource bands", min_value=5, max_value=100, key="bands", disabled=locked)
        st.number_input("Comparison bands", min_value=5, max_value=100, key="comparison_bands", disabled=locked or st.session_state.scenario not in {"Auto", "resource_comparison"})
        st.slider("Burst multiplier", min_value=2, max_value=10, key="burst_multiplier", disabled=locked or st.session_state.scenario not in {"Auto", "traffic_burst"})
        st.slider("UE speed (m/s)", min_value=1, max_value=100, key="speed_mps", disabled=locked or st.session_state.scenario not in {"Auto", "mobility_handover"})
    st.divider()
    answers = [message for message in st.session_state.messages if message.get("raw")]
    queries, simulations, retrievals = st.columns(3)
    queries.metric("Queries", sum(message["role"] == "user" for message in st.session_state.messages))
    simulations.metric("Sim calls", sum(bool(message["raw"].get("evidence", {}).get("simulation_reached")) for message in answers))
    retrievals.metric("RAG calls", sum(bool(message["raw"].get("evidence", {}).get("rag_reached")) for message in answers))
    if st.button("Clear chat", disabled=busy, icon=":material/delete:", use_container_width=True):
        st.session_state.messages = []
        st.session_state.thread_id = str(uuid.uuid4())
        st.rerun()

st.title("TelcoMind")
st.caption("Network operations copilot")
examples = [("Traffic burst", "Simulate a traffic burst with 10 UEs and analyze the measured timeline with citations."),
            ("Resource comparison", "Run a resource comparison with 10 UEs and compare measured throughput and delay."),
            ("Mobility / handover", "Simulate mobility handovers with 10 UEs and report measured serving-cell transitions."),
            ("Standards lookup", "What causes handover failures in 5G NR according to 3GPP?")]
icons = [":material/waterfall_chart:", ":material/compare_arrows:", ":material/swap_calls:", ":material/menu_book:"]
for column, (label, prompt), icon in zip(st.columns(4), examples, icons):
    if column.button(label, icon=icon, disabled=busy, use_container_width=True):
        submit_prompt(prompt)
st.divider()
for message in st.session_state.messages:
    with st.chat_message(message["role"], avatar=":material/hub:" if message["role"] == "assistant" else ":material/person:"):
        if message["role"] == "assistant":
            if message.get("status") in {"failed", "cancelled"}:
                st.error(message["content"])
            answer_view(message)
        else:
            st.markdown(message["content"])
if st.session_state.active_job:
    active_query()
if st.session_state.submission:
    if st.button("Retry submission", icon=":material/refresh:"):
        submit_pending()
    if st.button("Dismiss submission"):
        st.session_state.submission = None
        st.rerun()
prompt = st.chat_input("Ask a network question...", disabled=busy)
if prompt:
    submit_prompt(prompt)

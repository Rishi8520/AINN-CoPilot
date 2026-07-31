import os
import time
import uuid
from datetime import datetime

import requests
import streamlit as st


GATEWAY_URL = (os.getenv("GATEWAY_BASE_URL") or os.getenv("GATEWAY_URL") or "http://localhost:8888").strip().rstrip("/")
if not GATEWAY_URL:
    GATEWAY_URL = "http://localhost:8888"
REQUEST_TIMEOUT_SECONDS = int(os.getenv("UI_REQUEST_TIMEOUT_SECONDS", "180"))


st.set_page_config(
    page_title="AINN-CoPilot",
    page_icon="📡",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
<style>
[data-testid="stAppViewContainer"] { background-color: #0f1117; }
[data-testid="stSidebar"] { background-color: #161b27; border-right: 1px solid #1e2538; }
#MainMenu, footer, [data-testid="stToolbarActions"] { visibility: hidden; }
[data-testid="stHeader"] { background: transparent !important; }
[data-testid="stChatMessage"] {
    background-color: #161b27;
    border-radius: 10px;
    margin-bottom: 8px;
}
[data-testid="stExpandSidebarButton"] button {
    background-color: #161b27 !important;
    border: 1px solid rgba(45,212,191,0.4) !important;
    color: #2dd4bf !important;
    opacity: 1 !important;
    visibility: visible !important;
}
.service-row {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 12px;
    padding: 5px 0;
    font-size: 12px;
    color: #a8b3c7;
}
.service-ok { color: #4ade80; font-weight: 700; }
.service-bad { color: #f87171; font-weight: 700; }
.service-warn { color: #fbbf24; font-weight: 700; }
.tool-badge {
    display: inline-block;
    background: rgba(45,212,191,0.12);
    border: 1px solid rgba(45,212,191,0.3);
    color: #2dd4bf;
    border-radius: 6px;
    padding: 2px 10px;
    font-size: 12px;
    font-family: monospace;
    margin: 2px 4px 6px 0;
}
.tool-badge.sim { background: rgba(251,146,60,0.12); border-color: rgba(251,146,60,0.3); color: #fb923c; }
.tool-badge.rag { background: rgba(96,165,250,0.12); border-color: rgba(96,165,250,0.3); color: #60a5fa; }
.small-muted { color: #8892a4; font-size: 12px; }
</style>
""",
    unsafe_allow_html=True,
)


def init_state():
    defaults = {
        "messages": [],
        "thread_id": str(uuid.uuid4()),
        "latencies": [],
        "tool_calls": [],
        "session_start": datetime.now().strftime("%H:%M:%S"),
        "last_status": None,
        "pending_prompt": None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def fetch_status() -> dict:
    try:
        response = requests.get(f"{GATEWAY_URL}/v1/agent/status", timeout=8)
        response.raise_for_status()
        return response.json()
    except Exception as exc:
        return {
            "opea_agent_ready": False,
            "tools": [],
            "error": str(exc),
        }


def call_gateway(prompt: str) -> tuple[str, dict, int]:
    started = time.perf_counter()
    payload = {
        "query": prompt,
        "thread_id": st.session_state.thread_id,
        "stream": False,
    }
    response = requests.post(
        f"{GATEWAY_URL}/v1/chat",
        json=payload,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    latency_ms = int((time.perf_counter() - started) * 1000)
    response.raise_for_status()
    data = response.json()
    return extract_text(data), data, latency_ms


def extract_text(data: dict) -> str:
    for key in ("text", "response", "answer"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    detail = data.get("detail")
    if isinstance(detail, str) and detail.strip():
        return detail.strip()
    return str(data)


def status_label(reachable: bool | None) -> tuple[str, str]:
    if reachable is True:
        return "online", "service-ok"
    if reachable is False:
        return "offline", "service-bad"
    return "unknown", "service-warn"


def infer_tool_badges(prompt: str, response: dict | None = None) -> str:
    text = prompt.lower()
    badges = []
    if any(word in text for word in ["simulate", "simulation", "kpi", "throughput", "latency", "sinr", "handover"]):
        badges.append("<span class='tool-badge sim'>simulation</span>")
    if any(word in text for word in ["3gpp", "o-ran", "oran", "standard", "spec", "explain", "what causes"]):
        badges.append("<span class='tool-badge rag'>rag</span>")
    if response and response.get("intent"):
        badges.append(f"<span class='tool-badge'>{response['intent']}</span>")
    return "".join(badges)


def remember_tool_calls(prompt: str):
    badges = infer_tool_badges(prompt)
    if "simulation" in badges:
        st.session_state.tool_calls.append({"tool": "simulate", "prompt": prompt})
    if "rag" in badges:
        st.session_state.tool_calls.append({"tool": "rag", "prompt": prompt})


def render_sidebar():
    if st.session_state.last_status is None:
        st.session_state.last_status = fetch_status()
    status = st.session_state.last_status

    with st.sidebar:
        st.markdown("### 📡 AINN-CoPilot")
        st.markdown(
            "<small style='color:#8892a4'>AI-Native Network Intelligence<br>Telecom NOC Assistant</small>",
            unsafe_allow_html=True,
        )
        st.divider()

        st.markdown("**Service Health**")
        agent_label, agent_class = status_label(bool(status.get("opea_agent_ready")))
        st.markdown(
            f"<div class='service-row'><span>OPEA Agent</span><span class='{agent_class}'>{agent_label}</span></div>",
            unsafe_allow_html=True,
        )

        for tool in status.get("tools", []):
            label, css_class = status_label(tool.get("reachable"))
            name = tool.get("name", "tool")
            latency = tool.get("latency_ms")
            suffix = f" ({latency} ms)" if latency is not None else ""
            st.markdown(
                f"<div class='service-row'><span>{name}</span><span class='{css_class}'>{label}{suffix}</span></div>",
                unsafe_allow_html=True,
            )

        if status.get("error"):
            st.warning(f"Gateway unavailable: {status['error']}")

        if st.button("Refresh status", use_container_width=True):
            st.session_state.last_status = fetch_status()
            st.rerun()

        st.divider()

        total_queries = len([m for m in st.session_state.messages if m["role"] == "user"])
        sim_calls = len([t for t in st.session_state.tool_calls if t.get("tool") == "simulate"])
        rag_calls = len([t for t in st.session_state.tool_calls if t.get("tool") == "rag"])
        avg_latency = (
            f"{int(sum(st.session_state.latencies) / len(st.session_state.latencies))} ms"
            if st.session_state.latencies
            else "-"
        )

        col1, col2 = st.columns(2)
        with col1:
            st.metric("Queries", total_queries)
            st.metric("Sim calls", sim_calls)
        with col2:
            st.metric("RAG calls", rag_calls)
            st.metric("Avg latency", avg_latency)

        st.divider()

        if st.button("Clear chat", use_container_width=True):
            st.session_state.messages = []
            st.session_state.tool_calls = []
            st.session_state.latencies = []
            st.session_state.thread_id = str(uuid.uuid4())
            st.session_state.last_status = fetch_status()
            st.rerun()

        st.caption(f"Gateway: {GATEWAY_URL}")
        st.caption(f"Thread: {st.session_state.thread_id[:12]}...")
        st.caption(f"Session started: {st.session_state.session_start}")


def queue_prompt(prompt: str):
    st.session_state.pending_prompt = prompt


def render_examples():
    examples = [
        (
            "Fault diagnosis",
            "gNB-7 sector 3 is showing handover failures and packet loss. Diagnose the likely cause.",
        ),
        (
            "KPI simulation",
            "Run a normal operation simulation with 20 UEs and explain the KPIs.",
        ),
        (
            "Standards lookup",
            "What causes handover failures in 5G NR according to 3GPP?",
        ),
    ]
    cols = st.columns(3)
    for col, (label, prompt) in zip(cols, examples):
        with col:
            if st.button(label, use_container_width=True):
                queue_prompt(prompt)
                st.rerun()


def handle_prompt(prompt: str):
    st.session_state.messages.append({"role": "user", "content": prompt})
    remember_tool_calls(prompt)

    with st.chat_message("user", avatar="🧑‍💻"):
        st.markdown(prompt)

    with st.chat_message("assistant", avatar="📡"):
        placeholder = st.empty()
        placeholder.markdown("_Thinking through live network evidence..._")
        try:
            answer, raw, latency_ms = call_gateway(prompt)
            st.session_state.latencies.append(latency_ms)
            badges = infer_tool_badges(prompt, raw)
            if badges:
                st.markdown(badges, unsafe_allow_html=True)
            placeholder.markdown(answer)
            st.caption(f"Response time: {latency_ms} ms")
            with st.expander("Raw gateway response", expanded=False):
                st.json(raw)
            st.session_state.messages.append(
                {
                    "role": "assistant",
                    "content": answer,
                    "latency_ms": latency_ms,
                    "tool_badges": badges,
                    "raw": raw,
                }
            )
        except requests.exceptions.ConnectionError:
            error = f"Cannot reach the gateway at `{GATEWAY_URL}`. Start the Agent stack and retry."
            placeholder.error(error)
            st.session_state.messages.append({"role": "assistant", "content": error})
        except requests.exceptions.Timeout:
            error = "Request timed out. A simulation or model call may still be running."
            placeholder.warning(error)
            st.session_state.messages.append({"role": "assistant", "content": error})
        except requests.exceptions.HTTPError as exc:
            error = f"Gateway returned HTTP {exc.response.status_code}: {exc.response.text}"
            placeholder.error(error)
            st.session_state.messages.append({"role": "assistant", "content": error})


init_state()
render_sidebar()

st.markdown("## 📡 Network Operations CoPilot")
st.markdown(
    "<p style='color:#8892a4;margin-top:-12px;'>Ask about KPI simulation, standards-grounded RAG, "
    "or hybrid diagnosis across the full Agent stack.</p>",
    unsafe_allow_html=True,
)

render_examples()
st.divider()

for msg in st.session_state.messages:
    with st.chat_message(msg["role"], avatar="🧑‍💻" if msg["role"] == "user" else "📡"):
        if msg.get("tool_badges"):
            st.markdown(msg["tool_badges"], unsafe_allow_html=True)
        st.markdown(msg["content"])
        if msg.get("latency_ms"):
            st.caption(f"Response time: {msg['latency_ms']} ms")

pending_prompt = st.session_state.pending_prompt
if pending_prompt:
    st.session_state.pending_prompt = None
    handle_prompt(pending_prompt)

typed_prompt = st.chat_input("Describe the network issue or ask a 5G question...")
if typed_prompt:
    handle_prompt(typed_prompt)

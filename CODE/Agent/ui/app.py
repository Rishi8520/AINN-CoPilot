import streamlit as st
import time
from datetime import datetime

# ─── Page config (must be first Streamlit call) ───────────────────────────────
st.set_page_config(
    page_title="AINN-CoPilot",
    page_icon="📡",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
[data-testid="stAppViewContainer"] { background-color: #0f1117; }
[data-testid="stSidebar"] { background-color: #161b27; border-right: 1px solid #1e2538; }

/* Hide branding WITHOUT killing the expand sidebar button */
#MainMenu { visibility: hidden; }
footer { visibility: hidden; }
[data-testid="stToolbarActions"] { visibility: hidden; }
[data-testid="stHeader"] { background: transparent !important; }

/* Style the expand button that lives in stExpandSidebarButton */
[data-testid="stExpandSidebarButton"] button {
    background-color: #161b27 !important;
    border: 1px solid rgba(45,212,191,0.4) !important;
    color: #2dd4bf !important;
    opacity: 1 !important;
    visibility: visible !important;
}

/* Chat message bubbles */
[data-testid="stChatMessage"] { background-color: #161b27; border-radius: 10px; margin-bottom: 8px; }

.tool-badge {
    display: inline-block;
    background: rgba(45,212,191,0.12);
    border: 1px solid rgba(45,212,191,0.3);
    color: #2dd4bf;
    border-radius: 6px;
    padding: 2px 10px;
    font-size: 12px;
    font-family: monospace;
    margin: 2px 4px 2px 0;
}
.tool-badge.sim  { background: rgba(251,146,60,0.12); border-color: rgba(251,146,60,0.3); color: #fb923c; }
.tool-badge.rag  { background: rgba(96,165,250,0.12); border-color: rgba(96,165,250,0.3); color: #60a5fa; }
.tool-badge.done { background: rgba(74,222,128,0.12); border-color: rgba(74,222,128,0.3); color: #4ade80; }

.metric-card {
    background: #1e2538;
    border: 1px solid #2d3a52;
    border-radius: 8px;
    padding: 10px 14px;
    margin-bottom: 8px;
}
.metric-label { color: #8892a4; font-size: 11px; text-transform: uppercase; letter-spacing: 0.06em; }
.metric-value { color: #e2e8f0; font-size: 18px; font-weight: 700; margin-top: 2px; }
.metric-value.green { color: #4ade80; }
.metric-value.orange { color: #fb923c; }
.metric-value.red { color: #f87171; }
</style>
""", unsafe_allow_html=True)

# ─── Session state defaults ───────────────────────────────────────────────────
if "messages" not in st.session_state:
    st.session_state.messages = []          # chat history

if "tool_calls" not in st.session_state:
    st.session_state.tool_calls = []        # list of tool call records per session

if "latencies" not in st.session_state:
    st.session_state.latencies = []         # response latencies (ms)

if "session_start" not in st.session_state:
    st.session_state.session_start = datetime.now().strftime("%H:%M:%S")

if "show_examples" not in st.session_state:
    st.session_state.show_examples = True

# ─── Sidebar ──────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### 📡 AINN-CoPilot")
    st.markdown(
        "<small style='color:#8892a4'>AI-Native Network Intelligence<br>Telecom NOC Assistant</small>",
        unsafe_allow_html=True
    )
    st.divider()

    # Service health indicators (static for now — will be live-polled in Stage 3)
    st.markdown("**Service Health**")
    services = [
        ("OPEA Gateway",    ":8888", "🟡"),
        ("OPEA Agent",      ":9090", "🟡"),
        ("TEI Embedding",   ":6006", "🟡"),
        ("TEI Reranker",    ":8808", "🟡"),
        ("Redis VectorDB",  ":6379", "🟡"),
        ("Simu5G (M1 LAN)", ":8888", "🟡"),
        ("vLLM (M2 LAN)",   ":8080", "🟡"),
    ]
    for name, port, dot in services:
        st.markdown(
            f"<div style='display:flex;justify-content:space-between;align-items:center;"
            f"padding:4px 0;font-size:12px;color:#8892a4'>"
            f"<span>{name} <code style='font-size:10px'>{port}</code></span>"
            f"<span>{dot}</span></div>",
            unsafe_allow_html=True
        )

    st.divider()

    # Session stats
    st.markdown("**Session Stats**")
    total_queries = len([m for m in st.session_state.messages if m["role"] == "user"])
    sim_calls     = len([t for t in st.session_state.tool_calls if t.get("tool") == "simulate"])
    rag_calls     = len([t for t in st.session_state.tool_calls if t.get("tool") == "rag"])
    avg_latency   = (
        f"{int(sum(st.session_state.latencies)/len(st.session_state.latencies))} ms"
        if st.session_state.latencies else "—"
    )

    col1, col2 = st.columns(2)
    with col1:
        st.metric("Queries", total_queries)
        st.metric("Sim calls", sim_calls)
    with col2:
        st.metric("RAG calls", rag_calls)
        st.metric("Avg latency", avg_latency)

    st.divider()

    # Controls
    if st.button("🗑 Clear chat", use_container_width=True):
        st.session_state.messages   = []
        st.session_state.tool_calls = []
        st.session_state.latencies  = []
        st.rerun()

    st.markdown(
        f"<small style='color:#4a5568'>Session started: {st.session_state.session_start}</small>",
        unsafe_allow_html=True
    )

# ─── Main panel ───────────────────────────────────────────────────────────────
st.markdown("## 📡 Network Operations CoPilot")
st.markdown(
    "<p style='color:#8892a4;margin-top:-12px;'>Ask about 5G network faults, KPI analysis, "
    "3GPP spec lookups, or run live Simu5G simulations.</p>",
    unsafe_allow_html=True
)

# ─── Quick-switch example bar (always visible at top) ─────────────────────────
examples = [
    ("🔴 Fault diagnosis",
     "gNB-7 sector 3 is showing BLER above 15%. Diagnose and suggest corrective actions."),
    ("📊 KPI simulation",
     "Simulate a 5G NR scenario with 50 UEs under heavy load and report PRB utilisation."),
    ("📖 Spec lookup",
     "What does 3GPP TS 38.321 say about HARQ retransmission limits?"),
]

if st.session_state.messages:
    # Show as a compact row of buttons when chat is active
    st.markdown(
        "<p style='color:#8892a4;font-size:12px;margin-bottom:6px;'>Try another example:</p>",
        unsafe_allow_html=True
    )
    ex_cols = st.columns(len(examples))
    for col, (label, prompt) in zip(ex_cols, examples):
        with col:
            if st.button(label, use_container_width=True, key=f"ex_{label}"):
                st.session_state.messages.append({"role": "user", "content": prompt})
                st.session_state.messages.append({
                    "role": "assistant",
                    "content": "_Agent not yet connected._"
                })
                st.rerun()

    # New query clears only if user explicitly wants a fresh slate
    if st.button("🗑 Clear & start over", key="clear_main"):
        st.session_state.messages   = []
        st.session_state.tool_calls = []
        st.session_state.latencies  = []
        st.rerun()

    st.divider()

else:
    # First-time landing — show the big prompt cards
    st.markdown("**Try asking:**")
    example_cols = st.columns(3)
    for col, (label, prompt) in zip(example_cols, examples):
        with col:
            if st.button(label, use_container_width=True, help=prompt, key=f"land_{label}"):
                st.session_state.messages.append({"role": "user", "content": prompt})
                st.rerun()

# ─── Chat history display ─────────────────────────────────────────────────────
for msg in st.session_state.messages:
    with st.chat_message(msg["role"], avatar="🧑‍💻" if msg["role"] == "user" else "📡"):
        if msg.get("tool_badges"):
            st.markdown(msg["tool_badges"], unsafe_allow_html=True)
        st.markdown(msg["content"])
        if msg.get("latency_ms"):
            st.caption(f"⏱ {msg['latency_ms']} ms")

# ─── Chat input ───────────────────────────────────────────────────────────────
if prompt := st.chat_input("Describe the network issue or ask a 5G question…"):
    st.session_state.show_examples = False
    st.session_state.messages.append({"role": "user", "content": prompt})

    with st.chat_message("user", avatar="🧑‍💻"):
        st.markdown(prompt)

    with st.chat_message("assistant", avatar="📡"):
        placeholder = st.empty()
        placeholder.markdown(
            "<span style='color:#8892a4;font-style:italic'>⏳ Agent not yet connected — "
            "backend wiring comes in Stage 2.</span>",
            unsafe_allow_html=True
        )
        st.session_state.messages.append({
            "role": "assistant",
            "content": "_Agent not yet connected._"
        })
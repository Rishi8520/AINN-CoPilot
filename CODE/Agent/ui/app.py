import os
import json
import uuid
import requests
import streamlit as st
from dotenv import load_dotenv

# Load from CODE/.env (three levels up from ui/)
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", "..", "..", ".env"))

AGENT_URL = os.environ.get("AGENT_URL", "http://localhost:9090")

# ─────────────────────────────────────────────────────────────────
# Page config — must be first Streamlit call
# ─────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="AINN-CoPilot",
    page_icon="📡",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ─────────────────────────────────────────────────────────────────
# Session state initialisation
# ─────────────────────────────────────────────────────────────────
if "messages" not in st.session_state:
    st.session_state.messages = []

if "thread_id" not in st.session_state:
    st.session_state.thread_id = str(uuid.uuid4())

if "agent_ready" not in st.session_state:
    st.session_state.agent_ready = False

# ─────────────────────────────────────────────────────────────────
# Sidebar
# ─────────────────────────────────────────────────────────────────
with st.sidebar:
    st.title("📡 AINN-CoPilot")
    st.caption("AI-Native 5G Network Management")
    st.divider()

    # Agent health check
    st.subheader("System Status")
    if st.button("🔄 Check Agent Health"):
        try:
            resp = requests.get(f"{AGENT_URL}/health", timeout=5)
            if resp.status_code == 200:
                st.session_state.agent_ready = True
                st.success("Agent: Online ✅")
            else:
                st.session_state.agent_ready = False
                st.error(f"Agent returned {resp.status_code}")
        except requests.exceptions.ConnectionError:
            st.session_state.agent_ready = False
            st.error("Agent: Unreachable ❌")

    if st.session_state.agent_ready:
        st.info(f"Session ID:\n`{st.session_state.thread_id[:16]}...`")
    
    st.divider()

    # New conversation
    if st.button("🗑️ New Conversation"):
        st.session_state.messages = []
        st.session_state.thread_id = str(uuid.uuid4())
        st.rerun()

    st.divider()

    # Example queries
    st.subheader("Example Queries")
    examples = [
        "Cell 7 throughput dropped 40%, what's wrong?",
        "Run a high interference simulation with 30 UEs",
        "What does O-RAN say about handover optimisation?",
        "Compare baseline vs high_load scenario for 50 UEs",
        "Cell 3 has 80% packet loss, diagnose and suggest fix"
    ]
    for example in examples:
        if st.button(example, use_container_width=True):
            st.session_state.pending_input = example
            st.rerun()

# ─────────────────────────────────────────────────────────────────
# Main chat area
# ─────────────────────────────────────────────────────────────────
st.title("AINN-CoPilot — 5G Network Management Assistant")
st.caption(
    "Powered by OPEA · Simu5G · 3GPP/O-RAN Knowledge Base"
)

# Render existing conversation history
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# ─────────────────────────────────────────────────────────────────
# Handle input — either from chat_input or sidebar example button
# ─────────────────────────────────────────────────────────────────
prompt = st.chat_input("Describe your network issue or ask a question...")

# Pick up example button click from session state
if "pending_input" in st.session_state:
    prompt = st.session_state.pop("pending_input")

if prompt:
    # Render user message immediately
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # Call agent and stream response
    with st.chat_message("assistant"):
        placeholder = st.empty()
        full_response = ""
        tool_calls_made = []

        payload = {
            "role": "user",
            "messages": prompt,
            "thread_id": st.session_state.thread_id,
            "stream": True
        }

        try:
            with requests.post(
                f"{AGENT_URL}/v1/chat/completions",
                data=json.dumps(payload),
                stream=True,
                headers={"Content-Type": "application/json"},
                timeout=300    # full ReAct loop with simulation can take ~3 min
            ) as resp:
                resp.raise_for_status()

                for line in resp.iter_lines(decode_unicode=True):
                    if not line:
                        continue

                    # Detect tool call annotations in stream
                    # (agent emits these as intermediate thoughts)
                    if "run_simulation" in line:
                        tool_calls_made.append("🔬 Running Simu5G simulation...")
                        placeholder.markdown(
                            "\n\n".join(tool_calls_made) + "\n\n" + full_response + "▌"
                        )

                    elif "rag_retrieve" in line:
                        tool_calls_made.append("📚 Querying 3GPP/O-RAN knowledge base...")
                        placeholder.markdown(
                            "\n\n".join(tool_calls_made) + "\n\n" + full_response + "▌"
                        )

                    # Accumulate final answer tokens
                    elif line.startswith("data: ") and line != "data: [DONE]":
                        chunk = line[6:]   # strip "data: " prefix
                        full_response += chunk
                        display = (
                            "\n\n".join(tool_calls_made) + "\n\n" + full_response
                            if tool_calls_made else full_response
                        ) + "▌"
                        placeholder.markdown(display)

            # Final render without cursor
            final_display = (
                "\n\n".join(tool_calls_made) + "\n\n---\n\n" + full_response
                if tool_calls_made else full_response
            )
            placeholder.markdown(final_display)
            st.session_state.messages.append({
                "role": "assistant",
                "content": final_display
            })

        except requests.exceptions.ConnectionError:
            error_msg = (
                "❌ **Cannot reach the AINN Agent.**\n\n"
                f"Make sure the agent container is running at `{AGENT_URL}`.\n\n"
                "Run: `docker compose --env-file ../.env up -d ainn-agent`"
            )
            placeholder.error(error_msg)
            st.session_state.messages.append({
                "role": "assistant",
                "content": error_msg
            })

        except requests.exceptions.Timeout:
            error_msg = (
                "⏱️ **Request timed out after 5 minutes.**\n\n"
                "The simulation may still be running. Try asking again "
                "or reduce the `ue_count` in your query."
            )
            placeholder.warning(error_msg)
            st.session_state.messages.append({
                "role": "assistant",
                "content": error_msg
            })
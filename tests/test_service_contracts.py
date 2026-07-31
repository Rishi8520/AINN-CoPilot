import json
import re
from pathlib import Path
from urllib.parse import urlparse

import yaml


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "contracts" / "services.json"
SERVICE_DOC_PATH = ROOT / "DOCs" / "SERVICE_CONTRACTS.md"
ENV_EXAMPLE_PATHS = [ROOT / ".env.example", ROOT / "CODE" / ".env.example"]
CHANGED_YAML_PATHS = [
    ROOT / "CODE" / "Agent" / "docker-compose.yml",
    ROOT / "CODE" / "RAG" / "docker-compose.yml",
    ROOT / "CODE" / "Simulation" / "docker-compose.yml",
    ROOT / "CODE" / "Agent" / "tools" / "ainn_tools.yaml",
    ROOT / "CODE" / "Agent" / "k8s" / "agent_deployment.yaml",
    ROOT / "CODE" / "Agent" / "k8s" / "configmap.yaml",
]
ACTIVE_CONFIG_PATHS = [
    ROOT / ".env.example",
    ROOT / "CODE" / ".env.example",
    ROOT / "CODE" / "Agent" / "tools" / "tools.py",
    ROOT / "CODE" / "Agent" / "agent.py",
    ROOT / "CODE" / "Agent" / "gateway.py",
    ROOT / "CODE" / "Agent" / "ui" / "app.py",
    ROOT / "CODE" / "Agent" / "docker-compose.yml",
    ROOT / "CODE" / "RAG" / "docker-compose.yml",
    ROOT / "CODE" / "Simulation" / "docker-compose.yml",
]


def _services():
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))["services"]


def _env_values(path):
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key] = value
    return values


def test_canonical_ports_are_unique_and_expected():
    services = _services()
    ports = [service["host_port"] for service in services]

    assert len(ports) == len(set(ports))
    assert {service["name"]: service["host_port"] for service in services} == {
        "simulation": 7000,
        "rag": 7001,
        "vllm": 8080,
        "gateway": 8888,
        "agent": 9090,
        "ui": 8501,
    }


def test_env_examples_have_valid_canonical_urls_and_ports():
    expected_ports = {
        "SIMULATION_PORT": "7000",
        "RAG_PORT": "7001",
        "VLLM_PORT": "8080",
        "GATEWAY_PORT": "8888",
        "AGENT_PORT": "9090",
        "UI_PORT": "8501",
    }
    expected_urls = {
        "SIMULATION_BASE_URL": "http://simulation:7000",
        "RAG_BASE_URL": "http://rag:7001",
        "LLM_BASE_URL": "",
        "GATEWAY_BASE_URL": "http://gateway:8888",
        "AGENT_BASE_URL": "http://agent:9090",
    }

    for path in ENV_EXAMPLE_PATHS:
        values = _env_values(path)
        for key, expected in expected_ports.items():
            assert values[key] == expected
        for key, expected in expected_urls.items():
            assert values[key] == expected
            if expected:
                parsed = urlparse(values[key])
                assert parsed.scheme == "http"
                assert parsed.hostname
                assert parsed.port
        assert values["VLLM_BASE_URL"] == ""
        assert values["RAG_SYNTHESIS_BACKEND"] == "deterministic"
        assert values["LLM_REQUIRED"] == "false"


def test_active_config_has_no_tailscale_or_100x_default():
    forbidden_ip = re.compile(r"https?://100\.\d{1,3}\.\d{1,3}\.\d{1,3}")

    for path in ACTIVE_CONFIG_PATHS:
        text = path.read_text(encoding="utf-8")
        assert "Tailscale" not in text
        assert forbidden_ip.search(text) is None


def test_gateway_and_ui_use_configurable_destination_urls():
    gateway = (ROOT / "CODE" / "Agent" / "gateway.py").read_text(encoding="utf-8")
    ui = (ROOT / "CODE" / "Agent" / "ui" / "app.py").read_text(encoding="utf-8")

    assert "AGENT_BASE_URL" in gateway
    assert "GATEWAY_BASE_URL" in ui
    assert "http://localhost:8080" not in ui


def test_service_contract_doc_uses_existing_docs_directory():
    assert SERVICE_DOC_PATH.exists()
    doc_dirs = [path.name for path in ROOT.iterdir() if path.is_dir() and path.name.lower() == "docs"]
    assert doc_dirs == ["DOCs"]
    text = SERVICE_DOC_PATH.read_text(encoding="utf-8")
    assert "Simulation API | 7000" in text
    assert "RAG API | 7001" in text
    assert "Gateway API | 8888" in text


def test_changed_yaml_files_parse_and_use_canonical_ports():
    for path in CHANGED_YAML_PATHS:
        parsed = list(yaml.safe_load_all(path.read_text(encoding="utf-8")))
        assert any(item is not None for item in parsed), path

    agent_compose = yaml.safe_load((ROOT / "CODE" / "Agent" / "docker-compose.yml").read_text(encoding="utf-8"))
    rag_compose = yaml.safe_load((ROOT / "CODE" / "RAG" / "docker-compose.yml").read_text(encoding="utf-8"))
    sim_compose = yaml.safe_load((ROOT / "CODE" / "Simulation" / "docker-compose.yml").read_text(encoding="utf-8"))

    assert "${GATEWAY_PORT:-8888}:8888" in agent_compose["services"]["ainn-gateway"]["ports"]
    assert "${RAG_PORT:-7001}:7001" in rag_compose["services"]["rag-service"]["ports"]
    assert "${SIMULATION_PORT:-7000}:7000" in sim_compose["services"]["telcomind-backend"]["ports"]

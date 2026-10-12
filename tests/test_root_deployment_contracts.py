import json
import os
import shutil
import subprocess
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "docker-compose.yml"
SERVICES = {"simulation", "rag", "agent", "gateway", "ui"}


def _fake_deploy(tmp_path, root_env=False, invalid=False):
    shutil.copyfile(ROOT / "deploy.sh", tmp_path / "deploy.sh")
    (tmp_path / "CODE").mkdir()
    (tmp_path / "CODE" / ".env").write_text("LLM_API_KEY=fake-test-only\n")
    if root_env:
        (tmp_path / ".env").write_text("LLM_API_KEY=fake-root-only\n")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text('''#!/bin/sh
case "$*" in
  *"config --quiet"*)
    if [ "$TEST_INVALID_CONFIG" = "1" ]; then echo "required variable LLM_API_KEY is missing" >&2; exit 1; fi
    exit 0 ;;
  *"compose version"*) echo "test-compose"; exit 0 ;;
  *"version"*) echo "test-docker"; exit 0 ;;
esac
printf '%s\\n' "$@"
''')
    docker.chmod(0o755)
    environment = dict(os.environ, PATH=str(bin_dir) + os.pathsep + os.environ["PATH"], TEST_INVALID_CONFIG="1" if invalid else "0")
    return subprocess.run(["bash", str(tmp_path / "deploy.sh"), "--opea", "--status"],
                          env=environment, capture_output=True, text=True)


def test_deploy_uses_code_env_without_root_env(tmp_path):
    result = _fake_deploy(tmp_path)
    assert result.returncode == 0
    assert str(tmp_path / "CODE" / ".env") in result.stdout
    assert "--env-file" in result.stdout
    assert "fake-test-only" not in result.stdout


def test_deploy_prefers_root_env_when_both_exist(tmp_path):
    result = _fake_deploy(tmp_path, root_env=True)
    assert result.returncode == 0
    assert str(tmp_path / ".env") in result.stdout
    assert str(tmp_path / "CODE" / ".env") not in result.stdout


def test_invalid_config_stops_before_port_json_parsing(tmp_path):
    result = _fake_deploy(tmp_path, invalid=True)
    assert result.returncode != 0
    assert "Compose configuration is invalid" in result.stdout
    assert "JSONDecodeError" not in result.stdout + result.stderr
    assert "fake-test-only" not in result.stdout + result.stderr


def _compose():
    return yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))


def test_root_compose_parses_and_has_required_services():
    parsed = _compose()
    assert "version" not in parsed
    assert SERVICES.issubset(parsed["services"])


def test_canonical_internal_ports_are_unique_and_match_contract():
    parsed = _compose()
    contracts = {
        service["name"]: service
        for service in json.loads((ROOT / "contracts" / "services.json").read_text(encoding="utf-8"))["services"]
    }
    expected = {
        "simulation": 7000,
        "rag": 7001,
        "agent": 9090,
        "gateway": 8888,
        "ui": 8501,
    }
    ports = []
    for service, container_port in expected.items():
        port_entries = parsed["services"][service]["ports"]
        assert any(str(entry).endswith(f":{container_port}") for entry in port_entries)
        assert contracts[service]["container_port"] == container_port
        ports.append(container_port)
    assert len(ports) == len(set(ports))


def test_vllm_is_optional_and_not_default_startup():
    parsed = _compose()
    vllm = parsed["services"]["vllm"]
    assert vllm["profiles"] == ["gpu-llm"]
    assert "latest" not in vllm["image"]
    for service_name in SERVICES:
        assert "profiles" not in parsed["services"][service_name]


def test_no_default_gpu_tailscale_host_network_or_docker_socket():
    parsed = _compose()
    text = COMPOSE.read_text(encoding="utf-8")
    assert "Tailscale" not in text
    assert "100." not in text
    assert "host.docker.internal" not in text
    for name, service in parsed["services"].items():
        if name in SERVICES:
            assert service.get("network_mode") != "host"
            assert service.get("privileged") is not True
            assert "deploy" not in service or "devices" not in str(service.get("deploy"))
            for volume in service.get("volumes", []):
                assert "/var/run/docker.sock" not in str(volume)


def test_service_urls_use_compose_dns_and_safe_defaults():
    parsed = _compose()
    agent_env = parsed["services"]["agent"]["environment"]
    gateway_env = parsed["services"]["gateway"]["environment"]
    rag_env = parsed["services"]["rag"]["environment"]
    sim_env = parsed["services"]["simulation"]["environment"]

    assert agent_env["SIMULATION_BASE_URL"] == "http://simulation:7000"
    assert agent_env["RAG_BASE_URL"] == "http://rag:7001"
    assert gateway_env["AGENT_BASE_URL"] == "http://agent:9090"
    assert sim_env["SIMULATION_DEFAULT_MODE"] == "${SIMULATION_DEFAULT_MODE:-replay}"
    assert sim_env["SIMULATION_LIVE_ENABLED"] == "${SIMULATION_LIVE_ENABLED:-false}"
    assert rag_env["RAG_PROFILE"] == "${RAG_PROFILE:-quickstart}"
    assert rag_env["RAG_AUTO_INGEST"] == "${RAG_AUTO_INGEST:-false}"
    assert rag_env["RAG_SYNTHESIS_BACKEND"] == "${RAG_SYNTHESIS_BACKEND:-deterministic}"
    assert rag_env["LLM_REQUIRED"] == "${LLM_REQUIRED:-false}"


def test_healthchecks_and_depends_on_are_valid():
    parsed = _compose()
    service_names = set(parsed["services"])
    for service_name in SERVICES:
        service = parsed["services"][service_name]
        assert "healthcheck" in service
        for dependency in service.get("depends_on", {}):
            assert dependency in service_names
            assert service["depends_on"][dependency]["condition"] == "service_healthy"


def test_host_ports_are_configurable_and_no_absolute_bind_mounts():
    parsed = _compose()
    expected_vars = {
        "simulation": "HOST_SIMULATION_PORT",
        "rag": "HOST_RAG_PORT",
        "agent": "HOST_AGENT_PORT",
        "gateway": "HOST_GATEWAY_PORT",
        "ui": "HOST_UI_PORT",
    }
    for service, var_name in expected_vars.items():
        assert any(str(entry).startswith("${" + var_name + ":-") for entry in parsed["services"][service]["ports"])
        for volume in parsed["services"][service].get("volumes", []):
            source = str(volume).split(":", 1)[0]
            assert not Path(source).is_absolute()


def test_deploy_scripts_and_smoke_test_exist_with_lf_shell_script():
    deploy_sh = ROOT / "deploy.sh"
    assert deploy_sh.exists()
    assert (ROOT / "deploy.ps1").exists()
    assert (ROOT / "scripts" / "smoke_test.py").exists()
    data = deploy_sh.read_bytes()
    assert b"\r\n" not in data
    assert data.startswith(b"#!/usr/bin/env bash\n")


def test_dockerignore_keeps_quickstart_inputs_and_excludes_runtime_caches():
    text = (ROOT / ".dockerignore").read_text(encoding="utf-8")
    assert "CODE/RAG/quickstart" not in text
    assert "CODE/Simulation/fixtures" not in text
    assert "CODE/RAG/storage" in text
    assert "**/model_cache" in text
    assert "CODE/Simulation/app/scenarios/results/*" in text

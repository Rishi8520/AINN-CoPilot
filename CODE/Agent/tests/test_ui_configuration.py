import ast
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib


UI_APP = Path(__file__).resolve().parents[1] / "ui" / "app.py"


def test_ui_gateway_url_configuration_precedence_and_no_tailscale():
    text = UI_APP.read_text(encoding="utf-8", errors="replace")

    assert "GATEWAY_BASE_URL" in text
    assert "GATEWAY_URL" in text
    assert "http://localhost:8888" in text
    assert "Tailscale" not in text
    assert "100." not in text


def test_ui_health_and_static_endpoint_configuration_is_externalized():
    text = UI_APP.read_text(encoding="utf-8", errors="replace")

    assert "/v1/agent/status" in text
    assert "/v1/jobs" in text
    assert "UI_REQUEST_TIMEOUT_SECONDS" in text
    assert "http://localhost:8080" not in text


def test_ui_python_source_parses_without_importing_streamlit():
    ast.parse(UI_APP.read_text(encoding="utf-8", errors="replace"), filename=str(UI_APP))


def test_native_light_and_dark_themes_are_packaged_in_both_images():
    ui = UI_APP.parent
    config = tomllib.loads((ui / ".streamlit" / "config.toml").read_text())
    assert config["theme"]["light"]["backgroundColor"] == "#ffffff"
    assert config["theme"]["dark"]["backgroundColor"] == "#111516"
    for dockerfile in ("Dockerfile", "Dockerfile.quickstart"):
        assert "COPY" in (ui / dockerfile).read_text()
        assert ".streamlit" in (ui / dockerfile).read_text()
    assert "streamlit==1.65.0" in (ui / "requirements.quickstart.txt").read_text()


def test_frontend_keeps_job_workflow_and_does_not_override_native_colors():
    text = UI_APP.read_text()
    assert '@st.fragment(run_every="1s")' in text
    assert 'st.query_params["job"]' in text
    assert '"DELETE", f"/v1/jobs/{job_id}"' in text
    assert 'st.set_option("theme.' not in text
    assert 'candidate=simulation.get("comparison"' in text
    assert "escape(scenario)" in text

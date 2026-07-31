import ast
from pathlib import Path


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
    assert "/v1/chat" in text
    assert "UI_REQUEST_TIMEOUT_SECONDS" in text
    assert "http://localhost:8080" not in text


def test_ui_python_source_parses_without_importing_streamlit():
    ast.parse(UI_APP.read_text(encoding="utf-8", errors="replace"), filename=str(UI_APP))

import importlib.util
from pathlib import Path

import pytest
import yaml


spec = importlib.util.spec_from_file_location(
    "opea_model_compat", Path(__file__).parents[1] / "opea" / "model_compat.py")
compat = importlib.util.module_from_spec(spec)
spec.loader.exec_module(compat)


def test_compose_replaces_upstream_agent_entrypoint():
    class ComposeLoader(yaml.SafeLoader):
        pass

    ComposeLoader.add_constructor("!override", lambda loader, node: loader.construct_sequence(node))
    root = Path(__file__).resolve().parents[3]
    profile = yaml.load((root / "docker-compose.opea.yml").read_text(), Loader=ComposeLoader)
    service = profile["services"]["opea-reasoner"]
    assert service["entrypoint"] == ["python"]
    assert service["command"] == ["/home/user/telcomind/bootstrap.py"]


class Model:
    def model_copy(self, update):
        return update


@pytest.mark.parametrize("name", ["gpt-5", "gpt-5-mini", "gpt-5-nano", "gpt-5-mini-2025-08-07"])
def test_original_gpt5_settings(name):
    result = compat.configure_model(Model(), name, {})
    assert result == {"temperature": None, "top_p": None, "max_tokens": 4096,
                      "reasoning_effort": "minimal"}


@pytest.mark.parametrize("name", ["gpt-4.1-mini", "gpt-5.1", "gpt-5.2", "gpt-5-mini-other"])
def test_other_models_are_unchanged(name):
    model = Model()
    assert compat.configure_model(model, name, {}) is model


@pytest.mark.parametrize("env", [{"OPEA_REASONING_EFFORT": "none"},
                                     {"OPEA_MAX_COMPLETION_TOKENS": "512"},
                                     {"OPEA_MAX_COMPLETION_TOKENS": "32769"},
                                     {"OPEA_MAX_COMPLETION_TOKENS": "invalid"}])
def test_invalid_gpt5_configuration_fails(env):
    with pytest.raises(ValueError):
        compat.configure_model(Model(), "gpt-5-mini", env)

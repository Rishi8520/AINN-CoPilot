"""Run the actual OPEA agent with model-specific request compatibility."""

import runpy

from model_compat import configure_model
from comps.agent.src.integrations import utils
from comps.agent.src.integrations.strategy import base_agent


original_setup = utils.setup_chat_model


def setup_chat_model(args):
    return configure_model(original_setup(args), args.model)


utils.setup_chat_model = setup_chat_model
base_agent.setup_chat_model = setup_chat_model

if __name__ == "__main__":
    runpy.run_path("/home/user/comps/agent/src/agent.py", run_name="__main__")

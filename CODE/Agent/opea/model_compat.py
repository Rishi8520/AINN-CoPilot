"""Compatibility settings for the original GPT-5 family in the pinned OPEA image."""

import os
import re


def configure_model(llm, model, environ=None):
    if not re.fullmatch(r"gpt-5(?:-mini|-nano)?(?:-\d{4}-\d{2}-\d{2})?", model):
        return llm
    environ = os.environ if environ is None else environ
    effort = environ.get("OPEA_REASONING_EFFORT", "minimal")
    if effort not in {"minimal", "low", "medium", "high"}:
        raise ValueError("OPEA_REASONING_EFFORT must be minimal, low, medium, or high.")
    budget = int(environ.get("OPEA_MAX_COMPLETION_TOKENS", "4096"))
    if not 1024 <= budget <= 32768:
        raise ValueError("OPEA_MAX_COMPLETION_TOKENS must be between 1024 and 32768.")
    # LangChain omits None sampling fields and maps max_tokens to
    # max_completion_tokens. This budget includes reasoning and visible output.
    return llm.model_copy(update={"temperature": None, "top_p": None,
                                  "max_tokens": budget, "reasoning_effort": effort})

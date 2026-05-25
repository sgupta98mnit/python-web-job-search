"""Build the right LLMProvider from config. One function, no branching elsewhere."""

from __future__ import annotations

import os

import config

from .anthropic import AnthropicProvider
from .base import LLMProvider
from .openai_compat import OpenAICompatibleProvider


def build_provider(name: str | None = None) -> LLMProvider:
    """Construct the provider named in config (or override with `name`)."""
    name = name or config.PROVIDER
    if name not in config.PRESETS:
        raise ValueError(
            f"Unknown provider {name!r}. Known: {sorted(config.PRESETS)}"
        )
    preset = config.PRESETS[name]
    kind = preset["kind"]
    key_env = preset.get("key_env")
    api_key = os.getenv(key_env) if key_env else None
    model = preset["model"]

    if kind == "openai_compat":
        return OpenAICompatibleProvider(
            provider_name=name,
            base_url=preset["base_url"],
            api_key=api_key,
            model=model,
            rpm_limit=preset.get("rpm_limit"),
        )
    if kind == "anthropic":
        return AnthropicProvider(api_key=api_key, model=model)
    raise ValueError(f"Unknown provider kind: {kind!r}")

#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

import yaml


@dataclass(slots=True)
class RootConfig:
    system_prompt: str
    model_name: str
    group_name: str
    agent_name: str
    context_window_limit: int


@dataclass(slots=True)
class Settings:
    root: RootConfig
    models: List[str]
    mcp_executor: str


@dataclass(slots=True)
class Secrets:
    model_bindings: Dict[str, Dict[str, str | int | float]]


def resolve_model_binding(secrets: Secrets, model_name: str) -> tuple[str, str, int, float]:
    binding = secrets.model_bindings.get(model_name)
    if binding is None:
        raise KeyError(f"No model binding found for model '{model_name}' in secrets.yaml")
    api_url = str(binding.get("api_url", ""))
    api_key = str(binding.get("api_key", ""))
    parameter_count = int(binding.get("parameter_count", 0))
    price_per_million_tokens = float(binding.get("price_per_million_tokens", 0.0))
    return api_url, api_key, parameter_count, price_per_million_tokens


def load_settings(settings_path: Path, secrets_path: Path) -> tuple[Settings, Secrets]:
    settings_data = yaml.safe_load(settings_path.read_text(encoding="utf-8"))
    secrets_data = yaml.safe_load(secrets_path.read_text(encoding="utf-8"))

    root_data = settings_data.get("root", {})
    models = list(settings_data.get("models", []))
    default_model = str(root_data.get("model_name", models[0] if models else "gpt-5.3-codex"))

    root = RootConfig(
        system_prompt=str(root_data.get("system_prompt", "")),
        model_name=default_model,
        group_name=str(root_data.get("group_name", "sudo")),
        agent_name=str(root_data.get("agent_name", "root")),
        context_window_limit=int(root_data.get("context_window_limit", 8192)),
    )

    settings = Settings(
        root=root,
        models=models if models else [root.model_name],
        mcp_executor=str(settings_data.get("mcp", {}).get("executor", "dry-run")),
    )
    secrets = Secrets(model_bindings=dict(secrets_data.get("model_bindings", {})))
    return settings, secrets

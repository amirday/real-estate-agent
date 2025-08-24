from __future__ import annotations

import json
import os

import yaml
from dotenv import load_dotenv

from .models import AppConfig

"""Config loader for the CLI."""

def _merge(strict: dict, parsed: dict) -> dict:
    # strict wins; deep merge for nested dicts
    result = dict(parsed or {})
    for k, v in (strict or {}).items():
        if isinstance(v, dict) and isinstance(result.get(k), dict):
            result[k] = _merge(v, result.get(k) or {})
        else:
            result[k] = v
    return result


def load_config(path: str, logger=None) -> AppConfig:
    # Deferred import to avoid circular dependency (openai_parser imports LLMConfig)
    from .openai_parser import parse_free_text_to_config
    load_dotenv(override=False)

    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    strict = {k: v for k, v in raw.items() if k in {"filters", "arv_config", "profit_config", "deal_screen"}}
    free_text = raw.get("prompt")

    parsed = {}
    if free_text:
        parsed = parse_free_text_to_config(free_text)
        if logger:
            logger.info("Parsed free-text prompt into structured config via OpenAI")
            logger.debug(json.dumps(parsed, indent=2))

    merged = _merge(strict, parsed)

    # Ensure required sections exist
    merged.setdefault("filters", {})
    cfg = AppConfig(**merged, prompt=free_text)
    return cfg

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
    # Deferred import to avoid circular dependency (openai_parser imports AppConfig)
    from .openai_parser import parse_free_text_to_config
    from .cache import clear_all_cache, get_cache_stats
    
    load_dotenv(override=False)

    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    strict = {k: v for k, v in raw.items() if k in {"filters", "arv_config", "profit_config", "deal_screen", "cache_config"}}
    free_text = raw.get("prompt")

    # Create initial config to get cache settings
    initial_cfg = AppConfig(**{**strict, "filters": strict.get("filters", {})})
    
    # Handle cache clearing before run if configured
    if initial_cfg.cache_config.clear_before_run:
        if logger:
            logger.info("Clearing cache before run as configured")
        clear_all_cache()
        if logger:
            logger.debug("Cache cleared successfully")

    parsed = {}
    if free_text:
        # Use cache configuration for LLM calls
        parsed = parse_free_text_to_config(
            free_text, 
            cache_enabled=initial_cfg.cache_config.llm_cache_enabled,
            cache_ttl_hours=initial_cfg.cache_config.cache_ttl_hours
        )
        if logger:
            if initial_cfg.cache_config.llm_cache_enabled:
                logger.info("Parsed free-text prompt into structured config via OpenAI (cache enabled)")
            else:
                logger.info("Parsed free-text prompt into structured config via OpenAI (cache disabled)")
            logger.debug(json.dumps(parsed, indent=2))

    merged = _merge(strict, parsed)

    # Ensure required sections exist
    merged.setdefault("filters", {})
    cfg = AppConfig(**merged, prompt=free_text)
    
    # Log cache statistics
    if logger:
        cache_stats = get_cache_stats()
        logger.debug(f"Cache statistics: {cache_stats}")
    
    return cfg

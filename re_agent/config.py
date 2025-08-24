from __future__ import annotations

import json
import os
from typing import List, Optional

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field

from .openai_parser import parse_free_text_to_config


class Adjustments(BaseModel):
    bed_step_pct: float = 0.04
    bath_step_pct: float = 0.05
    lot_size_cap_ratio: float = 2.0
    age_condition_proxy: bool = False


class Filters(BaseModel):
    geos: List[str] = Field(default_factory=list)
    status: List[str] = Field(default_factory=lambda: ["FOR_SALE"])
    home_types: List[str] = Field(default_factory=lambda: ["SINGLE_FAMILY"])
    price_min: Optional[float] = None
    price_max: Optional[float] = None
    beds_min: Optional[int] = None
    baths_min: Optional[float] = None
    min_sqft: Optional[int] = None
    min_lot_sqft: Optional[int] = None
    year_built_min: Optional[int] = None
    max_dom: Optional[int] = None
    include_pending: bool = False
    hoa_max: Optional[float] = None
    price_reduction_only: bool = False
    page_cap: int = 1


class ArvConfig(BaseModel):
    comp_radius_mi: float = 0.75
    comp_window_months: int = 6
    extend_window_if_insufficient: int = 12
    min_comps: int = 3
    ppsf_method: str = "median"  # or "mean"
    adjustments: Adjustments = Field(default_factory=Adjustments)
    confidence_method: str = "n_iqr"


class ProfitConfig(BaseModel):
    rehab_budget: Optional[float] = None
    closing_costs_pct: float = 0.03
    selling_costs_pct: float = 0.06
    misc_buffer_pct: float = 0.02
    moe_pct_conservative: float = 0.10
    moe_pct_optimistic: float = 0.03


class DealScreen(BaseModel):
    max_list_to_arv_pct: Optional[float] = None


class AppConfig(BaseModel):
    filters: Filters
    arv_config: ArvConfig = Field(default_factory=ArvConfig)
    profit_config: ProfitConfig = Field(default_factory=ProfitConfig)
    deal_screen: Optional[DealScreen] = Field(default_factory=DealScreen)
    prompt: Optional[str] = None


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
    load_dotenv(override=False)

    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    strict = {k: v for k, v in raw.items() if k in {"filters", "arv_config", "profit_config", "deal_screen"}}
    free_text = raw.get("prompt")

    parsed = {}
    if free_text:
        try:
            parsed = parse_free_text_to_config(free_text)
            if logger:
                logger.info("Parsed free-text prompt into structured config via OpenAI")
                logger.debug(json.dumps(parsed, indent=2))
        except Exception as e:
            if logger:
                logger.warning(f"Failed to parse free-text prompt; proceeding with strict only: {e}")

    merged = _merge(strict, parsed)

    # Ensure required sections exist
    merged.setdefault("filters", {})
    cfg = AppConfig(**merged, prompt=free_text)
    return cfg


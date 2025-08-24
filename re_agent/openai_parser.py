import os
from typing import Any, Dict
from .exc import DataValidationError


def parse_free_text_to_config(prompt: str) -> Dict[str, Any]:
    """
    Parses the free-text 'prompt' into the strict schema using OpenAI structured output.
    If OpenAI isn't configured, returns an empty dict.
    """
    api_key = os.getenv("OPENAI_API_KEY")
    model = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
    if not api_key:
        # No LLM configured; skip structured parsing step gracefully.
        return {}

    # Deferred import so code runs without the package if not installed.
    try:
        from openai import OpenAI
    except Exception:
        return {}

    client = OpenAI(api_key=api_key)

    system = (
        "You are a helpful real estate config parser. "
        "Return ONLY valid JSON matching this schema keys: filters, arv_config, profit_config, deal_screen. "
        "Do not include extra keys. Use null for unknowns."
    )

    user = f"""
    Free-text user intent:
    ---
    {prompt}
    ---
    Map to these keys (omit if no data):
    filters.geos[], filters.status[], filters.home_types[], filters.price_min, filters.price_max,
    filters.beds_min, filters.baths_min, filters.min_sqft, filters.min_lot_sqft,
    filters.year_built_min, filters.max_dom, filters.include_pending, filters.hoa_max,
    filters.price_reduction_only, filters.page_cap,
    arv_config.comp_radius_mi, arv_config.comp_window_months, arv_config.extend_window_if_insufficient,
    arv_config.min_comps, arv_config.ppsf_method, arv_config.adjustments.bed_step_pct,
    arv_config.adjustments.bath_step_pct, arv_config.adjustments.lot_size_cap_ratio,
    arv_config.adjustments.age_condition_proxy, arv_config.confidence_method,
    profit_config.rehab_budget, profit_config.closing_costs_pct, profit_config.selling_costs_pct,
    profit_config.misc_buffer_pct, profit_config.moe_pct_conservative, profit_config.moe_pct_optimistic,
    deal_screen.max_list_to_arv_pct.
    """

    try:
        resp = client.chat.completions.create(
            model=model,
            temperature=0,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            response_format={"type": "json_object"},
        )
        content = resp.choices[0].message.content
        import json

        data = json.loads(content)
        # best-effort prune unknown keys
        allowed = {"filters", "arv_config", "profit_config", "deal_screen"}
        return {k: v for k, v in data.items() if k in allowed}
    except Exception as e:
        # When LLM is configured, any failure to produce valid JSON is fatal
        raise DataValidationError(f"LLM parsing failed: {e}; raw={locals().get('content', '')}")

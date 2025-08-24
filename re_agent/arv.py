from __future__ import annotations

from typing import Dict, List, Tuple

from .config import AppConfig
from .utils import median, iqr, safe_float, clamp01
from .exc import MissingFieldError, NoCompsError, DataValidationError
from .models import PropertyDetails, CompRecord, ArvComputation, ProfitScenarios


def _extract_subject_fields(subject: Dict) -> Dict:
    return {
        "price": safe_float(subject.get("price") or subject.get("listPrice")),
        "beds": safe_float(subject.get("bedrooms") or subject.get("beds")),
        "baths": safe_float(subject.get("bathrooms") or subject.get("baths")),
        "sqft": safe_float(subject.get("livingArea") or subject.get("sqft")),
        "lot_sqft": safe_float(subject.get("lotAreaValue") or subject.get("lotSize") or subject.get("lotArea")),
        "home_type": subject.get("homeType") or subject.get("home_type"),
        "year_built": safe_float(subject.get("yearBuilt")),
    }


def _filter_and_ppsf(comps: List[Dict], subject: Dict, cfg: AppConfig) -> List[float]:
    s = _extract_subject_fields(subject)
    s_sqft = s.get("sqft") or 0
    s_home_type = s.get("home_type")
    s_lot = s.get("lot_sqft") or 0
    lot_cap_ratio = cfg.arv_config.adjustments.lot_size_cap_ratio if cfg and cfg.arv_config else 2.0

    ppsf_vals: List[float] = []
    for c in comps:
        price = safe_float(c.get("price") or c.get("soldPrice") or c.get("sale_price"))
        sqft = safe_float(c.get("livingArea") or c.get("sqft") or c.get("living_area"))
        lot_sqft = safe_float(c.get("lotAreaValue") or c.get("lotSize") or c.get("lot_area"))
        if not price or not sqft or sqft <= 0:
            continue
        home_type = c.get("homeType") or c.get("home_type")
        if s_home_type and home_type and str(home_type).lower() != str(s_home_type).lower():
            continue
        # +/- 20% sqft filter
        if s_sqft:
            if not (0.8 * s_sqft <= sqft <= 1.2 * s_sqft):
                continue
        # Ignore comps with extreme lot size compared to subject when computing ppsf
        if s_lot and lot_sqft and lot_sqft > lot_cap_ratio * s_lot:
            continue
        ppsf_vals.append(price / sqft)
    return ppsf_vals


def _confidence_from_ppsf(ppsf_vals: List[float], min_comps: int) -> float:
    if not ppsf_vals:
        return 0.0
    med = median(ppsf_vals)
    if not med or med <= 0:
        return 0.0
    disp = (iqr(ppsf_vals) or 0.0) / med
    n = len(ppsf_vals)
    n_score = clamp01(n / float(max(min_comps * 2, 1)))
    spread_score = 1.0 / (1.0 + disp)
    return clamp01(0.5 * n_score + 0.5 * spread_score)


def estimate_arv_and_profit(subject: Dict, comps_payload: Dict, cfg: AppConfig) -> Tuple[Dict, None]:
    row: Dict = {}
    s = _extract_subject_fields(subject)
    s_sqft = s.get("sqft")
    list_price = s.get("price")

    if not s_sqft:
        raise MissingFieldError("Subject is missing sqft; cannot compute ARV")
    if list_price is None:
        raise MissingFieldError("Subject is missing list price; cannot compute deal ratio")

    comps = comps_payload.get("comps") or comps_payload.get("properties") or []
    ppsf_vals = _filter_and_ppsf(comps, subject, cfg)

    if not ppsf_vals:
        raise NoCompsError("No valid comps after filtering and fallback")

    med_ppsf = median(ppsf_vals)
    arv_base = (med_ppsf or 0.0) * s_sqft

    # Adjustments by beds/baths deltas
    adj = cfg.arv_config.adjustments
    bed_delta = 0.0
    bath_delta = 0.0
    try:
        s_beds = s.get("beds") or 0
        s_baths = s.get("baths") or 0
        # Use mean of comps' beds/baths for relative delta
        comp_beds = [safe_float(c.get("bedrooms") or c.get("beds"), 0.0) for c in comps]
        comp_baths = [safe_float(c.get("bathrooms") or c.get("baths"), 0.0) for c in comps]
        mean_beds = sum(comp_beds) / max(1, len(comp_beds))
        mean_baths = sum(comp_baths) / max(1, len(comp_baths))
        bed_delta = (s_beds - mean_beds) * adj.bed_step_pct
        bath_delta = (s_baths - mean_baths) * adj.bath_step_pct
    except Exception:
        pass

    adj_multiplier = 1.0 + bed_delta + bath_delta
    arv_estimate = max(0.0, arv_base * adj_multiplier)

    conf = _confidence_from_ppsf(ppsf_vals, cfg.arv_config.min_comps)

    list_to_arv_pct = float(list_price) / float(arv_estimate)

    # Profit scenarios
    profit_conservative = profit_median = profit_optimistic = ""
    if cfg.profit_config and cfg.profit_config.rehab_budget is not None and list_price is not None:
        arv_conservative = arv_estimate * (1.0 - cfg.profit_config.moe_pct_conservative)
        arv_median = arv_estimate
        arv_optimistic = arv_estimate * (1.0 - cfg.profit_config.moe_pct_optimistic)

        closing_costs = cfg.profit_config.closing_costs_pct * list_price
        selling_costs = cfg.profit_config.selling_costs_pct * arv_median
        misc_buffer = cfg.profit_config.misc_buffer_pct * arv_median
        total_costs = list_price + cfg.profit_config.rehab_budget + closing_costs + selling_costs + misc_buffer

        profit_conservative = arv_conservative - total_costs
        profit_median = arv_median - total_costs
        profit_optimistic = arv_optimistic - total_costs

    row.update({
        "arv_estimate": round(arv_estimate, 2) if arv_estimate else "",
        "arv_ppsf": round(med_ppsf, 2) if med_ppsf else "",
        "comp_count": len(ppsf_vals),
        "arv_confidence": round(conf, 3),
        "list_to_arv_pct": round(list_to_arv_pct, 4) if isinstance(list_to_arv_pct, float) else list_to_arv_pct,
        "profit_conservative": round(profit_conservative, 2) if isinstance(profit_conservative, float) else "",
        "profit_median": round(profit_median, 2) if isinstance(profit_median, float) else "",
        "profit_optimistic": round(profit_optimistic, 2) if isinstance(profit_optimistic, float) else "",
    })

    return row, None

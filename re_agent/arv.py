from __future__ import annotations

from typing import Dict, List, Tuple

from .utils import median, iqr, safe_float, clamp01
from .exc import MissingFieldError, NoCompsError, DataValidationError
from .models import PropertyDetails, CompRecord, ArvComputation, ProfitScenarios, AppConfig


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
    """Filter comps per agents.md specification and compute price per sqft."""
    s = _extract_subject_fields(subject)
    s_sqft = s.get("sqft") or 0
    s_home_type = s.get("home_type")
    s_lot = s.get("lot_sqft") or 0
    lot_cap_ratio = cfg.arv_config.adjustments.lot_size_cap_ratio

    ppsf_vals: List[float] = []
    for c in comps:
        price = safe_float(c.get("price") or c.get("soldPrice") or c.get("sale_price"))
        sqft = safe_float(c.get("livingArea") or c.get("sqft") or c.get("living_area"))
        lot_sqft = safe_float(c.get("lotAreaValue") or c.get("lotSize") or c.get("lot_area"))
        home_type = c.get("homeType") or c.get("home_type")
        
        # Skip if missing required data
        if not price or not sqft or sqft <= 0:
            continue
            
        # Filter: same home_type (agents.md requirement)
        if s_home_type and home_type and str(home_type).lower() != str(s_home_type).lower():
            continue
            
        # Filter: sqft within ±20% (agents.md constant)  
        if s_sqft and not (0.8 * s_sqft <= sqft <= 1.2 * s_sqft):
            continue
            
        # Ignore lot beyond lot_size_cap_ratio × subject_lot when computing ppsf
        if s_lot and lot_sqft and lot_sqft > lot_cap_ratio * s_lot:
            continue
            
        ppsf_vals.append(price / sqft)
    return ppsf_vals


def _confidence_from_ppsf(ppsf_vals: List[float], min_comps: int) -> float:
    """
    Confidence (n_iqr method from agents.md):
    • n = comp_count
    • dispersion = IQR(ppsf) / median(ppsf)  
    • Map to [0,1] increasing with n and decreasing with dispersion
    """
    if not ppsf_vals:
        return 0.0
    med = median(ppsf_vals)
    if not med or med <= 0:
        return 0.0
    
    # Dispersion = IQR / median
    disp = (iqr(ppsf_vals) or 0.0) / med
    n = len(ppsf_vals)
    
    # Map n to [0,1] - reaches 1.0 when n >= 2*min_comps
    n_score = clamp01(n / float(max(min_comps * 2, 1)))
    
    # Map dispersion to [0,1] - lower dispersion = higher confidence
    spread_score = 1.0 / (1.0 + disp)
    
    # Equal weighting of count and dispersion
    return clamp01(0.5 * n_score + 0.5 * spread_score)


def estimate_arv_and_profit(subject: Dict, comps_payload: Dict, cfg: AppConfig) -> Tuple[Dict, None]:
    """
    ARV Method (v0) per agents.md specification:
    • Filter comps: same home_type; sqft within ±20% (constant)
    • Baseline ARV = median(ppsf of comps) × subject_sqft  
    • Adjustments:
      • Beds: ARV *= (1 ± bed_step_pct × bed_delta)
      • Baths: ARV *= (1 ± bath_step_pct × bath_delta)
      • Ignore lot beyond lot_size_cap_ratio × subject_lot when computing ppsf
    """
    row: Dict = {}
    s = _extract_subject_fields(subject)
    s_sqft = s.get("sqft")
    list_price = s.get("price")

    # Fail-fast validation per agents.md
    if not s_sqft:
        raise MissingFieldError("Subject is missing sqft; cannot compute ARV")
    if list_price is None:
        raise MissingFieldError("Subject is missing list price; cannot compute deal ratio")

    # Extract and filter comps
    comps = comps_payload.get("comps") or comps_payload.get("properties") or []
    ppsf_vals = _filter_and_ppsf(comps, subject, cfg)

    # Fail if no comps after filtering (agents.md: fail if zero comps after fallback)
    if not ppsf_vals:
        raise NoCompsError("No valid comps after filtering and fallback")

    # Baseline ARV = median(ppsf of comps) × subject_sqft
    med_ppsf = median(ppsf_vals)
    arv_base = (med_ppsf or 0.0) * s_sqft

    # Adjustments per agents.md specification
    adj = cfg.arv_config.adjustments
    bed_delta = 0.0
    bath_delta = 0.0
    
    s_beds = s.get("beds") or 0
    s_baths = s.get("baths") or 0
    
    # Calculate mean beds/baths from filtered comps for relative comparison
    valid_comps = [c for c in comps if c.get("price") and c.get("sqft")]  # Use same comps that passed filtering
    comp_beds = [safe_float(c.get("bedrooms") or c.get("beds"), 0.0) for c in valid_comps]
    comp_baths = [safe_float(c.get("bathrooms") or c.get("baths"), 0.0) for c in valid_comps]
    
    if comp_beds and comp_baths:
        mean_beds = sum(comp_beds) / len(comp_beds)
        mean_baths = sum(comp_baths) / len(comp_baths)
        bed_delta = (s_beds - mean_beds) * adj.bed_step_pct
        bath_delta = (s_baths - mean_baths) * adj.bath_step_pct

    # Apply adjustments: ARV *= (1 ± bed_step_pct × bed_delta) × (1 ± bath_step_pct × bath_delta)
    adj_multiplier = 1.0 + bed_delta + bath_delta
    arv_estimate = max(0.0, arv_base * adj_multiplier)

    # Confidence computation per agents.md n_iqr method
    conf = _confidence_from_ppsf(ppsf_vals, cfg.arv_config.min_comps)

    # Deal ratio
    list_to_arv_pct = float(list_price) / float(arv_estimate) if arv_estimate > 0 else 0.0

    # Profit scenarios (nullable if no rehab budget) per agents.md
    profit_conservative = profit_median = profit_optimistic = None
    if cfg.profit_config and cfg.profit_config.rehab_budget is not None and list_price is not None:
        # ARV scenarios per agents.md formulas
        arv_conservative = arv_estimate * (1.0 - cfg.profit_config.moe_pct_conservative)
        arv_median = arv_estimate
        arv_optimistic = arv_estimate * (1.0 - cfg.profit_config.moe_pct_optimistic)

        # Total costs per agents.md formula
        closing_costs = cfg.profit_config.closing_costs_pct * list_price
        selling_costs = cfg.profit_config.selling_costs_pct * arv_median
        misc_buffer = cfg.profit_config.misc_buffer_pct * arv_median
        total_costs = list_price + cfg.profit_config.rehab_budget + closing_costs + selling_costs + misc_buffer

        # Profit_* = ARV_* − Costs per agents.md
        profit_conservative = arv_conservative - total_costs
        profit_median = arv_median - total_costs
        profit_optimistic = arv_optimistic - total_costs

    # Structure results with proper types and rounding
    row.update({
        "arv_estimate": round(arv_estimate, 2) if arv_estimate else 0.0,
        "arv_ppsf": round(med_ppsf, 2) if med_ppsf else 0.0,
        "comp_count": len(ppsf_vals),
        "arv_confidence": round(conf, 3),
        "list_to_arv_pct": round(list_to_arv_pct, 4),
        "profit_conservative": round(profit_conservative, 2) if profit_conservative is not None else None,
        "profit_median": round(profit_median, 2) if profit_median is not None else None,
        "profit_optimistic": round(profit_optimistic, 2) if profit_optimistic is not None else None,
    })

    return row, None

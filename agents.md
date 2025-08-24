# Real Estate Agent v0 – High-Level Guidance (agents.md)

## Goal
Build an AI-assisted **CLI** that:
1) Finds properties on Zillow via RapidAPI using filters (state, zip, budget, beds, baths, etc.).
2) Estimates **ARV** (After Repair Value) using comparable sales.
3) Computes **profit scenarios** (conservative / median / optimistic) for flips; include rental fields later.

## Non-Negotiable Principles
- **Fail-fast:** no silent failures. **Any exception must terminate the program** with a clear error message and non-zero exit code.
- **Typed everything:** use **Pydantic** models to define all inputs, outputs, and internal records.
- **Structured by default:** all LLM interactions must **request/return structured outputs** (JSON conforming to our Pydantic schemas). Free text is only a source; the result is always structured.

## Workflow
1) **Load config (YAML)** and validate with Pydantic.
   - `filters`: strict rules (price, beds, baths, etc.)
   - `arv_config`: comps radius, recency, adjustments
   - `profit_config`: rehab budget, costs %, margins
   - `deal_screen`: optional list-price/ARV gate
   - `prompt`: free-text that will be parsed by the LLM into the same schema
2) **Parse `prompt` → structured config** using OpenAI with a **function/schema call** that targets our Pydantic shapes. **Merge** with strict fields (strict wins). Validate again.
3) **Query Zillow via RapidAPI** (wrappers: `search_properties`, `get_property_details`, `get_property_comps`). On unsupported endpoints, **raise**; or explicitly log and execute the documented fallback — still **fail** if fallback has unmet preconditions.
4) For each property:
   - Collect details + comps (validated models).
   - Compute **ARV**:
     - Median **$ / sqft** of filtered comps × subject sqft
     - Adjust for bed/bath deltas; cap lot influence
   - Compute **confidence** (n & dispersion of comp ppsf)
   - If `rehab_budget` is set → compute **profit** scenarios
5) **Write CSV** with validated, typed rows only. If a row cannot be constructed → **raise**.
6) **Cache** raw API JSON in SQLite to avoid duplicates.
7) **Respect rate limits** (100/day), use backoff. If budget exceeded → **exit** with clear message.
8) **Log** pipeline steps clearly (INFO console, DEBUG file).

## Configuration (YAML)
Example `config.example.yaml`:
```yaml
filters:
  geos: ["Dallas, TX", "75253", "Fort Worth, TX"]
  status: ["FOR_SALE"]
  home_types: ["SINGLE_FAMILY"]
  price_min: 80000
  price_max: 400000
  beds_min: 3
  baths_min: 2
  min_sqft: 1000
  min_lot_sqft: 4000
  year_built_min: 1950
  max_dom: 30
  include_pending: false
  hoa_max: null
  price_reduction_only: false
  page_cap: 5

arv_config:
  comp_radius_mi: 0.75
  comp_window_months: 6
  extend_window_if_insufficient: 12
  min_comps: 3
  ppsf_method: median
  adjustments:
    bed_step_pct: 0.04
    bath_step_pct: 0.05
    lot_size_cap_ratio: 2.0
    age_condition_proxy: false
  confidence_method: n_iqr

profit_config:
  rehab_budget: null
  closing_costs_pct: 0.03
  selling_costs_pct: 0.06
  misc_buffer_pct: 0.02
  moe_pct_conservative: 0.10
  moe_pct_optimistic: 0.03

deal_screen:
  max_list_to_arv_pct: null  # e.g., 0.7 → list_price ≤ 70% of ARV

prompt: |
  Texas DFW single-family houses, 3+2 minimum, decent lots, DOM < 30,
  budget 80k–400k. Use nearby sold comps within 0.75mi and 6 months;
  extend to 12 months if fewer than 3 comps.

Pydantic Models (authoritative schemas)
	•	Define models for:
	•	Filters, ArvAdjustments, ArvConfig, ProfitConfig, DealScreen, AppConfig
	•	PropertySummary, PropertyDetails, CompRecord
	•	ArvComputation, ProfitScenarios, CsvRow
	•	Use model_validate_json / model_dump to convert between JSON and Python.
	•	All external responses (RapidAPI/LLM) must be parsed through these models; reject on validation errors.

Example (sketch)

class Filters(BaseModel):
    geos: list[str]
    status: list[str] = ["FOR_SALE"]
    home_types: list[str] = ["SINGLE_FAMILY"]
    price_min: float | None = None
    price_max: float | None = None
    beds_min: int | None = None
    baths_min: int | None = None
    min_sqft: int | None = None
    min_lot_sqft: int | None = None
    year_built_min: int | None = None
    max_dom: int | None = None
    include_pending: bool = False
    hoa_max: float | None = None
    price_reduction_only: bool = False
    page_cap: int = 5

(Define the rest similarly and use them everywhere.)

LLM Usage (always structured)
	•	System prompt: “Return only JSON matching the provided schema.”
	•	Use tool/function calling with an explicit JSON schema derived from the Pydantic models (or provide a formal JSON Schema).
	•	On any parsing/validation error: raise with the raw LLM output attached.

RapidAPI (Zillow) Requirements

Implement typed clients (httpx) for:
	1.	search_properties(params: dict) -> PropertySearchResult
	2.	get_property_details(zpid: str) -> PropertyDetails
	3.	get_property_comps(zpid: str, count: int = 25) -> CompsResult

	•	If a specific endpoint is unavailable in the plan, log once and use the documented fallback (e.g., nearby sold by geo). If fallback cannot satisfy min_comps, still compute ARV but confidence is low. If zero comps after fallback → raise.

ARV Method (v0)
	•	Filter comps: same home_type; sqft within ±20% (constant).
	•	Baseline ARV = median(ppsf of comps) × subject_sqft.
	•	Adjustments:
	•	Beds: ARV *= (1 ± bed_step_pct × bed_delta)
	•	Baths: ARV *= (1 ± bath_step_pct × bath_delta)
	•	Ignore lot beyond lot_size_cap_ratio × subject_lot when computing ppsf
	•	Confidence (n_iqr):
	•	n = comp_count
	•	dispersion = IQR(ppsf) / median(ppsf)
	•	Map to [0,1] increasing with n and decreasing with dispersion (document formula in code).

Profit Scenarios (nullable if no rehab budget)
	•	ARV_conservative = ARV × (1 − moe_pct_conservative)
	•	ARV_median = ARV
	•	ARV_optimistic = ARV × (1 − moe_pct_optimistic)
	•	Costs = list_price + rehab_budget + closing_costs_pct*list_price + selling_costs_pct*ARV_median + misc_buffer_pct*ARV_median
	•	Profit_* = ARV_* − Costs

CSV Columns (strict order)

Identification: zpid,address,city,state,zip,latitude,longitude,url,status,dom,hoa
Specs: list_price,beds,baths,sqft,lot_sqft,year_built,home_type
ARV: arv_estimate,arv_ppsf,comp_count,comp_radius_mi,comp_window_months,arv_confidence
Deal: list_to_arv_pct
Profit: profit_conservative,profit_median,profit_optimistic
Ops: search_geo,page,ts_utc

Caching & Rate Limits
	•	SQLite cache.db, table:
	•	raw(property_id TEXT, endpoint TEXT, payload_json TEXT, ts INTEGER, PRIMARY KEY(property_id, endpoint))
	•	Enforce ≤ 100 requests/day (token bucket). If exceeded → exit(2) with a clear message.
	•	Tenacity backoff on 429/5xx. If retries exhausted → raise.

Logging
	•	INFO → console; DEBUG → logs/run_<timestamp>.log
	•	Always log: merged/validated config, endpoints used/fallbacks, pagination counts, comp stats, CSV path.

Failure & Errors (explicit)
	•	Any unexpected condition (validation error, missing field, HTTP non-2xx, empty required data, CSV write failure) must raise and terminate the run.
	•	No try/except that swallows exceptions; if caught to add context, re-raise immediately after logging.

Deliverables
	•	find_props.py (single CLI)
	•	config.example.yaml
	•	.env.example (OPENAI_API_KEY, RAPIDAPI_KEY, etc.)
	•	README.md (setup, how to obtain RapidAPI access, how to run)


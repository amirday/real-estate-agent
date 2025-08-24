# Real Estate Agent v0 – High-Level Guidance

## Goal
Build an AI-assisted real estate agent that:
1. Finds properties on Zillow via RapidAPI using filters (state, zip, budget, etc.).
2. Estimates ARV (After Repair Value) using comparable sales.
3. Prepares profit scenarios for flip or rental.

## Workflow
1. Load config (JSON):
   - `filters`: strict rules (price, beds, baths, etc.).
   - `arv_config`: comps radius, recency, adjustments.
   - `profit_config`: rehab budget, costs %, margins.
   - `prompt`: free-text, parsed by OpenAI → merged with strict config.
2. Query Zillow via RapidAPI (`search_properties`, `get_property_details`, `get_property_comps`).
3. For each property:
   - Collect details + comps.
   - Compute ARV:
     - Median $/sqft × subject sqft.
     - Adjust for bed/bath deltas.
   - Compute confidence (based on comp count + price spread).
   - If rehab budget given → compute profit (conservative / median / optimistic).
4. Write results to CSV.
   - Include property specs, ARV, comps count, confidence, profit estimates.
5. Cache raw API JSON in SQLite to avoid duplicates.
6. Respect RapidAPI rate limits (100/day).
7. Log pipeline steps clearly.

## Output
CSV per run with:
- Property info (zpid, address, list price, specs).
- ARV estimate + confidence.
- Profit scenarios (if rehab budget given).
- Deal ratio: list_price / ARV.

## Notes
- v0 only → CLI + CSV. No web UI yet.
- ARV logic = simple comps (median $/sqft). Refinements later.
- Free-text config allows flexible natural language input.
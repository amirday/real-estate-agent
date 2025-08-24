**Zillow ARV Agent**

- **Goal:** CLI tool to search Zillow via RapidAPI, fetch details and comps, estimate ARV, compute profit scenarios, cache results, and export to CSV.

**Setup**
- **Python:** 3.11+
- **Install:**
  - Quick: `pip install -r requirements.txt`
  - Or: `pip install httpx pydantic loguru python-dotenv tenacity pyyaml openai`
- **Env:** copy `.env.example` → `.env` and set keys
  - `OPENAI_API_KEY` (optional, for free-text parsing)
  - `RAPIDAPI_KEY` (required)
  - `OPENAI_MODEL` (default `gpt-4.1-mini`)
  - `ZILLOW_RAPIDAPI_HOST` (default `zillow-com1.p.rapidapi.com`)

**Config**
- See `config.example.yaml`. You can provide both strict fields and a free-text `prompt`. Strict values win on conflicts.

**Run**
- Ready-to-run DFW: `python find_props.py --config config.yaml --out out/properties.csv --verbose`
- Example config: `python find_props.py --config config.example.yaml --out out/properties.csv --verbose`

**Outputs**
- CSV under `out/`
- Logs under `logs/` (DEBUG in file, INFO on console)
- Cache at `cache.db`

**Rate Limits & Caching**
- Local SQLite token bucket, max 100 network requests per UTC day.
- All responses cached by endpoint+parameters to minimize duplicates.

**Notes**
- Endpoints wrapped: `/propertyExtendedSearch`, `/property`, `/comps` with fallback to recently sold search when comps are unavailable.
- ARV: median $/sqft of filtered comps × subject sqft, with bed/bath adjustments and confidence based on comp count and IQR.
- Profit scenarios computed if `profit_config.rehab_budget` is set.

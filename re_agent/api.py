from __future__ import annotations

import os
from typing import Any, Dict, Optional

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from .cache import cache_key_from_params, get_cached, set_cached, rate_limit_check_and_increment
from .exc import RateLimitExceeded, DataValidationError
from .models import PropertySearchResult, PropertyDetails, CompsResult, PropertySummary


class ZillowClient:
    def __init__(self, logger=None):
        self.logger = logger
        self.host = os.getenv("ZILLOW_RAPIDAPI_HOST", "zillow-com1.p.rapidapi.com")
        self.key = os.getenv("RAPIDAPI_KEY")
        self.base_url = f"https://{self.host}"
        self.headers = {
            "x-rapidapi-host": self.host,
            "x-rapidapi-key": self.key or "",
        }

    def _log(self, msg: str):
        if self.logger:
            self.logger.info(msg)

    def _log_debug(self, msg: str):
        if self.logger:
            self.logger.debug(msg)

    def _check_key(self):
        if not self.key:
            raise RuntimeError("RAPIDAPI_KEY not set in environment")

    def _allowed_and_cached(self, endpoint: str, params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        key = cache_key_from_params(params)
        cached = get_cached(endpoint, key)
        if cached is not None:
            self._log_debug(f"Cache hit: {endpoint}")
            return cached
        # Rate limit check only if we will actually hit the network
        allowed = rate_limit_check_and_increment(limit_per_day=100)
        if not allowed:
            raise RateLimitExceeded("Daily request limit reached (100)")
        return None

    def _store_cache(self, endpoint: str, params: Dict[str, Any], payload: Dict[str, Any]):
        key = cache_key_from_params(params)
        set_cached(endpoint, key, payload)

    @retry(wait=wait_exponential(multiplier=1, min=1, max=8), stop=stop_after_attempt(3))
    def _get(self, path: str, params: Dict[str, Any]) -> Dict[str, Any]:
        self._check_key()
        url = f"{self.base_url}{path}"
        with httpx.Client(timeout=20.0) as client:
            resp = client.get(url, headers=self.headers, params=params)
            resp.raise_for_status()
            return resp.json()

    def search_properties(self, geo: str, page: int, cfg) -> PropertySearchResult:
        """Search properties and return structured PropertySearchResult per agents.md."""
        endpoint = "propertyExtendedSearch"
        params = self._params_from_filters(geo=geo, page=page, cfg=cfg)

        cached = self._allowed_and_cached(endpoint, params)
        if cached is not None:
            try:
                return PropertySearchResult.model_validate(cached)
            except Exception as e:
                raise DataValidationError(f"Failed to validate cached search result: {e}")

        # Zillow RapidAPI common search endpoint
        payload = self._get("/propertyExtendedSearch", params)
        self._store_cache(endpoint, params, payload)
        self._log(f"Used endpoint: {endpoint} geo={geo} page={page}")
        
        try:
            return PropertySearchResult.model_validate(payload)
        except Exception as e:
            raise DataValidationError(f"Failed to validate search result from API: {e}")

    def get_property_details(self, zpid: str) -> PropertyDetails:
        """Get property details and return structured PropertyDetails per agents.md."""
        endpoint = "property"
        params = {"zpid": zpid}

        cached = self._allowed_and_cached(endpoint, params)
        if cached is not None:
            try:
                return PropertyDetails.model_validate(cached)
            except Exception as e:
                raise DataValidationError(f"Failed to validate cached property details: {e}")

        payload = self._get("/property", params)
        # Normalize: some responses wrap details
        details = payload.get("property") or payload.get("data") or payload
        if isinstance(details, dict) and "property" in details:
            details = details["property"]
        
        self._store_cache(endpoint, params, details)
        self._log(f"Used endpoint: {endpoint} zpid={zpid}")
        
        try:
            return PropertyDetails.model_validate(details)
        except Exception as e:
            raise DataValidationError(f"Failed to validate property details from API: {e}")

    def get_property_comps(self, zpid: str, subject: Optional[PropertyDetails], cfg) -> CompsResult:
        """Get property comps and return structured CompsResult per agents.md."""
        # Primary: comps endpoint
        endpoint = "comps"
        params = {"zpid": zpid, "count": 25}

        cached = self._allowed_and_cached(endpoint, params)
        if cached is not None:
            try:
                return CompsResult.model_validate(cached)
            except Exception as e:
                raise DataValidationError(f"Failed to validate cached comps result: {e}")

        try:
            payload = self._get("/comps", params)
            comps = (
                payload.get("comparables")
                or payload.get("comp")
                or payload.get("results")
                or payload.get("props")
                or payload.get("comps")
                or []
            )
            out = {"comps": comps}
            self._store_cache(endpoint, params, out)
            self._log(f"Used endpoint: {endpoint} zpid={zpid}")
            
            try:
                return CompsResult.model_validate(out)
            except Exception as e:
                raise DataValidationError(f"Failed to validate comps result from API: {e}")
                
        except Exception as e:
            self._log(f"Comps endpoint unavailable, attempting fallback: {e}")

        # Fallback: recently sold near subject per agents.md fallback specification
        lat = subject.latitude if subject and hasattr(subject, 'latitude') else None
        lng = subject.longitude if subject and hasattr(subject, 'longitude') else None
        radius = cfg.arv_config.comp_radius_mi if cfg and cfg.arv_config else 0.75
        months = cfg.arv_config.comp_window_months if cfg and cfg.arv_config else 6
        endpoint = "propertyExtendedSearch_sold"
        params = {
            "status": "RecentlySold",
            "latitude": lat,
            "longitude": lng,
            "radius": radius,
            "soldInLast": months,
            "sort": "days",
            "isRecentlySold": True,
            "home_type": ",".join(cfg.filters.home_types) if cfg and cfg.filters and cfg.filters.home_types else None,
        }
        # Clean None
        params = {k: v for k, v in params.items() if v is not None}

        cached = self._allowed_and_cached(endpoint, params)
        if cached is not None:
            try:
                return CompsResult.model_validate(cached)
            except Exception as e:
                raise DataValidationError(f"Failed to validate cached fallback comps: {e}")

        payload = self._get("/propertyExtendedSearch", params)
        # normalize shape to {comps: [...]} if necessary
        comps = payload.get("results") or payload.get("props") or []
        
        # If insufficient comps and allowed to extend window per agents.md
        if cfg and cfg.arv_config and len(comps) < cfg.arv_config.min_comps:
            ext_months = cfg.arv_config.extend_window_if_insufficient
            if ext_months and ext_months > months:
                params_ext = dict(params)
                params_ext["soldInLast"] = ext_months
                try:
                    payload_ext = self._get("/propertyExtendedSearch", params_ext)
                    comps_ext = payload_ext.get("results") or payload_ext.get("props") or []
                    if len(comps_ext) > len(comps):
                        comps = comps_ext
                        params = params_ext
                        self._log("Extended comps window due to insufficiency")
                except Exception as e:
                    self._log_debug(f"Extended window fetch failed: {e}")
                    
        out = {"comps": comps}
        self._store_cache(endpoint, params, out)
        self._log("Used fallback: recently sold via propertyExtendedSearch")
        
        try:
            return CompsResult.model_validate(out)
        except Exception as e:
            raise DataValidationError(f"Failed to validate fallback comps result: {e}")

    def _params_from_filters(self, geo: str, page: int, cfg) -> Dict[str, Any]:
        f = cfg.filters
        params: Dict[str, Any] = {
            "location": geo,
            "page": page,
            "status_type": ",".join(f.status) if f.status else None,
            "home_type": ",".join(f.home_types) if f.home_types else None,
            "price_min": f.price_min,
            "price_max": f.price_max,
            "beds_min": f.beds_min,
            "baths_min": f.baths_min,
            "sqft_min": f.min_sqft,
            "lot_size_min": f.min_lot_sqft,
            "year_built_min": f.year_built_min,
            "include_pending": f.include_pending or None,
            "hoa_max": f.hoa_max,
            "is_price_reduced": f.price_reduction_only or None,
            "sort": "days" if f.max_dom else None,
        }
        # Remove None values
        params = {k: v for k, v in params.items() if v is not None}
        return params

from __future__ import annotations

import os
from typing import Any, Dict, Optional

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from .cache import cache_key_from_params, get_cached, set_cached
from .exc import DataValidationError
from .models import PropertySearchResult, PropertyDetails, CompsResult, PropertySummary, ZillowSearchParams, ZillowApiMapping


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

    def _get_cached(self, endpoint: str, params: Dict[str, Any], cache_enabled: bool = True, cache_ttl_hours: int = 24) -> Optional[Dict[str, Any]]:
        if not cache_enabled:
            return None
            
        key = cache_key_from_params(params)
        cached = get_cached(endpoint, key, cache_ttl_hours)
        if cached is not None:
            self._log_debug(f"Cache hit: {endpoint}")
            return cached
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
        
        # Create structured parameters using Pydantic models
        structured_params = self._params_from_filters(geo=geo, page=page, cfg=cfg)
        params_dict = self._params_to_dict(structured_params)

        # Check cache first
        cached = self._get_cached(
            endpoint, 
            params_dict,
            cache_enabled=cfg.cache_config.api_cache_enabled,
            cache_ttl_hours=cfg.cache_config.cache_ttl_hours
        )
        if cached is not None:
            try:
                return PropertySearchResult.model_validate(cached)
            except Exception as e:
                raise DataValidationError(f"Failed to validate cached search result: {e}")

        # Zillow RapidAPI common search endpoint
        payload = self._get("/propertyExtendedSearch", params_dict)
        
        # Store in cache only if enabled
        if cfg.cache_config.api_cache_enabled:
            self._store_cache(endpoint, params_dict, payload)
        
        cache_status = "cache enabled" if cfg.cache_config.api_cache_enabled else "cache disabled"
        self._log(f"Used endpoint: {endpoint} geo={geo} page={page} ({cache_status}) params={structured_params.model_dump_json(exclude_none=True)}")
        
        try:
            return PropertySearchResult.model_validate(payload)
        except Exception as e:
            raise DataValidationError(f"Failed to validate search result from API: {e}")

    def get_property_details(self, zpid: str, cfg=None) -> PropertyDetails:
        """Get property details and return structured PropertyDetails per agents.md."""
        endpoint = "property"
        params = {"zpid": zpid}

        # Use cache configuration if provided, otherwise use defaults
        if cfg:
            cached = self._get_cached(
                endpoint, 
                params, 
                cache_enabled=cfg.cache_config.api_cache_enabled,
                cache_ttl_hours=cfg.cache_config.cache_ttl_hours
            )
        else:
            cached = self._get_cached(endpoint, params, cache_enabled=True, cache_ttl_hours=24)
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
        
        # Store in cache only if enabled
        if cfg and cfg.cache_config.api_cache_enabled:
            self._store_cache(endpoint, params, details)
        elif not cfg:  # Default to caching if no config provided
            self._store_cache(endpoint, params, details)
        
        cache_status = "cache enabled" if (cfg and cfg.cache_config.api_cache_enabled) or not cfg else "cache disabled"
        self._log(f"Used endpoint: {endpoint} zpid={zpid} ({cache_status})")
        
        try:
            return PropertyDetails.model_validate(details)
        except Exception as e:
            raise DataValidationError(f"Failed to validate property details from API: {e}")

    def get_property_comps(self, zpid: str, subject: Optional[PropertyDetails], cfg) -> CompsResult:
        """Get property comps and return structured CompsResult per agents.md."""
        # Primary: comps endpoint
        endpoint = "comps"
        params = {"zpid": zpid, "count": 25}

        cached = self._get_cached(
            endpoint, 
            params, 
            cache_enabled=cfg.cache_config.api_cache_enabled,
            cache_ttl_hours=cfg.cache_config.cache_ttl_hours
        )
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
            
            # Store in cache only if enabled
            if cfg.cache_config.api_cache_enabled:
                self._store_cache(endpoint, params, out)
            
            cache_status = "cache enabled" if cfg.cache_config.api_cache_enabled else "cache disabled"
            self._log(f"Used endpoint: {endpoint} zpid={zpid} ({cache_status})")
            
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

        cached = self._get_cached(
            endpoint, 
            params, 
            cache_enabled=cfg.cache_config.api_cache_enabled,
            cache_ttl_hours=cfg.cache_config.cache_ttl_hours
        )
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
        
        # Store in cache only if enabled
        if cfg.cache_config.api_cache_enabled:
            self._store_cache(endpoint, params, out)
        
        cache_status = "cache enabled" if cfg.cache_config.api_cache_enabled else "cache disabled"
        self._log(f"Used fallback: recently sold via propertyExtendedSearch ({cache_status})")
        
        try:
            return CompsResult.model_validate(out)
        except Exception as e:
            raise DataValidationError(f"Failed to validate fallback comps result: {e}")

    def _params_from_filters(self, geo: str, page: int, cfg) -> ZillowSearchParams:
        """Convert internal filters to structured Zillow API parameters using Pydantic models."""
        f = cfg.filters
        mapping = cfg.zillow_api_mapping
        
        # Start with required parameters
        param_data = {
            "location": geo,
            "page": page,
        }
        
        # Map status values using configuration
        if f.status:
            mapped_status = [mapping.status_map.get(s, s) for s in f.status]
            param_data["status_type"] = mapped_status[0] if len(mapped_status) == 1 else ",".join(mapped_status)
            
        # Map home types using configuration  
        if f.home_types:
            mapped_types = [mapping.home_type_map.get(t, t) for t in f.home_types]
            param_data["home_type"] = mapped_types[0] if len(mapped_types) == 1 else ",".join(mapped_types)
            
        # Map filter parameters using configuration
        filter_mapping = {
            "price_min": f.price_min,
            "price_max": f.price_max,
            "beds_min": f.beds_min,
            "baths_min": f.baths_min,
            "min_sqft": f.min_sqft,
            "min_lot_sqft": f.min_lot_sqft,
            "year_built_min": f.year_built_min,
            "max_dom": f.max_dom,
            "hoa_max": f.hoa_max
        }
        
        for internal_param, value in filter_mapping.items():
            if value is not None:
                api_param = mapping.param_map.get(internal_param, internal_param)
                # Convert price values to integers
                if "Price" in api_param and isinstance(value, float):
                    param_data[api_param] = int(value)
                else:
                    param_data[api_param] = value
        
        # Set sort parameter if max_dom filter is specified
        if f.max_dom:
            param_data["sort"] = "days"
            
        # Validate and return structured parameters
        try:
            return ZillowSearchParams.model_validate(param_data)
        except Exception as e:
            raise DataValidationError(f"Failed to create valid Zillow API parameters: {e}")
    
    def _params_to_dict(self, params: ZillowSearchParams) -> Dict[str, Any]:
        """Convert ZillowSearchParams to dict excluding None values for URL building."""
        return {k: v for k, v in params.model_dump().items() if v is not None}

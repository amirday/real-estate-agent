from __future__ import annotations

from typing import Optional, List

from pydantic import BaseModel, Field


class Filters(BaseModel):
    geos: List[str]
    status: List[str] = ["FOR_SALE"]
    home_types: List[str] = ["SINGLE_FAMILY"]
    price_min: Optional[float] = None
    price_max: Optional[float] = None
    beds_min: Optional[int] = None
    baths_min: Optional[int] = None
    min_sqft: Optional[int] = None
    min_lot_sqft: Optional[int] = None
    year_built_min: Optional[int] = None
    max_dom: Optional[int] = None
    include_pending: bool = False
    hoa_max: Optional[float] = None
    price_reduction_only: bool = False
    page_cap: int = 5


class ArvAdjustments(BaseModel):
    bed_step_pct: float = 0.04
    bath_step_pct: float = 0.05
    lot_size_cap_ratio: float = 2.0
    age_condition_proxy: bool = False


class ArvConfig(BaseModel):
    comp_radius_mi: float = 0.75
    comp_window_months: int = 6
    extend_window_if_insufficient: int = 12
    min_comps: int = 3
    ppsf_method: str = "median"
    adjustments: ArvAdjustments = Field(default_factory=ArvAdjustments)
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


class ZillowApiMapping(BaseModel):
    """Configuration for mapping internal filter values to Zillow API parameters."""
    status_map: dict[str, str] = Field(default_factory=lambda: {
        "FOR_SALE": "ForSale",
        "SOLD": "Sold", 
        "RECENTLY_SOLD": "RecentlySold",
        "PENDING": "Pending"
    })
    home_type_map: dict[str, str] = Field(default_factory=lambda: {
        "SINGLE_FAMILY": "SingleFamily",
        "CONDO": "Condo",
        "TOWNHOUSE": "Townhouse",
        "MULTI_FAMILY": "MultiFamily",
        "LOT": "Lot",
        "MOBILE": "Mobile",
        "FARM": "Farm"
    })
    param_map: dict[str, str] = Field(default_factory=lambda: {
        "price_min": "minPrice",
        "price_max": "maxPrice", 
        "beds_min": "beds",
        "baths_min": "baths",
        "min_sqft": "minSqft",
        "min_lot_sqft": "minLotSize",
        "year_built_min": "minYearBuilt",
        "max_dom": "daysOnMarket",
        "hoa_max": "maxHOA"
    })


class ZillowSearchParams(BaseModel):
    """Pydantic model for Zillow API search parameters."""
    location: str
    page: int = 1
    status_type: Optional[str] = None
    home_type: Optional[str] = None
    minPrice: Optional[int] = None
    maxPrice: Optional[int] = None
    beds: Optional[int] = None
    baths: Optional[int] = None
    minSqft: Optional[int] = None
    minLotSize: Optional[int] = None
    minYearBuilt: Optional[int] = None
    daysOnMarket: Optional[int] = None
    maxHOA: Optional[float] = None
    sort: Optional[str] = None
    
    model_config = {
        "extra": "forbid"  # Prevent extra parameters that might cause API errors
    }


class LlmConfig(BaseModel):
    """Configuration for LLM/OpenAI settings."""
    model: str = "gpt-4o-mini"  # Cheapest model that supports JSON mode
    max_tokens: Optional[int] = None
    temperature: float = 0.0  # Deterministic for config parsing


class CacheConfig(BaseModel):
    """Configuration for caching behavior."""
    clear_before_run: bool = False
    clear_llm_cache: bool = False
    clear_api_cache: bool = False
    llm_cache_enabled: bool = True
    api_cache_enabled: bool = False
    cache_ttl_hours: int = 2400  # Time-to-live for cache entries


class AppConfig(BaseModel):
    filters: Filters
    arv_config: ArvConfig = Field(default_factory=ArvConfig)
    profit_config: ProfitConfig = Field(default_factory=ProfitConfig)
    deal_screen: Optional[DealScreen] = None
    prompt: Optional[str] = None
    zillow_api_mapping: ZillowApiMapping = Field(default_factory=ZillowApiMapping)
    cache_config: CacheConfig = Field(default_factory=CacheConfig)
    llm_config: LlmConfig = Field(default_factory=LlmConfig)


class PropertySummary(BaseModel):
    zpid: str
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    zipcode: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    price: Optional[float] = None
    beds: Optional[int] = None
    baths: Optional[float] = None
    sqft: Optional[float] = None
    lotSize: Optional[float] = None
    yearBuilt: Optional[int] = None
    homeType: Optional[str] = None
    homeStatus: Optional[str] = None
    daysOnZillow: Optional[int] = None
    detailUrl: Optional[str] = None

    model_config = {
        "extra": "allow",
    }


class PropertyDetails(BaseModel):
    zpid: str = Field(..., alias="zpid")
    address: Optional[str] = Field(default=None, alias="address")
    city: Optional[str] = Field(default=None, alias="city")
    state: Optional[str] = Field(default=None, alias="state")
    zipcode: Optional[str] = Field(default=None, alias="zipcode")
    latitude: Optional[float] = Field(default=None, alias="latitude")
    longitude: Optional[float] = Field(default=None, alias="longitude")
    url: Optional[str] = Field(default=None, alias="url")
    homeStatus: Optional[str] = Field(default=None, alias="homeStatus")
    daysOnZillow: Optional[int] = Field(default=None, alias="daysOnZillow")
    hoaFee: Optional[float] = Field(default=None, alias="hoaFee")
    price: Optional[float] = Field(default=None, alias="price")
    bedrooms: Optional[int] = Field(default=None, alias="bedrooms")
    bathrooms: Optional[float] = Field(default=None, alias="bathrooms")
    livingArea: Optional[float] = Field(default=None, alias="livingArea")
    lotAreaValue: Optional[float] = Field(default=None, alias="lotAreaValue")
    yearBuilt: Optional[int] = Field(default=None, alias="yearBuilt")
    homeType: Optional[str] = Field(default=None, alias="homeType")

    model_config = {
        "populate_by_name": True,
        "extra": "allow",
    }


class CompRecord(BaseModel):
    price: float
    sqft: float
    beds: Optional[int] = None
    baths: Optional[float] = None
    lot_sqft: Optional[float] = None
    home_type: Optional[str] = None

    model_config = {
        "extra": "allow",
    }


class PropertySearchResult(BaseModel):
    results: List[PropertySummary] = []
    totalResultCount: Optional[int] = None
    
    model_config = {
        "extra": "allow",
    }


class CompsResult(BaseModel):
    comps: List[CompRecord] = []
    
    model_config = {
        "extra": "allow",
    }


class ArvComputation(BaseModel):
    arv_estimate: float
    arv_ppsf: float
    comp_count: int
    arv_confidence: float


class ProfitScenarios(BaseModel):
    profit_conservative: Optional[float] = None
    profit_median: Optional[float] = None
    profit_optimistic: Optional[float] = None


class CsvRow(BaseModel):
    # Identification (exact order from agents.md)
    zpid: str
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    zip: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    url: Optional[str] = None
    status: Optional[str] = None
    dom: Optional[int] = None
    hoa: Optional[float] = None
    # Specs
    list_price: Optional[float] = None
    beds: Optional[int] = None
    baths: Optional[float] = None
    sqft: Optional[float] = None
    lot_sqft: Optional[float] = None
    year_built: Optional[int] = None
    home_type: Optional[str] = None
    # ARV
    arv_estimate: float
    arv_ppsf: float
    comp_count: int
    comp_radius_mi: float
    comp_window_months: int
    arv_confidence: float
    # Deal
    list_to_arv_pct: float
    # Profit
    profit_conservative: Optional[float] = None
    profit_median: Optional[float] = None
    profit_optimistic: Optional[float] = None
    # Ops
    search_geo: str
    page: int
    ts_utc: str


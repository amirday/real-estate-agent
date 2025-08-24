from __future__ import annotations

from typing import Optional, List

from pydantic import BaseModel, Field


class PropertyDetails(BaseModel):
    zpid: str = Field(..., alias="zpid")
    address: Optional[str] = Field(default=None, alias="address")
    city: Optional[str] = Field(default=None, alias="city")
    state: Optional[str] = Field(default=None, alias="state")
    zip: Optional[str] = Field(default=None, alias="zipcode")
    latitude: Optional[float] = Field(default=None, alias="latitude")
    longitude: Optional[float] = Field(default=None, alias="longitude")
    url: Optional[str] = Field(default=None, alias="url")
    status: Optional[str] = Field(default=None, alias="homeStatus")
    dom: Optional[int] = Field(default=None, alias="daysOnZillow")
    hoa: Optional[float] = Field(default=None, alias="hoaFee")
    list_price: Optional[float] = Field(default=None, alias="price")
    beds: Optional[float] = Field(default=None, alias="bedrooms")
    baths: Optional[float] = Field(default=None, alias="bathrooms")
    sqft: Optional[float] = Field(default=None, alias="livingArea")
    lot_sqft: Optional[float] = Field(default=None, alias="lotAreaValue")
    year_built: Optional[int] = Field(default=None, alias="yearBuilt")
    home_type: Optional[str] = Field(default=None, alias="homeType")

    # Allow population by field name too to support search payloads
    model_config = {
        "populate_by_name": True,
        "extra": "allow",
    }


class CompRecord(BaseModel):
    price: float
    sqft: float
    beds: Optional[float] = None
    baths: Optional[float] = None
    lot_sqft: Optional[float] = None
    home_type: Optional[str] = None

    model_config = {
        "extra": "allow",
    }


class ArvComputation(BaseModel):
    arv_estimate: float
    arv_ppsf: float
    comp_count: int
    arv_confidence: float


class ProfitScenarios(BaseModel):
    profit_conservative: float
    profit_median: float
    profit_optimistic: float


class CsvRow(BaseModel):
    # Identification
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
    beds: Optional[float] = None
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


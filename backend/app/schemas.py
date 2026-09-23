from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field


class CalculateRequest(BaseModel):
    warehouse: str | None = None
    category: str | None = None
    safety_days: int = Field(default=7, ge=0, le=90)
    service_factor: float = Field(default=1.65, ge=0, le=4, allow_inf_nan=False)
    outlier_threshold: float = Field(default=3.5, ge=1, le=10, allow_inf_nan=False)


class AdjustOrderRequest(BaseModel):
    final_quantity: float = Field(ge=0, allow_inf_nan=False)


class EditorRowPayload(BaseModel):
    row: dict[str, Any]


class EditorDraftPayload(BaseModel):
    dataset: str
    row: dict[str, Any] = Field(default_factory=dict)
    row_id: int | None = Field(default=None, ge=0)


class MovementLine(BaseModel):
    sku: str = Field(min_length=1)
    product_name: str = ''
    category: str = ''
    quantity: float = Field(allow_inf_nan=False)
    unit_price: float = Field(default=0, ge=0, allow_inf_nan=False)
    recommendation_id: str | None = None


class MovementRequest(BaseModel):
    kind: Literal['PURCHASE', 'RECEIPT', 'SALE', 'TRANSFER', 'ADJUSTMENT', 'RETURN']
    date: date
    warehouse: str = Field(min_length=1)
    destination_warehouse: str | None = None
    partner: str = ''
    reference: str = ''
    expected_arrival_date: date | None = None
    client_request_id: str | None = Field(default=None, max_length=60)
    lines: list[MovementLine] = Field(min_length=1)


class UploadResponse(BaseModel):
    dataset: str
    rows_loaded: int
    errors: list[str] = []
    warnings: list[str] = []


class Recommendation(BaseModel):
    id: str
    sku: str
    product_name: str
    warehouse: str
    category: str
    supplier_id: str
    supplier_name: str
    current_stock: float
    in_transit: float
    average_daily_demand: float
    forecast_lead_time: float
    safety_stock: float
    inventory_position: float
    raw_recommended_quantity: float
    recommended_quantity: float
    final_quantity: float
    lead_time_days: int
    days_of_cover: float
    urgency: Literal["CRITICAL", "HIGH", "MEDIUM", "LOW"]
    trend_direction: Literal["growing", "stable", "declining"]
    trend_percent: float
    seasonality_detected: bool
    outliers_removed: int
    estimated_lost_demand: float
    status: Literal["DRAFT", "ADJUSTED", "APPROVED"]
    explanation: str
    metadata: dict[str, Any] = {}

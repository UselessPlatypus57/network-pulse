"""Pydantic request/response schemas (the public API contract)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models import SiteStatus


class SiteUpsert(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    region: str = Field(default="", max_length=64)
    technology: str = Field(default="5G", max_length=16)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


class SiteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    region: str
    technology: str
    latitude: float
    longitude: float
    status: SiteStatus
    status_since: datetime
    reasons: list[str] = Field(default_factory=list, validation_alias="status_reasons")
    pending_status: SiteStatus | None = Field(
        default=None, description="Status the site is trending toward but has not yet been confirmed."
    )
    pending_count: int = 0
    last_seen_at: datetime | None
    window_latency_ms: float | None
    window_packet_loss_pct: float | None
    window_availability_pct: float | None

    @field_validator("reasons", mode="before")
    @classmethod
    def _split_reasons(cls, v: object) -> object:
        if isinstance(v, str):
            return [r for r in v.split("; ") if r]
        return v


class MetricIn(BaseModel):
    site_id: str = Field(min_length=1, max_length=32)
    ts: datetime | None = Field(default=None, description="Sample time (UTC). Defaults to server receive time.")
    latency_ms: float = Field(ge=0, le=60_000)
    packet_loss_pct: float = Field(ge=0, le=100)
    availability_pct: float = Field(ge=0, le=100)


class MetricBatch(BaseModel):
    samples: list[MetricIn] = Field(min_length=1, max_length=5_000)


class IngestResult(BaseModel):
    accepted: int
    rejected: int
    unknown_sites: list[str]


class MetricPoint(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    ts: datetime
    latency_ms: float
    packet_loss_pct: float
    availability_pct: float

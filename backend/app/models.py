"""Data model.

- Site:         a cell site and its *current* health state (denormalized so the
                dashboard can list every site with one cheap query).
- MetricSample: raw time-series readings reported for a site.
- Alert:        one incident per site, opened when it goes unhealthy and
                resolved when it recovers.
"""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import Enum, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, UTCDateTime, utcnow


class SiteStatus(str, enum.Enum):
    UNKNOWN = "unknown"  # registered, never reported
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    OFFLINE = "offline"


class AlertSeverity(str, enum.Enum):
    WARNING = "warning"  # site degraded
    CRITICAL = "critical"  # site offline


class AlertState(str, enum.Enum):
    OPEN = "open"
    RESOLVED = "resolved"


def _enum(e: type[enum.Enum], name: str) -> Enum:
    # Store enum *values* as plain strings: readable in psql and portable.
    return Enum(e, name=name, native_enum=False, values_callable=lambda x: [m.value for m in x])


class Site(Base):
    __tablename__ = "sites"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    region: Mapped[str] = mapped_column(String(64), default="")
    technology: Mapped[str] = mapped_column(String(16), default="5G")
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    # Current health (written by the evaluator)
    status: Mapped[SiteStatus] = mapped_column(_enum(SiteStatus, "site_status"), default=SiteStatus.UNKNOWN)
    status_since: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    status_reasons: Mapped[str] = mapped_column(Text, default="")  # "; "-joined

    # Hysteresis bookkeeping: the status we are *considering* moving to.
    pending_status: Mapped[SiteStatus | None] = mapped_column(_enum(SiteStatus, "site_status"), nullable=True)
    pending_count: Mapped[int] = mapped_column(Integer, default=0)

    # Rolling-window aggregates from the last evaluation
    last_seen_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    avg_latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_packet_loss_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_availability_pct: Mapped[float | None] = mapped_column(Float, nullable=True)

    samples: Mapped[list[MetricSample]] = relationship(back_populates="site", cascade="all, delete-orphan")
    alerts: Mapped[list[Alert]] = relationship(back_populates="site", cascade="all, delete-orphan")


class MetricSample(Base):
    __tablename__ = "metric_samples"
    __table_args__ = (Index("ix_metric_samples_site_ts", "site_id", "ts"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    site_id: Mapped[str] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"))
    ts: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    latency_ms: Mapped[float] = mapped_column(Float)
    packet_loss_pct: Mapped[float] = mapped_column(Float)
    availability_pct: Mapped[float] = mapped_column(Float)

    site: Mapped[Site] = relationship(back_populates="samples")


class Alert(Base):
    __tablename__ = "alerts"
    __table_args__ = (Index("ix_alerts_site_state", "site_id", "state"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    site_id: Mapped[str] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"))
    severity: Mapped[AlertSeverity] = mapped_column(_enum(AlertSeverity, "alert_severity"))
    state: Mapped[AlertState] = mapped_column(_enum(AlertState, "alert_state"), default=AlertState.OPEN)
    reason: Mapped[str] = mapped_column(Text, default="")
    opened_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    site: Mapped[Site] = relationship(back_populates="alerts")

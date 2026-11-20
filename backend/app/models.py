"""Data model.

- Site:         a cell site and its *current* health state (denormalized so the
                dashboard can list every site with one cheap query).
- MetricSample: raw time-series readings reported for a site.
- Alert:        one incident per site, opened when it goes unhealthy and
                resolved when it recovers.
- StatusEvent:  append-only log of status transitions (uptime / MTTR history).
"""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import Enum, Float, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, UTCDateTime, utcnow


class SiteStatus(enum.StrEnum):
    UNKNOWN = "unknown"  # registered, never reported
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    OFFLINE = "offline"
    MAINTENANCE = "maintenance"  # planned work: no alerts, excluded from uptime


class AlertSeverity(enum.StrEnum):
    WARNING = "warning"  # site degraded
    CRITICAL = "critical"  # site offline


class AlertState(enum.StrEnum):
    OPEN = "open"
    RESOLVED = "resolved"


class FaultKind(enum.StrEnum):
    LATENCY = "latency"  # congested backhaul: latency climbs to several hundred ms
    PACKET_LOSS = "packet_loss"  # radio interference: heavy loss, reduced availability
    OUTAGE = "outage"  # site stops reporting entirely (power/fiber cut)
    FLAP = "flap"  # brief intermittent spikes -- should NOT raise an alert


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

    # Planned maintenance window. Written only by the API, never by the evaluator
    # (whose bulk UPDATE would otherwise overwrite a window started mid-tick).
    maintenance_until: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    # Hysteresis bookkeeping: the status we are *considering* moving to.
    pending_status: Mapped[SiteStatus | None] = mapped_column(_enum(SiteStatus, "site_status"), nullable=True)
    pending_count: Mapped[int] = mapped_column(Integer, default=0)

    # Rolling-window aggregates from the last evaluation
    last_seen_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    window_latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    window_packet_loss_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    window_availability_pct: Mapped[float | None] = mapped_column(Float, nullable=True)

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
    __table_args__ = (
        Index("ix_alerts_site_state", "site_id", "state"),
        # The "one open alert per site" invariant, enforced by the database rather
        # than trusted to application code: even a brief overlap between two
        # evaluators during a leader handover can't open a duplicate page.
        Index(
            "uq_alerts_one_open_per_site", "site_id", unique=True,
            postgresql_where=text("state = 'open'"), sqlite_where=text("state = 'open'"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    site_id: Mapped[str] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"))
    severity: Mapped[AlertSeverity] = mapped_column(_enum(AlertSeverity, "alert_severity"))
    state: Mapped[AlertState] = mapped_column(_enum(AlertState, "alert_state"), default=AlertState.OPEN)
    reason: Mapped[str] = mapped_column(Text, default="")
    opened_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    site: Mapped[Site] = relationship(back_populates="alerts")


class ChaosFault(Base):
    """An injected fault the simulator should apply to a site until it expires."""

    __tablename__ = "chaos_faults"

    site_id: Mapped[str] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"), primary_key=True)
    fault: Mapped[FaultKind] = mapped_column(_enum(FaultKind, "fault_kind"))
    started_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)


class StatusEvent(Base):
    """Append-only log of status transitions: the history behind uptime/MTTR.

    ``sites`` holds the *current* state; this table holds how it got there.
    One row per confirmed transition (not per sample), so it stays tiny: a
    site that never changes status writes nothing after its first reading.
    """

    __tablename__ = "status_events"
    __table_args__ = (Index("ix_status_events_site_at", "site_id", "at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    site_id: Mapped[str] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"))
    at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    previous: Mapped[SiteStatus] = mapped_column(_enum(SiteStatus, "site_status"))
    status: Mapped[SiteStatus] = mapped_column(_enum(SiteStatus, "site_status"))


class EvaluatorHeartbeat(Base):
    """A single row, written each tick by whichever replica currently leads.

    Liveness has to live in the database, not in process memory: with several
    replicas behind a load balancer, the replica answering /health/summary is
    usually *not* the one evaluating.
    """

    __tablename__ = "evaluator_heartbeat"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)  # always 1
    leader: Mapped[str] = mapped_column(String(128))
    leader_since: Mapped[datetime] = mapped_column(UTCDateTime)
    last_run_at: Mapped[datetime] = mapped_column(UTCDateTime)
    last_duration_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

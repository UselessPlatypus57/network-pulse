"""Runtime configuration, read from environment variables.

Every knob that affects how the monitor decides "healthy vs. unhealthy" lives
here so it can be tuned per environment without a code change.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    return float(raw) if raw not in (None, "") else default


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    return int(raw) if raw not in (None, "") else default


@dataclass(frozen=True)
class Thresholds:
    """Metric limits, evaluated against a rolling-window average."""

    latency_degraded_ms: float = 150.0
    packet_loss_degraded_pct: float = 2.0
    availability_degraded_pct: float = 99.0

    packet_loss_offline_pct: float = 50.0
    availability_offline_pct: float = 50.0

    @classmethod
    def from_env(cls) -> Thresholds:
        return cls(
            latency_degraded_ms=_env_float("LATENCY_DEGRADED_MS", cls.latency_degraded_ms),
            packet_loss_degraded_pct=_env_float("PACKET_LOSS_DEGRADED_PCT", cls.packet_loss_degraded_pct),
            availability_degraded_pct=_env_float("AVAILABILITY_DEGRADED_PCT", cls.availability_degraded_pct),
            packet_loss_offline_pct=_env_float("PACKET_LOSS_OFFLINE_PCT", cls.packet_loss_offline_pct),
            availability_offline_pct=_env_float("AVAILABILITY_OFFLINE_PCT", cls.availability_offline_pct),
        )


@dataclass(frozen=True)
class Settings:
    database_url: str = "sqlite:///./network_pulse.db"

    # Health evaluation
    evaluation_interval_s: float = 5.0
    window_s: int = 30
    stale_after_s: int = 30
    trip_count: int = 3  # consecutive bad evaluations before a site is marked worse
    clear_count: int = 4  # consecutive good evaluations before a site is marked better
    retention_hours: int = 24

    # Alerting
    webhook_url: str | None = None

    # CORS (comma-separated origins) for the dev dashboard
    cors_origins: tuple[str, ...] = ("http://localhost:5173",)

    thresholds: Thresholds = field(default_factory=Thresholds)

    @classmethod
    def from_env(cls) -> Settings:
        origins = os.getenv("CORS_ORIGINS")
        return cls(
            database_url=os.getenv("DATABASE_URL", cls.database_url),
            evaluation_interval_s=_env_float("EVALUATION_INTERVAL_S", cls.evaluation_interval_s),
            window_s=_env_int("WINDOW_S", cls.window_s),
            stale_after_s=_env_int("STALE_AFTER_S", cls.stale_after_s),
            trip_count=_env_int("TRIP_COUNT", cls.trip_count),
            clear_count=_env_int("CLEAR_COUNT", cls.clear_count),
            retention_hours=_env_int("RETENTION_HOURS", cls.retention_hours),
            webhook_url=os.getenv("WEBHOOK_URL") or None,
            cors_origins=tuple(o.strip() for o in origins.split(",") if o.strip())
            if origins
            else cls.cors_origins,
            thresholds=Thresholds.from_env(),
        )


settings = Settings.from_env()

from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db, utcnow
from app.evaluator import monitor_state
from app.leader import INSTANCE_ID
from app.models import Alert, AlertState, EvaluatorHeartbeat, Site, SiteStatus
from app.schemas import SiteOut

router = APIRouter(prefix="/api/v1/health", tags=["health"])


class EvaluatorStatus(BaseModel):
    running: bool
    last_run_at: datetime | None
    last_duration_ms: float | None
    last_error: str | None
    interval_s: float
    leader: str | None = None
    leader_since: datetime | None = None
    served_by: str
    served_by_role: str


class HealthSummary(BaseModel):
    total: int
    counts: dict[SiteStatus, int]
    open_alerts: int
    evaluator: EvaluatorStatus
    generated_at: datetime


def evaluator_status(db: Session) -> EvaluatorStatus:
    """Read liveness from the shared heartbeat row, not this process's memory:
    behind a load balancer the replica answering is usually not the leader."""
    hb = db.get(EvaluatorHeartbeat, 1)
    last = hb.last_run_at if hb else None
    # "running" = some replica evaluated recently. 3 missed intervals means stuck or leaderless.
    running = last is not None and (utcnow() - last).total_seconds() < settings.evaluation_interval_s * 3
    return EvaluatorStatus(
        running=running and not (hb and hb.last_error),
        last_run_at=last,
        last_duration_ms=hb.last_duration_ms if hb else None,
        last_error=hb.last_error if hb else None,
        interval_s=settings.evaluation_interval_s,
        leader=hb.leader if hb else None,
        leader_since=hb.leader_since if hb else None,
        served_by=INSTANCE_ID,
        served_by_role=monitor_state.role,
    )


@router.get("/summary", response_model=HealthSummary)
def summary(db: Session = Depends(get_db)) -> HealthSummary:
    """Fleet-wide counts by status, plus whether the evaluator itself is alive."""
    counts = {s: 0 for s in SiteStatus}
    for status, n in db.execute(select(Site.status, func.count()).group_by(Site.status)):
        counts[status] = n
    return HealthSummary(
        total=sum(counts.values()),
        counts=counts,
        open_alerts=db.scalar(select(func.count()).select_from(Alert).where(Alert.state == AlertState.OPEN)) or 0,
        evaluator=evaluator_status(db),
        generated_at=utcnow(),
    )


@router.get("/unhealthy", response_model=list[SiteOut])
def unhealthy_sites(db: Session = Depends(get_db)) -> list[Site]:
    """Every site currently DEGRADED or OFFLINE, worst and longest-running first."""
    severity = case((Site.status == SiteStatus.OFFLINE, 0), else_=1)
    stmt = (
        select(Site)
        .where(Site.status.in_([SiteStatus.DEGRADED, SiteStatus.OFFLINE]))
        .order_by(severity, Site.status_since)
    )
    return list(db.scalars(stmt))


class DetectionConfig(BaseModel):
    """The rules the evaluator applies, so clients can draw thresholds instead of hard-coding them."""

    latency_degraded_ms: float
    packet_loss_degraded_pct: float
    availability_degraded_pct: float
    packet_loss_offline_pct: float
    availability_offline_pct: float
    window_s: int
    min_samples: int
    trip_count: int
    clear_count: int
    stale_after_s: int
    evaluation_interval_s: float


@router.get("/config", response_model=DetectionConfig)
def detection_config() -> DetectionConfig:
    t = settings.thresholds
    return DetectionConfig(
        latency_degraded_ms=t.latency_degraded_ms,
        packet_loss_degraded_pct=t.packet_loss_degraded_pct,
        availability_degraded_pct=t.availability_degraded_pct,
        packet_loss_offline_pct=t.packet_loss_offline_pct,
        availability_offline_pct=t.availability_offline_pct,
        window_s=settings.window_s,
        min_samples=settings.min_samples,
        trip_count=settings.trip_count,
        clear_count=settings.clear_count,
        stale_after_s=settings.stale_after_s,
        evaluation_interval_s=settings.evaluation_interval_s,
    )

from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db, utcnow
from app.evaluator import monitor_state
from app.models import Site, SiteStatus
from app.schemas import SiteOut

router = APIRouter(prefix="/api/v1/health", tags=["health"])


class EvaluatorStatus(BaseModel):
    running: bool
    last_run_at: datetime | None
    last_duration_ms: float | None
    last_error: str | None
    interval_s: float


class HealthSummary(BaseModel):
    total: int
    counts: dict[SiteStatus, int]
    evaluator: EvaluatorStatus
    generated_at: datetime


def evaluator_status() -> EvaluatorStatus:
    last = monitor_state.last_run_at
    # "running" = evaluated recently. 3 missed intervals means the loop is stuck.
    running = last is not None and (utcnow() - last).total_seconds() < settings.evaluation_interval_s * 3
    return EvaluatorStatus(
        running=running and monitor_state.last_error is None,
        last_run_at=last,
        last_duration_ms=monitor_state.last_duration_ms,
        last_error=monitor_state.last_error,
        interval_s=settings.evaluation_interval_s,
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
        evaluator=evaluator_status(),
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

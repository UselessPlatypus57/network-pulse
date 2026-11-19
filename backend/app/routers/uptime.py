"""Uptime / MTTR endpoints, built on the status_events log."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.db import get_db, utcnow
from app.models import Site, SiteStatus, StatusEvent
from app.uptime import UptimeReport, aggregate, compute_uptime

router = APIRouter(tags=["uptime"])

HOURS = Query(24, ge=1, le=24 * 7, description="Window length in hours (max 7 days).")


class UptimeOut(BaseModel):
    site_id: str
    hours: int
    window_start: datetime
    window_end: datetime
    observed_s: float
    seconds_by_status: dict[SiteStatus, float]
    available_pct: float | None
    healthy_pct: float | None
    incidents: int
    resolved_incidents: int
    mttr_s: float | None
    ongoing_incident_s: float | None


class FleetUptimeOut(BaseModel):
    hours: int
    window_start: datetime
    window_end: datetime
    sites: int
    observed_s: float
    available_pct: float | None
    healthy_pct: float | None
    incidents: int
    resolved_incidents: int
    mttr_s: float | None


def _r(v: float | None, digits: int) -> float | None:
    return None if v is None else round(v, digits)


def load_reports(db: Session, start: datetime, end: datetime, site_id: str | None = None) -> dict[str, UptimeReport]:
    """Build an UptimeReport per site with two queries, regardless of fleet size."""
    # Status in force at window start = the last transition before it, per site.
    last_before = (
        select(StatusEvent.site_id, func.max(StatusEvent.at).label("at"))
        .where(StatusEvent.at < start)
        .group_by(StatusEvent.site_id)
    )
    if site_id:
        last_before = last_before.where(StatusEvent.site_id == site_id)
    last_before = last_before.subquery()
    initial = dict(
        db.execute(
            select(StatusEvent.site_id, StatusEvent.status).join(
                last_before,
                and_(StatusEvent.site_id == last_before.c.site_id, StatusEvent.at == last_before.c.at),
            )
        ).all()
    )

    in_window = select(StatusEvent.site_id, StatusEvent.at, StatusEvent.status).where(
        StatusEvent.at >= start, StatusEvent.at < end
    )
    if site_id:
        in_window = in_window.where(StatusEvent.site_id == site_id)
    events: dict[str, list[tuple[datetime, SiteStatus]]] = defaultdict(list)
    for sid, at, status in db.execute(in_window.order_by(StatusEvent.site_id, StatusEvent.at, StatusEvent.id)):
        events[sid].append((at, status))

    site_ids = [site_id] if site_id else list(db.scalars(select(Site.id)))
    return {sid: compute_uptime(initial.get(sid), events.get(sid, []), start, end) for sid in site_ids}


@router.get("/api/v1/sites/{site_id}/uptime", response_model=UptimeOut)
def site_uptime(site_id: str, hours: int = HOURS, db: Session = Depends(get_db)) -> UptimeOut:
    """Time-weighted availability, incidents and MTTR for one site."""
    if db.get(Site, site_id) is None:
        raise HTTPException(status_code=404, detail=f"site {site_id!r} not found")
    end = utcnow()
    start = end - timedelta(hours=hours)
    r = load_reports(db, start, end, site_id)[site_id]
    return UptimeOut(
        site_id=site_id,
        hours=hours,
        window_start=start,
        window_end=end,
        observed_s=round(r.observed_s, 1),
        seconds_by_status={s: round(v, 1) for s, v in r.seconds_by_status.items()},
        available_pct=_r(r.available_pct, 3),
        healthy_pct=_r(r.healthy_pct, 3),
        incidents=r.incidents,
        resolved_incidents=r.resolved_incidents,
        mttr_s=_r(r.mttr_s, 1),
        ongoing_incident_s=_r(r.ongoing_incident_s, 1),
    )


@router.get("/api/v1/health/uptime", response_model=FleetUptimeOut)
def fleet_uptime(hours: int = HOURS, db: Session = Depends(get_db)) -> FleetUptimeOut:
    """Fleet-wide availability and MTTR, weighted by each site's observed time."""
    end = utcnow()
    start = end - timedelta(hours=hours)
    f = aggregate(list(load_reports(db, start, end).values()))
    return FleetUptimeOut(
        hours=hours,
        window_start=start,
        window_end=end,
        sites=f.sites,
        observed_s=round(f.observed_s, 1),
        available_pct=_r(f.available_pct, 3),
        healthy_pct=_r(f.healthy_pct, 3),
        incidents=f.incidents,
        resolved_incidents=f.resolved_incidents,
        mttr_s=_r(f.mttr_s, 1),
    )

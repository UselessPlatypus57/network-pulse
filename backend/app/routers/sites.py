from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db, utcnow
from app.models import MetricSample, Site, SiteStatus
from app.schemas import MetricPoint, SiteOut, SiteUpsert

router = APIRouter(prefix="/api/v1/sites", tags=["sites"])


def _get_site_or_404(db: Session, site_id: str) -> Site:
    site = db.get(Site, site_id)
    if site is None:
        raise HTTPException(status_code=404, detail=f"site {site_id!r} not found")
    return site


@router.get("", response_model=list[SiteOut])
def list_sites(
    status: SiteStatus | None = None,
    region: str | None = None,
    db: Session = Depends(get_db),
) -> list[Site]:
    stmt = select(Site).order_by(Site.id)
    if status is not None:
        stmt = stmt.where(Site.status == status)
    if region:
        stmt = stmt.where(Site.region == region)
    return list(db.scalars(stmt))


@router.get("/{site_id}", response_model=SiteOut)
def get_site(site_id: str, db: Session = Depends(get_db)) -> Site:
    return _get_site_or_404(db, site_id)


@router.put("/{site_id}", response_model=SiteOut)
def upsert_site(site_id: str, body: SiteUpsert, db: Session = Depends(get_db)) -> Site:
    """Register a site, or update its descriptive fields. Health state is untouched."""
    site = db.get(Site, site_id)
    if site is None:
        site = Site(id=site_id, status=SiteStatus.UNKNOWN, status_since=utcnow())
        db.add(site)
    for field, value in body.model_dump().items():
        setattr(site, field, value)
    db.commit()
    db.refresh(site)
    return site


class MaintenanceIn(BaseModel):
    minutes: int = Field(60, ge=1, le=24 * 60, description="Window length, starting now.")


@router.put("/{site_id}/maintenance", response_model=SiteOut)
def start_maintenance(site_id: str, body: MaintenanceIn, db: Session = Depends(get_db)) -> Site:
    """Start (or extend/replace) a planned maintenance window.

    Only ``maintenance_until`` is written; the evaluator applies the MAINTENANCE
    status on its next tick, so status keeps a single writer.
    """
    site = _get_site_or_404(db, site_id)
    site.maintenance_until = utcnow() + timedelta(minutes=body.minutes)
    db.commit()
    db.refresh(site)
    return site


@router.delete("/{site_id}/maintenance", response_model=SiteOut)
def end_maintenance(site_id: str, db: Session = Depends(get_db)) -> Site:
    """End maintenance now. The site is re-judged from scratch on the next tick."""
    site = _get_site_or_404(db, site_id)
    now = utcnow()
    if site.maintenance_until is not None and site.maintenance_until > now:
        site.maintenance_until = now
        db.commit()
        db.refresh(site)
    return site


@router.get("/{site_id}/metrics", response_model=list[MetricPoint])
def site_metrics(
    site_id: str,
    minutes: int = Query(15, ge=1, le=24 * 60),
    db: Session = Depends(get_db),
) -> list[MetricSample]:
    """Raw samples for one site over the last `minutes`, oldest first."""
    _get_site_or_404(db, site_id)
    since = utcnow() - timedelta(minutes=minutes)
    stmt = (
        select(MetricSample)
        .where(MetricSample.site_id == site_id, MetricSample.ts >= since)
        .order_by(MetricSample.ts)
    )
    return list(db.scalars(stmt))

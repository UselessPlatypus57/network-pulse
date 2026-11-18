"""Chaos / fault-injection API.

Lets an operator (or the dashboard's demo controls) ask the traffic simulator
to break a site on purpose. The API only *records* the fault; the simulator
polls ``GET /api/v1/chaos`` and changes what it reports. Keeping the monitor
itself unaware of chaos means detection is tested exactly as in production.
"""

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db import get_db, utcnow
from app.models import ChaosFault, FaultKind, Site

router = APIRouter(prefix="/api/v1/chaos", tags=["chaos"])


class FaultIn(BaseModel):
    fault: FaultKind
    duration_s: int = Field(120, ge=10, le=3600)


class FaultOut(BaseModel):
    site_id: str
    fault: FaultKind
    started_at: datetime
    expires_at: datetime


def _out(f: ChaosFault) -> FaultOut:
    return FaultOut(site_id=f.site_id, fault=f.fault, started_at=f.started_at, expires_at=f.expires_at)


@router.get("", response_model=list[FaultOut])
def active_faults(db: Session = Depends(get_db)) -> list[FaultOut]:
    now = utcnow()
    db.execute(delete(ChaosFault).where(ChaosFault.expires_at <= now))
    db.commit()
    return [_out(f) for f in db.scalars(select(ChaosFault).order_by(ChaosFault.started_at))]


@router.put("/{site_id}", response_model=FaultOut)
def inject_fault(site_id: str, body: FaultIn, db: Session = Depends(get_db)) -> FaultOut:
    """Start (or replace) a fault on a site for ``duration_s`` seconds."""
    if db.get(Site, site_id) is None:
        raise HTTPException(status_code=404, detail=f"site {site_id!r} not found")
    now = utcnow()
    fault = db.get(ChaosFault, site_id) or ChaosFault(site_id=site_id)
    fault.fault = body.fault
    fault.started_at = now
    fault.expires_at = now + timedelta(seconds=body.duration_s)
    db.add(fault)
    db.commit()
    return _out(fault)


@router.delete("/{site_id}", status_code=status.HTTP_204_NO_CONTENT)
def clear_fault(site_id: str, db: Session = Depends(get_db)) -> Response:
    db.execute(delete(ChaosFault).where(ChaosFault.site_id == site_id))
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)

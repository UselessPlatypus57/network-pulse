from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.db import get_db
from app.models import Alert, AlertSeverity, AlertState

router = APIRouter(prefix="/api/v1/alerts", tags=["alerts"])


class AlertOut(BaseModel):
    id: int
    site_id: str
    site_name: str
    severity: AlertSeverity
    state: AlertState
    reason: str
    opened_at: datetime
    updated_at: datetime
    resolved_at: datetime | None

    @classmethod
    def of(cls, a: Alert) -> "AlertOut":
        return cls(
            id=a.id, site_id=a.site_id, site_name=a.site.name, severity=a.severity, state=a.state,
            reason=a.reason, opened_at=a.opened_at, updated_at=a.updated_at, resolved_at=a.resolved_at,
        )


@router.get("", response_model=list[AlertOut])
def list_alerts(
    state: AlertState | None = None,
    site_id: str | None = None,
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
) -> list[AlertOut]:
    """Most recent alerts first. Filter with ?state=open for active incidents."""
    stmt = select(Alert).options(joinedload(Alert.site)).order_by(Alert.opened_at.desc(), Alert.id.desc())
    if state is not None:
        stmt = stmt.where(Alert.state == state)
    if site_id:
        stmt = stmt.where(Alert.site_id == site_id)
    return [AlertOut.of(a) for a in db.scalars(stmt.limit(limit))]


@router.get("/{alert_id}", response_model=AlertOut)
def get_alert(alert_id: int, db: Session = Depends(get_db)) -> AlertOut:
    alert = db.get(Alert, alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="alert not found")
    return AlertOut.of(alert)

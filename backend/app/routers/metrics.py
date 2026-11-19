from datetime import datetime

from fastapi import APIRouter, Depends, status
from sqlalchemy import bindparam, case, or_, select, update
from sqlalchemy.orm import Session

from app import observability as obs
from app.db import UTCDateTime, get_db, utcnow
from app.models import MetricSample, Site
from app.schemas import IngestResult, MetricBatch

router = APIRouter(prefix="/api/v1/metrics", tags=["metrics"])

_sites = Site.__table__
# Move last_seen_at forward only, in SQL: no read-modify-write race between
# concurrent batches, and an older (backfilled) sample can never move it back.
_bump_last_seen = (
    update(_sites)
    .where(_sites.c.id == bindparam("b_id"))
    .values(
        last_seen_at=case(
            (
                or_(_sites.c.last_seen_at.is_(None), _sites.c.last_seen_at < bindparam("b_ts", type_=UTCDateTime())),
                bindparam("b_ts", type_=UTCDateTime()),
            ),
            else_=_sites.c.last_seen_at,
        )
    )
)


@router.post("", response_model=IngestResult, status_code=status.HTTP_202_ACCEPTED)
def ingest_metrics(batch: MetricBatch, db: Session = Depends(get_db)) -> IngestResult:
    """Accept a batch of health samples from probes/collectors.

    Samples for unregistered sites are rejected (and reported back) rather than
    failing the whole batch, so one bad collector config can't block the rest.
    Health is *not* evaluated here -- ingestion stays fast and the evaluator
    decides status on its own schedule.
    """
    now = utcnow()
    known = set(db.scalars(select(Site.id).where(Site.id.in_({s.site_id for s in batch.samples}))))

    unknown: set[str] = set()
    rows: list[MetricSample] = []
    latest: dict[str, datetime] = {}
    for sample in batch.samples:
        if sample.site_id not in known:
            unknown.add(sample.site_id)
            continue
        # Don't trust collector clocks that run ahead of ours.
        ts = min(sample.ts or now, now)
        rows.append(
            MetricSample(
                site_id=sample.site_id,
                ts=ts,
                latency_ms=sample.latency_ms,
                packet_loss_pct=sample.packet_loss_pct,
                availability_pct=sample.availability_pct,
            )
        )
        if sample.site_id not in latest or ts > latest[sample.site_id]:
            latest[sample.site_id] = ts

    if latest:
        # Ascending id order on purpose: the evaluator also locks `sites` rows in
        # id order, and a single global lock order is what makes deadlocks
        # impossible. (Unordered, they deadlocked under load at 10k sites.)
        db.execute(_bump_last_seen, [{"b_id": sid, "b_ts": ts} for sid, ts in sorted(latest.items())])
    db.add_all(rows)
    db.commit()

    accepted = len(rows)
    obs.SAMPLES_INGESTED.inc(accepted)
    obs.SAMPLES_REJECTED.inc(len(batch.samples) - accepted)
    return IngestResult(
        accepted=accepted,
        rejected=len(batch.samples) - accepted,
        unknown_sites=sorted(unknown),
    )

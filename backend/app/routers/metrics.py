from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import observability as obs
from app.db import get_db, utcnow
from app.models import MetricSample, Site
from app.schemas import IngestResult, MetricBatch

router = APIRouter(prefix="/api/v1/metrics", tags=["metrics"])


@router.post("", response_model=IngestResult, status_code=status.HTTP_202_ACCEPTED)
def ingest_metrics(batch: MetricBatch, db: Session = Depends(get_db)) -> IngestResult:
    """Accept a batch of health samples from probes/collectors.

    Samples for unregistered sites are rejected (and reported back) rather than
    failing the whole batch, so one bad collector config can't block the rest.
    Health is *not* evaluated here — ingestion stays fast and the evaluator
    decides status on its own schedule.
    """
    now = utcnow()
    site_ids = {s.site_id for s in batch.samples}
    sites = {s.id: s for s in db.scalars(select(Site).where(Site.id.in_(site_ids)))}

    accepted = 0
    unknown: set[str] = set()
    rows: list[MetricSample] = []
    for sample in batch.samples:
        site = sites.get(sample.site_id)
        if site is None:
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
        if site.last_seen_at is None or ts > site.last_seen_at:
            site.last_seen_at = ts
        accepted += 1

    db.add_all(rows)
    db.commit()
    obs.SAMPLES_INGESTED.inc(accepted)
    obs.SAMPLES_REJECTED.inc(len(batch.samples) - accepted)
    return IngestResult(
        accepted=accepted,
        rejected=len(batch.samples) - accepted,
        unknown_sites=sorted(unknown),
    )

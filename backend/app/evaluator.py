"""Periodic health evaluation.

Runs every ``evaluation_interval_s`` seconds: aggregates each site's recent
samples, runs the classifier + state machine, and persists the result.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from statistics import median_high, median_low

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app import observability as obs
from app.alerts import Notifier, make_notifier, process_transitions
from app.config import Settings, settings
from app.db import SessionLocal, utcnow
from app.health import Transition, WindowStats, classify, step
from app.models import Alert, AlertSeverity, AlertState, MetricSample, Site, SiteStatus, StatusEvent

log = logging.getLogger("network_pulse.evaluator")


@dataclass
class MonitorState:
    """Self-observability: lets the API (and the dashboard) tell whether the
    evaluator is actually running, not just whether the web process is up."""

    started_at: datetime = field(default_factory=utcnow)
    last_run_at: datetime | None = None
    last_duration_ms: float | None = None
    last_error: str | None = None
    runs: int = 0


monitor_state = MonitorState()
default_notifier: Notifier = make_notifier(settings.webhook_url)


def window_stats(db: Session, since: datetime) -> dict[str, WindowStats]:
    """Per-site *strict-majority median* of each metric over the window.

    Median rather than mean: a single 2-second latency spike drags a 6-sample
    mean over the threshold for the whole window (and long enough to trip the
    hysteresis), but cannot move the median at all.

    For even-sized windows the textbook median averages the two middle values,
    so a window that is exactly half spikes reads as a breach. Instead we take
    the *optimistic* middle value -- ``median_low`` for metrics where higher is
    worse (latency, loss) and ``median_high`` for availability -- which means a
    breach must be present in a strict majority of samples to count.
    """
    rows = db.execute(
        select(
            MetricSample.site_id,
            MetricSample.latency_ms,
            MetricSample.packet_loss_pct,
            MetricSample.availability_pct,
        ).where(MetricSample.ts >= since)
    ).all()

    grouped: dict[str, list[tuple[float, float, float]]] = defaultdict(list)
    for site_id, lat, loss, avail in rows:
        grouped[site_id].append((lat, loss, avail))

    return {
        site_id: WindowStats(
            samples=len(vals),
            latency_ms=median_low([v[0] for v in vals]),
            packet_loss_pct=median_low([v[1] for v in vals]),
            availability_pct=median_high([v[2] for v in vals]),
        )
        for site_id, vals in grouped.items()
    }


def evaluate_all(
    db: Session, cfg: Settings, now: datetime | None = None, listening_since: datetime | None = None
) -> list[Transition]:
    """Evaluate every site once and persist the result in a single bulk UPDATE.

    Sites are read as plain rows rather than ORM objects and written back with
    one executemany. Profiling at 10,040 sites showed the per-object ORM flush
    (one UPDATE round-trip per site) was ~79% of each tick; the medians were 3%.
    """
    now = now or utcnow()
    stats_by_site = window_stats(db, now - timedelta(seconds=cfg.window_s))
    transitions: list[Transition] = []
    updates: list[dict] = []

    rows = db.execute(
        select(
            Site.id, Site.status, Site.status_since, Site.pending_status, Site.pending_count, Site.last_seen_at,
            Site.window_latency_ms, Site.window_packet_loss_pct, Site.window_availability_pct,
        )
    ).all()

    for site in rows:
        stats = stats_by_site.get(site.id)
        verdict = classify(stats, site.last_seen_at, now, cfg, listening_since)
        decision = step(site.status, site.pending_status, site.pending_count, verdict, cfg)

        if decision.changed:
            transitions.append(Transition(site.id, site.status, decision.status, verdict.reasons, now))
            # Same transaction as the status change: history can never disagree with current state.
            db.add(StatusEvent(site_id=site.id, at=now, previous=site.status, status=decision.status))
            log.info("site %s: %s -> %s (%s)", site.id, site.status.value, decision.status.value,
                     "; ".join(verdict.reasons) or "ok")

        # Every row carries the same keys, so SQLAlchemy sends one executemany batch.
        updates.append({
            "id": site.id,
            "status": decision.status,
            "status_since": now if decision.changed else site.status_since,
            "status_reasons": "; ".join(verdict.reasons),
            "pending_status": decision.pending_status,
            "pending_count": decision.pending_count,
            "window_latency_ms": round(stats.latency_ms, 2) if stats else site.window_latency_ms,
            "window_packet_loss_pct": round(stats.packet_loss_pct, 3) if stats else site.window_packet_loss_pct,
            "window_availability_pct": round(stats.availability_pct, 3) if stats else site.window_availability_pct,
        })

    if updates:
        db.execute(update(Site), updates)  # ORM bulk UPDATE by primary key
    db.commit()
    # Bulk UPDATE bypasses the identity map; drop any Site objects this session
    # already holds so later reads (alerts, callers, tests) see the new state.
    db.expire_all()
    return transitions


def prune_old_samples(db: Session, cfg: Settings, now: datetime | None = None) -> int:
    cutoff = (now or utcnow()) - timedelta(hours=cfg.retention_hours)
    result = db.execute(delete(MetricSample).where(MetricSample.ts < cutoff))
    db.commit()
    return result.rowcount or 0


def update_gauges(db: Session) -> None:
    counts = dict(db.execute(select(Site.status, func.count()).group_by(Site.status)).all())
    for status in SiteStatus:
        obs.SITES.labels(status.value).set(counts.get(status, 0))
    open_by_sev = dict(
        db.execute(
            select(Alert.severity, func.count()).where(Alert.state == AlertState.OPEN).group_by(Alert.severity)
        ).all()
    )
    for sev in AlertSeverity:
        obs.OPEN_ALERTS.labels(sev.value).set(open_by_sev.get(sev, 0))


def run_once(cfg: Settings = settings, notifier: Notifier | None = None) -> list[Transition]:
    started = time.perf_counter()
    with SessionLocal() as db:
        try:
            transitions = evaluate_all(db, cfg, listening_since=monitor_state.started_at)
            process_transitions(db, transitions, notifier or default_notifier)
            if monitor_state.runs % 60 == 0:
                prune_old_samples(db, cfg)
            update_gauges(db)
            for t in transitions:
                obs.TRANSITIONS.labels(t.current.value).inc()
            obs.EVALUATION_LAST_SUCCESS.set(time.time())
            monitor_state.last_error = None
            return transitions
        except Exception as exc:  # keep the loop alive; surface the error
            db.rollback()
            obs.EVALUATION_ERRORS.inc()
            monitor_state.last_error = f"{type(exc).__name__}: {exc}"
            log.exception("evaluation failed")
            return []
        finally:
            monitor_state.runs += 1
            monitor_state.last_run_at = utcnow()
            elapsed = time.perf_counter() - started
            obs.EVALUATION_DURATION.observe(elapsed)
            monitor_state.last_duration_ms = round(elapsed * 1000, 2)


async def evaluation_loop(cfg: Settings = settings) -> None:
    log.info("evaluator started (every %ss, window %ss)", cfg.evaluation_interval_s, cfg.window_s)
    while True:
        started = time.monotonic()
        await asyncio.to_thread(run_once, cfg)
        # Sleep only for what's left of the interval, so ticks stay on a fixed
        # cadence. (Sleeping a full interval *after* each run made the real period
        # interval + run time: 10 ticks/min instead of 12 at 10k sites.)
        await asyncio.sleep(max(0.0, cfg.evaluation_interval_s - (time.monotonic() - started)))

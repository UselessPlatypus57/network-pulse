"""Periodic health evaluation.

Runs every ``evaluation_interval_s`` seconds: aggregates each site's recent
samples, runs the classifier + state machine, and persists the result.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.alerts import Notifier, make_notifier, process_transitions
from app.config import Settings, settings
from app.db import SessionLocal, utcnow
from app.health import Transition, WindowStats, classify, step
from app.models import MetricSample, Site

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
    rows = db.execute(
        select(
            MetricSample.site_id,
            func.count(),
            func.avg(MetricSample.latency_ms),
            func.avg(MetricSample.packet_loss_pct),
            func.avg(MetricSample.availability_pct),
        )
        .where(MetricSample.ts >= since)
        .group_by(MetricSample.site_id)
    ).all()
    return {
        site_id: WindowStats(n, float(lat), float(loss), float(avail))
        for site_id, n, lat, loss, avail in rows
    }


def evaluate_all(db: Session, cfg: Settings, now: datetime | None = None) -> list[Transition]:
    now = now or utcnow()
    stats_by_site = window_stats(db, now - timedelta(seconds=cfg.window_s))
    transitions: list[Transition] = []

    for site in db.scalars(select(Site)):
        stats = stats_by_site.get(site.id)
        verdict = classify(stats, site.last_seen_at, now, cfg)
        decision = step(site.status, site.pending_status, site.pending_count, verdict, cfg)

        if stats is not None:
            site.avg_latency_ms = round(stats.avg_latency_ms, 2)
            site.avg_packet_loss_pct = round(stats.avg_packet_loss_pct, 3)
            site.avg_availability_pct = round(stats.avg_availability_pct, 3)
        site.status_reasons = "; ".join(verdict.reasons)
        site.pending_status = decision.pending_status
        site.pending_count = decision.pending_count

        if decision.changed:
            transitions.append(Transition(site.id, site.status, decision.status, verdict.reasons, now))
            log.info("site %s: %s -> %s (%s)", site.id, site.status.value, decision.status.value,
                     "; ".join(verdict.reasons) or "ok")
            site.status = decision.status
            site.status_since = now

    db.commit()
    return transitions


def prune_old_samples(db: Session, cfg: Settings, now: datetime | None = None) -> int:
    cutoff = (now or utcnow()) - timedelta(hours=cfg.retention_hours)
    result = db.execute(delete(MetricSample).where(MetricSample.ts < cutoff))
    db.commit()
    return result.rowcount or 0


def run_once(cfg: Settings = settings, notifier: Notifier | None = None) -> list[Transition]:
    started = time.perf_counter()
    with SessionLocal() as db:
        try:
            transitions = evaluate_all(db, cfg)
            process_transitions(db, transitions, notifier or default_notifier)
            if monitor_state.runs % 60 == 0:
                prune_old_samples(db, cfg)
            monitor_state.last_error = None
            return transitions
        except Exception as exc:  # keep the loop alive; surface the error
            db.rollback()
            monitor_state.last_error = f"{type(exc).__name__}: {exc}"
            log.exception("evaluation failed")
            return []
        finally:
            monitor_state.runs += 1
            monitor_state.last_run_at = utcnow()
            monitor_state.last_duration_ms = round((time.perf_counter() - started) * 1000, 2)


async def evaluation_loop(cfg: Settings = settings) -> None:
    log.info("evaluator started (every %ss, window %ss)", cfg.evaluation_interval_s, cfg.window_s)
    while True:
        await asyncio.to_thread(run_once, cfg)
        await asyncio.sleep(cfg.evaluation_interval_s)

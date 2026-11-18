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
from statistics import median

from sqlalchemy import delete, select
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
    """Per-site *median* of each metric over the window.

    Median rather than mean: a single 2-second latency spike drags a 6-sample
    mean over the threshold for the whole window (and long enough to trip the
    hysteresis), but cannot move the median at all. A genuine problem has to
    affect at least half the window's samples to count.
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
            latency_ms=median(v[0] for v in vals),
            packet_loss_pct=median(v[1] for v in vals),
            availability_pct=median(v[2] for v in vals),
        )
        for site_id, vals in grouped.items()
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
            site.window_latency_ms = round(stats.latency_ms, 2)
            site.window_packet_loss_pct = round(stats.packet_loss_pct, 3)
            site.window_availability_pct = round(stats.availability_pct, 3)
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

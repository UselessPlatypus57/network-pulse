"""Health classification and the hysteresis state machine.

Pure functions, no I/O — this is the part of the system that decides whether a
site is HEALTHY, DEGRADED or OFFLINE, so it is kept trivially unit-testable.

Two layers keep transient fluctuations from becoming alerts:

1. **Rolling window** — metrics are averaged over the last ``window_s`` seconds,
   so one bad sample barely moves the needle.
2. **Hysteresis** — a site must look worse for ``trip_count`` consecutive
   evaluations before it is marked worse, and better for ``clear_count``
   consecutive evaluations before it is marked better (asymmetric on purpose:
   quick to warn, slow to declare all-clear, which prevents flapping).

The one exception is a lost heartbeat: if a site has reported nothing for
``stale_after_s`` seconds it is OFFLINE immediately — the silence itself has
already been sustained for longer than the trip delay.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from app.config import Settings
from app.models import SiteStatus

RANK = {
    SiteStatus.UNKNOWN: -1,
    SiteStatus.HEALTHY: 0,
    SiteStatus.DEGRADED: 1,
    SiteStatus.OFFLINE: 2,
}


@dataclass(frozen=True)
class WindowStats:
    samples: int
    avg_latency_ms: float
    avg_packet_loss_pct: float
    avg_availability_pct: float


@dataclass(frozen=True)
class Verdict:
    """What the latest window of data says, before hysteresis is applied."""

    candidate: SiteStatus | None  # None = no evidence either way; hold state
    reasons: list[str] = field(default_factory=list)
    immediate: bool = False  # skip hysteresis (heartbeat loss)


@dataclass(frozen=True)
class Decision:
    status: SiteStatus
    pending_status: SiteStatus | None
    pending_count: int
    changed: bool


def classify(
    stats: WindowStats | None,
    last_seen_at: datetime | None,
    now: datetime,
    cfg: Settings,
) -> Verdict:
    if last_seen_at is None:
        return Verdict(SiteStatus.UNKNOWN)

    silent_for = (now - last_seen_at).total_seconds()
    if silent_for > cfg.stale_after_s:
        return Verdict(
            SiteStatus.OFFLINE,
            [f"no data for {int(silent_for)}s (heartbeat lost)"],
            immediate=True,
        )

    if stats is None or stats.samples == 0:
        return Verdict(None)

    t = cfg.thresholds
    offline: list[str] = []
    if stats.avg_availability_pct < t.availability_offline_pct:
        offline.append(f"availability {stats.avg_availability_pct:.1f}% < {t.availability_offline_pct:g}%")
    if stats.avg_packet_loss_pct >= t.packet_loss_offline_pct:
        offline.append(f"packet loss {stats.avg_packet_loss_pct:.1f}% >= {t.packet_loss_offline_pct:g}%")
    if offline:
        return Verdict(SiteStatus.OFFLINE, offline)

    degraded: list[str] = []
    if stats.avg_latency_ms > t.latency_degraded_ms:
        degraded.append(f"latency {stats.avg_latency_ms:.0f}ms > {t.latency_degraded_ms:g}ms")
    if stats.avg_packet_loss_pct > t.packet_loss_degraded_pct:
        degraded.append(f"packet loss {stats.avg_packet_loss_pct:.1f}% > {t.packet_loss_degraded_pct:g}%")
    if stats.avg_availability_pct < t.availability_degraded_pct:
        degraded.append(f"availability {stats.avg_availability_pct:.2f}% < {t.availability_degraded_pct:g}%")
    if degraded:
        return Verdict(SiteStatus.DEGRADED, degraded)

    return Verdict(SiteStatus.HEALTHY)


def _direction(current: SiteStatus, other: SiteStatus) -> int:
    return (RANK[other] > RANK[current]) - (RANK[other] < RANK[current])


def step(
    current: SiteStatus,
    pending_status: SiteStatus | None,
    pending_count: int,
    verdict: Verdict,
    cfg: Settings,
) -> Decision:
    """Advance the state machine by one evaluation."""
    candidate = verdict.candidate

    if candidate is None:
        return Decision(current, pending_status, pending_count, changed=False)

    if candidate == current:
        return Decision(current, None, 0, changed=False)

    # First real observation, or heartbeat loss: no confirmation needed.
    if current == SiteStatus.UNKNOWN or verdict.immediate:
        return Decision(candidate, None, 0, changed=True)

    direction = _direction(current, candidate)
    # Consecutive evaluations count toward a change as long as they keep
    # pointing the same way (e.g. DEGRADED then OFFLINE both count as "worse").
    if pending_status is not None and _direction(current, pending_status) == direction:
        count = pending_count + 1
    else:
        count = 1

    required = cfg.trip_count if direction > 0 else cfg.clear_count
    if count >= required:
        return Decision(candidate, None, 0, changed=True)
    return Decision(current, candidate, count, changed=False)

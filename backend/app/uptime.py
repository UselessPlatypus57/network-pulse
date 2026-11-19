"""Uptime and MTTR from the status-transition log.

Pure functions, no I/O. Uptime is a *time-weighted* measure: we integrate how
long a site spent in each status between transitions. Counting samples would
be wrong, because samples stop arriving during exactly the outages we are
trying to measure.

Definitions (over a window [start, end)):

- observed time  -- time with a known status. UNKNOWN (never reported) and any
                    time before the site's first recorded status are excluded,
                    so a site registered an hour ago isn't scored on 23 hours
                    of nothing.
- availability   -- share of observed time *not* OFFLINE (service was usable).
- healthy        -- share of observed time HEALTHY (no degradation either).
- incident       -- a maximal unhealthy period (DEGRADED and/or OFFLINE in a
                    row); DEGRADED -> OFFLINE -> HEALTHY is one incident, which
                    matches how alerts escalate rather than re-open.
- incidents are attributed to the window they *start* in; MTTR is the mean
                    duration of those that have also recovered.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from app.models import SiteStatus

UNHEALTHY = frozenset({SiteStatus.DEGRADED, SiteStatus.OFFLINE})


@dataclass
class UptimeReport:
    window_start: datetime
    window_end: datetime
    seconds_by_status: dict[SiteStatus, float] = field(default_factory=lambda: {s: 0.0 for s in SiteStatus})
    incidents: int = 0
    resolved_incidents: int = 0
    resolved_total_s: float = 0.0
    ongoing_incident_s: float | None = None

    @property
    def observed_s(self) -> float:
        return sum(v for s, v in self.seconds_by_status.items() if s != SiteStatus.UNKNOWN)

    @property
    def available_pct(self) -> float | None:
        obs = self.observed_s
        return None if obs == 0 else 100.0 * (obs - self.seconds_by_status[SiteStatus.OFFLINE]) / obs

    @property
    def healthy_pct(self) -> float | None:
        obs = self.observed_s
        return None if obs == 0 else 100.0 * self.seconds_by_status[SiteStatus.HEALTHY] / obs

    @property
    def mttr_s(self) -> float | None:
        return self.resolved_total_s / self.resolved_incidents if self.resolved_incidents else None


def compute_uptime(
    initial_status: SiteStatus | None,
    events: list[tuple[datetime, SiteStatus]],
    window_start: datetime,
    window_end: datetime,
) -> UptimeReport:
    """Integrate status time over [window_start, window_end).

    ``initial_status`` is the status in force at ``window_start`` (from the
    last transition before it), or None if the site had no history yet.
    ``events`` are (time, new_status) transitions, ascending; any outside the
    window are ignored.
    """
    report = UptimeReport(window_start, window_end)
    status = initial_status
    cursor = window_start
    # An incident already running at window start belongs to the previous window.
    incident_start: datetime | None = None

    def close_segment(until: datetime) -> None:
        if status is not None and until > cursor:
            report.seconds_by_status[status] += (until - cursor).total_seconds()

    for at, new_status in events:
        if at < window_start or at >= window_end:
            continue
        close_segment(at)

        was_unhealthy = status in UNHEALTHY
        now_unhealthy = new_status in UNHEALTHY
        if now_unhealthy and not was_unhealthy:
            report.incidents += 1
            incident_start = at
        elif was_unhealthy and new_status == SiteStatus.HEALTHY and incident_start is not None:
            report.resolved_incidents += 1
            report.resolved_total_s += (at - incident_start).total_seconds()
            incident_start = None
        elif not now_unhealthy:
            incident_start = None  # recovered from an incident that began before the window

        status, cursor = new_status, at

    close_segment(window_end)
    if status in UNHEALTHY and incident_start is not None:
        report.ongoing_incident_s = (window_end - incident_start).total_seconds()
    return report


@dataclass
class FleetUptime:
    sites: int
    observed_s: float
    available_pct: float | None
    healthy_pct: float | None
    incidents: int
    resolved_incidents: int
    mttr_s: float | None


def aggregate(reports: list[UptimeReport]) -> FleetUptime:
    """Fleet totals weight every site by its observed time, not equally."""
    observed = sum(r.observed_s for r in reports)
    offline = sum(r.seconds_by_status[SiteStatus.OFFLINE] for r in reports)
    healthy = sum(r.seconds_by_status[SiteStatus.HEALTHY] for r in reports)
    resolved = sum(r.resolved_incidents for r in reports)
    resolved_s = sum(r.resolved_total_s for r in reports)
    return FleetUptime(
        sites=len(reports),
        observed_s=observed,
        available_pct=None if observed == 0 else 100.0 * (observed - offline) / observed,
        healthy_pct=None if observed == 0 else 100.0 * healthy / observed,
        incidents=sum(r.incidents for r in reports),
        resolved_incidents=resolved,
        mttr_s=resolved_s / resolved if resolved else None,
    )

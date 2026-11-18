"""Alert lifecycle and outbound notifications.

Alerts are driven by *state transitions*, never by raw samples. Combined with
the hysteresis in ``app.health`` this means:

- at most one OPEN alert per site (no alert storms from a noisy site),
- DEGRADED -> OFFLINE escalates the existing alert instead of opening another,
- recovery to HEALTHY resolves it and records how long the incident lasted.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal, Protocol

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.health import Transition
from app.models import Alert, AlertSeverity, AlertState, Site, SiteStatus

log = logging.getLogger("network_pulse.alerts")

EventKind = Literal["opened", "escalated", "deescalated", "resolved"]


@dataclass(frozen=True)
class AlertEvent:
    kind: EventKind
    alert_id: int
    site_id: str
    site_name: str
    severity: AlertSeverity
    status: SiteStatus
    reason: str
    at: datetime
    duration: timedelta | None = None

    def message(self) -> str:
        icon = {"opened": "🔴" if self.severity == AlertSeverity.CRITICAL else "🟠",
                "escalated": "🔴", "deescalated": "🟠", "resolved": "✅"}[self.kind]
        head = f"{icon} [{self.kind.upper()}] {self.site_id} ({self.site_name})"
        if self.kind == "resolved":
            return f"{head} recovered after {_fmt_duration(self.duration)}"
        return f"{head} is {self.status.value.upper()}: {self.reason or 'threshold breached'}"


def _fmt_duration(d: timedelta | None) -> str:
    if d is None:
        return "?"
    secs = int(d.total_seconds())
    m, s = divmod(secs, 60)
    h, m = divmod(m, 60)
    return f"{h}h{m:02d}m" if h else f"{m}m{s:02d}s"


class Notifier(Protocol):
    def notify(self, event: AlertEvent) -> None: ...


class NullNotifier:
    def notify(self, event: AlertEvent) -> None:
        log.info("alert: %s", event.message())


class WebhookNotifier:
    """Posts alert events to a Slack/Discord/generic JSON webhook.

    Sends happen on a small thread pool so a slow or dead webhook endpoint can
    never stall health evaluation.
    """

    def __init__(self, url: str, timeout_s: float = 3.0) -> None:
        self.url = url
        self.timeout_s = timeout_s
        self._pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="webhook")

    def payload(self, event: AlertEvent) -> dict:
        text = event.message()
        if "discord.com" in self.url or "discordapp.com" in self.url:
            return {"content": text}
        if "hooks.slack.com" in self.url:
            return {"text": text}
        return {
            "text": text,
            "event": {
                "kind": event.kind,
                "alert_id": event.alert_id,
                "site_id": event.site_id,
                "severity": event.severity.value,
                "status": event.status.value,
                "reason": event.reason,
                "at": event.at.isoformat(),
            },
        }

    def notify(self, event: AlertEvent) -> None:
        log.info("alert: %s", event.message())
        self._pool.submit(self._send, event)

    def _send(self, event: AlertEvent) -> bool:
        try:
            resp = httpx.post(self.url, json=self.payload(event), timeout=self.timeout_s)
            resp.raise_for_status()
            return True
        except httpx.HTTPError as exc:
            log.warning("webhook delivery failed for alert %s: %s", event.alert_id, exc)
            return False


def make_notifier(webhook_url: str | None) -> Notifier:
    return WebhookNotifier(webhook_url) if webhook_url else NullNotifier()


def _severity_for(status: SiteStatus) -> AlertSeverity | None:
    return {
        SiteStatus.DEGRADED: AlertSeverity.WARNING,
        SiteStatus.OFFLINE: AlertSeverity.CRITICAL,
    }.get(status)


def process_transitions(db: Session, transitions: list[Transition], notifier: Notifier) -> list[AlertEvent]:
    events: list[AlertEvent] = []
    for t in transitions:
        site = db.get(Site, t.site_id)
        if site is None:
            continue
        reason = "; ".join(t.reasons)
        open_alert = db.scalars(
            select(Alert).where(Alert.site_id == t.site_id, Alert.state == AlertState.OPEN)
        ).first()
        severity = _severity_for(t.current)

        if severity is not None:
            if open_alert is None:
                open_alert = Alert(site_id=t.site_id, severity=severity, reason=reason,
                                   opened_at=t.at, updated_at=t.at)
                db.add(open_alert)
                db.flush()
                kind: EventKind = "opened"
            elif open_alert.severity != severity:
                kind = "escalated" if severity == AlertSeverity.CRITICAL else "deescalated"
                open_alert.severity = severity
                open_alert.reason = reason
                open_alert.updated_at = t.at
            else:
                continue
            events.append(AlertEvent(kind, open_alert.id, site.id, site.name, severity,
                                     t.current, reason, t.at))

        elif t.current == SiteStatus.HEALTHY and open_alert is not None:
            open_alert.state = AlertState.RESOLVED
            open_alert.resolved_at = t.at
            open_alert.updated_at = t.at
            events.append(AlertEvent("resolved", open_alert.id, site.id, site.name, open_alert.severity,
                                     t.current, open_alert.reason, t.at, duration=t.at - open_alert.opened_at))

    db.commit()
    for event in events:  # only notify once the state change is durable
        notifier.notify(event)
    return events

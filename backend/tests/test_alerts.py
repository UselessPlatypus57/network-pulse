"""End-to-end evaluation: samples in the DB -> status transitions -> alerts."""

import httpx
import pytest

from app.alerts import AlertEvent, WebhookNotifier, process_transitions
from app.evaluator import evaluate_all
from app.models import Alert, AlertSeverity, AlertState, Site, SiteStatus
from tests.conftest import T0, add_sample, add_site, tick


def evaluate(db, cfg, notifier, n):
    transitions = evaluate_all(db, cfg, now=tick(n))
    process_transitions(db, transitions, notifier)
    return transitions


def test_transient_spike_raises_no_alert(db, cfg, notifier):
    """Regression: one extreme sample used to skew the window *mean* above the
    threshold for long enough to trip the hysteresis and page someone."""
    site = add_site(db)
    for n in range(12):
        latency = 2000 if n == 5 else 40  # one terrible sample
        add_sample(db, site, tick(n), latency=latency)
        evaluate(db, cfg, notifier, n)

    db.refresh(site)
    assert site.status == SiteStatus.HEALTHY
    assert notifier.kinds == []


def test_short_burst_shorter_than_trip_delay_raises_no_alert(db, cfg, notifier):
    site = add_site(db)
    for n in range(20):
        latency = 600 if 5 <= n < 8 else 40  # 15s burst
        add_sample(db, site, tick(n), latency=latency)
        evaluate(db, cfg, notifier, n)
    assert notifier.kinds == []


def test_sustained_degradation_opens_single_warning(db, cfg, notifier):
    site = add_site(db)
    add_sample(db, site, tick(0))
    evaluate(db, cfg, notifier, 0)

    for n in range(1, 15):
        add_sample(db, site, tick(n), latency=600)
        evaluate(db, cfg, notifier, n)

    db.refresh(site)
    assert site.status == SiteStatus.DEGRADED
    assert notifier.kinds == ["opened"]
    alerts = db.query(Alert).all()
    assert len(alerts) == 1 and alerts[0].severity == AlertSeverity.WARNING
    assert "latency" in alerts[0].reason


def test_heartbeat_loss_escalates_then_recovery_resolves(db, cfg, notifier):
    site = add_site(db)
    for n in range(6):  # degraded for long enough to alert
        add_sample(db, site, tick(n), latency=600)
        evaluate(db, cfg, notifier, n)
    assert notifier.kinds == ["opened"]

    # Site goes silent: after 30s without data it is OFFLINE immediately.
    for n in range(6, 14):
        evaluate(db, cfg, notifier, n)
    db.refresh(site)
    assert site.status == SiteStatus.OFFLINE
    assert notifier.kinds == ["opened", "escalated"]

    # Comes back healthy: must stay healthy for clear_count evaluations.
    for n in range(14, 30):
        add_sample(db, site, tick(n))
        evaluate(db, cfg, notifier, n)
    db.refresh(site)
    assert site.status == SiteStatus.HEALTHY
    assert notifier.kinds[-1] == "resolved"

    alert = db.query(Alert).one()
    assert alert.state == AlertState.RESOLVED
    assert alert.severity == AlertSeverity.CRITICAL
    assert alert.resolved_at > alert.opened_at


def test_one_open_alert_per_site(db, cfg, notifier):
    site = add_site(db)
    for n in range(40):
        add_sample(db, site, tick(n), latency=600)
        evaluate(db, cfg, notifier, n)
    assert db.query(Alert).filter(Alert.state == AlertState.OPEN).count() == 1


def _event(kind="opened"):
    return AlertEvent(kind, 1, "HOU-001", "Montrose", AlertSeverity.CRITICAL, SiteStatus.OFFLINE,
                      "no data for 40s (heartbeat lost)", T0)


def test_webhook_payload_shapes():
    assert set(WebhookNotifier("https://discord.com/api/webhooks/1/x").payload(_event())) == {"content"}
    assert set(WebhookNotifier("https://hooks.slack.com/services/x").payload(_event())) == {"text"}
    generic = WebhookNotifier("https://example.test/hook").payload(_event())
    assert generic["event"]["site_id"] == "HOU-001"
    assert "OFFLINE" in generic["text"]


def test_webhook_failure_is_swallowed(monkeypatch):
    def boom(*a, **kw):
        raise httpx.ConnectError("unreachable")

    monkeypatch.setattr(httpx, "post", boom)
    assert WebhookNotifier("https://example.test/hook")._send(_event()) is False


def test_window_uses_strict_majority_median(db):
    """Regression: an even-sized window that is exactly half spikes used to
    average the two middle values (~470ms) and read as a breach. Found by the
    simulator's `flap` fault."""
    from app.evaluator import window_stats

    site = add_site(db)
    for n, (lat, avail) in enumerate([(40, 100), (900, 10), (40, 100), (900, 10)]):
        add_sample(db, site, tick(n), latency=lat, avail=avail)

    stats = window_stats(db, since=tick(0))[site.id]
    assert stats.samples == 4
    assert stats.latency_ms == 40  # not (40 + 900) / 2
    assert stats.availability_pct == 100


def test_flapping_site_never_alerts(db, cfg, notifier):
    site = add_site(db)
    for n in range(40):
        latency = 1000 if n % 3 == 0 else 40  # spike on every third sample
        add_sample(db, site, tick(n), latency=latency)
        evaluate(db, cfg, notifier, n)
    assert notifier.kinds == []


def test_first_reading_blip_is_not_adopted(db, cfg, notifier):
    """Regression: a site whose very first sample was a blip went straight
    from UNKNOWN to DEGRADED, because first observations skip hysteresis."""
    site = add_site(db)
    for n in range(8):
        add_sample(db, site, tick(n), latency=2200 if n == 0 else 40)
        evaluate(db, cfg, notifier, n)
    db.refresh(site)
    assert site.status == SiteStatus.HEALTHY
    assert notifier.kinds == []


def test_monitor_restart_does_not_mark_every_site_offline(db, cfg, notifier):
    """Regression: after the whole monitor was down for longer than
    stale_after_s, every site's last_seen_at was stale on restart and the first
    evaluation marked the entire fleet OFFLINE -- an alert storm caused by the
    monitor's own outage."""
    from datetime import timedelta

    sites = [add_site(db, f"S-{i}", f"Site {i}") for i in range(5)]
    for site in sites:
        for n in range(4):
            add_sample(db, site, tick(n))
    evaluate_all(db, cfg, now=tick(4))  # all healthy

    # Monitor is down for 10 minutes, then restarts.
    restart = tick(4) + timedelta(minutes=10)
    transitions = evaluate_all(db, cfg, now=restart + timedelta(seconds=5), listening_since=restart)
    process_transitions(db, transitions, notifier)
    assert transitions == [] and notifier.kinds == []

    # Collectors resume for four of the sites; S-4 really is dead.
    for k in range(1, 9):
        now = restart + timedelta(seconds=5 * k)
        for site in sites[:4]:
            add_sample(db, site, now)
        process_transitions(db, evaluate_all(db, cfg, now=now, listening_since=restart), notifier)

    statuses = {s.id: s.status for s in db.query(Site)}
    assert statuses["S-4"] == SiteStatus.OFFLINE  # caught once we'd listened long enough
    assert [st for sid, st in statuses.items() if sid != "S-4"] == [SiteStatus.HEALTHY] * 4
    assert notifier.kinds == ["opened"]


def test_database_rejects_a_second_open_alert_for_a_site(db):
    """The one-open-alert invariant is a partial unique index, not just app logic."""
    from sqlalchemy.exc import IntegrityError

    site = add_site(db)
    db.add(Alert(site_id=site.id, severity=AlertSeverity.WARNING, state=AlertState.RESOLVED, opened_at=T0))
    db.add(Alert(site_id=site.id, severity=AlertSeverity.WARNING, state=AlertState.RESOLVED, opened_at=T0))
    db.add(Alert(site_id=site.id, severity=AlertSeverity.WARNING, state=AlertState.OPEN, opened_at=T0))
    db.commit()  # any number of resolved alerts, plus one open: fine

    db.add(Alert(site_id=site.id, severity=AlertSeverity.CRITICAL, state=AlertState.OPEN, opened_at=T0))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()

"""End-to-end evaluation: samples in the DB -> status transitions -> alerts."""

import httpx

from app.alerts import AlertEvent, WebhookNotifier, process_transitions
from app.evaluator import evaluate_all
from app.models import Alert, AlertSeverity, AlertState, SiteStatus
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
    return AlertEvent(kind, 1, "SEA-001", "Capitol Hill", AlertSeverity.CRITICAL, SiteStatus.OFFLINE,
                      "no data for 40s (heartbeat lost)", T0)


def test_webhook_payload_shapes():
    assert set(WebhookNotifier("https://discord.com/api/webhooks/1/x").payload(_event())) == {"content"}
    assert set(WebhookNotifier("https://hooks.slack.com/services/x").payload(_event())) == {"text"}
    generic = WebhookNotifier("https://example.test/hook").payload(_event())
    assert generic["event"]["site_id"] == "SEA-001"
    assert "OFFLINE" in generic["text"]


def test_webhook_failure_is_swallowed(monkeypatch):
    def boom(*a, **kw):
        raise httpx.ConnectError("unreachable")

    monkeypatch.setattr(httpx, "post", boom)
    assert WebhookNotifier("https://example.test/hook")._send(_event()) is False

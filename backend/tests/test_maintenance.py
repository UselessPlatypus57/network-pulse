"""Planned maintenance: no alerts during the window, re-judged from scratch after it."""

from datetime import timedelta

import pytest

from app.alerts import process_transitions
from app.evaluator import evaluate_all
from app.models import Alert, AlertState, StatusEvent
from app.models import SiteStatus as S
from app.uptime import compute_uptime
from tests.conftest import T0, add_sample, add_site, tick


def evaluate(db, cfg, notifier, n):
    process_transitions(db, evaluate_all(db, cfg, now=tick(n)), notifier)


def healthy_site(db, cfg, notifier):
    site = add_site(db)
    for n in range(4):
        add_sample(db, site, tick(n))
        evaluate(db, cfg, notifier, n)
    db.refresh(site)
    assert site.status == S.HEALTHY
    return site


def test_maintenance_suppresses_status_changes_and_alerts(db, cfg, notifier):
    site = healthy_site(db, cfg, notifier)
    site.maintenance_until = tick(30)
    db.commit()

    for n in range(4, 25):  # terrible metrics, then total silence
        if n < 12:
            add_sample(db, site, tick(n), latency=900, loss=60, avail=10)
        evaluate(db, cfg, notifier, n)

    db.refresh(site)
    assert site.status == S.MAINTENANCE
    assert site.pending_status is None and site.pending_count == 0
    assert notifier.kinds == []
    events = [(e.previous, e.status) for e in db.query(StatusEvent).order_by(StatusEvent.at)]
    assert events[-1] == (S.HEALTHY, S.MAINTENANCE)


def test_site_still_broken_after_maintenance_alerts_immediately(db, cfg, notifier):
    """'The upgrade broke it' must page: no hysteresis delay once the window ends."""
    site = healthy_site(db, cfg, notifier)
    site.maintenance_until = tick(10)
    db.commit()
    for n in range(4, 10):
        evaluate(db, cfg, notifier, n)  # site silent during the work
    db.refresh(site)
    assert site.status == S.MAINTENANCE

    evaluate(db, cfg, notifier, 10)  # window over, still silent
    db.refresh(site)
    assert site.status == S.OFFLINE
    assert notifier.kinds == ["opened"]
    assert db.query(Alert).filter(Alert.state == AlertState.OPEN).count() == 1


def test_site_healthy_after_maintenance_returns_quietly(db, cfg, notifier):
    site = healthy_site(db, cfg, notifier)
    site.maintenance_until = tick(10)
    db.commit()
    for n in range(4, 16):
        add_sample(db, site, tick(n))
        evaluate(db, cfg, notifier, n)
    db.refresh(site)
    assert site.status == S.HEALTHY
    assert notifier.kinds == []


def test_maintenance_time_is_excluded_from_uptime():
    m = lambda minutes: T0 + timedelta(minutes=minutes)  # noqa: E731
    events = [(m(10), S.MAINTENANCE), (m(40), S.HEALTHY)]  # 30 minutes of planned work
    r = compute_uptime(S.HEALTHY, events, T0, m(60))
    assert r.observed_s == 30 * 60
    assert r.available_pct == 100 and r.incidents == 0


SITE = {"name": "Montrose", "region": "Inner Houston", "latitude": 29.745, "longitude": -95.391}


def test_maintenance_endpoints(client):
    client.put("/api/v1/sites/HOU-001", json=SITE)

    r = client.put("/api/v1/sites/HOU-001/maintenance", json={"minutes": 30})
    assert r.status_code == 200 and r.json()["maintenance_until"] is not None

    r = client.delete("/api/v1/sites/HOU-001/maintenance")
    assert r.status_code == 200

    assert client.put("/api/v1/sites/NOPE/maintenance", json={"minutes": 30}).status_code == 404
    assert client.put("/api/v1/sites/HOU-001/maintenance", json={"minutes": 0}).status_code == 422


@pytest.mark.parametrize("minutes", [1, 24 * 60])
def test_maintenance_duration_bounds_accepted(client, minutes):
    client.put("/api/v1/sites/HOU-001", json=SITE)
    assert client.put("/api/v1/sites/HOU-001/maintenance", json={"minutes": minutes}).status_code == 200

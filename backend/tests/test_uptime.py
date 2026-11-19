"""Uptime / MTTR: the pure integration logic, the evaluator's event log, and the API."""

from datetime import timedelta

import pytest

from app.evaluator import evaluate_all
from app.models import SiteStatus as S
from app.models import StatusEvent
from app.uptime import aggregate, compute_uptime
from tests.conftest import T0, add_sample, add_site, tick

START, END = T0, T0 + timedelta(hours=1)


def m(minutes: float):
    return T0 + timedelta(minutes=minutes)


# --- compute_uptime ---------------------------------------------------------

def test_healthy_all_window():
    r = compute_uptime(S.HEALTHY, [], START, END)
    assert r.available_pct == 100 and r.healthy_pct == 100
    assert r.incidents == 0 and r.mttr_s is None


def test_outage_is_time_weighted():
    # 10 minutes offline out of 60.
    r = compute_uptime(S.HEALTHY, [(m(20), S.OFFLINE), (m(30), S.HEALTHY)], START, END)
    assert r.available_pct == pytest.approx(100 * 50 / 60)
    assert r.incidents == 1 and r.resolved_incidents == 1
    assert r.mttr_s == 600


def test_degraded_counts_against_healthy_not_available():
    r = compute_uptime(S.HEALTHY, [(m(0), S.DEGRADED), (m(6), S.HEALTHY)], START, END)
    assert r.available_pct == 100
    assert r.healthy_pct == pytest.approx(90)


def test_escalation_is_one_incident():
    events = [(m(10), S.DEGRADED), (m(12), S.OFFLINE), (m(15), S.DEGRADED), (m(20), S.HEALTHY)]
    r = compute_uptime(S.HEALTHY, events, START, END)
    assert r.incidents == 1
    assert r.mttr_s == 600  # 10:00 -> 20:00
    assert r.seconds_by_status[S.OFFLINE] == 180


def test_mttr_is_mean_of_resolved_incidents():
    events = [(m(5), S.OFFLINE), (m(7), S.HEALTHY), (m(40), S.DEGRADED), (m(46), S.HEALTHY)]
    r = compute_uptime(S.HEALTHY, events, START, END)
    assert (r.incidents, r.resolved_incidents) == (2, 2)
    assert r.mttr_s == (120 + 360) / 2


def test_ongoing_incident_reported_not_in_mttr():
    r = compute_uptime(S.HEALTHY, [(m(50), S.OFFLINE)], START, END)
    assert r.incidents == 1 and r.resolved_incidents == 0
    assert r.mttr_s is None
    assert r.ongoing_incident_s == 600


def test_incident_from_previous_window_counts_time_but_not_incident():
    r = compute_uptime(S.OFFLINE, [(m(15), S.HEALTHY)], START, END)
    assert r.incidents == 0 and r.mttr_s is None
    assert r.available_pct == pytest.approx(75)


def test_time_before_first_status_and_unknown_are_not_scored():
    # Site first reported 30 minutes into the window.
    r = compute_uptime(None, [(m(30), S.HEALTHY)], START, END)
    assert r.observed_s == 1800
    assert r.available_pct == 100
    assert compute_uptime(None, [], START, END).available_pct is None


def test_events_outside_window_ignored():
    r = compute_uptime(S.HEALTHY, [(m(-5), S.OFFLINE), (m(61), S.OFFLINE)], START, END)
    assert r.available_pct == 100


def test_fleet_aggregate_weights_by_observed_time():
    a = compute_uptime(S.HEALTHY, [(m(0), S.OFFLINE), (m(30), S.HEALTHY)], START, END)  # 50%
    b = compute_uptime(S.HEALTHY, [], START, END)  # 100%
    f = aggregate([a, b])
    assert f.available_pct == pytest.approx(75)
    assert f.mttr_s == 1800 and f.incidents == 1


# --- evaluator writes the log ----------------------------------------------

def test_evaluator_logs_each_confirmed_transition(db, cfg):
    site = add_site(db)
    for n in range(10):
        add_sample(db, site, tick(n), latency=600 if n >= 3 else 40)
        evaluate_all(db, cfg, now=tick(n))
    events = [(e.previous, e.status) for e in db.query(StatusEvent).order_by(StatusEvent.at)]
    assert events == [(S.UNKNOWN, S.HEALTHY), (S.HEALTHY, S.DEGRADED)]


# --- API --------------------------------------------------------------------

SITE = {"name": "Montrose", "region": "Inner Houston", "latitude": 29.745, "longitude": -95.391}


def test_site_uptime_endpoint(client, db):
    from app.db import utcnow

    client.put("/api/v1/sites/HOU-001", json=SITE)
    now = utcnow()
    db.add_all([
        StatusEvent(site_id="HOU-001", at=now - timedelta(minutes=50), previous=S.UNKNOWN, status=S.HEALTHY),
        StatusEvent(site_id="HOU-001", at=now - timedelta(minutes=20), previous=S.HEALTHY, status=S.OFFLINE),
        StatusEvent(site_id="HOU-001", at=now - timedelta(minutes=15), previous=S.OFFLINE, status=S.HEALTHY),
    ])
    db.commit()

    r = client.get("/api/v1/sites/HOU-001/uptime?hours=1").json()
    assert r["incidents"] == 1 and r["resolved_incidents"] == 1
    assert r["mttr_s"] == pytest.approx(300, abs=1)
    assert r["available_pct"] == pytest.approx(90, abs=0.1)  # 5 of 50 observed minutes offline

    fleet = client.get("/api/v1/health/uptime?hours=1").json()
    assert fleet["sites"] == 1 and fleet["incidents"] == 1

    assert client.get("/api/v1/sites/NOPE/uptime").status_code == 404
    assert client.get("/api/v1/sites/HOU-001/uptime?hours=0").status_code == 422

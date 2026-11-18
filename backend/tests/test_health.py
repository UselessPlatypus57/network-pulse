"""Unit tests for the classifier and hysteresis state machine (no database)."""

from datetime import timedelta

from app.health import Verdict, WindowStats, classify, step
from app.models import SiteStatus as S
from tests.conftest import T0

GOOD = WindowStats(samples=6, latency_ms=40, packet_loss_pct=0.1, availability_pct=99.99)


def stats(**kw) -> WindowStats:
    base = dict(samples=6, latency_ms=40, packet_loss_pct=0.1, availability_pct=99.99)
    base.update(kw)
    return WindowStats(**base)


# --- classify ---------------------------------------------------------------

def test_never_reported_is_unknown(cfg):
    assert classify(None, None, T0, cfg).candidate == S.UNKNOWN


def test_healthy_metrics(cfg):
    v = classify(GOOD, T0, T0, cfg)
    assert v.candidate == S.HEALTHY and v.reasons == []


def test_high_latency_is_degraded_with_reason(cfg):
    v = classify(stats(latency_ms=320), T0, T0, cfg)
    assert v.candidate == S.DEGRADED
    assert v.reasons == ["latency 320ms > 150ms"]


def test_multiple_breaches_all_reported(cfg):
    v = classify(stats(latency_ms=200, packet_loss_pct=5, availability_pct=97), T0, T0, cfg)
    assert v.candidate == S.DEGRADED
    assert len(v.reasons) == 3


def test_availability_collapse_is_offline(cfg):
    assert classify(stats(availability_pct=20), T0, T0, cfg).candidate == S.OFFLINE


def test_massive_packet_loss_is_offline(cfg):
    assert classify(stats(packet_loss_pct=75), T0, T0, cfg).candidate == S.OFFLINE


def test_heartbeat_loss_is_immediate_offline(cfg):
    v = classify(GOOD, T0, T0 + timedelta(seconds=45), cfg)
    assert v.candidate == S.OFFLINE and v.immediate
    assert "heartbeat lost" in v.reasons[0]


def test_no_samples_in_window_holds_state(cfg):
    assert classify(None, T0, T0 + timedelta(seconds=10), cfg).candidate is None


# --- step (hysteresis) ------------------------------------------------------

def run(cfg, start: S, candidates: list[S]) -> list[S]:
    """Feed a sequence of candidate verdicts through the state machine."""
    status, pending, count = start, None, 0
    history = []
    for c in candidates:
        d = step(status, pending, count, Verdict(c), cfg)
        status, pending, count = d.status, d.pending_status, d.pending_count
        history.append(status)
    return history


def test_single_blip_does_not_change_status(cfg):
    assert run(cfg, S.HEALTHY, [S.DEGRADED, S.HEALTHY, S.HEALTHY])[-1] == S.HEALTHY


def test_flapping_never_trips(cfg):
    seq = [S.DEGRADED, S.DEGRADED, S.HEALTHY] * 5
    assert set(run(cfg, S.HEALTHY, seq)) == {S.HEALTHY}


def test_sustained_breach_trips_after_trip_count(cfg):
    history = run(cfg, S.HEALTHY, [S.DEGRADED] * 3)
    assert history == [S.HEALTHY, S.HEALTHY, S.DEGRADED]


def test_recovery_requires_clear_count(cfg):
    history = run(cfg, S.DEGRADED, [S.HEALTHY] * 4)
    assert history == [S.DEGRADED, S.DEGRADED, S.DEGRADED, S.HEALTHY]


def test_worsening_verdicts_accumulate_toward_trip(cfg):
    # DEGRADED then OFFLINE both point "worse": they count together.
    history = run(cfg, S.HEALTHY, [S.DEGRADED, S.DEGRADED, S.OFFLINE])
    assert history[-1] == S.OFFLINE


def test_first_observation_is_adopted_immediately(cfg):
    assert run(cfg, S.UNKNOWN, [S.HEALTHY]) == [S.HEALTHY]


def test_immediate_verdict_bypasses_hysteresis(cfg):
    d = step(S.HEALTHY, None, 0, Verdict(S.OFFLINE, ["no data"], immediate=True), cfg)
    assert d.changed and d.status == S.OFFLINE


def test_no_evidence_preserves_pending_progress(cfg):
    d = step(S.HEALTHY, S.DEGRADED, 2, Verdict(None), cfg)
    assert (d.status, d.pending_status, d.pending_count) == (S.HEALTHY, S.DEGRADED, 2)

"""Leader election and the shared evaluator heartbeat."""

import pytest

from app.db import engine
from app.evaluator import run_once
from app.leader import INSTANCE_ID, LeaderLock

postgres_only = pytest.mark.skipif(
    engine.dialect.name != "postgresql", reason="advisory locks need PostgreSQL (runs in CI's postgres job)"
)


def test_sqlite_instance_always_leads():
    if engine.dialect.name == "postgresql":
        pytest.skip("SQLite behaviour")
    lock = LeaderLock(engine)
    assert lock.ensure() and lock.is_leader


def test_heartbeat_is_shared_through_the_database(client):
    """/health/summary must report liveness from the heartbeat row, so any
    replica can answer it, not just the one that's evaluating."""
    before = client.get("/api/v1/health/summary").json()["evaluator"]
    assert before["running"] is False and before["leader"] is None

    run_once()
    ev = client.get("/api/v1/health/summary").json()["evaluator"]
    assert ev["running"] is True
    assert ev["leader"] == INSTANCE_ID
    assert ev["last_run_at"] is not None
    assert ev["served_by"] == INSTANCE_ID


@postgres_only
def test_only_one_leader_at_a_time_and_clean_handover():
    a, b = LeaderLock(engine, key=11), LeaderLock(engine, key=11)
    try:
        assert a.ensure() is True
        assert b.ensure() is False  # follower while a leads
        assert a.ensure() is True  # leader keeps the lock across ticks
        a.release()  # graceful shutdown
        assert b.ensure() is True  # follower takes over on its next tick
    finally:
        a.release()
        b.release()


@postgres_only
def test_follower_takes_over_when_leader_dies():
    a, b = LeaderLock(engine, key=12), LeaderLock(engine, key=12)
    try:
        assert a.ensure() is True and b.ensure() is False
        # Simulate the leader process dying: its connection drops without unlocking.
        a._conn.invalidate()
        a._conn = None
        assert b.ensure() is True  # Postgres released the dead session's lock
    finally:
        a.release()
        b.release()

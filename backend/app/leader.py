"""Leader election for the evaluator, using a Postgres advisory lock.

Every API replica runs the evaluation loop, but only the replica holding the
lock actually evaluates; the rest serve the API and ingest data, and retry the
lock each tick.

The lock is *session-level*: it belongs to one database connection, which the
leader checks out and keeps for as long as it leads. If the leader process
dies -- crash, OOM kill, container killed -- its connection closes and Postgres
releases the lock by itself, so a follower takes over on its next tick. No
ZooKeeper/etcd needed: the database we already depend on is the arbiter.

SQLite (local dev, tests) is single-process, so there every instance leads.
"""

from __future__ import annotations

import logging
import os
import socket

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

log = logging.getLogger("network_pulse.leader")

#: Identifies this process in logs, the API and the dashboard.
INSTANCE_ID = f"{socket.gethostname()}:{os.getpid()}"

#: Arbitrary application-wide key; every replica must use the same one.
LOCK_KEY = 726_354_011


class LeaderLock:
    def __init__(self, engine: Engine, key: int = LOCK_KEY) -> None:
        self.engine = engine
        self.key = key
        self.enabled = engine.dialect.name == "postgresql"
        self._conn: Connection | None = None

    @property
    def is_leader(self) -> bool:
        return not self.enabled or self._conn is not None

    def ensure(self) -> bool:
        """Return True if this process leads (acquiring the lock if it's free)."""
        if not self.enabled:
            return True
        if self._conn is not None:
            # Still leader only while the connection that holds the lock is alive.
            try:
                self._conn.execute(text("SELECT 1"))
                self._conn.commit()
                return True
            except Exception:
                log.warning("lost the leader lock: its database connection failed")
                self._drop()
        conn: Connection | None = None
        try:
            conn = self.engine.connect()
            got = bool(conn.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": self.key}).scalar())
            conn.commit()  # don't sit "idle in transaction" while holding the lock
        except Exception:
            log.warning("could not reach the database to try the leader lock")
            if conn is not None:
                conn.invalidate()
                conn.close()
            return False
        if got:
            self._conn = conn
            return True
        conn.close()
        return False

    def release(self) -> None:
        """Hand leadership over cleanly (on shutdown) instead of waiting for a crash."""
        if self._conn is None:
            return
        try:
            self._conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": self.key})
            self._conn.commit()
            self._conn.close()
        except Exception:
            self._drop()
        self._conn = None

    def _drop(self) -> None:
        # A connection that may still hold the lock must never go back to the pool.
        if self._conn is not None:
            try:
                self._conn.invalidate()
                self._conn.close()
            except Exception:
                pass
        self._conn = None

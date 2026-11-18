import os
import tempfile
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

# Must be set before the app (and its engine) is imported.
# SQLite by default; CI also runs the suite against PostgreSQL via TEST_DATABASE_URL.
_tmpdir = tempfile.mkdtemp(prefix="network-pulse-tests-")
os.environ["DATABASE_URL"] = os.getenv("TEST_DATABASE_URL") or f"sqlite:///{os.path.join(_tmpdir, 'test.db')}"
os.environ["EVALUATOR_ENABLED"] = "false"
os.environ.pop("WEBHOOK_URL", None)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.config import Settings  # noqa: E402
from app.db import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import MetricSample, Site  # noqa: E402

T0 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def fresh_db() -> Iterator[None]:
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield


@pytest.fixture
def db() -> Iterator[Session]:
    with SessionLocal() as session:
        yield session


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as c:
        yield c


@pytest.fixture
def cfg() -> Settings:
    return Settings(window_s=30, stale_after_s=30, trip_count=3, clear_count=4)


class RecordingNotifier:
    def __init__(self) -> None:
        self.events = []

    def notify(self, event) -> None:
        self.events.append(event)

    @property
    def kinds(self) -> list[str]:
        return [e.kind for e in self.events]


@pytest.fixture
def notifier() -> RecordingNotifier:
    return RecordingNotifier()


def add_site(db: Session, site_id: str = "HOU-001", name: str = "Montrose") -> Site:
    site = Site(id=site_id, name=name, region="Inner Houston", latitude=29.75, longitude=-95.39, status_since=T0)
    db.add(site)
    db.commit()
    return site


def add_sample(db: Session, site: Site, ts: datetime, latency=40.0, loss=0.1, avail=100.0) -> None:
    db.add(MetricSample(site_id=site.id, ts=ts, latency_ms=latency, packet_loss_pct=loss, availability_pct=avail))
    site.last_seen_at = ts if site.last_seen_at is None or ts > site.last_seen_at else site.last_seen_at
    db.commit()


def tick(n: int) -> datetime:
    """Time of the n-th 5-second evaluation tick."""
    return T0 + timedelta(seconds=5 * n)

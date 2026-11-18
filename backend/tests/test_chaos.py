from datetime import timedelta

from app.db import utcnow
from app.models import ChaosFault

SITE = {"name": "Capitol Hill", "region": "Seattle", "latitude": 47.62, "longitude": -122.32}


def test_inject_list_and_clear_fault(client):
    client.put("/api/v1/sites/SEA-001", json=SITE)

    r = client.put("/api/v1/chaos/SEA-001", json={"fault": "outage", "duration_s": 60})
    assert r.status_code == 200
    assert r.json()["fault"] == "outage"

    faults = client.get("/api/v1/chaos").json()
    assert [(f["site_id"], f["fault"]) for f in faults] == [("SEA-001", "outage")]

    # Re-injecting replaces rather than duplicates.
    client.put("/api/v1/chaos/SEA-001", json={"fault": "latency"})
    assert [f["fault"] for f in client.get("/api/v1/chaos").json()] == ["latency"]

    assert client.delete("/api/v1/chaos/SEA-001").status_code == 204
    assert client.get("/api/v1/chaos").json() == []


def test_expired_faults_are_dropped(client, db):
    client.put("/api/v1/sites/SEA-001", json=SITE)
    client.put("/api/v1/chaos/SEA-001", json={"fault": "packet_loss"})
    fault = db.get(ChaosFault, "SEA-001")
    fault.expires_at = utcnow() - timedelta(seconds=1)
    db.commit()
    assert client.get("/api/v1/chaos").json() == []


def test_fault_validation(client):
    assert client.put("/api/v1/chaos/NOPE", json={"fault": "outage"}).status_code == 404
    client.put("/api/v1/sites/SEA-001", json=SITE)
    assert client.put("/api/v1/chaos/SEA-001", json={"fault": "meteor"}).status_code == 422
    assert client.put("/api/v1/chaos/SEA-001", json={"fault": "outage", "duration_s": 1}).status_code == 422

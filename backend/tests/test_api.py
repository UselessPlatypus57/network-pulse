from app.models import SiteStatus

SITE = {"name": "Capitol Hill", "region": "Seattle", "latitude": 47.62, "longitude": -122.32}


def sample(site_id="SEA-001", latency=40, loss=0.1, avail=100):
    return {"site_id": site_id, "latency_ms": latency, "packet_loss_pct": loss, "availability_pct": avail}


def test_liveness_and_readiness(client):
    assert client.get("/healthz").json() == {"status": "ok"}
    assert client.get("/readyz").json() == {"status": "ready"}


def test_register_and_list_sites(client):
    r = client.put("/api/v1/sites/SEA-001", json=SITE)
    assert r.status_code == 200
    assert r.json()["status"] == "unknown"

    sites = client.get("/api/v1/sites").json()
    assert [s["id"] for s in sites] == ["SEA-001"]


def test_upsert_updates_descriptive_fields(client):
    client.put("/api/v1/sites/SEA-001", json=SITE)
    client.put("/api/v1/sites/SEA-001", json={**SITE, "name": "Renamed"})
    assert client.get("/api/v1/sites/SEA-001").json()["name"] == "Renamed"


def test_unknown_site_is_404(client):
    assert client.get("/api/v1/sites/NOPE").status_code == 404


def test_ingest_reports_unknown_sites_without_failing_batch(client):
    client.put("/api/v1/sites/SEA-001", json=SITE)
    r = client.post("/api/v1/metrics", json={"samples": [sample(), sample("GHOST")]})
    assert r.status_code == 202
    assert r.json() == {"accepted": 1, "rejected": 1, "unknown_sites": ["GHOST"]}
    assert len(client.get("/api/v1/sites/SEA-001/metrics").json()) == 1


def test_ingest_validates_ranges(client):
    client.put("/api/v1/sites/SEA-001", json=SITE)
    assert client.post("/api/v1/metrics", json={"samples": [sample(loss=140)]}).status_code == 422
    assert client.post("/api/v1/metrics", json={"samples": []}).status_code == 422


def test_ingest_updates_last_seen(client):
    client.put("/api/v1/sites/SEA-001", json=SITE)
    client.post("/api/v1/metrics", json={"samples": [sample()]})
    assert client.get("/api/v1/sites/SEA-001").json()["last_seen_at"] is not None


def test_unhealthy_endpoint_orders_offline_first(client, db):
    from app.models import Site

    for sid, status in [("A", SiteStatus.DEGRADED), ("B", SiteStatus.OFFLINE), ("C", SiteStatus.HEALTHY)]:
        client.put(f"/api/v1/sites/{sid}", json=SITE)
        db.get(Site, sid).status = status
    db.commit()

    ids = [s["id"] for s in client.get("/api/v1/health/unhealthy").json()]
    assert ids == ["B", "A"]

    summary = client.get("/api/v1/health/summary").json()
    assert summary["total"] == 3
    assert summary["counts"]["offline"] == 1

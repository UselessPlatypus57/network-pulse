from app.models import SiteStatus

SITE = {"name": "Montrose", "region": "Inner Houston", "latitude": 29.745, "longitude": -95.391}


def sample(site_id="HOU-001", latency=40, loss=0.1, avail=100):
    return {"site_id": site_id, "latency_ms": latency, "packet_loss_pct": loss, "availability_pct": avail}


def test_liveness_and_readiness(client):
    assert client.get("/healthz").json() == {"status": "ok"}
    assert client.get("/readyz").json() == {"status": "ready"}


def test_register_and_list_sites(client):
    r = client.put("/api/v1/sites/HOU-001", json=SITE)
    assert r.status_code == 200
    assert r.json()["status"] == "unknown"

    sites = client.get("/api/v1/sites").json()
    assert [s["id"] for s in sites] == ["HOU-001"]


def test_upsert_updates_descriptive_fields(client):
    client.put("/api/v1/sites/HOU-001", json=SITE)
    client.put("/api/v1/sites/HOU-001", json={**SITE, "name": "Renamed"})
    assert client.get("/api/v1/sites/HOU-001").json()["name"] == "Renamed"


def test_unknown_site_is_404(client):
    assert client.get("/api/v1/sites/NOPE").status_code == 404


def test_ingest_reports_unknown_sites_without_failing_batch(client):
    client.put("/api/v1/sites/HOU-001", json=SITE)
    r = client.post("/api/v1/metrics", json={"samples": [sample(), sample("GHOST")]})
    assert r.status_code == 202
    assert r.json() == {"accepted": 1, "rejected": 1, "unknown_sites": ["GHOST"]}
    assert len(client.get("/api/v1/sites/HOU-001/metrics").json()) == 1


def test_ingest_validates_ranges(client):
    client.put("/api/v1/sites/HOU-001", json=SITE)
    assert client.post("/api/v1/metrics", json={"samples": [sample(loss=140)]}).status_code == 422
    assert client.post("/api/v1/metrics", json={"samples": []}).status_code == 422


def test_ingest_updates_last_seen(client):
    client.put("/api/v1/sites/HOU-001", json=SITE)
    client.post("/api/v1/metrics", json={"samples": [sample()]})
    assert client.get("/api/v1/sites/HOU-001").json()["last_seen_at"] is not None


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


def test_prometheus_metrics_exposed(client):
    client.put("/api/v1/sites/HOU-001", json=SITE)
    client.post("/api/v1/metrics", json={"samples": [sample(), sample("GHOST")]})
    body = client.get("/metrics").text
    assert "network_pulse_samples_ingested_total" in body
    assert "network_pulse_samples_rejected_total" in body
    assert 'route="/api/v1/sites/{site_id}"' in body  # templated, not per-site


def test_detection_config_exposed(client):
    cfg = client.get("/api/v1/health/config").json()
    assert cfg["latency_degraded_ms"] == 150
    assert cfg["trip_count"] >= 1 and cfg["clear_count"] >= 1


def test_last_seen_only_moves_forward(client):
    """An older (backfilled or delayed) sample must not move last_seen_at back,
    or a live site could look stale and be marked OFFLINE."""
    client.put("/api/v1/sites/HOU-001", json=SITE)
    newer, older = "2026-01-01T12:00:10Z", "2026-01-01T12:00:00Z"
    client.post("/api/v1/metrics", json={"samples": [{**sample(), "ts": newer}]})
    client.post("/api/v1/metrics", json={"samples": [{**sample(), "ts": older}]})
    seen = client.get("/api/v1/sites/HOU-001").json()["last_seen_at"]
    assert seen.startswith("2026-01-01T12:00:10")


def test_large_responses_are_gzipped_when_the_client_accepts_it(client):
    """The site list is the dashboard's biggest poll; it must be compressed for
    clients that ask, sent plain to clients that don't, and tiny responses skip it."""
    for i in range(40):
        client.put(f"/api/v1/sites/HOU-{i:03d}", json=SITE)

    gz = client.get("/api/v1/sites", headers={"Accept-Encoding": "gzip"})
    plain = client.get("/api/v1/sites", headers={"Accept-Encoding": "identity"})
    assert gz.headers.get("content-encoding") == "gzip"
    assert "content-encoding" not in plain.headers
    assert gz.json() == plain.json()  # same data either way
    assert gz.num_bytes_downloaded < plain.num_bytes_downloaded / 4

    small = client.get("/healthz", headers={"Accept-Encoding": "gzip"})
    assert "content-encoding" not in small.headers  # under the 1 KB minimum

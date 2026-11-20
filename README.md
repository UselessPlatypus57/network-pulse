# Network Pulse

**A network health & outage monitor for simulated cellular sites.** Probes report latency, packet loss and availability for 40 cell sites across the Houston metro. A FastAPI service decides which sites are healthy, degraded or offline, and opens and resolves alerts. A React dashboard shows the fleet on a live map.

The interesting part is **telling a real outage from a blip**: a rolling-window median, a minimum sample count, hysteresis, and heartbeat-loss detection. A built-in chaos panel lets you break a site on demand and watch detection, alerting and recovery happen.

<!-- Add a screenshot: docs/dashboard.png -->

## Features

- **Ingestion API**: batched `POST /api/v1/metrics`. Unknown sites are reported back instead of failing the batch.
- **Health engine**: per-site status from the strict-majority median of a 30 s window, with N-of-M hysteresis (3 checks to escalate, 4 to clear). A site that stops reporting for 30 s goes OFFLINE.
- **Unhealthy-sites endpoint**: `GET /api/v1/health/unhealthy` lists every degraded or offline site, worst first, with human-readable reasons (`latency 412ms > 150ms`).
- **Alerts**: one alert per incident. Opens on degradation, escalates to critical when offline, resolves on recovery with the incident's duration. Optional Slack/Discord webhook.
- **Uptime and MTTR**: every confirmed status change is logged, and the API reports time-weighted 24 h availability, incident count and mean time to recovery, per site and fleet-wide.
- **Dashboard**: summary tiles (including fleet availability and MTTR), a scroll-to-zoom coverage map, filterable site list, per-site latency/loss/availability charts with threshold lines, a 24 h uptime row, and a live alert feed.
- **Load-tested to 10,000 sites**: a scale mode in the simulator plus `scripts/benchmark.py`. Load testing found an ORM write bottleneck and a Postgres deadlock; after fixing both, evaluation at 10k sites went from 3.2 s to 0.9 s per tick with no lost data (see [ARCHITECTURE.md](ARCHITECTURE.md#measured-at-scale)).
- **Chaos testing**: inject latency, packet loss, outage or *flapping* (which should **not** alert) from the UI or API.
- **Self-monitoring**: `/healthz`, `/readyz`, an evaluator heartbeat shown in the UI, and Prometheus `/metrics`, so you can tell when the monitor itself is broken.
- **High availability**: run several API replicas (`--scale api=2`). A Postgres advisory lock elects one evaluator; if it dies, another replica takes over within one tick (measured: 6.4 s after a hard kill, no false alerts). The database itself enforces one open alert per site.
- **Maintenance windows**: put a site into planned maintenance from the dashboard or API. It won't alert or count against uptime, and when the window ends it's re-checked from scratch, so if the work broke it, it pages immediately.

## Quick start (Docker)

```bash
docker compose up --build
```

Or with two API replicas and automatic failover:

```bash
docker compose up --build --scale api=2
```

| URL | What |
|---|---|
| http://localhost:8080 | Dashboard |
| http://localhost:8080/docs | Interactive API docs (OpenAPI) |
| http://localhost:8080/metrics | Prometheus metrics (from whichever replica answers) |

In Docker the API is reached through nginx on port 8080, which is what lets it run as several replicas.

To post alerts to Slack or Discord, copy `.env.example` to `.env` and set `WEBHOOK_URL`.

## Local development (no Docker)

Uses SQLite, so nothing else needs to be installed. Run each command in its own terminal.

```bash
# 1. API (http://localhost:8000)
cd backend
python -m venv .venv && .venv/Scripts/activate     # macOS/Linux: source .venv/bin/activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload
```

```bash
# 2. Simulator (from the repo root; it only needs httpx)
pip install -r simulator/requirements.txt
python simulator/simulator.py
```

```bash
# 3. Dashboard (http://localhost:5173, proxies /api to :8000)
cd frontend
npm install
npm run dev
```

Tests and lint:

```bash
cd backend && pytest && ruff check .
```

## Try it

1. Open the dashboard and click any healthy site.
2. Under **Chaos testing**, click **Site outage**. About 30 s later the site turns OFFLINE, its marker pulses, and a critical alert appears.
3. Click **Clear**. The site returns to HEALTHY only after 4 consecutive good checks, and the alert resolves with its duration.
4. Click **Flapping** on another site. It spikes on every third sample but never changes status and never alerts. That's the false-positive protection at work.
5. On a third site, click **Start maintenance**, then **Site outage**. The site stays in MAINTENANCE with no alert. Click **End maintenance now** while it's still down: it goes OFFLINE and pages within one tick.
6. With `--scale api=2`, hover the header pill to see which replica leads, then `docker kill` that container. The other replica takes over in a few seconds and the dashboard never notices.

Or use the API directly:

```bash
curl -X PUT localhost:8080/api/v1/chaos/HOU-002 -H "Content-Type: application/json" -d '{"fault":"latency","duration_s":120}'
curl localhost:8080/api/v1/health/unhealthy
```

## API

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/v1/metrics` | Ingest a batch of samples `{samples: [{site_id, latency_ms, packet_loss_pct, availability_pct, ts?}]}` |
| `GET` | `/api/v1/health/unhealthy` | Degraded + offline sites, worst first, with reasons |
| `GET` | `/api/v1/health/summary` | Counts by status, open alerts, evaluator liveness and current leader |
| `GET` | `/api/v1/health/config` | Active thresholds and hysteresis settings |
| `GET` | `/api/v1/sites[?status=&region=]` | All sites with current status and window medians |
| `PUT` | `/api/v1/sites/{id}` | Register / update a site |
| `GET` | `/api/v1/sites/{id}/metrics?minutes=15` | Raw time series |
| `PUT/DELETE` | `/api/v1/sites/{id}/maintenance` | Start a maintenance window `{minutes}` / end it now |
| `GET` | `/api/v1/sites/{id}/uptime?hours=24` | Availability, healthy %, incidents and MTTR for one site |
| `GET` | `/api/v1/health/uptime?hours=24` | The same, fleet-wide (weighted by observed time) |
| `GET` | `/api/v1/alerts[?state=open]` | Alerts, newest first |
| `GET/PUT/DELETE` | `/api/v1/chaos[/{id}]` | List / inject / clear faults |
| `GET` | `/healthz`, `/readyz`, `/metrics` | Liveness, readiness, Prometheus |

## Detection rules (defaults, all configurable by env var)

| Status | Condition on the window median |
|---|---|
| **Degraded** | latency > 150 ms, or packet loss > 2 %, or availability < 99 % |
| **Offline** | availability < 50 %, or packet loss ≥ 50 %, or **no data for 30 s** |

A breach must hold in a strict majority of a 30 s window (minimum 3 samples) for 3 consecutive 5 s checks before the status changes. Clearing takes 4 checks.

## Scale testing

The simulator can add thousands of synthetic sites around Houston. Start the stack with them, wait about a minute for the windows to fill, then measure:

```bash
SIM_EXTRA_SITES=10000 docker compose up -d --build
python scripts/benchmark.py --duration 60
```

In PowerShell, set the variable first: `$env:SIM_EXTRA_SITES=10000`. The benchmark uses the backend's virtualenv (it needs `httpx` and `prometheus-client`). It reads the service's own Prometheus metrics and prints evaluation time per tick, ticks per minute, ingest throughput and the dashboard's read latencies. Results and the bottleneck it found are in [ARCHITECTURE.md](ARCHITECTURE.md#measured-at-scale).

See **[ARCHITECTURE.md](ARCHITECTURE.md)** for the design and trade-offs: telling blips from outages, scaling to thousands of sites, what happens when the monitor goes down, and reducing false positives.

## Tech

Python 3.12 · FastAPI · SQLAlchemy 2 · PostgreSQL 17 · React 19 · TypeScript · Vite · Leaflet · Recharts · Docker Compose · GitHub Actions · Prometheus client

## Project layout

```
backend/     FastAPI service: ingestion, health engine, alerts, chaos API, tests
simulator/   Probe simulator for 40 Houston-area sites (blips, incidents, chaos)
frontend/    React + TypeScript dashboard (served by nginx in Docker)
```

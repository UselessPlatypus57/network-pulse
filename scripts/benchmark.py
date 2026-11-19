"""Measure Network Pulse under load, using the service's own Prometheus metrics.

Start the stack with extra synthetic sites, let it warm up, then run:

    SIM_EXTRA_SITES=5000 docker compose up -d --build
    python scripts/benchmark.py --duration 60

It scrapes /metrics twice, `duration` seconds apart, and reports deltas:
evaluation time per tick, ticks completed, ingest throughput, ingest request
latency, plus timed reads of the endpoints the dashboard polls.

Needs: httpx, prometheus-client (both are in backend/requirements.txt).
"""

from __future__ import annotations

import argparse
import statistics
import time
from collections import defaultdict

import httpx
from prometheus_client.parser import text_string_to_metric_families

Key = tuple[str, tuple[tuple[str, str], ...]]


def scrape(client: httpx.Client) -> dict[Key, float]:
    values: dict[Key, float] = {}
    for family in text_string_to_metric_families(client.get("/metrics").text):
        for s in family.samples:
            values[(s.name, tuple(sorted(s.labels.items())))] = s.value
    return values


def total(values: dict[Key, float], name: str, **labels: str) -> float:
    want = set(labels.items())
    return sum(v for (n, lbl), v in values.items() if n == name and want <= set(lbl))


def histogram_quantile(before: dict, after: dict, name: str, q: float, **labels: str) -> float | None:
    """Upper bound of the bucket containing quantile q, from bucket deltas."""
    want = set(labels.items())
    buckets: dict[float, float] = defaultdict(float)
    for (n, lbl), v in after.items():
        if n == f"{name}_bucket" and want <= set(lbl):
            le = dict(lbl)["le"]
            buckets[float("inf") if le == "+Inf" else float(le)] += v - before.get((n, lbl), 0.0)
    if not buckets or buckets[float("inf")] == 0:
        return None
    target = q * buckets[float("inf")]
    return next(le for le in sorted(buckets) if buckets[le] >= target)


def timed_get(client: httpx.Client, path: str, n: int = 5) -> tuple[float, int]:
    """Median latency (ms) and response size (bytes) of n GETs."""
    times, size = [], 0
    for _ in range(n):
        t = time.perf_counter()
        r = client.get(path)
        times.append((time.perf_counter() - t) * 1000)
        size = len(r.content)
    return statistics.median(times), size


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--api", default="http://localhost:8000")
    p.add_argument("--duration", type=float, default=60.0)
    args = p.parse_args()

    client = httpx.Client(base_url=args.api, timeout=30)
    before = scrape(client)
    started = time.monotonic()

    reads = {path: timed_get(client, path) for path in
             ("/api/v1/health/summary", "/api/v1/sites", "/api/v1/health/uptime")}

    time.sleep(max(0.0, args.duration - (time.monotonic() - started)))
    after = scrape(client)
    elapsed = time.monotonic() - started

    def delta(name: str, **labels: str) -> float:
        return total(after, name, **labels) - total(before, name, **labels)

    sites = int(total(after, "network_pulse_sites"))
    runs = delta("network_pulse_evaluation_duration_seconds_count")
    eval_avg_ms = 1000 * delta("network_pulse_evaluation_duration_seconds_sum") / runs if runs else float("nan")
    eval_p95 = histogram_quantile(before, after, "network_pulse_evaluation_duration_seconds", 0.95)
    ingested = delta("network_pulse_samples_ingested_total")
    post = {"method": "POST", "route": "/api/v1/metrics"}
    posts = delta("network_pulse_http_request_duration_seconds_count", **post)
    post_sum = delta("network_pulse_http_request_duration_seconds_sum", **post)
    post_avg_ms = 1000 * post_sum / posts if posts else float("nan")
    errors = delta("network_pulse_evaluation_errors_total")
    summary = client.get("/api/v1/health/summary").json()

    print(f"Measured over {elapsed:.0f}s against {args.api}\n")
    print("| sites | eval avg | eval p95 (bucket) | ticks/min | samples/s | POST /metrics avg "
          "| GET /sites (size) | GET /summary | GET /health/uptime | eval errors |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    sites_ms, sites_bytes = reads["/api/v1/sites"]
    print(
        f"| {sites:,} | {eval_avg_ms:,.0f} ms | ≤ {eval_p95 * 1000 if eval_p95 else float('nan'):,.0f} ms "
        f"| {runs * 60 / elapsed:.1f} | {ingested / elapsed:,.0f} | {post_avg_ms:,.0f} ms "
        f"| {sites_ms:,.0f} ms ({sites_bytes / 1024:,.0f} KB) | {reads['/api/v1/health/summary'][0]:,.0f} ms "
        f"| {reads['/api/v1/health/uptime'][0]:,.0f} ms | {errors:.0f} |"
    )
    print(f"\nstatus counts: {summary['counts']}  evaluator running: {summary['evaluator']['running']}")


if __name__ == "__main__":
    main()

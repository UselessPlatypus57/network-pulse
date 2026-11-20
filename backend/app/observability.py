"""Prometheus metrics: the monitor's own health, exposed at ``GET /metrics``.

"Who watches the watcher?" -- an external Prometheus scrapes these and can
alert on, for example:

    time() - network_pulse_evaluation_last_success_timestamp_seconds > 30
    rate(network_pulse_samples_ingested_total[5m]) == 0
    absent(up{job="network-pulse"})

none of which depend on this service being healthy enough to alert about itself.
"""

from __future__ import annotations

import time

from fastapi import FastAPI, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

SITES = Gauge("network_pulse_sites", "Cell sites by current health status", ["status"])
OPEN_ALERTS = Gauge("network_pulse_open_alerts", "Currently open alerts", ["severity"])

SAMPLES_INGESTED = Counter("network_pulse_samples_ingested_total", "Metric samples accepted")
SAMPLES_REJECTED = Counter("network_pulse_samples_rejected_total", "Metric samples rejected (unknown site)")

EVALUATION_DURATION = Histogram(
    "network_pulse_evaluation_duration_seconds", "Time to evaluate every site once",
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5),
)
EVALUATION_ERRORS = Counter("network_pulse_evaluation_errors_total", "Evaluation runs that raised")
EVALUATION_LAST_SUCCESS = Gauge(
    "network_pulse_evaluation_last_success_timestamp_seconds", "Unix time of the last successful evaluation"
)
IS_LEADER = Gauge("network_pulse_evaluator_is_leader", "1 if this replica currently leads evaluation")
TRANSITIONS = Counter("network_pulse_status_transitions_total", "Site status changes", ["to"])
NOTIFICATIONS = Counter("network_pulse_alert_notifications_total", "Webhook deliveries", ["result"])

HTTP_REQUESTS = Counter("network_pulse_http_requests_total", "HTTP requests", ["method", "route", "status"])
HTTP_LATENCY = Histogram("network_pulse_http_request_duration_seconds", "HTTP request latency", ["method", "route"])


def install(app: FastAPI) -> None:
    @app.middleware("http")
    async def record_http(request: Request, call_next):
        started = time.perf_counter()
        response = await call_next(request)
        route = request.scope.get("route")
        # Use the route *template* (/api/v1/sites/{site_id}) to keep label cardinality bounded.
        path = getattr(route, "path", "unmatched")
        if path != "/metrics":
            HTTP_REQUESTS.labels(request.method, path, str(response.status_code)).inc()
            HTTP_LATENCY.labels(request.method, path).observe(time.perf_counter() - started)
        return response

    @app.get("/metrics", include_in_schema=False)
    def metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

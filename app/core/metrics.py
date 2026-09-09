"""Prometheus metric objects (the default registry).

The `/metrics` route (`app/api/metrics.py`) refreshes the gauges from the DB on
every scrape; `MetricsMiddleware` (`app/api/middleware.py`) feeds the histogram
and the request counter. Importing this module registers the metrics.
"""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

REQUEST_LATENCY = Histogram(
    "drivenow_request_duration_seconds",
    "HTTP request latency in seconds, by operation",
    labelnames=("operation",),
)

OPERATIONS_TOTAL = Counter(
    "drivenow_operations_total",
    "HTTP requests handled, by operation and status class",
    labelnames=("operation", "outcome"),
)

CARS = Gauge(
    "drivenow_cars",
    "Cars in the fleet (not deleted), by operational status",
    labelnames=("status",),
)

ONGOING_RENTALS = Gauge(
    "drivenow_ongoing_rentals",
    "Rentals currently open (returned_date IS NULL)",
)

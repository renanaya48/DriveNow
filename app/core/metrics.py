"""Prometheus metric definitions.

Declared here so any layer can import stable names. Step 8 wires these up
(a latency middleware, gauges refreshed from the DB). The names below are the
contract other modules code against.
"""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

REQUEST_LATENCY = Histogram(
    "drivenow_request_duration_seconds",
    "Request / operation latency in seconds",
    labelnames=("operation",),
)

ACTIVE_CARS = Gauge(
    "drivenow_active_cars",
    "Number of cars currently available",
)

ONGOING_RENTALS = Gauge(
    "drivenow_ongoing_rentals",
    "Number of rentals currently active",
)

OPERATIONS_TOTAL = Counter(
    "drivenow_operations_total",
    "Count of business operations performed",
    labelnames=("operation", "outcome"),
)

"""Request-timing middleware feeding the Prometheus histogram and counter.

Implemented as pure ASGI middleware so request timing covers the full ASGI
response lifecycle and avoids ``BaseHTTPMiddleware``-specific limitations. Records
exactly one sample per request, including when the endpoint raises.
"""

from __future__ import annotations

import time

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.metrics import OPERATIONS_TOTAL, REQUEST_LATENCY

_SKIP_PATHS = frozenset(
    {"/metrics", "/health", "/docs", "/docs/oauth2-redirect", "/openapi.json", "/redoc"}
)


def _operation(scope: Scope) -> str:
    """``"<METHOD> <route-template>"`` - the template, so cardinality is bounded."""
    route = scope.get("route")
    template = getattr(route, "path", None) or "unmatched"
    return f"{scope['method']} {template}"


def _record(operation: str, outcome: str, elapsed: float) -> None:
    REQUEST_LATENCY.labels(operation=operation).observe(elapsed)
    OPERATIONS_TOTAL.labels(operation=operation, outcome=outcome).inc()


class MetricsMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] in _SKIP_PATHS:
            await self.app(scope, receive, send)
            return

        status = 500  # if start is never sent, treat it as a server error
        start = time.perf_counter()

        async def send_wrapper(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception:
            # Exactly one record path per request - no `finally` (double count).
            _record(_operation(scope), "5xx", time.perf_counter() - start)
            raise
        else:
            _record(
                _operation(scope), f"{status // 100}xx", time.perf_counter() - start
            )

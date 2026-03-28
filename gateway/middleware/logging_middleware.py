import time
import uuid
import structlog
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from prometheus_client import Counter, Histogram

logger = structlog.get_logger()

# Prometheus metrics
REQUEST_COUNT = Counter(
    "gateway_requests_total",
    "Total requests processed",
    ["method", "path", "status"],
)
REQUEST_LATENCY = Histogram(
    "gateway_request_duration_seconds",
    "Request latency in seconds",
    ["method", "path"],
)


class LoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # assign correlation ID early
        correlation_id = request.headers.get("X-Correlation-ID", str(uuid.uuid4()))
        request.state.correlation_id = correlation_id

        start = time.time()

        log = logger.bind(
            correlation_id=correlation_id,
            method=request.method,
            path=request.url.path,
            client_ip=request.client.host,
        )

        log.info("request_received")

        try:
            response = await call_next(request)
            latency = time.time() - start

            log.info(
                "request_completed",
                status=response.status_code,
                latency_ms=round(latency * 1000, 2),
            )

            # record metrics
            REQUEST_COUNT.labels(
                method=request.method,
                path=request.url.path,
                status=response.status_code,
            ).inc()
            REQUEST_LATENCY.labels(
                method=request.method,
                path=request.url.path,
            ).observe(latency)

            response.headers["X-Correlation-ID"] = correlation_id
            return response

        except Exception as e:
            latency = time.time() - start
            log.error("request_failed", error=str(e), latency_ms=round(latency * 1000, 2))
            raise
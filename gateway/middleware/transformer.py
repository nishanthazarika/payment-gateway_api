import uuid
import time
from gateway.config import Route


class RequestTransformer:
    """
    Transforms requests before forwarding to backend services:
    - Adds correlation ID for distributed tracing
    - Strips path prefixes (e.g., /api/v1/users/123 -> /users/123)
    - Injects custom headers from route config
    - Adds timing headers
    - Removes sensitive client headers
    """

    STRIP_HEADERS = {
        "host", "connection", "keep-alive",
        "transfer-encoding", "te", "trailer",
        "upgrade", "proxy-authorization",
    }

    def transform_request(
        self, headers: dict, path: str, route: Route, client_ip: str
    ) -> tuple[dict, str]:
        """Returns (transformed_headers, transformed_path)."""
        new_headers = {}

        # copy safe headers
        for k, v in headers.items():
            if k.lower() not in self.STRIP_HEADERS:
                new_headers[k] = v

        # add correlation ID for tracing
        correlation_id = headers.get("X-Correlation-ID", str(uuid.uuid4()))
        new_headers["X-Correlation-ID"] = correlation_id

        # add gateway metadata
        new_headers["X-Forwarded-For"] = client_ip
        new_headers["X-Gateway-Timestamp"] = str(time.time())
        new_headers["X-Forwarded-Host"] = headers.get("host", "")

        # inject route-specific headers
        for k, v in route.add_headers.items():
            new_headers[k] = v

        # strip prefix from path
        new_path = path
        if route.strip_prefix and path.startswith(route.strip_prefix):
            new_path = path[len(route.strip_prefix):] or "/"

        return new_headers, new_path

    def transform_response(self, headers: dict, correlation_id: str, latency_ms: float) -> dict:
        """Add gateway headers to the response going back to the client."""
        new_headers = dict(headers)
        new_headers["X-Correlation-ID"] = correlation_id
        new_headers["X-Gateway-Latency-Ms"] = f"{latency_ms:.2f}"
        new_headers.pop("transfer-encoding", None)
        return new_headers
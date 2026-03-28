import time
import httpx
import structlog
from fastapi import Request, Response
from gateway.config import Route
from gateway.balancer.load_balancer import LoadBalancer
from gateway.middleware.circuit_breaker import CircuitBreaker
from gateway.middleware.transformer import RequestTransformer

logger = structlog.get_logger()


class ReverseProxy:
    def __init__(self, balancer: LoadBalancer, breaker: CircuitBreaker):
        self.balancer = balancer
        self.breaker = breaker
        self.transformer = RequestTransformer()
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0, connect=5.0),
            follow_redirects=True,
            limits=httpx.Limits(max_connections=200, max_keepalive_connections=50),
        )

    async def forward(self, request: Request, route: Route) -> Response:
        # check circuit breaker
        if not self.breaker.can_execute(route.service):
            state = self.breaker.get_state(route.service)
            logger.warning("circuit_open", service=route.service, state=state.value)
            return Response(
                content=f'{{"error": "Service {route.service} is temporarily unavailable"}}',
                status_code=503,
                media_type="application/json",
                headers={"Retry-After": "30"},
            )

        # pick a target via load balancer
        target = self.balancer.pick_target(route.service, route.targets)
        if not target:
            return Response(
                content='{"error": "No healthy targets available"}',
                status_code=502,
                media_type="application/json",
            )

        # transform request
        raw_headers = dict(request.headers)
        client_ip = request.client.host
        headers, path = self.transformer.transform_request(
            raw_headers, request.url.path, route, client_ip
        )
        correlation_id = headers.get("X-Correlation-ID", "")

        # build target URL
        url = f"{target.url}{path}"
        if request.url.query:
            url += f"?{request.url.query}"

        # read request body
        body = await request.body()

        # forward request
        self.balancer.on_request_start(target.url)
        start = time.time()

        try:
            resp = await self.client.request(
                method=request.method,
                url=url,
                headers=headers,
                content=body,
                timeout=route.timeout,
            )

            latency_ms = (time.time() - start) * 1000
            self.balancer.on_request_end(target.url)

            # record success/failure based on status code
            if resp.status_code >= 500:
                self.breaker.on_failure(route.service)
            else:
                self.breaker.on_success(route.service)

            # transform response
            resp_headers = self.transformer.transform_response(
                dict(resp.headers), correlation_id, latency_ms
            )

            return Response(
                content=resp.content,
                status_code=resp.status_code,
                headers=resp_headers,
                media_type=resp.headers.get("content-type"),
            )

        except httpx.TimeoutException:
            self.balancer.on_request_end(target.url)
            self.breaker.on_failure(route.service)
            logger.error("upstream_timeout", service=route.service, target=target.url)
            return Response(
                content='{"error": "Upstream service timed out"}',
                status_code=504,
                media_type="application/json",
            )

        except httpx.ConnectError:
            self.balancer.on_request_end(target.url)
            self.breaker.on_failure(route.service)
            logger.error("upstream_unreachable", service=route.service, target=target.url)
            return Response(
                content='{"error": "Upstream service unreachable"}',
                status_code=502,
                media_type="application/json",
            )

    async def close(self):
        await self.client.aclose()
import redis.asyncio as redis
import structlog
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Response
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST

from gateway.config import load_config
from gateway.router.route_matcher import RouteMatcher
from gateway.balancer.load_balancer import LoadBalancer, Strategy
from gateway.middleware.rate_limiter import RateLimiter, RateLimitMiddleware
from gateway.middleware.auth import AuthMiddleware
from gateway.middleware.circuit_breaker import CircuitBreaker
from gateway.middleware.logging_middleware import LoggingMiddleware
from gateway.proxy import ReverseProxy

# configure structured logging
#this creates a log that is used in debugging without log-levels we wont be do any kind of debugging and all and can only see gateway and all. 
structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        structlog.dev.ConsoleRenderer(),
    ]
)
# it helps to create a logger opject that can be used anywhre 
logger = structlog.get_logger()

# load configuration
# this gives api gateway config likely from yaml 
config = load_config()

# initialize components
redis_client = redis.Redis(host="localhost", port=6379, decode_responses=True)
route_matcher = RouteMatcher()
balancer = LoadBalancer(strategy=Strategy.WEIGHTED_ROUND_ROBIN)
breaker = CircuitBreaker(
    failure_threshold=config.cb_failure_threshold,
    recovery_timeout=config.cb_recovery_timeout,
    half_open_max=config.cb_half_open_max,
)
proxy = ReverseProxy(balancer=balancer, breaker=breaker)

# register all routes
for route in config.routes:
    route_matcher.add_route(route)
    logger.info("route_registered", path=route.path, service=route.service,
                targets=[t.url for t in route.targets])


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("gateway_starting", host=config.host, port=config.port)
    yield
    # cleanup
    await proxy.close()
    await redis_client.close()
    logger.info("gateway_stopped")


app = FastAPI(title="API Gateway", lifespan=lifespan)
# ---- Middleware stack (order matters! last added = first executed) ----
# 4. Logging (outermost — runs first)
app.add_middleware(LoggingMiddleware)
# 3. Rate limiting
rate_limiter = RateLimiter(redis_client, rpm=config.rate_limit_rpm, burst=config.rate_limit_burst)
app.add_middleware(RateLimitMiddleware, limiter=rate_limiter, enabled=config.rate_limit_enabled)
# 2. Authentication
app.add_middleware(
    AuthMiddleware,
    secret=config.jwt_secret,
    algorithm=config.jwt_algorithm,
    redis_client=redis_client,
    public_paths=config.public_paths,
    enabled=config.auth_enabled,
)
# 1. Proxy handler (innermost — runs last)


# ---- Health & admin endpoints ----

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "circuits": breaker.get_all_states(),
    }


@app.get("/metrics")
async def metrics():
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/admin/routes")
async def list_routes():
    return {
        "routes": [
            {
                "path": r.path,
                "service": r.service,
                "methods": r.methods,
                "targets": [{"url": t.url, "healthy": t.healthy, "weight": t.weight} for t in r.targets],
            }
            for r in config.routes
        ]
    }


# ---- Catch-all route: the actual gateway proxy ----

@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
async def gateway_proxy(request: Request, path: str):
    full_path = f"/{path}"

    # match route
    route, params = route_matcher.match(full_path, request.method)

    if not route:
        return Response(
            content='{"error": "No route matched", "path": "' + full_path + '"}',
            status_code=404,
            media_type="application/json",
        )

    # store path params and route-specific overrides on request state
    request.state.path_params = params
    request.state.rate_limit_override = route.rate_limit_override

    # forward through the reverse proxy
    return await proxy.forward(request, route)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=config.host, port=config.port)
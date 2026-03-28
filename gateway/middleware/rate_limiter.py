import time
import redis.asyncio as redis
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

# Lua script runs atomically in Redis — no race conditions
TOKEN_BUCKET_SCRIPT = """
local key = KEYS[1]
local capacity = tonumber(ARGV[1])
local refill_rate = tonumber(ARGV[2])
local now = tonumber(ARGV[3])

local bucket = redis.call('HMGET', key, 'tokens', 'last_refill')
local tokens = tonumber(bucket[1])
local last_refill = tonumber(bucket[2])

if tokens == nil then
    tokens = capacity
    last_refill = now
end

-- calculate tokens to add since last refill
local elapsed = now - last_refill
local new_tokens = elapsed * refill_rate
tokens = math.min(capacity, tokens + new_tokens)

local allowed = 0
if tokens >= 1 then
    tokens = tokens - 1
    allowed = 1
end

redis.call('HMSET', key, 'tokens', tokens, 'last_refill', now)
redis.call('EXPIRE', key, 120)

return {allowed, math.ceil(tokens)}
"""


class RateLimiter:
    def __init__(self, redis_client: redis.Redis, rpm: int = 60, burst: int = 10):
        self.redis = redis_client
        self.rpm = rpm
        self.burst = burst
        self._script_sha = None

    async def _ensure_script(self):
        if self._script_sha is None:
            self._script_sha = await self.redis.script_load(TOKEN_BUCKET_SCRIPT)

    async def is_allowed(self, client_id: str, override_rpm: int | None = None) -> tuple[bool, int]:
        """
        Returns (allowed: bool, remaining_tokens: int).
        Uses token bucket algorithm via atomic Lua script.
        """
        await self._ensure_script()

        rpm = override_rpm or self.rpm
        refill_rate = rpm / 60.0  # tokens per second
        capacity = self.burst
        now = time.time()
        key = f"rl:{client_id}"

        result = await self.redis.evalsha(
            self._script_sha, 1, key,
            str(capacity), str(refill_rate), str(now)
        )

        allowed = bool(result[0])
        remaining = int(result[1])
        return allowed, remaining


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, limiter: RateLimiter, enabled: bool = True):
        super().__init__(app)
        self.limiter = limiter
        self.enabled = enabled

    async def dispatch(self, request: Request, call_next):
        if not self.enabled:
            return await call_next(request)

        # identify client by API key or IP
        client_id = request.headers.get("X-API-Key") or request.client.host

        # check for route-specific override (set by router middleware)
        override = getattr(request.state, "rate_limit_override", None)

        allowed, remaining = await self.limiter.is_allowed(client_id, override)

        if not allowed:
            return Response(
                content='{"error": "Rate limit exceeded. Try again later."}',
                status_code=429,
                media_type="application/json",
                headers={
                    "X-RateLimit-Remaining": str(remaining),
                    "Retry-After": "10",
                },
            )

        response = await call_next(request)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        return response
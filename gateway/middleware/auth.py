import jwt
import time
import redis.asyncio as redis
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
import json


class AuthMiddleware(BaseHTTPMiddleware):
    def __init__(
        self, app, secret: str, algorithm: str,
        redis_client: redis.Redis, public_paths: list[str],
        enabled: bool = True
    ):
        super().__init__(app)
        self.secret = secret
        self.algorithm = algorithm
        self.redis = redis_client
        self.public_paths = public_paths
        self.enabled = enabled

    async def dispatch(self, request: Request, call_next):
        if not self.enabled:
            return await call_next(request)

        # skip auth for public paths
        if self._is_public(request.url.path):
            return await call_next(request)

        # extract token
        auth_header = request.headers.get("Authorization", "")
        api_key = request.headers.get("X-API-Key", "")

        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
            payload = await self._validate_jwt(token)
            if payload is None:
                return self._unauthorized("Invalid or expired JWT token")
            request.state.user = payload
            request.state.auth_method = "jwt"

        elif api_key:
            valid = await self._validate_api_key(api_key)
            if not valid:
                return self._unauthorized("Invalid API key")
            request.state.user = {"api_key": api_key}
            request.state.auth_method = "api_key"

        else:
            return self._unauthorized("Missing authentication credentials")

        return await call_next(request)

    async def _validate_jwt(self, token: str) -> dict | None:
        # check cache first
        cache_key = f"auth:jwt:{token[:32]}"
        cached = await self.redis.get(cache_key)
        if cached:
            return json.loads(cached)

        try:
            payload = jwt.decode(token, self.secret, algorithms=[self.algorithm])

            # cache for remaining token lifetime (max 5 minutes)
            exp = payload.get("exp", 0)
            ttl = min(300, max(0, int(exp - time.time())))
            if ttl > 0:
                await self.redis.setex(cache_key, ttl, json.dumps(payload))

            return payload
        except jwt.ExpiredSignatureError:
            return None
        except jwt.InvalidTokenError:
            return None

    async def _validate_api_key(self, key: str) -> bool:
        # check if API key exists in Redis set
        return await self.redis.sismember("api_keys", key)

    def _is_public(self, path: str) -> bool:
        return any(path.startswith(p) for p in self.public_paths)

    @staticmethod
    def _unauthorized(msg: str) -> Response:
        return Response(
            content=json.dumps({"error": msg}),
            status_code=401,
            media_type="application/json",
        )
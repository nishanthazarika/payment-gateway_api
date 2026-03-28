import yaml
import os
from dataclasses import dataclass, field


@dataclass
class Target:
    url: str
    weight: int = 1
    healthy: bool = True


@dataclass
class Route:
    path: str
    service: str
    targets: list[Target]
    methods: list[str] = field(default_factory=lambda: ["GET"])
    prefix_match: bool = False
    strip_prefix: str = ""
    add_headers: dict = field(default_factory=dict)
    rate_limit_override: int | None = None
    timeout: int = 5


@dataclass
class GatewayConfig:
    host: str = "0.0.0.0"
    port: int = 8000
    routes: list[Route] = field(default_factory=list)
    rate_limit_rpm: int = 60
    rate_limit_burst: int = 10
    rate_limit_enabled: bool = True
    auth_enabled: bool = True
    jwt_secret: str = "change-me"
    jwt_algorithm: str = "HS256"
    public_paths: list[str] = field(default_factory=list)
    cb_failure_threshold: int = 5
    cb_recovery_timeout: int = 30
    cb_half_open_max: int = 3


def load_config(path: str = "config/routes.yaml") -> GatewayConfig:
    config_path = os.environ.get("GATEWAY_CONFIG", path)
    with open(config_path) as f:
        raw = yaml.safe_load(f)

    gw = raw.get("gateway", {})
    rl = raw.get("rate_limiting", {})
    auth = raw.get("auth", {})
    cb = raw.get("circuit_breaker", {})

    routes = []
    for r in raw.get("routes", []):
        targets = [Target(url=t["url"], weight=t.get("weight", 1)) for t in r.get("targets", [])]
        routes.append(Route(
            path=r["path"],
            service=r["service"],
            targets=targets,
            methods=r.get("methods", ["GET"]),
            prefix_match=r.get("prefix_match", False),
            strip_prefix=r.get("strip_prefix", ""),
            add_headers=r.get("add_headers", {}),
            rate_limit_override=r.get("rate_limit_override"),
            timeout=r.get("timeout", 5),
        ))

    return GatewayConfig(
        host=gw.get("host", "0.0.0.0"),
        port=gw.get("port", 8000),
        routes=routes,
        rate_limit_rpm=rl.get("requests_per_minute", 60),
        rate_limit_burst=rl.get("burst_size", 10),
        rate_limit_enabled=rl.get("enabled", True),
        auth_enabled=auth.get("enabled", True),
        jwt_secret=auth.get("jwt_secret", "change-me"),
        jwt_algorithm=auth.get("jwt_algorithm", "HS256"),
        public_paths=auth.get("public_paths", []),
        cb_failure_threshold=cb.get("failure_threshold", 5),
        cb_recovery_timeout=cb.get("recovery_timeout", 30),
        cb_half_open_max=cb.get("half_open_max_calls", 3),
    )
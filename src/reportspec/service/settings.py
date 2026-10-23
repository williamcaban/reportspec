"""Service settings. Everything has a safe default and can be set by environment variable or `reportspec serve` flag."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


@dataclass
class Settings:
    playground: bool = field(default_factory=lambda: os.environ.get("REPORTSPEC_PLAYGROUND", "") in ("1", "true", "yes"))
    docs: bool = field(default_factory=lambda: os.environ.get("REPORTSPEC_DOCS", "1") in ("1", "true", "yes"))
    api_token: str | None = field(default_factory=lambda: os.environ.get("REPORTSPEC_API_TOKEN") or None)
    cors_origins: list[str] = field(default_factory=lambda: [o for o in os.environ.get("REPORTSPEC_CORS_ORIGINS", "").split(",") if o])
    max_body_bytes: int = field(default_factory=lambda: _env_int("REPORTSPEC_MAX_BODY_MB", 5) * 1024 * 1024)
    max_inputs: int = field(default_factory=lambda: _env_int("REPORTSPEC_MAX_INPUTS", 16))
    render_timeout: float = field(default_factory=lambda: _env_float("REPORTSPEC_RENDER_TIMEOUT", 60.0))
    max_concurrency: int = field(default_factory=lambda: _env_int("REPORTSPEC_MAX_CONCURRENCY", 2))
    queue_timeout: float = field(default_factory=lambda: _env_float("REPORTSPEC_QUEUE_TIMEOUT", 10.0))

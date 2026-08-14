"""
backend/config.py
─────────────────
Centralised settings for the Datify backend, loaded from environment
variables (or a .env file at the project root / backend directory).

Usage
-----
    from backend.config import settings

    image = settings.SANDBOX_IMAGE
"""

from __future__ import annotations

import os
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Application-wide settings resolved from environment variables.
    Pydantic-settings automatically reads from a .env file when present.
    """

    model_config = SettingsConfigDict(
        # Look for .env in the backend/ directory first, then the repo root.
        env_file=(
            os.path.join(os.path.dirname(__file__), ".env"),
            os.path.join(os.path.dirname(os.path.dirname(__file__)), "datify-mvp", ".env"),
        ),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── LLM ────────────────────────────────────────────────────────────────────
    ANTHROPIC_API_KEY: str = ""

    # ── Docker Sandbox ──────────────────────────────────────────────────────────
    # Pre-built image that the sandbox container will run.
    # Build with: docker build -t datify-sandbox:latest ./backend
    SANDBOX_IMAGE: str = "datify-sandbox:latest"

    # Hard memory cap enforced per container.
    SANDBOX_MEM_LIMIT: str = "256m"

    # Wall-clock timeout in seconds before the container is force-killed.
    SANDBOX_TIMEOUT_SEC: int = 10


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached singleton Settings instance."""
    return Settings()


# Convenience alias — import `settings` directly for most use-cases.
settings: Settings = get_settings()

"""Central configuration, loaded from environment (.env supported)."""
import os
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv(override=True)  # .env always wins over stale OS env vars


class Settings:
    # --- database (your Zoho -> Postgres warehouse) ---
    DATABASE_URL: str = os.environ.get(
        "DATABASE_URL",
        "postgresql://postgres:password@localhost:5432/the_balaji",
    )

    # --- LLM provider ---
    LLM_PROVIDER: str = os.environ.get("LLM_PROVIDER", "anthropic")  # anthropic | openai
    ANTHROPIC_API_KEY: str = os.environ.get("ANTHROPIC_API_KEY", "")
    # identity-linked keys must say which workspace the request runs in
    ANTHROPIC_WORKSPACE_ID: str = os.environ.get("ANTHROPIC_WORKSPACE_ID", "")
    OPENAI_API_KEY: str = os.environ.get("OPENAI_API_KEY", "")
    MODEL: str = os.environ.get("MODEL", "claude-sonnet-5")

    # --- guardrails / limits ---
    MAX_ROWS: int = int(os.environ.get("MAX_ROWS", "500"))
    STATEMENT_TIMEOUT_MS: int = int(os.environ.get("STATEMENT_TIMEOUT_MS", "15000"))

    # --- app ---
    CURRENCY: str = os.environ.get("CURRENCY", "₹")
    CORS_ORIGINS: list = os.environ.get(
        "CORS_ORIGINS", "http://localhost:3000"
    ).split(",")
    ORG_NAME: str = os.environ.get("ORG_NAME", "The Balaji Industries")


@lru_cache
def get_settings() -> "Settings":
    return Settings()

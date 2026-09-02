"""Central configuration, loaded from environment (.env supported)."""
import os
from functools import lru_cache

from dotenv import load_dotenv

if os.environ.get("GANAK_SKIP_DOTENV") != "1":
    load_dotenv(override=True)  # .env always wins over stale OS env vars

# backend/  (this file is backend/app/config.py)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class Settings:
    # --- default tenant data warehouse (The Balaji's Zoho -> Postgres) ---
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
    MODEL: str = os.environ.get("MODEL", "claude-haiku-4-5-20251001")
    # occasional PDF extraction uses a stronger model for accuracy
    EXTRACT_MODEL: str = os.environ.get("EXTRACT_MODEL", "claude-sonnet-5")

    # --- guardrails / limits ---
    MAX_ROWS: int = int(os.environ.get("MAX_ROWS", "500"))
    STATEMENT_TIMEOUT_MS: int = int(os.environ.get("STATEMENT_TIMEOUT_MS", "15000"))

    # --- multi-tenant control plane + auth ---
    CONTROL_DB_PATH: str = os.environ.get(
        "CONTROL_DB_PATH", os.path.join(BASE_DIR, "ganak_control.db")
    )
    # where per-company SQLite warehouses (demo + self-serve signups) live
    TENANTS_DIR: str = os.environ.get("TENANTS_DIR", os.path.join(BASE_DIR, "tenants"))
    DEMO_DB_PATH: str = os.environ.get("DEMO_DB_PATH", os.path.join(TENANTS_DIR, "demo_traders.db"))
    AUTH_SECRET: str = os.environ.get("GANAK_AUTH_SECRET", "dev-only-change-me")
    TOKEN_TTL_SECONDS: int = int(os.environ.get("TOKEN_TTL_SECONDS", str(7 * 24 * 3600)))
    SEED_DEMO: bool = os.environ.get("SEED_DEMO", "1") != "0"

    # --- pay-as-you-go wallet ---
    USD_INR: float = float(os.environ.get("USD_INR", "88"))
    BILLING_MARKUP: float = float(os.environ.get("BILLING_MARKUP", "3.0"))
    SEED_BALANCE_INR: float = float(os.environ.get("SEED_BALANCE_INR", "100"))
    SIGNUP_BONUS_INR: float = float(os.environ.get("SIGNUP_BONUS_INR", "20"))

    # --- live Zoho Books access (answer without loading to the warehouse) ---
    ZOHO_REFRESH_TOKEN: str = os.environ.get("ZOHO_REFRESH_TOKEN", "")
    ZOHO_CLIENT_ID: str = os.environ.get("ZOHO_CLIENT_ID", "")
    ZOHO_CLIENT_SECRET: str = os.environ.get("ZOHO_CLIENT_SECRET", "")
    ZOHO_ORG_ID: str = os.environ.get("ZOHO_ORG_ID", "")
    ZOHO_BASE_URL: str = os.environ.get("ZOHO_BASE_URL", "https://www.zohoapis.in/books/v3")
    ZOHO_ACCOUNTS_URL: str = os.environ.get("ZOHO_ACCOUNTS_URL", "https://accounts.zoho.in")

    # --- app ---
    CURRENCY: str = os.environ.get("CURRENCY", "₹")
    CORS_ORIGINS: list = os.environ.get(
        "CORS_ORIGINS", "http://localhost:3000"
    ).split(",")
    ORG_NAME: str = os.environ.get("ORG_NAME", "The Balaji Industries")


@lru_cache
def get_settings() -> "Settings":
    return Settings()

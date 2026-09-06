"""Self-serve Zoho Books connector.

Any tenant can click "Connect Zoho" and authorize THEIR OWN Zoho org --
this is a real multi-tenant OAuth flow, distinct from app/zoho_live.py
(Balaji's single hardcoded org via env vars) and from
PyProject/zoho_postgres_sync.py (Balaji's own local script). The OAuth
client here (ZOHO_OAUTH_CLIENT_ID/SECRET) is a "Server-based Application"
client registered once in the Zoho API Console; every tenant authorizes
against that same client and gets their own refresh token.

Sync logic reuses the two real-data bug fixes verified against Balaji's
warehouse on 6 Sept 2026 (see PyProject/zoho_postgres_sync.py history):
  1. flatten_json_columns() prefixes flattened dict columns with their
     parent column name, so sibling dict fields sharing key names
     (billing_address vs shipping_address) can never collide.
  2. any column still holding raw list/dict values (e.g. items.tags,
     items.item_tax_preferences) is JSON-encoded before the Postgres
     insert, since psycopg2 cannot adapt a Python list/dict directly.
Date-shaped columns are also coerced to real timestamps at sync time
(the bug that broke Balaji's expense questions after a plain to_sql())
so a fresh self-serve tenant never hits that class of bug at all.
"""
import json
import logging
import re
import time
from datetime import datetime
from typing import Optional

import pandas as pd
import requests
from sqlalchemy import create_engine, text

from .config import get_settings
from . import crypto, tenancy

log = logging.getLogger("ganak.connectors.zoho")
settings = get_settings()

PROVIDER = "zoho"

# Zoho's default accounts server for authorization; the token response tells
# us the actual api_domain to use afterward, so this only matters for the
# initial redirect (fine for India-based orgs, our primary market today).
DEFAULT_ACCOUNTS_URL = "https://accounts.zoho.in"

ENTITIES = {
    "invoices": "invoices",
    "expenses": "expenses",
    "bills": "bills",
    "banktransactions": "banktransactions",
    "customers": "contacts",
    "vendors": "vendors",
    "items": "items",
    "salesorders": "salesorders",
    "purchaseorders": "purchaseorders",
    "payments": "customerpayments",
    "vendor_payments": "vendorpayments",
}

_DATE_NAME_RE = re.compile(
    r"(^date$)|(_date$)|(^date_)|(_time$)|(^created_time$)|(^last_modified_time$)",
    re.IGNORECASE,
)


def configured() -> bool:
    return bool(settings.ZOHO_OAUTH_CLIENT_ID and settings.ZOHO_OAUTH_CLIENT_SECRET)


# ---------------- OAuth ----------------
def authorize_url(state: str) -> str:
    redirect_uri = f"{settings.PUBLIC_API_BASE_URL}/connectors/zoho/callback"
    params = {
        "scope": settings.ZOHO_OAUTH_SCOPE,
        "client_id": settings.ZOHO_OAUTH_CLIENT_ID,
        "response_type": "code",
        "access_type": "offline",  # required to receive a refresh_token
        "redirect_uri": redirect_uri,
        "prompt": "consent",
        "state": state,
    }
    qs = "&".join(f"{k}={requests.utils.quote(str(v), safe='')}" for k, v in params.items())
    return f"{DEFAULT_ACCOUNTS_URL}/oauth/v2/auth?{qs}"


def exchange_code(code: str) -> dict:
    """Returns Zoho's raw token response: access_token, refresh_token,
    expires_in, api_domain (which regional Books API to call from here on)."""
    redirect_uri = f"{settings.PUBLIC_API_BASE_URL}/connectors/zoho/callback"
    resp = requests.post(
        f"{DEFAULT_ACCOUNTS_URL}/oauth/v2/token",
        data={
            "code": code,
            "client_id": settings.ZOHO_OAUTH_CLIENT_ID,
            "client_secret": settings.ZOHO_OAUTH_CLIENT_SECRET,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        },
        timeout=20,
    )
    data = resp.json()
    if "access_token" not in data:
        raise RuntimeError(f"Zoho code exchange failed: {data}")
    return data


def refresh_access_token(refresh_token: str) -> dict:
    resp = requests.post(
        f"{DEFAULT_ACCOUNTS_URL}/oauth/v2/token",
        data={
            "refresh_token": refresh_token,
            "client_id": settings.ZOHO_OAUTH_CLIENT_ID,
            "client_secret": settings.ZOHO_OAUTH_CLIENT_SECRET,
            "grant_type": "refresh_token",
        },
        timeout=20,
    )
    data = resp.json()
    if "access_token" not in data:
        raise RuntimeError(f"Zoho token refresh failed: {data}")
    return data


def list_organizations(access_token: str, api_domain: str) -> list:
    resp = requests.get(
        f"{api_domain}/books/v3/organizations",
        headers={"Authorization": f"Zoho-oauthtoken {access_token}"},
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json().get("organizations", [])


def _valid_access_token(connector: dict) -> tuple[str, str]:
    """Returns (access_token, api_domain), refreshing if the stored access
    token is missing/expired. api_domain is stored in `scopes` as a cheap
    reuse of an existing free-text column (see upsert call below)."""
    api_domain = connector.get("scopes") or "https://www.zohoapis.in"
    access_token = crypto.decrypt(connector.get("access_token_enc") or "")
    if access_token and time.time() < (connector.get("token_expires_at") or 0) - 60:
        return access_token, api_domain
    refresh_token = crypto.decrypt(connector["refresh_token_enc"])
    data = refresh_access_token(refresh_token)
    access_token = data["access_token"]
    api_domain = data.get("api_domain", api_domain)
    tenancy.update_connector_access_token(
        connector["id"], crypto.encrypt(access_token), time.time() + int(data.get("expires_in", 3600))
    )
    return access_token, api_domain


# ---------------- data transform (verified fixes, see module docstring) ----------------
def _flatten_json_columns(df: pd.DataFrame, max_depth: int = 1) -> pd.DataFrame:
    for col in list(df.columns):
        if col not in df.columns:
            continue
        if max_depth > 0 and df[col].dtype == "object":
            try:
                sample = df[col].iloc[0] if len(df) > 0 else None
                if isinstance(sample, dict):
                    expanded = pd.json_normalize(df[col], sep="_").add_prefix(f"{col}_")
                    df = pd.concat([df.drop(col, axis=1), expanded], axis=1)
                    df = df.loc[:, ~df.columns.duplicated()]
            except Exception as err:
                log.debug(f"could not flatten column {col}: {err}")
    return df


def _coerce_date_columns(df: pd.DataFrame) -> None:
    for col in df.columns:
        if not _DATE_NAME_RE.search(col):
            continue
        if pd.api.types.is_datetime64_any_dtype(df[col]):
            continue
        non_null = df[col].notna().sum()
        if non_null == 0:
            continue
        parsed = pd.to_datetime(df[col], errors="coerce", utc=False)
        if parsed.notna().sum() >= 0.9 * non_null:
            df[col] = parsed


def _prepare_for_postgres(df: pd.DataFrame, table_name: str) -> pd.DataFrame:
    df.columns = [c.lower().replace(" ", "_").replace("-", "_") for c in df.columns]
    if df.columns.duplicated().any():
        dupes = df.columns[df.columns.duplicated()].tolist()
        log.warning(f"dropping duplicate columns in {table_name}: {dupes}")
        df = df.loc[:, ~df.columns.duplicated()]

    for col in df.columns:
        if df[col].dtype == "object":
            sample = df[col].dropna()
            if len(sample) and sample.map(lambda v: isinstance(v, (list, dict))).any():
                df[col] = df[col].apply(lambda v: json.dumps(v) if isinstance(v, (list, dict)) else v)

    _coerce_date_columns(df)

    for col in df.columns:
        if df[col].dtype == "object":
            nn = df[col].dropna()
            if len(nn) and nn.isin([True, False, "true", "false", "True", "False"]).all():
                df[col] = df[col].map(
                    {"true": True, "false": False, "True": True, "False": False, True: True, False: False}
                )
    return df


def _fetch_paginated(api_domain: str, endpoint: str, item_key: str, access_token: str, org_id: str,
                      max_pages: int = 999) -> list:
    all_items: list = []
    page = 1
    headers = {"Authorization": f"Zoho-oauthtoken {access_token}"}
    while page <= max_pages:
        resp = requests.get(
            f"{api_domain}/books/v3/{endpoint}",
            headers=headers,
            params={"organization_id": org_id, "page": page, "per_page": 200},
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
        items = data.get(item_key, [])
        if not items:
            break
        all_items.extend(items)
        if not data.get("page_context", {}).get("has_more_page", False):
            break
        page += 1
        time.sleep(0.4)  # respect Zoho rate limits
    return all_items


def _engine_for_tenant(tenant: dict):
    db_url = tenant["db_url"]
    schema = tenant.get("db_schema") or None
    engine = create_engine(db_url)
    if schema:
        with engine.connect() as c:
            c.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))
            c.commit()
    return engine, schema


def run_full_sync(tenant: dict, connector: dict) -> dict:
    """Pulls every entity for this tenant's Zoho org into their own
    schema/db. Safe to re-run (each table is replaced wholesale)."""
    access_token, api_domain = _valid_access_token(connector)
    org_id = connector["org_id"]
    engine, schema = _engine_for_tenant(tenant)

    results = {}
    for table_name, endpoint in ENTITIES.items():
        item_key = endpoint if endpoint.endswith("s") else f"{endpoint}s"
        try:
            items = _fetch_paginated(api_domain, endpoint, item_key, access_token, org_id)
            if not items:
                results[table_name] = 0
                continue
            df = _flatten_json_columns(pd.DataFrame(items))
            df = _prepare_for_postgres(df, table_name)
            df.to_sql(table_name, engine, schema=schema, if_exists="replace", index=False,
                      method="multi", chunksize=500)
            results[table_name] = len(df)
        except Exception as e:
            log.error(f"zoho sync failed for {table_name} (tenant {tenant['id']}): {e}")
            results[table_name] = f"error: {e}"
    return results

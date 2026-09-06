"""Self-serve Gmail connector.

Any tenant can click "Connect Gmail" and authorize THEIR OWN mailbox -- a
real multi-tenant OAuth flow using a Google "Web application" OAuth client
(GOOGLE_OAUTH_CLIENT_ID/SECRET), distinct from the Desktop-app credentials.json
used by backend/connectors/gmail_sync.py for Balaji's own local script.

IMPORTANT LIMITATION (not something this code can work around): gmail.readonly
is a Google "sensitive" scope. Until the OAuth consent screen for this client
passes Google's app verification, only test users explicitly added in Google
Cloud Console -> OAuth consent screen -> Test users can complete this flow;
anyone else sees an "unverified app" warning and, once past that, still needs
to be a listed test user or the request is blocked outright. This module
implements the real flow either way, since verification and testing are a
separate, later step from having the plumbing be correct.

Talks to Gmail directly over its REST API with `requests` (no google-auth /
google-api-python-client dependency in the main service), consistent with
how connectors_zoho.py and app/zoho_live.py talk to Zoho.
"""
import logging
import time
from datetime import datetime, timezone

import pandas as pd
import requests
from sqlalchemy import create_engine, text

from .config import get_settings
from . import crypto, tenancy
from .email_classify import classify, parse_amount, sender_domain, direction

log = logging.getLogger("ganak.connectors.gmail")
settings = get_settings()

PROVIDER = "gmail"
TOKEN_URL = "https://oauth2.googleapis.com/token"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"
GMAIL_API = "https://gmail.googleapis.com/gmail/v1"

FINANCE_QUERY = (
    'invoice OR payment OR receipt OR "amount due" OR "balance confirmation" '
    'OR quotation OR "purchase order" OR bill'
)


def configured() -> bool:
    return bool(settings.GOOGLE_OAUTH_CLIENT_ID and settings.GOOGLE_OAUTH_CLIENT_SECRET)


# ---------------- OAuth ----------------
def authorize_url(state: str) -> str:
    redirect_uri = f"{settings.PUBLIC_API_BASE_URL}/connectors/gmail/callback"
    scope = f"{settings.GOOGLE_OAUTH_SCOPE} https://www.googleapis.com/auth/userinfo.email openid"
    params = {
        "client_id": settings.GOOGLE_OAUTH_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": scope,
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": state,
    }
    qs = "&".join(f"{k}={requests.utils.quote(str(v), safe='')}" for k, v in params.items())
    return f"{AUTH_URL}?{qs}"


def exchange_code(code: str) -> dict:
    redirect_uri = f"{settings.PUBLIC_API_BASE_URL}/connectors/gmail/callback"
    resp = requests.post(
        TOKEN_URL,
        data={
            "code": code,
            "client_id": settings.GOOGLE_OAUTH_CLIENT_ID,
            "client_secret": settings.GOOGLE_OAUTH_CLIENT_SECRET,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        },
        timeout=20,
    )
    data = resp.json()
    if "access_token" not in data:
        raise RuntimeError(f"Google code exchange failed: {data}")
    return data


def refresh_access_token(refresh_token: str) -> dict:
    resp = requests.post(
        TOKEN_URL,
        data={
            "refresh_token": refresh_token,
            "client_id": settings.GOOGLE_OAUTH_CLIENT_ID,
            "client_secret": settings.GOOGLE_OAUTH_CLIENT_SECRET,
            "grant_type": "refresh_token",
        },
        timeout=20,
    )
    data = resp.json()
    if "access_token" not in data:
        raise RuntimeError(f"Google token refresh failed: {data}")
    return data


def get_email_address(access_token: str) -> str:
    resp = requests.get(USERINFO_URL, headers={"Authorization": f"Bearer {access_token}"}, timeout=15)
    resp.raise_for_status()
    return resp.json().get("email", "")


def _valid_access_token(connector: dict) -> str:
    access_token = crypto.decrypt(connector.get("access_token_enc") or "")
    if access_token and time.time() < (connector.get("token_expires_at") or 0) - 60:
        return access_token
    refresh_token = crypto.decrypt(connector["refresh_token_enc"])
    data = refresh_access_token(refresh_token)
    access_token = data["access_token"]
    tenancy.update_connector_access_token(
        connector["id"], crypto.encrypt(access_token), time.time() + int(data.get("expires_in", 3600))
    )
    return access_token


# ---------------- Gmail fetch ----------------
def _header(headers, name):
    for h in headers:
        if h["name"].lower() == name.lower():
            return h["value"]
    return ""


def _fetch_messages(access_token: str, query: str, max_messages: int = 3000):
    headers = {"Authorization": f"Bearer {access_token}"}
    page_token = None
    fetched = 0
    while True:
        resp = requests.get(
            f"{GMAIL_API}/users/me/messages",
            headers=headers,
            params={"q": query, "pageToken": page_token, "maxResults": 100},
            timeout=20,
        )
        resp.raise_for_status()
        listing = resp.json()
        for m in listing.get("messages", []):
            full = requests.get(
                f"{GMAIL_API}/users/me/messages/{m['id']}",
                headers=headers,
                params={"format": "metadata", "metadataHeaders": ["From", "To", "Subject", "Date"]},
                timeout=20,
            ).json()
            hdrs = full.get("payload", {}).get("headers", [])
            yield {
                "message_id": full["id"],
                "thread_id": full["threadId"],
                "sender": _header(hdrs, "From"),
                "recipients": _header(hdrs, "To"),
                "subject": _header(hdrs, "Subject"),
                "snippet": full.get("snippet", ""),
                "internal_date": int(full.get("internalDate", "0")),
                "label_ids": full.get("labelIds", []),
            }
            fetched += 1
            if fetched >= max_messages:
                return
        page_token = listing.get("nextPageToken")
        if not page_token:
            return


def _to_row(m: dict, self_addr: str) -> dict:
    date = datetime.fromtimestamp(m["internal_date"] / 1000, tz=timezone.utc)
    return {
        "message_id": m["message_id"],
        "thread_id": m["thread_id"],
        "email_date": date,
        "sender": m["sender"],
        "sender_domain": sender_domain(m["sender"]),
        "recipients": m["recipients"],
        "subject": m["subject"],
        "snippet": m["snippet"],
        "direction": direction(m["sender"], m["label_ids"], self_addr),
        "category": classify(m["sender"], m["subject"], m["snippet"]),
        "amount": parse_amount(m["subject"]) or parse_amount(m["snippet"]),
        "labels": ",".join(m["label_ids"]),
    }


def _engine_for_tenant(tenant: dict):
    engine = create_engine(tenant["db_url"])
    schema = tenant.get("db_schema") or None
    if schema:
        with engine.connect() as c:
            c.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))
            c.commit()
    return engine, schema


def run_sync(tenant: dict, connector: dict, mode: str = "full") -> dict:
    access_token = _valid_access_token(connector)
    self_addr = connector.get("account_label") or ""
    engine, schema = _engine_for_tenant(tenant)

    query = FINANCE_QUERY
    if mode == "incremental":
        try:
            with engine.connect() as c:
                r = c.execute(text(f'SELECT MAX(email_date) FROM {"" if not schema else schema + "."}emails'))
                last = r.scalar()
            if last:
                query += f" after:{int(last.timestamp())}"
        except Exception:
            mode = "full"  # no table yet -- fall back to a full sync
    if mode == "full":
        query += " newer_than:1y"

    rows = [_to_row(m, self_addr) for m in _fetch_messages(access_token, query)]
    if not rows:
        return {"emails": 0}

    df = pd.DataFrame(rows)
    df.to_sql(
        "emails", engine, schema=schema,
        if_exists=("replace" if mode == "full" else "append"),
        index=False, method="multi", chunksize=500,
    )
    return {"emails": len(df)}

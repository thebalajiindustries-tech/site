"""Self-serve connector API: any tenant connects their own Gmail/Zoho.

  GET  /connectors                        this tenant's connections + status
  GET  /connectors/{provider}/start       (auth'd) returns the OAuth URL to send the browser to
  GET  /connectors/{provider}/callback    the provider redirects the BROWSER here (no auth
                                           header -- the signed `state` param carries the tenant)
  POST /connectors/{provider}/sync        (auth'd) trigger a sync now
  POST /connectors/{provider}/disconnect  (auth'd) forget this tenant's tokens

A sync (first-connect or manual) runs as a FastAPI BackgroundTask so the HTTP
response comes back immediately; the frontend polls GET /connectors to see
last_synced_at move and status flip to 'error' if something went wrong.
"""
import logging
import time

import requests
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from .config import get_settings
from . import auth, tenancy, crypto, db, connectors_zoho, connectors_gmail

log = logging.getLogger("ganak.connectors")
settings = get_settings()
router = APIRouter(prefix="/connectors", tags=["connectors"])

_MODULES = {"zoho": connectors_zoho, "gmail": connectors_gmail}


class ConnectorOut(BaseModel):
    provider: str
    connected: bool
    configured: bool = True
    status: str = ""
    account_label: str = ""
    last_synced_at: float = 0
    last_error: str = ""


def _sync_and_record(provider: str, tenant: dict, connector: dict) -> None:
    mod = _MODULES[provider]
    try:
        if provider == "zoho":
            results = mod.run_full_sync(tenant, connector)
        else:
            results = mod.run_sync(tenant, connector, mode="full")
        tenancy.mark_connector_synced(connector["id"])
        # A sync can create brand-new tables (e.g. `emails` on first Gmail
        # connect). /ask uses the CACHED schema for speed, so without this
        # the AI keeps answering as if that table doesn't exist until the
        # process restarts. /schema (used for the debug view) always
        # refreshes, which is why that looked fine while /ask didn't.
        db.invalidate_schema(tenant["db_url"], tenant.get("db_schema"))
        log.info(f"connector sync ok tenant={tenant['id']} provider={provider} results={results}")
    except Exception as e:
        tenancy.mark_connector_error(connector["id"], str(e))
        log.error(f"connector sync failed tenant={tenant['id']} provider={provider}: {e}")


@router.get("", response_model=list[ConnectorOut])
def list_connectors(ident: dict = Depends(auth.current_user)):
    tenant_id = ident["tenant"]["id"]
    existing = {c["provider"]: c for c in tenancy.list_connectors(tenant_id)}
    out = []
    for provider, mod in _MODULES.items():
        row = existing.get(provider) or {}
        out.append(ConnectorOut(
            provider=provider,
            connected=bool(row),
            configured=mod.configured(),
            status=row.get("status", ""),
            account_label=row.get("account_label", ""),
            last_synced_at=row.get("last_synced_at") or 0,
            last_error=row.get("last_error", ""),
        ))
    return out


@router.get("/{provider}/start")
def start(provider: str, ident: dict = Depends(auth.current_user)):
    mod = _MODULES.get(provider)
    if not mod:
        raise HTTPException(404, "Unknown connector.")
    if not mod.configured():
        raise HTTPException(503, f"The {provider} connector is not configured on this server yet.")
    state = auth.make_oauth_state(ident["tenant"]["id"], provider)
    return {"authorize_url": mod.authorize_url(state)}


@router.get("/{provider}/callback")
def callback(provider: str, background: BackgroundTasks, code: str = "", state: str = "", error: str = ""):
    app_url = settings.PUBLIC_APP_BASE_URL.rstrip("/")
    mod = _MODULES.get(provider)
    if not mod:
        raise HTTPException(404, "Unknown connector.")
    if error:
        return RedirectResponse(f"{app_url}/connections?error={requests.utils.quote(error)}")
    if not code:
        return RedirectResponse(f"{app_url}/connections?error=missing_code")

    tenant_id = auth.verify_oauth_state(state, provider)
    tenant = tenancy.get_tenant(tenant_id)
    if not tenant:
        return RedirectResponse(f"{app_url}/connections?error=tenant_not_found")

    try:
        token_data = mod.exchange_code(code)
        access_token = token_data["access_token"]
        refresh_token = token_data.get("refresh_token", "")
        if not refresh_token:
            # Both providers are asked for offline access + forced consent on
            # every authorization specifically so this always arrives; if it
            # didn't, something about the provider-side app config is off.
            return RedirectResponse(f"{app_url}/connections?error=no_refresh_token")
        expires_at = time.time() + int(token_data.get("expires_in", 3600))

        if provider == "zoho":
            api_domain = token_data.get("api_domain", "https://www.zohoapis.in")
            orgs = mod.list_organizations(access_token, api_domain)
            if not orgs:
                return RedirectResponse(f"{app_url}/connections?error=no_zoho_org")
            org = orgs[0]  # first-cut: the account's primary/first org
            tenancy.upsert_connector(
                tenant_id, provider,
                refresh_token_enc=crypto.encrypt(refresh_token),
                access_token_enc=crypto.encrypt(access_token),
                token_expires_at=expires_at,
                org_id=str(org.get("organization_id", "")),
                account_label=org.get("name", ""),
                scopes=api_domain,
            )
        else:  # gmail
            email = mod.get_email_address(access_token)
            tenancy.upsert_connector(
                tenant_id, provider,
                refresh_token_enc=crypto.encrypt(refresh_token),
                access_token_enc=crypto.encrypt(access_token),
                token_expires_at=expires_at,
                account_label=email,
            )

        connector = tenancy.get_connector(tenant_id, provider)
        background.add_task(_sync_and_record, provider, tenant, connector)
        return RedirectResponse(f"{app_url}/connections?connected={provider}")
    except Exception as e:
        log.error(f"oauth callback failed tenant={tenant_id} provider={provider}: {e}")
        return RedirectResponse(f"{app_url}/connections?error={requests.utils.quote(str(e)[:200])}")


@router.post("/{provider}/sync")
def sync_now(provider: str, background: BackgroundTasks, ident: dict = Depends(auth.current_user)):
    mod = _MODULES.get(provider)
    if not mod:
        raise HTTPException(404, "Unknown connector.")
    tenant = ident["tenant"]
    connector = tenancy.get_connector(tenant["id"], provider)
    if not connector:
        raise HTTPException(400, f"{provider} is not connected yet.")
    background.add_task(_sync_and_record, provider, tenant, connector)
    return {"status": "sync_started"}


@router.post("/{provider}/disconnect")
def disconnect(provider: str, ident: dict = Depends(auth.current_user)):
    if provider not in _MODULES:
        raise HTTPException(404, "Unknown connector.")
    tenancy.delete_connector(ident["tenant"]["id"], provider)
    return {"status": "disconnected"}

"""Self-serve connector API: any tenant connects their own Gmail/Zoho.

  GET  /connectors                        this tenant's connections + status
  GET  /connectors/{provider}/start       (auth'd) returns the OAuth URL to send the browser to
  GET  /connectors/{provider}/callback    the provider redirects the BROWSER here (no auth
                                           header -- the signed `state` param carries the tenant)
  GET  /connectors/zoho/pending-orgs      (no auth -- ticket itself is the secret) organizations
                                           to choose between when a Zoho account has more than one
  POST /connectors/zoho/select-org        (auth'd) finalize the connection with the chosen org
  POST /connectors/{provider}/sync        (auth'd) trigger a sync now
  POST /connectors/{provider}/disconnect  (auth'd) forget this tenant's tokens

A sync (first-connect or manual) runs as a FastAPI BackgroundTask so the HTTP
response comes back immediately; the frontend polls GET /connectors to see
last_synced_at move and status flip to 'error' if something went wrong.

A Zoho account can hold more than one organization. The callback below asks
Zoho for the account's org list and, when there's exactly one, connects it
immediately -- unchanged behaviour. When there's more than one, it does NOT
guess: it holds the freshly-obtained tokens in the in-memory ticket store
below (encrypted, same as at rest) and sends the browser to /sources to pick
one. Nothing is written to the tenants' `connectors` table until the user
actually chooses, via POST .../select-org.
"""
import logging
import secrets
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

# Pending Zoho org-selection tickets: ticket id -> {tenant_id, encrypted
# tokens, api_domain, organizations, expires_at}. Same trust model as the
# OAuth `state` param already used for the callback itself -- an
# unguessable, single-use, short-lived id standing in for a session,
# without needing a table (and a migration) for something this transient.
# Fine for a single-process deploy; a multi-worker deploy would need this
# moved to the control DB or a shared cache instead.
_ORG_TICKET_TTL_SECONDS = 600
_pending_org_tickets: dict[str, dict] = {}


def _purge_expired_org_tickets() -> None:
    now = time.time()
    for t in [t for t, v in _pending_org_tickets.items() if v["expires_at"] < now]:
        _pending_org_tickets.pop(t, None)


class SelectOrgIn(BaseModel):
    ticket: str
    organization_id: str


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
        return RedirectResponse(f"{app_url}/sources?error={requests.utils.quote(error)}")
    if not code:
        return RedirectResponse(f"{app_url}/sources?error=missing_code")

    tenant_id = auth.verify_oauth_state(state, provider)
    tenant = tenancy.get_tenant(tenant_id)
    if not tenant:
        return RedirectResponse(f"{app_url}/sources?error=tenant_not_found")

    try:
        token_data = mod.exchange_code(code)
        access_token = token_data["access_token"]
        refresh_token = token_data.get("refresh_token", "")
        if not refresh_token:
            # Both providers are asked for offline access + forced consent on
            # every authorization specifically so this always arrives; if it
            # didn't, something about the provider-side app config is off.
            return RedirectResponse(f"{app_url}/sources?error=no_refresh_token")
        expires_at = time.time() + int(token_data.get("expires_in", 3600))

        if provider == "zoho":
            api_domain = token_data.get("api_domain", "https://www.zohoapis.in")
            orgs = mod.list_organizations(access_token, api_domain)
            if not orgs:
                return RedirectResponse(f"{app_url}/sources?error=no_zoho_org")
            if len(orgs) > 1:
                # More than one organization on this Zoho account -- ask
                # which one instead of silently picking the first.
                _purge_expired_org_tickets()
                ticket = secrets.token_urlsafe(24)
                _pending_org_tickets[ticket] = {
                    "tenant_id": tenant_id,
                    "refresh_token_enc": crypto.encrypt(refresh_token),
                    "access_token_enc": crypto.encrypt(access_token),
                    "token_expires_at": expires_at,
                    "api_domain": api_domain,
                    "organizations": [
                        {"organization_id": str(o.get("organization_id", "")), "name": o.get("name", "")}
                        for o in orgs
                    ],
                    "expires_at": time.time() + _ORG_TICKET_TTL_SECONDS,
                }
                return RedirectResponse(f"{app_url}/sources?select_org=zoho&ticket={ticket}")
            org = orgs[0]  # the account's only org -- nothing to choose
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
        return RedirectResponse(f"{app_url}/sources?connected={provider}")
    except Exception as e:
        log.error(f"oauth callback failed tenant={tenant_id} provider={provider}: {e}")
        return RedirectResponse(f"{app_url}/sources?error={requests.utils.quote(str(e)[:200])}")


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


@router.get("/zoho/pending-orgs")
def zoho_pending_orgs(ticket: str):
    """No auth header on purpose -- the browser lands here straight off the
    Zoho redirect. Possession of the (unguessable, single-use) ticket is
    the same trust boundary the OAuth `state` param already relies on."""
    _purge_expired_org_tickets()
    pending = _pending_org_tickets.get(ticket)
    if not pending:
        raise HTTPException(404, "This connection attempt expired -- please try connecting again.")
    return {"organizations": pending["organizations"]}


@router.post("/zoho/select-org")
def zoho_select_org(body: SelectOrgIn, background: BackgroundTasks, ident: dict = Depends(auth.current_user)):
    _purge_expired_org_tickets()
    pending = _pending_org_tickets.get(body.ticket)
    if not pending:
        raise HTTPException(404, "This connection attempt expired -- please try connecting again.")
    if pending["tenant_id"] != ident["tenant"]["id"]:
        raise HTTPException(403, "This connection attempt belongs to a different account.")
    chosen = next(
        (o for o in pending["organizations"] if o["organization_id"] == body.organization_id), None
    )
    if not chosen:
        raise HTTPException(400, "Unknown organization.")

    tenant_id = pending["tenant_id"]
    tenancy.upsert_connector(
        tenant_id, "zoho",
        refresh_token_enc=pending["refresh_token_enc"],
        access_token_enc=pending["access_token_enc"],
        token_expires_at=pending["token_expires_at"],
        org_id=chosen["organization_id"],
        account_label=chosen["name"],
        scopes=pending["api_domain"],
    )
    _pending_org_tickets.pop(body.ticket, None)

    tenant = tenancy.get_tenant(tenant_id)
    connector = tenancy.get_connector(tenant_id, "zoho")
    background.add_task(_sync_and_record, "zoho", tenant, connector)
    return {"status": "connected"}


@router.post("/{provider}/disconnect")
def disconnect(provider: str, ident: dict = Depends(auth.current_user)):
    if provider not in _MODULES:
        raise HTTPException(404, "Unknown connector.")
    tenancy.delete_connector(ident["tenant"]["id"], provider)
    return {"status": "disconnected"}

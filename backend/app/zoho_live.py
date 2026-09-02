"""Live, READ-ONLY Zoho Books access — answer questions without loading to the
warehouse. Only GET requests are made; the token is a refresh-token grant.
"""
import time
import httpx

from .config import get_settings

settings = get_settings()

# friendly name -> (Zoho endpoint, list key in the response)
ENTITIES = {
    "invoices": ("invoices", "invoices"),
    "payments": ("customerpayments", "customerpayments"),
    "expenses": ("expenses", "expenses"),
    "bills": ("bills", "bills"),
    "customers": ("contacts", "contacts"),
    "salesorders": ("salesorders", "salesorders"),
    "purchaseorders": ("purchaseorders", "purchaseorders"),
}

_token = {"val": None, "exp": 0.0}


def configured() -> bool:
    return bool(settings.ZOHO_REFRESH_TOKEN and settings.ZOHO_CLIENT_ID and settings.ZOHO_ORG_ID)


def _access_token() -> str:
    if _token["val"] and time.time() < _token["exp"] - 60:
        return _token["val"]
    r = httpx.post(f"{settings.ZOHO_ACCOUNTS_URL}/oauth/v2/token", params={
        "refresh_token": settings.ZOHO_REFRESH_TOKEN,
        "client_id": settings.ZOHO_CLIENT_ID,
        "client_secret": settings.ZOHO_CLIENT_SECRET,
        "grant_type": "refresh_token",
    }, timeout=20)
    d = r.json()
    if "access_token" not in d:
        raise RuntimeError(f"Zoho auth failed ({d.get('error', 'unknown')}). The Zoho token may need re-authorizing.")
    _token["val"] = d["access_token"]
    _token["exp"] = time.time() + int(d.get("expires_in", 3600))
    return _token["val"]


# a compact subset of fields per entity, to keep tokens (and cost) low
_KEEP = {
    "invoices": ["invoice_number", "customer_name", "date", "due_date", "status", "total", "balance"],
    "payments": ["payment_number", "customer_name", "date", "amount", "payment_mode"],
    "expenses": ["date", "account_name", "vendor_name", "total"],
    "bills": ["bill_number", "vendor_name", "date", "due_date", "status", "total", "balance"],
    "customers": ["contact_name", "company_name", "outstanding_receivable_amount", "email", "phone"],
    "salesorders": ["salesorder_number", "customer_name", "date", "status", "total"],
    "purchaseorders": ["purchaseorder_number", "vendor_name", "date", "status", "total"],
}


def fetch(entity: str, params: dict | None = None, max_pages: int = 3):
    key = entity if entity in ENTITIES else "invoices"
    endpoint, list_key = ENTITIES[key]
    tok = _access_token()
    keep = _KEEP.get(key)
    out = []
    page = 1
    base = dict(params or {})
    base["organization_id"] = settings.ZOHO_ORG_ID
    while page <= max_pages:
        q = dict(base, page=page, per_page=200)
        r = httpx.get(f"{settings.ZOHO_BASE_URL}/{endpoint}", params=q,
                      headers={"Authorization": f"Zoho-oauthtoken {tok}"}, timeout=30)
        d = r.json()
        items = d.get(list_key, []) or []
        for it in items:
            out.append({k: it.get(k) for k in keep} if keep else it)
        if not (d.get("page_context") or {}).get("has_more_page"):
            break
        page += 1
    return key, out

"""Zoho multi-organization picker (Task: "when connecting zoho allow
selection of account if multiple account there", 19 Sept 2026). No real
Zoho HTTP calls -- exchange_code/list_organizations/run_full_sync are
monkeypatched. Confirms: a single-org account still auto-connects exactly
as before; a multi-org account gets NOTHING written to `connectors` until
the tenant picks one via the two new endpoints; a ticket only works for the
tenant it was issued to; and a bogus/reused ticket is rejected.
"""
import os
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

os.environ["GANAK_SKIP_DOTENV"] = "1"
os.environ["SEED_DEMO"] = "0"
os.environ["CONTROL_DB_PATH"] = "/tmp/ganak_control_zoho_org_test.db"
os.environ["TENANTS_DIR"] = "/tmp/ganak_tenants_zoho_org_test"
os.environ["DATABASE_URL"] = "sqlite:////tmp/ganak_demo_zoho_org_test.db"
os.environ.setdefault("ZOHO_OAUTH_CLIENT_ID", "fake-zoho-client-id")
os.environ.setdefault("ZOHO_OAUTH_CLIENT_SECRET", "fake-zoho-secret")
os.environ.setdefault("GOOGLE_OAUTH_CLIENT_ID", "fake-google-client-id")
os.environ.setdefault("GOOGLE_OAUTH_CLIENT_SECRET", "fake-google-secret")
os.environ.setdefault("PUBLIC_API_BASE_URL", "https://api.vidmahitech.com")
os.environ.setdefault("PUBLIC_APP_BASE_URL", "https://app.vidmahitech.com")

for f in ("/tmp/ganak_control_zoho_org_test.db",):
    try:
        os.remove(f)
    except FileNotFoundError:
        pass

from fastapi.testclient import TestClient  # noqa: E402
from app import tenancy, auth, connectors_zoho, seed  # noqa: E402
from app.main import app  # noqa: E402

seed.bootstrap()
client = TestClient(app, follow_redirects=False)
fails = []


def check(name, cond):
    print(("PASS" if cond else "FAIL") + " - " + name)
    if not cond:
        fails.append(name)


connectors_zoho.exchange_code = lambda code: {
    "access_token": f"acc-{code}", "refresh_token": f"ref-{code}",
    "expires_in": 3600, "api_domain": "https://www.zohoapis.in",
}
connectors_zoho.run_full_sync = lambda tenant, connector: {"synced": True}

# ---- tenant A: single-org Zoho account -> unchanged auto-connect behaviour ----
r = client.post("/auth/register", json={
    "email": "single-org@example.com", "password": "pass123",
    "company": "Single Org Co", "location": "",
})
check("tenant A registers", r.status_code == 200)
token_a = r.json()["token"]
headers_a = {"Authorization": f"Bearer {token_a}"}
tenant_a_id = tenancy.get_user_by_email("single-org@example.com")["tenant_id"]

connectors_zoho.list_organizations = lambda access_token, api_domain: [
    {"organization_id": "111", "name": "Only Org"},
]
state_a = auth.make_oauth_state(tenant_a_id, "zoho")
r = client.get("/connectors/zoho/callback", params={"code": "code-a", "state": state_a})
check("single-org callback redirects", r.status_code in (302, 307))
check("single-org callback redirects straight to connected=zoho",
      "connected=zoho" in r.headers.get("location", ""))
row_a = tenancy.get_connector(tenant_a_id, "zoho")
check("single-org: connector created immediately", row_a is not None)
check("single-org: correct org stored",
      row_a is not None and row_a["org_id"] == "111" and row_a["account_label"] == "Only Org")

# ---- tenant B: multi-org Zoho account -> must NOT auto-pick ----
r = client.post("/auth/register", json={
    "email": "multi-org@example.com", "password": "pass123",
    "company": "Multi Org Co", "location": "",
})
check("tenant B registers", r.status_code == 200)
token_b = r.json()["token"]
headers_b = {"Authorization": f"Bearer {token_b}"}
tenant_b_id = tenancy.get_user_by_email("multi-org@example.com")["tenant_id"]

connectors_zoho.list_organizations = lambda access_token, api_domain: [
    {"organization_id": "222", "name": "Acme Books"},
    {"organization_id": "333", "name": "Acme Retail"},
]
state_b = auth.make_oauth_state(tenant_b_id, "zoho")
r = client.get("/connectors/zoho/callback", params={"code": "code-b", "state": state_b})
check("multi-org callback redirects", r.status_code in (302, 307))
location = r.headers.get("location", "")
check("multi-org redirect carries select_org=zoho", "select_org=zoho" in location)
check("multi-org redirect carries a ticket", "ticket=" in location)
ticket = location.split("ticket=")[1].split("&")[0]

check("nothing written to connectors table yet", tenancy.get_connector(tenant_b_id, "zoho") is None)

r = client.get(f"/connectors/zoho/pending-orgs?ticket={ticket}")
check("pending-orgs 200 with no auth header", r.status_code == 200)
orgs = r.json()["organizations"]
check("pending-orgs lists both organizations", {o["organization_id"] for o in orgs} == {"222", "333"})

r = client.get("/connectors/zoho/pending-orgs?ticket=not-a-real-ticket")
check("bogus ticket -> 404", r.status_code == 404)

r = client.post("/connectors/zoho/select-org", json={"ticket": ticket, "organization_id": "222"}, headers=headers_a)
check("wrong tenant cannot use another tenant's ticket (403)", r.status_code == 403)
check("still nothing written after the cross-tenant attempt", tenancy.get_connector(tenant_b_id, "zoho") is None)

r = client.post("/connectors/zoho/select-org", json={"ticket": ticket, "organization_id": "999"}, headers=headers_b)
check("unknown organization_id rejected (400)", r.status_code == 400)

r = client.post("/connectors/zoho/select-org", json={"ticket": ticket, "organization_id": "333"}, headers=headers_b)
check("select-org succeeds (200)", r.status_code == 200)
row_b = tenancy.get_connector(tenant_b_id, "zoho")
check("chosen org (not the first one) was stored",
      row_b is not None and row_b["org_id"] == "333" and row_b["account_label"] == "Acme Retail")

r = client.post("/connectors/zoho/select-org", json={"ticket": ticket, "organization_id": "333"}, headers=headers_b)
check("ticket is single-use (404 on reuse)", r.status_code == 404)

print()
if fails:
    print(f"FAILED: {fails}")
    sys.exit(1)
print("ALL ZOHO MULTI-ORG TESTS PASSED")

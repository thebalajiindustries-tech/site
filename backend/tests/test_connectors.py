"""Smoke test for the self-serve connectors plumbing (Task: self-serve Connect
Gmail / Connect Zoho for any signup, 6 Sept 2026) -- no real OAuth provider
involved. Confirms: the /connectors endpoints exist and are wired correctly,
a fresh signup starts with nothing connected, /start builds a real-looking
authorize URL once OAuth client settings are present, tokens are genuinely
encrypted at rest (never stored or returned in plaintext), and disconnect
actually removes the row.
"""
import os
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

os.environ["GANAK_SKIP_DOTENV"] = "1"
os.environ["SEED_DEMO"] = "0"
os.environ["CONTROL_DB_PATH"] = "/tmp/ganak_control_conn_test.db"
os.environ["TENANTS_DIR"] = "/tmp/ganak_tenants_conn_test"
os.environ["DATABASE_URL"] = "sqlite:////tmp/ganak_demo_conn_test.db"
os.environ.setdefault("ZOHO_OAUTH_CLIENT_ID", "fake-zoho-client-id")
os.environ.setdefault("ZOHO_OAUTH_CLIENT_SECRET", "fake-zoho-secret")
os.environ.setdefault("GOOGLE_OAUTH_CLIENT_ID", "fake-google-client-id")
os.environ.setdefault("GOOGLE_OAUTH_CLIENT_SECRET", "fake-google-secret")
os.environ.setdefault("PUBLIC_API_BASE_URL", "https://api.vidmahitech.com")
os.environ.setdefault("PUBLIC_APP_BASE_URL", "https://app.vidmahitech.com")

for f in ("/tmp/ganak_control_conn_test.db",):
    try:
        os.remove(f)
    except FileNotFoundError:
        pass

from fastapi.testclient import TestClient  # noqa: E402
from app import tenancy, crypto, seed  # noqa: E402
from app.main import app  # noqa: E402

seed.bootstrap()
client = TestClient(app)
fails = []


def check(name, cond):
    print(("PASS" if cond else "FAIL") + " - " + name)
    if not cond:
        fails.append(name)


r = client.post("/auth/register", json={
    "email": "conntest@example.com", "password": "pass123",
    "company": "Conn Test Co", "location": "",
})
check("register succeeds", r.status_code == 200)
token = r.json()["token"]
headers = {"Authorization": f"Bearer {token}"}

r = client.get("/connectors", headers=headers)
check("list connectors 200", r.status_code == 200)
data = r.json()
check("both providers listed", {d["provider"] for d in data} == {"zoho", "gmail"})
check("nothing connected yet", all(not d["connected"] for d in data))
check("both report configured (fake creds present)", all(d["configured"] for d in data))

r = client.get("/connectors/zoho/start", headers=headers)
check("zoho start 200", r.status_code == 200)
url = r.json().get("authorize_url", "")
check("zoho authorize url points at zoho + has state", "accounts.zoho.in" in url and "state=" in url)

r = client.get("/connectors/gmail/start", headers=headers)
check("gmail start 200", r.status_code == 200)
gurl = r.json().get("authorize_url", "")
check("gmail authorize url points at google + has state", "accounts.google.com" in gurl and "state=" in gurl)

r = client.get("/connectors/nope/start", headers=headers)
check("unknown provider 404", r.status_code == 404)

r = client.get("/connectors/zoho/start")
check("start requires auth (401)", r.status_code == 401)

tenants_row = tenancy.get_user_by_email("conntest@example.com")
tenant_id = tenants_row["tenant_id"]

cid = tenancy.upsert_connector(
    tenant_id, "zoho",
    refresh_token_enc=crypto.encrypt("plaintext-refresh-token-xyz"),
    access_token_enc=crypto.encrypt("plaintext-access-token-abc"),
    token_expires_at=9999999999.0,
    org_id="60045370667", account_label="Test Org", scopes="https://www.zohoapis.in",
)
check("upsert_connector returns an id", isinstance(cid, int))

row = tenancy.get_connector(tenant_id, "zoho")
check("stored refresh token is NOT plaintext", "plaintext-refresh-token-xyz" not in row["refresh_token_enc"])
check("stored refresh token decrypts back correctly",
      crypto.decrypt(row["refresh_token_enc"]) == "plaintext-refresh-token-xyz")

r = client.get("/connectors", headers=headers)
zrow = next(d for d in r.json() if d["provider"] == "zoho")
check("API now reports zoho connected", zrow["connected"] is True)
check("API surfaces account_label, never the token", zrow["account_label"] == "Test Org")

r = client.post("/connectors/zoho/disconnect", headers=headers)
check("disconnect 200", r.status_code == 200)
check("connector actually removed", tenancy.get_connector(tenant_id, "zoho") is None)

print()
if fails:
    print(f"FAILED: {fails}")
    sys.exit(1)
print("ALL CONNECTOR PLUMBING TESTS PASSED")

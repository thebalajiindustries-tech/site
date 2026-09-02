"""Multi-tenant isolation + auth tests.

Runs the real FastAPI app against two SQLite tenant databases (so no Postgres or
AI network calls are needed) and proves that a login for one company can never
retrieve another company's data.

Run:  python tests/test_isolation.py     (from the backend/ directory)
"""
import os
import sys
import sqlite3
import tempfile
import pathlib

BACKEND = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

WORK = pathlib.Path(tempfile.mkdtemp(prefix="ganak_test_"))
TENANTS = WORK / "tenants"
TENANTS.mkdir(parents=True, exist_ok=True)
TENANT_A_DB = WORK / "balaji.db"

# Configure the app for the test BEFORE importing it (settings are cached at import).
os.environ["GANAK_SKIP_DOTENV"] = "1"  # hermetic: ignore the real .env
os.environ["CONTROL_DB_PATH"] = str(WORK / "control.db")
os.environ["DATABASE_URL"] = "sqlite:///" + str(TENANT_A_DB)  # Balaji tenant as SQLite here
os.environ["TENANTS_DIR"] = str(TENANTS)
os.environ["DEMO_DB_PATH"] = str(TENANTS / "demo.db")
os.environ["GANAK_AUTH_SECRET"] = "test-secret"
os.environ["SEED_DEMO"] = "1"

# Tenant A gets a marker row that ONLY it has.
_c = sqlite3.connect(TENANT_A_DB)
_c.executescript(
    "CREATE TABLE payments(payment_number TEXT, customer_name TEXT, date TEXT, amount REAL, mode TEXT);"
)
_c.execute(
    "INSERT INTO payments VALUES(?,?,?,?,?)",
    ("PMT-A", "BALAJI_ONLY_CUSTOMER", "2026-06-01", 999999, "bank"),
)
_c.commit()
_c.close()

from fastapi.testclient import TestClient  # noqa: E402
from app import llm, seed  # noqa: E402
from app.main import app  # noqa: E402

# Never call the real AI in tests: fixed SQL that works on both tenant DBs.
llm.question_to_sql = lambda q, schema, dialect="postgres": (
    "SELECT customer_name, amount FROM payments ORDER BY amount DESC"
)
llm.narrate = lambda q, rows: {"answer": "ok", "chart": {"type": "none"}}

seed.bootstrap()  # explicit (idempotent) so seeding doesn't depend on lifespan
client = TestClient(app)

failures = []
def check(name, cond):
    print(("PASS" if cond else "FAIL"), "-", name)
    if not cond:
        failures.append(name)

def login(email, pw):
    r = client.post("/auth/login", json={"email": email, "password": pw})
    assert r.status_code == 200, (email, r.status_code, r.text)
    return r.json()["token"]

def ask(token, q="top payment"):
    r = client.post("/ask", json={"question": q}, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, (r.status_code, r.text)
    return r.json()

# 1) auth required
check("unauthenticated /ask is rejected (401)",
      client.post("/ask", json={"question": "x"}).status_code == 401)

# 2) wrong password rejected
check("wrong password rejected (401)",
      client.post("/auth/login", json={"email": "balaji@ganak.local", "password": "nope"}).status_code == 401)

# 3) strict data isolation between the two companies
tokA = login("balaji@ganak.local", "balaji123")
tokB = login("demo@ganak.local", "demo123")
custA = {r["customer_name"] for r in ask(tokA)["rows"]}
custB = {r["customer_name"] for r in ask(tokB)["rows"]}
check("company A sees its own marker row", "BALAJI_ONLY_CUSTOMER" in custA)
check("company B does NOT see company A's data", "BALAJI_ONLY_CUSTOMER" not in custB)
check("company B sees its own demo data", any(("Sunrise" in c or "Metro" in c) for c in custB))
check("company A does NOT see company B's data", not any(("Sunrise" in c or "Metro" in c) for c in custA))

# 4) /me reflects the token's company
meA = client.get("/me", headers={"Authorization": f"Bearer {tokA}"}).json()
meB = client.get("/me", headers={"Authorization": f"Bearer {tokB}"}).json()
check("/me for A -> The Balaji Industries", meA["company"] == "The Balaji Industries")
check("/me for B -> Demo Traders", meB["company"] == "Demo Traders")

# 5) self-serve signup gets its own isolated, empty warehouse
r = client.post("/auth/register", json={"email": "new@co.local", "password": "secret1", "company": "New Co"})
check("register succeeds (200)", r.status_code == 200)
tokC = r.json()["token"]
rowsC = ask(tokC)["rows"]
check("new company starts empty", rowsC == [])
check("new company cannot see A or B data",
      not ({r["customer_name"] for r in rowsC} & (custA | custB)))
check("duplicate email is rejected (409)",
      client.post("/auth/register", json={"email": "new@co.local", "password": "secret1", "company": "X"}).status_code == 409)

# 6) tampered token rejected
bad = tokA[:-2] + ("aa" if not tokA.endswith("aa") else "bb")
check("tampered token rejected (401)",
      client.post("/ask", json={"question": "x"}, headers={"Authorization": f"Bearer {bad}"}).status_code == 401)

print()
if failures:
    print(f"{len(failures)} TEST(S) FAILED:", failures)
    sys.exit(1)
print("ALL TESTS PASSED")

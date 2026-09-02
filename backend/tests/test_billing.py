"""Pay-as-you-go wallet: metering debits balance, zero blocks, recharge credits."""
import os, sys, sqlite3, tempfile, pathlib

BACKEND = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
WORK = pathlib.Path(tempfile.mkdtemp(prefix="ganak_bill_"))
(WORK / "tenants").mkdir(parents=True, exist_ok=True)
DB = WORK / "t.db"
os.environ.update({
    "GANAK_SKIP_DOTENV": "1", "CONTROL_DB_PATH": str(WORK / "control.db"),
    "DATABASE_URL": "sqlite:///" + str(DB), "TENANTS_DIR": str(WORK / "tenants"),
    "DEMO_DB_PATH": str(WORK / "tenants" / "demo.db"),
    "GANAK_AUTH_SECRET": "test-secret", "SEED_DEMO": "1",
    "SEED_BALANCE_INR": "100",
})
c = sqlite3.connect(DB); c.executescript("CREATE TABLE t(amount REAL); INSERT INTO t VALUES(5);"); c.commit(); c.close()

from fastapi.testclient import TestClient
from app import llm, seed, tenancy, billing
from app.main import app

# simulate token spend inside the SQL step
def fake_sql(q, s, dialect="postgres"):
    billing.add_usage("claude-haiku-4-5-20251001", 1000, 500)  # ~₹0.92 at markup 3x
    return "SELECT amount FROM t"
llm.question_to_sql = fake_sql
llm.narrate = lambda q, rows: {"answer": "ok", "chart": {"type": "none"}}
seed.bootstrap()
client = TestClient(app)

def tok():
    return client.post("/auth/login", json={"email": "balaji@ganak.local", "password": "balaji123"}).json()["token"]
H = {"Authorization": f"Bearer {tok()}"}
fails = []
def check(n, c): print(("PASS" if c else "FAIL"), "-", n); (fails.append(n) if not c else None)

# 1) starts with seeded balance
b0 = client.get("/billing", headers=H).json()
check("starts with seeded balance ₹100", abs(b0["balance_inr"] - 100) < 0.001)

# 2) a question debits the wallet and reports cost + new balance
r = client.post("/ask", json={"question": "amount?"}, headers=H).json()
check("question reports a positive cost", r["cost_inr"] > 0)
check("balance dropped by the cost", abs((100 - r["cost_inr"]) - r["balance_inr"]) < 0.01)

# 3) the debit shows in the ledger
led = client.get("/billing", headers=H).json()["ledger"]
check("ledger has an 'ask' debit", any(x["kind"] == "ask" and x["amount_inr"] < 0 for x in led))

# 4) recharge credits the wallet
before = client.get("/billing", headers=H).json()["balance_inr"]
rc = client.post("/billing/recharge", json={"amount_inr": 500}, headers=H).json()
check("recharge adds credit", abs(rc["balance_inr"] - (before + 500)) < 0.01)

# 5) empty balance blocks AI with 402
tid = tenancy.get_user_by_email("balaji@ganak.local")["tenant_id"]
tenancy.adjust_balance(tid, -tenancy.get_balance(tid))  # zero it
r = client.post("/ask", json={"question": "amount?"}, headers=H)
check("empty balance blocks /ask (402)", r.status_code == 402)

# 6) after recharge, AI works again
client.post("/billing/recharge", json={"amount_inr": 50}, headers=H)
check("works again after recharge", client.post("/ask", json={"question": "amount?"}, headers=H).status_code == 200)

print()
print("ALL BILLING TESTS PASSED" if not fails else f"{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)

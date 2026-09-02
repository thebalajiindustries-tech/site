"""Safety + robustness tests: injection blocked, off-topic handled gracefully,
input capped, and login brute-force locked out."""
import os, sys, sqlite3, tempfile, pathlib

BACKEND = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

WORK = pathlib.Path(tempfile.mkdtemp(prefix="ganak_hard_"))
(WORK / "tenants").mkdir(parents=True, exist_ok=True)
DB = WORK / "t.db"
os.environ.update({
    "GANAK_SKIP_DOTENV": "1",
    "CONTROL_DB_PATH": str(WORK / "control.db"),
    "DATABASE_URL": "sqlite:///" + str(DB),
    "TENANTS_DIR": str(WORK / "tenants"),
    "DEMO_DB_PATH": str(WORK / "tenants" / "demo.db"),
    "GANAK_AUTH_SECRET": "test-secret",
    "SEED_DEMO": "1",
})
c = sqlite3.connect(DB)
c.executescript("CREATE TABLE payments(customer_name TEXT, amount REAL);"
                "INSERT INTO payments VALUES('Acme', 100);")
c.commit(); c.close()

from fastapi.testclient import TestClient
from app import llm, seed
from app.main import app

llm.narrate = lambda q, rows: {"answer": "ok", "chart": {"type": "none"}}
seed.bootstrap()
client = TestClient(app)

def tok():
    r = client.post("/auth/login", json={"email": "balaji@ganak.local", "password": "balaji123"})
    return r.json()["token"]

def ask(t, q="x"):
    return client.post("/ask", json={"question": q}, headers={"Authorization": f"Bearer {t}"})

fails = []
def check(name, cond):
    print(("PASS" if cond else "FAIL"), "-", name)
    if not cond: fails.append(name)

t = tok()

# 1) a normal SELECT still works
llm.question_to_sql = lambda q, s, dialect="postgres": "SELECT customer_name, amount FROM payments"
check("valid SELECT works", ask(t).status_code == 200)

# 2) injection / write attempts are blocked with a friendly message (no 500, no leak)
for bad in ["DROP TABLE payments",
            "SELECT 1; DROP TABLE payments",
            "DELETE FROM payments",
            "UPDATE payments SET amount=0",
            "SELECT amount FROM payments -- comment"]:
    llm.question_to_sql = (lambda b: (lambda q, s, dialect="postgres": b))(bad)
    r = ask(t)
    ok = r.status_code == 400 and "business data" in r.json()["detail"] and "DROP" not in r.json()["detail"]
    check(f"blocked + friendly: {bad[:28]}", ok)

# 3) off-topic (AI returns prose, not SQL) -> friendly, not a crash
llm.question_to_sql = lambda q, s, dialect="postgres": "I cannot help with that question."
r = ask(t, "what's the weather?")
check("off-topic -> friendly 400", r.status_code == 400 and "business data" in r.json()["detail"])

# 4) over-long question is capped
r = ask(t, "a" * 1500)
check("over-long question rejected", r.status_code == 400)

# 5) brute-force login lockout after repeated wrong passwords
for _ in range(5):
    client.post("/auth/login", json={"email": "lockme@ganak.local", "password": "nope"})
r = client.post("/auth/login", json={"email": "lockme@ganak.local", "password": "nope"})
check("login locks out after 5 fails (429)", r.status_code == 429)

print()
if fails:
    print(f"{len(fails)} FAILED:", fails); sys.exit(1)
print("ALL HARDENING TESTS PASSED")

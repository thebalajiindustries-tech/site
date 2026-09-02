"""Live (Zoho) mode: answers a question by calling the source, no warehouse load."""
import os, sys, sqlite3, tempfile, pathlib
BACKEND = pathlib.Path(__file__).resolve().parents[1]; sys.path.insert(0, str(BACKEND))
WORK = pathlib.Path(tempfile.mkdtemp(prefix="ganak_live_")); (WORK/"tenants").mkdir(parents=True)
DB = WORK/"t.db"; sqlite3.connect(DB).close()
os.environ.update({"GANAK_SKIP_DOTENV":"1","CONTROL_DB_PATH":str(WORK/"c.db"),
  "DATABASE_URL":"sqlite:///"+str(DB),"TENANTS_DIR":str(WORK/"tenants"),
  "DEMO_DB_PATH":str(WORK/"tenants"/"d.db"),"GANAK_AUTH_SECRET":"x","SEED_DEMO":"1","SEED_BALANCE_INR":"100"})
from fastapi.testclient import TestClient
from app import llm, seed, zoho_live
from app.main import app
zoho_live.configured = lambda: True
zoho_live.fetch = lambda entity, params, max_pages=3: (entity, [{"customer_name":"KSB","total":50000,"status":"unpaid"}])
llm.question_to_zoho = lambda q: {"entity":"invoices","params":{}}
llm.narrate = lambda q, rows: {"answer":"one unpaid invoice for KSB","chart":{"type":"none"}}
seed.bootstrap(); client=TestClient(app)
tok=client.post("/auth/login",json={"email":"balaji@ganak.local","password":"balaji123"}).json()["token"]
H={"Authorization":f"Bearer {tok}"}
fails=[]
def check(n,c): print(("PASS" if c else "FAIL"),"-",n); (fails.append(n) if not c else None)

r=client.post("/ask",json={"question":"unpaid invoices?","mode":"live"},headers=H)
check("live mode answers (200)", r.status_code==200)
j=r.json()
check("live rows came from source", any(row.get("customer_name")=="KSB" for row in j["rows"]))
check("marked as live source", j["sql"].startswith("[live]"))

# not-configured -> friendly guidance
zoho_live.configured = lambda: False
r=client.post("/ask",json={"question":"x","mode":"live"},headers=H)
check("unconfigured live -> friendly 400", r.status_code==400 and "Zoho" in r.json()["detail"])

# warehouse mode unaffected
zoho_live.configured = lambda: True
llm.question_to_sql = lambda q,s,dialect="postgres": "SELECT 1 AS n"
r=client.post("/ask",json={"question":"x","mode":"warehouse"},headers=H)
check("warehouse mode still works", r.status_code==200)

print()
print("ALL LIVE TESTS PASSED" if not fails else f"{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)

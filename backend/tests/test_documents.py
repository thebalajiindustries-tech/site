"""Document AI flow: extract (mocked) -> load -> queryable in Ask, safely."""
import os, sys, base64, sqlite3, tempfile, pathlib

BACKEND = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
WORK = pathlib.Path(tempfile.mkdtemp(prefix="ganak_docs_"))
(WORK / "tenants").mkdir(parents=True, exist_ok=True)
DB = WORK / "t.db"
os.environ.update({
    "GANAK_SKIP_DOTENV": "1", "CONTROL_DB_PATH": str(WORK / "control.db"),
    "DATABASE_URL": "sqlite:///" + str(DB), "TENANTS_DIR": str(WORK / "tenants"),
    "DEMO_DB_PATH": str(WORK / "tenants" / "demo.db"),
    "GANAK_AUTH_SECRET": "test-secret", "SEED_DEMO": "1",
})
sqlite3.connect(DB).close()

from fastapi.testclient import TestClient
from app import llm, seed, docai
from app.main import app

# never call the real document API
docai.extract_from_pdf = lambda pdf_bytes: {
    "doc_type": "bank_payment_advice", "party": "KSB", "doc_date": "2026-08-19",
    "amount": 254000.0, "currency": "INR", "reference_no": "E3S2608191894231",
    "gst_no": "", "direction": "incoming", "summary": "KSB paid via Deutsche Bank",
    "raw": {},
}
llm.narrate = lambda q, rows: {"answer": "ok", "chart": {"type": "none"}}
seed.bootstrap()
client = TestClient(app)

fails = []
def check(n, c): print(("PASS" if c else "FAIL"), "-", n); (fails.append(n) if not c else None)

tok = client.post("/auth/login", json={"email": "balaji@ganak.local", "password": "balaji123"}).json()["token"]
H = {"Authorization": f"Bearer {tok}"}

# 1) non-PDF rejected
r = client.post("/documents/extract", json={"filename": "x.txt", "data_b64": base64.b64encode(b"hi").decode()}, headers=H)
check("non-PDF rejected", r.status_code == 400)

# 2) extract returns fields
r = client.post("/documents/extract",
                json={"filename": "advice.pdf", "data_b64": base64.b64encode(b"%PDF-1.4 fake").decode()}, headers=H)
check("extract returns fields", r.status_code == 200 and r.json()["party"] == "KSB")
fields = r.json()

# 3) load into warehouse
r = client.post("/documents/load", json=fields, headers=H)
check("load succeeds", r.status_code == 200 and r.json()["ok"] is True)

# 4) now queryable via Ask (schema cache was invalidated)
llm.question_to_sql = lambda q, s, dialect="postgres": "SELECT party, amount FROM documents"
r = client.post("/ask", json={"question": "documents"}, headers=H)
ok = r.status_code == 200 and any(row.get("party") == "KSB" for row in r.json()["rows"])
check("loaded document is queryable in Ask", ok)

# 5) auth still required
check("extract needs auth", client.post("/documents/extract", json={"filename":"a.pdf","data_b64":"eA=="}).status_code == 401)

print()
print("ALL DOCUMENT TESTS PASSED" if not fails else f"{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)

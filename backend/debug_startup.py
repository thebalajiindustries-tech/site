"""Diagnose why the backend isn't answering requests.

Runs the exact startup sequence the real server runs (connect to Supabase,
create control tables, seed demo tenants) and then makes a couple of real
HTTP calls against the app in-process, printing full tracebacks on failure.
"""
import sys
import traceback

sys.path.insert(0, ".")

print("=== 1) importing app.config ===")
try:
    from app.config import get_settings
    s = get_settings()
    print("SUPABASE_DB_URL set:", bool(s.SUPABASE_DB_URL), "len:", len(s.SUPABASE_DB_URL))
    print("CONTROL_DB_URL set:", bool(s.CONTROL_DB_URL), "len:", len(s.CONTROL_DB_URL))
    print("DATABASE_URL set:", bool(s.DATABASE_URL))
except Exception:
    print("FAILED at config import"); traceback.print_exc(); sys.exit(1)

print("\n=== 2) tenancy.init_db() (creates control schema/tables on Supabase) ===")
try:
    from app import tenancy
    tenancy.init_db()
    print("OK")
except Exception:
    print("FAILED at tenancy.init_db()"); traceback.print_exc(); sys.exit(1)

print("\n=== 3) seed.bootstrap() (seeds Balaji + Demo Traders schemas) ===")
try:
    from app import seed
    seed.bootstrap()
    print("OK, users so far:", tenancy.count_users())
except Exception:
    print("FAILED at seed.bootstrap()"); traceback.print_exc(); sys.exit(1)

print("\n=== 4) starting the real FastAPI app in-process ===")
try:
    from fastapi.testclient import TestClient
    from app.main import app
    client = TestClient(app)
    r = client.get("/ping")
    print("GET /ping ->", r.status_code, r.text)
except Exception:
    print("FAILED starting app / /ping"); traceback.print_exc(); sys.exit(1)

print("\n=== 5) logging in as balaji@ganak.local ===")
try:
    r = client.post("/auth/login", json={"email": "balaji@ganak.local", "password": "balaji123"})
    print("POST /auth/login ->", r.status_code, r.text[:300])
except Exception:
    print("FAILED at login"); traceback.print_exc(); sys.exit(1)

print("\nALL STEPS COMPLETED — if step 5 printed 200, the backend logic itself is fine.")

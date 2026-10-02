"""Hermetic test for the SSC Saathi study-site endpoints -- no real Anthropic
calls (ssc_routes._client is monkeypatched). Confirms: access code required and
case-insensitive, feature off when no codes are set, per-code daily cap, images
forwarded to the model, JSON mode, CORS for the study site, and that existing
Ganak CORS origins still work.
"""
import os
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

os.environ["GANAK_SKIP_DOTENV"] = "1"
os.environ["SEED_DEMO"] = "0"
os.environ["CONTROL_DB_PATH"] = "/tmp/ganak_control_ssc_test.db"
os.environ["TENANTS_DIR"] = "/tmp/ganak_tenants_ssc_test"
os.environ["DATABASE_URL"] = "sqlite:////tmp/ganak_demo_ssc_test.db"
os.environ["CORS_ORIGINS"] = "https://app.vidmahitech.com"
os.environ["ANTHROPIC_API_KEY"] = "test-key-not-real"
os.environ["SSC_ACCESS_CODES"] = "SSC-2027, demo"
os.environ["SSC_DAILY_LIMIT_PER_CODE"] = "3"
for f in ("/tmp/ganak_control_ssc_test.db",):
    try:
        os.remove(f)
    except FileNotFoundError:
        pass

from fastapi.testclient import TestClient  # noqa: E402
from app import main, ssc_routes  # noqa: E402

seen = {}


class _Msgs:
    def create(self, **kw):
        seen.clear()
        seen.update(kw)

        class B:
            type = "text"
            text = '{"ok": true}'

        class R:
            content = [B()]
            model = kw["model"]
            stop_reason = "end_turn"
        return R()


class _Client:
    messages = _Msgs()


ssc_routes._client = lambda: _Client()
failures = 0


def check(cond, msg):
    global failures
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond:
        failures += 1


with TestClient(main.app) as c:
    body = {"turns": [{"role": "user", "content": "hi"}], "tier": "quick"}
    check(c.get("/ssc/health").json()["enabled"] is True, "health says enabled")
    check(c.post("/ssc/sample", json=body).status_code == 401, "missing code rejected")
    check(c.post("/ssc/sample", json=body, headers={"X-Access-Code": "nope"}).status_code == 401, "wrong code rejected")
    r = c.post("/ssc/sample", json=body, headers={"X-Access-Code": "ssc-2027"})
    check(r.status_code == 200 and r.json()["text"] == '{"ok": true}', "valid code works (case-insensitive)")
    check(seen.get("model") == main.settings.SSC_MODEL_QUICK, "quick tier uses the quick model")
    img = {"turns": [{"role": "user", "content": "grade"}], "tier": "complex", "json": True,
           "images": [{"media_type": "image/jpeg", "data": "QUJD"}]}
    r = c.post("/ssc/sample", json=img, headers={"X-Access-Code": "SSC-2027"})
    check(r.status_code == 200 and seen["messages"][-1]["content"][0]["type"] == "image", "photo forwarded to the model")
    check("JSON" in seen["system"] and seen["model"] == main.settings.SSC_MODEL, "json mode + main model for grading")
    check(c.post("/ssc/sample", json=body, headers={"X-Access-Code": "SSC-2027"}).status_code == 200, "3rd call of the day allowed")
    check(c.post("/ssc/sample", json=body, headers={"X-Access-Code": "SSC-2027"}).status_code == 429, "4th call blocked by daily cap")
    check(c.post("/ssc/sample", json=body, headers={"X-Access-Code": "demo"}).status_code == 200, "another code has its own cap")
    bad = {"turns": [{"role": "assistant", "content": "x"}]}
    check(c.post("/ssc/sample", json=bad, headers={"X-Access-Code": "demo"}).status_code == 400, "must end on a user turn")
    gif = {"turns": [{"role": "user", "content": "x"}], "images": [{"media_type": "application/pdf", "data": "QQ=="}]}
    check(c.post("/ssc/sample", json=gif, headers={"X-Access-Code": "demo"}).status_code == 400, "non-image upload rejected")

    def preflight(origin):
        return c.options("/ssc/sample", headers={"Origin": origin, "Access-Control-Request-Method": "POST",
                                                  "Access-Control-Request-Headers": "content-type,x-access-code"})
    check(preflight("https://ssc.vidmahitech.com").headers.get("access-control-allow-origin") == "https://ssc.vidmahitech.com", "CORS allows study site")
    check(preflight("https://app.vidmahitech.com").headers.get("access-control-allow-origin") == "https://app.vidmahitech.com", "CORS still allows Ganak app")
    check(preflight("https://evil.example.com").headers.get("access-control-allow-origin") is None, "CORS blocks other sites")

    main.settings.SSC_ACCESS_CODES = ""
    check(c.post("/ssc/sample", json=body, headers={"X-Access-Code": "demo"}).status_code == 401, "feature off when no codes configured")
    check(c.get("/ssc/health").json()["enabled"] is False, "health says disabled")

if failures:
    print(f"{failures} SSC TEST(S) FAILED")
    sys.exit(1)
print("ALL SSC TESTS PASSED")

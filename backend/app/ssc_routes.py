"""SSC Saathi -- AI endpoints for the Std 10 study site (ssc.vidmahitech.com).

The study site is a static page used by school students, not Ganak tenants, so
these routes don't use Ganak login or the tenant wallet. Instead every call
needs an access code from SSC_ACCESS_CODES (blank = feature switched off) and
is capped per code and in total per IST day, so the public page can't run up
the Anthropic bill. Counters live in memory and reset when the service restarts.

  GET  /ssc/health   is the feature configured?
  POST /ssc/sample   {turns, images, tier, json} -> {text}
  POST /ssc/login    {name} + access code -> {name, progress}   (student login)
  PUT  /ssc/progress {name, progress} + access code -> {ok}     (sync progress)
  GET  /ssc/teacher  X-Teacher-Key header -> every student's progress

Student login is "name + class code" (the access code): no passwords, chosen by
the school so students don't have to remember anything. Progress is a small JSON
blob per (code, name) kept in the control DB table ssc_students.
"""
import hmac
import json
import re
import threading
import time

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from . import tenancy
from .config import get_settings

router = APIRouter(prefix="/ssc", tags=["ssc"])
settings = get_settings()

MAX_TOKENS = {"quick": 1500, "default": 3000, "complex": 6000}
SYSTEM = ("You are SSC Saathi, a patient tutor and fair examiner for Maharashtra State Board "
          "Std 10 (SSC) students. Follow the instructions in the user's message exactly. "
          "Keep content age-appropriate and focused on studies.")
IMAGE_TYPES = ("image/jpeg", "image/png", "image/webp", "image/gif")

_lock = threading.Lock()
_usage: dict = {}  # (ist_day, code) -> requests used


def _codes() -> set:
    return {c.strip().lower() for c in settings.SSC_ACCESS_CODES.split(",") if c.strip()}


def _take_quota(code: str) -> None:
    day = time.strftime("%Y-%m-%d", time.gmtime(time.time() + 19800))  # IST
    with _lock:
        for k in [k for k in _usage if k[0] != day]:
            del _usage[k]
        total = sum(v for (d, _), v in _usage.items() if d == day)
        mine = _usage.get((day, code), 0)
        if mine >= settings.SSC_DAILY_LIMIT_PER_CODE or total >= settings.SSC_DAILY_LIMIT_TOTAL:
            raise HTTPException(429, "daily limit reached")
        _usage[(day, code)] = mine + 1


def _client():
    """Same Anthropic client setup as llm.py (workspace header for identity-linked keys)."""
    from anthropic import Anthropic
    headers = {"anthropic-workspace-id": settings.ANTHROPIC_WORKSPACE_ID} if settings.ANTHROPIC_WORKSPACE_ID else None
    return Anthropic(api_key=settings.ANTHROPIC_API_KEY, default_headers=headers)


class Img(BaseModel):
    media_type: str
    data: str


class Turn(BaseModel):
    role: str
    content: str = Field(max_length=200_000)


class SampleReq(BaseModel):
    turns: list[Turn] = Field(min_length=1, max_length=30)
    images: list[Img] = Field(default_factory=list, max_length=5)
    tier: str = "default"
    json_reply: bool = Field(default=False, alias="json")


@router.get("/health")
def ssc_health():
    return {"ok": True, "enabled": bool(_codes()) and bool(settings.ANTHROPIC_API_KEY)}


@router.post("/sample")
def ssc_sample(req: SampleReq, request: Request):
    code = (request.headers.get("x-access-code") or "").strip().lower()
    if not code or code not in _codes():
        raise HTTPException(401, "invalid access code")
    if not settings.ANTHROPIC_API_KEY:
        raise HTTPException(503, "AI not configured")
    if req.turns[-1].role != "user" or any(t.role not in ("user", "assistant") for t in req.turns):
        raise HTTPException(400, "turns must end on a user turn")
    for im in req.images:
        if im.media_type not in IMAGE_TYPES:
            raise HTTPException(400, "unsupported image type")
        if len(im.data) > 7_000_000:
            raise HTTPException(413, "image too large")
    _take_quota(code)

    tier = req.tier if req.tier in MAX_TOKENS else "default"
    model = settings.SSC_MODEL_QUICK if tier == "quick" else settings.SSC_MODEL
    msgs = [{"role": t.role, "content": t.content} for t in req.turns]
    if req.images:
        msgs[-1]["content"] = [
            {"type": "image", "source": {"type": "base64", "media_type": i.media_type, "data": i.data}}
            for i in req.images
        ] + [{"type": "text", "text": req.turns[-1].content}]
    system = SYSTEM + (" Your reply will be machine-parsed: reply with only valid JSON, no extra text."
                       if req.json_reply else "")
    import anthropic
    try:
        r = _client().messages.create(model=model, max_tokens=MAX_TOKENS[tier], system=system, messages=msgs)
    except anthropic.RateLimitError:
        raise HTTPException(429, "busy, try again")
    except anthropic.APIError as e:
        raise HTTPException(502, f"upstream error: {type(e).__name__}")
    text = "".join(b.text for b in r.content if getattr(b, "type", "") == "text")
    return {"text": text, "model": r.model, "stop": r.stop_reason}


# ---------- student login + progress (control DB) ----------
MAX_PROGRESS_BYTES = 60_000
_table_ready = False


def _ensure_table() -> None:
    global _table_ready
    if _table_ready:
        return
    with tenancy._cx() as conn:
        conn.cursor().execute(
            """
            CREATE TABLE IF NOT EXISTS ssc_students (
                code       TEXT NOT NULL,
                name_key   TEXT NOT NULL,
                name       TEXT NOT NULL,
                progress   TEXT NOT NULL DEFAULT '{}',
                created_at DOUBLE PRECISION NOT NULL,
                updated_at DOUBLE PRECISION NOT NULL,
                PRIMARY KEY (code, name_key)
            );
            """
        )
    _table_ready = True


def _student_code(request: Request) -> str:
    code = (request.headers.get("x-access-code") or "").strip().lower()
    if not code or code not in _codes():
        raise HTTPException(401, "invalid access code")
    return code


def _clean_name(name: str) -> tuple[str, str]:
    name = re.sub(r"\s+", " ", (name or "").strip())[:60]
    if len(name) < 2:
        raise HTTPException(400, "name required")
    return name, name.lower()


def _get_student(code: str, key: str):
    with tenancy._cx() as conn:
        cur = tenancy._cur(conn)
        cur.execute(tenancy._q("SELECT * FROM ssc_students WHERE code=? AND name_key=?"), (code, key))
        return tenancy._row(cur.fetchone())


class LoginReq(BaseModel):
    name: str = Field(max_length=80)


class ProgressReq(BaseModel):
    name: str = Field(max_length=80)
    progress: dict


@router.post("/login")
def ssc_login(req: LoginReq, request: Request):
    code = _student_code(request)
    name, key = _clean_name(req.name)
    _ensure_table()
    row = _get_student(code, key)
    if row is None:
        now = time.time()
        with tenancy._cx() as conn:
            conn.cursor().execute(
                tenancy._q("INSERT INTO ssc_students(code,name_key,name,progress,created_at,updated_at) "
                           "VALUES(?,?,?,?,?,?)"), (code, key, name, "{}", now, now))
        return {"name": name, "progress": {}, "new": True}
    return {"name": row["name"], "progress": json.loads(row["progress"] or "{}"), "new": False}


@router.put("/progress")
def ssc_progress(req: ProgressReq, request: Request):
    code = _student_code(request)
    name, key = _clean_name(req.name)
    blob = json.dumps(req.progress, ensure_ascii=False, separators=(",", ":"))
    if len(blob.encode()) > MAX_PROGRESS_BYTES:
        raise HTTPException(413, "progress too large")
    _ensure_table()
    now = time.time()
    with tenancy._cx() as conn:
        cur = conn.cursor()
        cur.execute(tenancy._q("UPDATE ssc_students SET progress=?, updated_at=? WHERE code=? AND name_key=?"),
                    (blob, now, code, key))
        if cur.rowcount == 0:
            cur.execute(tenancy._q("INSERT INTO ssc_students(code,name_key,name,progress,created_at,updated_at) "
                                   "VALUES(?,?,?,?,?,?)"), (code, key, name, blob, now, now))
    return {"ok": True, "saved_at": now}


@router.get("/teacher")
def ssc_teacher(request: Request):
    want = settings.SSC_TEACHER_KEY
    got = request.headers.get("x-teacher-key") or ""
    if not want:
        raise HTTPException(503, "teacher dashboard not configured")
    if not hmac.compare_digest(got.encode(), want.encode()):
        raise HTTPException(401, "invalid teacher key")
    _ensure_table()
    with tenancy._cx() as conn:
        cur = tenancy._cur(conn)
        cur.execute("SELECT code, name, progress, created_at, updated_at FROM ssc_students ORDER BY code, name_key")
        rows = [tenancy._row(r) for r in cur.fetchall()]
    for r in rows:
        r["progress"] = json.loads(r["progress"] or "{}")
    return {"students": rows}

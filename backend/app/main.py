"""Ganak backend — ask-your-data API for the VidmahiTech warehouse.

Endpoints:
  GET  /health   liveness + DB connectivity
  GET  /schema   the introspected table/column map the AI sees
  POST /ask      question -> read-only SQL -> answer + chart + rows
"""
import logging

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .config import get_settings
from . import db, llm
from .guardrails import sanitize, UnsafeSQLError

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("ganak")
settings = get_settings()

app = FastAPI(title="Ganak API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


class AskRequest(BaseModel):
    question: str


class ChartSpec(BaseModel):
    type: str = "none"
    x: str | None = None
    y: str | None = None


class AskResponse(BaseModel):
    answer: str
    sql: str
    columns: list
    rows: list
    chart: ChartSpec


@app.get("/health")
def health():
    return {"ok": True, "database": "up" if db.ping() else "down"}


@app.get("/schema")
def schema():
    return {"schema": db.load_schema(refresh=True)}


@app.post("/ask", response_model=AskResponse)
def ask(req: AskRequest):
    q = (req.question or "").strip()
    if not q:
        raise HTTPException(400, "Question is empty.")
    try:
        schema = db.load_schema()
        raw_sql = llm.question_to_sql(q, schema)
        sql = sanitize(raw_sql)
        log.info("Q: %s\nSQL: %s", q, sql)
        columns, rows = db.run_select(sql)
        narration = llm.narrate(q, rows)
        return AskResponse(
            answer=narration.get("answer", ""),
            sql=sql,
            columns=columns,
            rows=rows,
            chart=ChartSpec(**(narration.get("chart") or {"type": "none"})),
        )
    except UnsafeSQLError as e:
        raise HTTPException(400, f"Rejected unsafe query: {e}")
    except HTTPException:
        raise
    except Exception as e:  # pragma: no cover
        log.exception("ask failed")
        # Turn common, diagnosable failures into a clear message for the user,
        # instead of a vague "try rephrasing". We never echo the API key here.
        name = type(e).__name__
        text = str(e)
        if "workspace-id is required" in text or "anthropic-workspace-id" in text:
            msg = "Your Anthropic key is workspace-linked. Add ANTHROPIC_WORKSPACE_ID=wrkspc_... to backend/.env (find it at console.anthropic.com under Settings -> Workspaces), then restart."
        elif name in ("AuthenticationError", "PermissionDeniedError") or "401" in text or "Unauthorized" in text:
            msg = "AI key not accepted (401 Unauthorized). Create a fresh key at console.anthropic.com and paste the FULL key into backend/.env, then restart."
        elif name == "NotFoundError" or "model" in text.lower() and "not" in text.lower():
            msg = f"The AI model '{settings.MODEL}' was not found. Update MODEL in backend/.env to a current Claude model, then restart."
        elif name == "RateLimitError" or "credit balance" in text.lower() or "429" in text:
            msg = "AI request was rate-limited or the account is out of credit. Add credit at console.anthropic.com and retry."
        elif name in ("APIConnectionError", "APITimeoutError") or "connect" in text.lower():
            msg = "Could not reach the AI service. Check this PC's internet connection and retry."
        else:
            msg = "Could not answer that. Try rephrasing."
        raise HTTPException(500, msg) from e
# reloaded: 1788313911

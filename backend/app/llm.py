"""LLM calls: question -> SQL, and rows -> plain-English answer + chart spec.

Swappable provider (Anthropic or OpenAI) behind one small interface so you are
never locked in.
"""
import json
import re

from .config import get_settings

settings = get_settings()


def _complete(prompt: str, max_tokens: int = 700) -> str:
    """Send a single-user-message prompt to the configured provider, return text."""
    if settings.LLM_PROVIDER == "openai":
        from openai import OpenAI

        client = OpenAI(api_key=settings.OPENAI_API_KEY)
        resp = client.chat.completions.create(
            model=settings.MODEL,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        return resp.choices[0].message.content or ""

    # default: anthropic
    from anthropic import Anthropic

    # Identity-linked API keys require the workspace id on every request.
    extra_headers = {}
    if settings.ANTHROPIC_WORKSPACE_ID:
        extra_headers["anthropic-workspace-id"] = settings.ANTHROPIC_WORKSPACE_ID
    client = Anthropic(
        api_key=settings.ANTHROPIC_API_KEY,
        default_headers=extra_headers or None,
    )
    msg = client.messages.create(
        model=settings.MODEL,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text


def _strip_fences(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:sql|json)?", "", text, flags=re.IGNORECASE).strip()
    text = re.sub(r"```$", "", text).strip()
    return text


def question_to_sql(question: str, schema: str, dialect: str = "postgres") -> str:
    if dialect == "sqlite":
        engine = "SQLite"
        dialect_rules = (
            "- Target dialect: SQLite. Use ONLY SQLite-compatible SQL.\n"
            "- Dates are TEXT in ISO format (YYYY-MM-DD); group/filter with "
            "strftime('%Y', col), strftime('%Y-%m', col), or date(col). Do NOT use date_trunc or INTERVAL.\n"
            "- Cast numbers with CAST(NULLIF(col,'') AS REAL) when aggregating. Do NOT use ::type casts."
        )
    else:
        engine = "PostgreSQL"
        dialect_rules = (
            "- Target dialect: PostgreSQL.\n"
            "- Money columns may be text; cast with NULLIF(col,'')::numeric when aggregating.\n"
            "- Use date_trunc and INTERVAL for time grouping; sensible date filters on "
            "columns like invoice_date, expense_date, created_time, date."
        )
    prompt = f"""You are a {engine} expert for a business-analytics product.
Convert the user's question into ONE read-only {engine} query.

Rules:
- Use ONLY the tables and columns in the schema below. Never invent names.
- Read-only: a single SELECT (or WITH ... SELECT). No writes, DDL, or multiple statements.
{dialect_rules}
- Prefer aggregates + GROUP BY for "how much / how many / by X / trend" questions.
- Return ONLY the SQL. No prose, no markdown fences.

DATABASE SCHEMA:
{schema}

QUESTION: {question}
SQL:"""
    return _strip_fences(_complete(prompt, max_tokens=600))


def narrate(question: str, rows: list) -> dict:
    """Turn rows into {answer, chart:{type,x,y}} the frontend can render."""
    sample = json.dumps(rows[:50], default=str)
    cur = settings.CURRENCY
    prompt = f"""The user asked: "{question}"
The SQL returned these rows (JSON): {sample}

Currency is {cur} (Indian rupees). Always use the {cur} symbol for money, never $.

Reply with ONLY a JSON object shaped like:
{{
  "answer": "one or two sentences of plain English, naming the key number(s), with currency where relevant",
  "chart": {{ "type": "bar" | "line" | "none", "x": "<column for labels>", "y": "<column for values>" }}
}}
Use "none" when a single value or short list reads better than a chart.
Return only the JSON."""
    text = _strip_fences(_complete(prompt, max_tokens=500))
    try:
        data = json.loads(text)
        if not isinstance(data, dict) or "answer" not in data:
            raise ValueError
        data.setdefault("chart", {"type": "none"})
        return data
    except (json.JSONDecodeError, ValueError):
        return {"answer": text or "Here are the results.", "chart": {"type": "none"}}

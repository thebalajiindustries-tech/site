"""Extract structured finance fields from a PDF using Claude's document support."""
import base64
import json
import re

from .config import get_settings
from . import billing

settings = get_settings()

_PROMPT = """You are reading a business finance document for an Indian company —
it may be a bank payment advice, vendor bill, invoice, purchase order, balance
confirmation, bank statement, or receipt.

Extract the key fields and reply with ONLY this JSON object:
{
 "doc_type": "bank_payment_advice|vendor_bill|invoice|purchase_order|balance_confirmation|bank_statement|receipt|other",
 "party": "the other company or bank name",
 "doc_date": "YYYY-MM-DD, or empty if unclear",
 "amount": <total amount as a number, or null>,
 "currency": "INR",
 "reference_no": "invoice / advice / PO / UTR number, or empty",
 "gst_no": "GSTIN if present, or empty",
 "direction": "incoming if money was received, outgoing if money is to be paid, else empty",
 "summary": "one short plain-English sentence"
}
Return only the JSON, no prose."""


def extract_from_pdf(pdf_bytes: bytes) -> dict:
    from anthropic import Anthropic

    headers = {}
    if settings.ANTHROPIC_WORKSPACE_ID:
        headers["anthropic-workspace-id"] = settings.ANTHROPIC_WORKSPACE_ID
    client = Anthropic(api_key=settings.ANTHROPIC_API_KEY, default_headers=headers or None)

    b64 = base64.standard_b64encode(pdf_bytes).decode()
    msg = client.messages.create(
        model=settings.EXTRACT_MODEL,
        max_tokens=700,
        messages=[{"role": "user", "content": [
            {"type": "document",
             "source": {"type": "base64", "media_type": "application/pdf", "data": b64}},
            {"type": "text", "text": _PROMPT},
        ]}],
    )
    try:
        u = msg.usage
        billing.add_usage(settings.EXTRACT_MODEL, getattr(u, "input_tokens", 0), getattr(u, "output_tokens", 0),
                          getattr(u, "cache_read_input_tokens", 0) or 0,
                          getattr(u, "cache_creation_input_tokens", 0) or 0)
    except Exception:
        pass
    text = "".join(getattr(b, "text", "") for b in msg.content if getattr(b, "type", "") == "text").strip()
    text = re.sub(r"^```(?:json)?", "", text).strip()
    text = re.sub(r"```$", "", text).strip()
    try:
        data = json.loads(text)
        if not isinstance(data, dict):
            raise ValueError
    except (json.JSONDecodeError, ValueError):
        data = {"doc_type": "other", "summary": text[:200] or "Could not read the document."}
    data.setdefault("currency", "INR")
    data["raw"] = {k: v for k, v in data.items() if k != "raw"}
    return data

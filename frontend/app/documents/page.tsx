"use client";
import { useState } from "react";
import Link from "next/link";
import { extractDocument, loadDocument, type DocFields } from "../../lib/api";

const TYPES = [
  "bank_payment_advice", "vendor_bill", "invoice", "purchase_order",
  "balance_confirmation", "bank_statement", "receipt", "other",
];

function toB64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => { const s = String(r.result); resolve(s.slice(s.indexOf(",") + 1)); };
    r.onerror = () => reject(new Error("Could not read the file."));
    r.readAsDataURL(file);
  });
}

export default function DocumentsPage() {
  const [busy, setBusy] = useState(false);
  const [stage, setStage] = useState<"idle" | "reading" | "review" | "saved">("idle");
  const [err, setErr] = useState<string | null>(null);
  const [doc, setDoc] = useState<DocFields | null>(null);

  async function onFile(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0];
    e.target.value = "";
    if (!f) return;
    setErr(null); setDoc(null); setStage("reading"); setBusy(true);
    try {
      const b64 = await toB64(f);
      const fields = await extractDocument(f.name, b64);
      setDoc(fields); setStage("review");
    } catch (e) { setErr((e as Error).message); setStage("idle"); }
    finally { setBusy(false); }
  }

  function set<K extends keyof DocFields>(k: K, v: DocFields[K]) {
    setDoc((d) => (d ? { ...d, [k]: v } : d));
  }

  async function save() {
    if (!doc) return;
    setBusy(true); setErr(null);
    try { await loadDocument(doc); setStage("saved"); }
    catch (e) { setErr((e as Error).message); }
    finally { setBusy(false); }
  }

  return (
    <div className="view" style={{ maxWidth: 720 }}>
      <div className="card panel">
        <div className="ph">
          <h3>Add a document</h3>
          <span className="sub">PDF → Ganak reads it → you confirm → it's queryable</span>
        </div>
        <p className="muted" style={{ marginTop: 0 }}>
          Upload a bank payment advice, vendor bill, invoice, PO, or balance confirmation.
          Ganak extracts the key fields; you review them, then save to your warehouse.
        </p>

        <label style={upload}>
          <input type="file" accept="application/pdf,.pdf" onChange={onFile} disabled={busy} style={{ display: "none" }} />
          <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round"><path d="M12 16V4M8 8l4-4 4 4M4 16v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2" /></svg>
          <span>{stage === "reading" ? "Reading your PDF…" : "Choose a PDF"}</span>
        </label>

        {err && <div style={{ color: "#b91c1c", fontSize: ".85rem", marginTop: 12 }}>⚠ {err}</div>}
      </div>

      {stage === "review" && doc && (
        <div className="card panel" style={{ marginTop: 16 }}>
          <div className="ph"><h3>Review &amp; save</h3><span className="sub">{doc.source_filename}</span></div>
          <div style={grid}>
            <Field label="Type">
              <select value={doc.doc_type || "other"} onChange={(e) => set("doc_type", e.target.value)} style={inp}>
                {TYPES.map((t) => <option key={t} value={t}>{t.replace(/_/g, " ")}</option>)}
              </select>
            </Field>
            <Field label="Party"><input value={doc.party || ""} onChange={(e) => set("party", e.target.value)} style={inp} /></Field>
            <Field label="Date"><input value={doc.doc_date || ""} placeholder="YYYY-MM-DD" onChange={(e) => set("doc_date", e.target.value)} style={inp} /></Field>
            <Field label="Amount (₹)"><input value={doc.amount ?? ""} inputMode="decimal" onChange={(e) => set("amount", e.target.value === "" ? null : Number(e.target.value))} style={inp} /></Field>
            <Field label="Reference no."><input value={doc.reference_no || ""} onChange={(e) => set("reference_no", e.target.value)} style={inp} /></Field>
            <Field label="GSTIN"><input value={doc.gst_no || ""} onChange={(e) => set("gst_no", e.target.value)} style={inp} /></Field>
            <Field label="Direction">
              <select value={doc.direction || ""} onChange={(e) => set("direction", e.target.value)} style={inp}>
                <option value="">—</option><option value="incoming">incoming (received)</option><option value="outgoing">outgoing (to pay)</option>
              </select>
            </Field>
          </div>
          <Field label="Summary"><input value={doc.summary || ""} onChange={(e) => set("summary", e.target.value)} style={inp} /></Field>
          <div style={{ display: "flex", gap: 10, marginTop: 16 }}>
            <button className="send" onClick={save} disabled={busy} style={{ height: 40, padding: "0 18px", borderRadius: 9, fontWeight: 600 }}>
              {busy ? "Saving…" : "Save to warehouse"}
            </button>
            <button onClick={() => { setStage("idle"); setDoc(null); }} disabled={busy}
              style={{ height: 40, padding: "0 16px", borderRadius: 9, border: "1px solid var(--line,#d8dbe0)", background: "transparent", color: "inherit", cursor: "pointer" }}>
              Cancel
            </button>
          </div>
        </div>
      )}

      {stage === "saved" && (
        <div className="card panel" style={{ marginTop: 16, borderLeft: "3px solid var(--teal,#0d9488)" }}>
          <b>Saved to your warehouse.</b>
          <p className="muted" style={{ margin: "6px 0 0" }}>
            You can now ask about it — e.g. <i>“total amount of documents this month”</i> or <i>“show vendor bills to pay”</i>.
          </p>
          <div style={{ display: "flex", gap: 10, marginTop: 14 }}>
            <Link href="/ask" className="send" style={{ height: 38, padding: "0 16px", borderRadius: 9, fontWeight: 600, display: "inline-flex", alignItems: "center", textDecoration: "none" }}>Ask Ganak</Link>
            <button onClick={() => setStage("idle")} style={{ height: 38, padding: "0 16px", borderRadius: 9, border: "1px solid var(--line,#d8dbe0)", background: "transparent", color: "inherit", cursor: "pointer" }}>Add another</button>
          </div>
        </div>
      )}
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label style={{ display: "grid", gap: 5, fontSize: ".82rem" }}>
      <span className="muted" style={{ fontWeight: 500 }}>{label}</span>
      {children}
    </label>
  );
}

const grid: React.CSSProperties = { display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 12 };
const inp: React.CSSProperties = {
  height: 38, borderRadius: 8, border: "1px solid var(--line,#d8dbe0)", padding: "0 11px",
  fontSize: ".9rem", background: "var(--card,#fff)", color: "inherit", width: "100%",
};
const upload: React.CSSProperties = {
  display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 8,
  padding: "26px", marginTop: 14, borderRadius: 12, border: "1.5px dashed var(--line,#cfd6d4)",
  color: "var(--teal-deep,#0f766e)", cursor: "pointer", fontWeight: 500,
};

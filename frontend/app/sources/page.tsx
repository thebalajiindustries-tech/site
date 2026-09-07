"use client";
import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import {
  listConnectors, startConnector, syncConnectorNow, disconnectConnector,
  extractDocument, loadDocument, type ConnectorInfo, type DocFields,
} from "../../lib/api";

// ---------------- shared bits ----------------

const META: Record<string, { name: string; color: string; icon: string; desc: string }> = {
  zoho: {
    name: "Zoho Books", color: "#E42527", icon: "Z",
    desc: "Invoices, expenses, bills, payments, customers — your own Zoho org, synced read-only.",
  },
  gmail: {
    name: "Gmail", color: "#D14836", icon: "G",
    desc: "Finance emails classified automatically: payments received, bank advices, vendor bills, balance confirmations, quotations, POs.",
  },
};
const ORDER = ["zoho", "gmail"];
const COMING_SOON = [
  { n: "Tally", c: "#1F71B8", i: "T", d: "Ledgers and vouchers from Tally Prime. Great for GST data." },
  { n: "Outlook", c: "#0A78D4", i: "O", d: "Finance emails for Microsoft 365 businesses." },
];

function when(ts: number) {
  if (!ts) return "";
  return new Date(ts * 1000).toLocaleString("en-IN", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
}

// ---------------- Connections tab ----------------

function ConnectionsPanel({ params }: { params: ReturnType<typeof useSearchParams> }) {
  const [items, setItems] = useState<ConnectorInfo[] | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [banner, setBanner] = useState<string | null>(null);

  function load() {
    listConnectors().then(setItems).catch((e) => setErr((e as Error).message));
  }

  useEffect(() => {
    const connected = params.get("connected");
    const error = params.get("error");
    if (connected) setBanner(`${META[connected]?.name || connected} connected — pulling your data in now.`);
    if (error) setErr(`Connection failed (${error}). Please try again.`);
    load();
    // if we just connected, poll for a bit so "last synced" updates without a manual refresh
    if (connected) {
      const iv = setInterval(load, 4000);
      const stop = setTimeout(() => clearInterval(iv), 60_000);
      return () => { clearInterval(iv); clearTimeout(stop); };
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  async function connect(provider: string) {
    setBusy(provider); setErr(null);
    try {
      const { authorize_url } = await startConnector(provider);
      window.location.href = authorize_url;
    } catch (e) {
      setErr((e as Error).message);
      setBusy(null);
    }
  }

  async function syncNow(provider: string) {
    setBusy(provider); setErr(null);
    try { await syncConnectorNow(provider); setBanner("Sync started — this can take a minute for a lot of data."); load(); }
    catch (e) { setErr((e as Error).message); }
    finally { setBusy(null); }
  }

  async function disconnect(provider: string) {
    setBusy(provider); setErr(null);
    try { await disconnectConnector(provider); load(); }
    catch (e) { setErr((e as Error).message); }
    finally { setBusy(null); }
  }

  return (
    <div>
      <p className="muted" style={{ marginTop: 0, maxWidth: 640 }}>
        Ganak reads a synced, read-only copy of your own data — it can never change or
        delete anything in the source tool. Connect your own Zoho Books org and Gmail
        below; each connects to your account, not anyone else&apos;s.
      </p>

      {banner && <div className="card" style={{ padding: "10px 14px", marginBottom: 12, borderLeft: "3px solid var(--accent)" }}>{banner}</div>}
      {err && <div className="card" style={{ padding: "10px 14px", marginBottom: 12, borderLeft: "3px solid var(--red)", color: "var(--red)" }}>⚠ {err}</div>}

      <div className="static-list">
        {!items ? (
          <p className="muted">Loading…</p>
        ) : ORDER.map((provider) => {
          const c = items.find((i) => i.provider === provider);
          const m = META[provider];
          const label = !c?.configured
            ? "Not set up yet"
            : c?.connected
              ? (c.status === "error" ? "Needs attention" : "Connected")
              : "Not connected";
          const pillClass = !c?.configured ? "off" : c?.connected ? (c.status === "error" ? "off" : "ok") : "off";
          return (
            <div className="card conn-row" key={provider}>
              <span className="ci" style={{ background: m.color }}>{m.icon}</span>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div className="cn">{m.name}</div>
                <div className="cd">{m.desc}</div>
                {c?.connected && (
                  <div className="cd" style={{ marginTop: 4 }}>
                    {c.account_label && <span>{c.account_label} · </span>}
                    {c.last_synced_at ? <span>last synced {when(c.last_synced_at)}</span> : <span>sync starting…</span>}
                    {c.status === "error" && c.last_error && (
                      <span style={{ color: "var(--red)" }}> · {c.last_error}</span>
                    )}
                  </div>
                )}
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <span className={"pill " + pillClass}>{label}</span>
                {c?.configured && !c.connected && (
                  <button className="send" disabled={busy === provider}
                    onClick={() => connect(provider)}
                    style={{ padding: "6px 14px", borderRadius: 8, fontWeight: 600, width: "auto", height: "auto" }}>
                    {busy === provider ? "Connecting…" : `Connect ${m.name}`}
                  </button>
                )}
                {c?.connected && (
                  <>
                    <button disabled={busy === provider} onClick={() => syncNow(provider)}
                      style={{ padding: "6px 12px", borderRadius: 8, border: "1px solid var(--line-strong)", background: "transparent", color: "inherit", cursor: "pointer" }}>
                      {busy === provider ? "…" : "Sync now"}
                    </button>
                    <button disabled={busy === provider} onClick={() => disconnect(provider)}
                      style={{ padding: "6px 12px", borderRadius: 8, border: "1px solid var(--line-strong)", background: "transparent", cursor: "pointer", color: "var(--red)" }}>
                      Disconnect
                    </button>
                  </>
                )}
              </div>
            </div>
          );
        })}
        {COMING_SOON.map((c) => (
          <div className="card conn-row" key={c.n}>
            <span className="ci" style={{ background: c.c }}>{c.i}</span>
            <div>
              <div className="cn">{c.n}</div>
              <div className="cd">{c.d}</div>
            </div>
            <span className="pill off">Coming soon</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ---------------- Documents tab ----------------

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
  height: 38, borderRadius: 8, border: "1px solid var(--line-strong)", padding: "0 11px",
  fontSize: ".9rem", background: "var(--surface)", color: "inherit", width: "100%",
};
const upload: React.CSSProperties = {
  display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 8,
  padding: "26px", marginTop: 14, borderRadius: 12, border: "1.5px dashed var(--line-strong)",
  color: "var(--accent-ink)", cursor: "pointer", fontWeight: 500,
};

function DocumentsPanel() {
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
    <div>
      <div className="card panel">
        <div className="ph">
          <h3>Add a document</h3>
          <span className="sub">PDF → Ganak reads it → you confirm → it&apos;s queryable</span>
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

        {err && <div style={{ color: "var(--red)", fontSize: ".85rem", marginTop: 12 }}>⚠ {err}</div>}
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
          <div className="btn-row" style={{ marginTop: 16 }}>
            <button className="btn-primary" onClick={save} disabled={busy}>{busy ? "Saving…" : "Save to warehouse"}</button>
            <button className="btn-secondary" onClick={() => { setStage("idle"); setDoc(null); }} disabled={busy}>Cancel</button>
          </div>
        </div>
      )}

      {stage === "saved" && (
        <div className="card panel" style={{ marginTop: 16, borderLeft: "3px solid var(--accent)" }}>
          <b>Saved to your warehouse.</b>
          <p className="muted" style={{ margin: "6px 0 0" }}>
            You can now ask about it — e.g. <i>&ldquo;total amount of documents this month&rdquo;</i> or <i>&ldquo;show vendor bills to pay&rdquo;</i>.
          </p>
          <div className="btn-row" style={{ marginTop: 14 }}>
            <Link href="/ask" className="btn-primary" style={{ display: "inline-flex", alignItems: "center", textDecoration: "none" }}>Ask Ganak</Link>
            <button className="btn-secondary" onClick={() => setStage("idle")}>Add another</button>
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------- page shell: tabs ----------------

function SourcesInner() {
  const router = useRouter();
  const params = useSearchParams();
  const initialTab = params.get("tab") === "documents" ? "documents" : "connections";
  const [tab, setTab] = useState<"connections" | "documents">(initialTab);

  function switchTab(t: "connections" | "documents") {
    setTab(t);
    router.replace(`/sources?tab=${t}`);
  }

  return (
    <div className="view" style={{ maxWidth: 820 }}>
      <div className="tabs">
        <button className={tab === "connections" ? "active" : ""} onClick={() => switchTab("connections")}>Connections</button>
        <button className={tab === "documents" ? "active" : ""} onClick={() => switchTab("documents")}>Documents</button>
      </div>
      {tab === "connections" ? <ConnectionsPanel params={params} /> : <DocumentsPanel />}
    </div>
  );
}

export default function Sources() {
  return (
    <Suspense fallback={<div className="view"><p className="muted">Loading…</p></div>}>
      <SourcesInner />
    </Suspense>
  );
}

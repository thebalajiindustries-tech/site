"use client";
import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  inboxStatus, inboxMissing, inboxExtract, inboxAccounts, inboxCreate, inboxDismiss, syncConnectorNow,
  type InboxMissing, type InboxMissingItem, type InboxRecordType, type InboxExtract, type InboxAccounts,
} from "../../lib/api";

// Inbox -> Books: Ganak lists recent finance emails that are not in Zoho Books yet.
// Nothing is added until you open one, check the details and press "Add to Zoho Books".

const TYPE_LABEL: Record<InboxRecordType, string> = {
  bill: "Vendor bill",
  customer_payment: "Payment received (from a customer)",
  vendor_payment: "Payment made (to a vendor)",
  estimate: "Quotation (estimate)",
  purchase_order: "Purchase order",
  sales_order: "Sales order (customer PO)",
  expense: "Expense",
};
const TYPES = Object.keys(TYPE_LABEL) as InboxRecordType[];
const PAYMENT_MODES = ["banktransfer", "cash", "check", "creditcard", "others"];

const inp: React.CSSProperties = {
  height: 38, borderRadius: 8, border: "1px solid var(--line-strong)", padding: "0 11px",
  fontSize: ".9rem", background: "var(--surface)", color: "inherit", width: "100%",
};
const grid: React.CSSProperties = { display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 12 };

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label style={{ display: "grid", gap: 5, fontSize: ".82rem" }}>
      <span className="muted" style={{ fontWeight: 500 }}>{label}</span>
      {children}
    </label>
  );
}

function money(n: number | null | undefined) {
  if (n === null || n === undefined) return "—";
  return "₹" + n.toLocaleString("en-IN", { maximumFractionDigits: 2 });
}

type LineForm = { description: string; quantity: string; rate: string };
type Form = {
  party_name: string; document_number: string; date: string; due_date: string; total: string;
  lines: LineForm[]; reference_number: string; payment_mode: string; gst_no: string; notes: string;
  account_id: string; paid_through_account_id: string; deposit_account_id: string; invoice_id: string;
  bill_ids: string[];
};

function toForm(x: InboxExtract): Form {
  const f = x.fields;
  const best = x.invoice_candidates.find((c) => c.best);
  return {
    party_name: f.party_name, document_number: f.document_number, date: f.date, due_date: f.due_date,
    total: f.total !== null && f.total !== undefined ? String(f.total)
      : (f.line_items || []).length ? String((f.line_items || []).reduce((a, l) => a + l.quantity * l.rate, 0)) : "",
    lines: (f.line_items || []).map((l) => ({ description: l.description, quantity: String(l.quantity), rate: String(l.rate) })),
    reference_number: f.reference_number, payment_mode: f.payment_mode || "banktransfer", gst_no: f.gst_no,
    notes: f.notes, account_id: "", paid_through_account_id: "", deposit_account_id: "",
    invoice_id: best ? best.invoice_id : "",
    bill_ids: (x.bill_candidates || []).filter((c) => c.best).map((c) => c.bill_id),
  };
}

const usesLines = (t: InboxRecordType) => t === "bill" || t === "estimate" || t === "purchase_order" || t === "sales_order";

export default function InboxBooks() {
  const [status, setStatus] = useState<{ gmail_connected: boolean; zoho_connected: boolean; write_enabled: boolean } | null>(null);
  const [data, setData] = useState<InboxMissing | null>(null);
  const [days, setDays] = useState(30);
  const [err, setErr] = useState<string | null>(null);
  const [banner, setBanner] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [types, setTypes] = useState<Record<string, InboxRecordType>>({});

  // review dialog
  const [open, setOpen] = useState<InboxMissingItem | null>(null);
  const [rtype, setRtype] = useState<InboxRecordType>("bill");
  const [extracting, setExtracting] = useState(false);
  const [ex, setEx] = useState<InboxExtract | null>(null);
  const [accounts, setAccounts] = useState<InboxAccounts | null>(null);
  const [accErr, setAccErr] = useState<string | null>(null);
  const [form, setForm] = useState<Form | null>(null);
  const [saving, setSaving] = useState(false);
  const [dialogErr, setDialogErr] = useState<string | null>(null);
  const [dupe, setDupe] = useState(false);
  const [allowDupe, setAllowDupe] = useState(false);

  function load(d = days) {
    setLoading(true); setErr(null);
    inboxMissing(d).then(setData).catch((e) => { setErr((e as Error).message); setData(null); }).finally(() => setLoading(false));
  }

  useEffect(() => {
    inboxStatus().then((s) => {
      setStatus(s);
      if (s.gmail_connected && s.zoho_connected) load();
    }).catch((e) => setErr((e as Error).message));
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  async function syncBoth() {
    setSyncing(true); setErr(null);
    try {
      await Promise.all([syncConnectorNow("gmail"), syncConnectorNow("zoho")]);
      setBanner("Syncing Gmail and Zoho — this can take a minute. The list refreshes automatically.");
      setTimeout(() => load(), 20_000);
      setTimeout(() => { load(); setSyncing(false); }, 60_000);
    } catch (e) { setErr((e as Error).message); setSyncing(false); }
  }

  const items = data?.items ?? [];
  const typeFor = (i: InboxMissingItem) => types[i.message_id] ?? i.suggested_type;

  async function review(item: InboxMissingItem) {
    const t = typeFor(item);
    setOpen(item); setRtype(t); setEx(null); setForm(null); setDialogErr(null); setDupe(false); setAllowDupe(false);
    setAccounts(null); setAccErr(null); setExtracting(true);
    try {
      const x = await inboxExtract(item.message_id, t);
      setEx(x); setForm(toForm(x));
      if (t === "bill" || t === "expense" || t === "customer_payment" || t === "vendor_payment") {
        inboxAccounts().then(setAccounts).catch((e) => setAccErr((e as Error).message));
      }
    } catch (e) { setDialogErr((e as Error).message); }
    finally { setExtracting(false); }
  }

  function close() { if (!saving) setOpen(null); }

  function toggleBill(id: string) {
    setForm((f) => (f ? { ...f, bill_ids: f.bill_ids.includes(id) ? f.bill_ids.filter((b) => b !== id) : [...f.bill_ids, id] } : f));
  }
  function setF<K extends keyof Form>(k: K, v: Form[K]) { setForm((f) => (f ? { ...f, [k]: v } : f)); }
  function setLine(i: number, k: keyof LineForm, v: string) {
    setForm((f) => (f ? { ...f, lines: f.lines.map((l, j) => (j === i ? { ...l, [k]: v } : l)) } : f));
  }

  const lineTotal = useMemo(
    () => (form ? form.lines.reduce((s, l) => s + (parseFloat(l.quantity) || 0) * (parseFloat(l.rate) || 0), 0) : 0),
    [form]
  );

  const docTotal = form && form.total.trim() !== "" ? parseFloat(form.total) : null;
  // > 0: lines exceed the document total; < 0: lines fall short (usually the GST that isn't itemised)
  const mismatch = form && usesLines(rtype) && form.lines.length > 0 && docTotal !== null && !isNaN(docTotal)
    ? Math.round((lineTotal - docTotal) * 100) / 100 : 0;
  const blocked = Math.abs(mismatch) > 0.5;

  async function save() {
    if (!open || !ex || !form) return;
    setSaving(true); setDialogErr(null);
    const lines = usesLines(rtype)
      ? form.lines.filter((l) => parseFloat(l.rate) > 0).map((l) => ({
          description: l.description, quantity: parseFloat(l.quantity) || 1, rate: parseFloat(l.rate) }))
      : [];
    const total = form.total.trim() === "" ? null : parseFloat(form.total);
    try {
      const r = await inboxCreate(open.message_id, rtype, {
        ...ex.fields,
        party_name: form.party_name.trim(), document_number: form.document_number.trim(),
        date: form.date.trim(), due_date: form.due_date.trim(), total, line_items: lines,
        reference_number: form.reference_number.trim(), payment_mode: form.payment_mode, gst_no: form.gst_no.trim(),
        notes: form.notes.trim(), account_id: form.account_id, paid_through_account_id: form.paid_through_account_id,
        deposit_account_id: form.deposit_account_id, invoice_id: form.invoice_id,
        bill_ids: rtype === "vendor_payment" ? form.bill_ids : undefined,
        contact_id: ex.party_match && ex.party_match.contact_name.trim().toLowerCase() === form.party_name.trim().toLowerCase()
          ? ex.party_match.contact_id : undefined,
      }, allowDupe);
      setBanner(`${TYPE_LABEL[rtype]} from “${open.subject || open.sender}” — ${r.message}`);
      setData((d) => (d ? { ...d, items: d.items.filter((i) => i.message_id !== open.message_id) } : d));
      setOpen(null);
    } catch (e) {
      const m = (e as Error).message;
      setDialogErr(m);
      if (m.includes("already has a matching")) setDupe(true);
    } finally { setSaving(false); }
  }

  async function dismiss(item: InboxMissingItem) {
    try {
      await inboxDismiss(item.message_id);
      setData((d) => (d ? { ...d, items: d.items.filter((i) => i.message_id !== item.message_id) } : d));
    } catch (e) { setErr((e as Error).message); }
  }

  const isPayment = rtype === "customer_payment" || rtype === "vendor_payment";
  const notConnected = status && (!status.gmail_connected || !status.zoho_connected);

  return (
    <div className="view" style={{ maxWidth: 900 }}>
      <p className="muted" style={{ marginTop: 0, maxWidth: 680 }}>
        Ganak checks your recent finance emails against Zoho Books and lists the ones that aren&apos;t there yet.
        Nothing is added on its own — you open each one, check the details, and press <b>Add to Zoho Books</b>.
      </p>

      {banner && <div className="card" style={{ padding: "10px 14px", marginBottom: 12, borderLeft: "3px solid var(--accent)" }}>{banner}</div>}
      {err && <div className="card" style={{ padding: "10px 14px", marginBottom: 12, borderLeft: "3px solid var(--red)", color: "var(--red)" }}>⚠ {err}</div>}

      {notConnected && (
        <div className="card panel">
          <b>Connect Gmail and Zoho Books first.</b>
          <p className="muted" style={{ margin: "6px 0 12px" }}>
            {!status!.gmail_connected && "Gmail is not connected. "}{!status!.zoho_connected && "Zoho Books is not connected."}
          </p>
          <Link href="/sources" className="btn-primary" style={{ display: "inline-flex", alignItems: "center", textDecoration: "none" }}>
            Go to Sources
          </Link>
        </div>
      )}

      {status && !status.write_enabled && !notConnected && (
        <div className="card" style={{ padding: "10px 14px", marginBottom: 12, borderLeft: "3px solid var(--line-strong)" }}>
          You can see what&apos;s missing, but adding to Zoho Books isn&apos;t switched on for this Ganak yet.
        </div>
      )}

      {status && !notConnected && (
        <>
          <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap", marginBottom: 14 }}>
            <span className="muted">Emails from the last</span>
            <select value={days} style={{ ...inp, width: "auto", height: 34 }}
              onChange={(e) => { const d = Number(e.target.value); setDays(d); load(d); }}>
              <option value={7}>7 days</option><option value={30}>30 days</option><option value={90}>90 days</option>
            </select>
            <button className="btn-secondary" onClick={() => load()} disabled={loading}>{loading ? "Checking…" : "Check again"}</button>
            <button className="btn-secondary" onClick={syncBoth} disabled={syncing}
              title="Pull the newest emails and Zoho records first">{syncing ? "Syncing…" : "Sync Gmail & Zoho first"}</button>
          </div>

          {data && (data.body_pending ?? 0) > 0 && (
            <div className="card" style={{ padding: "10px 14px", marginBottom: 12, borderLeft: "3px solid var(--line-strong)" }}>
              Ganak reads each email&apos;s full text to compare amounts and invoice numbers — {data.body_pending} more still to read.
              Press <b>Check again</b> to continue.
            </div>
          )}
          {data && !data.gmail_synced && (
            <div className="card panel"><b>No emails synced yet.</b>
              <p className="muted" style={{ margin: "6px 0 0" }}>Press “Sync Gmail &amp; Zoho first”, wait a minute, then check again.</p></div>
          )}
          {data && data.gmail_synced && !data.zoho_synced && (
            <div className="card" style={{ padding: "10px 14px", marginBottom: 12, borderLeft: "3px solid var(--red)" }}>
              Zoho data isn&apos;t synced yet, so Ganak can&apos;t tell what&apos;s missing. Press “Sync Gmail &amp; Zoho first”.
            </div>
          )}

          {data && data.gmail_synced && items.length === 0 && !loading && (
            <div className="card panel"><b>Nothing missing 🎉</b>
              <p className="muted" style={{ margin: "6px 0 0" }}>
                Every recent finance email already has a matching record in Zoho Books.
              </p></div>
          )}

          <div className="static-list">
            {items.map((i) => (
              <div className="card panel" key={i.message_id} style={{ padding: 16 }}>
                <div style={{ display: "flex", gap: 12, alignItems: "flex-start", flexWrap: "wrap" }}>
                  <div style={{ flex: 1, minWidth: 220 }}>
                    <div style={{ fontWeight: 600 }}>{i.subject || "(no subject)"}</div>
                    <div className="muted" style={{ fontSize: ".82rem", marginTop: 2 }}>
                      {i.sender} · {i.email_date} · {money(i.amount)}
                    </div>
                    {i.snippet && <div className="muted" style={{ fontSize: ".82rem", marginTop: 6 }}>{i.snippet}</div>}
                    {i.note && <div style={{ fontSize: ".8rem", marginTop: 6, color: "var(--red)" }}>{i.note}</div>}
                  </div>
                  <div style={{ display: "grid", gap: 8, minWidth: 190 }}>
                    <select value={typeFor(i)} style={{ ...inp, height: 34 }}
                      onChange={(e) => setTypes((t) => ({ ...t, [i.message_id]: e.target.value as InboxRecordType }))}>
                      {TYPES.map((t) => <option key={t} value={t}>{TYPE_LABEL[t]}</option>)}
                    </select>
                    <div className="btn-row" style={{ display: "flex", gap: 8 }}>
                      <button className="btn-primary" disabled={!status.write_enabled} title={status.write_enabled ? "" : "Adding to Zoho isn't switched on for this Ganak yet"} onClick={() => review(i)}>Review &amp; add</button>
                      <button className="btn-secondary" onClick={() => dismiss(i)} title="Hide this email — it isn't a Zoho record">Not needed</button>
                    </div>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </>
      )}

      {open && (
        <div role="dialog" aria-modal="true" aria-labelledby="inbox-dialog-title"
          style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,.45)", display: "grid", placeItems: "center", zIndex: 50, padding: 16, overflowY: "auto" }}>
          <div className="card" style={{ maxWidth: 640, width: "100%", padding: 22, maxHeight: "92vh", overflowY: "auto" }}>
            <div id="inbox-dialog-title" style={{ fontWeight: 700, marginBottom: 2 }}>Add {TYPE_LABEL[rtype].toLowerCase()} to Zoho Books</div>
            <div className="muted" style={{ fontSize: ".82rem", marginBottom: 14 }}>{open.subject} · {open.sender}</div>

            {extracting && <p className="muted">Reading the email{open.snippet ? " and any PDF attached" : ""}… (a few seconds)</p>}
            {dialogErr && <div style={{ color: "var(--red)", fontSize: ".85rem", marginBottom: 12 }}>⚠ {dialogErr}</div>}

            {ex && form && (
              <>
                {ex.warnings.map((w) => (
                  <div key={w} className="muted" style={{ fontSize: ".82rem", marginBottom: 8 }}>ℹ {w}</div>
                ))}
                <div style={grid}>
                  <Field label={rtype === "bill" || rtype === "purchase_order" || rtype === "expense" || rtype === "vendor_payment" ? "Vendor" : "Customer"}>
                    <input style={inp} value={form.party_name} onChange={(e) => setF("party_name", e.target.value)} />
                    <span className="muted" style={{ fontSize: ".75rem" }}>
                      {ex.party_match ? `Matches “${ex.party_match.contact_name}” in Zoho` : "Not in Zoho yet — will be created"}
                    </span>
                  </Field>
                  {rtype !== "expense" && !isPayment ? (
                    <Field label={rtype === "bill" ? "Bill number" : "Document number (optional)"}>
                      <input style={inp} value={form.document_number} onChange={(e) => setF("document_number", e.target.value)} />
                    </Field>
                  ) : (
                    <Field label="Reference / UTR (optional)">
                      <input style={inp} value={form.reference_number} onChange={(e) => setF("reference_number", e.target.value)} />
                    </Field>
                  )}
                  <Field label="Date (YYYY-MM-DD)">
                    <input style={inp} value={form.date} placeholder="2026-09-19" onChange={(e) => setF("date", e.target.value)} />
                  </Field>
                  {rtype === "bill" && (
                    <Field label="Due date (optional)">
                      <input style={inp} value={form.due_date} placeholder="2026-10-19" onChange={(e) => setF("due_date", e.target.value)} />
                    </Field>
                  )}
                  <Field label={rtype === "customer_payment" ? "Amount received (₹)" : rtype === "expense" || rtype === "vendor_payment" ? "Amount paid (₹)" : "Total on the document, incl. GST (₹)"}>
                    <input style={inp} inputMode="decimal" value={form.total} onChange={(e) => setF("total", e.target.value)} />
                  </Field>
                </div>

                {usesLines(rtype) && form.lines.length > 0 && (
                  <div style={{ marginBottom: 12 }}>
                    <div className="muted" style={{ fontSize: ".82rem", fontWeight: 500, marginBottom: 6 }}>Line items</div>
                    {form.lines.map((l, i) => (
                      <div key={i} style={{ display: "grid", gridTemplateColumns: "1fr 70px 100px", gap: 8, marginBottom: 6 }}>
                        <input style={inp} value={l.description} onChange={(e) => setLine(i, "description", e.target.value)} placeholder="Description" />
                        <input style={inp} inputMode="decimal" value={l.quantity} onChange={(e) => setLine(i, "quantity", e.target.value)} placeholder="Qty" />
                        <input style={inp} inputMode="decimal" value={l.rate} onChange={(e) => setLine(i, "rate", e.target.value)} placeholder="Rate" />
                      </div>
                    ))}
                    <div className="muted" style={{ fontSize: ".82rem" }}>Lines add up to {money(lineTotal)}</div>
                    {mismatch !== 0 && (
                      <div style={{ fontSize: ".82rem", marginTop: 6, color: "var(--red)" }}>
                        The lines are {money(Math.abs(mismatch))} {mismatch > 0 ? "more" : "less"} than the document total.{" "}
                        {mismatch < 0 && (
                          <button className="btn-secondary" style={{ padding: "2px 10px" }}
                            onClick={() => setForm((f) => (f ? { ...f, lines: [...f.lines,
                              { description: "GST / tax", quantity: "1", rate: String(Math.round(-mismatch * 100) / 100) }] } : f))}>
                            Add the difference as a GST / tax line
                          </button>
                        )}
                      </div>
                    )}
                  </div>
                )}

                <div style={grid}>
                  {rtype === "bill" && (
                    <Field label="Expense account">
                      <AccountSelect value={form.account_id} onChange={(v) => setF("account_id", v)} list={accounts?.expense_accounts} err={accErr} />
                    </Field>
                  )}
                  {rtype === "expense" && (
                    <>
                      <Field label="Expense account">
                        <AccountSelect value={form.account_id} onChange={(v) => setF("account_id", v)} list={accounts?.expense_accounts} err={accErr} />
                      </Field>
                      <Field label="Paid through">
                        <AccountSelect value={form.paid_through_account_id} onChange={(v) => setF("paid_through_account_id", v)} list={accounts?.bank_accounts} err={accErr} />
                      </Field>
                    </>
                  )}
                  {rtype === "customer_payment" && (
                    <>
                      <Field label="Deposited to">
                        <AccountSelect value={form.deposit_account_id} onChange={(v) => setF("deposit_account_id", v)} list={accounts?.bank_accounts} err={accErr} />
                      </Field>
                      <Field label="Payment mode">
                        <select style={inp} value={form.payment_mode} onChange={(e) => setF("payment_mode", e.target.value)}>
                          {PAYMENT_MODES.map((m) => <option key={m} value={m}>{m}</option>)}
                        </select>
                      </Field>
                      <Field label="Apply to invoice (optional)">
                        <select style={inp} value={form.invoice_id} onChange={(e) => setF("invoice_id", e.target.value)}>
                          <option value="">Don&apos;t apply — record as unapplied payment</option>
                          {ex.invoice_candidates.map((c) => (
                            <option key={c.invoice_id} value={c.invoice_id}>
                              {c.invoice_number} · {c.customer_name} · due {money(c.balance)}{c.best ? " ✓ likely" : ""}
                            </option>
                          ))}
                        </select>
                      </Field>
                    </>
                  )}
                  {rtype === "vendor_payment" && (
                    <>
                      <Field label="Paid from">
                        <AccountSelect value={form.paid_through_account_id} onChange={(v) => setF("paid_through_account_id", v)} list={accounts?.bank_accounts} err={accErr} />
                      </Field>
                      <Field label="Payment mode">
                        <select style={inp} value={form.payment_mode} onChange={(e) => setF("payment_mode", e.target.value)}>
                          {PAYMENT_MODES.map((m) => <option key={m} value={m}>{m}</option>)}
                        </select>
                      </Field>
                    </>
                  )}
                  {!ex.party_match && (
                    <Field label="GSTIN (optional, for the new contact)">
                      <input style={inp} value={form.gst_no} onChange={(e) => setF("gst_no", e.target.value)} />
                    </Field>
                  )}
                </div>
                {rtype === "vendor_payment" && (
                  <div style={{ marginBottom: 12 }}>
                    <div className="muted" style={{ fontSize: ".82rem", fontWeight: 500, marginBottom: 6 }}>
                      Which bills does this pay? (optional)
                    </div>
                    {ex.bill_candidates.length === 0 && (
                      <div className="muted" style={{ fontSize: ".82rem" }}>
                        No open bills found for this vendor — the payment will be recorded unapplied, and you can apply it to bills in Zoho.
                      </div>
                    )}
                    {ex.bill_candidates.map((c) => (
                      <label key={c.bill_id} style={{ display: "flex", gap: 8, alignItems: "center", fontSize: ".85rem", marginBottom: 4 }}>
                        <input type="checkbox" checked={form.bill_ids.includes(c.bill_id)} onChange={() => toggleBill(c.bill_id)} />
                        {c.bill_number} · {c.vendor_name} · owes {money(c.balance)}{c.best ? " ✓ named in the email" : ""}
                      </label>
                    ))}
                    {ex.bill_candidates.length > 0 && (
                      <div className="muted" style={{ fontSize: ".75rem", marginTop: 4 }}>
                        The money is spread over the ticked bills, oldest first, never more than each still owes. Anything left stays unapplied.
                      </div>
                    )}
                  </div>
                )}
                <Field label="Notes">
                  <input style={inp} value={form.notes} onChange={(e) => setF("notes", e.target.value)} />
                </Field>

                {dupe && (
                  <label style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 12, fontSize: ".85rem" }}>
                    <input type="checkbox" checked={allowDupe} onChange={(e) => setAllowDupe(e.target.checked)} />
                    Add anyway — this is really a different record
                  </label>
                )}
              </>
            )}

            <div className="btn-row" style={{ marginTop: 18, display: "flex", gap: 8 }}>
              {ex && form && (
                <button className="btn-primary" onClick={save} disabled={saving || blocked || (dupe && !allowDupe)}>
                  {saving ? "Adding…" : "Add to Zoho Books"}
                </button>
              )}
              <button className="btn-secondary" onClick={close} disabled={saving}>Cancel</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function AccountSelect({ value, onChange, list, err }: {
  value: string; onChange: (v: string) => void; list?: { account_id: string; account_name: string }[]; err: string | null;
}) {
  if (err) return <span style={{ color: "var(--red)", fontSize: ".8rem" }}>⚠ {err}</span>;
  return (
    <select style={inp} value={value} onChange={(e) => onChange(e.target.value)} disabled={!list}>
      <option value="">{list ? "Choose…" : "Loading…"}</option>
      {(list ?? []).map((a) => <option key={a.account_id} value={a.account_id}>{a.account_name}</option>)}
    </select>
  );
}

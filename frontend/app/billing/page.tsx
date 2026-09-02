"use client";
import { useEffect, useState } from "react";
import { getBilling, recharge, type Billing } from "../../lib/api";

const QUICK = [100, 500, 1000, 2000];

function fmt(n: number) { return "₹" + n.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 }); }
function when(ts: number) { return new Date(ts * 1000).toLocaleString("en-IN", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" }); }

export default function BillingPage() {
  const [data, setData] = useState<Billing | null>(null);
  const [amount, setAmount] = useState<string>("500");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  function load() { getBilling().then(setData).catch((e) => setErr((e as Error).message)); }
  useEffect(() => { load(); }, []);

  async function topUp() {
    const amt = Number(amount);
    if (!amt || amt <= 0) { setErr("Enter a valid amount."); return; }
    setBusy(true); setErr(null);
    try { await recharge(amt); load(); }
    catch (e) { setErr((e as Error).message); }
    finally { setBusy(false); }
  }

  const bal = data?.balance_inr ?? 0;
  const low = bal < 10;

  return (
    <div className="view" style={{ maxWidth: 760 }}>
      <div className="kpis" style={{ gridTemplateColumns: "1.2fr 2fr" }}>
        <div className="card kpi" style={low ? { borderLeft: "3px solid var(--amber,#b45309)" } : undefined}>
          <div className="k-lbl">Wallet balance</div>
          <div className="k-val" style={{ color: low ? "var(--amber,#b45309)" : undefined }}>{fmt(bal)}</div>
          <div className="k-sub">{low ? "running low — top up to keep using AI" : "pay-as-you-go"}</div>
        </div>
        <div className="card panel" style={{ margin: 0 }}>
          <div className="ph"><h3>Recharge</h3><span className="sub">add credit to your wallet</span></div>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 10 }}>
            {QUICK.map((q) => (
              <button key={q} onClick={() => setAmount(String(q))}
                style={{ padding: "7px 14px", borderRadius: 8, cursor: "pointer",
                  border: "1px solid var(--line,#d8dbe0)",
                  background: Number(amount) === q ? "var(--teal,#0d9488)" : "transparent",
                  color: Number(amount) === q ? "#fff" : "inherit", fontWeight: 500 }}>₹{q}</button>
            ))}
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            <input value={amount} inputMode="numeric" onChange={(e) => setAmount(e.target.value.replace(/[^0-9.]/g, ""))}
              style={{ height: 40, flex: 1, borderRadius: 8, border: "1px solid var(--line,#d8dbe0)", padding: "0 12px", background: "var(--card,#fff)", color: "inherit" }} />
            <button className="send" onClick={topUp} disabled={busy}
              style={{ height: 40, padding: "0 18px", borderRadius: 9, fontWeight: 600 }}>
              {busy ? "Adding…" : "Add credit"}
            </button>
          </div>
          {err && <div style={{ color: "#b91c1c", fontSize: ".82rem", marginTop: 10 }}>⚠ {err}</div>}
          <p className="muted" style={{ fontSize: ".76rem", margin: "10px 0 0" }}>
            Simulated top‑up for now. In production this is where a payment gateway (e.g. Razorpay) confirms the payment, then credits your wallet.
          </p>
        </div>
      </div>

      <div className="card panel" style={{ marginTop: 16 }}>
        <div className="ph"><h3>Usage &amp; transactions</h3><span className="sub">every AI action debits your balance</span></div>
        {!data ? <p className="muted">Loading…</p> : data.ledger.length === 0 ? (
          <p className="muted">No activity yet. Ask a question or add a document and it'll show here.</p>
        ) : (
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: ".85rem" }}>
              <thead>
                <tr style={{ textAlign: "left", color: "var(--muted,#5b6b68)" }}>
                  <th style={th}>When</th><th style={th}>Type</th><th style={th}>Detail</th>
                  <th style={{ ...th, textAlign: "right" }}>Amount</th><th style={{ ...th, textAlign: "right" }}>Balance</th>
                </tr>
              </thead>
              <tbody>
                {data.ledger.map((r, i) => (
                  <tr key={i} style={{ borderTop: "1px solid var(--line,#e5e9e8)" }}>
                    <td style={td}>{when(r.ts)}</td>
                    <td style={td}>{r.kind}</td>
                    <td style={{ ...td, color: "var(--muted,#5b6b68)" }}>{r.detail}</td>
                    <td style={{ ...td, textAlign: "right", fontVariantNumeric: "tabular-nums",
                      color: r.amount_inr >= 0 ? "var(--green,#15803d)" : "inherit" }}>
                      {r.amount_inr >= 0 ? "+" : "−"}{fmt(Math.abs(r.amount_inr)).slice(1)}
                    </td>
                    <td style={{ ...td, textAlign: "right", fontVariantNumeric: "tabular-nums" }}>{fmt(r.balance_after)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

const th: React.CSSProperties = { padding: "6px 10px", fontWeight: 500, fontSize: ".76rem", textTransform: "uppercase", letterSpacing: ".04em" };
const td: React.CSSProperties = { padding: "8px 10px" };

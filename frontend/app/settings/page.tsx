"use client";
import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { getBilling, recharge, me, logout, type Billing, type Me } from "../../lib/api";

const QUICK = [100, 500, 1000, 2000];

function fmt(n: number) { return "₹" + n.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 }); }
function when(ts: number) { return new Date(ts * 1000).toLocaleString("en-IN", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" }); }

function BillingPanel() {
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
    <div>
      <div className="kpis" style={{ gridTemplateColumns: "minmax(0,1.2fr) minmax(0,2fr)" }}>
        <div className="card kpi" style={low ? { borderLeft: "3px solid var(--amber)" } : undefined}>
          <div className="k-lbl">Wallet balance</div>
          <div className="k-val" style={{ color: low ? "var(--amber)" : undefined }}>{fmt(bal)}</div>
          <div className="k-sub">{low ? "running low — top up to keep using AI" : "pay-as-you-go"}</div>
        </div>
        <div className="card panel" style={{ margin: 0 }}>
          <div className="ph"><h3>Recharge</h3><span className="sub">add credit to your wallet</span></div>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 10 }}>
            {QUICK.map((q) => (
              <button key={q} onClick={() => setAmount(String(q))}
                style={{ padding: "7px 14px", borderRadius: 8, cursor: "pointer",
                  border: "1px solid var(--line-strong)",
                  background: Number(amount) === q ? "var(--accent)" : "transparent",
                  color: Number(amount) === q ? "#fff" : "inherit", fontWeight: 500 }}>₹{q}</button>
            ))}
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            <input value={amount} inputMode="numeric" onChange={(e) => setAmount(e.target.value.replace(/[^0-9.]/g, ""))}
              style={{ height: 40, flex: 1, borderRadius: 8, border: "1px solid var(--line-strong)", padding: "0 12px", background: "var(--surface)", color: "inherit" }} />
            <button className="btn-primary" onClick={topUp} disabled={busy} style={{ padding: "0 18px", minHeight: 40 }}>
              {busy ? "Adding…" : "Add credit"}
            </button>
          </div>
          {err && <div style={{ color: "var(--red)", fontSize: ".82rem", marginTop: 10 }}>⚠ {err}</div>}
          <p className="muted" style={{ fontSize: ".76rem", margin: "10px 0 0" }}>
            Simulated top‑up for now. In production this is where a payment gateway (e.g. Razorpay) confirms the payment, then credits your wallet.
          </p>
        </div>
      </div>

      <div className="card panel" style={{ marginTop: 16 }}>
        <div className="ph"><h3>Usage &amp; transactions</h3><span className="sub">every AI action debits your balance</span></div>
        {!data ? <p className="muted">Loading…</p> : data.ledger.length === 0 ? (
          <p className="muted">No activity yet. Ask a question or add a document and it&apos;ll show here.</p>
        ) : (
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: ".85rem" }}>
              <thead>
                <tr style={{ textAlign: "left", color: "var(--muted)" }}>
                  <th style={th}>When</th><th style={th}>Type</th><th style={th}>Detail</th>
                  <th style={{ ...th, textAlign: "right" }}>Amount</th><th style={{ ...th, textAlign: "right" }}>Balance</th>
                </tr>
              </thead>
              <tbody>
                {data.ledger.map((r, i) => (
                  <tr key={i} style={{ borderTop: "1px solid var(--line)" }}>
                    <td style={td}>{when(r.ts)}</td>
                    <td style={td}>{r.kind}</td>
                    <td style={{ ...td, color: "var(--muted)" }}>{r.detail}</td>
                    <td style={{ ...td, textAlign: "right", fontVariantNumeric: "tabular-nums",
                      color: r.amount_inr >= 0 ? "var(--accent-ink)" : "inherit" }}>
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

function ProfilePanel() {
  const [profile, setProfile] = useState<Me | null>(null);
  const [theme, setTheme] = useState<"light" | "dark">("light");

  useEffect(() => {
    me().then(setProfile).catch(() => {});
    const saved = (typeof document !== "undefined" && document.documentElement.getAttribute("data-theme")) as "light" | "dark" | null;
    if (saved) setTheme(saved);
  }, []);

  function toggleTheme() {
    const next = theme === "dark" ? "light" : "dark";
    setTheme(next);
    document.documentElement.setAttribute("data-theme", next);
    try { localStorage.setItem("ganak-theme", next); } catch {}
  }

  return (
    <div>
      <div className="card panel">
        <div className="ph"><h3>Your account</h3><span className="sub">read-only</span></div>
        {!profile ? <p className="muted">Loading…</p> : (
          <>
            <div className="setting-row">
              <div><div className="st-lbl">Company</div><div className="st-desc">Your workspace name.</div></div>
              <div style={{ fontWeight: 600 }}>{profile.company}</div>
            </div>
            <div className="setting-row">
              <div><div className="st-lbl">Location</div><div className="st-desc">Used for tax/currency context.</div></div>
              <div>{profile.location || "—"}</div>
            </div>
            <div className="setting-row">
              <div><div className="st-lbl">Email</div><div className="st-desc">Your sign-in address.</div></div>
              <div>{profile.email}</div>
            </div>
            <div className="setting-row">
              <div><div className="st-lbl">Role</div><div className="st-desc">Access level on this workspace.</div></div>
              <div style={{ textTransform: "capitalize" }}>{profile.role || "owner"}</div>
            </div>
          </>
        )}
      </div>

      <div className="card panel" style={{ marginTop: 16 }}>
        <div className="ph"><h3>Appearance</h3></div>
        <div className="setting-row">
          <div><div className="st-lbl">Dark mode</div><div className="st-desc">Switch how Ganak looks on this device.</div></div>
          <button className={"toggle" + (theme === "dark" ? " on" : "")} role="switch" aria-checked={theme === "dark"} aria-label="Dark mode" onClick={toggleTheme} />
        </div>
      </div>

      <div className="card panel" style={{ marginTop: 16 }}>
        <div className="ph"><h3>Session</h3></div>
        <p className="muted" style={{ marginTop: 0 }}>Sign out of Ganak on this device.</p>
        <button className="btn-secondary" onClick={logout}>Log out</button>
      </div>
    </div>
  );
}

function SettingsInner() {
  const router = useRouter();
  const params = useSearchParams();
  const initialTab = params.get("tab") === "profile" ? "profile" : "billing";
  const [tab, setTab] = useState<"billing" | "profile">(initialTab);

  function switchTab(t: "billing" | "profile") {
    setTab(t);
    router.replace(`/settings?tab=${t}`);
  }

  return (
    <div className="view" style={{ maxWidth: 820 }}>
      <div className="tabs">
        <button className={tab === "billing" ? "active" : ""} onClick={() => switchTab("billing")}>Billing</button>
        <button className={tab === "profile" ? "active" : ""} onClick={() => switchTab("profile")}>Profile</button>
      </div>
      {tab === "billing" ? <BillingPanel /> : <ProfilePanel />}
    </div>
  );
}

export default function Settings() {
  return (
    <Suspense fallback={<div className="view"><p className="muted">Loading…</p></div>}>
      <SettingsInner />
    </Suspense>
  );
}

const th: React.CSSProperties = { padding: "6px 10px", fontWeight: 500, fontSize: ".76rem", textTransform: "uppercase", letterSpacing: ".04em" };
const td: React.CSSProperties = { padding: "8px 10px" };

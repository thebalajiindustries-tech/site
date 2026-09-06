"use client";
import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import {
  listConnectors, startConnector, syncConnectorNow, disconnectConnector,
  type ConnectorInfo,
} from "../../lib/api";

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

function ConnectionsInner() {
  const params = useSearchParams();
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
    <div className="view">
      <p className="muted" style={{ marginTop: 0, maxWidth: 640 }}>
        Ganak reads a synced, read-only copy of your own data — it can never change or
        delete anything in the source tool. Connect your own Zoho Books org and Gmail
        below; each connects to your account, not anyone else&apos;s.
      </p>

      {banner && <div className="card" style={{ padding: "10px 14px", marginBottom: 12, borderLeft: "3px solid var(--teal,#0d9488)" }}>{banner}</div>}
      {err && <div className="card" style={{ padding: "10px 14px", marginBottom: 12, borderLeft: "3px solid #b91c1c", color: "#b91c1c" }}>⚠ {err}</div>}

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
                      <span style={{ color: "#b91c1c" }}> · {c.last_error}</span>
                    )}
                  </div>
                )}
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <span className={"pill " + pillClass}>{label}</span>
                {c?.configured && !c.connected && (
                  <button className="send" disabled={busy === provider}
                    onClick={() => connect(provider)}
                    style={{ padding: "6px 14px", borderRadius: 8, fontWeight: 600 }}>
                    {busy === provider ? "Connecting…" : `Connect ${m.name}`}
                  </button>
                )}
                {c?.connected && (
                  <>
                    <button disabled={busy === provider} onClick={() => syncNow(provider)}
                      style={{ padding: "6px 12px", borderRadius: 8, border: "1px solid var(--line,#d8dbe0)", background: "transparent", cursor: "pointer" }}>
                      {busy === provider ? "…" : "Sync now"}
                    </button>
                    <button disabled={busy === provider} onClick={() => disconnect(provider)}
                      style={{ padding: "6px 12px", borderRadius: 8, border: "1px solid var(--line,#d8dbe0)", background: "transparent", cursor: "pointer", color: "#b91c1c" }}>
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

export default function Connections() {
  return (
    <Suspense fallback={<div className="view"><p className="muted">Loading…</p></div>}>
      <ConnectionsInner />
    </Suspense>
  );
}

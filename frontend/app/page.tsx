"use client";
import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import {
  ask, health, me, getBilling, listConnectors, getDigest,
  type Me, type Billing, type ConnectorInfo, type DigestSettings, type AskResponse,
} from "../lib/api";
import ResultView from "../components/ResultView";

type KpiDef = {
  key: string; label: string; q: string; prevQ?: string; money: boolean;
};

const KPIS: KpiDef[] = [
  {
    key: "revenue", label: "Paid revenue (30d)", money: true,
    q: "What is my total paid invoice revenue in the last 30 days? Return a single total.",
    prevQ: "What was my total paid invoice revenue in the 30 days before that (31 to 60 days ago)? Return a single total.",
  },
  {
    key: "receivable", label: "Outstanding receivables", money: true,
    q: "What is the total outstanding balance on unpaid or overdue invoices right now? Return a single total.",
  },
  {
    key: "expenses", label: "Expenses (30d)", money: true,
    q: "What are my total expenses in the last 30 days? Return a single total.",
    prevQ: "What were my total expenses in the 30 days before that (31 to 60 days ago)? Return a single total.",
  },
  {
    key: "invoices", label: "Invoices raised (30d)", money: false,
    q: "How many invoices were created in the last 30 days? Return a single count.",
    prevQ: "How many invoices were created in the 30 days before that (31 to 60 days ago)? Return a single count.",
  },
];

const SUGGESTIONS = [
  "What's my paid revenue for the last 6 months?",
  "Who owes me the most money right now?",
  "Break down my expenses by category this quarter",
  "Compare this month's sales to last month",
];

const PROVIDER_NAME: Record<string, string> = { zoho: "Zoho Books", gmail: "Gmail" };
const KIND_META: Record<string, string> = {
  ask: "Asked a question", "ask-live": "Asked a question (live)",
  document: "Added a document", digest: "Email digest sent", recharge: "Wallet top-up",
};

function headline(answer: string): string {
  const m = answer.match(/₹[\d,.]+\s?(?:lakh|crore|L|Cr|k)?|\b\d[\d,]*(?:\.\d+)?%?/i);
  return m ? m[0] : answer.length > 40 ? answer.slice(0, 40) + "…" : answer;
}

function numFrom(s: string | null): number | null {
  if (!s) return null;
  const n = parseFloat(s.replace(/[^0-9.\-]/g, ""));
  return isNaN(n) ? null : n;
}

function when(ts: number) {
  if (!ts) return "";
  return new Date(ts * 1000).toLocaleString("en-IN", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
}

function fmtInr(n: number) {
  return "₹" + n.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

// A tiny two-point sparkline: honest about what we actually have (a "then"
// and a "now"), not a fabricated multi-point trend line.
function Spark({ prev, cur, up }: { prev: number; cur: number; up: boolean }) {
  const lo = Math.min(prev, cur), hi = Math.max(prev, cur);
  const span = hi - lo || 1;
  const y1 = 20 - ((prev - lo) / span) * 14 - 3;
  const y2 = 20 - ((cur - lo) / span) * 14 - 3;
  const color = up ? "var(--accent)" : "var(--red)";
  return (
    <svg className="spark" width="40" height="20" viewBox="0 0 40 20">
      <polyline points={`2,${y1} 38,${y2}`} fill="none" stroke={color} strokeWidth={2} strokeLinecap="round" />
      <circle cx={38} cy={y2} r={2.4} fill={color} />
    </svg>
  );
}

function TrendPill({ prev, cur }: { prev: number; cur: number }) {
  if (prev === 0) return null;
  const pct = ((cur - prev) / Math.abs(prev)) * 100;
  const flat = Math.abs(pct) < 0.5;
  const up = pct > 0;
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
      <span className={"trend " + (flat ? "flat" : up ? "up" : "down")}>
        {!flat && (
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={3} strokeLinecap="round">
            {up ? <path d="M4 17 20 3M20 3H9M20 3v11" /> : <path d="M4 7 20 21M20 21H9M20 21V10" />}
          </svg>
        )}
        {flat ? "flat" : `${up ? "+" : ""}${pct.toFixed(1)}%`}
      </span>
      <Spark prev={prev} cur={cur} up={up} />
    </div>
  );
}

export default function Home() {
  const router = useRouter();
  const [db, setDb] = useState<string>("checking");
  const [profile, setProfile] = useState<Me | null>(null);
  const [vals, setVals] = useState<(string | null)[]>(KPIS.map(() => null));
  const [prevVals, setPrevVals] = useState<(string | null)[]>(KPIS.map(() => null));
  const [errs, setErrs] = useState<(string | null)[]>(KPIS.map(() => null));
  const [connectors, setConnectors] = useState<ConnectorInfo[] | null>(null);
  const [digest, setDigest] = useState<DigestSettings | null>(null);
  const [billing, setBilling] = useState<Billing | null>(null);

  const [askInput, setAskInput] = useState("");
  const [askBusy, setAskBusy] = useState(false);
  const [askData, setAskData] = useState<AskResponse | null>(null);
  const [askErr, setAskErr] = useState<string | null>(null);
  const [askedQ, setAskedQ] = useState("");
  const askRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const TTL = 10 * 60 * 1000; // reuse KPI answers for 10 min to avoid re-billing
    health().then((h) => setDb(h.database)).catch(() => setDb("down"));
    me().then(setProfile).catch(() => {});
    listConnectors().then(setConnectors).catch(() => {});
    getDigest().then(setDigest).catch(() => {});
    getBilling().then(setBilling).catch(() => {});

    KPIS.forEach((k, i) => {
      const key = `ganak-kpi:${k.key}`;
      try {
        const raw = localStorage.getItem(key);
        if (raw) {
          const c = JSON.parse(raw) as { v: string; pv?: string; t: number };
          if (c && typeof c.v === "string" && Date.now() - c.t < TTL) {
            setVals((v) => { const a = [...v]; a[i] = c.v; return a; });
            if (c.pv) setPrevVals((v) => { const a = [...v]; a[i] = c.pv!; return a; });
            return; // fresh cache — no API call
          }
        }
      } catch {}
      Promise.all([ask(k.q), k.prevQ ? ask(k.prevQ).catch(() => null) : Promise.resolve(null)])
        .then(([cur, prev]) => {
          const h = headline(cur.answer);
          const ph = prev ? headline(prev.answer) : undefined;
          setVals((v) => { const a = [...v]; a[i] = h; return a; });
          if (ph) setPrevVals((v) => { const a = [...v]; a[i] = ph; return a; });
          try { localStorage.setItem(key, JSON.stringify({ v: h, pv: ph, t: Date.now() })); } catch {}
        })
        .catch((e) => setErrs((v) => { const a = [...v]; a[i] = (e as Error).message; return a; }));
    });
  }, []);

  async function submitAsk(q: string) {
    q = q.trim();
    if (!q || askBusy) return;
    setAskBusy(true); setAskErr(null); setAskedQ(q);
    try {
      const data = await ask(q, "warehouse");
      setAskData(data);
    } catch (e) {
      setAskErr((e as Error).message);
      setAskData(null);
    } finally {
      setAskBusy(false);
      requestAnimationFrame(() => askRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" }));
    }
  }

  const attn: { key: string; msg: string; href: string }[] = [];
  if (profile && profile.balance_inr < 10) {
    attn.push({ key: "bal", href: "/settings?tab=billing",
      msg: `Wallet balance is low (${fmtInr(profile.balance_inr)}) — top up to keep AI features running.` });
  }
  (connectors || []).filter((c) => c.connected && c.status === "error").forEach((c) => {
    attn.push({ key: "conn-" + c.provider, href: "/sources?tab=connections",
      msg: `${PROVIDER_NAME[c.provider] || c.provider} sync needs attention${c.last_error ? ": " + c.last_error : "."}` });
  });
  if (digest?.log?.[0]?.status === "error") {
    attn.push({ key: "digest", href: "/digests", msg: `Last email digest failed: ${digest.log[0].detail}` });
  }

  const feed = billing ? [...billing.ledger].sort((a, b) => b.ts - a.ts).slice(0, 8) : [];

  return (
    <div className="view">
      {db === "down" && (
        <div className="card" style={{ padding: "12px 16px", marginBottom: 16, borderLeft: "3px solid var(--amber)" }}>
          <b>Warehouse not reachable.</b> <span className="muted">Start the backend and point <code>DATABASE_URL</code> at your Postgres, then refresh.</span>
        </div>
      )}

      <div className="ask-bar">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="var(--faint)" strokeWidth={2} strokeLinecap="round" style={{ flexShrink: 0 }}>
          <circle cx="11" cy="11" r="7" /><path d="m21 21-4.3-4.3" />
        </svg>
        <input
          placeholder="Ask about your business — e.g. who owes me the most?"
          value={askInput}
          onChange={(e) => setAskInput(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); submitAsk(askInput); } }}
        />
        <button className="send" onClick={() => submitAsk(askInput)} disabled={askBusy || !askInput.trim()}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.2} strokeLinecap="round"><path d="M22 2 11 13M22 2l-7 20-4-9-9-4 20-7z" /></svg>
        </button>
      </div>

      {(askBusy || askData || askErr) && (
        <div className="card panel" style={{ marginTop: 12 }} ref={askRef}>
          <div className="ph"><h3 style={{ fontSize: ".92rem" }}>{askedQ}</h3></div>
          {askBusy ? (
            <span className="typing"><i /><i /><i /></span>
          ) : askErr ? (
            <p className="ans errbox">⚠ {askErr}</p>
          ) : askData ? (
            <>
              <ResultView data={askData} />
              <button onClick={() => router.push(`/ask?q=${encodeURIComponent(askedQ)}`)}
                style={{ marginTop: 12, background: "none", border: "none", color: "var(--accent-ink)", fontWeight: 600, fontSize: ".84rem", padding: 0, cursor: "pointer" }}>
                Continue in full chat →
              </button>
            </>
          ) : null}
        </div>
      )}

      <div className="kpis" style={{ marginTop: 16 }}>
        {KPIS.map((k, i) => {
          const cur = numFrom(vals[i]);
          const prev = numFrom(prevVals[i]);
          return (
            <div className="card kpi" key={k.key}>
              <div className="k-lbl">{k.label}</div>
              <div className="k-val">
                {errs[i] ? <span className="muted" style={{ fontSize: ".8rem" }}>—</span>
                  : vals[i] === null ? <span className="skl" />
                  : vals[i]}
              </div>
              <div className="k-foot">
                <div className="k-sub">{errs[i] ? "unavailable" : "live from warehouse"}</div>
                {cur !== null && prev !== null && <TrendPill prev={prev} cur={cur} />}
              </div>
            </div>
          );
        })}
      </div>

      <div className="home-grid">
        <div>
          <div className="card panel">
            <div className="ph"><h3>Needs attention</h3><span className="sub">{attn.length || "0"}</span></div>
            {attn.length === 0 ? (
              <div className="attn-row ok">
                <span className="attn-dot" />
                <div className="attn-body"><div className="attn-msg">Everything looks good — connections are syncing and your wallet is funded.</div></div>
              </div>
            ) : (
              <div className="attn-list">
                {attn.map((a) => (
                  <div className="attn-row" key={a.key}>
                    <span className="attn-dot" />
                    <div className="attn-body"><div className="attn-msg">{a.msg}</div></div>
                    <button className="attn-link" style={{ background: "none", border: "none", cursor: "pointer" }} onClick={() => router.push(a.href)}>Fix →</button>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="card panel" style={{ marginTop: 16 }}>
            <div className="ph"><h3>Try asking</h3><span className="sub">powered by your data</span></div>
            <div className="sugg" style={{ margin: 0 }}>
              {SUGGESTIONS.map((s) => (
                <button key={s} onClick={() => submitAsk(s)}>{s}</button>
              ))}
            </div>
          </div>
        </div>

        <div className="card panel">
          <div className="ph"><h3>Recent activity</h3><span className="sub">from your wallet ledger</span></div>
          {!billing ? (
            <p className="muted">Loading…</p>
          ) : feed.length === 0 ? (
            <p className="muted">Nothing yet — ask a question, add a document, or connect a source.</p>
          ) : (
            <div className="feed-list">
              {feed.map((r, i) => (
                <div className="feed-row" key={i}>
                  <span className="feed-ic">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round">
                      {r.kind === "recharge" ? <path d="M12 5v14M5 12h14" /> : r.kind === "document" ? <path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9l-6-6zM14 3v6h6" /> : r.kind === "digest" ? <><path d="M3 6h18v12H3z" /><path d="m3 7 9 6 9-6" /></> : <path d="M21 11.5a8.5 8.5 0 0 1-12 7.7L3 21l1.8-5.9A8.5 8.5 0 1 1 21 11.5z" />}
                    </svg>
                  </span>
                  <div className="feed-body">
                    <div className="feed-title">{KIND_META[r.kind] || r.kind}{r.detail ? ` · ${r.detail}` : ""}</div>
                    <div className="feed-when">{when(r.ts)}</div>
                  </div>
                  <span className="feed-amt" style={{ color: r.amount_inr >= 0 ? "var(--accent-ink)" : "var(--muted)" }}>
                    {r.amount_inr >= 0 ? "+" : "−"}{fmtInr(Math.abs(r.amount_inr)).slice(1)}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

"use client";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { ask, health } from "../lib/api";

const KPIS = [
  { label: "Paid revenue (last 6 months)", q: "What is my total paid invoice revenue in the last 6 months? Return a single total." },
  { label: "Outstanding receivables", q: "What is the total outstanding balance on unpaid or overdue invoices right now? Return a single total." },
  { label: "Expenses (this quarter)", q: "What are my total expenses this quarter? Return a single total." },
  { label: "Invoices this month", q: "How many invoices were created this month? Return a single count." },
];

const SUGGESTIONS = [
  "What's my paid revenue for the last 6 months?",
  "Who owes me the most money right now?",
  "Break down my expenses by category this quarter",
  "Compare this month's sales to last month",
];

function headline(answer: string): string {
  const m = answer.match(/₹[\d,.]+\s?(?:lakh|crore|L|Cr|k)?|\b\d[\d,]*(?:\.\d+)?%?/i);
  return m ? m[0] : answer.length > 40 ? answer.slice(0, 40) + "…" : answer;
}

export default function Dashboard() {
  const router = useRouter();
  const [db, setDb] = useState<string>("checking");
  const [vals, setVals] = useState<(string | null)[]>(KPIS.map(() => null));
  const [errs, setErrs] = useState<(string | null)[]>(KPIS.map(() => null));

  useEffect(() => {
    health().then((h) => setDb(h.database)).catch(() => setDb("down"));
    KPIS.forEach((k, i) => {
      ask(k.q)
        .then((r) => setVals((v) => { const c = [...v]; c[i] = headline(r.answer); return c; }))
        .catch((e) => setErrs((v) => { const c = [...v]; c[i] = (e as Error).message; return c; }));
    });
  }, []);

  return (
    <div className="view">
      {db === "down" && (
        <div className="card" style={{ padding: "12px 16px", marginBottom: 16, borderLeft: "3px solid var(--amber)" }}>
          <b>Warehouse not reachable.</b> <span className="muted">Start the backend and point <code>DATABASE_URL</code> at your Postgres, then refresh.</span>
        </div>
      )}
      <div className="kpis">
        {KPIS.map((k, i) => (
          <div className="card kpi" key={i}>
            <div className="k-lbl">{k.label}</div>
            <div className="k-val">
              {errs[i] ? <span className="muted" style={{ fontSize: ".8rem" }}>—</span>
                : vals[i] === null ? <span className="skl" />
                : vals[i]}
            </div>
            <div className="k-sub">{errs[i] ? "unavailable" : "live from warehouse"}</div>
          </div>
        ))}
      </div>

      <div className="card panel">
        <div className="ph"><h3>Ask a question</h3><span className="sub">powered by your Zoho data</span></div>
        <p className="muted" style={{ marginTop: 0 }}>Skip the dashboards — ask Ganak directly and it writes the SQL, runs it, and answers with a chart.</p>
        <div className="sugg" style={{ margin: 0 }}>
          {SUGGESTIONS.map((s) => (
            <button key={s} onClick={() => router.push("/ask")}>{s}</button>
          ))}
        </div>
      </div>
    </div>
  );
}

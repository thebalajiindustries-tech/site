"use client";
import type { AskResponse } from "../lib/api";

function num(v: unknown): number | null {
  if (typeof v === "number") return v;
  if (typeof v === "string") { const n = parseFloat(v.replace(/[^0-9.\-]/g, "")); return isNaN(n) ? null : n; }
  return null;
}

export default function ResultView({ data }: { data: AskResponse }) {
  const { chart, rows, columns } = data;
  const xKey = chart?.x && columns.includes(chart.x) ? chart.x : columns[0];
  const yKey = chart?.y && columns.includes(chart.y) ? chart.y : columns[1];

  const canBar =
    chart?.type === "bar" && xKey && yKey && rows.length > 0 && rows.length <= 20 &&
    rows.every((r) => num(r[yKey!]) !== null);

  return (
    <div>
      <p className="ans" dangerouslySetInnerHTML={{ __html: boldNumbers(data.answer) }} />

      {data.sql && (
        <details className="sqlbox">
          <summary>view the SQL Ganak wrote</summary>
          <pre>{data.sql}</pre>
        </details>
      )}

      {canBar ? (
        <div style={{ marginTop: 14 }}>
          {(() => {
            const vals = rows.map((r) => num(r[yKey!])!);
            const max = Math.max(...vals, 1);
            return rows.map((r, i) => (
              <div className="barrow" key={i}>
                <span className="lbl">{String(r[xKey!])}</span>
                <span className="track"><span className="fill" style={{ width: `${(vals[i] / max) * 100}%` }} /></span>
                <span className="v">{vals[i].toLocaleString()}</span>
              </div>
            ));
          })()}
        </div>
      ) : rows.length > 0 ? (
        <div style={{ overflowX: "auto" }}>
          <table className="tbl">
            <thead><tr>{columns.map((c) => <th key={c}>{c}</th>)}</tr></thead>
            <tbody>
              {rows.slice(0, 20).map((r, i) => (
                <tr key={i}>{columns.map((c) => <td key={c}>{String(r[c] ?? "")}</td>)}</tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  );
}

function boldNumbers(s: string): string {
  return s
    .replace(/&/g, "&amp;").replace(/</g, "&lt;")
    .replace(/(₹[\d,.]+\s?(?:lakh|crore|L|Cr|k)?|\b\d[\d,]*(?:\.\d+)?%?)/gi, "<b>$1</b>");
}

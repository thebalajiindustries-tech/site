"use client";
import { useEffect, useState } from "react";
import { adminOverview, type AdminOverview, type AdminTenant } from "../../lib/api";

function fmtInr(n: number) {
  return "₹" + n.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}
function when(ts: number) {
  if (!ts) return "—";
  return new Date(ts * 1000).toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });
}
function whenAgo(ts: number) {
  if (!ts) return "never";
  return new Date(ts * 1000).toLocaleString("en-IN", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
}

const th: React.CSSProperties = { padding: "6px 10px", fontWeight: 500, fontSize: ".76rem", textTransform: "uppercase", letterSpacing: ".04em" };
const td: React.CSSProperties = { padding: "10px 10px", verticalAlign: "top" };

function ConnectorBadges({ tenant }: { tenant: AdminTenant }) {
  if (tenant.connectors.length === 0) {
    return <span className="muted" style={{ fontSize: ".8rem" }}>none connected</span>;
  }
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      {tenant.connectors.map((c) => {
        const isError = c.status === "error";
        return (
          <span key={c.provider} style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: ".78rem" }}>
            <span
              className="pill"
              style={{
                margin: 0,
                background: isError ? "var(--red-soft)" : "var(--accent-soft)",
                color: isError ? "var(--red)" : "var(--accent-ink)",
              }}
            >
              {c.provider}
            </span>
            <span className="muted">
              {isError ? (c.last_error || "error") : `synced ${whenAgo(c.last_synced_at)}`}
            </span>
          </span>
        );
      })}
    </div>
  );
}

export default function AdminPage() {
  const [data, setData] = useState<AdminOverview | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    adminOverview().then(setData).catch((e) => setErr((e as Error).message));
  }, []);

  if (err) {
    return (
      <div className="view">
        <div className="card panel" style={{ padding: "12px 16px", borderLeft: "3px solid var(--red)" }}>
          <b>Can&apos;t load the admin overview.</b>{" "}
          <span className="muted">{err}</span>
        </div>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="view">
        <p className="muted">Loading…</p>
      </div>
    );
  }

  const { totals, tenants } = data;

  return (
    <div className="view">
      <div className="kpis" style={{ marginTop: 0 }}>
        <div className="card kpi">
          <div className="k-lbl">Companies</div>
          <div className="k-val">{totals.tenant_count}</div>
          <div className="k-foot"><div className="k-sub">{totals.user_count} user{totals.user_count === 1 ? "" : "s"} total</div></div>
        </div>
        <div className="card kpi">
          <div className="k-lbl">Total wallet balance</div>
          <div className="k-val">{fmtInr(totals.total_balance_inr)}</div>
          <div className="k-foot"><div className="k-sub">across all companies</div></div>
        </div>
        <div className="card kpi">
          <div className="k-lbl">Total spent</div>
          <div className="k-val">{fmtInr(totals.total_spent_inr)}</div>
          <div className="k-foot"><div className="k-sub">lifetime, all AI usage</div></div>
        </div>
        <div className="card kpi">
          <div className="k-lbl">Total recharged</div>
          <div className="k-val">{fmtInr(totals.total_recharged_inr)}</div>
          <div className="k-foot"><div className="k-sub">lifetime top-ups</div></div>
        </div>
      </div>

      <div className="card panel" style={{ marginTop: 16 }}>
        <div className="ph"><h3>Companies</h3><span className="sub">{tenants.length} total</span></div>
        {tenants.length === 0 ? (
          <p className="muted">No companies have signed up yet.</p>
        ) : (
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: ".85rem" }}>
              <thead>
                <tr style={{ textAlign: "left", color: "var(--muted)" }}>
                  <th style={th}>Company</th>
                  <th style={th}>Users</th>
                  <th style={{ ...th, textAlign: "right" }}>Balance</th>
                  <th style={{ ...th, textAlign: "right" }}>Spent</th>
                  <th style={{ ...th, textAlign: "right" }}>Recharged</th>
                  <th style={th}>Sources</th>
                  <th style={th}>Joined</th>
                </tr>
              </thead>
              <tbody>
                {tenants.map((t) => (
                  <tr key={t.id} style={{ borderTop: "1px solid var(--line)" }}>
                    <td style={td}>
                      <div style={{ fontWeight: 600 }}>{t.name}</div>
                      {t.location && <div className="muted" style={{ fontSize: ".78rem" }}>{t.location}</div>}
                    </td>
                    <td style={td}>
                      {t.users.map((u) => (
                        <div key={u.email} style={{ fontSize: ".82rem" }}>
                          {u.email}
                          <span className="muted"> · {u.role}</span>
                        </div>
                      ))}
                    </td>
                    <td style={{ ...td, textAlign: "right", fontVariantNumeric: "tabular-nums" }}>
                      {fmtInr(t.balance_inr)}
                    </td>
                    <td style={{ ...td, textAlign: "right", fontVariantNumeric: "tabular-nums" }}>
                      {fmtInr(t.total_spent_inr)}
                    </td>
                    <td style={{ ...td, textAlign: "right", fontVariantNumeric: "tabular-nums" }}>
                      {fmtInr(t.total_recharged_inr)}
                    </td>
                    <td style={td}><ConnectorBadges tenant={t} /></td>
                    <td style={{ ...td, color: "var(--muted)", fontSize: ".8rem" }}>{when(t.created_at)}</td>
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

export default function Billing() {
  return (
    <div className="view">
      <div className="card panel" style={{ marginBottom: 16 }}>
        <div className="ph"><h3>Business plan</h3><span className="sub">single-tenant preview</span></div>
        <p className="muted" style={{ marginTop: 0 }}>
          Billing and usage metering land in the next milestone (Stripe subscriptions + a
          <code> question_answered </code> meter for pay-as-you-go). For now this build runs
          single-tenant on your own warehouse with no limits.
        </p>
      </div>
      <div className="static-list">
        {[
          ["Starter", "₹0 /mo + ₹5 / question", "Pay as you go"],
          ["Business", "₹1,499 /mo — 500 questions", "Most popular"],
          ["Pro", "₹3,999 /mo — 2,000 questions", "Zoho + Tally + email"],
        ].map(([n, p, t]) => (
          <div className="card conn-row" key={n}>
            <div>
              <div className="cn">{n}</div>
              <div className="cd">{t}</div>
            </div>
            <span className="pill off" style={{ fontFamily: "IBM Plex Mono" }}>{p}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

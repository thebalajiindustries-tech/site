const CONNS = [
  { n: "Zoho Books", c: "#E42527", i: "Z", ok: true,
    d: "Invoices, expenses, bills, payments, customers — synced to your warehouse every 30 min." },
  { n: "Gmail", c: "#D14836", i: "G", ok: true,
    d: "Finance emails classified into an emails table: payments received, bank advices, vendor bills, balance confirmations, quotations, POs." },
  { n: "Tally", c: "#1F71B8", i: "T", ok: false,
    d: "Ledgers and vouchers from Tally Prime. Great for GST data." },
  { n: "Outlook", c: "#0A78D4", i: "O", ok: false,
    d: "Finance emails for Microsoft 365 businesses." },
];

export default function Connections() {
  return (
    <div className="view">
      <p className="muted" style={{ marginTop: 0, maxWidth: 640 }}>
        Ganak reads a synced, read-only copy of your data — it can never change or
        delete anything in the source tool. Zoho Books and Gmail feed the same
        warehouse, so the AI can answer across both.
      </p>
      <div className="static-list">
        {CONNS.map((c) => (
          <div className="card conn-row" key={c.n}>
            <span className="ci" style={{ background: c.c }}>{c.i}</span>
            <div>
              <div className="cn">{c.n}</div>
              <div className="cd">{c.d}</div>
            </div>
            <span className={"pill " + (c.ok ? "ok" : "off")}>{c.ok ? "Connected" : "Coming soon"}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

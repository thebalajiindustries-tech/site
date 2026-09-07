"use client";
import { useEffect, useRef, useState } from "react";
import { getDigest, saveDigest, sendDigestNow, me, type DigestSettings } from "../../lib/api";

const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const HOURS = Array.from({ length: 24 }, (_, h) => {
  const label = h === 0 ? "12:00 AM" : h < 12 ? `${h}:00 AM` : h === 12 ? "12:00 PM" : `${h - 12}:00 PM`;
  return { value: h, label };
});

function isEmail(s: string) {
  const e = s.trim().toLowerCase();
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(e);
}

function when(ts: number) {
  if (!ts) return "";
  return new Date(ts * 1000).toLocaleString("en-IN", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
}

export default function Digests() {
  const [data, setData] = useState<DigestSettings | null>(null);
  const [enabled, setEnabled] = useState(false);
  const [frequency, setFrequency] = useState<"daily" | "weekly">("weekly");
  const [weekday, setWeekday] = useState(0);
  const [hour, setHour] = useState(8);
  const [recipients, setRecipients] = useState<string[]>([]);
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);
  const [sending, setSending] = useState(false);
  const [banner, setBanner] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  function applyFrom(d: DigestSettings) {
    setData(d);
    setEnabled(d.enabled);
    setFrequency(d.frequency);
    setWeekday(d.weekday);
    setHour(d.hour);
    setRecipients(d.recipients);
  }

  useEffect(() => {
    getDigest()
      .then((d) => {
        applyFrom(d);
        // First time through with nothing configured yet: default the
        // recipient list to the signed-in owner so there's one less step.
        if (d.recipients.length === 0) {
          me().then((m) => setRecipients([m.email])).catch(() => {});
        }
      })
      .catch((e) => setErr((e as Error).message));
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, []);

  function addChip(raw: string) {
    const e = raw.trim().toLowerCase().replace(/,$/, "");
    if (!e) return;
    if (!isEmail(e)) { setErr(`"${e}" doesn't look like a valid email address.`); return; }
    if (recipients.includes(e)) { setDraft(""); return; }
    if (recipients.length >= 10) { setErr("Please keep it to 10 recipients or fewer."); return; }
    setErr(null);
    setRecipients((r) => [...r, e]);
    setDraft("");
  }

  function onDraftKeyDown(ev: React.KeyboardEvent<HTMLInputElement>) {
    if (ev.key === "Enter" || ev.key === "," || ev.key === " ") { ev.preventDefault(); addChip(draft); }
    else if (ev.key === "Backspace" && !draft && recipients.length) {
      setRecipients((r) => r.slice(0, -1));
    }
  }

  async function save() {
    setSaving(true); setErr(null); setBanner(null);
    try {
      const result = await saveDigest({ enabled, frequency, weekday, hour, recipients });
      applyFrom(result);
      setBanner("Saved.");
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setSaving(false);
    }
  }

  async function sendTest() {
    setSending(true); setErr(null); setBanner(null);
    try {
      await sendDigestNow();
      setBanner("Sending a test digest now — it'll show up in the activity log below in a few seconds.");
      // poll briefly so the new log entry (sent or error) appears without a manual refresh
      let ticks = 0;
      pollRef.current = setInterval(() => {
        ticks += 1;
        getDigest().then(applyFrom).catch(() => {});
        if (ticks >= 6 && pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
      }, 2500);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setSending(false);
    }
  }

  if (!data) {
    return <div className="view"><p className="muted">Loading…</p></div>;
  }

  const dirty =
    enabled !== data.enabled || frequency !== data.frequency || weekday !== data.weekday ||
    hour !== data.hour || recipients.join(",") !== data.recipients.join(",");

  return (
    <div className="view" style={{ maxWidth: 720 }}>
      <p className="muted" style={{ marginTop: 0, maxWidth: 640 }}>
        A short, plain-English summary of your numbers — paid revenue, outstanding receivables,
        expenses, invoices raised, and your biggest receivable — emailed on the schedule below.
      </p>

      {!data.configured && (
        <div className="card" style={{ padding: "10px 14px", marginBottom: 12, borderLeft: "3px solid var(--amber)" }}>
          Email sending isn&apos;t set up on this server yet (SMTP_HOST / SMTP_FROM in <code>backend/.env</code>).
          You can still set your schedule and recipients below — nothing will send until that&apos;s configured.
        </div>
      )}
      {banner && <div className="card" style={{ padding: "10px 14px", marginBottom: 12, borderLeft: "3px solid var(--accent)" }}>{banner}</div>}
      {err && <div className="card" style={{ padding: "10px 14px", marginBottom: 12, borderLeft: "3px solid var(--red)", color: "var(--red)" }}>⚠ {err}</div>}

      <div className="card panel">
        <div className="ph"><h3>Digest schedule</h3><span className="sub">times are IST</span></div>

        <div className="setting-row">
          <div>
            <div className="st-lbl">Send email digests</div>
            <div className="st-desc">Turn the whole thing on or off.</div>
          </div>
          <button
            className={"toggle" + (enabled ? " on" : "")}
            role="switch" aria-checked={enabled} aria-label="Send email digests"
            onClick={() => setEnabled((v) => !v)}
          />
        </div>

        <div className="setting-row">
          <div>
            <div className="st-lbl">Frequency</div>
            <div className="st-desc">{frequency === "daily" ? "Every day, at the time below." : "Once a week, on the day and time below."}</div>
          </div>
          <div className="segmented">
            <button className={frequency === "daily" ? "active" : ""} onClick={() => setFrequency("daily")}>Daily</button>
            <button className={frequency === "weekly" ? "active" : ""} onClick={() => setFrequency("weekly")}>Weekly</button>
          </div>
        </div>

        {frequency === "weekly" && (
          <div className="setting-row">
            <div>
              <div className="st-lbl">Day of week</div>
              <div className="st-desc">Which day the weekly digest goes out.</div>
            </div>
            <div className="segmented">
              {DAYS.map((d, i) => (
                <button key={d} className={weekday === i ? "active" : ""} onClick={() => setWeekday(i)}>{d}</button>
              ))}
            </div>
          </div>
        )}

        <div className="setting-row">
          <div>
            <div className="st-lbl">Time of day</div>
            <div className="st-desc">Sent any time after this hour, IST.</div>
          </div>
          <select value={hour} onChange={(e) => setHour(Number(e.target.value))} style={selectStyle}>
            {HOURS.map((h) => <option key={h.value} value={h.value}>{h.label}</option>)}
          </select>
        </div>

        <div className="setting-row" style={{ flexDirection: "column", alignItems: "stretch", gap: 8 }}>
          <div>
            <div className="st-lbl">Recipients</div>
            <div className="st-desc">Up to 10 email addresses. Press Enter or comma to add one.</div>
          </div>
          <div className="chip-input">
            {recipients.map((r) => (
              <span className="chip" key={r}>
                {r}
                <button onClick={() => setRecipients((list) => list.filter((x) => x !== r))} aria-label={`Remove ${r}`}>×</button>
              </span>
            ))}
            <input
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={onDraftKeyDown}
              onBlur={() => draft && addChip(draft)}
              placeholder={recipients.length ? "Add another…" : "owner@yourcompany.com"}
              inputMode="email"
              autoCapitalize="off"
              autoCorrect="off"
            />
          </div>
        </div>

        <div className="btn-row" style={{ marginTop: 16 }}>
          <button className="btn-primary" onClick={save} disabled={saving || !dirty}>
            {saving ? "Saving…" : "Save changes"}
          </button>
          <button className="btn-secondary" onClick={sendTest} disabled={sending || !data.configured || recipients.length === 0}>
            {sending ? "Sending…" : "Send a test now"}
          </button>
        </div>
      </div>

      <div className="card panel" style={{ marginTop: 16 }}>
        <div className="ph"><h3>Recent activity</h3><span className="sub">last {data.log.length || 0} attempts</span></div>
        {data.log.length === 0 ? (
          <p className="muted">No digests sent yet — turn it on above, or send a test.</p>
        ) : (
          <div className="log-list">
            {data.log.map((l, i) => (
              <div className="log-row" key={i}>
                <span className={"log-dot " + (l.status === "sent" ? "sent" : "error")} />
                <div className="log-body">
                  <div className="log-when">{when(l.ts)} · {l.recipients}</div>
                  <div className={"log-detail" + (l.status === "error" ? " error" : "")}>{l.detail}</div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

const selectStyle: React.CSSProperties = {
  height: 42, borderRadius: 9, border: "1px solid var(--line-strong)", padding: "0 12px",
  fontSize: ".88rem", background: "var(--surface)", color: "inherit", minWidth: 150,
};

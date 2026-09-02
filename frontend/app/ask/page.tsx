"use client";
import { useRef, useState } from "react";
import { ask, type AskResponse } from "../../lib/api";
import ResultView from "../../components/ResultView";

type Msg =
  | { role: "user"; text: string }
  | { role: "bot"; loading: true }
  | { role: "bot"; loading: false; data?: AskResponse; error?: string };

const SUGGESTIONS = [
  "What's my paid revenue for the last 6 months?",
  "Who owes me the most money right now?",
  "Break down my expenses by category this quarter",
  "Show payment-received emails over ₹1 lakh this year",
  "Which vendors sent balance confirmations?",
  "How many bank payment advices did I get last month?",
];

const BotAva = () => (
  <span className="ava"><svg viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth={2.4} strokeLinecap="round"><path d="M4 19V5M4 19h16M8 15l3-4 3 2 4-6"/></svg></span>
);

export default function AskPage() {
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  async function send(q: string) {
    q = q.trim();
    if (!q || busy) return;
    setInput("");
    setBusy(true);
    setMsgs((m) => [...m, { role: "user", text: q }, { role: "bot", loading: true }]);
    try {
      const data = await ask(q);
      setMsgs((m) => [...m.slice(0, -1), { role: "bot", loading: false, data }]);
    } catch (e) {
      setMsgs((m) => [...m.slice(0, -1), { role: "bot", loading: false, error: (e as Error).message }]);
    } finally {
      setBusy(false);
      requestAnimationFrame(() => scrollRef.current?.scrollTo({ top: 1e9, behavior: "smooth" }));
    }
  }

  return (
    <div className="chatwrap">
      <div className="chatscroll" ref={scrollRef}>
        <div className="chatinner">
          <div className="msg bot">
            <BotAva />
            <div className="bub"><p className="ans">Hi Kiran 👋 I&apos;m connected to your Zoho warehouse. Ask me about revenue, expenses, who owes you money, or how this month compares.</p></div>
          </div>
          {msgs.map((m, i) =>
            m.role === "user" ? (
              <div className="msg user" key={i}><div className="bub">{m.text}</div></div>
            ) : (
              <div className="msg bot" key={i}>
                <BotAva />
                <div className="bub">
                  {"loading" in m && m.loading ? (
                    <span className="typing"><i /><i /><i /></span>
                  ) : m.error ? (
                    <p className="ans errbox">⚠ {m.error}</p>
                  ) : m.data ? (
                    <ResultView data={m.data} />
                  ) : null}
                </div>
              </div>
            )
          )}
        </div>
      </div>
      <div className="composer">
        <div className="composer-in">
          <div className="sugg">
            {SUGGESTIONS.map((s) => (
              <button key={s} onClick={() => send(s)} disabled={busy}>{s}</button>
            ))}
          </div>
          <div className="inbar">
            <textarea
              rows={1}
              placeholder="Ask about your finances…"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(input); } }}
            />
            <button className="send" onClick={() => send(input)} disabled={busy || !input.trim()}>
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.2} strokeLinecap="round"><path d="M22 2 11 13M22 2l-7 20-4-9-9-4 20-7z"/></svg>
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

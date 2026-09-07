"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { login, register } from "../../lib/api";

export default function LoginPage() {
  const router = useRouter();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [company, setCompany] = useState("");
  const [location, setLocation] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setErr(null);
    setBusy(true);
    try {
      if (mode === "login") await login(email.trim(), password);
      else await register(email.trim(), password, company.trim(), location.trim());
      router.replace("/");
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div style={{ minHeight: "100vh", display: "grid", placeItems: "center", background: "var(--ground)", padding: 24 }}>
      <div className="card" style={{ width: "100%", maxWidth: 420, padding: 32 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 6 }}>
          <span style={{ display: "grid", placeItems: "center", width: 34, height: 34, borderRadius: 9, background: "var(--accent)" }}>
            <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="#fff" strokeWidth={2.4} strokeLinecap="round"><path d="M4 19V5M4 19h16M8 15l3-4 3 2 4-6" /></svg>
          </span>
          <span style={{ fontSize: "1.35rem", fontWeight: 700 }}>Ganak</span>
        </div>
        <p className="muted" style={{ marginTop: 0, marginBottom: 22 }}>
          {mode === "login" ? "Sign in to your company workspace." : "Create your company workspace."}
        </p>

        <form onSubmit={submit} style={{ display: "grid", gap: 12 }}>
          {mode === "register" && (
            <>
              <label style={{ display: "grid", gap: 5, fontSize: ".85rem" }}>
                Company name
                <input value={company} onChange={(e) => setCompany(e.target.value)} required placeholder="Acme Traders" style={inp} />
              </label>
              <label style={{ display: "grid", gap: 5, fontSize: ".85rem" }}>
                Location <span className="muted">(optional)</span>
                <input value={location} onChange={(e) => setLocation(e.target.value)} placeholder="Pune" style={inp} />
              </label>
            </>
          )}
          <label style={{ display: "grid", gap: 5, fontSize: ".85rem" }}>
            Email
            <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required placeholder="you@company.com" style={inp} />
          </label>
          <label style={{ display: "grid", gap: 5, fontSize: ".85rem" }}>
            Password
            <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required placeholder="********" style={inp} />
          </label>

          {err && <div style={{ color: "var(--red)", fontSize: ".85rem" }}>! {err}</div>}

          <button type="submit" disabled={busy} className="send" style={{ height: 42, borderRadius: 9, fontWeight: 600, marginTop: 4 }}>
            {busy ? "Please wait..." : mode === "login" ? "Sign in" : "Create workspace"}
          </button>
        </form>

        <div style={{ marginTop: 16, fontSize: ".85rem", textAlign: "center" }} className="muted">
          {mode === "login" ? (
            <>New here? <a role="button" onClick={() => { setMode("register"); setErr(null); }} style={link}>Create a workspace</a></>
          ) : (
            <>Already have an account? <a role="button" onClick={() => { setMode("login"); setErr(null); }} style={link}>Sign in</a></>
          )}
        </div>
      </div>
    </div>
  );
}

const inp: React.CSSProperties = {
  height: 40, borderRadius: 8, border: "1px solid var(--line-strong)",
  padding: "0 12px", fontSize: ".92rem", background: "var(--surface)", color: "inherit",
};
const link: React.CSSProperties = { color: "var(--accent-ink)", cursor: "pointer", fontWeight: 600 };

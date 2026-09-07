"use client";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { getToken, me as fetchMe, logout, type Me } from "../lib/api";

const NAV = [
  { href: "/", label: "Home", group: "Workspace",
    icon: <><rect x="3" y="3" width="8" height="8" rx="1.5"/><rect x="13" y="3" width="8" height="5" rx="1.5"/><rect x="13" y="11" width="8" height="10" rx="1.5"/><rect x="3" y="14" width="8" height="7" rx="1.5"/></> },
  { href: "/ask", label: "Ask Ganak", group: "Workspace",
    icon: <path d="M21 11.5a8.5 8.5 0 0 1-12 7.7L3 21l1.8-5.9A8.5 8.5 0 1 1 21 11.5z"/> },
  { href: "/sources", label: "Sources", group: "Workspace",
    icon: <path d="M9 12h6M15.5 8.5 18 6a3.5 3.5 0 1 1 0 5l-2 2M8.5 15.5 6 18a3.5 3.5 0 1 1 0-5l2-2"/> },
  { href: "/digests", label: "Email Digests", group: "Workspace",
    icon: <><path d="M3 6h18v12H3z"/><path d="m3 7 9 6 9-6"/></> },
  { href: "/settings", label: "Settings", group: "Account",
    icon: <><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></> },
];
const TITLES: Record<string, string> = {
  "/": "Home", "/ask": "Ask Ganak", "/sources": "Sources",
  "/digests": "Email Digests", "/settings": "Settings",
};
// Old bookmarked paths redirect client-side (see their own page.tsx) but the
// shell still needs a sensible title for the instant before that fires.
const LEGACY_TITLES: Record<string, string> = {
  "/connections": "Sources", "/documents": "Sources", "/billing": "Settings",
};
const SHORT_LABEL: Record<string, string> = { "/ask": "Ask", "/digests": "Digests" };

export default function Shell({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const router = useRouter();
  const [theme, setTheme] = useState<"light" | "dark">("light");
  const [profile, setProfile] = useState<Me | null>(null);
  const [ready, setReady] = useState(false);
  const [navOpen, setNavOpen] = useState(false);

  // Close the mobile drawer on every route change (incl. tapping a nav item).
  useEffect(() => { setNavOpen(false); }, [path]);

  useEffect(() => {
    const saved = (typeof localStorage !== "undefined" && localStorage.getItem("ganak-theme")) as
      | "light" | "dark" | null;
    if (saved) { setTheme(saved); document.documentElement.setAttribute("data-theme", saved); }
  }, []);

  // Auth gate: everything except /login requires a valid session.
  useEffect(() => {
    if (path === "/login") { setReady(true); return; }
    if (!getToken()) { router.replace("/login"); return; }
    let alive = true;
    fetchMe()
      .then((m) => { if (alive) { setProfile(m); setReady(true); } })
      .catch(() => { logout(); });
    return () => { alive = false; };
  }, [path, router]);

  function toggle() {
    const next = theme === "dark" ? "light" : "dark";
    setTheme(next);
    document.documentElement.setAttribute("data-theme", next);
    try { localStorage.setItem("ganak-theme", next); } catch {}
  }

  // The login page renders on its own, without the app chrome.
  if (path === "/login") return <>{children}</>;

  if (!ready || !profile) {
    return <div style={{ minHeight: "100vh", display: "grid", placeItems: "center", color: "var(--muted, #6b7280)" }}>Loading…</div>;
  }

  const initial = (profile.company || "G").trim().charAt(0).toUpperCase();
  const userInitial = (profile.email || "?").trim().charAt(0).toUpperCase();

  let lastGroup = "";
  return (
    <div className="shell">
      {navOpen && <div className="nav-backdrop" onClick={() => setNavOpen(false)} />}
      <aside className={navOpen ? "nav-open" : ""}>
        <div className="sb-brand">
          <span className="logo"><svg viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth={2.4} strokeLinecap="round"><path d="M4 19V5M4 19h16M8 15l3-4 3 2 4-6"/></svg></span>
          Ganak
          <button className="nav-close" onClick={() => setNavOpen(false)} aria-label="Close menu">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round"><path d="M18 6 6 18M6 6l12 12"/></svg>
          </button>
        </div>
        <div className="org"><span className="av">{initial}</span><span className="nm">{profile.company}<small>{profile.location || " "}</small></span></div>
        <nav className="side">
          {NAV.map((n) => {
            const head = n.group !== lastGroup ? ((lastGroup = n.group), n.group) : null;
            const active = path === n.href;
            return (
              <div key={n.href}>
                {head && <span className="nav-lbl">{head}</span>}
                <button className={"navi" + (active ? " active" : "")} onClick={() => router.push(n.href)}>
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round">{n.icon}</svg>
                  {n.label}
                </button>
              </div>
            );
          })}
        </nav>
        <div className="spacer" />
        <div className="sb-user">
          <span className="av">{userInitial}</span>
          <span className="nm">{profile.email}<small>{profile.role || "owner"}</small></span>
          <button className="icon-btn" onClick={logout} aria-label="Log out" title="Log out" style={{ marginLeft: "auto" }}>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round"><path d="M15 12H4M11 8l-4 4 4 4M17 4h2a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-2"/></svg>
          </button>
        </div>
      </aside>
      <main>
        <div className="topbar">
          <button className="nav-burger" onClick={() => setNavOpen(true)} aria-label="Open menu">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round"><path d="M3 6h18M3 12h18M3 18h18"/></svg>
          </button>
          <h2>{TITLES[path] ?? LEGACY_TITLES[path] ?? "Ganak"}</h2>
          <div className="grow" />
          <span className="synced balance-chip">₹{(profile.balance_inr ?? 0).toFixed(2)}</span>
          <span className="synced company-chip">{profile.company} · connected</span>
          <button className="icon-btn" onClick={toggle} aria-label="Toggle theme">
            {theme === "dark" ? (
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>
            ) : (
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/></svg>
            )}
          </button>
        </div>
        {children}
        <nav className="bottom-tabs">
          {NAV.map((n) => (
            <button key={n.href} className={path === n.href ? "active" : ""} onClick={() => router.push(n.href)} aria-label={n.label}>
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round">{n.icon}</svg>
              {SHORT_LABEL[n.href] ?? n.label}
            </button>
          ))}
        </nav>
      </main>
    </div>
  );
}

"use client";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

const NAV = [
  { href: "/", label: "Dashboard", group: "Workspace",
    icon: <><rect x="3" y="3" width="8" height="8" rx="1.5"/><rect x="13" y="3" width="8" height="5" rx="1.5"/><rect x="13" y="11" width="8" height="10" rx="1.5"/><rect x="3" y="14" width="8" height="7" rx="1.5"/></> },
  { href: "/ask", label: "Ask Ganak", group: "Workspace",
    icon: <path d="M21 11.5a8.5 8.5 0 0 1-12 7.7L3 21l1.8-5.9A8.5 8.5 0 1 1 21 11.5z"/> },
  { href: "/connections", label: "Connections", group: "Workspace",
    icon: <path d="M9 12h6M15.5 8.5 18 6a3.5 3.5 0 1 1 0 5l-2 2M8.5 15.5 6 18a3.5 3.5 0 1 1 0-5l2-2"/> },
  { href: "/billing", label: "Usage & Billing", group: "Account",
    icon: <><rect x="2.5" y="5" width="19" height="14" rx="2.5"/><path d="M2.5 10h19"/></> },
];
const TITLES: Record<string, string> = {
  "/": "Dashboard", "/ask": "Ask Ganak", "/connections": "Connections", "/billing": "Usage & Billing",
};

export default function Shell({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const router = useRouter();
  const [theme, setTheme] = useState<"light" | "dark">("light");

  useEffect(() => {
    const saved = (typeof localStorage !== "undefined" && localStorage.getItem("ganak-theme")) as
      | "light" | "dark" | null;
    if (saved) { setTheme(saved); document.documentElement.setAttribute("data-theme", saved); }
  }, []);

  function toggle() {
    const next = theme === "dark" ? "light" : "dark";
    setTheme(next);
    document.documentElement.setAttribute("data-theme", next);
    try { localStorage.setItem("ganak-theme", next); } catch {}
  }

  let lastGroup = "";
  return (
    <div className="shell">
      <aside>
        <div className="sb-brand">
          <span className="logo"><svg viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth={2.4} strokeLinecap="round"><path d="M4 19V5M4 19h16M8 15l3-4 3 2 4-6"/></svg></span>
          Ganak
        </div>
        <div className="org"><span className="av">B</span><span className="nm">The Balaji Industries<small>Kharadi, Pune</small></span></div>
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
        <div className="sb-user"><span className="av">K</span><span className="nm">Kiran<small>Owner</small></span></div>
      </aside>
      <main>
        <div className="topbar">
          <h2>{TITLES[path] ?? "Ganak"}</h2>
          <div className="grow" />
          <span className="synced">warehouse connected</span>
          <button className="icon-btn" onClick={toggle} aria-label="Toggle theme">
            {theme === "dark" ? (
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>
            ) : (
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/></svg>
            )}
          </button>
        </div>
        {children}
      </main>
    </div>
  );
}

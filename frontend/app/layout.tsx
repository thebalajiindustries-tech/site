import "./globals.css";
import type { Metadata } from "next";
import Shell from "../components/Shell";

export const metadata: Metadata = {
  title: "Ganak — VidmahiTech",
  description: "Ask your business finances in plain language.",
};

// Baked in at build time (see frontend/Dockerfile / render.yaml buildArgs).
// Unset/"production" on the real site; the staging Render services build
// with NEXT_PUBLIC_APP_ENV=staging so nobody mistakes test data for real
// data -- same idea as GANAK_SCHEMA_PREFIX on the backend.
const APP_ENV = process.env.NEXT_PUBLIC_APP_ENV || "production";

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        {APP_ENV !== "production" && (
          <div
            style={{
              position: "sticky", top: 0, zIndex: 1000, textAlign: "center",
              padding: "5px 8px", fontSize: ".78rem", fontWeight: 600,
              letterSpacing: ".03em", textTransform: "uppercase",
              background: "#e0a800", color: "#1a1300",
            }}
          >
            {APP_ENV} — test environment, not your real data
          </div>
        )}
        <Shell>{children}</Shell>
      </body>
    </html>
  );
}

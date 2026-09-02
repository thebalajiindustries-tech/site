import "./globals.css";
import type { Metadata } from "next";
import Shell from "../components/Shell";

export const metadata: Metadata = {
  title: "Ganak — VidmahiTech",
  description: "Ask your business finances in plain language.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <Shell>{children}</Shell>
      </body>
    </html>
  );
}

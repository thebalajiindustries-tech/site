"use client";
// Billing now lives under Settings (with a new Profile tab alongside it).
import { useEffect } from "react";
import { useRouter } from "next/navigation";

export default function BillingRedirect() {
  const router = useRouter();
  useEffect(() => { router.replace("/settings?tab=billing"); }, [router]);
  return <div className="view"><p className="muted">Redirecting to Settings…</p></div>;
}

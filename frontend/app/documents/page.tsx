"use client";
// Documents now lives under Sources (merged with Connections) as a tab.
import { useEffect } from "react";
import { useRouter } from "next/navigation";

export default function DocumentsRedirect() {
  const router = useRouter();
  useEffect(() => { router.replace("/sources?tab=documents"); }, [router]);
  return <div className="view"><p className="muted">Redirecting to Sources…</p></div>;
}

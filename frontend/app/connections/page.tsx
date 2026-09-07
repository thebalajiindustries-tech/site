"use client";
// Connections now lives under Sources (merged with Documents). This stub
// keeps old bookmarks/links working, including the OAuth callback's query
// params, by forwarding straight through.
import { Suspense, useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";

function RedirectInner() {
  const router = useRouter();
  const params = useSearchParams();
  useEffect(() => {
    const qs = params.toString();
    router.replace(`/sources?tab=connections${qs ? "&" + qs : ""}`);
  }, [params, router]);
  return <div className="view"><p className="muted">Redirecting to Sources…</p></div>;
}

export default function ConnectionsRedirect() {
  return (
    <Suspense fallback={<div className="view"><p className="muted">Redirecting to Sources…</p></div>}>
      <RedirectInner />
    </Suspense>
  );
}

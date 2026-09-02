export type ChartSpec = { type: "bar" | "line" | "none"; x?: string | null; y?: string | null };
export type AskResponse = {
  answer: string;
  sql: string;
  columns: string[];
  rows: Record<string, unknown>[];
  chart: ChartSpec;
};

const BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export async function ask(question: string): Promise<AskResponse> {
  const res = await fetch(`${BASE}/ask`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question }),
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error((detail as { detail?: string }).detail || `Request failed (${res.status})`);
  }
  return res.json();
}

export async function health(): Promise<{ ok: boolean; database: string }> {
  const res = await fetch(`${BASE}/health`);
  return res.json();
}

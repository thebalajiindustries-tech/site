export type ChartSpec = { type: "bar" | "line" | "none"; x?: string | null; y?: string | null };
export type AskResponse = {
  answer: string;
  sql: string;
  columns: string[];
  rows: Record<string, unknown>[];
  chart: ChartSpec;
};
export type Me = { email: string; company: string; location: string; role: string; dialect: string; balance_inr: number };
export type AuthResult = { token: string; email: string; company: string; location: string; dialect: string };

const BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const TOKEN_KEY = "ganak-token";

export function getToken(): string | null {
  try { return localStorage.getItem(TOKEN_KEY); } catch { return null; }
}
function setToken(t: string) { try { localStorage.setItem(TOKEN_KEY, t); } catch {} }
function clearKpiCache() {
  try {
    for (let i = localStorage.length - 1; i >= 0; i--) {
      const k = localStorage.key(i);
      if (k && k.startsWith("ganak-kpi:")) localStorage.removeItem(k);
    }
  } catch {}
}

export function logout() {
  try { localStorage.removeItem(TOKEN_KEY); } catch {}
  clearKpiCache();
  if (typeof window !== "undefined") window.location.href = "/login";
}

function authHeaders(): Record<string, string> {
  const t = getToken();
  return t ? { Authorization: `Bearer ${t}` } : {};
}

// For authenticated calls: a 401 means the session is gone -> bounce to login.
async function handle<T>(res: Response): Promise<T> {
  if (res.status === 401) {
    try { localStorage.removeItem(TOKEN_KEY); } catch {}
    if (typeof window !== "undefined" && window.location.pathname !== "/login") {
      window.location.href = "/login";
    }
    throw new Error("Your session has expired. Please log in again.");
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error((data as { detail?: string }).detail || `Request failed (${res.status})`);
  return data as T;
}

// For login/register: surface the message, never redirect.
async function parse<T>(res: Response): Promise<T> {
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error((data as { detail?: string }).detail || `Request failed (${res.status})`);
  return data as T;
}

export async function login(email: string, password: string): Promise<AuthResult> {
  const res = await fetch(`${BASE}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  const data = await parse<AuthResult>(res);
  setToken(data.token);
  clearKpiCache();
  return data;
}

export async function register(
  email: string, password: string, company: string, location: string
): Promise<AuthResult> {
  const res = await fetch(`${BASE}/auth/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password, company, location }),
  });
  const data = await parse<AuthResult>(res);
  setToken(data.token);
  return data;
}

export async function me(): Promise<Me> {
  const res = await fetch(`${BASE}/me`, { headers: { ...authHeaders() } });
  return handle<Me>(res);
}

export async function ask(question: string): Promise<AskResponse> {
  const res = await fetch(`${BASE}/ask`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ question }),
  });
  return handle<AskResponse>(res);
}

export async function health(): Promise<{ ok: boolean; database: string; company?: string }> {
  const res = await fetch(`${BASE}/health`, { headers: { ...authHeaders() } });
  return handle(res);
}

export type DocFields = {
  doc_type?: string; party?: string; doc_date?: string; amount?: number | null;
  currency?: string; reference_no?: string; gst_no?: string; direction?: string;
  summary?: string; source_filename?: string; raw?: Record<string, unknown>;
};

export async function extractDocument(filename: string, dataB64: string): Promise<DocFields> {
  const res = await fetch(`${BASE}/documents/extract`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ filename, data_b64: dataB64 }),
  });
  return handle<DocFields>(res);
}

export async function loadDocument(rec: DocFields): Promise<{ ok: boolean; message: string }> {
  const res = await fetch(`${BASE}/documents/load`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify(rec),
  });
  return handle(res);
}

export type LedgerRow = { ts: number; kind: string; amount_inr: number; balance_after: number; detail: string };
export type Billing = { balance_inr: number; currency: string; ledger: LedgerRow[] };

export async function getBilling(): Promise<Billing> {
  const res = await fetch(`${BASE}/billing`, { headers: { ...authHeaders() } });
  return handle<Billing>(res);
}

export async function recharge(amountInr: number): Promise<{ ok: boolean; balance_inr: number }> {
  const res = await fetch(`${BASE}/billing/recharge`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ amount_inr: amountInr }),
  });
  return handle(res);
}

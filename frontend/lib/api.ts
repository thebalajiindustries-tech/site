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

export async function ask(question: string, mode: "warehouse" | "live" = "warehouse"): Promise<AskResponse> {
  const res = await fetch(`${BASE}/ask`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ question, mode }),
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

// ---------------- self-serve connectors (Gmail, Zoho, ...) ----------------
export type ConnectorInfo = {
  provider: string;
  connected: boolean;
  configured: boolean;
  status: string;
  account_label: string;
  last_synced_at: number;
  last_error: string;
};

export async function listConnectors(): Promise<ConnectorInfo[]> {
  const res = await fetch(`${BASE}/connectors`, { headers: { ...authHeaders() } });
  return handle<ConnectorInfo[]>(res);
}

export async function startConnector(provider: string): Promise<{ authorize_url: string }> {
  const res = await fetch(`${BASE}/connectors/${provider}/start`, { headers: { ...authHeaders() } });
  return handle(res);
}

export async function syncConnectorNow(provider: string): Promise<{ status: string }> {
  const res = await fetch(`${BASE}/connectors/${provider}/sync`, {
    method: "POST", headers: { ...authHeaders() },
  });
  return handle(res);
}

export async function disconnectConnector(provider: string): Promise<{ status: string }> {
  const res = await fetch(`${BASE}/connectors/${provider}/disconnect`, {
    method: "POST", headers: { ...authHeaders() },
  });
  return handle(res);
}

// A Zoho account can hold more than one organization. When it does, the
// OAuth callback doesn't guess -- it redirects back here with a ticket
// instead of connecting right away; these two calls let the picker in
// sources/page.tsx show the choices and finalize the one the user picks.
export type ZohoOrg = { organization_id: string; name: string };

export async function getPendingZohoOrgs(ticket: string): Promise<{ organizations: ZohoOrg[] }> {
  const res = await fetch(`${BASE}/connectors/zoho/pending-orgs?ticket=${encodeURIComponent(ticket)}`);
  return handle(res);
}

export async function selectZohoOrg(ticket: string, organizationId: string): Promise<{ status: string }> {
  const res = await fetch(`${BASE}/connectors/zoho/select-org`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ ticket, organization_id: organizationId }),
  });
  return handle(res);
}

// ---------------- scheduled email digests ----------------
export type DigestLogEntry = { ts: number; status: string; detail: string; recipients: string };
export type DigestSettings = {
  configured: boolean;
  enabled: boolean;
  frequency: "daily" | "weekly";
  weekday: number;
  hour: number;
  recipients: string[];
  last_sent_at: number;
  log: DigestLogEntry[];
};

export async function getDigest(): Promise<DigestSettings> {
  const res = await fetch(`${BASE}/digest`, { headers: { ...authHeaders() } });
  return handle<DigestSettings>(res);
}

export async function saveDigest(settings: {
  enabled: boolean; frequency: "daily" | "weekly"; weekday: number; hour: number; recipients: string[];
}): Promise<DigestSettings> {
  const res = await fetch(`${BASE}/digest`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify(settings),
  });
  return handle<DigestSettings>(res);
}

export async function sendDigestNow(): Promise<{ status: string }> {
  const res = await fetch(`${BASE}/digest/send-now`, { method: "POST", headers: { ...authHeaders() } });
  return handle(res);
}

// ---------------- admin console (owner-only) ----------------
export type AdminConnector = {
  provider: string; status: string; account_label: string;
  last_synced_at: number; last_error: string;
};
export type AdminUserRow = { email: string; role: string; created_at: number };
export type AdminTenant = {
  id: number; name: string; location: string; balance_inr: number; created_at: number;
  users: AdminUserRow[]; total_spent_inr: number; total_recharged_inr: number;
  connectors: AdminConnector[];
};
export type AdminOverview = {
  admin_email: string;
  totals: {
    tenant_count: number; user_count: number; total_balance_inr: number;
    total_spent_inr: number; total_recharged_inr: number;
  };
  tenants: AdminTenant[];
};

export async function adminOverview(): Promise<AdminOverview> {
  const res = await fetch(`${BASE}/admin/overview`, { headers: { ...authHeaders() } });
  return handle<AdminOverview>(res);
}

// ---------------- Inbox -> Books (find finance emails missing from Zoho, add after review) ----------------
export type InboxRecordType =
  "bill" | "customer_payment" | "estimate" | "purchase_order" | "sales_order" | "expense";

export type InboxMissingItem = {
  message_id: string; email_date: string; sender: string; subject: string; snippet: string;
  category: string; direction: string; suggested_type: InboxRecordType; amount: number | null;
  checked: boolean; note: string;
};
export type InboxMissing = {
  gmail_synced: boolean; zoho_synced: boolean; write_enabled: boolean;
  items: InboxMissingItem[]; counts: Record<string, number>;
};
export type InboxLineItem = { description: string; quantity: number; rate: number };
export type InboxFields = {
  party_name: string; document_number: string; date: string; due_date: string; currency: string;
  total: number | null; line_items: InboxLineItem[]; reference_number: string;
  related_invoice_number: string; payment_mode: string; gst_no: string; notes: string;
  // chosen in the review form (not read from the email):
  account_id?: string; paid_through_account_id?: string; deposit_account_id?: string; invoice_id?: string;
  contact_id?: string;
};
export type InboxInvoiceCandidate = {
  invoice_id: string; invoice_number: string; customer_name: string; balance: number | null;
  total: number | null; date: string; best: boolean;
};
export type InboxExtract = {
  record_type: InboxRecordType; fields: InboxFields;
  party_match: { contact_id: string; contact_name: string } | null;
  invoice_candidates: InboxInvoiceCandidate[];
  email: { subject: string; sender: string; date: string; has_pdf: boolean };
  warnings: string[];
};
export type InboxAccount = { account_id: string; account_name: string; account_type: string };
export type InboxAccounts = { expense_accounts: InboxAccount[]; bank_accounts: InboxAccount[] };

export async function inboxStatus(): Promise<{ gmail_connected: boolean; zoho_connected: boolean; write_enabled: boolean }> {
  const res = await fetch(`${BASE}/inbox-books/status`, { headers: { ...authHeaders() } });
  return handle(res);
}

export async function inboxMissing(days = 30): Promise<InboxMissing> {
  const res = await fetch(`${BASE}/inbox-books/missing?days=${days}`, { headers: { ...authHeaders() } });
  return handle<InboxMissing>(res);
}

export async function inboxExtract(messageId: string, recordType: InboxRecordType): Promise<InboxExtract> {
  const res = await fetch(`${BASE}/inbox-books/extract`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ message_id: messageId, record_type: recordType }),
  });
  return handle<InboxExtract>(res);
}

export async function inboxAccounts(): Promise<InboxAccounts> {
  const res = await fetch(`${BASE}/inbox-books/accounts`, { headers: { ...authHeaders() } });
  return handle<InboxAccounts>(res);
}

export async function inboxCreate(
  messageId: string, recordType: InboxRecordType, fields: InboxFields, allowDuplicate = false
): Promise<{ ok: boolean; zoho_id: string; zoho_number: string; message: string }> {
  const res = await fetch(`${BASE}/inbox-books/create`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ message_id: messageId, record_type: recordType, fields, allow_duplicate: allowDuplicate }),
  });
  return handle(res);
}

export async function inboxDismiss(messageId: string): Promise<{ ok: boolean }> {
  const res = await fetch(`${BASE}/inbox-books/dismiss`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ message_id: messageId }),
  });
  return handle(res);
}

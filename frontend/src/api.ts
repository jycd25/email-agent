import type { Alert, AnalyzeResult, AppStatus, EmailDetail, EmailRow, Profile, Rule, Settings, Status } from "./types";

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(path, { headers: { "Content-Type": "application/json" }, ...init });
  if (!r.ok) {
    let msg = r.statusText;
    try {
      const j = await r.json();
      msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail ?? j);
    } catch {
      /* body not json */
    }
    throw new Error(msg);
  }
  return r.json() as Promise<T>;
}
const post = <T,>(p: string, body?: unknown) => req<T>(p, { method: "POST", body: body ? JSON.stringify(body) : undefined });

export const api = {
  status: () => req<AppStatus>("/api/status"),
  fetchNow: () => post<{ fetched: number; processed: number }>("/api/fetch"),
  emails: (p: { status?: Status; q?: string; limit?: number } = {}) => {
    const qs = new URLSearchParams();
    if (p.status) qs.set("status", p.status);
    if (p.q) qs.set("q", p.q);
    qs.set("limit", String(p.limit ?? 100));
    return req<EmailRow[]>(`/api/emails?${qs}`);
  },
  email: (id: number) => req<EmailDetail>(`/api/emails/${id}`),
  retry: (id: number) => post<{ ok: boolean }>(`/api/emails/${id}/retry`),
  analyze: (prompt: string) => post<AnalyzeResult>("/api/analyze", { prompt }),
  instruction: (text: string) => post<{ applied: Record<string, unknown>; settings: Settings }>("/api/instruction", { text }),
  alerts: (unread = false) => req<Alert[]>(`/api/alerts?limit=200&unread=${unread}`),
  alertRead: (id: number) => post<{ ok: boolean }>(`/api/alerts/${id}/read`),
  alertsReadAll: () => post<{ updated: number }>("/api/alerts/read-all"),
  settings: () => req<Settings>("/api/settings"),
  saveSettings: (patch: Partial<Settings>) => req<Settings>("/api/settings", { method: "PUT", body: JSON.stringify(patch) }),
  profiles: () => req<Record<Profile, string[]>>("/api/profiles"),
  rules: () => req<Rule[]>("/api/sender-rules"),
  addRule: (r: { pattern: string; category: string; notes?: string }) => post<Rule>("/api/sender-rules", r),
  deleteRule: (pattern: string) => req<{ ok: boolean }>(`/api/sender-rules/${encodeURIComponent(pattern)}`, { method: "DELETE" }),
};

export type LiveEvent =
  | { type: "email"; id: number; status: Status }
  | { type: "alert"; alert: Alert }
  | { type: "settings"; settings: Settings };

/** Subscribe to server-sent events. Returns an unsubscribe function. */
export function subscribe(onEvent: (e: LiveEvent) => void, onState?: (open: boolean) => void): () => void {
  const es = new EventSource("/api/events");
  const handler = (ev: MessageEvent) => onEvent(JSON.parse(ev.data) as LiveEvent);
  for (const t of ["email", "alert", "settings"]) es.addEventListener(t, handler as EventListener);
  es.onopen = () => onState?.(true);
  es.onerror = () => onState?.(false);
  return () => es.close();
}

export function timeAgo(iso: string | null): string {
  if (!iso) return "never";
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return `${Math.round(s)}s ago`;
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  if (s < 86400) return `${Math.round(s / 3600)}h ago`;
  return `${Math.round(s / 86400)}d ago`;
}

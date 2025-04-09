import type { ReactNode } from "react";
import type { Analyses, Status } from "../types";

/** Which colour the severity rail shows for an email. */
export function railLevel(status: Status, a: Analyses | undefined): string {
  if (status === "queued" || status === "processing") return "pending";
  if (a?.sender?.is_blocked) return "urgent";
  return a?.urgency?.urgency_level ?? "none";
}

export function Tag({ children, cls = "" }: { children: ReactNode; cls?: string }) {
  return <span className={`tag ${cls}`}>{children}</span>;
}

export function pct(x: number | undefined): string {
  return x == null ? "–" : `${Math.round(x * 100)}%`;
}

export function fmtDate(iso: string): string {
  const d = new Date(iso);
  return isNaN(d.getTime()) ? iso : d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

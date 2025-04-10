import { useEffect, useState } from "react";
import { api } from "../api";
import type { Alert } from "../types";
import { fmtDate } from "./Rail";

export default function Alerts({ tick, onChanged }: { tick: number; onChanged: () => void }) {
  const [rows, setRows] = useState<Alert[]>([]);
  const [unreadOnly, setUnreadOnly] = useState(true);

  useEffect(() => { api.alerts(unreadOnly).then(setRows).catch(() => {}); }, [tick, unreadOnly]);

  const markRead = async (id: number) => {
    await api.alertRead(id);
    setRows((r) => r.map((a) => (a.id === id ? { ...a, read: true } : a)));
    onChanged();
  };
  const readAll = async () => { await api.alertsReadAll(); setRows((r) => r.map((a) => ({ ...a, read: true }))); onChanged(); };

  return (
    <div className="feed">
      <div className="row" style={{ justifyContent: "space-between", marginBottom: 12 }}>
        <h1>Alerts</h1>
        <div className="row">
          <label className="check"><input type="checkbox" checked={unreadOnly} onChange={(e) => setUnreadOnly(e.target.checked)} /> Unread only</label>
          <button className="btn small" onClick={readAll}>Mark all read</button>
        </div>
      </div>
      {rows.length === 0 && <div className="empty"><h2>No alerts</h2>Alerts appear when an email crosses your urgency or watchlist thresholds, or a blocked or VIP sender writes.</div>}
      {rows.map((a) => (
        <div key={a.id} className={`item rail ${a.read ? "read" : ""}`} data-level={a.level === "critical" ? "urgent" : a.level}>
          <div className="msg">{a.message}</div>
          <div className="when">{fmtDate(a.created_at)}</div>
          <div className="from">
            {a.type}{a.details.subject ? ` · ${String(a.details.subject)}` : ""}{a.details.from_addr ? ` · ${String(a.details.from_addr)}` : ""}
            {a.details.deadline ? ` · due ${String(a.details.deadline)}` : ""}
          </div>
          <div className="tags">
            {a.email_id != null && <a className="tag" href="#inbox">open email</a>}
            {!a.read && <button className="btn small" onClick={() => markRead(a.id)}>Mark read</button>}
          </div>
        </div>
      ))}
    </div>
  );
}

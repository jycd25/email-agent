import { useEffect, useState } from "react";
import { api } from "../api";
import type { EmailRow, Status } from "../types";
import EmailDetail from "./EmailDetail";
import { Tag, fmtDate, railLevel } from "./Rail";

const FILTERS: { key: Status | ""; label: string }[] = [
  { key: "", label: "All" },
  { key: "queued", label: "Queued" },
  { key: "done", label: "Analyzed" },
  { key: "failed", label: "Failed" },
];

export default function Inbox({ tick }: { tick: number }) {
  const [rows, setRows] = useState<EmailRow[]>([]);
  const [filter, setFilter] = useState<Status | "">("");
  const [q, setQ] = useState("");
  const [selected, setSelected] = useState<number | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    api.emails({ status: filter || undefined, q: q || undefined })
      .then((r) => { setRows(r); setErr(null); })
      .catch((e) => setErr(e.message));
  }, [tick, filter, q]);

  return (
    <div className="inbox">
      <section className="list" data-has-selection={selected != null} aria-label="Emails">
        <div className="toolbar">
          <select className="input" value={filter} onChange={(e) => setFilter(e.target.value as Status | "")} aria-label="Filter by status">
            {FILTERS.map((f) => <option key={f.key} value={f.key}>{f.label}</option>)}
          </select>
          <input className="input" placeholder="Search subject or sender" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
        {err && <div className="notice bad" style={{ margin: 12 }}>{err}</div>}
        {rows.length === 0 && !err && (
          <div className="empty">
            <h2>Nothing here yet</h2>
            The agent checks your Gmail and Outlook accounts on its own. Use <b>Check now</b> to pull immediately, or try the <b>Analyze</b> tab with a pasted email.
          </div>
        )}
        {rows.map((r) => {
          const a = r.analyses;
          return (
            <div
              key={r.id}
              role="button"
              tabIndex={0}
              className={`item rail`}
              data-level={railLevel(r.status, a)}
              aria-selected={selected === r.id}
              onClick={() => setSelected(r.id)}
              onKeyDown={(e) => e.key === "Enter" && setSelected(r.id)}
            >
              <div className="subject">{r.subject || "(no subject)"}</div>
              <div className="when" title={r.received_at}>{fmtDate(r.received_at)}</div>
              <div className="from">{r.from_addr}</div>
              <div className="tags">
                {r.status !== "done" && <Tag cls={`status-${r.status}`}>{r.status}</Tag>}
                {a?.urgency && <Tag cls={`level-${a.urgency.urgency_level}`}>{a.urgency.urgency_level}</Tag>}
                {a?.topic?.is_watchlist_topic && <Tag cls="topic">{a.topic.primary_topic}</Tag>}
                {a?.sender?.is_blocked && <Tag cls="blocked">blocked sender</Tag>}
                {a?.sender && !a.sender.is_blocked && a.sender.category !== "unknown" && <Tag>{a.sender.category}</Tag>}
                {a?.classification && <Tag>{a.classification.category} · {a.classification.priority}</Tag>}
              </div>
            </div>
          );
        })}
      </section>
      <section className="detail" aria-label="Email detail">
        {selected == null ? (
          <div className="empty"><h2>Select an email</h2>Analysis and the original text show here.</div>
        ) : (
          <EmailDetail id={selected} tick={tick} onBack={() => setSelected(null)} />
        )}
      </section>
    </div>
  );
}

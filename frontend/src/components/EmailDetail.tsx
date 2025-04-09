import { useEffect, useState } from "react";
import { api } from "../api";
import type { Classification, EmailDetail as Detail, Sender, Topic, Urgency } from "../types";
import { fmtDate, pct } from "./Rail";

export default function EmailDetail({ id, tick, onBack }: { id: number; tick: number; onBack: () => void }) {
  const [d, setD] = useState<Detail | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    api.email(id).then((x) => { setD(x); setErr(null); }).catch((e) => setErr(e.message));
  }, [id, tick]);

  if (err) return <div className="notice bad">{err}</div>;
  if (!d) return <div className="muted">Loading…</div>;

  const latest = <T,>(kind: string): T | undefined =>
    [...d.analyses].reverse().find((a) => a.kind === kind)?.result as T | undefined;
  const u = latest<Urgency>("urgency");
  const t = latest<Topic>("topic");
  const s = latest<Sender>("sender");
  const c = latest<Classification>("classification");
  const level = s?.is_blocked ? "urgent" : u?.urgency_level ?? (d.status === "done" ? "none" : "pending");

  return (
    <>
      <header className="rail" data-level={level}>
        <div className="row" style={{ justifyContent: "space-between" }}>
          <span className="eyebrow">{d.source} · {d.status}{d.attempts > 1 ? ` · attempt ${d.attempts}` : ""}</span>
          <button className="btn small" onClick={onBack}>Back</button>
        </div>
        <h1>{d.subject || "(no subject)"}</h1>
        <div className="meta">
          <span>{d.from_addr}</span>
          <span>{fmtDate(d.received_at)}</span>
        </div>
        {d.status === "failed" && (
          <div className="notice bad" style={{ marginTop: 10 }}>
            Analysis failed: {d.error}{" "}
            <button className="btn small" onClick={() => api.retry(d.id)}>Retry</button>
          </div>
        )}
      </header>

      <div className="cards">
        {u && (
          <div className="card">
            <div className="head"><h3>Urgency</h3><span className="mono muted">confidence {pct(u.confidence_score)}{u.detailed ? "" : " · quick check"}</span></div>
            <div className={`big level-${u.urgency_level}`}>{u.urgency_level}</div>
            <p style={{ margin: "6px 0 0" }}>{u.summary}</p>
            <dl>
              {u.deadline && <><dt>Deadline</dt><dd>{u.deadline}</dd></>}
              {u.keywords_detected.length > 0 && <><dt>Signals</dt><dd>{u.keywords_detected.join(", ")}</dd></>}
            </dl>
          </div>
        )}
        {t && (
          <div className="card">
            <div className="head"><h3>Watchlist</h3><span className="mono muted">similarity {pct(t.similarity_score)} · confidence {pct(t.confidence_score)}</span></div>
            <div className="big">{t.is_watchlist_topic ? t.primary_topic : "No match"}</div>
            {t.message_summary && <p style={{ margin: "6px 0 0" }}>{t.message_summary}</p>}
          </div>
        )}
        {s && (
          <div className="card">
            <div className="head"><h3>Sender</h3><span className="mono muted">{s.analysis_method === "llm" ? `model · confidence ${pct(s.confidence_score)}` : s.rule_matched ? `rule ${s.rule_matched}` : "no rule"}</span></div>
            <div className={`big ${s.is_blocked ? "level-urgent" : ""}`}>{s.category}</div>
            {s.notes && <p style={{ margin: "6px 0 0" }}>{s.notes}</p>}
            {s.suggested_rule && s.analysis_method === "llm" && (
              <div className="row" style={{ marginTop: 8 }}>
                <span className="muted">Suggested rule:</span>
                <code className="mono">{s.suggested_rule}</code>
                <button className="btn small" onClick={() => api.addRule({ pattern: s.suggested_rule!, category: s.category, notes: "from suggestion" })}>
                  Add rule
                </button>
              </div>
            )}
          </div>
        )}
        {c && (
          <div className="card">
            <div className="head"><h3>Classification</h3><span className="mono muted">{c.category} · {c.priority}</span></div>
            {c.summary && <p style={{ margin: 0 }}>{c.summary}</p>}
            {c.action_list.length > 0 && <ul>{c.action_list.map((a, i) => <li key={i}>{a}</li>)}</ul>}
            {c.important_dates.length > 0 && <dl><dt>Dates</dt><dd>{c.important_dates.join(", ")}</dd></dl>}
          </div>
        )}
        <div className="card">
          <div className="head"><h3>Original</h3></div>
          <div className="bodytext">{d.body_text || "(empty)"}</div>
        </div>
      </div>
    </>
  );
}

import { useState } from "react";
import { api } from "../api";
import type { AnalyzeResult } from "../types";
import { pct } from "./Rail";

const SAMPLES = [
  "is this urgent: {Prod API error rate is at 12% and climbing. Customers are reporting failed checkouts. Need someone on this now.}",
  "is this urgent: {Reminder: Assignment 3 is now due Friday 5pm. No extensions will be granted.}",
  "what is this about: {The registrar has opened spring enrollment. Your window starts Tuesday 8am.}",
  "analyze sender noreply@campus-deals.example",
];

export default function Analyze() {
  const [prompt, setPrompt] = useState("");
  const [res, setRes] = useState<AnalyzeResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const run = async () => {
    setBusy(true); setErr(null);
    try { setRes(await api.analyze(prompt)); } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  };

  return (
    <div className="page">
      <div>
        <h1>Analyze one email</h1>
        <p className="muted" style={{ margin: "4px 0 0" }}>
          Say what you want to know, then paste the email in braces. Sender-only questions just need the address.
        </p>
      </div>
      <textarea className="input" value={prompt} onChange={(e) => setPrompt(e.target.value)} placeholder={SAMPLES[0]} />
      <div className="row wrap">
        <button className="btn primary" onClick={run} disabled={busy || !prompt.trim()}>{busy ? "Thinking…" : "Analyze"}</button>
        <span className="muted">Try:</span>
        <div className="samples">
          {SAMPLES.map((s, i) => <button key={i} className="btn small" onClick={() => setPrompt(s)}>{s.split(":")[0].replace("{", "").trim()} #{i + 1}</button>)}
        </div>
      </div>
      {err && <div className="notice bad">{err}</div>}
      {res && (
        <div className="cards result">
          <div className="eyebrow">routed to {res.tool}</div>
          {res.error && <div className="notice bad">{res.error}</div>}
          {res.urgency && (
            <div className="card">
              <div className="head"><h3>Urgency</h3><span className="mono muted">confidence {pct(res.urgency.confidence_score)}</span></div>
              <div className={`big level-${res.urgency.urgency_level}`}>{res.urgency.urgency_level}</div>
              <p style={{ margin: "6px 0 0" }}>{res.urgency.summary}</p>
              {res.urgency.deadline && <dl><dt>Deadline</dt><dd>{res.urgency.deadline}</dd></dl>}
            </div>
          )}
          {res.topic && (
            <div className="card">
              <div className="head"><h3>Watchlist</h3><span className="mono muted">similarity {pct(res.topic.similarity_score)}</span></div>
              <div className="big">{res.topic.is_watchlist_topic ? res.topic.primary_topic : "No match"}</div>
              {res.topic.message_summary && <p style={{ margin: "6px 0 0" }}>{res.topic.message_summary}</p>}
            </div>
          )}
          {res.sender && (
            <div className="card">
              <div className="head"><h3>Sender</h3><span className="mono muted">{res.sender.analysis_method}</span></div>
              <div className="big">{res.sender.category}</div>
              {res.sender.notes && <p style={{ margin: "6px 0 0" }}>{res.sender.notes}</p>}
            </div>
          )}
          {res.classification && (
            <div className="card">
              <div className="head"><h3>Classification</h3></div>
              <div className="big">{res.classification.category} · {res.classification.priority}</div>
              {res.classification.action_list.length > 0 && <ul>{res.classification.action_list.map((a, i) => <li key={i}>{a}</li>)}</ul>}
            </div>
          )}
          <details><summary className="muted">Raw result</summary><pre>{JSON.stringify(res, null, 2)}</pre></details>
        </div>
      )}
    </div>
  );
}

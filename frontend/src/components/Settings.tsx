import { useEffect, useState } from "react";
import { api } from "../api";
import type { Profile, Rule, Settings } from "../types";

const PROFILES: { key: Profile; name: string; blurb: string }[] = [
  { key: "general", name: "General", blurb: "Deadlines, replies owed, money and legal matters." },
  { key: "student", name: "Student", blurb: "Assignments, exams, professors, registration, financial aid." },
  { key: "oncall", name: "On-call engineer", blurb: "Incidents, pages, failed deploys, security advisories." },
];
const CATEGORIES = ["trusted", "blocked", "vip", "work", "personal", "newsletter", "marketing", "social", "unknown"];

export default function SettingsPage({ settings, onSaved }: { settings: Settings; onSaved: (s: Settings) => void }) {
  const [s, setS] = useState<Settings>(settings);
  const [presets, setPresets] = useState<Record<Profile, string[]> | null>(null);
  const [rules, setRules] = useState<Rule[]>([]);
  const [newTopic, setNewTopic] = useState("");
  const [rule, setRule] = useState({ pattern: "", category: "vip", notes: "" });
  const [instr, setInstr] = useState("");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const dirty = JSON.stringify(s) !== JSON.stringify(settings);

  useEffect(() => setS(settings), [settings]);
  useEffect(() => { api.profiles().then(setPresets).catch(() => {}); loadRules(); }, []);
  const loadRules = () => api.rules().then(setRules).catch(() => {});
  const set = <K extends keyof Settings>(k: K, v: Settings[K]) => setS((x) => ({ ...x, [k]: v }));

  const pickProfile = (p: Profile) => {
    setS((x) => ({ ...x, profile: p, watchlist_topics: presets?.[p] ?? x.watchlist_topics }));
  };
  const save = async () => {
    try { onSaved(await api.saveSettings(s)); setMsg({ ok: true, text: "Saved" }); }
    catch (e) { setMsg({ ok: false, text: (e as Error).message }); }
  };
  const applyInstruction = async () => {
    try {
      const r = await api.instruction(instr);
      onSaved(r.settings); loadRules(); setInstr("");
      setMsg({ ok: true, text: `Applied: ${Object.keys(r.applied).filter((k) => !k.startsWith("_")).join(", ")}` });
    } catch (e) { setMsg({ ok: false, text: (e as Error).message }); }
  };
  const addRule = async () => {
    if (!rule.pattern.trim()) return;
    await api.addRule({ pattern: rule.pattern, category: rule.category, notes: rule.notes || undefined });
    setRule({ pattern: "", category: "vip", notes: "" }); loadRules();
  };

  return (
    <div className="settings">
      <h1>Settings</h1>
      {msg && <div className={`notice ${msg.ok ? "" : "bad"}`}>{msg.text}</div>}

      <section className="section">
        <h2>Who this inbox belongs to</h2>
        <p className="muted" style={{ margin: 0 }}>Sets the context the model reads before every email and fills in a starter watchlist.</p>
        <div className="profiles">
          {PROFILES.map((p) => (
            <button key={p.key} className="profile" aria-pressed={s.profile === p.key} onClick={() => pickProfile(p.key)}>
              <b>{p.name}</b><span>{p.blurb}</span>
            </button>
          ))}
        </div>
      </section>

      <section className="section">
        <h2>Quick instruction</h2>
        <div className="row">
          <input className="input" value={instr} onChange={(e) => setInstr(e.target.value)} placeholder="monitor urgency, starting today 9am" onKeyDown={(e) => e.key === "Enter" && applyInstruction()} />
          <button className="btn" onClick={applyInstruction} disabled={!instr.trim()}>Apply</button>
        </div>
        <span className="muted">Examples: <i>monitor topic Security Incident, starting now</i> · <i>track sender prof@uni.edu, from yesterday</i></span>
      </section>

      <section className="section">
        <h2>Watchlist topics</h2>
        <div className="chips">
          {s.watchlist_topics.map((t) => (
            <span key={t} className="chip">{t}<button aria-label={`Remove ${t}`} onClick={() => set("watchlist_topics", s.watchlist_topics.filter((x) => x !== t))}>×</button></span>
          ))}
        </div>
        <div className="row">
          <input className="input" value={newTopic} onChange={(e) => setNewTopic(e.target.value)} placeholder="Add a topic" onKeyDown={(e) => { if (e.key === "Enter" && newTopic.trim()) { set("watchlist_topics", [...s.watchlist_topics, newTopic.trim()]); setNewTopic(""); } }} />
          <button className="btn" onClick={() => { if (newTopic.trim()) { set("watchlist_topics", [...s.watchlist_topics, newTopic.trim()]); setNewTopic(""); } }}>Add</button>
        </div>
      </section>

      <section className="section">
        <h2>What to check</h2>
        <div className="grid2">
          <label className="check"><input type="checkbox" checked={s.analyze_urgency} onChange={(e) => set("analyze_urgency", e.target.checked)} /> Urgency</label>
          <label className="check"><input type="checkbox" checked={s.analyze_topics} onChange={(e) => set("analyze_topics", e.target.checked)} /> Watchlist topics</label>
          <label className="check"><input type="checkbox" checked={s.analyze_sender} onChange={(e) => set("analyze_sender", e.target.checked)} /> Sender</label>
          <label className="check"><input type="checkbox" checked={s.classify} onChange={(e) => set("classify", e.target.checked)} /> Full classification (extra model call)</label>
        </div>
        <div className="grid2">
          <label className="field"><span>Alert when urgency is at least</span>
            <select className="input" value={s.urgency_threshold} onChange={(e) => set("urgency_threshold", e.target.value as Settings["urgency_threshold"])}>
              {["low", "medium", "high", "urgent"].map((l) => <option key={l}>{l}</option>)}
            </select></label>
          <label className="field"><span>Topic similarity threshold ({s.topic_threshold})</span>
            <input type="range" min={0.2} max={0.95} step={0.05} value={s.topic_threshold} onChange={(e) => set("topic_threshold", Number(e.target.value))} /></label>
          <label className="field"><span>Minimum confidence to alert ({s.min_confidence})</span>
            <input type="range" min={0.3} max={0.95} step={0.05} value={s.min_confidence} onChange={(e) => set("min_confidence", Number(e.target.value))} /></label>
          <label className="field"><span>Sender analysis</span>
            <select className="input" value={s.sender_mode} onChange={(e) => set("sender_mode", e.target.value as Settings["sender_mode"])}>
              <option value="auto">Rules first, then model</option><option value="rule">Rules only</option><option value="llm">Model only</option>
            </select></label>
          <label className="check"><input type="checkbox" checked={s.alert_on_unknown_sender} onChange={(e) => set("alert_on_unknown_sender", e.target.checked)} /> Alert on unknown senders</label>
        </div>
      </section>

      <section className="section">
        <h2>Notifications and history</h2>
        <div className="grid2">
          <label className="check"><input type="checkbox" checked={s.desktop_notifications} onChange={(e) => set("desktop_notifications", e.target.checked)} /> Desktop notification for alerts</label>
          <label className="field"><span>Notify when alert level is at least</span>
            <select className="input" value={s.notify_min_level} onChange={(e) => set("notify_min_level", e.target.value as Settings["notify_min_level"])}>
              {["low", "medium", "high", "critical"].map((l) => <option key={l}>{l}</option>)}
            </select></label>
        </div>
      </section>

      <section className="section">
        <h2>Model</h2>
        <div className="grid2">
          <label className="field"><span>Provider</span>
            <select className="input" value={s.provider} onChange={(e) => set("provider", e.target.value as Settings["provider"])}>
              <option value="ollama">Ollama (local)</option><option value="openai">OpenAI</option>
            </select></label>
          <label className="field"><span>Model</span><input className="input" value={s.model} onChange={(e) => set("model", e.target.value)} /></label>
          {s.provider === "ollama" && <label className="field"><span>Ollama URL</span><input className="input" value={s.base_url} onChange={(e) => set("base_url", e.target.value)} /></label>}
          {s.provider === "openai" && <span className="muted" style={{ alignSelf: "end" }}>Set <code>OPENAI_API_KEY</code> in the environment before starting.</span>}
        </div>
      </section>

      <section className="section">
        <h2>Checking mail</h2>
        <div className="grid2">
          <label className="field"><span>Check every (seconds)</span><input className="input" type="number" min={5} max={3600} value={s.poll_interval_seconds} onChange={(e) => set("poll_interval_seconds", Number(e.target.value))} /></label>
          <label className="field"><span>Emails per check</span><input className="input" type="number" min={1} max={100} value={s.batch_size} onChange={(e) => set("batch_size", Number(e.target.value))} /></label>
          <label className="field"><span>Ignore mail before (ISO date, blank = none)</span><input className="input" value={s.fetch_since ?? ""} onChange={(e) => set("fetch_since", e.target.value || null)} placeholder="YYYY-MM-DDT00:00:00+00:00" /></label>
          <label className="field"><span>Give up after (attempts)</span><input className="input" type="number" min={1} max={10} value={s.max_attempts} onChange={(e) => set("max_attempts", Number(e.target.value))} /></label>
          <label className="check"><input type="checkbox" checked={s.smtp_enabled} onChange={(e) => set("smtp_enabled", e.target.checked)} /> Accept mail on a local SMTP port (restart required)</label>
          {s.smtp_enabled && <label className="field"><span>SMTP port</span><input className="input" type="number" value={s.smtp_port} onChange={(e) => set("smtp_port", Number(e.target.value))} /></label>}
        </div>
      </section>

      <section className="section">
        <h2>Sender rules</h2>
        <p className="muted" style={{ margin: 0 }}>Exact address, <code>*@domain</code>, or <code>/regex/</code>. Rules run before the model.</p>
        <div className="row">
          <input className="input" placeholder="*@university.edu" value={rule.pattern} onChange={(e) => setRule({ ...rule, pattern: e.target.value })} />
          <select className="input" style={{ maxWidth: 140 }} value={rule.category} onChange={(e) => setRule({ ...rule, category: e.target.value })}>{CATEGORIES.map((c) => <option key={c}>{c}</option>)}</select>
          <input className="input" placeholder="Note (optional)" value={rule.notes} onChange={(e) => setRule({ ...rule, notes: e.target.value })} />
          <button className="btn" onClick={addRule}>Add</button>
        </div>
        {rules.length > 0 && (
          <table className="rules">
            <thead><tr><th>Pattern</th><th>Category</th><th>Note</th><th>Matched</th><th /></tr></thead>
            <tbody>{rules.map((r) => (
              <tr key={r.pattern}>
                <td className="mono">{r.pattern}</td><td>{r.category}</td><td>{r.notes}</td><td className="mono">{r.match_count}</td>
                <td><button className="btn small" onClick={() => api.deleteRule(r.pattern).then(loadRules)}>Remove</button></td>
              </tr>
            ))}</tbody>
          </table>
        )}
      </section>

      <div className="save row">
        <button className="btn primary" onClick={save} disabled={!dirty}>Save changes</button>
        {dirty && <span className="muted">Unsaved changes</span>}
      </div>
    </div>
  );
}

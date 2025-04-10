import { useCallback, useEffect, useRef, useState } from "react";
import { api, subscribe, timeAgo } from "./api";
import type { AppStatus, Settings } from "./types";
import Inbox from "./components/Inbox";
import Alerts from "./components/Alerts";
import Analyze from "./components/Analyze";
import SettingsPage from "./components/Settings";

type View = "inbox" | "alerts" | "analyze" | "settings";
const VIEWS: { key: View; label: string }[] = [
  { key: "inbox", label: "Inbox" },
  { key: "alerts", label: "Alerts" },
  { key: "analyze", label: "Analyze" },
  { key: "settings", label: "Settings" },
];

function viewFromHash(): View {
  const h = location.hash.replace("#", "") as View;
  return VIEWS.some((v) => v.key === h) ? h : "inbox";
}

export default function App() {
  const [view, setView] = useState<View>(viewFromHash);
  const [status, setStatus] = useState<AppStatus | null>(null);
  const [settings, setSettings] = useState<Settings | null>(null);
  const [live, setLive] = useState(false);
  const [tick, setTick] = useState(0); // bumps on any live event so views refetch
  const [checking, setChecking] = useState(false);

  const refreshStatus = useCallback(() => api.status().then(setStatus).catch(() => {}), []);
  const bumpTimer = useRef<number | null>(null);
  const bump = useCallback(() => {
    if (bumpTimer.current != null) return;
    bumpTimer.current = window.setTimeout(() => {
      bumpTimer.current = null;
      setTick((t) => t + 1);
      refreshStatus();
    }, 250);
  }, [refreshStatus]);

  useEffect(() => {
    const onHash = () => setView(viewFromHash());
    addEventListener("hashchange", onHash);
    return () => removeEventListener("hashchange", onHash);
  }, []);

  useEffect(() => {
    refreshStatus();
    api.settings().then(setSettings).catch(() => {});
    const off = subscribe(
      (e) => {
        if (e.type === "settings") setSettings(e.settings);
        bump();
      },
      setLive,
    );
    const iv = setInterval(refreshStatus, 30_000);
    return () => {
      off();
      clearInterval(iv);
    };
  }, [refreshStatus, bump]);

  useEffect(() => {
    document.documentElement.dataset.profile = settings?.profile ?? "general";
  }, [settings?.profile]);

  const go = (v: View) => {
    location.hash = v;
    setView(v);
  };

  const checkNow = async () => {
    setChecking(true);
    try {
      await api.fetchNow();
    } finally {
      setChecking(false);
      refreshStatus();
    }
  };

  const q = status?.queue;
  return (
    <div className="shell">
      <header className="topbar">
        <div className="brand">
          email<b>-agent</b>
        </div>
        {settings && (
          <span className="pill" title="Active profile">
            {settings.profile === "oncall" ? "on-call" : settings.profile}
          </span>
        )}
        <span className="pill" title={live ? "Live updates connected" : "Reconnecting…"}>
          <i className={`dot ${live ? "on" : ""}`} /> live
        </span>
        <span className="pill" title="Gmail authorization">
          <i className={`dot ${status?.gmail_authorized ? "on" : "bad"}`} /> gmail
        </span>
        <span className="spacer" />
        {q && (
          <span className="mono muted">
            {q.queued} queued · {q.processing} working · {q.failed} failed · checked {timeAgo(status?.last_fetch_at ?? null)}
          </span>
        )}
        <button className="btn small" onClick={checkNow} disabled={checking}>
          {checking ? "Checking…" : "Check now"}
        </button>
      </header>
      <div className="body">
        <nav className="nav" aria-label="Sections">
          {VIEWS.map((v) => (
            <button key={v.key} onClick={() => go(v.key)} aria-current={view === v.key ? "page" : undefined}>
              {v.label}
              {v.key === "alerts" && status && status.unread_alerts > 0 && <span className="count">{status.unread_alerts}</span>}
              {v.key === "inbox" && q && q.total > 0 && <span className="count">{q.total}</span>}
            </button>
          ))}
        </nav>
        <main className="main">
          {status?.last_fetch_error && view === "inbox" && (
            <div className="notice bad" style={{ margin: 12 }}>
              {status.last_fetch_error}{" "}
              {!status.gmail_authorized && (
                <span>
                  — run <code>email-agent auth</code> in a terminal.
                </span>
              )}
            </div>
          )}
          {view === "inbox" && <Inbox tick={tick} />}
          {view === "alerts" && <Alerts tick={tick} onChanged={refreshStatus} />}
          {view === "analyze" && <Analyze />}
          {view === "settings" && settings && <SettingsPage settings={settings} onSaved={setSettings} />}
        </main>
      </div>
    </div>
  );
}

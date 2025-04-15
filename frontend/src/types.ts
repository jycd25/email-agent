export type Status = "queued" | "processing" | "done" | "failed";
export type Level = "low" | "medium" | "high" | "urgent";
export type Profile = "general" | "student" | "oncall";

export interface Urgency {
  urgency_level: Level;
  time_sensitive: boolean;
  deadline: string | null;
  keywords_detected: string[];
  confidence_score: number;
  summary: string;
  detailed: boolean;
}
export interface Topic {
  primary_topic: string;
  similarity_score: number;
  confidence_score: number;
  message_summary: string;
  is_watchlist_topic: boolean;
  detailed: boolean;
}
export interface Sender {
  email: string;
  category: string;
  rule_matched: string | null;
  is_trusted: boolean;
  is_blocked: boolean;
  notes: string | null;
  confidence_score: number;
  suggested_rule: string | null;
  analysis_method: string;
}
export interface Classification {
  category: string;
  priority: string;
  action_required: boolean;
  action_list: string[];
  important_dates: string[];
  summary: string;
}
export interface Analyses {
  urgency?: Urgency;
  topic?: Topic;
  sender?: Sender;
  classification?: Classification;
}
export interface EmailRow {
  id: number;
  source: string;
  received_at: string;
  from_addr: string;
  subject: string;
  body_text: string;
  status: Status;
  attempts: number;
  error: string | null;
  analyses: Analyses;
}
export interface EmailDetail extends Omit<EmailRow, "analyses"> {
  analyses: { kind: string; result: Record<string, unknown>; created_at: string }[];
}
export interface Alert {
  id: number;
  email_id: number | null;
  type: "urgency" | "topic" | "sender" | "system";
  level: "low" | "medium" | "high" | "critical";
  message: string;
  details: Record<string, unknown>;
  read: boolean;
  created_at: string;
}
export interface Settings {
  profile: Profile;
  provider: "ollama" | "openai";
  model: string;
  base_url: string;
  tool_selection_model: string;
  poll_interval_seconds: number;
  batch_size: number;
  max_attempts: number;
  fetch_since: string | null;
  analyze_urgency: boolean;
  analyze_topics: boolean;
  analyze_sender: boolean;
  classify: boolean;
  urgency_threshold: Level;
  topic_threshold: number;
  min_confidence: number;
  alert_on_unknown_sender: boolean;
  sender_mode: "rule" | "llm" | "auto";
  watchlist_topics: string[];
  smtp_enabled: boolean;
  smtp_port: number;
}
export interface AppStatus {
  profile: Profile;
  provider: string;
  model: string;
  gmail_authorized: boolean;
  outlook_authorized: boolean;
  outlook_configured: boolean;
  smtp_enabled: boolean;
  queue: Record<Status | "total", number>;
  unread_alerts: number;
  last_fetch_at: string | null;
  last_fetch_error: string | null;
}
export interface Rule {
  pattern: string;
  category: string;
  notes: string | null;
  added_at: string;
  last_matched: string | null;
  match_count: number;
}
export interface AnalyzeResult {
  tool: string;
  error?: string;
  urgency?: Urgency;
  topic?: Topic;
  sender?: Sender;
  classification?: Classification;
}

// Data contracts — mirror the real BETA AID backend exactly.
export type Outcome =
  | "answered"
  | "clarify"
  | "confirm_requested"
  | "stepup_required"
  | "action_done"
  | "cancelled"
  | "handoff"
  | "deny"
  | "refused"
  | "auth_required"
  | "tool_failure";

export interface Trace {
  turn_id: string;
  outcome: Outcome;
  intent?: string;
  intent_confidence?: number;
  intent_source?: "model" | "llm" | "keyword" | "resume" | "confirmation" | "model_low_confidence";
  policy_rule?: string;
  autonomy?: "A0" | "A2" | "A3";
  policy_version?: string;
  language?: "es" | "pt";
  guard?: string;
  grounding?: string;
  card?: string;
  stages: { stage: string; ms: number }[];
  latency_ms: number;
  llm_calls: number;
  tokens_in: number;
  tokens_out: number;
  cost_usd: number;
  action?: "block" | "unblock" | "reissue";
  action_id?: string;
  read_back?: boolean;
  retrieval?: { cite: string; score: number; classification: "public" | "internal" }[];
}

export type Queue = "fraud" | "risk" | "credit_limits" | "disputes" | "complaints" | "general";

export interface HandoffPacket {
  handoff_id: string;
  created_at: string;
  queue: Queue;
  priority: "high" | "normal";
  language: "es" | "pt";
  customer_id: string;
  authentication: "otp" | "otp+step-up";
  request: string;
  intent: { label: string; confidence: number; source: string };
  policy: { rule: string; version: string };
  verified_facts: Record<string, string | number | boolean | null> | null;
  actions_taken: { action_id: string; action: string; product_id: string; read_back: boolean; at: string }[];
  procedures: { cite: string; title: string; heading: string; classification: string; score: number; text: string }[];
  open_questions: string[];
  transcript: { role: "customer" | "copilot"; text: string }[];
}

export interface ChatResponse {
  text: string;
  outcome: Outcome;
  lang: "es" | "pt";
  buttons: { label: string; action: "message" | "confirm" | "cancel" | "stepup"; value?: string }[];
  handoff: HandoffPacket | null;
  trace: Trace;
}

// ---- Prototype-side types (not part of the backend contract) ----
export type Status = "ok" | "review" | "blocked" | "info";
export type Verdict = "green" | "amber" | "red";

export interface Card {
  product_id: string;
  suffix: string;
  brand: string;
  status: "active" | "blocked" | "expired" | "cancelled";
  limit: number;
  used: number;
  currency: "MXN" | "COP" | "ARS";
  expiry: string;
}
// A demo customer from a region's /api/demo: scenario label and id only (no names, as in the copilot).
export interface Persona {
  customer_id: string;
  role: string;
  scenario: string;
  cards: number;
  hint: string;
}

export interface DemoInfo {
  customers: { role: string; customer_id: string; cards: number; label_es: string; label_pt: string }[];
  otp: string;
  stepup: string;
  staff: string;
  deployment: { name: string; region: string | null; countries: string[] };
}

export interface DeskCase {
  packet: HandoffPacket;
  status: "new" | "accepted" | "approval_requested" | "approved" | "rejected" | "resolved" | "returned";
  sla_minutes: number;
  elapsed_minutes: number;
  timeline: { at: string; event: string; actor: string; hash: string }[];
}

export interface Kpi {
  id: string;
  label: string;
  value: number;
  lo: number;
  hi: number;
  display: string;
  better: "higher" | "lower";
}
export interface UnsafeCase {
  turn_id: string;
  at: string;
  lang: "es" | "pt";
  region: string;
  outcome: Outcome;
  intent: string;
  issue: string;
  trace: Trace;
}
export interface PolicyRow {
  intent: string;
  autonomy: "A0" | "A2" | "A3";
  queue: Queue | "—";
  rule: string;
}
export interface Veto {
  id: string;
  condition: string;
  effect: string;
}

export interface AtlasCell {
  model: string;
  grain: "event" | "day" | "cell" | "hour";
  verdict: Verdict | null;
  gain?: number;
  lo?: number;
  hi?: number;
  materiality?: number;
  mde?: number;
  root_cause?: string;
  oot?: string;
  benchmark?: string;
  requirement?: string;
  kumo?: { variant: string; gain: number; lo: number; hi: number; ablation: { table: string; delta: number }[] }[];
}

export interface QAgent {
  id: string;
  name: string;
  role: string;
  status: Status;
  status_label: string;
  last_run: string;
  findings: number;
}
export type IssueStage =
  | "Detected"
  | "Triaged"
  | "Requirement drafted"
  | "Owner assigned"
  | "Acceptance test defined"
  | "Fixed at source"
  | "Verified"
  | "Closed";
export interface QIssue {
  id: string;
  title: string;
  stage: IssueStage;
  table: string;
  rule: string;
  severity: "A" | "B" | "C";
  rows: number;
  sla: string;
  owner: string;
  gate: string;
}
export interface Correction {
  id: string;
  table: string;
  reason: string;
  proposer: string;
  approver: string | null;
  status: "proposed" | "applied" | "rejected" | "reverted";
  hash?: string;
  applied_at?: string;
  rows: { key: string; field: string; before: string; after: string }[];
}

export interface PipelineCell {
  scope: string;
  layer: string;
  status: Status;
  last_run: string;
  rows: number;
  reconciled: boolean;
  quality_gate: Verdict;
  governance_gate: Verdict;
}

export interface KDoc {
  id: string;
  title: string;
  status: "draft" | "approved" | "superseded" | "retired";
  version: string;
  effective: string;
  classification: "public" | "internal";
  owner: string;
  approver: string;
}
export interface KChunk {
  cite: string;
  text: string;
  classification: "public" | "internal";
  keywords: string[];
  found_by: "vector" | "graph:entity";
}

export interface Spec {
  id: string;
  title: string;
  stage: "Spec" | "Plan" | "Tasks" | "Implementation" | "Verification" | "Released";
  problem: string;
  users: string;
  criteria: string[];
  plan?: string;
  prs?: string[];
  tests?: string;
  eval?: string;
  version?: string;
  closes: string[];
}

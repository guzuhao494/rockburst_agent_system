export type RiskLevel = "L1" | "L2" | "L3" | "L4";
export type AlertStatus =
  | "Observed"
  | "Assessed"
  | "Alerted"
  | "PendingApproval"
  | "Approved"
  | "Rejected"
  | "Dispatched"
  | "Executed"
  | "Reviewed"
  | "Closed";
export type ApprovalStatus = "not_required" | "pending" | "approved" | "rejected";
export type ExecutionStatus = "not_created" | "ready" | "dispatched" | "executed" | "timed_out" | "blocked" | "closed";
export type ReviewStatus = "open" | "closed";

export interface RiskSnapshot {
  snapshot_id: string;
  area_id: string;
  ts: string;
  score: number;
  level: RiskLevel;
  triggered_rules: string[];
  explanation: string;
  contributing_factors: Record<string, number>;
}

export interface Alert {
  alert_id: string;
  risk_snapshot_id: string;
  area_id: string;
  level: RiskLevel;
  status: AlertStatus;
  message: string;
  suggested_actions: string[];
  created_at: string;
  updated_at: string;
}

export interface WorkOrder {
  workorder_id: string;
  alert_id: string;
  type: string;
  assignee: string | null;
  priority: string;
  approval_status: ApprovalStatus;
  execution_status: ExecutionStatus;
  due_at: string | null;
  details: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface ExecutionFeedback {
  feedback_id: string;
  workorder_id: string;
  ts: string;
  result: string;
  notes: string;
  attachments: string[];
}

export interface LoopReview {
  review_id: string;
  alert_id: string;
  effectiveness: string;
  residual_risk: string;
  followup_action: string;
  status: ReviewStatus;
  created_at: string;
  closed_at: string | null;
  closure_note: string | null;
}

export interface AuditLog {
  log_id?: number;
  entity_type: string;
  entity_id: string;
  stage: string;
  actor: string;
  action: string;
  payload: Record<string, unknown>;
  ts: string;
}

export interface AlertEnvelope {
  alert: Alert;
  risk_snapshot: RiskSnapshot;
  work_order: WorkOrder | null;
  latest_feedback: ExecutionFeedback | null;
  loop_review: LoopReview | null;
  audit_logs: AuditLog[];
}

export interface WorkOrderEnvelope {
  work_order: WorkOrder;
  alert: Alert;
  risk_snapshot: RiskSnapshot | null;
  feedbacks: ExecutionFeedback[];
  loop_review: LoopReview | null;
}

export interface DashboardSummary {
  generated_at: string;
  counts: Record<string, number>;
  risk_by_area: RiskSnapshot[];
  recent_audit: AuditLog[];
  replay_status: ReplayState;
}

export interface ReplayState {
  scenario_name: string | null;
  status: "idle" | "running" | "stopped" | "failed";
  progress: number;
  total_batches: number;
  loop_enabled: boolean;
  started_at: string | null;
  last_error: string | null;
  updated_at: string;
}

export interface ScenarioMetadata {
  name: string;
  description: string;
  batches: number;
  areas: string[];
}

export interface RuleConfigResponse {
  min_confidence: number;
  level_boundaries: Record<string, number>;
  weights: Record<string, number>;
  thresholds: Record<string, Record<string, Record<string, number>>>;
  action_templates: Record<string, string[]>;
  work_order_templates: Record<string, { type: string; priority: string; due_in_hours: number; checklist: string[] }>;
  escalation_sla_minutes: Record<string, number>;
}

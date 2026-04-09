import type {
  AlertEnvelope,
  DashboardSummary,
  ReplayState,
  RuleConfigResponse,
  ScenarioMetadata,
  WorkOrderEnvelope
} from "./types";

const DEFAULT_API_HOST = window.location.hostname || "127.0.0.1";
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? `http://${DEFAULT_API_HOST}:8000`;

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers: {
      "Content-Type": "application/json"
    },
    ...init
  });
  if (!response.ok) {
    const raw = await response.text();
    if (raw) {
      let message = raw;
      try {
        const payload = JSON.parse(raw) as { detail?: string };
        if (payload.detail) {
          message = payload.detail;
        }
      } catch {
        // Fall back to the raw response body when the error payload is not JSON.
      }
      throw new Error(message);
    }
    throw new Error(`${response.status} ${response.statusText}`);
  }
  return (await response.json()) as T;
}

export function fetchDashboardSummary() {
  return request<DashboardSummary>("/dashboard/summary");
}

export function fetchAlerts() {
  return request<AlertEnvelope[]>("/alerts");
}

export function fetchWorkOrders() {
  return request<WorkOrderEnvelope[]>("/work-orders");
}

export function fetchRules() {
  return request<RuleConfigResponse>("/config/rules");
}

export function fetchReplayStatus() {
  return request<ReplayState>("/replay/status");
}

export function fetchScenarios() {
  return request<ScenarioMetadata[]>("/replay/scenarios");
}

export function startReplay(scenarioName: string) {
  return request<ReplayState>("/replay/start", {
    method: "POST",
    body: JSON.stringify({
      scenario_name: scenarioName,
      interval_ms: 300,
      loop: false
    })
  });
}

export function stopReplay() {
  return request<ReplayState>("/replay/stop", {
    method: "POST"
  });
}

export function approveAlert(alertId: string, actor: string, note: string) {
  return request(`/alerts/${alertId}/approve`, {
    method: "POST",
    body: JSON.stringify({ actor, note })
  });
}

export function rejectAlert(alertId: string, actor: string, note: string) {
  return request(`/alerts/${alertId}/reject`, {
    method: "POST",
    body: JSON.stringify({ actor, note })
  });
}

export function dispatchWorkOrder(workOrderId: string, actor: string, assignee: string, dispatchNote: string) {
  return request(`/work-orders/${workOrderId}/dispatch`, {
    method: "POST",
    body: JSON.stringify({ actor, assignee, dispatch_note: dispatchNote })
  });
}

export function submitFeedback(workOrderId: string, actor: string, result: string, notes: string) {
  return request(`/work-orders/${workOrderId}/feedback`, {
    method: "POST",
    body: JSON.stringify({ actor, result, notes, attachments: [] })
  });
}

export function closeLoopReview(reviewId: string, actor: string, closureNote: string) {
  return request(`/loop-reviews/${reviewId}/close`, {
    method: "POST",
    body: JSON.stringify({ actor, closure_note: closureNote })
  });
}

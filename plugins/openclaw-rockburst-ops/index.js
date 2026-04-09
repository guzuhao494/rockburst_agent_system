import { Type } from "@sinclair/typebox";
import { definePluginEntry } from "openclaw/plugin-sdk/plugin-entry";

const DEFAULT_BASE_URL = "http://127.0.0.1:8000";
const DEFAULT_ACTOR_NAME = "OpenClaw Agent";
const DEFAULT_TIMEOUT_MS = 15000;

export default definePluginEntry({
  id: "rockburst-ops",
  name: "Rockburst Operations",
  description: "Wrap the rockburst simulation backend as OpenClaw agent tools.",
  register(api) {
    const client = createRockburstClient(api);

    api.registerTool({
      name: "rockburst_agent_briefing",
      description: "Read a prioritized operational briefing for the current rockburst command state.",
      parameters: Type.Object({}, { additionalProperties: false }),
      async execute() {
        const payload = await client.get("/agent/briefing");
        return textResult("Retrieved the rockburst agent briefing.", payload);
      }
    });

    api.registerTool({
      name: "rockburst_command_snapshot",
      description: "Read the current command snapshot, including dashboard summary, alerts, and work orders.",
      parameters: Type.Object(
        {
          includeAlerts: Type.Optional(Type.Boolean({ default: true })),
          includeWorkOrders: Type.Optional(Type.Boolean({ default: true })),
          includeRules: Type.Optional(Type.Boolean({ default: false }))
        },
        { additionalProperties: false }
      ),
      async execute(_id, params = {}) {
        const includeAlerts = params.includeAlerts !== false;
        const includeWorkOrders = params.includeWorkOrders !== false;
        const includeRules = params.includeRules === true;

        const payload = {
          dashboard: await client.get("/dashboard/summary")
        };
        if (includeAlerts) {
          payload.alerts = await client.get("/alerts");
        }
        if (includeWorkOrders) {
          payload.workOrders = await client.get("/work-orders");
        }
        if (includeRules) {
          payload.rules = await client.get("/config/rules");
        }

        return textResult("Retrieved the rockburst command snapshot.", payload);
      }
    });

    api.registerTool({
      name: "rockburst_list_replay_scenarios",
      description: "List available simulated replay scenarios for the rockburst demo system.",
      parameters: Type.Object({}, { additionalProperties: false }),
      async execute() {
        const payload = await client.get("/replay/scenarios");
        return textResult("Retrieved replay scenarios.", payload);
      }
    });

    api.registerTool({
      name: "rockburst_get_rules",
      description: "Read the current rule, threshold, and work-order template configuration.",
      parameters: Type.Object({}, { additionalProperties: false }),
      async execute() {
        const payload = await client.get("/config/rules");
        return textResult("Retrieved rule configuration.", payload);
      }
    });

    api.registerTool({
      name: "rockburst_list_alerts",
      description: "List alerts and optionally filter them by level or status.",
      parameters: Type.Object(
        {
          level: Type.Optional(Type.Union([Type.Literal("L1"), Type.Literal("L2"), Type.Literal("L3"), Type.Literal("L4")])),
          status: Type.Optional(
            Type.Union([
              Type.Literal("Observed"),
              Type.Literal("Assessed"),
              Type.Literal("Alerted"),
              Type.Literal("PendingApproval"),
              Type.Literal("Approved"),
              Type.Literal("Rejected"),
              Type.Literal("Dispatched"),
              Type.Literal("Executed"),
              Type.Literal("Reviewed"),
              Type.Literal("Closed")
            ])
          )
        },
        { additionalProperties: false }
      ),
      async execute(_id, params = {}) {
        const alerts = await client.get("/alerts");
        const filtered = alerts.filter((item) => {
          if (params.level && item.alert.level !== params.level) {
            return false;
          }
          if (params.status && item.alert.status !== params.status) {
            return false;
          }
          return true;
        });
        return textResult(`Retrieved ${filtered.length} alerts.`, filtered);
      }
    });

    api.registerTool({
      name: "rockburst_list_work_orders",
      description: "List work orders and optionally filter by approval, execution status, or priority.",
      parameters: Type.Object(
        {
          approvalStatus: Type.Optional(
            Type.Union([
              Type.Literal("not_required"),
              Type.Literal("pending"),
              Type.Literal("approved"),
              Type.Literal("rejected")
            ])
          ),
          executionStatus: Type.Optional(
            Type.Union([
              Type.Literal("not_created"),
              Type.Literal("ready"),
              Type.Literal("dispatched"),
              Type.Literal("executed"),
              Type.Literal("timed_out"),
              Type.Literal("blocked"),
              Type.Literal("closed")
            ])
          ),
          priority: Type.Optional(Type.String())
        },
        { additionalProperties: false }
      ),
      async execute(_id, params = {}) {
        const workOrders = await client.get("/work-orders");
        const filtered = workOrders.filter((item) => {
          if (params.approvalStatus && item.work_order.approval_status !== params.approvalStatus) {
            return false;
          }
          if (params.executionStatus && item.work_order.execution_status !== params.executionStatus) {
            return false;
          }
          if (params.priority && item.work_order.priority !== params.priority) {
            return false;
          }
          return true;
        });
        return textResult(`Retrieved ${filtered.length} work orders.`, filtered);
      }
    });

    api.registerTool(
      {
        name: "rockburst_start_replay",
        description: "Start a simulated replay scenario in the rockburst demo backend.",
        parameters: Type.Object(
          {
            scenarioName: Type.String(),
            intervalMs: Type.Optional(Type.Integer({ minimum: 100, maximum: 10000, default: 800 })),
            loop: Type.Optional(Type.Boolean({ default: false }))
          },
          { additionalProperties: false }
        ),
        async execute(_id, params) {
          const payload = await client.post("/replay/start", {
            scenario_name: params.scenarioName,
            interval_ms: params.intervalMs ?? 800,
            loop: params.loop ?? false
          });
          return textResult(`Started replay scenario ${params.scenarioName}.`, payload);
        }
      },
      { optional: true }
    );

    api.registerTool(
      {
        name: "rockburst_stop_replay",
        description: "Stop the current simulated replay scenario.",
        parameters: Type.Object({}, { additionalProperties: false }),
        async execute() {
          const payload = await client.post("/replay/stop", {});
          return textResult("Stopped the current replay scenario.", payload);
        }
      },
      { optional: true }
    );

    api.registerTool(
      {
        name: "rockburst_decide_alert",
        description: "Approve or reject an alert in the closed-loop workflow.",
        parameters: Type.Object(
          {
            alertId: Type.String(),
            decision: Type.Union([Type.Literal("approve"), Type.Literal("reject")]),
            note: Type.Optional(Type.String()),
            actor: Type.Optional(Type.String())
          },
          { additionalProperties: false }
        ),
        async execute(_id, params) {
          const actionPath =
            params.decision === "approve"
              ? `/alerts/${encodeURIComponent(params.alertId)}/approve`
              : `/alerts/${encodeURIComponent(params.alertId)}/reject`;
          const payload = await client.post(actionPath, {
            actor: params.actor || client.actorName,
            note: params.note || ""
          });
          return textResult(`Applied ${params.decision} to alert ${params.alertId}.`, payload);
        }
      },
      { optional: true }
    );

    api.registerTool(
      {
        name: "rockburst_dispatch_work_order",
        description: "Dispatch an approved work order to a named assignee.",
        parameters: Type.Object(
          {
            workorderId: Type.String(),
            assignee: Type.String(),
            dueAt: Type.Optional(Type.String()),
            dispatchNote: Type.Optional(Type.String()),
            actor: Type.Optional(Type.String())
          },
          { additionalProperties: false }
        ),
        async execute(_id, params) {
          const payload = await client.post(`/work-orders/${encodeURIComponent(params.workorderId)}/dispatch`, {
            actor: params.actor || client.actorName,
            assignee: params.assignee,
            due_at: params.dueAt ?? null,
            dispatch_note: params.dispatchNote || ""
          });
          return textResult(`Dispatched work order ${params.workorderId} to ${params.assignee}.`, payload);
        }
      },
      { optional: true }
    );

    api.registerTool(
      {
        name: "rockburst_submit_feedback",
        description: "Submit execution feedback for a dispatched work order.",
        parameters: Type.Object(
          {
            workorderId: Type.String(),
            result: Type.Union([
              Type.Literal("completed"),
              Type.Literal("timed_out"),
              Type.Literal("blocked"),
              Type.Literal("risk_not_reduced")
            ]),
            notes: Type.String(),
            attachments: Type.Optional(Type.Array(Type.String(), { default: [] })),
            actor: Type.Optional(Type.String())
          },
          { additionalProperties: false }
        ),
        async execute(_id, params) {
          const payload = await client.post(`/work-orders/${encodeURIComponent(params.workorderId)}/feedback`, {
            actor: params.actor || client.actorName,
            result: params.result,
            notes: params.notes,
            attachments: params.attachments || []
          });
          return textResult(`Submitted execution feedback for work order ${params.workorderId}.`, payload);
        }
      },
      { optional: true }
    );

    api.registerTool(
      {
        name: "rockburst_close_loop_review",
        description: "Close a loop review after the operator confirms the review outcome.",
        parameters: Type.Object(
          {
            reviewId: Type.String(),
            closureNote: Type.String(),
            actor: Type.Optional(Type.String())
          },
          { additionalProperties: false }
        ),
        async execute(_id, params) {
          const payload = await client.post(`/loop-reviews/${encodeURIComponent(params.reviewId)}/close`, {
            actor: params.actor || client.actorName,
            closure_note: params.closureNote
          });
          return textResult(`Closed loop review ${params.reviewId}.`, payload);
        }
      },
      { optional: true }
    );

    api.registerTool(
      {
        name: "rockburst_ingest_demo_batch",
        description: "Generate a synthetic microseismic event batch and ingest it into the backend.",
        parameters: Type.Object(
          {
            areaId: Type.String(),
            profile: Type.Union([Type.Literal("normal"), Type.Literal("escalating"), Type.Literal("burst")]),
            eventCount: Type.Optional(Type.Integer({ minimum: 1, maximum: 8, default: 4 })),
            source: Type.Optional(Type.String({ default: "openclaw-sim" }))
          },
          { additionalProperties: false }
        ),
        async execute(_id, params) {
          const events = buildSyntheticEvents({
            areaId: params.areaId,
            profile: params.profile,
            eventCount: params.eventCount ?? 4,
            source: params.source ?? "openclaw-sim"
          });
          const payload = await client.post("/ingest/microseismic-events", { events });
          return textResult(`Injected ${events.length} synthetic microseismic events into area ${params.areaId}.`, payload);
        }
      },
      { optional: true }
    );
  }
});

function createRockburstClient(api) {
  const config = readPluginConfig(api);
  const baseUrl = stripTrailingSlash(config.baseUrl || DEFAULT_BASE_URL);
  const actorName = config.actorName || DEFAULT_ACTOR_NAME;
  const requestTimeoutMs = config.requestTimeoutMs || DEFAULT_TIMEOUT_MS;

  async function request(path, init = {}) {
    const response = await fetch(`${baseUrl}${path}`, {
      ...init,
      headers: {
        "content-type": "application/json",
        ...(init.headers || {})
      },
      signal: AbortSignal.timeout(requestTimeoutMs)
    });

    const rawText = await response.text();
    const payload = rawText ? safeJsonParse(rawText) : {};
    if (!response.ok) {
      const detail =
        payload && typeof payload === "object" && "detail" in payload
          ? payload.detail
          : `${response.status} ${response.statusText}`;
      throw new Error(`Rockburst backend request failed: ${detail}`);
    }
    return payload;
  }

  return {
    actorName,
    get(path) {
      return request(path, { method: "GET" });
    },
    post(path, body) {
      return request(path, { method: "POST", body: JSON.stringify(body) });
    }
  };
}

function readPluginConfig(api) {
  const pluginConfig = api.pluginConfig && typeof api.pluginConfig === "object" ? api.pluginConfig : {};
  return {
    baseUrl:
      typeof pluginConfig.baseUrl === "string" && pluginConfig.baseUrl.trim()
        ? pluginConfig.baseUrl.trim()
        : DEFAULT_BASE_URL,
    actorName:
      typeof pluginConfig.actorName === "string" && pluginConfig.actorName.trim()
        ? pluginConfig.actorName.trim()
        : DEFAULT_ACTOR_NAME,
    requestTimeoutMs: normalizeTimeout(pluginConfig.requestTimeoutMs)
  };
}

function normalizeTimeout(value) {
  if (typeof value === "number" && Number.isFinite(value)) {
    return Math.max(1000, Math.min(60000, Math.trunc(value)));
  }
  return DEFAULT_TIMEOUT_MS;
}

function stripTrailingSlash(value) {
  return value.replace(/\/+$/, "");
}

function safeJsonParse(rawText) {
  try {
    return JSON.parse(rawText);
  } catch {
    return { rawText };
  }
}

function textResult(message, payload) {
  return {
    content: [
      {
        type: "text",
        text: `${message}\n\n${JSON.stringify(payload, null, 2)}`
      }
    ]
  };
}

function buildSyntheticEvents({ areaId, profile, eventCount, source }) {
  const now = Date.now();
  const profileFactories = {
    normal: (index) => ({
      energy: 8 + index * 2,
      magnitude: 0.4 + index * 0.05,
      confidence: 0.92
    }),
    escalating: (index) => ({
      energy: 25 + index * 18,
      magnitude: 0.8 + index * 0.18,
      confidence: 0.95
    }),
    burst: (index) => ({
      energy: index === eventCount - 1 ? 220 : 40 + index * 25,
      magnitude: index === eventCount - 1 ? 2.1 : 1.0 + index * 0.2,
      confidence: 0.97
    })
  };

  const buildMetrics = profileFactories[profile] || profileFactories.normal;
  return Array.from({ length: eventCount }, (_, index) => {
    const metrics = buildMetrics(index);
    return {
      event_id: `oc-${profile}-${areaId}-${now}-${index + 1}`,
      ts: new Date(now + index * 12000).toISOString(),
      area_id: areaId,
      energy: metrics.energy,
      magnitude: metrics.magnitude,
      x: Number((100 + index * 1.7).toFixed(2)),
      y: Number((45 + index * 1.3).toFixed(2)),
      z: Number((-320 - index * 4.5).toFixed(2)),
      confidence: metrics.confidence,
      source
    };
  });
}

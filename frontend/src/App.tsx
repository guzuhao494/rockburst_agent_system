import { useCallback, useEffect, useMemo, useState, useTransition } from "react";

import {
  approveAlert,
  closeLoopReview,
  dispatchWorkOrder,
  fetchAlerts,
  fetchDashboardSummary,
  fetchReplayStatus,
  fetchRules,
  fetchScenarios,
  fetchWorkOrders,
  rejectAlert,
  startReplay,
  stopReplay,
  submitFeedback,
} from "./api";
import type {
  AlertEnvelope,
  AgentMonitorState,
  DashboardSummary,
  ReplayState,
  RuleConfigResponse,
  ScenarioMetadata,
  WorkOrderEnvelope,
} from "./types";

type PageKey = "overview" | "alerts" | "workorders" | "rules";
type ReplayRoleKey =
  | "supervisor"
  | "ingest_intake"
  | "data_quality"
  | "risk_assessment"
  | "alert_explanation"
  | "action_planning"
  | "work_order_coordination"
  | "effectiveness_verification"
  | "supervisor_finalize";

type LoopStageKey =
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

const NAV_ITEMS: Array<{ key: PageKey; label: string; helper: string }> = [
  { key: "overview", label: "态势总览", helper: "当前风险态势与审计轨迹" },
  { key: "alerts", label: "告警中心", helper: "审批、驳回与证据解释" },
  { key: "workorders", label: "工单闭环台", helper: "派发、反馈与复核关环" },
  { key: "rules", label: "规则与回放", helper: "场景回放与阈值配置" },
];

const DEFAULT_ACTOR = "dispatcher-01";
const DEFAULT_ASSIGNEE = "field-inspection-team";
const DEFAULT_DEMO_SCENARIO = "escalating_risk";

const ALERT_STATUS_LABELS: Record<string, string> = {
  Observed: "已观测",
  Assessed: "已评估",
  Alerted: "已告警",
  PendingApproval: "待审批",
  Approved: "已批准",
  Rejected: "已驳回",
  Dispatched: "已派发",
  Executed: "已执行",
  Reviewed: "已复核",
  Closed: "已关闭",
};

const APPROVAL_STATUS_LABELS: Record<string, string> = {
  not_required: "无需审批",
  pending: "待审批",
  approved: "已批准",
  rejected: "已驳回",
};

const EXECUTION_STATUS_LABELS: Record<string, string> = {
  not_created: "未创建",
  ready: "待派发",
  dispatched: "已派发",
  executed: "已执行",
  timed_out: "已超时",
  blocked: "受阻",
  closed: "已关闭",
};

const REPLAY_STATUS_LABELS: Record<string, string> = {
  idle: "空闲",
  running: "运行中",
  stopped: "已停止",
  failed: "失败",
};

const MONITOR_STATUS_LABELS: Record<string, string> = {
  idle: "未启动",
  monitoring: "监测中",
  attention: "已发现关键事项",
  error: "监测异常",
};

const REPLAY_PHASE_LABELS: Record<string, string> = {
  idle: "空闲",
  waiting_batch: "等待批次注入",
  dispatching_batch: "注入批次事件",
  dispatching_case: "准备进入当前区域",
  running_role: "执行角色中",
  role_completed: "角色已完成",
  batch_completed: "批次已完成",
  completed: "回放已完成",
  stopped: "回放已停止",
  failed: "回放失败",
};

const REPLAY_ROLE_FLOW: Array<{ key: ReplayRoleKey; label: string; helper: string }> = [
  { key: "supervisor", label: "监督编排", helper: "确认本轮工作流开始执行。" },
  { key: "ingest_intake", label: "采集接入", helper: "整理当前批次事件并形成输入。" },
  { key: "data_quality", label: "数据质检", helper: "过滤低置信度和异常事件。" },
  { key: "risk_assessment", label: "风险评估", helper: "生成风险快照与等级判断。" },
  { key: "alert_explanation", label: "告警解释", helper: "决定是否生成告警并给出解释。" },
  { key: "action_planning", label: "处置规划", helper: "为高等级风险起草处置工单。" },
  { key: "work_order_coordination", label: "工单协调", helper: "落库工单或保留观察态。" },
  { key: "effectiveness_verification", label: "效果验证", helper: "在 review 模式下复核执行反馈。" },
  { key: "supervisor_finalize", label: "监督收尾", helper: "结束本轮工作流并写入审计。" },
];

const PRIORITY_LABELS: Record<string, string> = {
  low: "低",
  medium: "中",
  high: "高",
  critical: "紧急",
};

const AUDIT_STAGE_LABELS: Record<string, string> = {
  Supervisor: "监督编排",
  Observed: "已观测",
  Assessed: "已评估",
  Alerted: "已告警",
  PendingApproval: "待审批",
  Approved: "已批准",
  Rejected: "已驳回",
  Dispatched: "已派发",
  Executed: "已执行",
  Reviewed: "已复核",
  Closed: "已关闭",
};

const AUDIT_ACTOR_LABELS: Record<string, string> = {
  SupervisorAgent: "监督编排 Agent",
  IntakeAgent: "采集接入 Agent",
  QualityAgent: "数据质检 Agent",
  RiskAssessmentAgent: "风险评估 Agent",
  AlertExplanationAgent: "预警解释 Agent",
  ActionPlanningAgent: "处置规划 Agent",
  WorkOrderCoordinationAgent: "工单协调 Agent",
  EffectivenessVerificationAgent: "效果验证 Agent",
  "dispatcher-01": "调度员 dispatcher-01",
  rockburst: "OpenClaw 外层值守 Agent",
};

const ENTITY_TYPE_LABELS: Record<string, string> = {
  workflow: "流程",
  risk_snapshot: "风险快照",
  alert: "告警",
  work_order: "工单",
  loop_review: "复核",
  tool: "工具",
  agent_monitor: "自动监测",
};

const AUDIT_ACTION_LABELS: Record<string, string> = {
  workflow_started: "流程启动",
  events_received: "事件接收",
  quality_checked: "数据质检完成",
  assessment_skipped_no_valid_events: "无有效事件，跳过评估",
  risk_snapshot_created: "生成风险快照",
  alert_created: "生成告警",
  work_order_created: "生成工单",
  observation_only: "仅观察，不派工",
  loop_review_created: "生成复核结论",
  workflow_finished: "流程结束",
  alert_approved: "告警已批准",
  alert_rejected: "告警已驳回",
  work_order_dispatched: "工单已派发",
  execution_feedback_submitted: "已提交执行反馈",
  loop_review_completed: "复核已完成",
  loop_closed: "闭环已关闭",
  tool_completed: "工具调用完成",
  work_order_persisted: "工单已入库",
  agent_decision_failed: "角色决策失败",
  workflow_failed: "工作流失败",
  auto_briefing_published: "自动简报已发布",
};

const REVIEW_EFFECTIVENESS_LABELS: Record<string, string> = {
  effective: "有效",
  not_completed: "未完成",
  blocked: "受阻",
  risk_not_reduced: "风险未下降",
};

const RESIDUAL_RISK_LABELS: Record<string, string> = {
  "medium-low": "中低",
  high: "高",
};

const SCENARIO_LABELS: Record<string, string> = {
  normal_fluctuation: "正常波动",
  escalating_risk: "持续增强型风险",
  sudden_burst: "突发高能事件",
};

const FEEDBACK_RESULT_OPTIONS: Array<{ value: string; label: string }> = [
  { value: "completed", label: "已完成" },
  { value: "timed_out", label: "执行超时" },
  { value: "blocked", label: "执行受阻" },
  { value: "risk_not_reduced", label: "风险未下降" },
];

const LOOP_STATE_FLOW: Array<{ key: LoopStageKey; title: string; helper: string }> = [
  { key: "Observed", title: "Observed", helper: "微震事件进入采集接入，形成可追踪输入。" },
  { key: "Assessed", title: "Assessed", helper: "数据质检通过后生成风险快照与评分。" },
  { key: "Alerted", title: "Alerted", helper: "L2 及以上进入系统告警与解释提示。" },
  { key: "PendingApproval", title: "PendingApproval", helper: "L3/L4 待人工审批，准备派工。" },
  { key: "Approved", title: "Approved", helper: "审批通过，工单可进入现场派发。" },
  { key: "Rejected", title: "Rejected", helper: "审批驳回，回退为观察或停止处置。" },
  { key: "Dispatched", title: "Dispatched", helper: "工单已派发至现场团队执行。" },
  { key: "Executed", title: "Executed", helper: "执行反馈回写，进入效果验证阶段。" },
  { key: "Reviewed", title: "Reviewed", helper: "系统生成复核意见和后续建议。" },
  { key: "Closed", title: "Closed", helper: "监督编排完成关环并沉淀审计链。" },
];

export default function App() {
  const [page, setPage] = useState<PageKey>("overview");
  const [dashboard, setDashboard] = useState<DashboardSummary | null>(null);
  const [alerts, setAlerts] = useState<AlertEnvelope[]>([]);
  const [workOrders, setWorkOrders] = useState<WorkOrderEnvelope[]>([]);
  const [rules, setRules] = useState<RuleConfigResponse | null>(null);
  const [replayStatus, setReplayStatus] = useState<ReplayState | null>(null);
  const [scenarios, setScenarios] = useState<ScenarioMetadata[]>([]);
  const [selectedAlertId, setSelectedAlertId] = useState<string | null>(null);
  const [selectedWorkOrderId, setSelectedWorkOrderId] = useState<string | null>(null);
  const [decisionNote, setDecisionNote] = useState("请先核查局部支护状态与扰动源，再决定是否放行工单。");
  const [dispatchNote, setDispatchNote] = useState("先确认作业区边界，再回传现场巡检结论和照片。");
  const [assignee, setAssignee] = useState(DEFAULT_ASSIGNEE);
  const [feedbackNote, setFeedbackNote] = useState("现场处置已执行，等待最新巡检结论和风险变化记录。");
  const [feedbackResult, setFeedbackResult] = useState("completed");
  const [closureNote, setClosureNote] = useState("复核通过，转入持续观察状态。");
  const [error, setError] = useState<string | null>(null);
  const [booting, setBooting] = useState(true);
  const [actionLabel, setActionLabel] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();
  const agentMonitor = dashboard?.agent_monitor ?? null;
  const replayFailureMessage =
    replayStatus?.status === "failed" && replayStatus.last_error ? `回放失败：${replayStatus.last_error}` : null;
  const monitorFailureMessage =
    agentMonitor?.status === "error" && agentMonitor.last_error ? `自动监测异常：${agentMonitor.last_error}` : null;
  const effectiveError = error ?? replayFailureMessage ?? monitorFailureMessage;

  const refresh = useCallback(
    async (silent = false) => {
      if (!silent) {
        setBooting(true);
      }
      try {
        const [dashboardData, alertsData, workOrdersData, rulesData, replayData, scenariosData] = await Promise.all([
          fetchDashboardSummary(),
          fetchAlerts(),
          fetchWorkOrders(),
          fetchRules(),
          fetchReplayStatus(),
          fetchScenarios(),
        ]);
        startTransition(() => {
          setDashboard(dashboardData);
          setAlerts(alertsData);
          setWorkOrders(workOrdersData);
          setRules(rulesData);
          setReplayStatus(replayData);
          setScenarios(scenariosData);
          setError(null);
        });
      } catch (unknownError) {
        const message = unknownError instanceof Error ? unknownError.message : "数据加载失败";
        setError(message);
      } finally {
        setBooting(false);
      }
    },
    [startTransition],
  );

  useEffect(() => {
    void refresh();
    const intervalId = window.setInterval(() => {
      void refresh(true);
    }, 5000);
    return () => window.clearInterval(intervalId);
  }, [refresh]);

  useEffect(() => {
    if (!selectedAlertId && alerts[0]) {
      setSelectedAlertId(alerts[0].alert.alert_id);
    }
    if (selectedAlertId && !alerts.some((item) => item.alert.alert_id === selectedAlertId)) {
      setSelectedAlertId(alerts[0]?.alert.alert_id ?? null);
    }
  }, [alerts, selectedAlertId]);

  useEffect(() => {
    if (!selectedWorkOrderId && workOrders[0]) {
      setSelectedWorkOrderId(workOrders[0].work_order.workorder_id);
    }
    if (selectedWorkOrderId && !workOrders.some((item) => item.work_order.workorder_id === selectedWorkOrderId)) {
      setSelectedWorkOrderId(workOrders[0]?.work_order.workorder_id ?? null);
    }
  }, [selectedWorkOrderId, workOrders]);

  const selectedAlert = useMemo(
    () => alerts.find((item) => item.alert.alert_id === selectedAlertId) ?? alerts[0] ?? null,
    [alerts, selectedAlertId],
  );
  const selectedWorkOrder = useMemo(
    () => workOrders.find((item) => item.work_order.workorder_id === selectedWorkOrderId) ?? workOrders[0] ?? null,
    [selectedWorkOrderId, workOrders],
  );

  const runAction = useCallback(
    async (label: string, operation: () => Promise<unknown>) => {
      setActionLabel(label);
      try {
        await operation();
        await refresh(true);
      } catch (unknownError) {
        const message = unknownError instanceof Error ? unknownError.message : `${label}失败`;
        setError(message);
      } finally {
        setActionLabel(null);
      }
    },
    [refresh],
  );

  const handleApprove = () => {
    if (!selectedAlert) return;
    void runAction("批准告警", () => approveAlert(selectedAlert.alert.alert_id, DEFAULT_ACTOR, decisionNote));
  };

  const handleReject = () => {
    if (!selectedAlert) return;
    void runAction("驳回告警", () => rejectAlert(selectedAlert.alert.alert_id, DEFAULT_ACTOR, decisionNote));
  };

  const handleDispatch = () => {
    if (!selectedWorkOrder) return;
    void runAction("派发工单", () =>
      dispatchWorkOrder(selectedWorkOrder.work_order.workorder_id, DEFAULT_ACTOR, assignee, dispatchNote),
    );
  };

  const handleFeedback = () => {
    if (!selectedWorkOrder) return;
    void runAction("提交反馈", () =>
      submitFeedback(selectedWorkOrder.work_order.workorder_id, DEFAULT_ACTOR, feedbackResult, feedbackNote),
    );
  };

  const handleCloseLoop = () => {
    if (!selectedWorkOrder?.loop_review) return;
    const reviewId = selectedWorkOrder.loop_review.review_id;
    void runAction("完成关环", () => closeLoopReview(reviewId, DEFAULT_ACTOR, closureNote));
  };

  const handleStartReplay = (scenarioName: string) => {
    void runAction("启动回放", () => startReplay(scenarioName));
  };

  const handleStopReplay = () => {
    void runAction("停止回放", () => stopReplay());
  };

  if (booting && !dashboard) {
    return (
      <div className="shell loading-shell">
        <div className="loading-mark">正在构建闭环指挥台</div>
      </div>
    );
  }

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand-block">
          <p className="eyebrow">岩爆预警与防控</p>
          <h1>闭环协同指挥台</h1>
          <p className="muted">基于微震数据完成预警、审批、派工、反馈、复核与审计留痕。</p>
        </div>
        <nav className="nav-list">
          {NAV_ITEMS.map((item) => (
            <button
              type="button"
              key={item.key}
              className={`nav-item ${page === item.key ? "active" : ""}`}
              onClick={() => setPage(item.key)}
            >
              <span>{item.label}</span>
              <small>{item.helper}</small>
            </button>
          ))}
        </nav>
        <div className="sidebar-footer">
          <div className="status-row">
            <span>刷新状态</span>
            <strong>{isPending ? "同步中" : "在线"}</strong>
          </div>
          <div className="status-row">
            <span>回放状态</span>
            <strong>{labelReplayStatus(replayStatus?.status)}</strong>
          </div>
          <div className="status-row">
            <span>当前角色</span>
            <strong>{formatReplayRoleLabel(replayStatus?.current_role_key) ?? "等待中"}</strong>
          </div>
          <div className="status-row">
            <span>自动简报</span>
            <strong>{labelMonitorStatus(agentMonitor?.status)}</strong>
          </div>
        </div>
      </aside>

      <main className="workspace">
        <header className="masthead">
          <div>
            <p className="eyebrow">半自动闭环</p>
            <h2>以规则、评分与 Agent 协同驱动岩爆预警与防控</h2>
          </div>
          <div className="masthead-meta">
            <StatusChip label="活动告警" value={`${dashboard?.counts.active_alerts ?? 0}`} tone="neutral" />
            <StatusChip label="待审批" value={`${dashboard?.counts.pending_approval ?? 0}`} tone="warning" />
            <StatusChip label="待处理工单" value={`${dashboard?.counts.open_work_orders ?? 0}`} tone="info" />
            <StatusChip
              label="当前角色"
              value={formatReplayRoleLabel(replayStatus?.current_role_key) ?? "等待中"}
              tone={replayStatus?.status === "running" ? "info" : "neutral"}
            />
            <StatusChip
              label="回放"
              value={
                replayStatus?.scenario_name
                  ? `${formatScenarioName(replayStatus.scenario_name)} / ${labelReplayStatus(replayStatus.status)}`
                  : "空闲"
              }
              tone={replayStatus?.status === "running" ? "info" : replayStatus?.status === "failed" ? "warning" : "neutral"}
            />
            <StatusChip
              label="自动简报"
              value={labelMonitorStatus(agentMonitor?.status)}
              tone={agentMonitor?.status === "attention" ? "warning" : agentMonitor?.status === "error" ? "warning" : "neutral"}
            />
          </div>
        </header>

        {effectiveError ? <div className="error-banner">{effectiveError}</div> : null}
        {actionLabel ? <div className="action-banner">正在执行：{actionLabel}</div> : null}

        {page === "overview" ? (
          <OverviewPage
            dashboard={dashboard}
            alerts={alerts}
            workOrders={workOrders}
            replayStatus={replayStatus}
            agentMonitor={agentMonitor}
            busy={Boolean(actionLabel)}
            onNavigate={setPage}
            onStartReplay={handleStartReplay}
            onStopReplay={handleStopReplay}
          />
        ) : null}
        {page === "alerts" ? (
          <AlertsPage
            alerts={alerts}
            selectedAlert={selectedAlert}
            selectedAlertId={selectedAlertId}
            onSelect={setSelectedAlertId}
            decisionNote={decisionNote}
            setDecisionNote={setDecisionNote}
            onApprove={handleApprove}
            onReject={handleReject}
            busy={Boolean(actionLabel)}
          />
        ) : null}
        {page === "workorders" ? (
          <WorkOrdersPage
            workOrders={workOrders}
            selectedWorkOrder={selectedWorkOrder}
            selectedWorkOrderId={selectedWorkOrderId}
            onSelect={setSelectedWorkOrderId}
            assignee={assignee}
            setAssignee={setAssignee}
            dispatchNote={dispatchNote}
            setDispatchNote={setDispatchNote}
            feedbackNote={feedbackNote}
            setFeedbackNote={setFeedbackNote}
            feedbackResult={feedbackResult}
            setFeedbackResult={setFeedbackResult}
            closureNote={closureNote}
            setClosureNote={setClosureNote}
            onDispatch={handleDispatch}
            onFeedback={handleFeedback}
            onCloseLoop={handleCloseLoop}
            busy={Boolean(actionLabel)}
          />
        ) : null}
        {page === "rules" ? (
          <RulesPage
            rules={rules}
            replayStatus={replayStatus}
            agentMonitor={agentMonitor}
            scenarios={scenarios}
            onStartReplay={handleStartReplay}
            onStopReplay={handleStopReplay}
            busy={Boolean(actionLabel)}
          />
        ) : null}
      </main>
    </div>
  );
}

function OverviewPage(props: {
  dashboard: DashboardSummary | null;
  alerts: AlertEnvelope[];
  workOrders: WorkOrderEnvelope[];
  replayStatus: ReplayState | null;
  agentMonitor: AgentMonitorState | null;
  busy: boolean;
  onNavigate: (page: PageKey) => void;
  onStartReplay: (scenarioName: string) => void;
  onStopReplay: () => void;
}) {
  const { dashboard, alerts, workOrders, replayStatus, agentMonitor, busy, onNavigate, onStartReplay, onStopReplay } = props;

  const loopStageCounts: Record<LoopStageKey, number> = {
    Observed: dashboard?.counts.areas ?? 0,
    Assessed: dashboard?.risk_by_area.length ?? 0,
    Alerted: alerts.filter((item) => item.alert.status === "Alerted").length,
    PendingApproval: alerts.filter((item) => item.alert.status === "PendingApproval").length,
    Approved: alerts.filter((item) => item.alert.status === "Approved").length,
    Rejected: alerts.filter((item) => item.alert.status === "Rejected").length,
    Dispatched: workOrders.filter((item) => item.work_order.execution_status === "dispatched").length,
    Executed: workOrders.filter((item) => ["executed", "timed_out", "blocked"].includes(item.work_order.execution_status)).length,
    Reviewed: alerts.filter((item) => item.alert.status === "Reviewed").length,
    Closed: alerts.filter((item) => item.alert.status === "Closed").length,
  };
  const focusStage = getLoopFocusStage(loopStageCounts, replayStatus?.status);

  return (
    <div className="page-grid">
      <section className="hero-panel">
        <div className="hero-top">
          <div>
            <p className="eyebrow">运行态势</p>
            <h3>当前风险总览</h3>
          </div>
          <div className="button-strip">
            <button
              type="button"
              className="primary-button"
              onClick={() => onStartReplay(DEFAULT_DEMO_SCENARIO)}
              disabled={busy}
            >
              启动默认演示
            </button>
            <button
              type="button"
              className="ghost-button"
              onClick={onStopReplay}
              disabled={busy || replayStatus?.status !== "running"}
            >
              停止回放
            </button>
          </div>
        </div>
        <div className="metric-strip">
          <Metric label="监测区域" value={`${dashboard?.counts.areas ?? 0}`} />
          <Metric label="活动告警" value={`${dashboard?.counts.active_alerts ?? 0}`} />
          <Metric label="已关环" value={`${dashboard?.counts.closed_loops ?? 0}`} />
        </div>
        <div className="overview-status-grid">
          <ReplayProgressPanel replayStatus={replayStatus} />
          <MonitorBriefingPanel agentMonitor={agentMonitor} />
        </div>
        <div className="demo-flow">
          <article className="demo-step">
            <strong>1. 启动场景回放</strong>
            <p>默认推荐“持续增强型风险”，用于展示从预警到派工再到复核的完整链路。</p>
          </article>
          <article className="demo-step">
            <strong>2. 进入告警中心</strong>
            <p>查看触发规则、评分来源和建议动作，完成审批或驳回。</p>
          </article>
          <article className="demo-step">
            <strong>3. 进入工单闭环台</strong>
            <p>派发工单、回填执行结果，再由系统生成复核结论并完成关环。</p>
          </article>
          <article className="demo-step">
            <strong>4. 回到总览复盘</strong>
            <p>观察风险变化、最新审计轨迹和闭环效果。</p>
          </article>
        </div>
        <div className="button-strip">
          <button type="button" className="ghost-button" onClick={() => onNavigate("alerts")}>
            前往告警中心
          </button>
          <button type="button" className="ghost-button" onClick={() => onNavigate("workorders")}>
            前往工单闭环台
          </button>
          <button type="button" className="ghost-button" onClick={() => onNavigate("rules")}>
            前往规则与回放
          </button>
        </div>
        <div className="state-machine-shell">
          <div className="row-topline">
            <div>
              <p className="eyebrow">闭环状态机</p>
              <h3>当前闭环推进位置</h3>
            </div>
            <span className="muted">当前焦点：{labelAuditStage(focusStage)}</span>
          </div>
          <div className="state-machine-grid">
            {LOOP_STATE_FLOW.map((stage) => {
              const count = loopStageCounts[stage.key];
              const isFocus = stage.key === focusStage;
              return (
                <article
                  key={stage.key}
                  className={`state-card ${count > 0 ? "active" : ""} ${isFocus ? "focus" : ""}`}
                >
                  <div className="row-topline">
                    <strong>{labelAuditStage(stage.key)}</strong>
                    <span className="state-count">{count}</span>
                  </div>
                  <p>{stage.helper}</p>
                  <small className="muted">{stage.title}</small>
                </article>
              );
            })}
          </div>
          <p className="state-machine-note">
            说明：`L2` 通常停留在告警提示阶段；`L3/L4` 会进入待审批并生成待派工单，之后再进入执行、复核和关环。
          </p>
        </div>
        <div className="risk-lanes">
          {dashboard?.risk_by_area.length ? (
            dashboard.risk_by_area.map((snapshot) => (
              <div key={snapshot.snapshot_id} className="risk-lane">
                <div>
                  <div className="lane-head">
                    <span>{snapshot.area_id}</span>
                    <LevelTag level={snapshot.level} />
                  </div>
                  <p className="muted">{snapshot.explanation}</p>
                </div>
                <div className="lane-score">
                  <strong>{snapshot.score.toFixed(1)}</strong>
                  <small>综合评分</small>
                </div>
              </div>
            ))
          ) : (
            <EmptyState text="暂无风险快照，启动回放后这里会显示各区域最新态势。" />
          )}
        </div>
      </section>

      <section className="split-panel">
        <PanelHeader title="最新告警切片" helper="这里显示当前最值得优先关注的告警。" />
        <div className="stack-list">
          {alerts.slice(0, 4).map((item) => (
            <article key={item.alert.alert_id} className="list-row">
              <div>
                <div className="row-topline">
                  <strong>{item.alert.area_id}</strong>
                  <LevelTag level={item.alert.level} />
                </div>
                <p>{item.alert.message}</p>
              </div>
              <span className="muted">{labelAlertStatus(item.alert.status)}</span>
            </article>
          ))}
          {!alerts.length ? <EmptyState text="当前还没有告警记录。" /> : null}
        </div>
      </section>

      <section className="split-panel">
        <PanelHeader title="审计时间线" helper="监督编排 Agent 的关键动作都会在这里留痕。" />
        <div className="timeline">
          {dashboard?.recent_audit.map((item) => (
            <div key={`${item.entity_id}-${item.ts}-${item.action}`} className="timeline-item">
              <div className="timeline-dot" />
              <div>
                <div className="row-topline">
                  <strong>{labelAuditAction(item.action)}</strong>
                  <span className="muted">{formatTime(item.ts)}</span>
                </div>
                {"summary" in item.payload && typeof item.payload.summary === "string" ? (
                  <p>{item.payload.summary}</p>
                ) : null}
                <p className="muted">
                  {labelAuditActor(item.actor)} / {labelAuditStage(item.stage)} / {labelEntityType(item.entity_type)}:{item.entity_id}
                </p>
              </div>
            </div>
          ))}
          {!dashboard?.recent_audit.length ? <EmptyState text="暂时还没有审计记录。" /> : null}
        </div>
      </section>
    </div>
  );
}

function ReplayProgressPanel({
  replayStatus,
  compact = false,
}: {
  replayStatus: ReplayState | null;
  compact?: boolean;
}) {
  const batchPercent = getProgressPercent(getDisplayedBatchStep(replayStatus), replayStatus?.total_batches ?? 0);
  const rolePercent = getProgressPercent(getDisplayedRoleStep(replayStatus), replayStatus?.total_role_steps ?? 0);
  const activeRoleStep = replayStatus?.current_role_step ?? 0;

  return (
    <section className={`runtime-panel ${compact ? "compact" : ""}`}>
      <div className="row-topline">
        <div>
          <p className="eyebrow">回放执行跟踪</p>
          <h3>当前正在执行哪个角色</h3>
        </div>
        <span className="muted">{labelReplayPhase(replayStatus?.current_phase)}</span>
      </div>
      <div className="detail-grid">
        <DetailBox label="场景" value={replayStatus?.scenario_name ? formatScenarioName(replayStatus.scenario_name) : "未启动"} />
        <DetailBox label="状态" value={labelReplayStatus(replayStatus?.status)} />
        <DetailBox label="当前批次" value={replayStatus?.current_batch ? `${replayStatus.current_batch}` : "-"} />
        <DetailBox label="当前区域" value={replayStatus?.current_area_id ?? "等待中"} />
        <DetailBox label="当前角色" value={formatReplayRoleLabel(replayStatus?.current_role_key) ?? "等待中"} />
        <DetailBox label="角色进度" value={formatRoleProgress(replayStatus)} />
      </div>
      <div className="progress-stack">
        <ProgressMeter label="批次进度" value={formatBatchProgress(replayStatus)} percent={batchPercent} />
        <ProgressMeter label="角色进度" value={formatRoleProgress(replayStatus)} percent={rolePercent} />
      </div>
      <div className="replay-role-grid">
        {REPLAY_ROLE_FLOW.map((role, index) => {
          const step = index + 1;
          const isDone = (replayStatus?.completed_role_steps ?? 0) >= step;
          const isActive = replayStatus?.status === "running" && activeRoleStep === step;
          return (
            <article
              key={role.key}
              className={`replay-role-card ${isDone ? "done" : ""} ${isActive ? "active" : ""}`}
            >
              <div className="row-topline">
                <strong>{role.label}</strong>
                <span className="state-count">{step}</span>
              </div>
              <p>{role.helper}</p>
            </article>
          );
        })}
      </div>
      {replayStatus?.current_summary ? <p className="state-machine-note">{replayStatus.current_summary}</p> : null}
    </section>
  );
}

function MonitorBriefingPanel({ agentMonitor }: { agentMonitor: AgentMonitorState | null }) {
  return (
    <section className="runtime-panel">
      <div className="row-topline">
        <div>
          <p className="eyebrow">OpenClaw 自动简报</p>
          <h3>外层 rockburst 值守</h3>
        </div>
        <span className={`briefing-badge ${agentMonitor?.latest_priority ?? "normal"}`}>
          {labelMonitorStatus(agentMonitor?.status)}
        </span>
      </div>
      <div className="detail-grid">
        <DetailBox label="轮询周期" value={agentMonitor ? `${agentMonitor.poll_interval_seconds} 秒` : "-"} />
        <DetailBox label="最近检查" value={agentMonitor?.last_checked_at ? formatTime(agentMonitor.last_checked_at) : "-"} />
        <DetailBox label="最近简报" value={agentMonitor?.last_briefing_at ? formatTime(agentMonitor.last_briefing_at) : "尚未生成"} />
        <DetailBox label="会话" value={agentMonitor?.session_id ?? "rockburst-monitor"} />
      </div>
      {agentMonitor?.latest_headline ? (
        <div className="briefing-card">
          <div className="row-topline">
            <strong>{agentMonitor.latest_headline}</strong>
            <span className={`briefing-badge ${agentMonitor.latest_priority ?? "normal"}`}>
              {labelBriefingPriority(agentMonitor.latest_priority)}
            </span>
          </div>
          <p>{agentMonitor.latest_summary}</p>
        </div>
      ) : (
        <EmptyState text="值守监测已经启动，关键事项一出现就会在这里生成最新简报。" />
      )}
      {agentMonitor?.last_error ? <p className="muted">最近异常: {agentMonitor.last_error}</p> : null}
    </section>
  );
}

function ProgressMeter({ label, value, percent }: { label: string; value: string; percent: number }) {
  return (
    <div className="progress-meter">
      <div className="row-topline">
        <span>{label}</span>
        <strong>{value}</strong>
      </div>
      <div className="progress-bar" aria-hidden="true">
        <div className="progress-fill" style={{ width: `${percent}%` }} />
      </div>
    </div>
  );
}

function AlertsPage(props: {
  alerts: AlertEnvelope[];
  selectedAlert: AlertEnvelope | null;
  selectedAlertId: string | null;
  onSelect: (id: string) => void;
  decisionNote: string;
  setDecisionNote: (value: string) => void;
  onApprove: () => void;
  onReject: () => void;
  busy: boolean;
}) {
  const { alerts, selectedAlert, selectedAlertId, onSelect, decisionNote, setDecisionNote, onApprove, onReject, busy } = props;

  return (
    <div className="detail-layout">
      <section className="table-panel">
        <PanelHeader title="告警列表" helper="选择一条告警，查看证据、解释和决策链路。" />
        <div className="table-body">
          {alerts.map((item) => (
            <button
              type="button"
              key={item.alert.alert_id}
              className={`table-row ${selectedAlertId === item.alert.alert_id ? "selected" : ""}`}
              onClick={() => onSelect(item.alert.alert_id)}
            >
              <span>{item.alert.area_id}</span>
              <span>{labelAlertStatus(item.alert.status)}</span>
              <LevelTag level={item.alert.level} />
              <span>{formatTime(item.alert.updated_at)}</span>
            </button>
          ))}
          {!alerts.length ? <EmptyState text="暂无告警记录。" /> : null}
        </div>
      </section>

      <section className="detail-panel">
        <PanelHeader title="告警详情" helper="查看风险评分、触发规则和审批动作。" />
        {selectedAlert ? (
          <>
            <div className="headline-block">
              <div className="row-topline">
                <h3>{selectedAlert.alert.area_id}</h3>
                <LevelTag level={selectedAlert.alert.level} />
              </div>
              <p>{selectedAlert.alert.message}</p>
            </div>

            <div className="detail-grid">
              <DetailBox label="状态" value={labelAlertStatus(selectedAlert.alert.status)} />
              <DetailBox label="评分" value={selectedAlert.risk_snapshot.score.toFixed(1)} />
              <DetailBox label="时间" value={formatTime(selectedAlert.risk_snapshot.ts)} />
              <DetailBox label="关联工单" value={selectedAlert.work_order?.type ?? "未生成"} />
            </div>

            <section className="text-panel">
              <h4>解释说明</h4>
              <p>{selectedAlert.risk_snapshot.explanation}</p>
            </section>

            <section className="text-panel">
              <h4>触发规则</h4>
              <ul className="plain-list">
                {selectedAlert.risk_snapshot.triggered_rules.map((rule) => (
                  <li key={rule}>{rule}</li>
                ))}
                {!selectedAlert.risk_snapshot.triggered_rules.length ? <li>当前批次没有触发强规则，主要来自综合评分抬升。</li> : null}
              </ul>
            </section>

            <section className="text-panel">
              <h4>建议动作</h4>
              <ul className="plain-list">
                {selectedAlert.alert.suggested_actions.map((action) => (
                  <li key={action}>{action}</li>
                ))}
              </ul>
            </section>

            <label className="field">
              <span>审批说明</span>
              <textarea value={decisionNote} onChange={(event) => setDecisionNote(event.target.value)} rows={4} />
            </label>

            <div className="action-row">
              <button type="button" className="primary-button" onClick={onApprove} disabled={busy || selectedAlert.alert.status !== "PendingApproval"}>
                批准告警
              </button>
              <button type="button" className="ghost-button" onClick={onReject} disabled={busy || selectedAlert.alert.status === "Closed"}>
                驳回告警
              </button>
            </div>
          </>
        ) : (
          <EmptyState text="请选择一条告警查看详情。" />
        )}
      </section>
    </div>
  );
}

function WorkOrdersPage(props: {
  workOrders: WorkOrderEnvelope[];
  selectedWorkOrder: WorkOrderEnvelope | null;
  selectedWorkOrderId: string | null;
  onSelect: (id: string) => void;
  assignee: string;
  setAssignee: (value: string) => void;
  dispatchNote: string;
  setDispatchNote: (value: string) => void;
  feedbackNote: string;
  setFeedbackNote: (value: string) => void;
  feedbackResult: string;
  setFeedbackResult: (value: string) => void;
  closureNote: string;
  setClosureNote: (value: string) => void;
  onDispatch: () => void;
  onFeedback: () => void;
  onCloseLoop: () => void;
  busy: boolean;
}) {
  const {
    workOrders,
    selectedWorkOrder,
    selectedWorkOrderId,
    onSelect,
    assignee,
    setAssignee,
    dispatchNote,
    setDispatchNote,
    feedbackNote,
    setFeedbackNote,
    feedbackResult,
    setFeedbackResult,
    closureNote,
    setClosureNote,
    onDispatch,
    onFeedback,
    onCloseLoop,
    busy,
  } = props;

  const rawChecklist = selectedWorkOrder?.work_order.details["checklist"];
  const checklist = Array.isArray(rawChecklist) ? (rawChecklist as string[]) : [];

  return (
    <div className="detail-layout">
      <section className="table-panel">
        <PanelHeader title="工单队列" helper="查看所有已生成的闭环工单及其执行状态。" />
        <div className="table-body">
          {workOrders.map((item) => (
            <button
              type="button"
              key={item.work_order.workorder_id}
              className={`table-row ${selectedWorkOrderId === item.work_order.workorder_id ? "selected" : ""}`}
              onClick={() => onSelect(item.work_order.workorder_id)}
            >
              <span>{item.work_order.type}</span>
              <span>{labelApprovalStatus(item.work_order.approval_status)}</span>
              <span>{labelExecutionStatus(item.work_order.execution_status)}</span>
              <span>{labelPriority(item.work_order.priority)}</span>
            </button>
          ))}
          {!workOrders.length ? <EmptyState text="当前还没有工单。" /> : null}
        </div>
      </section>

      <section className="detail-panel">
        <PanelHeader title="工单详情" helper="在这里完成派发、执行反馈与复核关环。" />
        {selectedWorkOrder ? (
          <>
            <div className="headline-block">
              <div className="row-topline">
                <h3>{selectedWorkOrder.work_order.type}</h3>
                <LevelTag level={selectedWorkOrder.alert.level} />
              </div>
              <p>{selectedWorkOrder.alert.message}</p>
            </div>

            <div className="detail-grid">
              <DetailBox label="审批" value={labelApprovalStatus(selectedWorkOrder.work_order.approval_status)} />
              <DetailBox label="执行" value={labelExecutionStatus(selectedWorkOrder.work_order.execution_status)} />
              <DetailBox label="执行人" value={selectedWorkOrder.work_order.assignee ?? "待指定"} />
              <DetailBox label="截至时间" value={selectedWorkOrder.work_order.due_at ? formatTime(selectedWorkOrder.work_order.due_at) : "未设置"} />
            </div>

            <section className="text-panel">
              <h4>工单清单</h4>
              <ul className="plain-list">
                {checklist.map((item) => (
                  <li key={item}>{item}</li>
                ))}
                {!checklist.length ? <li>当前模板未配置检查清单。</li> : null}
              </ul>
            </section>

            <label className="field">
              <span>执行人</span>
              <input value={assignee} onChange={(event) => setAssignee(event.target.value)} />
            </label>
            <label className="field">
              <span>派发说明</span>
              <textarea value={dispatchNote} onChange={(event) => setDispatchNote(event.target.value)} rows={3} />
            </label>
            <button
              type="button"
              className="primary-button"
              onClick={onDispatch}
              disabled={busy || selectedWorkOrder.work_order.approval_status !== "approved" || selectedWorkOrder.work_order.execution_status !== "ready"}
            >
              派发工单
            </button>

            <div className="form-grid">
              <label className="field">
                <span>反馈结果</span>
                <select value={feedbackResult} onChange={(event) => setFeedbackResult(event.target.value)}>
                  {FEEDBACK_RESULT_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </label>
              <label className="field">
                <span>反馈说明</span>
                <textarea value={feedbackNote} onChange={(event) => setFeedbackNote(event.target.value)} rows={3} />
              </label>
            </div>

            <button
              type="button"
              className="primary-button"
              onClick={onFeedback}
              disabled={busy || !["dispatched", "executed", "timed_out", "blocked"].includes(selectedWorkOrder.work_order.execution_status)}
            >
              提交反馈
            </button>

            <section className="text-panel">
              <h4>闭环复核</h4>
              {selectedWorkOrder.loop_review ? (
                <>
                  <p>处置效果：{labelReviewEffectiveness(selectedWorkOrder.loop_review.effectiveness)}</p>
                  <p>剩余风险：{labelResidualRisk(selectedWorkOrder.loop_review.residual_risk)}</p>
                  <p>后续动作：{selectedWorkOrder.loop_review.followup_action}</p>
                  <label className="field">
                    <span>关环说明</span>
                    <textarea value={closureNote} onChange={(event) => setClosureNote(event.target.value)} rows={3} />
                  </label>
                  <button
                    type="button"
                    className="ghost-button"
                    onClick={onCloseLoop}
                    disabled={busy || selectedWorkOrder.loop_review.status === "closed"}
                  >
                    完成关环
                  </button>
                </>
              ) : (
                <p className="muted">提交执行反馈后，系统会自动生成复核意见。</p>
              )}
            </section>
          </>
        ) : (
          <EmptyState text="请选择一条工单查看详情。" />
        )}
      </section>
    </div>
  );
}

function RulesPage(props: {
  rules: RuleConfigResponse | null;
  replayStatus: ReplayState | null;
  agentMonitor: AgentMonitorState | null;
  scenarios: ScenarioMetadata[];
  onStartReplay: (scenarioName: string) => void;
  onStopReplay: () => void;
  busy: boolean;
}) {
  const { rules, replayStatus, agentMonitor, scenarios, onStartReplay, onStopReplay, busy } = props;

  return (
    <div className="page-grid">
      <section className="hero-panel">
        <div className="row-topline">
          <div>
            <p className="eyebrow">场景回放</p>
            <h3>回放控制台</h3>
          </div>
          <button type="button" className="ghost-button" onClick={onStopReplay} disabled={busy || replayStatus?.status !== "running"}>
            停止回放
          </button>
        </div>
        <div className="detail-grid">
          <DetailBox label="场景" value={replayStatus?.scenario_name ? formatScenarioName(replayStatus.scenario_name) : "未启动"} />
          <DetailBox label="状态" value={labelReplayStatus(replayStatus?.status)} />
          <DetailBox label="批次进度" value={formatBatchProgress(replayStatus)} />
          <DetailBox label="角色进度" value={formatRoleProgress(replayStatus)} />
          <DetailBox label="当前角色" value={formatReplayRoleLabel(replayStatus?.current_role_key) ?? "等待中"} />
          <DetailBox label="当前区域" value={replayStatus?.current_area_id ?? "等待中"} />
          <DetailBox label="阶段" value={labelReplayPhase(replayStatus?.current_phase)} />
          <DetailBox label="自动简报" value={labelMonitorStatus(agentMonitor?.status)} />
          <DetailBox label="更新时间" value={replayStatus?.updated_at ? formatTime(replayStatus.updated_at) : "-"} />
        </div>
        <ReplayProgressPanel replayStatus={replayStatus} compact />
        <div className="scenario-list">
          {scenarios.map((scenario) => (
            <article key={scenario.name} className="scenario-item">
              <div>
                <div className="row-topline">
                  <strong>{formatScenarioName(scenario.name)}</strong>
                  <span className="muted">{scenario.batches} 个批次</span>
                </div>
                <p>{scenario.description}</p>
                <small className="muted">区域：{scenario.areas.join(", ")}</small>
              </div>
              <button type="button" className="primary-button" onClick={() => onStartReplay(scenario.name)} disabled={busy}>
                启动回放
              </button>
            </article>
          ))}
        </div>
      </section>

      <section className="split-panel">
        <PanelHeader title="评分权重" helper="展示综合风险评分的计算权重。" />
        <div className="stack-list">
          {rules ? (
            Object.entries(rules.weights).map(([key, value]) => (
              <div key={key} className="list-row compact">
                <span>{key}</span>
                <strong>{value}</strong>
              </div>
            ))
          ) : (
            <EmptyState text="规则尚未加载。" />
          )}
        </div>
      </section>

      <section className="split-panel">
        <PanelHeader title="区域阈值" helper="展示默认阈值与分区域覆盖规则。" />
        <div className="threshold-table">
          {rules ? (
            Object.entries(rules.thresholds).map(([area, metrics]) => (
              <div key={area} className="threshold-block">
                <div className="row-topline">
                  <strong>{area}</strong>
                  <span className="muted">L2 / L3 / L4</span>
                </div>
                {Object.entries(metrics).map(([metricName, bands]) => (
                  <div key={metricName} className="metric-line">
                    <span>{metricName}</span>
                    <code>
                      {bands.L2} / {bands.L3} / {bands.L4}
                    </code>
                  </div>
                ))}
              </div>
            ))
          ) : (
            <EmptyState text="暂无阈值配置。" />
          )}
        </div>
      </section>
    </div>
  );
}

function PanelHeader({ title, helper }: { title: string; helper: string }) {
  return (
    <div className="panel-header">
      <h3>{title}</h3>
      <p>{helper}</p>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="metric">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function DetailBox({ label, value }: { label: string; value: string }) {
  return (
    <div className="detail-box">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function StatusChip({ label, value, tone }: { label: string; value: string; tone: "neutral" | "warning" | "info" }) {
  return (
    <div className={`status-chip ${tone}`}>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function LevelTag({ level }: { level: string }) {
  return <span className={`level-tag ${level.toLowerCase()}`}>{level}</span>;
}

function EmptyState({ text }: { text: string }) {
  return <div className="empty-state">{text}</div>;
}

function labelAlertStatus(status: string) {
  return ALERT_STATUS_LABELS[status] ?? status;
}

function labelApprovalStatus(status: string) {
  return APPROVAL_STATUS_LABELS[status] ?? status;
}

function labelExecutionStatus(status: string) {
  return EXECUTION_STATUS_LABELS[status] ?? status;
}

function labelReplayStatus(status?: string | null) {
  if (!status) {
    return REPLAY_STATUS_LABELS.idle;
  }
  return REPLAY_STATUS_LABELS[status] ?? status;
}

function labelMonitorStatus(status?: string | null) {
  if (!status) {
    return MONITOR_STATUS_LABELS.idle;
  }
  return MONITOR_STATUS_LABELS[status] ?? status;
}

function labelReplayPhase(phase?: string | null) {
  if (!phase) {
    return REPLAY_PHASE_LABELS.idle;
  }
  return REPLAY_PHASE_LABELS[phase] ?? phase;
}

function formatReplayRoleLabel(roleKey?: string | null) {
  if (!roleKey) {
    return null;
  }
  return REPLAY_ROLE_FLOW.find((item) => item.key === roleKey)?.label ?? roleKey;
}

function formatBatchProgress(replayStatus?: ReplayState | null) {
  if (!replayStatus?.total_batches) {
    return "0/0";
  }
  const current = getDisplayedBatchStep(replayStatus);
  return `${Math.min(current, replayStatus.total_batches)}/${replayStatus.total_batches}`;
}

function formatRoleProgress(replayStatus?: ReplayState | null) {
  if (!replayStatus?.total_role_steps) {
    return "0/0";
  }
  return `${getDisplayedRoleStep(replayStatus)}/${replayStatus.total_role_steps}`;
}

function labelBriefingPriority(priority?: string | null) {
  if (!priority) {
    return "一般";
  }
  if (priority === "critical") {
    return "紧急";
  }
  if (priority === "high") {
    return "关注";
  }
  return "一般";
}

function labelPriority(priority?: string | null) {
  if (!priority) {
    return "未设置";
  }
  return PRIORITY_LABELS[priority] ?? priority;
}

function labelAuditStage(stage: string) {
  return AUDIT_STAGE_LABELS[stage] ?? stage;
}

function labelAuditAction(action: string) {
  return AUDIT_ACTION_LABELS[action] ?? action;
}

function labelAuditActor(actor: string) {
  return AUDIT_ACTOR_LABELS[actor] ?? actor;
}

function labelEntityType(entityType: string) {
  return ENTITY_TYPE_LABELS[entityType] ?? entityType;
}

function labelReviewEffectiveness(effectiveness: string) {
  return REVIEW_EFFECTIVENESS_LABELS[effectiveness] ?? effectiveness;
}

function labelResidualRisk(residualRisk: string) {
  return RESIDUAL_RISK_LABELS[residualRisk] ?? residualRisk;
}

function getLoopFocusStage(counts: Record<LoopStageKey, number>, replayStatus?: string | null): LoopStageKey {
  if (counts.PendingApproval > 0) {
    return "PendingApproval";
  }
  if (counts.Approved > 0) {
    return "Approved";
  }
  if (counts.Dispatched > 0) {
    return "Dispatched";
  }
  if (counts.Executed > 0) {
    return "Executed";
  }
  if (counts.Reviewed > 0) {
    return "Reviewed";
  }
  if (counts.Rejected > 0) {
    return "Rejected";
  }
  if (counts.Alerted > 0) {
    return "Alerted";
  }
  if (counts.Closed > 0) {
    return "Closed";
  }
  if (counts.Assessed > 0) {
    return "Assessed";
  }
  if (replayStatus === "running" || counts.Observed > 0) {
    return "Observed";
  }
  return "Observed";
}

function formatScenarioName(name: string) {
  return SCENARIO_LABELS[name] ?? name;
}

function getProgressPercent(current: number, total: number) {
  if (!total) {
    return 0;
  }
  return Math.max(0, Math.min(100, (current / total) * 100));
}

function getDisplayedRoleStep(replayStatus?: ReplayState | null) {
  if (!replayStatus) {
    return 0;
  }
  return Math.max(replayStatus.completed_role_steps, replayStatus.current_role_step);
}

function getDisplayedBatchStep(replayStatus?: ReplayState | null) {
  if (!replayStatus) {
    return 0;
  }
  return replayStatus.status === "running"
    ? Math.max(replayStatus.current_batch, replayStatus.progress)
    : replayStatus.progress;
}

function formatTime(value: string) {
  return new Date(value).toLocaleString("zh-CN", {
    hour12: false,
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

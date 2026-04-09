# OpenClaw 接入说明

## 目标

在不改变当前模拟数据闭环演示模式的前提下，把本项目接入 OpenClaw，使其具备更明显的 Agent 交互能力。

当前方案采用：

- 本项目后端继续负责风险判定、告警状态机、工单闭环和审计
- OpenClaw 作为上层 Agent 网关
- 通过本仓库内的 `rockburst-ops` 插件，把业务能力暴露成 Agent Tools
- 通过插件内 Skill，告诉 Agent 怎样按安全顺序使用这些工具

## 插件位置

- [plugins/openclaw-rockburst-ops](C:/Users/17196/Desktop/应用于岩爆的多智能体协作系统/plugins/openclaw-rockburst-ops)

## 已封装的工具

只读工具：

- `rockburst_agent_briefing`
- `rockburst_command_snapshot`
- `rockburst_list_replay_scenarios`
- `rockburst_get_rules`
- `rockburst_list_alerts`
- `rockburst_list_work_orders`

写操作工具：

- `rockburst_start_replay`
- `rockburst_stop_replay`
- `rockburst_decide_alert`
- `rockburst_dispatch_work_order`
- `rockburst_submit_feedback`
- `rockburst_close_loop_review`
- `rockburst_ingest_demo_batch`

## 推荐落地顺序

1. 启动本项目后端
2. 在 OpenClaw 中安装或加载本地插件
3. 先只开放只读工具
4. 确认 Agent 能读到简报和快照后，再逐步开放审批、派工和反馈工具

## 本地安装或加载

本地链接安装：

```bash
openclaw plugins install ./plugins/openclaw-rockburst-ops
openclaw plugins enable rockburst-ops
openclaw gateway restart
```

或者直接用配置加载本地目录：

```json5
{
  plugins: {
    load: {
      paths: ["C:/Users/17196/Desktop/应用于岩爆的多智能体协作系统/plugins/openclaw-rockburst-ops"]
    },
    entries: {
      "rockburst-ops": {
        enabled: true,
        config: {
          baseUrl: "http://127.0.0.1:8000",
          actorName: "OpenClaw 值守 Agent",
          requestTimeoutMs: 15000
        }
      }
    }
  }
}
```

如果采用 `plugins.load.paths` 直接加载插件目录，建议先在插件目录执行一次：

```bash
cd plugins/openclaw-rockburst-ops
npm install
```

## OpenClaw 配置建议

推荐模型：

- `openai/gpt-5.4`

推荐策略：

- 默认先使用 `rockburst_agent_briefing`
- 默认允许只读工具
- 写操作工具按需加入 `tools.allow`
- 审批和派工类动作保留人工确认

## 与现有系统的关系

这次接入不是替换当前后端，而是在其上方增加一个 Agent 操作层：

`OpenClaw Agent -> rockburst-ops tools -> FastAPI backend -> LangGraph workflow + rule engine`

这样做的好处是：

- 保留安全边界
- 保留模拟数据演示能力
- 让系统在交互层看起来更像真正的 Agent
- 后续接入真实数据时，不需要推翻这层工具封装

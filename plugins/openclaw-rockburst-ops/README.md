# OpenClaw Rockburst Ops Plugin

这个插件把当前仓库里的岩爆闭环演示后端包装成 OpenClaw Agent Tools，并额外附带一个面向闭环操作的 Agent Skill。

它不会替换现有的 `FastAPI + LangGraph + 规则引擎` 内核，而是把这些业务能力暴露给 OpenClaw：

- 启动和停止模拟回放
- 读取态势总览、Agent 简报、告警、工单和规则
- 审批或驳回告警
- 派发工单
- 提交执行反馈
- 关闭复核
- 注入一批合成微震事件

## 目录

- `package.json`: OpenClaw 插件入口声明
- `openclaw.plugin.json`: 插件 Manifest、配置 Schema 和工具声明
- `index.js`: 工具实现
- `skills/rockburst-closed-loop-agent/SKILL.md`: 告诉 Agent 如何安全使用这些工具

## 建议使用方式

1. 先启动本项目后端
2. 再把此目录作为本地插件加载到 OpenClaw
3. 在 OpenClaw 里启用 `rockburst-ops`
4. 给 Agent 放开你需要的工具

## 本地加载方式

方式一，直接从当前仓库目录做本地链接安装：

```bash
openclaw plugins install ./plugins/openclaw-rockburst-ops
openclaw plugins enable rockburst-ops
openclaw gateway restart
```

方式二，不安装，直接在 OpenClaw 配置里通过 `plugins.load.paths` 加载当前插件目录：

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

如果你使用 `plugins.load.paths` 直接加载本地目录，建议先在插件目录安装依赖：

```bash
cd plugins/openclaw-rockburst-ops
npm install
```

## 最小配置示例

`~/.openclaw/openclaw.json`

```json5
{
  env: {
    OPENAI_API_KEY: "sk-..."
  },
  agents: {
    defaults: {
      model: { primary: "openai/gpt-5.4" },
      tools: {
        allow: [
          "rockburst-ops",
          "rockburst_agent_briefing",
          "rockburst_command_snapshot",
          "rockburst_start_replay",
          "rockburst_stop_replay",
          "rockburst_decide_alert",
          "rockburst_dispatch_work_order",
          "rockburst_submit_feedback",
          "rockburst_close_loop_review",
          "rockburst_ingest_demo_batch"
        ]
      }
    }
  },
  plugins: {
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

## 推荐对话指令

- “先读取岩爆系统 Agent 简报，再告诉我最优先处理的事项。”
- “再补充读取当前岩爆系统快照。”
- “启动持续增强型风险回放场景。”
- “列出所有待审批告警，并按风险等级排序。”
- “如果存在已批准但未派发的工单，先给我建议派工对象。”
- “给 N-101 注入一批 burst 模式的模拟微震事件。”

## 说明

- 该插件当前仍基于模拟数据或回放数据工作。
- 风险等级判定仍由本项目后端的规则引擎负责，不由 LLM 直接裁决。
- 写操作工具在 OpenClaw 里应按需加入 allowlist，不建议默认全开。

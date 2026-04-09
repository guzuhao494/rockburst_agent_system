# 岩爆预警与防控闭环多智能体系统

一个面向岩爆预警与防控演示场景的本地多智能体系统。它把微震事件回放、风险评估、告警审批、工单派发、执行反馈和复核关环串成一条完整链路，并在此基础上接入 OpenClaw，实现“业务工作流智能体 + 外层操作智能体”的协同。

## 项目亮点

- `FastAPI + LangGraph` 驱动后端闭环工作流
- `React/Vite` 提供可演示的前端指挥台
- `SQLite` 保存告警、工单、反馈、审计与回放状态
- 内置模拟微震场景，可一键 replay
- 已接入 OpenClaw，支持后端 9 个角色的 OpenClaw 决策链

## 系统结构

当前系统包含两层智能体：

1. 业务工作流智能体  
   负责采集接入、数据质检、风险评估、告警解释、处置规划、工单协调、效果验证与监督收尾。
2. OpenClaw 操作智能体  
   负责通过插件工具读取简报、查看状态并执行人工确认后的操作。

核心链路如下：

```text
OpenClaw Agent
  -> rockburst-ops plugin tools
  -> FastAPI backend
  -> LangGraph workflow
  -> SQLite / replay scenarios / audit logs
```

## 快速开始

### 1. 安装依赖

- 后端依赖安装到 `backend/.venv`
- 前端依赖安装到 `frontend/node_modules`

### 2. 一键启动演示环境

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start-demo.ps1
```

如果前端有改动，建议先构建：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start-demo.ps1 -Build
```

启动后默认地址：

- 前端：`http://127.0.0.1:4173`
- 后端文档：`http://127.0.0.1:8000/docs`
- 后端健康检查：`http://127.0.0.1:8000/health`

### 3. 停止或重置

停止：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\stop-demo.ps1
```

重置演示数据：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\reset-demo-data.ps1
```

## OpenClaw 使用方式

本仓库已经内置：

- OpenClaw 插件：[`plugins/openclaw-rockburst-ops`](./plugins/openclaw-rockburst-ops)
- OpenClaw 配置示例：[`openclaw/openclaw.example.json5`](./openclaw/openclaw.example.json5)
- 多角色 workspace：[`openclaw/workflow-agents`](./openclaw/workflow-agents)

推荐使用带代理的 helper 调 OpenClaw：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\openclaw-with-proxy.ps1 agent --local --agent rockburst --message "Call rockburst_agent_briefing and reply with only the briefing headline."
```

更多接入细节见：

- [`docs/OPENCLAW_INTEGRATION.md`](./docs/OPENCLAW_INTEGRATION.md)
- [`docs/OPENCLAW_TIMEOUT_TROUBLESHOOTING.md`](./docs/OPENCLAW_TIMEOUT_TROUBLESHOOTING.md)

## 目录结构

```text
backend/
  app/                  FastAPI、LangGraph、规则引擎、数据库逻辑
  configs/              风险阈值、权重、工单模板配置
  data/scenarios/       模拟回放场景
  tests/                后端测试
frontend/
  src/                  React/Vite 前端
plugins/
  openclaw-rockburst-ops/   OpenClaw 插件
openclaw/
  workflow-agents/      OpenClaw 角色工作区
scripts/
  start-demo.ps1
  stop-demo.ps1
  diagnose-openclaw.ps1
docs/
  OPENCLAW_INTEGRATION.md
```

## 后端核心接口

- `POST /ingest/microseismic-events`
- `POST /replay/start`
- `POST /replay/stop`
- `GET /replay/status`
- `GET /replay/scenarios`
- `GET /risk/current`
- `GET /alerts`
- `GET /work-orders`
- `GET /dashboard/summary`
- `GET /agent/briefing`
- `POST /alerts/{id}/approve`
- `POST /alerts/{id}/reject`
- `POST /work-orders/{id}/dispatch`
- `POST /work-orders/{id}/feedback`
- `POST /loop-reviews/{id}/close`

## 开发与测试

后端测试：

```powershell
wsl -e bash -lc 'cd "/mnt/c/Users/17196/Desktop/应用于岩爆的多智能体协作系统/backend" && . .venv/bin/activate && python -m pytest tests -q'
```

前端构建：

```powershell
cd C:\Users\17196\Desktop\应用于岩爆的多智能体协作系统\frontend
npm run build
```

协作分支规范见：

- [`CONTRIBUTING.md`](./CONTRIBUTING.md)

## 当前边界

- 当前仍以模拟微震数据和历史回放场景为主
- 风险等级由规则引擎裁决，不由 LLM 直接决定
- 写操作默认保持人工确认优先
- 完整 OpenClaw 多角色链路已打通，但整体耗时明显高于纯 Python 工作流
- 还没有接入真实生产设备和真实监测数据源

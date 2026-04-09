# 岩爆预警与防控闭环多智能体 MVP

这是一个面向岩爆预警与防控的本地单机演示系统，当前采用：

- `React/Vite` 前端指挥台
- `FastAPI` 后端 API
- `LangGraph` 多 Agent 编排
- `SQLite` 持久化
- 模拟微震数据、历史回放场景和闭环工单流程

当前版本已经支持两层能力：

1. 业务闭环内核  
   微震事件接入、数据质检、风险评分、告警、审批、派工、执行反馈、复核和关环
2. Agent 操作层  
   通过 OpenClaw 插件把系统能力暴露成 Agent Tools，并提供一套面向闭环操作的 Skill

## 主要目录

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
  openclaw.example.json5    OpenClaw 本地配置示例
scripts/
  start-demo.ps1
  stop-demo.ps1
  reset-demo-data.ps1
  install-openclaw-plugin.ps1
docs/
  OPENCLAW_INTEGRATION.md
```

## 一键演示

前提条件：

- 已安装后端依赖到 `backend/.venv`
- 已安装前端依赖到 `frontend/node_modules`

启动整套演示环境：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start-demo.ps1
```

如果你改过前端代码，建议先构建：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start-demo.ps1 -Build
```

停止演示环境：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\stop-demo.ps1
```

重置演示数据：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\reset-demo-data.ps1
```

默认访问地址：

- 前端指挥台：`http://127.0.0.1:4173`
- 后端文档：`http://127.0.0.1:8000/docs`
- 后端健康检查：`http://127.0.0.1:8000/health`

## 手动启动

### 后端

Windows 下推荐直接用 WSL 启动：

```powershell
wsl -e bash -lc 'cd "/mnt/c/Users/17196/Desktop/应用于岩爆的多智能体协作系统/backend" && . .venv/bin/activate && uvicorn app.main:app --host 127.0.0.1 --port 8000'
```

### 前端

预览模式：

```powershell
cd C:\Users\17196\Desktop\应用于岩爆的多智能体协作系统\frontend
npm run preview -- --host 127.0.0.1 --port 4173
```

开发模式：

```powershell
cd C:\Users\17196\Desktop\应用于岩爆的多智能体协作系统\frontend
npm run dev -- --host 127.0.0.1 --port 5173
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

## 当前多 Agent 结构

当前后端已经不是简单页面驱动，而是显式的 Agent + Tool 协作：

- Intake Agent
- Quality Agent
- Risk Assessment Agent
- Alert Explanation Agent
- Action Planning Agent
- Work Order Coordination Agent
- Effectiveness Verification Agent
- Supervisor Agent

并且工具调用会进入审计链，前端时间线可以看到 `tool_completed` 记录。

## OpenClaw 接入

本仓库已经内置 OpenClaw 插件：

- [openclaw-rockburst-ops](C:/Users/17196/Desktop/应用于岩爆的多智能体协作系统/plugins/openclaw-rockburst-ops)

完整接入说明见：

- [OPENCLAW_INTEGRATION.md](C:/Users/17196/Desktop/应用于岩爆的多智能体协作系统/docs/OPENCLAW_INTEGRATION.md)

OpenClaw 本地配置示例见：

- [openclaw.example.json5](C:/Users/17196/Desktop/应用于岩爆的多智能体协作系统/openclaw/openclaw.example.json5)

安装辅助脚本：

- [install-openclaw-plugin.ps1](C:/Users/17196/Desktop/应用于岩爆的多智能体协作系统/scripts/install-openclaw-plugin.ps1)

## 测试与构建

后端测试：

```powershell
wsl -e bash -lc 'cd "/mnt/c/Users/17196/Desktop/应用于岩爆的多智能体协作系统/backend" && . .venv/bin/activate && python -m pytest tests -q'
```

前端构建：

```powershell
cd C:\Users\17196\Desktop\应用于岩爆的多智能体协作系统\frontend
npm run build
```

## 当前边界

- 当前仍以模拟微震数据和回放数据为主
- 风险等级仍由规则引擎裁决，而不是由 LLM 直接决定
- 写操作保持人工确认优先
- 还没有接入真实生产设备和真实监测数据源

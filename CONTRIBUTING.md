# Contributing

## 分支规范

默认分支为 `main`，用于保存当前稳定、可演示的版本。

日常开发不要直接在 `main` 上改，建议按下面规则开分支：

- `feat/<topic>`：新功能
- `fix/<topic>`：缺陷修复
- `docs/<topic>`：文档改动
- `chore/<topic>`：脚本、配置、依赖维护
- `exp/<topic>`：实验性改动或性能试验

示例：

- `feat/openclaw-review-flow`
- `fix/replay-failed-status`
- `docs/readme-refresh`

## 提交流程

1. 从 `main` 拉出新分支
2. 完成单一主题改动
3. 本地验证关键命令
4. 提交后推送到远程
5. 通过 Pull Request 合回 `main`

## 提交建议

推荐每次提交只做一类改动，提交信息尽量短而明确，例如：

- `feat: add openclaw workflow agent sync script`
- `fix: surface replay failure state in frontend`
- `docs: rewrite github landing readme`

## 合并前检查

至少确认以下内容：

- 后端测试能运行
- 前端构建通过
- 变更没有把运行态文件带进 Git
- 如果涉及 OpenClaw，确认 `start-demo.ps1` 和 `openclaw-with-proxy.ps1` 仍可工作

## 当前约定

- `main` 保持“可启动、可演示、可推送”
- 大改动优先走分支和 PR
- 与 OpenClaw workspace 相关的运行态文件不要提交

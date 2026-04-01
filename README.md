# Agent Deliberation System

一个工作空间驱动的统一讨论平台。

## 目标

- 一个会话对应一个独立工作空间
- 你、Codex、ClaudeCode 围绕同一份上下文讨论
- 页面负责推进发言顺序
- 运行过程完整记录到 `events.jsonl`
- 对话消息以数据库为准，不再依赖 `discussion.md`

## 默认模板位置

可直接修改这里的默认模板，后续新建 workspace 会使用它们：

- [defaults/AGENTS.md](/Users/item_admin/workspace/project/agent-deliberation-system/defaults/AGENTS.md)
- [defaults/CLAUDE.md](/Users/item_admin/workspace/project/agent-deliberation-system/defaults/CLAUDE.md)

模板中的 `{{WORKSPACE_ROOT}}` 会在创建 topic 工作空间时自动替换成实际路径。

## 目录

- [README.md](/Users/item_admin/workspace/project/agent-deliberation-system/README.md)
- [DESIGN.md](/Users/item_admin/workspace/project/agent-deliberation-system/DESIGN.md)
- [defaults](/Users/item_admin/workspace/project/agent-deliberation-system/defaults)
- [topics](/Users/item_admin/workspace/project/agent-deliberation-system/topics)
- [app/main.py](/Users/item_admin/workspace/project/agent-deliberation-system/app/main.py)

## 运行

```bash
cd /Users/item_admin/workspace/project/agent-deliberation-system
uvicorn run:app --host 127.0.0.1 --port 8765
```

浏览器打开：

```text
http://127.0.0.1:8765
```

## 当前工作空间文件

每个 topic 工作空间下会有：

- `AGENTS.md`
- `CLAUDE.md`
- `events.jsonl`
- `artifacts/`

数据库负责：

- 对话消息
- topic 状态
- agent session 状态

## 说明

- agent 启动时会显式指定工作目录
- prompt 只传该 agent 尚未读过的新消息
- `discussion.md`、`state.json`、`sessions.json`、`config.json` 已不再作为当前主设计

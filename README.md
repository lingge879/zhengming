# Agent Deliberation System

一个面向多方讨论的本地工作台。

## 现在的主设计

- 每个会话对应一个独立工作空间
- 对话消息、topic 状态、agent session 状态全部以 SQLite 为准
- 工作空间目录只保留共享上下文文件，例如 `AGENTS.md`、`CLAUDE.md`、`artifacts/`
- agent 每次启动时都会显式指定当前工作空间目录
- 每次喂给 agent 的消息，只包含它“还没有读过的新消息”
- 运行原始事件统一写入系统日志，不再写 `discussion.md`、`sessions.json`、`config.json` 这类中间文件

## 目录约定

新会话工作空间默认创建在：

- [workspaces](/Users/item_admin/workspace/project/agent-deliberation-system/workspaces)

兼容历史遗留目录：

- [topics](/Users/item_admin/workspace/project/agent-deliberation-system/topics)

默认 agent 模板在：

- [defaults/AGENTS.md](/Users/item_admin/workspace/project/agent-deliberation-system/defaults/AGENTS.md)
- [defaults/CLAUDE.md](/Users/item_admin/workspace/project/agent-deliberation-system/defaults/CLAUDE.md)

系统日志默认写到：

- [data/system.log](/Users/item_admin/workspace/project/agent-deliberation-system/data/system.log)

## 运行

```bash
cd /Users/item_admin/workspace/project/agent-deliberation-system
uvicorn run:app --host 127.0.0.1 --port 8765
```

浏览器打开：

```text
http://127.0.0.1:8765
```

## 工作空间内容

每个工作空间下默认只有这些共享文件：

- `AGENTS.md`
- `CLAUDE.md`
- `artifacts/`

这两个文档是默认人设和工作约束模板；你可以直接改模板，也可以改单个工作空间中的副本。

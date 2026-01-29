# Agent (backend/agent)

seclens Agent 负责**会话与任务编排**：识别场景、构建提示词、发现/选择工具、委派子任务并汇总结果。

---

## 架构概览

三层结构（KV-cache 友好 + 主上下文干净）：

```
Layer 1: Main Agent (Strategist)
  - 只做规划/决策/复盘（不直接跑工具）
  - 通过 Sub-Agent 执行具体操作

Layer 2: Sub-Agent (Executor)
  - 执行任务（工具调用、重试、解析输出）
  - 返回 Summary（过滤噪音）

Layer 3: Tools
  - MCP 工具（Engine 提供）+ Agent 内置工具
```

---

## 关键目录（与代码一致）

```
agent/
├── core/           # 入口与核心配置（main/server/config/constants/knowledge）
├── infra/          # LLM/Docker/工具注册表/运行时上下文等
├── tools/          # Agent 内置工具（builtin/core/awares/ctf/valid_tools）
├── storage/        # 会话、容器绑定、记忆、PostgreSQL 持久化等
├── prompts/        # Prompt registry + 场景/工具 prompts（md）
├── models/         # SessionContext、TodoPanel、TraceLogger 等
├── observability/  # Langfuse / Rich Console
├── logs/           # JSONL 调试日志 + viewer_tree.html
└── utils/
```

---

## 启动方式

在 `backend/` 目录执行：

### CLI（交互式）

```bash
cd backend
uv run python -m agent.main
```

### Server（HTTP/WebSocket）

推荐方式（前端启动）：

```bash
cd backend
uv run python agent/run_server.py
```

或者直接运行 server 模块：

```bash
cd backend
uv run python -m agent.server
```

---

## Prompt 与日志

- Prompt 说明：`backend/agent/prompts/README.md`（简要）
  完整文档：`docs/backend/agent/prompts/README.md`
- 日志查看器：`backend/agent/logs/README.md`（打开 `viewer_tree.html`）

---

## 测试

```bash
cd backend
make test
```

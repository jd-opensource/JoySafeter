# Copilot 重构实施计划

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 消除 Copilot 模块中的死代码与职责混杂，拆出对话历史与异步持久化逻辑，拆分 DeepAgents manager 单文件，收口 API 序列化与类型约定，使前后端 Copilot 逻辑更内聚、可测、可维护。

**Architecture:** 分阶段重构：先做低风险清理与抽方法（死代码删除、mode 默认修正、异步任务内拆 _persist_conversation / _persist_graph_from_actions），再按需拆 CopilotService 的「对话历史」职责与 DeepAgents 的 prompt/runner，最后收口 API 序列化与前端类型约定。每阶段保持现有行为不变，通过既有测试与契约测试保障。

**Tech Stack:**
- Backend: FastAPI, Pydantic, Redis, SQLAlchemy, LangChain/DeepAgents
- Frontend: React, ReactFlow, TanStack Query, WebSocket

---

## 文件结构变更总览

### 将创建

- `backend/app/core/copilot_deepagents/prompts.py` — Manager 与子代理的 prompt 常量（从 manager.py 迁出）
- `backend/app/core/copilot_deepagents/runner.py` — `run_copilot_manager`、`stream_copilot_manager` 及流式循环（从 manager.py 迁出）
- `backend/app/repositories/copilot_chat_repository.py`（可选 Phase 3）— 对话历史 CRUD，供 Service 调用

### 将修改

- `backend/app/services/copilot_service.py` — 删除 `_process_actions`；修正 `generate_actions_async` 的 mode 默认；拆出 `_persist_conversation`、`_persist_graph_from_actions`；可选改为调用 CopilotChatRepository
- `backend/app/core/copilot_deepagents/manager.py` — 删除已迁出的 prompt 与 runner 代码，改为从 prompts/runner 导入
- `backend/app/core/copilot_deepagents/__init__.py` — 导出 runner 中的 run/stream 函数（若有对外引用）
- `backend/app/api/v1/graphs.py` — Copilot 历史接口改为调用 service 的序列化方法（或 Pydantic response）
- `frontend/app/workspace/[workspaceId]/[agentId]/hooks/useCopilotState.ts` — 依赖数组与注释整理，可选用 ref 稳定 actions
- `frontend/types/copilot.ts`、`frontend/lib/copilot/types.ts` — 顶部注释明确「领域类型」与「UI 类型」分工

### 测试与文档

- 已有 `backend/tests/core/copilot/test_action_applier.py`、`frontend/utils/copilot/__tests__/actionProcessor.contract.test.ts` 与 `docs/schemas/copilot-apply-fixtures.json`，重构前后均需保持通过
- `docs/schemas/README.md` 或 `frontend/app/workspace/.../docs/COPILOT_ARCHITECTURE.md` — 补充类型与 API 约定说明

---

## Phase 1：死代码与默认值修正（低风险）

### Task 1.1：删除 CopilotService._process_actions

**Files:** Modify: `backend/app/services/copilot_service.py`

- [ ] **Step 1:** 确认无引用 — 全文搜索 `_process_actions`，确认仅定义无调用。
- [ ] **Step 2:** 删除 `_process_actions` 方法整体（约 538–636 行，含 docstring 与实现）。
- [ ] **Step 3:** 运行 `pytest backend/tests/core/copilot/test_action_applier.py -v`，确认通过。

### Task 1.2：统一 generate_actions_async 的 mode 默认值

**Files:** Modify: `backend/app/services/copilot_service.py`

- [ ] **Step 1:** 将 `generate_actions_async(..., mode: str = "standard",)` 改为 `mode: str = "deepagents"`，与 CopilotRequest 默认一致。
- [ ] **Step 2:** 运行 Copilot 相关单测或手动验证 create task 仍按 payload.mode 工作。

---

## Phase 2：异步任务内拆「存对话」与「存图」

### Task 2.1：抽出 _persist_conversation

**Files:** Modify: `backend/app/services/copilot_service.py`

- [ ] **Step 1:** 在 `# ==================== Async Task Generation ====================` 之前新增私有方法 `_persist_conversation(self, session_id: str, graph_id: str, prompt: str, final_message: str, collected_thought_steps: List[Dict], collected_tool_calls: List[Dict], final_actions: List[Dict]) -> bool`：内联当前「事务 1」逻辑（async_session_factory、CopilotService(user_id, db=new_db)、save_conversation_from_stream、commit/rollback、logging），返回是否成功。
- [ ] **Step 2:** 在 `generate_actions_async` 的 `if graph_id:` 中，将原「事务 1」整块替换为 `await self._persist_conversation(session_id, graph_id, prompt, final_message, collected_thought_steps, collected_tool_calls, final_actions)`。
- [ ] **Step 3:** 运行 `pytest backend/tests/core/copilot/ -v` 与现有集成/手动验证，确认行为不变。

### Task 2.2：抽出 _persist_graph_from_actions

**Files:** Modify: `backend/app/services/copilot_service.py`

- [ ] **Step 1:** 新增私有方法 `_persist_graph_from_actions(self, graph_id: str, final_actions: List[Dict[str, Any]]) -> bool`：内联当前「事务 2」逻辑（new_db2、AuthUserRepository、GraphService、load_graph_state、apply_actions_to_graph_state、save_graph_state、commit/rollback、logging），返回是否成功。
- [ ] **Step 2:** 在 `generate_actions_async` 中，将原「事务 2」整块（`if final_actions and len(final_actions) > 0:` 下）替换为 `if final_actions: await self._persist_graph_from_actions(graph_id, final_actions)`。
- [ ] **Step 3:** 再次运行测试与手动验证，确认对话与图持久化均正常。

---

## Phase 3（可选）：对话历史职责独立

若希望 CopilotService 只做「流编排 + 对外 API」，可将历史 CRUD 迁出。

### Task 3.1：新增 CopilotChatRepository

**Files:** Create: `backend/app/repositories/copilot_chat_repository.py`；Modify: `backend/app/services/copilot_service.py`

- [ ] **Step 1:** 创建 `CopilotChatRepository`，接受 `db: AsyncSession`，提供 `get_by_graph_and_user`、`append_messages`、`create_or_append`、`delete_by_graph_and_user`（或与现有 get_history/save_messages/clear_history 语义一致的方法），从 CopilotService 中搬入与 CopilotChat 表交互的 SQL 与序列化逻辑。
- [ ] **Step 2:** CopilotService 的 `get_history`、`save_messages`、`save_conversation_from_stream`、`clear_history` 改为调用 repository；保留「构建 CopilotMessage 等」在 service 或 repository 其一，避免重复。
- [ ] **Step 3:** `_persist_conversation` 内部改为使用 repository（或通过 service 调 repository），运行测试确保历史读写与异步任务保存对话均正常。

---

## Phase 4：DeepAgents manager.py 拆分

### Task 4.1：迁出 prompt 常量

**Files:** Create: `backend/app/core/copilot_deepagents/prompts.py`；Modify: `backend/app/core/copilot_deepagents/manager.py`

- [ ] **Step 1:** 在 `copilot_deepagents/prompts.py` 中定义 `MANAGER_SYSTEM_PROMPT`、`REQUIREMENTS_ANALYST_PROMPT`、`WORKFLOW_ARCHITECT_PROMPT`、`VALIDATOR_PROMPT`（及当前在 manager.py 中的其它长字符串常量）。
- [ ] **Step 2:** 在 `manager.py` 中删除上述常量，改为 `from .prompts import MANAGER_SYSTEM_PROMPT, ...`；运行 `pytest backend/tests/` 与 DeepAgents 相关路径（若有），确认无回归。

### Task 4.2：迁出 run_copilot_manager 与 stream_copilot_manager

**Files:** Create: `backend/app/core/copilot_deepagents/runner.py`；Modify: `backend/app/core/copilot_deepagents/manager.py`、`backend/app/core/copilot_deepagents/__init__.py`

- [ ] **Step 1:** 在 `runner.py` 中实现 `run_copilot_manager` 与 `stream_copilot_manager`（从 manager.py 复制实现），依赖 `create_copilot_manager`、`safe_read_blueprint`、`read_and_layout_blueprint`、`_extract_actions_from_result` 等仍从 manager 或 artifacts/layout 导入。
- [ ] **Step 2:** 在 `manager.py` 中删除 `run_copilot_manager` 与 `stream_copilot_manager` 的实现，改为 `from .runner import run_copilot_manager, stream_copilot_manager` 并 re-export（或仅保留 create_copilot_manager 及 schema/artifact 辅助函数）。
- [ ] **Step 3:** 更新 `copilot_deepagents/__init__.py`，使对外仍能 `from app.core.copilot_deepagents import run_copilot_manager, stream_copilot_manager`（若现有代码如此引用）。运行 streaming 与 non-streaming 调用路径，确认行为一致。

---

## Phase 5：前端 useCopilotState 与类型约定

### Task 5.1：依赖数组与注释整理

**Files:** Modify: `frontend/app/workspace/[workspaceId]/[agentId]/hooks/useCopilotState.ts`

- [ ] **Step 1:** 在 `useCopilotState` 顶部增加注释：说明 state/actions/refs 的聚合关系及「子 hook 方法引用变化会导致 actions useMemo 重算」。
- [ ] **Step 2:** 检查 `actions` 的 useMemo 依赖数组是否与展开的 `messagesHook`/`streamingHook`/`actionExecutorHook`/`sessionHook` 的每个方法一一对应，去掉重复或多余依赖，保证与当前行为一致。
- [ ] **Step 3:** 运行 `npm run test` 与 `npm run type-check`，确认无报错；若有 Copilot 相关单测则一并运行。

### Task 5.2：类型与命名约定文档

**Files:** Modify: `frontend/types/copilot.ts`、`frontend/lib/copilot/types.ts`、`frontend/app/workspace/.../docs/COPILOT_ARCHITECTURE.md`（或 `docs/schemas/README.md`）

- [ ] **Step 1:** 在 `types/copilot.ts` 顶部注释中写明：本文件为与后端/契约一致的「领域类型」；UI 展示用类型（如 ToolCallState）见 `lib/copilot/types.ts`。
- [ ] **Step 2:** 在 `lib/copilot/types.ts` 顶部注释中写明：本文件为 Copilot UI 展示与工具调用状态类型，与 API 契约无关。
- [ ] **Step 3:** 在 COPILOT_ARCHITECTURE 或 docs/schemas/README 中增加简短小节「类型与命名约定」，指向上述两处及 `docs/schemas/copilot-contract.json`。

---

## Phase 6：API 层序列化收口

### Task 6.1：历史接口序列化收口到 Service

**Files:** Modify: `backend/app/services/copilot_service.py`、`backend/app/api/v1/graphs.py`

- [ ] **Step 1:** 在 CopilotService 中新增 `get_history_for_api(self, graph_id: str) -> dict`（或返回 Pydantic model）：内部调用 `get_history`，将 `CopilotMessage` 转为前端期望的 dict 结构（id, role, content, created_at, actions, thought_steps, tool_calls），返回 `{ "success": True, "data": { "graph_id", "messages", "created_at", "updated_at" } }` 或等价结构。
- [ ] **Step 2:** `get_copilot_history` 路由中改为调用 `service.get_history_for_api(graph_id)` 并直接 return 其返回值，删除路由内手写序列化。
- [ ] **Step 3:** 运行 API 测试或手动请求 `GET /graphs/{id}/copilot/history`，确认响应格式与前端兼容。

### Task 6.2（可选）：Copilot 路由迁出 graphs.py

**Files:** Create: `backend/app/api/v1/copilot.py`（或 `backend/app/routers/copilot.py`）；Modify: `backend/app/api/v1/graphs.py`、`backend/app/main.py`（或路由注册处）

- [ ] **Step 1:** 新建路由模块，将 `get_copilot_history`、`clear_copilot_history`、`save_copilot_messages`、`generate_graph_actions`、`create_copilot_task`、`get_copilot_session` 从 graphs.py 迁入，路径前缀保持与现有一致（如 `/graphs/{graph_id}/copilot/history`、`/copilot/actions/create` 等）。
- [ ] **Step 2:** 在 main 或 app 中注册新 router，从 graphs 中删除已迁出的 Copilot 端点。
- [ ] **Step 3:** 运行全量 API 测试与前端联调，确认 Copilot 功能正常。

---

## 验收与回滚

- 每完成一个 Phase，运行：`pytest backend/tests/core/copilot/ -v`、`pytest backend/tests/`（或项目约定范围）、前端 `npm run test` 与 `npm run type-check`；Apply 契约测试必须保持通过。
- 若某 Phase 引入问题，可单独回滚该 Phase 的提交；Phase 1–2 为必做，Phase 3–6 可按需选做或分多次迭代完成。

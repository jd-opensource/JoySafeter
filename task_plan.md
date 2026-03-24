# Task Plan: WS Chat Unification

## Goal
基于 `docs/superpowers/specs/2026-03-24-ws-chat-unification-design.md` 完成可执行规划，并将 Chat、Skill Creator、workspace execution 从 SSE/HTTP 流式迁移到持久化 WebSocket，移除公共 `/v1/chat*` API 暴露。

## Current Phase
Phase 5

## Phases

### Phase 1: Requirements & Discovery
- [x] 阅读设计文档并确认迁移边界
- [x] 审查当前后端 `/v1/chat` 与 websocket 实现
- [x] 审查当前前端 ChatProvider、SSE hook 和调用点
- [x] 记录发现与约束
- **Status:** complete

### Phase 2: Planning & Structure
- [x] 形成实施批次与依赖顺序
- [x] 确认需要保留的 HTTP 端点与需要删除的 legacy WS
- [x] 创建实现计划文档
- **Status:** complete

### Phase 3: Backend Implementation
- [x] 复用现有 chat 流式辅助函数接入 WS handler
- [x] 新增 `backend/app/websocket/chat_ws_handler.py`
- [x] 在 `backend/app/main.py` 注册 `WS /ws/chat`
- [x] 删除 legacy `chat_handler.py` 与 `connection_manager.py` 的引用与文件
- **Status:** complete

### Phase 4: Frontend Implementation
- [x] 新增 `frontend/app/chat/hooks/useChatWebSocket.ts`
- [x] 扩展 `ChatProvider` streaming context 持有 WS 能力
- [x] 将 `ChatLayout` 切换到 context 中的 WS 能力
- [x] 删除 Chat 页 `useBackendChatStream` 旧 SSE 用法
- [x] 将 `Skill Creator` 与 workspace execution 也切到 WS
- [x] 删除前端 `streamChat()` 实现
- **Status:** complete

### Phase 5: Verification & Delivery
- [x] 运行前端类型检查并区分新增问题与仓库既有问题
- [x] 运行后端最小编译验证
- [x] 更新 `findings.md` 与 `progress.md`
- [x] 总结结果与剩余风险
- **Status:** complete

## Key Questions
1. 如何最大化复用 `backend/app/api/v1/chat.py` 里的事件分发与持久化逻辑，避免 WS/SSE 行为漂移？
2. Chat 页切 WS 后，哪些 HTTP 端点仍需保留以避免影响 workspace builder？

## Decisions Made
| Decision | Rationale |
|----------|-----------|
| 初版按“仅迁移 Chat 页，暂留 `POST /v1/chat/stop` 与 `POST /v1/chat/resume`”起步 | 先降低切换风险，再视调用点收敛情况决定是否继续扩展 |
| 通过抽取后端共享 helper 复用现有 `_dispatch_stream_event`、持久化与 graph 构建逻辑 | 降低 SSE/WS 双实现分叉风险 |
| `ChatProvider` 持有单条持久化 WS 连接 | 符合设计文档要求，线程切换/模式切换时连接不重建 |
| 直接移除后端 `/v1/chat` 公共兼容 API | 用户已明确要求把公共 API 也重构掉，且仓库内业务代码已无调用 |
| 将 Skill Creator 与 workspace execution 一并迁到 `WS /ws/chat` | 这样可以真正删除 `/v1/chat/stream`、`/v1/chat/stop`、`/v1/chat/resume`，避免长期双轨维护 |

## Errors Encountered
| Error | Attempt | Resolution |
|-------|---------|------------|
| `backend/app/api/chat.py` 路径不存在 | 1 | 确认实际文件为 `backend/app/api/v1/chat.py` |
| `chat_ws_handler.py` 缩进错误导致 `py_compile` 失败 | 1 | 修正 `_cancel_all_tasks()` 中的 `try/except` 缩进后重新验证 |

## Notes
- 当前 worktree 已存在与本任务无关的删除改动，不能回退。
- 当前后续工作重点是文档与记录同步；代码侧迁移与路由下线已完成。

# Findings

## 2026-03-24

- Chat 流式后端实际位于 `backend/app/api/v1/chat.py`，其中 `_dispatch_stream_event()`、`save_run_result()`、`get_or_create_conversation()`、`get_user_config()` 等都可被 WS 复用。
- 初始排查时，`POST /v1/chat/stream` 是 Chat 页使用的 SSE 入口；`POST /v1/chat/stop` 与 `POST /v1/chat/resume` 也曾被 workspace builder 侧依赖。
- `backend/app/websocket/chat_handler.py` 与 `backend/app/websocket/connection_manager.py` 对应的是旧 `WS /ws/{session_id}` 会话聊天能力，和现有 Chat 页无调用关系，符合删除条件。
- 前端 Chat 页当前在 `frontend/app/chat/ChatLayout.tsx` 里直接调用 `useBackendChatStream(dispatch)`，说明迁移时应把连接提升到 `ChatProvider.tsx`，否则无法满足“整个 chat 子树共享同一 WS”。
- 现有通知与 copilot websocket 都自带重连/心跳模式，可直接复用其连接管理思路到 chat websocket。
- `docs/superpowers/specs/2026-03-24-ws-chat-unification-design.md` 中“`POST /v1/chat/stream` 仅 Chat 页使用”的前提与当前仓库不一致；至少 `frontend/app/skills/creator/page.tsx` 和 `frontend/app/workspace/[workspaceId]/[agentId]/stores/execution/executionStore.ts` 仍依赖 `streamChat()`.
- 本次实现先采用“Chat 页切 WS、其他调用点暂保留 HTTP/SSE”的过渡策略，随后继续把 Skill Creator 与 workspace execution 也切到同一 `WS /ws/chat` 协议。
- 目前前端仓库内已没有 `streamChat()`、`chat/stream`、`chat/stop`、`chat/resume` 的业务调用，剩余仅是文档注释示例。
- 后端 `chat_router` 已从 `backend/app/api/v1/__init__.py` 移除，`backend/app/api/v1/chat.py` 仅保留共享 helper，不再向外注册 `/v1/chat` HTTP 路由。
- 额外导入链检查显示，本地 Python 环境缺少 `jose` 依赖，因此无法用 `import app.main` 完成运行时导入验证；这属于环境依赖问题，不是本次 chat API 移除造成的异常。

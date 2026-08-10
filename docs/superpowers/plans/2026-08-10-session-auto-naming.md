# Session 自动命名实施计划

> **目标：** 所有无自定义标题的 Session 在后端创建时获得稳定默认标题，并在 Session 列表、Agent 详情和 Session 详情中一致展示。

## 文件职责

- `backend/app/joysafeter_domain/services/joysafeter_session_service.py`：生成并持久化默认 Session 标题。
- `backend/app/joysafeter_api/api/v1/sessions.py`：将已解析的 Agent 名称传入 Session 服务。
- `backend/app/joysafeter_domain/services/agent_trigger_execution.py`、`backend/app/joysafeter_api/api/v1/tasks.py`：为非 Session API 创建入口提供 Agent 名称。
- `backend/tests/test_session_auto_naming.py`：覆盖默认标题、空白标题与自定义标题。
- `frontend/app/managed/sessions/page.tsx`：旧空标题显示“未命名会话”。
- `frontend/app/managed/agents/[agentId]/page.tsx`：Agent 会话子列表使用相同降级文案。
- `frontend/app/managed/sessions/[sessionId]/page.tsx`：标题优先展示 `session.title`，ID 作为辅助信息。
- 对应前端测试：锁定列表和详情展示规则。

## 实施步骤

1. 先新增后端失败测试，证明无标题和空白标题未自动生成，自定义标题需保留。
2. 在 Session 服务边界增加统一标题规范化，避免不同创建入口各自生成。
3. 更新 API、任务和触发器调用点，传入 Agent 名称。
4. 新增前端失败测试，覆盖旧空标题降级和详情标题优先。
5. 更新三处展示并保留详情页 Session ID。
6. 运行相关前后端测试、类型检查、格式检查和生产构建。
7. 使用 Playwright 验证快捷启动后标题贯穿列表与详情。

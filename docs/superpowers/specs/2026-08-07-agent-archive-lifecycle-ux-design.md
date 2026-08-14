# 智能体归档闭环与操作区重构 — 设计文档

日期：2026-08-07
分支：joysafeter-v2

## 背景与问题

归档智能体是一个**高影响操作**，但当前的 UI 既没有讲清楚后果，操作区本身也不好用：

1. **归档确认提示严重低估后果。** 现文案（`zh.ts` / `en.ts` 的 `managed.agents.archiveDescription`）只说"归档后的智能体无法创建新会话"。实际上 `archive_agent_with_sessions`（`backend/app/joysafeter_domain/services/joysafeter_agent_service.py:439`）在一个事务里：
   - 把该智能体下所有未归档会话设为 `archived_at`、状态改为 `terminated`（终止进行中的会话）；
   - 调用 `pause_for_agent_archive` 清空所有 cron 触发器的 `next_run_at`（暂停定时触发）；
   - 设置 `agent.archived_at`，之后任何更新都被拒绝并返回 `AGENT_ARCHIVED`（配置只读）。
   - 前置拦截：若智能体有活动任务（pending/scheduling/running），归档被拒，返回 `AGENT_ACTIVE_TASKS`。

2. **归档后操作区变成死胡同。** 详情页（`frontend/app/managed/agents/[agentId]/page.tsx:362`）在 `isArchived || projectReadOnly` 时 `menuItems = []`，Edit 按钮也 disable。归档的智能体既不能删除、也没有恢复入口，用户被卡死。

3. **操作藏在三点菜单里、破坏性与普通操作混杂。** 高频的"启动会话"要点两次；删除（破坏性）和启动会话（普通）挤在同一菜单，仅靠红色区分。

后端现有 endpoint（`backend/app/joysafeter_api/api/v1/agents.py`）：`POST ""`（创建）、`POST /{id}`（更新，归档态被拒）、`DELETE /{id}`（删除，**对归档态智能体同样有效**）、`POST /{id}/archive`（归档）。**没有 unarchive/restore 接口**。

## 目标

闭环提升用户体验：

- 归档变为**可逆**操作（新增恢复能力）；
- 归档确认提示**完整、准确**地说明后果，并说明可恢复；
- 操作区重构为**平铺工具栏**，消除归档死胡同。

## 非目标（YAGNI）

- 不引入归档实时计数预览接口（提示用静态但完整的文案）。
- 不复活已终止的会话（沙箱已销毁）。
- 不做与本目标无关的重构。

## 设计

### 1. 后端 —— 新增"恢复归档"能力

镜像已有的项目恢复模式 `resume_after_project_restore`（`trigger_service.py:535`）。

**1a. 新 trigger 方法** `resume_after_agent_restore(agent_id)`（`backend/app/joysafeter_domain/services/joysafeter_trigger_service.py`）：
- 镜像 `resume_after_project_triggers_unpaused`：**仅在父项目未归档且 `triggers_paused` 为假时**重算。
- 对该 agent 下 `type == "cron"` 且未删除的触发器：清 `locked_by/locked_at/pending_slot_at/slot_attempts`，用 `_next_run_or_pause(trigger)` 重算 `next_run_at`（`enabled=false` 的触发器保持暂停/无 due slot），调用 `_sync_config(trigger)`。
- 调用方拥有事务（不在此方法内 commit）。

**1b. 新 service 方法** `restore_agent(agent_id, project_id=None) -> bool`（`joysafeter_agent_service.py`）：
- `get_agent`；不存在 → 返回 `False`（调用方转 404）。
- `agent.archived_at is None` → 幂等，返回 `True`（无副作用）。
- 清 `agent.archived_at = None`，`agent.updated_at = utc_now()`。
- 调用 `JoySafeterTriggerService(self.db).resume_after_agent_restore(agent_id)`。
- **不**修改已归档/终止的会话。
- `await self.db.commit()`，返回 `True`。

**1c. 新 endpoint** `POST /agents/{agent_id}/unarchive`（`agents.py`），依赖 `require_joysafeter_write`：
- `restored = await svc.restore_agent(agent_id, project_id=auth_ctx.project_id)`。
- `not restored` → `_agent_not_found_error(agent_id)`。
- 返回 `{"status": "active"}`。

### 2. 后端 —— 归档提示信息

保持静态完整文案，**无后端改动**。

### 3. 前端 —— 操作区改为平铺工具栏

改 `frontend/app/managed/agents/[agentId]/page.tsx` 的 `PageHeader` 的 `action` 区（当前是 Edit 按钮 + `ActionMenu`）。

- **正常（未归档、可写）智能体**，按顺序平铺：
  `[▶ 启动会话] [✎ 编辑] [✨ 引导编辑] [归档] [🗑 删除(destructive/红)]`
- **归档智能体**：`[↩ 恢复归档] [🗑 删除(红)]` —— 其余隐藏（配置只读）。
- **项目只读**：所有按钮 disable（沿用现有 `projectReadOnly` 逻辑）。
- 归档、删除、恢复均走现有 `ConfirmDialog`。
- 新增 `handleRestore`，沿用现有 `nextAction()` / `isCurrentAction()` / `managedRequestScopeRef` 的作用域防抖模式；成功后 `invalidateQueries(['agent', ...])`。
- 恢复归档使用**轻量确认弹窗**（非破坏性，`destructive: false`）。
- 删除保持 `destructive: true` 红色样式；平铺暴露的误触风险由确认弹窗兜底。
- 新增 endpoint 路径通过 `apiResourcePath('agents', agentId, 'unarchive')`。

`ActionMenu` 若不再被本页使用则移除其 import；否则保留。会话行内的归档操作（`AgentSessions`）不变。

### 4. 前端 —— 确认提示文案（中英双语）

改 `frontend/lib/i18n/locales/zh.ts` 与 `en.ts`。注意：`archiveDescription` 在这两个文件里各出现两处（顶层 `agents.*` 与嵌套 `managed.agents.*`），需同步。

**归档提示（重写）**
- zh：`归档 "{{name}}" 将：终止其所有进行中的会话、暂停关联的定时触发器、并将配置设为只读。你可以稍后恢复。确定继续吗？`
- en：`Archiving "{{name}}" will: terminate all its running sessions, pause associated cron triggers, and make its configuration read-only. You can restore it later. Continue?`

**恢复提示（新增 `restoreTitle` / `restoreDescription`）**
- `restoreTitle` zh：`恢复智能体` / en：`Restore Agent`
- `restoreDescription` zh：`恢复 "{{name}}" 会将其重新设为可用，并重新计算定时触发器的下次执行时间。已终止的会话不会恢复。`
- en：`Restoring "{{name}}" will make it usable again and recompute the next run time of its cron triggers. Terminated sessions are not restored.`
- 新增 `common.restore`（"恢复" / "Restore"）按钮文案（若不存在）。

### 5. 测试

**后端**（`cd backend && uv run pytest`）：新增或扩展 `backend/tests/test_agent_lifecycle_active_tasks.py`（或新建 `test_agent_restore.py`）：
- 归档→恢复：`agent.archived_at` 归档后非空、恢复后为空；恢复后更新（`POST /{id}`）不再返回 `AGENT_ARCHIVED`。
- 幂等：对未归档智能体调用 unarchive 返回成功且无副作用。
- 触发器：归档清空 `next_run_at`；恢复后 `enabled` 的 cron 触发器 `next_run_at` 被重算为未来时刻，`disabled` 的保持空。
- 父项目归档/暂停时，恢复不重算触发器。
- 终止的会话在恢复后仍为 `terminated`/`archived_at` 非空。
- 404：对不存在的 agent 调用 unarchive。

**前端**：详情页测试（扩展现有测试或新建 `[agentId]/page.test.tsx`）：
- active 态显示全部 5 个按钮；archived 态仅显示 恢复归档 + 删除；project read-only 全部 disable。
- 点击"恢复归档"确认后调用 `POST /agents/{id}/unarchive` 并刷新查询。

## 影响面 / 风险

- 触发器重算逻辑与项目恢复共用 `_next_run_or_pause`，行为一致，风险低。
- 平铺删除按钮误触：由确认弹窗 + 红色样式兜底。
- i18n 文案有重复键，需确保两处同步（顶层 + 嵌套）。

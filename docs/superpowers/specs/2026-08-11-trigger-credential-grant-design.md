# 触发器运行凭据授权设计（Trigger Credential Grant）

## 背景与问题

触发器（`JoySafeterTrigger`）是"cron / webhook / manual 触发就跑一次 agent"的规则。fire 时它经
`TriggerFireService` → `AgentTriggerExecutor.resolve_session`
（`backend/app/joysafeter_domain/services/agent_trigger_execution.py`）创建或复用一个 session 并派发 task。

交互式建 session 时（`create-session-dialog.tsx` → `sessions.py`）会带上 `vault_ids`，运行时
`VaultService.resolve_mcp_credentials`（`joysafeter_vault_service.py`）据此把 MCP 凭据注入沙箱。
但触发器 fire 出来的 session **完全没有 `vault_ids`**——`resolve_session` 建 session 时未传该参数。
因此触发器运行时没有任何 vault 凭据可注入，只能依赖 agent 快照里烘焙的 `agent.secret_ref` / `agent.mcp_servers`。

触发器唯一能配置的"凭据"（`secret_ref` / `secret_key`）仅用于**验证 webhook 入站调用方身份**，
不是给运行中的 agent 干活用的凭据。

结论：触发器运行的授权上下文当前只能在 agent 配置时决定，无法在触发器层面显式授予、审计或撤销。
这正是本设计要解决的缺口。

## 目标

1. 让触发器 fire 出来的 session 能拿到运行凭据（vault），与交互式 session 走同一条运行时授权路径。
2. 这个授权是**显式、可审计、可撤销**的：明确记录谁在何时授予了哪些 vault、谁在何时撤销。
3. 授权在 fire 时校验，失效则 **fail-closed**（不带无效授权继续跑），并复用触发器现有的失败计数 / 自动禁用机制。

## 非目标

- 不给 agent 增加默认 vault 集或 agent 级凭据继承（波及面大，YAGNI）。
- 不改动 webhook 入站验证（`secret_ref` / `secret_key`）的既有语义。
- 不新建平行的重试 / 死信机制；复用触发器现有的 `consecutive_failures` / `auto_disabled_at`。

## 数据模型

新表 `joysafeter_trigger_credential_grants`：

- `id`：主键，遵循仓库 typed entity id 约定。
- `trigger_id`：FK → `joysafeter_triggers`。
- `vault_ids`：JSONB 列表，被授权可用的 vault 集合。
- `granted_by`：授权人 user id。
- `granted_at`：授权时间（UTC）。
- `revoked_by`：撤销人 user id，nullable。
- `revoked_at`：撤销时间（UTC），nullable。
- `project_id` / `org_id`：作用域字段，与其他领域模型一致。

**不变式**：每个触发器至多一条 active grant（`revoked_at IS NULL`）。重新授权 = 撤销当前 active + 插入新行，
保留完整授权历史。

## 凭据绑定判定

fire 时依据"该触发器是否存在过 grant 记录"区分两类触发器：

- **零 grant 记录**（从未授权过）= 旧的 / 无凭据型触发器：照常用空 `vault_ids` 运行，向后兼容，不触发 fail-closed。
- **存在过 grant 记录**（active 或已撤销）= 凭据绑定型触发器：必须有一条**有效 active grant** 才能 fire，
  否则走 fail-closed。

这一判定使得"曾授权、后被撤销"的触发器在再次 fire 时会 fail-closed（停下来要求重新授权），
而不是静默用空凭据继续运行——撤销是一次刻意的安全动作，必须被尊重。

## Grant 生命周期与 API

- **创建触发器**：若表单选择了 vault，则在创建触发器的同一事务内插入一条 active grant。
  校验授权人具备 `require_joysafeter_write`，且每个 vault 属于本项目（复刻 `sessions.py` 中
  vault 归属校验逻辑）。未选 vault 则不建 grant（零 grant 记录）。
- **重新授权** `POST /triggers/{id}/credential-grant`：校验后撤销当前 active grant（置 `revoked_by/at`），
  插入新 active grant。
- **撤销授权** `POST /triggers/{id}/credential-grant/revoke`：给当前 active grant 置 `revoked_by/at`。
  之后该触发器变为"存在 grant 记录但无 active grant"，fire 时 fail-closed。
- 所有变更端点沿用 `require_joysafeter_write` 项目级写权限。

## Fire 时校验（fail-closed）

在 `AgentTriggerExecutor.resolve_session` 创建 session 之前：

1. 判定触发器是否为凭据绑定型（是否存在过 grant 记录）。
2. 凭据绑定型：加载 active grant。若无有效 active grant → fail-closed。
3. 校验 active grant 中每个 vault 仍存在且属于本项目；任一失效 → fail-closed。
4. 校验通过 → 将 `vault_ids=grant.vault_ids` 传入 `create_session(...)`，与交互式 session 一致。
5. 零 grant 记录触发器 → 用空 `vault_ids` 正常运行。

fail-closed 复用现有失败处理：写入 `last_error`（凭据授权失败的专用错误码 / 类型），
`consecutive_failures` 自增，达阈值时置 `auto_disabled_at` 自动禁用触发器。

## 与 session_mode 的交互

授权只在"触发器**新建** session"时生效；vault 在建 session 时落到 session 行上：

- `fresh` / `keyed`（及 `reuse` 首次新建可复用 session）：触发器新建 session → 注入 grant 的 `vault_ids`。
- `pinned`：session 由人工预先建好、已带自己的 `vault_ids` → 使用其自身的，grant **不覆盖**
  （仍校验 pinned session 存活）。
- `reuse` 复用已有 session：保留该 session 已存的 `vault_ids`。

理由：pinned / reuse-existing 的运行授权在人工建 session 时已确定；触发器 grant 只管它自己新建的 session。
凭据绑定判定与 fail-closed 校验仍对所有 session_mode 生效——只是校验通过后，vault 仅注入到触发器新建的 session。

## 前端

- `create-trigger-dialog.tsx` 增加 vault 多选，复用 session 建立对话框所用的同一 vault 选择组件。
- 触发器详情 / 编辑视图展示当前 active grant（授权人、授权时间），并提供"重新授权""撤销授权"操作。
- 触发器状态区在因授权失效而 fail-closed / 自动禁用时，明确提示"授权失效，请重新授权"，区别于普通运行失败。
- i18n（en + zh）术语沿用现有命名（MCP 凭据库 / vault）。

## 错误与边界

- 凭据授权失败使用独立错误码 / 类型，写入 `last_error` 与触发器状态，便于 UI 与排障区分普通失败。
- 撤销后的触发器（无 active grant）fire 一律 fail-closed，直至重新授权。
- grant 中引用的 vault 被删除或移出项目视为失效，fire 时 fail-closed。
- active grant 的唯一性由"重新授权=先撤销后插入"保证；并发下以数据库层约束 / 校验兜底。
- 授权与撤销均要求 `require_joysafeter_write`，与触发器其他变更一致。

## 测试范围

后端（从 `backend/` 运行 `uv run pytest`）：

- Grant 生命周期：创建触发器带 vault → 生成 active grant；重新授权 → 旧 grant 撤销 + 新 active grant；
  撤销 → active grant 置 `revoked_at`。
- Fire 时校验四条分支：
  - 有效 active grant → `vault_ids` 注入到触发器新建的 session。
  - grant 引用的 vault 失效 → fail-closed + `consecutive_failures` 自增。
  - 已撤销（无 active grant，但有历史）→ fail-closed。
  - 零 grant 记录旧触发器 → 空 `vault_ids` 正常运行。
- session_mode 交互：`pinned` / `reuse-existing` 保留 session 自身 vault，grant 不覆盖。
- 达阈自动禁用：连续授权失败累计到阈值 → `auto_disabled_at` 置位。

前端：

- 触发器对话框 vault 多选提交。
- 触发器详情展示当前 grant，重新授权 / 撤销授权动作。
- 授权失效时的状态提示文案（en + zh）。

回归：

- 零 grant 记录的既有触发器行为不变（空 vault 正常 fire）。
- webhook 入站验证（`secret_ref` / `secret_key`）不受影响。

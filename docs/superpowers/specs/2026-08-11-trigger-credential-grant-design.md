# 触发器运行凭据授权设计（Trigger Credential Grant）

> **修订说明（rev3，2026-08-14）**：rev2 完成了 P0 后 `vault_ids` →
> `credential_group_ids` 的术语迁移，但没有闭合撤销语义、`reuse` / `keyed` Session 复用、
> revoke/fire 竞态、Cron `replace` 副作用顺序、读取 API、结构化错误和审计主体。
>
> rev3 作出以下核心裁决：
>
> 1. Trigger Grant 采用 **动态 credential-group 成员集**，与现有 Session 授权一致；不记录用于执行隔离的成员快照。
> 2. Trigger 自动创建的 Session 必须绑定创建它的 **Grant ID**；`reuse` / `keyed` 只复用与当前 active grant 匹配的 Session。
> 3. grant 校验必须先于 Session 创建和 Cron `replace` 取消旧任务；fire/revoke 以 Trigger 行锁下的授权判定为线性化点。
> 4. Trigger 是否要求 grant 使用显式 `credential_policy`，不再依赖“历史 grant 行是否存在”推断安全状态。
> 5. revoke 只保证阻止在其线性化点之后开始的 fire；已经通过授权判定的在途 fire 和已运行 Task 不在本期强制取消。

## 1. 背景与现状

触发器（`JoySafeterTrigger`）是 cron、webhook 或 manual 触发后运行一次 Agent 的规则。执行链为：

`TriggerFireService / SchedulerLoop` → `AgentTriggerExecutor` → `SessionService` → `TaskSubmissionService`。

交互式创建 Session 时，前端提交 `credential_group_ids`，`SessionService.create_session()` 将其写入
`joysafeter_session_credential_groups`。Rust 运行时再按 Session 关联的 credential-group 动态读取当前未归档、
未删除的 MCP 成员，将匹配 URL 的凭据用于 MCP egress。

Trigger 当前创建 Session 时没有传入 `credential_group_ids`，所以 Trigger 自动创建的 Session 没有任何 MCP
credential-group 授权。它仍会继承 Agent 快照中的模型连接和 Environment 配置；本设计只补齐 **MCP 凭据库授权**，
不替代模型连接、Environment service credential 或 webhook 入站认证。

`webhook_auth_credential_id` / `webhook_auth_field` 只验证 webhook 入站调用者身份，与运行中 Agent 可使用的
MCP 凭据无关，继续保持独立。

## 2. 目标

1. Trigger 自动创建的 Session 能通过 credential-group 获得 MCP 运行凭据，与交互式 Session 使用同一运行时路径。
2. 授权显式、可审计、可撤销：记录谁、以什么主体、在何时授予或撤销了哪些 Group。
3. 撤销后，任何在撤销线性化点之后开始的 Trigger fire 都不得使用被撤销 Grant 创建或复用 Session。
4. `fresh`、`reuse`、`keyed` 能力全部保留；不通过退化为仅支持 `fresh` 来规避授权问题。
5. 旧 Trigger 默认保持无 MCP grant 运行行为，不因上线 P2A 被批量停用。
6. Group 成员动态变化时，Session 与 Trigger Grant 保持相同授权语义和 URL 冲突不变式。
7. Grant 的创建、重新授权、撤销、清除策略均有稳定 API、结构化错误、原子审计和完整测试。

## 3. 非目标

- 不把模型连接、Environment service credential、Git token 或 webhook 入站认证纳入 Trigger Grant。
- 不实现 grant-time credential 成员执行快照；本期采用动态 Group 成员集。
- 不在 revoke 时强制取消已运行 Task、销毁 Sandbox 或终止已经通过授权判定的在途 fire。
- 不改变 MCP OAuth 的安全与刷新模型；OAuth 属于 P2B。
- 不新建平行重试或死信系统；Cron 继续使用现有 scheduler retry/dead-letter 状态机。
- 不允许全局 Trigger（`project_id IS NULL`）绑定项目级 credential-group。

## 4. 术语与安全模型

### 4.1 用户可见术语

- 后端对象：`credential-group`、`TriggerCredentialGrant`。
- 用户可见对象：**MCP 凭据库 / MCP credential vault**。
- “撤销授权”表示停止该 Trigger 后续使用 MCP Grant，不表示删除 Group 或凭据材料。
- “清除凭据要求”是独立高风险动作，表示 Trigger 以后允许以空 MCP credential-group 集运行；不得与 revoke 混为一谈。

### 4.2 动态成员集

Grant 授权的是 credential-group，而不是授权时 Group 内凭据的静态副本：

- Group 增加 MCP 凭据会扩大所有绑定该 Group 的 active Session 和 active Trigger Grant 权限。
- Group 删除、归档成员会收缩这些权限。
- 所有成员变化必须写安全审计，并与在线网络策略 `pending` 标记同事务提交。
- 成员增加必须同时检查 active Session 和 active Trigger Grant 的跨 Group normalized MCP URL 冲突；冲突即拒绝。
- 如果未来需要“授权后不可被 Group 成员变化扩权”，必须另立设计，引入 credential-level 执行绑定；仅保存审计快照不能实现该安全性质。

### 4.3 显式凭据策略

`joysafeter_triggers` 新增非空字段：

```text
credential_policy = "none" | "mcp_group_grant"
```

- `none`：fire 使用空 MCP credential-group 集；这是既有 Trigger 的迁移默认值。
- `mcp_group_grant`：fire 必须取得有效 active grant，否则 fail-closed；该 policy 与 `pinned` 组合属于非法状态。
- revoke 只撤销 active grant，不把 policy 自动改回 `none`。
- 不允许通过清理历史 grant 行改变 `credential_policy`，安全状态不能依赖审计历史是否保留。

## 5. 数据模型

### 5.1 Typed ID

新增：

```python
class TriggerCredentialGrantId(EntityId):
    prefix = "triggrant_"
```

该类型必须贯穿 SQLAlchemy model、Pydantic schema、service、API、前端 parser 和 typed-ID architecture tests。

### 5.2 `joysafeter_trigger_credential_grants`

字段：

- `id: TriggerCredentialGrantId`：主键。
- `trigger_id: TriggerId`：FK → `joysafeter_triggers.id`，`ON DELETE RESTRICT`。
- `project_id: str`：非空 FK → project；Grant 不支持全局 Trigger。
- `org_id: str`：非空 FK → organization。
- `granted_by_actor_type: "user" | "api_key"`。
- `granted_by_actor_id: str`：真实调用主体 ID，不用 API Key 创建者冒充调用主体。
- `granted_at: timestamptz`。
- `revoked_by_actor_type: "user" | "api_key" | NULL`。
- `revoked_by_actor_id: str | NULL`。
- `revoked_at: timestamptz | NULL`。
- `created_at / updated_at`：沿用 mixin。

不变式：

- 每个 Trigger 至多一个 `revoked_at IS NULL` 的 active grant。
- 使用 PostgreSQL 与 SQLite 条件一致的部分唯一索引：
  `(trigger_id) WHERE revoked_at IS NULL`。
- actor type 与 actor id 必须同时为空或同时非空；grant actor 必须非空，revoke actor 随 `revoked_at` 同时出现。
- Grant 一经创建，其 Group 关联不可原地修改；重新授权必须创建新 Grant。
- Grant 的 `project_id / org_id` 必须与 Trigger 完全一致，创建后不可修改。
- actor ID 是保留审计身份的多态稳定标识，不使用会因用户/API Key 删除而丢失历史的强 FK；读取时优先解析显示名，
  主体已删除则回退显示 actor type + stable ID。

### 5.3 `joysafeter_trigger_credential_grant_groups`

关联表字段：

- `grant_id: TriggerCredentialGrantId`：FK → grant，`ON DELETE CASCADE`。
- `credential_group_id: CredentialGroupId`：FK → credential-group，`ON DELETE RESTRICT`。
- `(grant_id, credential_group_id)`：复合主键，天然去重。
- `created_at / updated_at`：与 Session 关联表一致。

历史 Grant 的 Group 关联必须保留，以便回答“当时授予了哪些 Group”。因此只要历史 Grant 仍在，Group 的物理强删就会被
`RESTRICT` 阻止；软删除和归档按 §9 生命周期处理。

### 5.4 Session Grant 绑定

`joysafeter_sessions` 新增：

```text
trigger_credential_grant_id: TriggerCredentialGrantId | NULL
```

- 仅 Trigger 自动创建且 `credential_policy=mcp_group_grant` 的 Session 写入该字段。
- FK → grant，`ON DELETE RESTRICT`。
- `credential_policy=none` 或人工创建 Session 时为 `NULL`。
- Grant 被 revoke 后不修改历史 Session；复用判定通过 grant ID 匹配阻止后续使用。
- 不把 Grant ID 只放入 Session metadata JSON；授权身份必须是 typed FK。

## 6. 权限与调用主体

- 读取 Grant 元数据：沿用项目 read 权限；只返回 Group 元数据和 actor 元数据，不返回凭据值。
- 创建、重新授权、撤销、清除 policy：`require_joysafeter_write`。
- `require_joysafeter_write` 同时允许用户和项目 API Key，因此 AuthContext 必须暴露真实 principal ID：
  - 用户：`principal_type=user`，principal ID 为 user id。
  - API Key：`principal_type=api_key`，principal ID 为 API Key 自身 id，而不是 `created_by`。
- 若 AuthContext 尚不能提供 API Key ID，P2A 必须先补齐；不得把 API Key 操作错误记成创建者本人操作。
- 所有 Grant 变更同时写 `audit_joysafeter_event(commit=False, best_effort=False)`，审计写入失败则整个业务事务回滚。
- `audit_joysafeter_event` 的 details 必须显式写入真实 `principal_type/principal_id`；现有顶层 `user_id` 字段可继续用于
  人类用户索引或 API Key 创建者关联，但不得作为判断实际调用主体的唯一字段。

审计事件：

- `trigger_credential_grant.created`
- `trigger_credential_grant.reauthorized`
- `trigger_credential_grant.revoked`
- `trigger_credential_policy.cleared`

details 仅包含 Trigger ID、Grant ID、Group IDs、旧/新 policy、actor type；不得包含凭据 `data` 或 token。

## 7. Grant 生命周期与 API

### 7.1 创建 Trigger

`POST /triggers` 的 `TriggerCreateRequest` 增加：

```text
credential_group_ids: list[CredentialGroupId] = []
```

- 空列表：创建 `credential_policy=none` 的 Trigger，不创建 Grant。
- 非空列表：校验后创建 `credential_policy=mcp_group_grant` 的 Trigger、active Grant、关联行及审计事件。
- `session_mode=pinned` 时禁止提交非空 `credential_group_ids`，返回 `TRIGGER_PINNED_MODE_GRANT_UNSUPPORTED`。
- Trigger、Grant、关联行、审计事件必须在同一事务中一次 commit。
- commit 成功后再执行 scheduler notify；notify 失败仍由 scheduler 轮询兜底。

### 7.2 读取

新增：

```text
GET /triggers/{id}/credential-grant
GET /triggers/{id}/credential-grants?limit=&after_id=
```

当前状态响应包含：

- `credential_policy`
- `active_grant: TriggerCredentialGrantResponse | null`
- 最近一次 revoked grant 摘要（active 为空时用于解释状态）
- Group：`id`、`name`、`archived_at`、`deleted` 状态
- actor type、可展示名称或稳定 ID、grant/revoke 时间

响应模型拆分为 `TriggerListItemResponse` 与 `TriggerDetailResponse`：detail 内嵌当前状态摘要；列表只返回
`credential_policy` 和批量计算的 `has_active_grant`，不得逐行查询造成 N+1。

`GET /credential-grant` 在 policy 为 `none`、或 policy required 但已无 active grant 时都返回 `200` 的状态对象，
不使用 `404` 表达“当前没有 active grant”。

### 7.3 重新授权

使用幂等目标状态端点：

```text
PUT /triggers/{id}/credential-grant
```

请求：

```text
credential_group_ids: list[CredentialGroupId]  # min_length=1
expected_active_grant_id: TriggerCredentialGrantId | null
reenable: bool = false
```

语义：

1. 锁定 Trigger。
2. `expected_active_grant_id` 与当前状态不一致时立即返回 `TRIGGER_CREDENTIAL_GRANT_STALE`，防止旧页面覆盖他人修改。
3. 校验 Trigger 非全局、非 deleted，且 `session_mode != pinned`。
4. 对去重并稳定排序后的 Group IDs 逐一加锁并完成 §8 校验。
5. 若当前 active grant 的 Group 集与目标集完全相同，不创建新 Grant：
   - `reenable=false`：直接返回当前状态，不重复审计；
   - `reenable=true`：只执行显式重新启用和授权错误清理，写 Trigger 状态变更审计后 commit。
6. 新 Group 全部校验成功后，才在同一事务内 revoke 旧 Grant、插入新 Grant、关联行和审计事件。
7. 设置 `credential_policy=mcp_group_grant`；清除 `reusable_session_id`，使 `reuse` 不再指向旧 Grant Session。
8. 无论是否重新启用，都清除已经不再成立的授权类 `last_error_code` 和
   `disabled_reason_code=credential_grant_revoked`；不得清除无关执行错误或其他禁用原因。
9. `reenable=true` 时显式重新启用 Trigger；否则保留当前 enabled 状态。
10. 单次 commit；任何一步失败时旧 active grant 保持不变。

### 7.4 撤销

```text
POST /triggers/{id}/credential-grant/revoke
```

请求：

```text
expected_active_grant_id: TriggerCredentialGrantId | null
```

语义：

- 锁定 Trigger；expected ID 不匹配返回 stale conflict。
- 有 active grant：写 `revoked_by_* / revoked_at` 和审计事件。
- 已无 active grant 且 policy 仍是 `mcp_group_grant`：幂等返回当前状态，不重复审计。
- policy 保持 `mcp_group_grant`，表示该 Trigger 仍要求授权，不能静默降级为空凭据运行。
- 原子设置 `enabled=false`、`next_run_at=NULL`、清除 `reusable_session_id`，并设置
  `disabled_reason_code=credential_grant_revoked` 和稳定的人类摘要。
- revoke 不得抢占或清除一个仍有效的 Scheduler `locked_by/locked_at` claim：已经通过 fire 预检的在途 Cron
  允许完成，并由现有 Scheduler completion 路径释放 claim。若无有效 claim，可清除尚未开始的 retry/pending slot 状态。
- revoke 后在途 fire 的 completion 可以记录 Task/Session 结果并释放 claim，但不得重新启用 Trigger、恢复
  `reusable_session_id`、覆盖 `credential_grant_revoked` 禁用原因，或把用户撤销转换成 scheduler auto-disable。
- revoke 不删除 Session↔Group 关联，也不取消已运行 Task；这些对象作为历史执行证据保留。

### 7.5 清除凭据要求

revoke 与“以后允许无 MCP 凭据运行”是不同操作。新增：

```text
DELETE /triggers/{id}/credential-grant-policy
```

约束：

- Trigger 必须已 `enabled=false`。
- 必须无 active grant；若有则要求先 revoke。
- 设置 `credential_policy=none`，清除 `reusable_session_id`；若当前禁用原因仅为
  `credential_grant_revoked`，同步清除该 reason code/摘要。写原子审计并保持 Trigger disabled。
- 用户之后必须显式启用 Trigger；启用后以空 credential-group 集运行。
- UI 使用危险确认文案，明确说明 Trigger 将不再要求 MCP 凭据授权。

## 8. Grant 创建与 Fire 校验

### 8.1 Group 绑定校验

创建或重新授权时，对去重后的每个 Group：

1. 必须存在且 `deleted_at IS NULL`。
2. 必须 `archived_at IS NULL`。
3. 必须与 Trigger 属于同一 project。
4. 多 Group 当前 live MCP 成员的 `normalized_mcp_server_url` 不得冲突。
5. Group 列表必须至少包含一个 ID。

校验逻辑由可复用的 `CredentialGroupService.validate_binding(...)` 承担；Session 和 Trigger Grant 都调用同一实现，
不得复制两套逐渐漂移的校验代码。

### 8.2 无副作用授权预检

所有 fire 来源必须在以下副作用之前完成 Grant 预检：

- Cron `replace` 取消旧 Task；
- 创建或复用 Session；
- 创建 Task；
- 向 Redis / orchestrator 派发。

预检在 Trigger `SELECT ... FOR UPDATE` 下执行，并产生不可变的 `TriggerCredentialContext`：

```text
policy
grant_id: TriggerCredentialGrantId | null
credential_group_ids: list[CredentialGroupId]
authorized_at
```

判定：

- `policy=none`：`grant_id=NULL`，Group 集为空，允许继续。
- `policy=mcp_group_grant`：必须存在 active grant，并重新验证关联 Group 当前有效；否则 fail-closed。
- `session_mode=pinned`：policy 必须为 `none`；若数据库出现 `mcp_group_grant`，视为不变式破坏并 fail-closed。
- Executor、Scheduler 和 FireService 必须显式传递同一个 context；后续阶段不得重新查询“当前 active grant”替换
  已在线性化点接受的 Grant，也不得只传松散的 Group ID 列表而丢失 grant identity。

### 8.3 线性化语义

- fire 的授权判定在线程取得 Trigger 行锁并读取 active grant 时线性化。
- revoke/reauthorize 在取得同一 Trigger 行锁并修改 active grant 时线性化。
- 若 fire 先取得锁并通过预检，它属于 revoke 之前已开始的在途 fire，即使 Task 最终在 revoke 响应后才可见，也允许完成。
- 若 revoke/reauthorize 先取得锁，之后开始的 fire 必须观察到新状态，不能使用旧 Grant。
- Grant 及其关联行创建后不可修改，fire 可以携带预检得到的 immutable grant ID 和 Group IDs 完成本次执行。
- fire 线性化后发生的 reauthorize/revoke 不改变本次 context；Session 必须记录 context 中的旧 Grant ID，使该次执行可审计。
- 这一保证不等同于立即终止已经运行的 Task；立即终止属于独立的强撤销设计。

### 8.4 Session 创建与复用

#### `fresh`

- 每次创建新 Session。
- `policy=none`：不绑定 Group，`trigger_credential_grant_id=NULL`。
- `policy=mcp_group_grant`：写 Group junction，并写本次预检得到的 grant ID。

#### `reuse`

- 仅当 `reusable_session_id` 指向同 Trigger、同 Agent、同 Project、idle、未归档且 grant identity 匹配时复用。
- `policy=none`：仅复用 `trigger_credential_grant_id IS NULL` 的 Trigger-owned Session。
- `policy=mcp_group_grant`：仅复用 `trigger_credential_grant_id == context.grant_id` 的 Session。
- 不匹配视为 cache miss，创建新 Session；旧 Session 保留但不再被该 Trigger 复用。
- completion 只有在完成 Session 的 grant identity 仍与 Trigger 当前 policy/active grant 匹配时，才能更新
  `reusable_session_id`；旧 Grant 的在途 fire 完成后不得把 reauthorize/revoke 已清除的旧指针写回来。

#### `keyed`

- 查询必须同时匹配：Project、Agent、Trigger ID、渲染后的 key、未归档、idle 和 grant identity。
- 不再只按 Project + Agent + key 查找，避免不同 Trigger 共享同一 keyed Session。
- grant 不匹配时为同一个 key 创建新 Session，并绑定当前 grant ID。

#### `pinned`

- 使用人工选择 Session 自身的 credential-group 关联。
- Trigger Grant 不覆盖、不合并该 Session 的 Group。
- pinned Trigger 必须 `credential_policy=none`，UI 不展示可编辑 Grant selector。
- 从 `fresh/reuse/keyed` 改为 `pinned` 时，若存在 active grant 或 policy 为 `mcp_group_grant`，更新请求必须被拒绝，
  要求用户先显式 revoke 并清除 policy。
- `fresh/reuse/keyed` 之间切换可以保留 active Grant；所有 Session 复用仍必须同时满足 Trigger ID 和 Grant identity。
- 修改 `session_key` 或离开 `reuse` 时清除 `reusable_session_id`，避免配置切换后保留无意义的复用指针。

Trigger 配置更新还必须执行以下启用门槛：`credential_policy=mcp_group_grant` 且无 active grant 时，任何
`enabled=true` 更新都返回 `TRIGGER_CREDENTIAL_GRANT_REQUIRED`；不能绕过 reauthorize 直接重新启用已撤销 Trigger。

### 8.5 Cron `replace` 顺序

正确顺序：

1. Grant 无副作用预检并完成 fire 授权线性化。
2. 检查 concurrency policy。
3. `forbid`：有 active Task 时正常 skip，不创建 Session。
4. `replace`：只有预检成功后才能取消旧 Task。
5. 创建或解析与本次 Grant identity 匹配的 Session。
6. 创建 Task 并派发。

这样不会因为一个在进入执行链前就已失效的 Grant，先取消健康旧任务再失败。预检以后仍可能因网络、并发资源变化或
Task 派发失败而无法完成替换；这属于现有 `replace` 的一般失败模型，不宣称“取消成功必然能启动替代任务”。

## 9. Group 生命周期与动态成员不变式

### 9.1 Group 归档与软删

- 被 active Session 绑定时：继续拒绝。
- 被 active Trigger Grant 绑定时：同样拒绝，并返回受影响 Trigger IDs。
- 仅被 revoked 历史 Grant 引用时：允许软归档/软删，但历史关联保留，读取 Grant 历史时显示 tombstone 状态。
- 物理强删：历史 Grant FK `RESTRICT` 阻止，除非通过独立合规清理流程先处理历史数据。

### 9.2 成员增加

在现有 active Session 冲突检查基础上，再查询所有包含该 Group 的 active Trigger Grants：

- 收集同一 Grant 的 peer Groups；
- 若新增成员 normalized URL 已存在于任一 peer Group，拒绝并返回 `CREDENTIAL_GROUP_URL_CONFLICT`；
- Group mutation 持有 Group/credential 锁，不反向获取 Trigger 行锁；Grant 创建始终按 Trigger → sorted Groups 加锁，避免死锁。

### 9.3 成员删除、归档、更新

- 允许动态收缩授权集。
- 仍需原子审计和网络策略 `pending`。
- URL 更新按“删除旧 URL + 增加新 URL”的冲突规则校验 active Session 与 active Grant。

## 10. 事务、锁与副作用边界

### 10.1 固定锁顺序

1. Trigger 行；
2. Credential Group 行，按 ID 稳定排序；
3. Credential 行，按 ID 稳定排序。

Group 成员操作不获取 Trigger 行锁；它们通过查询 active grant associations 检查不变式。这样不会与
Trigger → Group 的授权路径形成反向锁循环。

### 10.2 Trigger 创建

`JoySafeterTriggerService.__init__` 增加与 `CredentialGroupService` 一致的 `auto_commit: bool = True`；
创建带 Grant 的 API 路径必须使用 `auto_commit=False`：

1. 校验 target Agent/Environment/webhook auth。
2. 锁定并校验 Group。
3. insert Trigger。
4. insert Grant + associations。
5. insert audit event。
6. 单次 commit。
7. commit 后 scheduler notify。

### 10.3 重新授权与撤销

- 新授权必须先完整校验，再 revoke 旧 Grant；禁止先撤销后发现新 Group 无效。
- partial unique index 是最终并发兜底，不替代 Trigger 行锁。
- audit 与业务变更同事务；Redis nudge、scheduler notify 等外部通知只能在 commit 后执行。

### 10.4 Session 与 Task 提交

本设计不要求一次事务跨越所有 Session event 与 Redis enqueue，但要求：

- 授权预检先于任何执行副作用；
- Session 保存 immutable grant ID；
- Task 保存 `trigger_id`，运行历史可通过 Session 追溯 Grant；
- Session 创建失败不得残留 association；
- Task 创建或派发失败时沿用现有补偿逻辑，自动创建的孤儿 Session 必须删除或终止；
- 不允许在 Session metadata 中用非 typed 字符串替代 Grant FK。
- Scheduler completion 更新 Trigger 状态时必须使用“当前授权状态感知”的 merge：历史 fire 只能写 attempt/task/session
  结果，不能覆盖较新的 revoke/reauthorize 所建立的 policy、active grant、禁用原因或复用指针。

## 11. 结构化错误与状态

Trigger 增加：

```text
last_error_code: str | null
last_error_data: JSONB | null
disabled_reason_code: str | null
```

保留 `last_error` / `disabled_reason` 作为面向人的稳定摘要，但 UI 只依据 `last_error_code`、
`disabled_reason_code` 和 `auto_disabled_at` 判断状态类型。

错误码至少包括：

- `TRIGGER_CREDENTIAL_GRANT_REQUIRED`
- `TRIGGER_CREDENTIAL_GRANT_STALE`
- `TRIGGER_CREDENTIAL_GRANT_PROJECT_MISMATCH`
- `TRIGGER_CREDENTIAL_GROUP_NOT_FOUND`
- `TRIGGER_CREDENTIAL_GROUP_DELETED`
- `TRIGGER_CREDENTIAL_GROUP_ARCHIVED`
- `TRIGGER_CREDENTIAL_GROUP_URL_CONFLICT`
- `TRIGGER_CREDENTIAL_GRANT_REVOKED`
- `TRIGGER_PINNED_MODE_GRANT_UNSUPPORTED`
- `TRIGGER_CREDENTIAL_POLICY_CLEAR_REQUIRES_DISABLED`

来源差异：

- Cron：授权失败进入现有 scheduler failure/retry/dead-letter 记账；非 transient 授权错误不做同 slot backoff 重试，
  但计入 `consecutive_failures`，达到阈值自动禁用。
- Webhook：内部保存结构化授权错误，对外只返回不含 Group/Grant ID 的泛化错误；不由外部调用频率累加 Cron
  `consecutive_failures` 或触发自动禁用。
- Manual/Test：向项目用户返回具体错误码并保存最后错误，不增加 scheduler `consecutive_failures`。
- revoke：主动禁用 Trigger，不伪装成运行失败，不增加失败计数。
- reauthorize：仅清除授权相关 error；不得清除无关的执行错误。
- Trigger toggle：policy required 且无 active grant 时禁用“启用”动作，并处理后端
  `TRIGGER_CREDENTIAL_GRANT_REQUIRED`，引导用户先重新授权。

## 12. 前端 UX

### 12.1 共享选择器

先从 `create-session-dialog.tsx` 抽取共享 `CredentialGroupMultiSelect`，Session 与 Trigger 共用：

- 支持后端分页，不受 `/credential-groups` 默认 20 条限制；
- 搜索、加载更多、空状态、错误重试；
- 默认只允许选择 active Group；
- 编辑历史 Grant 时能展示 archived/deleted tombstone，而不是静默丢失已选项；
- 以 typed `CredentialGroupId[]` 输入输出；
- 多 Group URL 冲突以后端错误为准，并在 selector 附近显示可操作提示。

### 12.2 创建 Trigger

- `fresh/reuse/keyed`：显示可选 MCP 凭据库多选。
- 未选择：创建 `credential_policy=none`。
- 已选择：创建 `credential_policy=mcp_group_grant` 和 active Grant。
- `pinned`：隐藏 Grant selector，展示“使用固定 Session 自身的 MCP 凭据库”说明。

### 12.3 详情与编辑

Trigger 普通配置编辑与 Grant 变更分开，避免 PATCH Trigger 成功而 reauthorize 失败的部分保存：

- 配置卡：名称、Schedule、Session mode 等。
- MCP 运行授权卡：policy、active Grant、Groups、actor、时间、重新授权、撤销、清除要求。
- 重新授权使用独立请求和独立成功/失败反馈。
- `reuse/keyed` 重新授权后提示：旧 Session 不再复用，下次 fire 将创建绑定新 Grant 的 Session。
- revoke 确认框明确：Trigger 将被禁用；在途和已经运行的 Task 不会被本操作终止。
- reauthorize 已禁用 Trigger 时提供显式“重新授权后同时启用”复选项，默认不勾选。
- Grant 已撤销时禁用普通“启用”开关，避免用户进入必然 fail-closed 的状态。
- 清除 policy 只在 Trigger 已禁用且无 active Grant 时显示，并使用危险确认。

### 12.4 状态提示

根据结构化状态分别展示：

- 授权已撤销，Trigger 已禁用；
- Group 已归档/不存在，需要重新授权；
- 多 Group MCP URL 冲突；
- 普通运行失败；
- Scheduler 自动禁用。

所有文案提供 en + zh；用户可见术语统一为 MCP 凭据库 / MCP credential vault。

## 13. 迁移策略

仓库当前使用单一预发布完整 baseline migration `20260803_000001_initial_schema.py`。P2A 在 baseline 冻结前实施，
因此直接更新该 baseline，而不是创建第二条生产增量 migration：

1. 注册 `TriggerCredentialGrantId`。
2. `joysafeter_triggers` 增加 `credential_policy`、`last_error_code`、`last_error_data`、`disabled_reason_code`；
   `credential_policy` 使用 `server_default='none'` 且非空。
3. 创建 Grant 表和 Grant↔Group 关联表及索引/约束。
4. `joysafeter_sessions` 增加 nullable `trigger_credential_grant_id` FK。
5. downgrade 按 FK 依赖逆序删除。

数据默认：

- 既有 Trigger：`credential_policy=none`。
- 既有 Session：`trigger_credential_grant_id=NULL`。
- 不根据历史字段自动生成 Grant，不做猜测式回填。

如果实施前 baseline 已被正式冻结或进入生产，则必须改为独立 additive revision；不得同时修改已发布 baseline。

## 14. 测试范围

### 14.1 数据模型与 typed ID

- `TriggerCredentialGrantId` 前缀、解析、序列化和错误前缀测试。
- model/schema/service 不允许 `vault_ids` 或 JSONB Group ID list。
- Grant association 使用 typed composite PK/FK。
- active grant partial unique index 在 PostgreSQL 与 SQLite predicate 一致。
- actor/revoke 字段成对约束、Group `RESTRICT`、Session Grant FK。
- baseline upgrade/downgrade 和 model metadata 一致性。

### 14.2 Grant 生命周期

- 创建 Trigger 无 Groups → policy none、无 Grant。
- 创建 Trigger 有 Groups → Trigger、Grant、associations、audit 单事务成功。
- Grant/audit 失败 → Trigger 不残留。
- reauthorize 先校验新 Groups，再原子 revoke old + insert new。
- 相同 Group 集 PUT 幂等返回当前 Grant。
- stale expected Grant ID → 409，当前授权不变。
- revoke 幂等、原子禁用、保留 policy required。
- revoke 不清除有效 Scheduler claim；在途 fire 完成后由原 completion 路径释放。
- revoke/reauthorize 后，旧 fire completion 不得恢复旧 `reusable_session_id` 或覆盖较新的禁用原因。
- disabled + no active Grant 才能清除 policy。
- policy required 且无 active Grant 时，普通 PATCH `enabled=true` 被拒绝。
- API Key actor 记录真实 key principal，而不是创建者。

### 14.3 Group 校验与生命周期

- 空列表、重复 ID、跨项目、archived、deleted、缺失 Group。
- Grant 绑定时多 Group normalized URL 冲突。
- active Grant 阻止 Group archive/soft-delete。
- revoked 历史 Grant 不阻止软归档，但阻止物理强删。
- 成员增加同时检查 active Session 和 active Grant peer Groups。
- 并发成员增加与 reauthorize 不产生未检测 URL 冲突。

### 14.4 Session mode

- `fresh` 创建 Session 并写 Grant ID + Group junction。
- `reuse` 仅复用相同 Grant ID Session；reauthorize/revoke 后旧 Session 不复用。
- `keyed` 同时按 Trigger ID、key 和 Grant ID 复用，不跨 Trigger 共享。
- `keyed` Grant 改变后同 key 创建新 Session。
- `pinned` 禁止 Grant，继续使用固定 Session 自身 Group。
- mode 切换到 pinned 时，active Grant/policy required 必须先处理。
- policy none 不得复用带旧 Trigger Grant ID 的 Session。

### 14.5 并发与线性化

- fire 先取得 Trigger 锁 → 后续 revoke 不影响该在途 fire，但影响下一次 fire。
- revoke 先取得锁 → 后续 fire fail-closed。
- 并发 reauthorize 通过 expected ID 防止 lost update。
- partial unique index 兜底并发 active Grant。
- `replace` 在 Grant 预检失败时绝不取消旧 Task。
- fire 预检得到的 immutable context 在 revoke/reauthorize 后仍完成该次在途执行，并把旧 Grant ID 写入 Session。
- 旧 context completion 只记录执行结果，不覆盖新的 Grant/policy/disabled/reuse 状态。
- Session/Task 创建失败清理自动创建的 Session 和 associations。

### 14.6 Fire 来源与错误状态

- Cron 授权失败进入 scheduler 记账并按阈值自动禁用。
- Webhook 授权失败外部响应不泄露 Grant/Group ID，不增加 Cron failure counter。
- Manual/Test 返回具体授权错误但不增加 scheduler failure counter。
- revoke 不增加失败计数。
- reauthorize 只清除授权相关错误；`reenable` 行为显式。
- 成功 fire 清除对应授权错误状态。

### 14.7 API 与前端

- create request typed `credential_group_ids`。
- current/history GET response parser 和分页。
- 独立 reauthorize/revoke/clear-policy mutations 及 cache invalidation。
- selector 加载超过 20 个 Group、搜索和加载更多。
- archived/deleted historical Group tombstone。
- pinned 隐藏 selector。
- reuse/keyed 重新授权提示。
- revoke、清除 policy 危险确认。
- 授权错误、普通失败、auto-disabled 的 en/zh 区分。
- `disabled_reason_code=credential_grant_revoked` 与 scheduler `auto_disabled_at` 的 UI 状态不得混淆。
- Trigger 配置保存与 Grant 保存互不产生未提示的部分成功。

### 14.8 回归

- 既有 `credential_policy=none` Trigger 继续以空 MCP Group 集 fire。
- Agent 模型连接、Environment credential、webhook 入站认证不受影响。
- 现有 interactive Session credential-group 创建和运行时解析不变。
- `fresh/reuse/keyed/pinned` 原有非凭据行为保持，新增约束只阻止跨 Grant 或跨 Trigger 的不安全 Session 复用。

## 15. 验收标准

P2A 只有同时满足以下条件才算完成：

1. revoke 后开始的新 fire 无法复用任何旧 Grant Session。
2. `reuse` 与 `keyed` 能力保留，并通过 Grant ID 匹配实现安全复用。
3. 无效 Grant 不会导致 Cron `replace` 先取消旧任务。
4. 创建、重新授权、撤销和审计均具备明确单事务边界。
5. Group 动态成员变化同时维护 active Session 与 active Grant 的 URL 冲突不变式。
6. UI 能稳定读取并解释当前授权状态，不解析错误字符串，不受 20 条 Group 上限影响。
7. 旧 Trigger 行为兼容，但安全状态不依赖历史 Grant 行是否存在。
8. 并发、迁移、后端、Rust 运行时影响面和前端测试全部通过。

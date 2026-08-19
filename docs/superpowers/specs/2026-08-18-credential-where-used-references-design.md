# 凭证「谁在用 / 哪些流程」分层引用视图 — 设计

- 日期：2026-08-18
- 分支：joysafeter-v2-0814
- 相关：`project_joysafeter_service_credential_creation_ux`（服务凭证 create-flow 重设计）——**本 spec 拥有 where-used 共享地基，该 initiative 消费之，不重建**（见 §9）
- 修订：rev3 —— 确立"共享地基"边界（消费方 = 服务凭证 create-flow）+ 组件双呈现态；rev2 已对齐 scanner/coordinator 架构（原 rev1 按遗留 `as_data()` 4-list，作废）

## 1. 问题与现有架构

归档/删除仍被引用的凭证时，用户看到一句笼统英文
`Credential is still referenced and cannot be archived or deleted`。三诉求全落空——**谁在用、哪些流程、分层**——根因同一个：引用信息既无名称也无流程分组，且前端把它丢弃。

**工作区正在构建的架构（未提交，用户在并行推进；落地前须对照当前代码）：**

1. **扫描层** `backend/app/joysafeter_infrastructure/credentials/dependency_scanners.py`：9 个 scanner，每个 `scan_resource(project_id, credential_id)` / `scan_group(project_id, group_id)` 返回领域对象 `CredentialDependency`（`joysafeter_domain/credentials/dependencies.py`），带 `surface_id` + `source_id`（被引用实体 id）+ `dispositions`。`persistent_dependency_scanners(db)` 聚合，经 `composition.py` 暴露为 `scan_resource_dependencies` / `scan_group_dependencies`。
   - **关键：`CredentialDependency` 只有 `source_id`（id），没有 name——领域层刻意保持纯净。名称/标签解析是上层职责。**
2. **协调层** `lifecycle_coordinator.py` `_observe_resource` / `_observe_group`：新的阻塞判定路径，受 `settings.credential_dependency_registry_mode` 门控：
   - `shadow`：只记录新旧扫描差异日志，**不抛**；
   - `enforce`：用 scanner 的 blockers 抛 `CREDENTIAL_IN_USE`，`data = {credential_id, dependency_ids:[…], dependency_count, dispositions}`（**仍只有 id**）。
3. **遗留路径** 仓储 `sqlalchemy_repository.py` `_reject_if_in_use`（`:1032`）/ `_reject_group_lifecycle_blockers`（`:1341`）：`CredentialDependencies.as_data()` 的 4-list 裸 UUID。仍在真实调用链中——`CredentialService.archive`（API 入口，`credentials.py:432`）→ 协调器 `archive_resource` → `_observe_resource`（shadow/enforce）→ `_transactions.archive` → 仓储 `archive` → `_reject_if_in_use`。
   - 因此 **shadow 模式下遗留路径实际拦截（旧 data 形态）；enforce 模式下协调器先抛（新 data 形态）**。
4. **前端** `getOperationErrorMessage`（`frontend/lib/managed/errors.ts:59`）无 `CREDENTIAL_IN_USE` 分支 → 落到"显示原始英文 message"，`data` 整个丢弃。

领域里 `CREDENTIAL_REFERENCE_SURFACES`（`dependencies.py:168`）已是"哪些流程"的分类真源（`owner` + `kind` + `dispositions`），scanner 已按它打 `surface_id`。缺的只是：**过滤阻塞项 → 映射到可导航类型 → 批量解析名称 → 组装成前端可读结构**，以及前端渲染。

## 2. 已确认的产品/架构决策

| 维度 | 决策 |
|---|---|
| 呈现时机 | **提前展示**：凭证/凭证组详情页常驻 + 归档/删除确认弹窗内嵌；动作之前即可见 |
| 引用项形态 | **名称 + 可点击跳转** 到对应 agent/环境/触发器/会话 |
| 展示范围 | **只映射 4 个 live surface**（见 §4.1）；"分层"= 按流程分组 |
| 覆盖对象 | **凭证（模型+服务）和凭证组 / MCP Vault 都做** |
| 阻塞时按钮 | **按钮可点，确认弹窗内阻止提交** 并展示阻塞列表 |
| 扫描落点 | **复用 `dependency_scanners.py`**（不用遗留 `as_data()` 4-list） |
| 数据结构 | **统一 `references` 列表**，非分类数组 |
| 名称解析 | **新增 application 层 reference-view 组装器**，消费 scanner 输出 + 名称查询端口；scanner 保持 name-free |
| 门禁诚实性 | `can_archive/can_delete` 按**所有** `.blocks()` 计算；不可映射的阻塞（legacy）以**一条不可点汇总行**兜底，杜绝"无阻塞却 409"的静默失败 |

## 3. 架构

三个单一职责单元：

- **扫描器**（`dependency_scanners.py`，已存在）：找出谁引用，产出 name-free 的 `CredentialDependency`。
- **引用视图组装器**（application 层新增）：过滤阻塞项 → 映射类型 → 批量解析名称 → 组装 `references` + 门禁布尔。被读接口与 409 两处复用（单一真源）。
- **引用视图组件**（前端）：分层渲染 + 可点击导航；详情页与确认弹窗共用。

数据流（提前展示）：`详情页/弹窗挂载 → GET …/references → 组装器 → 分层渲染`。
数据流（并发兜底）：`归档/删除 409 → data.references（enforce）或旧数组（shadow）→ 前端 fallback 兼容两种形态 → 弹窗内联渲染`。

## 4. 后端

### 4.1 引用视图组装器（新增，application 层）

新增 `backend/app/joysafeter_application/credentials/reference_view.py`（或并入协调器邻近模块），暴露：

```python
@dataclass(frozen=True)
class ReferenceItem:
    surface: str          # 稳定机器码，见下表（只含 4 个 live surface）
    resource_type: str    # "agent" | "trigger" | "environment" | "session"
    id: str               # 可导航实体 id
    name: str | None      # 展示名；空名为 None（前端回退，如会话无 title）

@dataclass(frozen=True)
class ReferenceView:
    references: list[ReferenceItem]  # 仅 4 个 live surface 的具名可导航项
    other_count: int                 # 不可映射阻塞项（legacy 等）计数，无则 0
    can_archive: bool
    can_delete: bool

async def build_resource_reference_view(
    deps: Sequence[CredentialDependency], *, uow, disposition_archive, disposition_delete
) -> ReferenceView: ...
async def build_group_reference_view(...) -> ReferenceView: ...
```

**4 个 live surface → 类型/路由映射**（其余 surface 不逐项映射）：

| `surface_id`（scanner 产出） | 前端 `surface` | `resource_type` | 名称来源 | 路由 |
|---|---|---|---|---|
| `live_agent_model_binding` | `agent_model_binding` | `agent` | `JoySafeterAgent.name`（非空） | `/managed/agents/{id}` |
| `trigger_webhook_auth_binding` | `trigger_webhook_auth` | `trigger` | `JoySafeterTrigger.name`（非空） | `/managed/triggers/{id}` |
| `live_environment_direct_injection` | `environment_injection` | `environment` | `JoySafeterEnvironment.name`（非空） | `/managed/environments/{id}` |
| `live_environment_http_egress_binding` | `environment_injection` | `environment` | 同上 | `/managed/environments/{id}` |
| `active_session_model_environment_snapshot` | `active_session_snapshot` | `session` | `JoySafeterSession.title`（可空→前端回退） | `/managed/sessions/{id}` |
| 凭证组：`session_credential_group_association` | `active_session_snapshot` | `session` | 同上 | `/managed/sessions/{id}` |

组装逻辑：
1. 过滤 `dep.blocks(disposition)` 的项（资源用 archive/delete disposition；组用 group disposition）。
2. 两个环境 surface 合并到 `environment`；`source_id` 去重（同一环境被 direct+egress 双引用只算一项）。
3. 按 `resource_type` 分组，**每类一次批量查询** `id → name`（4 条查询封顶），沿用 `project_id` 过滤。
4. **不可映射的阻塞项**（如 `legacy_v0_v1_environment_snapshot`，source 异构）→ 不逐项列出，不进 `references`，仅累加到 `other_count`，供前端渲染"另有 N 处历史快照引用阻塞"一行。
5. `can_archive` = 无任何 archive-blocking 项（含计入 `other_count` 的项）；`can_delete` 同理。

**名称查询端口**：在 `ports.py` 的 `CredentialUnitOfWork`（或其 credentials 仓储）加只读批量方法，如 `names_for(resource_type, ids) -> dict[id,name]`，仓储实现四张表的 `select(id, name/title).where(id.in_(ids), project_id==…)`。保持 scanner 与领域纯净。

### 4.2 只读引用接口（提前展示的关键，两模式都工作）

- `GET /api/v1/credentials/{credential_id}/references`
- `GET /api/v1/credential-groups/{group_id}/references`

响应 DTO：

```
CredentialReferencesResponse {
  references: ReferenceItem[]      # 仅阻塞项；含 other 兜底行（若有）
  other_count: int                 # 不可映射阻塞项数（other 行的计数；无则 0）
  can_archive: bool
  can_delete: bool
}
```

Handler 跑 `scan_resource_dependencies` / `scan_group_dependencies` → 组装器 → DTO。与 409 共用组装器，保证提前展示与报错零漂移。**该接口走 scanner 路径，shadow/enforce 均可用**；shadow 期其 `can_archive` 反映的是 scanner（新）视图，与遗留门禁的完全一致性在 `enforce` 后由 shadow-diff 日志保证收敛（已有机制）。

### 4.3 409 `CREDENTIAL_IN_USE` 复用同一结构

- **协调器 enforce 路径**（`_observe_resource` `:165` / `_observe_group` `:219`）：把 `data` 从 `{dependency_ids, dependency_count, dispositions}` 改为调用组装器产出 `{credential_id(或 credential_group_id), references:[…], other_count}`（保留 `dependency_count` 供既有遥测，可选）。
- **遗留路径**（shadow 期实际拦截者）：`_reject_if_in_use` / `_reject_group_lifecycle_blockers` 本轮**不改造**（它随迁移退役）。其旧形态 409 在 shadow 期仍可能出现，由**前端 fallback 同时兼容新旧两种 data 形态**兜住（§5.3）。
- `error_catalog.py:52` 英文 `default_message` 不变（i18n 交前端）。

### 4.4 后端不需要的东西

- **无 DB 迁移**：只读既有列（agent/trigger/environment.name、session.title）→ 不触发 alembic single-head 守卫。
- **无新错误码**：复用 `CREDENTIAL_IN_USE` → 不触发 error-catalog 注册守卫。

## 5. 前端

### 5.1 共享组件 + 数据 hook

- `useCredentialReferences(id)` / `useCredentialGroupReferences(id)`：拉 §4.2 接口。
- `<CredentialReferences references other_count variant />`：按 `surface` **分层分组**，每组本地化流程标题 + 计数，每项名称为 `<Link>` 跳 §4.1 路由；`other_count>0` 时渲染一条不可点"另有 N 处历史快照引用阻塞"。空则不渲染。
  - **`variant: 'informational' | 'blocker'`** —— 同一组件两种呈现态，供两条 initiative 复用（共享地基，见 §9）：
    - `informational`：详情页/列表的"被使用于 · N 处"，中性标题"被使用于以下位置："，不出现"请先解绑"，忽略 `can_*`；`other_count` 默认不计入"N 处"（legacy 退役在即、不可导航）。
    - `blocker`：归档/删除确认弹窗，标题"以下位置正在使用，请先解绑："，`other_count` 计入门禁。

本地化流程标题（新增 i18n key，中/英）：

| surface | 中 | 英 |
|---|---|---|
| `agent_model_binding` | 模型绑定 | Model binding |
| `trigger_webhook_auth` | Webhook 鉴权 | Webhook auth |
| `environment_injection` | 环境注入 | Environment injection |
| `active_session_snapshot` | 活跃会话 | Active session |
| `other` | 历史快照引用 | Legacy snapshot refs |

外加标题文案 key（如"以下位置正在使用，请先解绑："）。

### 5.2 接入点

- `frontend/components/managed/credentials/model-connection-detail.tsx`
- `frontend/components/managed/credentials/service-credential-detail.tsx`
- `frontend/components/managed/credentials/mcp-vault-detail.tsx`（凭证组）

三处详情页常驻引用面板；**归档/删除确认弹窗内嵌同一组件**——`!can_archive`（或 `!can_delete`）时弹窗内 `disabled` 提交并展示列表（按钮本身仍可点）。

### 5.3 并发 409 兜底（兼容新旧两种 data 形态）

`getOperationErrorMessage`（`errors.ts:59`）加 `CREDENTIAL_IN_USE` 分支：
- 若 `data.references` 存在（enforce/新形态）→ 弹窗内联渲染同一组件；
- 若只有旧形态（`data.agents/triggers/environments/sessions` 或 `data.dependency_ids`，shadow 期）→ 至少渲染计数/概要，不弹一句笼统 toast。
这确保 shadow→enforce 过渡期前端都不静默失败。

### 5.4 前端测试守卫

- **源文件计数守卫**：`frontend/lib/i18n/credential-terminology.test.ts` 的 `sourceFileCount` 是硬编码计数。新增组件/hook 文件后，按**本次新增数量**上调该字面量（勿吸收他人未提交文件）。
- 若组件命名触发组件 allowlist 守卫，按既有约定登记。

## 6. 边界情况

- **shadow 模式一致性**：读接口（scanner 视图）的 `can_archive` 可能与遗留门禁短暂不一致——这是迁移 shadow 期的固有现象，由既有 shadow-diff 日志监控，`enforce` 后收敛。前端 fallback（§5.3）兜住过渡期的形态差异。
- **并发绑定**（打开时干净、提交时被占）→ 弹窗内联刷新阻塞项。
- **实体改名/删除于扫描与渲染之间** → 名称可能过期；链接失效则目标页优雅 404。
- **会话 title 为空** → 前端回退「会话 {短 id}」。
- **legacy 阻塞不可导航** → 计入 `other_count` + 门禁，渲染为不可点汇总行（不静默）。
- **project 隔离**：所有扫描/名称查询沿用 `project_id` 过滤。

## 7. 测试计划

**后端**
- 组装器单测：4 live surface 各映射正确（surface/type/name/route 字段）；两环境 surface 合并去重；非映射阻塞聚合为 other + 计数；`can_archive/can_delete` 含 other。
- 名称查询端口：批量解析、project 隔离、缺失 id 优雅缺省。
- 读接口测试：空、各 surface、组会话、含 other、project 隔离。
- 协调器 enforce 409：`data.references` + `other_count` 形态正确。
- 回归：确认遗留 `_reject_if_in_use` 未破坏（本轮不改）。

**前端**
- `<CredentialReferences>`：分组、链接路由、other 行不可点、空不渲染、会话空名回退。
- 确认弹窗：`!can_archive` 时提交 `disabled` 且展示列表。
- 并发 409 fallback：新形态内联渲染；旧形态渲染概要（均不弹笼统 toast）。

## 8. 非目标（YAGNI）

- 不扫描/展示非阻塞审计类引用（quickstart / skill 创作 / `agent_version` 历史快照的 REVALIDATE 项）——本轮只做阻塞项。
- 不为 legacy 阻塞项做逐项名称/导航（异构 source，退役在即）——仅 other 汇总兜底。
- 不做"一键解绑"批量操作——只做导向（跳转）。
- 不改造遗留 `_reject_if_in_use` 的 data 形态（随迁移退役；前端 fallback 兼容）。
- `can_archive`/`can_delete` 逻辑本轮等价（都=无阻塞），保留双字段备未来区分。

## 9. 共享地基边界（与服务凭证 create-flow initiative 的分工）

本 spec **拥有** where-used 共享地基，`project_joysafeter_service_credential_creation_ux` **消费**它，不重建：

| 产物 | 归属 | 消费方如何用 |
|---|---|---|
| `GET /credentials/{id}/references` + `useCredentialReferences` | 本 spec | 服务凭证详情页"被使用于 · N 处"直接调用；"N" = `references.length`（不含 `other_count`） |
| `<CredentialReferences variant>` 组件 | 本 spec | 详情页用 `variant="informational"`；本 spec 的确认弹窗用 `variant="blocker"` |
| 引用消费面 = agents / triggers / environments / sessions | 本 spec（scanner 已限定） | 消费方**照此 4 类**渲染，**不做 demo 里示意的"skill 消费方"**（skill 非 tracked surface） |

**明确划归对方、本 spec 不做**：服务卡片选择、per-service 字段模板（`GET /credentials/service-templates`）、3 步引导表单、列表行"🔗 N 处使用"徽标（若需列表级计数，由对方在 list 响应加计数字段，本 spec 不为此改 list 接口）、"补齐凭据"反向入口。

**协作纪律**（两条线都改 `service-credential-detail.tsx`）：本 spec 只负责把 `<CredentialReferences>` 挂到详情页与确认弹窗；表单/模板区块归对方。按不同 section 改，避免互相 clobber。

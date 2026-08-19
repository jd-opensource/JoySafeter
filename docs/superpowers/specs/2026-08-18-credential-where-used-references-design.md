# 凭证「谁在用 / 哪些流程」分层引用视图 — 设计

- 日期：2026-08-18
- 分支：joysafeter-v2-0814
- 相关：`project_joysafeter_service_credential_creation_ux`（本设计实现其"凭证详情展示 where-used"这条双向可见性轴）

## 1. 问题

归档/删除一个仍被引用的凭证时，用户看到一句笼统的英文报错
`Credential is still referenced and cannot be archived or deleted`。三个诉求全部落空——**谁在用、哪些流程、分层呈现**——根因是同一个：

1. 后端 `CredentialDependencies.as_data()`（`backend/app/joysafeter_infrastructure/credentials/sqlalchemy_repository.py:181`）只产出**扁平的裸 UUID 数组** `{agents:[…], triggers:[…], environments:[…], sessions:[…]}`：无名称、无流程标签。
2. 前端 `getOperationErrorMessage`（`frontend/lib/managed/errors.ts:59`）**没有 `CREDENTIAL_IN_USE` 分支**，直接落到"显示原始英文 message"，并把 `data` 整个丢弃。
3. 用户只能在动作**失败后**才看到信息，且无从据此操作。

领域里其实早有一套引用面分类 `CREDENTIAL_REFERENCE_SURFACES`（`backend/app/joysafeter_domain/credentials/dependencies.py:168`，含 `owner` 与 `kind`），但实际扫描从未产出带标签、带名称的结果。

## 2. 已确认的产品决策

| 维度 | 决策 |
|---|---|
| 呈现时机 | **提前展示**：凭证/凭证组详情页常驻 + 归档/删除确认弹窗内嵌；动作之前即可见 |
| 引用项形态 | **名称 + 可点击跳转** 到对应 agent/环境/触发器/会话 |
| 展示范围 | **只显示阻塞项**（真正阻止归档/删除的引用）；"分层"= 按流程类型分组 |
| 覆盖对象 | **凭证（模型连接 + 服务凭据）和凭证组 / MCP Vault 都做** |
| 阻塞时按钮 | **按钮可点，确认弹窗内阻止提交** 并展示阻塞列表 |

## 3. 架构

三个独立单元，各自单一职责，通过明确契约通信：

- **引用扫描器（后端 repository）**：给定 credential/group + project，产出结构化引用列表。
- **引用读接口（后端 API）**：把扫描结果暴露为只读 GET；同一份数据也塞进 409 报错。
- **引用视图（前端组件）**：把结构化列表分层渲染成可点击的"谁在用"面板；详情页与确认弹窗共用。

数据流：`详情页/弹窗挂载 → GET …/references → 分层渲染`；`归档/删除 409 → data.references → 弹窗内联渲染同一组件`。

## 4. 后端

### 4.1 引用项的结构化模型

`CredentialDependencies`（`sqlalchemy_repository.py:168`）现有四条查询只 `select(<Model>.id)`。改为每条同时取名称列，并给每条打一个**稳定机器枚举 `surface`**（取值对齐 `CREDENTIAL_REFERENCE_SURFACES.owner`）：

| surface（机器码） | 来源模型 | 名称列 | resource_type | 前端路由 |
|---|---|---|---|---|
| `agent_model_binding` | `JoySafeterAgent` | `name`（非空） | `agent` | `/managed/agents/{id}` |
| `trigger_webhook_auth` | `JoySafeterTrigger` | `name`（非空） | `trigger` | `/managed/triggers/{id}` |
| `environment_injection` | `JoySafeterEnvironment` | `name`（非空） | `environment` | `/managed/environments/{id}` |
| `active_session_snapshot` | `JoySafeterSession` | `title`（可空 → 回退） | `session` | `/managed/sessions/{id}` |

> 会话名来自 `JoySafeterSession.title`（`joysafeter_session.py:55`，nullable）；为空时后端返回 `name=null`，由前端回退为「会话 {短 id}」。后端不拼中文，保持 i18n 无关。

新增方法：

```python
@dataclass
class CredentialReferenceItem:
    surface: str          # "agent_model_binding" | ...
    resource_type: str    # "agent" | "trigger" | "environment" | "session"
    id: str
    name: str | None

class CredentialDependencies:
    ...
    def as_references(self) -> list[dict]:
        """扁平列表，每项 {surface, resource_type, id, name}，供 API 与 409 共用。"""
```

`in_use` 语义不变。环境的 name 需在现有 `_config_references_credential` 过滤（`sqlalchemy_repository.py:1009`）时一并 select 出来。

### 4.2 只读引用接口（提前展示的关键）

- `GET /api/v1/credentials/{credential_id}/references`
- `GET /api/v1/credential-groups/{group_id}/references`

响应 DTO：

```
CredentialReferencesResponse {
  references: CredentialReferenceItem[]   # 仅阻塞项，已分组前的扁平列表
  can_archive: bool
  can_delete: bool
}
CredentialReferenceItem { surface, resource_type, id, name }
```

两个 handler 与 `_reject_if_in_use` / `_reject_group_lifecycle_blockers` **调用同一个扫描 + builder**，保证提前展示与 409 报错零漂移。`can_archive` / `can_delete` 在"只显示阻塞项"决策下等价于 `not references`；保留两个布尔字段以便未来区分（当前实现二者相同）。

凭证组扫描（`_reject_group_lifecycle_blockers`，`sqlalchemy_repository.py:1341`）只产出 `active_session_snapshot` 引用。

### 4.3 409 `CREDENTIAL_IN_USE` 复用同一结构

`_reject_if_in_use`（`:1032`）与组路径（`:1344`）的 `data` 由：

```
{credential_id, agents:[uuid], triggers:[uuid], environments:[uuid], sessions:[uuid]}
```

改为：

```
{credential_id (或 credential_group_id), references:[{surface, resource_type, id, name}]}
```

`error_catalog.py:52` 的英文 `default_message` **保持不变**（i18n 交前端）。**这会改变 `as_data()` 的现有形态，所有消费该字段的测试一并更新**（系统化，不留旧形态双写）。

### 4.4 后端不需要的东西

- **无 DB 迁移**：只读取既有列（agent/trigger/environment.name、session.title），无 schema 变更 → 不触发 alembic single-head 守卫。
- **无新错误码**：复用既有 `CREDENTIAL_IN_USE` → 不触发 error-catalog 注册守卫。

## 5. 前端

### 5.1 共享组件 + 数据 hook

- `useCredentialReferences(id)` / `useCredentialGroupReferences(id)`：拉 §4.2 的新接口。
- `<CredentialReferences references={…} />`：按 `surface` **分层分组**，每组一个本地化流程标题 + 计数，每项名称是 `<Link>` 跳到 §4.1 表中的路由。空列表时不渲染。

本地化流程标题（新增 i18n key，中/英）：

| surface | 中 | 英 |
|---|---|---|
| `agent_model_binding` | 模型绑定 | Model binding |
| `trigger_webhook_auth` | Webhook 鉴权 | Webhook auth |
| `environment_injection` | 环境注入 | Environment injection |
| `active_session_snapshot` | 活跃会话 | Active session |

外加一条标题文案 key（如"以下位置正在使用，请先解绑："）。

### 5.2 接入点

- `frontend/components/managed/credentials/model-connection-detail.tsx`
- `frontend/components/managed/credentials/service-credential-detail.tsx`
- `frontend/components/managed/credentials/mcp-vault-detail.tsx`（凭证组）

三处详情页常驻展示引用面板；**归档/删除确认弹窗内嵌同一组件**——`references.length > 0` 时弹窗内 `disabled` 提交并展示列表（按钮本身仍可点）。

### 5.3 并发 409 兜底

`getOperationErrorMessage`（`errors.ts:59`）加 `CREDENTIAL_IN_USE` 分支：万一打开弹窗后别人刚绑定导致提交仍 409，弹窗捕获后**内联重渲染** `data.references`，而非弹一句笼统 toast。这正是"按钮可点、弹窗内阻止"的价值。

### 5.4 前端测试守卫

- **源文件计数守卫**：`frontend/lib/i18n/credential-terminology.test.ts` 的 `sourceFileCount` 是硬编码计数。新增组件/hook 文件后，按**本次新增数量**上调该字面量（勿吸收他人未提交文件）。
- 若组件命名触发组件 allowlist 守卫，按既有约定登记。

## 6. 边界情况

- **并发绑定**（打开时干净、提交时被占）→ 弹窗内联刷新阻塞项。
- **扫描与渲染间实体被改名/删除** → 名称可能过期；链接失效则目标页优雅 404。可接受。
- **会话 title 为空** → 前端回退「会话 {短 id}」。
- **project 隔离**：所有扫描沿用现有 `project_id` 过滤，不跨项目泄漏。

## 7. 测试计划

**后端**
- 扩展依赖扫描测试：断言每项含正确 `surface` + `name`（各来源一例）。
- 新接口测试：空引用、四类 surface 各一、组会话引用、project 隔离。
- 409 payload 形态测试：`data.references` 结构正确。
- 更新所有旧 `as_data()`（agents/triggers/environments/sessions 数组形态）消费方与断言。

**前端**
- `<CredentialReferences>`：分组正确、链接指向正确路由、空列表不渲染、会话空名回退。
- 确认弹窗：有阻塞项时提交被 `disabled` 且展示列表。
- 并发 409：捕获后内联渲染 references（不弹笼统 toast）。

## 8. 非目标（YAGNI）

- 不扫描非阻塞/审计类引用面（quickstart / skill 创作 / 历史版本快照 / legacy）——本轮只做阻塞项。
- 不做"一键解绑"批量操作——只做导向（跳转），解绑仍在各实体页完成。
- `can_archive`/`can_delete` 本轮不做差异化（二者相同）。

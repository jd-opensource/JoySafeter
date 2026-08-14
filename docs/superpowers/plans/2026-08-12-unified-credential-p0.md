# 统一凭据架构 P0（数据骨干）实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: 用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现。步骤用 `- [ ]` 勾选跟踪。

**Goal:** 把凭据/模型/鉴权域从"按名字引用 + secrets/vaults 双表"一次切换为"统一 `joysafeter_credentials` 表 + 全按 ID 引用"，落地后**产品仍可用**（含前端机械适配）。

**Architecture:** 合并 secrets + vaults/vault_credentials 为单表（kind∈{model,mcp,service}）；引用统一按 `CredentialId`（标量列用原生 FK、多值用关联表、Environment JSON 用写校验+删扫描+行锁、Session 快照字段改 ID）；运行时 Envoy 边界不动，仅把 4 个解析器 + run_spec 快照切到按 ID 读统一表并收敛 MCP URL 到单一规范化。预发布无数据 → 折进初始 alembic、无兼容/回填。

**Tech Stack:** Python 3.12 + SQLAlchemy 2.0 async + Alembic + FastAPI；Rust orchestrator（sqlx + tonic）；Next.js/React/TS 前端；pytest / cargo test / vitest。

## Global Constraints（每个任务隐含包含）

- **后端测试**：`cd backend && uv run pytest`（绝不在 repo 根跑裸 `pytest`——config 只在 `backend/pyproject.toml`，根目录跑会 strict-asyncio 全挂）。
- **预发布**：无历史数据。**折进初始迁移** `backend/alembic/versions/20260803_000001_initial_schema.py`，squash `20260807_000002_post_initial_schema_compatibility.py`；**不做** dual_read/回填/cutover/兼容列。
- **单头 alembic**：改完 `alembic heads` 必须单头（project_joysafeter_test_guards #2）。
- **错误码**：每个 emit 的 code 必须注册进 `error_catalog.py`，`gen_error_catalog --audit` 必须过（project_joysafeter_test_guards #1）。
- **typed-id 架构测试**：新增/改动 EntityId 必须同步 `backend/app/tests/test_typed_id_architecture.py` 的枚举元组（否则架构测试挂）。
- **加密信封**：`enc:v1:` 前缀；Python `CredentialCipher` 与 Rust `VaultCipher` 必须互通，用共享测试向量锁死。**不做密钥轮换（YAGNI）**。
- **命名**：后端 kind=model/mcp/service；不引入 UI 词汇（前端本阶段仅机械适配，保持现有 IA）。trigger 入站鉴权字段一次命名到位：`webhook_auth_credential_id` / `webhook_auth_field`。
- **project_id NOT NULL**（先核查无全局 seed 脚本，Task 2）。

---

## 文件结构（改动映射）

**后端 models**（`backend/app/joysafeter_domain/models/`）
- 新建 `joysafeter_credential.py`（`JoySafeterCredential` + `JoySafeterCredentialGroup` + `JoySafeterSessionCredentialGroup`）
- 删除 `joysafeter_secret.py`、`joysafeter_vault.py`
- 改 `joysafeter_agent.py`（`secret_ref`→`model_credential_id`）、`joysafeter_session.py`（去 `vault_ids`；`agent_snapshot` 内字段语义改 ID）、`joysafeter_trigger.py`（`secret_ref`/`secret_key`→`webhook_auth_credential_id`/`webhook_auth_field`）
- `models/__init__.py`（注册新模型、删旧模型 import）

**后端 schemas / services / routes**
- 新建 `schemas/joysafeter_credential.py`、`services/joysafeter_credential_service.py`、`services/joysafeter_credential_group_service.py`、`api/v1/credentials.py`、`api/v1/credential_groups.py`
- 删除 `services/joysafeter_secret_service.py`、`services/joysafeter_vault_service.py`、`api/v1/secrets.py`、`api/v1/vaults.py`
- 改 `api/v1/router.py`（换路由）、`api/v1/network_policy_refresh.py`（改为可在调用方事务内 mark-pending，不自 commit）
- 复用 `security/credential_cipher.py`（加 `v1` 信封）；新建 `joysafeter_shared/mcp_url.py`（规范化）

**共享 / 保护测试**
- `joysafeter_shared/ids.py`、`app/tests/test_typed_id_architecture.py`、`joysafeter_shared/common/error_catalog.py`

**Rust**（`backend/app/joysafeter_orchestrator_rs/src/`）
- `kernel/sandbox_resolver.rs`（4 解析器切按-ID/统一表）、`kernel/harness_input_builder.rs`（vault→credentials 表、URL 规范化、多组冲突）、`kernel/run_spec.rs`（快照字段改 ID）、加 `kernel/credential_store.rs`（`get_by_id`）、`kernel/mcp_url.rs`（规范化，与 Python 向量一致）

**前端**（`frontend/`）—— 机械适配，保持 IA
- `lib/managed/api-paths.ts`、`lib/managed/*-response-parsers.ts`、`app/managed/secrets/**`、`app/managed/vaults/**`、`components/managed/llm/*`、`components/managed/environments-egress-editor.tsx`、`components/managed/triggers/create-trigger-dialog.tsx`、`app/managed/sessions/components/create-session-dialog.tsx`、`hooks/managed/use-quickstart-chat.ts`、`lib/i18n/locales/{en,zh}.ts`（仅改 key/字段，不改词汇）

**迁移**：`alembic/versions/20260803_000001_initial_schema.py`（折入），删 `20260807_000002_*.py`

---

## 决策锚点（贯穿全计划）

- **统一表列**：`id: CredentialId` PK / `project_id NOT NULL` FK / `kind` / `name` / `data JSONB` / `provider,protocol`(model) / `is_default`(model) / `mcp_server_url,normalized_mcp_server_url,credential_type,oauth_config`(mcp) / `group_id`(mcp,NOT NULL by CHECK) / `archived_at,deleted_at`。
- **CHECK kind_identity**：model→provider+protocol，禁 mcp_*；mcp→mcp_server_url+group_id，禁 provider/protocol/is_default；service→禁 provider/protocol/mcp_*/group_id 且 is_default=false。
- **唯一索引**（全 `WHERE deleted_at IS NULL`）：`(project_id,kind,name)`；`(project_id,protocol) WHERE is_default AND kind='model' AND archived_at IS NULL`；`(group_id,normalized_mcp_server_url) WHERE kind='mcp'`。
- **复合 FK**：`credential_groups UNIQUE(id,project_id)` + `credentials(group_id,project_id)→credential_groups(id,project_id)`。
- **不可变**：`kind`、`provider`、`protocol`、`mcp_server_url`、`group_id`（改=删旧建新）；可改 `name`/`data`/`is_default`/`archived_at`。
- **错误码（12）**：`CREDENTIAL_NOT_FOUND` `CREDENTIAL_KIND_INVALID` `CREDENTIAL_NAME_EXISTS` `CREDENTIAL_IN_USE` `CREDENTIAL_ARCHIVED` `CREDENTIAL_FIELD_MISSING` `CREDENTIAL_FIELD_INVALID` `CREDENTIAL_MASK_CONFLICT` `CREDENTIAL_PROTOCOL_INCOMPATIBLE` `CREDENTIAL_GROUP_NOT_FOUND` `CREDENTIAL_GROUP_URL_CONFLICT` `CREDENTIAL_ENCRYPTION_CONFIG_MISSING`。

---

## Task 1: Typed IDs

**Files:**
- Modify: `backend/app/joysafeter_shared/ids.py`（`SecretId:117` 删；`VaultId:141` 删；`CredentialId:145` 保留复用；新增 `CredentialGroupId`）
- Modify: `backend/app/tests/test_typed_id_architecture.py`（枚举元组）
- Test: 同上

**Interfaces:**
- Produces: `CredentialId(prefix="cred_")`、`CredentialGroupId(prefix="credgrp_")`；`SecretId`/`VaultId` 不再存在。

- [ ] **Step 1: 写失败测试**（`test_typed_id_architecture.py` 加断言 + 新 id round-trip）
```python
def test_credential_group_id_roundtrip():
    from app.joysafeter_shared.ids import CredentialGroupId
    cid = CredentialGroupId.new()
    assert str(cid).startswith("credgrp_")
    assert CredentialGroupId.from_public(str(cid)) == cid

def test_secret_and_vault_ids_removed():
    import app.joysafeter_shared.ids as ids
    assert not hasattr(ids, "SecretId")
    assert not hasattr(ids, "VaultId")
```
- [ ] **Step 2: 跑测试确认失败**：`cd backend && uv run pytest app/tests/test_typed_id_architecture.py -k "credential_group or removed" -v` → FAIL。
- [ ] **Step 3: 实现**：`ids.py` 删 `SecretId`/`VaultId` 类；`CredentialId` 保留（`prefix="cred_"`）；新增：
```python
class CredentialGroupId(EntityId):
    prefix = "credgrp_"
```
更新 `test_typed_id_architecture.py` 里所有列出全部 EntityId 子类的元组（删 SecretId/VaultId，加 CredentialGroupId；CredentialId 已在）。
- [ ] **Step 4: 跑测试确认通过**：`cd backend && uv run pytest app/tests/test_typed_id_architecture.py -v` → PASS（注意：此时全项目其它 import SecretId/VaultId 处会红——由后续任务清理；本任务只保证 ids + 架构测试）。
- [ ] **Step 5: 提交**：`git add backend/app/joysafeter_shared/ids.py backend/app/tests/test_typed_id_architecture.py && git commit -m "refactor(ids): retire SecretId/VaultId, add CredentialGroupId, reuse CredentialId"`

---

## Task 2: 统一表 models + 折入初始迁移

**Files:**
- Create: `backend/app/joysafeter_domain/models/joysafeter_credential.py`
- Delete: `models/joysafeter_secret.py`, `models/joysafeter_vault.py`
- Modify: `models/__init__.py`, `alembic/versions/20260803_000001_initial_schema.py`
- Delete: `alembic/versions/20260807_000002_post_initial_schema_compatibility.py`
- Test: `backend/app/tests/test_credential_schema.py`（新建）

**Interfaces:**
- Produces: `JoySafeterCredential`(table `joysafeter_credentials`)、`JoySafeterCredentialGroup`(`joysafeter_credential_groups`)、`JoySafeterSessionCredentialGroup`(`joysafeter_session_credential_groups`)，列/约束见"决策锚点"。

- [ ] **Step 0: 核查全局 seed**：`git grep -n "project_id=None\|project_id is None" backend/app | rg -i secret\|vault` + 检查 `deploy/`、`scripts/`、`conftest` 有无创建全局凭据的 seed。无 → 落 `project_id NOT NULL`；有 → 记录并回报评审。
- [ ] **Step 1: 写失败测试**（schema 存在性 + CHECK）
```python
import pytest
from sqlalchemy import inspect
from app.joysafeter_domain.models.joysafeter_credential import JoySafeterCredential, JoySafeterCredentialGroup

@pytest.mark.asyncio
async def test_credentials_table_shape(db_session):
    cols = {c.name for c in JoySafeterCredential.__table__.columns}
    assert {"id","project_id","kind","name","data","provider","protocol","is_default",
            "mcp_server_url","normalized_mcp_server_url","credential_type","oauth_config",
            "group_id","archived_at","deleted_at"} <= cols
    assert JoySafeterCredential.__table__.columns["project_id"].nullable is False
```
- [ ] **Step 2: 跑确认失败**：`cd backend && uv run pytest app/tests/test_credential_schema.py -v` → FAIL（模型不存在）。
- [ ] **Step 3: 建模型** `joysafeter_credential.py`（按"决策锚点"列/CHECK/唯一索引/复合 FK；`JoySafeterBaseModel` 提供 created_at/updated_at）。`JoySafeterSessionCredentialGroup`：`session_id` FK、`credential_group_id` FK、`UNIQUE(session_id, credential_group_id)`。`models/__init__.py`：删 secret/vault import，加新模型（alembic 发现 + `_clean_tables` 需要）。
- [ ] **Step 4: 折入迁移**：把 `joysafeter_secrets`/`joysafeter_vaults`/`joysafeter_vault_credentials` 的 `op.create_table` 从初始迁移**替换**为 `joysafeter_credentials`/`joysafeter_credential_groups`/`joysafeter_session_credential_groups`（含索引/CHECK/复合 FK）；删 `20260807_000002_*.py`；确认 `down_revision` 链单头。
- [ ] **Step 5: 跑确认通过 + alembic 单头**：`cd backend && uv run pytest app/tests/test_credential_schema.py -v` → PASS；`cd backend && uv run alembic heads`（单头）。
- [ ] **Step 6: 提交**：`git add ... && git commit -m "feat(credentials): unified credentials/groups schema folded into initial migration"`

---

## Task 3: 加密信封 v1 + 跨语言向量

**Files:**
- Modify: `backend/app/joysafeter_shared/security/credential_cipher.py`
- Create: `backend/app/tests/fixtures/cipher_vectors.json`（Python/Rust 共享）
- Modify: Rust `.../src/**/vault_cipher.rs`（或等价 cipher 模块）
- Test: `backend/app/tests/test_credential_cipher.py` + Rust cipher 单测

**Interfaces:**
- Produces: `CredentialCipher.encrypt(str)->"enc:v1:..."`、`decrypt_stored("enc:v1:..."|"enc:...")->str`（读兼容无版本前缀的既有 `enc:`，写一律 v1）。

- [ ] **Step 1: 写失败测试**：加密输出以 `enc:v1:` 开头；解密 `cipher_vectors.json` 中每条 `{plaintext, ciphertext}` 得到 plaintext。
- [ ] **Step 2: 跑确认失败**。
- [ ] **Step 3: 实现**：encrypt 加 `v1:` 段；decrypt 解析可选版本段（无版本按 legacy 解）。用固定 key + 向量在 Python 生成 `cipher_vectors.json`；Rust `VaultCipher` 单测读同一 json 断言互通。
- [ ] **Step 4: 跑确认通过**：`cd backend && uv run pytest app/tests/test_credential_cipher.py -v`；`cargo test -p <cipher crate> cipher_vectors`（在 `backend/app/joysafeter_orchestrator_rs`）。
- [ ] **Step 5: 提交**。

---

## Task 4: MCP URL 单一规范化契约（Python + Rust 向量）

**Files:**
- Create: `backend/app/joysafeter_shared/mcp_url.py`、`backend/app/tests/fixtures/mcp_url_vectors.json`
- Create: Rust `.../src/kernel/mcp_url.rs`
- Test: `backend/app/tests/test_mcp_url.py` + Rust 单测

**Interfaces:**
- Produces: `normalize_mcp_url(raw: str) -> str`（lowercase host、去尾 `/`、默认端口归一、**保留 query**、去 fragment）——单一规范形（取代运行时多候选键匹配）。

- [ ] **Step 1: 写失败测试**：对 `mcp_url_vectors.json` 中 `{raw, normalized}` 断言相等（含大小写 host、尾斜杠、`:443`/`:80` 归一、带 query 的用例）。
- [ ] **Step 2: 跑确认失败**。
- [ ] **Step 3: 实现** Python `normalize_mcp_url`；Rust `mcp_url::normalize` 读同一 vectors 断言一致。
- [ ] **Step 4: 跑确认通过**（pytest + cargo test）。
- [ ] **Step 5: 提交**。

---

## Task 5: CredentialService（Resource CRUD + data 契约 + 掩码 + 生命周期 + 锁）

**Files:**
- Create: `backend/app/joysafeter_domain/schemas/joysafeter_credential.py`、`services/joysafeter_credential_service.py`
- Test: `backend/app/tests/test_credential_service.py`

**Interfaces:**
- Consumes: `CredentialCipher`(T3)、`normalize_mcp_url`(T4)、`CredentialId`(T1)、models(T2)。
- Produces:
  - `CredentialService.create(req, project_id) -> JoySafeterCredential`
  - `.get(cred_id, project_id) -> Optional[...]`；`.list(project_id, kind=None, ...)`
  - `.update(cred_id, req, project_id)`（掩码保留语义）
  - `.set_default(cred_id, project_id)`；`.archive/.restore/.soft_delete(cred_id, project_id)`
  - `.mask_data(dict)->dict`、`.get_masked(cred)`（沿用 `_is_display_safe_secret_key` 白名单）
  - `.dependencies(cred_id, project_id)`（扫 agent 列 / trigger 列 / env config / session 关联表 / **活跃会话快照**；供删除/归档 in-use 判定）
  - `.lock_credential(cred_id)`（`SELECT ... FOR UPDATE`，供并发写用）

- [ ] **Step 1: 写失败测试**（多用例，一组）
```python
@pytest.mark.asyncio
async def test_create_model_requires_provider_protocol(db_session): ...   # kind=model 缺 provider → CREDENTIAL_FIELD_MISSING
async def test_name_unique_per_kind(db_session): ...                       # 同 kind 同名 → CREDENTIAL_NAME_EXISTS；不同 kind 同名 → ok
async def test_update_preserves_masked_value(db_session): ...             # 传入 ******** → 保留原值(merge_update_plaintext 语义)
async def test_detail_masks_sensitive(db_session): ...                     # get_masked 脱敏非白名单键
async def test_delete_in_use_rejected(db_session): ...                     # 被 agent 引用 → CREDENTIAL_IN_USE
async def test_kind_immutable(db_session): ...                             # 改 kind → 拒绝
```
- [ ] **Step 2: 跑确认失败**。
- [ ] **Step 3: 实现** service（移植 `joysafeter_secret_service.py` 的 encrypt/decrypt/mask/merge_update_plaintext/`_is_display_safe_secret_key`；扩展 kind 校验、data 上限校验、mcp 写 `normalized_mcp_server_url`、生命周期与 dependencies 扫描含活跃会话快照）。data 契约：扁平 `dict[str,str]`、字段数/键长/值大小上限。
- [ ] **Step 4: 跑确认通过**：`cd backend && uv run pytest app/tests/test_credential_service.py -v`。
- [ ] **Step 5: 提交**。

---

## Task 6: CredentialGroupService（分组 CRUD + 成员 + URL 冲突拒绝 + 变更审计/刷新）

**Files:**
- Modify: `schemas/joysafeter_credential.py`；Create: `services/joysafeter_credential_group_service.py`
- Test: `backend/app/tests/test_credential_group_service.py`

**Interfaces:**
- Produces:
  - `CredentialGroupService.create/get/list/archive/soft_delete(...)`
  - `.add_member(group_id, cred_id, project_id)`（cred 必须 kind=mcp、同项目；**同组 normalized url 唯一**）
  - `.remove_member(...)`、`.list_members(group_id, project_id)`
  - `.check_url_conflict_for_session(group_ids, project_id)`（多组 normalized url 交集 → `CREDENTIAL_GROUP_URL_CONFLICT`）
  - 成员增/移/归档 → 审计事件 + `refresh_live_...`（在同事务，见 T7）

- [ ] **Step 1: 写失败测试**：加成员到别项目组拒绝；同组重复 URL 拒绝；`check_url_conflict_for_session` 两组含同 URL → 冲突。
- [ ] **Step 2: 跑确认失败**。
- [ ] **Step 3: 实现**（成员变更走 T7 的原子事务 + 审计 + mark-pending）。
- [ ] **Step 4: 跑确认通过**。
- [ ] **Step 5: 提交**。

---

## Task 7: 原子变更 + 策略刷新（一次提交）

**Files:**
- Modify: `backend/app/joysafeter_api/api/v1/network_policy_refresh.py`（拆出 `mark_live_sandboxes_pending(db, ...)` 只做 UPDATE 不 commit；`refresh_live_limited_sandbox_network_policies` 调它 + 提交后 nudge）
- Modify: `credential_service.py`/`credential_group_service.py`（mutate 路径调 `mark_..._pending` 并入同事务，调用方一次 commit）
- Test: `backend/app/tests/test_credential_atomic_refresh.py`

**Interfaces:**
- Produces: `mark_live_sandboxes_pending(db, *, project_id, source_type, source_id) -> list[SandboxId]`（不 commit）；`refresh_live_...` = 事务外便捷封装（自 commit + nudge）保留给非凭据调用方。

- [ ] **Step 1: 写失败测试**：patch commit 计数——一次凭据更新只发生 1 次 commit，且被标 pending 的沙箱在同一事务可见（未提交前查得到）。
- [ ] **Step 2: 跑确认失败**。
- [ ] **Step 3: 实现**（mark-pending 与 mutation+audit 同事务；nudge 移到 commit 后 fire-and-forget）。
- [ ] **Step 4: 跑确认通过**。
- [ ] **Step 5: 提交**。

---

## Task 8: REST —— /credentials + /credential-groups

**Files:**
- Create: `api/v1/credentials.py`、`api/v1/credential_groups.py`；Modify: `api/v1/router.py`
- Delete: `api/v1/secrets.py`、`api/v1/vaults.py`
- Test: `backend/app/tests/test_credentials_api.py`

**Interfaces:**
- Produces（全 `require_joysafeter_write` 于写；读 reader 可见脱敏）:
  - `GET/POST /credentials`（`?kind=`）、`GET/PATCH/DELETE /credentials/{id}`、`POST /credentials/{id}/default`、`POST /credentials/{id}/archive`、`POST /credentials/{id}/restore`、`POST /credentials/test`（test-connection，移植 secrets/test）
  - `GET/POST /credential-groups`、`GET/DELETE /credential-groups/{id}`、`POST /credential-groups/{id}/archive`、`GET/POST /credential-groups/{id}/members`、`DELETE /credential-groups/{id}/members/{cred_id}`
  - 响应统一 `{success,code,message,data}`；detail 脱敏；每写审计。

- [ ] **Step 1: 写失败测试**（route-level：create→list→get 脱敏→default→archive→restore→delete-in-use 409；group members CRUD + URL 冲突 409）。
- [ ] **Step 2: 跑确认失败**。
- [ ] **Step 3: 实现** 两个 router（移植 `secrets.py`/`vaults.py` 的权限+审计+`refresh` 调用，改用 T5/T6/T7 service）；`router.py` 注册新、删旧。
- [ ] **Step 4: 跑确认通过**：`cd backend && uv run pytest app/tests/test_credentials_api.py -v`。
- [ ] **Step 5: 提交**。

---

## Task 9: 消费方引用切 ID（Python：Agent/Trigger/Environment/Session/快照）

**Files:**
- Modify: `models/joysafeter_agent.py`（`secret_ref`→`model_credential_id: CredentialId?` FK RESTRICT）、`models/joysafeter_trigger.py`（`secret_ref`/`secret_key`→`webhook_auth_credential_id: CredentialId?` FK + `webhook_auth_field`）、`models/joysafeter_session.py`（删 `vault_ids`）、`schemas/joysafeter_environment.py`（`egress_services[].credential_ref`→`service_credential_id`；`secret_refs`→id 列表）、`alembic/.../20260803_000001`（同步列 + FK）
- Modify: 相关 services（agent create/snapshot builder、trigger config/webhook auth、environment、session create）：`agent_snapshot` 内 `secret_ref`→`model_credential_id`、内嵌 env config 引用→ID；session 挂载写 `joysafeter_session_credential_groups`
- Modify: `services/*`（依赖扫描接 T5 `.dependencies`，含活跃会话快照）
- Test: `backend/app/tests/test_credential_references.py`

**Interfaces:**
- Consumes: T5/T6 service、models。
- Produces: Agent.`model_credential_id`、Trigger.`webhook_auth_credential_id`/`webhook_auth_field`、Session↔group 关联、snapshot 用 ID 字段。

- [ ] **Step 1: 写失败测试**：agent 绑定 `model_credential_id` 后创建 session→快照含该 ID；删该凭据→`CREDENTIAL_IN_USE`（含"仅活跃会话快照引用"用例）；trigger webhook auth 用新字段解析。
- [ ] **Step 2: 跑确认失败**。
- [ ] **Step 3: 实现**（模型列 + 迁移同步；snapshot builder；webhook auth service 改按 ID 取 service 凭据字段；session create 写关联表 + 调 T6 URL 冲突检查）。
- [ ] **Step 4: 跑确认通过**。
- [ ] **Step 5: 提交**。

---

## Task 10: Rust —— CredentialStore + 4 解析器 + run_spec 快照切 ID

**Files:**
- Create: `.../src/kernel/credential_store.rs`（`get_by_id(pool, id, project_id)`）
- Modify: `.../src/kernel/sandbox_resolver.rs`（`extract_llm_egress`/`build_external_egress` 按 `model_credential_id`/`service_credential_id` 读 `joysafeter_credentials WHERE id=$1 AND project_id=$2`，删 `WHERE name=... ORDER BY created_at DESC`；`build_mcp_egress` 按 group→成员）、`kernel/harness_input_builder.rs`（`resolve_vault_credentials`→按 session 关联表取 group→credentials，用 `mcp_url::normalize` 匹配，**多组同 url 冲突已在写入侧拒绝**，此处按规范化 url 单键 map）、`kernel/run_spec.rs`（`:76` `secret_ref`→`model_credential_id`；`:81` 快照 env config 引用按 ID）
- Test: Rust `#[sqlx::test]` in-crate 测试

**Interfaces:**
- Consumes: T2 表、T4 `mcp_url::normalize`。
- Produces: 按-ID 解析；无按名字 SQL。

- [ ] **Step 1: 写失败测试**（sqlx::test：插 credential + agent 绑 id → resolver 产出正确 EgressCredentialRoute；插两 group 同 url 已被写侧拒绝，故 resolver 输入无冲突）。
- [ ] **Step 2: 跑确认失败**：`cd backend/app/joysafeter_orchestrator_rs && cargo test <name>` → FAIL。
- [ ] **Step 3: 实现**（改 4 处 SQL 到统一表按 ID；run_spec 快照字段）。
- [ ] **Step 4: 跑确认通过 + 全 crate 编译**：`cargo test`；`cargo build`。
- [ ] **Step 5: 提交**。

---

## Task 11: 错误码目录

**Files:**
- Modify: `joysafeter_shared/common/error_catalog.py`（注册 12 个 CREDENTIAL_*；删 `SECRET_*`/`VAULT_*`/`LLM_SECRET_*`）
- Test: `gen_error_catalog --audit`

- [ ] **Step 1**：注册 12 码，删旧码。
- [ ] **Step 2: 审计**：`cd backend && uv run python -m <gen_error_catalog> --audit` → PASS（无未注册/无孤儿）。
- [ ] **Step 3: 提交**。

---

## Task 12: 前端机械适配（保持现有 IA）

**Files:**
- Modify: `lib/managed/api-paths.ts`、`lib/managed/{secret,vault,environment}-response-parsers.ts`（→credentials/groups + ID 字段）、`app/managed/secrets/**`、`app/managed/vaults/**`（改调新端点；页面结构/文案不动）、`components/managed/llm/llm-secret-configurator.tsx`（POST `/credentials` kind=model）、`environments-egress-editor.tsx`（`credential_ref`(name)→`service_credential_id`(id) 的下拉 value）、`create-trigger-dialog.tsx`（webhook 字段→id）、`create-session-dialog.tsx` + `use-quickstart-chat.ts`（vault_ids→credential_group_ids 关联）、`lib/i18n/locales/{en,zh}.ts`（仅改 key 引用，不改词汇）
- Test: 相关 `*.test.tsx`（断言新端点/新 body 字段）

- [ ] **Step 1: 改测试**（dialog mock 断言 `mutateAsync.calls[0][0].body` 用新字段/端点）。
- [ ] **Step 2: 跑确认失败**：`cd frontend && npx vitest run <files>`。
- [ ] **Step 3: 实现** 机械改动（端点、字段名、by-id 引用；egress 下拉 value 由 `secret.name`→`credential.id`）。
- [ ] **Step 4: 跑确认通过 + 类型/lint**：`cd frontend && npx vitest run <files> && npx tsc --noEmit && npm run lint`。
- [ ] **Step 5: 提交**。

---

## Task 13: 删除旧面 + 残留清理

**Files:**
- Delete: 旧 model/service/route/schema（若前序未删净）；`git grep` 清 `secret_ref`/`vault_ids`/`SecretId`/`VaultId`/`get_secret_by_name` 残留
- Modify: `models/__init__.py`、任何遗留 import
- Test: 全后端 + 全 crate + 前端

- [ ] **Step 1: 残留扫描**：`git grep -n "SecretId\|VaultId\|secret_ref\|vault_ids\|/secrets\|/vaults\|get_secret_by_name" backend frontend` → 只应剩注释/文档/历史迁移无关项；逐一清理。
- [ ] **Step 2: 全链路测试**：`cd backend && uv run pytest`（全绿）；`cd backend/app/joysafeter_orchestrator_rs && cargo test && cargo build`；`cd frontend && npx vitest run && npx tsc --noEmit && npm run lint`。
- [ ] **Step 3: 提交**。

---

## Task 14: 端到端冒烟（本地栈，可选但推荐）

- [ ] **Step 1**：`cd deploy && ./deploy.sh doctor && ./deploy.sh local`。
- [ ] **Step 2**：建 model 凭据 → 建 agent 绑定 → 建 mcp 凭据库 + 成员 → 建 session 挂 group → 发一条消息，确认 Envoy 注入正常、沙箱看不到真实密钥（`grep -a` 校验，参 memory pi 镜像陷阱）。
- [ ] **Step 3**：改 model 凭据 → 确认在线沙箱策略被刷新（networking_status=pending → reconcile）。

---

## Self-Review（对 spec 核对）

- **覆盖**：spec §3.3 表/约束→T2；§3.5 引用+快照→T9/T10；§3.5b 组语义+URL 冲突→T6；§3.6 生命周期→T5/T9；§3.7 锁→T5/T6；§3.8 原子刷新→T7；§3.9 data 契约→T5；§3.10 权限审计→T8；§3.13 错误码→T11；§3.14 OAuth→**明确留 P2B，不在本计划**；§3.3 URL 规范化→T4/T10。
- **快照引用面**（第二轮审计 Blocker 1）→ T5 dependencies + T9 snapshot + T10 run_spec，均覆盖。
- **P0 只建 3 表**（Session→Group），grant 关联表留 P2A → T2 已限定。
- **无占位**：各任务给出接口签名 + 真实测试骨架 + 移植来源 file:line；移植类任务（T10 Rust、T12 前端）给出确切目标端点/字段与验证命令。
- **待计划内定**：`credentg_`? 前缀（用 `credgrp_`，Task 1 已定）；query 是否参与 URL 身份（Task 4 定：保留 query）；全局 seed（Task 2 Step 0 核查）。

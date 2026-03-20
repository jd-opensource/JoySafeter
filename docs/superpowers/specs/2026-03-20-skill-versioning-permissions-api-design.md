# Skill 多版本管理、团队协作权限、通用 Token 鉴权 设计文档

**日期**: 2026-03-20
**状态**: 设计完成，待实现

## 概述

为 Skill 系统新增三大能力：

1. **语义版本发布** — 发布后不可变，单 draft 编辑模式
2. **团队协作权限** — Skill 独立协作者体系（viewer/editor/publisher/admin）
3. **通用 Token 鉴权** — PlatformToken，支持 scope 控制，完整 CRUD + 发布 API

## 设计原则

- 现有 `skills` 和 `skill_files` 表零改动，已有数据自动成为 draft
- Skill 独立于 workspace，不引入 workspace 关联
- 新增表纯增量，Alembic migration 不影响线上数据
- 现有 API 行为不变，新增端点扩展能力

---

## 1. 数据模型

### 1.1 SkillVersion 表（新增）

存储已发布的不可变版本快照。

| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID | 主键 |
| skill_id | UUID FK → skills.id | 所属 Skill |
| version | String(20) | semver 版本号，仅 MAJOR.MINOR.PATCH 格式 |
| release_notes | Text | 发布说明 / changelog |
| skill_name | String(64) | 快照：发布时的 skill 名称 |
| skill_description | String(1024) | 快照：发布时的 skill 描述 |
| content | Text | 快照：skill body |
| tags | JSONB | 快照 |
| meta_data | JSONB | 快照 |
| allowed_tools | JSONB | 快照 |
| compatibility | String(500) | 快照 |
| license | String(100) | 快照 |
| published_by_id | String FK → user.id | 发布人 |
| published_at | DateTime(tz) | 发布时间 |
| created_at | DateTime(tz) | 继承自 BaseModel（updated_at 也会继承，值始终等于 created_at） |

**约束**:
- UniqueConstraint(`skill_id`, `version`)
- Index on `skill_id`
- Index on `published_at`

**版本号规则**:
- 仅接受 `MAJOR.MINOR.PATCH` 格式（如 `1.0.0`），不支持 pre-release 或 build metadata
- 使用 `semver` PyPI 包进行解析和比较（避免字符串排序导致 `1.10.0 < 1.9.0` 的错误）
- 新版本号必须大于已有最高版本

### 1.2 SkillVersionFile 表（新增）

版本文件快照，结构同 SkillFile，关联到 version。

| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID | 主键 |
| version_id | UUID FK → skill_versions.id | 所属版本 |
| path | String(512) | 相对路径 |
| file_name | String(255) | 文件名 |
| file_type | String(50) | 文件类型 |
| content | Text | 文件内容 |
| storage_type | String(20) | database/s3 |
| storage_key | String(512) | 外部存储键（可选） |
| size | Integer | 文件大小 |

**约束**:
- Index on `version_id`
- Cascade delete with SkillVersion

### 1.3 SkillCollaborator 表（新增）

Skill 级别的协作者权限管理，独立于 workspace。

| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID | 主键 |
| skill_id | UUID FK → skills.id | 所属 Skill |
| user_id | String FK → user.id | 协作者 |
| role | Enum | admin / publisher / editor / viewer |
| invited_by | String FK → user.id | 邀请人 |
| created_at | DateTime(tz) | 邀请时间 |

**约束**:
- UniqueConstraint(`skill_id`, `user_id`) — 自动创建 (skill_id, user_id) 复合索引
- Index on (`user_id`, `skill_id`) — 用于反向查询（用户有权访问哪些 skill）
- `invited_by` 字段 NOT NULL，始终设为执行操作的用户

**角色权限矩阵**:

| 操作 | owner | admin | publisher | editor | viewer |
|------|-------|-------|-----------|--------|--------|
| 查看 skill | Y | Y | Y | Y | Y |
| 编辑 draft | Y | Y | Y | Y | - |
| 发布版本 | Y | Y | Y | - | - |
| 删除版本 | Y | Y | - | - | - |
| 管理协作者 | Y | Y | - | - | - |
| 删除 skill | Y | - | - | - | - |
| 转让 ownership | Y | - | - | - | - |

### 1.4 PlatformToken 表（新增）

通用 Token 鉴权，支持多种资源类型，未来可扩展。

| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID | 主键 |
| user_id | String FK → user.id | Token 归属人 |
| name | String(255) | 用户自定义名称 |
| token_hash | String(64) | SHA-256 哈希值 |
| token_prefix | String(12) | 如 "sk_abc1..." 用于识别 |
| scopes | JSONB | ["skills:read", "skills:write", ...] |
| resource_type | String(50) | 可选，如 "skill"/"workspace"/"graph" |
| resource_id | UUID | 可选，绑定到特定资源实例 |
| expires_at | DateTime(tz) | 过期时间（可选） |
| last_used_at | DateTime(tz) | 最后使用时间 |
| is_active | Boolean | 是否有效，default True |
| created_at | DateTime(tz) | 创建时间 |

**约束**:
- Unique on `token_hash`
- Index on `user_id`
- Index on `token_hash`
- Index on `is_active`

**限制**:
- 每用户最多 50 个 active token（创建时校验，达到上限返回 400）
- 已撤销（is_active=False）的 token 不计入额度

**与现有 ApiKey 的关系**: 并行存在，互不影响。现有 ApiKey 继续服务已有功能，未来可选迁移但不在本次范围。

---

## 2. API 设计

### 2.1 版本管理 API

```
POST   /v1/skills/{skill_id}/versions           # 发布新版本
GET    /v1/skills/{skill_id}/versions           # 列出所有已发布版本
GET    /v1/skills/{skill_id}/versions/latest    # 获取最新发布版本
GET    /v1/skills/{skill_id}/versions/{version} # 获取特定版本详情
DELETE /v1/skills/{skill_id}/versions/{version} # 删除版本（admin+）
POST   /v1/skills/{skill_id}/restore            # 基于历史版本恢复 draft
```

**发布请求体**:
```json
{
  "version": "1.2.0",
  "release_notes": "新增 X 功能，修复 Y 问题"
}
```

**恢复请求体**:
```json
{
  "version": "1.0.0"
}
```

**规则**:
- 版本号需符合 semver `MAJOR.MINOR.PATCH` 格式（使用 `semver` 库解析），且大于已有最高版本
- 发布时把当前 draft 的 content + name + description + files 完整快照
- SkillVersion 创建后无 update 接口，天然不可变
- 恢复操作覆盖 draft，不影响任何已发布版本
- `GET /v1/skills/{id}` 增加 `latest_version` 字段指向最新已发布版本

### 2.2 协作者管理 API

```
GET    /v1/skills/{skill_id}/collaborators              # 列出协作者
POST   /v1/skills/{skill_id}/collaborators              # 添加协作者
PUT    /v1/skills/{skill_id}/collaborators/{user_id}    # 修改角色
DELETE /v1/skills/{skill_id}/collaborators/{user_id}    # 移除协作者
POST   /v1/skills/{skill_id}/transfer                   # 转让 ownership
```

**添加协作者请求体**:
```json
{
  "user_id": "xxx",
  "role": "editor"
}
```

**转让请求体**:
```json
{
  "new_owner_id": "xxx"
}
```

**转让规则**:
- 仅 owner 可发起转让
- 转让后旧 owner 自动成为 admin 协作者（不会失去访问权）
- `created_by_id` 不变（保留创建历史）
- 必须校验新 owner 是否已有同名 skill（`UniqueConstraint(owner_id, name)`），冲突时返回明确错误

### 2.3 Token 管理 API

```
POST   /v1/tokens          # 创建 token（返回明文，仅此一次）
GET    /v1/tokens          # 列出我的 tokens（不含明文，显示 prefix）
DELETE /v1/tokens/{id}     # 撤销 token（soft delete: is_active = False）
```

**创建请求体**:
```json
{
  "name": "CI deploy token",
  "scopes": ["skills:read", "skills:write", "skills:publish"],
  "resource_type": "skill",
  "resource_id": "xxx-optional",
  "expires_at": "2026-12-31T00:00:00Z"
}
```

**创建响应**（仅此一次返回明文）:
```json
{
  "id": "uuid",
  "name": "CI deploy token",
  "token": "sk_a1b2c3d4e5f6...",
  "token_prefix": "sk_a1b2c3d4",
  "scopes": ["skills:read", "skills:write", "skills:publish"],
  "expires_at": "2026-12-31T00:00:00Z"
}
```

---

## 3. 鉴权流程

### 3.1 双模式鉴权 Dependency

```
请求进入
  → get_current_user_or_token()
      1. 检查 session cookie → 如有则返回 AuthUser (scopes=None，走角色权限)
      2. 检查 Authorization: Bearer 头
         ├── token 以 "sk_" 开头 → PlatformToken 路径
         │     → sha256(token) → 查 platform_tokens.token_hash
         │     → 校验 is_active + expires_at
         │     → 异步更新 last_used_at（仅当距上次更新 >5 分钟时写入，减少 DB 压力）
         │     → 返回 (AuthUser, scopes)
         └── 否则 → 走现有 JWT/session token 解析流程
```

**关键规则**:
- `sk_` 前缀是 PlatformToken 的唯一判定标识，与现有 JWT token 不会冲突
- Token 管理 API（`POST/GET/DELETE /v1/tokens`）仅支持 session 鉴权，不允许用 PlatformToken 管理 PlatformToken
- PlatformToken 访问 skill 版本时，必须同时满足 scope 和 is_public/collaborator 权限

### 3.2 Skill 权限校验函数

```python
async def check_skill_access(
    skill: Skill,
    user_id: str,
    min_role: CollaboratorRole,
    token_scopes: Optional[List[str]] = None,
    required_scope: Optional[str] = None,
) -> None:
    """
    统一权限校验，替代现有 owner_id != current_user_id 硬编码。

    逻辑:
    1. 是 owner → 通过
    2. 查 SkillCollaborator → 角色 >= min_role → 通过
    3. skill.is_public + min_role == viewer → 通过
    4. 否则 → 403

    如果是 token 请求，额外校验:
    5. token_scopes 包含 required_scope → 通过
    6. 否则 → 403
    """
```

### 3.3 操作 → 角色 + Scope 映射

| 操作 | 最低角色 | 所需 Scope |
|------|---------|-----------|
| 读取 skill / 版本列表 | viewer | `skills:read` |
| 编辑 draft / 文件 | editor | `skills:write` |
| 发布版本 | publisher | `skills:publish` |
| 删除版本 | admin | `skills:admin` |
| 管理协作者 | admin | `skills:admin` |
| 删除 skill | owner | `skills:admin` |

---

## 4. 版本发布流程

### 4.1 发布

```
POST /v1/skills/{id}/versions  { version: "1.0.0", description: "..." }
    │
    ├── 校验权限 >= publisher
    ├── 校验 semver MAJOR.MINOR.PATCH 格式 & 大于最高已有版本（使用 semver 库比较）
    ├── 创建 SkillVersion（快照 skill_name/skill_description/content/tags/metadata/allowed_tools/compatibility/license）
    ├── 复制当前 SkillFile → SkillVersionFile（逐条复制内容）
    └── 返回 SkillVersion 详情
```

- 发布后 draft 不清空，继续可编辑
- SkillVersion 无 update 接口

### 4.2 基于历史版本恢复 Draft

```
POST /v1/skills/{id}/restore  { version: "1.0.0" }
    │
    ├── 校验权限 >= publisher（恢复是破坏性操作，覆盖整个 draft）
    ├── 读取 SkillVersion 的内容和文件
    ├── 覆盖 Skill draft content + 删除旧 SkillFile + 写入版本文件
    └── 返回更新后的 Skill（draft 状态）
```

### 4.3 版本消费

- 外部使用者通过 API token 或商店获取的是已发布版本
- PlatformToken 访问版本时需同时满足 scope (`skills:read`) 和 is_public/collaborator 权限
- `GET /v1/skills/{id}` 继续返回 draft content（后向兼容），增加 `latest_version` 字段
- Draft 内容对 viewer 继续可见（兼容现有行为），未来可通过 query param `?version=1.0.0` 获取指定版本内容

---

## 5. Token 生命周期

### 5.1 创建

```
生成 token: "sk_" + 48 字符随机串 (secrets.token_urlsafe)
存储: token_prefix = 前 12 字符, token_hash = sha256(full_token)
返回明文 token（仅此一次，不落库）
```

### 5.2 使用

```
请求头: Authorization: Bearer sk_xxxxxxxxx
后端: sha256(token) → 查 platform_tokens.token_hash
校验: is_active + expires_at + scopes
更新: last_used_at
注入: user context 继续走权限链
```

### 5.3 撤销

```
DELETE /v1/tokens/{id}
→ is_active = False（软删除，保留审计记录）
```

---

## 6. 迁移策略

### 6.1 数据库迁移

- 新增 4 张表: `skill_versions`, `skill_version_files`, `skill_collaborators`, `platform_tokens`
- 现有 `skills`, `skill_files` 表零改动
- 所有已有 Skill 数据自动成为 draft 状态
- 现有 skill 的 `owner_id` 用户自动拥有 owner 权限，无需数据迁移

### 6.2 代码改动

- `SkillService` 中所有 `owner_id != current_user_id` 硬编码替换为 `check_skill_access()` 调用
- `SkillRepository.list_by_user()` 查询条件扩展：`OR skill_id IN (SELECT skill_id FROM skill_collaborators WHERE user_id = :user_id)`，确保协作者能看到被授权的私有 skill
- 同步影响 `DatabaseSkillAdapter` 和 `skills_manager.py` 中的 skill 加载逻辑（它们都依赖 `list_skills()`）
- 新增 `SkillVersionService` 处理版本 CRUD
- 新增 `SkillCollaboratorService` 处理协作者管理
- 新增 `PlatformTokenService` 处理 token 管理
- 新增 FastAPI dependency `get_current_user_or_token()` 支持双模式鉴权
- 新增 API 路由文件: `skill_versions.py`, `skill_collaborators.py`, `tokens.py`

### 6.3 与现有 ApiKey 的关系

- PlatformToken 与 ApiKey 并行，互不影响
- 现有 ApiKey 继续服务已有功能
- 不在本次范围内做迁移

---

## 7. 影响范围

### 新增文件
- `backend/app/models/skill_version.py`
- `backend/app/models/skill_collaborator.py`
- `backend/app/models/platform_token.py`
- `backend/app/schemas/skill_version.py`
- `backend/app/schemas/skill_collaborator.py`
- `backend/app/schemas/platform_token.py`
- `backend/app/repositories/skill_version.py`
- `backend/app/repositories/skill_collaborator.py`
- `backend/app/repositories/platform_token.py`
- `backend/app/services/skill_version_service.py`
- `backend/app/services/skill_collaborator_service.py`
- `backend/app/services/platform_token_service.py`
- `backend/app/api/v1/skill_versions.py`
- `backend/app/api/v1/skill_collaborators.py`
- `backend/app/api/v1/tokens.py`
- `backend/app/common/auth_dependency.py` (双模式鉴权)
- `backend/app/common/skill_permissions.py` (统一权限校验)
- Alembic migration 文件

### 修改文件
- `backend/app/services/skill_service.py` — 权限检查替换为 `check_skill_access()`
- `backend/app/api/v1/skills.py` — 注入新鉴权 dependency
- `backend/app/models/__init__.py` — 注册新模型
- `backend/app/api/v1/__init__.py` — 注册新路由
- `frontend/services/skillService.ts` — 新增版本/协作者/token API 调用
- `frontend/app/skills/SkillsManager.tsx` — 版本管理 UI、协作者管理 UI
- `backend/app/api/v1/skills.py` — OpenClaw sync：协作者编辑时，同步 owner 的容器（不仅是当前用户的）

# Skill 前端：版本管理、协作者管理、Token 管理 设计文档

**日期**: 2026-03-23
**状态**: 设计完成，待实现
**依赖**: `2026-03-20-skill-versioning-permissions-api-design.md`（后端已实现）

## 概述

为 Skill 系统前端新增三大功能的完整 UI 实现：

1. **版本历史 Tab** — 在 Skill 编辑器内新增 Tab，支持发布版本、查看历史、恢复 draft、删除版本
2. **协作者管理 Tab** — 在 Skill 编辑器内新增 Tab，支持添加/移除协作者、修改角色、转让所有权
3. **API Tokens 页面** — 在全局 Settings 对话框中新增页签，支持创建/列出/撤销 Token

## 设计原则

- 遵循现有前端架构模式（React Query + Service Layer + shadcn/ui）
- 版本和协作者属于 Skill 级别，UI 放在 SkillsManager 编辑区域
- Token 属于用户级别，UI 放在全局 Settings 对话框
- i18n 双语支持（en + zh）
- 所有 API 调用通过 `@/lib/api-client` 的 `apiGet/apiPost/apiPut/apiDelete`

---

## 1. UI 布局

### 1.1 Skill 编辑器区域（SkillsManager）

在现有编辑器区域上方新增 Tab 栏：

```
┌─────────────────────────────────────────────┐
│ Skill Name        [Save] [Publish ▾]        │
├─────────────────────────────────────────────┤
│ [编辑器] [文件] [版本历史] [协作者]           │
│ ─────────────────────────────────────────── │
│ (Tab 对应的内容区)                           │
└─────────────────────────────────────────────┘
```

- **编辑器 Tab**: 现有的代码编辑器（默认选中）
- **文件 Tab**: 现有的文件树 + 编辑器布局
- **版本历史 Tab**: 新增，展示版本列表和发布入口
- **协作者 Tab**: 新增，展示协作者列表和管理操作

**注意**: 当前 SkillsManager 为三栏布局（sidebar w-52 + file tree w-48 + editor flex-1）。新增的 Tab 栏只在编辑器区域（flex-1）切换内容，sidebar 和 file tree 不受影响。当用户切换到"版本历史"或"协作者" Tab 时，file tree 面板可保持显示但不强制（编辑器内容区替换为对应 Tab 内容）。

### 1.2 Settings 对话框

在 `settings-dialog.tsx` 的侧栏新增 "API Tokens" 菜单项：

```
Settings
├── Profile
├── Models
├── Sandboxes
└── API Tokens  ← 新增
```

---

## 2. 版本历史 Tab

### 2.1 布局

版本历史 Tab 内置发布入口（方案 B）：

```
┌──────────────────────────────────────┐
│ [+ 发布新版本]                        │
│ ┌ 版本号: [1.3.0]                    │
│ │ Release Notes: [___________]       │
│ └                    [发布]          │
│ ────────────────────────────────────│
│ v1.2.0  2026-03-20  by Alice        │
│   新增 X 功能       [恢复] [删除]    │
│ v1.1.0  2026-03-15  by Bob          │
│   修复 Y 问题       [恢复] [删除]    │
│ v1.0.0  2026-03-10  by Alice        │
│   初始发布          [恢复] [删除]    │
└──────────────────────────────────────┘
```

### 2.2 交互逻辑

- **发布新版本**: 点击 "发布新版本" 按钮展开内联表单（版本号 input + release notes textarea）。表单使用 react-hook-form + Zod 校验版本号格式（`MAJOR.MINOR.PATCH`）。提交后调用 `POST /v1/skills/{skill_id}/versions`。
- **版本列表**: 调用 `GET /v1/skills/{skill_id}/versions` 获取所有已发布版本，按 `published_at` 降序排列。每条显示版本号、发布时间、发布人、release notes。
- **恢复 draft**: 点击 "恢复" 弹出确认 Dialog（"恢复将覆盖当前 draft，是否继续？"），确认后调用 `POST /v1/skills/{skill_id}/restore`。成功后 invalidate skill 查询，刷新编辑器内容。
- **删除版本**: 点击 "删除" 弹出确认 Dialog（"删除版本不可恢复，是否继续？"），确认后调用 `DELETE /v1/skills/{skill_id}/versions/{version}`。
- **权限控制**: 根据用户角色显示/隐藏操作按钮：

| 角色 | 可见操作 |
|------|---------|
| viewer | 只读版本列表，无操作按钮 |
| editor | 只读版本列表，无操作按钮 |
| publisher | 发布新版本、恢复 draft（无删除） |
| admin / owner | 发布、恢复、删除（全部操作） |

### 2.3 数据模型（TypeScript）

```typescript
interface SkillVersion {
  id: string
  skillId: string
  version: string
  releaseNotes: string | null
  skillName: string
  skillDescription: string
  content: string
  tags: string[]
  metadata: Record<string, unknown>
  allowedTools: string[]
  compatibility: string | null
  license: string | null
  publishedById: string
  publishedAt: string | null
  createdAt: string | null
  files: SkillVersionFile[] | null
}

interface SkillVersionFile {
  id: string
  versionId: string
  path: string
  fileName: string
  fileType: string
  content: string | null
  storageType: string
  storageKey: string | null
  size: number
}

// 列表接口使用轻量 summary（需扩展后端 VersionSummarySchema 以包含 published_by_id）
interface SkillVersionSummary {
  version: string
  releaseNotes: string | null
  publishedById: string
  publishedAt: string | null
}
```

---

## 3. 协作者管理 Tab

### 3.1 布局

内联列表 + 行内操作（方案 A）：

```
┌──────────────────────────────────────┐
│ [+ 添加协作者]                        │
│ ────────────────────────────────────│
│ 👤 Alice (owner)                     │
│ 👤 Bob     [editor ▾]          [✕]  │
│ 👤 Carol   [viewer ▾]          [✕]  │
│ ────────────────────────────────────│
│              [🔄 转让所有权]          │
└──────────────────────────────────────┘
```

### 3.2 交互逻辑

- **添加协作者**: 点击 "添加协作者" 展开内联表单（用户 ID input + 角色 Select），提交调用 `POST /v1/skills/{skill_id}/collaborators`。v1 使用原始用户 ID 输入，后续迭代可升级为用户搜索/自动补全。
- **修改角色**: 角色通过 Select 下拉框直接修改，onChange 调用 `PUT /v1/skills/{skill_id}/collaborators/{user_id}`。可选角色：viewer、editor、publisher、admin。
- **移除协作者**: 点击 ✕ 弹出确认 Dialog，确认后调用 `DELETE /v1/skills/{skill_id}/collaborators/{user_id}`。
- **转让所有权**: 点击 "转让所有权" 弹出 Dialog（选择目标用户），确认后调用 `POST /v1/skills/{skill_id}/transfer`。仅 owner 可见此按钮。转让后旧 owner 自动降为 admin。
- **权限控制**: 仅 owner 和 admin 可见此 Tab 的管理操作。其他角色看到只读列表。
- **Owner 行**: owner 不显示角色下拉框和删除按钮，仅显示 "(owner)" 标记。Owner 不在 `skill_collaborators` 表中，前端需从 `skill.owner_id` 读取并作为列表首行展示。

### 3.3 数据模型（TypeScript）

```typescript
type CollaboratorRole = 'viewer' | 'editor' | 'publisher' | 'admin'

interface SkillCollaborator {
  id: string
  skillId: string
  userId: string
  role: CollaboratorRole
  invitedBy: string
  createdAt: string | null
}
```

---

## 4. API Tokens 页面

### 4.1 布局

卡片列表式（方案 A），放在 Settings 对话框内：

```
┌──────────────────────────────────────┐
│ Settings > API Tokens                │
│ ────────────────────────────────────│
│ [+ Create Token]                     │
│                                      │
│ ┌──────────────────────────────────┐│
│ │ CI deploy token        [Revoke] ││
│ │ sk_a1b2c3d4                     ││
│ │ [read] [write] [publish]        ││
│ │ Expires: 2026-12-31             ││
│ │ Last used: 2h ago               ││
│ └──────────────────────────────────┘│
│ ┌──────────────────────────────────┐│
│ │ Local dev token        [Revoke] ││
│ │ sk_x9y8z7w6                     ││
│ │ [read]                          ││
│ │ No expiry                       ││
│ │ Last used: never                ││
│ └──────────────────────────────────┘│
└──────────────────────────────────────┘
```

### 4.2 交互逻辑

- **创建 Token**: 点击 "Create Token" 弹出 Dialog（name input + scopes 多选 + expires_at 日期选择器）。提交调用 `POST /v1/tokens`。成功后弹出明文 token 显示 Dialog（带复制按钮），提示"此 token 仅显示一次，请妥善保管"。关闭后无法再次查看明文。**注意**: `resource_type` 和 `resource_id` 字段在 v1 不暴露到创建 UI，保留给未来资源级 token 隔离使用。
- **Token 列表**: 调用 `GET /v1/tokens` 获取当前用户所有 token。每张卡片显示：name、token_prefix、scopes（Badge 标签）、expires_at（格式化为日期或 "No expiry"）、last_used_at（相对时间或 "never"）。
- **撤销 Token**: 点击 "Revoke" 弹出确认 Dialog（"撤销后使用此 token 的 API 调用将立即失败"），确认后调用 `DELETE /v1/tokens/{id}`。
- **可用 Scopes**: `skills:read`、`skills:write`、`skills:publish`、`skills:admin`。以 Checkbox 组形式展示在创建 Dialog 中。

### 4.3 数据模型（TypeScript）

```typescript
interface PlatformToken {
  id: string
  name: string
  tokenPrefix: string
  scopes: string[]
  resourceType: string | null
  resourceId: string | null
  expiresAt: string | null
  lastUsedAt: string | null
  isActive: boolean
  createdAt: string | null
}

// 创建响应（含明文 token，仅返回一次）
interface PlatformTokenCreateResponse {
  id: string
  name: string
  token: string  // plaintext, shown only once
  tokenPrefix: string
  scopes: string[]
  expiresAt: string | null
}
```

---

## 5. Service Layer

### 5.1 `services/skillVersionService.ts`（新增）

```typescript
export const skillVersionService = {
  publishVersion(skillId: string, data: { version: string; release_notes?: string }),
  listVersions(skillId: string): Promise<SkillVersionSummary[]>,
  getVersion(skillId: string, version: string): Promise<SkillVersion>,
  getLatestVersion(skillId: string): Promise<SkillVersion>,
  deleteVersion(skillId: string, version: string),
  restoreDraft(skillId: string, data: { version: string }): Promise<Skill>,  // returns updated draft Skill, not SkillVersion
}
```

API 路径映射：
| 方法 | 路径 |
|------|------|
| `publishVersion` | `POST /skills/{skill_id}/versions` |
| `listVersions` | `GET /skills/{skill_id}/versions` |
| `getVersion` | `GET /skills/{skill_id}/versions/{version}` |
| `getLatestVersion` | `GET /skills/{skill_id}/versions/latest` |
| `deleteVersion` | `DELETE /skills/{skill_id}/versions/{version}` |
| `restoreDraft` | `POST /skills/{skill_id}/restore` |

### 5.2 `services/skillCollaboratorService.ts`（新增）

```typescript
export const skillCollaboratorService = {
  listCollaborators(skillId: string): Promise<SkillCollaborator[]>,
  addCollaborator(skillId: string, data: { user_id: string; role: CollaboratorRole }),
  updateRole(skillId: string, userId: string, data: { role: CollaboratorRole }),
  removeCollaborator(skillId: string, userId: string),
  transferOwnership(skillId: string, data: { new_owner_id: string }),
}
```

API 路径映射：
| 方法 | 路径 |
|------|------|
| `listCollaborators` | `GET /skills/{skill_id}/collaborators` |
| `addCollaborator` | `POST /skills/{skill_id}/collaborators` |
| `updateRole` | `PUT /skills/{skill_id}/collaborators/{user_id}` |
| `removeCollaborator` | `DELETE /skills/{skill_id}/collaborators/{user_id}` |
| `transferOwnership` | `POST /skills/{skill_id}/transfer` |

### 5.3 `services/platformTokenService.ts`（新增）

```typescript
export const platformTokenService = {
  createToken(data: TokenCreateRequest): Promise<PlatformTokenCreateResponse>,
  listTokens(): Promise<PlatformToken[]>,
  revokeToken(tokenId: string),
}
```

API 路径映射：
| 方法 | 路径 |
|------|------|
| `createToken` | `POST /tokens` |
| `listTokens` | `GET /tokens` |
| `revokeToken` | `DELETE /tokens/{id}` |

---

## 6. React Query Hooks

### 6.1 `hooks/queries/skillVersions.ts`（新增）

```typescript
export const skillVersionKeys = {
  all: ['skill-versions'] as const,
  list: (skillId: string) => [...skillVersionKeys.all, 'list', skillId] as const,
  detail: (skillId: string, version: string) => [...skillVersionKeys.all, 'detail', skillId, version] as const,
  latest: (skillId: string) => [...skillVersionKeys.all, 'latest', skillId] as const,
}

export function useSkillVersions(skillId: string)           // useQuery → listVersions
export function useSkillVersion(skillId: string, v: string) // useQuery → getVersion
export function usePublishVersion(skillId: string)          // useMutation → publishVersion, invalidates list
export function useDeleteVersion(skillId: string)           // useMutation → deleteVersion, invalidates list
export function useRestoreDraft(skillId: string)            // useMutation → restoreDraft, invalidates skill detail
```

### 6.2 `hooks/queries/skillCollaborators.ts`（新增）

```typescript
export const skillCollaboratorKeys = {
  all: ['skill-collaborators'] as const,
  list: (skillId: string) => [...skillCollaboratorKeys.all, 'list', skillId] as const,
}

export function useSkillCollaborators(skillId: string)        // useQuery → listCollaborators
export function useAddCollaborator(skillId: string)           // useMutation → addCollaborator, invalidates list
export function useUpdateCollaboratorRole(skillId: string)    // useMutation → updateRole, invalidates list
export function useRemoveCollaborator(skillId: string)        // useMutation → removeCollaborator, invalidates list
export function useTransferOwnership(skillId: string)         // useMutation → transferOwnership, invalidates list + skill detail
```

### 6.3 `hooks/queries/platformTokens.ts`（新增）

```typescript
export const platformTokenKeys = {
  all: ['platform-tokens'] as const,
  list: () => [...platformTokenKeys.all, 'list'] as const,
}

export function usePlatformTokens()     // useQuery → listTokens
export function useCreateToken()        // useMutation → createToken, invalidates list
export function useRevokeToken()        // useMutation → revokeToken, invalidates list
```

---

## 7. UI 组件

### 7.1 新增组件

| 组件 | 路径 | 说明 |
|------|------|------|
| `VersionHistoryTab` | `app/skills/components/VersionHistoryTab.tsx` | 版本历史 Tab 内容，含发布表单和版本列表 |
| `CollaboratorsTab` | `app/skills/components/CollaboratorsTab.tsx` | 协作者管理 Tab 内容，含列表和内联操作 |
| `TokensPage` | `components/settings/tokens-page.tsx` | Token 管理页面，Settings 内嵌 |
| `CreateTokenDialog` | `components/settings/create-token-dialog.tsx` | 创建 Token Dialog（name + scopes + expiry） |
| `TokenCreatedDialog` | `components/settings/token-created-dialog.tsx` | 显示明文 token（仅一次），带复制按钮 |

### 7.2 修改组件

| 组件 | 修改内容 |
|------|---------|
| `app/skills/SkillsManager.tsx` | 编辑区域添加 Tab 栏（编辑器/文件/版本历史/协作者），管理 activeTab state |
| `components/settings/settings-dialog.tsx` | 侧栏新增 "API Tokens" MenuItem，内容区渲染 `TokensPage` |
| `lib/i18n/locales/en.ts` | 新增 skill versions / collaborators / tokens 相关翻译 key |
| `lib/i18n/locales/zh.ts` | 新增对应中文翻译 |

---

## 8. snake_case ↔ camelCase 转换

后端返回 snake_case（`skill_id`, `release_notes`, `published_at` 等），前端使用 camelCase。在 Service 层做转换：

- **Service 发送请求**: 直接使用 snake_case key（与后端 schema 一致）
- **Service 接收响应**: 用 normalizer helper 转为 camelCase（复用 `skillService.ts` 中已有的模式）
- **API 路径**: Service 层使用相对路径（如 `skills/${skillId}/versions`），`apiGet/apiPost` 等方法会自动拼接 `${API_BASE}` 前缀
- **metadata 字段**: 后端 Pydantic schema 使用 `validation_alias="meta_data"` + `populate_by_name=True`，序列化输出 key 为 `"metadata"`，与前端 camelCase 字段名一致

---

## 9. 错误处理

- 所有 mutation 使用 React Query 的 `onError` 回调，通过现有 toast 系统显示错误消息
- 版本号冲突（409）：显示"此版本号已存在，请使用更高版本号"
- 权限不足（403）：显示"您没有执行此操作的权限"
- 转让所有权时目标用户有同名 skill（409）：显示后端返回的具体错误消息
- Token 数量超限（400）：显示"已达 token 数量上限（50）"

---

## 10. 空状态与加载

- **版本列表为空**: 显示 "No versions published yet" 占位文本，引导用户发布第一个版本
- **协作者列表为空**: 仅显示 owner 行和 "添加协作者" 按钮
- **Token 列表为空**: 显示 "No API tokens created yet" 占位文本
- **加载中**: 使用 skeleton 占位（复用项目现有的 skeleton 组件），版本/协作者/Token 列表加载时各显示 2-3 行 skeleton

---

## 11. 后端适配（需同步修改）

为支持前端版本列表显示 "by Alice"，需扩展后端 `VersionSummarySchema`：

- `backend/app/schemas/skill_version.py` 的 `VersionSummarySchema` 新增 `published_by_id: str` 字段
- 可选：新增 `published_by_name: Optional[str]` 通过 join 获取用户名，避免前端额外查询

---

## 12. 文件清单

### 新增文件（11 个）
1. `frontend/services/skillVersionService.ts` — 版本 API 服务
2. `frontend/services/skillCollaboratorService.ts` — 协作者 API 服务
3. `frontend/services/platformTokenService.ts` — Token API 服务
4. `frontend/hooks/queries/skillVersions.ts` — 版本 React Query hooks
5. `frontend/hooks/queries/skillCollaborators.ts` — 协作者 React Query hooks
6. `frontend/hooks/queries/platformTokens.ts` — Token React Query hooks
7. `frontend/app/skills/components/VersionHistoryTab.tsx` — 版本历史 Tab UI
8. `frontend/app/skills/components/CollaboratorsTab.tsx` — 协作者管理 Tab UI
9. `frontend/components/settings/tokens-page.tsx` — Token 管理页面
10. `frontend/components/settings/create-token-dialog.tsx` — 创建 Token Dialog
11. `frontend/components/settings/token-created-dialog.tsx` — Token 明文展示 Dialog

### 修改文件（4 个）
1. `frontend/app/skills/SkillsManager.tsx` — 添加 Tab 栏和 Tab 内容切换
2. `frontend/components/settings/settings-dialog.tsx` — 添加 API Tokens 菜单项和页面
3. `frontend/lib/i18n/locales/en.ts` — 添加英文翻译
4. `frontend/lib/i18n/locales/zh.ts` — 添加中文翻译

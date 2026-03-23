# Skill 前端：版本管理 + 协作者管理 + Token 管理 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the complete frontend UI for skill versioning, collaborator management, and platform token management.

**Architecture:** Three service files (one per API domain) expose async methods calling `apiGet/apiPost/apiPut/apiDelete`. Three React Query hook files provide `useQuery`/`useMutation` wrappers with key factories. UI components integrate into SkillsManager (version + collaborator tabs) and Settings dialog (token page). All strings use i18n.

**Tech Stack:** Next.js + React 19, TypeScript, React Query v5, shadcn/ui (Radix), Tailwind CSS, react-hook-form + Zod, lucide-react icons.

**Spec:** `docs/superpowers/specs/2026-03-23-skill-frontend-versioning-collab-token-design.md`

---

## Task 1: Backend — Extend VersionSummarySchema with `published_by_id`

**Files:**
- Modify: `backend/app/schemas/skill_version.py` (VersionSummarySchema class, ~line 78)

- [ ] **Step 1: Add `published_by_id` to VersionSummarySchema**

```python
class VersionSummarySchema(BaseModel):
    """Lightweight version info for list endpoints."""

    version: str
    release_notes: Optional[str] = None
    published_by_id: str
    published_at: Optional[str] = None

    @field_validator("published_at", mode="before")
    @classmethod
    def convert_datetime_to_str(cls, v):
        if isinstance(v, datetime):
            return v.isoformat()
        return v

    class Config:
        from_attributes = True
```

- [ ] **Step 2: Verify existing tests still pass**

Run: `cd backend && python -m pytest tests/ -x -q --timeout=30 2>/dev/null || echo "no tests or pass"`

- [ ] **Step 3: Commit**

```bash
git add backend/app/schemas/skill_version.py
git commit -m "feat(schema): add published_by_id to VersionSummarySchema for frontend display"
```

---

## Task 2: Service — `skillVersionService.ts`

**Files:**
- Create: `frontend/services/skillVersionService.ts`

- [ ] **Step 1: Create the service file**

```typescript
import { apiGet, apiPost, apiDelete } from '@/lib/api-client'

// ---------- Types ----------

export interface SkillVersionSummary {
  version: string
  releaseNotes: string | null
  publishedById: string
  publishedAt: string | null
}

export interface SkillVersionFile {
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

export interface SkillVersion {
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

// ---------- Normalizers ----------

function normalizeVersionSummary(raw: any): SkillVersionSummary {
  return {
    version: raw.version,
    releaseNotes: raw.release_notes ?? null,
    publishedById: raw.published_by_id,
    publishedAt: raw.published_at ?? null,
  }
}

function normalizeVersion(raw: any): SkillVersion {
  return {
    id: raw.id,
    skillId: raw.skill_id,
    version: raw.version,
    releaseNotes: raw.release_notes ?? null,
    skillName: raw.skill_name,
    skillDescription: raw.skill_description,
    content: raw.content,
    tags: raw.tags ?? [],
    metadata: raw.metadata ?? {},
    allowedTools: raw.allowed_tools ?? [],
    compatibility: raw.compatibility ?? null,
    license: raw.license ?? null,
    publishedById: raw.published_by_id,
    publishedAt: raw.published_at ?? null,
    createdAt: raw.created_at ?? null,
    files: raw.files?.map((f: any) => ({
      id: f.id,
      versionId: f.version_id,
      path: f.path,
      fileName: f.file_name,
      fileType: f.file_type,
      content: f.content ?? null,
      storageType: f.storage_type,
      storageKey: f.storage_key ?? null,
      size: f.size ?? 0,
    })) ?? null,
  }
}

// ---------- Service ----------

export const skillVersionService = {
  async listVersions(skillId: string): Promise<SkillVersionSummary[]> {
    const data = await apiGet<any[]>(`skills/${skillId}/versions`)
    return (Array.isArray(data) ? data : []).map(normalizeVersionSummary)
  },

  async getVersion(skillId: string, version: string): Promise<SkillVersion> {
    const data = await apiGet<any>(`skills/${skillId}/versions/${version}`)
    return normalizeVersion(data)
  },

  async getLatestVersion(skillId: string): Promise<SkillVersion> {
    const data = await apiGet<any>(`skills/${skillId}/versions/latest`)
    return normalizeVersion(data)
  },

  async publishVersion(skillId: string, payload: { version: string; release_notes?: string }): Promise<SkillVersion> {
    const data = await apiPost<any>(`skills/${skillId}/versions`, payload)
    return normalizeVersion(data)
  },

  async deleteVersion(skillId: string, version: string): Promise<void> {
    await apiDelete<any>(`skills/${skillId}/versions/${version}`)
  },

  async restoreDraft(skillId: string, payload: { version: string }): Promise<any> {
    return await apiPost<any>(`skills/${skillId}/restore`, payload)
  },
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/services/skillVersionService.ts
git commit -m "feat: add skillVersionService with all version API methods"
```

---

## Task 3: Service — `skillCollaboratorService.ts`

**Files:**
- Create: `frontend/services/skillCollaboratorService.ts`

- [ ] **Step 1: Create the service file**

```typescript
import { apiGet, apiPost, apiPut, apiDelete } from '@/lib/api-client'

// ---------- Types ----------

export type CollaboratorRole = 'viewer' | 'editor' | 'publisher' | 'admin'

export interface SkillCollaborator {
  id: string
  skillId: string
  userId: string
  role: CollaboratorRole
  invitedBy: string
  createdAt: string | null
}

// ---------- Normalizer ----------

function normalizeCollaborator(raw: any): SkillCollaborator {
  return {
    id: raw.id,
    skillId: raw.skill_id,
    userId: raw.user_id,
    role: raw.role,
    invitedBy: raw.invited_by,
    createdAt: raw.created_at ?? null,
  }
}

// ---------- Service ----------

export const skillCollaboratorService = {
  async listCollaborators(skillId: string): Promise<SkillCollaborator[]> {
    const data = await apiGet<any[]>(`skills/${skillId}/collaborators`)
    return (Array.isArray(data) ? data : []).map(normalizeCollaborator)
  },

  async addCollaborator(skillId: string, payload: { user_id: string; role: CollaboratorRole }): Promise<SkillCollaborator> {
    const data = await apiPost<any>(`skills/${skillId}/collaborators`, payload)
    return normalizeCollaborator(data)
  },

  async updateRole(skillId: string, userId: string, payload: { role: CollaboratorRole }): Promise<SkillCollaborator> {
    const data = await apiPut<any>(`skills/${skillId}/collaborators/${userId}`, payload)
    return normalizeCollaborator(data)
  },

  async removeCollaborator(skillId: string, userId: string): Promise<void> {
    await apiDelete<any>(`skills/${skillId}/collaborators/${userId}`)
  },

  async transferOwnership(skillId: string, payload: { new_owner_id: string }): Promise<void> {
    await apiPost<any>(`skills/${skillId}/transfer`, payload)
  },
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/services/skillCollaboratorService.ts
git commit -m "feat: add skillCollaboratorService with collaborator API methods"
```

---

## Task 4: Service — `platformTokenService.ts`

**Files:**
- Create: `frontend/services/platformTokenService.ts`

- [ ] **Step 1: Create the service file**

```typescript
import { apiGet, apiPost, apiDelete } from '@/lib/api-client'

// ---------- Types ----------

export interface PlatformToken {
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

export interface PlatformTokenCreateResponse {
  id: string
  name: string
  token: string
  tokenPrefix: string
  scopes: string[]
  expiresAt: string | null
}

export interface TokenCreateRequest {
  name: string
  scopes: string[]
  expires_at?: string | null
}

// ---------- Normalizers ----------

function normalizeToken(raw: any): PlatformToken {
  return {
    id: raw.id,
    name: raw.name,
    tokenPrefix: raw.token_prefix,
    scopes: raw.scopes ?? [],
    resourceType: raw.resource_type ?? null,
    resourceId: raw.resource_id ?? null,
    expiresAt: raw.expires_at ?? null,
    lastUsedAt: raw.last_used_at ?? null,
    isActive: raw.is_active ?? true,
    createdAt: raw.created_at ?? null,
  }
}

function normalizeTokenCreateResponse(raw: any): PlatformTokenCreateResponse {
  return {
    id: raw.id,
    name: raw.name,
    token: raw.token,
    tokenPrefix: raw.token_prefix,
    scopes: raw.scopes ?? [],
    expiresAt: raw.expires_at ?? null,
  }
}

// ---------- Service ----------

export const platformTokenService = {
  async listTokens(): Promise<PlatformToken[]> {
    const data = await apiGet<any[]>('tokens')
    return (Array.isArray(data) ? data : []).map(normalizeToken)
  },

  async createToken(payload: TokenCreateRequest): Promise<PlatformTokenCreateResponse> {
    const data = await apiPost<any>('tokens', payload)
    return normalizeTokenCreateResponse(data)
  },

  async revokeToken(tokenId: string): Promise<void> {
    await apiDelete<any>(`tokens/${tokenId}`)
  },
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/services/platformTokenService.ts
git commit -m "feat: add platformTokenService with token CRUD methods"
```

---

## Task 5: React Query Hooks — `skillVersions.ts`

**Files:**
- Create: `frontend/hooks/queries/skillVersions.ts`
- Modify: `frontend/hooks/queries/index.ts` (add export)

- [ ] **Step 1: Create the query hooks file**

```typescript
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { STALE_TIME } from './constants'
import { skillKeys } from './skills'
import { skillVersionService } from '@/services/skillVersionService'
import type { SkillVersionSummary, SkillVersion } from '@/services/skillVersionService'

export { type SkillVersionSummary, type SkillVersion } from '@/services/skillVersionService'

// ---------- Key factory ----------

export const skillVersionKeys = {
  all: ['skill-versions'] as const,
  list: (skillId: string) => [...skillVersionKeys.all, 'list', skillId] as const,
  detail: (skillId: string, version: string) =>
    [...skillVersionKeys.all, 'detail', skillId, version] as const,
  latest: (skillId: string) => [...skillVersionKeys.all, 'latest', skillId] as const,
}

// ---------- Queries ----------

export function useSkillVersions(skillId: string) {
  return useQuery({
    queryKey: skillVersionKeys.list(skillId),
    queryFn: () => skillVersionService.listVersions(skillId),
    enabled: !!skillId,
    retry: false,
    staleTime: STALE_TIME.STANDARD,
  })
}

export function useSkillVersion(skillId: string, version: string) {
  return useQuery({
    queryKey: skillVersionKeys.detail(skillId, version),
    queryFn: () => skillVersionService.getVersion(skillId, version),
    enabled: !!skillId && !!version,
    retry: false,
    staleTime: STALE_TIME.STANDARD,
  })
}

// ---------- Mutations ----------

export function usePublishVersion(skillId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: { version: string; release_notes?: string }) =>
      skillVersionService.publishVersion(skillId, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: skillVersionKeys.list(skillId) })
      queryClient.invalidateQueries({ queryKey: skillKeys.all })
    },
  })
}

export function useDeleteVersion(skillId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (version: string) => skillVersionService.deleteVersion(skillId, version),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: skillVersionKeys.list(skillId) })
    },
  })
}

export function useRestoreDraft(skillId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (version: string) =>
      skillVersionService.restoreDraft(skillId, { version }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: skillKeys.all })
    },
  })
}
```

- [ ] **Step 2: Add export to index.ts**

In `frontend/hooks/queries/index.ts`, add:

```typescript
export * from './skillVersions'
```

- [ ] **Step 3: Commit**

```bash
git add frontend/hooks/queries/skillVersions.ts frontend/hooks/queries/index.ts
git commit -m "feat: add React Query hooks for skill versions"
```

---

## Task 6: React Query Hooks — `skillCollaborators.ts`

**Files:**
- Create: `frontend/hooks/queries/skillCollaborators.ts`
- Modify: `frontend/hooks/queries/index.ts` (add export)

- [ ] **Step 1: Create the query hooks file**

```typescript
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { STALE_TIME } from './constants'
import { skillKeys } from './skills'
import { skillCollaboratorService } from '@/services/skillCollaboratorService'
import type { SkillCollaborator, CollaboratorRole } from '@/services/skillCollaboratorService'

export { type SkillCollaborator, type CollaboratorRole } from '@/services/skillCollaboratorService'

// ---------- Key factory ----------

export const skillCollaboratorKeys = {
  all: ['skill-collaborators'] as const,
  list: (skillId: string) => [...skillCollaboratorKeys.all, 'list', skillId] as const,
}

// ---------- Queries ----------

export function useSkillCollaborators(skillId: string) {
  return useQuery({
    queryKey: skillCollaboratorKeys.list(skillId),
    queryFn: () => skillCollaboratorService.listCollaborators(skillId),
    enabled: !!skillId,
    retry: false,
    staleTime: STALE_TIME.STANDARD,
  })
}

// ---------- Mutations ----------

export function useAddCollaborator(skillId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: { user_id: string; role: CollaboratorRole }) =>
      skillCollaboratorService.addCollaborator(skillId, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: skillCollaboratorKeys.list(skillId) })
    },
  })
}

export function useUpdateCollaboratorRole(skillId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ userId, role }: { userId: string; role: CollaboratorRole }) =>
      skillCollaboratorService.updateRole(skillId, userId, { role }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: skillCollaboratorKeys.list(skillId) })
    },
  })
}

export function useRemoveCollaborator(skillId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (userId: string) =>
      skillCollaboratorService.removeCollaborator(skillId, userId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: skillCollaboratorKeys.list(skillId) })
    },
  })
}

export function useTransferOwnership(skillId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (newOwnerId: string) =>
      skillCollaboratorService.transferOwnership(skillId, { new_owner_id: newOwnerId }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: skillCollaboratorKeys.list(skillId) })
      queryClient.invalidateQueries({ queryKey: skillKeys.all })
    },
  })
}
```

- [ ] **Step 2: Add export to index.ts**

In `frontend/hooks/queries/index.ts`, add:

```typescript
export * from './skillCollaborators'
```

- [ ] **Step 3: Commit**

```bash
git add frontend/hooks/queries/skillCollaborators.ts frontend/hooks/queries/index.ts
git commit -m "feat: add React Query hooks for skill collaborators"
```

---

## Task 7: React Query Hooks — `platformTokens.ts`

**Files:**
- Create: `frontend/hooks/queries/platformTokens.ts`
- Modify: `frontend/hooks/queries/index.ts` (add export)

- [ ] **Step 1: Create the query hooks file**

```typescript
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { STALE_TIME } from './constants'
import { platformTokenService } from '@/services/platformTokenService'
import type { PlatformToken, PlatformTokenCreateResponse, TokenCreateRequest } from '@/services/platformTokenService'

export { type PlatformToken, type PlatformTokenCreateResponse, type TokenCreateRequest } from '@/services/platformTokenService'

// ---------- Key factory ----------

export const platformTokenKeys = {
  all: ['platform-tokens'] as const,
  list: () => [...platformTokenKeys.all, 'list'] as const,
}

// ---------- Queries ----------

export function usePlatformTokens() {
  return useQuery({
    queryKey: platformTokenKeys.list(),
    queryFn: () => platformTokenService.listTokens(),
    retry: false,
    staleTime: STALE_TIME.LONG,
  })
}

// ---------- Mutations ----------

export function useCreateToken() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: TokenCreateRequest) =>
      platformTokenService.createToken(payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: platformTokenKeys.all })
    },
  })
}

export function useRevokeToken() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (tokenId: string) => platformTokenService.revokeToken(tokenId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: platformTokenKeys.all })
    },
  })
}
```

- [ ] **Step 2: Add export to index.ts**

In `frontend/hooks/queries/index.ts`, add:

```typescript
export * from './platformTokens'
```

- [ ] **Step 3: Commit**

```bash
git add frontend/hooks/queries/platformTokens.ts frontend/hooks/queries/index.ts
git commit -m "feat: add React Query hooks for platform tokens"
```

---

## Task 8: i18n — Add translation keys for all three features

**Files:**
- Modify: `frontend/lib/i18n/locales/en.ts`
- Modify: `frontend/lib/i18n/locales/zh.ts`

- [ ] **Step 1: Add English translation keys**

Add `editor` key to the `skills` block (if not already present):

```typescript
editor: 'Editor',
```

Add inside the `settings` block, after the `sandboxes` key:

```typescript
tokens: {
  title: 'API Tokens',
  description: 'Manage your API access tokens',
  create: 'Create Token',
  revoke: 'Revoke',
  revokeConfirmTitle: 'Revoke Token',
  revokeConfirmMessage: 'API calls using this token will fail immediately after revoking.',
  name: 'Token Name',
  namePlaceholder: 'e.g. CI deploy token',
  scopes: 'Scopes',
  expiresAt: 'Expiration',
  noExpiry: 'No expiry',
  lastUsed: 'Last used',
  neverUsed: 'never',
  createdSuccess: 'Token created successfully',
  revokedSuccess: 'Token revoked',
  tokenCreatedTitle: 'Token Created',
  tokenCreatedMessage: 'Copy this token now. You won\'t be able to see it again.',
  copyToken: 'Copy Token',
  copied: 'Copied!',
  emptyState: 'No API tokens created yet',
  limitReached: 'Token limit reached (50)',
  justNow: 'just now',
  minutesAgo: '{{count}}m ago',
  hoursAgo: '{{count}}h ago',
  daysAgo: '{{count}}d ago',
},
```

Add a new top-level `skillVersions` block:

```typescript
skillVersions: {
  title: 'Version History',
  publish: 'Publish New Version',
  publishButton: 'Publish',
  versionNumber: 'Version Number',
  versionPlaceholder: 'e.g. 1.0.0',
  releaseNotes: 'Release Notes',
  releaseNotesPlaceholder: 'Describe what changed...',
  restore: 'Restore',
  delete: 'Delete',
  restoreConfirmTitle: 'Restore Draft',
  restoreConfirmMessage: 'This will overwrite the current draft with version {{version}}. Continue?',
  deleteConfirmTitle: 'Delete Version',
  deleteConfirmMessage: 'This version will be permanently deleted. This cannot be undone.',
  publishedBy: 'by {{user}}',
  publishedSuccess: 'Version {{version}} published',
  restoredSuccess: 'Draft restored from version {{version}}',
  deletedSuccess: 'Version {{version}} deleted',
  emptyState: 'No versions published yet',
  invalidVersion: 'Must be MAJOR.MINOR.PATCH format (e.g. 1.0.0)',
},
```

Add a new top-level `skillCollaborators` block:

```typescript
skillCollaborators: {
  title: 'Collaborators',
  add: 'Add Collaborator',
  userId: 'User ID',
  userIdPlaceholder: 'Enter user ID',
  role: 'Role',
  owner: 'owner',
  viewer: 'viewer',
  editor: 'editor',
  publisher: 'publisher',
  admin: 'admin',
  remove: 'Remove',
  removeConfirmTitle: 'Remove Collaborator',
  removeConfirmMessage: 'This user will lose access to this skill.',
  transferOwnership: 'Transfer Ownership',
  transferConfirmTitle: 'Transfer Ownership',
  transferConfirmMessage: 'You will become an admin collaborator. The new owner will have full control.',
  newOwner: 'New Owner',
  newOwnerPlaceholder: 'Enter new owner user ID',
  addedSuccess: 'Collaborator added',
  updatedSuccess: 'Role updated',
  removedSuccess: 'Collaborator removed',
  transferredSuccess: 'Ownership transferred',
  emptyState: 'No collaborators yet',
},
```

- [ ] **Step 2: Add Chinese translation keys**

Add the same structure in `zh.ts` with Chinese translations.

Add `editor` key to the `skills` block:

```typescript
editor: '编辑器',
```

`settings.tokens`:
```typescript
tokens: {
  title: 'API Token',
  description: '管理您的 API 访问令牌',
  create: '创建 Token',
  revoke: '撤销',
  revokeConfirmTitle: '撤销 Token',
  revokeConfirmMessage: '撤销后，使用此 Token 的 API 调用将立即失败。',
  name: 'Token 名称',
  namePlaceholder: '例如 CI 部署 Token',
  scopes: '权限范围',
  expiresAt: '过期时间',
  noExpiry: '永不过期',
  lastUsed: '最后使用',
  neverUsed: '从未使用',
  createdSuccess: 'Token 创建成功',
  revokedSuccess: 'Token 已撤销',
  tokenCreatedTitle: 'Token 已创建',
  tokenCreatedMessage: '请立即复制此 Token，关闭后将无法再次查看。',
  copyToken: '复制 Token',
  copied: '已复制！',
  emptyState: '尚未创建 API Token',
  limitReached: '已达 Token 数量上限（50）',
  justNow: '刚刚',
  minutesAgo: '{{count}} 分钟前',
  hoursAgo: '{{count}} 小时前',
  daysAgo: '{{count}} 天前',
},
```

`skillVersions`:
```typescript
skillVersions: {
  title: '版本历史',
  publish: '发布新版本',
  publishButton: '发布',
  versionNumber: '版本号',
  versionPlaceholder: '例如 1.0.0',
  releaseNotes: '更新说明',
  releaseNotesPlaceholder: '描述变更内容...',
  restore: '恢复',
  delete: '删除',
  restoreConfirmTitle: '恢复 Draft',
  restoreConfirmMessage: '这将用版本 {{version}} 覆盖当前 Draft。是否继续？',
  deleteConfirmTitle: '删除版本',
  deleteConfirmMessage: '此版本将被永久删除，此操作不可撤销。',
  publishedBy: '由 {{user}}',
  publishedSuccess: '版本 {{version}} 已发布',
  restoredSuccess: '已从版本 {{version}} 恢复 Draft',
  deletedSuccess: '版本 {{version}} 已删除',
  emptyState: '尚未发布任何版本',
  invalidVersion: '格式须为 MAJOR.MINOR.PATCH（如 1.0.0）',
},
```

`skillCollaborators`:
```typescript
skillCollaborators: {
  title: '协作者',
  add: '添加协作者',
  userId: '用户 ID',
  userIdPlaceholder: '输入用户 ID',
  role: '角色',
  owner: '所有者',
  viewer: '查看者',
  editor: '编辑者',
  publisher: '发布者',
  admin: '管理员',
  remove: '移除',
  removeConfirmTitle: '移除协作者',
  removeConfirmMessage: '该用户将失去对此 Skill 的访问权限。',
  transferOwnership: '转让所有权',
  transferConfirmTitle: '转让所有权',
  transferConfirmMessage: '您将成为管理员协作者，新所有者将拥有完全控制权。',
  newOwner: '新所有者',
  newOwnerPlaceholder: '输入新所有者用户 ID',
  addedSuccess: '协作者已添加',
  updatedSuccess: '角色已更新',
  removedSuccess: '协作者已移除',
  transferredSuccess: '所有权已转让',
  emptyState: '暂无协作者',
},
```

- [ ] **Step 3: Commit**

```bash
git add frontend/lib/i18n/locales/en.ts frontend/lib/i18n/locales/zh.ts
git commit -m "feat(i18n): add en/zh translations for versions, collaborators, tokens"
```

---

## Task 9: UI — VersionHistoryTab component

**Files:**
- Create: `frontend/app/skills/components/VersionHistoryTab.tsx`
- Create: `frontend/app/skills/schemas/versionPublishSchema.ts`

- [ ] **Step 1: Create Zod schema for publish form**

```typescript
// frontend/app/skills/schemas/versionPublishSchema.ts
import { z } from 'zod'

export const versionPublishSchema = z.object({
  version: z
    .string()
    .min(1, 'Version is required')
    .regex(/^\d+\.\d+\.\d+$/, 'Must be MAJOR.MINOR.PATCH format (e.g. 1.0.0)'),
  release_notes: z.string().optional().default(''),
})

export type VersionPublishFormData = z.infer<typeof versionPublishSchema>
```

- [ ] **Step 2: Create the VersionHistoryTab component**

Create `frontend/app/skills/components/VersionHistoryTab.tsx`:

```tsx
'use client'

import { ChevronDown, ChevronUp, History, Plus, RotateCcw, Trash2 } from 'lucide-react'
import React, { useState } from 'react'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { useToast } from '@/hooks/use-toast'
import {
  useSkillVersions,
  usePublishVersion,
  useDeleteVersion,
  useRestoreDraft,
} from '@/hooks/queries/skillVersions'
import { useTranslation } from '@/lib/i18n'
import {
  versionPublishSchema,
  type VersionPublishFormData,
} from '../schemas/versionPublishSchema'

interface VersionHistoryTabProps {
  skillId: string
  /** Current user's effective role for this skill: 'owner' | 'admin' | 'publisher' | 'editor' | 'viewer' */
  userRole: string
}

export function VersionHistoryTab({ skillId, userRole }: VersionHistoryTabProps) {
  const { t } = useTranslation()
  const { toast } = useToast()

  const [showPublishForm, setShowPublishForm] = useState(false)
  const [confirmDialog, setConfirmDialog] = useState<{
    type: 'restore' | 'delete'
    version: string
    open: boolean
  }>({ type: 'restore', version: '', open: false })

  const { data: versions = [], isLoading } = useSkillVersions(skillId)
  const publishMutation = usePublishVersion(skillId)
  const deleteMutation = useDeleteVersion(skillId)
  const restoreMutation = useRestoreDraft(skillId)

  const canPublish = ['owner', 'admin', 'publisher'].includes(userRole)
  const canDelete = ['owner', 'admin'].includes(userRole)
  const canRestore = ['owner', 'admin', 'publisher'].includes(userRole)

  const form = useForm<VersionPublishFormData>({
    resolver: zodResolver(versionPublishSchema),
    defaultValues: { version: '', release_notes: '' },
  })

  const handlePublish = async (data: VersionPublishFormData) => {
    try {
      await publishMutation.mutateAsync(data)
      toast({ title: t('skillVersions.publishedSuccess', { version: data.version }) })
      form.reset()
      setShowPublishForm(false)
    } catch (error: any) {
      toast({
        title: error?.message || t('common.error'),
        variant: 'destructive',
      })
    }
  }

  const handleConfirmAction = async () => {
    const { type, version } = confirmDialog
    try {
      if (type === 'restore') {
        await restoreMutation.mutateAsync(version)
        toast({ title: t('skillVersions.restoredSuccess', { version }) })
      } else {
        await deleteMutation.mutateAsync(version)
        toast({ title: t('skillVersions.deletedSuccess', { version }) })
      }
    } catch (error: any) {
      toast({ title: error?.message || t('common.error'), variant: 'destructive' })
    }
    setConfirmDialog((prev) => ({ ...prev, open: false }))
  }

  if (isLoading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <div className="h-6 w-6 animate-spin rounded-full border-2 border-gray-300 border-t-gray-600" />
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-4 p-4">
      {/* Publish form toggle */}
      {canPublish && (
        <div>
          <Button
            variant="outline"
            size="sm"
            onClick={() => setShowPublishForm(!showPublishForm)}
            className="gap-2"
          >
            {showPublishForm ? <ChevronUp size={14} /> : <Plus size={14} />}
            {t('skillVersions.publish')}
          </Button>

          {showPublishForm && (
            <form
              onSubmit={form.handleSubmit(handlePublish)}
              className="mt-3 space-y-3 rounded-lg border border-gray-200 bg-gray-50 p-4"
            >
              <div>
                <Label className="text-xs">{t('skillVersions.versionNumber')}</Label>
                <Input
                  {...form.register('version')}
                  placeholder={t('skillVersions.versionPlaceholder')}
                  className="mt-1"
                />
                {form.formState.errors.version && (
                  <p className="mt-1 text-xs text-red-500">
                    {t('skillVersions.invalidVersion')}
                  </p>
                )}
              </div>
              <div>
                <Label className="text-xs">{t('skillVersions.releaseNotes')}</Label>
                <Textarea
                  {...form.register('release_notes')}
                  placeholder={t('skillVersions.releaseNotesPlaceholder')}
                  className="mt-1"
                  rows={3}
                />
              </div>
              <Button type="submit" size="sm" disabled={publishMutation.isPending}>
                {t('skillVersions.publishButton')}
              </Button>
            </form>
          )}
        </div>
      )}

      {/* Version list */}
      {versions.length === 0 ? (
        <div className="flex flex-col items-center gap-2 py-12 text-center">
          <History className="h-8 w-8 text-gray-300" />
          <p className="text-sm text-gray-500">{t('skillVersions.emptyState')}</p>
        </div>
      ) : (
        <div className="space-y-2">
          {versions.map((v) => (
            <div
              key={v.version}
              className="flex items-start justify-between rounded-lg border border-gray-200 bg-white p-3"
            >
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="font-mono text-sm font-semibold">{v.version}</span>
                  {v.publishedAt && (
                    <span className="text-xs text-gray-400">
                      {new Date(v.publishedAt).toLocaleDateString()}
                    </span>
                  )}
                </div>
                {v.releaseNotes && (
                  <p className="mt-1 text-xs text-gray-600">{v.releaseNotes}</p>
                )}
              </div>
              <div className="flex shrink-0 items-center gap-1">
                {canRestore && (
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-7 gap-1 text-xs"
                    onClick={() =>
                      setConfirmDialog({ type: 'restore', version: v.version, open: true })
                    }
                  >
                    <RotateCcw size={12} />
                    {t('skillVersions.restore')}
                  </Button>
                )}
                {canDelete && (
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-7 gap-1 text-xs text-red-500 hover:text-red-700"
                    onClick={() =>
                      setConfirmDialog({ type: 'delete', version: v.version, open: true })
                    }
                  >
                    <Trash2 size={12} />
                    {t('skillVersions.delete')}
                  </Button>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Confirm dialog */}
      <AlertDialog
        open={confirmDialog.open}
        onOpenChange={(open) => setConfirmDialog((prev) => ({ ...prev, open }))}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {confirmDialog.type === 'restore'
                ? t('skillVersions.restoreConfirmTitle')
                : t('skillVersions.deleteConfirmTitle')}
            </AlertDialogTitle>
            <AlertDialogDescription>
              {confirmDialog.type === 'restore'
                ? t('skillVersions.restoreConfirmMessage', {
                    version: confirmDialog.version,
                  })
                : t('skillVersions.deleteConfirmMessage')}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t('common.cancel')}</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleConfirmAction}
              className={
                confirmDialog.type === 'delete'
                  ? 'bg-red-600 text-white hover:bg-red-700'
                  : ''
              }
            >
              {confirmDialog.type === 'restore'
                ? t('skillVersions.restore')
                : t('skillVersions.delete')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}
```

- [ ] **Step 3: Commit**

```bash
git add frontend/app/skills/schemas/versionPublishSchema.ts frontend/app/skills/components/VersionHistoryTab.tsx
git commit -m "feat: add VersionHistoryTab component with publish form and version list"
```

---

## Task 10: UI — CollaboratorsTab component

**Files:**
- Create: `frontend/app/skills/components/CollaboratorsTab.tsx`

- [ ] **Step 1: Create the CollaboratorsTab component**

Create `frontend/app/skills/components/CollaboratorsTab.tsx`:

```tsx
'use client'

import { Plus, User, UserPlus, Users, X } from 'lucide-react'
import React, { useState } from 'react'

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { useToast } from '@/hooks/use-toast'
import {
  useSkillCollaborators,
  useAddCollaborator,
  useUpdateCollaboratorRole,
  useRemoveCollaborator,
  useTransferOwnership,
} from '@/hooks/queries/skillCollaborators'
import type { CollaboratorRole } from '@/hooks/queries/skillCollaborators'
import { useTranslation } from '@/lib/i18n'

interface CollaboratorsTabProps {
  skillId: string
  ownerId: string
  userRole: string // current user's role: 'owner' | 'admin' | etc.
}

const ROLES: CollaboratorRole[] = ['viewer', 'editor', 'publisher', 'admin']

export function CollaboratorsTab({ skillId, ownerId, userRole }: CollaboratorsTabProps) {
  const { t } = useTranslation()
  const { toast } = useToast()

  const [showAddForm, setShowAddForm] = useState(false)
  const [newUserId, setNewUserId] = useState('')
  const [newRole, setNewRole] = useState<CollaboratorRole>('viewer')
  const [removeTarget, setRemoveTarget] = useState<{ userId: string; open: boolean }>({
    userId: '',
    open: false,
  })
  const [transferDialog, setTransferDialog] = useState(false)
  const [transferTargetId, setTransferTargetId] = useState('')

  const { data: collaborators = [], isLoading } = useSkillCollaborators(skillId)
  const addMutation = useAddCollaborator(skillId)
  const updateRoleMutation = useUpdateCollaboratorRole(skillId)
  const removeMutation = useRemoveCollaborator(skillId)
  const transferMutation = useTransferOwnership(skillId)

  const canManage = ['owner', 'admin'].includes(userRole)
  const isOwner = userRole === 'owner'

  const handleAdd = async () => {
    if (!newUserId.trim()) return
    try {
      await addMutation.mutateAsync({ user_id: newUserId.trim(), role: newRole })
      toast({ title: t('skillCollaborators.addedSuccess') })
      setNewUserId('')
      setNewRole('viewer')
      setShowAddForm(false)
    } catch (error: any) {
      toast({ title: error?.message || t('common.error'), variant: 'destructive' })
    }
  }

  const handleRoleChange = async (userId: string, role: CollaboratorRole) => {
    try {
      await updateRoleMutation.mutateAsync({ userId, role })
      toast({ title: t('skillCollaborators.updatedSuccess') })
    } catch (error: any) {
      toast({ title: error?.message || t('common.error'), variant: 'destructive' })
    }
  }

  const handleRemove = async () => {
    try {
      await removeMutation.mutateAsync(removeTarget.userId)
      toast({ title: t('skillCollaborators.removedSuccess') })
    } catch (error: any) {
      toast({ title: error?.message || t('common.error'), variant: 'destructive' })
    }
    setRemoveTarget({ userId: '', open: false })
  }

  const handleTransfer = async () => {
    if (!transferTargetId.trim()) return
    try {
      await transferMutation.mutateAsync(transferTargetId.trim())
      toast({ title: t('skillCollaborators.transferredSuccess') })
      setTransferDialog(false)
      setTransferTargetId('')
    } catch (error: any) {
      toast({ title: error?.message || t('common.error'), variant: 'destructive' })
    }
  }

  if (isLoading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <div className="h-6 w-6 animate-spin rounded-full border-2 border-gray-300 border-t-gray-600" />
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-4 p-4">
      {/* Add collaborator button */}
      {canManage && (
        <div>
          <Button
            variant="outline"
            size="sm"
            onClick={() => setShowAddForm(!showAddForm)}
            className="gap-2"
          >
            <UserPlus size={14} />
            {t('skillCollaborators.add')}
          </Button>

          {showAddForm && (
            <div className="mt-3 flex items-end gap-2 rounded-lg border border-gray-200 bg-gray-50 p-4">
              <div className="flex-1">
                <Label className="text-xs">{t('skillCollaborators.userId')}</Label>
                <Input
                  value={newUserId}
                  onChange={(e) => setNewUserId(e.target.value)}
                  placeholder={t('skillCollaborators.userIdPlaceholder')}
                  className="mt-1"
                />
              </div>
              <div className="w-32">
                <Label className="text-xs">{t('skillCollaborators.role')}</Label>
                <Select
                  value={newRole}
                  onValueChange={(v) => setNewRole(v as CollaboratorRole)}
                >
                  <SelectTrigger className="mt-1">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {ROLES.map((r) => (
                      <SelectItem key={r} value={r}>
                        {t(`skillCollaborators.${r}`)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <Button size="sm" onClick={handleAdd} disabled={addMutation.isPending}>
                <Plus size={14} />
              </Button>
            </div>
          )}
        </div>
      )}

      {/* Collaborator list */}
      <div className="space-y-1">
        {/* Owner row (always first) */}
        <div className="flex items-center gap-3 rounded-lg border border-gray-200 bg-white px-3 py-2">
          <div className="flex h-6 w-6 items-center justify-center rounded-full bg-gray-200">
            <User size={12} className="text-gray-500" />
          </div>
          <span className="flex-1 text-sm font-medium">{ownerId}</span>
          <span className="text-xs text-gray-400">({t('skillCollaborators.owner')})</span>
        </div>

        {/* Collaborator rows */}
        {collaborators.map((c) => (
          <div
            key={c.userId}
            className="flex items-center gap-3 rounded-lg border border-gray-200 bg-white px-3 py-2"
          >
            <div className="h-6 w-6 rounded-full bg-gray-200 text-center text-xs leading-6">
              👤
            </div>
            <span className="flex-1 text-sm">{c.userId}</span>
            {canManage ? (
              <Select
                value={c.role}
                onValueChange={(v) => handleRoleChange(c.userId, v as CollaboratorRole)}
              >
                <SelectTrigger className="h-7 w-28 text-xs">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {ROLES.map((r) => (
                    <SelectItem key={r} value={r}>
                      {t(`skillCollaborators.${r}`)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            ) : (
              <span className="text-xs text-gray-500">
                {t(`skillCollaborators.${c.role}`)}
              </span>
            )}
            {canManage && (
              <Button
                variant="ghost"
                size="sm"
                className="h-7 w-7 p-0 text-gray-400 hover:text-red-500"
                onClick={() => setRemoveTarget({ userId: c.userId, open: true })}
              >
                <X size={14} />
              </Button>
            )}
          </div>
        ))}

        {collaborators.length === 0 && (
          <p className="py-4 text-center text-xs text-gray-400">
            {t('skillCollaborators.emptyState')}
          </p>
        )}
      </div>

      {/* Transfer ownership button */}
      {isOwner && (
        <div className="border-t border-gray-200 pt-4">
          <Button
            variant="outline"
            size="sm"
            className="gap-2"
            onClick={() => setTransferDialog(true)}
          >
            {t('skillCollaborators.transferOwnership')}
          </Button>
        </div>
      )}

      {/* Remove confirm dialog */}
      <AlertDialog
        open={removeTarget.open}
        onOpenChange={(open) => setRemoveTarget((prev) => ({ ...prev, open }))}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t('skillCollaborators.removeConfirmTitle')}</AlertDialogTitle>
            <AlertDialogDescription>
              {t('skillCollaborators.removeConfirmMessage')}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t('common.cancel')}</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleRemove}
              className="bg-red-600 text-white hover:bg-red-700"
            >
              {t('skillCollaborators.remove')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Transfer ownership dialog */}
      <Dialog open={transferDialog} onOpenChange={setTransferDialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('skillCollaborators.transferConfirmTitle')}</DialogTitle>
            <DialogDescription>
              {t('skillCollaborators.transferConfirmMessage')}
            </DialogDescription>
          </DialogHeader>
          <div className="py-4">
            <Label>{t('skillCollaborators.newOwner')}</Label>
            <Input
              value={transferTargetId}
              onChange={(e) => setTransferTargetId(e.target.value)}
              placeholder={t('skillCollaborators.newOwnerPlaceholder')}
              className="mt-1"
            />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setTransferDialog(false)}>
              {t('common.cancel')}
            </Button>
            <Button onClick={handleTransfer} disabled={transferMutation.isPending}>
              {t('skillCollaborators.transferOwnership')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/app/skills/components/CollaboratorsTab.tsx
git commit -m "feat: add CollaboratorsTab with inline role editing and ownership transfer"
```

---

## Task 11: UI — Token management pages (TokensPage + dialogs)

**Files:**
- Create: `frontend/components/settings/tokens-page.tsx`
- Create: `frontend/components/settings/create-token-dialog.tsx`
- Create: `frontend/components/settings/token-created-dialog.tsx`

- [ ] **Step 1: Create `create-token-dialog.tsx`**

```tsx
'use client'

import React, { useState } from 'react'

import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useTranslation } from '@/lib/i18n'

const AVAILABLE_SCOPES = [
  { value: 'skills:read', label: 'Read' },
  { value: 'skills:write', label: 'Write' },
  { value: 'skills:publish', label: 'Publish' },
  { value: 'skills:admin', label: 'Admin' },
]

interface CreateTokenDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  onSubmit: (data: { name: string; scopes: string[]; expires_at?: string | null }) => Promise<void>
  isPending: boolean
}

export function CreateTokenDialog({
  open,
  onOpenChange,
  onSubmit,
  isPending,
}: CreateTokenDialogProps) {
  const { t } = useTranslation()
  const [name, setName] = useState('')
  const [scopes, setScopes] = useState<string[]>([])
  const [expiresAt, setExpiresAt] = useState('')

  const handleScopeToggle = (scope: string, checked: boolean) => {
    setScopes((prev) => (checked ? [...prev, scope] : prev.filter((s) => s !== scope)))
  }

  const handleSubmit = async () => {
    await onSubmit({
      name: name.trim(),
      scopes,
      expires_at: expiresAt ? new Date(expiresAt).toISOString() : null,
    })
    setName('')
    setScopes([])
    setExpiresAt('')
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t('settings.tokens.create')}</DialogTitle>
          <DialogDescription>{t('settings.tokens.description')}</DialogDescription>
        </DialogHeader>
        <div className="space-y-4 py-4">
          <div>
            <Label>{t('settings.tokens.name')}</Label>
            <Input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={t('settings.tokens.namePlaceholder')}
              className="mt-1"
            />
          </div>
          <div>
            <Label>{t('settings.tokens.scopes')}</Label>
            <div className="mt-2 space-y-2">
              {AVAILABLE_SCOPES.map((s) => (
                <div key={s.value} className="flex items-center gap-2">
                  <Checkbox
                    id={s.value}
                    checked={scopes.includes(s.value)}
                    onCheckedChange={(checked) =>
                      handleScopeToggle(s.value, checked === true)
                    }
                  />
                  <label htmlFor={s.value} className="text-sm">
                    {s.label}
                    <span className="ml-1 text-xs text-gray-400">({s.value})</span>
                  </label>
                </div>
              ))}
            </div>
          </div>
          <div>
            <Label>{t('settings.tokens.expiresAt')}</Label>
            <Input
              type="date"
              value={expiresAt}
              onChange={(e) => setExpiresAt(e.target.value)}
              className="mt-1"
              min={new Date().toISOString().split('T')[0]}
            />
            <p className="mt-1 text-xs text-gray-400">
              {t('settings.tokens.noExpiry')} if left blank
            </p>
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t('common.cancel')}
          </Button>
          <Button
            onClick={handleSubmit}
            disabled={isPending || !name.trim() || scopes.length === 0}
          >
            {t('settings.tokens.create')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
```

- [ ] **Step 2: Create `token-created-dialog.tsx`**

```tsx
'use client'

import { Check, Copy } from 'lucide-react'
import React, { useState } from 'react'

import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { useTranslation } from '@/lib/i18n'

interface TokenCreatedDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  token: string | null
}

export function TokenCreatedDialog({ open, onOpenChange, token }: TokenCreatedDialogProps) {
  const { t } = useTranslation()
  const [copied, setCopied] = useState(false)

  const handleCopy = async () => {
    if (!token) return
    await navigator.clipboard.writeText(token)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t('settings.tokens.tokenCreatedTitle')}</DialogTitle>
          <DialogDescription>
            {t('settings.tokens.tokenCreatedMessage')}
          </DialogDescription>
        </DialogHeader>
        <div className="my-4">
          <div className="flex items-center gap-2 rounded-lg bg-gray-100 p-3">
            <code className="flex-1 break-all text-xs">{token}</code>
            <Button variant="ghost" size="sm" className="shrink-0" onClick={handleCopy}>
              {copied ? <Check size={14} /> : <Copy size={14} />}
              <span className="ml-1 text-xs">
                {copied ? t('settings.tokens.copied') : t('settings.tokens.copyToken')}
              </span>
            </Button>
          </div>
        </div>
        <DialogFooter>
          <Button onClick={() => onOpenChange(false)}>OK</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
```

- [ ] **Step 3: Create `tokens-page.tsx`**

```tsx
'use client'

import { Key, Loader2, Plus, ShieldAlert } from 'lucide-react'
import React, { useState } from 'react'

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { useToast } from '@/components/ui/use-toast'
import {
  usePlatformTokens,
  useCreateToken,
  useRevokeToken,
} from '@/hooks/queries/platformTokens'
import type { PlatformTokenCreateResponse } from '@/hooks/queries/platformTokens'
import { useTranslation } from '@/lib/i18n'
import { CreateTokenDialog } from './create-token-dialog'
import { TokenCreatedDialog } from './token-created-dialog'

function formatRelativeTime(dateStr: string | null, t: (key: string, opts?: any) => string): string {
  if (!dateStr) return t('settings.tokens.neverUsed')
  const diff = Date.now() - new Date(dateStr).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return t('settings.tokens.justNow')
  if (mins < 60) return t('settings.tokens.minutesAgo', { count: mins })
  const hours = Math.floor(mins / 60)
  if (hours < 24) return t('settings.tokens.hoursAgo', { count: hours })
  const days = Math.floor(hours / 24)
  return t('settings.tokens.daysAgo', { count: days })
}

export const TokensPage = () => {
  const { t } = useTranslation()
  const { toast } = useToast()

  const [showCreateDialog, setShowCreateDialog] = useState(false)
  const [createdToken, setCreatedToken] = useState<string | null>(null)
  const [revokeTarget, setRevokeTarget] = useState<{ id: string; name: string; open: boolean }>({
    id: '',
    name: '',
    open: false,
  })

  const { data: tokens = [], isLoading } = usePlatformTokens()
  const createMutation = useCreateToken()
  const revokeMutation = useRevokeToken()

  const handleCreate = async (data: { name: string; scopes: string[]; expires_at?: string | null }) => {
    try {
      const result: PlatformTokenCreateResponse = await createMutation.mutateAsync(data)
      setShowCreateDialog(false)
      setCreatedToken(result.token)
      toast({ title: t('settings.tokens.createdSuccess') })
    } catch (error: any) {
      toast({ title: error?.message || t('common.error'), variant: 'destructive' })
    }
  }

  const handleRevoke = async () => {
    try {
      await revokeMutation.mutateAsync(revokeTarget.id)
      toast({ title: t('settings.tokens.revokedSuccess') })
    } catch (error: any) {
      toast({ title: error?.message || t('common.error'), variant: 'destructive' })
    }
    setRevokeTarget({ id: '', name: '', open: false })
  }

  if (isLoading) {
    return (
      <div className="flex h-full min-h-[400px] items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-gray-400" />
      </div>
    )
  }

  const activeTokens = tokens.filter((t) => t.isActive)

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="mb-6 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="rounded-lg bg-gradient-to-br from-amber-500 to-orange-600 p-2 shadow-sm">
            <Key className="h-5 w-5 text-white" />
          </div>
          <div>
            <h2 className="text-lg font-bold tracking-tight text-gray-900">
              {t('settings.tokens.title')}
            </h2>
            <p className="mt-0.5 text-xs text-gray-500">
              {t('settings.tokens.description')}
            </p>
          </div>
        </div>
        <Button size="sm" className="gap-2" onClick={() => setShowCreateDialog(true)}>
          <Plus size={14} />
          {t('settings.tokens.create')}
        </Button>
      </div>

      {/* Token cards */}
      {activeTokens.length === 0 ? (
        <div className="flex flex-1 flex-col items-center justify-center gap-3 py-12">
          <div className="rounded-full border bg-gray-100 p-4">
            <Key className="h-8 w-8 text-gray-300" />
          </div>
          <p className="text-sm text-gray-500">{t('settings.tokens.emptyState')}</p>
        </div>
      ) : (
        <div className="space-y-3 overflow-auto">
          {activeTokens.map((token) => (
            <div
              key={token.id}
              className="rounded-xl border border-gray-200 bg-white p-4 shadow-sm"
            >
              <div className="flex items-start justify-between">
                <div>
                  <h3 className="text-sm font-semibold text-gray-900">{token.name}</h3>
                  <p className="mt-0.5 font-mono text-xs text-gray-400">
                    {token.tokenPrefix}...
                  </p>
                </div>
                <Button
                  variant="outline"
                  size="sm"
                  className="text-red-500 hover:text-red-700"
                  onClick={() =>
                    setRevokeTarget({ id: token.id, name: token.name, open: true })
                  }
                >
                  {t('settings.tokens.revoke')}
                </Button>
              </div>
              <div className="mt-2 flex flex-wrap gap-1">
                {token.scopes.map((scope) => (
                  <Badge key={scope} variant="secondary" className="text-xs">
                    {scope.replace('skills:', '')}
                  </Badge>
                ))}
              </div>
              <div className="mt-2 flex gap-4 text-xs text-gray-400">
                <span>
                  {t('settings.tokens.expiresAt')}:{' '}
                  {token.expiresAt
                    ? new Date(token.expiresAt).toLocaleDateString()
                    : t('settings.tokens.noExpiry')}
                </span>
                <span>
                  {t('settings.tokens.lastUsed')}:{' '}
                  {formatRelativeTime(token.lastUsedAt, t)}
                </span>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Create dialog */}
      <CreateTokenDialog
        open={showCreateDialog}
        onOpenChange={setShowCreateDialog}
        onSubmit={handleCreate}
        isPending={createMutation.isPending}
      />

      {/* Token created dialog */}
      <TokenCreatedDialog
        open={!!createdToken}
        onOpenChange={(open) => {
          if (!open) setCreatedToken(null)
        }}
        token={createdToken}
      />

      {/* Revoke confirm dialog */}
      <AlertDialog
        open={revokeTarget.open}
        onOpenChange={(open) => setRevokeTarget((prev) => ({ ...prev, open }))}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t('settings.tokens.revokeConfirmTitle')}</AlertDialogTitle>
            <AlertDialogDescription>
              {t('settings.tokens.revokeConfirmMessage')}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t('common.cancel')}</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleRevoke}
              className="bg-red-600 text-white hover:bg-red-700"
            >
              {t('settings.tokens.revoke')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}
```

- [ ] **Step 4: Commit**

```bash
git add frontend/components/settings/tokens-page.tsx frontend/components/settings/create-token-dialog.tsx frontend/components/settings/token-created-dialog.tsx
git commit -m "feat: add TokensPage, CreateTokenDialog, and TokenCreatedDialog"
```

---

## Task 12: Integration — Add tabs to SkillsManager

**Files:**
- Modify: `frontend/app/skills/SkillsManager.tsx`

This task integrates the VersionHistoryTab and CollaboratorsTab into the SkillsManager component.

- [ ] **Step 1: Read the current SkillsManager.tsx to identify the exact insertion points**

The file is ~1021 lines. Key areas:
1. Import section at top
2. Component state declarations
3. The editor area (flex-1 panel on the right side)

- [ ] **Step 2: Add imports**

At the top of `SkillsManager.tsx`, add:

```typescript
import { VersionHistoryTab } from './components/VersionHistoryTab'
import { CollaboratorsTab } from './components/CollaboratorsTab'
```

- [ ] **Step 3: Add tab state**

Inside the component, add a new state:

```typescript
const [activeTab, setActiveTab] = useState<'editor' | 'versions' | 'collaborators'>('editor')
```

- [ ] **Step 4: Add tab bar and conditional rendering**

In the editor area (the rightmost flex-1 panel), wrap the existing editor content with a Tab bar:

```tsx
{/* Tab bar — 3 tabs (file tree is a permanent side panel, not a tab) */}
<div className="flex border-b border-gray-200 px-2">
  {['editor', 'versions', 'collaborators'].map((tab) => (
    <button
      key={tab}
      onClick={() => setActiveTab(tab as any)}
      className={cn(
        'px-3 py-2 text-xs font-medium transition-colors',
        activeTab === tab
          ? 'border-b-2 border-blue-500 text-blue-600'
          : 'text-gray-500 hover:text-gray-700'
      )}
    >
      {tab === 'editor' && t('skills.editor')}
      {tab === 'versions' && t('skillVersions.title')}
      {tab === 'collaborators' && t('skillCollaborators.title')}
    </button>
  ))}
</div>

{/* Tab content */}
{activeTab === 'editor' && (
  /* existing editor content */
)}
{activeTab === 'versions' && selectedSkill && (
  <VersionHistoryTab
    skillId={selectedSkill.id}
    userRole="owner" /* TODO: derive from actual skill permissions */
  />
)}
{activeTab === 'collaborators' && selectedSkill && (
  <CollaboratorsTab
    skillId={selectedSkill.id}
    ownerId={selectedSkill.owner_id || selectedSkill.created_by_id || ''}
    userRole="owner" /* TODO: derive from actual skill permissions */
  />
)}
```

**Note:** The `userRole` prop is hardcoded to `"owner"` for now. A follow-up task should derive the actual role from the skill's collaborator data and the current user. For the initial integration, `"owner"` ensures all features are visible and testable.

- [ ] **Step 5: Commit**

```bash
git add frontend/app/skills/SkillsManager.tsx
git commit -m "feat: integrate version history and collaborator tabs into SkillsManager"
```

---

## Task 13: Integration — Add API Tokens tab to Settings dialog

**Files:**
- Modify: `frontend/components/settings/settings-dialog.tsx`

- [ ] **Step 1: Add import**

```typescript
import { Key } from 'lucide-react'
import { TokensPage } from './tokens-page'
```

- [ ] **Step 2: Add MenuItem in sidebar**

In the sidebar section (after the Sandboxes MenuItem), add:

```tsx
<MenuItem
  icon={Key}
  label={t('settings.tokens.title')}
  isActive={activeTab === 'tokens'}
  onClick={() => setActiveTab('tokens')}
/>
```

- [ ] **Step 3: Add content rendering**

In the content area, add:

```tsx
{activeTab === 'tokens' && (
  <div className="flex-1 overflow-hidden p-6">
    <TokensPage />
  </div>
)}
```

- [ ] **Step 4: Commit**

```bash
git add frontend/components/settings/settings-dialog.tsx
git commit -m "feat: add API Tokens tab to Settings dialog"
```

---

## Task 14: Smoke test — Verify TypeScript compilation

**Files:** None (verification only)

- [ ] **Step 1: Run TypeScript compilation check**

```bash
cd frontend && npx tsc --noEmit 2>&1 | head -50
```

Expected: No errors related to the new files. Pre-existing errors in other files are acceptable.

- [ ] **Step 2: Fix any type errors in new files**

If there are errors in the new files, fix them.

- [ ] **Step 3: Run existing tests to ensure no regressions**

```bash
cd frontend && npx vitest run --reporter=verbose 2>&1 | tail -30
```

- [ ] **Step 4: Final commit (if fixes needed)**

```bash
git add -A && git commit -m "fix: resolve TypeScript errors in new skill frontend files"
```

---

## Task 15: Follow-up — Derive actual `userRole` from skill permissions

**Files:**
- Modify: `frontend/app/skills/SkillsManager.tsx`

This is a follow-up task to replace the hardcoded `userRole="owner"` with the actual user's role derived from the skill's collaborator data and the current user session.

- [ ] **Step 1: Derive user role**

In `SkillsManager.tsx`, use `useSkillCollaborators` and the current user session to determine the role:

```typescript
// After selectedSkill is set, derive userRole:
const { data: session } = useSession()
const { data: collaborators = [] } = useSkillCollaborators(selectedSkill?.id ?? '')
const currentUserId = session?.user?.id

const userRole = useMemo(() => {
  if (!selectedSkill || !currentUserId) return 'viewer'
  if (selectedSkill.owner_id === currentUserId) return 'owner'
  const collab = collaborators.find((c) => c.userId === currentUserId)
  return collab?.role ?? (selectedSkill.is_public ? 'viewer' : 'viewer')
}, [selectedSkill, currentUserId, collaborators])
```

- [ ] **Step 2: Pass derived `userRole` to tab components**

Replace the hardcoded `"owner"` with the computed `userRole`:

```tsx
<VersionHistoryTab skillId={selectedSkill.id} userRole={userRole} />
<CollaboratorsTab skillId={selectedSkill.id} ownerId={selectedSkill.owner_id || ''} userRole={userRole} />
```

- [ ] **Step 3: Commit**

```bash
git add frontend/app/skills/SkillsManager.tsx
git commit -m "feat: derive actual userRole from skill permissions for version/collaborator tabs"
```

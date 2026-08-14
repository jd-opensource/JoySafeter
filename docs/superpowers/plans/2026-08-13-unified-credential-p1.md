# Unified Credential P1 — "Models & Credentials" UX Merge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Revision:** rev4 (2026-08-14) — adds backward-compatible archived filtering before pagination and reconciles the implemented Model/Service lifecycle, per-tab state retention, nested-interaction a11y, create-scope race guards, and vocabulary cleanup. Supersedes rev3.

**Goal:** Collapse the two credential nav entries (`/managed/secrets`, `/managed/vaults`) into one `/managed/credentials` "Models & Credentials" surface with kind tabs, a canonical MCP vault detail route, and a unified creation entry. Preserve schema, response shapes, and credential runtime semantics; add only a backward-compatible `GET /credentials?include_archived=` query parameter so archived filtering occurs before pagination.

**Architecture:** A `CredentialManagementShell` owns tab query-state (`?tab=models|services|mcp`) and the unified create orchestration (chooser → kind-locked flow → tab-switch + cache-invalidate on success); three extracted list components render per-tab with independent loading/error/empty/pagination; a kind-dispatching `CredentialDetail` at `/managed/credentials/[credentialId]` dispatches model/service/mcp/orphan; the MCP vault detail lives at the static-segment route `/managed/credentials/mcp/[credentialGroupId]`. Old `secrets/`+`vaults/` route pages become server-side `redirect()` shells. Kind filtering is server-side via a `query` option on the shared `usePaginatedList`; Model/Service archived filtering is also server-side through an explicit `includeArchived` value. The LLM catalog dependency is scoped to Model surfaces only.

**Tech Stack:** Next.js App Router + TypeScript + React + React Query + Radix; vitest (`bun run test`); eslint (`bun run lint`); `tsc --noEmit` (`bun run type-check`). All frontend commands run from `frontend/`.

## Global Constraints

- **Minimal compatible API extension only.** No schema, response-shape, or credential-runtime change and no new endpoint. `GET /credentials` supports `kind=model|service` plus optional tri-state `include_archived`; `GET /credential-groups` is unchanged.
- **Capability-equivalence — verified against the backend and current UI (rev4):** P1 preserves existing capabilities and exposes the existing credential lifecycle consistently:
  - **Model Connection:** list/detail set-default · archive · restore · delete · active detail edit-data/save · **test-connection only at CREATE time** (via `LlmSecretConfigurator`; `POST /credentials/test` takes full plaintext `{provider,protocol,data}`, and detail reads are masked, so detail test-connection is not technically valid).
  - **Service Credential:** list/detail archive · restore · delete · active detail edit masked fields incl. add/remove key/save.
  - **MCP Vault:** list create · list archive · list delete · detail archive · detail delete. **Member:** add · archive (not delete — archive preserves history) · show-archived toggle.
  - **Explicitly NOT in P1:** model/service **detail test-connection**. The server returns masked detail data, so retesting it would send masked placeholders rather than the original secret.
- **Lifecycle/list fact:** omitted `include_archived` preserves the historical active + archived result for existing callers; `false` excludes archived rows in SQL before cursor/limit; `true` returns active + archived. Model/Service lists explicitly send `false` by default and `true` when toggled. Existing `/archive` + `/restore` endpoints remain unchanged.
- **State continuity:** switching tabs preserves per-tab search/filter/show-archived/page-size state while keeping only the active list mounted. Cursor state remains kind/scope/page-size isolated.
- **Mutation safety:** project switch, project archival, dialog close, or unmount invalidates in-flight create/mutation tails; stale completions must not update cache/UI or navigate.
- **§3.12 vocabulary is a DECIDED RULING (B5).** Object names: **模型连接 / Model Connection** (material = **模型访问密钥 / model access key**; the boundary "模型连接 ≠ 凭据" is decided), **服务凭据 / Service Credential**, **MCP 凭据库 / MCP Credential Vault** (containing **MCP 凭据**). The menu is **模型与凭据 / Models & Credentials**. Do NOT use "New credential" / "Create a credential" as an umbrella term for all three objects; the global action is just **New / 新建** and the chooser asks "what to create". Network-sense 连接 (test connection / connected) must NOT be scanned into object renames. This also means the existing `managed.llm.modelConfiguration` zh value (`模型接入`) is drift and is converged to `模型连接` in Task 2 (pin updated there).
- **Stage changes by explicit path only. NEVER `git add -A` / `git add .`** (working tree is chronically dirty with the user's concurrent edits). Paths containing `[` MUST be quoted after `--` for zsh: `git add -- 'frontend/app/managed/credentials/[credentialId]/page.tsx'`.
- **All new user-visible copy MUST use `t()` keys** — never hard-coded strings (the terminology test's `findHardCodedLegacyCredentialCopy` AST scan forbids literals like `model secrets`, `vault configuration`, `${…} vaults` in `app/`, `components/`, `hooks/`).
- **Do NOT rename backend `kind` values or i18n KEY names** — user-visible copy only.
- **Architecture guards are migrated IN the task that breaks them (B4), never deferred.** `frontend/types/entity-id-architecture.test.ts` typed-list-cursor + typed-detail assertions and `frontend/app/managed/vaults/vault-member-lifecycle.test.ts` read old page source; Task 11 repoints them to the new component files in the same commit and runs them before committing.
- **i18n inventory counts** (`sourceFileCount`, `direct`/`dynamic`/`total`, `templateAdditions`, `finiteAdditions` in `credential-terminology.test.ts`) go RED once new source files/keys land — EXPECTED. They are reconciled ONCE, to the true post-P1 reality, in **Task 14**. Semantic assertions (Task 2) are the real regression detector.
- **Per-task verification runs from `frontend/`:** `bun run type-check`, the task's test file(s), `bun run lint`. Route-migration tasks additionally run the relevant architecture guard tests. The full-suite green gate + count reconciliation is **Task 14**.
- **Verification-before-completion:** after Task 14's implementation, spawn a `verification` subagent (original request + files changed + this plan path) before reporting completion.

---

## File Structure

**New files (all under `frontend/`):**
- `app/managed/credentials/page.tsx` — merged page (renders shell).
- `app/managed/credentials/[credentialId]/page.tsx` — model/service detail route (`CredentialDetail`).
- `app/managed/credentials/mcp/[credentialGroupId]/page.tsx` — MCP vault detail route (`McpVaultDetail`); consumes/strips `?add=1`.
- `components/managed/credentials/credential-management-shell.tsx`
- `components/managed/credentials/credential-kind-chooser.tsx`
- `components/managed/credentials/model-connection-list.tsx`
- `components/managed/credentials/service-credential-list.tsx`
- `components/managed/credentials/mcp-vault-list.tsx`
- `components/managed/credentials/credential-detail.tsx`
- `components/managed/credentials/model-connection-detail.tsx`
- `components/managed/credentials/service-credential-detail.tsx`
- `components/managed/credentials/mcp-vault-detail.tsx`
- `lib/managed/credential-redirects.ts` — pure redirect-target helpers (testable).
- Colocated `*.test.tsx` per component + `credential-parity.test.tsx`.

**Modified files:**
- `backend/app/joysafeter_api/api/v1/credentials.py`, `backend/app/joysafeter_domain/services/joysafeter_credential_service.py` — optional compatible `include_archived` filter before pagination.
- `backend/tests/test_credentials_api.py`, `backend/tests/test_credential_service.py` — tri-state compatibility and pagination-order regression coverage.
- `hooks/managed/use-compatible-secrets.ts`, `hooks/managed/use-service-credentials.ts` (+ tests) — exclude archived credentials from runtime-binding selectors.
- `app/managed/environments/page.tsx`, `app/managed/environments/[envId]/page.tsx` — keep typed-cursor pagination and explicitly exclude archived Service Credentials.
- `hooks/managed/use-paginated-list.ts` (+ existing `use-paginated-list.test.tsx`)
- `app/managed/secrets/components/create-secret-dialog.tsx` (+ its test) — `lockKind`.
- `app/managed/vaults/components/create-vault-dialog.tsx` (+ its test) — `onCreated`.
- `app/managed/secrets/page.tsx`, `app/managed/secrets/[secretId]/page.tsx`, `app/managed/vaults/page.tsx`, `app/managed/vaults/[vaultId]/page.tsx` → redirect shells.
- `components/app-sidebar/app-sidebar.tsx` — single nav entry.
- `components/managed/shared/data-table.tsx` — additive keyboard row activation (a11y).
- `components/managed/environments-egress-editor.tsx`, `app/managed/agents/[agentId]/edit/page.tsx`, `app/managed/sessions/components/create-session-dialog.tsx`, `app/managed/sessions/[sessionId]/page.tsx` — deep-link updates.
- `lib/i18n/locales/en.ts`, `lib/i18n/locales/zh.ts`, `lib/i18n/credential-terminology.test.ts`.
- `types/entity-id-architecture.test.ts`, `app/managed/vaults/vault-member-lifecycle.test.ts` — guard migration.

---

### Task 1: Add `query` option to `usePaginatedList` (server-side kind scoping)

**Files:**
- Modify: `frontend/hooks/managed/use-paginated-list.ts`
- Modify: `frontend/hooks/managed/use-paginated-list.test.tsx` (EXISTS — extend, do not create)

**Interfaces:**
- Produces: `usePaginatedList<T>({ …, query?: Record<string, string | number | boolean | null | undefined>, includeArchived?: boolean })`. When `query` is set, the effective request path is `apiCollectionPath(path, query)` and that scoped path flows into the fetch URL, the query key (`fullKey[2]`), the sessionStorage cursor scope (`listScope`), the prefetch key, and the `placeholderData` guard — so two callers differing only by `query` (even with the SAME `queryKey` and a SHARED QueryClient) never share cache or cursor. `includeArchived` is serialized without truthiness coercion: explicit `false` MUST produce `include_archived=false`, while `undefined` omits the parameter. Later tasks pass `query: { kind: 'model' }` / `{ kind: 'service' }` and `includeArchived: showArchived`.

- [ ] **Step 1: Write the failing tests** — append to `frontend/hooks/managed/use-paginated-list.test.tsx`.

The isolation test MUST use ONE shared QueryClient (rev1 bug: two clients cannot prove shared-cache isolation). Add a separate regression test asserting `includeArchived: false` is preserved in the request URL:

```tsx
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { describe, expect, it, vi } from 'vitest'

describe('usePaginatedList query option', () => {
  it('threads query params into the request path alongside pagination params', async () => {
    managedGetMock.mockResolvedValue({ data: [], has_more: false })
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const wrap = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    )
    renderHook(
      () =>
        usePaginatedList<{ id: string }>({
          queryKey: 'credentials',
          path: '/credentials',
          query: { kind: 'model' },
        }),
      { wrapper: wrap },
    )
    await waitFor(() => expect(managedGetMock).toHaveBeenCalled())
    const url = managedGetMock.mock.calls[0][0] as string
    expect(url).toContain('/credentials?')
    expect(url).toContain('kind=model')
    expect(url).toContain('limit=')
  })

  it('isolates cache/cursor between two kinds sharing queryKey AND a single QueryClient', async () => {
    managedGetMock.mockImplementation(async (url: string) => ({
      data: [{ id: (url as string).includes('kind=model') ? 'cred_model' : 'cred_service' }],
      has_more: false,
    }))
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const wrap = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    )
    const model = renderHook(
      () => usePaginatedList<{ id: string }>({ queryKey: 'credentials', path: '/credentials', query: { kind: 'model' } }),
      { wrapper: wrap },
    )
    const service = renderHook(
      () => usePaginatedList<{ id: string }>({ queryKey: 'credentials', path: '/credentials', query: { kind: 'service' } }),
      { wrapper: wrap },
    )
    await waitFor(() => expect(model.result.current.data.length).toBe(1))
    await waitFor(() => expect(service.result.current.data.length).toBe(1))
    expect(model.result.current.data[0].id).toBe('cred_model')
    expect(service.result.current.data[0].id).toBe('cred_service')
  })
})
```
Reuse the file's existing `managedGetMock` + `useManagedRequestScope` mock (the file already mocks `@/lib/api-client` and `@/lib/managed/request-scope`; add these to the same file so those mocks apply). If the existing file lacks a `managedGetMock` handle, add the standard mock block at the top matching the file's convention.

- [ ] **Step 2: Run to verify it fails** — `cd frontend && bun run test use-paginated-list` → FAIL (`query` not accepted; not threaded).

- [ ] **Step 3: Implement** — in `use-paginated-list.ts`:

Add to `UsePaginatedListOptions<T>` after `path`:
```ts
  query?: Record<string, string | number | boolean | null | undefined>
```
Destructure `query,` in the hook. Immediately after `const managedScope = useManagedRequestScope()`:
```ts
  const queryScope = query ? JSON.stringify(query) : ''
  const scopedPath = useMemo(
    () => (query ? apiCollectionPath(path, query) : path),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [path, queryScope],
  )
```
Replace every in-body use of `path` with `scopedPath`: `listScope` (~168), `fullKey[2]` (~181), the `useQuery` `queryFn` `apiPage(...)` call (~203), the `placeholderData` guard `previousKey[2] === path` (~218), the prefetch `nextKey[2]` (~240) and its `apiPage(...)` (~250), and the prefetch effect dep `path` (~267). `apiPage` serializes `include_archived: includeArchived` directly; never use `includeArchived || undefined`, because that silently drops the required explicit `false`. Passing `/credentials?kind=model` still yields `/credentials?kind=model&limit=…&include_archived=false`.

- [ ] **Step 4: Pass** — `cd frontend && bun run test use-paginated-list` → PASS.
- [ ] **Step 5: Guards** — `cd frontend && bun run type-check && bun run lint` → clean.
- [ ] **Step 6: Commit**
```bash
git add -- frontend/hooks/managed/use-paginated-list.ts frontend/hooks/managed/use-paginated-list.test.tsx
git commit -m "feat(credentials): add query option to usePaginatedList for kind-scoped lists"
```

---

### Task 1A: Add compatible `/credentials` archived filtering before pagination

**Files:**
- Modify: `backend/app/joysafeter_api/api/v1/credentials.py`
- Modify: `backend/app/joysafeter_domain/services/joysafeter_credential_service.py`
- Modify: `backend/tests/test_credentials_api.py`
- Modify: `backend/tests/test_credential_service.py`

**Contract:** Route accepts `include_archived: Optional[bool] = Query(None)` and passes it through. Service accepts `bool | None = None`. Omitted/`true` preserve active + archived results; only explicit `false` adds `archived_at IS NULL`. Apply this predicate before `after_id`, ordering, and `limit + 1`, so a page cannot become falsely empty after client filtering.

- [ ] **Step 1: Red tests** — prove omitted remains backward compatible and `false` filters archived rows before pagination at both API and service layers.
- [ ] **Step 2: Implement** — add the optional route parameter and service predicate; do not change response shape or mutation endpoints.
- [ ] **Step 3: Green** — `backend/.venv/bin/pytest backend/tests/test_credentials_api.py backend/tests/test_credential_service.py -q`.

---

### Task 1B: Align credential selectors with backend runtime eligibility

**Files:**
- Modify: `frontend/hooks/managed/use-compatible-secrets.ts` + test
- Modify: `frontend/hooks/managed/use-service-credentials.ts` + test
- Modify: `frontend/app/managed/environments/page.tsx`
- Modify: `frontend/app/managed/environments/[envId]/page.tsx`

**Contract:** Agent model references and Environment service references must resolve to non-archived credentials. Selector/fetch-all paths therefore send `include_archived=false` before pagination. Exact by-name conflict lookup may keep the omitted legacy behavior because it is not a binding-option query. Environment pages keep `usePaginatedList` + `parseCredentialId` so the typed-cursor architecture guard remains intact.

- [ ] **Step 1: Red tests** — assert model compatibility/protocol and Service Credential selector URLs contain `include_archived=false` on every page.
- [ ] **Step 2: Implement** — add the explicit parameter to the two shared hooks and both Environment page list calls.
- [ ] **Step 3: Green** — run both hook suites plus TypeScript.

---

### Task 2: i18n — §3.12 vocabulary, per-tab keys, semantic pins, converge modelConfiguration

**Files:**
- Modify: `frontend/lib/i18n/locales/en.ts`, `frontend/lib/i18n/locales/zh.ts`
- Modify: `frontend/lib/i18n/credential-terminology.test.ts`

**New keys (values verbatim; en → `en.ts`, zh → `zh.ts`):**

| Key | en | zh |
|---|---|---|
| `nav.credentials` | `Models & Credentials` | `模型与凭据` |
| `managed.credentials.title` | `Models & Credentials` | `模型与凭据` |
| `managed.credentials.subtitle` | `Model connections, service credentials, and MCP credential vaults for this project.` | `本项目的模型连接、服务凭据与 MCP 凭据库。` |
| `managed.credentials.tabs.models` | `Model Connections` | `模型连接` |
| `managed.credentials.tabs.services` | `Service Credentials` | `服务凭据` |
| `managed.credentials.tabs.mcp` | `MCP Credential Vaults` | `MCP 凭据库` |
| `managed.credentials.new` | `New` | `新建` |
| `managed.credentials.addModelConnection` | `Add Model Connection` | `添加模型连接` |
| `managed.credentials.addServiceCredential` | `Add Service Credential` | `添加服务凭据` |
| `managed.credentials.newMcpVault` | `New MCP Credential Vault` | `新建 MCP 凭据库` |
| `managed.credentials.searchModelsOnPage` | `Search model connections on this page` | `在本页搜索模型连接` |
| `managed.credentials.searchServicesOnPage` | `Search service credentials on this page` | `在本页搜索服务凭据` |
| `managed.credentials.emptyModels` | `No model connections yet.` | `暂无模型连接。` |
| `managed.credentials.emptyServices` | `No service credentials yet.` | `暂无服务凭据。` |
| `managed.credentials.chooser.title` | `Create` | `创建` |
| `managed.credentials.chooser.description` | `Choose what to create.` | `选择要创建的资源。` |
| `managed.credentials.chooser.model` | `Model Connection` | `模型连接` |
| `managed.credentials.chooser.modelDescription` | `Connect an LLM provider for agents to use.` | `接入 LLM 供应商供智能体使用。` |
| `managed.credentials.chooser.service` | `Service Credential` | `服务凭据` |
| `managed.credentials.chooser.serviceDescription` | `Store API keys and secrets for egress services.` | `保存出网服务的 API 密钥与机密。` |
| `managed.credentials.chooser.vault` | `MCP Credential Vault` | `MCP 凭据库` |
| `managed.credentials.chooser.vaultDescription` | `Group MCP bearer credentials for sessions.` | `为会话分组管理 MCP Bearer 凭据。` |

**Converge (B5):** change `managed.llm.modelConfiguration` zh from `模型接入` (drift) to `模型连接` in `zh.ts`. (en stays `Model Connection`.)

- [ ] **Step 1: Write failing semantic assertions** — add to `credential-terminology.test.ts` (match its `en`/`zh` import names):
```ts
describe('unified credentials surface vocabulary (P1, §3.12)', () => {
  it('lands the merged menu + tab labels as Model Connection (not 模型接入)', () => {
    expect(en.translation.nav.credentials).toBe('Models & Credentials')
    expect(zh.translation.nav.credentials).toBe('模型与凭据')
    expect(en.translation.managed.credentials.tabs.models).toBe('Model Connections')
    expect(zh.translation.managed.credentials.tabs.models).toBe('模型连接')
    expect(zh.translation.managed.llm.modelConfiguration).toBe('模型连接')
  })
  it('uses a neutral create action, not a "credential" umbrella', () => {
    expect(en.translation.managed.credentials.new).toBe('New')
    expect(en.translation.managed.credentials.chooser.description).toBe('Choose what to create.')
    expect(en.translation.managed.credentials.chooser.model).toBe('Model Connection')
    expect(en.translation.managed.credentials.chooser.vault).toBe('MCP Credential Vault')
  })
})
```
Also update the EXISTING pin that asserts `managed.llm.modelConfiguration` zh — change its expected value from `模型接入` to `模型连接` (locate the assertion; it is a pin, not an inventory count).

- [ ] **Step 2: Run to verify it fails** — `cd frontend && bun run test credential-terminology -t "unified credentials surface"` → FAIL.
- [ ] **Step 3: Add the keys + converge** — add every row above to `en.ts` + `zh.ts`; flip `managed.llm.modelConfiguration` zh to `模型连接`.
- [ ] **Step 4: Pass the semantic block** — `cd frontend && bun run test credential-terminology -t "unified credentials surface"` → PASS. (Inventory counts elsewhere in the file are now red — EXPECTED, reconciled in Task 14.)
- [ ] **Step 5: Type-check** — `cd frontend && bun run type-check` → clean (locales stay key-aligned).
- [ ] **Step 6: Commit**
```bash
git add -- frontend/lib/i18n/locales/en.ts frontend/lib/i18n/locales/zh.ts frontend/lib/i18n/credential-terminology.test.ts
git commit -m "feat(credentials): land §3.12 Model Connection vocabulary + merged-surface keys"
```

---

### Task 3: `ModelConnectionList` (kind=model, catalog-gated)

**Files:**
- Create: `frontend/components/managed/credentials/model-connection-list.tsx`
- Test: `frontend/components/managed/credentials/model-connection-list.test.tsx`

**Interfaces:** `<ModelConnectionList onCreate={() => void} state? onStateChange? />`. Own loading/error/empty; gates ONLY on the LLM catalog. Row click → `/managed/credentials/[id]`. Active rows expose set-default/archive/delete; archived rows expose restore/delete and never set-default. Search/created-filter/show-archived/page-size are controllable so the shell can retain tab state. The list passes `includeArchived: showArchived`; default `false` must reach the server. Client-side `(showArchived || !archived_at)` is defense-in-depth only. Every mutation uses `useScopedActions`: request options come from the action's scope snapshot, stale completions cannot invalidate/cache-update/navigate, and confirmation revalidates the row's current lifecycle state.

- [ ] **Step 1: Write the failing test** — mock the catalog HOOK (not `/llm/catalog` payload) so no real catalog schema is needed:
```tsx
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { describe, expect, it, vi } from 'vitest'

vi.mock('@/lib/i18n', () => ({ useTranslation: () => ({ t: (k: string) => k }) }))
vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn() }) }))
vi.mock('@/lib/api-client', () => ({ managedGet: vi.fn(), managedPost: vi.fn(), managedDelete: vi.fn() }))
vi.mock('@/lib/managed/request-scope', () => ({
  useManagedRequestScope: () => ({ orgId: 'o', projectId: 'p', key: 'o:p' }),
  managedRequestOptions: () => ({}),
  hasManagedRequestScope: () => true,
}))
vi.mock('@/hooks/managed/use-current-project-read-only', () => ({ useCurrentProjectReadOnly: () => false }))
vi.mock('@/hooks/managed/use-llm-catalog', () => ({
  useLlmCatalog: () => ({ isSuccess: true, isError: false, data: { version: 'v1' }, refetch: vi.fn() }),
}))
vi.mock('@/components/managed/shared/compatible-engine-badges', () => ({ CompatibleEngineBadges: () => null }))

import { managedGet } from '@/lib/api-client'
import { ModelConnectionList } from './model-connection-list'

const managedGetMock = managedGet as unknown as ReturnType<typeof vi.fn>
function Wrap({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>
}

describe('ModelConnectionList', () => {
  it('requests only kind=model credentials', async () => {
    managedGetMock.mockResolvedValue({ data: [], has_more: false })
    render(<Wrap><ModelConnectionList onCreate={() => {}} /></Wrap>)
    await waitFor(() => {
      const cred = managedGetMock.mock.calls.find(([u]) => (u as string).startsWith('/credentials'))
      expect(cred![0]).toContain('kind=model')
    })
  })
})
```

- [ ] **Step 2: Run to verify it fails** — `cd frontend && bun run test model-connection-list` → FAIL (module missing).

- [ ] **Step 3: Implement** `model-connection-list.tsx`:
```tsx
'use client'

import { useQueryClient } from '@tanstack/react-query'
import { Check, Plus, Star } from 'lucide-react'
import { useRouter } from 'next/navigation'
import { useMemo, useState } from 'react'

import { CompatibleEngineBadges } from '@/components/managed/shared/compatible-engine-badges'
import { LlmCatalogPageState } from '@/components/managed/llm/llm-catalog-page-state'
import {
  ConfirmDialog,
  DataTable,
  FilterBar,
  MonoId,
  RelativeTime,
  ResourceErrorState,
  type Column,
  type FilterDef,
} from '@/components/managed/shared'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { useCurrentProjectReadOnly } from '@/hooks/managed/use-current-project-read-only'
import { useLlmCatalog } from '@/hooks/managed/use-llm-catalog'
import { usePaginatedList } from '@/hooks/managed/use-paginated-list'
import { managedDelete, managedPost } from '@/lib/api-client'
import { useTranslation } from '@/lib/i18n'
import { apiResourcePath } from '@/lib/managed/api-paths'
import { toastOperationError } from '@/lib/managed/errors'
import { createCreatedTimeFilter, filterByCreatedTime, matchesSearch } from '@/lib/managed/filters'
import { managedRequestOptions, useManagedRequestScope } from '@/lib/managed/request-scope'
import { parseSecretResponse } from '@/lib/managed/secret-response-parsers'
import { parseCredentialId } from '@/types/entity-id'
import type { Secret } from '@/types/managed'

function displayId(value: string | null) {
  if (!value) return '—'
  return value.split('_').map((p) => p.charAt(0).toUpperCase() + p.slice(1)).join(' ')
}

export function ModelConnectionList({ onCreate }: { onCreate: () => void }) {
  const { t } = useTranslation()
  const router = useRouter()
  const queryClient = useQueryClient()
  const managedScope = useManagedRequestScope()
  const projectReadOnly = useCurrentProjectReadOnly()
  const catalogQuery = useLlmCatalog()
  const catalogVersion = catalogQuery.data?.version ?? ''
  const catalogReady = catalogQuery.isSuccess && Boolean(catalogVersion)
  const [searchQuery, setSearchQuery] = useState('')
  const [createdFilter, setCreatedFilter] = useState('all')
  const [deleteTarget, setDeleteTarget] = useState<Secret | null>(null)

  const list = usePaginatedList<Secret>({
    queryKey: 'credentials',
    path: '/credentials',
    query: { kind: 'model' },
    cacheVersion: catalogVersion || undefined,
    enabled: catalogReady,
    parseItem: parseSecretResponse,
    parseCursor: parseCredentialId,
  })

  const filtered = useMemo(
    () =>
      list.data.filter(
        (s) =>
          filterByCreatedTime(s.created_at, createdFilter) &&
          matchesSearch(searchQuery, [s.id, s.name, s.provider ?? '', s.protocol ?? '', s.model ?? '']),
      ),
    [createdFilter, list.data, searchQuery],
  )
  const filters: FilterDef[] = [{ ...createCreatedTimeFilter(t), value: createdFilter, onChange: setCreatedFilter }]

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['credentials', managedScope.key] })
    queryClient.invalidateQueries({ queryKey: ['compatible-secrets', managedScope.key] })
  }
  const handleSetDefault = async (s: Secret) => {
    if (s.kind !== 'model' || projectReadOnly) return
    try {
      await managedPost(apiResourcePath('credentials', s.id, 'default'), {}, managedRequestOptions(managedScope))
      invalidate()
    } catch (error) {
      toastOperationError(t, error, 'common.operationFailed')
    }
  }
  const handleDelete = async () => {
    if (!deleteTarget || projectReadOnly) return
    try {
      await managedDelete(apiResourcePath('credentials', deleteTarget.id), managedRequestOptions(managedScope))
      invalidate()
    } catch (error) {
      toastOperationError(t, error, 'common.operationFailed')
    } finally {
      setDeleteTarget(null)
    }
  }

  const columns: Column<Secret>[] = [
    { key: 'id', header: t('managed.table.id'), render: (s) => <MonoId id={s.id} /> },
    {
      key: 'name',
      header: t('managed.table.name'),
      render: (s) => (
        <div className="space-y-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-medium">{s.name}</span>
            {s.is_default ? (
              <Badge variant="secondary" className="gap-1">
                <Check className="h-3 w-3" />
                {t('managed.secrets.default')}
              </Badge>
            ) : null}
          </div>
          {s.model ? <p className="text-xs text-muted-foreground">{s.model}</p> : null}
        </div>
      ),
    },
    {
      key: 'binding',
      header: t('managed.llm.providerProtocol'),
      render: (s) => (
        <div className="text-xs">
          <p className="font-medium text-foreground">{displayId(s.provider)}</p>
          <p className="text-muted-foreground">{displayId(s.protocol)}</p>
        </div>
      ),
    },
    {
      key: 'engines',
      header: t('managed.llm.compatibleEngines'),
      render: (s) => <CompatibleEngineBadges engineIds={s.compatible_engine_ids} catalog={catalogQuery.data} />,
    },
    {
      key: 'created_at',
      header: t('managed.table.created'),
      render: (s) => <span className="text-xs text-muted-foreground"><RelativeTime date={s.created_at} /></span>,
    },
  ]

  if (catalogQuery.isError) return <LlmCatalogPageState state="error" onRetry={() => catalogQuery.refetch()} />
  if (!catalogReady) return <LlmCatalogPageState state="loading" />
  if (list.isError)
    return (
      <ResourceErrorState
        error={list.error}
        resource="secret"
        onRetry={() => queryClient.invalidateQueries({ queryKey: ['credentials', managedScope.key] })}
      />
    )

  return (
    <div>
      {projectReadOnly ? null : (
        <div className="mb-3 flex justify-end">
          <Button size="sm" onClick={onCreate}>
            <Plus className="h-4 w-4" />
            {t('managed.credentials.addModelConnection')}
          </Button>
        </div>
      )}
      <FilterBar
        searchPlaceholder={t('managed.credentials.searchModelsOnPage')}
        searchValue={searchQuery}
        onSearchChange={setSearchQuery}
        filters={filters}
      />
      <DataTable
        columns={columns}
        data={filtered}
        loading={list.isLoading}
        fetching={list.isFetching}
        onRowClick={(s) => router.push(`/managed/credentials/${s.id}`)}
        actionMenu={(s) =>
          projectReadOnly
            ? []
            : [
                ...(s.kind === 'model' && !s.is_default
                  ? [{ label: t('managed.secrets.setDefault'), icon: <Star className="h-4 w-4" />, onClick: () => handleSetDefault(s) }]
                  : []),
                { label: t('common.delete'), onClick: () => setDeleteTarget(s), destructive: true },
              ]
        }
        pagination={{
          hasNext: list.hasNext,
          hasPrev: list.hasPrev,
          page: list.page,
          pageSize: list.pageSize,
          pageSizeOptions: list.pageSizeOptions,
          onNext: list.goNext,
          onPrev: list.goPrev,
          onPageChange: list.goToPage,
          onPageSizeChange: list.setPageSize,
        }}
        emptyMessage={t('managed.credentials.emptyModels')}
      />
      <ConfirmDialog
        open={!projectReadOnly && Boolean(deleteTarget)}
        title={t('managed.secrets.deleteTitle')}
        description={t('managed.secrets.deleteDescription', { name: deleteTarget?.name })}
        confirmLabel={t('common.delete')}
        destructive
        onConfirm={handleDelete}
        onCancel={() => setDeleteTarget(null)}
      />
    </div>
  )
}
```

- [ ] **Step 4: Pass** — `cd frontend && bun run test model-connection-list` → PASS.
- [ ] **Step 5: Guards** — `cd frontend && bun run type-check && bun run lint` → clean.
- [ ] **Step 6: Commit**
```bash
git add -- frontend/components/managed/credentials/model-connection-list.tsx frontend/components/managed/credentials/model-connection-list.test.tsx
git commit -m "feat(credentials): extract ModelConnectionList (kind=model, catalog-gated)"
```

---

### Task 4: `ServiceCredentialList` (kind=service, NOT catalog-gated)

**Files:**
- Create: `frontend/components/managed/credentials/service-credential-list.tsx`
- Test: `frontend/components/managed/credentials/service-credential-list.test.tsx`

**Interfaces:** `<ServiceCredentialList onCreate={() => void} state? onStateChange? />`. No `useLlmCatalog`. Active rows expose archive/delete; archived rows expose restore/delete. Search/created-filter/show-archived/page-size are controllable so the shell can retain tab state. The list passes `includeArchived: showArchived`; default `false` must reach the server. Client-side `(showArchived || !archived_at)` is defense-in-depth only. Every mutation uses `useScopedActions`, a request-scope snapshot, stale-completion guards, and confirmation-time lifecycle-state revalidation. Uses `addServiceCredential`, `searchServicesOnPage`, and `emptyServices`.

- [ ] **Step 1: Write the failing test:**
```tsx
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { describe, expect, it, vi } from 'vitest'

vi.mock('@/lib/i18n', () => ({ useTranslation: () => ({ t: (k: string) => k }) }))
vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn() }) }))
vi.mock('@/lib/api-client', () => ({ managedGet: vi.fn(), managedDelete: vi.fn() }))
vi.mock('@/lib/managed/request-scope', () => ({
  useManagedRequestScope: () => ({ orgId: 'o', projectId: 'p', key: 'o:p' }),
  managedRequestOptions: () => ({}),
  hasManagedRequestScope: () => true,
}))
vi.mock('@/hooks/managed/use-current-project-read-only', () => ({ useCurrentProjectReadOnly: () => false }))

import { managedGet } from '@/lib/api-client'
import { ServiceCredentialList } from './service-credential-list'

const managedGetMock = managedGet as unknown as ReturnType<typeof vi.fn>
function Wrap({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>
}

describe('ServiceCredentialList', () => {
  it('requests only kind=service and never touches the LLM catalog', async () => {
    managedGetMock.mockResolvedValue({ data: [], has_more: false })
    render(<Wrap><ServiceCredentialList onCreate={() => {}} /></Wrap>)
    await waitFor(() => {
      const cred = managedGetMock.mock.calls.find(([u]) => (u as string).startsWith('/credentials'))
      expect(cred![0]).toContain('kind=service')
    })
    expect(managedGetMock.mock.calls.some(([u]) => (u as string).startsWith('/llm/catalog'))).toBe(false)
  })
})
```

- [ ] **Step 2: Fail** — `cd frontend && bun run test service-credential-list` → FAIL.

- [ ] **Step 3: Implement** `service-credential-list.tsx`:
```tsx
'use client'

import { useQueryClient } from '@tanstack/react-query'
import { Plus } from 'lucide-react'
import { useRouter } from 'next/navigation'
import { useMemo, useState } from 'react'

import {
  ConfirmDialog,
  DataTable,
  FilterBar,
  MonoId,
  RelativeTime,
  ResourceErrorState,
  type Column,
  type FilterDef,
} from '@/components/managed/shared'
import { Button } from '@/components/ui/button'
import { useCurrentProjectReadOnly } from '@/hooks/managed/use-current-project-read-only'
import { usePaginatedList } from '@/hooks/managed/use-paginated-list'
import { managedDelete } from '@/lib/api-client'
import { useTranslation } from '@/lib/i18n'
import { apiResourcePath } from '@/lib/managed/api-paths'
import { toastOperationError } from '@/lib/managed/errors'
import { createCreatedTimeFilter, filterByCreatedTime, matchesSearch } from '@/lib/managed/filters'
import { managedRequestOptions, useManagedRequestScope } from '@/lib/managed/request-scope'
import { parseSecretResponse } from '@/lib/managed/secret-response-parsers'
import { parseCredentialId } from '@/types/entity-id'
import type { Secret } from '@/types/managed'

export function ServiceCredentialList({ onCreate }: { onCreate: () => void }) {
  const { t } = useTranslation()
  const router = useRouter()
  const queryClient = useQueryClient()
  const managedScope = useManagedRequestScope()
  const projectReadOnly = useCurrentProjectReadOnly()
  const [searchQuery, setSearchQuery] = useState('')
  const [createdFilter, setCreatedFilter] = useState('all')
  const [deleteTarget, setDeleteTarget] = useState<Secret | null>(null)

  const list = usePaginatedList<Secret>({
    queryKey: 'credentials',
    path: '/credentials',
    query: { kind: 'service' },
    parseItem: parseSecretResponse,
    parseCursor: parseCredentialId,
  })

  const filtered = useMemo(
    () =>
      list.data.filter(
        (s) => filterByCreatedTime(s.created_at, createdFilter) && matchesSearch(searchQuery, [s.id, s.name]),
      ),
    [createdFilter, list.data, searchQuery],
  )
  const filters: FilterDef[] = [{ ...createCreatedTimeFilter(t), value: createdFilter, onChange: setCreatedFilter }]

  const handleDelete = async () => {
    if (!deleteTarget || projectReadOnly) return
    try {
      await managedDelete(apiResourcePath('credentials', deleteTarget.id), managedRequestOptions(managedScope))
      queryClient.invalidateQueries({ queryKey: ['credentials', managedScope.key] })
    } catch (error) {
      toastOperationError(t, error, 'common.operationFailed')
    } finally {
      setDeleteTarget(null)
    }
  }

  const columns: Column<Secret>[] = [
    { key: 'id', header: t('managed.table.id'), render: (s) => <MonoId id={s.id} /> },
    { key: 'name', header: t('managed.table.name'), render: (s) => <span className="font-medium text-foreground">{s.name}</span> },
    {
      key: 'created_at',
      header: t('managed.table.created'),
      render: (s) => <span className="text-xs text-muted-foreground"><RelativeTime date={s.created_at} /></span>,
    },
  ]

  if (list.isError)
    return (
      <ResourceErrorState
        error={list.error}
        resource="secret"
        onRetry={() => queryClient.invalidateQueries({ queryKey: ['credentials', managedScope.key] })}
      />
    )

  return (
    <div>
      {projectReadOnly ? null : (
        <div className="mb-3 flex justify-end">
          <Button size="sm" onClick={onCreate}>
            <Plus className="h-4 w-4" />
            {t('managed.credentials.addServiceCredential')}
          </Button>
        </div>
      )}
      <FilterBar
        searchPlaceholder={t('managed.credentials.searchServicesOnPage')}
        searchValue={searchQuery}
        onSearchChange={setSearchQuery}
        filters={filters}
      />
      <DataTable
        columns={columns}
        data={filtered}
        loading={list.isLoading}
        fetching={list.isFetching}
        onRowClick={(s) => router.push(`/managed/credentials/${s.id}`)}
        actionMenu={(s) =>
          projectReadOnly ? [] : [{ label: t('common.delete'), onClick: () => setDeleteTarget(s), destructive: true }]
        }
        pagination={{
          hasNext: list.hasNext,
          hasPrev: list.hasPrev,
          page: list.page,
          pageSize: list.pageSize,
          pageSizeOptions: list.pageSizeOptions,
          onNext: list.goNext,
          onPrev: list.goPrev,
          onPageChange: list.goToPage,
          onPageSizeChange: list.setPageSize,
        }}
        emptyMessage={t('managed.credentials.emptyServices')}
      />
      <ConfirmDialog
        open={!projectReadOnly && Boolean(deleteTarget)}
        title={t('managed.secrets.deleteTitle')}
        description={t('managed.secrets.deleteDescription', { name: deleteTarget?.name })}
        confirmLabel={t('common.delete')}
        destructive
        onConfirm={handleDelete}
        onCancel={() => setDeleteTarget(null)}
      />
    </div>
  )
}
```

- [ ] **Step 4: Pass** — `cd frontend && bun run test service-credential-list` → PASS.
- [ ] **Step 5: Guards** — `cd frontend && bun run type-check && bun run lint` → clean.
- [ ] **Step 6: Commit**
```bash
git add -- frontend/components/managed/credentials/service-credential-list.tsx frontend/components/managed/credentials/service-credential-list.test.tsx
git commit -m "feat(credentials): extract ServiceCredentialList (kind=service, catalog-independent)"
```

---

### Task 5: `McpVaultList` (credential-groups, race-safe archive/delete)

**Files:**
- Create: `frontend/components/managed/credentials/mcp-vault-list.tsx`
- Test: `frontend/components/managed/credentials/mcp-vault-list.test.tsx`

**Interfaces:** `<McpVaultList onCreate={() => void} />`. Full `useScopedActions` archive/delete race-safety preserved; row click → `/managed/credentials/mcp/[id]`; create button → `onCreate()`; `newMcpVault` label.

- [ ] **Step 1: Write the failing test:**
```tsx
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { describe, expect, it, vi } from 'vitest'

vi.mock('@/lib/i18n', () => ({ useTranslation: () => ({ t: (k: string) => k }) }))
vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn() }) }))
vi.mock('@/lib/api-client', () => ({ managedGet: vi.fn(), managedPost: vi.fn(), managedDelete: vi.fn() }))
vi.mock('@/lib/managed/request-scope', () => ({
  useManagedRequestScope: () => ({ orgId: 'o', projectId: 'p', key: 'o:p' }),
  managedRequestOptions: () => ({}),
  hasManagedRequestScope: () => true,
}))

import { managedGet } from '@/lib/api-client'
import { McpVaultList } from './mcp-vault-list'

const managedGetMock = managedGet as unknown as ReturnType<typeof vi.fn>
function Wrap({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>
}

describe('McpVaultList', () => {
  it('lists credential-groups and never touches the LLM catalog', async () => {
    managedGetMock.mockResolvedValue({ data: [], has_more: false })
    render(<Wrap><McpVaultList onCreate={() => {}} /></Wrap>)
    await waitFor(() =>
      expect(managedGetMock.mock.calls.some(([u]) => (u as string).startsWith('/credential-groups'))).toBe(true),
    )
    expect(managedGetMock.mock.calls.some(([u]) => (u as string).startsWith('/llm/catalog'))).toBe(false)
  })
})
```

- [ ] **Step 2: Fail** — `cd frontend && bun run test mcp-vault-list` → FAIL.

- [ ] **Step 3: Implement** `mcp-vault-list.tsx` (adapted verbatim from `app/managed/vaults/page.tsx`; drops the `createOpen` state, `PageHeader`, and `CreateVaultDialog`; create button → `onCreate()`; row → mcp detail):
```tsx
'use client'

import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Plus, Trash2 } from 'lucide-react'
import { useRouter } from 'next/navigation'
import { useEffect, useState } from 'react'

import {
  ConfirmDialog,
  DataTable,
  FilterBar,
  MonoId,
  RelativeTime,
  ResourceErrorState,
  StatusBadge,
  type Column,
  type FilterDef,
} from '@/components/managed/shared'
import { Button } from '@/components/ui/button'
import { currentProjectAllowsWrite } from '@/hooks/managed/use-current-project-read-only'
import { usePaginatedList } from '@/hooks/managed/use-paginated-list'
import { useScopedActions } from '@/hooks/managed/use-scoped-actions'
import { managedDelete, managedPost } from '@/lib/api-client'
import { useTranslation } from '@/lib/i18n'
import { apiResourcePath } from '@/lib/managed/api-paths'
import { toastOperationError } from '@/lib/managed/errors'
import { createCreatedTimeFilter, filterByCreatedTime, matchesSearch } from '@/lib/managed/filters'
import { managedRequestOptions, type ManagedRequestScope } from '@/lib/managed/request-scope'
import { parseVaultResponse } from '@/lib/managed/vault-response-parsers'
import { parseCredentialGroupId } from '@/types/entity-id'
import type { Vault } from '@/types/managed'

interface VaultActionVariables {
  vault: Vault
  runId: number
  scope: string
  requestScope: ManagedRequestScope
}

export function McpVaultList({ onCreate }: { onCreate: () => void }) {
  const { t } = useTranslation()
  const router = useRouter()
  const queryClient = useQueryClient()
  const [showArchived, setShowArchived] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const [createdFilter, setCreatedFilter] = useState('all')
  const [archiveTarget, setArchiveTarget] = useState<Vault | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<Vault | null>(null)
  const {
    scopeRef: managedScopeRef,
    scope: managedScope,
    readOnly,
    beginAction,
    isCurrentAction,
    scopeIsActive,
    bumpRun,
  } = useScopedActions({
    onReset: () => {
      setArchiveTarget(null)
      setDeleteTarget(null)
    },
  })

  const currentVaultIsActive = (vault: Vault, scope: string) =>
    scopeIsActive(scope) &&
    currentProjectAllowsWrite() &&
    queryClient
      .getQueriesData<{ data?: Vault[] }>({ queryKey: ['credential-groups', scope, '/credential-groups'] })
      .some(([, page]) => page?.data?.some((v) => v.id === vault.id && !v.archived_at))

  const openArchiveDialog = (vault: Vault) => {
    if (!currentVaultIsActive(vault, managedScopeRef.current)) return
    bumpRun()
    setArchiveTarget(vault)
  }
  const closeArchiveDialog = () => {
    bumpRun()
    setArchiveTarget(null)
  }
  const openDeleteDialog = (vault: Vault) => {
    if (!currentVaultIsActive(vault, managedScopeRef.current)) return
    bumpRun()
    setDeleteTarget(vault)
  }
  const closeDeleteDialog = () => {
    bumpRun()
    setDeleteTarget(null)
  }

  const { data, isLoading, isFetching, isError, error, hasNext, hasPrev, page, pageSize, pageSizeOptions, goNext, goPrev, goToPage, setPageSize } =
    usePaginatedList<Vault>({
      queryKey: 'credential-groups',
      path: '/credential-groups',
      includeArchived: showArchived,
      parseItem: parseVaultResponse,
      parseCursor: parseCredentialGroupId,
    })

  const archiveMutation = useMutation({
    mutationFn: ({ vault, runId, scope, requestScope }: VaultActionVariables) => {
      if (!isCurrentAction(runId, scope)) throw new Error('Stale vault archive ignored')
      if (!currentProjectAllowsWrite()) throw new Error('Archived project vault archive ignored')
      return managedPost(apiResourcePath('credential-groups', vault.id, 'archive'), {}, managedRequestOptions(requestScope))
    },
    onSuccess: (_d, { runId, scope }) => {
      if (!isCurrentAction(runId, scope)) return
      queryClient.invalidateQueries({ queryKey: ['credential-groups', scope] })
      setArchiveTarget(null)
    },
    onError: (err, { runId, scope }) => {
      if (!isCurrentAction(runId, scope)) return
      toastOperationError(t, err, 'common.operationFailed')
    },
  })
  const deleteMutation = useMutation({
    mutationFn: ({ vault, runId, scope, requestScope }: VaultActionVariables) => {
      if (!isCurrentAction(runId, scope)) throw new Error('Stale vault delete ignored')
      if (!currentProjectAllowsWrite()) throw new Error('Archived project vault delete ignored')
      return managedDelete(apiResourcePath('credential-groups', vault.id), managedRequestOptions(requestScope))
    },
    onSuccess: (_d, { runId, scope }) => {
      if (!isCurrentAction(runId, scope)) return
      queryClient.invalidateQueries({ queryKey: ['credential-groups', scope] })
      setDeleteTarget(null)
    },
    onError: (err, { runId, scope }) => {
      if (!isCurrentAction(runId, scope)) return
      toastOperationError(t, err, 'common.operationFailed')
    },
  })

  const vaults = data.filter(
    (v) =>
      (showArchived || !v.archived_at) &&
      filterByCreatedTime(v.created_at, createdFilter) &&
      matchesSearch(searchQuery, [v.id, v.name, v.archived_at ? 'archived' : 'active']),
  )
  const filters: FilterDef[] = [{ ...createCreatedTimeFilter(t), value: createdFilter, onChange: setCreatedFilter }]

  useEffect(() => {
    const activeById = new Map(data.filter((v) => !v.archived_at).map((v) => [v.id, v]))
    setArchiveTarget((target) => {
      if (!target) return null
      const current = activeById.get(target.id) ?? null
      if (!current) bumpRun()
      return current
    })
    setDeleteTarget((target) => {
      if (!target) return null
      const current = activeById.get(target.id) ?? null
      if (!current) bumpRun()
      return current
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data])

  const columns: Column<Vault>[] = [
    { key: 'id', header: t('managed.table.id'), render: (v) => <MonoId id={v.id} /> },
    { key: 'name', header: t('managed.table.name'), render: (v) => <span className="font-medium text-foreground">{v.name}</span> },
    { key: 'status', header: t('managed.table.status'), render: (v) => <StatusBadge status={v.archived_at ? 'archived' : 'active'} /> },
    {
      key: 'created_at',
      header: t('managed.table.created'),
      render: (v) => <span className="text-xs text-muted-foreground"><RelativeTime date={v.created_at} /></span>,
    },
  ]

  if (isError)
    return (
      <ResourceErrorState
        error={error}
        resource="vault"
        onRetry={() => queryClient.invalidateQueries({ queryKey: ['credential-groups', managedScope.key] })}
      />
    )

  return (
    <div>
      {readOnly ? null : (
        <div className="mb-3 flex justify-end">
          <Button
            size="sm"
            onClick={() => {
              if (!currentProjectAllowsWrite()) return
              if (!scopeIsActive()) return
              onCreate()
            }}
          >
            <Plus className="h-4 w-4" />
            {t('managed.credentials.newMcpVault')}
          </Button>
        </div>
      )}
      <FilterBar
        searchPlaceholder={t('managed.search.vaults')}
        searchValue={searchQuery}
        onSearchChange={setSearchQuery}
        filters={filters}
        showArchived={showArchived}
        onArchivedChange={setShowArchived}
      />
      <DataTable
        columns={columns}
        data={vaults}
        loading={isLoading}
        fetching={isFetching}
        onRowClick={(v) => router.push(`/managed/credentials/mcp/${v.id}`)}
        actionMenu={(v) =>
          readOnly || v.archived_at
            ? []
            : [
                { label: t('managed.vaults.archiveVault'), onClick: () => openArchiveDialog(v) },
                { label: t('common.delete'), destructive: true, icon: <Trash2 className="h-3.5 w-3.5" />, onClick: () => openDeleteDialog(v) },
              ]
        }
        pagination={{
          hasNext,
          hasPrev,
          page,
          pageSize,
          pageSizeOptions,
          onNext: goNext,
          onPrev: goPrev,
          onPageChange: goToPage,
          onPageSizeChange: setPageSize,
        }}
        emptyMessage={t('managed.vaults.empty')}
      />
      <ConfirmDialog
        open={!readOnly && !!archiveTarget}
        title={t('managed.vaults.archiveTitle')}
        description={t('managed.vaults.archiveDescription', { name: archiveTarget?.name })}
        confirmLabel={t('common.archive')}
        destructive
        onConfirm={() => {
          if (!currentProjectAllowsWrite()) return closeArchiveDialog()
          if (archiveTarget) {
            if (!currentVaultIsActive(archiveTarget, managedScopeRef.current)) return closeArchiveDialog()
            const action = beginAction()
            if (!action) return closeArchiveDialog()
            archiveMutation.mutate({ vault: archiveTarget, runId: action.runId, scope: action.scope, requestScope: action.requestScope })
          }
        }}
        onCancel={closeArchiveDialog}
      />
      <ConfirmDialog
        open={!readOnly && !!deleteTarget}
        title={t('managed.vaults.deleteTitle')}
        description={t('managed.vaults.deleteDescription', { name: deleteTarget?.name })}
        confirmLabel={t('common.delete')}
        destructive
        onConfirm={() => {
          if (!currentProjectAllowsWrite()) return closeDeleteDialog()
          if (deleteTarget) {
            if (!currentVaultIsActive(deleteTarget, managedScopeRef.current)) return closeDeleteDialog()
            const action = beginAction()
            if (!action) return closeDeleteDialog()
            deleteMutation.mutate({ vault: deleteTarget, runId: action.runId, scope: action.scope, requestScope: action.requestScope })
          }
        }}
        onCancel={closeDeleteDialog}
      />
    </div>
  )
}
```
> The two `ConfirmDialog onConfirm` bodies use `return closeXDialog()` (void) for brevity; if lint objects to returning a void expression, expand to `{ closeXDialog(); return }`.

- [ ] **Step 4: Pass** — `cd frontend && bun run test mcp-vault-list` → PASS.
- [ ] **Step 5: Guards** — `cd frontend && bun run type-check && bun run lint` → clean.
- [ ] **Step 6: Commit**
```bash
git add -- frontend/components/managed/credentials/mcp-vault-list.tsx frontend/components/managed/credentials/mcp-vault-list.test.tsx
git commit -m "feat(credentials): extract McpVaultList (credential-groups, catalog-independent)"
```

---

### Task 6: `CredentialKindChooser`

**Files:**
- Create: `frontend/components/managed/credentials/credential-kind-chooser.tsx`
- Test: `frontend/components/managed/credentials/credential-kind-chooser.test.tsx`

**Interfaces:** `type CredentialKindChoice = 'model' | 'service' | 'vault'`; `<CredentialKindChooser open onOpenChange onChoose />`. Title "Create", description "Choose what to create." Choosing calls `onChoose(kind)` then `onOpenChange(false)`.

- [ ] **Step 1: Write the failing test:**
```tsx
import { fireEvent, render } from '@testing-library/react'
import type { ReactNode } from 'react'
import { describe, expect, it, vi } from 'vitest'

vi.mock('@/lib/i18n', () => ({ useTranslation: () => ({ t: (k: string) => k }) }))
vi.mock('@/components/ui/dialog', () => ({
  Dialog: ({ children, open }: { children: ReactNode; open: boolean }) => (open ? <div>{children}</div> : null),
  DialogContent: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  DialogDescription: ({ children }: { children: ReactNode }) => <p>{children}</p>,
  DialogHeader: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  DialogTitle: ({ children }: { children: ReactNode }) => <h1>{children}</h1>,
}))

import { CredentialKindChooser } from './credential-kind-chooser'

describe('CredentialKindChooser', () => {
  it('emits the chosen kind and closes', () => {
    const onChoose = vi.fn()
    const onOpenChange = vi.fn()
    const { getByText } = render(<CredentialKindChooser open onOpenChange={onOpenChange} onChoose={onChoose} />)
    fireEvent.click(getByText('managed.credentials.chooser.vault'))
    expect(onChoose).toHaveBeenCalledWith('vault')
    expect(onOpenChange).toHaveBeenCalledWith(false)
  })
})
```

- [ ] **Step 2: Fail** — `cd frontend && bun run test credential-kind-chooser` → FAIL.

- [ ] **Step 3: Implement** `credential-kind-chooser.tsx`:
```tsx
'use client'

import { KeyRound, Lock, Zap } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { useTranslation } from '@/lib/i18n'

export type CredentialKindChoice = 'model' | 'service' | 'vault'

interface Props {
  open: boolean
  onOpenChange: (open: boolean) => void
  onChoose: (kind: CredentialKindChoice) => void
}

export function CredentialKindChooser({ open, onOpenChange, onChoose }: Props) {
  const { t } = useTranslation()
  const choose = (kind: CredentialKindChoice) => {
    onChoose(kind)
    onOpenChange(false)
  }
  const options: Array<{ kind: CredentialKindChoice; icon: typeof Zap; label: string; description: string }> = [
    { kind: 'model', icon: Zap, label: t('managed.credentials.chooser.model'), description: t('managed.credentials.chooser.modelDescription') },
    { kind: 'service', icon: Lock, label: t('managed.credentials.chooser.service'), description: t('managed.credentials.chooser.serviceDescription') },
    { kind: 'vault', icon: KeyRound, label: t('managed.credentials.chooser.vault'), description: t('managed.credentials.chooser.vaultDescription') },
  ]
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t('managed.credentials.chooser.title')}</DialogTitle>
          <DialogDescription>{t('managed.credentials.chooser.description')}</DialogDescription>
        </DialogHeader>
        <div className="grid gap-3">
          {options.map((o) => (
            <Button key={o.kind} type="button" variant="outline" className="h-auto justify-start gap-3 p-4 text-left" onClick={() => choose(o.kind)}>
              <o.icon className="h-5 w-5 shrink-0" />
              <span className="flex flex-col">
                <span className="font-medium">{o.label}</span>
                <span className="text-xs text-muted-foreground">{o.description}</span>
              </span>
            </Button>
          ))}
        </div>
      </DialogContent>
    </Dialog>
  )
}
```

- [ ] **Step 4: Pass** — `cd frontend && bun run test credential-kind-chooser` → PASS.
- [ ] **Step 5: Guards** — `cd frontend && bun run type-check && bun run lint` → clean.
- [ ] **Step 6: Commit**
```bash
git add -- frontend/components/managed/credentials/credential-kind-chooser.tsx frontend/components/managed/credentials/credential-kind-chooser.test.tsx
git commit -m "feat(credentials): add CredentialKindChooser (neutral create, no umbrella term)"
```

---

### Task 7: Add `lockKind` to `CreateSecretDialog`

**Files:**
- Modify: `frontend/app/managed/secrets/components/create-secret-dialog.tsx`
- Modify: `frontend/app/managed/secrets/components/create-secret-dialog.test.tsx`

**Interfaces:** `CreateSecretDialogProps` gains `lockKind?: boolean` (default `false`). When `true`, the `role="tablist"` switcher is not rendered; `kind` stays `initialKind`. Existing callers unaffected.

- [ ] **Step 1: Failing test** — add to `create-secret-dialog.test.tsx`:
```tsx
it('hides the kind tablist when lockKind is set', () => {
  const { queryByRole } = render(
    <CreateSecretDialog open onOpenChange={() => {}} onCreated={() => {}} initialKind="generic" lockKind />,
  )
  expect(queryByRole('tablist')).toBeNull()
})
```
- [ ] **Step 2: Fail** — `cd frontend && bun run test create-secret-dialog` → FAIL.
- [ ] **Step 3: Implement** — add `lockKind?: boolean` to props; destructure `lockKind = false`; wrap the `<div … role="tablist">…</div>` block in `{lockKind ? null : ( … )}`.
- [ ] **Step 4: Pass** — `cd frontend && bun run test create-secret-dialog` → PASS.
- [ ] **Step 5: Guards** — `cd frontend && bun run type-check && bun run lint` → clean.
- [ ] **Step 6: Commit**
```bash
git add -- frontend/app/managed/secrets/components/create-secret-dialog.tsx frontend/app/managed/secrets/components/create-secret-dialog.test.tsx
git commit -m "feat(credentials): add lockKind to CreateSecretDialog to hide inner kind tabs"
```

---

### Task 8: `CredentialManagementShell` + `/managed/credentials` page (tabs + full create closure)

**Files:**
- Create: `frontend/components/managed/credentials/credential-management-shell.tsx`
- Create: `frontend/app/managed/credentials/page.tsx`
- Test: `frontend/components/managed/credentials/credential-management-shell.test.tsx`

**Interfaces:** `<CredentialManagementShell />` reading `?tab=`. Fixes: (B1) chooser/create switches to the created kind's tab, and `onCreated` invalidates `['credentials', scope]` (+ `['compatible-secrets', scope]` for model); (B1) `create=*` normalizes `tab` to match the kind; (UI#2) `create=*` is permission-gated (read-only → strip param, don't open); (UI#1) global button is "New", per-tab Add labels come from the lists. Illegal `?tab=` → `replace` to models; tab click → `push` (guarded no-op if unchanged); `create` stripped after consumption preserving other params.

- [ ] **Step 1: Write the failing tests** (note the required imports — rev1 omitted `beforeEach`):
```tsx
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const replaceMock = vi.fn()
const pushMock = vi.fn()
let searchParamsValue = new URLSearchParams('')
let readOnlyValue = false

vi.mock('@/lib/i18n', () => ({ useTranslation: () => ({ t: (k: string) => k }) }))
vi.mock('next/navigation', () => ({
  useRouter: () => ({ replace: replaceMock, push: pushMock }),
  useSearchParams: () => searchParamsValue,
}))
vi.mock('@/hooks/managed/use-current-project-read-only', () => ({ useCurrentProjectReadOnly: () => readOnlyValue }))
vi.mock('@/lib/managed/request-scope', () => ({ useManagedRequestScope: () => ({ orgId: 'o', projectId: 'p', key: 'o:p' }) }))
vi.mock('./model-connection-list', () => ({ ModelConnectionList: ({ onCreate }: { onCreate: () => void }) => <button onClick={onCreate}>model-add</button> }))
vi.mock('./service-credential-list', () => ({ ServiceCredentialList: ({ onCreate }: { onCreate: () => void }) => <button onClick={onCreate}>service-add</button> }))
vi.mock('./mcp-vault-list', () => ({ McpVaultList: ({ onCreate }: { onCreate: () => void }) => <button onClick={onCreate}>vault-add</button> }))
vi.mock('./credential-kind-chooser', () => ({ CredentialKindChooser: ({ open }: { open: boolean }) => (open ? <div>chooser-open</div> : null) }))
vi.mock('@/app/managed/secrets/components/create-secret-dialog', () => ({
  CreateSecretDialog: ({ open, initialKind, lockKind }: { open: boolean; initialKind?: string; lockKind?: boolean }) =>
    open ? <div>{`secret-dialog:${initialKind}:${String(lockKind)}`}</div> : null,
}))
vi.mock('@/app/managed/vaults/components/create-vault-dialog', () => ({
  CreateVaultDialog: ({ open }: { open: boolean }) => (open ? <div>vault-dialog</div> : null),
}))
vi.mock('@/components/ui/tabs', () => ({
  Tabs: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  TabsList: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  TabsTrigger: ({ children, value }: { children: ReactNode; value: string }) => <button data-tab={value}>{children}</button>,
}))

import { CredentialManagementShell } from './credential-management-shell'

function Wrap({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>
}

describe('CredentialManagementShell', () => {
  beforeEach(() => {
    replaceMock.mockClear()
    pushMock.mockClear()
    searchParamsValue = new URLSearchParams('')
    readOnlyValue = false
  })

  it('normalizes an illegal tab to models via replace', async () => {
    searchParamsValue = new URLSearchParams('tab=bogus')
    render(<Wrap><CredentialManagementShell /></Wrap>)
    await waitFor(() => expect((replaceMock.mock.calls.at(-1)?.[0] as string) ?? '').toContain('tab=models'))
  })

  it('consumes create=vault: opens vault dialog, normalizes tab=mcp, strips create', async () => {
    searchParamsValue = new URLSearchParams('tab=models&create=vault')
    const { getByText } = render(<Wrap><CredentialManagementShell /></Wrap>)
    await waitFor(() => expect(getByText('vault-dialog')).toBeTruthy())
    const url = replaceMock.mock.calls.at(-1)![0] as string
    expect(url).toContain('tab=mcp')
    expect(url).not.toContain('create=')
  })

  it('consumes create=service: opens generic secret dialog locked', async () => {
    searchParamsValue = new URLSearchParams('tab=models&create=service')
    const { getByText } = render(<Wrap><CredentialManagementShell /></Wrap>)
    await waitFor(() => expect(getByText('secret-dialog:generic:true')).toBeTruthy())
  })

  it('does NOT open a create dialog from create=* for a read-only project', async () => {
    readOnlyValue = true
    searchParamsValue = new URLSearchParams('tab=services&create=service')
    const { queryByText } = render(<Wrap><CredentialManagementShell /></Wrap>)
    await waitFor(() => expect(replaceMock).toHaveBeenCalled())
    expect(queryByText('secret-dialog:generic:true')).toBeNull()
    expect((replaceMock.mock.calls.at(-1)![0] as string)).not.toContain('create=')
  })

  it('per-tab Add on services tab opens generic locked dialog', async () => {
    searchParamsValue = new URLSearchParams('tab=services')
    const { getByText } = render(<Wrap><CredentialManagementShell /></Wrap>)
    fireEvent.click(getByText('service-add'))
    await waitFor(() => expect(getByText('secret-dialog:generic:true')).toBeTruthy())
  })
})
```

- [ ] **Step 2: Fail** — `cd frontend && bun run test credential-management-shell` → FAIL.

- [ ] **Step 3: Implement** `credential-management-shell.tsx`:
```tsx
'use client'

import { useQueryClient } from '@tanstack/react-query'
import { Plus } from 'lucide-react'
import { useRouter, useSearchParams } from 'next/navigation'
import { useCallback, useEffect, useState } from 'react'

import { CreateSecretDialog } from '@/app/managed/secrets/components/create-secret-dialog'
import { CreateVaultDialog } from '@/app/managed/vaults/components/create-vault-dialog'
import { Button } from '@/components/ui/button'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useCurrentProjectReadOnly } from '@/hooks/managed/use-current-project-read-only'
import { useTranslation } from '@/lib/i18n'
import { useManagedRequestScope } from '@/lib/managed/request-scope'
import type { Vault } from '@/types/managed'

import { CredentialKindChooser, type CredentialKindChoice } from './credential-kind-chooser'
import { McpVaultList } from './mcp-vault-list'
import { ModelConnectionList } from './model-connection-list'
import { ServiceCredentialList } from './service-credential-list'

type CredentialTab = 'models' | 'services' | 'mcp'
const TABS: CredentialTab[] = ['models', 'services', 'mcp']
const KIND_TO_TAB: Record<CredentialKindChoice, CredentialTab> = { model: 'models', service: 'services', vault: 'mcp' }

function normalizeTab(raw: string | null): CredentialTab {
  return TABS.includes(raw as CredentialTab) ? (raw as CredentialTab) : 'models'
}

export function CredentialManagementShell() {
  const { t } = useTranslation()
  const router = useRouter()
  const searchParams = useSearchParams()
  const queryClient = useQueryClient()
  const managedScope = useManagedRequestScope()
  const projectReadOnly = useCurrentProjectReadOnly()

  const rawTab = searchParams.get('tab')
  const tab = normalizeTab(rawTab)

  const [chooserOpen, setChooserOpen] = useState(false)
  const [secretDialog, setSecretDialog] = useState<{ open: boolean; kind: 'llm' | 'generic' }>({ open: false, kind: 'llm' })
  const [vaultDialogOpen, setVaultDialogOpen] = useState(false)

  // Normalize illegal ?tab= to models (replace, no history).
  useEffect(() => {
    if (rawTab !== null && !TABS.includes(rawTab as CredentialTab)) {
      const next = new URLSearchParams(searchParams.toString())
      next.set('tab', 'models')
      router.replace(`/managed/credentials?${next.toString()}`)
    }
  }, [rawTab, router, searchParams])

  const goToTab = useCallback(
    (next: CredentialTab) => {
      if (next === tab) return
      const params = new URLSearchParams(searchParams.toString())
      params.set('tab', next)
      router.push(`/managed/credentials?${params.toString()}`)
    },
    [router, searchParams, tab],
  )

  const openForKind = useCallback(
    (kind: CredentialKindChoice) => {
      goToTab(KIND_TO_TAB[kind])
      if (kind === 'model') setSecretDialog({ open: true, kind: 'llm' })
      else if (kind === 'service') setSecretDialog({ open: true, kind: 'generic' })
      else setVaultDialogOpen(true)
    },
    [goToTab],
  )

  // Consume create=* once: permission-gate, open the flow, normalize tab, strip create.
  useEffect(() => {
    const create = searchParams.get('create')
    if (!create) return
    const kind: CredentialKindChoice | null =
      create === 'model' ? 'model' : create === 'service' ? 'service' : create === 'vault' ? 'vault' : null
    const next = new URLSearchParams(searchParams.toString())
    next.delete('create')
    if (kind && !projectReadOnly) {
      next.set('tab', KIND_TO_TAB[kind])
      if (kind === 'model') setSecretDialog({ open: true, kind: 'llm' })
      else if (kind === 'service') setSecretDialog({ open: true, kind: 'generic' })
      else setVaultDialogOpen(true)
    }
    router.replace(`/managed/credentials?${next.toString()}`)
  }, [searchParams, router, projectReadOnly])

  const perTabAdd = useCallback(() => {
    openForKind(tab === 'models' ? 'model' : tab === 'services' ? 'service' : 'vault')
  }, [tab, openForKind])

  const onSecretCreated = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ['credentials', managedScope.key] })
    if (secretDialog.kind === 'llm') queryClient.invalidateQueries({ queryKey: ['compatible-secrets', managedScope.key] })
    goToTab(secretDialog.kind === 'llm' ? 'models' : 'services')
    setSecretDialog((s) => ({ ...s, open: false }))
  }, [queryClient, managedScope.key, secretDialog.kind, goToTab])

  return (
    <div>
      <div className="mb-4 flex items-center justify-between gap-3">
        <div className="overflow-x-auto">
          <Tabs value={tab} onValueChange={(v) => goToTab(v as CredentialTab)}>
            <TabsList>
              <TabsTrigger value="models">{t('managed.credentials.tabs.models')}</TabsTrigger>
              <TabsTrigger value="services">{t('managed.credentials.tabs.services')}</TabsTrigger>
              <TabsTrigger value="mcp">{t('managed.credentials.tabs.mcp')}</TabsTrigger>
            </TabsList>
          </Tabs>
        </div>
        {projectReadOnly ? null : (
          <Button size="sm" onClick={() => setChooserOpen(true)}>
            <Plus className="h-4 w-4" />
            {t('managed.credentials.new')}
          </Button>
        )}
      </div>

      {tab === 'models' ? <ModelConnectionList onCreate={perTabAdd} /> : null}
      {tab === 'services' ? <ServiceCredentialList onCreate={perTabAdd} /> : null}
      {tab === 'mcp' ? <McpVaultList onCreate={perTabAdd} /> : null}

      <CredentialKindChooser open={chooserOpen} onOpenChange={setChooserOpen} onChoose={openForKind} />

      <CreateSecretDialog
        open={secretDialog.open}
        initialKind={secretDialog.kind}
        lockKind
        onOpenChange={(open) => setSecretDialog((s) => ({ ...s, open }))}
        onCreated={onSecretCreated}
      />

      <CreateVaultDialog
        open={vaultDialogOpen}
        onOpenChange={setVaultDialogOpen}
        onCreated={(vault: Vault) => {
          setVaultDialogOpen(false)
          router.push(`/managed/credentials/mcp/${vault.id}?add=1`)
        }}
      />
    </div>
  )
}
```
> Verify `@/components/ui/tabs` exists (grep). If absent, either add a minimal Radix Tabs wrapper or replace `<Tabs/TabsList/TabsTrigger>` with the segmented-button pattern from `create-secret-dialog.tsx` — the shell test stubs `@/components/ui/tabs`, so keep the import surface `Tabs/TabsList/TabsTrigger` regardless.

- [ ] **Step 4: Create the page** `app/managed/credentials/page.tsx`:
```tsx
'use client'

import { CredentialManagementShell } from '@/components/managed/credentials/credential-management-shell'
import { PageHeader } from '@/components/managed/shared'
import { useTranslation } from '@/lib/i18n'

export default function CredentialsPage() {
  const { t } = useTranslation()
  return (
    <div>
      <PageHeader title={t('managed.credentials.title')} subtitle={t('managed.credentials.subtitle')} />
      <CredentialManagementShell />
    </div>
  )
}
```

- [ ] **Step 5: Pass** — `cd frontend && bun run test credential-management-shell` → PASS (all 5).
- [ ] **Step 6: Guards** — `cd frontend && bun run type-check && bun run lint` → clean.
- [ ] **Step 7: Commit**
```bash
git add -- frontend/components/managed/credentials/credential-management-shell.tsx frontend/components/managed/credentials/credential-management-shell.test.tsx frontend/app/managed/credentials/page.tsx
git commit -m "feat(credentials): CredentialManagementShell + page (tab switch + cache invalidate + permission-gated create)"
```

---

### Task 9: `CredentialDetail` dispatch + model/service detail bodies + route

**Files:**
- Create: `frontend/components/managed/credentials/credential-detail.tsx`
- Create: `frontend/components/managed/credentials/model-connection-detail.tsx`
- Create: `frontend/components/managed/credentials/service-credential-detail.tsx`
- Create: `frontend/app/managed/credentials/[credentialId]/page.tsx`
- Test: `frontend/components/managed/credentials/credential-detail.test.tsx`

**Interfaces:** `<CredentialDetail credentialId={CredentialId} />` fetches the credential **un-gated by catalog** (`['credential-detail', scope, id]`, enabled on scope), then dispatches (B3-fixed): `model` → `<ModelConnectionDetail credential={..} />` (catalog-gated internally); `service` → `<ServiceCredentialDetail credential={..} />` (no catalog); `mcp` → `group_id ? <RedirectingState/> (router.replace to vault) : <ResourceErrorState reason="notFound"/>`; unknown → error. Route wraps with `withEntityRouteGuard(Inner, { kind:'secret', idKind:'credential', paramKey:'credentialId', backTo:'/managed/credentials' })`. Detail bodies' breadcrumb back is **kind-correct** (UI#4): model → `?tab=models`, service → `?tab=services`.

- [ ] **Step 1: Write the failing dispatch tests** — fixtures are FULL strict-parser-valid objects (B6.5):
```tsx
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const replaceMock = vi.fn()
vi.mock('@/lib/i18n', () => ({ useTranslation: () => ({ t: (k: string) => k }) }))
vi.mock('next/navigation', () => ({ useRouter: () => ({ replace: replaceMock, push: vi.fn() }) }))
vi.mock('@/lib/api-client', () => ({ managedGet: vi.fn() }))
vi.mock('@/lib/managed/request-scope', () => ({
  useManagedRequestScope: () => ({ orgId: 'o', projectId: 'p', key: 'o:p' }),
  managedRequestOptions: () => ({}),
  hasManagedRequestScope: () => true,
}))
vi.mock('./model-connection-detail', () => ({ ModelConnectionDetail: () => <div>model-detail</div> }))
vi.mock('./service-credential-detail', () => ({ ServiceCredentialDetail: () => <div>service-detail</div> }))

import { managedGet } from '@/lib/api-client'
import { CredentialDetail } from './credential-detail'

const managedGetMock = managedGet as unknown as ReturnType<typeof vi.fn>
const ID = 'cred_018f6f42-0a51-7cc4-98c8-4f6f0ca5f001'
const GROUP = 'credgrp_018f6f42-0a51-7cc4-98c8-4f6f0ca5f040'

function base(overrides: Record<string, unknown>) {
  return {
    id: ID, name: 'x', provider: null, protocol: null, model: null,
    compatible_engine_ids: [], is_default: false, mcp_server_url: null, group_id: null,
    archived_at: null, created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
    data: {}, ...overrides,
  }
}
function Wrap({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>
}

describe('CredentialDetail dispatch', () => {
  beforeEach(() => { managedGetMock.mockReset(); replaceMock.mockClear() })

  it('renders model detail for kind=model without fetching the catalog', async () => {
    managedGetMock.mockResolvedValue(base({ kind: 'model', provider: 'anthropic', protocol: 'anthropic_messages' }))
    const { getByText } = render(<Wrap><CredentialDetail credentialId={ID as never} /></Wrap>)
    await waitFor(() => expect(getByText('model-detail')).toBeTruthy())
    expect(managedGetMock.mock.calls.some(([u]) => (u as string).startsWith('/llm/catalog'))).toBe(false)
  })

  it('renders service detail for kind=service', async () => {
    managedGetMock.mockResolvedValue(base({ kind: 'service' }))
    const { getByText } = render(<Wrap><CredentialDetail credentialId={ID as never} /></Wrap>)
    await waitFor(() => expect(getByText('service-detail')).toBeTruthy())
  })

  it('redirects an mcp credential WITH group_id to the vault detail route', async () => {
    managedGetMock.mockResolvedValue(base({ kind: 'mcp', group_id: GROUP, mcp_server_url: 'https://x' }))
    render(<Wrap><CredentialDetail credentialId={ID as never} /></Wrap>)
    await waitFor(() => expect(replaceMock).toHaveBeenCalledWith(`/managed/credentials/mcp/${GROUP}`))
  })

  it('shows an explicit error for an ORPHAN mcp credential (no group_id) — never blank', async () => {
    managedGetMock.mockResolvedValue(base({ kind: 'mcp', group_id: null }))
    const { getByText } = render(<Wrap><CredentialDetail credentialId={ID as never} /></Wrap>)
    await waitFor(() => expect(getByText('managed.credentials.orphanCredential')).toBeTruthy())
    expect(replaceMock).not.toHaveBeenCalled()
  })
})
```
Add i18n keys `managed.credentials.orphanCredential` (en `This credential is not attached to a vault.` / zh `该凭据未归属任何凭据库。`) and `managed.credentials.redirecting` (en `Redirecting…` / zh `正在跳转…`) to Task 2's key set if not already present — add them now to `en.ts`/`zh.ts` in THIS task's commit if Task 2 didn't include them (they weren't in Task 2's table, so add them here).

- [ ] **Step 2: Fail** — `cd frontend && bun run test credential-detail` → FAIL.

- [ ] **Step 3: Implement the two detail bodies (extraction from `app/managed/secrets/[secretId]/page.tsx`).**

`model-connection-detail.tsx` — the `kind === 'model'` half. Signature `export function ModelConnectionDetail({ credential }: { credential: SecretDetail })`. It owns the catalog gate (LlmCatalogPageState loading/error), computes `profile` via `findCredentialProfileForBinding`, renders the profile-field editor (or the `catalogIdentityUnavailable` Alert), active edit/save, set-default, archive, restore, delete, show/hide values, and a `PageHeader` breadcrumb `[{ label: t('managed.credentials.tabs.models'), to: '/managed/credentials?tab=models' }, { label: credential.name }]`. Archived credentials are read-only and cannot become default. Seed `values` from `credential.data`; pristine forms accept refetch data while dirty forms preserve local edits. It does NOT re-fetch the credential (the parent supplies it). Save/lifecycle mutations use `useScopedActions`, request-scope snapshots, stale-tail guards, and mutually exclusive pending state; successful writes update/invalidate only the originating scope. Detail test-connection remains absent because GET data is masked. The earlier extraction code below is the structural baseline; the rev3 lifecycle/scope amendment immediately before Task 13 supersedes its mutation body.
```tsx
'use client'

import { useQueryClient } from '@tanstack/react-query'
import { Eye, EyeOff, Save } from 'lucide-react'
import { useMemo, useState } from 'react'

import { CompatibleEngineBadges } from '@/components/managed/shared/compatible-engine-badges'
import { LlmCatalogPageState } from '@/components/managed/llm/llm-catalog-page-state'
import { FormFieldLabel, MonoId, PageHeader, RelativeTime, type } from '@/components/managed/shared'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { useCurrentProjectReadOnly } from '@/hooks/managed/use-current-project-read-only'
import { useLlmCatalog } from '@/hooks/managed/use-llm-catalog'
import { managedPatch } from '@/lib/api-client'
import { useTranslation } from '@/lib/i18n'
import { apiResourcePath } from '@/lib/managed/api-paths'
import { toastOperationError } from '@/lib/managed/errors'
import { findCredentialProfileForBinding } from '@/lib/managed/llm-catalog'
import { managedRequestOptions, useManagedRequestScope } from '@/lib/managed/request-scope'
import { parseSecretDetailResponse } from '@/lib/managed/secret-response-parsers'
import type { LlmCredentialField } from '@/types/llm'
import type { SecretDetail } from '@/types/managed'

function inputType(field: LlmCredentialField, showValues: boolean) {
  if (field.type === 'secret' && !showValues) return 'password'
  if (field.type === 'url') return 'url'
  return 'text'
}

export function ModelConnectionDetail({ credential }: { credential: SecretDetail }) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const managedScope = useManagedRequestScope()
  const projectReadOnly = useCurrentProjectReadOnly()
  const catalogQuery = useLlmCatalog()
  const catalogVersion = catalogQuery.data?.version ?? ''
  const catalogReady = catalogQuery.isSuccess && Boolean(catalogVersion)
  const [values, setValues] = useState<Record<string, string>>(credential.data)
  const [showValues, setShowValues] = useState(false)
  const [dirty, setDirty] = useState(false)
  const [saving, setSaving] = useState(false)

  const profile = useMemo(() => {
    if (!catalogQuery.data || !credential.provider || !credential.protocol) return null
    return findCredentialProfileForBinding(catalogQuery.data, credential.provider, credential.protocol)
  }, [catalogQuery.data, credential.provider, credential.protocol])
  const catalogIdentityUnavailable = catalogQuery.isSuccess && !profile

  const save = async () => {
    if (projectReadOnly) return
    setSaving(true)
    try {
      const response = await managedPatch<unknown>(
        apiResourcePath('credentials', credential.id),
        { data: values },
        managedRequestOptions(managedScope),
      )
      const updated = parseSecretDetailResponse(response)
      queryClient.setQueryData(['credential-detail', managedScope.key, credential.id], updated)
      queryClient.invalidateQueries({ queryKey: ['credentials', managedScope.key] })
      queryClient.invalidateQueries({ queryKey: ['compatible-secrets', managedScope.key] })
      setValues(updated.data)
      setDirty(false)
    } catch (error) {
      toastOperationError(t, error, 'common.operationFailed')
    } finally {
      setSaving(false)
    }
  }

  if (catalogQuery.isError) return <LlmCatalogPageState state="error" onRetry={() => catalogQuery.refetch()} />
  if (!catalogReady) return <LlmCatalogPageState state="loading" />

  return (
    <div className="space-y-6">
      <PageHeader
        title={credential.name}
        breadcrumb={[{ label: t('managed.credentials.tabs.models'), to: '/managed/credentials?tab=models' }, { label: credential.name }]}
        titleExtra={<Badge variant="default">{t('managed.llm.modelConfiguration')}</Badge>}
        action={
          projectReadOnly ? null : (
            <Button onClick={save} disabled={!dirty || saving || catalogIdentityUnavailable}>
              <Save className="mr-1 h-4 w-4" />
              {saving ? t('common.loading') : t('common.save')}
            </Button>
          )
        }
      />
      <section className="grid gap-4 rounded-xl border bg-card p-4 sm:grid-cols-2 lg:grid-cols-4">
        <div>
          <p className="text-xs text-muted-foreground">{t('managed.table.id')}</p>
          <MonoId id={credential.id} />
        </div>
        <div>
          <p className="text-xs text-muted-foreground">{t('managed.llm.provider')}</p>
          <p className="mt-1 text-sm font-medium">{credential.provider ?? '—'}</p>
        </div>
        <div>
          <p className="text-xs text-muted-foreground">{t('managed.llm.protocol')}</p>
          <p className="mt-1 text-sm font-medium">{credential.protocol ?? '—'}</p>
        </div>
        <div>
          <p className="text-xs text-muted-foreground">{t('managed.table.updated')}</p>
          <p className="mt-1 text-sm"><RelativeTime date={credential.updated_at} /></p>
        </div>
        <div className="sm:col-span-2 lg:col-span-4">
          <p className="mb-2 text-xs text-muted-foreground">{t('managed.llm.compatibleEngines')}</p>
          <CompatibleEngineBadges engineIds={credential.compatible_engine_ids} catalog={catalogQuery.data} />
        </div>
      </section>
      <section className="space-y-4 rounded-xl border bg-card p-4">
        <div className="flex items-center justify-between gap-3">
          <div>
            <h2 className="font-semibold">{t('managed.secrets.dataLabel')}</h2>
            <p className="text-xs text-muted-foreground">{t('managed.llm.identityImmutableHint')}</p>
          </div>
          <Button type="button" variant="ghost" size="sm" onClick={() => setShowValues((v) => !v)}>
            {showValues ? <EyeOff className="mr-1 h-4 w-4" /> : <Eye className="mr-1 h-4 w-4" />}
            {showValues ? t('managed.secrets.hideValues') : t('managed.secrets.showValues')}
          </Button>
        </div>
        {profile ? (
          <div className="grid gap-4 sm:grid-cols-2">
            {profile.fields.map((field) => (
              <div key={field.key} className="space-y-2">
                <FormFieldLabel htmlFor={`secret-${field.key}`} required={field.required}>{field.label}</FormFieldLabel>
                {field.type === 'select' ? (
                  <select
                    id={`secret-${field.key}`}
                    value={values[field.key] ?? ''}
                    disabled={projectReadOnly}
                    onChange={(e) => { setValues((c) => ({ ...c, [field.key]: e.target.value })); setDirty(true) }}
                    className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
                  >
                    <option value="">{t('common.select')}</option>
                    {field.options.map((o) => <option key={o} value={o}>{o}</option>)}
                  </select>
                ) : (
                  <Input
                    id={`secret-${field.key}`}
                    type={inputType(field, showValues)}
                    value={values[field.key] ?? ''}
                    disabled={projectReadOnly}
                    onChange={(e) => { setValues((c) => ({ ...c, [field.key]: e.target.value })); setDirty(true) }}
                  />
                )}
                <code className="block text-[11px] text-muted-foreground">{field.key}</code>
              </div>
            ))}
          </div>
        ) : (
          <Alert variant="destructive"><AlertDescription>{t('managed.llm.catalogIdentityUnavailable')}</AlertDescription></Alert>
        )}
      </section>
    </div>
  )
}
```
> Remove the stray `, type` in the shared import — import only the symbols used (`FormFieldLabel, MonoId, PageHeader, RelativeTime`). (Artifact of trimming; the implementer must import exactly what's referenced.)

`service-credential-detail.tsx` — the service/generic half. Signature `export function ServiceCredentialDetail({ credential }: { credential: SecretDetail })`. No catalog. Active credentials support editable `genericPairs` (add/remove/update), save `PATCH /credentials/:id` with trimmed pairs, archive, and delete; archived credentials are read-only and support restore + delete. Show/hide uses `isSecretValueMaskedKey`; breadcrumb returns to `?tab=services`. Pristine forms accept refetch data while dirty forms preserve local edits. Save/lifecycle mutations use `useScopedActions`, request-scope snapshots, stale-tail guards, and mutually exclusive pending state. The earlier extraction code below is the structural baseline; the rev3 lifecycle/scope amendment immediately before Task 13 supersedes its mutation body.
```tsx
'use client'

import { useQueryClient } from '@tanstack/react-query'
import { Eye, EyeOff, Plus, Save, Trash2 } from 'lucide-react'
import { useState } from 'react'

import { MonoId, PageHeader, RelativeTime } from '@/components/managed/shared'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { useCurrentProjectReadOnly } from '@/hooks/managed/use-current-project-read-only'
import { managedPatch } from '@/lib/api-client'
import { useTranslation } from '@/lib/i18n'
import { apiResourcePath } from '@/lib/managed/api-paths'
import { toastOperationError } from '@/lib/managed/errors'
import { managedRequestOptions, useManagedRequestScope } from '@/lib/managed/request-scope'
import { isSecretValueMaskedKey } from '@/lib/managed/secret-keys'
import { parseSecretDetailResponse } from '@/lib/managed/secret-response-parsers'
import type { SecretDetail } from '@/types/managed'

interface GenericPair {
  key: string
  value: string
}

export function ServiceCredentialDetail({ credential }: { credential: SecretDetail }) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const managedScope = useManagedRequestScope()
  const projectReadOnly = useCurrentProjectReadOnly()
  const [pairs, setPairs] = useState<GenericPair[]>(Object.entries(credential.data).map(([key, value]) => ({ key, value })))
  const [showValues, setShowValues] = useState(false)
  const [dirty, setDirty] = useState(false)
  const [saving, setSaving] = useState(false)

  const save = async () => {
    if (projectReadOnly) return
    const data = Object.fromEntries(pairs.map((p) => [p.key.trim(), p.value] as const).filter(([k]) => Boolean(k)))
    setSaving(true)
    try {
      const response = await managedPatch<unknown>(
        apiResourcePath('credentials', credential.id),
        { data },
        managedRequestOptions(managedScope),
      )
      const updated = parseSecretDetailResponse(response)
      queryClient.setQueryData(['credential-detail', managedScope.key, credential.id], updated)
      queryClient.invalidateQueries({ queryKey: ['credentials', managedScope.key] })
      setPairs(Object.entries(updated.data).map(([key, value]) => ({ key, value })))
      setDirty(false)
    } catch (error) {
      toastOperationError(t, error, 'common.operationFailed')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title={credential.name}
        breadcrumb={[{ label: t('managed.credentials.tabs.services'), to: '/managed/credentials?tab=services' }, { label: credential.name }]}
        titleExtra={<Badge variant="outline">{t('managed.llm.genericSecret')}</Badge>}
        action={
          projectReadOnly ? null : (
            <Button onClick={save} disabled={!dirty || saving}>
              <Save className="mr-1 h-4 w-4" />
              {saving ? t('common.loading') : t('common.save')}
            </Button>
          )
        }
      />
      <section className="grid gap-4 rounded-xl border bg-card p-4 sm:grid-cols-2 lg:grid-cols-4">
        <div>
          <p className="text-xs text-muted-foreground">{t('managed.table.id')}</p>
          <MonoId id={credential.id} />
        </div>
        <div>
          <p className="text-xs text-muted-foreground">{t('managed.table.updated')}</p>
          <p className="mt-1 text-sm"><RelativeTime date={credential.updated_at} /></p>
        </div>
      </section>
      <section className="space-y-4 rounded-xl border bg-card p-4">
        <div className="flex items-center justify-between gap-3">
          <h2 className="font-semibold">{t('managed.secrets.dataLabel')}</h2>
          <Button type="button" variant="ghost" size="sm" onClick={() => setShowValues((v) => !v)}>
            {showValues ? <EyeOff className="mr-1 h-4 w-4" /> : <Eye className="mr-1 h-4 w-4" />}
            {showValues ? t('managed.secrets.hideValues') : t('managed.secrets.showValues')}
          </Button>
        </div>
        <div className="space-y-3">
          {pairs.map((pair, index) => (
            <div key={index} className="grid gap-2 sm:grid-cols-[1fr_1fr_auto]">
              <Input
                value={pair.key}
                disabled={projectReadOnly}
                onChange={(e) => { setPairs((c) => c.map((it, i) => (i === index ? { ...it, key: e.target.value } : it))); setDirty(true) }}
              />
              <Input
                type={isSecretValueMaskedKey(pair.key) && !showValues ? 'password' : 'text'}
                value={pair.value}
                disabled={projectReadOnly}
                onChange={(e) => { setPairs((c) => c.map((it, i) => (i === index ? { ...it, value: e.target.value } : it))); setDirty(true) }}
              />
              <Button
                type="button"
                variant="ghost"
                size="icon"
                disabled={projectReadOnly}
                onClick={() => { setPairs((c) => c.filter((_, i) => i !== index)); setDirty(true) }}
              >
                <Trash2 className="h-4 w-4" />
              </Button>
            </div>
          ))}
          {!projectReadOnly ? (
            <Button type="button" variant="outline" size="sm" onClick={() => { setPairs((c) => [...c, { key: '', value: '' }]); setDirty(true) }}>
              <Plus className="mr-1 h-4 w-4" />
              {t('managed.secrets.addPair')}
            </Button>
          ) : null}
        </div>
      </section>
    </div>
  )
}
```

- [ ] **Step 4: Implement `CredentialDetail` (dispatch, B3-fixed) + route.**

`credential-detail.tsx`:
```tsx
'use client'

import { useQuery } from '@tanstack/react-query'
import { useRouter } from 'next/navigation'
import { useEffect } from 'react'

import { ResourceErrorState } from '@/components/managed/shared'
import { managedGet } from '@/lib/api-client'
import { useTranslation } from '@/lib/i18n'
import { apiResourcePath } from '@/lib/managed/api-paths'
import { hasManagedRequestScope, managedRequestOptions, useManagedRequestScope } from '@/lib/managed/request-scope'
import { parseSecretDetailResponse } from '@/lib/managed/secret-response-parsers'
import type { CredentialId } from '@/types/entity-id'

import { ModelConnectionDetail } from './model-connection-detail'
import { ServiceCredentialDetail } from './service-credential-detail'

export function CredentialDetail({ credentialId }: { credentialId: CredentialId }) {
  const { t } = useTranslation()
  const router = useRouter()
  const managedScope = useManagedRequestScope()

  const query = useQuery({
    queryKey: ['credential-detail', managedScope.key, credentialId],
    queryFn: async () => {
      const res = await managedGet<unknown>(apiResourcePath('credentials', credentialId), managedRequestOptions(managedScope))
      return parseSecretDetailResponse(res)
    },
    enabled: hasManagedRequestScope(managedScope),
  })

  const credential = query.data
  const redirectGroupId = credential?.kind === 'mcp' ? credential.group_id : null

  useEffect(() => {
    if (redirectGroupId) router.replace(`/managed/credentials/mcp/${redirectGroupId}`)
  }, [redirectGroupId, router])

  if (query.isError) return <ResourceErrorState error={query.error} resource="secret" onRetry={() => query.refetch()} />
  if (query.isLoading || !credential) {
    return <div className="py-10 text-center text-sm text-muted-foreground">{t('common.loading')}</div>
  }
  if (credential.kind === 'model') return <ModelConnectionDetail credential={credential} />
  if (credential.kind === 'service') return <ServiceCredentialDetail credential={credential} />
  if (credential.kind === 'mcp') {
    return credential.group_id ? (
      <div className="py-10 text-center text-sm text-muted-foreground">{t('managed.credentials.redirecting')}</div>
    ) : (
      <ResourceErrorState resource="secret" reason="notFound" onBack={() => router.push('/managed/credentials?tab=mcp')} />
    )
  }
  return <ResourceErrorState resource="secret" reason="notFound" onBack={() => router.push('/managed/credentials')} />
}
```
> The orphan test asserts text `managed.credentials.orphanCredential`. If `ResourceErrorState reason="notFound"` renders a generic message, pass an explicit message prop or render a small block with `t('managed.credentials.orphanCredential')` for the orphan branch. Verify `ResourceErrorState`'s prop surface (`reason`/`message`/`onBack`) before writing; render the `orphanCredential` string in the orphan branch so the test's `getByText` matches.

`app/managed/credentials/[credentialId]/page.tsx`:
```tsx
'use client'

import React from 'react'

import { CredentialDetail } from '@/components/managed/credentials/credential-detail'
import { withEntityRouteGuard } from '@/components/managed/shared'
import { parseCredentialId } from '@/types/entity-id'

function CredentialDetailPageInner({ params }: { params: Promise<{ credentialId: string }> }) {
  const { credentialId } = React.use(params)
  return <CredentialDetail credentialId={parseCredentialId(credentialId)} />
}

export default withEntityRouteGuard(CredentialDetailPageInner, {
  kind: 'secret',
  idKind: 'credential',
  paramKey: 'credentialId',
  backTo: '/managed/credentials',
})
```
(Mirror the exact `withEntityRouteGuard` import source used by the existing detail pages — it re-exports from `@/components/managed/shared`.)

- [ ] **Step 5: Pass** — `cd frontend && bun run test credential-detail` → PASS (all 4, incl. orphan).
- [ ] **Step 6: Guards** — `cd frontend && bun run type-check && bun run lint` → clean.
- [ ] **Step 7: Commit**
```bash
git add -- frontend/components/managed/credentials/credential-detail.tsx frontend/components/managed/credentials/model-connection-detail.tsx frontend/components/managed/credentials/service-credential-detail.tsx frontend/components/managed/credentials/credential-detail.test.tsx 'frontend/app/managed/credentials/[credentialId]/page.tsx' frontend/lib/i18n/locales/en.ts frontend/lib/i18n/locales/zh.ts
git commit -m "feat(credentials): kind-invariant CredentialDetail (orphan-safe) + kind-correct detail bodies"
```

---

### Task 10: `McpVaultDetail` + route (?add consume) + `CreateVaultDialog.onCreated`

**Files:**
- Create: `frontend/components/managed/credentials/mcp-vault-detail.tsx`
- Create: `frontend/app/managed/credentials/mcp/[credentialGroupId]/page.tsx`
- Modify: `frontend/app/managed/vaults/components/create-vault-dialog.tsx` (+ its test)
- Test: `frontend/components/managed/credentials/mcp-vault-detail.test.tsx`

**Interfaces:** `<McpVaultDetail credentialGroupId autoOpenAddCredential? />` — extracted verbatim from `app/managed/vaults/[vaultId]/page.tsx`; back navigation → `/managed/credentials?tab=mcp`; `createCredOpen` seeded from `autoOpenAddCredential`; **preserves the exact string** `apiResourcePath('credential-groups', vaultId, 'members', credId!, 'archive')` (guard in Task 11). The page reads `?add=1`, passes `autoOpenAddCredential`, and strips `add` (UI#6). `CreateVaultDialog` gains `onCreated?: (vault: Vault) => void`, called in `onSuccess` with the parsed vault.

- [ ] **Step 1: Failing tests.** Add to `create-vault-dialog.test.tsx` (match its harness) an `onCreated` assertion: mock `managedPost` → resolve `{ id: 'credgrp_…', name: 'v', archived_at: null, created_at: '', updated_at: '' }`, submit, assert the `onCreated` spy received an object with that `id`.

Create `mcp-vault-detail.test.tsx`:
```tsx
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { describe, expect, it, vi } from 'vitest'

vi.mock('@/lib/i18n', () => ({ useTranslation: () => ({ t: (k: string) => k }) }))
vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn() }) }))
vi.mock('@/lib/api-client', () => ({ managedGet: vi.fn() }))
vi.mock('@/lib/managed/request-scope', () => ({
  useManagedRequestScope: () => ({ orgId: 'o', projectId: 'p', key: 'o:p' }),
  managedRequestOptions: () => ({}),
  hasManagedRequestScope: () => true,
  managedScopeKey: () => 'o:p',
}))
vi.mock('@/hooks/managed/use-current-project-read-only', () => ({
  useCurrentProjectReadOnly: () => false,
  currentProjectAllowsWrite: () => true,
}))
vi.mock('@/stores/managed/project-store', () => ({ useProjectStore: { getState: () => ({ currentOrgId: 'o', currentProjectId: 'p' }) } }))
vi.mock('../../../app/managed/vaults/components/create-credential-dialog', () => ({ CreateCredentialDialog: () => null }))

import { managedGet } from '@/lib/api-client'
import { McpVaultDetail } from './mcp-vault-detail'

const managedGetMock = managedGet as unknown as ReturnType<typeof vi.fn>
const GROUP = 'credgrp_018f6f42-0a51-7cc4-98c8-4f6f0ca5f040'
function Wrap({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>
}

describe('McpVaultDetail', () => {
  it('fetches the group and its members', async () => {
    managedGetMock.mockImplementation(async (url: string) =>
      (url as string).includes('/members')
        ? { data: [], has_more: false }
        : { id: GROUP, name: 'v', description: null, archived_at: null, created_at: '', updated_at: '' },
    )
    render(<Wrap><McpVaultDetail credentialGroupId={GROUP as never} /></Wrap>)
    await waitFor(() => {
      expect(managedGetMock.mock.calls.some(([u]) => (u as string).includes('/members'))).toBe(true)
      expect(managedGetMock.mock.calls.some(([u]) => (u as string).endsWith(GROUP))).toBe(true)
    })
  })
})
```
(Fix the `CreateCredentialDialog` mock path to whatever import specifier `mcp-vault-detail.tsx` uses; simplest is to import it via an absolute alias `@/app/managed/vaults/components/create-credential-dialog` and mock that.)

- [ ] **Step 2: Fail** — `cd frontend && bun run test mcp-vault-detail create-vault-dialog` → FAIL.

- [ ] **Step 3: Add `onCreated` to `CreateVaultDialog`** — add `onCreated?: (vault: Vault) => void` to props (import `Vault`); in `mutation.onSuccess(data, { runId, scope })` after the guard + `invalidateQueries`, call `onCreated?.(data)` (the `mutationFn` already returns `parseVaultResponse(...)`), keep `setName('')` + `onOpenChange(false)`.

- [ ] **Step 4: Implement `McpVaultDetail`** — port the full body of `app/managed/vaults/[vaultId]/page.tsx` `VaultDetailPageInner` (group fetch, members fetch, both vault mutations, member-archive mutation, confirm-dialog state machine, columns, `CreateCredentialDialog` render), with edits: signature `export function McpVaultDetail({ credentialGroupId, autoOpenAddCredential = false }: { credentialGroupId: CredentialGroupId; autoOpenAddCredential?: boolean })`; set `const vaultId = credentialGroupId; const id = credentialGroupId;`; `useState(autoOpenAddCredential)` for `createCredOpen`; replace all `router.push('/managed/vaults')` and `ResourceErrorState onBack`/breadcrumb `to` with `/managed/credentials?tab=mcp`; import `CreateCredentialDialog` from `@/app/managed/vaults/components/create-credential-dialog`; **keep the exact** `apiResourcePath('credential-groups', vaultId, 'members', credId!, 'archive')` call in `archiveCredMutation`. All other logic verbatim from the source (which is fully reproduced in the plan's grounding notes; the implementer copies it and applies only the listed edits). Because the source is 483 lines, it is not re-pasted here; the edits above are the complete diff.

> This is the one task that ports a large existing body. To satisfy no-placeholder: the source file `app/managed/vaults/[vaultId]/page.tsx` is the authoritative content; the FIVE edits above (signature, id vars, createCredOpen seed, three navigation targets, import path) are exhaustive — nothing else changes. The verifier confirms the archive-string invariant and the mcp-tab back navigation.

- [ ] **Step 5: Create the route** `app/managed/credentials/mcp/[credentialGroupId]/page.tsx`:
```tsx
'use client'

import { useRouter, useSearchParams } from 'next/navigation'
import React, { useEffect } from 'react'

import { McpVaultDetail } from '@/components/managed/credentials/mcp-vault-detail'
import { withEntityRouteGuard } from '@/components/managed/shared'
import { parseCredentialGroupId } from '@/types/entity-id'

function McpVaultDetailPageInner({ params }: { params: Promise<{ credentialGroupId: string }> }) {
  const { credentialGroupId } = React.use(params)
  const router = useRouter()
  const searchParams = useSearchParams()
  const add = searchParams.get('add') === '1'
  useEffect(() => {
    if (!add) return
    const next = new URLSearchParams(searchParams.toString())
    next.delete('add')
    const qs = next.toString()
    router.replace(`/managed/credentials/mcp/${credentialGroupId}${qs ? `?${qs}` : ''}`)
  }, [add, credentialGroupId, router, searchParams])
  return <McpVaultDetail credentialGroupId={parseCredentialGroupId(credentialGroupId)} autoOpenAddCredential={add} />
}

export default withEntityRouteGuard(McpVaultDetailPageInner, {
  kind: 'vault',
  idKind: 'credentialGroup',
  paramKey: 'credentialGroupId',
  backTo: '/managed/credentials?tab=mcp',
})
```

- [ ] **Step 6: Pass** — `cd frontend && bun run test mcp-vault-detail create-vault-dialog` → PASS.
- [ ] **Step 7: Guards** — `cd frontend && bun run type-check && bun run lint` → clean.
- [ ] **Step 8: Commit**
```bash
git add -- frontend/components/managed/credentials/mcp-vault-detail.tsx frontend/components/managed/credentials/mcp-vault-detail.test.tsx 'frontend/app/managed/credentials/mcp/[credentialGroupId]/page.tsx' frontend/app/managed/vaults/components/create-vault-dialog.tsx frontend/app/managed/vaults/components/create-vault-dialog.test.tsx
git commit -m "feat(credentials): McpVaultDetail route (?add closure) + CreateVaultDialog.onCreated"
```

---

### Task 11: Redirect shells + single nav entry + deep-link callers + guard migration (B4)

**Files:**
- Create: `frontend/lib/managed/credential-redirects.ts` (+ test `credential-redirects.test.ts`)
- Modify: `frontend/app/managed/secrets/page.tsx`, `frontend/app/managed/secrets/[secretId]/page.tsx`, `frontend/app/managed/vaults/page.tsx`, `frontend/app/managed/vaults/[vaultId]/page.tsx`
- Modify: `frontend/components/app-sidebar/app-sidebar.tsx`
- Modify: `frontend/components/managed/environments-egress-editor.tsx`, `frontend/app/managed/agents/[agentId]/edit/page.tsx`, `frontend/app/managed/sessions/components/create-session-dialog.tsx`, `frontend/app/managed/sessions/[sessionId]/page.tsx`
- Modify (guard migration): `frontend/types/entity-id-architecture.test.ts`, `frontend/app/managed/vaults/vault-member-lifecycle.test.ts`

**Interfaces:** Old routes become server-side `redirect()` shells (App Router `redirect()`, no client flicker) driven by pure helpers; sidebar collapses to one `/managed/credentials` entry; deep-link callers repointed per §2.2; the three architecture guards are repointed to the new component files IN THIS COMMIT and run before committing.

- [ ] **Step 1: Write failing helper tests** — `frontend/lib/managed/credential-redirects.test.ts`:
```ts
import { describe, expect, it } from 'vitest'
import { resolveSecretsRedirect, resolveVaultsRedirect } from './credential-redirects'

describe('credential redirect helpers', () => {
  it('maps secrets list + create params', () => {
    expect(resolveSecretsRedirect(null)).toBe('/managed/credentials?tab=models')
    expect(resolveSecretsRedirect('llm')).toBe('/managed/credentials?tab=models&create=model')
    expect(resolveSecretsRedirect('generic')).toBe('/managed/credentials?tab=services&create=service')
    expect(resolveSecretsRedirect('custom')).toBe('/managed/credentials?tab=services&create=service')
    expect(resolveSecretsRedirect('bogus')).toBe('/managed/credentials?tab=models')
  })
  it('maps vaults list + create param', () => {
    expect(resolveVaultsRedirect(null)).toBe('/managed/credentials?tab=mcp')
    expect(resolveVaultsRedirect('1')).toBe('/managed/credentials?tab=mcp&create=vault')
  })
})
```

- [ ] **Step 2: Fail** — `cd frontend && bun run test credential-redirects` → FAIL.

- [ ] **Step 3: Implement the helper** `frontend/lib/managed/credential-redirects.ts`:
```ts
export function resolveSecretsRedirect(create: string | null): string {
  if (create === 'llm') return '/managed/credentials?tab=models&create=model'
  if (create === 'generic' || create === 'custom') return '/managed/credentials?tab=services&create=service'
  return '/managed/credentials?tab=models'
}

export function resolveVaultsRedirect(create: string | null): string {
  if (create === '1') return '/managed/credentials?tab=mcp&create=vault'
  return '/managed/credentials?tab=mcp'
}
```

- [ ] **Step 4: Replace the four old pages with server redirect shells.**

`app/managed/secrets/page.tsx`:
```tsx
import { redirect } from 'next/navigation'

import { resolveSecretsRedirect } from '@/lib/managed/credential-redirects'

export default async function SecretsRedirect({ searchParams }: { searchParams: Promise<{ create?: string }> }) {
  const { create } = await searchParams
  redirect(resolveSecretsRedirect(create ?? null))
}
```

`app/managed/secrets/[secretId]/page.tsx`:
```tsx
import { redirect } from 'next/navigation'

export default async function SecretDetailRedirect({ params }: { params: Promise<{ secretId: string }> }) {
  const { secretId } = await params
  redirect(`/managed/credentials/${secretId}`)
}
```

`app/managed/vaults/page.tsx`:
```tsx
import { redirect } from 'next/navigation'

import { resolveVaultsRedirect } from '@/lib/managed/credential-redirects'

export default async function VaultsRedirect({ searchParams }: { searchParams: Promise<{ create?: string }> }) {
  const { create } = await searchParams
  redirect(resolveVaultsRedirect(create ?? null))
}
```

`app/managed/vaults/[vaultId]/page.tsx`:
```tsx
import { redirect } from 'next/navigation'

export default async function VaultDetailRedirect({ params }: { params: Promise<{ vaultId: string }> }) {
  const { vaultId } = await params
  redirect(`/managed/credentials/mcp/${vaultId}`)
}
```
> These are server components (no `'use client'`). They drop `withEntityRouteGuard` and the old list/detail imports — intended (the logic now lives in `components/managed/credentials/`). The old create dialogs remain (imported by the shell/detail).

- [ ] **Step 5: Collapse sidebar** — in `app-sidebar.tsx`, remove `{ to: '/managed/vaults', labelKey: 'nav.vaults', icon: KeyRound }` (buildItems) and `{ to: '/managed/secrets', labelKey: 'nav.secrets', icon: Lock }` (resourceItems); add `{ to: '/managed/credentials', labelKey: 'nav.credentials', icon: KeyRound }` to `resourceItems`. If `Lock` becomes unused, drop it from the `lucide-react` import.

- [ ] **Step 6: Repoint deep-link callers** (§2.2):
  - `components/managed/environments-egress-editor.tsx:411` → `window.open('/managed/credentials?tab=services&create=service', '_blank')`
  - `app/managed/agents/[agentId]/edit/page.tsx:643` → `window.open('/managed/credentials?tab=models&create=model', '_blank')`
  - `app/managed/sessions/components/create-session-dialog.tsx:793` → `router.push('/managed/credentials?tab=mcp')`
  - `app/managed/sessions/components/create-session-dialog.tsx:879` → `router.push('/managed/credentials?tab=mcp&create=vault')`
  - `app/managed/sessions/[sessionId]/page.tsx:1443` → `router.push(`/managed/credentials/mcp/${vaultDetail.id}`)`

- [ ] **Step 7: Migrate the architecture guards (B4).**
  - `types/entity-id-architecture.test.ts` `typedLists` array (~747): change `['app/managed/secrets/page.tsx', 'parseCursor: parseCredentialId']` → `['components/managed/credentials/model-connection-list.tsx', 'parseCursor: parseCredentialId']`; change `['app/managed/vaults/page.tsx', 'parseCursor: parseCredentialGroupId']` → `['components/managed/credentials/mcp-vault-list.tsx', 'parseCursor: parseCredentialGroupId']`.
  - Grep the same file for any assertion reading `app/managed/secrets/[secretId]/page.tsx` or `app/managed/vaults/[vaultId]/page.tsx` (typed-detail route guard). Repoint the secret-detail id-parse assertion to `app/managed/credentials/[credentialId]/page.tsx` (`parseCredentialId(credentialId)`) and the vault-detail one to `app/managed/credentials/mcp/[credentialGroupId]/page.tsx` (`parseCredentialGroupId(credentialGroupId)`). If the assertion asserts the exact old variable name (`rawSecretId`), update it to match the new page's variable (`credentialId`).
  - `app/managed/vaults/vault-member-lifecycle.test.ts:9` → read `components/managed/credentials/mcp-vault-detail.tsx` instead of `app/managed/vaults/[vaultId]/page.tsx`. The archive-string assertion (`apiResourcePath('credential-groups', vaultId, 'members', credId!, 'archive')`) is unchanged (McpVaultDetail preserves it).

- [ ] **Step 8: Run the affected tests (do NOT defer).**

Run: `cd frontend && bun run test credential-redirects entity-id-architecture vault-member-lifecycle create-session-dialog`
Expected: PASS (helper + both migrated guards + session dialog with new URLs).

- [ ] **Step 9: Guards** — `cd frontend && bun run type-check && bun run lint` → clean.

- [ ] **Step 10: Commit**
```bash
git add -- frontend/lib/managed/credential-redirects.ts frontend/lib/managed/credential-redirects.test.ts frontend/app/managed/secrets/page.tsx 'frontend/app/managed/secrets/[secretId]/page.tsx' frontend/app/managed/vaults/page.tsx 'frontend/app/managed/vaults/[vaultId]/page.tsx' frontend/components/app-sidebar/app-sidebar.tsx frontend/components/managed/environments-egress-editor.tsx 'frontend/app/managed/agents/[agentId]/edit/page.tsx' frontend/app/managed/sessions/components/create-session-dialog.tsx 'frontend/app/managed/sessions/[sessionId]/page.tsx' frontend/types/entity-id-architecture.test.ts frontend/app/managed/vaults/vault-member-lifecycle.test.ts
git commit -m "feat(credentials): redirect shells + single nav entry + deep-link + architecture-guard migration"
```

---

### Task 12: Accessibility / mobile (UI#5) — keyboard-actionable rows + scrollable tabs

**Files:**
- Modify: `frontend/components/managed/shared/data-table.tsx`
- Test: `frontend/components/managed/shared/data-table.test.tsx` (create or extend)

**Interfaces:** additive — when `onRowClick` is provided, each `<tr>` becomes keyboard-actionable (`role="button"`, `tabIndex={0}`, Enter/Space triggers the same handler). No behavior change when `onRowClick` is absent. The shell's tab bar already scrolls horizontally (`overflow-x-auto`, Task 8). This affects all managed lists — the change is purely additive (keyboard mirrors the existing mouse handler), so it cannot regress existing mouse behavior.

- [ ] **Step 1: Write the failing test:**
```tsx
import { fireEvent, render } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

vi.mock('@/lib/i18n', () => ({ useTranslation: () => ({ t: (k: string) => k }) }))

import { DataTable, type Column } from './data-table'

type Row = { id: string; name: string }
const columns: Column<Row>[] = [{ key: 'name', header: 'Name', render: (r) => <span>{r.name}</span> }]

describe('DataTable row accessibility', () => {
  it('activates onRowClick via keyboard (Enter)', () => {
    const onRowClick = vi.fn()
    const { getAllByRole } = render(<DataTable columns={columns} data={[{ id: 'a', name: 'Row A' }]} onRowClick={onRowClick} />)
    const row = getAllByRole('button').find((el) => el.tagName === 'TR')!
    expect(row.getAttribute('tabindex')).toBe('0')
    fireEvent.keyDown(row, { key: 'Enter' })
    expect(onRowClick).toHaveBeenCalledWith({ id: 'a', name: 'Row A' })
  })
})
```
(Match the DataTable test import surface; if `DataTable` is re-exported only from `@/components/managed/shared`, import from there.)

- [ ] **Step 2: Fail** — `cd frontend && bun run test data-table` → FAIL (row has no role/tabindex/keydown).

- [ ] **Step 3: Implement (additive)** — in `data-table.tsx` (~291) change the row element:
```tsx
                  <tr
                    key={row.id}
                    onClick={() => onRowClick?.(row.original)}
                    {...(onRowClick
                      ? {
                          role: 'button',
                          tabIndex: 0,
                          onKeyDown: (event: React.KeyboardEvent<HTMLTableRowElement>) => {
                            if (event.target !== event.currentTarget) return
                            if (event.key === 'Enter' || event.key === ' ') {
                              event.preventDefault()
                              onRowClick(row.original)
                            }
                          },
                        }
                      : {})}
                    className={`border-b border-border transition-colors last:border-b-0 ${
                      onRowClick ? 'cursor-pointer hover:bg-accent/50' : ''
                    }`}
                  >
```
Ensure `React` is imported (add `import React from 'react'` if the file lacks it and uses the `React.KeyboardEvent` type; otherwise import the type: `import { type KeyboardEvent } from 'react'` and use `KeyboardEvent<HTMLTableRowElement>`).

- [ ] **Step 4: Pass** — `cd frontend && bun run test data-table` → PASS, including Enter/Space on a nested action button proving it does not invoke `onRowClick`.
- [ ] **Step 5: Regression sweep of consumers** — `cd frontend && bun run test managed/` (or the list tests: `bun run test agents sessions credentials`) to confirm the additive change breaks no existing table test. Then `bun run type-check && bun run lint` → clean.
- [ ] **Step 6: Commit**
```bash
git add -- frontend/components/managed/shared/data-table.tsx frontend/components/managed/shared/data-table.test.tsx
git commit -m "feat(a11y): keyboard-actionable DataTable rows for credential (and all) lists"
```

---

### Rev3 amendment: Model/Service lifecycle + scope hardening (supersedes Task 3/4/9 mutation excerpts)

**Files:**
- Modify: `frontend/components/managed/credentials/model-connection-list.tsx`
- Modify: `frontend/components/managed/credentials/service-credential-list.tsx`
- Modify: `frontend/components/managed/credentials/model-connection-detail.tsx`
- Modify: `frontend/components/managed/credentials/service-credential-detail.tsx`
- Modify: `frontend/components/managed/credentials/model-connection-list.test.tsx`
- Modify: `frontend/components/managed/credentials/service-credential-list.test.tsx`
- Create: `frontend/components/managed/credentials/credential-detail-lifecycle.test.tsx`

- [ ] **Step 1: Complete list lifecycle** — render status; active Model actions are set-default/archive/delete; archived Model actions are restore/delete; active Service actions are archive/delete; archived Service actions are restore/delete. At confirmation, find the current row by id and require its archived/default state to still match the requested transition.
- [ ] **Step 2: Scope-guard list mutations** — replace direct reactive-scope mutation tails with `useScopedActions`. Capture `requestScope` at `beginAction()`, guard success/error/finally with `isCurrentAction`, invalidate only `action.scope`, reset targets/pending state on scope/read-only changes, and block concurrent list mutations. Guard same-turn create/row actions with live scope/write checks.
- [ ] **Step 3: Complete detail lifecycle** — active details are editable; archived details are read-only; Model supports set-default/archive/restore/delete; Service supports archive/restore/delete. Save and lifecycle operations share one mutually exclusive pending gate so a save cannot race archive/default/delete.
- [ ] **Step 4: Scope-guard detail mutations** — use `beginAction()` request snapshots; ignore stale success/error/finally tails; never navigate, cache-write, invalidate, toast, or close state in a newly active scope. Scope reset clears confirmation, pending flags, value visibility, and dirty state so the next credential refetch can reseed pristine form data.
- [ ] **Step 5: Regression tests first** — prove confirmation after scope invalidation sends no request; prove an already-started Model/Service delete that completes stale does not navigate; retain lifecycle/read-only/refetch assertions. Run the focused list/detail tests RED before implementation, then GREEN.

---

### Task 13: Capability-parity + isolation matrix (§6 acceptance gate) — REAL test code

**Files:**
- Create: `frontend/components/managed/credentials/credential-parity.test.tsx`

**Interfaces:** adds no product code — the behavior matrix proving no capability regressed, using the rev4 lifecycle/list-filter capability set (B2). Failures are fixed in the owning component task (return there). Every case below is a real `it()` with assertions — no `it.todo`, no prose-only bullets.

Cover (real assertions):
- **Isolation:** `ModelConnectionList` fetch URL contains `kind=model`; `ServiceCredentialList` contains `kind=service` and never calls `/llm/catalog`; `McpVaultList` calls `/credential-groups` and never `/llm/catalog`. (Consolidate the Task 3/4/5 assertions; kind-scoped cursor isolation is proven at the hook level in Task 1.)
- **Reader role (all three tabs):** with `useCurrentProjectReadOnly: () => true`, `ModelConnectionList`/`ServiceCredentialList`/`McpVaultList` render NO add button (`queryByText` of the add-label is null) and `actionMenu(row)` returns `[]` (assert by rendering a row and confirming no action trigger). The shell renders no global "New" button.
- **Model capability (present):** active rows expose set-default/archive/delete; archived rows expose restore/delete and never set-default; detail mirrors lifecycle and is read-only when archived. Test-connection remains create-only.
- **Service capability (present):** active rows expose archive/delete; archived rows expose restore/delete; detail mirrors lifecycle and is read-only when archived.
- **MCP capability (present):** vault list archive + delete actions appear for an active vault; `McpVaultDetail` renders archive + delete + Add-Credential (writer) and a member archive action; show-archived toggle present.
- **Scope safety (present):** Model/Service list and detail save/default/archive/restore/delete actions capture the originating request scope, abort when confirmation occurs after a scope/write-capability change, ignore stale success/error tails, and never navigate or invalidate the newly active project. Scope reset clears pending targets, pending flags, and dirty detail state.
- **Detail kind-invariant:** reference `credential-detail.test.tsx` for model/service/mcp/orphan (already covered) — here add ONE guard that orphan mcp renders the `orphanCredential` copy and does NOT redirect (dup-guard acceptable as the acceptance gate).
- **Routing:** default (no `?tab=`) renders models list; illegal `?tab=` triggers `replace` to models; a real tab change triggers `push`; `create=service` leaves `tab` present after strip. (Reference/repeat the Task 8 shell assertions consolidated here.)
- **Kind-correct back:** `ModelConnectionDetail` breadcrumb `to` is `/managed/credentials?tab=models`; `ServiceCredentialDetail` is `?tab=services`; `McpVaultDetail` back is `?tab=mcp`. Assert by rendering each with a valid `credential`/group and querying the breadcrumb link target (mock `PageHeader` to expose `breadcrumb` if needed).
- **Deep-link parity:** reference the Task 11 `credential-redirects.test.ts` for the redirect map; add nothing unless a case is missing.

- [ ] **Step 1: Write the matrix** with the harness conventions (mock `@/lib/i18n`, `next/navigation` incl. `useSearchParams` where the shell is under test, `@/lib/api-client`, `@/lib/managed/request-scope`, `@/hooks/managed/use-current-project-read-only`, `@/hooks/managed/use-llm-catalog` for model, stub `@/components/ui/*` + `@/components/managed/shared` as needed, `QueryClientProvider` retry:false). Use full strict-parser-valid fixtures (see Task 9 `base()` helper).

- [ ] **Step 2: Run** — `cd frontend && bun run test credential-parity` → PASS. Any failure ⇒ fix in the owning task, re-run.
- [ ] **Step 3: Guards** — `cd frontend && bun run type-check && bun run lint` → clean.
- [ ] **Step 4: Commit**
```bash
git add -- frontend/components/managed/credentials/credential-parity.test.tsx
git commit -m "test(credentials): capability-parity + isolation matrix (rev4 lifecycle set)"
```

---

### Task 14: i18n count reconciliation + full green gate + verification

**Files:**
- Modify: `frontend/lib/i18n/credential-terminology.test.ts`

- [ ] **Step 1: Read the true numbers** — `cd frontend && bun run test credential-terminology` → FAIL on inventory counts; the message reports the ACTUAL numbers.
- [ ] **Step 2: Reconcile** — set each inventory expectation (`sourceFileCount`, `direct`/`dynamic`/`total`, `templateAdditions`, `finiteAdditions`) to the reported actual. Do NOT weaken any semantic assertion or relax `findHardCodedLegacyCredentialCopy`. Confirm each delta is explained by P1's real additions (new `components/managed/credentials/*.tsx`, new `managed.credentials.*` + `nav.credentials` keys); if a count moved beyond that, investigate a stray hard-coded string rather than blindly matching.
- [ ] **Step 3: Terminology green** — `cd frontend && bun run test credential-terminology` → PASS.
- [ ] **Step 4: FULL green gate** — `cd frontend && bun run type-check && bun run test && bun run lint` → type-check clean; full vitest green (incl. `entity-id-architecture.test.ts`, `api-paths.test.ts`, terminology, and every new/updated component test); lint exit 0. If `api-paths.test.ts` / `entity-id-architecture.test.ts` assert on the moved route-page set, reconcile them to the new `app/managed/credentials/**` pages + redirect shells (real deltas only).
- [ ] **Step 5: Commit**
```bash
git add -- frontend/lib/i18n/credential-terminology.test.ts
git commit -m "test(credentials): reconcile i18n inventory snapshot to true post-P1 reality"
```
- [ ] **Step 6: Adversarial verification** — review against the original P1 request, the full changed-file list (Tasks 1-14 plus Tasks 1A-1B), the primarily frontend Models & Credentials approach, the rev4 lifecycle/list-filter capability set, and this plan path. Use an independent review agent only when the execution environment explicitly permits delegation. Do not report completion until PASS; on FAIL, fix and repeat the verification.

---

## Self-Review

**Blockers resolved:**
- **B1** (create closure): Task 8 `openForKind` switches tab; `onSecretCreated` invalidates `['credentials', scope]` (+ `['compatible-secrets', scope]` for model) and navigates to the kind's tab; `create=*` normalizes `tab` to the kind. ✓
- **B2** (false parity): rev4 verifies archive/restore behavior plus archived filtering before pagination and implements full Model/Service lifecycle without weakening set-default/delete/edit capabilities; only masked-detail test-connection remains out of scope. ✓
- **B3** (orphan whiteout): Task 9 `CredentialDetail` renders `orphanCredential` for mcp-without-group_id and redirects only when `group_id` present; a dedicated orphan test exists (not deferred). ✓
- **B4** (guard migration): Task 11 edits `entity-id-architecture.test.ts` (typed-list + typed-detail) and `vault-member-lifecycle.test.ts` in the same commit and runs them before committing; both files are in Files + git add. ✓
- **B5** (naming): §3.12 vocabulary (模型连接; material 模型访问密钥; no "credential" umbrella; neutral New/Create) in Task 2, with `modelConfiguration` zh converged and pin updated. ✓
- **B6** (test scaffolding): `.tsx` path (Task 1); single shared QueryClient isolation test (Task 1); catalog mocked at the HOOK (Task 3) — no invalid catalog payload; `beforeEach` imported (Task 8); full strict-parser-valid fixtures (Tasks 9/10/13). ✓

**UI/UX risks resolved:** (1) global "New" + distinct per-tab Add labels; (2) locked create flows use specific Model Connection / Service Credential titles; (3) `create=*` permission-gated; (4) per-tab search/created-filter/show-archived/page-size state retained independently across tab switches; (5) kind-correct back routes; (6) row keyboard navigation ignores nested action controls; (7) MCP `?add=1` opens the member dialog before being stripped. ✓

**Engineering quality resolved:** component extraction code is inlined, with the rev3 lifecycle/scope amendments explicitly superseding the earlier Task 3/4/9 mutation excerpts; Task 10's single large port has an exhaustive 5-item edit list against a named source; Task 13 specifies real assertions per matrix bullet; all `git add` use `--` with quoted bracket paths; server `redirect()` shells avoid flicker; Task 11 tests Vault + both detail redirects + unknown query via the helper; route-migration guards run in-task, not deferred.

**Spec coverage (rev4 UX design §1–§9):** catalog isolation, canonical routes, redirect compatibility, server kind filtering, tri-state archived filtering before pagination, runtime-selector exclusion of archived credentials, MCP create closure, full Model/Service lifecycle, archived read-only behavior, per-tab state continuity, project-scope stale-run guards, vocabulary convergence, kind dispatch, and nested-control keyboard isolation are all represented by colocated behavior tests plus the full verification gate.

**Verification points for the implementer** (confirm before writing, don't assume): `@/components/ui/tabs` existence (Task 8 fallback); `ResourceErrorState` prop surface — `reason`/`message`/`onBack` and whether it renders custom copy (Task 9 orphan branch must surface `orphanCredential`); exact `withEntityRouteGuard` import source; `PageHeader` `breadcrumb` prop shape for the kind-correct-back assertions (Task 13).

---

## Execution Handoff

Plan (rev4) complete and saved to `docs/superpowers/plans/2026-08-13-unified-credential-p1.md`.

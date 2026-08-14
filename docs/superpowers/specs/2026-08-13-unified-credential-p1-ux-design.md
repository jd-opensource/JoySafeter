# Unified Credential P1 — "Models & Credentials" UX merge (design)

Date: 2026-08-14 (rev 4 — adds compatible archived filtering before pagination and reconciles implementation)
Depends on: P0 + post-P0 hardening (commit `802fc986`) — unified `/credentials` +
`/credential-groups` by-id API; frontend migrated; suites green.
Umbrella: `docs/superpowers/specs/2026-08-11-unified-credential-architecture-design.md` §4 (P1) + §3.12.

## 1. Goal, guardrails, capability-equivalence, error boundaries

P1 is primarily a **frontend product-experience refactor**: collapse the two credential nav entries
into one "Models & Credentials" surface with kind tabs, an MCP credential-vault master-detail
sub-view, and a unified creation entry, landing the §3.12 vocabulary. It makes no schema,
response-shape, or credential-runtime change. The only API extension is an optional,
backward-compatible `GET /credentials?include_archived=` query parameter required to filter archived
rows before cursor pagination.

**Capability-equivalence rule (non-negotiable):** P1 must not shrink any capability that exists
today on `/managed/secrets` or `/managed/vaults`. The §6 parity matrix is the acceptance gate.

**Independent error boundaries (H3):** each tab and each detail view owns its own
loading/error/empty state. The LLM catalog dependency is scoped to the **Model** surfaces only:
- Model list + Model detail: MAY gate on `useLlmCatalog()` (as today) for compatibility labels.
- Service list/detail and MCP list/detail: MUST NOT depend on the LLM catalog.
- A failure in one tab (catalog down, list error) must not blank the page or other tabs.

## 2. Information architecture — canonical routes, redirects, query semantics

### 2.1 Canonical routes (B1)
| Surface | Route |
|---|---|
| Page (tabs) | `/managed/credentials?tab=models\|services\|mcp` (default `models`) |
| Model detail | `/managed/credentials/[credentialId]` (kind=model) |
| Service detail | `/managed/credentials/[credentialId]` (kind=service) |
| **MCP vault detail** | `/managed/credentials/mcp/[credentialGroupId]` (static `mcp` segment) |

The static `mcp` segment (B1) keeps the group-id route from colliding with the
`[credentialId]` entity type and makes the MCP master-detail a real, linkable route (mobile-safe —
no same-page split required). "Master-detail" = **list at the tab, detail at its own route**.

### 2.2 Redirect + deep-link compat matrix (B4)
Old routes become **pure redirect shells** (H1); their query params map explicitly:
| Old | New |
|---|---|
| `/managed/secrets` | `/managed/credentials?tab=models` |
| `/managed/secrets?create=llm` | `/managed/credentials?tab=models&create=model` |
| `/managed/secrets?create=generic` or `?create=custom` | `/managed/credentials?tab=services&create=service` |
| `/managed/secrets/[id]` | `/managed/credentials/[id]` |
| `/managed/vaults` | `/managed/credentials?tab=mcp` |
| `/managed/vaults?create=1` | `/managed/credentials?tab=mcp&create=vault` |
| `/managed/vaults/[groupId]` | `/managed/credentials/mcp/[groupId]` |

**Callers are updated to point at the new URLs directly** (not rely on the redirect):
- `components/managed/environments-egress-editor.tsx` (`/secrets?create=custom` → `…?tab=services&create=service`)
- `app/managed/agents/[agentId]/edit/page.tsx` + create-agent-dialog (`/secrets?create=llm` → `…?tab=models&create=model`)
- `app/managed/sessions/components/create-session-dialog.tsx` (`/vaults?create=1` → `…?tab=mcp&create=vault`)
- `app/managed/sessions/[sessionId]/page.tsx` (`/vaults/[vaultId]` → `/credentials/mcp/[groupId]`)
Old routes remain only as compatibility fallback.

### 2.3 Query-param semantics
- Illegal/unknown `?tab=` → normalize to `models` via `router.replace` (no history entry).
- User tab click → `router.push` (preserves back-button).
- `create=*` is consumed once: on open, the create flow launches; on close/success, **only** the
  `create` param is stripped, `tab` and any other params are preserved.
- Detail back / breadcrumb returns to the correct tab by the credential's kind
  (model/service → its tab; mcp vault detail → `?tab=mcp`).
- Each tab keeps its own independent search / created-time filter / show-archived / pageSize /
  cursor state (§3).

## 3. Data flow — kind filtering, query keys, pagination (B2)

**Kind is filtered server-side, before pagination. Client-side `filter(kind)` after a page load is
forbidden** (it breaks cursor pagination — a page can look empty while later pages hold matches,
and model/service become unreachable through a shared cursor).

| Concern | Rule |
|---|---|
| List request | `apiCollectionPath('credentials', { kind })` plus explicit `include_archived=false\|true` |
| MCP list | `GET /credential-groups` (unchanged) |
| React Query key | MUST include `kind` (e.g. `['credentials', scopeKey, kind]`) so tabs never share cache |
| Pagination cursor scope | cursor / sessionStorage key MUST include `kind`; model & service pagination are isolated |
| Prefetch key | includes `kind` |
| Archived filtering | Model/Service default to `false`; the toggle sends `true`; filtering happens in SQL before `limit`/cursor |
| Binding selectors | Model/Service pickers always send `include_archived=false`, because Agent/Environment writes reject archived credential references |

`usePaginatedList` threads `kind` into the path AND into the queryKey/cursor scope, and preserves an
explicit `includeArchived: false` instead of collapsing it to `undefined`. Client filtering remains
a defensive rendering fallback only; it MUST NOT carry pagination correctness. Tests cover kind
isolation, explicit-false serialization, and archived filtering before pagination (§6).

## 4. Creation flows + role/lifecycle behavior

### 4.1 Unified create — single-layer kind selection (H4)
- One primary **"New"** opens a **`CredentialKindChooser`** (Model Connection / MCP
  Credential Vault / Service Credential). Choosing a kind opens that kind's create flow **with the
  kind locked** — the existing `CreateSecretDialog`'s internal LLM/Generic tab is **removed/hidden**
  when launched from the chooser (no triple decision).
- Per-tab contextual **"Add"** skips the chooser and opens directly with that tab's kind locked.
- `create=model|service|vault` deep-links open the corresponding flow directly (kind locked).

### 4.2 MCP create closure (B3) — RESOLVED: create-then-continue
Creating an MCP Credential Vault is a **closed loop**:
1. `CreateVaultDialog` creates the empty group (existing behavior).
2. On success, navigate to `/managed/credentials/mcp/[groupId]` (the new vault detail) and
   **auto-open its "Add Credential" (add-member) dialog**, so the user immediately adds the first
   member.
The contradictory "group + member in one dialog" wording is removed. A vault may legitimately have
zero members until the user adds one; the flow just guides them there.

### 4.3 Role / lifecycle behavior (carried from P0, must be preserved in the merged UI)
- **Reader** (no write scope): sees masked list/detail across all tabs; **no** create/edit/delete/
  archive controls rendered.
- **Archived project**: all create/edit/archive/delete actions blocked (as today).
- **Project/scope lifecycle**: switching project, archiving the current project, closing a dialog,
  or unmounting invalidates in-flight create/mutation results; stale completions must not close,
  invalidate, navigate, or populate the newly active project.
- **Model list/detail**: active rows support set-default, archive, and delete; archived rows are
  visibly marked, read-only, and support restore + delete. Detail supports edit-data/save while
  active. **Detail test-connection is intentionally absent**: detail GET data is masked while
  `POST /credentials/test` requires full plaintext. Test-connection remains available at create time.
- **Service list/detail**: active rows support archive + delete; archived rows are visibly marked,
  read-only, and support restore + delete. Active detail supports masked-field add/remove/update/save.
- **MCP vault**: create / archive / delete group; **member**: add / archive (not delete — archive
  preserves history per P0 hardening) / show-archived toggle.

## 5. Vocabulary (§3.12) + i18n (corrected baseline — H6)

- Land the §3.12 user-facing strings (already present in the catalog): "Models & Credentials"
  entry, tab labels (Model Connections / MCP / Service Credentials), "MCP Credential Vault",
  "Service Credential", "Model Connection". Converge leftover user-visible "secret/vault" drift.
  Do NOT rename backend `kind` values or i18n KEY names — user-visible copy only.
- **Baseline is GREEN** as of HEAD (`credential-terminology.test.ts` 375 passed;
  `entity-id-architecture.test.ts` 26; `api-paths.test.ts` 4 — 405 total). The earlier
  "pre-existing red" note was stale and is retracted.
- `sourceFileCount` counts **production `.ts/.tsx` files** (not route dirs) — so P1 adding the new
  page + extracted components (§8) WILL change it. P1 updates the snapshot to the **true** new
  count and the true translation-leaf counts, accounting only for P1's real additions — never a
  mechanical bump justified by "it was red". Any new user-facing vocabulary gets a matching
  **semantic** assertion in the terminology test (the semantic assertions, not the raw counts, are
  the real regression detector).

## 6. Testing — capability-parity matrix (H5)

Beyond render/route tests, P1 must add behavior-parity tests proving no capability regressed:
- **Model**: edit data · create-time test-connection · set-default · archive/restore · delete ·
  archived detail read-only.
- **Service**: edit masked fields · add/remove field · archive/restore · delete · archived detail
  read-only.
- **MCP Vault**: create · archive · delete.
- **MCP Member**: add · archive · archived shown (toggle).
- **Role**: reader sees masked info but **no** write controls; archived project blocks all writes.
- **Isolation**: after project switch, stale requests must not populate the new project; each tab
  has independent loading/error/empty/pagination; MCP credentials never appear in Model/Service tabs.
- **Tab continuity**: switching tabs must preserve that tab's search, created-time filter,
  show-archived state where applicable, cursor, and page size without mounting all tabs concurrently.
- **Routing**: default tab; illegal `?tab=` normalization (replace); tab click pushes history;
  `create=*` consumed leaves `tab` intact; kind-correct back/breadcrumb.
- **Deep-link parity**: every `create=*` and old detail deep-link (§2.2) lands on the right
  tab/flow with the create action intact.
- **Detail kind-invariant** (H2, see §8).
- Guards: `type-check` clean, `lint` exit 0, full `vitest` green incl. the reconciled terminology
  snapshot; `entity-id-architecture.test.ts` / `api-paths.test.ts` updated for moved route pages.

## 7. Non-goals + P0 constraints to respect

- Later phases: unified cross-flow credential picker → **P2C**; trigger grants → **P2A**; MCP
  OAuth → **P2B**. P1 has no schema, response-shape, or credential-runtime change beyond the
  compatible list query parameter below.
- **P0 API facts P1 relies on:**
  - `GET /credentials` excludes deleted rows and historically returns active + archived credentials
    when `include_archived` is omitted. Rev4 preserves that default for existing callers.
  - `include_archived=false` excludes archived rows in the database query before cursor/limit;
    `include_archived=true` returns active + archived. Model/Service lists always send one of these
    explicit values, while legacy callers may omit the parameter without behavior change.
  - Binding/authoring selectors (`useCompatibleSecrets`, protocol-model pickers,
    `useServiceCredentials`, and Environment egress editors) explicitly send `false`; archived
    credentials are lifecycle-visible in management UI but are not valid new runtime references.
  - Existing `POST /credentials/{id}/archive` and `/restore` endpoints continue to provide the
    lifecycle mutations; no new mutation endpoint or response shape is introduced.
  - List `name`/created-time filtering is **per-cursor-page**, not global search. P1 must not
    present it as global search; the search box scope matches today's behavior.

## 8. Component architecture, invariants, a11y (H1/H2/H3 + follow-ups)

### 8.1 Extraction (H1) — old pages are full routes with their own header/create/pagination; do NOT nest them. Extract embeddable units:
`CredentialManagementShell` (tabs + query-state), `ModelConnectionList`, `ServiceCredentialList`,
`CredentialDetail` (kind-dispatching), `McpVaultList`, `McpVaultDetail`, `CredentialKindChooser`.
Old `secrets/` + `vaults/` route pages reduce to **redirect shells** with no business logic.
(Note: extraction changes the frontend source-file set → drives the §5 snapshot update.)

### 8.2 Detail kind-invariant (H2) — `/credentials/[credentialId]` must dispatch by fetched kind:
- `model` → Model Connection detail.
- `service` → Service Credential detail.
- `mcp` (has `group_id`) → **redirect** to `/credentials/mcp/[group_id]`.
- orphan/unknown → explicit error state; **never** fall through to the generic/service editor.

### 8.3 Catalog fault isolation (H3) — only Model surfaces gate on `useLlmCatalog()`; Service + MCP
render independently of catalog success.

### 8.4 Accessibility / responsive
- Radix Tabs keyboard nav; `CredentialKindChooser` sets initial focus and restores focus on close.
- Mobile: tabs scroll horizontally (or equivalent); MCP list→detail routes degrade naturally on
  mobile (separate routes, no split-pane requirement).
- Table rows are keyboard-actionable (not mouse-only); destructive actions keep their confirm dialog.
- Row keyboard activation handles only events targeted at the row itself; Enter/Space on nested
  buttons or action menus must not trigger row navigation.

## 9. Resolved decisions (for the record)
- Tab state: query param (`?tab=`), replace-on-normalize / push-on-click (§2.3).
- MCP detail route: `/credentials/mcp/[groupId]` static segment (B1).
- Kind filtering: server-side + kind-scoped pagination/cache (B2, §3).
- MCP create: create-vault → vault detail → auto-open Add-Credential (B3, §4.2).
- Create chooser: single-layer, kind locked; dialog inner tab hidden (H4, §4.1).
- i18n: baseline green; snapshot updated to true post-P1 reality only (H6, §5).
- Archived Model/Service lifecycle: **in scope** using existing archive/restore endpoints plus the
  backward-compatible list filter; archived detail is read-only (§4.3, §7).
- Detail test-connection: **out of scope** because detail data is masked; create-time testing remains.
- Per-tab UI state: retained in the shell while only the active list is mounted.

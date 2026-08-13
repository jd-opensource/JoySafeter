# Unified Credential P1 — "Models & Credentials" UX merge (design)

Date: 2026-08-13
Depends on: P0 (unified `/credentials` + `/credential-groups` by-id API; frontend migrated) — committed.
Umbrella: `docs/superpowers/specs/2026-08-11-unified-credential-architecture-design.md` §4 (P1) + §3.12.

## 1. Goal & guardrails

P1 is a **pure product-experience refactor**: land the §3.12 vocabulary end-state and
collapse today's two credential nav entries into one "Models & Credentials" surface with a
kind-filtered list, an MCP credential-vault sub-view, and a unified creation entry.

Hard guardrails (define what P1 is NOT):
- **No backend API or contract change.** P0's `/credentials` + `/credential-groups` endpoints
  and response shapes are frozen. P1 is frontend-only.
- **No runtime-semantic change.** Model/MCP/service resolution, locking, audit, archive
  lifecycle are untouched (that was P0 + the post-P0 hardening commit `802fc986`).
- **No new backend files, no schema/migration change.**

## 2. Information architecture

- **New page** `app/managed/credentials/` — the single "Models & Credentials" entry, with three
  tabs: **Model Connections** | **MCP** | **Service Credentials**.
- **Tab state = query param** `?tab=models|mcp|services` (default `models`). Rationale: linkable /
  bookmarkable, back-button friendly, and it adds ONE route dir (not three nested segment dirs) —
  minimizing churn to the i18n `sourceFileCount` guard. (Rejected alternative: nested route
  segments `/credentials/[tab]` — more dirs, more redirect surface, no UX gain.)
- **Sidebar**: the two current entries (`nav.secrets` "Connections & Credentials",
  `nav.vaults` "MCP Credential Vault") collapse into **one** entry → `/managed/credentials`.
- **Redirects**: old routes `/managed/secrets`, `/managed/vaults` (+ their list pages) redirect
  into the new page/tab so existing links/bookmarks keep working. Detail pages:
  `/managed/credentials/[credentialId]` (model/service detail) and the MCP vault detail reachable
  from the MCP tab; old detail routes redirect to the new equivalents.
- **Implementation = relocation + a tab shell**, reusing the existing list/detail/create
  components rather than rewriting them. Behaviour is identical; only the container + nav change.

## 3. Tab contents (reuse existing components)

- **Model Connections** (`kind=model`): flat list — existing model/LLM list columns
  (provider / protocol / model / default + compatibility). Reuses today's secrets model list.
- **Service Credentials** (`kind=service`): flat list — today's generic/service list.
- **MCP** (`kind=mcp`): **master-detail** — lists credential **vaults** (groups); drilling into a
  vault shows its members (today's `vaults/[vaultId]` view, incl. the P0-hardening member archive
  lifecycle). Preserves MCP's natural two-level structure. (Confirmed brainstorm choice: "kind
  tabs, MCP stays 2-level".)

## 4. Unified creation entry

- A single primary **"New"** action on the page opens a **kind chooser** (Model Connection /
  MCP Credential Vault / Service Credential), then routes into the existing kind-specific create
  flow (LLM configurator for model; group + member for MCP; generic form for service).
- Each tab also exposes a contextual **"Add"** defaulting to that tab's kind (skips the chooser).
- No new create logic — this is a router over the existing create dialogs.

## 5. Vocabulary (§3.12) + i18n reconciliation

- Land the §3.12 end-state user-facing strings (already largely present in the i18n catalog):
  entry "Models & Credentials", the three tab labels, "MCP Credential Vault", "Service
  Credential", "Model Connection". Converge any leftover "secret/vault" user-facing drift into
  the new vocabulary. Do NOT rename backend `kind` values (model/mcp/service) or i18n KEY names —
  only user-visible copy.
- **P1 owns reconciling `lib/i18n/credential-terminology.test.ts`** (the inventory-count snapshot:
  `sourceFileCount`, `counts`, `templateAdditions`, `finiteAdditions`). It was pre-existing red
  before P0's frontend work and drifts further as P1 legitimately adds the new page + adjusts
  copy. P1 updates the snapshot to the true post-P1 reality; the semantic vocabulary assertions
  (specific keys present) must still pass — they are the real regression detector, the counts are
  just the snapshot. Rationale: P1 is exactly the vocabulary/IA phase, so it is the correct owner
  of this reconciliation rather than leaving a chronically-red guard.

## 6. Testing

- `bun run type-check` clean; `bun run lint` exit 0; `bun run test` (vitest) green — including the
  reconciled `credential-terminology.test.ts`.
- New/updated tests: tab routing + default tab; redirect from `/managed/secrets` + `/managed/vaults`
  (and old detail routes) to the new page/tab; the kind chooser routes to the correct create flow;
  each tab renders its kind's list; MCP tab master-detail drill-in.
- Architecture guards (`entity-id-architecture.test.ts`, `api-paths.test.ts`) updated for any moved
  route-page `parseCursor`/route-parse assertions.

## 7. Non-goals (later phases)

- Unified cross-flow credential picker (agent/trigger/session/env pickers) → **P2C**.
- Trigger credential grants → **P2A**. MCP OAuth security → **P2B**.
- Any backend/runtime change.

## 8. Open items resolved (for the record)

- Tab state: **query param** (§2).
- i18n snapshot reconciliation: **owned by P1** (§5).
- Material name for a model connection's access key (umbrella §7 open item): out of P1's critical
  path — P1 uses the existing i18n label; renaming the material string, if desired, is a copy-only
  tweak that can ride along without structural impact.

# Credential Domain Normalization Phase 1 Exceptional Terminology Fix Report

**Status:** DONE_WITH_CONCERNS
**Verification date:** 2026-08-10
**Workspace:** `/Users/yuzhenjiang1/Downloads/workspace/JoySafeter/.worktrees/credential-domain-normalization-phase-1`
**Branch:** `credential-domain-normalization-phase-1`
**Fix base SHA:** `d42aaf2cc8fb5f3841aa33b92b7fe204c9a6bb3a`

## Pre-Fix Audit Method

- Parsed the 157 production TypeScript/TSX files below `frontend/app`, `frontend/components`, and `frontend/hooks`, excluding tests, specs, stories, and generated paths.
- Matched every string literal that resolves to an English or Chinese catalog key, then expanded template-key calls such as `managed.errorStates.${resource}.${reason}` against both catalogs.
- Resolved 1,527 production-referenced catalog paths and reviewed all 65 dynamic translation calls. Dynamic identifier calls were traced to their literal key producers; credential-resource values passed to `ResourceErrorState` were enumerated from production JSX props.
- Parsed source literals, JSX text, and template literals for legacy credential nouns. Routes, query keys, API paths, entity/type names, and internal stale-operation diagnostics were classified as compatibility identifiers rather than user vocabulary.
- Cross-checked all active values containing `secret`, `vault`, `configuration`, `API key`, `key`, `密钥`, `凭证库`, `凭据库`, `模型配置`, or credential equivalents before semantic classification.

The disposable audit output was written outside the repository at `/private/tmp/credential_terminology_audit.json` so the implementation contains no generated audit artifact.

## Pre-Fix Active Inventory

### Model Connections

- `managed.agents.basicSettingsDesc` is rendered by both Agent create and edit and says `model secret / 模型密钥`; both callsites also contain the same Chinese legacy fallback literal.
- `managed.quickstart.stepComplete.secretSelected` and `managed.quickstart.stepDesc.1` render `Agent Secret / Agent 密钥` in the Quickstart completion flow.
- `managed.skills.aiAuthor.noSecrets` is rendered when the AI Skill Author has no `openai_responses` LLM Secret; the production query is `useProtocolSecrets`, so this is a Model Connection state rather than a generic Secret state.
- The duplicate `agents.edit.*Secret` and `managed.agents.edit.*Secret` selection/search catalog values contain `model configuration(s)` and `model secret(s)`. Direct production searches found no current callsite, but they are included in this explicitly authorized residual catalog cleanup because they were named in the human-confirmed findings.

### Service Credentials And Credential Fields

- `managed.environments.egressCreateSecretOption` and `managed.environments.egressAllowedPathsHint` describe the Generic Secret selected for outbound injection; their approved resource noun is Service Credential.
- `managed.llm.genericKey`, `managed.llm.genericPairRequired`, and `managed.llm.genericValuePlaceholder` are rendered by Service Credential creation; the key is a Credential Field and the stored value is a credential value.
- The dynamic `managed.errorStates.secret.*` family is active from both Connections & Credentials pages through `resource="secret"`; its six values still expose the internal Secret resource noun.

### MCP Credential Sets

- `frontend/app/managed/sessions/[sessionId]/page.tsx` renders the hard-coded plural label ``${count} vaults`` for sessions with multiple MCP Credential Sets.
- `frontend/hooks/managed/use-quickstart-chat.ts` sends the production Quickstart prompt `What vault configuration does my agent need for MCP server credentials?`.
- `managed.sessions.credentials` and `managed.sessions.noCredentials` are rendered inside the MCP Credential Set drawer but use an unqualified generic credential label.

### Project Access Tokens

- The dynamic `managed.errorStates.apiKey.*` family is active from the Project Access Tokens page through `resource="apiKey"`; all six values still render API key vocabulary.
- `manage.apiKeys.namePlaceholder`, `manage.apiKeys.newKeyWarning`, and `manage.apiKeys.revokeDesc` describe the project authentication resource as a key rather than a Project Access Token.

## Pre-Fix Inactive Proof

- `rg` across non-test frontend TypeScript/TSX found no production references to `agents.edit.selectSecret`, `agents.edit.searchSecret`, `agents.edit.noSecretMatch`, `agents.edit.createSecret`, or their `managed.agents.edit.*` duplicates.
- `managed.triggers.secretRefPlaceholder` remains unreferenced; the active Trigger flow uses `managed.triggers.serviceCredential*` and `managed.triggers.credentialField*`.
- `managed.skills.aiAuthor.selectSecret` is unreferenced; the current page auto-selects from `useProtocolSecrets` and renders only `managed.skills.aiAuthor.noSecrets`.
- `SecretKeySelect` and its `managed.secrets.selectKey` fallback have no production import or render callsite; the active Trigger field selector uses the Service Credential-specific component.
- Provider API-key field copy, Bearer token copy, Trigger `SECRET` sample variables, routes, query keys, and internal `Secret`/`Vault` diagnostics were classified as legitimate protocol or compatibility terminology and are not replacement targets.

## Root Cause

The first terminology wave built its contract from a manually selected replacement list instead of deriving the list from production callsites. That left four systematic gaps: dynamic catalog paths selected by resource props, helper/consumer semantics such as the AI Skill Author's LLM-only query, hard-coded source strings outside locale catalogs, and leaf copy below already-normalized page titles. The prior regression contract therefore passed while active UI and production prompts still exposed legacy vocabulary.

## Changed Active Paths And Semantic Mapping

### Model Connection / 模型连接

- Normalized Agent create/edit descriptions, the Quickstart selected/completion copy, and the AI Skill Author empty state from model/Agent Secret wording to Model Connection wording.
- Normalized the provider/protocol form's active generic configuration labels to neutral `Name` and `Type`, and its model-specific hints to Model Connection.
- Normalized both legacy Agent selection/search catalog families named in the residual findings without renaming their i18n paths.
- Replaced the hard-coded Quickstart Vault prompt with `managed.quickstart.autoIntro.mcpCredentialSetQuestion`; the hook now sends locale-specific approved copy.

### Service Credential / 服务凭据

- Normalized outbound-service creation and high-privilege guidance from Secret to Service Credential.
- Normalized Service Credential key/value creation to `Credential Field / 凭据字段` and credential value wording.
- Normalized the active dynamic `managed.errorStates.secret.*` family to the combined Connections & Credentials resource vocabulary because the internal `secret` route can represent either a Model Connection or Service Credential.

### MCP Credential Set / MCP 凭据组

- Replaced the session-detail ``${count} vaults`` literal with `t('managed.sessions.mcpCredentialSetCount', { count })`.
- Added i18next v4 `_one` and `_other` forms in both locales and verified singular/plural interpolation through a real i18next instance.
- Qualified the MCP drawer's active `Credentials` and empty-state copy as MCP Credentials / MCP 凭据.

### Project Access Token / 项目访问令牌

- Normalized all six active dynamic `managed.errorStates.apiKey.*` paths.
- Normalized the token-name placeholder, one-time copy warning, and revoke description on the production Project Access Tokens page.
- Provider API-key field wording, Bearer token wording, and Trigger sample variables remain unchanged because they describe real external protocol fields rather than the JoySafeter project authentication resource.

## RED Evidence

After adding the table-driven expectations, i18next plural contract, production-literal AST guard, and Quickstart hook test, the final pre-fix run was:

```bash
cd frontend
bun run test -- \
  lib/i18n/credential-terminology.test.ts \
  hooks/managed/use-quickstart-chat.test.tsx
```

- Exit status: `1`.
- Result: `2` failed files; `87 failed, 313 passed` tests.
- The terminology contract had `86` expected failures covering both locales, missing count/auto-intro keys, and plural behavior.
- The source guard reported exactly four production literals: both Agent Chinese fallbacks, the session ``${count} vaults`` label, and the Quickstart `vault configuration` prompt.
- The hook test received the legacy hard-coded prompt instead of the requested translated key.
- There were no collection, syntax, fixture, or environment errors in the final RED run.

## GREEN Evidence

### Direct RED Pair

The same command exited `0` after the minimal locale and callsite changes:

- Result: `2/2` files and `400/400` tests passed.
- The table pins exact English and Chinese values for every newly classified path.
- Real i18next interpolation returns `1 MCP credential set`, `2 MCP credential sets`, and the corresponding Chinese count wording.
- The production-literal AST guard reports no legacy UI literal.

### Affected UI And Hook Suite

```bash
cd frontend
bun run test -- \
  lib/i18n/credential-terminology.test.ts \
  hooks/managed/use-quickstart-chat.test.tsx \
  app/managed/agents/components/create-agent-dialog.test.tsx \
  components/managed/llm/compatible-secret-picker.test.tsx \
  app/managed/secrets/components/create-secret-dialog.test.tsx \
  app/managed/sessions/components/create-session-dialog.test.tsx
```

- Exit status: `0`.
- Result: `6/6` files and `429/429` tests passed.
- One pre-existing React stderr warning reports the test-only `onSelectValue` property in `create-agent-dialog.test.tsx`; it is warning-only.

## Full Suites And Static Checks

### Complete Task 8 Frontend Suite

The exact 10-file Task 8 frontend command exited `0`.

- Result: `10/10` files and `440/440` tests passed.
- No warnings or errors were emitted by this suite.

### Complete Task 8 Backend Suite

The exact 16-file Task 8 backend command exited `0`.

- Result: `194 passed, 0 failed` in `35.59s`.
- Warning result: `135 warnings`, all from the pre-existing SQLAlchemy FK-cycle `SAWarning` at `backend/tests/conftest.py:148`.
- This terminology-only wave changes no backend file.

### Static Checks

```bash
cd frontend
bun run type-check
```

- Exit status: `0`; `tsc --noEmit` produced no diagnostics.

```bash
cd frontend
bun run lint
```

- Exit status: `0`.
- Result: `692 warnings, 0 errors`; `609` warnings are potentially fixable with `--fix`.
- This exactly matches the recorded Task 8 baseline and includes no new error.

```bash
git diff --check
```

- Exit status: `0`; no whitespace errors were found.

## Post-Fix Audit And Compatibility Boundaries

- Re-running the same AST/catalog audit covered 157 production files, resolved 1,529 literal or expanded-dynamic catalog paths, reviewed 65 dynamic calls, and found `0` active legacy catalog values.
- The production source guard found no hard-coded model Secret/configuration, Agent Secret, Vault configuration, Chinese legacy credential nouns, or hard-coded Vault count label.
- The only remaining catalog value matched by the old Vault scan is the unreferenced `managed.triggers.secretRefPlaceholder`; direct production search still finds no callsite. Other `vault` matches are normalized values under unchanged internal key names.
- `git diff --name-only -- backend/alembic` is empty: no migration change.
- The selector-path `secret_data` search is empty across `use-service-credentials.ts`, `service-credential-select.tsx`, and `create-trigger-dialog.tsx`.
- The `mcp_oauth|oauth` search remains empty in `create-credential-dialog.tsx`; Vault creation has no OAuth branch.
- The production callsite diff contains only translated fallback copy, one translated Quickstart prompt, and the session count translation call. It changes no route, query key, API field, persisted value, TypeScript/domain type, or existing i18n key name.

## Files

- `frontend/lib/i18n/credential-terminology.test.ts` — expands the bilingual table, verifies i18next count behavior, and guards production literals through the TypeScript AST.
- `frontend/lib/i18n/locales/en.ts` — normalizes the classified English values and adds count/Quickstart keys.
- `frontend/lib/i18n/locales/zh.ts` — provides exact matching Chinese terminology and plural forms.
- `frontend/hooks/managed/use-quickstart-chat.ts` — translates the MCP Credential Set auto-intro prompt.
- `frontend/hooks/managed/use-quickstart-chat.test.tsx` — proves the hook consumes the translated prompt key.
- `frontend/app/managed/sessions/[sessionId]/page.tsx` — replaces the hard-coded Vault count with interpolated i18n.
- `frontend/app/managed/agents/components/create-agent-dialog.tsx` and `frontend/app/managed/agents/[agentId]/edit/page.tsx` — normalize active fallback copy.

## Commits

- `5df1b1585bab753ca99a6723c69a4dbb63821183` — `fix(frontend): close credential terminology gaps`
- Report commit: the separate commit containing this report; its SHA is recorded in the final handoff.

## Concerns

1. The backend suite retains the pre-existing `135` SQLAlchemy FK-cycle warnings; there are no backend failures.
2. Frontend lint retains the pre-existing `692`-warning baseline with zero errors.
3. The affected Agent dialog suite retains one existing React warning about the test-only `onSelectValue` property; all required tests pass.
4. The unreferenced Trigger placeholder keeps legacy Vault wording by design; production callsite and AST evidence prove it is inactive.

No active legacy credential-domain path, migration, plaintext selector access, OAuth creation branch, route/API/type rename, or compatibility-boundary change remains.

## Fix Round — Independent Review Residuals

### Dispositions

1. `frontend/hooks/managed/use-skill-authoring.ts` is production-reachable from the AI Skill Author page and used `密钥(Secret)` when an `openai_responses` Model Connection was not selected. The prompt now says `包含 OPENAI_API_KEY 的模型连接`, preserving the requirement that the selected connection contain the provider's real `OPENAI_API_KEY` field while naming the JoySafeter resource as Model Connection / 模型连接.
2. `managed.vaults.credArchiveTitle` is rendered by the MCP Credential Set detail page for an individual MCP Credential archive action. Its values are now `Archive MCP Credential` / `归档 MCP 凭据`.
3. `managed.vaults.cred.createFailed` is rendered by the MCP Credential creation dialog after an MCP Credential create failure. Its values are now `Failed to create MCP credential. Please try again.` / `创建 MCP 凭据失败，请重试。`.
4. The hook contract pins the exact production prompt, the bilingual terminology table pins both active MCP keys, and the production-source guard now detects the exact `包含 OPENAI_API_KEY 的密钥(Secret)` context. The guard remains intentionally narrow so provider API key fields, Bearer tokens, and internal Secret diagnostics remain permitted.

### Revised Active-Key Audit Count

The earlier `1,527` pre-fix and `1,529` post-fix totals are superseded because the disposable script did not retain reproducible literal and dynamic buckets, expanded only template-key dynamics, and mislabeled the resulting union.

- Scope remains the same `157` production TS/TSX files below `frontend/app`, `frontend/components`, and `frontend/hooks`, excluding tests, specs, stories, and generated paths.
- Both locale catalogs were flattened to leaf paths. AST string literals and no-substitution template literals equal to a catalog leaf produced `1,321` unique direct literal leaves.
- Template translation keys were expanded by matching their static path segments against both catalogs. After removing leaves already present in the direct bucket, these contributed `187` unique leaves.
- The remaining `42` non-template dynamic translation callsites were traced to finite arrays, object metadata, helper return branches, and literal-union producers. After the same deduplication, these contributed `46` unique leaves.
- The finite dynamic bucket is therefore `187 + 46 = 233`; the corrected active inventory is `1,321 + 233 = 1,554` unique translation leaves. Direct and finite-dynamic buckets are disjoint, and each catalog path is counted once.

The audit still finds no active credential-domain value using the legacy concepts in scope. Inactive catalog values remain governed by the unreferenced proof recorded earlier in this report.

### RED And GREEN Evidence

The pre-fix command was:

```bash
cd frontend
bun run test -- lib/i18n/credential-terminology.test.ts hooks/managed/use-skill-authoring.test.tsx
```

- RED exit status: `1`; `6 failed, 386 passed` across two files.
- Expected failures were the hook's legacy prompt, its source-guard match, and exact English/Chinese assertions for the two MCP keys.
- GREEN exit status: `0`; `2/2` files and `392/392` tests passed after the minimal production changes.

The affected hook, terminology, and MCP creation-dialog suite also exited `0`:

```bash
cd frontend
bun run test -- \
  lib/i18n/credential-terminology.test.ts \
  hooks/managed/use-skill-authoring.test.tsx \
  app/managed/vaults/components/create-credential-dialog.test.tsx
```

- Result: `3/3` files and `396/396` tests passed with no warnings or errors.

### Full Verification

- Exact Task 8 frontend suite: `10/10` files and `444/444` tests passed; no warnings or errors.
- `bun run type-check`: exit `0`; `tsc --noEmit` produced no diagnostics.
- `bun run lint`: exit `0`; the unchanged baseline is `692 warnings, 0 errors`, with `609` warnings potentially fixable.
- Exact Task 8 backend suite: `194 passed, 0 failed` in `35.50s`; the existing SQLAlchemy FK-cycle warning occurred `135` times at `backend/tests/conftest.py:148`.
- `git diff --check`: exit `0` before the code commit.
- Compatibility commands confirmed no Alembic change, no selector-path `secret_data`, no OAuth branch in Vault Credential creation, and no route, query key, API field, persisted value, i18n key, or TypeScript/domain-type rename. The focused code diff contains only one prompt value, two bilingual locale values, and their tests.

### Commits

- `00d639df03c5d382b8eb9ac92158d2b2205f4982` — `fix(frontend): close reviewed terminology gaps`
- Fix-round report commit: the separate commit containing this appended section; its SHA is recorded in the final handoff because a commit cannot contain its own SHA without amendment.

### Fix-Round Concerns

1. Frontend lint and backend SQLAlchemy warnings remain baseline warnings, not errors.
2. The source guard is context-specific by design; broad bans on `Secret`, `密钥`, or `凭据` would incorrectly reject legitimate provider and protocol terminology.
3. The earlier audit totals remain in the historical sections above; this revised method and `1,554` total explicitly supersede them.

No independent-review finding remains open. No push or main-checkout modification was performed.

## Fix Round — Environment Service Credentials And Complete Dynamic Inventory

### Dispositions And Callsites

1. `managed.environments.envVarsHint` is active in both `frontend/app/managed/environments/page.tsx` and `frontend/app/managed/environments/[envId]/page.tsx`. The Chinese catalog value and both production fallbacks now classify token, cookie, and API-key material as sensitive `凭据字段` and direct users to store it in a `服务凭据`. The English value remains unchanged and is pinned by the bilingual contract.
2. `managed.environments.egressServicesHint` is active on both Environment create and detail pages. Its Chinese value now states that the platform injects the `服务凭据` without exposing it to the sandbox.
3. `managed.environments.egressBaseUrlHint` is active in `frontend/components/managed/environments-egress-editor.tsx`. Its Chinese value now states that the gateway uses the `服务凭据` to inject authentication information.
4. `managed.environments.egressSectionCredential` is active as the outbound-service editor section heading. Its Chinese value is now the exact resource term `服务凭据`.
5. `managed.environments.egressSkillExampleHint` is active in the outbound URL preview. Its Chinese value now states that authentication information from the `服务凭据` is injected automatically.

These changes preserve the semantic distinction between the Service Credential resource and a Credential Field inside that resource. Provider API key names, token and cookie protocol terms, Bearer authentication, internal Secret diagnostics, routes, API fields, persisted values, i18n key names, and TypeScript/domain identifiers remain unchanged.

### Reproducible Active Translation Inventory

`frontend/lib/i18n/active-translation-inventory.test-support.ts` replaces the earlier disposable audit with a repository-backed implementation used by `frontend/lib/i18n/credential-terminology.test.ts`.

- It recursively scans the same `157` production TS/TSX files below `frontend/app`, `frontend/components`, and `frontend/hooks`, excluding test, spec, story, and generated paths.
- It flattens both locale catalogs, collects string literals and no-substitution template literals that resolve to catalog leaves, expands typed and catalog-matched template translation calls, and adds finite variable-driven families from their production helpers or bounded producers.
- Deduplication is explicit: `1,321` direct leaves form the first set; `188` template candidates contribute `183` new leaves after `5` direct overlaps; finite families then contribute `79` additional leaves not already present.
- The finite additions are `26` skill-eligibility, `6` skill-severity, `5` Quickstart-input, `5` skill-lifecycle/visibility, `8` cron-preset, `19` status, `6` alert, and `4` suggestion leaves.
- The corrected result is therefore `1,321` direct plus `262` deduplicated dynamic leaves, or `1,583` unique active leaves. Both catalogs contain every resolved leaf.

The contract pins the total and each newly omitted family, so deleting status, alert, or suggestion coverage changes the inventory count and fails the test. This method and `1,583` total supersede the earlier `1,554` count and its non-reproducible `187 + 46` dynamic split.

### Corrected Vocabulary Scan And Inactive Proof

The active-value scan now evaluates all `1,583` resolved leaves in both English and Chinese and reports zero active legacy credential-domain values. It exposed no additional production value after the five Environment paths were corrected.

The prior inactive-key disposition remains valid under the larger inventory. In particular, `managed.triggers.secretRefPlaceholder` has no production reference under `frontend/app`, `frontend/components`, or `frontend/hooks`, and the repository-backed inventory reports it absent from `activeLeaves`. Its unreferenced catalog value may therefore remain without weakening the active UI contract.

The hard-coded production-source guard now also targets the exact sensitive-credential fallback context that caused this round while retaining the earlier narrow exclusions. It does not ban legitimate provider API key, Bearer, Cookie, or internal Secret terminology.

### RED And GREEN Evidence

The pre-fix command was:

```bash
cd frontend
bun run test -- lib/i18n/credential-terminology.test.ts
```

- RED exit status: `1`; `7 failed, 379 passed`.
- Five exact Chinese expectations received the legacy Environment values.
- The inventory expected `1,583` leaves but received the incomplete `1,554` result because status, alert, and suggestion families were omitted.
- The production-source guard found the two active `敏感凭证` fallbacks on the Environment create and detail pages.

After the minimal locale, fallback, inventory, and test changes, the targeted command was:

```bash
cd frontend
bun run test -- \
  lib/i18n/credential-terminology.test.ts \
  components/managed/environments-egress-editor.test.tsx \
  lib/managed/environment-response-parsers.test.ts
```

- GREEN exit status: `0`; `3/3` files and `392/392` tests passed.
- The terminology contract resolves exactly `1,321` direct plus `262` dynamic leaves, verifies all five bilingual paths, and reports zero active vocabulary violations.
- The focused UI test renders the approved Chinese Service Credential copy from the real Environment egress editor.

### Full Verification And Boundaries

- Exact Task 8 frontend suite: `10/10` files and `456/456` tests passed with no warnings or errors.
- `bun run type-check`: exit `0`; `tsc --noEmit` produced no diagnostics.
- `bun run lint`: exit `0`; the unchanged baseline is `692 warnings, 0 errors`, with `609` warnings potentially fixable.
- Exact Task 8 backend suite: `194 passed, 0 failed` in `35.94s`; the existing SQLAlchemy FK-cycle warning occurred `135` times at `backend/tests/conftest.py:148`.
- `git diff --check` and the staged diff check both exited `0`.
- Compatibility checks found no Alembic change from base `d42aaf2cc8fb5f3841aa33b92b7fe204c9a6bb3a`, no selector-path `secret_data`, no OAuth branch in MCP Credential Set creation, no backend/API/type file change, and no file or route rename.
- The focused production diff changes only five Chinese locale values and two synchronized fallback strings; no route, query key, API field, persisted value, existing i18n key, or TypeScript/domain type changed.

### Commits

- `128964f5dc6270417aac01878741dcd6732c0324` — `fix(frontend): close environment terminology audit gaps`
- This appended fix-round report is committed separately; its SHA is recorded in the final handoff because a commit cannot contain its own SHA without amendment.

### Fix-Round Concerns

1. Frontend lint and backend SQLAlchemy warnings remain unchanged baseline warnings, not errors.
2. The inventory intentionally keeps bounded finite-family declarations explicit; its exact family and total assertions make omissions visible in review and CI.
3. Broad bans on `凭据`, API key, token, Bearer, Cookie, or Secret would reject legitimate field, protocol, and internal diagnostic language, so both active-value and hard-coded-source guards remain semantically targeted.

No finding from this review round remains open. No push, amend, or main-checkout modification was performed.

## Fix Round — Semantic Credential Copy And Catalog-Derived Dynamics

### Semantic Dispositions

1. `managed.environments.envVarsHint` now identifies tokens, cookies, API keys, and similar material as sensitive values, then directs users to store those values in a Service Credential. It no longer misclassifies the values themselves as Credential Fields. Both Chinese production fallbacks remain synchronized with the catalog.
2. `managed.environments.egressServicesHint` now explains that Skills call the real URL while authentication values derived from the selected Service Credential are applied automatically and never exposed to the sandbox. It no longer says that the credential resource is injected.
3. `managed.environments.egressBaseUrlHint` now explains that the platform authenticates the request at the gateway using the selected Service Credential before re-originating to HTTPS. It no longer says that the platform injects the credential.
4. `managed.environments.egressSectionCredential` now uses the exact section noun `Service Credential` / `服务凭据` in both locales.
5. `managed.environments.egressSkillExampleHint` now explains that authentication derived from the selected Service Credential is applied automatically. It no longer says that the credential resource itself is injected.

The exact bilingual contract pins all five values, and the focused Environment egress editor test renders the English and Chinese Base URL guidance, exact section noun, and Skill preview guidance. Provider API key, token, Cookie, Bearer, Credential Field, and internal Secret language remains unchanged where it describes a real field, value, protocol, or diagnostic concept.

### Inventory Root Cause And Correction

The repository-backed inventory had a special-case `aiAuthorScanStatuses` list for the dynamic call `managed.skills.aiAuthor.scan.status.${result.status}`. That list contained six statuses but omitted the active catalog leaf `not_scanned`, even though the backend scan summary defaults to `not_scanned` and can return it to the UI. The manual exception therefore undercounted an open-ended dynamic family.

- Template translation calls now use their typed values when finite; otherwise the inventory matches every bilingual catalog leaf against the template's static segments. The AI Skill Author status family therefore expands from the catalog prefix and automatically includes `managed.skills.aiAuthor.scan.status.not_scanned`.
- Alert details now derive from every catalog leaf below `analytics.alerts.detail.` instead of duplicating backend alert slugs.
- Suggestion messages now derive from every catalog leaf below `analytics.tokenSummary.suggestionMessages.` instead of duplicating backend suggestion slugs.
- Status labels do not share a safe catalog prefix because the production map intentionally spans `common.*`, `managed.sessions.*`, and `managed.triggers.*`. The audit therefore derives that bounded family directly from the string values in the production `STATUS_LABEL_KEY` object instead of maintaining a second raw-status list.

The recomputed repository-state buckets are:

- `157` production TS/TSX files under `frontend/app`, `frontend/components`, and `frontend/hooks`, with tests, specs, stories, and generated paths excluded.
- `1,321` unique direct literal leaves.
- `189` template candidates, of which `5` overlap the direct set, producing `184` template additions.
- `79` finite-family additions: `26` skill eligibility, `6` skill severity, `5` Quickstart input, `5` skill lifecycle/visibility, `8` cron presets, `19` status, `6` alerts, and `4` suggestions.
- `1,321 + 184 + 79 = 1,584` unique active leaves, equivalently `1,321` direct plus `263` dynamic leaves.

Both locale catalogs contain every resolved leaf. The active credential-value scan evaluates all `1,584` English and Chinese leaves and reports zero active legacy vocabulary violations. No additional active credential-domain value was exposed by the corrected inventory.

### RED And GREEN Evidence

The pre-fix command was:

```bash
cd frontend
bun run test -- \
  lib/i18n/credential-terminology.test.ts \
  components/managed/environments-egress-editor.test.tsx
```

- RED exit status: `1`; `13 failed, 376 passed` across two files.
- Failures covered both rendering locales, all five incorrect English expectations, the four Chinese values that still conflated values/resources/application, the incomplete `1,583` inventory, and the production-source guard for both stale `敏感凭据字段` fallbacks.
- The inventory received `1,321` direct plus `262` dynamic leaves instead of `1,321 + 263`, proving that `not_scanned` was absent.
- There were no collection, syntax, fixture, or environment errors.

The post-fix targeted command was:

```bash
cd frontend
bun run test -- \
  lib/i18n/credential-terminology.test.ts \
  components/managed/environments-egress-editor.test.tsx \
  lib/managed/environment-response-parsers.test.ts
```

- GREEN exit status: `0`; `3/3` files and `393/393` tests passed.
- The contract explicitly requires `managed.skills.aiAuthor.scan.status.not_scanned`, the `184` template additions, the `79` finite additions, and the `1,584` total.

### Full Verification And Boundaries

- Exact Task 8 frontend suite: `10/10` files and `456/456` tests passed with no warnings or errors.
- `bun run type-check`: exit `0`; `tsc --noEmit` produced no diagnostics.
- `bun run lint`: exit `0`; the unchanged baseline remains `692 warnings, 0 errors`, with `609` warnings potentially fixable.
- Exact Task 8 backend suite: `194 passed, 0 failed` in `34.87s`; the existing SQLAlchemy FK-cycle warning occurred `135` times at `backend/tests/conftest.py:148`.
- `git diff --check` and the staged diff check both exited `0`.
- Compatibility checks found no Alembic change from base `d42aaf2cc8fb5f3841aa33b92b7fe204c9a6bb3a`, no selector-path `secret_data`, no OAuth branch in MCP Credential Set creation, no backend/API/type file change, and no file or route rename.
- Production changes are limited to five bilingual catalog values and the two synchronized Chinese fallbacks. No route, query key, API field, persisted value, existing i18n key, or TypeScript/domain type changed.

### Commits

- `37a9732bd886bd4163a95ce92768702a64bee342` — `fix(frontend): correct credential semantics and inventory`
- This appended fix-round report is committed separately; its SHA is recorded in the final handoff because a commit cannot contain its own SHA without amendment.

### Fix-Round Concerns

1. Frontend lint and backend SQLAlchemy warnings remain unchanged baseline warnings, not errors.
2. Open-ended template, alert, and suggestion families now grow with their safe catalog prefixes; the mixed-prefix status family remains source-derived from its production map.
3. The hard-coded source guard remains semantically narrow so legitimate provider API key, token, Cookie, Bearer, Credential Field, and internal Secret terms are not rejected.

No finding from this review round remains open. No push, amend, or main-checkout modification was performed.

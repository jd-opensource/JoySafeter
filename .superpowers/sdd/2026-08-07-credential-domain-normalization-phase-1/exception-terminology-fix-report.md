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

# Final Contract Alignment Review Fix Wave

**Status:** COMPLETE_WITH_BASELINE_WARNINGS
**Verification date:** 2026-08-10
**Workspace:** `/Users/yuzhenjiang1/Downloads/workspace/JoySafeter/.worktrees/credential-domain-normalization-phase-1`
**Branch:** `credential-domain-normalization-phase-1`
**Review base:** `ee0f941e9e4abc341ce16e91406876e9dc62351c`

## Root Causes And Fixes

### 1. Optional MCP Bearer Credential Name

- The frontend deliberately omitted an empty optional `name`, but `CreateCredentialRequest.name` was a required `str`. FastAPI/Pydantic therefore rejected the valid frontend request with `422` before the service could apply product behavior.
- The database model requires a non-null credential name, while the service previously persisted the caller value without normalization.
- `CreateCredentialRequest.name` is now `Optional[str] = None`. Omitted and explicit `null` values therefore reach the service; blank strings were already structurally valid.
- The documented creation normalization rule is: trim an explicit name; if the trimmed value is empty or absent, use the trimmed MCP server URL; if both are blank, use the stable product term `MCP Credential`. This guarantees a deterministic, useful, nonblank fallback without changing the route or response shape.
- The service owns both URL and name normalization, preserving the same result for API and direct service callers. The persisted model and returned response continue to expose the required nonblank `name` string.
- Static Bearer type and nonblank-token validation still run before persistence. Unsupported OAuth/custom creation and blank tokens produce the established errors without audit writes or live-network refreshes. Historical OAuth rows and their read/update/archive/delete compatibility were not changed.

### 2. Quickstart Completion Mapping

- `StepCompleteCard` keyed titles by the current UI step but keyed descriptions by an older positional sequence. Cards from Agent onward therefore described the following resource instead of the resource just completed.
- The MCP description also retained false workspace-level scope, while trial success requested absent `managed.quickstart.stepDesc.6` and could render the raw key.
- Completion titles and descriptions now share one exhaustive semantic step type and one rendered mapping. Internal step IDs, progression logic, and routes remain unchanged.

| UI step | Lifecycle action | Completion description |
| --- | --- | --- |
| 1 | Choose engine | Advances into Model Connection selection; no completion card is rendered. |
| 2 | Select Model Connection | Describes the selected Model Connection and its runtime model, endpoint, and API-key settings. |
| 3 | Create Agent | Describes the reusable, versioned Agent configuration. |
| 4 | Create/select Environment | Describes the Environment sandbox, network, package, and resource constraints. |
| 5 | Create/select MCP Credential Set | Describes a project-scoped MCP Credential Set for sessions in the current project. |
| 6 | Start Session and complete trial | Describes the successful Session/trial run in the selected Environment. |

- Ten bilingual rendered regressions cover steps `2` through `6`, including the MCP Credential Set and Session/trial states, and reject any rendered `managed.quickstart.stepDesc.*` key.

### 3. Active Translation Inventory

- The old inventory scanned only `app`, `components`, and `hooks`, so production translations under `frontend/lib` were invisible.
- Its direct-literal discovery depended on a key already existing in either catalog. Deleting a literal callsite key from both catalogs therefore removed the only evidence that the key was required.
- The inventory now scans production TypeScript/TSX under `app`, `components`, `hooks`, and `lib`. It excludes locale catalogs, declarations, tests/specs/stories, fixtures, generated trees/files, test utilities, test support, and the audit implementation itself.
- AST call analysis collects literal keys from `t(...)`, `tr(...)`, and supported translation-object `.t(...)` calls independently of both catalogs. Template expansion and explicit finite runtime families remain separate, bounded sources; arbitrary source strings are not added to the direct-call inventory.
- Plural callsite bases are considered satisfied only when the catalog has both `_one` and `_other` leaves.
- The source-derived inventory is `235` production files and `1,661` active leaves: `1,274` direct and `387` dynamic/finite. Both catalogs have zero active missing leaves after adding `19` newly exposed bilingual keys, and active legacy-vocabulary checks remain clean.
- The mutation regression removes `managed.errors.writeRequired` from both catalogs and proves the production call at `frontend/lib/managed/errors.ts` remains inventoried and is reported missing in English and Chinese.

## TDD Evidence

| Finding | RED | GREEN |
| --- | --- | --- |
| Optional name | The initial focused contract selection produced `9` failures for schema omission/null handling, name normalization/persistence, and invalid-request side effects. A final service-edge RED then produced `2` expected failures for an untrimmed URL fallback and the all-blank case. | The final `10` focused cases passed; the full Vault contract file passed `33` tests. |
| Quickstart copy | The new rendered regression failed because the semantic completion component/mapping did not exist. | All `10` English/Chinese step `2`-`6` rendered cases passed; the current Quickstart UI/hook/terminology selection passed `428` tests. |
| Translation inventory | The lib-callsite and both-catalog mutation regressions failed (`2` failures) because `lib` was excluded and direct discovery required catalog membership. | The terminology/inventory file passed `389` tests, including both mutation checks. |

## Full Verification

### Backend

- The exact Task 8 backend command passed: **206 passed**, `0` failed, with `147` existing SQLAlchemy dependency-cycle warnings.
- The command included all 16 credential-focused Task 8 files, including `tests/test_vault_error_contract.py`.

### Frontend

- The expanded affected suite passed: **17 files, 503 tests**, `0` failures.
- It includes the complete Task 8 frontend selection plus the Vault dialog, Quickstart completion UI, Quickstart LLM UI, Quickstart hook and helper suites, and terminology/inventory audit.
- `bun run type-check` passed with no diagnostics.
- `bun run lint` passed with `0` errors and the established baseline of `692` warnings; `609` are potentially fixable. A follow-up import-order-only commit prevents this wave from increasing that baseline.

### Range And Compatibility

- The worktree was clean before report creation; `git diff --check` passed.
- `git diff --check ee0f941e..HEAD` passed for the complete implementation range.
- The range contains `11` changed files before this report: `478` insertions and `104` deletions.
- No `backend/alembic` file changed, and no changed API module added or modified an `@router` decorator.
- The service-credential selector path contains no `secret_data` access; the full frontend addition range adds no `secret_data` access.
- The Vault credential creation dialog contains no `oauth` or `mcp_oauth` branch.
- No route, public JSON-field, or major TypeScript/domain type was renamed. No migration, plaintext exposure, OAuth creation/runtime expansion, or main-checkout change entered this wave.

## Implementation Commits

- `eb6f1c61` — `fix(vault): normalize optional bearer names`
- `fc479d8b` — `fix(quickstart): align completion copy`
- `6a57e979` — `test(i18n): audit active lib translations`
- `0047f015` — `chore(frontend): preserve lint baseline`
- `bacc6a1b` — `fix(vault): guarantee bearer fallback names`

## Concerns

- Backend verification retains `147` pre-existing SQLAlchemy warnings about unresolvable foreign-key cycles during metadata sorting.
- Frontend lint retains `692` pre-existing warnings and zero errors. This wave restores, rather than expands, that baseline.
- No blocking contract or compatibility concern remains in the reviewed range.

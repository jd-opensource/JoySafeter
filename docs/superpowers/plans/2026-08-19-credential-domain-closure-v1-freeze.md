# Credential Domain Closure v1 Freeze Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` and `superpowers:test-driven-development`. Do not create commits, stage files, or disturb concurrent dirty/index state.

**Goal:** Complete Credential Domain Closure with v1-only persistence, Registry authority, canonical public language, and runtime material isolation.

**Architecture:** Domain and public contracts remain canonical while a persistence adapter writes the existing v1 JSON shape. Dependency Registry becomes the sole lifecycle authority in enforce mode. Cross-component E2E tests prove that managed material does not enter sandbox-visible surfaces except explicit Environment Injection.

**Tech Stack:** Python 3.13, FastAPI/Pydantic, SQLAlchemy/PostgreSQL, Rust, React/TypeScript/Bun.

**Spec:** `docs/superpowers/specs/2026-08-19-credential-domain-closure-v1-freeze-design.md`

## Global Constraints

- Preserve immutable historical Agent Version and Session Snapshot contents.
- Production reference persistence remains v1 only.
- Do not add a v2 writer flag or backfill command.
- Preserve Task 11 transaction and lock ordering.
- Never expose Credential material in metrics, logs, Audit, Snapshot, or API responses.
- Preserve protected paths: `.deps/SkillSpector`, `deploy/deploy.sh`, `deploy/.env.example`.
- Do not stage, commit, restore, reset, checkout, stash, or push.

---

### Task 1: Close Domain and Registry Contract Gates

**Files:**
- Modify: `backend/app/joysafeter_domain/credentials/references.py`
- Modify: `backend/tests/test_credential_domain_architecture.py`
- Modify: `backend/tests/test_credential_reference_registry.py`
- Modify as required: `backend/app/joysafeter_infrastructure/credentials/dependency_scanners.py`

**Produces:** Framework-free Domain Core and a green real-database Registry contract matrix.

- [ ] Add a failing test proving Domain Core rejects Shared ID imports and Public ID conversion occurs outside Domain.
- [ ] Remove `joysafeter_shared.ids` from Domain reference decoding while preserving typed fail-closed ID validation.
- [ ] Run `backend/.venv/bin/pytest -q backend/tests/test_credential_domain_architecture.py`.
- [ ] Replace naive Registry path fixtures with complete schema-aware contract fixtures.
- [ ] Add explicit negative cases for v2 legacy aliases and unknown schemas.
- [ ] Run `backend/.venv/bin/pytest -q backend/tests/test_credential_reference_registry.py backend/tests/test_credential_reference_codec.py`.

### Task 2: Make Dependency Registry Authoritative

**Files:**
- Modify: `backend/app/joysafeter_application/credentials/lifecycle_coordinator.py`
- Modify: `backend/app/joysafeter_shared/config/settings.py`
- Modify: `deploy/docker-compose.yml`
- Modify: `backend/tests/test_credential_reference_registry.py`
- Create: `docs/runbooks/credential-dependency-registry.md`

**Produces:** `shadow` as explicit rollback/observation and `enforce` as the single production authority.

- [ ] Add a failing test proving enforce mode never calls the legacy Resource or Group scanner.
- [ ] Add a failing test proving Registry scanner errors fail closed in enforce mode.
- [ ] Refactor mode branches so shadow runs legacy+Registry while enforce runs Registry only.
- [ ] Set new-deployment defaults to `enforce`; document `shadow` rollback.
- [ ] Run Registry lifecycle, concurrency, and transaction suites.

### Task 3: Canonicalize Public Credential Language

**Files:**
- Modify: `backend/app/joysafeter_domain/schemas/joysafeter_environment.py`
- Modify: `backend/app/joysafeter_api/api/v1/environments.py`
- Modify: `backend/app/joysafeter_domain/services/joysafeter_environment_service.py`
- Modify: `frontend/types/managed.ts`
- Modify: `frontend/lib/managed/environment-response-parsers.ts`
- Modify: `frontend/components/managed/environments-egress-editor.tsx`
- Modify: active Credential Group pages/components/parsers
- Create/Modify: Backend and Frontend compatibility/terminology tests

**Produces:** Canonical API/UI language while persistence remains v1.

- [ ] Add failing Backend tests that accept old/new request aliases, reject conflicts, emit canonical responses, and persist v1 keys only.
- [ ] Add failing Frontend tests that submit canonical keys and expose no active Vault domain types.
- [ ] Rename active public types/components to Credential Group language; confine legacy routes/parsers to exact compatibility adapters.
- [ ] Keep the persistence Codec explicitly on v1.
- [ ] Run Environment API, Frontend parser/editor, type-check, lint, and terminology census suites.

### Task 4: Prove Runtime Material Isolation and Close Release

**Files:**
- Create: `backend/tests/test_credential_runtime_e2e.py`
- Modify: `backend/tests/test_credential_domain_architecture.py`
- Modify: `backend/tests/test_credential_reference_reverse_census.py`
- Create: `frontend/lib/i18n/credential-terminology.test.ts`
- Create: `docs/superpowers/evidence/2026-08-19-credential-domain-closure-v1-freeze.md`
- Modify: old P0.5 spec/plan with supersession notices

**Produces:** Runtime security proof, full regression evidence, and cleaned closure artifacts.

- [ ] Add failing E2E assertions for model, MCP, HTTP, webhook, Repository Access, Task Identity, and Environment Injection boundaries.
- [ ] Implement only fixes exposed by those E2E tests.
- [ ] Run focused Backend architecture/E2E/regression suites.
- [ ] Run complete Rust tests and Frontend test/type-check/lint gates.
- [ ] Run active terminology, raw-reference, SQL, and material-call censuses.
- [ ] Remove dead aliases, obsolete E2/E3 artifacts, stale exceptions, and generated non-release artifacts.
- [ ] Write final evidence with test outputs, v1-only invariant, Registry mode, rollback, and known warning baseline.
- [ ] Run `git diff --check` and `git diff --cached --check`.


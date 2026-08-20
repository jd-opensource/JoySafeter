# Credential Domain Closure v1 Freeze Evidence

**Specification date:** 2026-08-19  
**Validation date:** 2026-08-20  
**Scope:** P0.5 Credential Domain Closure only  
**Decision:** Close on v1 persistence. Do not start P0.6, enc:v2 rollout, re-encryption, backfill, or immutable Snapshot rewrite.

## 1. Frozen Production Contract

- `legacy-v0` remains read compatibility only.
- `v1` is the only production persistence format for Credential references and Snapshots.
- `v2` remains a fail-closed Codec grammar and test contract. Internal Python and Rust Codec branches are callable by tests, but there is no production caller, rollout flag, or deployment setting that selects v2.
- New Python Snapshot persistence calls the canonical Codec with `version="v1"`.
- New Rust Snapshot persistence calls `encode_snapshot(..., Some(EncodeVersion::V1))`.
- Historical Agent Version and Session Snapshot documents are not rewritten.
- `CREDENTIAL_DEPENDENCY_REGISTRY_MODE=enforce` is the application and Docker Compose default.
- `shadow` is rollback/observation mode. It keeps the legacy scanner authoritative while comparing Registry metadata; it does not disable lifecycle blockers or mutate persisted data.

## 2. Closure Delivered

- Credential Group creation and initial member attachment are atomic in the Application layer rather than coordinated by the API route.
- Group/member Audit and impact signaling commit once after the atomic operation.
- Domain Core owns canonical `CredentialId` and `CredentialGroupId` factories without importing Shared ID conversion helpers.
- Public Environment and Credential Group contracts use canonical Credential language while exact legacy aliases remain confined to compatibility boundaries.
- Registry enforce mode is the sole archive/delete dependency authority and fails closed on scanner errors.
- Registry shadow mode normalizes IDs before starting asynchronous scans, preventing abandoned coroutine leaks.
- Reverse-census guards cover registered dependency descriptors, Credential reference surfaces, raw SQL/material access, and typed ID boundaries.
- Rust runtime material access is centralized through `CredentialStore` and consumer-specific resolvers.
- Model, MCP, HTTP, webhook, Repository Access, Task Identity, and Environment Injection boundaries are covered by runtime contract tests. Only explicit Environment Injection may expose selected material to sandbox environment variables.
- Public error catalog gaps found by the closure tests were filled without exposing Credential material.

## 3. Real PostgreSQL Preflight

Command:

```bash
backend/.venv/bin/python backend/scripts/credential_p0_5_preflight.py \
  --output /private/tmp/credential-p0-5-preflight-2026-08-20.json \
  --fail-on-blocker
```

Result after cleanup:

```json
{
  "credential_type_counts": {},
  "cross_project_references": [],
  "invalid_resources": [],
  "legacy_reference_counts": {},
  "mcp_url_conflicts": [],
  "null_project_references": [],
  "snapshot_schema_counts": {
    "legacy-v0": 0,
    "unknown": 0,
    "v1": 27,
    "v2": 0
  }
}
```

The blocker gate passed. The production-like database contains only v1 Snapshots and no invalid, cross-project, ambiguous MCP URL, null-project, legacy-v0, v2, or unknown-schema references.

## 4. Real Environment Cleanup

The real PostgreSQL and Docker environment contained accumulated Rust/Python test fixtures from failed or interrupted runs. Cleanup was not based on age, generic UUID shape, or broad table deletion. Each cleanup set was proven by exact test-only organization/agent naming from source, expanded into a key closure, inspected across every relevant foreign-key column, executed once with a full `ROLLBACK` rehearsal, then committed with exact count assertions.

Removed in total:

| Entity                      | Removed |
| --------------------------- | ------: |
| Test Organizations          |      53 |
| Test Projects               |      53 |
| Test Agents                 |      67 |
| Test Sessions               |      70 |
| Test Tasks                  |      46 |
| Test Sandboxes              |      43 |
| Test Credentials            |      37 |
| Test Credential Groups      |      14 |
| Test Environments           |      10 |
| Test Session Events         |     236 |
| Test Session/Group bindings |      14 |

Additional observations:

- The apparent running sandbox containers were re-created from database state by the Orchestrator, proving the root cause was persisted test state rather than Docker garbage alone.
- The one test-bound stopped container exited before the commit-time label capture. No unproven container was removed.
- Eight normal projectless `pooled` sandbox rows/containers remained after cleanup and were intentionally preserved.
- Redis `joysafeter:task_sandbox:*` keys for captured test tasks were already absent/expired at commit time; zero unrelated Redis keys were changed.
- Final organization/project inventory contains only `Default / Default`.
- Final test-name census is zero and there are no active non-pool test sandboxes.

## 5. Backend Verification

### Current focused closure matrix

```text
443 passed, 160 warnings in 95.48s
```

Files covered Domain/Application boundaries, Registry authority and reverse census, v1 Codec grammar, runtime material isolation, Environment references, typed IDs, preflight behavior, and cipher contract behavior.

All 160 warnings are the existing SQLAlchemy metadata sort warning for the known cyclic FK group involving Skills, Tasks, and Triggers. The focused suite left zero test-named database fixtures.

### Broader evidence from the same closure run

- Credential full-domain real PostgreSQL matrix: `739 passed`, with `348` instances of the same known SQLAlchemy cycle warning.
- Full Backend run before the final Registry shadow normalization repair: `2201 passed, 12 failed`.
- The six Registry failures from that run were repaired and re-run independently: `6 passed`.
- The six remaining full-suite failures were outside Credential Closure: one protected federation environment-example mismatch and five Scheduler fake-session fixtures that do not implement the newer `execute()` locking behavior.

The full Backend suite was not represented as fully green after those targeted repairs because it was not re-run end-to-end again.

## 6. Rust Verification

Current and earlier closure evidence:

- Credential SQL architecture: `28 passed`.
- Credential Store integration against real PostgreSQL: `4 passed`.
- Credential Snapshot linearization against real PostgreSQL: `11 passed`.
- Credential Runtime Contract with the contract test key: `244 passed`.
- Archive-before-decrypt focused paths: `2 passed`.
- `cargo fmt --check`: passed before final evidence work and is repeated in the final gate.

The Runtime Contract embeds a fixed `enc:v1` vector encrypted with the 32-byte key `00..1f`. A first host-side run incorrectly injected the deployment key and correctly returned `EnvelopeInvalid` before the intended `FieldMissing` assertion. Re-running with the vector's specified test key passed `244/244`. This was a test-environment key mismatch, not an implementation or error-classification defect. The single fixture left by the interrupted assertion was identified as a one-row key closure and removed transactionally.

The earlier full serial Rust library run produced `233 passed, 4 failed`. The four failures were outside Credential Closure:

- pending control replay expects a bare UUID rather than canonical `evt_...`;
- a Scheduler fixture omits the now-required project;
- an orphaned task assertion expects `pending` rather than `scheduling`;
- stopped-sandbox sweep was contaminated by residual test sandboxes. The contaminating database residue is now removed, but the full serial library suite was not re-run and is not claimed green.

Existing compiler warnings remain baseline warnings and were not hidden or converted into Credential changes.

## 7. Frontend Verification

Current focused Vitest matrix:

```text
8 files passed
548 tests passed
```

This covers Credential terminology, canonical Environment parsing, Credential redirects, Agent/Session boundary parsing, Credential management parity, and Entity-ID architecture.

The active translation inventory was deliberately re-baselined only after identifying the exact concurrent source delta:

- five newly added Quickstart production files increased source inventory from `261` to `266`;
- direct translation leaves increased from `1361` to `1376`;
- dynamic leaves increased from `435` to `443`;
- total active leaves increased from `1796` to `1819`;
- template additions increased from `388` to `396`;
- finite-family additions remained `47`;
- missing English and Chinese leaves remained empty;
- hard-coded legacy Credential vocabulary and active Vault wording guards remained green.

Broader frontend evidence from the same closure run:

- Full Vitest: `105 files`, `1037 tests passed`.
- TypeScript type-check: passed.
- Production Next.js build: passed.
- ESLint: `0 errors`, `589` historical warnings.
- Authenticated browser E2E passed Credential creation, detail, and compatibility redirect flows and removed its temporary users, groups, projects, and organizations.

## 8. Production Writer Census

The current production call census shows:

- Python Snapshot persistence enters the Domain Codec and explicitly writes v1.
- Rust Snapshot persistence explicitly selects `EncodeVersion::V1`.
- No production source outside the Rust Codec implementation references `EncodeVersion::V2`.
- No Python production caller selects `version="v2"`.
- No deployment or settings flag enables a v2 writer.

The Rust and Python Codec implementations retain v2 branches because the freeze requires fail-closed read/grammar parity and test vectors. Their presence does not constitute a production v2 rollout.

## 9. Release and Operational Risks Outside Closure

### Standalone frontend CSP

The standalone frontend image builds CSP `connect-src` from build-time `NEXT_PUBLIC_API_URL`, while runtime environment injection happens later. Building with an empty API URL yields `connect-src 'self'`; login then remains loading even if the runtime container receives an API URL. The existing Compose image works because the API URL was present at build time.

This is a real release/configuration risk but is not a Credential Domain defect and was not silently folded into this closure.

### Protected and concurrent changes

The worktree contains protected deployment files and concurrent Quickstart work. This closure did not restore, stage, commit, or overwrite those changes. Protected paths remain outside the owned patch even when they appear in worktree status.

## 10. Closure Verdict

Credential Domain Closure is coherent and production-capable at the v1 freeze boundary:

- canonical Domain and public language are enforced;
- lifecycle dependency authority is centralized and reversible through shadow mode;
- production persistence is v1-only;
- v2 cannot be selected by a production caller or flag;
- runtime material access is isolated and covered across consumers;
- immutable Snapshots are preserved;
- real PostgreSQL preflight and focused cross-language gates pass;
- test residue capable of changing Orchestrator behavior has been removed.

No remaining meaningful Credential Closure work requires P0.6. The known Backend, Rust, CSP, warning, and concurrent-work items above should remain separate follow-up work rather than reopening this domain closure.

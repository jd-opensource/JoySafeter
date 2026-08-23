# Credential System Completion and Gaps Audit

**Audit date:** 2026-08-23
**Scope:** API keys, unified Credentials, Credential Groups, task identity material, repository tokens, runtime material access, frontend/API contracts, database constraints, compatibility names, package ownership, retention, purge, tests, and temporary-environment cleanup
**Status:** Audit complete; no production implementation changes are made by this report
**Design baseline:** `docs/superpowers/specs/2026-08-23-credential-lifecycle-integrity-and-cleanup-design.md`

> **Same-day remediation note:** This report records the state found at the start of the audit. The accompanying implementation subsequently resolves P0-1, declares the missing task-identity index in ORM metadata (P1-6), and re-registers the manually reviewed sensitive surfaces from P1-9. The remaining P1 and design-gated P2 items below remain open unless a later evidence document explicitly closes them.

## 1. Executive Verdict

The credential system has moved from a fragmented secret-storage implementation toward an explicit lifecycle architecture, but it is not yet end-to-end complete.

The strongest completed areas are encryption-envelope handling, scoped runtime material access, API-key identity constraints, atomic API-key revoke, task-identity consumption/expiry erasure, repository-token terminal erasure, and the unified credential management frontend.

The system still has one release-blocking material-erasure defect: deleting an OAuth-backed Credential, directly or through Credential Group deletion, clears `data` but leaves decryptable material in `oauth_config`. The database nevertheless allows `material_erased_at` to be set. Consequently, the current tombstone state can falsely claim that material was erased.

The remaining major gaps are not isolated UI polish. They span database truth, concurrency contracts, telemetry, write-time management projection, compatibility exit governance, current documentation, test architecture gates, retention, and physical purge.

### 1.1 Readiness index

The following percentages are an evidence-based readiness index, not line or test coverage. Ten lifecycle domains are equally weighted so that a strong frontend or large passing test count cannot hide an incomplete destructive lifecycle.

| Domain | Readiness | Status | Main reason |
|---|---:|---|---|
| Encryption envelope and key rotation | 95% | Strong | v2 envelope, AAD, mixed readers, canary, inventory, rewrap, and offline verification exist |
| Runtime material access and audit | 90% | Strong | Purpose/field-scoped access and non-secret access audit exist in Python and Rust |
| API-key lifecycle | 78% | Partial | State, constraints, expiry, revoke, and UI exist; usage/denial telemetry remains incomplete |
| Credential lifecycle | 62% | Blocked | General terminal erasure exists, but OAuth material survives deletion |
| Credential Group lifecycle | 58% | Blocked | Group/member tombstones exist; OAuth erasure, member locking, and audit granularity are incomplete |
| Task identity lifecycle | 72% | Partial | Runtime paths erase material; database invariants and metadata purge are incomplete |
| Repository-token lifecycle | 60% | Partial | Rotation, expiry fields, sweeper, and terminal erasure exist; expiry is optional and purge is absent |
| Frontend and API integration | 78% | Partial | Unified UI is functional; canonical route ownership, token expiry UX, and docs are incomplete |
| Naming, compatibility, and structure | 45% | Weak | Required compatibility exists but lacks telemetry/removal gates; duplicate names and oversized modules remain |
| Retention and physical purge | 8% | Design only | Phase 2 is intentionally design-gated and almost entirely unimplemented |
| **Whole-system lifecycle readiness** | **65%** | **Not release-complete** | P0 material erasure and multiple P1 lifecycle gaps remain |

For the approved Phase 0 and Phase 1 scope alone, readiness is approximately **72%**. Phase 2 retention and purge must not be counted as implemented merely because tombstones and erasure timestamps exist.

## 2. Audit Method

The audit traced each material-bearing object through:

1. creation and validation;
2. storage representation and database constraints;
3. management read behavior;
4. runtime material reveal;
5. expiry, rotation, archive, revoke, and delete;
6. audit and transactional coupling;
7. secret erasure;
8. metadata retention and physical purge;
9. frontend/API representation;
10. compatibility, naming, ownership, tests, and operational cleanup.

Evidence was accepted only when supported by production code, migrations, direct SQL behavior, or executable tests. A checked plan item or an API projection alone was not treated as proof of database state.

## 3. Lifecycle Completion Matrix

### 3.1 Encryption and material access

| Capability | Result | Evidence |
|---|---|---|
| Versioned ciphertext envelope | Complete | `enc:v2:<key_id>:` writer and Python/Rust readers |
| Associated-data binding | Complete | AAD is required by the v2 contract |
| Rolling compatibility | Complete for current rollout | Legacy envelope readers and configured legacy key remain available |
| Keyring startup validation | Complete | Canary and concurrent initialization paths exist |
| Inventory and rewrap | Complete | Inventory and rewrap flows exist without exposing plaintext |
| Offline integrity verification | Complete | Cursor-paged, read-only verification exists outside startup paths |
| Management secret isolation | Safe stopgap | Secret-classified fields are not decrypted; display-safe fields are individually decrypted and sanitized |
| Write-time display projection | Missing | Management reads still depend on read-time extraction for display-safe values |
| Runtime access boundary | Complete | Python and Rust enforce declared purpose and selected fields |
| Material-access audit | Complete for current runtime paths | Append-only audit and runtime success idempotency are enforced |

### 3.2 API keys

| Transition | Current behavior | Assessment |
|---|---|---|
| Create | Validates trimmed name, supported role, optional future expiry; stores unique hash and UUIDv7 ID | Complete |
| List | Returns lifecycle status and timestamps | Complete |
| Authenticate | Validates key state, creator access, project scope, and capability cap | Functionally complete |
| Usage telemetry | Writes `last_used_at` synchronously on every successful authentication attempt | Incomplete |
| Denial observability | Invalid, expired, and revoked keys converge to no-match behavior | Incomplete |
| Revoke | Conditional, idempotent, first timestamp stable, audit in the same transaction | Complete |
| Purge | No retention-based physical deletion | Missing, Phase 2 |

The authentication state check is correct before context creation, but the later telemetry update does not repeat the revoke/expiry predicates. A concurrent revoke may therefore be followed by a `last_used_at` update. This does not reactivate the key, but it violates the approved state-aware telemetry contract and makes operational evidence less precise.

### 3.3 Credentials

| Transition | Current behavior | Assessment |
|---|---|---|
| Create/update | Validated, encrypted, project-scoped | Complete |
| Archive/restore | Explicit reversible state | Complete |
| Delete | Clears `data`; sets `material_erased_at` and `deleted_at` once | Incomplete for OAuth |
| Repeated delete | No duplicate transition audit | Complete |
| Dependency validation | Active references are scanned before destructive mutation | Complete for logical delete |
| Runtime reveal | Purpose- and field-scoped | Complete |
| Management display | Conservative no-secret-decrypt behavior | Safe stopgap |
| Physical purge | No coordinator or retention policy | Missing, Phase 2 |

### 3.4 Credential Groups

| Transition | Current behavior | Assessment |
|---|---|---|
| Create/update | Group identity and MCP member rules are enforced | Complete |
| Archive/restore | Explicit reversible state | Complete |
| Delete | Group and active members are tombstoned in one transaction | Partial |
| Member material erasure | Bulk update clears `data` only | Blocked for OAuth-backed members |
| Member locking | Group is locked; members are not explicitly locked in deterministic ID order | Incomplete design contract |
| Dependency validation | Active session/group references are checked | Complete for known active bindings |
| Audit | One `credential_group.deleted` event | Incomplete forensic detail |
| Physical purge | No ordered member/group purge | Missing, Phase 2 |

### 3.5 Task identity material

| Transition | Current behavior | Assessment |
|---|---|---|
| Capture | Persists encrypted credential with expiry | Complete at service path |
| Consume | Atomically sets `consumed_at`, `erased_at`, and clears material | Complete |
| Expire | Bounded sweeper uses `FOR UPDATE SKIP LOCKED` | Complete |
| Task terminal state | Trigger clears existing identity material | Complete for task status transition |
| Insert after terminal task | Database does not reject or immediately erase the new row | Missing invariant |
| Timestamp/material consistency | No database CHECK couples `consumed_at`, `erased_at`, and `encrypted_credential` | Missing invariant |
| Expiry chronology | No database CHECK requires `expires_at > captured_at` | Missing invariant |
| Metadata purge | No retention job | Missing, Phase 2 |

### 3.6 Repository tokens

| Transition | Current behavior | Assessment |
|---|---|---|
| Create/attach | Token may be stored with optional expiry | Partial |
| Rotate | Re-encrypts and records rotation time | Complete |
| Expire | Sweeper erases expired material | Complete when expiry exists |
| Session terminal/archive | Database/runtime paths erase material according to current lifecycle policy | Complete for covered transitions |
| Attach to terminal session | Database lifecycle guard rejects the operation | Complete |
| Active session without expiry | Token may remain indefinitely | Policy gap |
| Metadata purge | No retention job | Missing, Phase 2 |

The approved design states that repository-token material must not silently inherit indefinite Session retention. The current optional `token_expires_at` contract leaves this unresolved. The product must choose one explicit policy: mandatory expiry, a server-assigned bounded default TTL, or a formally accepted indefinite-active-session exception.

## 4. Highest-Severity Findings

### P0-1 — OAuth material survives terminal deletion

**Impact:** A Credential can be marked deleted and materially erased while valid OAuth ciphertext remains recoverable from `oauth_config`.

**Affected paths:**

- Direct Credential delete: `backend/app/joysafeter_infrastructure/credentials/sqlalchemy_repository.py`
- Credential Group delete: `backend/app/joysafeter_infrastructure/credentials/sqlalchemy_repository.py`
- ORM constraint: `backend/app/joysafeter_domain/models/joysafeter_credential.py`
- Migration/backfill constraint: `backend/alembic/versions/20260823_000002_credential_material_erasure.py`

**Root cause:** The erasure implementation and database invariant define material as only `data`. OAuth material is stored separately in `oauth_config`, but deletion, backfill, and the `deleted_material_erased` CHECK do not include that column.

**Direct PostgreSQL result:** Disposable PostgreSQL probes confirmed both direct Credential deletion and Credential Group deletion leave encrypted `client_secret`/`refresh_token` values in `oauth_config` while `data = {}`, `deleted_at IS NOT NULL`, and `material_erased_at IS NOT NULL`.

**Required correction:**

1. Define the complete material-bearing column set for every Credential kind.
2. Clear `oauth_config` in direct and group delete paths in the same transaction.
3. Backfill already-deleted OAuth rows.
4. Strengthen the database CHECK so erased/deleted rows cannot retain OAuth material.
5. Add direct-SQL regression assertions for single delete, group delete, repeated delete, rollback, and migration backfill.
6. Re-run Python and Rust readers against mixed pre/post-migration data.

This is the only current P0 because it invalidates the meaning of `material_erased_at` and violates the global terminal-erasure invariant.

## 5. P1 Gaps

| ID | Surface | Gap | Root cause | Implementation readiness |
|---|---|---|---|---|
| P1-1 | Group delete audit | No member count and no per-member delete evidence | Transaction helper emits only the group transition | Ready after audit format is explicitly selected |
| P1-2 | Group concurrency | Members are bulk-updated without deterministic row locks | Repository locks the group but does not call the existing stable member-lock primitive | Ready; add race tests first |
| P1-3 | API-key telemetry | Unthrottled writes, no final state predicate, no stable denial signal | Usage tracking is embedded as best-effort auth-side mutation | Needs a telemetry policy decision, then implementation |
| P1-4 | Repository-token lifetime | Expiry remains optional and UI does not collect it | Product retention policy was not finalized | Design decision required |
| P1-5 | Task identity invariants | Terminal insert, timestamp consistency, and expiry chronology are not DB-enforced | Erasure trigger observes task status changes only | Ready after transition truth table is fixed |
| P1-6 | ORM/migration drift | Migration-only pending-expiry index makes `alembic check` request removal | ORM metadata omits the migrated index | Ready |
| P1-7 | Current API documentation | Docs present removed names and invalid role examples as current contract | Documentation did not migrate with canonical routes/types | Ready; historical docs must remain historical |
| P1-8 | Architecture documentation | Claims v1 reference names are read aliases although v1 writers remain active | Freeze decision and architecture narrative diverged | Ready; document the approved rollout boundary |
| P1-9 | Architecture gates | Reverse census and SQL-owner tests are stale | Approved surface hashes/locations and ownership contracts were not updated with code movement | Ready after manual diff review |
| P1-10 | Management projection | No persisted non-secret write-time projection | Safe read-time stopgap landed before final schema design | Schema/design decision required |

### 5.1 Group delete audit and locking

The design requires group lock, deterministic member locks, blocker validation, member erasure/tombstones, group tombstone, and group plus member audit evidence in one transaction. The current path locks the group and uses one bulk member update. Normal member mutations also lock the parent group, which reduces practical races, but the implementation does not satisfy the explicit lock contract and has no test proving the intended serialization boundary.

The current `CredentialGroupService.soft_delete()` records only `credential_group.deleted`. Either per-member `credential.deleted` events plus a group summary or one approved aggregate event containing immutable member IDs/count must be selected before implementation.

### 5.2 API-key telemetry

The current successful authentication path:

1. checks that the key is active;
2. constructs principal fields;
3. writes `last_used_at` when the stored timestamp is older than the current request timestamp;
4. commits telemetry independently;
5. suppresses telemetry failure.

The update is monotonic but not throttled. Its predicate does not include `revoked_at IS NULL` or the expiry boundary. Invalid, expired, and revoked attempts do not produce a stable operational metric or an explicitly sampled audit event. The lifecycle is usable, but not independently observable as required by the design.

### 5.3 Migration metadata drift

`20260823_000003_task_identity_erasure.py` creates the partial index `ix_task_identity_pending_expiry`. `JoySafeterTaskIdentityContext.__table_args__` does not declare it. On a freshly migrated PostgreSQL database, Alembic autogeneration therefore reports a removal operation instead of a clean schema.

This is not a runtime data-loss defect, but it makes the migration gate untrustworthy and risks accidental index removal in a later generated migration.

## 6. P2 and Design-Gated Gaps

### 6.1 Retention and purge

The following remain unimplemented by explicit design decision:

- Credential and Credential Group tombstone retention and purge;
- API-key revoked/expired retention and purge;
- task-identity metadata retention and purge;
- repository-token metadata retention and purge;
- partitioned material-access audit retention;
- legal hold and privileged retention execution;
- checkpointed, bounded, resumable, dry-run-capable purge orchestration;
- historical JSON reference tombstone rewriting;
- terminated Session-to-Group association cleanup;
- project/organization asynchronous purge orchestration;
- cleanup metrics for eligible, claimed, erased, purged, blocked, failed, retried, and oldest-pending age.

These gaps must not be fixed ad hoc. Physical deletion changes audit/history guarantees and requires approved retention durations, legal-hold behavior, rollback boundaries, and operator permissions.

### 6.2 Test fixtures and governance

Some failing tests construct states that the new database constraints intentionally reject:

- `test_organization_credential_blockers.py` inserts a deleted Credential without `material_erased_at`.
- Rust `credential_store_integration` has the same invalid tombstone fixture.

Those fixtures must be updated to model a valid tombstone. Weakening the database constraint to preserve stale fixtures would be the wrong fix.

The reverse-census and SQL-ownership failures require a different treatment. Their expected source spans/hashes are stale, but they protect sensitive boundaries. Each changed surface must be manually classified before updating the allowlist; blindly regenerating hashes would destroy the value of the gate.

## 7. Frontend and API Completeness

### 7.1 Completed

- `/managed/credentials` is the canonical UI for model Credentials, service Credentials, and MCP Credential Groups.
- Archive, restore, delete, member lifecycle, project scoping, stale-response suppression, and archived-project read-only behavior are covered by targeted tests.
- API-key status, expiry display/input, and revoke wording exist.
- `/managed/secrets` and `/managed/vaults` are redirect-only compatibility routes.
- Management responses avoid returning raw credential material.

### 7.2 Remaining inconsistencies

1. `frontend/app/managed/api-keys/page.tsx` contains the full implementation, but `/managed/api-keys` permanently redirects to `/managed/projects`.
2. `frontend/app/managed/projects/[projectId]/tokens/page.tsx` imports that legacy-path implementation and supplies `projectId`.
3. The component still supports a no-`projectId` API branch using `/auth/api-keys`, despite the route being unreachable through the redirected page.
4. `ApiKeyInfo` in `frontend/types/managed.ts` is unused while the page declares a local `ApiKey` interface.
5. Repository-token creation/rotation UI submits the token without `token_expires_at`, even though the backend accepts it.
6. Canonical credential components retain internal names such as `secretDialog` and `resource="secret"`/`resource="vault"`.

The correct cleanup is not to remove API-key compatibility endpoints immediately. The safe structural change is to move the canonical token-page component into a neutral project-token module, make the explicit project route its owner, then delete the unreachable no-`projectId` branch after route tests prove no internal caller depends on it.

## 8. Compatibility Registry

Compatibility must be retained only when there is a named contract and an exit condition. Current surfaces fall into four categories.

| Surface | Actual status | Why it exists | Decision now | Required exit evidence |
|---|---|---|---|---|
| `/managed/secrets` | UI redirect | Old bookmarks and documentation | Retain temporarily | Route telemetry reaches zero for an agreed window; docs updated |
| `/managed/vaults` | UI redirect | Old bookmarks and documentation | Retain temporarily | Same as above |
| `create=vault` | Input-only alias | Old deep links | Retain only if telemetry proves use; otherwise remove | Producer census plus route/query telemetry |
| `/api/v1/auth/api-keys` | Public API compatibility route | Published clients/docs | Retain | Client migration notice, usage telemetry, dated removal gate |
| v1 `secret_ref` / `secret_refs` | Active persisted writer and reader contract | v1 freeze and stored JSON compatibility | Retain | Stop v1 writes, migrate persisted documents, prove zero v1 reads |
| `cnkey_` | Current raw API-key prefix | External credentials already held by users | Treat as canonical until versioned replacement | Explicit new format and dual-acceptance migration |
| `enc:` / `enc:v1` | Persisted ciphertext compatibility | Existing encrypted rows and rolling deployments | Retain reader | Inventory proves zero remaining legacy envelopes plus rollback-floor approval |
| `JOYSAFETER_VAULT_ENCRYPTION_KEY` | Deployment and old-envelope key name | Existing deployments and ciphertext | Retain | Deployment census, rewrap completion, rollback-window expiry |

### 8.1 Documentation contradiction

`docs/ARCHITECTURE.md` describes `secret_ref` and `secret_refs` as persisted v1 read aliases. Production code still deliberately writes v1 shapes when `EncodeVersion::V1` is selected, including `secret_refs`, `credential_ref`, and `secret_key`. This is an approved rollout boundary in the v1 freeze evidence, not dead compatibility code. The architecture document must say “version-selected writer compatibility,” not “read alias only.”

### 8.2 Missing compatibility governance

Compatibility route metrics and removal dates are absent. Credential-reference counters are process-local and test-visible but are not exported as durable operational telemetry. Therefore, most compatibility surfaces cannot currently satisfy their own removal criteria.

## 9. Naming and Package Ownership

### 9.1 Duplicate service identity

Two classes are named `CredentialGroupService`:

- `backend/app/joysafeter_application/credentials/application_service.py`: compatibility facade;
- `backend/app/joysafeter_application/credentials/group_service.py`: canonical composed service.

They have different constructor contracts. This is not cosmetic: a disposable OAuth erasure probe initially imported the wrong class and exercised the wrong construction path. The duplicate public name increases the probability of incorrect composition and misleading tests.

Recommended sequence:

1. inventory all production and test imports;
2. give the facade an explicit compatibility name or remove it after callers migrate;
3. export only the canonical service from the package boundary;
4. add an architecture test forbidding duplicate public service class names.

### 9.2 Plaintext facade debt

The following convenience path has no production caller but remains available:

- `CredentialService.get_credential_data`;
- `CredentialResourceService.get_credential_data`;
- repository `get_credential_data`.

Tests still call it directly. Retaining a generic plaintext-returning facade weakens the purpose/field-scoped access architecture. Migrate tests to the material access contract, remove the facade chain, and add a residual architecture assertion.

### 9.3 Dependency direction

`credential_binding_errors.py` lives under Domain services but is imported by API, Application, and Infrastructure. The module converts internal binding errors into public/application-facing errors, so its ownership is not domain-pure. Move the translation policy to Application or a shared boundary package; keep Domain exceptions independent of transport/public error formatting.

### 9.4 Oversized modules

| File | Lines | Main concern |
|---|---:|---|
| `backend/app/joysafeter_api/api/v1/auth.py` | 1,853 | Authentication, project membership, and API-key routes share one module |
| `backend/app/joysafeter_infrastructure/credentials/sqlalchemy_repository.py` | 1,667 | Resource, group, lock, query, lifecycle, and impact concerns are co-located |
| `frontend/components/managed/credentials/mcp-credential-group-detail.tsx` | 716 | Query, mutations, state synchronization, and presentation are coupled |
| `frontend/app/managed/api-keys/page.tsx` | 588 | Route ownership, data access, mutation state, filtering, and dialogs are coupled |
| `frontend/components/managed/credentials/mcp-credential-group-list.tsx` | 520 | Listing, mutation orchestration, and presentation are coupled |

Splitting these modules belongs after correctness fixes. Structural movement before P0/P1 behavior is locked would churn sensitive-surface hashes and obscure functional diffs.

## 10. Test and Database Evidence

### 10.1 Passing evidence

| Suite | Result |
|---|---:|
| Frontend targeted Vitest | 15 files, 96 tests passed |
| Frontend type-check | Passed |
| Rust credential unit tests | 35 passed |
| Rust PostgreSQL credential runtime contract | 279 passed |
| Rust PostgreSQL snapshot linearization | 11 passed |
| Rust PostgreSQL encryption canary | 1 passed |
| OAuth erasure disposable PostgreSQL probes | Reproduced the P0 failure for direct and group deletion |

### 10.2 Expected red gates and interpretation

| Suite | Result | Interpretation |
|---|---:|---|
| Python matrix 1 | 247 passed, 2 failed | Both failures are stale reverse-census registrations |
| Python matrix 2 | 341 passed, 4 failed | One invalid deleted-row fixture, two stale Rust source assertions, one ORM/migration index drift |
| Rust SQL architecture | 27 passed, 1 failed | New inventory query lacks an ownership/exception classification |
| Rust PostgreSQL credential store | 18 passed, 1 failed | Fixture constructs a deleted row invalid under the new erasure constraint |

A red architecture gate is not dismissed as “only a test issue.” It means the repository can no longer prove that sensitive SQL and raw-key surfaces are owned. A stale invalid fixture is different: the database is correctly rejecting an impossible state, so the fixture must change.

### 10.3 Environment isolation and cleanup

- Real PostgreSQL validation used disposable containers/Testcontainers rather than the long-lived `joysafeter-db` environment.
- The long-lived project database was not mutated by audit probes.
- Temporary OAuth probe files, temporary scripts, logs, Testcontainers, and disposable audit containers were removed after evidence collection.
- The current worktree contains no untracked temporary probe, generated log, or disposable-environment artifact; intentional source, test, migration, and evidence files remain part of the work under review.

## 11. Root-Cause Ordering

Implementation must follow dependency order rather than visible surface order.

1. **Material truth:** fix OAuth erasure and strengthen the database invariant.
2. **Schema truth:** align ORM metadata, migrations, and valid tombstone fixtures.
3. **Concurrency and evidence:** close Group locking/audit and API-key telemetry races.
4. **Product lifetime policy:** decide repository-token expiry and management projection schema.
5. **Contract truth:** correct current API/architecture docs without rewriting historical records.
6. **Governance truth:** repair sensitive-surface ownership and compatibility telemetry gates.
7. **Retention:** approve policy, then implement checkpointed purge.
8. **Structure:** split oversized modules and remove dead facades only after behavior is stable.

This order prevents structural cleanup from hiding lifecycle defects and prevents a purge implementation from being built on false erasure metadata.

## 12. Phased Remediation

### Phase A — restore lifecycle truth

**Can start after explicit approval of the schema change.**

1. Add failing direct-SQL tests for OAuth direct delete, Group delete, repeated delete, and rollback.
2. Clear `oauth_config` wherever terminal erasure occurs.
3. Backfill deleted OAuth Credentials and strengthen the database CHECK.
4. Declare `ix_task_identity_pending_expiry` in ORM metadata.
5. Update invalid tombstone fixtures without weakening constraints.
6. Manually re-register changed sensitive surfaces and SQL ownership entries.
7. Run migration upgrade, downgrade/irreversibility decision, `alembic check`, Python matrices, and Rust PostgreSQL suites in a disposable database.

**Exit gate:** No terminally deleted Credential retains decryptable material; Alembic reports no drift; architecture gates are green for reviewed surfaces.

### Phase B — complete operational lifecycles

**Requires small policy decisions but no destructive retention policy.**

1. Lock Group members in stable ID order and add concurrent mutation/delete tests.
2. Select and implement Group/member delete audit granularity.
3. Add throttled, state-predicated API-key success telemetry and stable denial metrics.
4. Decide mandatory/default repository-token TTL and expose it consistently in API/UI.
5. Add task-identity consistency constraints and terminal-insert protection.
6. Design and persist non-secret management display projections.
7. Correct current API/tutorial/architecture documentation.

**Exit gate:** Every non-purge transition has database, service, API, UI, audit, concurrency, and direct-SQL evidence.

### Phase C — retention, purge, compatibility exit, and structure

**Must remain design-gated until retention and legal-hold policy is approved.**

1. Approve per-object retention periods, legal hold, operator role, and irreversible boundaries.
2. Partition access audit and implement privileged retention execution.
3. Build bounded, checkpointed, resumable, dry-run purge orchestration.
4. Reconcile relational blockers and versioned JSON tombstone rewrites.
5. Add project/organization asynchronous purge coordination and failure recovery.
6. Export compatibility telemetry and assign dated removal gates.
7. Move canonical project-token UI ownership and remove unreachable branches.
8. Remove plaintext facades, duplicate service names, unused types, and stale internal terminology.
9. Split oversized modules along application command/query, repository resource/group, and UI container/presentation boundaries.

**Exit gate:** Every sensitive field has a documented owner, lifecycle, erasure rule, retention rule, purge path, audit policy, and tested compatibility exit.

## 13. Do-Not-Do List

- Do not mark the OAuth issue fixed by changing only API output or masking.
- Do not set `material_erased_at` unless every material-bearing column is empty.
- Do not weaken erasure constraints to make stale fixtures pass.
- Do not regenerate sensitive-surface hashes without manually reviewing each changed query/call.
- Do not delete v1 reference writers while `EncodeVersion::V1` is an approved active rollout mode.
- Do not remove `enc:v1`, `cnkey_`, old environment-key support, or public API routes without migration evidence.
- Do not implement broad `CASCADE` deletion as a substitute for an explicit purge plan.
- Do not split the largest modules before behavior, migration, and architecture gates are stable.
- Do not run destructive validation against the user's long-lived database.

## 14. Final Completion Criteria

The credential system can be called lifecycle-complete only when all of the following are true:

1. `material_erased_at` is database-verifiable for every material-bearing column, including OAuth fields.
2. Every mutation is lifecycle-authorized, concurrency-safe, idempotent, and transactionally audited.
3. Management reads require no secret decryption.
4. Runtime reveals are purpose/field-scoped and independently auditable.
5. API-key and repository-token expiry behavior is explicit and operationally observable.
6. Task identity and repository-token invalid states are rejected by the database, not only services.
7. ORM metadata, migrations, architecture inventories, and tests agree.
8. Current API/UI/docs use canonical names; compatibility surfaces have owners and exit gates.
9. Retention and purge are approved, bounded, resumable, dry-run capable, and tested against real PostgreSQL.
10. No temporary audit database, container, script, or generated artifact remains.

Until P0-1 is resolved, the lifecycle cannot be considered materially self-consistent. Until Phase C is complete, it cannot be considered retention- or purge-complete.

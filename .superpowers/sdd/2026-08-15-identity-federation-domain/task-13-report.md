# Task 13 Implementer Report

## Status

Implemented Task 13 callback completion in the four planned code/test paths and this report path. The implementation adds the completion command/results, consume-first coordinator flow, authenticated session result, and one bounded restart using the attempt store replacement boundary.

## Scope

Changed only:

- `backend/app/joysafeter_identity_federation/application/commands.py`
- `backend/app/joysafeter_identity_federation/application/results.py`
- `backend/app/joysafeter_identity_federation/application/coordinator.py`
- `backend/tests/test_identity_federation_complete_login.py`
- `.superpowers/sdd/2026-08-15-identity-federation-domain/task-13-report.md`

No API, adapter, store, account gateway, session gateway, bootstrap, deployment, frontend, credential, or orchestrator files were modified for this task.

## RED

Added the complete-login matrix before production code and ran:

```text
cd backend
UV_CACHE_DIR=/private/tmp/joysafeter-uv-cache uv run pytest tests/test_identity_federation_complete_login.py -q
```

The suite failed during collection for the expected missing-feature reason:

```text
ImportError: cannot import name 'CompleteLoginCommand' from
'app.joysafeter_identity_federation.application.commands'
```

Before that valid RED run, two harness-only issues were corrected without changing production behavior: the initial patch was moved from accidental `backend/backend/tests/` placement to the planned test path, and `UV_CACHE_DIR` was redirected to writable `/private/tmp` because the sandbox denied the default user cache.

## GREEN

Implemented:

- Frozen `CompleteLoginCommand(provider_id)`.
- Frozen `LoginSucceeded` carrying only callback URL, access token, refresh token, CSRF token, access expiry, and refresh expiry.
- Frozen `LoginRestarted` carrying the replacement `AuthorizationAction` plus explicit `clear_correlation_cookie=True`; the action carries the replacement cookie to set.
- Optional account/session constructor dependencies so existing Task 12 begin-only construction remains valid until Task 14 injects both gateways.
- Active provider resolution before adapter selection or correlation extraction.
- Adapter-owned attempt-ID extraction for both OAuth state and JD signed-cookie correlation.
- Atomic attempt consumption before attempt validation, adapter completion, account resolution, or session issuance.
- Stable missing, provider-mismatch, expiry, and retry-exhaustion errors.
- Authenticated flow through `FederatedAccountGateway.resolve_or_create()` with compiled account policy, followed by `AuthSessionGateway.issue()`.
- Session result projection without exposing account/principal objects or adding commit/rollback orchestration.
- One restart that creates a new 256-bit-default attempt ID through the existing secure factory, preserves provider/callback/redirect/correlation fields, increments `retry_count`, creates the replacement authorization action, and then calls `replace_for_retry()`.
- Second restart rejection with `FEDERATION_RETRY_EXHAUSTED` after the original attempt remains consumed.

The first GREEN run of the new suite passed:

```text
14 passed in 0.04s
```

## Test Matrix

The new test file covers:

- Missing consumed attempt -> `FEDERATION_ATTEMPT_INVALID`.
- Provider mismatch -> `FEDERATION_ATTEMPT_MISMATCH`.
- Expiry at the current clock instant -> `FEDERATION_ATTEMPT_EXPIRED`.
- Active-provider enforcement before correlation extraction.
- Success ordering: extract, consume, adapter completion, account resolution, session issuance.
- Exact `LoginSucceeded` cookie/redirect data projection.
- OAuth correlation from query state even when a conflicting correlation cookie exists.
- JD correlation from the signed-cookie channel even when a conflicting query state exists; there is no application query-state fallback.
- Adapter, account, and session failure identity propagation after attempt consumption.
- One JD restart with a fresh replacement attempt and preserved callback/provider data.
- Replacement authorization action before atomic store replacement.
- Adapter begin failure without replacement.
- Replacement failure propagation after action construction.
- Second restart rejection without begin/replacement/account/session work.
- Explicit old-cookie clearing and replacement-cookie setting through `LoginRestarted` and its `AuthorizationAction`.

## Verification

Application flow:

```text
uv run pytest tests/test_identity_federation_begin_login.py tests/test_identity_federation_complete_login.py -q
43 passed in 0.05s
```

State store, domain, architecture, adapters, correlation, account, and session boundaries:

```text
uv run pytest \
  tests/test_identity_federation_state_store.py \
  tests/test_identity_federation_domain.py \
  tests/test_identity_federation_architecture.py \
  tests/test_identity_federation_oauth2_adapter.py \
  tests/test_identity_federation_jd_adapter.py \
  tests/test_identity_federation_correlation.py \
  tests/test_identity_federation_account_gateway.py \
  tests/test_identity_federation_session_gateway.py -q
129 passed, 18 warnings in 6.87s
```

The first boundary run was blocked at fixture setup by sandbox denial of the Docker socket. The same unchanged command passed with approved Docker access. The 18 warnings are the existing SQLAlchemy metadata sort-cycle warning emitted by `tests/conftest.py`; no Task 13 test failed or warned.

Ruff on the planned Python paths:

```text
uv run ruff format <three application files> tests/test_identity_federation_complete_login.py
1 file reformatted, 3 files left unchanged

uv run ruff check <three application files> tests/test_identity_federation_complete_login.py
All checks passed!
```

The final format verification reported `4 files already formatted`. The final verification pass and staged `git diff --check` are run immediately before the Task 13 commit.

## Self-Review

### Requirement review

- The coordinator contains no provider protocol branch. It resolves the active provider, resolves that provider's adapter, and dispatches only on the domain outcome type.
- JD correlation remains adapter-owned. The application never reads `state`, the JD ticket cookie, or a correlation cookie directly.
- The consumed attempt is never recreated. Retry uses only `replace_for_retry(consumed, replacement)`.
- Missing, mismatch, and expiry validation happens after `consume()`, preserving one-time callback semantics.
- Account/session failures cannot restore the consumed attempt and are propagated unchanged.
- No Redis/SQL/AuthService atomicity is claimed. The coordinator imports no Redis, SQLAlchemy, database session, AuthService, commit, or rollback symbol.
- The account gateway remains responsible for flush-only account writes, and the session gateway remains responsible for the existing durable session boundary.
- Retry is bounded by persisted `retry_count`; `retry_count >= 1` fails closed.
- Replacement action construction precedes replacement persistence, so adapter failure does not publish a replacement attempt and store failure does not return an authorization result.
- The success result exposes only transport-neutral values required by the later API cookie response.
- No compatibility reads, API changes, fallback path, or unrelated cleanup were introduced.

### Diff review

- No Critical or Important self-review findings remain.
- The optional gateway constructor parameters are deliberate compatibility for Task 12 begin-login tests; completion fails immediately with a configuration `RuntimeError` if a future composition root omits a required gateway. Task 14's planned factory injects both gateways.
- `LoginRestarted.authorization_action.correlation_cookie` is the explicit replacement cookie to set; `clear_correlation_cookie` separately instructs the API to clear the prior cookie first.

## Concurrent Work Safety

The original dispatch base was `2d46654f`. During Task 13, another worker advanced the shared branch to `0a7e2a5f` (`fix(credentials): normalize persisted public ids`) and removed the previously visible unrelated working-tree changes by committing them. That concurrent commit does not touch Task 13 paths. Task 13 remains an isolated follow-up commit; no history was rewritten and no unrelated file is staged.

The scoped review base for Task 13 must be `0a7e2a5f`, because it is the actual parent of the Task 13 commit. Reviewers should use `0a7e2a5f..TASK_13_COMMIT` for the isolated Task 13 diff, while retaining `2d46654f` only as the original dispatch base.

## Concerns

- The boundary suite requires Docker/PostgreSQL testcontainer access outside the restricted sandbox.
- The existing SQLAlchemy table-cycle warning remains unrelated to Task 13.
- Task 14 must inject account/session gateways before exposing callback completion through the application factory, as already specified by the plan.

## Fix Round 1

### Review findings addressed

1. Stored attempts now match the selected active provider on all trusted callback invariants before expiry or adapter completion:
   - `provider_id` equals the selected provider.
   - `redirect_uri` equals the current trusted callback route derived from `CallbackContext.base_url` and the selected provider ID.
   - `correlation_method` equals the selected adapter's declared correlation method.
2. Attempt mismatch validation remains after atomic consume but now precedes expiry. A callback with both a route mismatch and expiry returns `FEDERATION_ATTEMPT_MISMATCH`.
3. Required account and session gateways are preflighted after active provider and adapter resolution but before adapter correlation extraction or attempt consumption. A composition error therefore cannot consume or complete an attempt while Task 12 begin-only construction remains compatible.
4. Adapter/account/session failure tests now assert the exact event sequence, exact account/session call counts, no restart begin call, and no replacement-store call.

### Fix Round 1 RED

Added the regression cases before modifying the coordinator and ran:

```text
cd backend
UV_CACHE_DIR=/private/tmp/joysafeter-uv-cache uv run pytest tests/test_identity_federation_complete_login.py -q
```

The expected failures were:

```text
5 failed, 14 passed in 0.07s
```

Failure evidence:

- Redirect mismatch did not raise `FederationError`.
- Correlation-method mismatch did not raise `FederationError`.
- Combined redirect mismatch and expiry returned `FEDERATION_ATTEMPT_EXPIRED` instead of `FEDERATION_ATTEMPT_MISMATCH`.
- Missing account gateway still produced `extract`, `consume`, and `complete` events before the composition `RuntimeError`.
- Missing session gateway still produced `extract`, `consume`, and `complete` events before the composition `RuntimeError`.

An earlier command attempted to apply the root-relative test path while running from `backend/`; `apply_patch` rejected the nonexistent `backend/backend/tests/...` path, and the unchanged 14-test suite passed. No file changed in that attempt, and it was not treated as RED evidence.

### Fix Round 1 GREEN

The minimal coordinator change preflights both gateways before extraction and compares all three stored attempt invariants before expiry. The focused suite then passed:

```text
UV_CACHE_DIR=/private/tmp/joysafeter-uv-cache uv run pytest tests/test_identity_federation_complete_login.py -q
19 passed in 0.04s
```

Task 12+13 application verification:

```text
UV_CACHE_DIR=/private/tmp/joysafeter-uv-cache uv run pytest \
  tests/test_identity_federation_begin_login.py \
  tests/test_identity_federation_complete_login.py -q
48 passed in 0.06s
```

State, domain, architecture, protocol, correlation, account, and session boundaries:

```text
UV_CACHE_DIR=/private/tmp/joysafeter-uv-cache uv run pytest \
  tests/test_identity_federation_state_store.py \
  tests/test_identity_federation_domain.py \
  tests/test_identity_federation_architecture.py \
  tests/test_identity_federation_oauth2_adapter.py \
  tests/test_identity_federation_jd_adapter.py \
  tests/test_identity_federation_correlation.py \
  tests/test_identity_federation_account_gateway.py \
  tests/test_identity_federation_session_gateway.py -q
129 passed, 18 warnings in 7.80s
```

Formatting and linting on the touched Python paths:

```text
uv run ruff format app/joysafeter_identity_federation/application/coordinator.py \
  tests/test_identity_federation_complete_login.py
2 files left unchanged

uv run ruff check app/joysafeter_identity_federation/application/coordinator.py \
  tests/test_identity_federation_complete_login.py
All checks passed!
```

### Fix Round 1 self-review

- Active-provider validation still occurs before gateway preflight, extraction, or consume.
- Adapter resolution still follows the selected provider protocol; no protocol branch or compatibility path was added.
- Gateway preflight is configuration validation only and adds no transaction, commit, rollback, or cross-store atomicity claim.
- Attempt consumption remains atomic and still occurs before stored-attempt mismatch/expiry validation, preserving replay protection.
- Mismatch validation uses the same trusted route construction as begin login and compares the adapter contract directly rather than reading protocol-specific request fields.
- Restart semantics are unchanged; the stricter boundary failure tests prove authenticated failures never call retry begin or replacement.
- Task 12 begin-login construction remains valid because constructor gateway parameters remain optional and only completion requires them.
- Fix Round 1 scoped review base is `e98a470a`; the fix commit is a focused child of the original Task 13 commit.
- Concurrent credential/deploy working-tree changes are preserved and excluded from staging.

### Fix Round 1 residual risks

- The Docker-backed boundary suite still emits the same 18 pre-existing SQLAlchemy table-cycle warnings.
- Task 14 remains responsible for always injecting both gateways in the production coordinator factory.

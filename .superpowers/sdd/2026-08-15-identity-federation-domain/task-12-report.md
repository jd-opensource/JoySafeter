# Identity Federation Task 12 Report

## Scope

- BASE: `c9ffbcc9cf766f17e02e48de9e85abadd1be22a8`
- Branch: `joysafeter-v2-0814`
- Implemented only:
  - `backend/app/joysafeter_identity_federation/application/commands.py`
  - `backend/app/joysafeter_identity_federation/application/results.py`
  - `backend/app/joysafeter_identity_federation/application/callback_policy.py`
  - `backend/app/joysafeter_identity_federation/application/coordinator.py`
  - `backend/tests/test_identity_federation_begin_login.py`
  - this report
- Existing and concurrently appearing unrelated modifications were not edited, formatted, staged, or committed.

## RED

1. Added `backend/tests/test_identity_federation_begin_login.py` before the application implementation.
2. Ran:

   ```text
   cd backend
   UV_CACHE_DIR=/private/tmp/joysafeter-uv-cache uv run pytest tests/test_identity_federation_begin_login.py -q
   ```

3. Observed the expected collection failure:

   ```text
   ModuleNotFoundError: No module named 'app.joysafeter_identity_federation.application.commands'
   ```

4. During self-review, added a malformed lone-surrogate callback case before changing the policy.
5. Ran the focused begin-login suite and observed the expected failure:

   ```text
   UnicodeEncodeError: 'utf-8' codec can't encode character '\ud800'
   ```

6. The first attempted RED command used the default home `uv` cache and was blocked by sandbox permissions. The same test command was rerun with `UV_CACHE_DIR=/private/tmp/joysafeter-uv-cache`; this was an environment correction, not a product-code change.

## GREEN

- Added frozen `BeginLoginCommand` and `BeginLoginResult` application DTOs.
- Added `CallbackUrlPolicy` with fail-closed validation:
  - accepts only a non-empty relative URL beginning with exactly one `/`;
  - uses the compiled default only when the command value is `None`;
  - rejects empty and whitespace-only values rather than falling back;
  - rejects absolute/network-path URLs, backslashes, whitespace, Unicode/control/format characters, malformed percent escapes, encoded path separators, encoded percent ambiguity, dot segments, invalid UTF-8, and malformed Unicode;
  - preserves valid relative query strings and fragments.
- Added `FederatedLoginCoordinator.begin_login()`:
  - parses `ProviderId` and maps malformed or inactive providers to `FEDERATION_PROVIDER_NOT_ACTIVE`;
  - resolves the active provider through the registry;
  - resolves the callback through `CallbackUrlPolicy` before adapter delegation;
  - generates production attempt IDs with `secrets.token_urlsafe(32)`, providing 32 random bytes/256 bits and URL-safe encoding;
  - permits deterministic `attempt_id_factory` and `clock` injection for tests;
  - builds `/api/v1/auth/oauth/{provider}/callback` from trusted `RequestContext.base_url`;
  - constructs one `LoginAttempt` with retry count zero and an exact 600-second TTL;
  - delegates exactly once to the resolved protocol adapter;
  - persists exactly once through `LoginAttemptStore.create()` only after adapter success;
  - returns the adapter authorization URL and correlation cookie unchanged.
- Hardened malformed Unicode handling by catching `UnicodeError`; the new RED case then passed.

## Verification

### Begin-login GREEN

```text
cd backend
UV_CACHE_DIR=/private/tmp/joysafeter-uv-cache uv run pytest tests/test_identity_federation_begin_login.py -q
29 passed in 0.07s
```

### Focused domain, state-store, and adapter boundaries

```text
cd backend
UV_CACHE_DIR=/private/tmp/joysafeter-uv-cache uv run pytest \
  tests/test_identity_federation_begin_login.py \
  tests/test_identity_federation_state_store.py \
  tests/test_identity_federation_domain.py \
  tests/test_identity_federation_oauth2_adapter.py \
  tests/test_identity_federation_jd_adapter.py -q
124 passed in 0.58s
```

### Architecture

The repository autouse fixture starts testcontainers for this unmarked architecture file, so the sandboxed combined run produced 122 passing tests plus three Docker-permission setup errors. The architecture file was rerun with the required Docker socket access:

```text
backend/.venv/bin/pytest backend/tests/test_identity_federation_architecture.py -q
3 passed in 2.55s
```

### Ruff

```text
cd backend
UV_CACHE_DIR=/private/tmp/joysafeter-uv-cache uv run ruff format --check \
  app/joysafeter_identity_federation/application/commands.py \
  app/joysafeter_identity_federation/application/results.py \
  app/joysafeter_identity_federation/application/callback_policy.py \
  app/joysafeter_identity_federation/application/coordinator.py \
  tests/test_identity_federation_begin_login.py
5 files already formatted

UV_CACHE_DIR=/private/tmp/joysafeter-uv-cache uv run ruff check \
  app/joysafeter_identity_federation/application/commands.py \
  app/joysafeter_identity_federation/application/results.py \
  app/joysafeter_identity_federation/application/callback_policy.py \
  app/joysafeter_identity_federation/application/coordinator.py \
  tests/test_identity_federation_begin_login.py
All checks passed!
```

### Git whitespace validation

- Pending path-specific staging and `git diff --cached --check`; the result will be recorded before commit.

## Self-Review

### Requirements audit

- Callback fallback occurs only for `None`; empty and invalid input fails with `FEDERATION_CALLBACK_URL_INVALID`.
- Exact-one-leading-slash policy is covered by valid local paths and malicious absolute, `//`, `///`, backslash, control, malformed percent, encoded separator, dot-segment, and malformed Unicode cases.
- Provider parsing and active-provider enforcement happen before adapter resolution, delegation, or persistence.
- Redirect URI is route-specific and derived only from the trusted request context plus validated `ProviderId`.
- Production attempt IDs contain 256 bits of cryptographic randomness; tests can inject deterministic IDs.
- The adapter receives the exact `LoginAttempt`; OAuth state remains `attempt.id`, and signed-cookie correlation is returned through the existing `AuthorizationAction.correlation_cookie` interface without compatibility fallback.
- Adapter failure creates no attempt; store failure exposes no authorization result; success delegates once and calls the store once with the same object.
- New application code imports no Redis client or concrete store. `LoginAttemptStore` remains the sole persistence owner in Task 12.

### Scope note

- The legacy API module still contains its pre-existing Redis state writes. The approved plan assigns API cutover and removal of those writes to Task 15. Task 12 does not modify that API file, and no new adapter or application code writes Redis directly.

### Review findings

- No Critical or Important findings remain.
- The initial patch was accidentally applied beneath `backend/backend/` because `apply_patch` ran from `backend/`; those untracked accidental files were deleted before the planned files were created at the correct root-relative paths.
- No compatibility fallback, protocol branch, API edit, adapter edit, store edit, or unrelated cleanup was added.

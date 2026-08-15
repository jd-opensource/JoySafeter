# Identity Federation Task 14 Report

## Scope

- BASE: `0d5a0ae6e56330b7b95496a577840b377bd163ef`
- Branch: `joysafeter-v2-0814`
- Implemented only:
  - `backend/app/joysafeter_identity_federation/bootstrap.py`
  - `backend/app/joysafeter_api/startup.py`
  - `backend/tests/test_identity_federation_bootstrap_factory.py`
  - `backend/tests/test_identity_federation_startup.py`
  - this report
- Existing concurrent credential, migration, deploy, and credential-design modifications were preserved and excluded from formatting, staging, and commit.

## RED

1. Added `backend/tests/test_identity_federation_bootstrap_factory.py` before changing production code.
2. Ran:

   ```text
   cd backend
   UV_CACHE_DIR=/private/tmp/joysafeter-uv-cache uv run pytest \
     tests/test_identity_federation_bootstrap_factory.py -q
   ```

3. Observed the expected collection failure because the Task 14 facade did not exist:

   ```text
   ImportError: cannot import name 'build_federated_account_service' from
   'app.joysafeter_identity_federation.bootstrap'
   ```

4. After the minimal implementation, the focused suite reached real configuration compilation and failed because the no-network test lacked the deterministic endpoint resolver used by the existing configuration tests:

   ```text
   4 failed, 3 passed
   FEDERATION_ENDPOINT_UNSAFE: Endpoint destination could not be safely resolved
   ```

   The root cause was test-environment DNS isolation. The test-only resolver seam was added; production endpoint validation and Task 8 transport behavior were unchanged.

5. During self-review, aligned the provider-view facade with both the Task 14 example and zero-argument API consumption. Added the explicit-runtime call before changing the function and observed:

   ```text
   TypeError: get_federation_provider_view() takes 0 positional arguments but 1 was given
   ```

6. One earlier patch command used a root-relative path while already inside `backend/`; `apply_patch` rejected `backend/backend/tests/...`, and the unchanged single test passed. No file changed in that attempt, and it was not treated as RED evidence.

## GREEN

- Added frozen `FederationRuntime` with the compiled immutable provider registry, protocol adapter resolver, and singleton Redis login-attempt store.
- Added `initialize_identity_federation(force=False)` and `get_identity_federation_runtime()` runtime caching.
- Runtime initialization remains fail-fast through `initialize_identity_federation_configuration()`.
- Registered the concrete OAuth2 and JD SSO adapters in `ProtocolAdapterRegistry`.
- Both adapters receive the reviewed `direct_http_client_factory`; no generic `httpx.AsyncClient` shortcut was introduced.
- Created `SignedCorrelationCodec` from `settings.secret_key` with cookie name `joysafeter_federation_attempt`.
- Created `RedisLoginAttemptStore` from `RedisClient.get_client`.
- Added frozen public provider DTOs containing only string `id`, `display_name`, `icon`, ordered providers, and string `login_mode`.
- `get_federation_provider_view()` supports singleton access and the explicit `FederationRuntime` form shown in the Task 14 brief.
- Added `build_federated_login_coordinator(db)` using shared runtime registry/adapters/store and fresh SQLAlchemy account and auth-session gateways for every supplied session.
- Added `build_federated_account_service(db)` using a fresh SQLAlchemy account gateway and the supplied session's commit boundary.
- Kept concrete infrastructure imports private inside the composition root.
- Changed API startup from configuration-only initialization to final runtime initialization while retaining the transitional configuration compiler functions for Task 17.

Focused factory/startup GREEN:

```text
UV_CACHE_DIR=/private/tmp/joysafeter-uv-cache uv run pytest \
  tests/test_identity_federation_bootstrap_factory.py \
  tests/test_identity_federation_startup.py -q
7 passed in 0.38s
```

## Verification

Factory/startup, Tasks 12 and 13 application flows, protocol registry, OAuth2/JD adapters, state store, correlation, account/session gateways, domain, and architecture boundaries:

```text
UV_CACHE_DIR=/private/tmp/joysafeter-uv-cache uv run pytest \
  tests/test_identity_federation_bootstrap_factory.py \
  tests/test_identity_federation_startup.py \
  tests/test_identity_federation_begin_login.py \
  tests/test_identity_federation_complete_login.py \
  tests/test_identity_federation_protocol_registry.py \
  tests/test_identity_federation_oauth2_adapter.py \
  tests/test_identity_federation_jd_adapter.py \
  tests/test_identity_federation_state_store.py \
  tests/test_identity_federation_correlation.py \
  tests/test_identity_federation_account_gateway.py \
  tests/test_identity_federation_session_gateway.py \
  tests/test_identity_federation_domain.py \
  tests/test_identity_federation_architecture.py -q
193 passed, 18 warnings in 8.16s
```

Configuration compiler regression suite:

```text
UV_CACHE_DIR=/private/tmp/joysafeter-uv-cache uv run pytest \
  tests/test_identity_federation_config.py -q
66 passed in 0.22s
```

Formatting, lint, and whitespace checks:

```text
UV_CACHE_DIR=/private/tmp/joysafeter-uv-cache uv run ruff format --check \
  app/joysafeter_identity_federation/bootstrap.py \
  app/joysafeter_api/startup.py \
  tests/test_identity_federation_bootstrap_factory.py \
  tests/test_identity_federation_startup.py
4 files already formatted

UV_CACHE_DIR=/private/tmp/joysafeter-uv-cache uv run ruff check \
  app/joysafeter_identity_federation/bootstrap.py \
  app/joysafeter_api/startup.py \
  tests/test_identity_federation_bootstrap_factory.py \
  tests/test_identity_federation_startup.py
All checks passed!

git diff --check
exit 0
```

## Self-Review

- Runtime caching reuses exactly one compiled provider registry, adapter registry, and Redis attempt store until `force=True` is requested.
- Coordinator/account-service factories never reuse SQLAlchemy gateways and always bind them to the supplied `AsyncSession`.
- The coordinator factory always injects both Task 13 gateways; production completion cannot consume an attempt without account/session composition.
- Runtime adapter construction preserves Task 8 security because both adapters use the existing direct client factory and retain adapter-owned endpoint allowlisting, DNS/IP pinning, original Host/SNI, redirect/proxy rejection, hard deadline, and development-only loopback checks.
- No API-facing provider view contains `ProviderId`, protocol settings, client credentials, active-provider objects, configuration loaders, or adapter instances.
- Concrete adapter, codec, store, and gateway class imports are underscore-private within `bootstrap.py`; consumers can remain limited to the facade functions and public DTO/runtime types.
- Startup now compiles configuration and constructs the final runtime before agent identity validation or broadcaster startup, so federation configuration errors remain fail-fast and unswallowed.
- No compatibility aliases, legacy OAuth configuration reads, protocol fallback, generic HTTP client factory, cross-store transaction claims, or unrelated changes were added.
- A separate reviewer subagent was unavailable in this harness, so the review was completed directly against the Task 14 brief, design, plan, and focused diff.

## Concerns

- The Docker-backed boundary suite emits 18 pre-existing SQLAlchemy table-cycle warnings from `tests/conftest.py`.
- Transitional configuration bootstrap functions remain intentionally public until Task 17 removes their remaining consumers.

## Fix Round 1 — Coherent Configuration/Runtime Cache Lifecycle

### Scope

- Requested Task 14 commit: `8ac5e115725f6b7043639602ebbf29d8f85230d9`.
- The shared branch had advanced cleanly to `abc5031c8ee5a5da9548c8dc0e6d5a64d1004a52`, a direct child of the Task 14 commit, before this fix began.
- `bootstrap.py`, its factory tests, and this report were unchanged between those commits.
- Fix Round 1 changes only:
  - `backend/app/joysafeter_identity_federation/bootstrap.py`
  - `backend/tests/test_identity_federation_bootstrap_factory.py`
  - this report

### Finding

`initialize_identity_federation_configuration(force=True)` replaced `_configuration` without invalidating `_runtime`. A later `get_identity_federation_runtime()` could therefore return adapters/store and a provider registry compiled from the previous configuration. Full runtime force also published the replacement configuration before adapter/store construction completed, so a construction failure could leave a new configuration paired with the old runtime.

### Fix Round 1 RED

Added regressions before changing bootstrap behavior for:

- forced configuration replacement followed by runtime access;
- successful full runtime force replacing registry, adapters, and store together;
- failed forced configuration compilation through both transitional and final initializers;
- failed runtime construction after successful replacement compilation.

Ran:

```text
cd backend
UV_CACHE_DIR=/private/tmp/joysafeter-uv-cache uv run pytest \
  tests/test_identity_federation_bootstrap_factory.py -q
```

Observed the expected failures:

```text
2 failed, 7 passed in 0.48s
```

Failure evidence:

- A successful configuration-only force returned the original cached runtime.
- A forced runtime construction failure left `get_identity_federation_configuration()` pointing at the newly compiled configuration instead of the prior coherent pair.

The successful full-force replacement and failed-compile preservation cases already behaved correctly and remain explicit regression coverage.

### Fix Round 1 GREEN

Replaced the two independently published globals with one frozen `_FederationCache` snapshot containing configuration and optional runtime.

- `_compile_configuration()` builds a configuration candidate without publishing it.
- `_build_runtime(configuration)` builds the codec, concrete OAuth2/JD adapters, and Redis attempt store without publishing them.
- Successful configuration-only force publishes one snapshot containing the new configuration and no runtime, intentionally invalidating the old runtime.
- The next ordinary runtime access builds from that exact cached configuration and publishes the coherent full snapshot.
- Successful full runtime force compiles and builds both candidates first, then publishes configuration/runtime together with one cache assignment.
- Failed compile or runtime construction performs no cache assignment, preserving the prior coherent pair.
- Ordinary no-force caching and startup behavior remain unchanged.
- No lock was added because API startup initialization is synchronous and no existing concurrent force caller exists.

Focused GREEN:

```text
UV_CACHE_DIR=/private/tmp/joysafeter-uv-cache uv run pytest \
  tests/test_identity_federation_bootstrap_factory.py -q
9 passed in 0.67s
```

### Fix Round 1 Verification

Factory, startup, Tasks 12 and 13 application flows, and configuration compiler boundaries:

```text
UV_CACHE_DIR=/private/tmp/joysafeter-uv-cache uv run pytest \
  tests/test_identity_federation_bootstrap_factory.py \
  tests/test_identity_federation_startup.py \
  tests/test_identity_federation_begin_login.py \
  tests/test_identity_federation_complete_login.py \
  tests/test_identity_federation_config.py -q
126 passed in 0.64s
```

Formatting, lint, and whitespace checks:

```text
UV_CACHE_DIR=/private/tmp/joysafeter-uv-cache uv run ruff format --check \
  app/joysafeter_identity_federation/bootstrap.py \
  tests/test_identity_federation_bootstrap_factory.py
2 files already formatted

UV_CACHE_DIR=/private/tmp/joysafeter-uv-cache uv run ruff check \
  app/joysafeter_identity_federation/bootstrap.py \
  tests/test_identity_federation_bootstrap_factory.py
All checks passed!

git diff --check
exit 0
```

### Fix Round 1 Self-Review

- Removing runtime invalidation from configuration force fails the stale-runtime regression.
- Publishing configuration before runtime construction fails the construction-failure preservation regression.
- Reusing any registry, adapter registry, or attempt store during full force fails the full replacement regression.
- Both forced compile entry points preserve the previous cache snapshot on configuration errors.
- Runtime construction still uses the reviewed direct HTTP client factory; endpoint pinning, Host/SNI preservation, proxy/redirect rejection, deadline enforcement, and development-only loopback capability remain inside the unchanged adapters.
- Startup still invokes final runtime initialization and transitional configuration functions remain available for Task 17.
- The single snapshot removes observable configuration/runtime split state without adding locking or unrelated lifecycle complexity.

### Fix Round 1 Risks

- Concurrent forced reinitializations would still be last-writer-wins because no lock is used. No current startup or application path performs concurrent force calls, matching the requested scope.

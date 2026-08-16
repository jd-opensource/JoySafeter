# Identity Federation Task 15 Report

## Status

Complete. OAuth HTTP routes now delegate to the identity-federation bootstrap/application boundary, use the validated canonical backend origin, preserve the legacy HTTP paths/envelopes, and enforce stable callback and cookie behavior.

## Scope

Task 15 changes are limited to:

- `backend/app/joysafeter_api/api/v1/oauth.py`
- `backend/app/joysafeter_shared/config/settings.py`
- `backend/tests/test_identity_federation_api.py`
- `backend/tests/test_oauth_async_boundary_contract.py`
- `backend/tests/test_oauth_state_fail_closed_contract.py` (deleted because state ownership moved to the attempt store/coordinator)
- `backend/tests/test_identity_federation_architecture.py`
- this report

Concurrent credential-management/frontend changes were preserved and excluded. The existing modification to `backend/tests/test_settings_contract.py` was also preserved but excluded from the Task 15 commit because it was outside the declared Task 15 path set; the committed API test file contains direct `BACKEND_URL` default, normalization, malformed-authority, and canonical request-context coverage.

## Preserved Work Audit

The replacement pass began with the prior worker's uncommitted Task 15 implementation intact. The initial focused command was:

```bash
cd backend
uv run pytest tests/test_identity_federation_api.py tests/test_identity_federation_begin_login.py tests/test_identity_federation_complete_login.py tests/test_identity_federation_architecture.py tests/test_oauth_async_boundary_contract.py -q
```

Initial result before additional audit regressions:

```text
72 passed in 0.60s
```

The passing baseline confirmed that further findings required contract/security audit rather than merely repairing an existing red suite.

## RED

### Stable mapping, callback cleanup, and canonical-origin validation

The audit found three defects in the preserved implementation:

1. An unmapped `FederationError` from authorize could expose its internal code and returned 400 rather than a stable unavailable response.
2. A coordinator factory/setup failure happened outside the callback `try` block, producing a 500 and bypassing mandatory federation-correlation cookie clearing.
3. `BACKEND_URL` accepted malformed authority text containing whitespace/control characters or percent-encoded authority data.

Regression tests were added first, then run with:

```bash
cd backend
uv run pytest tests/test_identity_federation_api.py -q
```

Expected RED result:

```text
5 failed, 13 passed in 0.56s
```

The five failures were:

- `test_authorize_unknown_federation_error_maps_to_stable_unavailable_code`: received 400 instead of 503.
- `test_callback_factory_failure_uses_stable_redirect_and_clears_cookie`: received 500 instead of the stable 302 error redirect.
- Three `test_backend_url_rejects_malformed_authority_text` cases did not raise for embedded space, percent-encoded authority text, or an embedded newline.

### Empty-port authority

Final validator self-review found that `https://api.example.com:` was also accepted. After adding that case, the honest RED command was:

```bash
cd backend
UV_CACHE_DIR=/private/tmp/joysafeter-uv-cache \
  uv run pytest tests/test_identity_federation_api.py::test_backend_url_rejects_malformed_authority_text -q
```

Expected RED result:

```text
1 failed, 3 passed in 0.51s
```

The new empty-port case failed because no validation error was raised.

One earlier chained attempt is not counted as RED evidence: it used `backend/tests/...` while already running from `backend/`, so `apply_patch` rejected the nonexistent `backend/backend/tests/...` path, and the subsequent command hit the sandboxed default `uv` cache. No source file changed in that attempt.

## GREEN

Minimal production changes:

- Moved coordinator construction and all callback result-to-response mapping inside the callback failure boundary so setup, completion, unsupported-result, and response-construction failures use the stable generic redirect and clear the correlation cookie.
- Mapped unknown authorize failures to `FEDERATION_UPSTREAM_UNAVAILABLE` with HTTP 503 without exposing internal codes or exception messages.
- Added validated `BACKEND_URL` with local API default and origin-only normalization.
- Rejected whitespace/control characters, encoded/backslash authority text, credentials, paths, queries, fragments, invalid ports, and empty ports.
- Kept base/request URL construction exclusively on `settings.backend_url`; Host and `X-Forwarded-Host` do not influence the canonical URL.
- Kept client IP resolution on the existing trusted-proxy CIDR helper and covered trusted and untrusted peers.

The first regression GREEN was:

```bash
cd backend
uv run pytest tests/test_identity_federation_api.py -q
```

```text
18 passed in 0.52s
```

The empty-port regression GREEN was:

```bash
cd backend
UV_CACHE_DIR=/private/tmp/joysafeter-uv-cache \
  uv run pytest tests/test_identity_federation_api.py::test_backend_url_rejects_malformed_authority_text -q
```

```text
4 passed in 0.46s
```

## Final Verification

### Focused Task 15 matrix

```bash
cd backend
UV_CACHE_DIR=/private/tmp/joysafeter-uv-cache \
  uv run pytest \
    tests/test_identity_federation_api.py \
    tests/test_identity_federation_begin_login.py \
    tests/test_identity_federation_complete_login.py \
    tests/test_identity_federation_architecture.py \
    tests/test_oauth_async_boundary_contract.py -q
```

```text
81 passed in 0.46s
```

### Ruff

```bash
cd backend
UV_CACHE_DIR=/private/tmp/joysafeter-uv-cache \
  uv run ruff check \
    app/joysafeter_api/api/v1/oauth.py \
    app/joysafeter_shared/config/settings.py \
    app/joysafeter_identity_federation \
    tests/test_identity_federation_api.py \
    tests/test_oauth_async_boundary_contract.py \
    tests/test_identity_federation_architecture.py
```

```text
All checks passed!
```

### Adjacent boundaries

```bash
cd backend
UV_CACHE_DIR=/private/tmp/joysafeter-uv-cache \
  uv run pytest \
    tests/test_settings_contract.py \
    tests/test_identity_federation_bootstrap_factory.py \
    tests/test_identity_federation_oauth2_adapter.py \
    tests/test_identity_federation_jd_adapter.py \
    tests/test_identity_federation_state_store.py \
    tests/test_identity_federation_account_gateway.py \
    tests/test_identity_federation_session_gateway.py \
    tests/test_auth_service_login_tokens.py -q
```

The first sandboxed run reached:

```text
114 passed, 15 errors in 1.69s
```

All 15 errors were account-gateway fixture setup failures caused by Docker socket denial while `testcontainers` attempted to start Postgres:

```text
docker.errors.DockerException: Error while fetching server API version:
('Connection aborted.', PermissionError(1, 'Operation not permitted'))
```

The same unchanged command was rerun with approved Docker access:

```text
129 passed, 15 warnings in 7.34s
```

The 15 warnings are the existing SQLAlchemy metadata table-sort cycle warning from `tests/conftest.py`; no Task 15 or adjacent test failed.

## Requirements Audit

- OAuth API imports no Redis client, old `OAuthService`/`AuthService`, protocol handler/config loader, protocol branch, state helper, commit, or rollback.
- Provider response preserves provider fields and adds `login_mode`.
- Authorize delegates through the federation coordinator and preserves the existing success envelope.
- Callback success writes correlation-cookie deletion before auth, refresh, and CSRF cookies.
- Callback restart deletes the old correlation cookie before setting its replacement.
- Callback federation and unexpected failures redirect with stable codes only and clear the correlation cookie.
- Redirect URLs do not include exception messages, upstream response content, authorization code, ticket, claims, or secrets.
- Canonical base/request URLs come only from validated `BACKEND_URL`, defaulting to `http://localhost:8000`.
- Host and forwarded-host spoofing do not alter canonical callback URLs.
- Trusted and untrusted proxy client-IP behavior is covered through the shared CIDR helper.
- Callback query `callback_url` is passed only as transport context and cannot replace the application-owned callback destination.
- JD-specific authorize/retry behavior remains in the reviewed adapter/coordinator path.
- Account list and unlink routes use the federation account application service.
- Legacy route paths and auth/CSRF cookie semantics remain compatible.

## Self-Review

- Re-read the Task 15 brief, identity-federation design, Tasks 12-14 reports, and the complete focused diff.
- Confirmed all additional production fixes were preceded by failing regression evidence.
- Confirmed architecture tests prohibit the old API-layer runtime dependencies and state helper.
- Confirmed no concurrent frontend/credential-management file is included in Task 15 staging.
- Confirmed the old state fail-closed API test is deleted because equivalent ownership and fail-closed behavior live in the state-store/coordinator suites.

## Concerns

- No full backend regression suite was run in this finishing pass; verification was intentionally limited to Task 15 and directly adjacent boundaries as requested.
- `backend/tests/test_settings_contract.py` remains modified but unstaged as concurrent/out-of-scope work. Task 15's committed API suite independently covers the new setting contract needed by this cutover.
- Adjacent account-gateway tests require Docker/Postgres testcontainer access; the approved rerun passed, while the restricted sandbox run cannot execute those fixtures.

## Fix Round 1 — 2026-08-16

### Review Findings

1. The authorize response had lost the legacy `data.state` field even though the frontend authorization contract still requires it.
2. `BACKEND_URL` accepted empty query/fragment delimiters and non-DNS hostnames, did not normalize IDNA, and silently used the localhost default in production.
3. `_resolve_frontend_callback_url` still converted malformed application results into successful quickstart/relative redirects and issued auth cookies.
4. The OAuth API architecture assertion relied on source substrings rather than AST import/call/function constraints and did not protect against renamed callback fallback helpers.

### Scope

Fix Round 1 changes are limited to:

- `backend/app/joysafeter_identity_federation/application/results.py`
- `backend/app/joysafeter_identity_federation/application/coordinator.py`
- `backend/app/joysafeter_api/api/v1/oauth.py`
- `backend/app/joysafeter_shared/config/settings.py`
- `backend/tests/test_identity_federation_begin_login.py`
- `backend/tests/test_identity_federation_api.py`
- `backend/tests/test_identity_federation_architecture.py`
- this report

The existing frontend OAuth authorization type already requires both `authorization_url` and `state`, and its lifecycle fixtures already include `state`; no Task 16 behavior change was necessary. Concurrent `backend/tests/test_settings_contract.py`, credential-management, app-shell, and sidebar work remained untouched and unstaged.

### RED — Authorize Envelope

Task 12 and API tests were changed first to require the generated attempt ID as `BeginLoginResult.state` and `data.state`:

```bash
cd backend
UV_CACHE_DIR=/private/tmp/joysafeter-uv-cache \
  uv run pytest \
    tests/test_identity_federation_begin_login.py::test_begin_login_creates_one_attempt_and_delegates_once \
    tests/test_identity_federation_api.py::test_authorize_delegates_with_canonical_context_and_sets_correlation_cookie -q
```

Expected RED:

```text
2 failed in 0.40s
TypeError: BeginLoginResult.__init__() got an unexpected keyword argument 'state'
```

An earlier patch attempt used root-relative `backend/tests/...` paths while already running from `backend/`; both patches were rejected and the unchanged two tests passed. No file changed, and that run is not RED evidence.

### GREEN — Authorize Envelope

- Added required `state` to `BeginLoginResult`.
- Returned `attempt.id` directly from the coordinator.
- Serialized `result.state` directly in the existing success envelope without parsing the provider authorization URL.

```text
2 passed in 0.36s
```

### RED — Strict Canonical Backend Origin

Task 15-owned API tests added malformed origin, DNS/IDNA/IP, and production explicitness cases without modifying the concurrent settings test file.

The comprehensive settings-focused RED command was:

```bash
cd backend
UV_CACHE_DIR=/private/tmp/joysafeter-uv-cache \
  uv run pytest tests/test_identity_federation_api.py \
    -k 'backend_url or production_requires_explicit' -q
```

Expected RED before the strict validator:

```text
12 failed, 12 passed, 15 deselected in 0.55s
```

Failures covered empty `?`/`#` delimiters, underscore/leading-hyphen/trailing-hyphen/empty/overlong DNS labels, missing IDNA normalization, and production accepting an implicit default.

Additional test-first audit expanded malformed authority coverage:

```text
11 failed, 7 passed in 0.44s
```

after adding port `0`, and:

```text
13 failed, 7 passed in 0.43s
```

after adding leading/trailing whitespace rejection.

### GREEN — Strict Canonical Backend Origin

- Accepts only `http` and `https` origins.
- Rejects any whitespace/control character, userinfo, path other than empty or `/`, any `?`/`#` delimiter, percent/backslash authority text, empty/zero/out-of-range ports, and malformed authority forms.
- Accepts valid IPv4/IPv6 literals.
- Normalizes strict IDNA/DNS labels to lowercase ASCII and rejects underscores, empty labels, leading/trailing hyphens, labels over 63 bytes, and names over 253 bytes.
- Uses `model_fields_set` in an after-model validator so production requires an explicitly supplied `BACKEND_URL`; development retains the local API default.

```text
27 passed, 15 deselected in 0.56s
```

### RED — Callback Result Fail-Closed

The callback test supplied absolute, protocol-relative, and relative malformed `LoginSucceeded.callback_url` values. Before removing the compatibility fallback:

```bash
cd backend
UV_CACHE_DIR=/private/tmp/joysafeter-uv-cache \
  uv run pytest \
    tests/test_identity_federation_api.py::test_callback_malformed_application_path_fails_closed_without_auth_cookies -q
```

```text
3 failed in 0.52s
```

The route redirected successfully to quickstart or a normalized relative path instead of the stable failure redirect.

### GREEN — Callback Result Fail-Closed

- Deleted `_resolve_frontend_callback_url` and the `urlparse` import.
- `_create_auth_response` accepts only an exact-one-leading-slash application path and joins it directly to the normalized frontend origin.
- Any malformed facade result raises inside the callback boundary, maps to `FEDERATION_UPSTREAM_UNAVAILABLE`, clears the correlation cookie, and writes no auth/refresh/CSRF cookies.

```text
4 passed in 0.49s
```

### RED — AST Architecture Enforcement

A synthetic violating module was added before the analyzer existed:

```text
1 failed in 0.14s
NameError: name '_oauth_api_architecture_violations' is not defined
```

After the first analyzer implementation, the synthetic fallback helper was renamed to prove that enforcement was semantic rather than tied only to the historical helper name:

```text
1 failed in 0.03s
Extra items in the right set: 'callback-helper:_callback_url_fallback'
```

### GREEN — AST Architecture Enforcement

The analyzer now parses imports, imported symbols, function definitions, calls, attribute calls, and protocol constants. It rejects:

- old Redis/OAuth service/shared OAuth imports and symbols;
- identity-federation infrastructure/config/protocol and callback-policy imports;
- `get_oauth_config`, `get_protocol_handler`, old state/JD/callback helpers;
- `commit`/`rollback` calls;
- `jd_sso` API branching;
- callback helpers whose names indicate fallback, normalization, policy, resolution, or validation, including renamed helpers.

```text
5 passed in 0.06s
All checks passed!
```

### Final Verification

Focused Task 12/13/API/architecture/async/bootstrap/settings command:

```bash
cd backend
UV_CACHE_DIR=/private/tmp/joysafeter-uv-cache \
  uv run pytest \
    tests/test_identity_federation_begin_login.py \
    tests/test_identity_federation_complete_login.py \
    tests/test_identity_federation_api.py \
    tests/test_identity_federation_architecture.py \
    tests/test_oauth_async_boundary_contract.py \
    tests/test_identity_federation_bootstrap_factory.py \
    tests/test_settings_contract.py -q
```

```text
128 passed in 0.66s
```

Adjacent protocol/state/session/cookie boundaries:

```bash
cd backend
UV_CACHE_DIR=/private/tmp/joysafeter-uv-cache \
  uv run pytest \
    tests/test_identity_federation_oauth2_adapter.py \
    tests/test_identity_federation_jd_adapter.py \
    tests/test_identity_federation_state_store.py \
    tests/test_identity_federation_correlation.py \
    tests/test_identity_federation_session_gateway.py \
    tests/test_auth_service_login_tokens.py \
    tests/test_csrf_protection_contract.py -q
```

```text
107 passed, 6 warnings in 0.85s
```

The six warnings are existing httpx per-request cookie deprecation warnings in `test_csrf_protection_contract.py`; no test failed.

Ruff and diff whitespace:

```text
All checks passed!
```

### Fix Round 1 Self-Review

- The authorize envelope is exactly restored with application-owned state; no URL parsing was introduced.
- Production cannot silently use the localhost `BACKEND_URL` default, while non-production retains the local default.
- Backend origin validation is deterministic and independent of frontend URL, CORS, Host, forwarded-host, or request data.
- Callback success still preserves cookie order; malformed result handling clears only the federation correlation cookie and emits the stable generic redirect.
- JD behavior remains in the adapter/coordinator, and trusted proxy IP/canonical request URL behavior is unchanged.
- Architecture enforcement is AST-based and mutation-tested against renamed fallback helpers.

### Fix Round 1 Risks

- IDNA normalization uses Python's standard `idna` codec and strict post-encoding DNS-label checks; it does not add a new external IDNA dependency.
- The focused settings verification command includes the concurrently modified `test_settings_contract.py`, but that file is not part of this fix-round diff or commit. All new regression coverage needed by Fix Round 1 is committed in `test_identity_federation_api.py`.
- No full backend or frontend suite was run; verification remained limited to the explicitly requested Task 12/13/API/bootstrap/settings and adjacent protocol/cookie boundaries.

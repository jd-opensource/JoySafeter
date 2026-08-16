# Task 17 Report — Legacy OAuth Compatibility Removal

Date: 2026-08-16
Requested base: `590780570f95c46f70dabbffdd0a13e9c19c1404`
Branch: `joysafeter-v2-0814`

During Task 17 staging, the concurrent production work landed separately as
`dd7e8c54d148fac27f51efef2215044917ae5533`. Task 17 keeps those files unchanged and commits on top without
rewriting either commit.

## Scope

Completed one compatibility removal with no aliases, dual reads, fallback factories, or split runtime ownership.

## RED

Added `backend/tests/test_identity_federation_legacy_removal.py` before production changes. The test covers:

- deleted runtime/config/test paths;
- scoped active-text scans across backend runtime/config/env, frontend runtime/env/current README, deploy, current docs,
  root current docs, and CHANGELOG;
- explicit exclusions for historical `docs/plans`, `docs/superpowers`, and `.superpowers` artifacts;
- AST import and symbol-reference checks across backend application and test modules;
- Settings model-field removal;
- Provider Catalog activation-key removal;
- canonical backend/deploy env examples;
- explicit Docker Compose propagation.

Command:

```bash
cd backend
uv run pytest tests/test_identity_federation_legacy_removal.py tests/test_settings_contract.py -q
```

Observed RED: `21 failed, 15 passed`. Failures named the old package, old config files, service/import references,
settings field, env examples, current docs, and missing Compose variables.

## Exact Removals

- Deleted `backend/app/joysafeter_shared/oauth/`, including loader, factory, security helper, base protocol, OAuth2,
  JD SSO, and package exports.
- Deleted `backend/config/oauth_providers.yaml` and `backend/config/oauth_providers.example.yaml`.
- Removed the complete `OAuthService` section from `joysafeter_auth_service.py`.
- Removed `oauth_config_path` and its environment read from Settings.
- Removed active deployment/config use of `OAUTH_CONFIG_PATH`, `SSO_DEFAULT_PROVIDER`, `JD_TOKEN_URL`, and
  `JOYSAFETER_ENABLED`.
- Removed old per-provider activation/default-selection instructions and old config filenames from current docs.
- Removed the legacy-only tests from `test_oauth_async_boundary_contract.py` and retired that filename.

## Preserved Contracts

- Preserved `AuthService`, `issue_login_tokens`, and `run_post_login_init`.
- Replaced the legacy-named shared error helper with `_auth_service_error_payload` for remaining auth/session logging.
- Migrated the refresh-token rotation structured-error contract to `test_auth_service_login_tokens.py`.
- Preserved the Task 15 new-facade state-store/non-leak boundary as
  `test_identity_federation_async_boundary_contract.py`.
- Left the reviewed online JD five-parameter adapter behavior unchanged, including no `ReturnUrl`, no JD token URL,
  and no query-state fallback.
- Left concurrent unstaged production files byte-for-byte unchanged:
  - `backend/app/joysafeter_api/api/v1/oauth.py`
  - `backend/app/joysafeter_identity_federation/infrastructure/protocols/jd_sso.py`
  - `backend/app/joysafeter_identity_federation/infrastructure/protocols/oauth2.py`

## Deployment And Documentation

- Renamed and rewrote the local guide as `backend/config/README_IDENTITY_FEDERATION_LOCAL.md`.
- Provider activation now comes only from `IDENTITY_FEDERATION_PROVIDERS`.
- Added canonical provider/config-path/login-mode variables to backend and deploy env examples.
- Added explicit canonical federation variables to `x-backend-common-env`.
- Updated both local and remote internal JD examples to provider `jd`, `redirect` mode, and only client ID, client
  secret, authorize URL, and userinfo URL.
- Updated current documentation status and CHANGELOG migration notes dated 2026-08-16.

## GREEN

Focused corrected-scope verification:

```text
39 passed in 8.34s
```

Federation/auth/session/JD boundary matrix:

```bash
cd backend
uv run pytest tests/test_identity_federation_*.py tests/test_auth_service_login_tokens.py tests/test_settings_contract.py -q
```

```text
385 passed, 15 warnings in 14.48s
```

The warnings are the existing SQLAlchemy table-cycle warnings from `tests/conftest.py`.

Full backend collection:

```bash
UV_CACHE_DIR=/private/tmp/joysafeter-uv-cache uv run pytest --collect-only -q
```

```text
1615 tests collected in 1.16s
```

Docker Compose rendered successfully to `/tmp/joysafeter-compose-config.yaml`; the rendered API/worker environments
contain the three canonical identity-federation variables.

## Self-Review

- Active exact-token scan returns zero matches outside deliberate historical/task artifacts and regression-test
  constants.
- AST scan finds no imports or live references to the deleted package or service.
- New Provider Catalog retains the reviewed `auto_link_by_email` federation policy; no removed activation or
  provider-selection compatibility vocabulary remains.
- Existing OAuth HTTP route paths and OAuth2 protocol terminology remain intentionally unchanged.
- No changes were made to the three concurrent production files, and unrelated test behavior was not staged into
  Task 17.
- Task 17 files will be path-staged only; no push or history rewrite will be performed.

# Final Fix: Production HTTPS Origin Contract

Date executed: 2026-08-16

## Decision

- Production rejects every `http://` `BACKEND_URL` and `FRONTEND_URL`, including loopback origins.
- Development and test retain loopback HTTP support.
- TLS termination is assumed; the configured URLs are the external browser-visible origins, not internal container transport URLs.
- No request/header inference, compatibility aliases, or fallback URL sources were added.

## Changes

- Reused the existing strict backend origin rules through a field-aware canonical public-origin validator.
- Applied the same canonical validation and normalization to `FRONTEND_URL`.
- Added actionable production failures for insecure backend and frontend origins.
- Kept `cookie_secure_effective` behavior unchanged and added characterization coverage.
- Updated `deploy/.env.remote.example` to use HTTPS for frontend, backend, both CORS variables, and the CSP connect extra origin.
- Updated the existing production identity API settings test to supply both required secure public origins.

## TDD Evidence

Red run before implementation:

```text
backend/.venv/bin/pytest -q backend/tests/test_settings_contract.py
12 failed, 15 passed
```

The failures covered missing frontend canonical validation, insecure production backend/frontend origins, production loopback HTTP, and the HTTP remote example.

Green focused run after implementation and characterization tests:

```text
backend/.venv/bin/pytest -q backend/tests/test_settings_contract.py \
  backend/tests/test_identity_federation_api.py \
  backend/tests/test_identity_federation_bootstrap_factory.py \
  backend/tests/test_identity_federation_startup.py
107 passed
```

## Final Verification

```text
backend/.venv/bin/pytest -q \
  backend/tests/test_settings_contract.py \
  backend/tests/test_identity_federation_config.py \
  backend/tests/test_identity_federation_api.py \
  backend/tests/test_identity_federation_bootstrap_factory.py \
  backend/tests/test_identity_federation_startup.py
179 passed
```

```text
backend/.venv/bin/ruff check \
  backend/app/joysafeter_shared/config/settings.py \
  backend/tests/test_settings_contract.py \
  backend/tests/test_identity_federation_api.py
All checks passed!
```

Compose was rendered with these sentinel values:

```text
FRONTEND_URL=https://frontend.sentinel.invalid
BACKEND_URL=https://backend.sentinel.invalid
CORS_ORIGINS=["https://frontend.sentinel.invalid"]
BACKEND_CORS_ORIGINS=["https://frontend.sentinel.invalid"]
NEXT_PUBLIC_CSP_CONNECT_SRC_EXTRA=https://backend.sentinel.invalid
```

The rendered Compose configuration contained the HTTPS frontend origin, HTTPS backend API origin, and HTTPS API CORS origin. `deploy/.env.remote.example` parsing separately confirmed production plus HTTPS values for both CORS variables and the CSP connect extra origin.

```text
git diff --check
passed
```

## Risks and Notes

- Operators terminating TLS at a proxy must still configure the external `https://` origins even if proxy-to-container traffic remains HTTP.
- Production loopback HTTP is intentionally rejected; local production-mode smoke runs must use HTTPS origins or use development/test mode.
- `NEXT_PUBLIC_CSP_CONNECT_SRC_EXTRA` is not a separately rendered Compose environment key today. The backend HTTPS sentinel is rendered as `NEXT_PUBLIC_API_URL`, which the frontend CSP builder uses for backend connect sources; the canonical remote example still keeps the explicit CSP extra value HTTPS as required.
- `ruff format --check` reports pre-existing formatting drift in `backend/tests/test_identity_federation_api.py`; the same drift exists at the parent commit. Ruff lint passes, and this fix does not reformat unrelated API test sections.
- Unrelated frontend worktree edits were preserved and are not part of this fix.

## Parent

The focused commit is based directly on `40264a2c98cbb28a0de1e2dd47dccde980fd5098`.

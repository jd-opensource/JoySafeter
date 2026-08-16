# Final Frontend Callback Error Fix Report

## Scope

- Work-start HEAD: `40264a2c98cbb28a0de1e2dd47dccde980fd5098`.
- Actual implementation commit parent: `71800cf43914c84e8a77b0b1b723f436b5797758`; the concurrent `fix production HTTPS origin contract` commit landed after validation and before the scoped frontend commit.
- Updated the sign-in callback error mapping to match the backend `CALLBACK_REDIRECT_CODES` contract in `backend/app/joysafeter_api/api/v1/oauth.py`.
- Added focused parameterized coverage for every stable callback code, retired `OAUTH_*` behavior, arbitrary unknown codes, URL cleanup, redirect-effect suppression, and server-message rejection.
- Added English and Chinese user-facing messages where the existing catalog did not distinguish the stable federation failure.

## TDD Evidence

1. Added the callback tests before production changes.
2. Ran `bun test 'app/(auth)/signin/login-form.test.tsx'` and observed 11 expected failures: nine stable codes rendered the untrusted server message, the retired `OAUTH_ACCESS_DENIED` branch remained active, and an arbitrary unknown code rendered the server message.
3. Replaced the retired callback mapping with the exact nine stable `FEDERATION_*` codes and removed all rendering of `error_message` query content.
4. Re-ran the focused test file and observed 31 passing tests.

## Behavior

- `FEDERATION_ATTEMPT_INVALID`, `FEDERATION_ATTEMPT_MISMATCH`, and `FEDERATION_ATTEMPT_EXPIRED` render distinct retry guidance.
- `FEDERATION_UPSTREAM_DENIED` renders the existing cancellation message.
- `FEDERATION_UPSTREAM_UNAVAILABLE`, `FEDERATION_ACCOUNT_LINK_REQUIRED`, `FEDERATION_REGISTRATION_DISABLED`, `FEDERATION_SESSION_ISSUE_FAILED`, and `FEDERATION_CALLBACK_FAILED` render specific local translations.
- Unsupported codes, including retired `OAUTH_ACCESS_DENIED`, render `auth.oauthError`.
- The frontend never renders callback `error_message` query values.
- Callback errors continue to clear callback query parameters and prevent the chooser/redirect policy effect from starting.

## Verification

- Focused Bun test runner: 31 passed.
- Canonical Vitest: 31 passed.
- TypeScript: `bun run type-check` passed.
- Scoped ESLint passed for the changed TypeScript and locale files.
- Scoped Prettier check passed for the changed frontend and report files.
- `git diff --check` passed.

## Preserved Concurrent Work

The unrelated private-network backend/deploy edits were not modified or staged. At report time, Git showed six non-frontend changed paths, while the task description referred to seven; the commit uses explicit frontend/report pathspecs so any current or later concurrent backend path remains excluded.

## Risks

- The new copy is intentionally local and generic enough not to disclose backend or upstream details; product wording can be refined later without changing the stable code policy.
- No legacy callback-code compatibility remains because the current callback endpoint can redirect only codes from `CALLBACK_REDIRECT_CODES`.

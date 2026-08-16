# Identity Federation Task 16 Report

## Status

Complete. Frontend login behavior now follows the compiled backend `login_mode` policy without any frontend provider-selection configuration.

## Scope

Task 16 changes are limited to:

- `frontend/app/(auth)/signin/login-form.tsx`
- `frontend/app/(auth)/signin/login-form.test.tsx`
- `frontend/components/auth/oauth-buttons.tsx`
- `frontend/components/auth/oauth-buttons.test.tsx`
- `frontend/env.example`
- `frontend/README.md`
- this report

Concurrent backend settings-contract and frontend credential/filter/i18n changes were preserved and excluded.

## RED

The first behavior test preloaded a recent `sso_auto_attempted` value and returned a chooser-mode provider response. The expected behavior was to fetch backend policy, avoid authorization, and clear the redirect-only guard.

Command:

```bash
cd frontend
bun test app/'(auth)'/signin/login-form.test.tsx components/auth/oauth-buttons.test.tsx
```

Observed failure before implementation:

```text
12 pass
1 fail

Expected managedGet to be called once for auth/oauth/providers.
Received 0 calls.
```

The failure proved the existing loop guard ran before backend policy resolution, so chooser mode could neither govern behavior nor clear a prior redirect guard.

## GREEN

Implementation changes:

- Added `login_mode: 'chooser' | 'redirect'` to both frontend provider response types.
- Kept authorization responses typed as required `{ authorization_url, state }` envelopes.
- Fetches backend provider policy before applying the redirect-only session guard.
- In chooser mode, clears `sso_auto_attempted` and never requests an authorization URL.
- In redirect mode, selects only `providers[0]`, preserving backend order and the existing TTL loop guard.
- Clears the guard for empty providers, provider-policy failures, authorization failures, and cancelled authorization resolution.
- Preserves callback URL query construction from Task 15.
- Removed `SSO_DEFAULT_PROVIDER` and its documentation with no compatibility read or fallback.

Focused GREEN result:

```text
15 pass
0 fail
44 expect() calls
```

Coverage includes chooser rendering/manual buttons, chooser stale-guard cleanup, first-provider redirect ordering, redirect TTL suppression, empty providers, provider fetch failure, authorization failure, and cancelled authorization resolution.

## Validation

```bash
cd frontend
bun test app/'(auth)'/signin/login-form.test.tsx components/auth/oauth-buttons.test.tsx
bun run type-check
bun run lint
./node_modules/.bin/eslint 'app/(auth)/signin/login-form.tsx' 'app/(auth)/signin/login-form.test.tsx' components/auth/oauth-buttons.tsx components/auth/oauth-buttons.test.tsx
./node_modules/.bin/prettier --check 'app/(auth)/signin/login-form.tsx' 'app/(auth)/signin/login-form.test.tsx' components/auth/oauth-buttons.tsx components/auth/oauth-buttons.test.tsx README.md
cd ..
git diff --check
rg -n 'SSO_DEFAULT_PROVIDER' frontend
```

Results:

- Focused tests: `15 passed`.
- Type check: passed.
- Full lint: exited successfully with `0 errors` and `593` repository warnings.
- Scoped lint: `0 errors`; one pre-existing warning remains on the unchanged `window.location.href` assignment in `oauth-buttons.tsx`.
- Scoped Prettier check: passed. `env.example` is excluded because Prettier has no parser for that filename.
- `git diff --check`: passed.
- Frontend `SSO_DEFAULT_PROVIDER` search: no matches.

## Self-Review

- Confirmed chooser policy is checked before provider selection and authorization.
- Confirmed redirect mode uses the first provider ID exactly as returned by the backend and performs no frontend name/env selection.
- Confirmed the session guard is retained only around redirect-mode authorization, allowing chooser visits to clear it.
- Confirmed missing `login_mode` has no compatibility fallback and therefore cannot silently restore legacy auto-redirect behavior.
- Confirmed Task 15 callback URL encoding and required authorization `state` typing remain intact.
- Confirmed only Task16 files are intended for staging; concurrent unrelated modifications remain unstaged.

## Concerns

No Task16 correctness concerns remain. Repository-wide lint still reports existing warnings outside this task, including the unchanged OAuth navigation assignment warning noted above.

## Fix Round 1 — Redirect Run Ownership

### Review Base

- Original Task16 commit: `ed358a7c108bb8c44bae4476d74cd3f356b84fcc`.
- Actual review base and parent of this fix commit: `a2fd5bb4c252e148b85153c87147c791be302b50`.
- The intervening credential/config commits were preserved without reset or rewrite, and the original Task16 files were unchanged between `ed358a7c` and `a2fd5bb4`.

### RED

Deferred race tests were added before production changes for overlapping callback/provider requests, stale authorization completion, StrictMode, unresolved request cleanup, malformed policy, and exact guard ownership.

Command:

```bash
cd frontend
bun test app/'(auth)'/signin/login-form.test.tsx
```

Observed before the fix:

```text
15 pass
4 fail
```

The four failures demonstrated that:

- provider requests had no abort signal when a callback change superseded the run;
- a new callback run reused the stale numeric guard instead of owning a unique token;
- unmount could not abort a never-resolving provider request;
- unmount could not abort a never-resolving authorization request or release its guard immediately.

### GREEN

The redirect effect now:

- assigns every eligible effect run a monotonic run ID and `AbortController`;
- passes the run signal to both provider and authorization `managedGet` requests;
- checks current ownership immediately after each await and before guard creation, authorization, and navigation;
- writes a unique timestamp/run/sequence guard while still parsing legacy numeric timestamps for TTL checks;
- removes a guard only when its exact token is still present;
- invalidates and aborts a superseded run during cleanup, releasing its owned guard immediately even if a promise never settles;
- marks navigation committed before assigning `window.location.href`, so navigation cleanup preserves the loop guard;
- treats missing or invalid `login_mode` as non-redirect and clears stale guard state;
- preserves chooser mode, backend first-provider order, callback encoding, required authorization state typing, and the absence of `SSO_DEFAULT_PROVIDER`.

Focused result:

```text
23 pass
0 fail
80 expect() calls
```

This includes `20` login-form lifecycle tests and `3` OAuth button lifecycle tests.

### Validation

```bash
cd frontend
bun test app/'(auth)'/signin/login-form.test.tsx components/auth/oauth-buttons.test.tsx
bun run type-check
./node_modules/.bin/eslint 'app/(auth)/signin/login-form.tsx' 'app/(auth)/signin/login-form.test.tsx' components/auth/oauth-buttons.tsx components/auth/oauth-buttons.test.tsx
bun run lint
./node_modules/.bin/prettier --check 'app/(auth)/signin/login-form.tsx' 'app/(auth)/signin/login-form.test.tsx' components/auth/oauth-buttons.tsx components/auth/oauth-buttons.test.tsx
cd ..
git diff --check
```

Results:

- Focused tests: `23 passed`.
- Type check: passed.
- Scoped lint: `0 errors`; the unchanged OAuth button navigation line retains its pre-existing warning.
- Full lint: exited successfully with `0 errors` and `593` existing repository warnings.
- Scoped Prettier check: passed.

### Self-Review

- Confirmed stale provider resolution cannot begin authorization.
- Confirmed stale authorization resolution cannot navigate or remove the current run's guard.
- Confirmed StrictMode authorizes only once with the current callback URL.
- Confirmed unresolved provider and authorization requests are aborted on unmount.
- Confirmed owned guard cleanup is immediate, exact-token only, and skipped after committed navigation.
- Confirmed legacy numeric guards retain TTL behavior and missing/invalid policy fails safe.
- Confirmed no backend, credential, filter, i18n, env, README, OAuth button production, or shared API-client files were modified for this round.

### Fix Round 1 Concerns

No Task16 race correctness concern remains. Repository-wide lint warnings are unchanged from the prior round.

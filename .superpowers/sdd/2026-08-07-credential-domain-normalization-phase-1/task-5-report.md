# Task 5 Implementation Report

## Status

DONE

## Revisions

- Base SHA: `46add8957efcef99491fcaa8574d2bd35e1b6032`
- Head SHA (code and tests): `4f34274b2d9d697b68e2a98091109ea692e0b2b6`
- Implementation commit: `4f34274b2d9d697b68e2a98091109ea692e0b2b6` (`feat(triggers): add service credential selector`)

## Files Changed

- `frontend/hooks/managed/use-service-credentials.ts`
- `frontend/hooks/managed/use-service-credentials.test.tsx`
- `frontend/components/managed/shared/service-credential-select.tsx`
- `frontend/components/managed/shared/service-credential-select.test.tsx`
- `frontend/components/managed/shared/index.ts`
- `frontend/components/managed/triggers/create-trigger-dialog.tsx`
- `frontend/components/managed/triggers/create-trigger-dialog.test.tsx`
- `.superpowers/sdd/2026-08-07-credential-domain-normalization-phase-1/task-5-report.md`

## RED Evidence

Paginated Generic Secret query:

```bash
cd frontend
bun run test -- hooks/managed/use-service-credentials.test.tsx
```

The first run failed because `use-service-credentials.ts` did not exist. After
adding only a nonfunctional shell, the assertion-level run reported `2 failed`:
the hook made no `/secrets` requests and the cursor-loop test resolved with an
empty array instead of rejecting.

Service credential selector:

```bash
cd frontend
bun run test -- components/managed/shared/service-credential-select.test.tsx
```

Result: the suite failed because `service-credential-select.tsx` did not exist,
before the component or barrel export was added.

Trigger data flow and validation:

```bash
cd frontend
bun run test -- components/managed/triggers/create-trigger-dialog.test.tsx
```

After correcting the test-only Select harness, the run reported
`5 failed, 4 passed`. The five new cases could not find `hook-prod` or the
resource unavailable, field unavailable, empty-field, and load-failed states,
proving the existing dialog had none of the requested credential data flow.
The later copy-contract correction produced `1 failed, 8 passed` until the
empty-field key was aligned to `managed.triggers.credentialFieldEmpty`.

## GREEN Evidence

Individual focused cycles:

- Hook query: `2 passed`.
- Service credential selector: `2 passed`.
- Trigger dialog: `9 passed`.

Final exact command from the Task 5 brief:

```bash
cd frontend
bun run test -- \
  hooks/managed/use-service-credentials.test.tsx \
  components/managed/shared/service-credential-select.test.tsx \
  components/managed/triggers/create-trigger-dialog.test.tsx
```

Result: `3 passed` test files and `13 passed` tests with no failures or warnings.

## Requirement Mapping

1. `serviceCredentialsQueryKey` scopes the query by managed scope, while
   `fetchAllServiceCredentials` requests only `/secrets?limit=100&kind=generic`,
   follows `after_id`, parses resource IDs and `keys`, and rejects missing or
   repeated pagination cursors.
2. `useServiceCredentials` respects both its `enabled` option and managed scope,
   and uses the required 30-second stale time.
3. `ServiceCredentialSelect` uses each Generic Secret resource `name` as its
   option and callback value, reports metadata key counts, and keeps a missing
   historical resource visibly selectable with the unavailable label.
4. The Trigger dialog enables the query only while an open Webhook form is
   active, derives fields exclusively from `Secret.keys`, and never requests or
   reads `secret_data`.
5. Resource changes explicitly choose `WEBHOOK_SECRET`, then the first metadata
   key, then an empty value. Query arrival has no state-repair effect, so missing
   historical resources and fields remain visible and invalid until interaction.
6. Webhook submission now sends `secret_ref` as the selected Secret resource
   name and `secret_key` as the selected metadata key. Field options are drawn
   only from the selected credential's `keys`.
7. Save remains gated by the existing common, authentication-method, and filter
   rules, plus query loading/error state, selected-resource existence, non-empty
   field selection, and membership of that field in `Secret.keys`.
8. Explicit inline states cover query failure, unavailable historical resource,
   no metadata fields, and unavailable historical field. Existing cron and
   manual edit behavior remains covered by the focused dialog suite.
9. Existing local shadcn Select primitives were composed directly; no registry
   installation, primitive overwrite, unrelated refactor, or locale edit was made.

## Commit

`4f34274b2d9d697b68e2a98091109ea692e0b2b6`

## Concerns

None.

## Fix Round 1

### Status

COMPLETE

### Finding Dispositions

1. **Select test harness quality: CLOSED.** The selector test now uses a
   component-scoped accessible listbox double instead of a shared callback and
   button with an incomplete `option` role. Options expose `aria-selected` and
   `aria-disabled`, the labelled trigger composes the current value or
   placeholder, and disabled interaction cannot invoke `onValueChange`.
   Assertions cover the trigger `aria-label`, selected-value composition,
   resource-name wire values, selected state, disabled state, and blocked
   disabled interaction.
2. **Managed-scope and explicit-enabled query gating: CLOSED.** The hook test
   imports the real request-scope helpers and controls only
   `useManagedRequestScope`. Separate cases prove that a missing organization,
   a missing project, and `enabled: false` all leave the query idle and make no
   `managedGet` request.
3. **Trigger/service-credential locale strings: PARKED FOR TASK 7.** No locale
   catalog was edited. `task-7-brief.md` explicitly owns the
   `managed.triggers.serviceCredential*` and
   `managed.triggers.credentialField*` terminology and locale entries, so this
   is a planned Task 7 dependency rather than an open Task 5 defect.

### RED Evidence

Command run from `frontend/` after adding the new selector assertions but
before replacing the test harness:

```bash
bun run test -- components/managed/shared/service-credential-select.test.tsx
```

Result: `2 failed, 1 passed`. The existing double did not render the selected
value in the trigger and did not expose disabled option state, matching the
review findings.

### Validation

Exact Task 5 focused suite, run from `frontend/`:

```bash
bun run test -- \
  hooks/managed/use-service-credentials.test.tsx \
  components/managed/shared/service-credential-select.test.tsx \
  components/managed/triggers/create-trigger-dialog.test.tsx
```

Result: `3 passed` test files and `18 passed` tests with no warnings.

Frontend type-check:

```bash
bun run type-check
```

Result: PASS (`tsc --noEmit`, exit 0).

Additional scope checks:

```bash
git diff --check
git diff --name-only
```

Result: clean whitespace validation; only the two Task 5 test files changed
before the report update. Production files and locale catalogs were unchanged.

### Files and Revisions

- Selector harness and behavior coverage:
  `frontend/components/managed/shared/service-credential-select.test.tsx`
- Query gating coverage: `frontend/hooks/managed/use-service-credentials.test.tsx`
- Task 5 report: `.superpowers/sdd/2026-08-07-credential-domain-normalization-phase-1/task-5-report.md`
- Fix Round 1 code/test head SHA:
  `b4c6088866aa094af7b1aa23d3f7484c4ced5485`
- Fix Round 1 commit: `b4c6088866aa094af7b1aa23d3f7484c4ced5485`
  (`test(task-5): strengthen credential selector coverage`)
- Original Task 5 commits:
  `4f34274b2d9d697b68e2a98091109ea692e0b2b6` and
  `37f861f902dccf9e892d991b491c0c8d348efe93`
- This report update is committed separately after the test-quality fix.

### Concerns

None. Task 7 remains responsible for the parked locale terminology dependency.

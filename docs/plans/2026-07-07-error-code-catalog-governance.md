# Error-Code Catalog & Governance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Promote the JoySafeter error-code vocabulary from ~478 ungoverned magic strings into a single authoritative catalog, enforced by CI on both backend and frontend, so emitted codes and consumed codes can never drift apart again.

**Architecture:** The transport layer is already unified (`AppError` hierarchy in `app_errors.py`, central handlers in `exceptions.py` deriving HTTP status from type, `to_payload()`/`to_stream_event()` as the sole envelope builders). This plan adds ONE layer *above* that: a backend `error_catalog` registry that is the single source of truth for the valid code set and each code's semantics; a generated frontend mirror of that code set; and CI guards that assert `{emitted codes} ⊆ catalog` and `{frontend-dispatched codes} ⊆ catalog`. We do **not** rewrite the 478 `raise` sites — they keep passing `code="..."` strings; the catalog is the *authority* and CI is the *enforcement*. Later phases converge the stream/boundary paths onto the same catalog and semantic classes.

**Tech Stack:** Python 3.13, FastAPI, dataclasses, `ast` for static scanning, pytest (backend gate via `backend/.venv/bin/`); TypeScript, Next.js, vitest, eslint, tsc (frontend gate via `bun run`).

## Global Constraints

- Backend gate commands (run from repo root): `backend/.venv/bin/ruff check .` · `backend/.venv/bin/ruff format --check .` · `backend/.venv/bin/mypy app --ignore-missing-imports` (run with cwd `backend/`) · `backend/.venv/bin/pytest tests/<file> -q`. **pre-commit is NOT installed as a git hook — you own running the gates.** **mypy is CI-only** (`.github/workflows/ci.yml`: `uv run mypy app --ignore-missing-imports`); the pre-diff `mypy app` baseline is clean, so any mypy error is a regression you introduced — fix it for real, never `# type: ignore`.
- Frontend gate commands (run with cwd `frontend/`): `bun run lint` · `bun run type-check` · `bun run test`.
- No new heavyweight tooling. Frontend "codegen" = a plain Python emitter + a CI `git diff --exit-code` check. Do NOT introduce openapi/orval/swagger.
- Do NOT modify: the central handler stack (`exceptions.py`), the `app_errors.py` semantic hierarchy, `trace_id` injection, the SSE `event: error` concept, or the existing `test_*_error_contract.py` suite (it pins the envelope and must stay green).
- Every commit must leave `ruff`, `mypy`, and the touched test files green simultaneously (ruff `check .` is whole-tree).
- Chinese default messages are the norm in this codebase (`app_errors.py` defaults are Chinese) — keep catalog `default_message` values consistent with existing site messages; do not translate.
- All new code is typed; catalog entries are immutable (`frozen=True`).

---

## File Structure

- `backend/app/joysafeter_shared/common/error_catalog.py` — **NEW**. The authoritative registry: `CatalogEntry` dataclass + `CATALOG: dict[str, CatalogEntry]` + accessors (`is_registered`, `entry_for`, `all_codes`). Hand-owned; seeded once by the generator, reviewed, then maintained by hand.
- `backend/scripts/gen_error_catalog.py` — **NEW**. One-shot + re-runnable seeding/audit tool. Statically scans the codebase for emitted codes (explicit `code="..."` literals AND semantic-class default codes) and prints a diff against the catalog. Used to seed Phase 1 and, in Phase 2, to power the backend guard.
- `backend/tests/test_error_code_catalog_guard.py` — **NEW**. Backend CI guard: asserts every emitted code ∈ `CATALOG`, and (soft) that every catalog code is either emitted or explicitly allow-listed.
- `frontend/lib/managed/error-codes.generated.ts` — **NEW, generated**. A `const`/union mirror of the catalog code set, emitted from the backend catalog. Checked in; regenerated + `git diff --exit-code` in CI.
- `backend/scripts/gen_frontend_error_codes.py` — **NEW**. Emits `error-codes.generated.ts` from `CATALOG`.
- `frontend/lib/managed/errors.ts` — **MODIFY**. Import dispatch codes from the generated mirror instead of inline string literals; keep `parseApiError` as-is.
- `frontend/tests/error-codes-guard.test.ts` — **NEW**. Frontend guard: asserts every code `errors.ts` dispatches on ∈ the generated mirror.
- `backend/app/joysafeter_shared/common/stream_errors.py` — **MODIFY** (Phase 5). Route `async_error_payload`/`stream_error_event` through catalog lookup → semantic subclass.
- `backend/app/joysafeter_shared/common/async_boundaries.py` — **MODIFY** (Phase 5). Let callers pass a semantic class; `ServiceUnavailableError` becomes the fallback default, not the hardcoded verdict.

---

## Phase 0 — Green baseline

### Task 0: Record the pre-change green baseline

**Files:** none (verification only)

- [ ] **Step 1: Run backend gates and record output**

Run (cwd = repo root):
```bash
backend/.venv/bin/ruff check . && backend/.venv/bin/ruff format --check .
(cd backend && .venv/bin/mypy app --ignore-missing-imports)
```
Expected: ruff clean; `mypy app` clean (`Success: no issues found`). If anything is red BEFORE your changes, stop and report — it is not your regression to silently absorb, but you must know the baseline.

- [ ] **Step 2: Run the existing error-architecture test to confirm the current contract is green**

Run (cwd = repo root):
```bash
backend/.venv/bin/pytest tests/test_api_error_architecture.py -q
```
Expected: PASS.

- [ ] **Step 3: Run frontend gates**

Run (cwd = `frontend/`):
```bash
bun run type-check && bun run test && bun run lint
```
Expected: all PASS. Record any pre-existing failures verbatim so later phases are judged against this baseline, not zero.

---

## Phase 1 — Backend catalog (the source of truth)

### Task 1.1: Define the `CatalogEntry` type and empty registry

**Files:**
- Create: `backend/app/joysafeter_shared/common/error_catalog.py`
- Test: `backend/tests/test_error_code_catalog_guard.py`

**Interfaces:**
- Produces:
  - `CatalogEntry` — frozen dataclass: `code: str`, `error_class: type[AppError]`, `default_message: str`, `retryable: bool = False`, `user_action: str | None = None`, `data_fields: tuple[str, ...] = ()`.
  - `CATALOG: dict[str, CatalogEntry]`
  - `is_registered(code: str) -> bool`
  - `entry_for(code: str) -> CatalogEntry | None`
  - `all_codes() -> frozenset[str]`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_error_code_catalog_guard.py
from app.joysafeter_shared.common.error_catalog import (
    CATALOG,
    CatalogEntry,
    all_codes,
    entry_for,
    is_registered,
)


def test_catalog_is_wellformed_registry():
    assert isinstance(CATALOG, dict)
    assert CATALOG, "catalog must not be empty"
    for code, entry in CATALOG.items():
        assert isinstance(entry, CatalogEntry)
        assert entry.code == code, f"key {code!r} != entry.code {entry.code!r}"
        assert entry.default_message, f"{code} missing default_message"


def test_catalog_accessors():
    sample = next(iter(CATALOG))
    assert is_registered(sample) is True
    assert is_registered("____DEFINITELY_NOT_A_CODE____") is False
    assert entry_for(sample) is CATALOG[sample]
    assert entry_for("____NOPE____") is None
    assert sample in all_codes()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `backend/.venv/bin/pytest tests/test_error_code_catalog_guard.py -q`
Expected: FAIL with `ModuleNotFoundError: ...error_catalog`.

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/joysafeter_shared/common/error_catalog.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Type

from app.joysafeter_shared.common.app_errors import AppError


@dataclass(frozen=True, slots=True)
class CatalogEntry:
    code: str
    error_class: Type[AppError]
    default_message: str
    retryable: bool = False
    user_action: str | None = None
    data_fields: tuple[str, ...] = field(default=())


# Populated in Task 1.2 by the seeding generator, then hand-maintained.
CATALOG: dict[str, CatalogEntry] = {}


def is_registered(code: str) -> bool:
    return code in CATALOG


def entry_for(code: str) -> CatalogEntry | None:
    return CATALOG.get(code)


def all_codes() -> frozenset[str]:
    return frozenset(CATALOG)
```

- [ ] **Step 4: Run test — it will still fail on `test_catalog_is_wellformed_registry` (empty CATALOG)**

Run: `backend/.venv/bin/pytest tests/test_error_code_catalog_guard.py::test_catalog_accessors -q`
Expected: PASS. `test_catalog_is_wellformed_registry` is expected to FAIL until Task 1.2 seeds the catalog — that is intentional (it is the red that Task 1.2 turns green).

- [ ] **Step 5: Commit**

```bash
git add backend/app/joysafeter_shared/common/error_catalog.py backend/tests/test_error_code_catalog_guard.py
git commit -m "feat(errors): add empty CatalogEntry registry scaffold"
```

### Task 1.2: Seed the catalog from the live codebase

**Files:**
- Create: `backend/scripts/gen_error_catalog.py`
- Modify: `backend/app/joysafeter_shared/common/error_catalog.py` (populate `CATALOG`)

**Interfaces:**
- Consumes: `CATALOG`, `CatalogEntry` from Task 1.1.
- Produces: a populated `CATALOG` covering every emitted code; `python backend/scripts/gen_error_catalog.py --audit` exits non-zero on drift (used by Task 2.1).

The generator infers, for each code, the semantic class it is constructed with (by finding `XxxError(... code="CODE" ...)` in the AST) and the default message (the first string literal message argument), and also harvests **class-default codes** (the `code=` default in each `__init__` in `app_errors.py`, e.g. `NotFoundError`→`NOT_FOUND`, `AccessDeniedError`→`FORBIDDEN`, `AuthenticationError`→`UNAUTHORIZED`) which never appear as call-site literals.

- [ ] **Step 1: Write the generator**

```python
# backend/scripts/gen_error_catalog.py
from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1] / "app"
APP_ERRORS = APP_ROOT / "joysafeter_shared" / "common" / "app_errors.py"

# Semantic classes whose constructor takes `code=` and carries a default source.
SEMANTIC_CLASSES = {
    "NotFoundError", "InvalidRequestError", "AuthenticationError", "AccessDeniedError",
    "ResourceConflictError", "RateLimitExceededError", "InternalServiceError",
    "ServiceUnavailableError", "ClientClosedError", "RequestValidationAppError",
    "ModelConfigError", "AppError",
}


def _string_value(node: ast.AST) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def scan_call_site_codes(root: Path) -> dict[str, tuple[str, str]]:
    """code -> (error_class, default_message) inferred from `XxxError(code="...", "msg")` calls."""
    found: dict[str, tuple[str, str]] = {}
    for path in root.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for call in ast.walk(tree):
            if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Name):
                continue
            cls = call.func.id
            if cls not in SEMANTIC_CLASSES:
                continue
            code = None
            for kw in call.keywords:
                if kw.arg == "code":
                    code = _string_value(kw.value)
            if code is None:
                continue
            msg = ""
            if call.args:
                msg = _string_value(call.args[0]) or ""
            for kw in call.keywords:
                if kw.arg == "message":
                    msg = _string_value(kw.value) or msg
            found.setdefault(code, (cls, msg))
    return found


def scan_class_default_codes(app_errors: Path) -> dict[str, tuple[str, str]]:
    """code -> (error_class, default_message) from each subclass __init__ default `code=`."""
    tree = ast.parse(app_errors.read_text(encoding="utf-8"))
    found: dict[str, tuple[str, str]] = {}
    for cls in tree.body:
        if not isinstance(cls, ast.ClassDef):
            continue
        init = next((n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "__init__"), None)
        if init is None:
            continue
        args = init.args
        defaults_by_name: dict[str, ast.AST] = {}
        # message: first positional arg default
        pos = args.args[1:]  # skip self
        for name, default in zip([a.arg for a in pos][-len(args.defaults):], args.defaults):
            defaults_by_name[name] = default
        for name, default in zip([a.arg for a in args.kwonlyargs], args.kw_defaults):
            if default is not None:
                defaults_by_name[name] = default
        code = _string_value(defaults_by_name.get("code")) if "code" in defaults_by_name else None
        msg = _string_value(defaults_by_name.get("message")) if "message" in defaults_by_name else ""
        if code:
            found.setdefault(code, (cls.name, msg or ""))
    return found


def collect() -> dict[str, tuple[str, str]]:
    merged = scan_class_default_codes(APP_ERRORS)
    for code, meta in scan_call_site_codes(APP_ROOT).items():
        merged.setdefault(code, meta)
    return dict(sorted(merged.items()))


def render_catalog(entries: dict[str, tuple[str, str]]) -> str:
    lines = [
        "    "
        f'"{code}": CatalogEntry(code="{code}", error_class={cls}, '
        f'default_message={msg!r}),'
        for code, (cls, msg) in entries.items()
    ]
    return "CATALOG: dict[str, CatalogEntry] = {\n" + "\n".join(lines) + "\n}\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--audit", action="store_true", help="exit 1 if emitted codes not in catalog")
    ap.add_argument("--emit", action="store_true", help="print the CATALOG literal for pasting")
    args = ap.parse_args()
    entries = collect()
    if args.emit:
        print(render_catalog(entries))
        return 0
    if args.audit:
        from app.joysafeter_shared.common.error_catalog import all_codes  # noqa: PLC0415

        missing = sorted(set(entries) - all_codes())
        if missing:
            print("Emitted codes missing from CATALOG:", *missing, sep="\n  ")
            return 1
        print(f"OK: all {len(entries)} emitted codes are registered.")
        return 0
    print(f"{len(entries)} emitted codes discovered.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Generate the catalog body**

Run (cwd = `backend/`):
```bash
.venv/bin/python scripts/gen_error_catalog.py --emit > /tmp/catalog_body.py
wc -l /tmp/catalog_body.py   # expect ~490+ entry lines
```
Expected: a `CATALOG = { ... }` literal with one `CatalogEntry(...)` per discovered code.

- [ ] **Step 3: Paste the generated body into `error_catalog.py`**

Replace the empty `CATALOG: dict[str, CatalogEntry] = {}` line with the generated literal from `/tmp/catalog_body.py`. Add the required imports at the top of `error_catalog.py`:

```python
from app.joysafeter_shared.common.app_errors import (
    AccessDeniedError,
    AppError,
    AuthenticationError,
    ClientClosedError,
    InternalServiceError,
    InvalidRequestError,
    ModelConfigError,
    NotFoundError,
    RateLimitExceededError,
    RequestValidationAppError,
    ResourceConflictError,
    ServiceUnavailableError,
)
```

- [ ] **Step 4: Run tests + gates**

Run (cwd = repo root):
```bash
backend/.venv/bin/pytest tests/test_error_code_catalog_guard.py -q
backend/.venv/bin/ruff check backend/app/joysafeter_shared/common/error_catalog.py
backend/.venv/bin/ruff format backend/app/joysafeter_shared/common/error_catalog.py
(cd backend && .venv/bin/mypy app --ignore-missing-imports)
```
Expected: both catalog tests PASS; ruff clean; mypy clean.

- [ ] **Step 5: Commit**

```bash
git add backend/scripts/gen_error_catalog.py backend/app/joysafeter_shared/common/error_catalog.py
git commit -m "feat(errors): seed error-code catalog from live codebase"
```

---

## Phase 2 — CI guard (drift prevention — highest ROI)

### Task 2.1: Backend guard — emitted codes ⊆ catalog

**Files:**
- Modify: `backend/tests/test_error_code_catalog_guard.py`

**Interfaces:**
- Consumes: `collect()` from `backend/scripts/gen_error_catalog.py`; `all_codes()` from `error_catalog.py`.

- [ ] **Step 1: Write the failing test**

```python
# append to backend/tests/test_error_code_catalog_guard.py
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from gen_error_catalog import collect  # noqa: E402


def test_every_emitted_code_is_registered():
    emitted = set(collect())
    missing = sorted(emitted - all_codes())
    assert not missing, (
        "These codes are raised in the backend but absent from CATALOG "
        f"(add them to error_catalog.py): {missing}"
    )
```

- [ ] **Step 2: Run — expect PASS (catalog was seeded from the same collector)**

Run: `backend/.venv/bin/pytest tests/test_error_code_catalog_guard.py::test_every_emitted_code_is_registered -q`
Expected: PASS. To prove the guard BITES, temporarily add `raise NotFoundError("x", code="__PROVE_GUARD__")` to any `app/joysafeter_api/api/v1/health.py` handler, re-run → FAIL listing `__PROVE_GUARD__`, then revert.

- [ ] **Step 3: Wire the guard into CI**

Modify `.github/workflows/ci.yml` backend job to add, after the mypy step:
```yaml
      - name: Error-code catalog guard
        working-directory: backend
        run: uv run pytest tests/test_error_code_catalog_guard.py -q
```

- [ ] **Step 4: Commit**

```bash
git add backend/tests/test_error_code_catalog_guard.py .github/workflows/ci.yml
git commit -m "test(errors): CI guard that emitted codes are catalog-registered"
```

---

## Phase 3 — Resolve the observed synonym drift

Concrete drift confirmed by census: the frontend dispatches on `WRITE_ACCESS_DENIED` and `RESOURCE_ARCHIVED`, but the backend emits `JOYSAFETER_WRITE_REQUIRED` and (per-resource) `*_ARCHIVED` codes; `UNAUTHORIZED` and `JOYSAFETER_UNAUTHORIZED` are dual. Pick ONE canonical code per semantic, alias the rest in the catalog, and delete dead frontend branches.

### Task 3.1: Canonicalize the write-permission code

**Files:**
- Modify: `backend/app/joysafeter_shared/common/error_catalog.py` (add `aliases`)
- Modify: `frontend/lib/managed/errors.ts:80`

- [ ] **Step 1: Add an `aliases` field to `CatalogEntry` (failing test first)**

Append to `test_error_code_catalog_guard.py`:
```python
def test_aliases_are_registered_and_point_to_canonical():
    from app.joysafeter_shared.common.error_catalog import canonical_code
    # JOYSAFETER_WRITE_REQUIRED is canonical; WRITE_ACCESS_DENIED is its alias.
    assert canonical_code("WRITE_ACCESS_DENIED") == "JOYSAFETER_WRITE_REQUIRED"
    assert canonical_code("JOYSAFETER_WRITE_REQUIRED") == "JOYSAFETER_WRITE_REQUIRED"
    assert canonical_code("SOME_UNKNOWN") == "SOME_UNKNOWN"
```

- [ ] **Step 2: Run — FAIL (`canonical_code` undefined)**

Run: `backend/.venv/bin/pytest tests/test_error_code_catalog_guard.py::test_aliases_are_registered_and_point_to_canonical -q`
Expected: FAIL with `ImportError` / `cannot import name 'canonical_code'`.

- [ ] **Step 3: Implement aliases in `error_catalog.py`**

Add below `CATALOG`:
```python
# alias code -> canonical code. Frontend should dispatch only on canonical codes.
ALIASES: dict[str, str] = {
    "WRITE_ACCESS_DENIED": "JOYSAFETER_WRITE_REQUIRED",
    "UNAUTHORIZED": "JOYSAFETER_UNAUTHORIZED",
}


def canonical_code(code: str) -> str:
    return ALIASES.get(code, code)
```

- [ ] **Step 4: Update the frontend to dispatch on the canonical code only**

In `frontend/lib/managed/errors.ts`, change the write-required branch (currently line ~80):
```ts
  // before:
  if (code === 'JOYSAFETER_WRITE_REQUIRED' || code === 'WRITE_ACCESS_DENIED') {
  // after:
  if (code === 'JOYSAFETER_WRITE_REQUIRED') {
```
Leave the `JOYSAFETER_UNAUTHORIZED || UNAUTHORIZED` branch for Task 3.2.

- [ ] **Step 5: Run gates**

Run:
```bash
backend/.venv/bin/pytest tests/test_error_code_catalog_guard.py -q
(cd frontend && bun run type-check && bun run test)
```
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/joysafeter_shared/common/error_catalog.py backend/tests/test_error_code_catalog_guard.py frontend/lib/managed/errors.ts
git commit -m "refactor(errors): canonicalize WRITE_ACCESS_DENIED -> JOYSAFETER_WRITE_REQUIRED"
```

### Task 3.2: Canonicalize the unauthorized code and delete the dead `RESOURCE_ARCHIVED` branch

**Files:**
- Modify: `frontend/lib/managed/errors.ts:89,101`
- Modify: `backend/tests/test_error_code_catalog_guard.py`

- [ ] **Step 1: Investigate `RESOURCE_ARCHIVED` — is it emitted anywhere?**

Run (cwd = repo root):
```bash
grep -rn "RESOURCE_ARCHIVED" backend/app/ frontend/lib/
```
Expected: hits only in `frontend/lib/managed/errors.ts` (dead branch) OR also a backend emit site. If backend emits it, keep the branch and instead add `RESOURCE_ARCHIVED` to the catalog (it will already be caught by the Task 2.1 guard). If it is frontend-only, it is dead — proceed to delete in Step 2.

- [ ] **Step 2: Apply the edits**

In `frontend/lib/managed/errors.ts`:
```ts
  // unauthorized branch — dispatch on canonical only:
  if (code === 'JOYSAFETER_UNAUTHORIZED') {
    return t('managed.errors.unauthorized')
  }
```
If Step 1 proved `RESOURCE_ARCHIVED` is frontend-dead, delete these two lines:
```ts
  if (code === 'RESOURCE_ARCHIVED') {
    return t('managed.errors.resourceArchived')
  }
```

- [ ] **Step 3: Run frontend gates**

Run (cwd = `frontend/`): `bun run type-check && bun run test && bun run lint`
Expected: PASS. (`eslint` will flag the now-unused `managed.errors.resourceArchived` key only if a no-unused-i18n rule exists; if lint fails on the removed key, also remove it from `frontend/lib/i18n/locales/en.ts` and `zh.ts`.)

- [ ] **Step 4: Commit**

```bash
git add frontend/lib/managed/errors.ts frontend/lib/i18n/locales/en.ts frontend/lib/i18n/locales/zh.ts
git commit -m "refactor(errors): canonicalize UNAUTHORIZED dispatch, drop dead RESOURCE_ARCHIVED"
```

---

## Phase 4 — Generated frontend mirror + frontend guard

### Task 4.1: Emit the frontend code mirror from the catalog

**Files:**
- Create: `backend/scripts/gen_frontend_error_codes.py`
- Create: `frontend/lib/managed/error-codes.generated.ts`

**Interfaces:**
- Consumes: `CATALOG`, `ALIASES` from `error_catalog.py`.
- Produces: `error-codes.generated.ts` exporting `KNOWN_ERROR_CODES` (readonly string array) + `ManagedErrorCode` (union type).

- [ ] **Step 1: Write the emitter**

```python
# backend/scripts/gen_frontend_error_codes.py
from __future__ import annotations

from pathlib import Path

from app.joysafeter_shared.common.error_catalog import ALIASES, all_codes

OUT = Path(__file__).resolve().parents[2] / "frontend" / "lib" / "managed" / "error-codes.generated.ts"

HEADER = "// AUTO-GENERATED by backend/scripts/gen_frontend_error_codes.py — do not edit by hand.\n"


def render() -> str:
    codes = sorted(all_codes() | set(ALIASES))
    body = ",\n".join(f"  '{c}'" for c in codes)
    union = " | ".join(f"'{c}'" for c in codes) or "never"
    return (
        HEADER
        + "\nexport const KNOWN_ERROR_CODES = [\n"
        + body
        + "\n] as const\n\n"
        + f"export type ManagedErrorCode = {union}\n"
    )


def main() -> None:
    OUT.write_text(render(), encoding="utf-8")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Generate the file**

Run (cwd = `backend/`):
```bash
.venv/bin/python scripts/gen_frontend_error_codes.py
```
Expected: `wrote .../frontend/lib/managed/error-codes.generated.ts`; the file contains `KNOWN_ERROR_CODES` and `ManagedErrorCode`.

- [ ] **Step 3: Format + typecheck the generated file**

Run (cwd = `frontend/`): `bunx prettier --write lib/managed/error-codes.generated.ts && bun run type-check`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add backend/scripts/gen_frontend_error_codes.py frontend/lib/managed/error-codes.generated.ts
git commit -m "feat(errors): generate frontend error-code mirror from catalog"
```

### Task 4.2: Frontend guard — dispatched codes ⊆ generated mirror

**Files:**
- Create: `frontend/tests/error-codes-guard.test.ts`
- Modify: `frontend/lib/managed/errors.ts` (export the dispatched set)

**Interfaces:**
- Consumes: `KNOWN_ERROR_CODES` from `error-codes.generated.ts`.
- Produces: `DISPATCHED_ERROR_CODES` exported from `errors.ts`.

- [ ] **Step 1: Export the dispatched code set from `errors.ts`**

Add near the top of `frontend/lib/managed/errors.ts`:
```ts
// Codes that getOperationErrorMessage / shouldRetry branch on. Keep in sync with the branches below.
export const DISPATCHED_ERROR_CODES = [
  'SKILL_SECURITY_SCAN_REJECTED',
  'SKILL_SECURITY_SCAN_FAILED',
  'JOYSAFETER_WRITE_REQUIRED',
  'JOYSAFETER_ADMIN_REQUIRED',
  'NOT_ORG_MEMBER',
  'JOYSAFETER_UNAUTHORIZED',
  'MEMBERSHIP_EXPIRED',
  'PROJECT_ACCESS_DENIED',
  'PROJECT_ARCHIVED',
  'FORBIDDEN',
  'NOT_FOUND',
] as const
```
(Reflect the actual branches after Phase 3 edits; drop any you removed.)

- [ ] **Step 2: Write the failing guard test**

```ts
// frontend/tests/error-codes-guard.test.ts
import { describe, expect, it } from 'vitest'
import { KNOWN_ERROR_CODES } from '@/lib/managed/error-codes.generated'
import { DISPATCHED_ERROR_CODES } from '@/lib/managed/errors'

describe('frontend error-code governance', () => {
  it('every dispatched code exists in the backend-generated catalog', () => {
    const known = new Set<string>(KNOWN_ERROR_CODES)
    const unknown = DISPATCHED_ERROR_CODES.filter((c) => !known.has(c))
    expect(unknown).toEqual([])
  })
})
```

- [ ] **Step 2b: Run — investigate any failures**

Run (cwd = `frontend/`): `bun run test error-codes-guard`
Expected: PASS. If a dispatched code is reported unknown, it means the backend never registers it (dead frontend branch) OR the code is a class-default not captured — add it to the catalog seed (Task 1.2 collector already harvests class defaults, so re-run `gen_frontend_error_codes.py`). Suffix codes like `*_NOT_FOUND` handled by `code.endsWith('_NOT_FOUND')` are a PATTERN, not a literal — exclude the `endsWith` branch from `DISPATCHED_ERROR_CODES` (it is not a single code).

- [ ] **Step 3: Wire into CI (regen + diff + test)**

Modify `.github/workflows/ci.yml` frontend job, before `bun run test`:
```yaml
      - name: Regenerate error-code mirror and check for drift
        run: |
          (cd backend && uv run python scripts/gen_frontend_error_codes.py)
          (cd frontend && bunx prettier --write lib/managed/error-codes.generated.ts)
          git diff --exit-code frontend/lib/managed/error-codes.generated.ts
```
This fails CI if the catalog changed but the committed mirror was not regenerated.

- [ ] **Step 4: Commit**

```bash
git add frontend/tests/error-codes-guard.test.ts frontend/lib/managed/errors.ts .github/workflows/ci.yml
git commit -m "test(errors): CI guard that frontend-dispatched codes exist in catalog"
```

---

## Phase 5 — Converge stream & boundary paths onto catalog semantics

### Task 5.1: Route the stream builders through catalog lookup

**Files:**
- Modify: `backend/app/joysafeter_shared/common/stream_errors.py:51-93`
- Test: `backend/tests/test_openai_stream_error_contract.py` (existing — extend, don't rewrite)

**Interfaces:**
- Consumes: `entry_for` from `error_catalog.py`.
- Produces: `async_error_payload`/`stream_error_event` construct the catalog-registered semantic subclass when `code` is known, falling back to bare `AppError` only for unregistered codes.

- [ ] **Step 1: Write the failing test**

```python
# append to backend/tests/test_openai_stream_error_contract.py
from app.joysafeter_shared.common.stream_errors import async_error_payload


def test_async_error_payload_uses_catalog_semantic_class():
    # SESSION_NOT_FOUND is registered as a NotFoundError in the catalog.
    payload = async_error_payload(code="SESSION_NOT_FOUND", message="x")
    assert payload["type"] == "error"
    assert payload["code"] == "SESSION_NOT_FOUND"
    # source is derived from the semantic class default (DomainError -> "api"),
    # not the generic "internal" the old bare-AppError path produced.
    assert payload["source"] == "api"
```

- [ ] **Step 2: Run — FAIL (source == 'internal')**

Run: `backend/.venv/bin/pytest tests/test_openai_stream_error_contract.py::test_async_error_payload_uses_catalog_semantic_class -q`
Expected: FAIL, `assert 'internal' == 'api'`.

- [ ] **Step 3: Implement catalog-aware construction**

In `stream_errors.py`, replace the body of `async_error_payload` and `stream_error_event`'s `AppError(...)` construction with a helper:
```python
from app.joysafeter_shared.common.error_catalog import entry_for


def _build_error(
    *, code: str, message: str, data, source, retryable, user_action, detail
) -> AppError:
    entry = entry_for(code)
    if entry is not None:
        return entry.error_class(
            message,
            code=code,
            data=data,
            retryable=retryable,
            user_action=user_action,
            detail=detail,
        )
    return AppError(
        code=code, message=message, data=data, source=source,
        retryable=retryable, user_action=user_action, detail=detail,
    )
```
Then `async_error_payload` returns `_build_error(...).to_stream_event(status=status)`, and `stream_error_event` wraps the same in `f"event: error\ndata: {json.dumps(payload)}\n\n"`. Keep signatures unchanged so the 117 call sites are untouched.

Note: `ModelConfigError` has a different `__init__` signature (`code` positional). Guard `_build_error` with `if entry.error_class is ModelConfigError: return entry.error_class(code, message, ...)`.

- [ ] **Step 4: Run tests + gates**

Run:
```bash
backend/.venv/bin/pytest tests/test_openai_stream_error_contract.py tests/test_task_stream_error_contract.py -q
(cd backend && .venv/bin/mypy app --ignore-missing-imports)
```
Expected: PASS; mypy clean. If any existing stream contract test asserts `source == "internal"` for a now-registered code, update that assertion to the semantic source (the new behavior is correct).

- [ ] **Step 5: Commit**

```bash
git add backend/app/joysafeter_shared/common/stream_errors.py backend/tests/test_openai_stream_error_contract.py
git commit -m "refactor(errors): stream builders use catalog semantic class not bare AppError"
```

### Task 5.2: Let async boundaries carry a real semantic class

**Files:**
- Modify: `backend/app/joysafeter_shared/common/async_boundaries.py`
- Test: `backend/tests/test_async_boundary_failure_contract.py` (existing — extend)

**Interfaces:**
- Consumes: `AppError`, `ServiceUnavailableError` from `app_errors.py`.
- Produces: `async_boundary_error_payload(..., error_class: type[AppError] = ServiceUnavailableError)` — new optional keyword; default preserves today's behavior so the 110 call sites keep working unchanged.

- [ ] **Step 1: Write the failing test**

```python
# append to backend/tests/test_async_boundary_failure_contract.py
from app.joysafeter_shared.common.app_errors import NotFoundError
from app.joysafeter_shared.common.async_boundaries import async_boundary_error_payload


def test_boundary_payload_honors_explicit_error_class():
    payload = async_boundary_error_payload(
        code="TASK_AGENT_NOT_FOUND", message="agent gone",
        boundary="worker", operation="dispatch", error_class=NotFoundError,
    )
    assert payload["code"] == "TASK_AGENT_NOT_FOUND"
    assert payload["retryable"] is False  # NotFoundError default, not the 503 retryable=True


def test_boundary_payload_defaults_to_service_unavailable():
    payload = async_boundary_error_payload(
        code="REDIS_DOWN", message="redis", boundary="bus", operation="publish",
    )
    assert payload["retryable"] is True  # unchanged default
```

- [ ] **Step 2: Run — FAIL (`unexpected keyword argument 'error_class'`)**

Run: `backend/.venv/bin/pytest tests/test_async_boundary_failure_contract.py -q -k error_class`
Expected: FAIL, `TypeError: ... unexpected keyword argument 'error_class'`.

- [ ] **Step 3: Implement the optional class parameter**

```python
# async_boundaries.py
from typing import Any, Mapping, Type
from app.joysafeter_shared.common.app_errors import AppError, ServiceUnavailableError


def async_boundary_error_payload(
    *,
    code: str,
    message: str,
    boundary: str,
    operation: str,
    data: Mapping[str, Any] | None = None,
    source: str = "runtime",
    retryable: bool | None = None,
    user_action: str | None = "retry",
    detail: str | None = None,
    error_class: Type[AppError] = ServiceUnavailableError,
) -> dict[str, Any]:
    payload_data: dict[str, Any] = {"boundary": boundary, "operation": operation}
    if data:
        payload_data.update(dict(data))
    kwargs: dict[str, Any] = {
        "message": message, "code": code, "data": payload_data,
        "source": source, "user_action": user_action, "detail": detail,
    }
    if retryable is not None:
        kwargs["retryable"] = retryable
    return error_class(**kwargs).to_stream_event()
```
`retryable=None` means "use the class default" (NotFoundError→False, ServiceUnavailableError→True). Update `boundary_errors.py::_payload` to pass `retryable=None` by default instead of hardcoded `True` if you want boundary logs to inherit class semantics; otherwise leave `boundary_errors.py` unchanged (it explicitly wants retryable=True for infra logs — acceptable).

- [ ] **Step 4: Run tests + gates**

Run:
```bash
backend/.venv/bin/pytest tests/test_async_boundary_failure_contract.py tests/test_audit_async_boundary_contract.py tests/test_oauth_async_boundary_contract.py -q
(cd backend && .venv/bin/mypy app --ignore-missing-imports)
```
Expected: PASS; mypy clean.

- [ ] **Step 5: Commit**

```bash
git add backend/app/joysafeter_shared/common/async_boundaries.py backend/tests/test_async_boundary_failure_contract.py
git commit -m "refactor(errors): async boundaries accept explicit semantic error class"
```

---

## Phase 6 — Final verification

### Task 6: Whole-suite green + guard proof

**Files:** none (verification only)

- [ ] **Step 1: Full backend gate**

Run (cwd = repo root):
```bash
backend/.venv/bin/ruff check . && backend/.venv/bin/ruff format --check .
(cd backend && .venv/bin/mypy app --ignore-missing-imports)
backend/.venv/bin/pytest tests/test_error_code_catalog_guard.py tests/test_api_error_architecture.py tests/test_openai_stream_error_contract.py tests/test_async_boundary_failure_contract.py -q
```
Expected: all PASS / clean.

- [ ] **Step 2: Full frontend gate**

Run (cwd = `frontend/`): `bun run type-check && bun run test && bun run lint`
Expected: all PASS.

- [ ] **Step 3: Prove both guards bite (then revert)**

Backend: add a `raise NotFoundError("x", code="__DRIFT__")` in `health.py`, run the catalog guard → expect FAIL listing `__DRIFT__`, revert.
Frontend: add `'__DRIFT__'` to `DISPATCHED_ERROR_CODES`, run `bun run test error-codes-guard` → expect FAIL, revert.

- [ ] **Step 4: Independent verification**

Dispatch the `verification` subagent with: the original task ("catalog + CI guards + synonym resolution + stream/boundary convergence"), the list of files changed across all phases, and the plan path. Note (per prior env experience) that verification subagents in this repo sometimes have Bash/git denied and return an environmental PARTIAL — if so, reconcile against your own gate re-runs from Steps 1–3.

---

## Self-Review

**Spec coverage:** catalog (Phase 1) · codegen (Phase 4) · CI guards (Phases 2 & 4.2) · synonym resolution (Phase 3) · stream/boundary convergence (Phase 5) — all present, each phase independently shippable.

**Placeholder scan:** none — the 478 catalog entries are produced by the shown generator (`gen_error_catalog.py --emit`), not hand-listed; all novel code (catalog, generator, both guards, both convergence edits) is inlined in full.

**Type consistency:** `CatalogEntry`/`CATALOG`/`is_registered`/`entry_for`/`all_codes` defined in Task 1.1 and consumed unchanged in 1.2, 2.1, 4.1, 5.1; `ALIASES`/`canonical_code` from 3.1 consumed in 4.1; `KNOWN_ERROR_CODES`/`ManagedErrorCode` from 4.1 consumed in 4.2; `DISPATCHED_ERROR_CODES` from 4.2 self-contained. `error_class` keyword from 5.2 matches its test.

**Known risk:** the generator infers `error_class` per code from the FIRST call site it sees; a code raised with two different classes across files will pick one — the catalog is hand-reviewed after seeding (Task 1.2 Step 3) to correct such cases. This is the one place human judgment is required and is called out explicitly rather than hidden.

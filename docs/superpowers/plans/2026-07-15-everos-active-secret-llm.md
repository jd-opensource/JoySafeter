# EverOS Active Secret LLM Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make EverOS resolve its LLM credentials from the current project default JoySafeter secret, with `EVEROS_LLM__*` retained only as fallback.

**Architecture:** Add a project-aware EverOS LLM resolver next to the existing LLM client code. The resolver loads the project default secret through `SecretService`, maps OpenAI-compatible secret keys to `LLMSettings`, caches clients by `(project_id, secret_id, updated_at)`, and falls back to the existing settings-based singleton only when no active secret exists.

**Tech Stack:** Python 3.12, FastAPI services, SQLAlchemy async sessions, Pydantic settings, pytest.

---

### Task 1: Add Project Credential Resolution

**Files:**
- Create: `backend/app/everos/component/llm/project.py`
- Test: `backend/tests/test_everos_project_llm.py`

- [x] **Step 1: Write failing tests**

Add tests that monkeypatch `AsyncSessionLocal`, `SecretService`, and `build_llm_provider` to cover active-secret resolution, active-secret switching, incompatible active secret, and fallback when no active secret exists.

- [x] **Step 2: Run tests and confirm RED**

Run: `cd backend && uv run pytest tests/test_everos_project_llm.py -q`

Expected: fail because `app.everos.component.llm.project` does not exist.

- [x] **Step 3: Implement minimal resolver**

Create `project.py` with:

- `ProjectLLMCredential`
- `IncompatibleProjectLLMSecretError`
- `get_project_llm_client(project_id)`
- `_resolve_project_llm_credential(project_id)`
- cache clear helper for tests

Use `SecretService.get_default_secret(project_id=...)` and `get_secret_data(...)`.

- [x] **Step 4: Run tests and confirm GREEN**

Run: `cd backend && uv run pytest tests/test_everos_project_llm.py -q`

Expected: all tests pass.

### Task 2: Export Resolver and Thread Project ID Through Search

**Files:**
- Modify: `backend/app/everos/component/llm/__init__.py`
- Modify: `backend/app/everos/service/search.py`
- Test: `backend/tests/test_everos_project_llm.py`

- [x] **Step 1: Write failing service-level test**

Add a test that monkeypatches `search.get_project_llm_client`, calls the internal search LLM resolver with a project id, and asserts the project id is passed through.

- [x] **Step 2: Run test and confirm RED**

Run: `cd backend && uv run pytest tests/test_everos_project_llm.py -q`

Expected: fail because search still uses settings/global LLM resolution.

- [x] **Step 3: Implement search wiring**

Export project resolver from `component/llm/__init__.py`. Change `service/search.py` so `_get_llm_client(project_id)` uses `get_project_llm_client(project_id)` when a project id is present, and falls back to existing behavior only without project id.

- [x] **Step 4: Run tests and confirm GREEN**

Run: `cd backend && uv run pytest tests/test_everos_project_llm.py -q`

Expected: all tests pass.

### Task 3: Thread Project ID Through Memorize

**Files:**
- Modify: `backend/app/everos/service/memorize.py`
- Test: `backend/tests/test_everos_project_llm.py`

- [x] **Step 1: Write failing test for memorize helper**

Add a test around a small helper that resolves the LLM for a project id and asserts it uses `get_project_llm_client`.

- [x] **Step 2: Run test and confirm RED**

Run: `cd backend && uv run pytest tests/test_everos_project_llm.py -q`

Expected: fail because memorize calls `get_llm_client()` directly.

- [x] **Step 3: Implement memorize wiring**

Add a small `_get_llm_client(project_id)` helper in `memorize.py` and replace direct calls with it, using request `project_id`.

- [x] **Step 4: Run tests and confirm GREEN**

Run: `cd backend && uv run pytest tests/test_everos_project_llm.py -q`

Expected: all tests pass.

### Task 4: Verification

**Files:**
- No new files.

- [x] **Step 1: Run targeted tests**

Run: `cd backend && uv run pytest tests/test_everos_project_llm.py tests/test_everos_sidecar_imports.py -q`

Expected: all tests pass.

- [x] **Step 2: Inspect changed files**

Run: `git diff -- backend/app/everos/component/llm backend/app/everos/service/search.py backend/app/everos/service/memorize.py backend/tests/test_everos_project_llm.py`

Expected: only scoped EverOS LLM resolver, search/memorize wiring, and tests changed.

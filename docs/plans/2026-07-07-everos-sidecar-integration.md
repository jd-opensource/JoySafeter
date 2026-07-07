# EverOS Sidecar Integration Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Integrate EverOS source under `backend/app/everos`, run it as a dedicated JoySafeter backend service on port `8003`, and make Claude Code, Codex, and Native sandboxes able to reach it.

**Architecture:** EverOS is vendored into the backend package but runs in a separate `everos` service container. It keeps its own Markdown/SQLite/LanceDB data under `/data/everos`, while JoySafeter execution sandboxes receive `EVEROS_BASE_URL=http://everos:8003` and call it over the Docker network.

**Tech Stack:** Python 3.12, FastAPI, uvicorn/gunicorn, Docker Compose, EverOS, LanceDB, SQLite, JoySafeter sandbox runner.

---

## Scope

This plan implements the first integration slice:

- Source integration under `backend/app/everos/`.
- EverOS backend service on port `8003`.
- Docker Compose service and persistent data volume.
- Backend/env templates for EverOS settings.
- Sandbox environment injection for `EVEROS_BASE_URL`.
- Health/smoke verification.

This plan does not implement platform-managed memory extraction, automatic `/memory/add`, `/flush`, `/search` injection, or MCP tools. Those are later phases after the service and sandbox access are proven.

## Pre-Flight

**Step 1: Confirm current branch and dirty state**

Run:

```bash
git status --short
git branch --show-current
```

Expected:

- You are on the intended feature branch.
- There may be unrelated existing changes such as `.agents/`, `.claude-flow/`, `backend/uv.lock`, or `JoySafeter V2/`. Do not modify or revert unrelated user changes.

**Step 2: Confirm EverOS source exists**

Run:

```bash
test -d /Users/sunhuajie.3/Desktop/EverOS/src/everos
test -f /Users/sunhuajie.3/Desktop/EverOS/pyproject.toml
```

Expected: both commands exit `0`.

---

## Task 1: Vendor EverOS Source Into Backend

**Files:**

- Create: `backend/app/everos/`
- Source: `/Users/sunhuajie.3/Desktop/EverOS/src/everos/`

**Step 1: Copy EverOS source**

Run:

```bash
rsync -a --delete /Users/sunhuajie.3/Desktop/EverOS/src/everos/ backend/app/everos/
```

Expected: `backend/app/everos/__init__.py` exists.

**Step 2: Verify required non-Python assets copied**

Run:

```bash
test -f backend/app/everos/config/default.toml
test -f backend/app/everos/config/default_ome.toml
find backend/app/everos/config/prompt_slots -type f | head
```

Expected:

- Both `default.toml` and `default_ome.toml` exist.
- Prompt slot files are listed.

**Step 3: Commit source copy only after import rewrite and smoke test**

Do not commit yet. The copied source still contains `everos.*` imports and cannot run from `app.everos` until Task 2 is complete.

---

## Task 2: Rewrite EverOS Imports For `app.everos`

**Files:**

- Modify: `backend/app/everos/**/*.py`

**Step 1: Rewrite normal imports mechanically**

Run:

```bash
python - <<'PY'
from pathlib import Path

root = Path("backend/app/everos")
for path in root.rglob("*.py"):
    text = path.read_text()
    new = text
    new = new.replace("from everos.", "from app.everos.")
    new = new.replace("import everos.", "import app.everos.")
    new = new.replace("from everos import", "from app.everos import")
    if new != text:
        path.write_text(new)
PY
```

Expected: command exits `0`.

**Step 2: Rewrite string-based imports and uvicorn targets**

Run:

```bash
rg -n "\"everos\\.|'everos\\.|everos\\.entrypoints" backend/app/everos
```

For each result that is a Python import target or uvicorn target, replace it with `app.everos...`.

Expected important replacement:

```python
uvicorn.run(
    "app.everos.entrypoints.api.app:create_app",
    ...
)
```

Do not rewrite user-facing prose unless it affects runtime behavior.

**Step 3: Verify no runtime imports remain**

Run:

```bash
rg -n "from everos|import everos|\"everos\.|'everos\." backend/app/everos
```

Expected:

- No runtime import statements remain.
- Any remaining matches are comments/docs only and should be reviewed.

**Step 4: Verify package imports compile syntactically**

Run:

```bash
cd backend
python -m compileall -q app/everos
```

Expected: command exits `0`.

Do not commit until dependencies are added, because import smoke tests may still fail due missing packages.

---

## Task 3: Add EverOS Dependencies To Backend Packaging

**Files:**

- Modify: `backend/pyproject.toml`
- Modify: `backend/uv.lock`

**Step 1: Add missing dependencies**

Modify `backend/pyproject.toml` and add the EverOS runtime dependencies that JoySafeter does not already include.

Add these to `[project].dependencies`:

```toml
    "lancedb>=0.13.0",
    "aiosqlite>=0.20.0",
    "sqlmodel>=0.0.22",
    "PyYAML>=6.0",
    "watchdog>=4.0.0",
    "structlog>=24.0.0",
    "prometheus-client>=0.20.0",
    "typer>=0.12.0",
    "textual>=8.2.7",
    "jieba==0.42.1",
    "apscheduler>=3.10.4,<4.0",
    "portalocker>=2.8.2",
    "watchfiles>=0.21.0",
    "anyio>=4.0",
    "openai>=1.0.0",
    "everalgo-user-memory==0.3.1",
    "everalgo-agent-memory==0.3.1",
    "everalgo-rank==0.4.1",
    "everalgo-knowledge==0.1.1",
```

Skip dependencies already present at compatible versions, such as `fastapi`,
`uvicorn`, `python-multipart`, `pydantic`, `pydantic-settings`,
`python-dotenv`, `alembic`, and `greenlet`.

**Step 2: Refresh lockfile**

Run:

```bash
cd backend
uv lock
```

Expected: lock resolves successfully.

If network access is blocked, rerun with the approved network/escalation path.

**Step 3: Install/sync local backend environment if needed**

Run:

```bash
cd backend
uv sync --frozen --no-dev
```

Expected: sync succeeds.

**Step 4: Commit dependency changes with copied source later**

Do not commit yet. First add import/app smoke tests.

---

## Task 4: Add EverOS Import And App Factory Smoke Tests

**Files:**

- Create: `backend/tests/test_everos_sidecar_imports.py`

**Step 1: Create failing tests**

Create `backend/tests/test_everos_sidecar_imports.py`:

```python
import importlib


def test_everos_service_modules_import_from_app_namespace():
    modules = [
        "app.everos.service.memorize",
        "app.everos.service.search",
        "app.everos.service.get",
        "app.everos.entrypoints.api.app",
    ]

    for module in modules:
        importlib.import_module(module)


def test_everos_app_factory_uses_expected_metadata_without_lifespan():
    app_module = importlib.import_module("app.everos.entrypoints.api.app")

    app = app_module.create_app(lifespan_providers=[])

    assert app.title == "everos"
    paths = set(app.openapi()["paths"])
    assert "/health" in paths
    assert "/api/v1/memory/add" in paths
    assert "/api/v1/memory/search" in paths
```

**Step 2: Run the tests and verify failure before implementation is complete**

Run:

```bash
cd backend
uv run pytest tests/test_everos_sidecar_imports.py -q
```

Expected before Tasks 1-3: fail because `app.everos` does not exist or dependencies are missing.

Expected after Tasks 1-3: pass.

**Step 3: Commit source/dependency/import test slice**

Run:

```bash
git add backend/app/everos backend/pyproject.toml backend/uv.lock backend/tests/test_everos_sidecar_imports.py
git commit -m "feat: vendor EverOS backend service source"
```

Expected: commit succeeds and only intended files are included.

---

## Task 5: Add EverOS Service To Docker Compose

**Files:**

- Modify: `deploy/docker-compose.yml`
- Modify: `deploy/.env.example`
- Modify: `backend/env.example`

**Step 1: Add compose variables**

In `deploy/.env.example`, add near service port settings:

```env
EVEROS_PORT_HOST=8003
EVEROS_ROOT=/data/everos
EVEROS_BASE_URL=http://everos:8003
```

In `backend/env.example`, add an EverOS section:

```env
# -----------------------------------------------------------------------------
# ===== EverOS Memory Service =====
# -----------------------------------------------------------------------------
EVEROS_BASE_URL=http://everos:8003
EVEROS_ROOT=/data/everos
EVEROS_API__HOST=0.0.0.0
EVEROS_API__PORT=8003

# Fill these for real memory extraction/search.
EVEROS_LLM__MODEL=
EVEROS_LLM__API_KEY=
EVEROS_LLM__BASE_URL=
EVEROS_EMBEDDING__MODEL=
EVEROS_EMBEDDING__API_KEY=
EVEROS_EMBEDDING__BASE_URL=
EVEROS_RERANK__MODEL=
EVEROS_RERANK__API_KEY=
EVEROS_RERANK__BASE_URL=
```

**Step 2: Add `everos` service**

In `deploy/docker-compose.yml`, add a service near the other backend services:

```yaml
  everos:
    image: ${BACKEND_FULL_IMAGE:-joysafeter-backend:latest}
    build: *backend-build
    container_name: joysafeter-everos
    restart: unless-stopped
    env_file: *backend-env-files
    environment:
      <<: *backend-common-env
      JOYSAFETER_SERVICE_ROLE: everos
      BACKEND_APP_MODULE: app.everos.entrypoints.api.app:create_app
      BACKEND_PORT: 8003
      WORKERS: 1
      EVEROS_ROOT: ${EVEROS_ROOT:-/data/everos}
      EVEROS_API__HOST: 0.0.0.0
      EVEROS_API__PORT: 8003
    ports:
      - "${EVEROS_BIND_HOST:-127.0.0.1}:${EVEROS_PORT_HOST:-8003}:8003"
    depends_on: *backend-depends
    volumes:
      - backend-logs:/app/app/logs
      - backend-files:/app/data/files
      - ../skills:/app/skills:ro
      - everos-data:/data/everos
    healthcheck:
      <<: *backend-health-common
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8003/health', timeout=5)"]
    networks:
      - joysafeter-network
```

**Step 3: Add volume**

In the `volumes:` section of `deploy/docker-compose.yml`, add:

```yaml
  everos-data:
    driver: local
    name: joysafeter-everos-data
```

**Step 4: Validate compose config**

Run:

```bash
cd deploy
docker compose config >/tmp/joysafeter-compose.yml
rg -n "joysafeter-everos|everos-data|8003" /tmp/joysafeter-compose.yml
```

Expected: service, port, and volume are present.

**Step 5: Commit compose/config slice**

Run:

```bash
git add deploy/docker-compose.yml deploy/.env.example backend/env.example
git commit -m "feat: add EverOS backend service container"
```

Expected: commit succeeds.

---

## Task 6: Inject EverOS Base URL Into Execution Sandboxes

**Files:**

- Modify: `backend/app/joysafeter_orchestrator/kernel/harness_input_builder.py`
- Test: `backend/tests/test_everos_harness_input.py`

**Step 1: Write tests for helper behavior**

Create `backend/tests/test_everos_harness_input.py`:

```python
from app.joysafeter_orchestrator.kernel import harness_input_builder as hib


def test_everos_base_url_defaults_to_compose_service(monkeypatch):
    monkeypatch.delenv("EVEROS_BASE_URL", raising=False)

    assert hib._resolve_everos_base_url() == "http://everos:8003"


def test_everos_base_url_can_be_overridden(monkeypatch):
    monkeypatch.setenv("EVEROS_BASE_URL", "http://memory.local:18003")

    assert hib._resolve_everos_base_url() == "http://memory.local:18003"


def test_append_everos_system_prompt_adds_service_note():
    base = "You are a security assistant."
    out = hib._append_everos_system_prompt(base, "http://everos:8003")

    assert "You are a security assistant." in out
    assert "EverOS memory service" in out
    assert "http://everos:8003" in out
```

**Step 2: Run tests and verify failure**

Run:

```bash
cd backend
uv run pytest tests/test_everos_harness_input.py -q
```

Expected: fail because helper functions do not exist.

**Step 3: Add helpers**

In `backend/app/joysafeter_orchestrator/kernel/harness_input_builder.py`, add near the other builder helpers:

```python
def _resolve_everos_base_url() -> str:
    return os.getenv("EVEROS_BASE_URL", "http://everos:8003").rstrip("/")


def _append_everos_system_prompt(base_system: Optional[str], everos_base_url: str) -> str:
    note = (
        "# EverOS Memory Service\n"
        "The EverOS memory service is available inside this sandbox at "
        f"`{everos_base_url}`. Use it for long-term memory operations when "
        "the task explicitly requires memory search or memory writes."
    )
    if base_system:
        return f"{base_system}\n\n{note}"
    return note
```

**Step 4: Inject env and system prompt**

In `build_harness_input()`, after environment variables are collected and before returning `HarnessInput`, add:

```python
    everos_base_url = _resolve_everos_base_url()
    env.setdefault("EVEROS_BASE_URL", everos_base_url)
```

Then replace final system prompt combination:

```python
    if memory_system_prompt:
        combined_system = (
            f"{base_system}\n\n{memory_system_prompt}"
            if base_system
            else memory_system_prompt
        )
    else:
        combined_system = base_system or None
```

with:

```python
    if memory_system_prompt:
        combined_system = (
            f"{base_system}\n\n{memory_system_prompt}"
            if base_system
            else memory_system_prompt
        )
    else:
        combined_system = base_system or None

    combined_system = _append_everos_system_prompt(combined_system, everos_base_url)
```

**Step 5: Run helper tests**

Run:

```bash
cd backend
uv run pytest tests/test_everos_harness_input.py -q
```

Expected: pass.

**Step 6: Run import smoke tests again**

Run:

```bash
cd backend
uv run pytest tests/test_everos_sidecar_imports.py tests/test_everos_harness_input.py -q
```

Expected: pass.

**Step 7: Commit sandbox access slice**

Run:

```bash
git add backend/app/joysafeter_orchestrator/kernel/harness_input_builder.py backend/tests/test_everos_harness_input.py
git commit -m "feat: expose EverOS service to execution sandboxes"
```

Expected: commit succeeds.

---

## Task 7: Verify EverOS Service Boots Locally

**Files:**

- No source changes expected.

**Step 1: Build backend image**

Run:

```bash
cd deploy
docker compose build everos
```

Expected: image builds successfully.

If dependency downloads fail because of network restrictions, rerun with approved network access.

**Step 2: Start EverOS dependencies and service**

Run:

```bash
cd deploy
docker compose --profile local-redis up -d db redis skillspector everos
```

Expected: `joysafeter-everos` starts.

**Step 3: Check health from host**

Run:

```bash
curl -fsS http://127.0.0.1:8003/health
```

Expected:

```json
{"status":"ok"}
```

If EverOS refuses to start because `everos.toml` is missing, add a setup step in the Docker entrypoint or compose command to initialize `/data/everos` before starting. Keep that change in the EverOS service only.

**Step 4: Check health from compose network**

Run:

```bash
cd deploy
docker compose exec api python - <<'PY'
import urllib.request
print(urllib.request.urlopen("http://everos:8003/health", timeout=5).read().decode())
PY
```

Expected: JSON health response.

**Step 5: Verify persistence directory**

Run:

```bash
docker compose exec everos sh -lc 'ls -la /data/everos && test -d /data/everos/.index'
```

Expected: `.index` exists after service startup.

---

## Task 8: Verify Sandbox Can Reach EverOS

**Files:**

- No source changes expected unless networking fails.

**Step 1: Start the normal JoySafeter stack**

Run:

```bash
cd deploy
docker compose --profile local-redis --profile python-orchestrator up -d --build
```

Expected: `api`, `orchestrator`, `worker`, and `everos` become healthy.

**Step 2: Run a minimal Claude/Codex/Native task that prints env**

Use an existing local test flow or UI task with a prompt equivalent to:

```text
Print the value of EVEROS_BASE_URL, then run:
python - <<'PY'
import os, urllib.request
url = os.environ["EVEROS_BASE_URL"] + "/health"
print(urllib.request.urlopen(url, timeout=5).read().decode())
PY
```

Expected:

- The agent sees `EVEROS_BASE_URL=http://everos:8003`.
- The health call succeeds.

Repeat for Claude Code, Codex, and Native runtime images when those images are available locally.

**Step 3: Document limited networking gap if present**

If unrestricted networking works but limited networking blocks `everos`, update the design or deployment docs to state that Phase 2 supports unrestricted networking first and limited networking requires Envoy/allowed-host wiring in a later task.

**Step 4: Commit any documentation-only clarification**

If docs were changed:

```bash
git add docs/superpowers/specs/2026-07-07-everos-sidecar-integration-design.md
git commit -m "docs: clarify EverOS sandbox network access"
```

---

## Task 9: Final Verification

**Step 1: Run backend tests added by this plan**

Run:

```bash
cd backend
uv run pytest tests/test_everos_sidecar_imports.py tests/test_everos_harness_input.py -q
```

Expected: all pass.

**Step 2: Validate compose config**

Run:

```bash
cd deploy
docker compose config >/tmp/joysafeter-compose.yml
rg -n "joysafeter-everos|EVEROS_BASE_URL|8003|everos-data" /tmp/joysafeter-compose.yml
```

Expected: all expected strings are present.

**Step 3: Verify git contains only intended changes**

Run:

```bash
git status --short
```

Expected:

- Clean if unrelated pre-existing files were absent.
- If unrelated pre-existing files remain, confirm they are not part of this implementation.

**Step 4: Summarize remaining phases**

In the final implementation report, state explicitly that this plan completes service/sandbox access only. Remaining phases:

- platform-managed `/memory/add` and `/flush`,
- pre-task `/search` memory injection,
- MCP/tool wrapper for agent-managed memory.

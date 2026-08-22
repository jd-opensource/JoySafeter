# Documentation Contract Governance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reconcile JoySafeter's normative engineering documentation with executable repository facts and add automated checks that prevent future drift.

**Architecture:** Executable configuration and source remain the final authority. A standard-library Python checker extracts deterministic facts and compares them with narrowly marked documentation contracts, while human-authored prose remains outside false mechanical guarantees. Normative documents own one concern each; component and contribution documents link to those sources instead of copying mutable command matrices.

**Tech Stack:** Python 3.12 standard library, pytest, Markdown, GitHub Actions, pre-commit, FastAPI router source parsed with `ast`, TOML parsed with `tomllib`, JSON.

**Spec:** `docs/superpowers/specs/2026-08-22-documentation-contract-governance-design.md`

## Global Constraints

- Preserve every unrelated working-tree modification.
- Stage and commit only the files listed by each task.
- Use executable source, CI, manifests, and scripts as the final authority.
- Do not import the FastAPI application or connect to Docker, databases, Redis, or the network from the checker.
- Keep the checker dependency-free outside the Python standard library.
- Keep architecture prose human-authored; validate only deterministic contract data.
- Run backend pytest commands from `backend/`.
- Treat `docs/ARCHITECTURE.md` as canonical and `docs/ARCHITECTURE_CN.md` as its synchronized translation.

---

### Task 1: Build the Checker Foundation

**Files:**
- Create: `scripts/check_documentation_contracts.py`
- Create: `backend/tests/test_documentation_contracts.py`

**Interfaces:**
- Produces: `NORMATIVE_DOCUMENTS: tuple[Path, ...]` containing `AGENTS.md`,
  `CLAUDE.md`, `DEVELOPMENT.md`, `docs/ARCHITECTURE.md`,
  `docs/ARCHITECTURE_CN.md`, `backend/README.md`, `frontend/README.md`,
  `deploy/README.md`, `CONTRIBUTING.md`, and `docs/DOCUMENTATION_STATUS.md`
- Produces: `Violation(code: str, path: Path, message: str, line: int | None = None)`
- Produces: `slugify_markdown_heading(heading: str) -> str`
- Produces: `check_relative_markdown_links(repo_root: Path, documents: Sequence[Path]) -> list[Violation]`
- Produces: `run_checks(repo_root: Path, selected: frozenset[str] | None = None) -> list[Violation]`
- Produces: CLI `python3 scripts/check_documentation_contracts.py [--check NAME]`

- [ ] **Step 1: Write failing link and aggregation tests**

Add `pytestmark = pytest.mark.no_db` and load the root script through
`importlib.util.spec_from_file_location`. Use `tmp_path` fixtures to cover a valid
relative link, a missing path, a missing heading anchor, a Unicode heading, and two
simultaneous violations.

```python
def test_reports_missing_path_and_anchor(tmp_path: Path) -> None:
    write(tmp_path / "README.md", "[missing](missing.md)\n[bad](target.md#absent)\n")
    write(tmp_path / "target.md", "# Existing Heading\n")

    violations = checker.check_relative_markdown_links(
        tmp_path,
        [Path("README.md")],
    )

    assert [(item.code, item.path.as_posix()) for item in violations] == [
        ("DOC-LINK", "README.md"),
        ("DOC-LINK", "README.md"),
    ]
    assert "missing.md" in violations[0].message
    assert "#absent" in violations[1].message
```

- [ ] **Step 2: Run the focused tests and verify failure**

Run:

```bash
cd backend
uv run pytest tests/test_documentation_contracts.py -q
```

Expected: collection or import fails because
`scripts/check_documentation_contracts.py` does not exist.

- [ ] **Step 3: Implement the checker foundation**

Implement an immutable violation type and pure Markdown link extraction. Resolve
relative paths from the referring document, ignore external URLs and `mailto:`, and
derive GitHub-style anchors from Markdown headings.

```python
@dataclass(frozen=True, slots=True)
class Violation:
    code: str
    path: Path
    message: str
    line: int | None = None


CHECKS: dict[str, Callable[[Path], list[Violation]]] = {}


def run_checks(
    repo_root: Path,
    selected: frozenset[str] | None = None,
) -> list[Violation]:
    names = selected or frozenset(CHECKS)
    violations: list[Violation] = []
    for name in sorted(names):
        violations.extend(CHECKS[name](repo_root))
    return sorted(violations, key=lambda item: (item.path.as_posix(), item.line or 0, item.code))
```

The CLI accepts repeatable `--check` values, prints every violation, and returns `1`
when violations exist, `0` otherwise, and `2` for an unknown check name.

- [ ] **Step 4: Run the focused tests and CLI help**

Run:

```bash
cd backend
uv run pytest tests/test_documentation_contracts.py -q
cd ..
python3 scripts/check_documentation_contracts.py --help
```

Expected: tests pass and help lists the available check groups.

- [ ] **Step 5: Commit the checker foundation**

```bash
git add scripts/check_documentation_contracts.py backend/tests/test_documentation_contracts.py
git commit -m "test(governance): add documentation contract checker"
```

---

### Task 2: Validate Commands, Versions, and Agent Policy

**Files:**
- Modify: `scripts/check_documentation_contracts.py`
- Modify: `backend/tests/test_documentation_contracts.py`

**Interfaces:**
- Produces: `extract_shell_fences(text: str) -> list[tuple[int, list[str]]]`
- Produces: `check_backend_tool_wrappers(repo_root: Path) -> list[Violation]`
- Produces: `parse_deploy_subcommands(script_text: str) -> frozenset[str]`
- Produces: `check_documented_deploy_commands(repo_root: Path) -> list[Violation]`
- Produces: `read_tool_versions(repo_root: Path) -> Mapping[str, str]`
- Produces: `check_documented_tool_versions(repo_root: Path) -> list[Violation]`
- Produces: `extract_contract_block(text: str, name: str) -> str`
- Produces: `check_agent_policy_parity(repo_root: Path) -> list[Violation]`

- [ ] **Step 1: Write failing command, version, and parity tests**

Cover these exact cases:

```python
def test_rejects_unsupported_deploy_subcommand(tmp_path: Path) -> None:
    write(tmp_path / "deploy/deploy.sh", 'doctor|local|down) COMMAND="$1" ;;\n')
    write(tmp_path / "DEVELOPMENT.md", "```bash\n./deploy.sh up\n```\n")
    violations = checker.check_documented_deploy_commands(tmp_path)
    assert [item.code for item in violations] == ["DOC-COMMAND"]
    assert "up" in violations[0].message


def test_rejects_bare_backend_tools_in_shell_fences(tmp_path: Path) -> None:
    write(tmp_path / "CONTRIBUTING.md", "```bash\ncd backend\npytest\nruff check .\n```\n")
    violations = checker.check_backend_tool_wrappers(tmp_path)
    assert len(violations) == 2
    assert all(item.code == "DOC-COMMAND" for item in violations)


def test_agent_shared_policy_must_match(tmp_path: Path) -> None:
    write(tmp_path / "AGENTS.md", "<!-- shared-policy:start -->\none\n<!-- shared-policy:end -->\n")
    write(tmp_path / "CLAUDE.md", "<!-- shared-policy:start -->\ntwo\n<!-- shared-policy:end -->\n")
    assert checker.check_agent_policy_parity(tmp_path)[0].code == "DOC-PARITY"
```

Add version fixtures for Python `>=3.12,<3.14`, Node `>=20.0.0`, Bun `>=1.2.0`,
and Rust `1.97.1`.

- [ ] **Step 2: Run tests and verify the new cases fail**

Run:

```bash
cd backend
uv run pytest tests/test_documentation_contracts.py -q
```

Expected: the new tests fail because the extraction and comparison functions are
missing.

- [ ] **Step 3: Implement static command and version checks**

Parse only fenced `bash`, `sh`, or `shell` blocks for executable command policy. Flag
lines beginning with `pytest`, `ruff`, `mypy`, or `alembic` unless they begin with
`uv run` or an explicit repository virtualenv executable.

Parse:

- `project.requires-python` from `backend/pyproject.toml` with `tomllib`
- `engines.node` and `engines.bun` from `frontend/package.json`
- `toolchain.channel` from `rust-toolchain.toml` with `tomllib`
- accepted lifecycle commands from the command-alternative branch in
  `deploy/deploy.sh`

Read the `tool-versions` block in `DEVELOPMENT.md` and the `shared-policy` blocks in
the two agent guidance files. Return `DOC-VERSION`, `DOC-COMMAND`, or `DOC-PARITY`
without modifying files.

- [ ] **Step 4: Run focused tests**

```bash
cd backend
uv run pytest tests/test_documentation_contracts.py -q
```

Expected: all checker tests pass.

- [ ] **Step 5: Commit command and version checks**

```bash
git add scripts/check_documentation_contracts.py backend/tests/test_documentation_contracts.py
git commit -m "feat(governance): validate documented commands and versions"
```

---

### Task 3: Validate Architecture Contracts

**Files:**
- Modify: `scripts/check_documentation_contracts.py`
- Modify: `backend/tests/test_documentation_contracts.py`

**Interfaces:**
- Produces: `extract_router_prefixes(router_source: str) -> frozenset[str]`
- Produces: `extract_markdown_table_column(block: str, column: int) -> frozenset[str]`
- Produces: `check_api_route_contract(repo_root: Path) -> list[Violation]`
- Produces: `check_architecture_source_paths(repo_root: Path) -> list[Violation]`
- Produces: `check_bilingual_architecture_parity(repo_root: Path) -> list[Violation]`

- [ ] **Step 1: Write failing architecture extraction tests**

Use fixture source with aliased router imports and literal prefixes:

```python
def test_extracts_include_router_prefixes_from_ast() -> None:
    source = """
from app.example import router as example_router
api.include_router(example_router, prefix="/examples")
api.include_router(example_router, prefix="/nested/examples")
"""
    assert checker.extract_router_prefixes(source) == frozenset(
        {"/examples", "/nested/examples"}
    )
```

Add cases for a missing route in the English document, an extra route in the Chinese
document, a missing repository-relative source path, duplicated contract markers, and
matching route/FSM/entity-prefix blocks.

- [ ] **Step 2: Run tests and verify failure**

```bash
cd backend
uv run pytest tests/test_documentation_contracts.py -q
```

Expected: failures identify the missing architecture-check functions.

- [ ] **Step 3: Implement architecture checks**

Parse `include_router(..., prefix="...")` calls with `ast` and compare the result to
the `api-routes` contract table in both architecture documents.

Use explicit markers:

```markdown
<!-- doc-contract:api-routes:start -->
...
<!-- doc-contract:api-routes:end -->
```

Support the same marker form for `services`, `state-machines`, `entity-prefixes`, and
`source-paths`. Compare language-neutral values such as prefixes, enum tokens, and
repository-relative paths rather than translated prose.

For source paths, validate backticked values beginning with `backend/`, `frontend/`,
`proto/`, `sandbox-runner/`, or `deploy/`. Reject ambiguous package-relative anchors
inside the machine-checked block.

- [ ] **Step 4: Run focused tests**

```bash
cd backend
uv run pytest tests/test_documentation_contracts.py -q
```

Expected: all checker unit tests pass.

- [ ] **Step 5: Commit architecture checks**

```bash
git add scripts/check_documentation_contracts.py backend/tests/test_documentation_contracts.py
git commit -m "feat(governance): validate architecture documentation contracts"
```

---

### Task 4: Reconcile the Developer Workflow Surface

**Files:**
- Modify: `DEVELOPMENT.md`
- Modify: `deploy/README.md`
- Modify: `backend/README.md`
- Modify: `frontend/README.md`
- Modify: `CONTRIBUTING.md`

**Interfaces:**
- Consumes: checker groups `links`, `commands`, and `versions`
- Produces: one authoritative clean-checkout development workflow

- [ ] **Step 1: Run the checker against the current documents**

```bash
python3 scripts/check_documentation_contracts.py \
  --check links --check commands --check versions
```

Expected: failures include the unsupported `deploy.sh up` reference in a downstream
document, the Python version mismatch, and the missing `tool-versions` contract block.

- [ ] **Step 2: Rewrite the setup order and version contract**

Move dependency installation before host-stack startup. Add this machine-checked
table to `DEVELOPMENT.md`:

```markdown
<!-- doc-contract:tool-versions:start -->
| Tool | Supported version | Executable source |
| --- | --- | --- |
| Python | `>=3.12,<3.14` | `backend/pyproject.toml` |
| Node.js | `>=20.0.0` | `frontend/package.json` |
| Bun | `>=1.2.0` | `frontend/package.json` |
| Rust | `1.97.1` | `rust-toolchain.toml` |
<!-- doc-contract:tool-versions:end -->
```

Define `frontend/.env` as the shared host-stack configuration created by
`local-test.sh`; document `frontend/.env.local` only as an optional developer override
with higher Next.js precedence.

- [ ] **Step 3: Make startup and shutdown semantics explicit**

Document that `Ctrl+C` stops API, worker, orchestrator, and frontend host processes but
keeps PostgreSQL, Redis, the standalone Envoy container, and an optional runner-control
proxy available. Provide separate commands for Compose shutdown and removal of the
standalone containers, including the configured-name caveat.

Clarify that `deploy/local-test.sh` is the host-development path and
`deploy/deploy.sh local` is the complete Compose deployment path.

- [ ] **Step 4: Align local quality gates with CI**

Document these categories and commands:

- Backend: pytest, mypy, Ruff lint, Ruff format check through `uv run`
- Frontend: test, lint, type-check, format check, and production build
- Rust workspaces: pinned-toolchain fmt, clippy, and test with `--workspace`,
  `--all-targets`, and `--locked`
- Pre-commit: installation and the manual all-files command

Add a `### Pre-commit Hooks` heading so existing contribution links have a stable
target.

- [ ] **Step 5: Correct the host-development section in deploy documentation**

Update `deploy/README.md` to use the same environment-file and shutdown semantics as
`DEVELOPMENT.md`. Keep deployment-only commands and troubleshooting in this file.

- [ ] **Step 6: Simplify backend guidance**

Remove the unsupported `./deploy.sh up` command and replace bare `alembic` and `pytest`
commands with links to the canonical sections in `DEVELOPMENT.md`.

Update the backend layout to include application, infrastructure, identity, and
identity-federation packages. Remove the nonexistent API `services.py` entry. Keep only
component-specific entry points that are not duplicated elsewhere.

- [ ] **Step 7: Simplify frontend guidance**

Use `frontend/.env` as the shared host-stack file and describe `.env.local` only as an
optional override. Keep the frontend-specific script inventory, but point full quality
and deployment workflows to `DEVELOPMENT.md` and `deploy/README.md`.

- [ ] **Step 8: Simplify contribution guidance**

Replace duplicated test and linter command blocks with a required link to the
`DEVELOPMENT.md#tests-and-quality-checks` section. Keep review expectations and
Conventional Commit guidance.

Replace rigid line-count and blanket docstring rules with responsibility-based guidance
that follows configured formatters, linters, type checking, and existing local style.

- [ ] **Step 9: Run focused documentation checks**

```bash
python3 scripts/check_documentation_contracts.py \
  --check links --check commands --check versions
bash -n deploy/local-test.sh
bash deploy/deploy.sh --help >/tmp/joysafeter-deploy-help.txt
```

Expected: the selected documentation checks pass and both shell entry points remain
valid.

- [ ] **Step 10: Commit developer workflow reconciliation**

```bash
git add DEVELOPMENT.md deploy/README.md backend/README.md frontend/README.md CONTRIBUTING.md
git commit -m "docs(development): align local workflow with executable tooling"
```

---

### Task 5: Reconcile Canonical and Chinese Architecture

**Files:**
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/ARCHITECTURE_CN.md`

**Interfaces:**
- Consumes: checker group `architecture`
- Produces: synchronized machine-checkable architecture contract blocks

- [ ] **Step 1: Run architecture checks and record current failures**

```bash
python3 scripts/check_documentation_contracts.py --check architecture
```

Expected: failures identify missing contract markers, stale route groups, and stale
source anchors.

- [ ] **Step 2: Correct runtime ownership and event flow**

Make both languages state the same durable-event contract:

- Rust orchestrator direct Postgres persistence is the primary path.
- Redis Stream plus worker persistence is fallback/backfill.
- Redis Pub/Sub provides live SSE fan-out.

Synchronize task submission, session-resource, cancellation, project-lifecycle,
sandbox-CAS, organization-membership, and persistence ownership rules. Correct the
duplicate numbering in the English list.

- [ ] **Step 3: Correct transport and source anchors**

Replace stale references including:

- `joysafeter_api/services.py`
- `kernel/task_runner.py`
- `sandbox/envoy_manager.py`

Use current repository-relative anchors such as:

- `backend/app/joysafeter_domain/services/task_submission_service.py`
- `backend/app/joysafeter_shared/orchestrator_bridge/enqueue.py`
- `backend/app/joysafeter_orchestrator_rs/src/kernel/task_runner.rs`
- `backend/app/joysafeter_orchestrator_rs/src/sandbox/envoy.rs`

- [ ] **Step 4: Synchronize API route contracts**

Replace removed `/secrets` and `/vaults` rows with the current mounted route groups and
include all prefixes registered in
`backend/app/joysafeter_api/api/v1/router.py`, including `/credentials`,
`/credential-groups`, `/network-policies`, `/storage-volumes`, `/llm`, and
`/analytics`.

Wrap the English and Chinese route tables in matching `api-routes` contract markers.

- [ ] **Step 5: Synchronize source layout and stable contract tables**

Add the current top-level backend packages to both source-layout sections:

- `joysafeter_application`
- `joysafeter_infrastructure`
- `joysafeter_identity`
- `joysafeter_identity_federation`

Mark the service, state-machine, entity-prefix, and source-path sections with matching
contract markers. Preserve translated prose while keeping language-neutral values
identical.

- [ ] **Step 6: Run architecture and link checks**

```bash
python3 scripts/check_documentation_contracts.py \
  --check architecture --check links
```

Expected: no `DOC-ROUTE`, `DOC-PATH`, `DOC-PARITY`, or `DOC-LINK` violations.

- [ ] **Step 7: Commit architecture reconciliation**

```bash
git add docs/ARCHITECTURE.md docs/ARCHITECTURE_CN.md
git commit -m "docs(architecture): reconcile runtime contracts with source"
```

---

### Task 6: Record Documentation Governance Evidence

**Files:**
- Modify: `docs/DOCUMENTATION_STATUS.md`

**Interfaces:**
- Consumes: canonical workflow from `DEVELOPMENT.md`
- Consumes: canonical architecture from `docs/ARCHITECTURE.md`
- Produces: a bounded, evidence-based documentation audit record

- [ ] **Step 1: Capture current deterministic evidence**

```bash
python3 scripts/check_documentation_contracts.py \
  --check links --check commands --check versions --check architecture
```

Expected: all selected checks pass before the audit record is updated.

- [ ] **Step 2: Convert documentation status into an evidence log**

Set the review date to `2026-08-22`. Record the normative scope, checker command,
verified executable sources, and the explicit limitation that historical plans and
tutorial prose are not runtime authority.

Remove claims that are no longer demonstrated by current checks.

- [ ] **Step 3: Validate the updated evidence log**

```bash
python3 scripts/check_documentation_contracts.py \
  --check links --check commands --check versions --check architecture
```

Expected: all selected checks pass.

- [ ] **Step 4: Commit the audit record**

```bash
git add docs/DOCUMENTATION_STATUS.md
git commit -m "docs(governance): record documentation contract audit"
```

---

### Task 7: Integrate Governance with Agents, Pre-commit, and CI

**Files:**
- Modify: `AGENTS.md`
- Modify: `CLAUDE.md`
- Modify: `.pre-commit-config.yaml`
- Modify: `.github/workflows/ci.yml`
- Modify: `DEVELOPMENT.md`
- Modify: `scripts/check_documentation_contracts.py`
- Modify: `backend/tests/test_documentation_contracts.py`

**Interfaces:**
- Consumes: all checker groups
- Produces: pre-commit hook `documentation-contracts`
- Produces: CI step `Run documentation contract checks`

- [ ] **Step 1: Add failing repository-integration and policy tests**

Add a test that resolves the real repository root and asserts:

```python
def test_repository_documentation_contracts_are_consistent() -> None:
    violations = checker.run_checks(REPO_ROOT)
    assert violations == []
```

Add tests that require exactly one `shared-policy` block in each agent file and reject
unknown `--check` names with exit code `2`.

- [ ] **Step 2: Run the integration test and verify failure**

```bash
cd backend
uv run pytest tests/test_documentation_contracts.py::test_repository_documentation_contracts_are_consistent -q
```

Expected: failure because the shared policy markers and integration wiring are not yet
present.

- [ ] **Step 3: Update agent authority rules**

Wrap the common body of `AGENTS.md` and `CLAUDE.md` in matching `shared-policy`
markers. Replace the unconditional command reference with this policy:

```md
Use `DEVELOPMENT.md` as the human-facing command index. Treat package manifests,
tool configuration, CI workflows, deployment scripts, and source registration as the
executable source of truth. If documentation differs from executable configuration,
follow the executable source and update the affected documentation within scope.
```

Keep only the agent-specific title and instruction-precedence wording outside the
shared block.

- [ ] **Step 4: Add pre-commit and CI entry points**

Add this local hook to `.pre-commit-config.yaml`:

```yaml
      - id: documentation-contracts
        name: Documentation contract checks
        entry: python3 scripts/check_documentation_contracts.py
        language: system
        pass_filenames: false
        always_run: true
```

Add a CI step after Python setup in the existing pre-commit job:

```yaml
      - name: Run documentation contract checks
        run: python3 scripts/check_documentation_contracts.py
```

Document the direct checker command under the quality-check section in
`DEVELOPMENT.md`.

- [ ] **Step 5: Run focused unit and integration verification**

```bash
cd backend
uv run pytest tests/test_documentation_contracts.py -q
cd ..
python3 scripts/check_documentation_contracts.py
backend/.venv/bin/python -m pre_commit run documentation-contracts --all-files
```

Expected: all commands exit `0` with no documentation violations.

- [ ] **Step 6: Validate changed configuration and documentation**

```bash
git diff --check
bash -n deploy/deploy.sh
bash -n deploy/local-test.sh
cd backend
uv run ruff check ../scripts/check_documentation_contracts.py tests/test_documentation_contracts.py
uv run ruff format --check ../scripts/check_documentation_contracts.py tests/test_documentation_contracts.py
```

Expected: all commands exit `0`. Do not run an all-files autofixing hook while unrelated
business changes remain in the working tree.

- [ ] **Step 7: Commit governance integration**

```bash
git add AGENTS.md CLAUDE.md .pre-commit-config.yaml .github/workflows/ci.yml \
  DEVELOPMENT.md scripts/check_documentation_contracts.py \
  backend/tests/test_documentation_contracts.py
git commit -m "ci(governance): enforce documentation contracts"
```

---

### Task 8: Perform Final Evidence Review

**Files:**
- Modify only if verification reveals an in-scope defect.

**Interfaces:**
- Consumes: completed documentation governance system
- Produces: final verification evidence and clean scoped status

- [ ] **Step 1: Run the complete governance verification set**

```bash
cd backend
uv run pytest tests/test_documentation_contracts.py -q
cd ..
python3 scripts/check_documentation_contracts.py
backend/.venv/bin/python -m pre_commit run documentation-contracts --all-files
git diff --check
```

Expected: every command exits `0`.

- [ ] **Step 2: Confirm commit and working-tree scope**

```bash
git log --oneline --decorate -10
git status --short
git diff --name-only 3162213d..HEAD
```

Verify that governance commits contain only the planned files and that every unrelated
pre-existing modification remains uncommitted and unchanged.

- [ ] **Step 3: Review acceptance criteria against evidence**

Confirm each acceptance criterion in
`docs/superpowers/specs/2026-08-22-documentation-contract-governance-design.md` against
the checker output, focused pytest result, hook result, diff check, and committed file
list.

- [ ] **Step 4: Report completion without creating an extra commit**

Report the implemented authority hierarchy, corrected document set, automated checks,
commands executed, exact results, and any remaining manual-review limitation. Do not
claim broader repository tests passed unless they were run during this task.

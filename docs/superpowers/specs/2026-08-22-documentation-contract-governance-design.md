# Documentation Contract Governance Design

**Date:** 2026-08-22
**Status:** Approved design, pending implementation planning

## Context

The repository-level agent guidance delegates development commands to
`DEVELOPMENT.md` and cross-service architecture decisions to
`docs/ARCHITECTURE.md`. Those references make the documents part of the effective
engineering control plane for Codex and Claude Code.

The current documentation set contains repeated mutable facts without automated
consistency checks. Confirmed drift includes unsupported deployment commands,
incorrect runtime version ranges, incomplete local quality gates, conflicting
frontend environment-file conventions, stale architecture source paths, outdated API
route groups, incomplete source-layout descriptions, and divergence between the
English and Chinese architecture documents.

The root cause is not isolated documentation mistakes. The repository lacks an
explicit authority hierarchy, clear ownership for each class of documentation, and
machine-enforced checks for facts that can be derived from executable sources.

## Goals

- Establish an explicit source-of-truth hierarchy for agents and contributors.
- Give each normative document one clear responsibility.
- Remove duplicated commands and architecture facts from derivative documents.
- Reconcile the normative documentation with current executable configuration and
  source structure.
- Add deterministic checks that detect future documentation drift before merge.
- Keep checks fast, offline, side-effect free, and independently testable.
- Preserve all unrelated working-tree changes.

## Non-Goals

- Generating entire prose documents from source code.
- Rewriting historical plans, completed design documents, or tutorials that are not
  part of the normative dependency chain.
- Treating prose-level architectural judgment as mechanically provable.
- Refactoring production code solely to make documentation easier to describe.
- Adding network-dependent documentation validation.

## Authority Hierarchy

Repository facts are resolved in this order:

1. Executable source: production code, tests, migrations, package manifests, tool
   configuration, CI workflows, deployment scripts, and Compose manifests.
2. Normative human documentation: `DEVELOPMENT.md`, `docs/ARCHITECTURE.md`, and
   `deploy/README.md` within their assigned scopes.
3. Derived entry points: component READMEs, contribution guidance, translations, and
   documentation status reports.
4. Historical plans and tutorials.

`AGENTS.md` and `CLAUDE.md` define how coding agents apply this hierarchy. When a
derived or normative document conflicts with executable source, the executable source
wins and the affected documentation must be corrected in the same change when it is
within scope.

## Document Ownership

### Agent Guidance

`AGENTS.md` and `CLAUDE.md` own agent workflow, risk gates, verification discipline,
and the authority hierarchy. They must not duplicate tool versions, full command
matrices, API route inventories, or deployment topology.

Their shared policy body remains equivalent apart from agent-specific headings and
instruction-precedence wording.

### Development Workflow

`DEVELOPMENT.md` is the only complete human-facing index for local development. It
owns:

- Supported tool version ranges
- First-time dependency installation
- Environment-file initialization
- Host-based stack startup and complete shutdown
- Manual component startup
- Targeted and CI-equivalent verification commands
- Pre-commit setup
- Database migration workflow

Commands must identify their required working directory and prerequisites.

### Runtime Architecture

`docs/ARCHITECTURE.md` is the canonical English runtime architecture contract. It
owns stable service responsibilities, state authority, communication paths, lifecycle
ownership, cross-layer boundaries, state machines, public route groups, typed-ID
boundaries, and current source layout.

`docs/ARCHITECTURE_CN.md` is a synchronized translation. It does not independently
define architecture. Machine-checkable contract sets must match the canonical English
document.

### Deployment

`deploy/README.md` owns Compose deployment, image lifecycle, deployment modes,
deployment-specific environment configuration, operational commands, and deployment
troubleshooting. Its command surface must match `deploy/deploy.sh --help` and the
Compose service definitions.

### Component Entry Points

`backend/README.md` and `frontend/README.md` own component orientation, local module
structure, and the shortest component-specific development path. They refer to
`DEVELOPMENT.md` for shared setup and verification and to `deploy/README.md` for
deployment. They must not maintain independent copies of the full command matrix or
runtime architecture.

### Contribution Process

`CONTRIBUTING.md` owns issue, pull-request, review, and commit conventions. It points
to `DEVELOPMENT.md` for executable setup and quality commands instead of duplicating
them.

### Audit Record

`docs/DOCUMENTATION_STATUS.md` records audit date, reviewed scope, verification
commands, known limitations, and remaining non-normative documentation debt. It is an
evidence log, not an independent source of runtime truth.

## Documentation Contract Checker

Add `scripts/check_documentation_contracts.py`, implemented with the Python standard
library only.

The checker separates pure extraction and comparison functions from filesystem and
console I/O. Every check returns structured violations containing a stable code, file,
line when available, observed value, and expected contract.

The initial contract set covers:

1. Relative Markdown paths and heading anchors.
2. Shared policy parity between `AGENTS.md` and `CLAUDE.md`.
3. Python, Node, Bun, and Rust version declarations against their executable config.
4. Documented `deploy.sh` subcommands against the script's accepted command set.
5. Prohibited bare backend tool commands that bypass `uv run`.
6. API route-prefix inventory against `joysafeter_api/api/v1/router.py`.
7. Explicit architecture source anchors against repository paths.
8. Critical English/Chinese architecture contract parity, including service names,
   route prefixes, state sets, and typed-ID prefixes.

The checker does not import the FastAPI application, connect to services, start
containers, or access the network. Static parsing is preferred over runtime imports to
avoid side effects.

## Failure Semantics

Deterministic contract violations fail closed with a non-zero exit code. The checker
reports all discovered violations in one run using stable categories:

- `DOC-LINK`
- `DOC-COMMAND`
- `DOC-VERSION`
- `DOC-ROUTE`
- `DOC-PATH`
- `DOC-PARITY`
- `DOC-STRUCTURE`

Messages identify the affected file and actionable expected value. The initial
implementation provides no automatic rewrite mode because silent rewriting could
damage architectural intent.

Claims that cannot be reliably derived from source remain subject to focused manual
review and are recorded in `docs/DOCUMENTATION_STATUS.md`. The checker must not imply
that passing deterministic checks proves every prose statement correct.

## Integration

The same checker entry point runs in three contexts:

1. Directly from the repository root for focused local validation.
2. Through a local pre-commit hook for relevant documentation and executable-source
   changes.
3. In GitHub Actions as an unconditional documentation-contract check.

The pre-commit and CI integrations call the script rather than duplicating validation
logic.

## Test Strategy

Unit tests cover the checker's pure behavior with temporary repositories and fixture
documents. Cases include:

- Valid and invalid relative links and anchors
- Unicode headings
- Supported and unsupported deployment commands
- Required `uv run` command forms
- Matching and mismatching tool versions
- Aliased router imports and `include_router` calls
- Allowed agent-specific policy differences
- Missing or duplicated bilingual contract entries
- Aggregation of multiple violations
- Missing files and malformed input

A repository-level integration test executes the checker against the real tree. It
must complete without network, service, Docker, or database access.

## Migration Sequence

1. Implement and unit-test the documentation contract checker.
2. Correct `DEVELOPMENT.md` using current manifests, CI, and startup scripts.
3. Correct `docs/ARCHITECTURE.md` using current routes, source layout, protocols, and
   ownership boundaries.
4. Synchronize `docs/ARCHITECTURE_CN.md` with the canonical contract.
5. Reduce duplicated guidance in backend/frontend READMEs and `CONTRIBUTING.md`.
6. Correct host-development lifecycle details in `deploy/README.md`.
7. Update `AGENTS.md` and `CLAUDE.md` with the authority hierarchy.
8. Update `docs/DOCUMENTATION_STATUS.md` with current evidence and limitations.
9. Wire the checker into pre-commit and CI.
10. Run targeted tests, the repository contract checker, pre-commit, and relevant
    existing quality checks.

## Working-Tree Safety

The repository currently contains unrelated uncommitted business changes. The
implementation must inspect status before each commit, stage only documentation
governance files, and never restore, rewrite, or include unrelated changes.

Normative documentation must not describe behavior that exists only in unrelated
uncommitted files. Facts used by this change must already exist in committed source or
be introduced in the same focused governance change.

## Acceptance Criteria

- The authority hierarchy is explicit and consistent in both agent guidance files.
- Development setup works in the documented order from a clean checkout.
- Host-based startup has a complete and accurate shutdown procedure.
- Local quality commands cover the CI-enforced checks.
- No normative document references unsupported commands or missing anchors.
- Architecture route groups, source anchors, source layout, state authority, and
  English/Chinese critical contracts match current source.
- Component and contribution documents no longer duplicate mutable command matrices.
- The contract checker has focused unit tests and passes against the repository.
- Pre-commit and CI call the same checker entry point.
- The final change contains no unrelated business modifications.

## Trade-offs

This design intentionally validates only deterministic facts. More aggressive prose
generation would reduce some manual work but would make the architecture document less
readable and create a generator that becomes another source of truth. The selected
approach keeps design intent human-authored while enforcing high-change facts at the
repository boundary.

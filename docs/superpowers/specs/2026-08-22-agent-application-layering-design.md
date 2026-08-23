# Agent Application Layering Design

Date: 2026-08-22

## Problem

`joysafeter_domain/services/joysafeter_agent_service.py` combines unrelated responsibilities:

- pure Agent asset and execution-snapshot transformations;
- SQLAlchemy reads, row locks, version writes, bulk updates, and hard deletes;
- create/update use-case orchestration and transaction commits;
- Credential Application composition and model-binding validation;
- Trigger, Session, Task, and Agent lifecycle orchestration.

The result is the last Domain → Application reverse dependency. Agent create/update validation is also split between the API router and the Domain service, so direct service callers bypass MCP, Environment, archived-state, active-task, and structured version-conflict rules.

Two correctness gaps are part of the same ownership problem:

1. model binding validation receives engine/model through mutable service attributes and is not repeated when engine/model changes while the credential id remains unchanged;
2. Agent Environment binding validates with an unlocked read, allowing Environment archive/rename to race with Agent create/update.

## Goals

1. Remove `joysafeter_agent_service.py` and the final Domain → Application import.
2. Put pure Agent rules and transformations in Domain.
3. Put SQLAlchemy persistence and row-lock operations in Infrastructure.
4. Put complete create/update and lifecycle orchestration in Application.
5. Keep API routes limited to transport, authorization, request metadata, and response mapping.
6. Preserve REST shapes, database schema, typed ids, Agent version snapshots, error codes, and deletion behavior.
7. Remove obsolete import paths and private helper imports without compatibility shims.

## Non-Goals

- No database migration or public endpoint change.
- No change to Credential reference encoding or encryption compatibility.
- No change to Trigger, Session, Task, Sandbox, or identity-provider protocols.
- No redesign of Agent request/response schemas.

## Layer Ownership

### Domain

Create `joysafeter_domain/agents/`:

- `assets.py`: public `merge_agent_assets` and `split_agent_assets` transformations.
- `configuration_policy.py`: pure MCP URL, duplicate-name, and tool-to-server reference validation. Runtime configuration such as HTTPS enforcement is supplied as an explicit boolean.
- `snapshots.py`: pure Agent and Environment execution-snapshot construction.

Domain code receives values and returns values or raises stable application errors. It does not import Application or Infrastructure and does not access the database.

### Application

Create `joysafeter_application/agents/`:

- `command_service.py`: complete Agent create/update use cases.
- `query_service.py`: read facade used by API, Session, Task, and Scheduler callers.
- `lifecycle_service.py`: archive, restore, delete, hard-delete, session archival, task cancellation, sandbox destruction, and identity cleanup orchestration.
- `ports.py`: Agent repository and external lifecycle side-effect protocols.
- `composition.py`: production wiring for the SQLAlchemy repository and runtime/identity adapters.

Application owns transaction boundaries and cross-resource ordering. No command rule remains private to the API router.

### Infrastructure

Create `joysafeter_infrastructure/agents/sqlalchemy_repository.py` for:

- Agent lookup and row locking;
- list and delete-preview queries;
- active-task and Session queries;
- Agent version persistence and lookup;
- bulk Session archival;
- hard deletion of Agent-owned durable rows.

The repository does not invoke Credential Application services or external runtime operations.

## Command Semantics

### Create

1. Validate engine, MCP configuration, and tool references.
2. Lock and validate the referenced Environment when present.
3. Resolve and validate published Skill references.
4. Lock and validate the model Credential when present.
5. Insert Agent and version 1 in one transaction.
6. Translate only Agent name uniqueness violations to `AGENT_NAME_CONFLICT`; rollback before raising.

Lock order is Environment → Credential for create, matching Environment mutation flows that lock Environment before referenced Credentials.

### Update

1. Lock Agent and reject missing or archived records.
2. Enforce optimistic version when supplied.
3. Derive the complete effective configuration.
4. Validate engine, MCP configuration, tools, and Environment.
5. When model credential, engine, or model changes, lock the old/new credential ids in deterministic order and validate the effective binding using explicit engine/model arguments.
6. When Environment or model Credential identity changes, reject while active tasks exist.
7. Apply changes, preserve no-op version behavior, write the next immutable Agent version, and commit once.
8. Translate Agent name uniqueness violations consistently and rollback before raising.

Lock order is Agent → Environment → sorted Credentials. Credential lifecycle scans Agent references without taking Agent row locks, so this does not introduce a reverse lock cycle. Environment lifecycle locks Environment and performs non-locking reference scans, so taking the Environment lock closes the validation/archive race.

## Lifecycle Semantics

`AgentLifecycleService` preserves the established Trigger → Agent aggregate lock order before blocker scans or destructive mutations. External cancellation, sandbox destruction, and identity cleanup move out of the API router behind explicit Application ports. Failure codes and compensation behavior remain unchanged.

Database mutation commits remain owned by Application. Runtime operations that must precede deletion remain outside the database transaction exactly as today; the final hard-delete transaction re-locks and rechecks blockers before deletion.

## Query Semantics

`AgentQueryService` exposes the current read contract without mutation side effects:

- get/lock by id;
- get by name and paginated list;
- versions and version snapshots;
- delete-preview counts;
- active-task listing;
- execution snapshot construction.

Callers no longer import Infrastructure directly.

## Compatibility

Preserve:

- `/api/v1/agents` request and response contracts;
- `model_credential_id` persistence and snapshot field;
- typed `AgentId`, `CredentialId`, `SessionId`, and `SkillId` boundaries;
- all existing structured error codes and HTTP mappings;
- Agent version numbering and no-op update behavior;
- Trigger → Agent lifecycle lock order;
- current force-delete cancellation and sandbox acknowledgement semantics.

Do not preserve:

- `joysafeter_domain.services.joysafeter_agent_service`;
- `JoySafeterAgentService`;
- private cross-module `_merge_agent_assets` / `_split_agent_assets` names;
- direct create/update access that bypasses the Application command boundary.

## Verification

- Architecture tests prove Domain has zero Application imports and the old service file is absent.
- Unit tests cover pure Agent configuration and asset policies.
- Application tests cover create/update errors, no-op updates, name conflicts, and engine/model/credential compatibility.
- PostgreSQL concurrency tests cover Credential archive versus Agent binding and Environment archive versus Agent binding.
- Existing Agent lifecycle, restore, snapshot, Session, Task, Trigger, and credential dependency suites run against an isolated PostgreSQL database.
- Ruff, format, Python compilation, and `git diff --check` must pass for all touched files.

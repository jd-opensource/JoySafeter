# Agent Model Restructure Design

Date: 2026-04-20

## Goal

Restructure JoySafeter around a single product-facing `Agent` object while preserving internal flexibility for multiple runtimes, draft editing, published versions, and future run-system unification.

This design resolves the current product confusion among `Agent`, `Graph`, `AgentProfile`, deployed graph, and runtime-related execution objects.

## Problem Statement

The current system mixes several different concerns under overlapping product terms:

- `Graph` acts as the editable definition and also as the thing users effectively deploy and chat with.
- `AgentProfile` acts as a runtime/executor configuration shell, but is exposed to users as if it were an `Agent`.
- `Chat`, `Mission`, and run-related pages do not point to the same primary object.
- `Graph` and `AgentProfile` leak internal implementation boundaries into product navigation and user mental models.

This creates a product surface where users cannot reliably answer:

- What is an Agent?
- What do I edit?
- What gets published?
- What does Mission assign?
- What exactly is running?

## Design Principles

- Product-facing concepts must be fewer than implementation concepts.
- Users should operate on `Agent`, not on implementation artifacts like `Graph` or `AgentProfile`.
- Versioning should be explicit and immutable.
- Editing should be draft-only.
- Runtime configuration should be attached to `Agent`, not to specific versions.
- External execution entry points should run only the active published version.
- Migration should reuse the existing `graphs`, deployment versions, and runtime infrastructure where possible.

## Chosen Model

### Product-Facing Objects

- `Agent`
- `Mission`
- `Run`
- `Skill`
- `Tool`

Optional secondary areas:

- `Memory`
- `OpenClaw`

Objects that should no longer be product-facing:

- `Graph`
- `AgentProfile`
- deployed graph

### Internal Domain Objects

- `Agent`
- `AgentDraft`
- `AgentVersion`
- `AgentRuntime`
- `Run`

## Object Definitions

### Agent

`Agent` is the single user-facing primary object.

It represents the thing a user creates, edits, publishes, assigns to missions, and runs through chat or API.

Recommended fields:

- `id`
- `workspace_id`
- `name`
- `description`
- `source`
- `build_mode`
- `status`
- `draft_graph_id`
- `active_version_id`
- `default_runtime_id`
- `created_at`
- `updated_at`

`source` and `build_mode` remain separate:

- `source`: `template | manual | copilot | import | system`
- `build_mode`: `canvas | code | template`

### AgentDraft

`AgentDraft` is the unique editable state for an `Agent`.

Rules:

- Every `Agent` has at most one current draft.
- Builder, Copilot, and Code Mode always edit the draft.
- Draft is never the default external runtime target.
- Publishing the draft creates a new immutable `AgentVersion`.

For the first migration stage, `AgentDraft` does not require a new physical table. It can be backed by the existing `graphs` row referenced by `agents.draft_graph_id`.

### AgentVersion

`AgentVersion` is an immutable published snapshot of an `Agent`.

Rules:

- A published version is never edited in place.
- `Chat`, `Mission`, and public/API execution always run the active published version.
- Exactly one version is active per `Agent`.
- Version activation is explicit.

This maps naturally to the existing `graph_deployment_version` snapshot model.

### AgentRuntime

`AgentRuntime` is a hidden runtime/executor configuration attached to `Agent`.

Rules:

- One `Agent` may have multiple runtimes internally.
- Phase 1 UI exposes only the default runtime.
- Runtime is not attached to version.
- Runtime holds executor-specific configuration, environment, concurrency, health, and pooling identity.

This is the internal evolution of the current `agent_profiles` model.

Recommended fields:

- `id`
- `agent_id`
- `runtime_type`
- `status`
- `max_concurrent_tasks`
- `instructions`
- `skill_ids`
- `custom_env`
- `runtime_config`
- `visibility`
- `created_at`
- `updated_at`

## Core Behavioral Rules

### Editing Rule

- Users always edit the current draft.
- Historical versions are never edited in place.
- Publishing the current draft creates a new version.

### Execution Rule

- `Chat`, `Mission`, and API execution always resolve to `Agent.active_version_id`.
- Draft may only be used for builder-local self-test workflows.
- Runtime is resolved from `Agent.default_runtime_id`.

### Assignment Rule

- `Mission` assigns `agent_id`, not `agent_profile_id`.
- Dispatch resolves:
  - `agent_id`
  - `active_version_id`
  - `default_runtime_id`

### Runtime Rule

- Runtime is agent-level, not version-level.
- All versions of an agent share the same runtime family/configuration envelope in phase 1.
- Future multi-runtime support is allowed, but hidden behind a single default runtime in phase 1 UI.

## Target Relationships

### Domain Relationships

- `Agent 1 -> 1 Draft`
- `Agent 1 -> N Versions`
- `Agent 1 -> N Runtimes`
- `Agent 1 -> 1 ActiveVersion`
- `Agent 1 -> 1 DefaultRuntime`
- `Mission N -> 1 Agent`
- `Run N -> 1 Agent`
- `Run N -> 1 AgentVersion`
- `Run N -> 1 AgentRuntime`

## Mapping from Current Models

### graphs

Current meaning:

- editable graph definition
- de facto user-facing agent in builder/chat contexts

Target meaning:

- backing store for `AgentDraft`

Migration intent:

- stop exposing `Graph` as a product object
- retain existing storage during the first migration stage
- point `Agent.draft_graph_id` to the current draft graph

### graph_deployment_version

Current meaning:

- immutable snapshot of deployed graph state

Target meaning:

- `AgentVersion`

Migration intent:

- preserve snapshot semantics
- add `agent_id`
- make version identity agent-scoped rather than graph-scoped at the product layer

### agent_profiles

Current meaning:

- runtime shell for CLI/openclaw/langgraph-like execution
- mission/execution dispatch target

Target meaning:

- `AgentRuntime`

Migration intent:

- hide from product UI and API naming
- attach to `Agent`
- preserve runtime behavior and runner integration

## Recommended Migration Sequence

### Phase 1: Introduce Agent as the Aggregate Root

Add a new `agents` table and make it the primary product-facing object.

Initial rules:

- each visible agent gets one `agents` row
- each agent points to one current draft graph
- each agent points to one default runtime
- each agent points to one active published version when available

Do not remove existing `graphs` or `agent_profiles` yet.

### Phase 2: Rebind Version Axis

Evolve deployment versions into agent versions:

- add `agent_id` to version records
- treat current deployment snapshots as `AgentVersion`
- set `agents.active_version_id`

The version model remains immutable.

### Phase 3: Rebind Runtime Axis

Internalize `agent_profiles` as runtimes:

- add `agent_id` ownership
- rename usage in services and APIs conceptually to `AgentRuntime`
- keep current execution runner and pooling logic

The runtime layer remains internal.

### Phase 4: Rebind Mission Assignment

Change mission assignment from runtime-level to agent-level:

- `mission.assignee_id` becomes `agent_id`
- dispatch resolves active version + default runtime internally

This is the key step that makes product semantics match user expectations.

### Phase 5: Rework Navigation and Product Surface

After the aggregate root is stable:

- make `Agents` the main product object
- move builder under agent detail
- remove `Graph` and `AgentProfile` from user-facing naming

### Phase 6: Unify Run System

Only after `Agent`, `Version`, and `Runtime` identities are stable:

- unify `agent_runs` and `executions` into a single run model or a single product-facing run contract
- require runs to carry:
  - `agent_id`
  - `agent_version_id`
  - `runtime_id`

This phase is intentionally last.

## Navigation and UI Restructure

### Top-Level Navigation

Recommended primary navigation:

- `Agents`
- `Missions`
- `Runs`
- `Skills`
- `Tools`

Secondary or lower-priority areas:

- `Memory`
- `OpenClaw`

Remove as top-level product concepts:

- `Workspace` as builder entry
- `Graph`
- `Agent Profile`

### Agents List

`/agents` becomes the primary workbench.

Each card/list item should show:

- agent name
- description
- source
- build mode
- current status
- active version
- default runtime
- recent run summary

### Agent Detail

Introduce a canonical detail route such as `/agents/[agentId]`.

Recommended tabs:

- `Build`
- `Versions`
- `Runtime`
- `Runs`
- `Settings`

### Build Tab

- edits current draft only
- canvas/code are editing modes, not separate product objects
- replaces the mental model of “editing a graph in workspace”

### Versions Tab

- lists immutable published versions
- shows active version
- supports publish, activate, inspect

### Runtime Tab

- shows only default runtime in phase 1
- configures runtime type, environment, concurrency, runtime settings
- must not use the term `AgentProfile`

### Runs Page

The product-facing run center must become a single history surface for agent executions.

The UI should no longer force users to reason about separate run classes such as `AgentRun` versus `Execution`.

### Chat Page

`/chat` should be demoted from primary product definition entry to execution entry.

Target role:

- choose an agent
- run the active published version
- inspect conversation outputs and artifacts

Preferred long-term experience:

- global `/chat` can remain as a convenience entry
- agent-scoped chat entry should also exist from agent detail

### Missions Page

Mission semantics should become straightforward:

- assign agent
- dispatch agent
- record which active version and runtime were used at dispatch time

Users should not see runtime-shell concepts here.

## Constraints and Non-Goals

### Constraints

- runtime remains agent-level in phase 1
- version remains immutable
- draft is the only editable state
- public execution never defaults to draft
- internal storage reuse is preferred over full rewrites

### Non-Goals

- no first-phase support for version-specific runtime overrides
- no first-phase public exposure of multiple runtimes
- no immediate full physical replacement of `graphs`
- no immediate run-table unification before agent identity is stabilized

## Why This Design

This design intentionally combines:

- product semantics of a single-object `Agent`
- internal flexibility of separate draft/version/runtime layers

It gives the user a stable mental model without prematurely collapsing implementation layers that will likely be needed as the system grows.

In short:

- product experience behaves like a strict single-object model
- internal architecture remains layered and evolvable

## Recommended Next Step

Write an implementation plan that executes the migration in this order:

1. introduce `Agent` aggregate root
2. rebind versions
3. rebind runtimes
4. rebind mission assignment
5. rework UI/navigation
6. unify run system

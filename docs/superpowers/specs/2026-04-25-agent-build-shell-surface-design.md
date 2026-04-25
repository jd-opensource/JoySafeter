# Agent Build Shell and Builder Surface Design

## Goal

Refactor the Agent build experience so the product architecture is based on the Agent lifecycle, not on one visual implementation. Visual orchestration remains a builder surface, and future surfaces such as CLI, prompt, or code builders can plug into the same lifecycle.

## Architecture

The UI separates two responsibilities:

- `AgentBuildShell`: the generic lifecycle shell for building, testing, releasing, and using an Agent.
- Builder surfaces: implementation-specific build UIs such as the visual canvas, future CLI builder, prompt builder, or code builder.

The Visual Agent route keeps its current URL behavior, including `stage=brief`, `stage=canvas`, `stage=test-lab`, `stage=release`, and `stage=usage`, but the implementation no longer treats `AgentStudioShell` as the platform-wide architecture. `AgentStudioShell` becomes a visual compatibility wrapper around `AgentBuildShell`.

## User Flow

All Agent types follow the same lifecycle:

1. Brief: describe what the Agent should do.
2. Build: use a builder surface to create the draft.
3. Test: run the current draft without affecting active releases.
4. Release: publish, activate, retire, and inspect releases.
5. Usage: connect the active release to chat, tasks, API, or business scenarios.

For Visual Agents, the Build stage renders the canvas surface. For future CLI Agents, the Build stage can render a terminal/session surface without changing release or usage stages.

## Boundary Rules

- Canvas editing must not own release management, API access, deployment history, or active-release execution.
- Draft test execution belongs to Test Lab.
- Publishing and release lifecycle belong to Release.
- Business invocation and API access belong to Usage.
- Backend execution identity remains unchanged: draft runs use `agent_version_id`; production runs use `release_id`.

## Compatibility

Existing visual URLs and tests remain valid. Legacy `tab=builder` can remain as a compatibility route, but the default Visual Agent experience should enter the lifecycle shell.

# Agent Studio Workflow Design

Date: 2026-04-25
Status: Design

## Context

JoySafeter currently exposes Agent building, Copilot generation, visual orchestration, version history, release management, chat, and execution monitoring through overlapping frontend surfaces. Users can build and publish Agents, but the product flow is unclear:

- It is not obvious whether the user is editing a draft, testing a draft, or using the published Agent.
- Copilot appears as another chat-like surface rather than a construction tool.
- Component selection competes with Copilot in the builder sidebar.
- Version and release management are exposed as standalone management concepts instead of supporting the "publish for use" workflow.
- Agent Chat, builder test runs, and business executions are easy to confuse.

This design defines a user-facing Agent Studio workflow for Visual Agents. It builds on the existing Agent aggregate model, Graph Builder integration, user-centric frontend refactoring, and global chat/debug architecture.

## Goal

When a user enters a specific Agent type, the product should help them build a useful Agent, validate it, publish it, and connect it to a business scenario.

For Visual Agents, the primary flow is:

```text
Create Visual Agent
  -> Brief
  -> Canvas
  -> Test Lab
  -> Release
  -> Usage
```

## Decisions

| Area | Decision | Rationale |
| --- | --- | --- |
| Agent type | Build mode is locked at creation | Avoid ambiguous conversion between prompt, visual, and code definitions |
| Visual Agent entry | First use is goal-first; normal use is canvas-first | Avoid blank-canvas confusion while preserving visual orchestration as the core workspace |
| Product shell | One Agent Studio with stage navigation | Prevent Build, Versions, Releases, Runs, and Chat from fragmenting the workflow |
| Copilot role | Construction assistant, not normal chat | Copilot should mutate or explain the draft with context-aware actions |
| Component adding | Canvas action, not a right-sidebar tab | Keeps right side available for Copilot and Inspector |
| Draft testing | Test Lab runs the editable draft only | Prevents draft debugging from affecting business usage |
| Published usage | Agent Chat, Tasks, API, and business runs use the active release | Gives users a stable external target |

## Non-Goals

- This design does not redesign Prompt Agent or Code Agent workspaces in detail.
- This design does not change the backend AgentVersion or AgentRelease model.
- This design does not move full business monitoring into the builder.
- This design does not require removing drag-and-drop node adding; it demotes it from the primary layout model.

## Information Architecture

The frontend should expose two main levels:

```text
/agents
  Agent list
  Create Agent
  Filter by build mode and status

/agents/:agentId
  Type-specific Agent workspace
```

For `build_mode = visual`, `/agents/:agentId` opens Visual Agent Studio:

```text
Top bar
  Agent name
  Build mode
  Draft status
  Published status
  Primary next action

Left rail
  Brief
  Canvas
  Test Lab
  Release
  Usage

Center
  Active stage workspace

Right panel
  Copilot when no object is selected
  Inspector when a node, edge, test, release, or usage target is selected
```

Routes that should be folded into Studio:

| Current Surface | Target Placement |
| --- | --- |
| `/agents/:id/build` | Studio Canvas |
| `/agents/:id/versions` | Studio Release history |
| `/agents/:id/releases` | Studio Release |
| `/agents/:id/runs` | Removed as Agent management surface; business runs belong to Task/Execution |
| `/agents/:id/threads` | Usage or published Agent Chat entry, not construction flow |

## Studio Stages

### Brief

Brief is the first-run surface for an empty Visual Agent and an optional reset/rethink surface later.

It captures structured intent:

```text
What problem should this Agent solve?
What input does it receive?
What output should it produce?
What tools or Skills does it need?
What safety, approval, or human-confirmation rules apply?
Where will it be used after publishing?
```

After submission, Copilot should generate:

- Initial graph nodes and edges
- Suggested tools and Skills
- Default variables or inputs
- Initial test cases
- Missing configuration checklist

The user then moves into Canvas.

### Canvas

Canvas is the normal main workspace for a Visual Agent. It should remain visually and behaviorally centered on React Flow orchestration.

Recommended layout:

```text
Top toolbar
  Save
  Run Draft
  Publish
  More

Center
  Visual graph canvas

Right panel
  Copilot when nothing is selected
  Inspector when an editable object is selected
```

Node/component adding should move from a persistent right-sidebar tab to canvas-native actions:

| Interaction | Behavior |
| --- | --- |
| `+ Add` toolbar button | Opens searchable node palette |
| Canvas right-click | Opens context menu and adds the selected node at cursor position |
| Edge midpoint `+` | Inserts a node between connected nodes |
| Drag from palette | Remains supported as an advanced/manual path |
| Copilot operation | Uses the same add/update/connect command layer |

This preserves the underlying `addNode(type, position, label)` model while removing the need for a permanent `Components` tab beside Copilot.

Right panel behavior:

| State | Right Panel |
| --- | --- |
| Nothing selected | Copilot construction assistant |
| Node selected | Node Inspector |
| Edge selected | Edge Inspector |
| Test failure selected | Copilot repair suggestions |
| Release selected | Release details |

### Test Lab

Test Lab validates the current editable draft. It does not run or change the published Agent.

Capabilities:

- Run the draft with ad hoc input
- Save reusable test cases
- Stream execution events
- Show tool calls, errors, artifacts, and final output
- Compare recent draft test results
- Trigger "Fix with Copilot" based on a failed test

Terminology should avoid calling this Chat:

```text
Run Draft
Test Run
Debug Draft
```

Test Lab runs against the draft version or draft graph backing store. It must not create the impression that business users are affected by failed tests.

### Release

Release is where the user converts a working draft into something stable for business use.

The user-facing actions are:

```text
Create Version from Draft
Publish Version
Activate Release
Rollback Release
View Release History
```

Recommended terminology:

| Term | Meaning |
| --- | --- |
| Draft | Current editable state |
| Version | Immutable snapshot created from a draft |
| Published Release | Version currently available to external/business usage |

Release should not expose backend naming or deployment internals as primary navigation. Users should experience this as "I am publishing the Agent I have tested."

### Usage

Usage bridges Studio to business scenarios after a release is active.

It should expose:

- Create Task
- Start Chat with published Agent
- Copy API endpoint or integration snippet
- Bind to business scenario
- View recent business executions

Usage may show a compact recent-run summary, but full monitoring belongs to Dashboard, Task Detail, and Execution views.

## Copilot, Chat, Test, and Business Run Boundaries

The product should enforce four distinct concepts:

```text
Copilot = construction assistant
Agent Chat = conversation with active release
Test Lab = draft validation
Business Run = production/business execution
```

### Copilot

Copilot lives in Agent Studio and operates on the draft.

Allowed behaviors:

- Generate initial graph
- Explain current graph
- Add, remove, or modify nodes
- Connect graph paths
- Fill tool and Skill configuration
- Generate test cases
- Diagnose test failures
- Propose release-readiness fixes

Copilot responses should prefer structured operations over plain advice:

```text
Add node: Web Recon
Connect: Input -> Web Recon
Update config: timeout = 60s
Create test case: example.com
```

### Agent Chat

Agent Chat is for interacting with the published Agent. It uses the active release.

Rules:

- Agent Chat does not edit the draft.
- Agent Chat does not run unpublished changes.
- Issues discovered in chat can be sent back to Studio as a fix request or test case.

### Test Lab

Test Lab runs draft behavior inside the construction workflow.

Rules:

- Test Lab can use current unsafely edited draft state.
- Test Lab results can drive Copilot repair operations.
- Test Lab failures do not imply published Agent failure.

### Business Run

Business Runs are triggered by Tasks, APIs, schedules, or business scenarios. They use the active release.

Rules:

- Business Runs are monitored in Task/Execution surfaces.
- Business Runs should not be mixed with draft test history.
- Retrying a Business Run should not mutate the Agent draft.

## State Model

Visual Agent Studio should make this state relationship visible:

```text
Draft
  Editable
  Used by Canvas, Copilot, and Test Lab
  Does not affect business usage

Version
  Immutable snapshot created from Draft
  Candidate for publishing or rollback

Active Release
  Published target used by Agent Chat, Task, API, and Business Run
  Stable external behavior
```

The top bar should answer:

- Am I editing a draft?
- Is the draft different from the active release?
- Is there an active release?
- What is the next recommended action?

## User Flows

### First-Time Visual Agent Build

```text
Create Agent -> choose Visual Agent
Brief -> describe goal and constraints
Copilot generates graph and test cases
Canvas -> review and edit graph
Test Lab -> run draft
Fix with Copilot or edit manually
Release -> publish tested version
Usage -> create Task, chat with published Agent, or copy API
```

### Existing Visual Agent Edit

```text
Open Agent -> Studio opens at Canvas
Edit draft manually or with Copilot
Run Draft in Test Lab
Publish when ready
Usage shows updated active release after activation
```

### Debug From Published Usage

```text
Business Run or Agent Chat exposes issue
User sends issue to Studio
Studio creates test case from failing input
Test Lab reproduces against draft
Copilot proposes fix
User validates and publishes new release
```

## Interaction Guardrails

- Do not show Copilot and Components as equal right-panel tabs.
- Do not call draft testing "Chat".
- Do not show Version and Release as top-level Agent management pages for normal users.
- Do not put full business monitoring inside Studio.
- Do not let Agent Chat silently run drafts.
- Do not let Copilot modify active releases directly.
- Do not make an empty canvas the first screen for a new Visual Agent.

## Implementation Notes

The current Graph Builder already has useful primitives:

- `BuilderCanvas` supports drag-and-drop and calls `addNode(type, position, label)`.
- `BuilderToolbar` already exposes run and publish actions.
- `BuilderSidebarTabs` currently makes Copilot and Components compete in a tab set.
- `ComponentsSidebar` can be reused as the content of an Add Node palette.
- `PropertiesPanel` and `EdgePropertiesPanel` can become the Inspector side of the right panel.

Recommended frontend refactoring direction:

- Replace `BuilderSidebarTabs` with an Agent Studio right-panel controller.
- Move `ComponentsSidebar` into a searchable Add Node palette and context menu.
- Keep `CopilotPanel` as the default right panel when no canvas object is selected.
- Reuse node registry and `addNode` for toolbar, right-click, edge insert, drag, and Copilot operations.
- Move deployment history into the Release stage, not the toolbar overflow as the primary route.
- Move execution panel behavior into Test Lab for draft runs.

## Success Criteria

- A new user can create a Visual Agent without facing an empty canvas first.
- A returning user can immediately edit the graph without going through a wizard.
- Users can tell whether they are testing a draft or using the published Agent.
- Copilot is perceived as a builder action layer, not a separate chat product.
- Version and release management support publishing without becoming the primary mental model.
- Business usage has a clear next step after publish.

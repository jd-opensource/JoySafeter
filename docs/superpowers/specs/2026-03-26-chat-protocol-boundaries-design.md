# Chat Protocol Boundaries Design

## Goal

Keep the Chat UI unified while separating protocol-level control flow from mode-specific business semantics. In particular, `skill_creator` should remain a first-class workflow, but it must no longer leak into the generic chat transport contract or share validation paths with unrelated chat modes.

## Problem Summary

The current `/ws/chat` protocol mixes three concerns in one payload:

- generic turn transport (`request_id`, `thread_id`, `graph_id`, `message`)
- mode-specific control fields (`mode`, `edit_skill_id`, `run_id`)
- free-form metadata (`files`, UI context, tracing hints)

That coupling caused a regression on 2026-03-26: frontend chat pages sent a general `metadata.mode` value such as `apk-vulnerability`, while the backend promoted that free-form value into `ChatRequest.mode`, whose schema only allowed `"skill_creator"`. The failure happened inside the async task setup path, so the client observed a hung request with no terminal event and no working cancel path.

This is not a one-off bug. The structure is wrong:

- `metadata` is being used as both extensible context and protocol control
- generic chat request types include `skill_creator`-specific fields
- validation occurs too late, after task creation begins
- stop/cancel relies too heavily on `thread_id`, which may not exist yet

## Design Principles

- Generic chat transport must not know business-specific extension fields.
- Mode-specific workflows must use explicit typed extensions, not `metadata` conventions.
- All protocol validation must complete before creating an asyncio task.
- Every accepted `request_id` must end in a terminal outcome visible to the client.
- Cancel must work by `request_id` first and use `thread_id` only as a secondary mapping.

## Target Protocol

### Client-to-server start frame

Replace the implicit `metadata.mode` contract with an explicit extension envelope.

```jsonc
{
  "type": "chat.start",
  "request_id": "<uuid>",
  "thread_id": "<string|null>",
  "graph_id": "<uuid|null>",
  "input": {
    "message": "<string>",
    "files": [
      {
        "filename": "<string>",
        "path": "<string>",
        "size": 123
      }
    ]
  },
  "extension": null,
  "metadata": {}
}
```

For `skill_creator`:

```jsonc
{
  "type": "chat.start",
  "request_id": "<uuid>",
  "thread_id": "<string|null>",
  "graph_id": "<uuid|null>",
  "input": {
    "message": "<string>",
    "files": []
  },
  "extension": {
    "kind": "skill_creator",
    "run_id": "<uuid|null>",
    "edit_skill_id": "<string|null>"
  },
  "metadata": {}
}
```

### Resume and stop frames

Resume remains a separate frame. Stop continues to accept `request_id`, but the client must treat `request_id` as the primary handle for active turns.

```jsonc
{ "type": "chat.resume", "request_id": "<uuid>", "thread_id": "<string>", "command": {} }
{ "type": "chat.stop", "request_id": "<uuid>" }
```

### Metadata rule

`metadata` remains available for loose auxiliary data, but it is forbidden from carrying protocol control fields such as:

- `mode`
- `run_id`
- `edit_skill_id`
- extension kind selectors

## Backend Architecture

Split the current `chat_ws_handler.py` responsibilities into four layers.

### 1. `ChatFrameParser`

Responsibilities:

- parse raw websocket JSON frames
- validate the transport schema synchronously
- reject invalid frames before creating tasks
- output typed parsed frames

Output types:

- `ParsedChatStartFrame`
- `ParsedChatResumeFrame`
- `ParsedChatStopFrame`

This layer owns protocol errors such as:

- missing `request_id`
- malformed `input`
- invalid `extension.kind`
- forbidden control fields inside `metadata`

All such failures return `ws_error` immediately.

### 2. `ChatCommandFactory`

Responsibilities:

- convert parsed transport frames into business commands
- keep generic chat and `skill_creator` commands distinct

Output command types:

- `StandardChatTurnCommand`
- `SkillCreatorTurnCommand`
- `ResumeChatTurnCommand`

This is the only layer that knows how an extension kind maps to business behavior.

### 3. `ChatTaskSupervisor`

Responsibilities:

- create and register turn tasks
- maintain `request_id -> task entry`
- maintain `thread_id -> latest active request_id`
- centralize stop, disconnect, and cleanup behavior
- guarantee terminal cleanup for every request

Task entry should contain at least:

- `request_id`
- `thread_id`
- `task`
- `run_id`
- `heartbeat_task`
- `persist_on_disconnect`

Rules:

- stop by `request_id` is the primary path
- stop by `thread_id` is a compatibility helper, not the core contract
- disconnect cleanup and explicit stop must both go through the same supervisor finalization path

### 4. `ChatTurnExecutor`

Responsibilities:

- run the actual graph turn for a validated business command
- stream normalized events back to the supervisor/emitter
- keep standard chat and `skill_creator` execution branches separate

The executor receives already-validated command objects. It must not infer workflow kind from loose metadata.

## Frontend Architecture

### Page and feature layer

The page decides which workflow to invoke:

- normal chat pages send no extension
- skill creator pages send `extension.kind = "skill_creator"`

Product mode names such as `default-chat` or `apk-vulnerability` remain a UI concern. They are not protocol-level workflow selectors.

### Chat transport layer

Replace the current `sendChat` request shape with a typed transport request:

```ts
type ChatSendRequest = {
  threadId?: string | null
  graphId?: string | null
  input: {
    message: string
    files?: UploadedFileRef[]
  }
  extension?: {
    kind: 'skill_creator'
    runId?: string | null
    editSkillId?: string | null
  } | null
  metadata?: Record<string, unknown>
}
```

Client changes:

- `useChatWebSocket` tracks `activeRequestId` and `activeThreadId` separately
- stop uses `requestId` first
- `threadId` is populated later from `accepted` and subsequent stream events
- `metadata.mode` is removed from generic chat sends

## Failure Semantics

The websocket contract must guarantee one of two outcomes for every inbound start frame:

1. synchronous rejection before task creation
   - server sends `ws_error`
   - no task is registered

2. accepted task lifecycle
   - server sends `accepted`
   - task eventually yields `done`, `interrupt`, or `error`
   - supervisor always clears active request bookkeeping

This removes the current failure mode where a request appears active in the UI but no terminal event is ever emitted.

## Migration Plan

### Phase 1: Introduce typed transport without deleting old paths

- add parser and typed start-frame schema
- add `extension.kind = "skill_creator"` support
- continue accepting legacy `type: "chat"` frames temporarily
- continue tolerating old `metadata.mode` only for backwards compatibility

Compatibility behavior in this phase:

- legacy `metadata.mode == "skill_creator"` maps to the new extension
- any other `metadata.mode` is ignored for protocol purposes

### Phase 2: Frontend switches to explicit extension protocol

- update chat client request types
- update standard chat pages to stop sending `metadata.mode`
- update skill creator pages to send `extension.kind = "skill_creator"`
- move stop UI to `requestId`-first behavior

### Phase 3: Remove metadata-driven control flow

- delete backend code that derives protocol control fields from `metadata`
- delete compatibility parsing for `metadata.mode`
- forbid reserved control keys in `metadata`

### Phase 4: Cleanup and consolidation

- simplify `ChatRequest` into either:
  - a generic turn input model with no extension-specific fields, or
  - multiple explicit command models used after parsing
- fold stop/disconnect cleanup into supervisor-owned finalization
- refresh websocket protocol tests and documentation

## Risks and Tradeoffs

### Risk: temporary protocol duality

During migration both old and new frame shapes may be supported. This increases short-term complexity, but it keeps rollout risk low and avoids hard-cutting the frontend and backend in one step.

### Risk: hidden metadata consumers

Existing code may rely on `metadata.mode`, `metadata.run_id`, or `metadata.edit_skill_id`. Before deleting compatibility behavior, all call sites must be identified and updated.

### Risk: partial lifecycle refactor

If parsing is separated but task supervision is not centralized, the codebase will keep the same failure semantics problems. The supervisor layer is not optional.

## Testing Strategy

### Backend

- parser unit tests for valid and invalid start frames
- command factory tests for standard chat vs `skill_creator`
- websocket handler tests for:
  - invalid frame rejected before task creation
  - accepted start frame emits `accepted`
  - non-`skill_creator` UI modes never touch extension validation
  - stop by `request_id` works before `thread_id` is known
  - disconnect finalization clears active tasks

### Frontend

- chat hook tests verifying:
  - standard sends omit extension
  - skill creator sends explicit extension
  - stop uses `requestId`
  - missing `threadId` does not block cancel
- integration tests for request lifecycle:
  - send -> accepted -> done
  - send -> ws_error
  - send -> stop before thread assignment

## Acceptance Criteria

- Generic chat no longer sends or depends on `metadata.mode`.
- `skill_creator` workflow uses an explicit extension object.
- Backend does not construct business semantics from free-form metadata.
- Invalid protocol input fails synchronously with `ws_error`.
- An active UI request is always represented by a `request_id`, even before `thread_id` exists.
- Stop works reliably before `accepted.thread_id` arrives.
- The regression where normal chat modes are rejected by `Literal["skill_creator"]` cannot recur by construction.

# Unify mode→graph_id Routing

**Date:** 2026-03-18
**Status:** Approved

## Problem

`ChatRequest.mode` field creates a parallel routing path that only accepts `Literal["skill_creator"]`. The frontend `chatBackend.ts` unconditionally promotes `metadata.mode` (a UI concept) to this top-level field, causing 422 errors when non-skill-creator modes (e.g., `apk-vulnerability`) are selected.

## Decision

Remove `mode` and `edit_skill_id` from `ChatRequest`. All chat routing goes through `graph_id`. The `skill_creator` becomes a graph template like `apk-detector` and `default-chat`.

## Design

### Backend Changes

1. **`ChatRequest` schema** (`backend/app/schemas/chat.py`):
   - Remove `mode` field
   - Remove `edit_skill_id` field

2. **`chat.py` API endpoints** (both `/chat` and `/chat/stream`):
   - Remove the `if payload.mode == "skill_creator"` branch
   - Routing simplifies to: `graph_id` provided → `create_graph_by_graph_id()`, otherwise → `create_default_deep_agents_graph()`
   - `edit_skill_id` extracted from `payload.metadata.get("edit_skill_id")` and injected into `enriched_message` (same pattern as `files`)

3. **`graph_service.py`**:
   - `create_skill_creator_graph()` method can be removed (the template JSON replaces it)

### Frontend Changes

4. **New template file** (`frontend/public/data/graph-templates/skill-creator.json`):
   - Single DeepAgents node with the skill creator system prompt, tools (`preview_skill`, `tavily_search`, `think_tool`), and `skills: ["*"]`
   - Structure mirrors `apk-detector.json`

5. **`modeConfig.ts`**:
   - Change `skill-creator` entry from `type: 'simple'` to `type: 'template'` with `templateName: 'skill-creator'`, `templateGraphName: 'Skill Creator'`

6. **New `skillCreatorHandler.ts`** (`frontend/app/chat/services/modeHandlers/`):
   - Follows same pattern as `apkVulnerabilityHandler.ts`: find-or-create graph by name

7. **`handlerFactory.ts`**:
   - Add `skill-creator` case routing to the new handler

8. **`chatBackend.ts`** (`frontend/services/chatBackend.ts`):
   - Remove the `mode` extraction/promotion logic entirely
   - Remove `edit_skill_id` extraction — leave it in `metadata` for the backend to read

9. **`skills/creator/page.tsx`**:
   - Replace `metadata: { mode: 'skill_creator' }` with proper `graphId` resolution via `graphResolutionService` or direct graph lookup
   - `edit_skill_id` stays in `metadata`

### Tests

10. **Backend tests**:
    - Update `test_chat.py` schema tests (remove mode/edit_skill_id field tests)
    - Update `test_skill_creator.py` integration tests to use `graph_id` instead of `mode`

## Migration Path

No database migration needed. The template JSON is a static file. First-time use auto-creates the graph instance (lazy initialization, same as apk-detector).

# Skill Creator Agent — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow users to create/modify Skills through AI Agent conversation in a Docker sandbox, preview results, and save to DB after confirmation.

**Architecture:** Reuse existing `/v1/chat/stream` SSE architecture with a new `mode="skill_creator"` parameter. A dedicated `create_skill_creator_graph()` method in `GraphService` creates a single-node DeepAgents graph with skill-creator system prompt. The `preview_skill` builtin tool reads generated files from the sandbox for frontend rendering. Frontend adds a Skill Creator page with chat + preview panel layout, and a Dashboard entry card.

**Tech Stack:** FastAPI, LangGraph, DeepAgents, Docker Sandbox (pydantic-ai-backend), Next.js 16 (App Router), React 19, TypeScript, Zustand, TanStack Query

**Spec:** `docs/superpowers/specs/2026-03-18-skill-creator-agent-design.md`

---

## File Structure

### Backend — New Files

| File | Responsibility |
|------|---------------|
| `backend/app/core/tools/buildin/preview_skill.py` | `preview_skill` tool: reads skill files from sandbox host path, validates, returns structured JSON |

### Backend — Modified Files

| File | Change |
|------|--------|
| `backend/app/schemas/chat.py` | Add `mode` and `edit_skill_id` fields to `ChatRequest` |
| `backend/app/api/v1/chat.py` | Handle `mode="skill_creator"` branch in `chat_stream` and `chat` |
| `backend/app/services/graph_service.py` | Add `create_skill_creator_graph()` method |
| `backend/app/core/tools/tool_registry.py` | Register `preview_skill` in `_initialize_builtin_tools()` |

### Frontend — New Files

| File | Responsibility |
|------|---------------|
| `frontend/app/skills/creator/page.tsx` | Skill Creator page (route: `/skills/creator`) |
| `frontend/app/skills/creator/components/SkillCreatorChat.tsx` | Chat panel wrapping `ChatInterface` with `mode=skill_creator` |
| `frontend/app/skills/creator/components/SkillPreviewPanel.tsx` | Right panel: file tree + content viewer + save button |
| `frontend/app/skills/creator/components/SkillFileTree.tsx` | File directory tree |
| `frontend/app/skills/creator/components/SkillFileViewer.tsx` | Single file content with syntax highlighting |
| `frontend/app/skills/creator/components/SkillSaveDialog.tsx` | Confirmation dialog before saving to DB |

### Frontend — Modified Files

| File | Change |
|------|--------|
| `frontend/app/chat/hooks/useBackendChatStream.ts` | Pass `mode` through to backend in `streamChat` call |
| `frontend/app/skills/page.tsx` | Add "AI Create" button linking to `/skills/creator` |
| `frontend/app/chat/components/ChatHome.tsx` | Add Skill Creator entry card on chat home |

---

## Task 1: Backend — Extend ChatRequest Schema

**Files:**
- Modify: `backend/app/schemas/chat.py:8-15`
- Test: `backend/tests/test_schemas/test_chat.py` (create if needed)

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_schemas/test_chat.py
from app.schemas.chat import ChatRequest


def test_chat_request_with_mode():
    req = ChatRequest(
        message="Create a skill",
        mode="skill_creator",
        edit_skill_id="some-uuid-string",
    )
    assert req.mode == "skill_creator"
    assert req.edit_skill_id == "some-uuid-string"


def test_chat_request_mode_defaults_to_none():
    req = ChatRequest(message="Hello")
    assert req.mode is None
    assert req.edit_skill_id is None


def test_chat_request_mode_validation():
    """mode must be None or 'skill_creator'"""
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ChatRequest(message="Hello", mode="invalid_mode")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_schemas/test_chat.py -v`
Expected: FAIL — `ChatRequest` doesn't accept `mode` or `edit_skill_id`

- [ ] **Step 3: Implement schema changes**

Edit `backend/app/schemas/chat.py`:

```python
from typing import Any, Literal

class ChatRequest(PydanticBaseModel):
    message: str = Field(..., description="用户消息")
    thread_id: str | None = Field(None, description="会话线程ID，不提供则创建新会话")
    graph_id: uuid.UUID | None = Field(None, description="图ID，使用指定的图进行对话")
    metadata: dict[str, Any] = Field(default_factory=dict, description="元数据")
    mode: Literal["skill_creator"] | None = Field(None, description="特殊模式: skill_creator 使用 Skill 创建专用 Graph")
    edit_skill_id: str | None = Field(None, description="修改已有 Skill 时传入 Skill ID")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_schemas/test_chat.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas/chat.py backend/tests/test_schemas/test_chat.py
git commit -m "feat(schema): add mode and edit_skill_id to ChatRequest"
```

---

## Task 2: Backend — preview_skill Builtin Tool

**Files:**
- Create: `backend/app/core/tools/buildin/preview_skill.py`
- Test: `backend/tests/test_tools/test_preview_skill.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_tools/test_preview_skill.py
import json
import os
import tempfile
from pathlib import Path

import pytest

from app.core.tools.buildin.preview_skill import preview_skill_in_sandbox


@pytest.fixture
def skill_dir():
    """Create a temporary skill directory with SKILL.md and a script."""
    with tempfile.TemporaryDirectory() as tmpdir:
        skill_path = Path(tmpdir) / "skills" / "test-skill"
        skill_path.mkdir(parents=True)

        # Write SKILL.md
        skill_md = skill_path / "SKILL.md"
        skill_md.write_text(
            "---\nname: test-skill\ndescription: A test skill\n---\n# Test Skill\nInstructions here."
        )

        # Write a script
        scripts_dir = skill_path / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "run.py").write_text("print('hello')")

        yield tmpdir


def test_preview_skill_returns_structured_output(skill_dir):
    result = preview_skill_in_sandbox(
        skill_name="test-skill",
        sandbox_root=skill_dir,
    )
    data = json.loads(result)
    assert data["skill_name"] == "test-skill"
    assert len(data["files"]) == 2
    assert data["validation"]["valid"] is True

    file_paths = [f["path"] for f in data["files"]]
    assert "SKILL.md" in file_paths
    assert "scripts/run.py" in file_paths


def test_preview_skill_missing_skill_md(skill_dir):
    """A skill without SKILL.md should fail validation."""
    skill_path = Path(skill_dir) / "skills" / "bad-skill"
    skill_path.mkdir(parents=True)
    (skill_path / "readme.txt").write_text("no skill md")

    result = preview_skill_in_sandbox(
        skill_name="bad-skill",
        sandbox_root=skill_dir,
    )
    data = json.loads(result)
    assert data["validation"]["valid"] is False
    assert any("SKILL.md" in e for e in data["validation"]["errors"])


def test_preview_skill_nonexistent_dir(skill_dir):
    result = preview_skill_in_sandbox(
        skill_name="nonexistent",
        sandbox_root=skill_dir,
    )
    data = json.loads(result)
    assert data["validation"]["valid"] is False
    assert any("not found" in e.lower() for e in data["validation"]["errors"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_tools/test_preview_skill.py -v`
Expected: FAIL — `ImportError: cannot import name 'preview_skill_in_sandbox'`

- [ ] **Step 3: Implement preview_skill tool**

Create `backend/app/core/tools/buildin/preview_skill.py`:

```python
"""preview_skill — reads generated skill files from sandbox and returns structured JSON."""
import json
from pathlib import Path
from typing import Optional

from app.core.skill.validators import (
    validate_skill_description,
    validate_skill_name,
)
from app.core.skill.yaml_parser import parse_skill_md


def _detect_file_type(path: str) -> str:
    ext_map = {
        ".py": "python",
        ".md": "markdown",
        ".json": "json",
        ".yaml": "yaml",
        ".yml": "yaml",
        ".txt": "text",
        ".sh": "shell",
        ".js": "javascript",
        ".ts": "typescript",
    }
    suffix = Path(path).suffix.lower()
    return ext_map.get(suffix, "text")


def preview_skill_in_sandbox(
    skill_name: str,
    sandbox_root: str,
    skills_subdir: str = "skills",
) -> str:
    """Read all files from a skill directory in the sandbox and return structured JSON.

    Args:
        skill_name: Directory name under /workspace/skills/ in the sandbox.
        sandbox_root: Host-side sandbox root (e.g., /tmp/sandboxes/{user_id}).
        skills_subdir: Subdirectory within sandbox_root where skills live.

    Returns:
        JSON string with skill_name, files[], and validation{}.
    """
    skill_dir = Path(sandbox_root) / skills_subdir / skill_name
    errors: list[str] = []
    warnings: list[str] = []
    files: list[dict] = []

    if not skill_dir.exists() or not skill_dir.is_dir():
        return json.dumps(
            {
                "skill_name": skill_name,
                "files": [],
                "validation": {
                    "valid": False,
                    "errors": [f"Skill directory not found: {skill_name}"],
                    "warnings": [],
                },
            },
            ensure_ascii=False,
        )

    # Collect all files recursively
    for file_path in sorted(skill_dir.rglob("*")):
        if not file_path.is_file():
            continue
        rel_path = str(file_path.relative_to(skill_dir))
        try:
            content = file_path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            content = f"[Binary or unreadable file: {rel_path}]"
        files.append(
            {
                "path": rel_path,
                "content": content,
                "file_type": _detect_file_type(rel_path),
                "size": file_path.stat().st_size,
            }
        )

    # Validate: SKILL.md must exist
    skill_md_files = [f for f in files if f["path"] == "SKILL.md"]
    if not skill_md_files:
        errors.append("Missing required file: SKILL.md")
    else:
        # Parse and validate frontmatter
        skill_md_content = skill_md_files[0]["content"]
        try:
            frontmatter, body = parse_skill_md(skill_md_content)
            name = frontmatter.get("name", "")
            description = frontmatter.get("description", "")

            name_valid, name_msg = validate_skill_name(name)
            if not name_valid:
                errors.append(f"Name validation: {name_msg}")

            desc_valid, desc_msg = validate_skill_description(description)
            if not desc_valid:
                errors.append(f"Description validation: {desc_msg}")

            if not body.strip():
                warnings.append("SKILL.md body is empty")

        except Exception as e:
            errors.append(f"Failed to parse SKILL.md: {e}")

    return json.dumps(
        {
            "skill_name": skill_name,
            "files": files,
            "validation": {
                "valid": len(errors) == 0,
                "errors": errors,
                "warnings": warnings,
            },
        },
        ensure_ascii=False,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_tools/test_preview_skill.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/core/tools/buildin/preview_skill.py backend/tests/test_tools/test_preview_skill.py
git commit -m "feat(tools): add preview_skill builtin tool"
```

---

## Task 3: Backend — Register preview_skill in Tool Registry

**Files:**
- Modify: `backend/app/core/tools/tool_registry.py:611-652`

- [ ] **Step 1: Add import and registration**

Edit `backend/app/core/tools/tool_registry.py`, inside `_initialize_builtin_tools()`, after the existing `skill_tools.deploy_local_skill` registration block:

```python
from app.core.tools.buildin.preview_skill import preview_skill_in_sandbox

registry.register_builtin(
    callable_func=preview_skill_in_sandbox,
    name="preview_skill",
    description="Preview a skill generated in the sandbox. Reads all files from the skill directory and returns structured JSON with file contents and validation results.",
    category="skill",
    tags={"skill", "preview", "sandbox"},
)
```

- [ ] **Step 2: Verify import works**

Run: `cd backend && python -c "from app.core.tools.buildin.preview_skill import preview_skill_in_sandbox; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add backend/app/core/tools/tool_registry.py
git commit -m "feat(tools): register preview_skill in builtin tool registry"
```

---

## Task 4: Backend — GraphService.create_skill_creator_graph()

**Files:**
- Modify: `backend/app/services/graph_service.py:667-744` (add method after `create_default_deep_agents_graph`)

- [ ] **Step 1: Read the existing `create_default_deep_agents_graph` method**

Read `backend/app/services/graph_service.py` lines 667-744 to understand the exact pattern.

- [ ] **Step 2: Implement `create_skill_creator_graph()`**

Add new method to `GraphService` class, following the same pattern as `create_default_deep_agents_graph`:

```python
async def create_skill_creator_graph(
    self,
    llm_model: Optional[str] = None,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    max_tokens: int = 4096,
    user_id: Optional[Any] = None,
    edit_skill_id: Optional[str] = None,
) -> CompiledStateGraph:
    """Create a specialized graph for the Skill Creator Agent.

    Uses the same single-node DeepAgents pattern as the default graph,
    but with a skill-creator-specific system prompt and tool configuration.
    """
    from app.core.skill.sandbox_loader import SkillSandboxLoader

    # Build skill creator system prompt
    skill_creator_system_prompt = (
        "You are a Skill Creator Agent. Your job is to help users create and modify "
        "Skills (reusable capability packages) through conversation.\n\n"
        "## Workflow\n"
        "1. Understand the user's requirements through conversation\n"
        "2. Use init_skill.py to initialize the skill directory structure\n"
        "3. Write SKILL.md with proper YAML frontmatter (name, description) + markdown body\n"
        "4. Create supporting files in scripts/, references/, assets/ as needed\n"
        "5. Run quick_validate.py to validate the skill\n"
        "6. Call the preview_skill tool to output the final result for user review\n\n"
        "## Rules\n"
        "- Skill names must match: ^[a-z0-9]+(-[a-z0-9]+)*$ (max 64 chars)\n"
        "- SKILL.md is required with YAML frontmatter containing 'name' and 'description'\n"
        "- Always validate before previewing\n"
        "- The skill-creator skill is pre-loaded at /workspace/skills/skill-creator/ — "
        "use its scripts (init_skill.py, quick_validate.py) and references for guidance\n"
    )

    if edit_skill_id:
        skill_creator_system_prompt += (
            f"\n## Editing Mode\n"
            f"The user wants to modify an existing skill (ID: {edit_skill_id}). "
            f"The skill files have been pre-loaded into the sandbox. "
            f"Read the existing files first, then apply the user's requested changes.\n"
        )

    graph_id = uuid.uuid4()
    graph = AgentGraph(
        id=graph_id,
        name="Skill Creator",
        description="AI-powered skill creation and modification",
    )

    node = GraphNode(
        id=uuid.uuid4(),
        graph_id=graph_id,
        type="agent",
        data={
            "label": "Skill Creator Agent",
            "config": {
                "useDeepAgents": True,
                "skills": ["*"],
                "mode": "skill_creator",
                "system_prompt": skill_creator_system_prompt,
            },
        },
        position={"x": 0, "y": 0},
    )

    builder = GraphBuilder(
        graph=graph,
        nodes=[node],
        edges=[],
        llm_model=llm_model,
        api_key=api_key,
        base_url=base_url,
        max_tokens=max_tokens,
        user_id=user_id,
    )
    return await builder.build()
```

- [ ] **Step 3: Verify no import errors**

Run: `cd backend && python -c "from app.services.graph_service import GraphService; print('OK')"`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/graph_service.py
git commit -m "feat(graph): add create_skill_creator_graph() to GraphService"
```

---

## Task 5: Backend — Wire mode="skill_creator" into Chat Stream

**Files:**
- Modify: `backend/app/api/v1/chat.py:694-713` (inside `event_generator()` in `chat_stream`)

- [ ] **Step 1: Read the current branching logic**

Read `backend/app/api/v1/chat.py` lines 690-720 to see the exact graph creation branch.

- [ ] **Step 2: Add skill_creator mode branch**

Insert the new branch between `graph_service = GraphService(db)` (line 694) and `if payload.graph_id is None` (line 695):

```python
graph_service = GraphService(db)

# Skill Creator mode — dedicated graph
if payload.mode == "skill_creator":
    graph = await graph_service.create_skill_creator_graph(
        llm_model=llm_model,
        api_key=api_key,
        base_url=base_url,
        max_tokens=max_tokens,
        user_id=str(current_user.id),
        edit_skill_id=payload.edit_skill_id,
    )
elif payload.graph_id is None:
    # ... existing default graph creation
```

Also add the same branch in the non-streaming `chat` endpoint (around lines 554-573) following the identical pattern.

- [ ] **Step 3: Handle edit_skill_id preloading**

After the graph is created in skill_creator mode, add skill preloading logic. If `edit_skill_id` is provided, load the target skill into the sandbox before the agent starts:

```python
if payload.mode == "skill_creator" and payload.edit_skill_id:
    try:
        from app.core.skill.sandbox_loader import SkillSandboxLoader
        from app.services.skill_service import SkillService

        skill_service = SkillService(db)
        loader = SkillSandboxLoader(db, user_id=str(current_user.id))
        # The sandbox backend will be available from the graph's agent node
        # Preloading happens at graph build time via DeepAgentsGraphBuilder
    except Exception as e:
        logger.warning(f"Failed to preload skill for editing: {e}")
```

Note: The actual preloading mechanism depends on how `DeepAgentsGraphBuilder` initializes the sandbox. The `edit_skill_id` is passed into the graph config so the builder can handle it during `build()`. Verify by reading `deep_agents_builder.py` before implementing this step.

- [ ] **Step 4: Test manually**

Run: `cd backend && python -c "from app.api.v1.chat import router; print('Router loaded OK')"`
Expected: `OK` (no import errors)

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/v1/chat.py
git commit -m "feat(chat): wire mode=skill_creator into chat_stream endpoint"
```

---

## Task 6: Frontend — Skill Creator Page Layout

**Files:**
- Create: `frontend/app/skills/creator/page.tsx`

- [ ] **Step 1: Create the page**

```tsx
// frontend/app/skills/creator/page.tsx
"use client";

import { useSearchParams } from "next/navigation";
import { useState, useCallback } from "react";
import { SkillCreatorChat } from "./components/SkillCreatorChat";
import { SkillPreviewPanel } from "./components/SkillPreviewPanel";

export interface SkillPreviewData {
  skill_name: string;
  files: Array<{
    path: string;
    content: string;
    file_type: string;
    size: number;
  }>;
  validation: {
    valid: boolean;
    errors: string[];
    warnings: string[];
  };
}

export default function SkillCreatorPage() {
  const searchParams = useSearchParams();
  const editSkillId = searchParams.get("edit");
  const [previewData, setPreviewData] = useState<SkillPreviewData | null>(null);

  const handlePreviewUpdate = useCallback((data: SkillPreviewData) => {
    setPreviewData(data);
  }, []);

  return (
    <div className="flex h-full w-full">
      {/* Left: Chat panel */}
      <div className="flex-1 min-w-0 border-r border-border">
        <SkillCreatorChat
          editSkillId={editSkillId}
          onPreviewUpdate={handlePreviewUpdate}
        />
      </div>

      {/* Right: Preview panel */}
      <div className="w-[480px] shrink-0">
        <SkillPreviewPanel
          data={previewData}
          editSkillId={editSkillId}
        />
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Verify route exists**

Run: `ls frontend/app/skills/creator/page.tsx`
Expected: File exists

- [ ] **Step 3: Commit**

```bash
git add frontend/app/skills/creator/page.tsx
git commit -m "feat(frontend): add Skill Creator page layout"
```

---

## Task 7: Frontend — SkillCreatorChat Component

**Files:**
- Create: `frontend/app/skills/creator/components/SkillCreatorChat.tsx`

- [ ] **Step 1: Create the component**

This component wraps the existing chat stream hook with `mode="skill_creator"`. It intercepts `tool_end` events for `preview_skill` to extract preview data.

```tsx
// frontend/app/skills/creator/components/SkillCreatorChat.tsx
"use client";

import { useState, useCallback, useRef } from "react";
import { useBackendChatStream } from "@/app/chat/hooks/useBackendChatStream";
import type { SkillPreviewData } from "../page";

interface SkillCreatorChatProps {
  editSkillId: string | null;
  onPreviewUpdate: (data: SkillPreviewData) => void;
}

interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
}

export function SkillCreatorChat({
  editSkillId,
  onPreviewUpdate,
}: SkillCreatorChatProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const threadIdRef = useRef<string | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const { sendMessage } = useBackendChatStream(setMessages as any, {
    onEvent: (event: any) => {
      // Intercept preview_skill tool_end events
      if (
        event.type === "tool_end" &&
        event.data?.tool_name === "preview_skill"
      ) {
        try {
          const previewData = JSON.parse(event.data.output);
          onPreviewUpdate(previewData);
        } catch {
          // ignore parse errors
        }
      }
      if (event.type === "thread_id" && event.data?.thread_id) {
        threadIdRef.current = event.data.thread_id;
      }
    },
  });

  const handleSend = useCallback(async () => {
    if (!input.trim() || isStreaming) return;

    const userMessage = input.trim();
    setInput("");
    setMessages((prev) => [
      ...prev,
      { id: crypto.randomUUID(), role: "user", content: userMessage },
    ]);
    setIsStreaming(true);

    try {
      await sendMessage(userMessage, {
        threadId: threadIdRef.current,
        graphId: null,
        metadata: {
          mode: "skill_creator",
          edit_skill_id: editSkillId,
        },
      });
    } finally {
      setIsStreaming(false);
    }
  }, [input, isStreaming, sendMessage, editSkillId]);

  return (
    <div className="flex flex-col h-full">
      <div className="p-4 border-b border-border">
        <h2 className="text-lg font-semibold">
          {editSkillId ? "AI Skill Editor" : "AI Skill Creator"}
        </h2>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {messages.map((msg) => (
          <div
            key={msg.id}
            className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}
          >
            <div
              className={`max-w-[80%] rounded-lg px-4 py-2 ${
                msg.role === "user"
                  ? "bg-primary text-primary-foreground"
                  : "bg-muted"
              }`}
            >
              {msg.content}
            </div>
          </div>
        ))}
        <div ref={messagesEndRef} />
      </div>

      {/* Input */}
      <div className="p-4 border-t border-border">
        <div className="flex gap-2">
          <input
            className="flex-1 px-3 py-2 rounded-md border border-input bg-background"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && handleSend()}
            placeholder={
              editSkillId
                ? "Describe what you want to change..."
                : "Describe the skill you want to create..."
            }
            disabled={isStreaming}
          />
          <button
            className="px-4 py-2 rounded-md bg-primary text-primary-foreground disabled:opacity-50"
            onClick={handleSend}
            disabled={isStreaming || !input.trim()}
          >
            {isStreaming ? "Generating..." : "Send"}
          </button>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/app/skills/creator/components/SkillCreatorChat.tsx
git commit -m "feat(frontend): add SkillCreatorChat component"
```

---

## Task 8: Frontend — SkillPreviewPanel + File Viewer

**Files:**
- Create: `frontend/app/skills/creator/components/SkillPreviewPanel.tsx`
- Create: `frontend/app/skills/creator/components/SkillFileTree.tsx`
- Create: `frontend/app/skills/creator/components/SkillFileViewer.tsx`
- Create: `frontend/app/skills/creator/components/SkillSaveDialog.tsx`

- [ ] **Step 1: Create SkillFileTree**

```tsx
// frontend/app/skills/creator/components/SkillFileTree.tsx
"use client";

interface FileEntry {
  path: string;
  file_type: string;
  size: number;
}

interface SkillFileTreeProps {
  files: FileEntry[];
  selectedPath: string | null;
  onSelectFile: (path: string) => void;
}

const FILE_ICONS: Record<string, string> = {
  markdown: "📄",
  python: "🐍",
  json: "{ }",
  yaml: "⚙️",
  shell: "🖥️",
  text: "📝",
};

export function SkillFileTree({
  files,
  selectedPath,
  onSelectFile,
}: SkillFileTreeProps) {
  return (
    <div className="text-sm">
      {files.map((file) => (
        <button
          key={file.path}
          className={`w-full text-left px-2 py-1 rounded hover:bg-accent ${
            selectedPath === file.path ? "bg-accent" : ""
          }`}
          onClick={() => onSelectFile(file.path)}
        >
          <span className="mr-1">{FILE_ICONS[file.file_type] ?? "📄"}</span>
          <span className="font-mono text-xs">{file.path}</span>
          <span className="ml-2 text-muted-foreground text-xs">
            {file.size}B
          </span>
        </button>
      ))}
    </div>
  );
}
```

- [ ] **Step 2: Create SkillFileViewer**

```tsx
// frontend/app/skills/creator/components/SkillFileViewer.tsx
"use client";

interface SkillFileViewerProps {
  path: string;
  content: string;
  fileType: string;
}

export function SkillFileViewer({ path, content, fileType }: SkillFileViewerProps) {
  return (
    <div className="h-full flex flex-col">
      <div className="px-3 py-2 border-b border-border text-xs font-mono text-muted-foreground">
        {path}
      </div>
      <pre className="flex-1 overflow-auto p-3 text-xs font-mono bg-muted/30 whitespace-pre-wrap">
        {content}
      </pre>
    </div>
  );
}
```

- [ ] **Step 3: Create SkillSaveDialog**

```tsx
// frontend/app/skills/creator/components/SkillSaveDialog.tsx
"use client";

import { useState } from "react";
import type { SkillPreviewData } from "../page";

interface SkillSaveDialogProps {
  data: SkillPreviewData;
  editSkillId: string | null;
  onConfirm: () => void;
  onCancel: () => void;
  isSaving: boolean;
}

export function SkillSaveDialog({
  data,
  editSkillId,
  onConfirm,
  onCancel,
  isSaving,
}: SkillSaveDialogProps) {
  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-background rounded-lg p-6 max-w-md w-full mx-4 shadow-xl">
        <h3 className="text-lg font-semibold mb-4">
          {editSkillId ? "Update Skill" : "Save Skill"}
        </h3>

        <div className="space-y-2 mb-6 text-sm">
          <div>
            <span className="text-muted-foreground">Name: </span>
            <span className="font-mono">{data.skill_name}</span>
          </div>
          <div>
            <span className="text-muted-foreground">Files: </span>
            <span>{data.files.length}</span>
          </div>
          {data.validation.warnings.length > 0 && (
            <div className="text-yellow-600 text-xs">
              {data.validation.warnings.map((w, i) => (
                <div key={i}>⚠ {w}</div>
              ))}
            </div>
          )}
        </div>

        <div className="flex gap-2 justify-end">
          <button
            className="px-4 py-2 rounded-md border border-input hover:bg-accent"
            onClick={onCancel}
            disabled={isSaving}
          >
            Cancel
          </button>
          <button
            className="px-4 py-2 rounded-md bg-primary text-primary-foreground disabled:opacity-50"
            onClick={onConfirm}
            disabled={isSaving}
          >
            {isSaving ? "Saving..." : editSkillId ? "Update" : "Save"}
          </button>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Create SkillPreviewPanel**

```tsx
// frontend/app/skills/creator/components/SkillPreviewPanel.tsx
"use client";

import { useState, useCallback } from "react";
import { SkillFileTree } from "./SkillFileTree";
import { SkillFileViewer } from "./SkillFileViewer";
import { SkillSaveDialog } from "./SkillSaveDialog";
import type { SkillPreviewData } from "../page";

interface SkillPreviewPanelProps {
  data: SkillPreviewData | null;
  editSkillId: string | null;
}

export function SkillPreviewPanel({ data, editSkillId }: SkillPreviewPanelProps) {
  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const [showSaveDialog, setShowSaveDialog] = useState(false);
  const [isSaving, setIsSaving] = useState(false);

  const selectedFile = data?.files.find((f) => f.path === selectedPath) ?? null;

  const handleSave = useCallback(async () => {
    if (!data) return;
    setIsSaving(true);
    try {
      const skillFiles = data.files.map((f) => ({
        path: f.path,
        file_name: f.path.split("/").pop() ?? f.path,
        file_type: f.file_type,
        content: f.content,
        size: f.size,
      }));

      // Parse name/description from SKILL.md frontmatter
      const skillMd = data.files.find((f) => f.path === "SKILL.md");
      const frontmatterMatch = skillMd?.content.match(
        /^---\n([\s\S]*?)\n---/
      );
      let name = data.skill_name;
      let description = "";
      let content = skillMd?.content ?? "";

      if (frontmatterMatch) {
        const lines = frontmatterMatch[1].split("\n");
        for (const line of lines) {
          const [key, ...vals] = line.split(":");
          if (key.trim() === "name") name = vals.join(":").trim();
          if (key.trim() === "description") description = vals.join(":").trim();
        }
        // content = body after frontmatter
        content = (skillMd?.content ?? "").replace(/^---\n[\s\S]*?\n---\n?/, "");
      }

      const payload = {
        name,
        description,
        content,
        tags: [],
        is_public: false,
        files: skillFiles,
      };

      const baseUrl = process.env.NEXT_PUBLIC_BACKEND_URL ?? "";
      const url = editSkillId
        ? `${baseUrl}/api/v1/skills/${editSkillId}`
        : `${baseUrl}/api/v1/skills`;

      const resp = await fetch(url, {
        method: editSkillId ? "PUT" : "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify(payload),
      });

      if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        throw new Error(err.detail ?? `HTTP ${resp.status}`);
      }

      setShowSaveDialog(false);
      // TODO: show success toast / redirect to skills list
    } catch (error) {
      console.error("Failed to save skill:", error);
      // TODO: show error toast
    } finally {
      setIsSaving(false);
    }
  }, [data, editSkillId]);

  if (!data) {
    return (
      <div className="h-full flex items-center justify-center text-muted-foreground text-sm p-8 text-center">
        Skill preview will appear here once the Agent generates it.
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col">
      {/* Header */}
      <div className="p-4 border-b border-border flex items-center justify-between">
        <div>
          <h3 className="font-semibold font-mono">{data.skill_name}/</h3>
          {!data.validation.valid && (
            <span className="text-xs text-destructive">
              {data.validation.errors.join("; ")}
            </span>
          )}
        </div>
        <button
          className="px-3 py-1.5 rounded-md bg-primary text-primary-foreground text-sm disabled:opacity-50"
          onClick={() => setShowSaveDialog(true)}
          disabled={!data.validation.valid}
        >
          Save to Library
        </button>
      </div>

      {/* File tree */}
      <div className="p-2 border-b border-border">
        <SkillFileTree
          files={data.files}
          selectedPath={selectedPath}
          onSelectFile={setSelectedPath}
        />
      </div>

      {/* File content viewer */}
      <div className="flex-1 min-h-0">
        {selectedFile ? (
          <SkillFileViewer
            path={selectedFile.path}
            content={selectedFile.content}
            fileType={selectedFile.file_type}
          />
        ) : (
          <div className="h-full flex items-center justify-center text-muted-foreground text-sm">
            Select a file to preview
          </div>
        )}
      </div>

      {/* Save dialog */}
      {showSaveDialog && (
        <SkillSaveDialog
          data={data}
          editSkillId={editSkillId}
          onConfirm={handleSave}
          onCancel={() => setShowSaveDialog(false)}
          isSaving={isSaving}
        />
      )}
    </div>
  );
}
```

- [ ] **Step 5: Commit**

```bash
git add frontend/app/skills/creator/components/
git commit -m "feat(frontend): add Skill preview panel, file tree, viewer, save dialog"
```

---

## Task 9: Frontend — Dashboard Entry Card + Skills Page Button

**Files:**
- Modify: `frontend/app/chat/components/ChatHome.tsx` (add Skill Creator card)
- Modify: `frontend/app/skills/page.tsx` (add "AI Create" button)

- [ ] **Step 1: Read existing ChatHome.tsx**

Read `frontend/app/chat/components/ChatHome.tsx` to understand the current layout and how mode cards are rendered (Rapid Mode, Deep Mode, etc.).

- [ ] **Step 2: Add Skill Creator card to ChatHome**

Add a new card alongside existing mode cards. Follow the existing card pattern. Example addition:

```tsx
<Link href="/skills/creator">
  <div className="/* same card classes as Rapid/Deep Mode cards */">
    <h3>Skill Creator</h3>
    <p>AI-powered skill creation and modification</p>
  </div>
</Link>
```

Exact classes and structure must match the existing cards — read the file first.

- [ ] **Step 3: Add "AI Create" button to Skills page**

Edit `frontend/app/skills/page.tsx`. Add a button/link near the tab switcher:

```tsx
import Link from "next/link";

// In the header/action area of the skills page:
<Link href="/skills/creator">
  <button className="/* match existing button styles */">
    AI Create
  </button>
</Link>
```

- [ ] **Step 4: Verify no build errors**

Run: `cd frontend && npx next build --no-lint 2>&1 | tail -20`
Expected: No errors related to the new pages

- [ ] **Step 5: Commit**

```bash
git add frontend/app/chat/components/ChatHome.tsx frontend/app/skills/page.tsx
git commit -m "feat(frontend): add Skill Creator entry on chat home and skills page"
```

---

## Task 10: Backend — Pass mode through Chat Stream to Metadata

**Files:**
- Modify: `frontend/app/chat/hooks/useBackendChatStream.ts`
- Modify: `frontend/services/chatBackend.ts` (or wherever `streamChat` is defined)

- [ ] **Step 1: Read the streaming service**

Read `frontend/app/chat/hooks/useBackendChatStream.ts` and the `streamChat` function to understand how metadata is passed to the backend.

- [ ] **Step 2: Ensure mode passes through**

The `metadata` field in `ChatRequest` already supports arbitrary keys. The `SkillCreatorChat` component passes `mode: "skill_creator"` via metadata. Verify that the `streamChat` function forwards metadata to the `POST /v1/chat/stream` body. If `mode` needs to be a top-level field (not inside metadata), update the `streamChat` function to include it.

If `mode` is a top-level ChatRequest field (as designed in Task 1), the frontend `streamChat` call needs to pass it at the top level:

```typescript
// In streamChat or equivalent:
const body = {
  message: userPrompt,
  thread_id: opts.threadId,
  graph_id: opts.graphId,
  mode: opts.metadata?.mode ?? null,
  edit_skill_id: opts.metadata?.edit_skill_id ?? null,
  metadata: opts.metadata ?? {},
};
```

- [ ] **Step 3: Commit**

```bash
git add frontend/app/chat/hooks/useBackendChatStream.ts frontend/services/chatBackend.ts
git commit -m "feat(frontend): pass mode and edit_skill_id through to chat API"
```

---

## Task 11: Integration Test — End-to-End Skill Creator Flow

**Files:**
- Create: `backend/tests/test_api/test_skill_creator.py`

- [ ] **Step 1: Write integration test**

```python
# backend/tests/test_api/test_skill_creator.py
"""Integration test for skill_creator mode in chat stream."""
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_chat_stream_skill_creator_mode_accepted(
    client: AsyncClient, auth_headers: dict
):
    """Verify that mode=skill_creator is accepted by the chat stream endpoint."""
    response = await client.post(
        "/api/v1/chat/stream",
        json={
            "message": "Create a simple hello-world skill",
            "mode": "skill_creator",
        },
        headers=auth_headers,
    )
    # SSE endpoint returns 200 with streaming response
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_chat_request_rejects_invalid_mode(
    client: AsyncClient, auth_headers: dict
):
    """Verify that an invalid mode value is rejected."""
    response = await client.post(
        "/api/v1/chat/stream",
        json={
            "message": "Hello",
            "mode": "invalid_mode",
        },
        headers=auth_headers,
    )
    assert response.status_code == 422  # Pydantic validation error
```

- [ ] **Step 2: Run test**

Run: `cd backend && python -m pytest tests/test_api/test_skill_creator.py -v`
Expected: PASS (requires test fixtures — adapt to existing test setup)

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_api/test_skill_creator.py
git commit -m "test: add integration tests for skill_creator chat mode"
```

---

## Dependency Order

```
Task 1 (Schema)
    ↓
Task 2 (preview_skill tool) → Task 3 (Register tool)
    ↓
Task 4 (GraphService method)
    ↓
Task 5 (Wire into chat.py) — depends on Tasks 1, 3, 4
    ↓
Task 6 (Page layout) → Task 7 (Chat component) → Task 8 (Preview components)
    ↓
Task 9 (Entry points)
    ↓
Task 10 (Frontend streaming passthrough) — depends on Tasks 7, 5
    ↓
Task 11 (Integration test) — depends on all above
```

Tasks 1-5 are backend (sequential). Tasks 6-9 are frontend (can parallelize with backend after Task 1). Task 10 bridges both. Task 11 is final verification.

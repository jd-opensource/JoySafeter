"""Skill authoring orchestrator.

Bridges the AI workspace (``/managed/skills/new-ai``) to the OpenAI-compatible
streaming helper. Responsible for:

  * Loading a small set of high-quality SKILL.md examples on first use and
    baking them into the system prompt as few-shot context.
  * Defining the ``update_draft`` tool the model uses to patch right-side
    fields (name / description / tags / visibility / content / files).
  * Wiring per-request OpenAI credentials supplied by the caller (resolved
    from a JoySafeter secret upstream — see ``skills_ai_authoring`` router)
    into ``stream_openai_chat``.
  * Translating ``stream_openai_chat`` events into the SSE shape the frontend
    consumes: ``text_delta`` (verbatim) and ``draft_patch`` (parsed from the
    completed ``update_draft`` tool call).

The frontend talks to this through ``POST /api/v1/skills/ai-authoring/chat``
which is a thin SSE pass-through over :func:`stream_authoring_chat`.
"""

from __future__ import annotations

import functools
import json
import logging
from pathlib import Path
from typing import Any, AsyncGenerator, Optional

from app.joysafeter_shared.common.boundary_errors import log_boundary_failure
from app.joysafeter_shared.common.stream_errors import async_error_payload
from app.joysafeter_shared.llm.openai_stream import stream_openai_chat

logger = logging.getLogger(__name__)

# Few-shot examples are kept short and intentionally diverse — one security
# review skill, one analysis skill, one workflow skill — so the model picks
# up the *shape* of a good SKILL.md (frontmatter + Purpose + Workflow +
# References) without overfitting to one domain. We resolve the path
# relative to the repo root rather than the package because skills/ lives
# outside the Python package tree (it's the shipped catalog).
_REPO_ROOT = Path(__file__).resolve().parents[4]
_FEW_SHOT_SKILLS = (
    # A multi-file skill that demonstrates the references/ pattern — its
    # SKILL.md ends with a ``## References`` section pointing at
    # ``references/tools.md`` + ``references/workflows.md``. This is the
    # template most JoySafeter skills follow.
    "skills/pentest-ai-llm-security/SKILL.md",
    # A short single-file skill as a counter-example so the model knows
    # SKILL.md alone is acceptable for pure-workflow skills with no
    # external references.
    "skills/brainstorming/SKILL.md",
)


@functools.lru_cache(maxsize=1)
def _load_few_shot_block() -> str:
    """Read few-shot SKILL.md examples once on first call and cache.

    Skips silently if a file is missing — the model still works without
    examples, just produces slightly less idiomatic SKILL.md. We don't
    fail the whole authoring feature on a missing example.
    """
    parts: list[str] = []
    for rel in _FEW_SHOT_SKILLS:
        path = _REPO_ROOT / rel
        try:
            body = path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            logger.warning("few-shot skill %s unavailable: %s", rel, exc)
            continue
        # Trim aggressively: only the first ~80 lines are useful; the
        # really long ones drift the model toward producing essays.
        lines = body.splitlines()
        if len(lines) > 80:
            body = "\n".join(lines[:80]) + "\n…(truncated)"
        parts.append(f"### Example: {rel}\n\n```markdown\n{body}\n```")
    return "\n\n".join(parts)


SYSTEM_PROMPT = """\
You are a SKILL.md authoring assistant for JoySafeter, an AI-agent platform.

A "skill" is a SELF-CONTAINED DIRECTORY, not a single markdown file. The
canonical layout (Anthropic Agent Skills convention, verified against
JoySafeter's 60+ shipped skills):

    skill-name/
      SKILL.md                       # required entry / index
      references/
        tools.md                     # tools, signatures, parameters
        workflows.md                 # attack patterns / playbooks / steps
        ...                          # any extra reference docs
      scripts/                       # optional executable helpers
        do_thing.py / run.sh / ...
      examples/                      # optional code samples
      assets/                        # optional non-code resources (templates, configs)

SKILL.md is the entry point that **indexes** the rest. It MUST end with a
``## References`` section listing the sub-files with one-line descriptions,
e.g.:

    ## References
    - `references/tools.md` — Tool function signatures and parameters
    - `references/workflows.md` — Attack pattern definitions and test vectors

This is how the agent runtime discovers and loads helper files on demand.

## Your job

Given the user's intent in natural language, draft and iteratively refine
a complete skill DIRECTORY (SKILL.md plus the relevant sub-files). You
talk to the user via plain assistant text AND you update the right-side
preview by calling the ``update_draft`` function.

## Rules

1. ALWAYS call ``update_draft`` when you have something to fill in. The user
   only sees what you write to the draft — your chat text alone is not the
   deliverable.
2. ALWAYS ALSO reply with 1-2 short sentences of plain assistant text in
   parallel with the tool call, telling the user what you just changed.
   The chat bubble is the user's main feedback signal — a silent tool call
   looks like the system is broken, even when the right-side preview did
   update.
3. PREFER multi-file output. A skill that's only SKILL.md is almost always
   incomplete. By default produce:
     - SKILL.md (always)
     - references/workflows.md (concrete steps / playbook / test vectors)
     - references/tools.md (commands / signatures / payloads)
   Add more sub-files (scripts/, examples/, assets/) when the skill type
   genuinely needs them. Skip a sub-file ONLY when it would be vacuous
   (e.g. a pure brainstorming skill might not need scripts).
4. SKILL.md MUST end with a ``## References`` section listing each sub-file
   in the ``files`` array with a one-line description. Without this section
   the runtime cannot discover the sub-files.
5. Fields you can set on the draft:
   - ``name``: short, slug-friendly, ≤ 64 chars, lowercase letters / digits / hyphens
   - ``description``: 1-2 sentences, ≤ 1024 chars, no marketing tone
   - ``tags``: 2-5 short kebab-case tags
   - ``content``: the SKILL.md body (UTF-8 markdown), MUST start with YAML
     frontmatter containing ``name`` and ``description`` matching the fields
     above, then markdown headings, ending with ``## References``.
   - ``files``: list of ``{path, content}``. ``path`` is a relative POSIX
     path (no leading slash, no ``..``). Use the conventional directories:
     ``references/*.md``, ``scripts/*.{py,sh}``, ``examples/*``, ``assets/*``.
6. SKILL.md outline (concise — heavy content goes into references/):
     - YAML frontmatter (--- name + description ---)
     - ``# Title``
     - ``## Purpose`` — one paragraph
     - ``## When to use`` — bullet list of triggers
     - ``## Core Workflow`` — numbered steps (overview only; details in references/)
     - ``## Tool Categories`` or domain-specific overview table (optional)
     - ``## References`` — list of sub-files
7. Only patch fields that change between turns. Don't resend identical content.
8. New skills are created as project resources; exposing them to the wider
   organization or the public is a separate, reviewed promotion step and is
   NOT something you set here.
9. Talk to the user in the language they used (Chinese ⇄ English mirror).

## Quality bar (what separates an expert skill from token waste)

A skill's value = expert knowledge MINUS what the model already knows. Hold
every skill you draft to these five bars — they are the difference between a
skill that changes behavior and one that just fills the context window:

A. KNOWLEDGE DELTA (most important). Write only what a domain expert knows
   that the model does NOT: decision trees for non-obvious choices, trade-offs,
   real-world edge cases, "do X not Y because <non-obvious reason>". NEVER
   write "what is <basic concept>", standard-library tutorials, or generic
   advice ("write clean code", "handle errors"). If the model already knows
   it, delete it.
B. THINKING > MECHANICS. Prefer "Before doing X, ask yourself: …" framings and
   domain-specific procedures the model wouldn't know (non-obvious ordering,
   easy-to-miss critical steps) over generic step-1/step-2 file operations.
C. NEVER LIST. Include an explicit, SPECIFIC anti-pattern list, each with the
   non-obvious reason ("NEVER use purple gradients on white — reads as
   AI-generated"). Vague warnings ("be careful", "avoid errors") are worthless.
D. DESCRIPTION MUST TRIGGER. The description is the ONLY thing the runtime sees
   when deciding whether to load the skill. It MUST answer WHAT it does, WHEN
   to use it ("Use when…" + concrete scenarios), and include searchable
   KEYWORDS (file extensions, domain terms, action verbs). Trigger info belongs
   in the description, NOT only in the body.
E. FREEDOM MATCHES FRAGILITY. Creative/design tasks → give principles and bold
   direction, not rigid steps. Fragile/exact operations (file formats, byte-
   level edits) → give exact scripts and "do NOT modify" constraints. Match the
   constraint level to the cost of a mistake.

For multi-file skills, embed loading triggers in the workflow ("MANDATORY:
read references/foo.md before this step") and say when NOT to load a file, so
references get used at the right moment instead of sitting unread.

## Few-shot examples of well-formed SKILL.md (note the References section
   at the end and the multi-file pattern they expect):

{FEW_SHOT}

When in doubt about whether to add a sub-file, ASK the user. Then commit.
"""


# The OpenAI tool-call definition the model uses to patch the right-side
# preview. Mirrors the SkillDraft frontend type 1:1.
UPDATE_DRAFT_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "update_draft",
        "description": (
            "Patch the user's skill draft. Include ONLY the fields that "
            "change in this turn. Use 'content' for the full SKILL.md body."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "maxLength": 64},
                "description": {"type": "string", "maxLength": 1024},
                "tags": {"type": "array", "items": {"type": "string"}, "maxItems": 10},
                "content": {
                    "type": "string",
                    "description": ("Full SKILL.md body including YAML frontmatter and markdown sections."),
                },
                "files": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string"},
                            "content": {"type": "string"},
                        },
                        "required": ["path", "content"],
                        "additionalProperties": False,
                    },
                },
            },
            "additionalProperties": False,
        },
    },
}


def _build_messages(
    *,
    history: list[dict[str, Any]],
    draft: Optional[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Compose the wire ``messages`` array for the LLM call.

    Structure:
        [system]      few-shot enriched authoring guide
        [system]      current draft snapshot, if any (so the model sees what
                      it already filled in and can patch incrementally)
        [user/asst…]  prior turns, verbatim
    """
    system = SYSTEM_PROMPT.replace("{FEW_SHOT}", _load_few_shot_block())
    out: list[dict[str, Any]] = [{"role": "system", "content": system}]

    if draft:
        # Pass the current draft as a compact JSON system message so the model
        # treats it as ground truth, not as user input it should reformat.
        snapshot = {k: v for k, v in draft.items() if v not in (None, "", [])}
        if snapshot:
            out.append(
                {
                    "role": "system",
                    "content": (
                        "Current draft state (you previously filled these "
                        "fields; patch incrementally):\n" + json.dumps(snapshot, ensure_ascii=False, indent=2)
                    ),
                }
            )

    for msg in history:
        role = msg.get("role")
        content = msg.get("content") or ""
        if role in ("user", "assistant") and content:
            out.append({"role": role, "content": content})
    return out


async def stream_authoring_chat(
    *,
    api_key: str,
    base_url: str,
    model: str,
    history: list[dict[str, Any]],
    draft: Optional[dict[str, Any]] = None,
) -> AsyncGenerator[dict[str, Any], None]:
    """Run one authoring turn against the LLM and stream events.

    Yields the wire shape the SSE endpoint forwards verbatim::

        {"type": "text_delta", "text": "..."}
        {"type": "draft_patch", "patch": {...}}
        {"type": "done"}
        {"type": "error", "code": "...", "message": "...", "data": None, ...}

    ``draft_patch`` is produced by parsing the completed ``update_draft``
    tool call's JSON arguments. Invalid JSON from the model is logged and
    skipped (the model occasionally emits trailing commas etc.).
    """
    messages = _build_messages(history=history, draft=draft)

    async for event in stream_openai_chat(
        base_url=base_url,
        api_key=api_key,
        model=model,
        messages=messages,
        tools=[UPDATE_DRAFT_TOOL],
        # Multi-file skills routinely emit 8-12k of tool_call JSON
        # (SKILL.md + 2-4 references/scripts files). Reasoning models like
        # GPT-5.5 also burn output budget on hidden reasoning tokens. The
        # default 4096 starves them — set high enough that even the
        # largest reasonable skill fits.
        max_tokens=16000,
    ):
        etype = event.get("type")
        if etype == "text_delta":
            yield {"type": "text_delta", "text": event["text"]}
        elif etype == "tool_call_complete":
            if event.get("name") != "update_draft":
                continue
            args_raw = event.get("args_json") or ""
            try:
                patch = json.loads(args_raw)
            except json.JSONDecodeError as exc:
                log_boundary_failure(
                    logger,
                    boundary="skill_authoring",
                    code="SKILL_AUTHORING_DRAFT_PATCH_PARSE_FAILED",
                    message="Failed to parse update_draft arguments",
                    operation="parse_update_draft_args",
                    error=exc,
                    data={"raw_length": len(args_raw)},
                    retryable=False,
                    user_action=None,
                )
                continue
            if not isinstance(patch, dict) or not patch:
                continue
            yield {"type": "draft_patch", "patch": patch}
        elif etype == "error":
            status = event.get("status")
            yield async_error_payload(
                code=event.get("code") or "UPSTREAM_STREAM_ERROR",
                message=event.get("message") or "LLM error",
                data=event.get("data") if isinstance(event.get("data"), dict) else None,
                source=event.get("source") or "upstream",
                retryable=bool(event.get("retryable", False)),
                status=status if isinstance(status, int) else None,
            )
            return
        elif etype == "done":
            yield {"type": "done"}
            return
        # tool_call_delta events are dropped — we only emit a draft_patch
        # when the call is complete to avoid re-rendering partial JSON.

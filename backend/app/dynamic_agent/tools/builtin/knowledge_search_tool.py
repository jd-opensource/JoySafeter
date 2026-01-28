"""
Knowledge Search Tool for Lazy RAG

Allows the Agent to search the CTF knowledge base on-demand,
rather than pre-loading all knowledge at the start.

Feature: 010-lazy-rag-retrieval
Tasks: T010, T011, T012

Design:
- Tricks are stored in shared state (MetadataContext), not returned to LLM context
- Knowledge files are tracked at SESSION level to avoid duplicate retrieval
- Each file can only be recalled ONCE per session (across all SubAgents)
- Each search returns ALL tricks from one unused file for systematic exploration
- Both Main Agent and Sub-Agent can access tricks via get_available_tricks()
"""

import json
from typing import Any, Dict, List, Optional, Set

from langchain_core.tools import tool
from loguru import logger

from app.dynamic_agent.infra.metadata_context import MetadataContext

# Keys for storing tricks in MetadataContext
_TRICKS_KEY = "knowledge_tricks"  # Current available tricks
_USED_FILES_KEY = "used_knowledge_files"  # Already used knowledge file names (per context_id)
_CURRENT_CONTEXT_ID_KEY = "current_knowledge_context_id"  # Current context ID for tracking


def normalize_results_to_xml(
    matches: List[Dict[str, Any]],
    query: str,
    max_matches: int = 3,
    max_tricks_per_match: int = 5,
) -> str:
    """
    Normalize search results to XML format for LLM consumption.

    XML format is more token-efficient and easier for LLM to parse.
    """
    if not matches:
        return "<knowledge_search>\n<note>No similar problems found in knowledge base. Suggest continuing with basic methods.</note>\n</knowledge_search>"

    lines = [
        "<knowledge_search>",
        "<note>⚠️ Try tricks in order, check if the 'when' condition matches the current state!</note>",
    ]

    for match in matches[:max_matches]:
        name = match.get("name", "unknown")
        category = match.get("category", "misc")
        relevance = match.get("relevance", 0.5)

        lines.append(f'<match name="{name}" category="{category}" relevance="{relevance}">')

        # Extract tricks
        tricks = match.get("tricks", [])
        for trick in tricks[:max_tricks_per_match]:
            if hasattr(trick, "name"):
                # Trick dataclass
                t_name = trick.name
                t_when = trick.when
                t_how = trick.how
                t_payload = trick.payload or ""
            elif isinstance(trick, dict):
                # Dict format
                t_name = trick.get("name", "")
                t_when = trick.get("when", "")
                t_how = trick.get("how", "")
                t_payload = trick.get("payload", "")
            else:
                continue

            lines.append(f'  <trick name="{t_name}">')
            lines.append(f"    <when>{t_when}</when>")
            lines.append(f"    <how>{t_how}</how>")
            if t_payload:
                # Escape special XML chars in payload
                t_payload = t_payload.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                lines.append(f"    <payload>{t_payload}</payload>")
            lines.append("  </trick>")

        lines.append("</match>")

    lines.append("</knowledge_search>")
    return "\n".join(lines)


def _emit_search_event(event_type: str, data: Dict[str, Any]) -> None:
    """Emit WebSocket event for frontend visualization (T021)."""
    try:
        metadata = MetadataContext.get()
        if metadata and "stream_callback" in metadata:
            import time

            event = {"type": event_type, "data": data, "timestamp": int(time.time() * 1000)}
            metadata["stream_callback"](json.dumps(event))
    except Exception as e:
        logger.debug(f"Failed to emit search event: {e}")


def _get_current_context_id() -> Optional[str]:
    """Get current context ID for trick tracking."""
    metadata = MetadataContext.get()
    if metadata is None:
        return None
    return metadata.get(_CURRENT_CONTEXT_ID_KEY)


def set_context_id(context_id: str) -> None:
    """
    Set the current context ID for trick tracking.

    Call this when creating a new SubAgent to isolate its used tricks
    from other SubAgents that don't share the same conversation context.

    Args:
        context_id: Unique identifier for the current context/conversation
    """
    metadata = MetadataContext.get()
    if metadata is None:
        return
    metadata[_CURRENT_CONTEXT_ID_KEY] = context_id
    logger.debug(f"🔑 Set knowledge context ID: {context_id}")


def _get_used_files() -> Set[str]:
    """Get set of knowledge file names already used in current session (global, not per-context)."""
    metadata = MetadataContext.get()
    if metadata is None:
        return set()

    # Session-level: all SubAgents share the same used_files set
    # This ensures each knowledge file is only recalled ONCE per session
    used_files = metadata.get(_USED_FILES_KEY, set())
    return used_files if isinstance(used_files, set) else set()  # type: ignore[return-value]


def _mark_file_as_used(file_name: str) -> None:
    """Mark a knowledge file as used for current session (global, not per-context)."""
    metadata = MetadataContext.get()
    if metadata is None:
        return

    # Session-level: all SubAgents share the same used_files set
    used_files = metadata.get(_USED_FILES_KEY, set())
    used_files.add(file_name)
    metadata[_USED_FILES_KEY] = used_files
    logger.debug(f"📁 Marked file as used (session-level): {file_name}")


def _store_tricks(tricks: List[Dict[str, Any]]) -> None:
    """Store tricks in shared state for agents to access."""
    metadata = MetadataContext.get()
    if metadata is None:
        return

    # Append to existing tricks (don't overwrite)
    existing = metadata.get(_TRICKS_KEY, [])
    existing.extend(tricks)
    metadata[_TRICKS_KEY] = existing
    logger.debug(f"📚 Stored {len(tricks)} tricks in shared state")


def get_available_tricks() -> List[Dict[str, Any]]:
    """
    Get available tricks from shared state.

    Call this in Main Agent or Sub-Agent to access retrieved tricks
    without them being in the LLM context.

    Returns:
        List of trick dicts with keys: name, when, how, payload
    """
    metadata = MetadataContext.get()
    if metadata is None:
        return []
    tricks = metadata.get(_TRICKS_KEY, [])
    return tricks if isinstance(tricks, list) else []  # type: ignore[return-value]


def clear_tricks(context_id: Optional[str] = None) -> None:
    """
    Clear stored tricks and used files.

    Args:
        context_id: Deprecated, kept for backward compatibility. Always clears session-level state.
    """
    metadata = MetadataContext.get()
    if metadata is None:
        return

    # Session-level: clear all tricks and used files
    metadata[_TRICKS_KEY] = []
    metadata[_USED_FILES_KEY] = set()
    metadata[_CURRENT_CONTEXT_ID_KEY] = None
    logger.debug("🧹 Cleared all tricks and used files (session-level)")


def format_tricks_for_planning() -> str:
    """
    Format available tricks as a concise string for planning.

    Use this to inject tricks into agent_tool context parameter.

    Returns:
        Formatted string of tricks, or empty string if none
    """
    tricks = get_available_tricks()
    if not tricks:
        return ""

    lines = ["\n💡 Available tricks from knowledge base:"]
    for t in tricks[-5:]:  # Only show last 5 to keep it concise
        lines.append(f"- {t.get('name', 'unknown')}: {t.get('how', '')[:100]}")
        if t.get("payload"):
            lines.append(f"  Payload: {t.get('payload', '')}")

    return "\n".join(lines)


@tool
def knowledge_search(query: str) -> str:
    """
    Search CTF knowledge base for relevant tricks and techniques.

    Tricks are stored in shared state (not in LLM context) and can be
    accessed via get_available_tricks(). Used tricks won't be retrieved again.

    Args:
        query: Search query describing the problem (e.g. "SSTI bypass WAF", "JWT signature bypass")

    Returns:
        Brief confirmation message (tricks are stored separately, not returned here)
    """
    import time

    start_time = time.time()
    node_id = f"ks_{int(start_time * 1000)}"

    logger.info(f"🔍 Knowledge search: {query}")

    # T021: Emit search start event
    _emit_search_event("knowledge_search_start", {"node_id": node_id, "query": query})

    try:
        from app.dynamic_agent.core.knowledge import get_knowledge_loader

        loader = get_knowledge_loader()

        # Search using the query
        matches = loader.search_by_query(query)

        # Get already used files to filter them out
        used_files = _get_used_files()

        # Extract tricks - ONE FILE AT A TIME
        new_tricks = []
        selected_file = None
        selected_knowledge_name = None

        # Try to find a file we haven't used yet
        for match in matches:
            # Use file_name if available, fallback to name (knowledge base name)
            file_name = match.get("file_name") or match.get("name", "")
            knowledge_name = match.get("name", "")

            # Skip files we've already used in this context
            if file_name in used_files:
                logger.debug(f"⏭️ Skipping used file: {file_name}")
                continue

            # Found an unused file! Use ALL tricks from this file
            selected_file = file_name
            selected_knowledge_name = knowledge_name
            tricks = match.get("tricks", [])

            for trick in tricks:
                # Handle both dataclass and dict formats
                if hasattr(trick, "name"):
                    t_dict = {"name": trick.name, "when": trick.when, "how": trick.how, "payload": trick.payload or ""}
                elif isinstance(trick, dict):
                    t_dict = {
                        "name": trick.get("name", ""),
                        "when": trick.get("when", ""),
                        "how": trick.get("how", ""),
                        "payload": trick.get("payload", ""),
                    }
                else:
                    continue

                new_tricks.append(t_dict)

            # Found tricks from this file, stop here (one file per search)
            if new_tricks:
                break

        # Store new tricks in shared state and mark file as used
        if new_tricks and selected_file:
            _store_tricks(new_tricks)
            _mark_file_as_used(selected_file)

        duration_ms = int((time.time() - start_time) * 1000)
        # Log with both filename and knowledge name for clarity
        if selected_file:
            log_msg = f"✅ Found {len(new_tricks)} tricks from '{selected_file}'"
            if selected_knowledge_name and selected_file != selected_knowledge_name:
                log_msg += f" (knowledge: {selected_knowledge_name})"
            log_msg += f" in {duration_ms}ms (filtered {len(used_files)} used files)"
            logger.info(log_msg)

        # T021: Emit search complete event
        _emit_search_event(
            "knowledge_search_complete",
            {
                "node_id": node_id,
                "query": query,
                "match_count": len(matches),
                "new_tricks_count": len(new_tricks),
                "filtered_files_count": len(used_files),
                "selected_file": selected_file,
                "selected_knowledge_name": selected_knowledge_name,
                "duration_ms": duration_ms,
            },
        )

        # Return actionable summary - tricks will be auto-injected to Sub-Agent
        if new_tricks:
            # Show both filename and knowledge name in the response
            knowledge_display = selected_knowledge_name or selected_file or "unknown"
            response_header = f"✅ Found {len(new_tricks)} relevant tricks from knowledge base '{knowledge_display}'"
            if selected_file and selected_file != knowledge_display:
                response_header += f" (file: {selected_file})"
            lines = [response_header + ":"]
            for t in new_tricks[:5]:  # Show up to 5 tricks
                lines.append(f"\n💡 **{t['name']}**")
                if t.get("when"):
                    lines.append(f"   When: {t['when']}")
                lines.append(
                    f"   How: {t['how'][:150]}..." if len(t.get("how", "")) > 150 else f"   How: {t.get('how', '')}"
                )
                if t.get("payload"):
                    lines.append(f"   Payload: `{t['payload']}`")
            if len(new_tricks) > 5:
                lines.append(f"\n... and {len(new_tricks) - 5} more tricks from this file")
            lines.append(
                "\n➡️ Apply these techniques. If they don't work, search again to try a different knowledge base."
            )
            return "\n".join(lines)
        else:
            if used_files:
                return f"❌ No new tricks found. Already tried {len(used_files)} knowledge files. Try a different query or continue with current approach."
            else:
                return "❌ No relevant tricks found in knowledge base. Continue with current approach."

    except Exception as e:
        logger.error(f"Knowledge search failed: {e}")

        # T021: Emit search failed event
        _emit_search_event("knowledge_search_failed", {"node_id": node_id, "query": query, "error": str(e)})

        return "⚠️ Knowledge search unavailable. Continue with current approach."


# Export for tool registration
__all__ = [
    "knowledge_search",
    "get_available_tricks",
    "format_tricks_for_planning",
    "clear_tricks",
    "set_context_id",
]

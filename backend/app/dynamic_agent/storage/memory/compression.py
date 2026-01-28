"""
Context compression for long conversations.

Handles message history compression and pruning.
"""

from datetime import datetime, timedelta
from typing import Any, Dict, List

from loguru import logger


class ContextCompressor:
    """Context compressor for long conversation histories."""

    def __init__(self, llm_provider=None):
        self.llm = llm_provider

    async def compress_messages(
        self, messages: List[Dict[str, Any]], max_messages: int = 20, preserve_recent: int = 5
    ) -> List[Dict[str, Any]]:
        """Compress message history."""
        if len(messages) <= max_messages:
            return messages

        # Always preserve recent messages
        recent_messages = messages[-preserve_recent:]
        old_messages = messages[:-preserve_recent]

        # Simple compression: keep important messages
        # todo
        compressed = self._simple_compress(old_messages, max_messages - preserve_recent)

        return compressed + recent_messages

    def _simple_compress(self, messages: List[Dict[str, Any]], target_count: int) -> List[Dict[str, Any]]:
        """Simple compression by keeping important messages."""
        if len(messages) <= target_count:
            return messages

        # Score messages by importance
        scored_messages = []
        for msg in messages:
            score = self._calculate_importance(msg)
            scored_messages.append((score, msg))

        # Sort by score and keep top N
        scored_messages.sort(reverse=True, key=lambda x: x[0])
        compressed = [msg for _, msg in scored_messages[:target_count]]

        # Sort by original order
        compressed.sort(key=lambda x: messages.index(x))

        return compressed

    def _calculate_importance(self, message: Dict[str, Any]) -> float:
        """Calculate message importance score."""
        content = message.get("content", "").lower()
        score = 0.5  # Base score

        # Important keywords increase score
        important_keywords = [
            "vulnerability",
            "exploit",
            "found",
            "discovered",
            "critical",
            "high",
            "success",
            "failed",
            "error",
        ]

        for keyword in important_keywords:
            if keyword in content:
                score += 0.1

        # Assistant messages are slightly more important
        if message.get("role") == "assistant":
            score += 0.05

        # Recent messages get bonus (if timestamp available)
        if "timestamp" in message:
            try:
                msg_time = datetime.fromisoformat(message["timestamp"])
                age_hours = (datetime.now() - msg_time).total_seconds() / 3600
                if age_hours < 1:
                    score += 0.2
                elif age_hours < 24:
                    score += 0.1
            except (ValueError, AttributeError) as e:
                logger.debug(f"Failed to parse message timestamp: {e}")

        return min(1.0, score)

    async def create_summary(self, messages: List[Dict[str, Any]]) -> str:
        """Create conversation summary (placeholder for LLM integration)."""
        # Simple summary without LLM
        total = len(messages)
        user_msgs = sum(1 for m in messages if m.get("role") == "user")
        assistant_msgs = sum(1 for m in messages if m.get("role") == "assistant")

        # Extract key findings
        findings = []
        for msg in messages:
            content = msg.get("content", "").lower()
            if "vulnerability" in content or "found" in content:
                findings.append(msg.get("content", "")[:100])

        summary = f"Conversation with {total} messages ({user_msgs} user, {assistant_msgs} assistant)."
        if findings:
            summary += f" Key findings: {len(findings)} items."

        return summary


class ContextPruner:
    """Context pruner for removing old/irrelevant data."""

    def __init__(self, memory_store):
        self.memory_store = memory_store

    async def prune_session(
        self, session_id: str, max_age_days: int = 30, min_importance: float = 0.3
    ) -> Dict[str, int | str]:
        """Prune session data."""
        cutoff_date = datetime.now() - timedelta(days=max_age_days)

        # Get all memories
        memories = await self.memory_store.search(session_id=session_id, limit=1000)

        deleted_count = 0
        for memory in memories:
            # Delete if old, low importance, and rarely accessed
            if memory.created_at < cutoff_date and memory.importance < min_importance and memory.accessed_count < 2:
                await self.memory_store.delete_memory(memory.memory_id)
                deleted_count += 1

        return {"deleted_memories": deleted_count, "cutoff_date": cutoff_date.isoformat()}

    async def archive_old_messages(self, context_manager, session_id: str, keep_recent: int = 50):
        """Archive old messages (keep only recent ones)."""
        context = await context_manager.get_session(session_id)
        if not context:
            return

        if len(context.messages) > keep_recent:
            # Keep only recent messages
            archived_count = len(context.messages) - keep_recent
            context.messages = context.messages[-keep_recent:]
            await context_manager.update_session(context)

            return {"archived_messages": archived_count}

        return {"archived_messages": 0}

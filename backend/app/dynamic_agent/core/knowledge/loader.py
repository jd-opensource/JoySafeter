"""
CTF Knowledge Loader

Loads and registers CTF keyword-guided recon knowledge for CTF mode.
Integrates with reference_search to provide context-aware keyword searches.

Task: T008 - Load/register CTF keyword-guided recon knowledge pack
"""

from pathlib import Path
from threading import Lock
from typing import Any

import yaml

from app.dynamic_agent.tools.ctf.reference import SearchResult, search_references_rg

from .models import (
    CTF_KNOWLEDGE_PATH,
    CtfKnowledge,
    KeywordSearchContext,
    Trick,
)
from .parser import (
    convert_attack_steps_to_tricks as _convert_attack_steps_to_tricks,
)
from .parser import (
    normalize_knowledge as _normalize_knowledge,
)
from .search import (
    get_default_hints as _get_default_hints_impl,
)
from .search import (
    search_by_query as _search_by_query_impl,
)
from .search import (
    search_yaml_with_keywords as _search_yaml_with_keywords_impl,
)

# Fallback keywords for legacy search_knowledge_with_llm (only used in ENABLE_EAGER_RAG mode)
FALLBACK_KEYWORDS = ["flag", "ctf", "exploit", "vulnerability"]

from loguru import logger  # noqa: E402


def convert_attack_steps_to_tricks(attack_steps: list[dict[str, Any]]) -> list[Trick]:
    """Compatibility wrapper. Implementation lives in `agent.core.knowledge.parser`."""
    return _convert_attack_steps_to_tricks(attack_steps)


def normalize_knowledge(yaml_data: dict[str, Any]) -> dict[str, Any]:
    """Compatibility wrapper. Implementation lives in `agent.core.knowledge.parser`."""
    return _normalize_knowledge(yaml_data)


class CtfKnowledgeLoader:
    """
    Loads and manages CTF knowledge packs.

    Provides:
    - Loading CTF knowledge from YAML files
    - Keyword-guided reference search
    - Context-aware keyword assembly
    """

    def __init__(self, knowledge_path: Path | None = None):
        self.knowledge_path = knowledge_path or CTF_KNOWLEDGE_PATH
        self._knowledge_cache: dict[str, CtfKnowledge] = {}
        self._loaded = False

    def load_knowledge(self) -> dict[str, CtfKnowledge]:
        """Load all CTF knowledge packs from YAML files."""
        if self._loaded:
            return self._knowledge_cache

        if not self.knowledge_path.exists():
            logger.warning(f"CTF knowledge path not found: {self.knowledge_path}")
            return {}

        for yaml_file in self.knowledge_path.glob("*.yaml"):
            try:
                with open(yaml_file, encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                    if data and isinstance(data, dict):
                        knowledge = CtfKnowledge(
                            name=data.get("name", yaml_file.stem),
                            category=data.get("category", "unknown"),
                            tags=data.get("tags", []),
                            description=data.get("description", ""),
                            prerequisites=data.get("prerequisites", []),
                            indicators=data.get("indicators", []),
                            detection=data.get("detection", []),
                            mitigation=data.get("mitigation", []),
                            limitations=data.get("limitations", []),
                        )
                        self._knowledge_cache[knowledge.name] = knowledge
                        logger.debug(f"Loaded CTF knowledge: {knowledge.name}")
            except Exception as e:
                logger.error(f"Failed to load {yaml_file}: {e}")

        self._loaded = True
        logger.info(f"Loaded {len(self._knowledge_cache)} CTF knowledge packs")
        return self._knowledge_cache

    def get_knowledge(self, name: str) -> CtfKnowledge | None:
        """Get a specific knowledge pack by name."""
        if not self._loaded:
            self.load_knowledge()
        return self._knowledge_cache.get(name)

    def search_with_keywords(
        self,
        context: KeywordSearchContext,
        search_paths: list[str] | None = None,
        max_results_per_keyword: int = 5,
    ) -> dict[str, list[SearchResult]]:
        """
        Perform keyword-guided search based on context.

        Args:
            context: Search context with challenge type and hints
            search_paths: Paths to search (uses defaults if None)
            max_results_per_keyword: Max results per keyword

        Returns:
            Dict mapping keywords to their search results
        """
        keywords = context.get_keywords()
        results: dict[str, list[SearchResult]] = {}

        logger.info(f"CTF keyword search with {len(keywords)} keywords: {keywords[:5]}...")

        for keyword in keywords:
            try:
                hits = search_references_rg(
                    query=keyword,
                    search_paths=search_paths,
                    max_results=max_results_per_keyword,
                    case_sensitive=False,
                )
                if hits:
                    results[keyword] = hits
                    logger.debug(f"Keyword '{keyword}' found {len(hits)} hits")
            except Exception as e:
                logger.error(f"Search error for keyword '{keyword}': {e}")

        return results

    def search_knowledge_with_llm(
        self,
        user_message: str,
        search_paths: list[str] | None = None,
    ) -> list[str]:
        """
        Legacy method for ENABLE_EAGER_RAG=true mode.

        In Lazy RAG mode (default), Agent uses knowledge_search tool directly.
        This method is only called when ENABLE_EAGER_RAG=true.

        Args:
            user_message: The original user message/challenge description
            search_paths: Paths to search for references

        Returns:
            List of actionable hints from knowledge base
        """
        # Simple keyword extraction from user message (no LLM call)
        keywords = [w.lower() for w in user_message.split() if len(w) > 3][:10]
        keywords.extend(FALLBACK_KEYWORDS)

        logger.info(f"🔍 Extracted keywords: {keywords[:5]}...")

        # Search YAML files using keywords
        hints = self._search_yaml_with_keywords(keywords)

        if hints:
            logger.info(f"✅ Found {len(hints)} hints from knowledge base")
        else:
            logger.info("⚠️ No matching knowledge found")

        return hints[:15]

    def _search_yaml_with_keywords(self, keywords: list[str]) -> list[str]:
        """
        Search YAML knowledge files using LLM-extracted keywords.

        NOTE: Implementation moved to `agent.core.knowledge.search` to keep this file small.
        """
        return _search_yaml_with_keywords_impl(
            knowledge_path=self.knowledge_path,
            ensure_loaded=self.load_knowledge,
            keywords=keywords,
        )

    def get_first_attempt_hints(
        self,
        challenge_type: str,
        user_hints: list[str] | None = None,
        file_signals: list[str] | None = None,
        search_paths: list[str] | None = None,
    ) -> list[str]:
        """
        Legacy method - kept for backward compatibility.
        Prefer search_knowledge_with_llm() for new code.
        """
        # Use fallback keywords if no user message available
        hints = self._search_yaml_with_keywords(FALLBACK_KEYWORDS)

        if not hints:
            hints = self._get_default_hints(challenge_type)

        return hints[:10]

    def search_by_query(self, query: str) -> list[dict[str, Any]]:
        """
        Search knowledge base by natural language query.

        This is the PRIMARY method for Lazy RAG - Agent calls this tool
        when it needs help, rather than pre-loading all knowledge.

        Args:
            query: Natural language query describing the problem
                   e.g., "Flask SSTI bypass WAF" or "IDOR enumerate ID range"

        Returns:
            List of matching knowledge entries with tricks
        """
        # NOTE: Implementation moved to `agent.core.knowledge.search` to keep this file small.
        return _search_by_query_impl(
            knowledge_path=self.knowledge_path,
            ensure_loaded=self.load_knowledge,
            query=query,
        )

    def _get_default_hints(self, challenge_type: str) -> list[str]:
        """Get default hints when no references are found."""
        # NOTE: Implementation moved to `agent.core.knowledge.search` to keep this file small.
        return _get_default_hints_impl(challenge_type)


# Application-level singleton for CTF knowledge base
# Note: This is immutable reference data (read-only after loading), not session/user data
_knowledge_loader: CtfKnowledgeLoader | None = None
_loader_lock = Lock()


def get_knowledge_loader() -> CtfKnowledgeLoader:
    """
    Get the application-level CTF knowledge loader singleton (thread-safe).

    Returns:
        CtfKnowledgeLoader instance with pre-loaded CTF knowledge base.

    Note:
        This singleton is justified because:
        1. Knowledge base is read-only reference data (immutable after loading)
        2. Loading ~hundreds of YAML files is expensive (~1-2s startup cost)
        3. Data is shared across all sessions (no session-specific state)
        4. Thread-safe for concurrent read access
        5. Similar to i18n dictionaries or configuration registries
    """
    global _knowledge_loader
    if _knowledge_loader is None:
        with _loader_lock:
            # Double-check locking pattern
            if _knowledge_loader is None:
                _knowledge_loader = CtfKnowledgeLoader()
                _knowledge_loader.load_knowledge()
    return _knowledge_loader


def search_ctf_references(
    challenge_type: str,
    user_hints: list[str] | None = None,
    file_signals: list[str] | None = None,
) -> list[str]:
    """
    Convenience function to search CTF references.

    Args:
        challenge_type: Type of CTF challenge
        user_hints: User-provided hints
        file_signals: File types in workspace

    Returns:
        List of actionable hints
    """
    loader = get_knowledge_loader()
    return loader.get_first_attempt_hints(
        challenge_type=challenge_type,
        user_hints=user_hints,
        file_signals=file_signals,
    )

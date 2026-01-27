from abc import ABC, abstractmethod
from typing import List

from langchain_core.language_models.llms import LLM

from app.schemas.memory import UserMemory
from app.utils.tokens import count_tokens as count_text_tokens


class MemoryOptimizationStrategy(ABC):
    """Abstract base class for memory optimization strategies.

    Subclasses must implement optimize() and aoptimize().
    get_system_prompt() is optional and only needed for LLM-based strategies.
    """

    def get_system_prompt(self) -> str:
        """Get system prompt for this optimization strategy.

        Returns:
            System prompt string for LLM-based strategies.
        """
        raise NotImplementedError

    @abstractmethod
    def optimize(
        self,
        memories: List[UserMemory],
        model: LLM,
    ) -> List[UserMemory]:
        """Optimize memories synchronously.

        Args:
            memories: List of UserMemory objects to optimize
            model: Model to use for optimization (if needed)

        Returns:
            List of optimized UserMemory objects
        """
        raise NotImplementedError

    @abstractmethod
    async def aoptimize(
        self,
        memories: List[UserMemory],
        model: LLM,
    ) -> List[UserMemory]:
        """Optimize memories asynchronously.

        Args:
            memories: List of UserMemory objects to optimize
            model: Model to use for optimization (if needed)

        Returns:
            List of optimized UserMemory objects
        """
        raise NotImplementedError

    def count_tokens(self, memories: List[UserMemory]) -> int:
        """Count total tokens across all memories.

        Args:
            memories: List of UserMemory objects

        Returns:
            Total token count using tiktoken (or fallback estimation)
        """
        return sum(count_text_tokens(mem.memory or "") for mem in memories)

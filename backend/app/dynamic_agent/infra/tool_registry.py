"""
Tool Registry and Classification System

This module provides a comprehensive tool registry with classification,
priority management, and dynamic selection capabilities.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Set

from langchain_core.tools import BaseTool

ToolCategory = str


class ToolPriority(str, Enum):
    """Tool priority levels."""

    CRITICAL = "critical"  # Always include if relevant
    HIGH = "high"  # Include in most scenarios
    MEDIUM = "medium"  # Include based on context
    LOW = "low"  # Include only if space available
    OPTIONAL = "optional"  # Rarely include


ToolPriorityScore = {
    ToolPriority.CRITICAL: 100,
    ToolPriority.HIGH: 75,
    ToolPriority.MEDIUM: 50,
    ToolPriority.LOW: 25,
    ToolPriority.OPTIONAL: 10,
}


@dataclass
class ToolMetadata:
    """Metadata for a registered tool."""

    name: str
    category: ToolCategory
    description: str
    priority: Optional[ToolPriority] = None
    keywords: Set[str] = field(default_factory=set)
    dependencies: Set[str] = field(default_factory=set)  # Other tool names
    scenarios: Set[str] = field(default_factory=set)  # Use case scenarios
    cost_estimate: int = 1  # Relative execution cost (1-10)

    def matches_keywords(self, query_keywords: Set[str]) -> int:
        """Calculate keyword match score."""
        if not query_keywords:
            return 0
        matches = self.keywords.intersection(query_keywords)
        return len(matches)

    def matches_scenario(self, scenario: str) -> bool:
        """Check if tool matches a scenario."""
        return scenario.lower() in self.scenarios


class ToolRegistry:
    """Central registry for all available tools."""

    def __init__(self):
        self._tools_meta: Dict[str, ToolMetadata] = {}
        self._tools_obj: Dict[str, BaseTool] = {}
        self._category_index: Dict[ToolCategory, Set[str]] = {}

    def register(self, metadata: ToolMetadata, tool: BaseTool):
        """Register a tool with metadata."""
        self._tools_meta[metadata.name] = metadata
        self._tools_obj[metadata.name] = tool

        # Update category index
        if metadata.category not in self._category_index:
            self._category_index[metadata.category] = set()
        self._category_index[metadata.category].add(metadata.name)

    def get_tool(self, name: str) -> Optional[BaseTool]:
        """Get tool metadata by name."""
        return self._tools_obj.get(name)

    def get_tool_meta(self, name: str) -> Optional[ToolMetadata]:
        """Get tool metadata by name."""
        return self._tools_meta.get(name)

    def get_tool_by_category(self, category: ToolCategory) -> Set[BaseTool]:
        """Get all tools in a category."""
        tool_names = self._category_index.get(category, set())
        return set([self._tools_obj[name] for name in tool_names])

    def get_tool_meta_by_category(self, category: ToolCategory) -> List[ToolMetadata]:
        """Get all tools in a category."""
        tool_names = self._category_index.get(category, set())
        return [self._tools_meta[name] for name in tool_names]

    def get_all_categories(self) -> List[ToolCategory]:
        """Get all available categories."""
        return list(self._category_index.keys())

    def get_all_tools(self) -> List[str]:
        """Get all registered tool names."""
        return list(self._tools_obj.keys())

    def search(
        self,
        keywords: Optional[Set[str]] = None,
        categories: Optional[List[ToolCategory]] = None,
        min_priority_score: Optional[ToolPriority] = None,
        scenario: Optional[str] = None,
    ) -> List[ToolMetadata]:
        """Search tools by keywords, categories, priority, and scenario."""
        candidates: List[ToolMetadata] = []

        # Filter by categories
        if categories:
            for category in categories:
                candidates.extend(self.get_tool_meta_by_category(category))
        else:
            # Get all tools
            candidates = list(self._tools_meta.values())

        # Filter by keywords
        if keywords:
            filtered = []
            for tool in candidates:
                if tool.matches_keywords(keywords) > 0:
                    filtered.append(tool)
            candidates = filtered

        # Filter by scenario
        if scenario:
            filtered = []
            for tool in candidates:
                if tool.matches_scenario(scenario):
                    filtered.append(tool)
            candidates = filtered

        # Filter by priority
        if min_priority_score:
            min_score = ToolPriorityScore.get(min_priority_score, 0)
            filtered = []
            for tool in candidates:
                tool_score = ToolPriorityScore.get(tool.priority, 0) if tool.priority else 0
                if tool_score >= min_score:
                    filtered.append(tool)
            candidates = filtered

        return candidates

    def get_by_category(self, category: ToolCategory) -> List[ToolMetadata]:
        """Get tools by category (alias for get_tool_meta_by_category)."""
        return self.get_tool_meta_by_category(category)

    def clear(self):
        """Clear all tool metadata."""
        self._tools_meta.clear()
        self._tools_obj.clear()
        self._category_index.clear()

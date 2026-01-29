"""
Dynamic Tool Selector

This module implements intelligent tool selection based on:
- User intent analysis
- Task context and scenario
- Tool priority and relevance
- Resource constraints (max 50 tools)
- CTF mode prioritization (shell/python first)
"""

import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple

from langchain_core.tools import BaseTool

from app.dynamic_agent.core.constants import (
    CtfToolType,
)
from app.dynamic_agent.infra.context import tool_registry
from app.dynamic_agent.infra.tool_registry import (
    ToolCategory,
    ToolMetadata,
    ToolPriority,
    ToolPriorityScore,
    ToolRegistry,
)
from app.dynamic_agent.tools.ctf.primitives import prioritize_tools as ctf_prioritize_tools


@dataclass
class SelectionContext:
    """Context for tool selection."""

    user_query: str
    scenario: Optional[str] = None
    preferred_categories: Optional[List[ToolCategory]] = None
    max_tools: int = 50
    min_priority: Optional[ToolPriority] = None
    include_general: bool = True
    cost_budget: Optional[int] = None  # Total cost budget
    is_ctf: bool = False  # CTF mode flag for shell/python prioritization


class IntentAnalyzer:
    """Analyze user intent to determine relevant tool categories and keywords."""

    # Scenario patterns
    SCENARIO_PATTERNS = {
        "ctf": [
            r"\bctf\b",
            r"capture\s+the\s+flag",
            r"\bflag\b",
            r"flag\{",
            r"\bpwn\b",
            r"pwnable",
            r"\breverse\b",
            r"reversing",
            r"\bcrypto\b",
            r"cryptography",
            r"\bmisc\b",
            r"miscellaneous",
            r"\bchallenge\b",
            r"jeopardy",
            r"attack.*defense",
            r"get\s+flag",
            r"find\s+flag",
            r"submit\s+flag",
        ],
        "web_security": [
            r"web\s+app",
            r"website",
            r"http",
            r"xss",
            r"sql\s+injection",
            r"csrf",
            r"web\s+vulnerability",
            r"web\s+scan",
        ],
        "api_security": [r"\bapi\b", r"rest", r"graphql", r"jwt", r"token", r"endpoint"],
        "network_scan": [r"network\s+scan", r"port\s+scan", r"nmap", r"host\s+discovery"],
        "reconnaissance": [r"recon", r"information\s+gathering", r"osint", r"enumeration", r"footprint", r"discover"],
        "exploitation": [r"exploit", r"attack", r"penetration", r"metasploit", r"payload"],
        "code_analysis": [r"code\s+review", r"static\s+analysis", r"sast", r"source\s+code", r"vulnerability\s+scan"],
        "reverse_engineering": [
            r"reverse\s+engineering",
            r"binary\s+analysis",
            r"disassemble",
            r"decompile",
            r"malware",
        ],
        "password_cracking": [r"password\s+crack", r"hash\s+crack", r"brute\s+force", r"dictionary"],
        "forensics": [r"forensic", r"incident\s+response", r"log\s+analysis", r"evidence"],
        "vulnerability_assessment": [
            r"vulnerability\s+assessment",
            r"vuln\s+scan",
            r"security\s+audit",
            r"penetration\s+test",
        ],
    }

    # Category keywords
    # CATEGORY_KEYWORDS = {
    #     ToolCategory.RECONNAISSANCE: {
    #         "reconnaissance", "recon", "information", "gathering", "osint",
    #         "enumeration", "discovery", "footprint"
    #     },
    #     ToolCategory.SCANNING: {
    #         "scan", "scanner", "port", "vulnerability", "nmap", "detect"
    #     },
    #     ToolCategory.EXPLOITATION: {
    #         "exploit", "attack", "payload", "metasploit", "shell", "compromise"
    #     },
    #     ToolCategory.WEB_SECURITY: {
    #         "web", "http", "https", "xss", "sql", "injection", "csrf", "website"
    #     },
    #     ToolCategory.API_SECURITY: {
    #         "api", "rest", "graphql", "jwt", "token", "endpoint"
    #     },
    #     ToolCategory.NETWORK_ANALYSIS: {
    #         "network", "traffic", "packet", "capture", "sniff", "ssl", "tls"
    #     },
    #     ToolCategory.CODE_ANALYSIS: {
    #         "code", "static", "sast", "analysis", "source", "dependency"
    #     },
    #     ToolCategory.REVERSE_ENGINEERING: {
    #         "reverse", "binary", "disassemble", "decompile", "assembly"
    #     },
    #     ToolCategory.CRYPTOGRAPHY: {
    #         "crypto", "encryption", "hash", "cipher", "decrypt", "crack"
    #     },
    #     ToolCategory.DATA_EXTRACTION: {
    #         "extract", "parse", "data", "regex", "json", "log"
    #     },
    #     ToolCategory.FILE_OPERATIONS: {
    #         "file", "read", "write", "search", "directory"
    #     },
    #     ToolCategory.REPORTING: {
    #         "report", "document", "findings", "generate", "output"
    #     },
    #     ToolCategory.POST_EXPLOITATION: {
    #         "post", "privilege", "escalation", "credential", "dump"
    #     }
    # }

    def analyze(self, query: str) -> Tuple[Optional[str], List[ToolCategory], Set[str]]:
        """
        Analyze user query to extract scenario, categories, and keywords.

        Returns:
            Tuple of (scenario, relevant_categories, keywords)
        """
        query_lower = query.lower()

        # Detect scenario
        scenario = self._detect_scenario(query_lower)

        # Extract relevant categories
        categories = self._extract_categories(query_lower)

        # Extract keywords
        keywords = self._extract_keywords(query_lower)

        return scenario, categories, keywords

    def _detect_scenario(self, query: str) -> Optional[str]:
        """Detect the most relevant scenario from query."""
        for scenario, patterns in self.SCENARIO_PATTERNS.items():
            for pattern in patterns:
                # todo go to optimize
                if re.search(pattern, query, re.IGNORECASE):
                    return scenario
        return None

    def _extract_categories(self, query: str) -> List[ToolCategory]:
        """Extract relevant tool categories from query."""
        # CATEGORY_KEYWORDS was commented out, use scenario patterns instead
        # This is a simplified implementation
        relevant_categories: List[ToolCategory] = []
        query_lower = query.lower()

        # Map scenario patterns to categories (simplified)
        # ToolCategory is str type, use string values directly
        # This would need proper implementation based on business logic
        if any(pattern in query_lower for pattern in ["recon", "osint", "enumeration"]):
            relevant_categories.append("reconnaissance")
        if any(pattern in query_lower for pattern in ["scan", "nmap", "port"]):
            relevant_categories.append("scanning")

        return relevant_categories

    def _extract_keywords(self, query: str) -> Set[str]:
        """Extract relevant keywords from query."""
        # Remove common stop words
        stop_words = {
            "the",
            "a",
            "an",
            "and",
            "or",
            "but",
            "in",
            "on",
            "at",
            "to",
            "for",
            "of",
            "with",
            "by",
            "from",
            "is",
            "are",
            "was",
            "were",
            "i",
            "you",
            "we",
            "they",
            "need",
            "want",
            "can",
            "could",
            "should",
            "would",
            "please",
            "help",
            "me",
            "my",
            "how",
            "what",
            "when",
            "where",
        }

        # Tokenize and filter
        words = re.findall(r"\b\w+\b", query.lower())
        keywords = {word for word in words if word not in stop_words and len(word) > 2}

        return keywords


class DynamicToolSelector:
    """
    Intelligent tool selector that dynamically chooses tools based on context.

    Key features:
    - Intent-based selection
    - Priority-based ranking
    - Cost-aware selection
    - Dependency resolution
    - Scenario matching
    """

    def __init__(self, registry: Optional[ToolRegistry] = None):
        self.registry = registry or tool_registry
        self.intent_analyzer = IntentAnalyzer()

    def select_tools(
        self,
        context: SelectionContext,
    ) -> List[str]:
        """
        Select optimal tools based on context.

        Args:
            context: Selection context with user query and constraints

        Returns:
            List of selected tool names
        """
        # Analyze user intent
        scenario, categories, keywords = self.intent_analyzer.analyze(context.user_query)

        # Override with explicit context if provided
        if context.scenario:
            scenario = context.scenario
        if context.preferred_categories:
            categories = context.preferred_categories

        # Get candidate tools
        candidates = self._get_candidates(
            scenario=scenario, categories=categories, keywords=keywords, min_priority=context.min_priority
        )

        # Score and rank tools
        scored_tools = self._score_tools(candidates=candidates, keywords=keywords, scenario=scenario)

        # Apply constraints and select
        selected = self._apply_constraints(
            scored_tools=scored_tools,
            max_tools=context.max_tools,
            cost_budget=context.cost_budget,
            include_general=context.include_general,
        )

        # Resolve dependencies
        final_tools = self._resolve_dependencies(selected)

        tool_names = [tool.name for tool in final_tools]

        # Apply CTF prioritization if in CTF mode
        if context.is_ctf or scenario == "ctf":
            tool_names = ctf_prioritize_tools(tool_names, is_ctf=True)

        return tool_names

    def _get_candidates(
        self,
        scenario: Optional[str],
        categories: List[ToolCategory],
        keywords: Set[str],
        min_priority: Optional[ToolPriority],
    ) -> List[ToolMetadata]:
        """Get candidate tools based on initial filters."""
        if scenario or categories:
            # Use targeted search
            candidates = self.registry.search(
                keywords=keywords if keywords else None,
                categories=categories if categories else None,
                min_priority_score=min_priority,
                scenario=scenario,
            )
        else:
            # Broad search with keywords
            # ToolPriorityScore.get returns int | None, use min_priority directly
            candidates = self.registry.search(
                keywords=keywords if keywords else None,
                min_priority_score=min_priority,
            )

        return candidates

    def _score_tools(
        self, candidates: List[ToolMetadata], keywords: Set[str], scenario: Optional[str]
    ) -> List[Tuple[ToolMetadata, float]]:
        """
        Score tools based on relevance.

        Scoring factors:
        - Priority (40%)
        - Keyword match (30%)
        - Scenario match (20%)
        - Cost efficiency (10%)
        """
        scored = []

        for tool in candidates:
            score = 0.0

            # Priority score (0-40)
            tool_priority = tool.priority if tool.priority else ToolPriority.MEDIUM
            priority_score = (ToolPriorityScore.get(tool_priority, 50) / 100) * 40
            score += priority_score

            # Keyword match score (0-30)
            if keywords:
                keyword_matches = tool.matches_keywords(keywords)
                keyword_score = min(keyword_matches / len(keywords), 1.0) * 30
                score += keyword_score

            # Scenario match score (0-20)
            if scenario and tool.matches_scenario(scenario):
                score += 20

            # Cost efficiency score (0-10)
            # Lower cost = higher score
            cost_score = (10 - min(tool.cost_estimate, 10)) / 10 * 10
            score += cost_score

            scored.append((tool, score))

        # Sort by score descending
        scored.sort(key=lambda x: x[1], reverse=True)

        return scored

    def _apply_constraints(
        self,
        scored_tools: List[Tuple[ToolMetadata, float]],
        max_tools: int,
        cost_budget: Optional[int],
        include_general: bool,
    ) -> List[ToolMetadata]:
        """Apply constraints and select final tools."""
        selected = []
        total_cost = 0

        # Always include critical tools first
        critical_tools = [tool for tool, score in scored_tools if tool.priority == ToolPriority.CRITICAL]

        for tool in critical_tools[:max_tools]:
            selected.append(tool)
            total_cost += tool.cost_estimate

        # Add remaining tools by score
        max_tools - len(selected)

        for tool, score in scored_tools:
            if len(selected) >= max_tools:
                break

            # Skip if already selected
            if tool in selected:
                continue

            # Skip general tools if not included
            if not include_general and tool.category == "general":
                continue

            # Check cost budget
            if cost_budget and (total_cost + tool.cost_estimate) > cost_budget:
                continue

            selected.append(tool)
            total_cost += tool.cost_estimate

        return selected

    def _resolve_dependencies(self, selected: List[ToolMetadata]) -> List[ToolMetadata]:
        """Resolve tool dependencies and add missing tools."""
        final_tools = list(selected)
        selected_names = {tool.name for tool in selected}

        # Check dependencies
        for tool in selected:
            for dep_name in tool.dependencies:
                if dep_name not in selected_names:
                    dep_tool_meta = self.registry.get_tool_meta(dep_name)
                    if dep_tool_meta:
                        final_tools.append(dep_tool_meta)
                        selected_names.add(dep_name)

        return final_tools

    def get_tools_by_category(self, category: ToolCategory) -> List[str]:
        """Get all tool names in a category."""
        tools = self.registry.get_by_category(category)
        return [tool.name for tool in tools]

    def get_all_categories(self) -> List[str]:
        """Get all available categories."""
        categories = self.registry.get_all_categories()
        # ToolCategory is str, not Enum
        return [str(cat) for cat in categories]

    def explain_selection(self, context: SelectionContext, selected_tools: List[str]) -> str:
        """
        Provide explanation for tool selection.

        Args:
            context: Selection context used
            selected_tools: List of selected tool names

        Returns:
            Human-readable explanation
        """
        scenario, categories, keywords = self.intent_analyzer.analyze(context.user_query)

        explanation = "# Tool Selection Explanation\n\n"
        explanation += f"**Query:** {context.user_query}\n\n"

        if scenario:
            explanation += f"**Detected Scenario:** {scenario}\n"

        if categories:
            # ToolCategory is str, not Enum
            cat_names = [str(cat) for cat in categories]
            explanation += f"**Relevant Categories:** {', '.join(cat_names)}\n"

        if keywords:
            explanation += f"**Key Terms:** {', '.join(sorted(keywords)[:10])}\n"

        explanation += f"\n**Selected {len(selected_tools)} tools:**\n\n"

        for tool_name in selected_tools:
            tool_meta = self.registry.get_tool_meta(tool_name)
            if tool_meta:
                # ToolCategory is str, not Enum
                explanation += f"- **{tool_meta.name}** ({tool_meta.category}): {tool_meta.description}\n"
                priority_str = tool_meta.priority.value if tool_meta.priority else "medium"
                explanation += f"  - Priority: {priority_str}\n"
                explanation += f"  - Cost: {tool_meta.cost_estimate}/10\n\n"

        return explanation

    def generate_ctf_first_attempt(
        self,
        context: SelectionContext,
        reference_hits: Optional[List[Dict]] = None,
    ) -> Optional[Dict]:
        """
        Generate first shell/python attempt for CTF mode.

        Args:
            context: Selection context with user query
            reference_hits: Optional list of reference hits from search

        Returns:
            Dict with tool_type, command/code, and rationale, or None
        """
        from app.dynamic_agent.tools.ctf.primitives import (
            generate_action_from_reference,
            get_template,
        )

        # Analyze query for CTF patterns
        scenario, categories, keywords = self.intent_analyzer.analyze(context.user_query)

        if scenario != "ctf" and not context.is_ctf:
            return None

        # Try to generate from reference hits first
        if reference_hits:
            from uuid import UUID

            from app.dynamic_agent.storage.session.ctf import CtfReferenceSource, ReferenceHit

            for ref_dict in reference_hits:
                # Convert dict to ReferenceHit if needed
                if isinstance(ref_dict, dict):
                    # Create ReferenceHit from dict
                    source_str = ref_dict.get("source", "heuristic")
                    source = (
                        CtfReferenceSource(source_str) if isinstance(source_str, str) else CtfReferenceSource.HEURISTIC
                    )
                    ref = ReferenceHit(
                        ref_id=UUID(ref_dict["ref_id"]) if ref_dict.get("ref_id") else UUID(),
                        session_id=UUID(ref_dict["session_id"]) if ref_dict.get("session_id") else None,
                        source=source,
                        location=ref_dict.get("location", ""),
                        snippet=ref_dict.get("snippet"),
                        confidence=ref_dict.get("confidence", 0.5),
                    )
                else:
                    ref = ref_dict  # Already a ReferenceHit
                action = generate_action_from_reference(ref)
                if action:
                    return {
                        "tool_type": action["tool_type"].value,
                        "suggested_command": action.get("suggested_command", ""),
                        "template_name": action.get("template_name", ""),
                        "rationale": f"Based on reference: {action.get('source', 'unknown')}",
                        "confidence": action.get("confidence", 0.5),
                    }

        # Fallback: suggest based on keywords
        query_lower = context.user_query.lower()

        # Crypto patterns
        if any(kw in query_lower for kw in ["base64", "decode", "encode"]):
            template = get_template("base64_decode")
            if template:
                return {
                    "tool_type": template.tool_type.value,
                    "template_name": template.name,
                    "description": template.description,
                    "rationale": "Detected encoding/decoding task",
                    "confidence": 0.7,
                }

        # Web patterns
        if any(kw in query_lower for kw in ["curl", "http", "url", "web", "request"]):
            template = get_template("curl_get")
            if template:
                return {
                    "tool_type": template.tool_type.value,
                    "template_name": template.name,
                    "description": template.description,
                    "rationale": "Detected web request task",
                    "confidence": 0.7,
                }

        # Pwn patterns
        if any(kw in query_lower for kw in ["nc", "netcat", "connect", "port", "pwn"]):
            template = get_template("nc_connect")
            if template:
                return {
                    "tool_type": template.tool_type.value,
                    "template_name": template.name,
                    "description": template.description,
                    "rationale": "Detected network connection task",
                    "confidence": 0.7,
                }

        # Misc patterns
        if any(kw in query_lower for kw in ["strings", "file", "binary", "extract"]):
            template = get_template("strings_extract")
            if template:
                return {
                    "tool_type": template.tool_type.value,
                    "template_name": template.name,
                    "description": template.description,
                    "rationale": "Detected file analysis task",
                    "confidence": 0.6,
                }

        # Default: suggest shell command for CTF
        return {
            "tool_type": CtfToolType.SHELL.value,
            "template_name": None,
            "description": "General shell command for CTF",
            "rationale": "CTF mode active - shell/python prioritized",
            "confidence": 0.5,
        }

    def apply_user_hints_to_actions(
        self,
        hints: List[Dict],
        context: SelectionContext,
    ) -> Tuple[List[Dict], List[Dict]]:
        """
        Apply user hints to generate planned actions or mark as skipped.

        Args:
            hints: List of hint dicts with 'content' and optional 'order'
            context: Selection context

        Returns:
            Tuple of (planned_actions, skipped_hints)
        """
        from app.dynamic_agent.storage.session.ctf import UserHint
        from app.dynamic_agent.tools.ctf.primitives import generate_action_from_hint

        planned_actions = []
        skipped_hints = []

        for i, hint_data in enumerate(hints):
            content = hint_data.get("content", "") if isinstance(hint_data, dict) else str(hint_data)

            # Create a UserHint object for processing
            hint = UserHint(
                content=content,
                order=hint_data.get("order", i) if isinstance(hint_data, dict) else i,
            )

            # Try to generate action from hint
            action = generate_action_from_hint(hint)

            if action:
                hint.apply()
                planned_actions.append(
                    {
                        "hint_content": content[:100],
                        "hint_order": hint.order,
                        "tool_type": action.get("tool_type", CtfToolType.SHELL).value
                        if hasattr(action.get("tool_type"), "value")
                        else action.get("tool_type", "shell"),
                        "template_name": action.get("template_name"),
                        "description": action.get("description", ""),
                        "risk_level": action.get("risk_level", "low").value
                        if hasattr(action.get("risk_level"), "value")
                        else action.get("risk_level", "low"),
                        "status": "applied",
                    }
                )
            else:
                # Could not generate action - mark as skipped
                skip_reason = self._determine_skip_reason(content, context)
                hint.skip(skip_reason)
                skipped_hints.append(
                    {
                        "hint_content": content[:100],
                        "hint_order": hint.order,
                        "status": "skipped",
                        "skip_reason": skip_reason,
                    }
                )

        return planned_actions, skipped_hints

    def _determine_skip_reason(self, hint_content: str, context: SelectionContext) -> str:
        """Determine why a hint was skipped."""
        content_lower = hint_content.lower()

        # Check for vague hints
        if len(hint_content.strip()) < 10:
            return "Hint too short to generate specific action"

        # Check for non-actionable hints
        non_actionable_patterns = [
            "maybe",
            "perhaps",
            "might",
            "could be",
            "not sure",
            "i think",
            "possibly",
            "probably",
        ]
        if any(p in content_lower for p in non_actionable_patterns):
            return "Hint is too vague or uncertain to convert to action"

        # Check for already-tried patterns
        if "already tried" in content_lower or "didn't work" in content_lower:
            return "Hint references previously attempted approach"

        # Default reason
        return "Could not map hint to a specific shell/Python action"


def create_mock_tool_implementations() -> Dict[str, BaseTool]:
    """
    Create mock tool implementations for testing.

    Returns:
        Dict mapping tool names to BaseTool instances
    """
    from langchain_core.tools import tool

    mock_tools = {}
    registry = tool_registry

    # Create a mock implementation for each registered tool
    for tool_name, metadata in registry._tools_meta.items():
        # Create a closure to capture metadata
        def make_tool_func(meta: ToolMetadata):
            @tool(name=meta.name, description=meta.description)  # type: ignore[call-overload]
            def mock_tool(query: str) -> str:
                """Mock tool implementation."""
                return f"[Mock] {meta.name} executed with query: {query}"

            return mock_tool

        mock_tools[tool_name] = make_tool_func(metadata)

    return mock_tools

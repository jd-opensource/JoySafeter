"""
Dynamic Tool Selection Agent using LangGraph

This module implements an intelligent agent that dynamically discovers and selects
tools based on user goals. It uses LangGraph's prebuilt ReAct agent pattern with
custom tool selection logic.

Key Features:
- Automatic tool category discovery
- Context-aware tool selection
- ReAct-style reasoning and execution
- Support for multi-step tool workflows
"""

import json
import logging
import os
from operator import add
from typing import Annotated, Any, Dict, List, Optional, TypedDict

from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool

from app.common.constants import COMMAND_TOOL, KNOWLEDGE_TOOL
from app.dynamic_agent.infra.metadata_context import MetadataContext
from app.dynamic_agent.observability.langfuse import callbacks
from app.dynamic_agent.prompts.registry import get_registry

logger = logging.getLogger(__name__)


class AgentState(TypedDict):
    """
    State structure for the dynamic tool selection agent.

    Attributes:
        input: User's original input/goal description
        available_categories: List of discovered tool categories
        selected_categories: Categories selected by the agent
        available_tools: Tools discovered from selected categories
        selected_tools: Final list of tools selected for the task
        messages: Conversation history with the LLM
        intermediate_steps: List of (action, observation) tuples from tool execution
        final_output: Final response to the user
        iteration_count: Number of iterations performed
        error: Error message if any step fails
    """

    # Input and output
    input: str
    final_output: Optional[str]

    # Tool discovery and selection
    available_categories: List[str]
    selected_categories: List[str]
    available_tools: List[Dict[str, Any]]
    selected_tools: List[str]

    # Agent execution
    messages: Annotated[List[Dict[str, Any]], add]  # Append-only message history
    intermediate_steps: Annotated[List[tuple], add]  # Append-only execution steps

    # Control flow
    iteration_count: int
    error: Optional[str]


def create_initial_state(user_input: str) -> AgentState:
    """
    Create initial agent state from user input.

    Args:
        user_input: User's goal description or direct input

    Returns:
        Initialized AgentState
    """
    return AgentState(
        input=user_input,
        final_output=None,
        available_categories=[],
        selected_categories=[],
        available_tools=[],
        selected_tools=[],
        messages=[],
        intermediate_steps=[],
        iteration_count=0,
        error=None,
    )


class DynamicToolSelectionAgent:
    """
    Agent that dynamically selects and uses tools based on user goals.

    This agent follows a two-phase approach:
    1. Tool Discovery: Uses helper tools to discover available categories and tools
    2. Task Execution: Uses selected tools to accomplish the user's goal

    The agent uses LangGraph's prebuilt ReAct agent for reasoning and tool execution.
    """

    # System prompt for the agent
    SYSTEM_PROMPT_BACKUP = f"""You are an intelligent cybersecurity assistant with dynamic tool selection capabilities.

    Your workflow:
    1. Understand the user's goal or request
    2. Use list_all_tool_categories() to discover available tool categories
    3. Analyze which categories are relevant to the user's goal
    4. Use list_tools_by_categories() to get tools from relevant categories
    5. Select the most appropriate tools for the task
    6. If task is planning related, you **must** prioritize {KNOWLEDGE_TOOL}; otherwise, you **must** prioritize {COMMAND_TOOL}.
    7. You will execute the task using the selected tools

    Guidelines:
    - Be strategic in tool selection - choose only relevant categories
    - The total number of tools **MUST BE** less than 3 for fucus.
    - The number of {KNOWLEDGE_TOOL} **MUST BE** less than 50%.
    - Prioritize tools with higher priority levels
    - Consider tool cost estimates for efficiency
    - Provide clear explanations of your reasoning

    Available helper tools:
    - list_all_tool_categories: Discover all tool categories
    - list_tools_by_categories: Get tools from specific categories


    About final result:
    - the selected tools will be ordered by relevance
    - final result MUST BE a JSON array containing tools selected, for example
    `["a","b"]`
    - the final result format **MUST BE** valid before return
    """

    # System prompt loaded from registry
    @staticmethod
    def _get_system_prompt() -> str:
        """Load system prompt from registry with variable substitution."""
        try:
            registry = get_registry()
            prompt = registry.get("tools/tool_selection")
            return prompt.render(
                KNOWLEDGE_TOOL=KNOWLEDGE_TOOL,
                COMMAND_TOOL=COMMAND_TOOL,
            )
        except Exception as e:
            import logging

            logging.getLogger(__name__).warning(f"Failed to load tool_selection prompt: {e}")
            return "You are an intelligent cybersecurity assistant."

    SYSTEM_PROMPT = None  # Will be set in __init__

    def __init__(
        self,
        llm: Optional[BaseChatModel],
        tools: Optional[List[BaseTool]] = None,
        max_iterations: int = 15,
        verbose: bool = True,
    ):
        """
        Initialize the dynamic tool selection agent.
        :param llm:
        :param tools:
        :param max_iterations:
        :param verbose:
        """
        """

        Args:
            llm: Language model to use (defaults to GPT-4)
            max_iterations: Maximum number of agent iterations
            verbose: Whether to print verbose output
        """

        self.llm = llm
        self.max_iterations = max_iterations
        self.verbose = verbose

        # Initialize with tool discovery tools
        self.discovery_tools = tools

        # Load system prompt from registry
        system_prompt = self._get_system_prompt()

        # Create the ReAct agent with discovery tools
        # create_agent expects model to be non-None, but we allow Optional
        if self.llm is None:
            raise ValueError("LLM model is required for DynamicToolSelectionAgent")

        from typing import Any as AnyType

        self.agent: AnyType = create_agent(
            model=self.llm,
            tools=self.discovery_tools or [],
            system_prompt=system_prompt,
            debug=verbose,
        )
        self.agent.bind(llm={"parallel_tool_calls": False})

    def run(self, messages: List[Dict[str, str]], metadata: Dict[str, Any]) -> Dict[str, Any]:
        """
        Run the agent with user input.

        Args:
            user_input: User's goal description or direct input

        Returns:
            Dictionary containing:
            - output: Final response
            - selected_tools: List of tools that were selected
            - messages: Full conversation history
        """
        # if self.verbose:
        #     print(f"\n{'=' * 70}")
        #     print(f"Dynamic Tool Selection Agent")
        #     print(f"{'=' * 70}")
        #     print(f"User Input: {user_input}\n")
        #
        # # Create initial state
        # state = create_initial_state(user_input)

        # Prepare input for the agent
        inputs = {"messages": messages}

        # Run the agent
        try:
            metadata = MetadataContext.get() or {}
            result = self.agent.ainvoke(
                inputs,
                config={
                    "callbacks": metadata.get("callbacks", []),
                    "metadata": {k: v for k, v in metadata.items() if k != "callbacks"},
                    "recursion_limit": int(os.getenv("AGENT_MAX_INTERACTIVE_STEPS", 64)),
                },
            )

            if self.verbose:
                print(f"\n{'=' * 70}")
                print("Agent Execution Complete")
                print(f"{'=' * 70}\n")

            # Extract the final message
            messages = result.get("messages", [])
            final_message = messages[-1] if messages else None

            try:
                # Check if final_message has content attribute
                if final_message is None or not hasattr(final_message, "content"):
                    return {
                        "output": [],
                        "success": False,
                        "error": "No output generated",
                    }
                content = getattr(final_message, "content", None)
                if not content:
                    return {
                        "output": [],
                        "success": False,
                        "error": "No output generated",
                    }
                else:
                    output = json.loads(content)
                    return {
                        "output": output,
                        "success": True,
                    }
            except Exception as e:
                logger.exception("Failed to parse output")
                return {
                    "output": None,
                    "success": False,
                    "error": str(e),
                }

        except Exception as e:
            logger.exception("Agent execution failed")
            if self.verbose:
                print(f"\n❌ Error: {e}\n")

            return {
                "success": False,
                "error": f"Error: {str(e)}",
            }

    async def arun(self, messages: List[Dict[str, str]], metadata: Dict[str, Any]) -> Dict[str, Any]:
        """
        Async version of run().

        Args:
            user_input: User's goal description or direct input

        Returns:
            Dictionary containing execution results
        """
        # if self.verbose:
        #     print(f"\n{'=' * 70}")
        #     print(f"Dynamic Tool Selection Agent (Async)")
        #     print(f"{'=' * 70}")
        #     print(f"User Input: {user_input}\n")

        # Prepare input for the agent
        inputs = {"messages": messages}

        # Run the agent asynchronously
        try:
            result = await self.agent.ainvoke(
                inputs,
                config={
                    "callbacks": callbacks(),
                    "metadata": metadata,
                    "recursion_limit": int(os.getenv("AGENT_MAX_INTERACTIVE_STEPS", 64)),
                },
            )

            if self.verbose:
                print(f"\n{'=' * 70}")
                print("Agent Execution Complete")
                print(f"{'=' * 70}\n")

            # Extract the final message
            messages = result.get("messages", [])
            final_message = messages[-1] if messages else None
            # Check if final_message has content attribute
            if final_message is not None and hasattr(final_message, "content"):
                content = getattr(final_message, "content", "No output generated")
            else:
                content = "No output generated"
            return {
                "output": content,
                "messages": messages,
                "success": True,
            }

        except Exception as e:
            if self.verbose:
                print(f"\n❌ Error: {e}\n")

            return {
                "output": f"Error: {str(e)}",
                "messages": [],
                "success": False,
                "error": str(e),
            }


def create_select_agent(
    llm: Optional[BaseChatModel],
    tools: List[BaseTool],
    verbose: bool = True,
) -> DynamicToolSelectionAgent:
    """
    Factory function to create a dynamic tool selection agent.

    Args:
        llm: Language model to use (defaults to GPT-4)
        verbose: Whether to print verbose output

    Returns:
        Configured DynamicToolSelectionAgent instance
    """
    return DynamicToolSelectionAgent(
        llm=llm,
        tools=tools,
        verbose=verbose,
    )

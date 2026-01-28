"""
CodeAgent - Production-ready code execution agent for DeepAgents.

This module provides a complete implementation of a code-based agent that solves
tasks through the Thought → Code → Observation iterative pattern.

Key Features:
- Secure Python execution via AST interpretation
- Docker-based sandboxing for unsafe code
- State persistence across execution steps
- Tool injection and compensation
- Planning capabilities for complex tasks
- Data analysis presets
- Multi-agent support with managed agents
- Comprehensive monitoring and logging
- Rate limiting and retry mechanisms
- Final answer validation
- Step callbacks for extensibility

Usage:
    >>> from app.core.agent.code_agent import CodeAgent, get_code_agent, tool
    >>>
    >>> # Quick start
    >>> agent = get_code_agent(model_name="gpt-4")
    >>> result = await agent.run("Calculate the sum of primes under 100")
    >>>
    >>> # With custom tools using @tool decorator
    >>> @tool
    ... def search(query: str) -> str:
    ...     '''Search the web.
    ...
    ...     Args:
    ...         query: Search query
    ...     '''
    ...     return web_search(query)
    >>>
    >>> agent = CodeAgent(
    ...     llm=my_llm_function,
    ...     tools={"search": search},
    ... )
    >>>
    >>> # With streaming
    >>> async for event in agent.run_stream("Analyze this data"):
    ...     print(f"{event.event_type}: {event.content}")
    >>>
    >>> # Multi-agent setup
    >>> research_agent = CodeAgent(llm=llm, name="researcher", ...)
    >>> main_agent = CodeAgent(llm=llm, managed_agents=[research_agent])

Architecture:
- agent.py: Main CodeAgent class
- executor/: Python execution backends (local, docker, router)
- interpreter/: AST-based Python interpreter with security
- memory.py: Execution history and state management
- parser.py: Code extraction and validation
- loop.py: Thought-Code-Observation iteration engine
- planning.py: Multi-step task planning
- compensator.py: Missing tool compensation
- data_analysis.py: Data science presets
- tools.py: Tool base class and @tool decorator
- monitoring.py: Logging, metrics, and visualization
- utils.py: Rate limiting and retry utilities

"""

from .agent import CodeAgent, DataAnalysisAgent, get_code_agent
from .compensator import (
    FALLBACK_TEMPLATES,
    CompensationResult,
    ToolCompensator,
    create_compensator,
)
from .data_analysis import (
    ALL_DATA_ANALYSIS_MODULES,
    CORE_DATA_MODULES,
    ML_MODULES,
    PRESET_BASIC,
    PRESET_FULL,
    PRESET_ML,
    PRESET_VISUALIZATION,
    STATISTICS_MODULES,
    VISUALIZATION_MODULES,
    DataAnalysisPreset,
    create_data_analysis_tools,
    get_preset,
)
from .executor import (
    BaseToolWrapper,
    CodeOutput,
    DockerPythonExecutor,
    ExecutorRouter,
    FinalAnswerException,
    LocalPythonExecutor,
    PythonExecutor,
    SecurityError,
    create_docker_executor,
    create_local_executor,
    create_router,
    wrap_final_answer,
)
from .interpreter import (
    BASE_BUILTIN_MODULES,
    BASE_PYTHON_TOOLS,
    DANGEROUS_FUNCTIONS,
    DANGEROUS_MODULES,
    DATA_ANALYSIS_MODULES,
    MAX_OPERATIONS,
    MAX_WHILE_ITERATIONS,
    NETWORK_MODULES,
    InterpreterError,
    PrintContainer,
    check_import_authorized,
    check_safer_result,
    evaluate_ast,
    get_allowed_imports,
    is_safe_code,
    validate_import_statement,
)
from .loop import (
    CODEAGENT_RESPONSE_SCHEMA,
    CodeAgentLoop,
    LoopConfig,
    StepEvent,
    create_simple_llm_call,
)
from .memory import (
    ActionStep,
    AgentMemory,
    ChatMessage,
    MessageStep,
    PlanningStep,
    StepMetrics,
    StepType,
    ToolCallStep,
)
from .monitoring import (
    AgentLogger,
    LogLevel,
    Monitor,
    Timing,
    TokenUsage,
)
from .parser import (
    ParsingError,
    clean_code,
    extract_imports,
    extract_thought_and_code,
    fix_final_answer_code,
    format_observation,
    parse_code_blobs,
    split_code_into_steps,
    validate_python_syntax,
)
from .planning import (
    Plan,
    PlanningEngine,
    PlanStatus,
    PlanStep,
    create_planning_engine,
)
from .tools import (
    AUTHORIZED_TYPES,
    FinalAnswerTool,
    Tool,
    create_final_answer_tool,
    get_json_type,
    python_type_to_json_type,
    tool,
    validate_tool_arguments,
)
from .utils import (
    RateLimiter,
    Retrying,
    is_rate_limit_error,
    is_transient_error,
    retry,
)

__version__ = "1.0.0"

__all__ = [
    # Main agent
    "CodeAgent",
    "DataAnalysisAgent",
    "get_code_agent",
    # Loop
    "CodeAgentLoop",
    "LoopConfig",
    "StepEvent",
    "create_simple_llm_call",
    "CODEAGENT_RESPONSE_SCHEMA",
    # Executors
    "PythonExecutor",
    "LocalPythonExecutor",
    "DockerPythonExecutor",
    "ExecutorRouter",
    "CodeOutput",
    "FinalAnswerException",
    "SecurityError",
    "BaseToolWrapper",
    "wrap_final_answer",
    "create_local_executor",
    "create_docker_executor",
    "create_router",
    # Interpreter
    "evaluate_ast",
    "InterpreterError",
    "PrintContainer",
    "BASE_PYTHON_TOOLS",
    "BASE_BUILTIN_MODULES",
    "DATA_ANALYSIS_MODULES",
    "NETWORK_MODULES",
    "DANGEROUS_MODULES",
    "DANGEROUS_FUNCTIONS",
    "MAX_OPERATIONS",
    "MAX_WHILE_ITERATIONS",
    "check_import_authorized",
    "check_safer_result",
    "get_allowed_imports",
    "is_safe_code",
    "validate_import_statement",
    # Memory
    "AgentMemory",
    "ActionStep",
    "PlanningStep",
    "ToolCallStep",
    "MessageStep",
    "ChatMessage",
    "StepType",
    "StepMetrics",
    # Parser
    "ParsingError",
    "parse_code_blobs",
    "extract_thought_and_code",
    "fix_final_answer_code",
    "clean_code",
    "validate_python_syntax",
    "extract_imports",
    "format_observation",
    "split_code_into_steps",
    # Planning
    "PlanningEngine",
    "Plan",
    "PlanStep",
    "PlanStatus",
    "create_planning_engine",
    # Compensator
    "ToolCompensator",
    "CompensationResult",
    "create_compensator",
    "FALLBACK_TEMPLATES",
    # Data Analysis
    "DataAnalysisPreset",
    "PRESET_BASIC",
    "PRESET_VISUALIZATION",
    "PRESET_ML",
    "PRESET_FULL",
    "CORE_DATA_MODULES",
    "VISUALIZATION_MODULES",
    "ML_MODULES",
    "STATISTICS_MODULES",
    "ALL_DATA_ANALYSIS_MODULES",
    "create_data_analysis_tools",
    "get_preset",
    # Tools
    "Tool",
    "tool",
    "FinalAnswerTool",
    "AUTHORIZED_TYPES",
    "validate_tool_arguments",
    "create_final_answer_tool",
    "python_type_to_json_type",
    "get_json_type",
    # Monitoring
    "Monitor",
    "TokenUsage",
    "Timing",
    "AgentLogger",
    "LogLevel",
    # Utils
    "RateLimiter",
    "Retrying",
    "retry",
    "is_rate_limit_error",
    "is_transient_error",
]

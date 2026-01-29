"""
Mock data generator for development and testing
Generates realistic execution data for visualization

MOCK: This module generates synthetic data for development purposes.
In production, data will be fetched from actual execution logs.
"""

import random
import time
from typing import Any, Dict, List, Optional

from .models import (
    AgentResponse,
    ChatMessageResponse,
    ExecutionTreeResponse,
    SessionResponse,
    TaskSummaryResponse,
    ToolInfo,
    ToolInvocationResponse,
)

# ==================== Constants ====================

TOOLS_DATABASE = [
    {
        "id": "tool_nmap",
        "name": "nmap_scan",
        "description": "Network port scanning and service detection",
        "category": "network_scanning",
        "parameters": {"target": "string", "ports": "string", "aggressive": "boolean", "timing": "string"},
    },
    {
        "id": "tool_gobuster",
        "name": "gobuster_scan",
        "description": "Directory and DNS enumeration",
        "category": "directory_enumeration",
        "parameters": {"target": "string", "wordlist": "string", "threads": "integer", "extensions": "string"},
    },
    {
        "id": "tool_nuclei",
        "name": "nuclei_scan",
        "description": "Vulnerability scanning with templates",
        "category": "vulnerability_scanning",
        "parameters": {"target": "string", "templates": "string", "severity": "string"},
    },
    {
        "id": "tool_sqlmap",
        "name": "sqlmap_test",
        "description": "SQL injection testing",
        "category": "web_testing",
        "parameters": {"url": "string", "method": "string", "data": "string"},
    },
    {
        "id": "tool_decision",
        "name": "decision_engine",
        "description": "AI-powered decision making tool",
        "category": "knowledge_based",
        "parameters": {"context": "string", "options": "array"},
    },
    {
        "id": "tool_think",
        "name": "think_tool",
        "description": "Reasoning and analysis tool",
        "category": "knowledge_based",
        "parameters": {"question": "string", "context": "string"},
    },
]

AGENT_NAMES = [
    "Reconnaissance Agent",
    "Vulnerability Scanner",
    "Exploitation Agent",
    "Analysis Agent",
    "Reporting Agent",
    "Network Mapper",
    "Web Crawler",
    "Security Auditor",
]

TASK_DESCRIPTIONS = [
    "Perform network reconnaissance on target",
    "Scan for common vulnerabilities",
    "Test web application security",
    "Enumerate DNS records",
    "Analyze security headers",
    "Check for SQL injection vulnerabilities",
    "Perform port scanning",
    "Identify running services",
]

CHAT_TEMPLATES = [
    "Scan the target {target} for open ports",
    "Perform a comprehensive security assessment of {target}",
    "Check for common vulnerabilities on {target}",
    "Enumerate subdomains for {target}",
    "Test web application security on {target}",
    "Analyze security posture of {target}",
]


# ==================== Mock Data Generators ====================


def generate_tool_invocation(
    tool_index: int = 0,
    start_time_ms: Optional[int] = None,
    duration_ms: Optional[int] = None,
) -> ToolInvocationResponse:
    """
    MOCK: Generate a mock tool invocation

    Args:
        tool_index: Index into TOOLS_DATABASE
        start_time_ms: Start time in milliseconds
        duration_ms: Duration in milliseconds

    Returns:
        ToolInvocationResponse with mock data
    """
    if start_time_ms is None:
        start_time_ms = int(time.time() * 1000)
    if duration_ms is None:
        duration_ms = random.randint(1000, 30000)

    tool = TOOLS_DATABASE[tool_index % len(TOOLS_DATABASE)]
    end_time_ms = start_time_ms + duration_ms

    # MOCK: Generate realistic tool results
    status = random.choice(["completed", "completed", "completed", "failed"])

    result = {}
    if tool["name"] == "nmap_scan":
        result = {
            "open_ports": [22, 80, 443, 3306],
            "services": ["ssh", "http", "https", "mysql"],
            "scan_time": f"{duration_ms}ms",
        }
    elif tool["name"] == "gobuster_scan":
        result = {
            "found_paths": ["/admin", "/api", "/backup", "/config"],
            "status_codes": {"200": 4, "403": 2, "404": 100},
            "scan_time": f"{duration_ms}ms",
        }
    elif tool["name"] == "nuclei_scan":
        result = {
            "vulnerabilities": [
                {"type": "CVE-2021-1234", "severity": "high"},
                {"type": "Weak SSL", "severity": "medium"},
            ],
            "scan_time": f"{duration_ms}ms",
        }
    elif tool["name"] == "decision_engine":
        result = {
            "decision": "proceed_with_exploitation",
            "confidence": 0.85,
            "reasoning": "Target shows signs of common vulnerabilities",
        }
    elif tool["name"] == "think_tool":
        result = {
            "analysis": "Target appears to be running outdated software",
            "recommendations": ["Update software", "Enable WAF"],
            "risk_level": "high",
        }
    else:
        result = {"status": "completed", "records": random.randint(10, 100)}

    tool_name = tool.get("name", "")
    tool_description = tool.get("description", "")
    tool_params = tool.get("parameters", {})

    # Convert to proper types
    tool_name_str = str(tool_name) if not isinstance(tool_name, str) else tool_name
    tool_description_str = str(tool_description) if not isinstance(tool_description, str) else tool_description
    tool_params_dict = tool_params if isinstance(tool_params, dict) else {}

    return ToolInvocationResponse(
        id=f"invocation_{random.randint(1000, 9999)}",
        tool_name=tool_name_str,
        tool_description=tool_description_str,
        parameters=tool_params_dict,
        result=result,
        status=status,
        start_time=start_time_ms,
        end_time=end_time_ms,
        duration_ms=duration_ms,
        error_message="Connection timeout" if status == "failed" else None,
        is_agent_tool=False,
        child_agent_id=None,
    )


def generate_agent(
    level: int = 0,
    parent_agent_id: Optional[str] = None,
    start_time_ms: Optional[int] = None,
    depth: int = 2,
) -> AgentResponse:
    """
    MOCK: Generate a mock agent with recursive sub-agents

    Args:
        level: Nesting level (0=root)
        parent_agent_id: Parent agent ID
        start_time_ms: Start time in milliseconds
        depth: Maximum depth for recursion

    Returns:
        AgentResponse with mock data
    """
    if start_time_ms is None:
        start_time_ms = int(time.time() * 1000)

    agent_id = f"agent_{random.randint(10000, 99999)}"
    duration_ms = random.randint(5000, 60000)
    end_time_ms = start_time_ms + duration_ms

    # MOCK: Generate tool invocations
    tool_count = random.randint(2, 5)
    tool_invocations = [
        generate_tool_invocation(
            tool_index=i, start_time_ms=start_time_ms + i * 5000, duration_ms=random.randint(3000, 15000)
        )
        for i in range(tool_count)
    ]

    # MOCK: Generate sub-agents if depth allows
    sub_agents = []
    if level < depth and random.random() > 0.6:
        sub_agent_count = random.randint(1, 3)
        for i in range(sub_agent_count):
            sub_agents.append(
                generate_agent(
                    level=level + 1, parent_agent_id=agent_id, start_time_ms=start_time_ms + i * 10000, depth=depth
                )
            )

    return AgentResponse(
        id=agent_id,
        name=random.choice(AGENT_NAMES),
        task_description=random.choice(TASK_DESCRIPTIONS),
        status=random.choice(["completed", "completed", "completed", "failed"]),
        level=level,
        start_time=start_time_ms,
        end_time=end_time_ms,
        duration_ms=duration_ms,
        parent_agent_id=parent_agent_id,
        tool_invocations=tool_invocations,
        sub_agents=sub_agents,
        child_agents=None,
        context={"target": "example.com", "objective": "Security Assessment"},
        available_tools=[str(tool["name"]) for tool in TOOLS_DATABASE[:4]],
        output={"result": "success", "findings": random.randint(5, 20)},
        error_message=None,
        success_rate=random.uniform(80, 100),
    )


def generate_execution_tree(task_id: Optional[str] = None) -> ExecutionTreeResponse:
    """
    MOCK: Generate a mock execution tree

    Args:
        task_id: Associated task ID

    Returns:
        ExecutionTreeResponse with mock data
    """
    if task_id is None:
        task_id = f"task_{random.randint(1000, 9999)}"

    execution_id = f"exec_{random.randint(10000, 99999)}"
    start_time_ms = int(time.time() * 1000)
    total_duration_ms = random.randint(30000, 300000)
    end_time_ms = start_time_ms + total_duration_ms

    # MOCK: Generate root agent
    root_agent = generate_agent(level=0, start_time_ms=start_time_ms, depth=2)

    # MOCK: Count total agents and tools recursively
    def count_agents_and_tools(agent: AgentResponse) -> tuple:
        """Count total agents and tools in tree"""
        agent_count = 1
        tool_count = len(agent.tool_invocations)

        for sub_agent in agent.sub_agents:
            sub_agents, sub_tools = count_agents_and_tools(sub_agent)
            agent_count += sub_agents
            tool_count += sub_tools

        return agent_count, tool_count

    agent_count, tool_count = count_agents_and_tools(root_agent)

    return ExecutionTreeResponse(
        id=execution_id,
        root_agent=root_agent,
        total_duration_ms=total_duration_ms,
        total_agents_count=agent_count,
        total_tools_count=tool_count,
        success_rate=random.uniform(75, 100),
        execution_start_time=start_time_ms,
        execution_end_time=end_time_ms,
        created_at=start_time_ms,
        max_depth=2,
    )


def generate_task(session_id: str, task_index: int = 0) -> TaskSummaryResponse:
    """
    MOCK: Generate a mock task

    Args:
        session_id: Associated session ID
        task_index: Task index in session

    Returns:
        TaskSummaryResponse with mock data
    """
    task_id = f"task_{random.randint(10000, 99999)}"
    execution = generate_execution_tree(task_id)

    start_time_ms = int(time.time() * 1000) - random.randint(0, 3600000)
    duration_ms = execution.total_duration_ms
    end_time_ms = start_time_ms + duration_ms

    return TaskSummaryResponse(
        id=task_id,
        session_id=session_id,
        title=f"Task {task_index + 1}: {random.choice(TASK_DESCRIPTIONS)}",
        description=random.choice(TASK_DESCRIPTIONS),
        status=execution.root_agent.status,
        start_time=start_time_ms,
        end_time=end_time_ms,
        duration_ms=duration_ms,
        execution_id=execution.id,
        root_agent_id=execution.root_agent.id,
        agent_count=execution.total_agents_count,
        tool_count=execution.total_tools_count,
        success_rate=execution.success_rate,
        error_message=None,
    )


def generate_chat_message(
    session_id: str,
    message_index: int,
    role: str = "user",
) -> ChatMessageResponse:
    """
    MOCK: Generate a mock chat message

    Args:
        session_id: Associated session ID
        message_index: Message index
        role: Message role (user|assistant|system)

    Returns:
        ChatMessageResponse with mock data
    """
    timestamp_ms = int(time.time() * 1000) - (100 - message_index) * 60000

    if role == "user":
        content = random.choice(CHAT_TEMPLATES).format(target="example.com")
        message_type = "text"
    elif role == "assistant":
        content = f"I'll help you with that. Starting analysis... [Intermediate result {message_index}]"
        message_type = random.choice(["text", "intermediate"])
    else:
        content = "System initialized"
        message_type = "system"

    return ChatMessageResponse(
        id=f"msg_{random.randint(100000, 999999)}",
        session_id=session_id,
        role=role,
        content=content,
        timestamp=timestamp_ms,
        message_type=message_type,
        metadata={"index": message_index},
    )


def generate_session(user_id: str, session_index: int = 0) -> SessionResponse:
    """
    MOCK: Generate a mock session

    Args:
        user_id: Associated user ID
        session_index: Session index for user

    Returns:
        SessionResponse with mock data
    """
    session_id = f"session_{random.randint(100000, 999999)}"
    created_at_ms = int(time.time() * 1000) - random.randint(0, 30 * 24 * 3600 * 1000)
    updated_at_ms = created_at_ms + random.randint(0, 24 * 3600 * 1000)

    return SessionResponse(
        id=session_id,
        user_id=user_id,
        title=f"Security Assessment - Session {session_index + 1}",
        created_at=created_at_ms,
        updated_at=updated_at_ms,
        task_count=random.randint(2, 5),
        mode=None,
    )


def generate_sessions_for_user(user_id: str, count: int = 5) -> List[SessionResponse]:
    """
    MOCK: Generate multiple sessions for a user

    Args:
        user_id: User ID
        count: Number of sessions to generate

    Returns:
        List of SessionResponse objects
    """
    return [generate_session(user_id, i) for i in range(count)]


def generate_tasks_for_session(session_id: str, count: int = 3) -> List[TaskSummaryResponse]:
    """
    MOCK: Generate multiple tasks for a session

    Args:
        session_id: Session ID
        count: Number of tasks to generate

    Returns:
        List of TaskSummaryResponse objects
    """
    return [generate_task(session_id, i) for i in range(count)]


def generate_chat_history(session_id: str, message_count: int = 10) -> List[ChatMessageResponse]:
    """
    MOCK: Generate chat history for a session

    Args:
        session_id: Session ID
        message_count: Number of messages to generate

    Returns:
        List of ChatMessageResponse objects
    """
    messages = []
    for i in range(message_count):
        # Alternate between user and assistant messages
        role = "user" if i % 2 == 0 else "assistant"
        messages.append(generate_chat_message(session_id, i, role))

    return messages


def get_mock_tools() -> List[ToolInfo]:
    """
    MOCK: Get list of available tools

    Returns:
        List of ToolInfo objects
    """
    result = []
    for tool in TOOLS_DATABASE:
        # Convert tool dict to proper types
        tool_dict: Dict[str, Any] = {
            "id": str(tool.get("id", "")),
            "name": str(tool.get("name", "")),
            "description": str(tool.get("description", "")),
            "category": str(tool.get("category", "")),
            "parameters": tool.get("parameters", {}) if isinstance(tool.get("parameters"), dict) else {},
        }
        result.append(ToolInfo(**tool_dict))
    return result


def get_mock_tool_by_name(tool_name: str) -> ToolInfo:
    """
    MOCK: Get tool information by name

    Args:
        tool_name: Tool name

    Returns:
        ToolInfo object or None if not found
    """
    for tool in TOOLS_DATABASE:
        tool_name_val = tool.get("name", "")
        if str(tool_name_val) == tool_name:
            # Convert tool dict to proper types
            tool_dict: Dict[str, Any] = {
                "id": str(tool.get("id", "")),
                "name": str(tool.get("name", "")),
                "description": str(tool.get("description", "")),
                "category": str(tool.get("category", "")),
                "parameters": tool.get("parameters", {}) if isinstance(tool.get("parameters"), dict) else {},
            }
            return ToolInfo(**tool_dict)
    raise ValueError(f"Tool not found: {tool_name}")

"""
Data models for web API responses
Defines Pydantic models for serializing execution data
"""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

# ==================== Execution Status ====================


class ExecutionStatusEnum:
    """Execution status constants"""

    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    PENDING = "pending"


# ==================== Tool Information ====================


class ToolInfo(BaseModel):
    """Information about a tool"""

    id: str = Field(..., description="Unique tool identifier")
    name: str = Field(..., description="Tool name (e.g., 'nmap_scan')")
    description: str = Field(..., description="Tool description")
    category: str = Field(..., description="Tool category (e.g., 'network_scanning')")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="Tool parameters schema")

    class Config:
        json_schema_extra = {
            "example": {
                "id": "tool_001",
                "name": "nmap_scan",
                "description": "Network port scanning tool",
                "category": "network_scanning",
                "parameters": {"target": "string", "ports": "string", "aggressive": "boolean"},
            }
        }


# ==================== Tool Invocation ====================


class ToolInvocationResponse(BaseModel):
    """Tool invocation details"""

    id: str = Field(..., description="Unique invocation ID")
    tool_name: str = Field(..., description="Name of the tool")
    tool_description: str = Field(..., description="Tool description")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="Input parameters")
    result: Dict[str, Any] = Field(default_factory=dict, description="Tool output/result")
    status: str = Field(..., description="Execution status: running|completed|failed|pending")
    start_time: int = Field(..., description="Unix timestamp in milliseconds")
    end_time: int = Field(..., description="Unix timestamp in milliseconds")
    duration_ms: int = Field(..., description="Duration in milliseconds")
    error_message: Optional[str] = Field(None, description="Error message if failed")
    is_agent_tool: bool = Field(False, description="Whether this tool spawns child agents")
    child_agent_id: Optional[str] = Field(None, description="ID of child agent if is_agent_tool")

    class Config:
        json_schema_extra = {
            "example": {
                "id": "invocation_001",
                "tool_name": "nmap_scan",
                "tool_description": "Network port scanning",
                "parameters": {"target": "192.168.1.1", "ports": "1-1000"},
                "result": {"open_ports": [22, 80, 443]},
                "status": "completed",
                "start_time": 1700000000000,
                "end_time": 1700000010000,
                "duration_ms": 10000,
                "error_message": None,
                "is_agent_tool": False,
                "child_agent_id": None,
            }
        }


# ==================== Agent ====================


class AgentResponse(BaseModel):
    """Agent execution details"""

    id: str = Field(..., description="Unique agent ID")
    name: str = Field(..., description="Agent name")
    task_description: str = Field(..., description="Task description")
    status: str = Field(..., description="Execution status")
    level: int = Field(..., description="Nesting level (0=root)")
    start_time: int = Field(..., description="Unix timestamp in milliseconds")
    end_time: int = Field(..., description="Unix timestamp in milliseconds")
    duration_ms: int = Field(..., description="Duration in milliseconds")
    parent_agent_id: Optional[str] = Field(None, description="Parent agent ID")
    tool_invocations: List[ToolInvocationResponse] = Field(
        default_factory=list, description="Tools called by this agent"
    )
    sub_agents: List["AgentResponse"] = Field(default_factory=list, description="Sub-agents spawned")
    child_agents: Optional[List["AgentResponse"]] = Field(None, description="Child agents from app.dynamic_agent_tool")
    context: Optional[Dict[str, Any]] = Field(None, description="Agent context")
    available_tools: List[str] = Field(default_factory=list, description="Available tools")
    output: Optional[Dict[str, Any]] = Field(None, description="Final output")
    error_message: Optional[str] = Field(None, description="Error message if failed")
    success_rate: Optional[float] = Field(None, description="Success rate percentage")

    class Config:
        json_schema_extra = {
            "example": {
                "id": "agent_001",
                "name": "Root Agent",
                "task_description": "Perform network reconnaissance",
                "status": "completed",
                "level": 0,
                "start_time": 1700000000000,
                "end_time": 1700000060000,
                "duration_ms": 60000,
                "parent_agent_id": None,
                "tool_invocations": [],
                "sub_agents": [],
                "context": {"target": "example.com"},
                "available_tools": ["nmap_scan", "dns_lookup"],
                "output": {"result": "success"},
                "error_message": None,
                "success_rate": 100.0,
            }
        }


# Update forward references for recursive model
AgentResponse.model_rebuild()


# ==================== Execution Tree ====================


class ExecutionTreeResponse(BaseModel):
    """Complete execution tree for a task"""

    id: str = Field(..., description="Unique execution ID")
    root_agent: AgentResponse = Field(..., description="Root agent of execution")
    total_duration_ms: int = Field(..., description="Total execution time")
    total_agents_count: int = Field(..., description="Total agents spawned")
    total_tools_count: int = Field(..., description="Total tools called")
    success_rate: float = Field(..., description="Overall success rate percentage")
    execution_start_time: int = Field(..., description="Unix timestamp in milliseconds")
    execution_end_time: int = Field(..., description="Unix timestamp in milliseconds")
    created_at: int = Field(..., description="Creation timestamp in milliseconds")
    max_depth: Optional[int] = Field(None, description="Maximum nesting depth")

    class Config:
        json_schema_extra = {
            "example": {
                "id": "exec_001",
                "root_agent": {},
                "total_duration_ms": 60000,
                "total_agents_count": 5,
                "total_tools_count": 12,
                "success_rate": 95.0,
                "execution_start_time": 1700000000000,
                "execution_end_time": 1700000060000,
                "created_at": 1700000000000,
                "max_depth": 2,
            }
        }


# ==================== Task ====================


class TaskBasicResponse(BaseModel):
    """Basic task information for session details"""

    id: str = Field(..., description="Unique task ID")
    session_id: str = Field(..., description="Associated session ID")
    user_input: str = Field(..., description="User input that triggered this task")
    status: str = Field(..., description="Execution status")
    created_at: str = Field(..., description="ISO format creation timestamp")
    updated_at: str = Field(..., description="ISO format update timestamp")
    completed_at: Optional[str] = Field(None, description="ISO format completion timestamp")
    result_summary: Optional[str] = Field(None, description="Task result summary")
    metadata: dict = Field(default_factory=dict, description="Task metadata")

    class Config:
        json_schema_extra = {
            "example": {
                "id": "task_001",
                "session_id": "session_001",
                "user_input": "Scan the target network",
                "status": "completed",
                "created_at": "2024-01-01T00:00:00",
                "updated_at": "2024-01-01T00:01:00",
                "completed_at": "2024-01-01T00:01:00",
                "result_summary": "Found 5 open ports",
                "metadata": {},
            }
        }


class TaskSummaryResponse(BaseModel):
    """Task summary with execution statistics for visualization"""

    id: str = Field(..., description="Unique task ID")
    session_id: str = Field(..., description="Associated session ID")
    title: str = Field(..., description="Task title")
    description: str = Field(..., description="Task description")
    status: str = Field(..., description="Execution status")
    start_time: int = Field(..., description="Unix timestamp in milliseconds")
    end_time: int = Field(..., description="Unix timestamp in milliseconds")
    duration_ms: int = Field(..., description="Duration in milliseconds")
    execution_id: str = Field(..., description="Associated execution tree ID")
    root_agent_id: str = Field(..., description="Root agent ID")
    agent_count: int = Field(..., description="Number of agents")
    tool_count: int = Field(..., description="Number of tools")
    success_rate: float = Field(..., description="Success rate percentage")
    error_message: Optional[str] = Field(None, description="Error message if failed")

    class Config:
        json_schema_extra = {
            "example": {
                "id": "task_001",
                "session_id": "session_001",
                "title": "Network Reconnaissance",
                "description": "Scan target network for open ports",
                "status": "completed",
                "start_time": 1700000000000,
                "end_time": 1700000060000,
                "duration_ms": 60000,
                "execution_id": "exec_001",
                "root_agent_id": "agent_001",
                "agent_count": 5,
                "tool_count": 12,
                "success_rate": 95.0,
                "error_message": None,
            }
        }


# ==================== Session ====================


class SessionResponse(BaseModel):
    """Session information"""

    id: str = Field(..., description="Unique session ID")
    user_id: str = Field(..., description="User ID")
    title: str = Field(..., description="Session title")
    created_at: int = Field(..., description="Creation timestamp in milliseconds")
    updated_at: int = Field(..., description="Last update timestamp in milliseconds")
    task_count: int = Field(..., description="Number of tasks in session")
    mode: Optional[str] = Field(None, description="Session mode: ctf|pentest")

    class Config:
        json_schema_extra = {
            "example": {
                "id": "session_001",
                "user_id": "user_123",
                "title": "Security Assessment - example.com",
                "created_at": 1700000000000,
                "updated_at": 1700000060000,
                "task_count": 3,
                "mode": "pentest",
            }
        }


# ==================== Chat Message ====================


class ChatMessageResponse(BaseModel):
    """Chat message in a session"""

    id: str = Field(..., description="Unique message ID")
    session_id: str = Field(..., description="Session ID")
    role: str = Field(..., description="Message role: user|assistant|system")
    content: str = Field(..., description="Message content")
    timestamp: int = Field(..., description="Unix timestamp in milliseconds")
    message_type: str = Field(default="text", description="Message type: text|tool_call|tool_result|intermediate")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional metadata")
    task_id: Optional[str] = Field(default=None, description="Associated task ID for user messages")

    class Config:
        json_schema_extra = {
            "example": {
                "id": "msg_001",
                "session_id": "session_001",
                "role": "user",
                "content": "Scan the target for open ports",
                "timestamp": 1700000000000,
                "message_type": "text",
                "metadata": {},
            }
        }


# ==================== Session Details ====================


class SessionDetailsResponse(BaseModel):
    """Complete session details with chat history"""

    session: SessionResponse = Field(..., description="Session information")
    messages: List[ChatMessageResponse] = Field(default_factory=list, description="Chat messages")
    tasks: List[TaskBasicResponse] = Field(default_factory=list, description="Tasks in session")

    class Config:
        json_schema_extra: Dict[str, Any] = {"example": {"session": {}, "messages": [], "tasks": []}}


# ==================== List Responses ====================


class SessionListResponse(BaseModel):
    """List of sessions for a user"""

    user_id: str = Field(..., description="User ID")
    sessions: List[SessionResponse] = Field(default_factory=list, description="Sessions")
    total_count: int = Field(..., description="Total number of sessions")

    class Config:
        json_schema_extra = {"example": {"user_id": "user_123", "sessions": [], "total_count": 0}}


class TaskListResponse(BaseModel):
    """List of tasks in a session"""

    session_id: str = Field(..., description="Session ID")
    tasks: List[TaskSummaryResponse] = Field(default_factory=list, description="Tasks")
    total_count: int = Field(..., description="Total number of tasks")

    class Config:
        json_schema_extra = {"example": {"session_id": "session_001", "tasks": [], "total_count": 0}}


# ==================== Error Response ====================


class ErrorResponse(BaseModel):
    """Error response"""

    error: str = Field(..., description="Error message")
    detail: Optional[str] = Field(None, description="Error details")
    timestamp: str = Field(..., description="ISO format timestamp")

    class Config:
        json_schema_extra = {
            "example": {"error": "Not found", "detail": "Session not found", "timestamp": "2025-11-30T10:00:00Z"}
        }

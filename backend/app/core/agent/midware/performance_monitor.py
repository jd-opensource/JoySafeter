"""性能监控中间件 - 监控和分析代理性能指标

基于AgentMemoryMiddleware的标准实现模式，提供完整的性能监控功能。
"""

import json
import threading
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional

import psutil

if TYPE_CHECKING:
    pass

from deepagents.backends.protocol import BackendProtocol
from langchain.agents.middleware.types import AgentMiddleware, AgentState, ModelRequest, ModelResponse
from typing_extensions import NotRequired


@dataclass
class PerformanceRecord:
    """性能记录数据类"""

    timestamp: float
    response_time: float
    token_count: int = 0
    tool_calls: int = 0
    error_occurred: bool = False
    memory_usage: float = 0.0
    cpu_usage: float = 0.0
    session_id: str = ""
    request_type: str = ""


class PerformanceState(AgentState):
    """性能监控中间件的状态"""

    session_id: NotRequired[str]  # type: ignore[valid-type]
    """会话ID"""
    request_count: NotRequired[int]  # type: ignore[valid-type]
    """请求计数"""
    total_response_time: NotRequired[float]  # type: ignore[valid-type]
    """总响应时间"""
    last_metrics: NotRequired[PerformanceRecord]  # type: ignore[valid-type]
    """最后一次性能记录"""


class PerformanceCollector:
    """性能数据收集器"""

    def __init__(self, max_history: int = 1000):
        self.max_history = max_history
        self.records: List[PerformanceRecord] = []
        self.session_records: Dict[str, List[PerformanceRecord]] = {}
        self.tool_stats: Dict[str, Dict[str, float]] = {}
        self._lock = threading.Lock()

    def add_record(self, record: PerformanceRecord) -> None:
        """添加性能记录"""
        with self._lock:
            self.records.append(record)
            if len(self.records) > self.max_history:
                self.records = self.records[-self.max_history :]

            if record.session_id:
                if record.session_id not in self.session_records:
                    self.session_records[record.session_id] = []
                self.session_records[record.session_id].append(record)

    def update_tool_stats(self, tool_name: str, execution_time: float, success: bool = True) -> None:
        """更新工具统计"""
        with self._lock:
            if tool_name not in self.tool_stats:
                self.tool_stats[tool_name] = {
                    "count": 0,
                    "total_time": 0.0,
                    "errors": 0,
                    "successes": 0,
                }

            stats = self.tool_stats[tool_name]
            stats["count"] += 1
            stats["total_time"] += execution_time
            if success:
                stats["successes"] += 1
            else:
                stats["errors"] += 1

    def get_summary(self, time_window_minutes: int = 60) -> Dict[str, Any]:
        """获取性能摘要"""
        with self._lock:
            cutoff_time = time.time() - (time_window_minutes * 60)
            recent_records = [r for r in self.records if r.timestamp > cutoff_time]

            if not recent_records:
                return {"error": "No data available"}

            response_times = [r.response_time for r in recent_records]
            errors = sum(1 for r in recent_records if r.error_occurred)

            return {
                "time_window_minutes": time_window_minutes,
                "total_requests": len(recent_records),
                "error_rate": (errors / len(recent_records)) * 100,
                "avg_response_time": sum(response_times) / len(response_times),
                "min_response_time": min(response_times),
                "max_response_time": max(response_times),
                "avg_token_count": sum(r.token_count for r in recent_records) / len(recent_records),
                "total_tokens": sum(r.token_count for r in recent_records),
                "total_tool_calls": sum(r.tool_calls for r in recent_records),
                "avg_memory_usage": sum(r.memory_usage for r in recent_records) / len(recent_records),
                "avg_cpu_usage": sum(r.cpu_usage for r in recent_records) / len(recent_records),
                "active_sessions": len(self.session_records),
                "timestamp": datetime.now().isoformat(),
            }


class PerformanceMonitorMiddleware(AgentMiddleware):
    """性能监控中间件

    基于AgentMemoryMiddleware的标准实现模式，提供完整的性能监控功能。

    Args:
        backend: 用于保存性能数据的后端
        metrics_path: 性能数据文件路径
        enable_system_monitoring: 是否启用系统监控（CPU和内存）
        max_records: 最大保存记录数

    Example:
        ```python
        from deepagents.memory.backends import FilesystemBackend
        from pathlib import Path

        backend = FilesystemBackend(root_dir=Path.home() / ".deepagents")
        middleware = PerformanceMonitorMiddleware(
            backend=backend,
            metrics_path="/performance/",
            enable_system_monitoring=True
        )
        ```
    """

    state_schema = PerformanceState

    def __init__(
        self,
        *,
        backend: BackendProtocol,
        metrics_path: str = "/performance/",
        enable_system_monitoring: bool = True,
        max_records: int = 1000,
    ) -> None:
        """初始化性能监控中间件"""
        self.backend = backend
        self.metrics_path = metrics_path
        self.enable_system_monitoring = enable_system_monitoring
        self.max_records = max_records

        self.collector = PerformanceCollector(max_history=max_records)
        self.session_id = self._generate_session_id()

        # 系统监控
        self.process = psutil.Process()
        self._cpu_usage = 0.0
        self._memory_usage = 0.0
        self._monitor_thread = None

        if enable_system_monitoring:
            self._monitor_thread = threading.Thread(target=self._monitor_system, daemon=True)
            self._monitor_thread.start()

    def _generate_session_id(self) -> str:
        """生成会话ID"""
        import uuid

        return str(uuid.uuid4())[:8]

    def _monitor_system(self) -> None:
        """后台系统监控线程"""
        while True:
            try:
                self._cpu_usage = self.process.cpu_percent(interval=1.0)
                self._memory_usage = self.process.memory_info().rss / 1024 / 1024  # MB
            except Exception:
                pass
            time.sleep(1)

    def before_agent(
        self,
        state: AgentState[Any],  # type: ignore[override]
        runtime,
    ) -> dict[str, Any]:  # type: ignore[override]
        """在代理执行前初始化性能监控"""
        # 确保会话ID存在
        if "session_id" not in state:
            return {"session_id": self.session_id, "messages": []}
        return state  # type: ignore[return-value]

    async def abefore_agent(
        self,
        state: AgentState[Any],  # type: ignore[override]
        runtime,
    ) -> dict[str, Any]:  # type: ignore[override]
        """异步：在代理执行前初始化性能监控"""
        if "session_id" not in state:
            return {"session_id": self.session_id, "messages": []}
        return state  # type: ignore[return-value]

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        """包装模型调用，监控性能指标"""
        start_time = time.time()

        # 获取当前系统状态
        current_cpu = self._cpu_usage
        current_memory = self._memory_usage

        # 估算token数量
        request_tokens = 0
        if hasattr(request, "content") and request.content:
            request_tokens = self._estimate_tokens(request.content)
        elif hasattr(request, "messages") and request.messages:
            # 从messages中提取内容
            content = ""
            for msg in request.messages:
                if hasattr(msg, "content") and msg.content:
                    content += str(msg.content) + " "
            request_tokens = self._estimate_tokens(content.strip()) if content.strip() else 0

        try:
            # 执行模型调用
            response = handler(request)

            # 计算性能指标
            end_time = time.time()
            response_time = end_time - start_time

            # 估算响应token数量
            response_tokens = 0
            if hasattr(response, "content") and response.content:
                response_tokens = self._estimate_tokens(response.content)
            elif hasattr(response, "messages") and response.messages:
                # 从messages中提取内容
                content = ""
                for msg in response.messages:
                    if hasattr(msg, "content") and msg.content:
                        content += str(msg.content) + " "
                response_tokens = self._estimate_tokens(content.strip()) if content.strip() else 0
            total_tokens = request_tokens + response_tokens

            # 获取工具调用数量
            tool_calls = len(response.get("tool_results", [])) if hasattr(response, "get") else 0

            # 创建性能记录
            record = PerformanceRecord(
                timestamp=start_time,
                response_time=response_time,
                token_count=total_tokens,
                tool_calls=tool_calls,
                error_occurred=False,
                memory_usage=current_memory,
                cpu_usage=current_cpu,
                session_id=str(request.state.get("session_id", "")),
                request_type="model_call",
            )

            # 记录性能数据
            self.collector.add_record(record)

            # 更新状态
            request_count = request.state.get("request_count", 0)
            total_response_time = request.state.get("total_response_time", 0.0)
            # Convert to int/float safely
            request_count_int = int(request_count) if isinstance(request_count, (int, float)) else 0
            total_response_time_float = (
                float(total_response_time) if isinstance(total_response_time, (int, float)) else 0.0
            )
            request.state["request_count"] = request_count_int + 1  # type: ignore[typeddict-unknown-key, assignment]
            request.state["total_response_time"] = total_response_time_float + response_time  # type: ignore[typeddict-unknown-key, assignment]

            return response

        except Exception:
            # 记录错误指标
            end_time = time.time()
            response_time = end_time - start_time

            error_record = PerformanceRecord(
                timestamp=start_time,
                response_time=response_time,
                token_count=request_tokens,
                tool_calls=0,
                error_occurred=True,
                memory_usage=current_memory,
                cpu_usage=current_cpu,
                session_id=str(request.state.get("session_id", "")),
                request_type="model_call_error",
            )

            self.collector.add_record(error_record)

            # 重新抛出异常
            raise

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        """异步：包装模型调用，监控性能指标"""
        start_time = time.time()

        # 获取当前系统状态
        current_cpu = self._cpu_usage
        current_memory = self._memory_usage

        request_tokens = 0
        if hasattr(request, "content") and request.content:
            request_tokens = self._estimate_tokens(request.content)
        elif hasattr(request, "messages") and request.messages:
            # 从messages中提取内容
            content = ""
            for msg in request.messages:
                if hasattr(msg, "content") and msg.content:
                    content += str(msg.content) + " "
            request_tokens = self._estimate_tokens(content.strip()) if content.strip() else 0

        try:
            # 执行异步模型调用
            response = await handler(request)

            end_time = time.time()
            response_time = end_time - start_time

            response_tokens = 0
            if hasattr(response, "content") and response.content:
                response_tokens = self._estimate_tokens(response.content)
            elif hasattr(response, "messages") and response.messages:
                # 从messages中提取内容
                content = ""
                for msg in response.messages:
                    if hasattr(msg, "content") and msg.content:
                        content += str(msg.content) + " "
                response_tokens = self._estimate_tokens(content.strip()) if content.strip() else 0
            total_tokens = request_tokens + response_tokens
            tool_calls = len(response.get("tool_results", [])) if hasattr(response, "get") else 0

            record = PerformanceRecord(
                timestamp=start_time,
                response_time=response_time,
                token_count=total_tokens,
                tool_calls=tool_calls,
                error_occurred=False,
                memory_usage=current_memory,
                cpu_usage=current_cpu,
                session_id=str(request.state.get("session_id", "")),
                request_type="model_call",
            )

            self.collector.add_record(record)

            return response

        except Exception:
            end_time = time.time()
            response_time = end_time - start_time

            error_record = PerformanceRecord(
                timestamp=start_time,
                response_time=response_time,
                token_count=request_tokens,
                tool_calls=0,
                error_occurred=True,
                memory_usage=current_memory,
                cpu_usage=current_cpu,
                session_id=str(request.state.get("session_id", "")),
                request_type="model_call_error",
            )

            self.collector.add_record(error_record)

            raise

    def _estimate_tokens(self, text: str) -> int:
        """估算文本的token数量（简化版本）"""
        if not text:
            return 0

        # 对于中文：约1.5个字符 = 1个token
        # 对于英文：约4个字符 = 1个token
        chinese_chars = len([c for c in text if "\u4e00" <= c <= "\u9fff"])
        english_chars = len(text) - chinese_chars

        estimated_tokens = (english_chars / 4) + (chinese_chars / 1.5)
        return int(estimated_tokens)

    def get_performance_summary(self, time_window_minutes: int = 60) -> Dict[str, Any]:
        """获取性能摘要"""
        return self.collector.get_summary(time_window_minutes)

    def get_tool_performance(self) -> Dict[str, Dict[str, Any]]:
        """获取工具性能统计"""
        with self.collector._lock:
            result = {}
            for tool_name, stats in self.collector.tool_stats.items():
                if stats["count"] > 0:
                    success_rate = (stats["successes"] / stats["count"]) * 100
                    result[tool_name] = {
                        "call_count": stats["count"],
                        "avg_execution_time": stats["total_time"] / stats["count"],
                        "success_rate": success_rate,
                        "error_rate": 100 - success_rate,
                        "total_time": stats["total_time"],
                    }
            return result

    def export_metrics(self, filename: Optional[str] = None) -> str:
        """导出性能指标到文件"""
        if not filename:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"performance_metrics_{timestamp}.json"

        # 准备导出数据
        data = {
            "export_timestamp": datetime.now().isoformat(),
            "performance_summary": self.get_performance_summary(time_window_minutes=1440),  # 24小时
            "tool_performance": self.get_tool_performance(),
            "active_sessions": len(self.collector.session_records),
            "total_records": len(self.collector.records),
            "configuration": {
                "enable_system_monitoring": self.enable_system_monitoring,
                "max_records": self.max_records,
                "metrics_path": self.metrics_path,
            },
        }

        # 导出到文件
        try:
            # 先写入临时文件，然后重命名
            temp_file = Path(f"temp_{filename}")
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

            # 如果使用后端，尝试通过后端保存
            final_path = self.metrics_path + filename
            temp_file.rename(final_path)

            return str(final_path)

        except Exception:
            # 如果重命名失败，返回临时文件路径
            return str(temp_file)

    def get_session_metrics(self, session_id: str) -> Dict[str, Any]:
        """获取特定会话的性能指标"""
        with self.collector._lock:
            session_records = self.collector.session_records.get(session_id, [])
            if not session_records:
                return {"error": f"No records found for session {session_id}"}

            response_times = [r.response_time for r in session_records]
            errors = sum(1 for r in session_records if r.error_occurred)

            return {
                "session_id": session_id,
                "total_requests": len(session_records),
                "error_rate": ((errors / len(session_records)) * 100 if session_records else 0),
                "avg_response_time": (sum(response_times) / len(response_times) if response_times else 0),
                "min_response_time": min(response_times) if response_times else 0,
                "max_response_time": max(response_times) if response_times else 0,
                "total_tokens": sum(r.token_count for r in session_records),
                "total_tool_calls": sum(r.tool_calls for r in session_records),
                "first_request_time": min(r.timestamp for r in session_records),
                "last_request_time": max(r.timestamp for r in session_records),
            }

    def cleanup(self) -> None:
        """清理资源"""
        # 系统监控线程会在进程结束时自动清理
        pass

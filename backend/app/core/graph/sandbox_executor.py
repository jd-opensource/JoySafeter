"""
Sandbox Executor - Safe code execution for FunctionNodeExecutor.

Provides sandboxed execution environment for custom Python code.
"""

from typing import Any, Dict

from loguru import logger

# Try to import RestrictedPython for sandboxing
try:
    from RestrictedPython import compile_restricted
    from RestrictedPython.Guards import safe_builtins

    RESTRICTED_PYTHON_AVAILABLE = True
except ImportError:
    RESTRICTED_PYTHON_AVAILABLE = False
    logger.warning(
        "[SandboxExecutor] RestrictedPython not available. "
        "Code execution will be unsafe. Install with: pip install RestrictedPython"
    )


class SandboxExecutor:
    """沙箱化代码执行器。"""

    @staticmethod
    def execute_safe(code: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """安全执行 Python 代码。

        Args:
            code: Python 代码字符串
            context: 执行上下文（包含 state, context 等）

        Returns:
            执行结果字典，包含 result 和可能的错误信息
        """
        if not RESTRICTED_PYTHON_AVAILABLE:
            logger.warning(
                "[SandboxExecutor] RestrictedPython not available, using unsafe exec(). "
                "This is a security risk in production!"
            )
            return SandboxExecutor._execute_unsafe(code, context)

        try:
            # 使用 RestrictedPython 编译
            byte_code = compile_restricted(code, "<inline>", "exec")
            if byte_code.errors:
                error_msg = "; ".join(str(e) for e in byte_code.errors)
                logger.error(f"[SandboxExecutor] Code compilation failed: {error_msg}")
                return {
                    "status": "error",
                    "error_msg": f"Code compilation failed: {error_msg}",
                }

            # 准备安全的执行环境
            safe_globals = {
                "__builtins__": safe_builtins,
                **context,
            }

            # 执行代码
            exec(byte_code.code, safe_globals, {})

            # 提取结果
            result = safe_globals.get("result", {"status": "success", "output": "Code executed"})

            return result if isinstance(result, dict) else {"result": result, "status": "success"}

        except Exception as e:
            logger.error(f"[SandboxExecutor] Error executing sandboxed code | error={type(e).__name__}: {e}")
            return {
                "status": "error",
                "error_msg": str(e),
            }

    @staticmethod
    def _execute_unsafe(code: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """不安全执行（仅在没有 RestrictedPython 时使用）。"""
        try:
            local_vars = {
                "state": context.get("state", {}),
                "context": context.get("context", {}),
                "result": {},
            }

            # 限制可用的内置函数
            restricted_builtins = {
                "len": len,
                "str": str,
                "int": int,
                "float": float,
                "bool": bool,
                "list": list,
                "dict": dict,
                "tuple": tuple,
                "set": set,
                "min": min,
                "max": max,
                "sum": sum,
                "abs": abs,
                "round": round,
            }

            exec(code, {"__builtins__": restricted_builtins}, local_vars)

            result = local_vars.get("result", {})
            return result if isinstance(result, dict) else {"result": result, "status": "success"}

        except Exception as e:
            return {
                "status": "error",
                "error_msg": str(e),
            }

#!/usr/bin/env python3

import importlib.util
import inspect
import logging
import os
import traceback
from pathlib import Path
from typing import Any, Callable, Dict, List, Tuple, Type

from fastmcp import FastMCP

from app.dynamic_agent.core.shared_constants import COMMAND_TOOL, KNOWLEDGE_TOOL
from dynamic_engine.mcp.config import ToolOriginConf
from dynamic_engine.mcp.handler import AbstractHandler

logger = logging.getLogger(__name__)


class ToolMetadataBuilder:
    """
    Helper class to build tool metadata and reduce code duplication (DRY principle).

    Extracts common logic from generate_py_function and generate_md_function.
    """

    @staticmethod
    def build_metadata(
        config: Dict[str, Any],
        tool_type: str,  # 'command' or 'knowledge'
    ) -> Dict[str, Any]:
        """
        Build common tool metadata from config.

        Args:
            config: Tool configuration dict
            tool_type: Type of tool ('command' for .py handlers, 'knowledge' for .md)

        Returns:
            Dict containing: tool_name, description, parameters, returns
        """
        tool_name = config.get("name", "unknown")

        if tool_type == "command":
            description = config.get("description", f"Execute {tool_name}")
            description = f"{COMMAND_TOOL}\n\n{description}"
            parameters = config.get("parameters", [])
            returns = config.get("returns", "Tool execution results")
            returns = f"Result from {COMMAND_TOOL}\n\n{returns}"
        else:  # knowledge
            description = config.get("description", f"Reference {tool_name}")
            description = f"{KNOWLEDGE_TOOL}\n\n{description}"
            parameters = config.get(
                "parameters",
                [{"name": "reason", "required": True, "type": "string", "description": "The reason to call this tool"}],
            )
            returns = config.get("returns", f"{KNOWLEDGE_TOOL} result for reference")
            returns = f"Result from {KNOWLEDGE_TOOL}\n\n{returns}"

        return {
            "tool_name": tool_name,
            "description": description,
            "parameters": parameters,
            "returns": returns,
        }


class ToolRegistry:
    """MCP tool registry center"""

    # Type mapping
    TYPE_MAPPING = {"string": str, "integer": int, "boolean": bool, "number": float, "object": dict, "array": list}

    def __init__(self, mcp: FastMCP):
        """
        Initialize tool registry center

        Args:
            mcp: FastMCP instance
        """
        self.mcp = mcp
        self.tool_configs: Dict[str, ToolOriginConf] = {}
        self.handler_root: Path | None = None

    def _is_within_dir(self, path: Path, base: Path) -> bool:
        """Check if path is within base directory."""
        try:
            # Resolve paths to normalize .. and symlinks
            resolved_path = path.resolve()
            resolved_base = base.resolve()
            resolved_path.relative_to(resolved_base)
            return True
        except ValueError:
            return False

    def _build_signature(self, parameters: List[Dict[str, Any]]) -> inspect.Signature:
        """Build inspect.Signature from parameter configurations."""
        sig_params = []
        for param in parameters:
            name = param["name"]
            param_type = self.TYPE_MAPPING.get(param.get("type", "string"), str)
            required = param.get("required", False)
            default = param.get("default") if not required else inspect.Parameter.empty
            if not required and default is None:
                default = None
            sig_params.append(
                inspect.Parameter(
                    name,
                    inspect.Parameter.POSITIONAL_OR_KEYWORD,
                    default=default,
                    annotation=param_type,
                )
            )
        return inspect.Signature(sig_params)

    def scan_handlers(self, handler_dir: str) -> List[ToolOriginConf]:
        """
        Scan handlers directory to find all tool groups

        Args:
            handler_dir: handlers directory path

        Returns:
            List of tool groups
        """
        handler_path = Path(handler_dir)
        if not handler_path.exists():
            logger.error(f"Handler directory not found: {handler_dir}")
            return []

        self.handler_root = handler_path.resolve()
        tool_configs = {}

        # Deep traverse directory
        for root, dirs, files in os.walk(handler_path):
            # Group by filename
            # file_groups = {}
            for file in files:
                if not file.endswith(".yaml"):
                    continue

                # Get filename (without extension)
                base_name = Path(file).stem
                # ext = Path(file).suffix

                tool_config = ToolOriginConf(base_name, root)
                tool_config.yaml_file = os.path.join(root, file)
                tool_configs[f"{root}/{base_name}"] = tool_config

                # Assign files by extension
                md_file = os.path.join(root, base_name + ".md")
                if os.path.exists(md_file):
                    tool_config.md_file = md_file
                py_file = os.path.join(root, base_name + ".py")
                if os.path.exists(py_file):
                    tool_config.py_file = py_file

        self.tool_configs = tool_configs
        logger.info(f"Found {len(tool_configs)} tool configs")

        return list(tool_configs.values())

    def register_tool(self, originConfig: ToolOriginConf) -> bool:
        # Load configuration
        if not originConfig.load_config():
            return False

        config = originConfig.config
        if not config:
            logger.error(f"No config found: {originConfig}")
            return False

        tool_func = None
        if originConfig.py_file:
            tool_func = self.generate_py_function(config, originConfig.py_file)
        elif originConfig.md_file:
            tool_func = self.generate_md_function(config, originConfig.md_file)
            pass
        else:
            logger.error(f"Unsupported handler: {originConfig}")
            return False

        if not tool_func:
            return False

        try:
            # todo: strengthen tool deduplication logic
            self.mcp.tool()(tool_func)
            logger.info(f"✓ Registered tool: {config['name']}")
            return True
        except Exception as e:
            logger.exception("Failed to register tool")
            logger.error(f"Failed to register tool{config['name']}: {e}")
            return False

    def _generate_parameters(self, parameters: List[Dict[str, Any]]) -> Tuple[str, Dict[str, type]]:
        """
        Generate function parameters and annotations.

        Args:
            parameters: Parameter configurations

        Returns:
            Tuple of (signature string, annotations dict)
        """
        params = []
        annotations = {}

        for param in parameters:
            name = param["name"]
            param_type = param.get("type", "string")
            required = param.get("required", False)
            default = param.get("default")

            # Get Python type
            py_type = self.TYPE_MAPPING.get(param_type, str)
            annotations[name] = py_type

            # Build parameter string
            if not required:
                if default is not None:
                    if param_type == "string":
                        params.append(f"{name}: {py_type.__name__} = '{default}'")
                    else:
                        params.append(f"{name}: {py_type.__name__} = {default}")
                else:
                    params.append(f"{name}: {py_type.__name__} = None")
            else:
                params.append(f"{name}: {py_type.__name__}")

        return ", ".join(params), annotations

    def _generate_param_docs(self, parameters: List[Dict[str, Any]]) -> str:
        """
        Generate parameter documentation

        Args:
            parameters: List of parameters

        Returns:
            Parameter documentation string
        """
        docs = []
        for param in parameters:
            name = param["name"]
            desc = param.get("description", "")
            docs.append(f"        {name}: {desc}")
        return "\n".join(docs) if docs else "        None"

    def register_all(self, handler_dir: str) -> Tuple[List[ToolOriginConf], List[ToolOriginConf]]:
        """
        Scan and register all tools

        Args:
            handler_dir: handlers directory path

        Returns:
            Successfully registered tool count
        """
        tool_configs = self.scan_handlers(handler_dir)

        success = []
        fail = []
        for config in tool_configs:
            try:
                if self.register_tool(config):
                    success.append(config)
                else:
                    fail.append(config)
            except Exception:
                logger.exception("Failed to register tool")
                fail.append(config)

        logger.info(f"Successfully registered {len(success)}/{len(tool_configs)} tools")
        return success, fail

    def generate_py_function(self, config: Dict[str, Any], py_file: str) -> Callable | None:
        try:
            py_path = Path(py_file).resolve()
            if self.handler_root and not self._is_within_dir(py_path, self.handler_root):
                logger.warning(f"PY file {py_file} is outside allowed handler directory")
                return None

            # 1. Dynamically import Python module
            spec = importlib.util.spec_from_file_location(f"handler_{config.get('name', 'unknown')}", py_file)
            if not spec or not spec.loader:
                raise ImportError(f"Cannot load module from {py_file}")

            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            # 2. Find Handler class
            handler_class: Type[AbstractHandler] = None
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if isinstance(attr, type) and attr_name.endswith("Handler") and attr_name != "AbstractHandler":
                    handler_class = attr
                    break

            if not handler_class:
                raise ValueError(f"No Handler class found in {py_file}")

            handler_instance: AbstractHandler = handler_class(config)
            if not handler_instance.available():
                logger.warning(f"handler from {py_file} is not available")
                return None

            # 3. Get tool metadata (DRY: use ToolMetadataBuilder)
            metadata = ToolMetadataBuilder.build_metadata(config, "command")
            tool_name = metadata["tool_name"]
            description = metadata["description"]
            parameters = metadata["parameters"]
            returns = metadata["returns"]

            # 4. Generate parameter signature and annotations
            _, param_annotations = self._generate_parameters(parameters)
            signature = self._build_signature(parameters)
            param_names = [p["name"] for p in parameters]

            # 5. Use closure instead of exec
            def tool_func(*args, **kwargs):
                bound = signature.bind(*args, **kwargs)
                bound.apply_defaults()
                data = {name: bound.arguments.get(name) for name in param_names}
                try:
                    return handler_instance.handle(data)
                except Exception as e:
                    error_msg = f"Error executing {tool_name}: {str(e)}\n{traceback.format_exc()}"
                    logger.error(error_msg)
                    return {"error": str(e), "traceback": traceback.format_exc()}

            tool_func.__name__ = tool_name
            tool_func.__doc__ = f"""{description}

    Args:
{self._generate_param_docs(parameters)}

    Returns:
        {returns}
    """
            tool_func.__signature__ = signature
            tool_func.__annotations__ = param_annotations
            tool_func.__annotations__["return"] = Any

            logger.info(f"Generated function for {tool_name} from {py_file}")
            return tool_func

        except Exception as e:
            logger.error(f"Failed to generate function from {py_file}: {e}")
            logger.exception("Failed to generate function")
            raise

    def generate_md_function(self, config: Dict[str, Any], md_file: str) -> Callable:
        try:
            md_path = Path(md_file).resolve()
            if self.handler_root and not self._is_within_dir(md_path, self.handler_root):
                logger.warning(f"MD file {md_file} is outside allowed handler directory")
                return None
            if not md_path.exists():
                logger.error(f"MD file not found: {md_file}")
                return None
            if md_path.stat().st_size > 1024 * 1024:
                raise ValueError(f"MD file too large: {md_path.stat().st_size} bytes")

            with open(md_path, "r", encoding="utf-8") as f:
                md_content = f.read()

            # Get tool metadata (DRY: use ToolMetadataBuilder)
            metadata = ToolMetadataBuilder.build_metadata(config, "knowledge")
            tool_name = metadata["tool_name"]
            description = metadata["description"]
            parameters = metadata["parameters"]
            returns = metadata["returns"]

            _, param_annotations = self._generate_parameters(parameters)
            signature = self._build_signature(parameters)

            def knowledge_tool(*args, **kwargs) -> str:
                signature.bind(*args, **kwargs)
                return f"Result from {KNOWLEDGE_TOOL}\n\n{md_content}"

            knowledge_tool.__name__ = tool_name
            knowledge_tool.__doc__ = f"""{description}

    Args:
{self._generate_param_docs(parameters)}

    Returns:
        {returns}
    """
            knowledge_tool.__signature__ = signature
            knowledge_tool.__annotations__ = param_annotations
            knowledge_tool.__annotations__["return"] = str

            logger.info(f"Generated function for {tool_name} from {md_file}")
            return knowledge_tool

        except Exception as e:
            logger.error(f"Failed to generate function from {md_file}: {e}")
            logger.exception("Failed to generate function")
            raise

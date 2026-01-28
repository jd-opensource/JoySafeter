import asyncio
import logging
from typing import Any, Dict, List, Optional, Set

from dynamic_engine.mcp.server import dynamic_tools_conf, mcp_server
from dynamic_engine.runtime.command.command_executor import execute_command
from dynamic_engine.runtime.file_manager import file_manager
from dynamic_engine.utils.python_env import env_manager

logger = logging.getLogger(__name__)

BASIC = "basic"


@mcp_server.tool
def list_all_tool_categories() -> Set[str]:
    """
    list all tool categories

    :return: list of categories
    """

    categories = [BASIC]

    for origin_conf in dynamic_tools_conf:
        conf = origin_conf.config
        categories.append(conf["category"])
        categories.extend(conf.get("tags", []))
    return set(categories)


def build_basic_tools() -> list[Any]:
    """Build list of basic tools, handling both sync and async contexts."""
    dynamic_tools = set()
    basic_tools = []
    for origin_conf in dynamic_tools_conf:
        conf = origin_conf.config
        dynamic_tools.add(conf["name"])

    # Get tools in a way that works in both sync and async contexts
    async def _get_tools():
        return await mcp_server.get_tools()

    try:
        # Check if we're in an existing event loop
        asyncio.get_running_loop()
        # We're in an async context - use nest_asyncio or run in thread
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(asyncio.run, _get_tools())
            tools = future.result(timeout=10)
    except RuntimeError:
        # No running loop - safe to use asyncio.run
        tools = asyncio.run(_get_tools())

    for name, tool in tools.items():
        if tool.name in dynamic_tools:
            continue
        basic_tools.append(
            {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters,
                # 'returns': tool,
                "category": BASIC,
                "tags": BASIC,
            }
        )
    return basic_tools


@mcp_server.tool
def list_tools_by_categories(categories: List[str]) -> List[Dict[str, Any]]:
    """
    list tools by categories
    :param categories:
    :return: list of tools info
    """

    result = []
    distinct_names = set()
    for origin_conf in dynamic_tools_conf:
        conf = origin_conf.config
        this_name = conf.get("name", "unknown")
        if this_name in distinct_names:
            continue

        this_categories = [conf["category"]] + conf.get("tags", [])
        if this_categories and any([c in categories for c in this_categories]):
            distinct_names.add(this_name)
            result.append(
                {
                    "name": conf.get("name", "unknown"),
                    "description": conf.get("description", f"Execute {conf.get('name', 'unknown')}"),
                    # 'parameters': conf.get('parameters', []),
                    # 'returns': conf.get('returns', 'Tool execution results'),
                    "category": conf.get("category", "unknown"),
                    "tags": conf.get("tags", []),
                }
            )

    if BASIC in categories:
        result.extend(build_basic_tools())

    return result


# todo: provide a tool to list all available security commands


@mcp_server.tool
def execute_shell_command(command: str, timeout: int = None, cwd: Optional[str] = None) -> Dict[str, Any]:
    """
    Execute any shell command directly. This is the PRIMARY tool for running
    system commands like curl, wget, nc, nmap, python, etc.

    USE THIS TOOL WHEN:
    - You need to make HTTP requests (curl, wget, httpie)
    - You need network operations (nc, netcat, nmap, ping, traceroute)
    - You need to run scripts (python, bash, sh)
    - You need file operations (cat, ls, find, grep)
    - You need to interact with CTF challenges
    - You need to send payloads or exploits
    - No specialized tool exists for your specific task

    SUPPORTED COMMANDS (examples):
    - HTTP: curl, wget, httpie
    - Network: nc, netcat, nmap, ping, dig, host, traceroute, telnet
    - Scripts: python, python3, bash, sh, perl, ruby, php
    - Files: cat, ls, find, grep, head, tail, xxd, hexdump, strings
    - Encoding: base64, xxd, od, hexdump
    - Security: sqlmap, nikto, dirb, gobuster, hydra, john, hashcat
    - Utils: echo, printf, sed, awk, jq, tr, cut, sort, uniq

    EXAMPLES:
    - curl -v http://target:8080/api
    - curl -X POST -d '{"key":"value"}' -H "Content-Type: application/json" http://target/api
    - nc -v target 1337
    - echo "payload" | nc target 1337
    - nmap -sV -p 1-1000 target
    - python3 -c "print('hello')"
    - echo "ZmxhZw==" | base64 -d
    - cat /etc/passwd | grep root

    PARAMETERS:
    :param command: The full shell command to execute (required)
    :param timeout: Timeout in seconds (optional, default: 300)
    :param cwd: Working directory (optional, default: /workspace)

    RETURNS:
    - stdout: Command standard output
    - stderr: Command standard error
    - return_code: Exit code (0 = success)
    - success: Boolean indicating success
    - timed_out: Boolean indicating timeout
    - execution_time: Execution duration in seconds

    NOTE: Commands run in an isolated container environment. Use this tool
    freely for CTF challenges, penetration testing, and security research.
    """

    return execute_command(command, timeout, cwd)


@mcp_server.tool
def get_command_help(command: str) -> Dict[str, Any]:
    """
    Get help documentation for a command by executing command --help or -h

    :param command: The command name to get help for (e.g., 'dotdotpwn', 'nmap', 'ghidra')
    :return: A dictionary containing the help output and metadata
    """
    try:
        if not command or not command.strip():
            return {"error": "Command name is required"}

        command_name = command.strip().split()[0]

        # Try different help flags in order of preference
        help_flags = ["--help", "-h", "-help", "help", "--info", "-?"]

        for flag in help_flags:
            try:
                help_command = f"{command_name} {flag}"
                logger.info(f"🔍 Attempting to get help for {command_name} with flag: {flag}")
                result = execute_command(help_command, timeout=10)

                # Check if we got meaningful output
                if result.get("stdout") or result.get("stderr"):
                    result["help_flag_used"] = flag
                    result["command"] = command_name
                    logger.info(f"✅ Successfully retrieved help for {command_name}")
                    return result
            except Exception as e:
                logger.debug(f"Flag {flag} failed for {command_name}: {str(e)}")
                continue

        return {
            "error": f"Could not retrieve help for command: {command_name}",
            "attempted_flags": help_flags,
            "command": command_name,
        }

    except Exception as e:
        logger.error(f"💥 Error getting command help: {str(e)}")
        return {"error": f"Server error: {str(e)}"}


@mcp_server.tool
def execute_python_script(
    script: str, file_name: str = "script.py", env_name: str = None, cwd: Optional[str] = None
) -> Dict[str, Any]:
    """
        Execute a Python script in the container environment.

        USE THIS TOOL FOR:
        - Complex multi-step operations (login + session + requests)
        - Bulk/parallel HTTP requests (enumeration, fuzzing)
        - Cryptographic operations (encryption, decryption, hashing)
        - Data processing (parsing, extraction, transformation)
        - Any task requiring Python libraries (requests, pwntools, etc.)

        PARAMETERS:
        :param script: The Python code to execute (required)
        :param file_name: Name for the script file (default: script.py)
        :param env_name: Virtual environment name (optional, uses system python3 if not specified)
        :param cwd: Working directory (optional)

        RETURNS:
        - stdout: Script output
        - stderr: Error output
        - return_code: Exit code (0 = success)
        - success: Boolean indicating success

        EXAMPLE:
        script = '''
    import requests
    session = requests.Session()
    r = session.post("http://target/login", data={"user": "test", "pass": "test"})
    print(r.text)
    '''
    """

    try:
        if not script:
            return {"error": "Script content is required"}
        script_result = file_manager.create_file(file_name, script)
        if not script_result["success"]:
            return script_result
        python_path = env_manager.get_python_path(env_name)
        script_path = script_result["path"]
        command = f"{python_path} {script_path}"
        logger.info(f"🐍 Executing Python script in env {env_name}: {file_name}")
        result = execute_command(command)
        file_manager.delete_file(file_name)
        result["env_name"] = env_name
        result["script_filename"] = file_name
        logger.info("📊 Python script execution completed")
        return result
    except Exception as e:
        logger.error(f"💥 Error executing Python script: {str(e)}")
        return {"error": f"Server error: {str(e)}"}


# todo
def execute_python_script_backup(
    script: str, file_name: str = "script.py", env_name: str = None, cwd: Optional[str] = None
) -> Dict[str, Any]:
    import os
    import tempfile

    try:
        if not script:
            return {"error": "Script content is required"}

        # Create script in a temp directory that's accessible
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, dir="/tmp") as f:
            f.write(script)
            script_path = f.name

        # Use system python3 directly (env_name is for future virtual env support)
        python_path = "python3" if not env_name else env_manager.get_python_path(env_name)
        command = f"{python_path} {script_path}"

        logger.info(f"🐍 Executing Python script: {script_path}")
        result = execute_command(command, cwd=cwd)

        # Clean up
        try:
            os.unlink(script_path)
        except Exception:
            pass

        result["env_name"] = env_name or "system"
        result["script_filename"] = file_name
        logger.info(f"📊 Python script execution completed: return_code={result.get('return_code')}")
        return result
    except Exception as e:
        logger.error(f"💥 Error executing Python script: {str(e)}")
        return {"error": f"Server error: {str(e)}"}


# if __name__ == "__main__":
#     mcp_server.run()

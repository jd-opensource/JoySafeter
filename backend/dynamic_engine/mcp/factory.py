#!/usr/bin/env python3

import argparse
import os
import sys
from typing import List

# Import core_tools to register execute_shell_command and execute_python_script
import dynamic_engine.admin.core_tools  # noqa: F401 - side effect import for tool registration
from dynamic_engine.mcp.log_config import setup_logging
from dynamic_engine.mcp.registry import ToolOriginConf, ToolRegistry
from dynamic_engine.mcp.server import dynamic_tools_conf, mcp_server


class Colors:
    """Enhanced color palette matching the server's ModernVisualEngine.COLORS"""

    # Basic colors
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    MAGENTA = "\033[95m"
    CYAN = "\033[96m"
    WHITE = "\033[97m"

    # Core enhanced colors
    MATRIX_GREEN = "\033[38;5;46m"
    NEON_BLUE = "\033[38;5;51m"
    ELECTRIC_PURPLE = "\033[38;5;129m"
    CYBER_ORANGE = "\033[38;5;208m"
    HACKER_RED = "\033[38;5;196m"
    TERMINAL_GRAY = "\033[38;5;240m"
    BRIGHT_WHITE = "\033[97m"
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"

    # Enhanced reddish tones
    BLOOD_RED = "\033[38;5;124m"
    CRIMSON = "\033[38;5;160m"
    DARK_RED = "\033[38;5;88m"
    FIRE_RED = "\033[38;5;202m"
    ROSE_RED = "\033[38;5;167m"
    BURGUNDY = "\033[38;5;52m"
    SCARLET = "\033[38;5;197m"
    RUBY = "\033[38;5;161m"

    # Status colors
    SUCCESS = "\033[38;5;46m"
    WARNING = "\033[38;5;208m"
    ERROR = "\033[38;5;196m"
    CRITICAL = "\033[48;5;196m\033[38;5;15m\033[1m"
    INFO = "\033[38;5;51m"
    DEBUG = "\033[38;5;240m"


# ============================================================================
# MCP SERVER SETUP
# ============================================================================


def setup_mcp_server(debug: bool = True, host="0.0.0.0", port=8000):
    """Setup MCP server"""
    # Setup logging
    logger = setup_logging()
    logger.info(f"{Colors.INFO}🔧 Initialized FastMCP server{Colors.RESET}")

    registry = ToolRegistry(mcp_server)
    # todo dynamic load from db
    success, fail = registry.register_all(os.path.join(os.path.dirname(os.path.abspath(__file__)), "../handlers"))
    dynamic_tools_conf.extend(success)

    success: List[ToolOriginConf] = success
    tools = [suc.config for suc in success]

    # Category statistics
    if debug:
        category_stats = {}
        for tool_config in tools:
            cat = tool_config.get("category", "unknown")
            category_stats[cat] = category_stats.get(cat, 0) + 1

        logger.debug(f"{Colors.INFO}📈 Tools by category:{Colors.RESET}")
        for cat, count in sorted(category_stats.items(), key=lambda x: x[1], reverse=True):
            # cat_name = categories.get(cat, {}).get('name', cat)
            logger.debug(f"{Colors.DEBUG}  - {cat}: {count} tools{Colors.RESET}")

    logger.info(
        f"{Colors.SUCCESS}🎉 MCP server ready! All tools generated dynamically from configuration.{Colors.RESET}"
    )

    return mcp_server


# ============================================================================
# MAIN ENTRY POINT
# ============================================================================


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description="seclens AI MCP Client - Dynamic Tool Generation v7.0")

    parser.add_argument("--debug", action="store_true", help="Enable debug logging")

    args = parser.parse_args()

    try:
        # Setup and run MCP server
        mcp = setup_mcp_server(args.debug)
        mcp.run(transport="sse")

    except KeyboardInterrupt:
        print(f"\n{Colors.WARNING}⚠️  Interrupted by user{Colors.RESET}")
        sys.exit(0)

    except Exception as e:
        print(f"{Colors.ERROR}❌ Fatal error: {e}{Colors.RESET}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()

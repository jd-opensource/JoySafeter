KNOWLEDGE_TOOL = "<knowledge based tool>"
COMMAND_TOOL = "<command based tool>"
COMMAND_HELP_TOOL = "get_command_help"
AGENT_TOOL = "agent_tool"
THINK_TOOL = "think_tool"
SHELL_COMMAND_TOOL = "execute_shell_command"

# Single-layer architecture: Main Agent (level 0) → Sub-Agent (level 1)
# Sub-Agent cannot spawn child agents
MAX_AGENT_DEPTH = 1

# 006: Subagent execution timeout (10 minutes)
# Increased from 5min to 10min to accommodate CTF challenges with multiple tool calls
SUBAGENT_TIMEOUT_SECONDS = 600

# 006: Maximum length for subagent result summary
# Increased to 4000 to accommodate full <result> XML with all attempts
SUMMARY_MAX_LENGTH = 4000

WORKSPACE = "/workspace"

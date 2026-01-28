"""
Ask Human Tool - Request human intervention when stuck.

Allows the Agent to pause and request specific information from the user
when automated approaches have failed.
"""

from langchain_core.tools import tool
from loguru import logger


@tool
def ask_human(question: str, context: str, tried_approaches: str, specific_info_needed: str) -> str:
    """
    Request human intervention to obtain critical information.

    Use this tool when automated methods cannot continue. The agent will pause and wait for user input.

    Args:
        question: Specific question to ask the user
        context: Current task context (what has been discovered, where it is stuck)
        tried_approaches: List of methods already tried
        specific_info_needed: Specific type of information needed from the user
            Examples: "Order ID range", "Special authentication header", "Hidden endpoint", "Admin credentials"

    Returns:
        Information provided by the user, or timeout message

    Example:
        ask_human(
            question="What is the order ID range where the FLAG is located?",
            context="Logged in as test:test, enumerated 1-1000 and 300000-301000 but found nothing",
            tried_approaches="/order/{1-1000}/receipt, /order/{300000-301000}/receipt",
            specific_info_needed="Correct order ID range or other IDOR endpoints"
        )
    """
    logger.info(f"🙋 Human intervention requested: {question}")

    # Format the request for display
    request_msg = f"""
╭─────────────────────────────────────────────────────────────────╮
│  🙋 HUMAN INTERVENTION REQUESTED                                │
╰─────────────────────────────────────────────────────────────────╯

**Question**: {question}

**Current Context**:
{context}

**Tried Approaches**:
{tried_approaches}

**Specific Info Needed**: {specific_info_needed}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Please provide the requested information below:
"""

    print(request_msg)

    try:
        # Check if stdin is interactive
        import sys

        if not sys.stdin.isatty():
            # Non-interactive mode - STOP and require human intervention
            stop_msg = f"""
⛔ STOP - HUMAN INTERVENTION REQUIRED ⛔

The agent has reached a point where it cannot proceed without human input.
This is running in non-interactive mode (piped input).

To provide the requested information, please:
1. Run the agent in interactive mode (without piping)
2. Or modify the task to include the needed information

Question: {question}
Info Needed: {specific_info_needed}

AGENT MUST STOP HERE. Do not continue with guesses or workarounds.
"""
            print(stop_msg)
            logger.warning("Agent stopped - human intervention required in non-interactive mode")
            return "⛔ STOP: Human intervention required. Agent must stop here. Do not continue guessing or trying other methods. Please run in interactive mode or provide the required information."

        # Interactive mode - read user input (supports multi-line)
        # User can paste multiple lines, end with empty line or Ctrl+D
        print("Your input (end with empty line or Ctrl+D):")
        lines = []
        try:
            while True:
                line = input()
                if line == "":  # Empty line ends input
                    break
                lines.append(line)
        except EOFError:
            pass  # Ctrl+D ends input

        user_input = "\n".join(lines).strip()

        if not user_input:
            return "User did not provide information. Please continue trying other methods or ask again later."

        logger.info(f"✅ Human provided: {user_input[:100]}...")
        return f"Information provided by user: {user_input}"

    except EOFError:
        # Stdin closed unexpectedly
        return "⛔ STOP: stdin closed, human intervention required. Agent must stop."
    except KeyboardInterrupt:
        return "⛔ STOP: User canceled input. Agent must stop."


# Export
__all__ = ["ask_human"]

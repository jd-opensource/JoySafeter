"""Utility for precise token counting using LangChain models."""

from pathlib import Path

from langchain_core.messages import SystemMessage
from loguru import logger


def calculate_baseline_tokens(model, agent_dir: Path, system_prompt: str) -> int:
    """Count baseline context tokens using the model's official tokenizer.

    Use the model's get_num_tokens_from_messages() method to get a precise
    token count for the initial context (system prompt + agent.md).

    Note: due to LangChain limitations, tool definitions cannot be accurately
    counted before the first API call. They will be included in the total
    after the first message is sent (~5000 tokens).

    Args:
        model: LangChain model instance (ChatAnthropic or ChatOpenAI)
        agent_dir: path to the agent directory containing agent.md
        system_prompt: base system prompt string

    Returns:
        Token count for system prompt + agent.md (excluding tools)
    """
    # Load agent.md content
    agent_md_path = agent_dir / "agent.md"
    agent_memory = ""
    if agent_md_path.exists():
        agent_memory = agent_md_path.read_text()

    # Build the complete system prompt as it will be sent
    # This mimics what AgentMemoryMiddleware.wrap_model_call() does
    memory_section = f"<agent_memory>\n{agent_memory}\n</agent_memory>"

    # Get the long-term memory system prompt
    memory_system_prompt = get_memory_system_prompt()

    # Combine all parts in the same order as the middleware
    full_system_prompt = memory_section + "\n\n" + system_prompt + "\n\n" + memory_system_prompt

    # Count tokens using the model's official method
    messages = [SystemMessage(content=full_system_prompt)]

    try:
        # Note: tools parameter is not supported by LangChain's token counting
        # Tool tokens will be included in the API response after first message
        token_count = model.get_num_tokens_from_messages(messages)
        return int(token_count)  # type: ignore[no-any-return]
    except NotImplementedError as e:
        # some models (e.g. GLM, custom models) do not implement token counting
        logger.info(f"[yellow]Token counting unavailable: {e}[/yellow]")
        logger.info("[dim]Falling back to estimated token count...[/dim]")
        return estimate_token_count(full_system_prompt)
    except Exception as e:
        # handle other errors
        logger.info(f"[yellow]Token counting failed: {e}[/yellow]")
        logger.info("[dim]Falling back to estimated token count...[/dim]")
        return estimate_token_count(full_system_prompt)


def estimate_token_count(text: str) -> int:
    """Estimate the token count of a text string.

    A simple heuristic that works reasonably well for mixed Chinese/English text.
    Note: this is an approximation; actual token counts vary by model.

    Args:
        text: the text to estimate token count for

    Returns:
        Estimated token count
    """
    if not text:
        return 0

    # basic token estimation rules:
    # 1. English words average ~1.3 tokens
    # 2. Chinese characters are typically ~2 tokens each
    # 3. code, punctuation, whitespace counted by character

    import re

    # separate Chinese characters from English content
    chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", text))
    english_words = len(re.findall(r"\b[a-zA-Z]+\b", text))
    other_chars = len(text) - chinese_chars - len("".join(re.findall(r"\b[a-zA-Z]+\b", text)))

    # estimate token count
    estimated_tokens = chinese_chars * 2 + english_words * 1.3 + other_chars * 0.5

    return int(estimated_tokens)


def get_memory_system_prompt() -> str:
    """Return the long-term memory system prompt text."""
    # Import from agent_memory middleware
    from ..midware.memory_in_file import LONGTERM_MEMORY_SYSTEM_PROMPT

    return str(LONGTERM_MEMORY_SYSTEM_PROMPT.format(memory_path="/memories/"))


def count_tokens(text: str) -> int:
    """Count tokens in text using tiktoken.

    Uses cl100k_base encoding (compatible with GPT-4, GPT-4o, GPT-3.5-turbo).
    Falls back to character-based estimation if tiktoken is not available.

    Args:
        text: The text string to count tokens for.

    Returns:
        Total token count for the text.

    Examples:
        >>> count_tokens("Hello world")
        2
        >>> count_tokens("")
        0
    """
    try:
        import tiktoken

        # Use cl100k_base encoding (GPT-4, GPT-4o, GPT-3.5-turbo)
        encoding = tiktoken.get_encoding("cl100k_base")
        tokens = encoding.encode(text)
        return len(tokens)
    except ImportError:
        from loguru import logger

        logger.warning(
            "tiktoken not installed. You can install with `pip install -U tiktoken`. Using character-based estimation."
        )
        # Fallback: rough estimation (1 token H 4 characters)
        return len(text) // 4
    except Exception as e:
        from loguru import logger

        logger.warning(f"Error counting tokens: {e}. Using character-based estimation.")
        return len(text) // 4

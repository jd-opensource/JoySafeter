"""使用LangChain model进行精确token计数的实用工具。"""

from pathlib import Path

from langchain_core.messages import SystemMessage
from loguru import logger


def calculate_baseline_tokens(model, agent_dir: Path, system_prompt: str) -> int:
    """使用模型的官方分词器计算基线上下文token数。

    这使用模型的get_num_tokens_from_messages()方法来获取初始上下文（系统提示+agent.md）的精确token计数。

    注意：由于LangChain限制，工具定义无法在第一次API调用之前准确计数。
    它们将在第一条消息发送后包含在总数中（约5000个token）。

    Args:
        model: LangChain模型实例 (ChatAnthropic或ChatOpenAI)
        agent_dir: 包含agent.md的代理目录路径
        system_prompt: 基础系统提示字符串

    Returns:
        系统提示+agent.md的token计数（不包括工具）
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
        # 某些模型（如GLM、自定义模型）没有实现token计数方法
        logger.info(f"[yellow]Token计数不可用: {e}[/yellow]")
        logger.info("[dim]使用估算方法计算token数...[/dim]")
        return estimate_token_count(full_system_prompt)
    except Exception as e:
        # 其他错误的处理
        logger.info(f"[yellow]Token计算失败: {e}[/yellow]")
        logger.info("[dim]使用估算方法计算token数...[/dim]")
        return estimate_token_count(full_system_prompt)


def estimate_token_count(text: str) -> int:
    """估算文本的token数量。

    这是一个简单的估算方法，对于中英文混合文本比较有效。
    注意：这是一个估算值，实际token数可能因模型而异。

    Args:
        text: 要估算token数的文本

    Returns:
        估算的token数量
    """
    if not text:
        return 0

    # 基本的token估算规则：
    # 1. 英文单词平均约 1.3 tokens
    # 2. 中文字符通常 1 个字符约 2 tokens
    # 3. 代码、标点、空格等按字符计数

    import re

    # 分离中文字符和英文内容
    chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", text))
    english_words = len(re.findall(r"\b[a-zA-Z]+\b", text))
    other_chars = len(text) - chinese_chars - len("".join(re.findall(r"\b[a-zA-Z]+\b", text)))

    # 估算token数
    estimated_tokens = chinese_chars * 2 + english_words * 1.3 + other_chars * 0.5

    return int(estimated_tokens)


def get_memory_system_prompt() -> str:
    """获取长期记忆系统提示文本"""
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

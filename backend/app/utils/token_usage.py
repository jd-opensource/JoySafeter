"""
Token Usage Normalization

Modeled after Langfuse _parse_usage_model().
Normalize token usage from various LLM vendors into a standard {input, output, total} format.
Support OpenAI, Anthropic, Bedrock, Vertex AI, IBM watsonx, etc.
"""

from typing import Any, Optional

# vendor key -> normalized key mapping table
# order matters: try vendor-specific keys first, generic keys last
USAGE_KEY_MAPPING: list[tuple[str, str]] = [
    # Anthropic (via langchain-anthropic, also Bedrock-Anthropic)
    ("input_tokens", "input"),
    ("output_tokens", "output"),
    # OpenAI / ChatBedrock (non-Converse API)
    ("prompt_tokens", "input"),
    ("completion_tokens", "output"),
    # Generic
    ("total_tokens", "total"),
    # Google Vertex AI
    ("prompt_token_count", "input"),
    ("candidates_token_count", "output"),
    ("total_token_count", "total"),
    # AWS Bedrock (CloudWatch format)
    ("inputTokenCount", "input"),
    ("outputTokenCount", "output"),
    ("totalTokenCount", "total"),
    # IBM watsonx (langchain-ibm)
    ("input_token_count", "input"),
    ("generated_token_count", "output"),
]


def normalize_usage(raw_usage: Any) -> Optional[dict[str, int]]:
    """
    Normalize token usage from various vendors into {input, output, total}.

    Modeled after Langfuse CallbackHandler._parse_usage_model()

    Args:
        raw_usage: raw usage data; may be a dict, pydantic model, or other object

    Returns:
        Normalized {input: int, output: int, total: int}, or None if unparseable
    """
    if raw_usage is None:
        return None

    # convert to dict
    usage: dict
    if isinstance(raw_usage, dict):
        usage = raw_usage.copy()
    elif hasattr(raw_usage, "__dict__"):
        usage = {k: v for k, v in raw_usage.__dict__.items() if not k.startswith("_")}
    elif hasattr(raw_usage, "model_dump"):
        try:
            usage = raw_usage.model_dump()
        except Exception:
            return None
    else:
        return None

    if not usage:
        return None

    # detect standard OpenAI format (return directly, no conversion needed)
    openai_keys_full = {
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "prompt_tokens_details",
        "completion_tokens_details",
    }
    openai_keys_basic = {"prompt_tokens", "completion_tokens", "total_tokens"}
    if set(usage.keys()) == openai_keys_full or set(usage.keys()) == openai_keys_basic:
        return {
            "input": usage.get("prompt_tokens", 0) or 0,
            "output": usage.get("completion_tokens", 0) or 0,
            "total": usage.get("total_tokens", 0) or 0,
        }

    # convert using mapping table
    result: dict[str, int] = {}
    for source_key, target_key in USAGE_KEY_MAPPING:
        if source_key in usage:
            value = usage.pop(source_key)
            # Bedrock streaming may return a list
            if isinstance(value, list):
                value = sum(v for v in value if isinstance(v, (int, float)))
            if isinstance(value, (int, float)):
                result[target_key] = int(value)

    # ensure total exists
    if "total" not in result and "input" in result and "output" in result:
        result["total"] = result["input"] + result["output"]

    # keep only valid integer values
    result = {k: v for k, v in result.items() if isinstance(v, int) and v >= 0}

    return result if result else None


def extract_usage_from_output(output: Any) -> Optional[dict[str, int]]:
    """
    Extract token usage from a LangChain LLM output using multiple sources.

    Modeled after Langfuse CallbackHandler._parse_usage(), trying sources by priority:
    1. output.usage_metadata (langchain_core >= 0.2, most direct)
    2. output.response_metadata["token_usage"] (OpenAI)
    3. output.response_metadata["usage"] (Bedrock-Anthropic)
    4. output.response_metadata["amazon-bedrock-invocationMetrics"] (Bedrock-Titan)
    5. output.response_metadata["usage_metadata"] (legacy)

    Args:
        output: LLM output object (typically AIMessage or ChatGeneration)

    Returns:
        Normalized token usage, or None
    """
    if output is None:
        return None

    raw_usage = None

    # 1. output.usage_metadata (langchain_core >= 0.2, most direct)
    if hasattr(output, "usage_metadata") and output.usage_metadata:
        raw_usage = output.usage_metadata

    # 2-5. various locations inside response_metadata
    if raw_usage is None and hasattr(output, "response_metadata"):
        rm = output.response_metadata
        if isinstance(rm, dict):
            # 2. token_usage (OpenAI via langchain-openai)
            raw_usage = rm.get("token_usage")
            # 3. usage (Bedrock-Anthropic)
            if raw_usage is None:
                raw_usage = rm.get("usage")
            # 4. amazon-bedrock-invocationMetrics (Bedrock-Titan)
            if raw_usage is None:
                raw_usage = rm.get("amazon-bedrock-invocationMetrics")
            # 5. usage_metadata (legacy fallback)
            if raw_usage is None:
                raw_usage = rm.get("usage_metadata")

    if raw_usage is None:
        return None

    return normalize_usage(raw_usage)


def extract_usage_from_llm_result(response: Any) -> Optional[dict[str, int]]:
    """
    Extract token usage from an LLMResult object.

    Args:
        response: LLMResult object (the response parameter of on_llm_end)

    Returns:
        Normalized token usage, or None
    """
    if response is None:
        return None

    raw_usage = None

    # extract from llm_output
    llm_output = getattr(response, "llm_output", None)
    if isinstance(llm_output, dict):
        raw_usage = llm_output.get("token_usage") or llm_output.get("usage")

    # extract from generations
    if raw_usage is None:
        generations = getattr(response, "generations", None)
        if generations and len(generations) > 0:
            gen_list = generations[0] if isinstance(generations[0], list) else generations
            if gen_list and len(gen_list) > 0:
                gen = gen_list[0]
                # ChatGeneration.message
                msg = getattr(gen, "message", None)
                if msg:
                    return extract_usage_from_output(msg)
                # Generation.generation_info
                gen_info = getattr(gen, "generation_info", None)
                if isinstance(gen_info, dict):
                    raw_usage = gen_info.get("usage_metadata") or gen_info.get("usage")

    if raw_usage is None:
        return None

    return normalize_usage(raw_usage)

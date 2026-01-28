import os
from typing import Optional

from langchain_openai import ChatOpenAI

from app.core.settings import get_default_model_config


class LLMManager:
    """LLM instance manager"""

    def __init__(self):
        self._default_llm: Optional[ChatOpenAI] = None

    def _get_llm_config(self):
        """Get LLM config, priority from database cache, otherwise from environment variables"""
        # 1. Try to get from database cache
        config = get_default_model_config()
        if config:
            return config

        # 2. Fallback: Get from environment variables
        base_url = os.getenv("DEFAULT_OPENAI_COMPATIBLE_API_BASE")
        api_key = os.getenv("DEFAULT_OPENAI_COMPATIBLE_API_KEY")
        model = os.getenv("DEFAULT_OPENAI_COMPATIBLE_MODEL")
        timeout_str = os.getenv("DEFAULT_OPENAI_COMPATIBLE_MODEL_TIMEOUT", "300")

        if base_url and api_key and model:
            return {
                "base_url": base_url,
                "api_key": api_key,
                "model": model,
                "timeout": int(timeout_str),
            }

        # 3. Error if neither is available
        raise ValueError(
            "Default model configuration not found. Please configure via one of the following methods:\n"
            "1. Configure default model in system settings\n"
            "2. Set DEFAULT_OPENAI_COMPATIBLE_* environment variables in .env file"
        )

    def _create_llm_from_config(self, config: dict) -> ChatOpenAI:
        """Create ChatOpenAI instance from config"""
        return ChatOpenAI(
            model=config["model"],
            api_key=config["api_key"],
            base_url=config["base_url"],
            timeout=config["timeout"],
            # max_retries=0,
            streaming=False,
            callbacks=[],
        )

    def get_default_llm(self) -> ChatOpenAI:
        """Get default LLM instance (singleton, lazy initialization)"""
        if self._default_llm is None:
            config = self._get_llm_config()
            self._default_llm = self._create_llm_from_config(config)
        return self._default_llm

    def create_llm(self) -> ChatOpenAI:
        """Create new LLM instance"""
        config = self._get_llm_config()
        return self._create_llm_from_config(config)


# Global LLM manager instance
_llm_manager = LLMManager()


# Convenience function interface
def get_default_llm() -> ChatOpenAI:
    """Get default LLM instance (lazy initialization singleton)"""
    # return _llm_manager.get_default_llm()
    return create_llm_instance()


def create_llm_instance() -> ChatOpenAI:
    """Create new LLM instance"""
    return _llm_manager.create_llm()


DEBUG = os.environ.get("DEBUG", "false").lower() == "true"

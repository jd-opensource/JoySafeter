import os
import re
from pathlib import Path

from dotenv import load_dotenv

# Load environment variables from .env file
# .env is in agent/ directory (parent of core/)
env_path = Path(__file__).parent.parent.parent / ".env"
load_dotenv(env_path)

# PORT=${PORT:-8000}
pattern = re.compile(r"\$\{([^}:\-]+)(:-([^}]+))?\}")


def expand_env(value: str):
    if not value:
        return value

    def repl(match):
        key = match.group(1)
        default = match.group(3)
        return os.getenv(key, default if default is not None else "")

    return pattern.sub(repl, value)


for key, value in os.environ.items():
    expanded = expand_env(value)
    os.environ[key] = expanded

# Debug: print(json.dumps({i:os.environ.get(i) for i in os.environ}, indent=2, ensure_ascii=False))


class Config:
    """Configuration class that loads settings from environment variables."""

    NAME = "seclens"
    # SERVER_CONFIGS = [
    #     {"name": "seclens", "url": "http://127.0.0.1:8000/sse"},
    #     # {"name": "serverB", "url": "http://127.0.0.1:8000/sse"},
    # ]

    # Langfuse Configuration
    LANGFUSE_SECRET_KEY = os.getenv("LANGFUSE_SECRET_KEY", "")
    LANGFUSE_PUBLIC_KEY = os.getenv("LANGFUSE_PUBLIC_KEY", "")
    LANGFUSE_HOST = os.getenv("LANGFUSE_HOST", "")

    # CTF Mode Configuration
    CTF_MODE_ENABLED = os.getenv("CTF_MODE_ENABLED", "true").lower() == "true"
    CTF_DEFAULT_RISK_LEVEL = os.getenv("CTF_DEFAULT_RISK_LEVEL", "low")  # low, medium, high
    CTF_MAX_RETRY_ATTEMPTS = int(os.getenv("CTF_MAX_RETRY_ATTEMPTS", "3"))
    CTF_REFERENCE_SEARCH_ENABLED = os.getenv("CTF_REFERENCE_SEARCH_ENABLED", "true").lower() == "true"
    CTF_AUTO_DETECT = os.getenv("CTF_AUTO_DETECT", "true").lower() == "true"  # Auto-detect CTF intent from user input

    # Rich CLI Display Configuration
    RICH_CLI_ENABLED = os.getenv("RICH_CLI_ENABLED", "false").lower() == "true"  # Enable Rich console output

    def __init__(self):
        """Initialize configuration and validate required settings."""
        self._validate_config()
        # import logging

        # todo
        # Remove existing handlers to prevent previous settings from affecting
        # for handler in logging.root.handlers[:]:
        #     logging.root.removeHandler(handler)
        #
        # log_level = os.environ.get('LOG_LEVEL', 'INFO')
        # log_format = "%(asctime)s [%(levelname)s] %(name)s - %(filename)s:%(lineno)d - %(message)s"
        # date_format = "%H:%M:%S"
        #
        # # Reconfigure logging to output to both file and console
        # logging.basicConfig(
        #     level=log_level,
        #     format=log_format,
        #     datefmt=date_format,
        #     handlers=[
        #         logging.StreamHandler(sys.stdout),
        #         logging.FileHandler("seclens.log", encoding='utf-8')
        #     ]
        # )
        # logging.getLogger().setLevel(log_level)

    def _validate_config(self):
        """Validate that all required configuration values are set."""
        required_keys = []
        missing_keys = [key for key in required_keys if not getattr(self, key, None)]

        if missing_keys:
            raise ValueError(f"Missing required environment variables: {', '.join(missing_keys)}")

    def to_dict(self):
        """Convert configuration to dictionary."""
        return {
            "LANGFUSE_SECRET_KEY": self.LANGFUSE_SECRET_KEY,
            "LANGFUSE_PUBLIC_KEY": self.LANGFUSE_PUBLIC_KEY,
            "LANGFUSE_HOST": self.LANGFUSE_HOST,
        }


# Create a singleton instance
conf = Config()

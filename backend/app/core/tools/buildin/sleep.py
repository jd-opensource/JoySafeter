import time

from loguru import logger

from app.core.tools.toolkit import Toolkit


class SleepTools(Toolkit):
    def __init__(self, enable_sleep: bool = True, all: bool = False, **kwargs):
        tools = []
        if all or enable_sleep:
            tools.append(self.sleep)

        super().__init__(name="sleep", tools=tools, **kwargs)

    def sleep(self, seconds: int) -> str:
        """Use this function to sleep for a given number of seconds."""
        logger.info(f"Sleeping for {seconds} seconds")
        time.sleep(seconds)
        logger.info(f"Awake after {seconds} seconds")
        return f"Slept for {seconds} seconds"

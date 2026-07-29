import os


_TRUE_VALUES = {"1", "true", "yes", "on"}


def legacy_sandbox_memory_enabled() -> bool:
    """Whether JoySafeter's legacy /mnt/memory runtime is active.

    EverOS is the default long-term memory runtime. This flag only controls the
    old sandbox file-mount and memory_sync path; stored legacy data and API
    endpoints remain intact.
    """
    raw = os.getenv("JOYSAFETER_LEGACY_SANDBOX_MEMORY_ENABLED", "false")
    return raw.strip().lower() in _TRUE_VALUES

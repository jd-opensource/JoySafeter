"""Cloud sandbox backends and factory functions.

This package provides cloud-based sandbox implementations and factory functions
for creating sandbox environments across different providers.

**Architecture Overview:**

The sandbox system has two main branches:

1. **Local Backends** (`app.core.agent.backends`):
   - FilesystemSandboxBackend: Local filesystem with command execution
   - StateSandboxBackend: In-memory state with command execution
   - PydanticSandboxAdapter: Docker-based sandbox (via pydantic-ai-backend)

2. **Cloud Backends** (`app.core.tools.sandbox`):
   - ModalBackend: Modal.com cloud sandbox
   - RunloopBackend: Runloop.ai cloud devbox

All backends implement `SandboxBackendProtocol` from `deepagents.backends.protocol`,
ensuring a consistent interface for:
- Command execution (`execute()`)
- File operations (`read()`, `write()`, `edit()`, etc.)
- File search (`grep_raw()`, `glob_info()`)
- File transfer (`download_files()`, `upload_files()`)

**Usage:**

```python
# Using factory function (recommended)
from app.core.tools.sandbox import create_sandbox, create_docker_sandbox

# Create Docker sandbox
with create_docker_sandbox(runtime="python-datascience") as sandbox:
    result = sandbox.execute("python -c 'import pandas; print(pandas.__version__)'")

# Create cloud sandbox (Modal, Runloop)
with create_sandbox("modal") as sandbox:
    result = sandbox.execute("echo 'Hello from Modal!'")
```

**Available Providers:**
- `docker`: Local Docker container (via PydanticSandboxAdapter)
- `modal`: Modal.com cloud sandbox
- `runloop`: Runloop.ai cloud devbox
"""

from app.core.tools.sandbox.sandbox_factory import (
    create_docker_sandbox,
    create_sandbox,
    get_available_sandbox_types,
    get_default_working_dir,
)

# Cloud backends (lazy import to avoid dependency issues)
try:
    from app.core.tools.sandbox.modal import ModalBackend

    MODAL_AVAILABLE = True
except ImportError:
    ModalBackend = None  # type: ignore
    MODAL_AVAILABLE = False

try:
    from app.core.tools.sandbox.runloop import RunloopBackend

    RUNLOOP_AVAILABLE = True
except ImportError:
    RunloopBackend = None  # type: ignore
    RUNLOOP_AVAILABLE = False

__all__ = [
    # Factory functions
    "create_sandbox",
    "create_docker_sandbox",
    "get_available_sandbox_types",
    "get_default_working_dir",
    # Cloud backends
    "ModalBackend",
    "RunloopBackend",
    # Availability flags
    "MODAL_AVAILABLE",
    "RUNLOOP_AVAILABLE",
]

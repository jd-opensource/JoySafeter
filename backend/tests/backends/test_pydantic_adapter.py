"""Tests for PydanticSandboxAdapter and RuntimeConfig.

These tests verify the new features added to pydantic_adapter.py:
- RuntimeConfig data class
- BUILTIN_RUNTIMES predefined configurations
- _resolve_runtime() method
- Extended constructor parameters (runtime, session_id, idle_timeout, volumes)
"""

import pytest

from app.core.agent.backends.pydantic_adapter import (
    BUILTIN_RUNTIMES,
    PydanticSandboxAdapter,
    RuntimeConfig,
    get_builtin_runtime,
    list_builtin_runtimes,
)
from app.core.agent.backends.runtime_config import resolve_runtime


class TestRuntimeConfig:
    """Tests for RuntimeConfig dataclass."""

    def test_create_with_defaults(self):
        """Test creating RuntimeConfig with default values."""
        config = RuntimeConfig(name="test")
        assert config.name == "test"
        assert config.base_image == "python:3.12-slim"
        assert config.packages == []
        assert config.setup_commands == []
        assert config.env_vars == {}

    def test_create_with_all_parameters(self):
        """Test creating RuntimeConfig with all parameters."""
        config = RuntimeConfig(
            name="custom-ml",
            base_image="python:3.11-slim",
            packages=["torch", "numpy"],
            setup_commands=["pip install --upgrade pip"],
            env_vars={"CUDA_VISIBLE_DEVICES": "0"},
        )
        assert config.name == "custom-ml"
        assert config.base_image == "python:3.11-slim"
        assert config.packages == ["torch", "numpy"]
        assert config.setup_commands == ["pip install --upgrade pip"]
        assert config.env_vars == {"CUDA_VISIBLE_DEVICES": "0"}

    def test_to_pydantic_runtime(self):
        """Test conversion to pydantic-ai-backend RuntimeConfig."""
        config = RuntimeConfig(
            name="test",
            base_image="python:3.12",
            packages=["requests"],
        )
        # to_pydantic_runtime returns self if pydantic RuntimeConfig is not available
        result = config.to_pydantic_runtime()
        # Should either return the same config or a PydanticRuntimeConfig
        assert hasattr(result, "name")
        assert result.name == "test"


class TestBuiltinRuntimes:
    """Tests for BUILTIN_RUNTIMES and related functions."""

    def test_builtin_runtimes_exist(self):
        """Test that BUILTIN_RUNTIMES dictionary is populated."""
        assert len(BUILTIN_RUNTIMES) > 0
        assert "python-minimal" in BUILTIN_RUNTIMES
        assert "python-datascience" in BUILTIN_RUNTIMES
        assert "python-web" in BUILTIN_RUNTIMES

    def test_python_minimal_runtime(self):
        """Test python-minimal runtime configuration."""
        runtime = BUILTIN_RUNTIMES["python-minimal"]
        assert runtime.name == "python-minimal"
        assert runtime.base_image == "python:3.12-slim"
        assert runtime.packages == []

    def test_python_datascience_runtime(self):
        """Test python-datascience runtime configuration."""
        runtime = BUILTIN_RUNTIMES["python-datascience"]
        assert runtime.name == "python-datascience"
        assert "pandas" in runtime.packages
        assert "numpy" in runtime.packages
        assert "matplotlib" in runtime.packages
        assert "scikit-learn" in runtime.packages

    def test_python_web_runtime(self):
        """Test python-web runtime configuration."""
        runtime = BUILTIN_RUNTIMES["python-web"]
        assert runtime.name == "python-web"
        assert "fastapi" in runtime.packages
        assert "uvicorn" in runtime.packages
        assert "httpx" in runtime.packages

    def test_python_ml_runtime(self):
        """Test python-ml runtime configuration."""
        runtime = BUILTIN_RUNTIMES["python-ml"]
        assert runtime.name == "python-ml"
        assert "torch" in runtime.packages
        assert "transformers" in runtime.packages

    def test_node_minimal_runtime(self):
        """Test node-minimal runtime configuration."""
        runtime = BUILTIN_RUNTIMES["node-minimal"]
        assert runtime.name == "node-minimal"
        assert runtime.base_image == "node:20-slim"
        assert runtime.packages == []

    def test_node_react_runtime(self):
        """Test node-react runtime configuration."""
        runtime = BUILTIN_RUNTIMES["node-react"]
        assert runtime.name == "node-react"
        assert runtime.base_image == "node:20-slim"
        assert "react" in runtime.packages
        assert "typescript" in runtime.packages

    def test_get_builtin_runtime_exists(self):
        """Test get_builtin_runtime with existing runtime."""
        runtime = get_builtin_runtime("python-datascience")
        assert runtime is not None
        assert runtime.name == "python-datascience"

    def test_get_builtin_runtime_not_exists(self):
        """Test get_builtin_runtime with non-existing runtime."""
        runtime = get_builtin_runtime("non-existent")
        assert runtime is None

    def test_list_builtin_runtimes(self):
        """Test list_builtin_runtimes function."""
        runtimes = list_builtin_runtimes()
        assert isinstance(runtimes, list)
        assert "python-minimal" in runtimes
        assert "python-datascience" in runtimes
        assert "python-web" in runtimes
        assert "python-ml" in runtimes
        assert "node-minimal" in runtimes
        assert "node-react" in runtimes


class TestResolveRuntime:
    """Tests for resolve_runtime function."""

    def test_resolve_none_runtime(self):
        """Test resolving None runtime uses default image."""
        image, config = resolve_runtime(
            "python:3.12-slim",
            None,
        )
        assert image == "python:3.12-slim"
        assert config is None

    def test_resolve_builtin_runtime_string(self):
        """Test resolving builtin runtime by name."""
        image, config = resolve_runtime(
            "default:image",
            "python-datascience",
        )
        assert image == "python:3.12-slim"
        assert config is not None
        assert config.name == "python-datascience"
        assert "pandas" in config.packages

    def test_resolve_image_string_with_colon(self):
        """Test resolving image string (contains ':')."""
        image, config = resolve_runtime(
            "default:image",
            "custom/image:v1.0",
        )
        assert image == "custom/image:v1.0"
        assert config is None

    def test_resolve_image_string_with_slash(self):
        """Test resolving image string (contains '/')."""
        image, config = resolve_runtime(
            "default:image",
            "docker.io/library/python",
        )
        assert image == "docker.io/library/python"
        assert config is None

    def test_resolve_custom_runtime_config(self):
        """Test resolving custom RuntimeConfig instance."""
        custom_config = RuntimeConfig(
            name="custom",
            base_image="python:3.11",
            packages=["custom-package"],
        )
        image, config = resolve_runtime(
            "default:image",
            custom_config,
        )
        assert image == "python:3.11"
        assert config is not None
        assert config.name == "custom"
        assert "custom-package" in config.packages

    def test_resolve_unknown_string_as_image(self):
        """Test resolving unknown string (not builtin, no special chars)."""
        image, config = resolve_runtime(
            "default:image",
            "unknown-runtime",
        )
        # Should treat as image name (with warning logged)
        assert image == "unknown-runtime"
        assert config is None


class TestPydanticSandboxAdapterInit:
    """Tests for PydanticSandboxAdapter initialization (without Docker).

    These tests verify constructor parameter handling without actually
    creating Docker containers.
    """

    def test_import_error_without_backend(self):
        """Test ImportError is raised when pydantic-ai-backend is not available."""
        pytest.skip("pydantic-ai-backend[docker] 是必选依赖；不再覆盖缺失依赖的分支测试")


class TestPydanticSandboxAdapterProperties:
    """Tests for PydanticSandboxAdapter instance properties.

    These tests use mocking to avoid creating actual Docker containers.
    """

    @pytest.fixture
    def mock_docker_sandbox(self, monkeypatch):
        """Mock DockerSandbox to avoid creating actual containers."""
        from unittest.mock import MagicMock

        mock_sandbox = MagicMock()
        mock_sandbox.start = MagicMock()
        mock_sandbox.stop = MagicMock()
        monkeypatch.setattr(
            "app.core.agent.backends.pydantic_adapter.DockerSandbox",
            MagicMock(return_value=mock_sandbox),
        )
        return mock_sandbox

    def test_adapter_stores_runtime_config(self, mock_docker_sandbox):
        """Test that adapter stores runtime configuration."""
        adapter = PydanticSandboxAdapter(runtime="python-datascience")
        config = adapter.get_runtime_config()
        assert config is not None
        assert config.name == "python-datascience"

    def test_adapter_stores_session_id(self, mock_docker_sandbox):
        """Test that adapter stores session_id."""
        adapter = PydanticSandboxAdapter(session_id="test-session-123")
        assert adapter.session_id == "test-session-123"
        assert adapter.id == "test-session-123"

    def test_adapter_stores_idle_timeout(self, mock_docker_sandbox):
        """Test that adapter stores idle_timeout."""
        adapter = PydanticSandboxAdapter(idle_timeout=1800)
        assert adapter.idle_timeout == 1800

    def test_adapter_stores_volumes(self, mock_docker_sandbox):
        """Test that adapter stores volumes."""
        volumes = {"/host/data": "/container/data"}
        adapter = PydanticSandboxAdapter(volumes=volumes)
        assert adapter.volumes == volumes

    def test_adapter_image_from_runtime(self, mock_docker_sandbox):
        """Test that adapter uses image from runtime config."""
        adapter = PydanticSandboxAdapter(runtime="node-minimal")
        assert adapter.image == "node:20-slim"


class TestPydanticSandboxAdapterFileOps:
    """Tests for PydanticSandboxAdapter file operations.

    These tests verify that read/write/edit methods properly delegate
    to the upstream DockerSandbox methods.
    """

    @pytest.fixture
    def adapter_with_mock(self, monkeypatch):
        """Create adapter with mocked DockerSandbox."""
        from unittest.mock import MagicMock

        mock_sandbox = MagicMock()
        mock_sandbox.start = MagicMock()
        mock_sandbox.stop = MagicMock()

        # Mock execute for file existence check (file doesn't exist by default)
        mock_sandbox.execute = MagicMock(return_value=MagicMock(output="", exit_code=1))

        # Patch DockerSandbox constructor
        monkeypatch.setattr(
            "app.core.agent.backends.pydantic_adapter.DockerSandbox",
            MagicMock(return_value=mock_sandbox),
        )

        adapter = PydanticSandboxAdapter()
        return adapter, mock_sandbox

    def test_read_delegates_to_sandbox(self, adapter_with_mock):
        """Test that read() delegates to self._sandbox.read()."""
        adapter, mock_sandbox = adapter_with_mock
        mock_sandbox.read = lambda path, offset, limit: "line1\nline2\nline3"

        result = adapter.read("/workspace/test.txt", offset=0, limit=10)

        # Should return formatted content with line numbers
        assert "line1" in result
        assert "line2" in result

    def test_read_handles_error_from_sandbox(self, adapter_with_mock):
        """Test that read() handles errors from upstream."""
        adapter, mock_sandbox = adapter_with_mock
        mock_sandbox.read = lambda path, offset, limit: "[Error: File not found]"

        result = adapter.read("/workspace/nonexistent.txt")

        assert "Error" in result

    def test_write_delegates_to_sandbox(self, adapter_with_mock):
        """Test that write() delegates to self._sandbox.write()."""
        from unittest.mock import MagicMock

        adapter, mock_sandbox = adapter_with_mock
        mock_write_result = MagicMock(error=None, path="/workspace/test.txt")
        mock_sandbox.write = MagicMock(return_value=mock_write_result)

        result = adapter.write("/workspace/test.txt", "content")

        mock_sandbox.write.assert_called_once_with("/workspace/test.txt", "content")
        assert result.path == "/workspace/test.txt"
        assert result.error is None

    def test_write_prevents_overwrite_existing(self, adapter_with_mock):
        """Test that write() prevents overwriting existing files."""
        from unittest.mock import MagicMock

        adapter, mock_sandbox = adapter_with_mock
        # Simulate file exists (exit_code=0)
        mock_sandbox.execute = MagicMock(return_value=MagicMock(output="", exit_code=0))

        result = adapter.write("/workspace/existing.txt", "new content")

        assert result.error is not None
        assert "already exists" in result.error

    def test_write_overwrite_delegates_to_sandbox(self, adapter_with_mock):
        """Test that write_overwrite() delegates to self._sandbox.write()."""
        from unittest.mock import MagicMock

        adapter, mock_sandbox = adapter_with_mock
        mock_write_result = MagicMock(error=None, path="/workspace/test.txt")
        mock_sandbox.write = MagicMock(return_value=mock_write_result)

        result = adapter.write_overwrite("/workspace/test.txt", "new content")

        mock_sandbox.write.assert_called_once_with("/workspace/test.txt", "new content")
        assert result.path == "/workspace/test.txt"
        assert result.error is None

    def test_edit_delegates_to_sandbox(self, adapter_with_mock):
        """Test that edit() delegates to self._sandbox.edit()."""
        from unittest.mock import MagicMock

        adapter, mock_sandbox = adapter_with_mock
        mock_edit_result = MagicMock(error=None, path="/workspace/test.txt", occurrences=2)
        mock_sandbox.edit = MagicMock(return_value=mock_edit_result)

        result = adapter.edit("/workspace/test.txt", "old", "new", replace_all=True)

        mock_sandbox.edit.assert_called_once_with("/workspace/test.txt", "old", "new", True)
        assert result.path == "/workspace/test.txt"
        assert result.occurrences == 2
        assert result.error is None

    def test_edit_handles_error_from_sandbox(self, adapter_with_mock):
        """Test that edit() handles errors from upstream."""
        from unittest.mock import MagicMock

        adapter, mock_sandbox = adapter_with_mock
        mock_edit_result = MagicMock(error="String not found")
        mock_sandbox.edit = MagicMock(return_value=mock_edit_result)

        result = adapter.edit("/workspace/test.txt", "not found", "new")

        assert result.error == "String not found"

    def test_write_handles_special_characters(self, adapter_with_mock):
        """Test that write() handles special characters in content."""
        from unittest.mock import MagicMock

        adapter, mock_sandbox = adapter_with_mock
        mock_write_result = MagicMock(error=None, path="/workspace/test.txt")
        mock_sandbox.write = MagicMock(return_value=mock_write_result)

        # Content with special characters that would break shell commands
        special_content = "echo 'hello'\n$VAR\n`command`\n\"quotes\"\n!#$%&"

        result = adapter.write("/workspace/test.txt", special_content)

        # Should delegate to upstream without modification
        mock_sandbox.write.assert_called_once_with("/workspace/test.txt", special_content)
        assert result.error is None

    def test_write_handles_large_content(self, adapter_with_mock):
        """Test that write() handles large content (> 1MB)."""
        from unittest.mock import MagicMock

        adapter, mock_sandbox = adapter_with_mock
        mock_write_result = MagicMock(error=None, path="/workspace/large.txt")
        mock_sandbox.write = MagicMock(return_value=mock_write_result)

        # Large content (1.5 MB) - would fail with base64+echo approach
        large_content = "x" * (1024 * 1024 + 500000)  # 1.5 MB

        result = adapter.write("/workspace/large.txt", large_content)

        # Should delegate to upstream without size issues
        mock_sandbox.write.assert_called_once()
        assert result.error is None


class TestSandboxFactoryDockerSandbox:
    """Tests for create_docker_sandbox factory function."""

    def test_import_create_docker_sandbox(self):
        """Test that create_docker_sandbox can be imported."""
        from app.core.tools.sandbox.sandbox_factory import create_docker_sandbox

        assert callable(create_docker_sandbox)

    def test_docker_in_sandbox_providers(self):
        """Test that docker is in sandbox providers."""
        from app.core.tools.sandbox.sandbox_factory import get_available_sandbox_types

        types = get_available_sandbox_types()
        assert "docker" in types

    def test_docker_working_dir(self):
        """Test that docker working dir is /workspace."""
        from app.core.tools.sandbox.sandbox_factory import get_default_working_dir

        assert get_default_working_dir("docker") == "/workspace"

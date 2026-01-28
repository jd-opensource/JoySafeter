"""
Custom exception classes for Docker management system
"""


class DockerException(Exception):
    """Base exception for Docker operations"""

    pass


class DockerConnectionError(DockerException):
    """Docker connection error"""

    pass


class ContainerCreationError(DockerException):
    """Container creation failed"""

    pass


class ContainerExecutionError(DockerException):
    """Container execution failed"""

    pass


class ResourceLimitError(DockerException):
    """Resource limit configuration error"""

    pass


class ResourceMonitorError(DockerException):
    """Resource monitoring error"""

    pass


class ContainerNotFoundError(DockerException):
    """Container not found"""

    pass


class ContainerStateError(DockerException):
    """Container state error"""

    pass

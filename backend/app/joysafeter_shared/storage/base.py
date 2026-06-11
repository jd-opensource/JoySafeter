from typing import Protocol, runtime_checkable


@runtime_checkable
class StorageBackend(Protocol):
    """Abstract storage interface. Supports local filesystem and S3-compatible backends."""

    async def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
        """Store data at the given key."""
        ...

    async def get(self, key: str) -> bytes:
        """Retrieve data by key. Raises FileNotFoundError if not found."""
        ...

    async def delete(self, key: str) -> None:
        """Delete data at key. No-op if not found."""
        ...

    async def exists(self, key: str) -> bool:
        """Check if key exists."""
        ...

    async def presign_url(self, key: str, expires: int = 3600) -> str | None:
        """Generate a presigned download URL. Returns None if not supported."""
        ...

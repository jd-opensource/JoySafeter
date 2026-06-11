import os
from pathlib import Path

import aiofiles
import aiofiles.os


class LocalBackend:
    """Local filesystem storage backend. Suitable for single-node / Docker volume deployments."""

    def __init__(self, base_path: str):
        self._base = Path(base_path)
        self._base.mkdir(parents=True, exist_ok=True)

    def _resolve(self, key: str) -> Path:
        base_resolved = self._base.resolve()
        resolved = (self._base / key).resolve()
        if resolved != base_resolved and not str(resolved).startswith(str(base_resolved) + "/"):
            raise ValueError(f"path traversal detected: {key}")
        return resolved

    async def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
        path = self._resolve(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        async with aiofiles.open(path, "wb") as f:
            await f.write(data)

    async def get(self, key: str) -> bytes:
        path = self._resolve(key)
        if not path.exists():
            raise FileNotFoundError(f"file not found: {key}")
        async with aiofiles.open(path, "rb") as f:
            return await f.read()

    async def delete(self, key: str) -> None:
        path = self._resolve(key)
        if path.exists():
            await aiofiles.os.remove(path)

    async def exists(self, key: str) -> bool:
        return self._resolve(key).exists()

    async def presign_url(self, key: str, expires: int = 3600) -> str | None:
        return None

"""
Storage abstraction layer.

Supports local filesystem and S3-compatible backends (MinIO, AWS S3, Aliyun OSS S3-compatible endpoint).
Configuration via environment variables:

  STORAGE_BACKEND=local|s3|oss  (default: local)

  # local backend
  STORAGE_LOCAL_PATH=/data/files

  # s3 backend
  STORAGE_S3_ENDPOINT=http://minio:9000
  STORAGE_S3_BUCKET=joysafeter-files
  STORAGE_S3_ACCESS_KEY=minioadmin
  STORAGE_S3_SECRET_KEY=minioadmin
  STORAGE_S3_REGION=us-east-1
"""

import os

from app.joysafeter_shared.storage.base import StorageBackend
from app.joysafeter_shared.storage.local import LocalBackend

__all__ = ["StorageBackend", "LocalBackend", "create_storage", "get_storage"]

_instance: StorageBackend | None = None


def create_storage() -> StorageBackend:
    """Create storage backend based on environment configuration."""
    backend_type = os.getenv("STORAGE_BACKEND", "local").lower()

    if backend_type in {"s3", "oss"}:
        from app.joysafeter_shared.storage.s3 import S3Backend
        bucket = os.getenv("STORAGE_S3_BUCKET") or os.getenv("STORAGE_OSS_BUCKET")
        endpoint_url = os.getenv("STORAGE_S3_ENDPOINT") or os.getenv("STORAGE_OSS_ENDPOINT")
        access_key = os.getenv("STORAGE_S3_ACCESS_KEY") or os.getenv("STORAGE_OSS_ACCESS_KEY")
        secret_key = os.getenv("STORAGE_S3_SECRET_KEY") or os.getenv("STORAGE_OSS_SECRET_KEY")
        region = os.getenv("STORAGE_S3_REGION") or os.getenv("STORAGE_OSS_REGION") or "us-east-1"
        if not bucket:
            raise RuntimeError("STORAGE_S3_BUCKET or STORAGE_OSS_BUCKET is required for object storage")
        if not access_key or not secret_key:
            raise RuntimeError("Storage access key and secret key are required for object storage")
        return S3Backend(
            bucket=bucket,
            endpoint_url=endpoint_url,
            access_key=access_key,
            secret_key=secret_key,
            region=region,
        )

    if backend_type != "local":
        raise RuntimeError(
            "Unsupported STORAGE_BACKEND=%r. Expected local, s3, or oss." % backend_type
        )

    return LocalBackend(
        base_path=os.getenv("STORAGE_LOCAL_PATH", "data/files"),
    )


def get_storage() -> StorageBackend:
    """Get or create the singleton storage backend instance."""
    global _instance
    if _instance is None:
        _instance = create_storage()
    return _instance

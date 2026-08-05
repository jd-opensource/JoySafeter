from __future__ import annotations

import aioboto3
from botocore.config import Config


class S3Backend:
    """S3-compatible storage backend. Works with AWS S3, MinIO, etc."""

    def __init__(
        self,
        bucket: str,
        endpoint_url: str | None = None,
        access_key: str | None = None,
        secret_key: str | None = None,
        region: str = "us-east-1",
    ):
        self._bucket = bucket
        self._endpoint_url = endpoint_url
        self._region = region
        self._session = aioboto3.Session(
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region,
        )
        self._config = Config(signature_version="s3v4")

    def _client(self):
        return self._session.client(
            "s3",
            endpoint_url=self._endpoint_url,
            config=self._config,
        )

    async def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
        async with self._client() as s3:
            await s3.put_object(
                Bucket=self._bucket,
                Key=key,
                Body=data,
                ContentType=content_type,
            )

    async def get(self, key: str) -> bytes:
        async with self._client() as s3:
            try:
                resp = await s3.get_object(Bucket=self._bucket, Key=key)
                data: bytes = await resp["Body"].read()
                return data
            except s3.exceptions.NoSuchKey:
                raise FileNotFoundError(f"file not found: {key}")
            except Exception as e:
                if "NoSuchKey" in str(e) or "404" in str(e):
                    raise FileNotFoundError(f"file not found: {key}")
                raise

    async def delete(self, key: str) -> None:
        async with self._client() as s3:
            await s3.delete_object(Bucket=self._bucket, Key=key)

    async def exists(self, key: str) -> bool:
        async with self._client() as s3:
            try:
                await s3.head_object(Bucket=self._bucket, Key=key)
                return True
            except Exception:
                return False

    async def presign_url(self, key: str, expires: int = 3600) -> str | None:
        async with self._client() as s3:
            url: str = await s3.generate_presigned_url(
                "get_object",
                Params={"Bucket": self._bucket, "Key": key},
                ExpiresIn=expires,
            )
            return url

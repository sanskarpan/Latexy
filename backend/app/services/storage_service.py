"""
MinIO / S3-compatible storage service.

Wraps boto3 for uploading, downloading, and checking objects in the configured bucket.
Uses a module-level singleton client to avoid per-request client creation overhead.
"""

import threading

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from ..core.config import settings
from ..core.logging import get_logger

logger = get_logger(__name__)

_client = None
_client_lock = threading.Lock()


def _get_client():
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                _client = boto3.client(
                    "s3",
                    endpoint_url=settings.MINIO_ENDPOINT,
                    aws_access_key_id=settings.MINIO_ACCESS_KEY,
                    aws_secret_access_key=settings.MINIO_SECRET_KEY,
                    region_name="us-east-1",
                    config=Config(
                        connect_timeout=5,
                        read_timeout=15,
                        retries={"max_attempts": 3, "mode": "standard"},
                    ),
                )
    return _client


def upload_bytes(key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
    """Upload raw bytes to the configured bucket."""
    client = _get_client()
    client.put_object(
        Bucket=settings.MINIO_BUCKET,
        Key=key,
        Body=data,
        ContentType=content_type,
    )
    logger.info(f"Uploaded {key} ({len(data)} bytes)")


def download_bytes(key: str) -> bytes | None:
    """Download an object from the bucket. Returns None if not found."""
    client = _get_client()
    try:
        response = client.get_object(Bucket=settings.MINIO_BUCKET, Key=key)
        return response["Body"].read()
    except ClientError as e:
        if e.response["Error"]["Code"] == "NoSuchKey":
            return None
        raise


def file_exists(key: str) -> bool:
    """Check whether an object exists in the bucket."""
    client = _get_client()
    try:
        client.head_object(Bucket=settings.MINIO_BUCKET, Key=key)
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] in ("404", "NoSuchKey"):
            return False
        raise


def generate_presigned_url(key: str, ttl: int = 3600) -> str:
    """Generate a presigned GET URL for an object (default 1-hour TTL)."""
    client = _get_client()
    return client.generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.MINIO_BUCKET, "Key": key},
        ExpiresIn=ttl,
    )

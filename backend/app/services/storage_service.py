"""
MinIO / S3-compatible storage service.

Wraps boto3 for uploading, downloading, and checking objects in the configured bucket.
Uses a module-level singleton client to avoid per-request client creation overhead.
"""

import threading
import time

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


def list_objects(prefix: str, max_keys: int = 1000) -> list[dict]:
    """
    List objects under a prefix. Returns dicts with "key", "size" and "last_modified".

    Paginated so callers see every object, not just the first page.
    """
    client = _get_client()
    paginator = client.get_paginator("list_objects_v2")
    objects: list[dict] = []
    for page in paginator.paginate(
        Bucket=settings.MINIO_BUCKET,
        Prefix=prefix,
        PaginationConfig={"MaxItems": max_keys},
    ):
        for obj in page.get("Contents", []):
            objects.append({
                "key": obj["Key"],
                "size": obj.get("Size", 0),
                "last_modified": obj.get("LastModified"),
            })
    return objects


def delete_object(key: str) -> bool:
    """Delete an object. Returns False (without raising) if it does not exist."""
    client = _get_client()
    try:
        client.delete_object(Bucket=settings.MINIO_BUCKET, Key=key)
        logger.info(f"Deleted {key}")
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


_probe_client = None


def _get_probe_client():
    """
    A separate client for health probing: fast, and no retries.

    The shared client is tuned for real transfers — connect_timeout=5 with 3
    retries. Reusing it here measured **24s** against a black-holed endpoint and
    1.7s against a refused one, which would have turned a storage outage into a
    /health outage: the TUI polls health every 30s and Modal probes it on a
    schedule. A probe is allowed to be wrong under load; it is not allowed to hang.
    """
    global _probe_client
    if _probe_client is None:
        with _client_lock:
            if _probe_client is None:
                _probe_client = boto3.client(
                    "s3",
                    endpoint_url=settings.MINIO_ENDPOINT,
                    aws_access_key_id=settings.MINIO_ACCESS_KEY,
                    aws_secret_access_key=settings.MINIO_SECRET_KEY,
                    region_name="us-east-1",
                    config=Config(
                        connect_timeout=2,
                        read_timeout=2,
                        retries={"max_attempts": 1, "mode": "standard"},
                    ),
                )
    return _probe_client


_probe_cache: tuple[float, bool, str] | None = None
_PROBE_TTL = 30.0


def probe() -> tuple[bool, str]:
    """
    Cheap reachability check for the health endpoint.

    Object storage was the one backing service /health did not probe, so the
    endpoint reported {"status": "healthy"} in production while every template
    thumbnail and preview PDF returned 502 Storage unavailable — 0 of 147 served.
    The outage was invisible to anything watching health.

    HeadBucket is the lightest call that proves both connectivity and credentials.
    Returns (ok, detail) rather than raising, so a health check can degrade
    gracefully instead of failing.
    """
    global _probe_cache
    now = time.monotonic()
    if _probe_cache is not None and now - _probe_cache[0] < _PROBE_TTL:
        # /health is polled roughly every 30s by the TUI and on a schedule by
        # Modal. Without this, a down endpoint costs ~4s on every single call.
        return _probe_cache[1], _probe_cache[2]

    try:
        _get_probe_client().head_bucket(Bucket=settings.MINIO_BUCKET)
        result = (True, "ok")
    except Exception as exc:                     # noqa: BLE001 — any failure is "unavailable"
        result = (False, type(exc).__name__)

    _probe_cache = (now, result[0], result[1])
    return result

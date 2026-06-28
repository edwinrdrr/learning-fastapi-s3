"""The S3 storage layer — the only file that knows about boto3.

Keeping all object-store calls here (instead of scattering boto3 through your
endpoints) is good design: if you later swap S3 for GCS, or add caching, you
change one file. Your endpoints just call put_json/get_json/list_keys/etc.

Mental model for S3:
  - A *bucket* is a namespace (like "readings").
  - An *object* is one file, identified by its *key* (a string path like
    "readings/sensor-001/2026-06-26/<uuid>.json").
  - There are no real folders — the "/" in a key is just a convention, and
    listing by *prefix* is how you query a slice of the data ("partitioning").
"""
import json
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from app.config import settings

# One shared S3 client. boto3 is thread-safe for clients.
# Timeouts + bounded retries so a slow/flaky S3 can't hang a worker indefinitely.
_config = Config(
    signature_version="s3v4",
    connect_timeout=5,
    read_timeout=30,
    retries={"max_attempts": 3, "mode": "adaptive"},
)
# Only pass endpoint/credentials when explicitly configured; otherwise boto3 uses
# its default credential chain (env vars, ~/.aws, or an IAM role) — the right
# choice on AWS.
_client_kwargs: dict[str, Any] = {"region_name": settings.aws_region, "config": _config}
if settings.s3_endpoint_url:
    _client_kwargs["endpoint_url"] = settings.s3_endpoint_url
if settings.aws_access_key_id and settings.aws_secret_access_key:
    _client_kwargs["aws_access_key_id"] = settings.aws_access_key_id
    _client_kwargs["aws_secret_access_key"] = settings.aws_secret_access_key

_s3 = boto3.client("s3", **_client_kwargs)

BUCKET = settings.s3_bucket


def ensure_bucket() -> None:
    """Create the bucket if it doesn't exist. Called once on startup.
    (On real AWS you'd usually create buckets via Terraform/console instead.)"""
    try:
        _s3.head_bucket(Bucket=BUCKET)
    except ClientError:
        _s3.create_bucket(Bucket=BUCKET)


def ping() -> None:
    """Cheap reachability check for the health endpoint."""
    _s3.head_bucket(Bucket=BUCKET)


def put_json(key: str, data: dict[str, Any]) -> None:
    """Write one JSON object to S3 at `key`."""
    _s3.put_object(
        Bucket=BUCKET,
        Key=key,
        Body=json.dumps(data).encode("utf-8"),
        ContentType="application/json",
    )


def get_json(key: str) -> dict[str, Any] | None:
    """Read and parse one JSON object. Returns None if the key doesn't exist."""
    try:
        resp = _s3.get_object(Bucket=BUCKET, Key=key)
    except ClientError as e:
        if e.response["Error"]["Code"] in ("NoSuchKey", "404"):
            return None
        raise
    return json.loads(resp["Body"].read())


def list_keys(prefix: str = "", limit: int = 1000) -> list[str]:
    """List object keys under a prefix. Prefix-based listing is how you 'query'
    a data lake without a database. The paginator handles >1000 objects."""
    keys: list[str] = []
    paginator = _s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=BUCKET, Prefix=prefix):
        for obj in page.get("Contents", []):
            keys.append(obj["Key"])
            if len(keys) >= limit:
                return keys
    return keys


def delete_key(key: str) -> bool:
    """Delete one object. Returns False if it wasn't there."""
    if get_json(key) is None:
        return False
    _s3.delete_object(Bucket=BUCKET, Key=key)
    return True


# --- Raw byte helpers (used for non-JSON objects like Parquet files) ---

def put_bytes(key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
    """Write arbitrary bytes (e.g. a Parquet file) to S3."""
    _s3.put_object(Bucket=BUCKET, Key=key, Body=data, ContentType=content_type)


def get_bytes(key: str) -> bytes | None:
    """Read raw bytes. Returns None if the key doesn't exist."""
    try:
        resp = _s3.get_object(Bucket=BUCKET, Key=key)
    except ClientError as e:
        if e.response["Error"]["Code"] in ("NoSuchKey", "404"):
            return None
        raise
    return resp["Body"].read()


def exists(key: str) -> bool:
    """True if an object exists at `key` — a cheap HEAD, no body transferred."""
    try:
        _s3.head_object(Bucket=BUCKET, Key=key)
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] in ("NoSuchKey", "NoSuchBucket", "404"):
            return False
        raise

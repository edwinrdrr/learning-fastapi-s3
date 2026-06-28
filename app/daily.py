"""Daily-dataset layer: query processed Parquet directly in S3 with DuckDB.

The API is a read-only consumer. A separate upstream writes
  processed/scrape/dt=YYYY-MM-DD/data.parquet
to S3; we query it IN PLACE with DuckDB's httpfs extension (HTTP range reads),
pushing column projection + LIMIT/OFFSET into the scan. Nothing is downloaded
whole and nothing is cached on local disk — so the read path is fully stateless
and works unchanged on serverless runtimes (e.g. Lambda), where a local cache
would not survive between cold starts.

DuckDB serializes results to JSON in C++ (COPY ... FORMAT JSON); the router
streams those bytes back to the client.
"""
import os
import tempfile
import threading
from typing import Any
from urllib.parse import urlparse

import duckdb

from app import storage
from app.config import settings


def _parquet_key(day: str) -> str:
    """S3 key for a day's processed Parquet (what the API reads)."""
    return f"processed/scrape/dt={day}/data.parquet"


def _s3_uri(day: str) -> str:
    return f"s3://{settings.s3_bucket}/{_parquet_key(day)}"


def _read_parquet(day: str) -> str:
    """A read_parquet(...) source for a day's S3 object.

    hive_partitioning=false: the key sits under a `dt=YYYY-MM-DD/` path, which
    DuckDB would otherwise auto-detect as a Hive partition and inject as a spurious
    `dt` column. We read the file faithfully — only the columns the producer wrote.
    """
    return f"read_parquet('{_s3_uri(day)}', hive_partitioning=false)"


# DuckDB connections are NOT safe to share across threads, and FastAPI runs sync
# endpoints in a threadpool. Give each thread its own connection, configured once
# with httpfs + an S3 secret derived from our settings (same creds boto3 uses).
_local = threading.local()


def _s3_secret_sql() -> str:
    """Build a DuckDB S3 secret from the same config boto3 uses."""
    if settings.s3_endpoint_url:
        # Custom endpoint (e.g. MinIO): explicit static keys, path-style addressing.
        netloc = urlparse(settings.s3_endpoint_url).netloc
        use_ssl = "true" if settings.s3_endpoint_url.startswith("https") else "false"
        return (
            "CREATE OR REPLACE SECRET s3secret (TYPE S3,"
            f" KEY_ID '{settings.aws_access_key_id}',"
            f" SECRET '{settings.aws_secret_access_key}',"
            f" REGION '{settings.aws_region}',"
            f" ENDPOINT '{netloc}', URL_STYLE 'path', USE_SSL {use_ssl})"
        )
    # Real AWS: no endpoint / no static keys -> use the default credential chain
    # (env, ~/.aws, or the Lambda/instance IAM role) via the aws extension.
    return (
        "CREATE OR REPLACE SECRET s3secret"
        f" (TYPE S3, PROVIDER credential_chain, REGION '{settings.aws_region}')"
    )


def _conn() -> duckdb.DuckDBPyConnection:
    """Per-thread DuckDB connection, configured for S3 access on first use."""
    con = getattr(_local, "con", None)
    if con is None:
        con = duckdb.connect()
        con.execute("INSTALL httpfs; LOAD httpfs;")
        if not settings.s3_endpoint_url:
            con.execute("INSTALL aws; LOAD aws;")
        con.execute(_s3_secret_sql())
        _local.con = con
    return con


def meta(day: str) -> dict[str, Any] | None:
    """Row count + column names for a day, without shipping the rows.

    Returns None if that day hasn't been written to S3 yet (router -> 404).
    Cheap: count + schema come from the Parquet footer, not a full scan.
    """
    if not storage.exists(_parquet_key(day)):
        return None
    con = _conn()
    src = _read_parquet(day)
    rows = con.execute(f"SELECT count(*) FROM {src}").fetchone()[0]
    cur = con.execute(f"SELECT * FROM {src} LIMIT 0")
    columns = [d[0] for d in cur.description]
    return {"day": day, "rows": int(rows), "columns": columns}


def export_json(
    day: str,
    columns: list[str] | None = None,
    limit: int | None = None,
    offset: int = 0,
) -> str | None:
    """Write one page of the day to a temp JSON-array file and return its path.

    DuckDB reads only the requested rows/columns straight from S3 (range reads)
    and serializes to JSON in C++. Returns None if the day doesn't exist; the
    CALLER is responsible for deleting the returned temp file when done.

    `columns` -> column pushdown; `limit`/`offset` -> pagination pushed into SQL.
    """
    if not storage.exists(_parquet_key(day)):
        return None

    # "*" when no projection requested. If a caller ever passes columns (not
    # user-exposed today), only allow plain identifiers and quote them — defends
    # against identifier injection if a `fields` query param is added later.
    if not columns:
        select = "*"
    else:
        for c in columns:
            if not c.replace("_", "").isalnum():
                raise ValueError(f"invalid column name: {c!r}")
        select = ", ".join(f'"{c}"' for c in columns)
    page = f" LIMIT {int(limit)} OFFSET {int(offset)}" if limit is not None else ""

    fd, out_path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    con = _conn()
    # ARRAY true => a single valid JSON array (not newline-delimited).
    con.execute(
        f"COPY (SELECT {select} FROM {_read_parquet(day)}{page}) "
        f"TO '{out_path}' (FORMAT JSON, ARRAY true)"
    )
    return out_path

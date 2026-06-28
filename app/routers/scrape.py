"""Daily scrape dataset: READ-ONLY API over the processed Parquet.

This API never writes data — it only consumes. A separate upstream system
produces the processed Parquet and writes it to S3. The API only does GET: it
reads the processed Parquet and serves it as JSON. Endpoints:

  GET /scrape/{day}/meta   row count + column names (cheap)
  GET /scrape/{day}        stream the dataset back as a JSON array (fast)

If a day hasn't been processed yet, reads return 404 — the API doesn't try to
produce the data, that's the job's responsibility.
"""
import os
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Path
from fastapi.responses import StreamingResponse

from app import daily
from app.schemas import DayMeta, ScrapeRecord

router = APIRouter(prefix="/scrape", tags=["scrape"])

_NOT_FOUND = {404: {"description": "That day has not been scraped/processed yet"}}


def valid_day(
    day: str = Path(..., pattern=r"^\d{4}-\d{2}-\d{2}$",
                    description="Scrape date (YYYY-MM-DD)", examples=["2026-03-15"]),
) -> str:
    """Validate the day path param.

    SECURITY: `day` is interpolated into the S3 key and the DuckDB SQL (DuckDB's
    read_parquet path must be a literal — it can't be a bound parameter), so we
    constrain it to a real calendar date here. The regex blocks the shape and
    this check rejects impossible dates (e.g. 2026-02-30) — together they prevent
    SQL/path injection via the URL.
    """
    try:
        date.fromisoformat(day)
    except ValueError:
        raise HTTPException(status_code=422, detail="day must be a valid date (YYYY-MM-DD)")
    return day


# --- Metadata: count + columns without shipping the data ---
@router.get(
    "/{day}/meta",
    response_model=DayMeta,
    summary="Get metadata for a scrape day",
    description=(
        "Returns the row count and column names for one day **without** "
        "downloading the rows. Use it to size your pagination."
    ),
    responses=_NOT_FOUND,
)
def day_meta(day: str = Depends(valid_day)) -> dict:
    info = daily.meta(day)
    if info is None:
        raise HTTPException(status_code=404, detail=f"No data for day {day}")
    return info


# --- Read: stream one page of a day's dataset back as a JSON array ---
@router.get(
    "/{day}",
    summary="Get (a page of) a scrape day",
    description=(
        "Returns the day's records as a JSON array. Use `page`/`page_size` to "
        "paginate. An **empty array `[]`** means you've paged past the end of "
        "the day. To fetch many days, request one date at a time (loop client-side)."
    ),
    response_description="A JSON array of scrape records",
    responses={
        200: {"model": list[ScrapeRecord], "description": "A page of scrape records"},
        **_NOT_FOUND,
    },
)
def get_day(
    day: str = Depends(valid_day),
    page: int = Query(1, ge=1, description="1-based page number"),
    page_size: int = Query(
        1000, ge=1, le=5000,
        description="Rows per page (max 5000 to stay within response-size limits)",
    ),
) -> StreamingResponse:
    # page/page_size is the client-facing contract; translate to LIMIT/OFFSET.
    # An empty array ([]) means you've paged past the end of this day.
    offset = (page - 1) * page_size

    # DuckDB serializes the result to a JSON-array file (fast, in C++).
    out_path = daily.export_json(day, limit=page_size, offset=offset)
    if out_path is None:
        raise HTTPException(status_code=404, detail=f"No data for day {day}")

    def generate() -> Any:
        # Stream the file in chunks so memory stays flat regardless of size,
        # and delete the temp file once the response is fully sent.
        try:
            with open(out_path, "rb") as f:
                while chunk := f.read(64 * 1024):
                    yield chunk
        finally:
            os.remove(out_path)

    return StreamingResponse(generate(), media_type="application/json")

"""Scrape config (control-plane) — the UPLOAD side of the API.

Demonstrates the two main upload patterns:
  - Pattern 2 (file upload / multipart): POST /scrape-config/input-table
  - Pattern 1 (JSON body):                POST /scrape-config/{blacklist|whitelist}

These WRITE endpoints are separate from the read-only /scrape data API. They are
protected by the API-key dependency (wired in main.py). The scraper (external)
reads what's stored here; the API just validates and stores it.

For very large input tables you'd prefer a presigned-URL upload (client uploads
straight to S3, bypassing the API) — see learning/11-uploads.md.
"""
from fastapi import APIRouter, Depends, File, HTTPException, Path, UploadFile

from app import scrape_config
from app.schemas import AppendEntries, AppendResult, InputTableMeta, ListState

router = APIRouter(prefix="/scrape-config", tags=["scrape-config"])


async def _read_capped(file: UploadFile, cap: int) -> bytes:
    """Read an upload in chunks, refusing anything larger than `cap` bytes."""
    chunks: list[bytes] = []
    total = 0
    while chunk := await file.read(1024 * 1024):
        total += len(chunk)
        if total > cap:
            raise HTTPException(status_code=413, detail=f"file too large (> {cap} bytes)")
        chunks.append(chunk)
    return b"".join(chunks)


# --- Input table: upload a CSV/JSON file that REPLACES the current one ---
@router.post(
    "/input-table",
    response_model=InputTableMeta,
    status_code=201,
    summary="Upload the scraping input table (replaces the current one)",
    responses={413: {"description": "File too large"}, 422: {"description": "Unparseable / wrong type"}},
)
async def upload_input_table(
    file: UploadFile = File(..., description="CSV or JSON table of items to scrape"),
) -> dict:
    data = await _read_capped(file, scrape_config.MAX_INPUT_BYTES)
    if not data:
        raise HTTPException(status_code=400, detail="empty file")
    try:
        return scrape_config.set_input_table(file.filename or "upload", file.content_type, data)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.get(
    "/input-table",
    response_model=InputTableMeta,
    summary="Get metadata for the current scraping input table",
    responses={404: {"description": "No input table uploaded yet"}},
)
def get_input_table() -> dict:
    meta = scrape_config.get_input_table_meta()
    if meta is None:
        raise HTTPException(status_code=404, detail="no input table uploaded yet")
    return meta


# --- Blacklist / whitelist: APPEND entries via a JSON body ---
def list_name(
    name: str = Path(..., pattern="^(blacklist|whitelist)$",
                     description="Which list", examples=["blacklist"]),
) -> str:
    return name


@router.post(
    "/{name}",
    response_model=AppendResult,
    status_code=201,
    summary="Append entries to the blacklist/whitelist (deduplicated)",
)
def append_entries(payload: AppendEntries, name: str = Depends(list_name)) -> dict:
    result = scrape_config.append_list(name, payload.entries)
    return {"name": name, **result}


@router.get(
    "/{name}",
    response_model=ListState,
    summary="Get the current blacklist/whitelist",
)
def get_entries(name: str = Depends(list_name)) -> dict:
    entries = scrape_config.get_list(name)
    return {"name": name, "count": len(entries), "entries": entries}

"""Endpoints 2-6: ingest and serve readings stored as JSON objects on S3.

Key design = "partitioning": readings/<sensor_id>/<YYYY-MM-DD>/<uuid>.json
That layout lets us list a single sensor, or a single day, cheaply by prefix —
the file-based equivalent of an index. Real data lakes (Hive/Athena/Spark) use
exactly this trick.

API id vs storage key: internally every object's S3 key starts with the
ROOT_PREFIX ("readings/"). We DON'T leak that prefix into the API. The public
"id" a client sees is the part AFTER the prefix (e.g. "sensor-001/2026-06-26/
<uuid>.json"), so URLs read naturally as /readings/<id>. We add the prefix back
before touching S3. Separating the public id from the physical storage path is a
common, healthy API pattern.
"""
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query

from app import storage
from app.schemas import BulkResult, ReadingBulkCreate, ReadingCreate, ReadingOut

router = APIRouter(prefix="/readings", tags=["readings"])

ROOT_PREFIX = "readings/"


def _to_storage_key(reading_id: str) -> str:
    """Public id -> full S3 key."""
    return ROOT_PREFIX + reading_id


def _to_id(storage_key: str) -> str:
    """Full S3 key -> public id (strip the ROOT_PREFIX)."""
    return storage_key.removeprefix(ROOT_PREFIX)


def _build_storage_key(r: ReadingCreate) -> str:
    """Construct the partitioned full S3 key for a new reading."""
    day = r.recorded_at.date().isoformat()           # YYYY-MM-DD
    return f"{ROOT_PREFIX}{r.sensor_id}/{day}/{uuid4().hex}.json"


# --- Endpoint 2: ingest one reading ---
@router.post("", response_model=ReadingOut, status_code=201)
def create_reading(reading: ReadingCreate) -> ReadingOut:
    storage_key = _build_storage_key(reading)
    # mode="json" makes datetimes JSON-serializable strings.
    storage.put_json(storage_key, reading.model_dump(mode="json"))
    return ReadingOut(key=_to_id(storage_key), **reading.model_dump())


# --- Endpoint 3: batch ingest ---
@router.post("/bulk", response_model=BulkResult, status_code=201)
def create_readings_bulk(payload: ReadingBulkCreate) -> BulkResult:
    ids: list[str] = []
    for reading in payload.readings:
        storage_key = _build_storage_key(reading)
        storage.put_json(storage_key, reading.model_dump(mode="json"))
        ids.append(_to_id(storage_key))
    # NOTE: this writes one S3 object per record in a loop. It works and is clear,
    # but it's also a real DE lesson: thousands of tiny files is an anti-pattern
    # ("small files problem"). A later iteration would batch many records into one
    # JSON-Lines or Parquet object. Feel the problem first, then fix it.
    return BulkResult(inserted=len(ids), keys=ids)


# --- Endpoint 4: list/query readings by prefix ---
@router.get("", response_model=list[ReadingOut])
def list_readings(
    sensor_id: str | None = Query(None, description="Filter to one sensor"),
    day: str | None = Query(None, description="Filter to one day, YYYY-MM-DD"),
    limit: int = Query(100, ge=1, le=1000),
) -> list[ReadingOut]:
    # Build the most specific prefix we can from the filters.
    prefix = ROOT_PREFIX
    if sensor_id:
        prefix += f"{sensor_id}/"
        if day:
            prefix += f"{day}/"

    out: list[ReadingOut] = []
    for storage_key in storage.list_keys(prefix=prefix, limit=limit):
        data = storage.get_json(storage_key)
        if data is not None:
            out.append(ReadingOut(key=_to_id(storage_key), **data))
    return out


# --- Endpoint 5: fetch one reading by its id ---
# :path lets the id contain slashes (e.g. sensor-001/2026-06-26/<uuid>.json)
@router.get("/{reading_id:path}", response_model=ReadingOut)
def get_reading(reading_id: str) -> ReadingOut:
    data = storage.get_json(_to_storage_key(reading_id))
    if data is None:
        raise HTTPException(status_code=404, detail="Reading not found")
    return ReadingOut(key=reading_id, **data)


# --- Endpoint 6: delete one reading ---
@router.delete("/{reading_id:path}", status_code=204)
def delete_reading(reading_id: str) -> None:
    if not storage.delete_key(_to_storage_key(reading_id)):
        raise HTTPException(status_code=404, detail="Reading not found")

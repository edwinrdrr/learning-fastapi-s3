"""Endpoint 1: health check. Green = API up AND S3 reachable."""
from fastapi import APIRouter, HTTPException

from app import storage
from app.schemas import HealthOut

router = APIRouter(tags=["health"])


@router.get(
    "/health",
    response_model=HealthOut,
    summary="Liveness check",
    description="Returns `200` when the API is up **and** its object store is reachable.",
    responses={503: {"description": "Object store not reachable"}},
)
def health() -> dict:
    try:
        storage.ping()
    except Exception as e:  # noqa: BLE001 - surface any S3 problem as 503
        raise HTTPException(status_code=503, detail=f"S3 not reachable: {e}")
    return {"status": "ok", "s3": "reachable", "bucket": storage.BUCKET}

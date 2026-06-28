"""API-key authentication.

If `API_KEY` is configured, every protected route requires a matching
`X-API-Key` header. If it's unset (local/dev), auth is disabled — routes are
open. Using APIKeyHeader makes the scheme show up in /docs with an Authorize
button.
"""
from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader

from app.config import settings

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def require_api_key(provided: str | None = Security(_api_key_header)) -> None:
    """Dependency that enforces the API key when one is configured."""
    if settings.api_key is None:
        return  # auth disabled
    if provided != settings.api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
        )

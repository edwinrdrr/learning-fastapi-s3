"""Application entrypoint: create the FastAPI app and wire up the routers.

Run it:  docker compose up --build
Then open http://localhost:8000/docs for interactive API docs (Swagger UI),
and http://localhost:9001 (minioadmin / minioadmin) to watch JSON files appear.
"""
import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address

from app import storage
from app.config import settings
from app.routers import health, readings, scrape, scrape_config, stats
from app.security import require_api_key

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Runs once on startup: make sure our bucket exists before serving traffic.
    storage.ensure_bucket()
    log.info("startup complete (bucket=%s, auth=%s)",
             storage.BUCKET, "on" if settings.api_key else "off")
    yield
    # (nothing to clean up on shutdown for now)


# Tag descriptions show up as section intros in /docs.
openapi_tags = [
    {"name": "scrape", "description": "Read daily scrape datasets (the main product). "
                                      "Read-only; data is served from processed Parquet on S3."},
    {"name": "scrape-config", "description": "Upload the inputs that drive scraping: the "
                                             "input table (replace) and blacklist/whitelist (append)."},
    {"name": "health", "description": "Liveness and dependency checks."},
    {"name": "readings", "description": "Learning scaffold — not part of the scrape product."},
    {"name": "stats", "description": "Learning scaffold — aggregation over many JSON objects."},
]

app = FastAPI(
    title="Readings API (FastAPI + S3)",
    description="Learning project: a JSON-on-S3 data pipeline served over HTTP.",
    version="0.1.0",
    lifespan=lifespan,
    openapi_tags=openapi_tags,
)

# --- Rate limiting (slowapi). default_limits + middleware applies it globally. ---
limiter = Limiter(key_func=get_remote_address, default_limits=[settings.rate_limit])
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, lambda r, e: _rate_limited())
app.add_middleware(SlowAPIMiddleware)

# --- CORS ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_methods=["GET"],
    allow_headers=["*"],
)


def _rate_limited():
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=429, content={"detail": "Rate limit exceeded"})


# Each router groups related endpoints. The data routers are protected by the
# API-key dependency (a no-op until API_KEY is configured); health stays open.
app.include_router(health.router)
app.include_router(readings.router, dependencies=[Depends(require_api_key)])
app.include_router(stats.router, dependencies=[Depends(require_api_key)])
app.include_router(scrape.router, dependencies=[Depends(require_api_key)])
app.include_router(scrape_config.router, dependencies=[Depends(require_api_key)])


@app.get("/", tags=["root"])
def root() -> dict:
    return {"message": "See /docs for the interactive API.", "health": "/health"}

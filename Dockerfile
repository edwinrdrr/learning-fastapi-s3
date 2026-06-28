# ---- Build stage: install dependencies into an isolated prefix ----
FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1
WORKDIR /build

COPY requirements.txt .
# Install into /install so we can copy just the packages into the runtime image
# (keeps build tooling out of the final image).
RUN pip install --prefix=/install -r requirements.txt


# ---- Runtime stage: small image, non-root, production server ----
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Copy the installed packages + console scripts (uvicorn, etc.) from the builder.
COPY --from=builder /install /usr/local

WORKDIR /code
COPY app ./app

# Run as an unprivileged user, not root.
RUN useradd --create-home --uid 10001 appuser && chown -R appuser /code
USER appuser

EXPOSE 8000

# Container-level health: hit /health using stdlib (no curl in slim image).
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health').status==200 else 1)"

# Production default: multiple workers, NO --reload. (docker-compose overrides
# this with a --reload single-process command for local development.)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]

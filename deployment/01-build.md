# 01 — Building the API

The app ships as a single container image built from the repo's **`Dockerfile`**. There is
nothing to compile; the image is just Python + the dependencies + the `app/` package.

## What's in the image

- **Base:** `python:3.12-slim` (multi-stage: a `builder` installs deps, the `runtime` stage
  copies only the installed packages + `app/`).
- **Copied in:** only `app/` (`COPY app ./app`). Dev-only things — `tests/`, `docs/`,
  `learning/`, `infra-choices/`, `deployment/`, and the out-of-repo data generator — are
  **not** in the image.
- **User:** non-root `appuser` (uid 10001).
- **Port:** `8000`.
- **Healthcheck:** hits `/health` (which checks S3 reachability).
- **Default command (production):** `uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2`.

## Dependencies

`requirements.txt` (runtime):

```
fastapi          # web framework
uvicorn[standard]# ASGI server
boto3            # S3 client
duckdb           # in-process query engine (reads Parquet directly from S3 via httpfs)
pydantic / pydantic-settings  # models + env-var config
slowapi          # rate limiting
python-multipart # file uploads (/scrape-config)
mangum           # ASGI->AWS Lambda adapter (only used by app/lambda_handler.py)
```

`requirements-dev.txt` adds `pytest` + `httpx` for the test suite.

> **DuckDB extensions:** `httpfs` (and `aws`, on real AWS) are **not** pip packages — DuckDB
> downloads them at runtime on first use. That's fine on a normal container with egress. On
> Lambda, give it egress or bundle them, and set `HOME=/tmp` (see
> [`../infra-choices/04-lambda.md`](../infra-choices/04-lambda.md)).

## Build & tag

```bash
# local build
docker build -t learning-fastapi-s3:latest .

# tag for AWS ECR (see 05-deploy-aws.md for the registry login)
docker tag learning-fastapi-s3:latest \
  <ACCOUNT_ID>.dkr.ecr.<REGION>.amazonaws.com/learning-fastapi-s3:latest
```

## Run the image directly (without Compose)

Useful to sanity-check the production image against a real/standalone S3. For the full local
stack with MinIO, use [04-run-locally.md](04-run-locally.md) instead.

```bash
docker run --rm -p 8000:8000 \
  -e S3_BUCKET=readings \
  -e AWS_REGION=us-east-1 \
  -e AWS_ACCESS_KEY_ID=... -e AWS_SECRET_ACCESS_KEY=... \
  learning-fastapi-s3:latest
# then: curl localhost:8000/health
```

(On AWS you'd omit the keys and let the IAM role supply credentials — see
[02-configuration.md](02-configuration.md).)

## Tests

```bash
pip install -r requirements-dev.txt
python -m pytest tests/        # hermetic — no S3/Docker needed
```

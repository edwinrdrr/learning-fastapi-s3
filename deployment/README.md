# Deployment & operations guide

Everything needed to **build, configure, run, deploy, and feed** this service, in one
place. This API is a **read-only consumer**: a separate upstream writes processed
Parquet to S3; the API serves it over HTTP. Nothing here produces data.

## How the pieces fit

```
  ┌───────────────────────┐   writes   ┌──────────────────┐   reads   ┌──────────────────┐
  │ Upstream producer      │ ─────────▶ │  S3 bucket        │ ◀──────── │ This API          │
  │ (scraper + ETL,        │            │  processed/scrape │           │ FastAPI + DuckDB  │
  │  OUT OF SCOPE here)     │            │  /dt=…/data.parquet│           │ (read-only)       │
  └───────────────────────┘            └──────────────────┘           └──────────────────┘
        (e.g. the standalone                                                    │ HTTPS
         generate_dummy.py for                                                  ▼
         local testing)                                                    API consumers
```

The API also has two **write** surfaces that store small JSON objects in the same
bucket — `/readings` (a CRUD demo) and `/scrape-config` (uploads). That's why its IAM
role needs read **and** write, even though `/scrape` is read-only. See
[03-data-contract.md](03-data-contract.md).

## The files in this folder

| File | What it covers |
|---|---|
| [01-build.md](01-build.md) | Building the container image (Dockerfile, requirements, build/tag/run) |
| [02-configuration.md](02-configuration.md) | **Every setting / env var**, per-environment, secrets |
| [03-data-contract.md](03-data-contract.md) | S3 bucket layout — the folders/files the producer writes and the API consumes |
| [04-run-locally.md](04-run-locally.md) | Run the whole thing locally with Docker Compose + MinIO, seed data, smoke test |
| [05-deploy-aws.md](05-deploy-aws.md) | AWS prerequisites (bucket, ECR, IAM, secret) common to every target |
| [06-consume.md](06-consume.md) | How a client consumes the API (auth, endpoints, paging loop) |
| [07-curl-cookbook.md](07-curl-cookbook.md) | **Copy-paste curl commands** to test every endpoint (blacklist, scrape, readings…) |
| [08-images-and-ecr.md](08-images-and-ecr.md) | Images vs ECR vs where your code runs (why Lambda needs ECR; the two images) |
| [09-lambda-deployment.md](09-lambda-deployment.md) | **Focused: the Lambda + ECR deployment only** — architecture, build→ECR→function, request flow |
| [10-lambda-lifecycle.md](10-lambda-lifecycle.md) | **Lambda-only** end-to-end request trace (client → response), cold starts, multi-day timing |
| [11-testing-lambda.md](11-testing-lambda.md) | Test the Lambda **before API Gateway** — `aws lambda invoke` (AWS) and the local RIE (no AWS) |

## Related docs (not duplicated here)

- **[`../infra-choices/`](../infra-choices/)** — pick a compute target (App Runner / ECS /
  EC2 / Lambda) with cost + trade-offs. `05-deploy-aws.md` covers the shared setup, then
  points you there.
- **[`../docs/client-api.md`](../docs/client-api.md)** — the canonical API reference.
- **[`../docs/internal-architecture.md`](../docs/internal-architecture.md)** — how the read
  path, caching-free design, and DuckDB-on-S3 work internally.

## TL;DR (local, from zero)

```bash
docker compose up --build -d                       # API on :8000, MinIO on :9000/:9001
# seed a day to read (generator lives OUTSIDE this repo):
S3_ENDPOINT_URL=http://localhost:9000 AWS_ACCESS_KEY_ID=minioadmin \
AWS_SECRET_ACCESS_KEY=minioadmin S3_BUCKET=readings \
  python /home/edwin/Documents/data/dummy-data/generate_dummy.py 2026-06-26 2026-06-26
curl localhost:8000/scrape/2026-06-26/meta         # -> 200 with row count + columns
```

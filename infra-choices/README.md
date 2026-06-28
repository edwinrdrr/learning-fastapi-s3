# Infra choices — deploying learning-fastapi-s3 on AWS

This folder documents the realistic ways to run this service on AWS, with the trade-offs
written for **this specific app**, not generic advice.

## What this app actually needs from infrastructure

These properties drive every decision below:

- **Fully stateless web service** — S3 is the only system of record (no database, no local
  cache). `app/daily.py` range-reads the Parquet straight from S3 each request, so there's no
  disk state to preserve — it runs identically on one box or many, warm or cold.
- **Container-first** — ships a production-ready multi-stage `Dockerfile` (port 8000,
  non-root, `/health` healthcheck). Anything that runs a container can run this.
- **IAM-role-ready credentials** — when `S3_ENDPOINT_URL` + the static AWS keys are unset,
  boto3 falls back to the instance/task role (`app/storage.py`). No secrets in the image.
- **Needs read *and* write on the bucket.** The `/scrape` group is read-only, but
  `/readings` (POST/DELETE) and `/scrape-config` (uploads) still write objects — so the role
  needs `s3:GetObject`, `s3:PutObject`, `s3:DeleteObject`, `s3:ListBucket`.
- **DuckDB runs in-process** — `/scrape/{day}` streams up to 100k rows/page by serializing
  JSON in DuckDB's C++ engine. A memory + response-size consideration: wants ~1–2 GB RAM and
  the ability to stream large HTTP responses.
- **No batch/cron tier.** This is a pure read-only-plus-CRUD API. Producing the scrape
  Parquet is **out of scope** (a separate upstream writes it to S3). There is no ingest job
  to schedule — so no EventBridge / scheduled-task infrastructure is needed.
- **Single-writer admin lock** — `app/scrape_config.py` guards blacklist/whitelist appends
  with an in-process `threading.Lock`. Multiple instances/workers can race, so cap the web
  tier at 1 instance (or replace the lock) until a real fix exists.

## The choices at a glance

| Choice | Effort | Idle cost/mo | Best when… | DuckDB fit |
|---|---|---|---|---|
| **[01 App Runner](01-app-runner.md)** ⭐ | Lowest | ~$10–15 | You want it live fast with managed TLS/scaling | Good (1 vCPU/2 GB) |
| **[02 ECS Fargate + ALB](02-ecs-fargate-alb.md)** | Highest | ~$35–45 | You want the "real" production container setup | Good |
| **[03 EC2 + docker compose](03-ec2-docker-compose.md)** | Medium | ~$8–17 | Cheapest, closest to local, you don't mind ops | Good (size the box) |
| **[04 Lambda](04-lambda.md)** | Medium | ~$0 | True scale-to-zero; occasional cold starts OK | OK (small pages, stateless reads) |

⭐ = the recommended path for this project. (The app was redesigned — small pages + stateless
S3 reads + a Mangum handler — so Lambda is now viable, not just theoretical.)

## How to read these

Each file follows the same shape: **mental model → architecture diagram → request flow →
app-specific fit notes → steps → cost → pros/cons/when to choose.** Prices are approximate
**us-east-1** list prices (June 2026) — confirm in the AWS Pricing Calculator for your region.

## TL;DR recommendation

- **Learning + want it online with least fuss →** App Runner (01).
- **Learning the production container stack employers use →** ECS Fargate (02).
- **Optimizing for cost and you're comfortable on a Linux box →** EC2 (03).
- **Want scale-to-zero →** Lambda (04), but only after accepting it breaks the large
  `/scrape` streaming responses — read that file before choosing it.

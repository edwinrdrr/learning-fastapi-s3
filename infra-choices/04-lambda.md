# 04 — AWS Lambda (scale-to-zero)

> True scale-to-zero: pay only per request, nothing when idle. The app was **redesigned to
> fit Lambda** (small pages + stateless S3 reads + a Mangum handler), so this is now a real
> option — the trade is small pages and cold starts in exchange for ~$0 idle cost.

## Mental model

- **Lambda function** = your code, run on demand, frozen between invocations.
- **Mangum** = the ASGI adapter that runs the FastAPI app inside a Lambda handler
  (`app/lambda_handler.py` → `handler`).
- **API Gateway** = the HTTPS front door.
- **Execution role** = how the function reaches S3 (DuckDB + boto3 both use it).

## What was changed to make it fit

1. **`page_size` capped at 5000** so any `/scrape/{day}` response stays under API Gateway's
   ~6–10 MB limit. A full day (~20k rows) is now ~4 requests instead of one big dump.
2. **Stateless read path** — DuckDB range-reads the Parquet **directly from S3**; nothing is
   cached on local disk, so cold starts don't lose a warm cache (there isn't one).
3. **Mangum handler** — `app/lambda_handler.py` wraps `app.main:app`; deploy it as the Lambda
   handler `app.lambda_handler.handler`.

## Architecture

```
   Internet
      │ HTTPS
      ▼
 ┌──────────────┐    ┌───────────────────────────┐
 │ API Gateway  │───▶│ Lambda: FastAPI via Mangum │  exec role ──▶ S3 (r/w, range reads)
 │ (~6–10MB cap)│    │  container image, 2 GB     │
 └──────────────┘    └───────────────────────────┘
```

## Remaining trade-offs (not blockers)

- **Cold starts.** First request after idle pays container start + DuckDB import (~1–3 s).
  Provisioned concurrency removes it but reintroduces an always-on cost — which defeats the
  zero-idle point.
- **DuckDB extensions.** `httpfs` (and `aws`, on the real-AWS credential path) download on
  first use. Give the function egress **or** bundle the extensions into the image, and set
  `HOME=/tmp` so DuckDB has a writable extension dir.
- **No warm cache.** Every cold container re-reads from S3 (HEAD + footer + range reads per
  request). Cheap per call, but more S3 traffic than a long-lived container; a CDN in front
  (`Cache-Control: immutable` on published days) amortizes it.
- **`/scrape-config` write lock** does nothing across concurrent Lambdas — rare admin-write
  race, documented (the fix is S3 conditional writes).

## Steps (high level)

1. **S3 bucket** + push a **container-image** build of the Dockerfile to ECR.
2. **Lambda** from that image, handler `app.lambda_handler.handler`, **memory 2048 MB**,
   env `HOME=/tmp`, `S3_BUCKET`/`AWS_REGION` set, `S3_ENDPOINT_URL` and static keys **unset**.
3. **Execution role** with S3 r/w (`Get/Put/Delete/List`) + `ssm:GetParameter` for the API key.
4. **API Gateway** (HTTP API) proxying all routes to the function; map `API_KEY` from SSM.

## Cost (approx, us-east-1)

| Item | ~Monthly |
|---|---|
| Lambda requests + GB-seconds (learning traffic) | **~$0–2** |
| Idle | **$0** (true scale-to-zero) |
| API Gateway (per-request) | cents at low volume |
| S3 / SSM / logs | cents |
| Provisioned concurrency (only if you add it) | adds always-on $$ |

## Pros / cons

**Pros:** genuine scale-to-zero; near-zero cost at learning traffic; the stateless read path
fits serverless cleanly.
**Cons:** cold-start latency; small pages only (4 requests for a full day); more S3 round-trips
without a warm cache; extension-bundling fiddliness; the write-lock race appears sooner.

## When to choose

**Near-zero idle cost is the priority** and occasional cold-start latency + small pages are
acceptable (e.g. a demo hit a few times a day). For steady traffic, App Runner (01) keeps the
container warm and is the smoother deal at ~$10–15/mo.

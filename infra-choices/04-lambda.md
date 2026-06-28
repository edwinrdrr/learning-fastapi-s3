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
4. **`Dockerfile.lambda`** — a Lambda-flavored image (AWS base image + Runtime Interface) that
   **pre-bakes DuckDB's `httpfs`/`aws` extensions** into the image, so cold starts need no
   network. `app/daily.py` loads them offline via `DUCKDB_EXTENSION_DIRECTORY`.

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
- **DuckDB extensions.** Handled: `Dockerfile.lambda` pre-bakes `httpfs`/`aws` into the image
  (`/opt/duckdb_ext`) and sets `HOME=/tmp`, so cold starts load them offline — no egress needed.
- **No warm cache.** Every cold container re-reads from S3 (HEAD + footer + range reads per
  request). Cheap per call, but more S3 traffic than a long-lived container; a CDN in front
  (`Cache-Control: immutable` on published days) amortizes it.
- **`/scrape-config` write lock** does nothing across concurrent Lambdas — rare admin-write
  race, documented (the fix is S3 conditional writes).

## Steps

Do the shared AWS prerequisites first — bucket, ECR repo, IAM, SSM secret — in
[`../deployment/05-deploy-aws.md`](../deployment/05-deploy-aws.md). The role here is the
**Lambda execution role** with the same S3 r/w + `ssm:GetParameter` policy. Then:

```bash
# 1. Build the Lambda image (x86_64 to match the baked extensions) and push to ECR
docker build --platform linux/amd64 -f Dockerfile.lambda -t "$IMAGE" .
docker push "$IMAGE"

# 2. Create the function from the image
aws lambda create-function \
  --function-name learning-fastapi-s3 \
  --package-type Image \
  --code ImageUri="$IMAGE" \
  --role arn:aws:iam::$ACCOUNT_ID:role/<lambda-exec-role> \
  --architectures x86_64 \
  --memory-size 2048 \
  --timeout 30 \
  --environment "Variables={S3_BUCKET=$BUCKET,AWS_REGION=$AWS_REGION,CORS_ORIGINS=*}"
# Note: S3_ENDPOINT_URL and the static AWS keys stay UNSET (uses the exec role).
# HOME=/tmp and DUCKDB_EXTENSION_DIRECTORY are already baked into the image.

# 3. Front it with an HTTP API Gateway proxying all routes to the function
aws apigatewayv2 create-api \
  --name learning-fastapi-s3 \
  --protocol-type HTTP \
  --target arn:aws:lambda:$AWS_REGION:$ACCOUNT_ID:function:learning-fastapi-s3
# (grant API Gateway permission to invoke: aws lambda add-permission … --principal apigateway.amazonaws.com)
```

To inject `API_KEY` from the SSM secret, add it to the function's `--environment` as a secret
reference (or read it in code) — see [`../deployment/02-configuration.md`](../deployment/02-configuration.md).
For redeploys: `docker push` the new image, then `aws lambda update-function-code
--function-name learning-fastapi-s3 --image-uri "$IMAGE"`.

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
without a warm cache; the write-lock race appears sooner.

## When to choose

**Near-zero idle cost is the priority** and occasional cold-start latency + small pages are
acceptable (e.g. a demo hit a few times a day). For steady traffic, App Runner (01) keeps the
container warm and is the smoother deal at ~$10–15/mo.

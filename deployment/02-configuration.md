# 02 — Configuration (all settings)

The app is **12-factor**: every setting comes from an environment variable, parsed in
`app/config.py` (`pydantic-settings`). Locally a `.env` file is also read; in the cloud you
set real environment variables / secrets. No setting is hard-coded.

## Every environment variable

| Env var | Required? | Default | Purpose |
|---|---|---|---|
| `S3_BUCKET` | recommended | `readings` | Bucket the API reads/writes |
| `AWS_REGION` | recommended | `us-east-1` | AWS region for S3 + DuckDB |
| `S3_ENDPOINT_URL` | local only | _(unset)_ | Custom S3 endpoint. **Set to `http://minio:9000` locally; leave UNSET for real AWS.** |
| `AWS_ACCESS_KEY_ID` | local only | _(unset)_ | Static key. **Set locally (MinIO); leave UNSET on AWS** so the IAM role is used. |
| `AWS_SECRET_ACCESS_KEY` | local only | _(unset)_ | Static secret. Same rule as above. |
| `API_KEY` | prod: yes | _(unset)_ | If set, clients must send `X-API-Key: <value>` on data routes. **Unset = auth disabled** (fine locally). |
| `CORS_ORIGINS` | prod: yes | `*` | Comma-separated allowed origins. Avoid `*` in production. |
| `RATE_LIMIT` | no | `120/minute` | Global rate limit (slowapi syntax). |

> Both **boto3 and DuckDB** read the same credentials. When `S3_ENDPOINT_URL` + the two
> `AWS_*` keys are unset, both fall back to the default credential chain (env / `~/.aws` /
> the instance or Lambda IAM role) — the correct setup on AWS, with no secrets in the image.

## Per-environment matrix

| Setting | Local (Docker + MinIO) | Real AWS |
|---|---|---|
| `S3_ENDPOINT_URL` | `http://minio:9000` | **unset** |
| `AWS_ACCESS_KEY_ID` / `_SECRET_ACCESS_KEY` | `minioadmin` / `minioadmin` | **unset** (IAM role) |
| `AWS_REGION` | `us-east-1` | your region |
| `S3_BUCKET` | `readings` | your real bucket |
| `API_KEY` | unset (auth off) | **set** (via secret store) |
| `CORS_ORIGINS` | `*` | your frontend origin(s) |

## Secrets

Never put `API_KEY` (or static AWS keys) in the image or in plain env on a shared service.

- **Local:** a `.env` file (gitignored) or the `environment:` block in `docker-compose.yml`.
- **AWS:** store `API_KEY` in **SSM Parameter Store (SecureString)** or Secrets Manager and
  inject it as a runtime secret. App Runner/ECS/Lambda all support referencing it by ARN; the
  task/instance/execution role needs `ssm:GetParameter` on that parameter. See
  [05-deploy-aws.md](05-deploy-aws.md).

## Where it's set per runtime

- **Docker Compose (local):** `docker-compose.yml` → `api.environment`.
- **App Runner / ECS:** the service's runtime environment variables + secrets.
- **EC2:** the `environment:` block of the compose file on the box (drop the MinIO vars).
- **Lambda:** the function's environment variables (+ `HOME=/tmp` for DuckDB extensions).

## Quick verification

```bash
curl localhost:8000/health
# {"status":"ok","s3":"reachable","bucket":"readings"}  => S3 creds + bucket are correct
```
A `503` from `/health` means the app can't reach S3 — wrong endpoint, region, bucket, or
credentials.

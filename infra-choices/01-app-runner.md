# 01 — AWS App Runner ⭐ (recommended)

> Managed container web service. You give it an image; it runs the HTTP service and hides the
> load balancer, VMs, TLS, and scaling. The simplest way to get this app on a public HTTPS URL.

## Mental model

- **ECR** = where the image lives.
- **App Runner** = the thing that runs it and gives you a URL.
- **IAM instance role** = how the running container reaches S3 (no secrets in the image).

Because the app no longer ingests anything, there's no cron/batch tier — App Runner alone is
the entire deployment.

## Architecture

```
            git push / docker push
                     │
                     ▼
   ┌──────────┐   pull    ┌─────────────────────────┐
   │   ECR    │◀──────────│      App Runner          │  ── public HTTPS URL (managed TLS)
   │  image   │  (access  │  ┌───────────────────┐   │       https://xxx.awsapprunner.com
   └──────────┘   role)   │  │ container :8000   │   │
                          │  │ FastAPI + DuckDB  │   │
                          │  └─────────┬─────────┘   │
                          │  health: /health         │
                          │  instance role ──────────┼──▶  S3 bucket (read + write)
                          └──────────────────────────┘

   (scrape Parquet is written to the same bucket by a SEPARATE upstream producer,
    out of scope for this deployment)
```

## Request flow

1. Client hits the App Runner HTTPS URL.
2. App Runner terminates TLS and routes to a warm container instance.
3. FastAPI handles the request; boto3 fetches **temporary credentials from the instance
   role** via the metadata endpoint and talks to S3.
4. App Runner continuously polls `/health` (which calls `head_bucket`) — a green check means
   "container is up **and** can reach S3." A failed deploy never enters rotation.

## App-specific fit notes

- **Memory:** use **1 vCPU / 2 GB**, not the 0.25/0.5 minimum — DuckDB streaming a 100k-row
  page can spike past 0.5 GB and get OOM-killed.
- **Concurrency / the lock:** set **autoscaling max = 1**. The `scrape_config.py` in-process
  lock can't protect blacklist/whitelist appends across multiple instances. (Even at 1
  instance the Dockerfile's 2 uvicorn workers aren't lock-shared, but those are
  low-frequency admin writes — acceptable for a learning deploy.)
- **IAM is read + write:** `/scrape` is read-only, but `/readings` and `/scrape-config` write
  — the instance role needs Get/Put/Delete/List (see step 4).
- **No persistent disk needed:** reads stream directly from S3, nothing cached locally.

## Steps (console / CLI)

1. **S3 bucket** — pre-create it (so the app never needs `s3:CreateBucket`).
2. **ECR** — `docker build` + `docker push` the existing Dockerfile.
3. **API key → SSM Parameter Store** (SecureString) so it isn't a plaintext env var.
4. **Two IAM roles** — *access role* (`build.apprunner.amazonaws.com`, pull from ECR) and
   *instance role* (`tasks.apprunner.amazonaws.com`) with this policy:
   ```json
   {
     "Version": "2012-10-17",
     "Statement": [
       { "Effect": "Allow", "Action": ["s3:ListBucket"], "Resource": "arn:aws:s3:::BUCKET" },
       { "Effect": "Allow",
         "Action": ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"],
         "Resource": "arn:aws:s3:::BUCKET/*" },
       { "Effect": "Allow", "Action": ["ssm:GetParameter"],
         "Resource": "arn:aws:ssm:REGION:ACCOUNT_ID:parameter/learning-fastapi-s3/API_KEY" }
     ]
   }
   ```
5. **App Runner service** — port `8000`, health `/health`, env `S3_BUCKET`/`AWS_REGION`/
   `CORS_ORIGINS`/`RATE_LIMIT`, secret `API_KEY` from SSM, **leave `S3_ENDPOINT_URL` and the
   static AWS keys unset**, autoscaling max = 1.

## Cost (approx, us-east-1)

App Runner bills **memory 24/7** (~$0.007/GB-hr, even idle) + **vCPU only while serving**
(~$0.064/vCPU-hr). No free tier.

| Item | ~Monthly |
|---|---|
| App Runner 1 vCPU / 2 GB (warm baseline) | **~$10–12** |
| ECR image storage (~0.3–0.5 GB) | ~$0.05 |
| S3 storage + requests (learning scale) | cents |
| SSM Standard param + CloudWatch logs | ~free |
| **Total** | **~$10–15** |

## Pros / cons

**Pros:** least to configure; managed HTTPS, scaling, and deploys; no load balancer or VPC to
own; clean IAM-role credential story; no batch tier to run.
**Cons:** small always-on baseline (no scale-to-zero); less control than ECS; VPC access
requires extra config.

## When to choose

You want the app **online quickly with minimal ops**, and a ~$10–15/mo baseline is fine. This
is the recommended path for this project.

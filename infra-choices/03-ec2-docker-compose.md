# 03 — Single EC2 + docker compose

> Cheapest and closest to your local setup: one Linux VM running `docker compose`, with the
> MinIO service swapped out for real S3. Most manual ops, least "cloud native."

## Mental model

- **EC2 instance** = one Linux box you own and patch.
- **docker compose** = the same orchestration you run locally, minus MinIO.
- **Instance IAM role** = how the container reaches S3 (no keys on disk).

## Architecture

```
        Internet
           │  HTTP/HTTPS
           ▼
   ┌──────────────────────────── EC2 instance ────────────────────────────┐
   │  (optional) Caddy/nginx :443  ──▶  api container :8000                 │
   │                                     FastAPI + DuckDB                   │
   │  docker compose up -d                instance profile (role) ─────────┼──▶ S3 (r/w)
   └────────────────────────────────────────────────────────────────────────┘
                              ▲ security group: 22 (you), 80/443 (world)
```

## Request flow

1. Client → EC2 public IP / Elastic IP (front it with Caddy/nginx for TLS, or skip TLS for
   pure learning).
2. Reverse proxy → `api` container on port 8000.
3. boto3 in the container uses the **EC2 instance profile role** for S3 (attach the role to
   the instance; do **not** put keys in `.env`).

## App-specific fit notes

- **Drop MinIO:** the local `docker-compose.yml` runs MinIO as a stand-in for S3. For AWS,
  remove the `minio` service and the `S3_ENDPOINT_URL` / static-key env vars so boto3 uses
  the instance role against real S3. Keep `S3_BUCKET` and `AWS_REGION`.
- **The lock is a near-non-issue here:** a single box runs one `api` container, so the
  `scrape_config.py` lock behaves as designed within that process (the 2 uvicorn workers are
  still separate processes — same low-frequency-admin caveat as everywhere).
- **IAM is read + write** (`/readings` + `/scrape-config` write): the instance role needs
  `s3:GetObject/PutObject/DeleteObject/ListBucket`.
- **Sizing:** `t3.small` (2 GB) is the floor for DuckDB; `t3.medium` (4 GB) is comfortable.
- **You own patching, restarts, and uptime** — set `restart: unless-stopped` and consider a
  systemd unit so compose comes back after reboot.

## Steps (high level)

1. **S3 bucket** (pre-create) + **IAM role** with S3 r/w; create an **instance profile**.
2. **Launch EC2** (Amazon Linux 2023 or Ubuntu), attach the instance profile, security group
   allowing 22 from your IP and 80/443 from the world.
3. **Install Docker + compose plugin** on the box.
4. **Copy the repo** (git clone) and **edit compose** to remove MinIO + the endpoint/key env
   vars; set `S3_BUCKET`, `AWS_REGION`, `API_KEY`, `CORS_ORIGINS`.
5. **`docker compose up -d`** (use the production CMD, not the hot-reload override).
6. **(TLS)** put Caddy in front for an automatic Let's Encrypt cert, if you want HTTPS.

## Cost (approx, us-east-1, on-demand)

| Item | ~Monthly |
|---|---|
| `t3.small` (2 GB) 24/7 | **~$15** |
| `t3.micro` (1 GB) 24/7 | ~$7.5 (tight for DuckDB) |
| EBS root volume (~10–20 GB gp3) | ~$1–2 |
| Elastic IP (while attached) | free |
| S3 / data transfer (learning scale) | cents |
| **Total** | **~$8–17** |

> Cheaper than ECS, comparable to App Runner — but the savings come at the cost of **you doing
> the ops** (patching, TLS, restarts, monitoring). A **Reserved Instance / Savings Plan** can
> cut the EC2 line ~30–40% if you commit.

## Pros / cons

**Pros:** cheapest predictable cost; closest to your working local setup; full control of the box.
**Cons:** you own all ops (OS patching, Docker upgrades, TLS, uptime, scaling); single point
of failure; no managed autoscaling; manual deploys.

## When to choose

You want the **lowest, most predictable cost**, you're comfortable on a Linux box, and managed
convenience matters less than control and price.

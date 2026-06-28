# 04 — Run locally (Docker Compose + MinIO)

Local dev uses **MinIO** as a stand-in for S3 (S3-compatible). The exact same boto3 + DuckDB
code talks to real AWS S3 by changing only the config in [02-configuration.md](02-configuration.md).

## Start the stack

```bash
docker compose up --build -d
```

This runs two containers (see `docker-compose.yml`):

| Service | Ports | What |
|---|---|---|
| `minio` | `9000` (S3 API), `9001` (web console) | Local object store; user/pass `minioadmin`/`minioadmin` |
| `api` | `8000` | This FastAPI app, hot-reload, code bind-mounted from `./app` |

Open:
- **http://localhost:8000/docs** — interactive API docs (Swagger).
- **http://localhost:9001** — MinIO console, to watch objects appear.

Health check:
```bash
curl localhost:8000/health
# {"status":"ok","s3":"reachable","bucket":"readings"}
```

## Seed a day to read

The API only consumes; you need a `processed/scrape/dt=…/data.parquet` object to read. The
data generator lives **outside this repo** (this repo is API-only) at
`/home/edwin/Documents/data/dummy-data/generate_dummy.py`. Point it at MinIO and run it:

```bash
pip install boto3 duckdb   # once, in whatever env you run the generator from

S3_ENDPOINT_URL=http://localhost:9000 \
AWS_ACCESS_KEY_ID=minioadmin AWS_SECRET_ACCESS_KEY=minioadmin \
AWS_REGION=us-east-1 S3_BUCKET=readings \
  python /home/edwin/Documents/data/dummy-data/generate_dummy.py 2026-06-26 2026-06-26
# done: 1 days, 20000 rows -> s3://readings/processed/scrape/
```

(Seed a range with `… generate_dummy.py 2026-03-01 2026-05-31`.)

## Smoke test

```bash
DAY=2026-06-26
curl -s localhost:8000/scrape/$DAY/meta                       # row count + 20 columns
curl -s "localhost:8000/scrape/$DAY?page=1&page_size=5000"    # first page (max 5000 rows)
curl -s "localhost:8000/scrape/$DAY?page=5&page_size=5000"    # [] once you page past the end
curl -s -o /dev/null -w '%{http_code}\n' localhost:8000/scrape/2099-01-01/meta  # 404
```

## Stop / reset

```bash
docker compose down       # stop containers, keep the seeded data (miniodata volume)
docker compose down -v    # also wipe all MinIO data
```

## Common issues

| Symptom | Cause / fix |
|---|---|
| `/health` returns `503` | API can't reach MinIO — is the `minio` container healthy? Check `S3_ENDPOINT_URL`. |
| `/scrape/<day>` always `404` | No data seeded for that day — run the generator above. |
| Generator: `Could not connect` | Use `S3_ENDPOINT_URL=http://localhost:9000` from the host (not `minio:9000`, which only resolves inside the compose network). |
| `dt` shows up as a column | You're on old code — the app reads with `hive_partitioning=false`; rebuild. |

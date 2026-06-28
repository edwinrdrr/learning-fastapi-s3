# learning-fastapi-s3

A learning project that builds **FastAPI** skills (for your job) and **data
engineering** intuition (object storage, ingestion, partitioning, aggregation)
at the same time — using **JSON files on S3**, just like your real work.

Locally, S3 is faked by **MinIO** (an S3-compatible server in Docker). The boto3
code is identical against real AWS S3 — you only change the endpoint URL and
credentials.

## Documentation

- **[deployment/](deployment/)** — build, configure, run, deploy & consume guide
  (settings reference, Docker, S3 data contract, local + AWS setup).
- **[infra-choices/](infra-choices/)** — pick an AWS compute target (App Runner /
  ECS / EC2 / Lambda) with costs and trade-offs.
- **[docs/client-api.md](docs/client-api.md)** — client-facing API guide (the
  consumer contract: endpoints, params, response schema, examples).
- **[docs/internal-architecture.md](docs/internal-architecture.md)** — internal
  reference (S3 layout, formats, stateless read path, performance, operations).
- **Interactive (auto-generated):** with the stack running, FastAPI serves live
  OpenAPI docs at **http://localhost:8000/docs** (Swagger) and
  **/redoc**; the raw spec is at **/openapi.json**.

## Architecture

```
HTTP client ──> FastAPI (app/) ──boto3──> MinIO (local S3)
                                            └── bucket: readings
                                                └── readings/<sensor>/<date>/<uuid>.json
```

## Run it

```bash
docker compose up --build
```

Then open:
- **http://localhost:8000/docs** — interactive API docs (try every endpoint here)
- **http://localhost:9001** — MinIO console (user/pass: `minioadmin`/`minioadmin`)
  to watch JSON files appear as you POST.

Stop with `Ctrl+C`; wipe all data with `docker compose down -v`.

## The 7 endpoints

| # | Method & path            | What it teaches                                  |
|---|--------------------------|--------------------------------------------------|
| 1 | `GET /health`            | Liveness + dependency check                      |
| 2 | `POST /readings`         | Ingest one record → one S3 object                |
| 3 | `POST /readings/bulk`    | Batch ingestion (and the "small files" pitfall)  |
| 4 | `GET /readings`          | Query by prefix (partitioning) + pagination      |
| 5 | `GET /readings/{key}`    | Fetch one object                                 |
| 6 | `DELETE /readings/{key}` | Delete one object                                |
| 7 | `GET /stats/summary`     | Aggregation by reading many files (the DE "transform") |
| 8 | `GET /scrape/{day}/meta` | Row count + columns, cheap (~15 ms)              |
| 9 | `GET /scrape/{day}`      | **Stream** the daily dataset back as JSON, fast  |

## The daily-scrape dataset (the `/scrape` group)

Real scenario: an upstream system produces ~20k rows × 20 columns of scrape data
**daily** and writes it to S3 as Parquet. This app is a **read-only consumer** —
it never scrapes and never writes; it only reads the processed data and serves it
over an API whose contract is **JSON**:

```
Upstream (separate)   ──writes──▶  s3: processed/scrape/dt=YYYY-MM-DD/data.parquet
FastAPI (this app)    ──GET only─▶  reads Parquet, serves JSON   (404 if not available yet)
```

- **The API is read-only (GET).** It never produces data; producing the Parquet
  is an upstream concern (a scraper + ETL), out of scope for this app. POSTing to
  `/scrape/...` returns `405`.
- If a day hasn't been written yet, reads return `404` — the API doesn't try to
  create it.

### S3 layout (partitioned by day)

```
s3://readings/
└── processed/scrape/dt=2026-06-26/data.parquet  ← columnar dataset the API reads
```

`dt=YYYY-MM-DD` is Hive-style partitioning: a read for one day resolves to a
single object path, so the API prunes to that day without scanning the rest.

### Reading a day

This app only reads. Producing the Parquet is a **separate, external concern** —
an upstream scraper/ETL writes `processed/scrape/dt=.../data.parquet` to the bucket
(for local testing, that data is generated outside this repo). Once a day exists:

```bash
# GET only — args are date (path), page, page_size
curl localhost:8000/scrape/2026-06-26/meta
curl 'localhost:8000/scrape/2026-06-26?page=1&page_size=5000' > day.json
```

### Reading many days (e.g. a 40-day range)

Each request targets **one date** and returns a page of that day. To pull a
range, the client loops over the dates (and can do it in parallel):

```python
for day in daterange(start, end):          # e.g. 40 days
    page = 1
    while True:
        rows = GET(f"/scrape/{day}?page={page}&page_size=5000")
        if not rows: break                 # empty array => past the last page
        consume(rows); page += 1
```

Why this stays fast no matter how much history exists: each day is its own
Parquet file, so a request reads **only that day** (partition pruning) — never
the other months. Per request ≈ ms–0.1 s; the only real cost is total volume
shipped, which pagination bounds and parallel day-fetches hide. Daily files are
immutable, so responses are cache-friendly (`Cache-Control: immutable`).

### Why the reads are fast (see `app/daily.py`)
1. **Parquet, not JSON, at rest** — columnar + compressed; reading 3 of 20
   columns reads only those 3.
2. **Read straight from S3, only what's needed** — DuckDB (httpfs) range-reads the
   Parquet in place, pulling just the requested page's rows + columns. No
   full-file download and nothing cached on local disk, so the read path is
   stateless (works unchanged on Lambda).
3. **Push serialization down to DuckDB** — Python doing `json.dumps` per row was
   the bottleneck (2.5 s for 20k rows); `COPY ... (FORMAT JSON)` does it in C++.
   Then stream the bytes.

Measured locally (MinIO) on a 12k-row day:

| Request | Time |
|---|---|
| `GET /scrape/{day}/meta` (footer only) | ~14 ms |
| `GET /scrape/{day}?page_size=5` | ~18 ms |
| `GET /scrape/{day}?page_size=5000` | ~40 ms |

## Try it from the terminal

```bash
# Ingest one reading
curl -X POST localhost:8000/readings -H 'content-type: application/json' -d '{
  "sensor_id":"sensor-001","metric":"temperature","value":21.5,
  "unit":"C","recorded_at":"2026-06-26T10:00:00Z"}'

# List readings for one sensor
curl 'localhost:8000/readings?sensor_id=sensor-001'

# Aggregate
curl localhost:8000/stats/summary
```

## Where this maps to data engineering

- **Ingestion** — endpoints 2 & 3 are how raw data lands in a lake.
- **Storage / partitioning** — the `sensor/date/` key layout is real lake design.
- **Serving** — endpoints 4 & 5 expose the data to consumers.
- **Transform / analytics** — endpoint 7 is aggregation done the hard way.

## Next exercises (in rough order)

1. **Feel the small-files problem:** POST a few thousand readings, then time
   `/stats/summary`. Watch it crawl.
2. **Add DuckDB:** query the JSON files with SQL instead of Python loops —
   `SELECT metric, avg(value) FROM 'readings/**/*.json' GROUP BY metric`.
3. **Switch JSON → Parquet** for the bulk writes; re-time the aggregation.
4. **Build the upstream producer** (a small script, then later Prefect/Dagster)
   that pulls from a public API and writes Parquet to S3 — this app then serves it.
5. **Deploy to real AWS:** drop `S3_ENDPOINT_URL`, use real S3 + IAM creds.
   Same code, real cloud.

# Internal Architecture & Operations

Detailed reference for engineers operating and extending the service. For the
consumer contract, see [`client-api.md`](./client-api.md).

---

## 1. System overview

**This app is a read-only consumer of processed Parquet** — it never scrapes,
converts, or writes data. A separate upstream system (a scraper + ETL) produces
`processed/scrape/dt=YYYY-MM-DD/data.parquet` and writes it to S3; the API only
does `GET`.

```
┌──────────────────────────┐        ┌─────────────────────┐        ┌──────────────────────┐
│  Upstream producer        │ writes │  S3 (object store)  │ reads  │  FastAPI (this app)  │
│  (scraper + ETL, separate)├───────►│  processed/scrape/  ├───────►│  GET only            │
└──────────────────────────┘        └─────────────────────┘        └──────────────────────┘
```

| Actor | Responsibility | In this repo |
|-------|----------------|--------------|
| Upstream producer | Writes processed Parquet to S3 daily | External (not our code), out of scope |
| API | Serves processed Parquet as JSON | `app/routers/scrape.py` → `daily.py` |

Producing that Parquet is external and out of scope for this repo (see §7).

Local development substitutes **MinIO** for S3 (S3-compatible). The same boto3
code targets real AWS S3 by changing `S3_ENDPOINT_URL` + credentials.

---

## 2. S3 layout (partitioned by day)

```
s3://<bucket>/
└── processed/scrape/dt=YYYY-MM-DD/data.parquet ← columnar; the API reads this
```

The bucket may also hold an upstream `raw/` layer, but that's the producer's
concern — this app neither reads nor writes it.

- **`dt=YYYY-MM-DD` partitioning (Hive-style).** A read for one day resolves to a
  single object path; the API never lists or scans other days. This is what keeps
  reads O(1) in the size of history ("partition pruning").
- **Stable filename** (`data.parquet`) makes a day's object path deterministic —
  the API derives it straight from the date.

### Key construction (code)
`app/daily.py`:
```python
def _parquet_key(day):   return f"processed/scrape/dt={day}/data.parquet"
```
A request `GET /scrape/2026-03-15` → `_parquet_key("2026-03-15")` →
`processed/scrape/dt=2026-03-15/data.parquet`. The date in the URL *is* the path.

---

## 3. Why these formats

| Concern | Choice | Rationale |
|--------|--------|-----------|
| API contract | **JSON** | What clients send/receive (fixed requirement) |
| Storage at rest | **Parquet** | Columnar + compressed + typed; ~6× smaller than JSON, far faster to read/slice |
| Query engine | **DuckDB** | Embedded SQL over Parquet with column + pagination pushdown; no server to run |

JSON lives only at the **edges** (the response). Internally everything is Parquet
+ DuckDB. A ~20k-row day is ~9 MB as JSON but ~0.37–1 MB as Parquet.

---

## 4. Request lifecycle (`GET /scrape/{day}`)

1. **Router** (`app/routers/scrape.py`) translates `page`/`page_size` → SQL
   `LIMIT`/`OFFSET` (`offset = (page-1) * page_size`).
2. **`daily.export_json(day, limit, offset)`**:
   - `storage.exists(day's key)` is a cheap HEAD — missing → router responds `404`.
   - DuckDB reads the Parquet **directly from S3** via the httpfs extension and runs
     `COPY (SELECT ... LIMIT ? OFFSET ?) TO <tmp.json> (FORMAT JSON, ARRAY true)`.
     Range reads pull only the page's rows + columns; **DuckDB serializes to JSON
     in C++** — much faster than per-row Python. `hive_partitioning=false` keeps the
     `dt=…` path from injecting a spurious `dt` column.
3. **Router streams** the temp JSON file back in 64 KB chunks
   (`StreamingResponse`), then deletes it. Memory stays flat regardless of size.

### No local cache (stateless read path)
- The read path **downloads nothing whole and caches nothing on disk** — DuckDB
  range-reads the Parquet in place from S3 each request. This is deliberate: it
  keeps the service stateless, so it runs unchanged on serverless runtimes (e.g.
  Lambda) where a local cache wouldn't survive cold starts.
- Each request opens (per thread) a DuckDB connection configured with an S3 secret
  derived from the same config boto3 uses (`app/daily.py`). On real AWS that's the
  `credential_chain` provider (IAM role); against MinIO it's the static keys.
- Because published days are immutable, HTTP responses are safe to cache at a CDN
  (`Cache-Control: immutable`) — not yet configured. That, plus Parquet's footer
  caching, is where you'd claw back the per-request S3 round-trips if needed.

---

## 5. Data fidelity (a producer concern)

This app doesn't transform data — it serves whatever Parquet the producer wrote.
But any producer of `processed/` must make representation decisions, because
DuckDB's JSON→Parquet type inference is opinionated. Two behaviours to handle
explicitly so the served data stays **faithful to the source**:

1. **No injected `dt` column.** DuckDB auto-detects Hive partitioning from the
   `dt=…` path and would add a `dt` column. Pass `hive_partitioning=false`.
2. **Timestamps preserved as ISO-8601 strings.** DuckDB infers `TIMESTAMP` for
   ISO strings and re-serializes them as `2026-03-15 03:00:00` (no `T`/`Z`). The
   seeder restores the exact original form with
   `strftime(col, '%Y-%m-%dT%H:%M:%SZ')`.

**Principle:** the *producer* owns representation decisions; the API is a dumb
passthrough. Whoever writes `processed/` decides whether it's *faithful* to the
source or *enriched/typed* — don't let the tool decide by accident.

---

## 6. Performance characteristics

Measured locally (MinIO), reading a 12k-row × 20-col day directly from S3:

| Operation | Time |
|-----------|------|
| `GET /scrape/{day}/meta` (footer only) | ~14 ms |
| `GET /scrape/{day}?page_size=5` | ~18 ms |
| `GET /scrape/{day}?page_size=5000` (a full page) | ~40 ms |

(Local MinIO has near-zero network latency; against real S3 each request adds a
HEAD + the Parquet footer/range round-trips, so expect higher but still small
times — and a CDN or footer caching would amortize them.)

Scaling notes:
- **History size is irrelevant per request** — each day is its own file
  (partition pruning). 3 months or 3 years, one day costs the same.
- **The real limit is total volume shipped**, now bounded hard by `page_size ≤
  5000`. A full day (~20k rows) is ~4 pages; a 40-day range loops client-side.
- **`OFFSET` deep-paging** is fine within a day. If a single day grew huge and
  clients paged deep, switch to keyset pagination (cursor on `id`).

---

## 7. Where the data comes from

Producing `processed/` is **out of scope for this repo** — there is no scraper,
ingest job, or cron here. A separate upstream system (scraper + ETL, e.g.
Prefect/Dagster/Airflow) writes the daily `processed/scrape/dt=.../data.parquet`
to the bucket; this service simply serves whatever is present, and returns `404`
for days that don't exist yet.

For local testing, that data is generated **outside this repo** and uploaded to
the MinIO bucket — anything that writes a valid Parquet to the right key works.

---

## 8. Configuration

Environment variables (see `app/config.py`, set in `docker-compose.yml`):

| Var | Purpose | Local value |
|-----|---------|-------------|
| `S3_ENDPOINT_URL` | S3 endpoint; **unset** for real AWS | `http://minio:9000` |
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` | Credentials; **unset** → boto3 default chain / IAM role | `minioadmin` |
| `AWS_REGION` | Region | `us-east-1` |
| `S3_BUCKET` | Bucket name | `readings` |
| `API_KEY` | If set, requires `X-API-Key` header on data routes | _(unset → auth off)_ |
| `CORS_ORIGINS` | Comma-separated allowed origins | `*` |
| `RATE_LIMIT` | Global rate limit (slowapi syntax) | `120/minute` |

**Deploy to real AWS:** leave `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` **unset**
so both boto3 *and* DuckDB use the instance/role credential chain; remove
`S3_ENDPOINT_URL`; point `S3_BUCKET` at a real bucket; set `API_KEY` and a real
`CORS_ORIGINS`. No code changes. See `infra-choices/` for the per-target guides.

### Dev vs production server
- **Dev:** `docker-compose.yml` overrides the command to `uvicorn … --reload`
  (single process, hot reload).
- **Prod:** the image's default `CMD` runs `uvicorn … --workers 2` as the
  non-root `appuser`. Put a reverse proxy (Nginx/Traefik) in front for TLS.
- **Lambda:** `app/lambda_handler.py` wraps the app with Mangum; deploy as a
  container-image Lambda behind API Gateway. The stateless read path makes this
  viable; mind two things — `page_size` is capped at 5000 so responses fit the
  gateway limit, and DuckDB downloads the `httpfs`/`aws` extensions on first use
  (give it egress or bundle them, and set `HOME=/tmp`).
- **Tests:** `pip install -r requirements-dev.txt && python -m pytest tests/`.

---

## 9. Other endpoints (learning scaffold)

The repo also contains an earlier learning scaffold unrelated to the scrape
product. Treat these as examples, not part of the client contract:

- `readings` group (`app/routers/readings.py`) — CRUD + batch over one-JSON-object-
  per-record storage, demonstrating ingestion/serving against S3.
- `stats` group (`app/routers/stats.py`) — aggregation by reading many JSON
  objects (the "do it the slow way" lesson that motivates Parquet/DuckDB).

---

## 10. Hardening status & remaining work

**Done (hardening pass):**
- ✅ **Input validation** — `day` is constrained to a real calendar date
  (`valid_day` in `app/routers/scrape.py`), closing SQL/path injection via the URL.
- ✅ **Auth** — optional API key (`X-API-Key`) on data routes; off until `API_KEY` set.
- ✅ **CORS** + **rate limiting** (slowapi, global default limit).
- ✅ **Non-root container**, multi-stage build, prod server (workers, no `--reload`),
  container `HEALTHCHECK`, `.dockerignore`.
- ✅ **IAM-ready** — static keys optional; both boto3 and DuckDB fall back to the
  credential chain.
- ✅ **boto3 timeouts + bounded retries**.
- ✅ **Stateless read path** — DuckDB range-reads Parquet directly from S3, no local
  cache; `page_size ≤ 5000` bounds response size. Serverless-ready (Mangum handler
  in `app/lambda_handler.py`).
- ✅ **Tests** — `tests/` (pytest + TestClient), hermetic (no S3 needed).

**Remaining / future work:**
- **`/scrape-config` write concurrency** — blacklist/whitelist appends are guarded
  by an in-process `threading.Lock`, which protects within one process only. Across
  multiple workers/instances (e.g. several Lambdas) concurrent appends can race and
  lose an entry. These are rare admin writes, so it's documented rather than fixed;
  the real fix is S3 conditional writes (read ETag → `put` with `If-Match` → retry).
- **Range endpoint** — optional `GET /scrape?start&end&page&page_size` globbing
  multiple day-files in one DuckDB query, to reduce client round-trips.
- **Deeper partitioning** — if clients filter heavily by another field (e.g.
  country), partition by it too (`dt=…/country=…/`) so that filter also becomes
  path resolution instead of a column scan. Balance against the small-files cost.
- **CDN caching headers** — emit `Cache-Control: immutable` for published days.
- **Response schema enforcement** — optionally validate served rows against the
  `ScrapeRecord` contract so a malformed upstream Parquet fails fast instead of
  leaking bad shapes to clients (record-level validation at write time is the
  producer's job, upstream).
- **Observability** — request logging is on (stdlib `logging`); add metrics/tracing
  (Prometheus/OpenTelemetry) and per-dependency timeouts in handlers for prod.

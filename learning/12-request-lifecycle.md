# 12 — Request lifecycle: from client to response

This traces **exactly what happens** when a client calls the API, through the real code in
this repo. We'll follow one concrete request the whole way:

```
GET /scrape/2026-06-26?page=2&page_size=5000
Header: X-API-Key: <key>        (only needed if API_KEY is configured)
```

## The big picture

```
  CLIENT
    │  ① HTTPS request
    ▼
  FRONT DOOR  (varies by deployment: App Runner URL / ALB / API Gateway)
    │  ② terminates TLS, forwards plain HTTP to the app
    ▼
  ASGI SERVER  (uvicorn on a container, or Mangum on Lambda)
    │  ③ parses HTTP into an ASGI request, calls the FastAPI app
    ▼
  FASTAPI APP  (app/main.py)
    │  ④ middleware: CORS  →  rate limit (slowapi)
    │  ⑤ routing: match GET /scrape/{day}  →  get_day()
    │  ⑥ dependencies: require_api_key, valid_day, query validation
    ▼
  ROUTE HANDLER  (app/routers/scrape.py: get_day)
    │  ⑦ calls the data layer
    ▼
  DATA LAYER  (app/daily.py: export_json)
    │  ⑧ storage.exists() HEAD  →  DuckDB queries Parquet IN S3 (range reads)
    ▼
  S3  (processed/scrape/dt=2026-06-26/data.parquet)
    │  ⑨ returns only the bytes for the requested rows/columns
    ▼
  …back up: stream JSON to the client, response flows out through the middleware
```

Two supporting facts before we walk it:

- **Where your code runs:** steps **④–⑨ are your own `app/` code** (`main.py`, `routers/`,
  `daily.py`). On **Lambda** they run *inside the Lambda function*; on **App Runner / ECS / EC2**
  the *same* code runs inside the container. The only thing that swaps is the adapter at ③
  (**Mangum** on Lambda, **uvicorn** on a container). It's one codebase, different hosts — not
  separate "Lambda code."
- **Where credentials come from:** both boto3 (`app/storage.py`) and DuckDB (`app/daily.py`)
  read S3 credentials from the **IAM role** on AWS (or static keys against local MinIO). No
  secrets live in the code.
- **Where the data came from:** a **separate upstream producer** wrote that `data.parquet`
  earlier. This API only ever reads it.

---

## Step by step (the read path)

### ① Client → ② Front door
The client opens an HTTPS connection to the public URL. The **front door** depends on how it's
deployed (see the table at the end): App Runner, an ALB (ECS), or API Gateway (Lambda). It
terminates TLS and forwards a plain HTTP request inward. *This layer is infrastructure — not
your code.*

### ③ ASGI server
- On a container (App Runner / ECS / EC2): **uvicorn** receives the HTTP request and turns it
  into an ASGI call into the FastAPI `app`.
- On Lambda: **Mangum** (`app/lambda_handler.py`) does the same job — it converts the API
  Gateway event into the identical ASGI call. *Same app, different doorway.*

### ④ Middleware (app/main.py)
The request passes through two middlewares before hitting any route:
1. **CORS** (`CORSMiddleware`) — handles cross-origin rules; only `GET` is allowed
   (`allow_methods=["GET"]`).
2. **Rate limiting** (`SlowAPIMiddleware`) — enforces `RATE_LIMIT` (default `120/minute`) **per
   client IP**. Over the limit → **429** immediately, never reaching the route.

### ⑤ Routing
FastAPI matches the path `GET /scrape/{day}` to the `get_day` function in
`app/routers/scrape.py`. `2026-06-26` is captured as the `day` path parameter; `page` and
`page_size` come from the query string.

### ⑥ Dependencies run *before* the handler body
FastAPI resolves these first; if any fails, the handler never runs:

- **`require_api_key`** (`app/security.py`, attached to the router in `main.py`) — if `API_KEY`
  is configured, the `X-API-Key` header must match, else **401**. If `API_KEY` is unset (local),
  this is a no-op.
- **`valid_day`** (`app/routers/scrape.py`) — the path is first constrained by a regex
  (`^\d{4}-\d{2}-\d{2}$`), then parsed with `date.fromisoformat`. A wrong shape or an impossible
  date (e.g. `2026-02-30`) → **422**. *This also blocks SQL/path injection, since `day` gets
  interpolated into the S3 key and DuckDB SQL.*
- **Query validation** — `page` must be ≥ 1, `page_size` must be 1–5000. Violations → **422**.

### ⑦ Route handler (get_day)
Now the handler body runs. It converts the page contract into SQL pagination:

```python
offset = (page - 1) * page_size      # (2 - 1) * 5000 = 5000
out_path = daily.export_json(day, limit=page_size, offset=offset)
if out_path is None:
    raise HTTPException(404, ...)     # day not produced yet
```

### ⑧ Data layer (app/daily.py: export_json)
This is the heart of it:

1. **Existence check** — `storage.exists("processed/scrape/dt=2026-06-26/data.parquet")` is a
   cheap S3 **HEAD**. Missing → returns `None` → handler raises **404**.
2. **Build the query** — `SELECT *` (no column filter) with ` LIMIT 5000 OFFSET 5000`, plus
   `hive_partitioning=false` so the `dt=…` path doesn't inject a phantom `dt` column.
3. **Get a DuckDB connection** — `_conn()` returns a per-thread connection, configured once with
   the `httpfs` extension and an **S3 secret** built from the same settings boto3 uses
   (credential chain on AWS, static keys on MinIO).
4. **Query the Parquet IN S3** — DuckDB runs
   `COPY (SELECT * FROM read_parquet('s3://…/data.parquet') LIMIT 5000 OFFSET 5000) TO <tmp.json> (FORMAT JSON, ARRAY true)`.
   Via `httpfs` it issues **HTTP range GETs** to S3: it reads the Parquet *footer* (metadata),
   then fetches **only** the row groups/columns needed for rows 5000–9999 — never the whole
   file. It serializes those rows to a JSON array **in C++** into a temp file.
5. Returns the temp file path.

### ⑨ Stream the response back
The handler returns a `StreamingResponse` whose generator reads the temp file in **64 KB
chunks** and **deletes it** when finished. Memory stays flat no matter the page size.

The bytes flow back out through the middleware (CORS adds its headers), the ASGI server writes
the HTTP response, and the front door returns it to the client:

```
200 OK
[ {"id":5000,...}, {"id":5001,...}, …, {"id":9999,...} ]   ← up to 5000 rows
```

An **empty array `[]`** means you paged past the end of the day — stop.

---

## The write path (briefly): POST /scrape-config/blacklist

`{"entries":["spam.com","SKU-42"]}` follows ①–⑥ the same way, then differs at the handler:

- **Body validation** — the JSON is parsed into the `AppendEntries` model; missing `entries` →
  **422**. The `name` path segment must be `blacklist` or `whitelist` (regex) → else **422**.
- **Read-modify-write** (`app/scrape_config.py: append_list`): under an in-process lock, it
  `storage.get_json("config/scrape/blacklist.json")` → merges the new entries (deduplicated) →
  `storage.put_json(...)` back to S3. Returns `{"added": N, "total": M, "added_entries": [...]}`.
- **The lock caveat:** that lock only protects one process. Across multiple workers/instances
  (e.g. several Lambdas) concurrent appends can race — documented in
  [`../docs/internal-architecture.md`](../docs/internal-architecture.md) §10.

So: reads go **straight through DuckDB→S3**; writes are a **read-modify-write of a small JSON
object**.

---

## What can go wrong, and where

| Status | Where it's decided | Meaning |
|---|---|---|
| `429` | rate-limit middleware (④) | Too many requests for this IP |
| `401` | `require_api_key` dependency (⑥) | Missing/invalid `X-API-Key` (only when `API_KEY` set) |
| `422` | `valid_day` / query / body validation (⑥) | Bad date, `page_size>5000`, malformed body |
| `404` | data layer (⑧) | That day's Parquet isn't in S3 yet |
| `405` | routing (⑤) | Wrote to a read-only route (`POST /scrape/…`) |
| `503` | `/health` only | App can't reach S3 (bad role/endpoint/bucket) |
| `200` | handler (⑦–⑨) | Success |

---

## The front door changes per deployment (everything else is identical)

| Deployment | ① Front door | ③ ASGI server |
|---|---|---|
| App Runner | App Runner managed URL + TLS | uvicorn (container) |
| ECS Fargate | Application Load Balancer | uvicorn (container) |
| EC2 | your nginx/Caddy (or direct) | uvicorn (container) |
| Lambda | API Gateway | **Mangum** (`app/lambda_handler.py`) |

Steps ④–⑨ — the FastAPI app, dependencies, DuckDB-on-S3 read, streaming — are **the same code
in every case**. That's the payoff of keeping the app stateless and the storage behind one
module: the deployment wrapper changes, the request lifecycle doesn't.

---

## See also
- [`06-structuring-the-app.md`](06-structuring-the-app.md) — why it's split into routers /
  data layer / storage.
- [`09-making-it-fast.md`](09-making-it-fast.md) — the DuckDB-on-S3 read in depth.
- [`../docs/internal-architecture.md`](../docs/internal-architecture.md) — the operations-level
  version of this.

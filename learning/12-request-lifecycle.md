# 12 — Request lifecycle: from client to response

When a request hits the API it passes through **two layers**. Keeping these apart is the whole
point of this page:

1. **The wrapper (infrastructure).** The front door + the host that runs your code. **This part
   changes depending on where you deploy** — App Runner, ECS, EC2, or Lambda.
2. **Your application.** The `app/` package (FastAPI, routing, the DuckDB→S3 read). **This part
   is identical no matter where you deploy.** It just runs *inside* whatever host the wrapper
   provides.

So whenever you look at the FastAPI app or the route handler below and ask *"is this running on
Lambda?"* — the answer is: **it runs inside whatever host you deployed to.** On Lambda it runs
inside the Lambda function; on App Runner / ECS / EC2 the *same* code runs inside a container.
It is **not** separate "Lambda code."

We'll follow one concrete request all the way down and back:

```
GET /scrape/2026-06-26?page=2&page_size=5000
Header: X-API-Key: <key>        (only if API_KEY is configured)
```

## The big picture

```
╔═ THE WRAPPER — infrastructure, CHANGES per deployment ══════════════════════╗
║                                                                             ║
║   CLIENT                                                                     ║
║     │ ① HTTPS request                                                       ║
║     ▼                                                                        ║
║   FRONT DOOR     App Runner URL  ·  ALB (ECS)  ·  API Gateway (Lambda)       ║
║     │ ② terminate TLS, forward plain HTTP inward                            ║
║     ▼                                                                        ║
║   HOST + ADAPTER     a CONTAINER running uvicorn                            ║
║                          — OR —   a LAMBDA FUNCTION running Mangum           ║
║     │ ③ hand the request to your app (as an ASGI call)                      ║
╚═════╪═══════════════════════════════════════════════════════════════════════╝
      │
      ▼
╔═ YOUR APPLICATION — the app/ package, the SAME code in EVERY deployment ════╗
║                                                                             ║
║   ④ middleware: CORS → rate limit            app/main.py                     ║
║   ⑤ routing: GET /scrape/{day} → get_day()   app/routers/scrape.py           ║
║   ⑥ dependencies: require_api_key, valid_day, query validation              ║
║   ⑦ handler get_day() → calls the data layer                                ║
║   ⑧ data layer: read Parquet from S3         app/daily.py  (DuckDB httpfs)   ║
║     │                                                                        ║
║     ▼                                                                        ║
║   S3   processed/scrape/dt=2026-06-26/data.parquet                          ║
║     │ returns only the bytes for the requested rows/columns                 ║
║     ▼                                                                        ║
║   ⑨ stream the JSON array back to the client                                ║
╚═════════════════════════════════════════════════════════════════════════════╝
```

**Read the box boundary as the answer to "where does my code run":** everything in the lower box
runs **inside** the host from the upper box. Swap the host (container ↔ Lambda function) and the
lower box doesn't change — only the **adapter at ③** swaps (uvicorn ↔ Mangum).

Two more facts before we walk it:

- **Where credentials come from:** both boto3 (`app/storage.py`) and DuckDB (`app/daily.py`) read
  S3 credentials from the **IAM role** on AWS (or static keys against local MinIO). No secrets
  live in the code.
- **Where the data came from:** a **separate upstream producer** wrote that `data.parquet`
  earlier. This API only ever reads it.

---

# Part A — the wrapper (infrastructure: ①–③)

This is the part that differs per deployment. It's *not* your code.

### ① Client → ② Front door
The client opens an HTTPS connection to the public URL. The **front door** depends on how it's
deployed: App Runner's URL, an ALB (ECS), or API Gateway (Lambda). It terminates TLS and forwards
a plain HTTP request inward.

### ③ Host + adapter (the doorway into your app)
The host runs your code and an **adapter** turns the incoming HTTP into a call your FastAPI app
understands (an "ASGI call"):
- On a **container** (App Runner / ECS / EC2): **uvicorn** is the adapter.
- On **Lambda**: **Mangum** (`app/lambda_handler.py`) is the adapter — it converts the API Gateway
  event into the *identical* ASGI call.

*Same app underneath, different doorway.* From step ④ on, nothing below knows or cares which host
it's in.

---

# Part B — your application (④–⑨)

This is your `app/` code. **It runs identically whether the host is a container or a Lambda
function.**

### ④ Middleware (app/main.py)
The request passes through two middlewares before any route:
1. **CORS** (`CORSMiddleware`) — cross-origin rules; only `GET` is allowed (`allow_methods=["GET"]`).
2. **Rate limiting** (`SlowAPIMiddleware`) — enforces `RATE_LIMIT` (default `120/minute`) **per
   client IP**. Over the limit → **429**, never reaching the route.

### ⑤ Routing
FastAPI matches `GET /scrape/{day}` to `get_day` in `app/routers/scrape.py`. `2026-06-26` becomes
the `day` path parameter; `page` and `page_size` come from the query string.

### ⑥ Dependencies run *before* the handler body
If any fails, the handler never runs:
- **`require_api_key`** (`app/security.py`) — if `API_KEY` is set, `X-API-Key` must match, else
  **401**. Unset (local) → no-op.
- **`valid_day`** (`app/routers/scrape.py`) — regex (`^\d{4}-\d{2}-\d{2}$`) then
  `date.fromisoformat`. Wrong shape or impossible date (`2026-02-30`) → **422**. *This also blocks
  injection, since `day` is interpolated into the S3 key and DuckDB SQL.*
- **Query validation** — `page` ≥ 1, `page_size` 1–5000. Violations → **422**.

### ⑦ Route handler (get_day)
Now the handler body runs. It turns the page contract into SQL pagination:

```python
offset = (page - 1) * page_size      # (2 - 1) * 5000 = 5000
out_path = daily.export_json(day, limit=page_size, offset=offset)
if out_path is None:
    raise HTTPException(404, ...)     # day not produced yet
```

### ⑧ Data layer (app/daily.py: export_json)
The heart of it:
1. **Existence check** — `storage.exists("processed/scrape/dt=2026-06-26/data.parquet")` is a cheap
   S3 **HEAD**. Missing → `None` → handler raises **404**.
2. **Build the query** — `SELECT *` with ` LIMIT 5000 OFFSET 5000`, plus `hive_partitioning=false`
   so the `dt=…` path doesn't inject a phantom `dt` column.
3. **Get a DuckDB connection** — `_conn()`, configured once with the `httpfs` extension and an **S3
   secret** built from the same settings boto3 uses (credential chain on AWS, static keys on MinIO).
4. **Query the Parquet IN S3** —
   `COPY (SELECT * FROM read_parquet('s3://…/data.parquet') LIMIT 5000 OFFSET 5000) TO <tmp.json> (FORMAT JSON, ARRAY true)`.
   Via `httpfs`, DuckDB issues **HTTP range GETs**: it reads the Parquet *footer* (metadata), then
   fetches **only** the rows/columns for rows 5000–9999 — never the whole file — and serializes them
   to a JSON array **in C++** into a temp file.
5. Returns the temp file path.

### ⑨ Stream the response back
The handler returns a `StreamingResponse` that reads the temp file in **64 KB chunks** and
**deletes it** when done — memory stays flat regardless of page size. The bytes flow back out
through the middleware (CORS adds headers), the adapter writes the HTTP response, and the front
door returns it to the client:

```
200 OK
[ {"id":5000,...}, …, {"id":9999,...} ]   ← up to 5000 rows
```

An **empty array `[]`** means you paged past the end of the day — stop.

---

## The write path (briefly): POST /scrape-config/blacklist

`{"entries":["spam.com","SKU-42"]}` goes through the same wrapper (①–③) and the same ④–⑥, then
differs at the handler:
- **Body validation** — parsed into the `AppendEntries` model; missing `entries` → **422**. The
  `name` segment must be `blacklist`/`whitelist` → else **422**.
- **Read-modify-write** (`app/scrape_config.py: append_list`): under an in-process lock,
  `storage.get_json("config/scrape/blacklist.json")` → merge new entries (deduplicated) →
  `storage.put_json(...)`. Returns `{"added": N, "total": M, "added_entries": [...]}`.
- **Lock caveat:** that lock protects one process only. Across multiple instances (e.g. several
  Lambdas) concurrent appends can race — see [`../docs/internal-architecture.md`](../docs/internal-architecture.md) §10.

So reads go **straight through DuckDB→S3**; writes are a **read-modify-write of a small JSON object**.

---

## What can go wrong, and where

| Status | Decided in | Meaning |
|---|---|---|
| `429` | Part A→B boundary: rate-limit middleware (④) | Too many requests for this IP |
| `401` | dependency (⑥) | Missing/invalid `X-API-Key` (only when `API_KEY` set) |
| `422` | validation (⑥) | Bad date, `page_size>5000`, malformed body |
| `404` | data layer (⑧) | That day's Parquet isn't in S3 yet |
| `405` | routing (⑤) | Wrote to a read-only route (`POST /scrape/…`) |
| `503` | `/health` only | App can't reach S3 (bad role/endpoint/bucket) |
| `200` | handler (⑦–⑨) | Success |

---

## The wrapper per deployment (Part B is identical in every row)

| Deployment | ① Front door | ③ Host + adapter |
|---|---|---|
| App Runner | App Runner URL + TLS | container + **uvicorn** |
| ECS Fargate | Application Load Balancer | container + **uvicorn** |
| EC2 | your nginx/Caddy (or direct) | container + **uvicorn** |
| Lambda | API Gateway | Lambda function + **Mangum** (`app/lambda_handler.py`) |

The whole right-hand side of the system — middleware, dependencies, the DuckDB-on-S3 read,
streaming — is **the same code in every row**. Change the wrapper, the request lifecycle inside
your app doesn't move.

---

## See also
- [`06-structuring-the-app.md`](06-structuring-the-app.md) — routers / data layer / storage split.
- [`09-making-it-fast.md`](09-making-it-fast.md) — the DuckDB-on-S3 read in depth.
- [`../deployment/08-images-and-ecr.md`](../deployment/08-images-and-ecr.md) — where the code is
  stored (ECR) vs where it runs (the host).

# 12 — End to end: from a client request to the response

This follows **one real request** across the **whole deployed system** — every component it
touches, in order. To make it concrete we use the **Lambda deployment** (API Gateway + Lambda +
ECR + S3), because that's what this repo builds. The other deployments differ only at the front —
see [Deployed somewhere else?](#deployed-somewhere-else) at the bottom.

The request we'll trace:

```
GET https://your-api.example.com/scrape/2026-06-26?page=2&page_size=5000
Header: X-API-Key: <key>        (only if API_KEY is configured)
```

## The cast (every component involved)

| # | Component | Role |
|---|---|---|
| Client | browser / script | sends the HTTPS request, gets JSON back |
| **API Gateway** | AWS managed HTTPS endpoint | the public front door; receives the request, invokes Lambda |
| **Lambda function** | AWS serverless runner | runs your app; on cold start it loads the image from ECR |
| **ECR** | image registry | **stores** the container image; Lambda **pulls** it (cold start only) |
| Mangum | `app/lambda_handler.py` | adapter: turns the Lambda event into a call your app understands |
| FastAPI app | `app/main.py` + routers | your code: validation, routing, the handler |
| DuckDB | inside `app/daily.py` | reads the Parquet **directly from S3** |
| **S3** | object storage | holds the data file `processed/scrape/dt=2026-06-26/data.parquet` |
| IAM role | the Lambda execution role | how Lambda's code is allowed to read/write S3 (no passwords in code) |

## The whole journey

```
 [ CLIENT ]
     │ ① GET https://your-api…/scrape/2026-06-26?page=2&page_size=5000  (HTTPS)
     ▼
 [ API GATEWAY ]  ── public HTTPS endpoint, terminates TLS
     │ ② invokes the Lambda function with the request as an "event"
     ▼
 ┌─ [ LAMBDA FUNCTION ] ─────────────────────────────────────────────────────┐
 │                                                                            │
 │   (COLD START only, first time:                                            │
 │      Lambda pulls the container image ◀───────── [ ECR ]  (image storage)  │
 │      then runs init: load app + extensions)                                │
 │                                                                            │
 │   ③ Mangum (app/lambda_handler.py)  →  hands the request to the app        │
 │   ④ FastAPI middleware (app/main.py): CORS, rate limit                     │
 │   ⑤ routing → get_day()             (app/routers/scrape.py)                │
 │   ⑥ checks: API key, valid date, page/page_size bounds                     │
 │   ⑦ handler → daily.export_json()   (app/daily.py)                         │
 │   ⑧ DuckDB (httpfs) reads the file from S3 ──────────┐                     │
 │      using the LAMBDA IAM ROLE for credentials       │                     │
 └──────────────────────────────────────────────────────┼─────────────────────┘
                                                         ▼
                                              [ S3 BUCKET ]
                                              processed/scrape/dt=2026-06-26/data.parquet
                                                         │ ⑨ returns ONLY the bytes
                                                         │    for rows 5000–9999
                                                         ▼
 …back up: DuckDB makes JSON → Lambda returns it → API Gateway → CLIENT (200 OK)
```

---

## Step by step

### ① Client → API Gateway
The client makes an HTTPS request to the public URL. DNS resolves it to **API Gateway**, AWS's
managed HTTPS endpoint. API Gateway terminates TLS (decrypts HTTPS) and packages the request as an
**event**.

### ② API Gateway → Lambda
API Gateway **invokes the Lambda function**, passing that event. This is the boundary between "AWS
infrastructure" and "your code" — from here on, what runs is *your* application.

### Cold start: where ECR comes in
The **first** time a Lambda instance handles a request (a "cold start"), Lambda has no code in
memory yet, so it:
1. **Pulls your container image from ECR** (the registry where `docker push` put it), then
2. runs the **init**: imports your app via `app/lambda_handler.py`, and DuckDB loads its pre-baked
   `httpfs`/`aws` extensions (no network, thanks to `Dockerfile.lambda`).

After that, the instance stays **warm** for a while: subsequent requests **skip ECR and init
entirely** and jump straight to step ③. So **ECR is touched at cold start, never during a normal
request** — that's why it isn't in the per-request loop.

### ③ Mangum → your app
**Mangum** (`app/lambda_handler.py`) converts the Lambda event into the standard call a FastAPI app
expects ("ASGI"). On a container deployment this job is done by **uvicorn** instead — but it hands
the app the *identical* request. From here, **everything is your `app/` code, and it runs the same
no matter where it's deployed.**

### ④ Middleware (`app/main.py`)
The request passes two middlewares first:
1. **CORS** — cross-origin rules; only `GET` is allowed.
2. **Rate limiting** — `RATE_LIMIT` (default `120/minute`) per client IP. Over it → **429**, and
   the route never runs.

### ⑤ Routing
FastAPI matches `GET /scrape/{day}` to `get_day` in `app/routers/scrape.py`. `2026-06-26` is the
`day` path param; `page=2`, `page_size=5000` come from the query string.

### ⑥ Checks (dependencies), before the handler runs
- **API key** (`app/security.py`) — if `API_KEY` is set, `X-API-Key` must match, else **401**.
- **valid_day** (`app/routers/scrape.py`) — regex + real-date check; bad/impossible date → **422**.
  (Also blocks injection — `day` goes into the S3 key and DuckDB SQL.)
- **Query bounds** — `page ≥ 1`, `page_size` 1–5000, else **422**.

### ⑦ Handler (`get_day`)
Turns the page into SQL pagination and calls the data layer:
```python
offset = (page - 1) * page_size          # (2-1)*5000 = 5000
out_path = daily.export_json(day, limit=page_size, offset=offset)
if out_path is None:
    raise HTTPException(404, ...)         # that day's file doesn't exist in S3
```

### ⑧ Reading the file from S3 (`app/daily.py`)
This is where it touches the actual data:
1. **Does the file exist?** `storage.exists("processed/scrape/dt=2026-06-26/data.parquet")` — a
   cheap S3 **HEAD**. Missing → **404**.
2. **DuckDB queries the file *in place* in S3.** It runs
   `COPY (SELECT * FROM read_parquet('s3://<bucket>/processed/scrape/dt=2026-06-26/data.parquet') LIMIT 5000 OFFSET 5000) TO <tmp.json> (FORMAT JSON)`.
   Via the `httpfs` extension, DuckDB makes **HTTP range requests** to S3: it reads the Parquet
   *footer* (the index), then downloads **only the bytes for rows 5000–9999** — not the whole file
   — and serializes them to JSON in C++.
3. **Credentials:** DuckDB (and boto3) authenticate to S3 using the **Lambda execution role** —
   no keys in the code. (Locally, against MinIO, it uses the dev keys instead.)

### ⑨ Response back to the client
The handler streams that JSON to Mangum, which returns it to **API Gateway**, which sends it to the
**client**:
```
200 OK
[ {"id":5000,...}, …, {"id":9999,...} ]      ← up to 5000 rows
```
(On Lambda the response is buffered by API Gateway — which is exactly *why* `page_size` is capped at
5000, so a page always fits under the gateway's size limit.) An empty array `[]` means you've paged
past the end of the day.

---

## Cold starts: what "first time" means, and how long

A **cold start** is the first request handled by a **new** Lambda instance — *not* just the first
request ever. Lambda creates a new (cold) instance when:

- you **just deployed or updated** the function,
- a request arrives and **no warm instance is free**,
- it **scales up** — N concurrent requests with fewer warm instances → N new instances → N cold
  starts at once,
- instances were **reclaimed after idle** (roughly ~5–15 min of no traffic; not officially fixed).

After its first request, an instance stays **warm** and is **reused** until reclaimed. A low-traffic
API goes cold between bursts — that's the scale-to-zero trade-off.

A cold start is two phases stacked:

| Phase | What happens | ~Time (estimate) |
|---|---|---|
| Platform init | Lambda provisions the instance + loads the container image (**pulls from ECR** the first time, cached layers after) | ~0.3–1.5 s |
| App init | imports `fastapi`/`boto3`/**`duckdb`**, loads the baked `httpfs`/`aws` extensions (local, fast), builds the app, runs the startup `head_bucket` | ~0.5–1.5 s |
| **Cold start total** | | **~1–3 s** (the first-ever pull after a deploy is slowest) |

**Warm** requests skip both phases → just the request work (tens of ms + S3 latency).

Reduce it with: **more memory** (2048 MB here → more CPU → faster init), or **provisioned
concurrency** (keeps instances permanently warm — but costs 24/7, which defeats scale-to-zero; if
you need that, App Runner is the better fit).

> These are typical figures, **not measured** on a deployed Lambda for this app.

---

## How long to fetch many big days (e.g. 15 days)?

Remember the API is **one day per request**, paginated at `page_size ≤ 5000`. So 15 days is **not
one call** — the client **loops over 15 dates** and pages through each. If a day is ~20k rows,
that's ~4 pages/day → **~60 requests** for 15 days.

When each day is big, the total time is **dominated by total bytes ÷ the client's download
bandwidth**, not by the number of requests:

```
total ≈ cold start(s)  +  per-request overhead  +  (total bytes ÷ client bandwidth)
                                                    ▲ the dominant term when days are big
```

**Worked example** (assume ~20k rows ≈ ~9 MB JSON per day):
- 15 days ≈ 300k rows ≈ **~135 MB of JSON** to move.
- **The hard floor is just the download:** 135 MB at 50 Mbps ≈ **~22 s**; at 200 Mbps ≈ **~5 s**;
  at 1 Gbps ≈ **~1 s**. You can't go faster than your pipe.
- **Sequential** (one request at a time): + one cold start (~2 s) + ~60 × per-request overhead
  (~0.1–0.3 s each) on top of the transfer → roughly **~30–45 s** on a 50 Mbps link.
- **Parallel** (fetch several days at once): overlaps the cold starts and per-request latency, so
  the total falls toward the **bandwidth floor** (~5–22 s here). Parallel requests **share** your
  download pipe, so they can't beat `total_bytes ÷ bandwidth` — they just stop you waiting on
  round-trips. (Note: many parallel requests may trigger several **cold starts** at once, and can
  hit the `RATE_LIMIT`.)

**Takeaways:**
- **Parallelize** the per-day loop to hide latency + cold starts.
- The hard floor is **total volume ÷ your bandwidth** — for big exports, that's the real cost.
- If "big" means tens/hundreds of MB regularly, shipping JSON **through** Lambda/API Gateway is slow
  and expensive (you pay Lambda GB-seconds + gateway transfer for every page). The better pattern is
  to hand the client a **presigned S3 URL** so it downloads the Parquet **directly from S3** — no API
  in the path, far faster and cheaper. This API is built for **slicing/paging**, not bulk dumps.

---

## What can go wrong, and where

| Status | Where | Meaning |
|---|---|---|
| `429` | rate-limit middleware (④) | too many requests from this IP |
| `401` | API-key check (⑥) | missing/invalid `X-API-Key` (only when `API_KEY` set) |
| `422` | validation (⑥) | bad date, `page_size > 5000`, malformed query |
| `404` | data layer (⑧) | that day's `.parquet` isn't in S3 yet |
| `405` | routing (⑤) | wrote to a read-only route (`POST /scrape/…`) |
| `503` | `/health` only | the app can't reach S3 (bad role/bucket) |
| `200` | handler (⑦–⑨) | success |

---

## The write path, briefly: `POST /scrape-config/blacklist`

Same journey through ①–⑥, then the handler does a **read-modify-write of a small JSON file in S3**
(`app/scrape_config.py`): read `config/scrape/blacklist.json` → add the new entries (deduplicated)
→ write it back. Returns `{"added": N, "total": M, …}`. So **reads go DuckDB→S3; writes edit a tiny
JSON object in S3.**

---

## Deployed somewhere else?

Only the **front door + host** change. **ECR, the app, and the S3 read stay the same.**

| Deployment | ① Front door | ② Host + adapter | Pulls image from ECR? |
|---|---|---|---|
| **Lambda** (traced above) | API Gateway | Lambda function + **Mangum** | yes (cold start) |
| App Runner | App Runner URL | container + **uvicorn** | yes |
| ECS Fargate | Load Balancer (ALB) | container + **uvicorn** | yes |
| EC2 | your nginx/Caddy | container + **uvicorn** | yes (or build on the box) |

In every case: the image lives in **ECR**, a host **pulls and runs it**, and steps ③–⑨ (your app
reading the Parquet from **S3**) are **identical**. Swap the front door and host; the rest doesn't
move.

---

## See also
- [`09-making-it-fast.md`](09-making-it-fast.md) — the DuckDB-on-S3 read, in depth.
- [`../deployment/08-images-and-ecr.md`](../deployment/08-images-and-ecr.md) — image vs ECR vs host
  (where the code is stored vs where it runs).
- [`../deployment/03-data-contract.md`](../deployment/03-data-contract.md) — what the S3 files are
  and how they're laid out.
